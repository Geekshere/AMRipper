import subprocess
import threading
import re
import signal
import urllib.request
import urllib.error
from pathlib import Path
from flask import render_template, request, jsonify
import shlex
import yaml
import os
import json
import base64
from . import app

try:
    from mutagen.mp4 import MP4
    from mutagen.flac import FLAC, Picture
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# Environment passed to downloader/wrapper subprocesses. NO_COLOR/CLICOLOR/
# TERM=dumb tell the Go tool's color library (fatih/color) and any other
# TTY-aware output to skip ANSI escape codes, since they're only meant for
# a real terminal and otherwise show up as garbage in the web UI's log view.
SUBPROCESS_ENV = {**os.environ, "NO_COLOR": "1", "CLICOLOR": "0", "TERM": "dumb"}

# Matches ANSI escape sequences (colors, cursor movement, etc.) as a
# belt-and-suspenders cleanup in case something still emits them despite
# NO_COLOR/TERM=dumb.
ANSI_ESCAPE_RE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


def strip_ansi(text):
    return ANSI_ESCAPE_RE.sub('', text)


# Apple Music tags single-track releases with an album name ending in
# " - Single" (sometimes " - EP" too). This strips that suffix from both
# the download folder name and the embedded album tag after a successful
# download, so libraries don't end up full of "Song Name - Single" folders.
SINGLE_SUFFIX_RE = re.compile(r'\s*-\s*(Single|EP)\s*$', re.IGNORECASE)


def _get_save_folders(amd_dir):
    """Read the configured save folders from config.yaml (best effort)."""
    config_path = os.path.join(amd_dir, "config.yaml")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return []
    keys = ("alac-save-folder", "atmos-save-folder", "aac-save-folder")
    folders = []
    for key in keys:
        folder = config.get(key)
        if folder:
            folders.append(os.path.join(amd_dir, folder))
    return folders


def clean_single_release_names(amd_dir, log_target=None):
    """Rename album folders ending in '- Single'/'- EP' and fix the
    matching album tag inside any .m4a/.mp4 files in them. Best effort —
    logs and continues past problems rather than failing the download."""
    for base_folder in _get_save_folders(amd_dir):
        base_path = Path(base_folder)
        if not base_path.exists():
            continue

        for dirpath, dirnames, _ in os.walk(base_path):
            for dirname in list(dirnames):
                match = SINGLE_SUFFIX_RE.search(dirname)
                if not match:
                    continue

                old_path = Path(dirpath) / dirname
                new_name = SINGLE_SUFFIX_RE.sub('', dirname).strip()
                if not new_name:
                    continue
                new_path = Path(dirpath) / new_name

                if MUTAGEN_AVAILABLE:
                    for audio_file in old_path.glob("*.m4a"):
                        try:
                            tags = MP4(audio_file)
                            if "\xa9alb" in tags:
                                tags["\xa9alb"] = [SINGLE_SUFFIX_RE.sub('', tags["\xa9alb"][0]).strip()]
                                tags.save()
                        except Exception as e:
                            if log_target is not None:
                                log_target.append(f"WARN: Could not update album tag for {audio_file.name}: {e}")
                    for audio_file in old_path.glob("*.flac"):
                        try:
                            tags = FLAC(audio_file)
                            if "album" in tags:
                                tags["album"] = [SINGLE_SUFFIX_RE.sub('', tags["album"][0]).strip()]
                                tags.save()
                        except Exception as e:
                            if log_target is not None:
                                log_target.append(f"WARN: Could not update album tag for {audio_file.name}: {e}")

                try:
                    if new_path.exists():
                        if log_target is not None:
                            log_target.append(f"WARN: Skipped rename, target already exists: {new_path.name}")
                        continue
                    old_path.rename(new_path)
                    if log_target is not None:
                        log_target.append(f"Renamed '{dirname}' -> '{new_name}'")
                except Exception as e:
                    if log_target is not None:
                        log_target.append(f"WARN: Could not rename '{dirname}': {e}")


