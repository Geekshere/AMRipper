# AMRipper

A simple web interface for downloading your favorite tracks from Apple Music, no command line needed.

## About

AMRipper started as a fork of [lalit22km/alac-rip](https://github.com/lalit22km/alac-rip) and has since grown into its own standalone project: fixed up, hardened, and simplified. It's a humble web interface wrapper built around the work of other developers in the Apple Music downloading community. It gives you a clean, browser-based way to interact with the powerful Apple Music Downloader tools instead of typing commands.

**This project would not exist without the work of:**
- **[lalit22km/alac-rip](https://github.com/lalit22km/alac-rip)**, the original project this UI is based on
- **[zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)**, the core Go-based Apple Music downloader that does all the actual downloading
- **[WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper)**, the authentication wrapper that handles Apple Music login and session management

All credit for the actual downloading capabilities goes to these original creators. AMRipper is a convenience layer and bugfix pass on top of their tools.

## Features

- Clean, modern web UI accessible from any browser
- Save credentials for automatic login on startup
- ALAC (lossless) downloads, converted to FLAC automatically after downloading
- Full metadata tagging on every download: title, artist, album, track/disc numbers, composer, genre, lyrics, and cover art
- Strips the trailing "- Single" that Apple appends to single-track releases, in both the folder name and the album tag
- Live log streaming without debug spam or raw terminal escape codes cluttering the view
- Works across distros: detects and uses whichever of apt, dnf, zypper, or pacman is available
- Only the one-time system package install needs elevated privileges; everything else runs as your own user, so downloaded files aren't left root-owned
- Artist URLs automatically grab the full discography and organize it into an artist folder, instead of hanging on a terminal prompt the web server can't answer
- A settings page for the options you'd actually want to change, with the rarely-touched ones tucked away in an Advanced section

## Platform Support

Linux only, for now. `main.py` shells out to distro package managers, uses Unix-specific APIs, and downloads Linux binaries for Bento4 and the wrapper, none of which work on Windows or macOS as they are.

WSL (Windows Subsystem for Linux) should work fine, since it's a real Linux environment underneath. That's effectively how this already gets used on Windows today.

Native Windows or macOS support isn't implemented, and it's not a small change: the wrapper and Bento4 binaries would need Windows/macOS builds, and most of `main.py`'s setup logic would need platform-specific branches. If you want something similar on native Windows, [nawf-dev/AM-DL](https://github.com/nawf-dev/AM-DL) is a separate tool built around the same wrapper backend. Contributions adding real native support here are welcome, but it isn't something currently planned.

## Quick Start

### Prerequisites

You need Python 3 and sudo access on a Linux machine (or WSL). That's really it; the setup script installs everything else (git, ffmpeg, gpac, Go) for you automatically.

If you're not sure whether you have Python 3, open a terminal and run:

```bash
python3 --version
```

If that prints a version number, you're set. If it says "command not found," install Python first:

- **Ubuntu/Debian:** `sudo apt install python3`
- **Fedora:** `sudo dnf install python3`
- **openSUSE:** `sudo zypper install python3`
- **Arch:** `sudo pacman -S python`

You'll also need `git` to clone this repository in the first place. If `git --version` doesn't work, install it the same way (swap `python3` for `git` in the commands above).

### Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/Geekshere/AMRipper.git
   cd AMRipper
   ```

2. Run the setup:
   ```bash
   python3 main.py
   ```

   You do not need to run this as root or with `sudo`. The first run will automatically:
   - Detect your distro's package manager and install the required system packages, asking for your `sudo` password only for that one step
   - Download and set up Bento4
   - Download the wrapper tool
   - Clone the Apple Music Downloader
   - Install Python dependencies

3. Your browser will open automatically to `http://localhost:5000` once the server is ready. If it doesn't, just open that address yourself.

## Usage

### First Time Setup

1. Click "Login to Wrapper" and enter your iCloud email and password. This is your Apple ID; it's sent directly to the wrapper running on your own machine, nowhere else.
2. Watch the wrapper logs until you see a login-success message.
3. Click Settings if you want to change anything, most importantly your storefront (defaults to "us") and your media-user-token if you want lyrics.
4. Paste an Apple Music URL and click Download. Artist URLs automatically grab the full discography.

### Tagging

Every downloaded track gets tagged automatically: title, artist, album, album artist, track/disc numbers, composer, genre, ISRC, release date, copyright, and cover art. After each download finishes, AMRipper reads the tags back off the actual file and reports what it found in the downloader log, so you can see directly whether tagging worked without needing a separate tool.

Single-track releases also have the trailing "- Single" suffix Apple adds stripped from both the folder name and the album tag.

### File Naming

By default, albums are saved as `Artist Name - Album Name (Year)`, and tracks inside as `Track# - Song Name`. Both can be changed on the Settings page under Advanced.

### Settings

The settings page is split into what you'll actually want to touch (your media-user-token, storefront, download folder, and conversion settings) and an Advanced section for everything else: file naming templates, tag formatting, and low-level connection settings that most people never need to change.

## Disclaimer

This tool is for educational purposes and personal use only. Please respect Apple's Terms of Service and only download content you have the legal right to access. The developers of this UI wrapper are not responsible for any misuse of the underlying downloading tools.

**Security note:** the setup script only requests elevated (`sudo`) privileges for the one-time system package install step. Please review the code before running it.

## Acknowledgments

Massive thanks to:

- **[@lalit22km](https://github.com/lalit22km)** for the original [alac-rip](https://github.com/lalit22km/alac-rip) project this is based on
- **[@zhaarey](https://github.com/zhaarey)** for creating the [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) that makes this possible
- **[WorldObservationLog](https://github.com/WorldObservationLog)** for maintaining the authentication [wrapper](https://github.com/WorldObservationLog/wrapper)
- The entire Apple Music downloading community for their research and tools

## Development Notes

Some of the Python/Flask code in this repo (the setup script and web UI, not the underlying downloader or wrapper tools) was written with AI coding assistance. Every change was reviewed and tested by hand before being merged. AI assistance was used for writing and iterating on code, not as a substitute for actually running it.
