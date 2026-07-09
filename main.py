import os
import subprocess
import shutil
import urllib.request
import json
import zipfile
from pathlib import Path
import sys

PROJECT_DIR = Path(__file__).resolve().parent
BENTO4_DIR = PROJECT_DIR / "bento4"
WRAPPER_DIR = PROJECT_DIR / "wrapper"
AMD_DIR = PROJECT_DIR / "apple-music-downloader"

# Package names for the same set of dependencies differ across distros.
# "go" is intentionally left as a separate go.dev install fallback on
# distros whose repo Go version can be too old for this project's go.mod.
PACKAGE_MANAGERS = {
    "apt-get": {
        "check_cmd": ["dpkg", "-s"],
        "install_cmd": ["apt-get", "install", "-y"],
        "update_cmd": ["apt-get", "update"],
        "packages": ["git", "ffmpeg", "gpac", "golang-go", "wget", "python3-flask", "python3-yaml"],
    },
    "dnf": {
        "check_cmd": ["rpm", "-q"],
        "install_cmd": ["dnf", "install", "-y"],
        "update_cmd": None,
        "packages": ["git", "ffmpeg", "gpac", "golang", "wget", "python3-flask", "python3-pyyaml"],
    },
    "zypper": {
        "check_cmd": ["rpm", "-q"],
        "install_cmd": ["zypper", "--non-interactive", "install"],
        "update_cmd": None,
        "packages": ["git", "ffmpeg", "gpac", "go", "wget", "python3-Flask", "python3-PyYAML"],
    },
    "pacman": {
        "check_cmd": ["pacman", "-Q"],
        "install_cmd": ["pacman", "-S", "--noconfirm"],
        "update_cmd": None,
        "packages": ["git", "ffmpeg", "gpac", "go", "wget", "python-flask", "python-yaml"],
    },
}


def detect_package_manager():
    """Return the name of the first available package manager, or None."""
    for name in PACKAGE_MANAGERS:
        if shutil.which(name):
            return name
    return None