def convert_and_finalize_downloads(amd_dir, log_target=None):
    """AMRipper's own conversion step, replacing the Go tool's built-in
    one entirely. The Go tool's ffmpeg conversion requests
    -map_metadata 0 but doesn't actually carry tags over (confirmed by
    testing: the resulting FLAC has only ffmpeg's own encoder comment,
    nothing else, even when the source M4A has complete correct tags).
    Worse, the Go tool deletes the M4A itself, inside its own process,
    the moment its conversion finishes — so there's no way to fix this
    by post-processing after the fact if the Go tool is the one doing
    the deleting; there's no hook into its internals to intercept that.

    So the Go tool's conversion is now permanently disabled
    (convert-after-download: false is forced in its config, see
    ensure_config_yaml in main.py) and AMRipper does the whole thing
    itself: run ffmpeg directly, copy tags from the M4A with mutagen
    once we know that succeeded, then delete the M4A ourselves — fully
    within our own control, so 'delete the M4A after' and 'tags
    actually survive' aren't in tension with each other."""
    if not MUTAGEN_AVAILABLE:
        if log_target is not None:
            log_target.append("NOTE: mutagen isn't installed — skipping AMRipper's own FLAC conversion entirely.")
        return

    try:
        config = _read_amd_config(amd_dir)
    except Exception as e:
        if log_target is not None:
            log_target.append(f"WARN: Conversion skipped — could not read config.yaml: {e}")
        return

    if not config.get("amripper-convert-after-download", True):
        if log_target is not None:
            log_target.append("NOTE: amripper-convert-after-download is off — leaving files as ALAC (.m4a).")
        return

    target_format = (config.get("amripper-convert-format") or "flac").lower()
    if target_format != "flac":
        if log_target is not None:
            log_target.append(f"NOTE: amripper-convert-format is '{target_format}' — AMRipper's own "
                               "conversion currently only implements flac. Leaving files as ALAC (.m4a).")
        return

    keep_original = bool(config.get("amripper-keep-original", False))
    ffmpeg_path = config.get("ffmpeg-path") or "ffmpeg"

    folder = Path(config.get("alac-save-folder", ""))
    if not folder.exists():
        if log_target is not None:
            log_target.append(f"WARN: Conversion skipped — download folder doesn't exist: {folder}")
        return

    m4a_files = list(folder.rglob("*.m4a"))
    if log_target is not None:
        log_target.append(f"Checking for ALAC files to convert in {folder} — found {len(m4a_files)}.")

    text_map = {
        "\xa9nam": "title", "\xa9ART": "artist", "aART": "albumartist",
        "\xa9alb": "album", "\xa9wrt": "composer", "\xa9gen": "genre",
        "\xa9day": "date", "cprt": "copyright", "\xa9lyr": "lyrics",
    }

    for m4a_path in m4a_files:
        flac_path = m4a_path.with_suffix(".flac")
        # No "skip if flac already exists" check — ffmpeg already has -y
        # (force overwrite), and skipping based on existence alone risks
        # silently leaving a stale/broken FLAC in place from before this
        # fix (or from a failed prior attempt) instead of replacing it.

        try:
            result = subprocess.run(
                [ffmpeg_path, "-y", "-i", str(m4a_path), "-map", "0:a", "-map_metadata", "-1",
                 "-c:a", "flac", "-loglevel", "error", str(flac_path)],
                capture_output=True, text=True, timeout=300
            )
        except FileNotFoundError:
            if log_target is not None:
                log_target.append(f"WARN: ffmpeg ('{ffmpeg_path}') not found — skipping conversion for {m4a_path.name}.")
            continue
        except subprocess.TimeoutExpired:
            if log_target is not None:
                log_target.append(f"WARN: ffmpeg timed out converting {m4a_path.name}.")
            continue

        if result.returncode != 0:
            if log_target is not None:
                log_target.append(f"WARN: ffmpeg conversion failed for {m4a_path.name}: {result.stderr.strip()[:300]}")
            flac_path.unlink(missing_ok=True)
            continue

        try:
            m4a = MP4(m4a_path)
            flac = FLAC(flac_path)

            for atom, vorbis_key in text_map.items():
                if atom in m4a and m4a[atom]:
                    flac[vorbis_key] = [str(v) for v in m4a[atom]]

            if "trkn" in m4a and m4a["trkn"]:
                track, total = m4a["trkn"][0]
                flac["tracknumber"] = [str(track)]
                if total:
                    flac["tracktotal"] = [str(total)]

            if "disk" in m4a and m4a["disk"]:
                disc, total = m4a["disk"][0]
                flac["discnumber"] = [str(disc)]
                if total:
                    flac["disctotal"] = [str(total)]

            if "covr" in m4a and m4a["covr"]:
                cover_data = m4a["covr"][0]
                pic = Picture()
                pic.data = bytes(cover_data)
                pic.type = 3  # front cover
                pic.mime = "image/png" if cover_data.imageformat == cover_data.FORMAT_PNG else "image/jpeg"
                flac.clear_pictures()
                flac.add_picture(pic)

            flac.save()

            if not keep_original:
                try:
                    m4a_path.unlink()
                except Exception as e:
                    if log_target is not None:
                        log_target.append(f"WARN: Converted and tagged but couldn't remove original {m4a_path.name}: {e}")

            if log_target is not None:
                log_target.append(f"Converted and tagged {flac_path.name}")

        except Exception as e:
            if log_target is not None:
                log_target.append(f"WARN: Converted {m4a_path.name} but tag copy failed: {e}")


