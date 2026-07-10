# AMRipper 🎵

A simple web interface for downloading your favorite tracks from Apple Music. No command line needed once it's set up.

---

## About

AMRipper started as a fork of [lalit22km/alac-rip](https://github.com/lalit22km/alac-rip) and has since grown into its own standalone project: fixed up, hardened, and simplified. It's a browser-based front end for the excellent tools built by others in the Apple Music downloading community. All credit for the actual downloading capabilities goes to the original creators listed in [Acknowledgments](#acknowledgments); AMRipper is a convenience layer and bugfix pass on top of their work.

## Features

- 🌐 Clean, modern web UI, no command line needed day to day
- 🔐 Save credentials for automatic login on startup
- 🎧 ALAC (lossless), converted to FLAC automatically, fully tagged (title, artist, album, track/disc numbers, composer, genre, lyrics, cover art)
- 📁 Artist URLs grab the full discography automatically and organize it into an artist folder
- 🧹 Strips the trailing "- Single" Apple adds to single-track releases
- 🐧 Works across distros (apt, dnf, zypper, pacman), no full root access needed
- ⚙️ A settings page with the essentials up front and everything else tucked into Advanced

## Platform Support

**Linux only, for now** (WSL works fine too, since it's real Linux underneath). Native Windows/macOS support isn't implemented and would take real work. See [nawf-dev/AM-DL](https://github.com/nawf-dev/AM-DL) if you want something similar on native Windows.

## Quick Start

### Prerequisites

You need Python 3 and sudo access on a Linux machine. That's it: the setup script installs everything else (git, ffmpeg, gpac, Go) automatically.

Check if you have Python 3:

```bash
python3 --version
```

No version number? Install it first:

| Distro | Command |
|---|---|
| Ubuntu/Debian | `sudo apt install python3` |
| Fedora | `sudo dnf install python3` |
| openSUSE | `sudo zypper install python3` |
| Arch | `sudo pacman -S python` |

You'll also need `git` to clone this repo. Same idea if `git --version` comes up empty.

### Installation

```bash
git clone https://github.com/Geekshere/AMRipper.git
cd AMRipper
python3 main.py
```

That one command does everything: installs dependencies (asking for your `sudo` password just once, for that step), sets up the downloader tools, and launches the web UI, which opens automatically in your browser at `http://localhost:5000`. No need to run it more than once; the same command starts it again on future launches too.

## Usage

1. Click **Login to Wrapper** and enter your iCloud email and password. This goes straight to the wrapper running on your own machine, nowhere else.
2. Once you see a login-success message in the logs, head to **Settings** if you want to change anything, most importantly your storefront (defaults to `us`) and your media-user-token if you want lyrics.
3. Paste an Apple Music URL and hit **Download**. Artist URLs grab the full discography automatically.

### Tagging

Every track gets tagged automatically. The downloader tags the ALAC file directly, then AMRipper handles the conversion to FLAC itself (rather than trusting the underlying tool's own conversion, which doesn't reliably carry tags over), copies the tags across, and reports what it found right in the downloader log, so you can see tagging worked without needing a separate tool.

Want to keep the original ALAC file too, or skip conversion entirely? Both are toggles in Settings.

### File Naming

Albums save as `Artist Name - Album Name (Year)`, tracks as `Track# - Song Name`. Changeable in Settings under Advanced.

## Found a Bug or Want a Feature?

Please [open an issue](https://github.com/Geekshere/AMRipper/issues) with what you were doing, what you expected, and what happened instead. The downloader/wrapper log output is usually the most useful thing to include.

## Disclaimer

For educational purposes and personal use only. Please respect Apple's Terms of Service and only download content you have the legal right to access.

**Security note:** the setup script only asks for elevated (`sudo`) privileges for the one-time system package install. Please review the code before running it.

## Acknowledgments

Massive thanks to:

- **[@lalit22km](https://github.com/lalit22km)** for the original [alac-rip](https://github.com/lalit22km/alac-rip) this is based on
- **[@zhaarey](https://github.com/zhaarey)** for [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader), which does all the actual downloading
- **[WorldObservationLog](https://github.com/WorldObservationLog)** for the authentication [wrapper](https://github.com/WorldObservationLog/wrapper)
- The entire Apple Music downloading community for their research and tools

## Development Notes

Some of the Python/Flask code here (the setup script and web UI, not the underlying downloader or wrapper tools) was written with AI coding assistance. Every change was reviewed and tested by hand before merging.