def install_system_packages():
    """Install required system packages using whatever package manager
    is available on this distro. Only this step needs root; everything
    else in firstsetup() runs as the invoking user."""
    pm_name = detect_package_manager()
    if pm_name is None:
        print("WARN: No supported package manager found (looked for apt-get, dnf, zypper, pacman). "
              "Skipping package install — make sure git, ffmpeg, gpac (MP4Box), wget, go, "
              "python3-flask, and python3-yaml/pyyaml are installed manually.")
        return

    pm = PACKAGE_MANAGERS[pm_name]
    sudo_prefix = [] if os.geteuid() == 0 else ["sudo"]
    print(f"Detected package manager: {pm_name}")

    if pm["update_cmd"]:
        try:
            subprocess.run(sudo_prefix + pm["update_cmd"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"WARN: Package index update failed ({e}). Continuing anyway.")

    try:
        subprocess.run(sudo_prefix + pm["install_cmd"] + pm["packages"], check=True)
        print("Packages installed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"WARN: Package install failed ({e}). Some packages in {pm['packages']} "
              f"may not exist under those exact names on your distro/repo config — "
              f"install git/ffmpeg/gpac/go manually if setup fails below.")


def install_python_deps():
    """Install Python packages not reliably available via system package
    managers (e.g. mutagen, used for single-release tag cleanup). Best
    effort — the app still works without it, just skips retagging."""
    pip_cmd = [sys.executable, "-m", "pip", "install", "--user", "mutagen"]
    try:
        subprocess.run(pip_cmd, check=True)
    except subprocess.CalledProcessError:
        # Some distros (e.g. externally-managed Python) refuse --user
        # installs outside a venv; retry allowing the override.
        try:
            subprocess.run(pip_cmd + ["--break-system-packages"], check=True)
        except subprocess.CalledProcessError as e:
            print(f"WARN: Could not install mutagen ({e}). "
                  "Single-release folder renaming will still work, but the "
                  "embedded album tag won't be updated to match.")


def get_github_release_asset_url(repo, tag, name_contains):
    """Query the GitHub API for a release's assets and return the
    browser_download_url of the first asset whose filename contains
    name_contains. Used instead of hardcoding a versioned zip filename,
    since WorldObservationLog/wrapper publishes to a rolling release tag
    where the actual asset filename (embeds a commit hash) changes on
    every CI build."""
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": "AMRipper-setup", "Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
    for asset in data.get("assets", []):
        if name_contains in asset["name"]:
            return asset["browser_download_url"]
    raise RuntimeError(f"No asset matching '{name_contains}' found in {repo}@{tag} release")


def download_file(url, dest_path):
    """Download a file with a browser-like User-Agent. Some hosts (e.g.
    bok.net, which serves Bento4) return 403 Forbidden for the default
    urllib User-Agent string, so a plain urlretrieve() fails there."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
    )
    with urllib.request.urlopen(req) as response, open(dest_path, "wb") as out_file:
        shutil.copyfileobj(response, out_file)


def firstsetup():
    # --- Only escalate for the actual package install step ---
    # Everything else (downloads, extraction, git clone) runs as the
    # invoking user so the resulting files aren't root-owned. Root-owned
    # files under the project dir is what previously blocked downloads
    # with "permission denied" after the first run.
    try:
        # Step 1: Install required packages (needs root)
        install_system_packages()
        install_python_deps()

        # Step 2: Download and set up Bento4
        BENTO4_URL = "https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.x86_64-unknown-linux.zip"
        zip_path = PROJECT_DIR / "bento4.zip"

        if not BENTO4_DIR.exists():
            print(f"Downloading Bento4 from {BENTO4_URL}...")
            download_file(BENTO4_URL, zip_path)
            print("Extracting Bento4...")

            BENTO4_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(BENTO4_DIR)
            os.remove(zip_path)

            print("Bento4 installed inside project folder.")

            # Make the extracted tools executable (ZIP extraction doesn't
            # preserve the execute bit) and add them to PATH for this
            # session. We intentionally do NOT symlink into /usr/local/bin
            # here — that requires root, and start() already prepends this
            # bin dir to PATH on every run, so a system-wide symlink is
            # unnecessary and was the second reason this script needed root.
            bin_candidates = list(BENTO4_DIR.glob("Bento4*"))
            if bin_candidates:
                bin_dir = bin_candidates[0] / "bin"
                if bin_dir.exists():
                    for exe_file in bin_dir.glob("*"):
                        if exe_file.is_file():
                            try:
                                exe_file.chmod(exe_file.stat().st_mode | 0o755)
                            except Exception as e:
                                print(f"  WARN: Failed to set execute permission on {exe_file.name}: {e}")
                    os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"
                    print(f"Bento4 tools available at: {bin_dir}")
                else:
                    print(f"WARN: Bin directory does not exist: {bin_dir}")
            else:
                print("WARN: Could not find Bento4 extracted folder")

        else:
            print("INFO: Bento4 already exists, skipping download")

            bin_candidates = list(BENTO4_DIR.glob("Bento4*"))
            if bin_candidates:
                bin_dir = bin_candidates[0] / "bin"
                os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

        # Step 3: Download and extract wrapper
        WRAPPER_REPO = "WorldObservationLog/wrapper"
        WRAPPER_TAG = "wrapper.x86_64.latest"
        try:
            WRAPPER_URL = get_github_release_asset_url(WRAPPER_REPO, WRAPPER_TAG, "x86_64")
        except Exception as e:
            print(f"WARN: Could not resolve the latest wrapper release via GitHub API ({e}). "
                  "Falling back to the stable 'latest' asset URL directly.")
            WRAPPER_URL = f"https://github.com/{WRAPPER_REPO}/releases/download/{WRAPPER_TAG}/Wrapper.x86_64.latest.zip"
        wrapper_zip = PROJECT_DIR / "wrapper.x86_64.zip"

        if not WRAPPER_DIR.exists():
            print(f"Downloading wrapper from {WRAPPER_URL}...")
            download_file(WRAPPER_URL, wrapper_zip)
            print("Extracting wrapper...")

            WRAPPER_DIR.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(wrapper_zip, "r") as zip_ref:
                zip_ref.extractall(WRAPPER_DIR)
            os.remove(wrapper_zip)

            # Ensure the wrapper binary is executable
            wrapper_bin = WRAPPER_DIR / "wrapper"
            try:
                if wrapper_bin.exists():
                    current_mode = wrapper_bin.stat().st_mode
                    wrapper_bin.chmod(current_mode | 0o755)
                    print("Set execute permission on wrapper binary")
                else:
                    print("WARN: Wrapper binary not found after extraction")
            except Exception as e:
                print(f"WARN: Failed to chmod wrapper binary: {e}")

            print("Wrapper extracted inside project folder")
        else:
            print("INFO: Wrapper already exists, skipping download")

        # Step 4: Clone Apple Music Downloader repo
        if not AMD_DIR.exists():
            print("Cloning Apple Music Downloader...")
            subprocess.run(
                ["git", "clone", "https://github.com/zhaarey/apple-music-downloader", str(AMD_DIR)],
                check=True
            )
            print("Apple Music Downloader cloned inside project folder")
        else:
            print("INFO: Apple Music Downloader already exists, skipping clone")

        print("First setup complete!")

    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed during setup: {e}")
        sys.exit(1)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        print(f"ERROR: Failed to download a required file during setup: {e}")
        print("This is usually a network issue or the host temporarily blocking the request. Try running again.")
        sys.exit(1)

def start():
    print("Starting Apple Music Downloader Web UI...")

    # Ensure Bento4 and Wrapper are in PATH locally
    bin_candidates = list(BENTO4_DIR.glob("Bento4*"))  # find extracted folder
    if bin_candidates:
        bin_dir = bin_candidates[0] / "bin"
        os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

    os.environ["PATH"] = f"{WRAPPER_DIR}:{os.environ['PATH']}"

    # Import and run the Flask app
    from app import app   # FIXED: no double "app.app"
    app.run(host="0.0.0.0", port=5000, debug=True)

# === First run check ===
marker_file = PROJECT_DIR / "firstrun"

if not marker_file.exists():
    firstsetup()
    with open(marker_file, "w") as f:
        f.write("This file marks that first setup has been completed.\n")

start()