def verify_tags_on_latest_download(amd_dir, log_target=None):
    """Check the actual tags on whatever file was most recently written to
    the download folder, and report a plain summary in the download log.
    This exists because 'no tags applied' has been hard to pin down
    without a concrete before/after: this makes each download report,
    in AMRipper's own log, exactly what ended up embedded — instead of
    relying on kid3 or another external tool that may or may not read
    M4A/FLAC tags correctly itself."""
    if not MUTAGEN_AVAILABLE:
        if log_target is not None:
            log_target.append("NOTE: mutagen isn't installed, so tags can't be auto-verified here. "
                               "Check manually with: ffprobe -show_entries format_tags <file>")
        return

    try:
        config = _read_amd_config(amd_dir)
    except Exception:
        return

    folder = Path(config.get("alac-save-folder", ""))
    if not folder.exists():
        return

    audio_files = [p for p in folder.rglob("*") if p.suffix.lower() in (".m4a", ".flac") and p.is_file()]
    if not audio_files:
        return

    latest = max(audio_files, key=lambda p: p.stat().st_mtime)

    try:
        if latest.suffix.lower() == ".m4a":
            tags = MP4(latest)
            title = tags.get("\xa9nam", ["(missing)"])[0]
            artist = tags.get("\xa9ART", ["(missing)"])[0]
            album = tags.get("\xa9alb", ["(missing)"])[0]
        else:
            tags = FLAC(latest)
            title = tags.get("title", ["(missing)"])[0]
            artist = tags.get("artist", ["(missing)"])[0]
            album = tags.get("album", ["(missing)"])[0]

        if title == "(missing)" and artist == "(missing)" and album == "(missing)":
            if log_target is not None:
                log_target.append(f"WARN: No tags found on {latest.name} — title/artist/album all missing.")
        else:
            if log_target is not None:
                log_target.append(f"Tag check on {latest.name}: title=\"{title}\", artist=\"{artist}\", album=\"{album}\"")
    except Exception as e:
        if log_target is not None:
            log_target.append(f"WARN: Could not read tags from {latest.name} to verify: {e}")


# --- Per-download artist-folder toggle ---
# artist-folder-format in config.yaml is a single global setting, applied
# to every download regardless of what kind of link you gave it. That
# means a direct album link would get nested under an artist folder too
# (Artist/Album/track.flac) even though there's only one album — only
# useful when actually downloading a full discography. We toggle it per
# download instead: on for artist URLs, off otherwise, then restore
# whatever the user had configured once the download finishes.
_artist_folder_backup = {"value": None, "active": False}


def _read_amd_config(amd_dir):
    config_path = os.path.join(amd_dir, "config.yaml")
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def _write_amd_config(amd_dir, config):
    config_path = os.path.join(amd_dir, "config.yaml")
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def set_artist_folder_for_download(amd_dir, is_artist_url):
    try:
        config = _read_amd_config(amd_dir)
    except Exception:
        return

    _artist_folder_backup["value"] = config.get("artist-folder-format", "")
    _artist_folder_backup["active"] = True

    if is_artist_url:
        # Always force a real artist-folder value for artist/discography
        # downloads — deterministic, rather than depending on whatever
        # the backed-up value happened to be (which could itself be
        # empty in some edge case, silently skipping the artist folder).
        config["artist-folder-format"] = "{ArtistName}"
    else:
        config["artist-folder-format"] = ""

    try:
        _write_amd_config(amd_dir, config)
    except Exception:
        _artist_folder_backup["active"] = False


def restore_artist_folder_after_download(amd_dir):
    if not _artist_folder_backup["active"]:
        return
    try:
        config = _read_amd_config(amd_dir)
        config["artist-folder-format"] = _artist_folder_backup["value"]
        _write_amd_config(amd_dir, config)
    except Exception:
        pass
    finally:
        _artist_folder_backup["active"] = False



# --- Experimental: check available audio formats before downloading ---
# This queries Apple's public catalog API directly (not the wrapper/
# downloader) to answer "is this only available in AAC, or does it have
# lossless/hi-res/Atmos too" before you spend time downloading it. It's
# read-only and separate from the actual download pipeline, so a failure
# here never blocks a download — it just means we couldn't tell you in
# advance. This hits an undocumented Apple endpoint, so treat results as
# best-effort rather than guaranteed.

_ANON_TOKEN_CACHE = {"token": None}

APPLE_MUSIC_URL_RE = re.compile(
    r'music\.apple\.com/(?P<storefront>[a-z]{2})/(?P<type>album|song)/[^/]+/(?:id)?(?P<id>\d+)',
    re.IGNORECASE
)


def _get_anonymous_apple_token():
    """Scrape the public (anonymous) MusicKit token that music.apple.com's
    own web player uses — same two-step approach the actual Go downloader
    uses (utils/ampapi/token.go): the token isn't inline in the homepage
    HTML, it's inside a bundled JS asset the homepage references. Cached
    for the life of the process; Apple rotates these occasionally, so a
    401/403 downstream should clear the cache and retry once."""
    if _ANON_TOKEN_CACHE["token"]:
        return _ANON_TOKEN_CACHE["token"]

    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

    req = urllib.request.Request("https://music.apple.com", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode('utf-8', errors='ignore')

    asset_match = re.search(r'/assets/index~[^/"\']+\.js', html)
    if not asset_match:
        raise RuntimeError("Could not find the index JS asset on music.apple.com — Apple may have changed their page")

    js_req = urllib.request.Request("https://music.apple.com" + asset_match.group(0), headers=headers)
    with urllib.request.urlopen(js_req, timeout=10) as resp:
        js_body = resp.read().decode('utf-8', errors='ignore')

    token_match = re.search(r'eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+', js_body)
    if not token_match:
        raise RuntimeError("Could not find a token in music.apple.com's JS bundle — Apple may have changed their page")

    token = token_match.group(0)
    _ANON_TOKEN_CACHE["token"] = token
    return token


def _apple_catalog_request(url, token):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://music.apple.com",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


TRAIT_LABELS = {
    "atmos": "Dolby Atmos",
    "hi-res-lossless": "Hi-Res Lossless (ALAC)",
    "lossless": "Lossless (ALAC)",
    "dolby-audio": "Dolby Audio",
}


def check_available_formats(link):
    """Returns {'formats': {trait: bool}, 'raw_traits': [...]}, or raises
    with a human-readable message on any failure. Caller is responsible
    for catching and degrading gracefully."""
    match = APPLE_MUSIC_URL_RE.search(link)
    if not match:
        raise ValueError("Couldn't recognize this as a song or album URL (playlists/artists aren't supported yet)")

    storefront = match.group("storefront").lower()
    media_type = match.group("type")
    media_id = match.group("id")

    # An album URL with ?i=<id> is a link to one specific track within
    # that album, not the album as a whole — look up that track directly
    # so results reflect the actual link, not the whole album's aggregate.
    song_id_match = re.search(r'[?&]i=(\d+)', link)
    if song_id_match:
        media_type = "song"
        media_id = song_id_match.group(1)

    token = _get_anonymous_apple_token()

    try:
        if media_type == "song":
            url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/songs/{media_id}"
            data = _apple_catalog_request(url, token)
            traits = set(data["data"][0]["attributes"].get("audioTraits", []))
        else:
            url = f"https://amp-api.music.apple.com/v1/catalog/{storefront}/albums/{media_id}?include=tracks"
            data = _apple_catalog_request(url, token)
            traits = set()
            for track in data["data"][0].get("relationships", {}).get("tracks", {}).get("data", []):
                traits.update(track.get("attributes", {}).get("audioTraits", []))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # Token likely expired/rotated — clear cache so the next
            # request re-scrapes a fresh one, but don't retry mid-request.
            _ANON_TOKEN_CACHE["token"] = None
        raise RuntimeError(f"Apple's catalog API returned HTTP {e.code}")

    formats = {label: (key in traits) for key, label in TRAIT_LABELS.items()}
    # AAC is effectively always available as the baseline stereo format;
    # explicitly note it rather than leaving it implicit.
    formats["AAC"] = True

    return {"formats": formats, "raw_traits": sorted(traits)}


wrapper_process = None
wrapper_running = False
wrapper_needs_2fa = False
download_process = None
download_running = False

def stream_download_logs(pipe, target_list):
    """Thread target to read logs from download process and store them."""
    global download_running, download_process
    
    try:
        for line in iter(pipe.readline, ''):
            line = strip_ansi(line).strip()
            if line:
                target_list.append(line)

    except Exception as e:
        target_list.append(f"Error reading download logs: {str(e)}")
    finally:
        # By the time we're here, the readline loop already exhausted —
        # meaning the subprocess's stdout closed, which happens at or
        # before process exit. wait() (not poll()) is used deliberately:
        # it blocks until the process is actually reaped and always
        # returns a real exit code, rather than racing a poll() call
        # that could return None if the process hasn't been reaped yet
        # even though its stdout already closed. Short timeout as a
        # safety net in case something genuinely unexpected is going on.
        exit_code = None
        if download_process:
            try:
                exit_code = download_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                exit_code = download_process.poll()

        if download_process and exit_code is not None:
            script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            amd_dir = os.path.join(script_dir, "apple-music-downloader")

            # Always restore the user's configured artist-folder-format,
            # whether the download succeeded or failed.
            try:
                restore_artist_folder_after_download(amd_dir)
            except Exception as e:
                target_list.append(f"WARN: Could not restore artist-folder-format setting: {e}")

            if exit_code == 0:
                target_list.append("Download completed successfully.")
                try:
                    convert_and_finalize_downloads(amd_dir, log_target=target_list)
                except Exception as e:
                    target_list.append(f"WARN: Tag copy to converted file failed: {e}")
                try:
                    clean_single_release_names(amd_dir, log_target=target_list)
                except Exception as e:
                    target_list.append(f"WARN: Single-release cleanup failed: {e}")
                try:
                    verify_tags_on_latest_download(amd_dir, log_target=target_list)
                except Exception as e:
                    target_list.append(f"WARN: Tag verification failed: {e}")
            else:
                target_list.append(f"Download failed with exit code: {exit_code}")
            download_running = False
        pipe.close()

def stream_wrapper_logs(pipe, target_list, email=None, password=None, auto_login=False):
    """Thread target to read logs from wrapper process and store them."""
    global wrapper_running, wrapper_process, wrapper_needs_2fa
    login_successful = False
    
    try:
        for line in iter(pipe.readline, ''):
            line = strip_ansi(line).strip()
            if line:
                target_list.append(line)

                # Check for 2FA requirement
                if "credentialHandler:" in line and "2FA: true" in line:
                    wrapper_needs_2fa = True
                    target_list.append("2FA required - please enter your code")
                    
                # Check for successful login message
                if "[.] response type 6" in line or "listening" in line:
                    wrapper_running = True
                    wrapper_needs_2fa = False
                    login_successful = True
                    if auto_login:
                        target_list.append("Auto-login successful. Ready for downloads.")
                    else:
                        target_list.append("Wrapper login successful. Ready for downloads.")
                        # Save credentials on successful manual login
                        if email and password:
                            if save_credentials(email, password):
                                target_list.append("Credentials saved for auto-login")
                            else:
                                target_list.append("Failed to save credentials")
                    
    except Exception as e:
        target_list.append(f"Error reading wrapper logs: {str(e)}")
    finally:
        # Check if process ended
        if wrapper_process and wrapper_process.poll() is not None:
            exit_code = wrapper_process.poll()
            if not login_successful:
                # Process ended before successful login
                target_list.append(f"Login failed - wrapper process exited with code: {exit_code}")
                wrapper_running = False
                wrapper_needs_2fa = False
                # Delete credentials on failed auto-login
                if auto_login:
                    target_list.append("Auto-login failed, deleting saved credentials")
                    delete_credentials()
            elif exit_code != 0:
                target_list.append(f"Wrapper process ended unexpectedly with exit code: {exit_code}")
                wrapper_running = False
                wrapper_needs_2fa = False
            else:
                target_list.append("Wrapper process ended normally")
                wrapper_running = False
                wrapper_needs_2fa = False
        pipe.close()

wrapper_logs = []
downloader_logs = []

def get_credentials_path():
    """Get the path to the credentials file"""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(script_dir, ".credentials")

def save_credentials(email, password):
    """Save credentials to file (base64 encoded for basic obfuscation)"""
    try:
        credentials = {
            "email": base64.b64encode(email.encode()).decode(),
            "password": base64.b64encode(password.encode()).decode()
        }
        with open(get_credentials_path(), 'w') as f:
            json.dump(credentials, f)
        return True
    except Exception as e:
        print(f"Error saving credentials: {e}")
        return False

def load_credentials():
    """Load and decode saved credentials"""
    try:
        credentials_path = get_credentials_path()
        if os.path.exists(credentials_path):
            with open(credentials_path, 'r') as f:
                credentials = json.load(f)
            email = base64.b64decode(credentials["email"]).decode()
            password = base64.b64decode(credentials["password"]).decode()
            return email, password
    except Exception as e:
        print(f"Error loading credentials: {e}")
    return None, None

def delete_credentials():
    """Delete saved credentials"""
    try:
        credentials_path = get_credentials_path()
        if os.path.exists(credentials_path):
            os.remove(credentials_path)
        return True
    except Exception as e:
        print(f"Error deleting credentials: {e}")
        return False

def attempt_auto_login():
    """Try to automatically login with saved credentials"""
    email, password = load_credentials()
    if email and password:
        wrapper_logs.append("Found saved credentials, attempting auto-login...")
        return start_wrapper_login(email, password, auto_login=True)
    return False

def start_wrapper_login(email, password, auto_login=False):
    """Start wrapper login process"""
    global wrapper_process, wrapper_running, wrapper_logs
    
    if wrapper_process and wrapper_process.poll() is None:
        if not auto_login:
            wrapper_logs.append("Wrapper already running")
        return False

    if not auto_login:
        wrapper_logs = []  # reset logs only for manual login
    
    prefix = "Auto-login: " if auto_login else ""
    wrapper_logs.append(f"{prefix}Starting wrapper login for {email}...")
    
    # Use absolute path and proper command format
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    wrapper_dir = os.path.join(script_dir, "wrapper")
    wrapper_path = os.path.join(wrapper_dir, "wrapper")
    
    cmd = [wrapper_path, "-L", f"{email}:{password}"]
    wrapper_logs.append(f"{prefix}Executing: {' '.join(cmd)}")
    wrapper_logs.append(f"{prefix}Working directory: {wrapper_dir}")
    
    try:
        wrapper_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True,
            cwd=wrapper_dir,  # Run from wrapper directory
            env=SUBPROCESS_ENV
        )
        
        # Don't set wrapper_running=True yet, wait for the success message
        threading.Thread(target=stream_wrapper_logs, args=(wrapper_process.stdout, wrapper_logs, email, password, auto_login), daemon=True).start()
        
        wrapper_logs.append(f"{prefix}Wrapper process started, waiting for login confirmation...")
        return True
        
    except Exception as e:
        wrapper_logs.append(f"{prefix}Error starting wrapper: {str(e)}")
        if auto_login:
            wrapper_logs.append("Auto-login failed, deleting saved credentials")
            delete_credentials()
        return False


@app.route("/")
def index():
    # Check for saved credentials and attempt auto-login on first load
    email, password = load_credentials()
    if email and password and not wrapper_running and (not wrapper_process or wrapper_process.poll() is not None):
        # Attempt auto-login in a separate thread to not block page load
        threading.Thread(target=attempt_auto_login, daemon=True).start()
    
    return render_template("index.html", wrapper_running=wrapper_running, has_saved_credentials=email is not None, saved_email=email if email else "")


@app.route("/login_wrapper", methods=["POST"])
def login_wrapper():
    email = request.form.get("email")
    password = request.form.get("password")

    if wrapper_process and wrapper_process.poll() is None:
        return jsonify({"status": "error", "msg": "Wrapper already running"})

    if start_wrapper_login(email, password, auto_login=False):
        return jsonify({"status": "ok", "msg": "Wrapper process started, waiting for login..."})
    else:
        return jsonify({"status": "error", "msg": "Failed to start wrapper"})

@app.route("/submit_2fa", methods=["POST"])
def submit_2fa():
    global wrapper_process, wrapper_needs_2fa, wrapper_logs
    
    two_fa_code = request.form.get("twofa_code")
    
    if not wrapper_needs_2fa:
        return jsonify({"status": "error", "msg": "2FA not required"})
    
    if not wrapper_process or wrapper_process.poll() is not None:
        return jsonify({"status": "error", "msg": "Wrapper not running"})
    
    if not two_fa_code:
        return jsonify({"status": "error", "msg": "2FA code required"})
    
    try:
        # Send 2FA code to wrapper process
        wrapper_process.stdin.write(f"{two_fa_code}\n")
        wrapper_process.stdin.flush()
        wrapper_logs.append(f"Submitted 2FA code: {two_fa_code}")
        wrapper_needs_2fa = False
        return jsonify({"status": "ok", "msg": "2FA code submitted"})
    except Exception as e:
        wrapper_logs.append(f"Error submitting 2FA code: {str(e)}")
        return jsonify({"status": "error", "msg": f"Failed to submit 2FA code: {str(e)}"})


@app.route("/check_formats", methods=["POST"])
def check_formats_route():
    """Experimental: look up what audio formats a song/album is actually
    available in before downloading. Read-only, hits Apple's public
    catalog API directly — never blocks or affects an actual download,
    it's purely informational."""
    link = request.form.get("link", "")
    if not link:
        return jsonify({"status": "error", "msg": "No URL provided"})
    try:
        result = check_available_formats(link)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


@app.route("/download", methods=["POST"])
def download():
    global download_process, download_running, downloader_logs
    
    link = request.form.get("link")
    format_choice = request.form.get("format")
    special_audio = request.form.get("special_audio") == "true"
    
    if not wrapper_running:
        return jsonify({"status": "error", "msg": "Wrapper not running"})
    
    if download_running:
        return jsonify({"status": "error", "msg": "Download already in progress"})
    
    if not link:
        return jsonify({"status": "error", "msg": "No URL provided"})
    
    # Determine the command to run
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    amd_dir = os.path.join(script_dir, "apple-music-downloader")
    
    # Artist URLs make the downloader list every album and prompt on stdin
    # for a selection ("comma-separated / range / 'all'"). Since this
    # process is launched from the web server with no interactive stdin
    # attached, that prompt just hangs forever. The downloader has a
    # built-in flag to skip it and grab the whole discography instead.
    is_artist_url = "/artist/" in link
    extra_flags = ["--all-album"] if is_artist_url else []

    if special_audio:
        if format_choice == "ATMOS":
            cmd = ["go", "run", "main.go", "--atmos", *extra_flags, link]
            downloader_logs.append(f"Starting ATMOS download: {link}")
        elif format_choice == "AAC":
            cmd = ["go", "run", "main.go", "--aac", *extra_flags, link]
            downloader_logs.append(f"Starting AAC download: {link}")
        else:
            return jsonify({"status": "error", "msg": "Invalid format selected"})
    else:
        cmd = ["go", "run", "main.go", *extra_flags, link]
        downloader_logs.append(f"Starting standard download: {link}")

    if is_artist_url:
        downloader_logs.append("Artist URL detected — downloading full discography (--all-album)")

    try:
        set_artist_folder_for_download(amd_dir, is_artist_url)
    except Exception as e:
        downloader_logs.append(f"WARN: Could not adjust artist-folder-format setting: {e}")

    downloader_logs.append(f"Working directory: {amd_dir}")
    downloader_logs.append(f"Executing: {' '.join(cmd)}")
    
    try:
        download_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            bufsize=1,
            universal_newlines=True,
            cwd=amd_dir,  # Run from apple-music-downloader directory
            env=SUBPROCESS_ENV,
            start_new_session=True  # own process group, so cancel can kill
                                     # the actual compiled binary `go run`
                                     # spawns, not just the go-run wrapper
        )
        
        download_running = True
        threading.Thread(target=stream_download_logs, args=(download_process.stdout, downloader_logs), daemon=True).start()
        
        return jsonify({"status": "ok", "msg": "Download started successfully"})
        
    except Exception as e:
        downloader_logs.append(f"Error starting download: {str(e)}")
        return jsonify({"status": "error", "msg": f"Failed to start download: {str(e)}"})


@app.route("/get_logs")
def get_logs():
    global wrapper_running, wrapper_process, download_running, download_process, wrapper_needs_2fa
    
    # Check if wrapper process is still running
    if wrapper_process and wrapper_process.poll() is not None:
        if wrapper_running:  # Process ended but we thought it was still running
            wrapper_running = False
    
    # Check if download process is still running
    if download_process and download_process.poll() is not None:
        if download_running:  # Process ended but we thought it was still running
            download_running = False
    
    return jsonify({
        "wrapper": wrapper_logs[-200:],  # last 200 lines
        "downloader": downloader_logs[-200:],
        "wrapper_running": wrapper_running,
        "download_running": download_running,
        "wrapper_needs_2fa": wrapper_needs_2fa
    })

@app.route("/stop_wrapper", methods=["POST"])
def stop_wrapper():
    global wrapper_process, wrapper_running, wrapper_logs, wrapper_needs_2fa
    
    if wrapper_process and wrapper_process.poll() is None:
        wrapper_process.terminate()
        wrapper_logs.append("Wrapper process terminated by user")
        wrapper_running = False
        wrapper_needs_2fa = False
        return jsonify({"status": "ok", "msg": "Wrapper stopped"})
    else:
        return jsonify({"status": "error", "msg": "Wrapper not running"})

@app.route("/stop_download", methods=["POST"])
def stop_download():
    global download_process, downloader_logs

    if download_process and download_process.poll() is None:
        try:
            # Kill the whole process group — `go run` spawns a separate
            # compiled binary as a child, and terminate() on just the
            # go-run wrapper can leave that child running as an orphan.
            os.killpg(os.getpgid(download_process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            download_process.terminate()
        downloader_logs.append("Download cancelled by user")
        # download_running is cleared by stream_download_logs' finally
        # block once the process actually exits, which also handles
        # restoring artist-folder-format — no need to duplicate that here.
        return jsonify({"status": "ok", "msg": "Download cancelled"})
    else:
        return jsonify({"status": "error", "msg": "No download in progress"})

@app.route("/settings")
def settings():
    return render_template("settings.html")

@app.route("/get_config")
def get_config():
    try:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(script_dir, "apple-music-downloader", "config.yaml")

        if not os.path.exists(config_path):
            return jsonify({
                "status": "error",
                "msg": "config.yaml doesn't exist yet. Restart AMRipper (python3 main.py) to have it "
                       "generated automatically, then reload this page."
            })

        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)
            return jsonify({"status": "ok", "config": config})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route("/save_config", methods=["POST"])
def save_config():
    try:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(script_dir, "apple-music-downloader", "config.yaml")
        
        config_data = request.json
        
        # Define fields that should be integers
        integer_fields = {
            'alac-max', 'atmos-max', 'limit-max', 'max-memory-limit', 'mv-max'
        }
        
        # Define fields that should be booleans
        boolean_fields = {
            'embed-lrc', 'save-lrc-file', 'save-artist-cover', 'save-animated-artwork',
            'emby-animated-artwork', 'embed-cover', 'get-m3u8-from-device',
            'use-songinfo-for-playlist', 'dl-albumcover-for-playlist',
            'amripper-convert-after-download', 'amripper-keep-original'
        }
        
        # Define fields that are folder paths and need Windows to WSL translation
        path_fields = {
            'alac-save-folder', 'atmos-save-folder', 'aac-save-folder', 'mv-save-folder'
        }
        
        def translate_path_to_wsl(path):
            """Translate Windows paths to WSL paths when saving config"""
            if not path:
                return path
            # Check if it's a Windows-style path (e.g., C:/, D:/)
            if len(path) >= 3 and path[1:3] == ':\\':
                # Convert C:\ to /mnt/c/
                drive = path[0].lower()
                rest = path[3:].replace('\\', '/')
                return f"/mnt/{drive}/{rest}"
            elif len(path) >= 3 and path[1:3] == ':/':
                # Convert C:/ to /mnt/c/
                drive = path[0].lower()
                rest = path[3:]
                return f"/mnt/{drive}/{rest}"
            return path
        
        # Convert data types properly
        for key, value in config_data.items():
            if key in integer_fields:
                try:
                    config_data[key] = int(value) if value else 0
                except (ValueError, TypeError):
                    config_data[key] = 0
            elif key in boolean_fields:
                # Handle boolean conversion
                if isinstance(value, str):
                    config_data[key] = value.lower() in ('true', '1', 'yes', 'on')
                else:
                    config_data[key] = bool(value)
            elif key in path_fields:
                # Translate Windows paths to WSL format
                config_data[key] = translate_path_to_wsl(str(value))
            # Strings remain as strings (default)
        
        # Merge into the existing config rather than overwriting it — the
        # settings page intentionally only exposes a subset of config.yaml's
        # fields (some are advanced/rarely touched, and mv-save-folder was
        # never in the UI at all). A full overwrite would silently wipe
        # anything not present in the submitted form data. Read first: the
        # write-mode open below truncates the file immediately.
        try:
            with open(config_path, 'r', encoding='utf-8') as existing_file:
                full_config = yaml.safe_load(existing_file) or {}
        except Exception:
            full_config = {}
        full_config.update(config_data)
        # The Go tool's own conversion is permanently disabled — its
        # ffmpeg metadata mapping doesn't work (see convert_and_finalize_
        # downloads in routes.py). AMRipper's own amripper-convert-after-
        # download controls conversion instead. Force this regardless of
        # what was submitted, so it can't get flipped back on by mistake.
        full_config['convert-after-download'] = False

        with open(config_path, 'w', encoding='utf-8') as file:
            yaml.dump(full_config, file, default_flow_style=False, allow_unicode=True)
            
        return jsonify({"status": "ok", "msg": "Configuration saved successfully"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@app.route("/check_saved_credentials")
def check_saved_credentials():
    """Check if saved credentials exist"""
    email, password = load_credentials()
    return jsonify({"has_credentials": email is not None, "email": email if email else ""})

@app.route("/delete_saved_credentials", methods=["POST"])
def delete_saved_credentials():
    """Delete saved credentials"""
    if delete_credentials():
        return jsonify({"status": "ok", "msg": "Saved credentials deleted"})
    else:
        return jsonify({"status": "error", "msg": "Failed to delete credentials"})

@app.route("/auto_login", methods=["POST"])
def auto_login():
    """Attempt auto-login with saved credentials"""
    if attempt_auto_login():
        return jsonify({"status": "ok", "msg": "Auto-login started"})
    else:
        return jsonify({"status": "error", "msg": "No saved credentials or login failed"})

@app.route("/get_download_folders")
def get_download_folders():
    """Get the unified download folder path from config"""
    try:
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(script_dir, "apple-music-downloader", "config.yaml")
        
        with open(config_path, 'r', encoding='utf-8') as file:
            config = yaml.safe_load(file)

        # All formats share one folder now — alac-save-folder is the
        # representative value, but they're kept in sync by ensure_config_yaml().
        folder = config.get("alac-save-folder", "downloads")

        return jsonify({"status": "ok", "folder": folder})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})
