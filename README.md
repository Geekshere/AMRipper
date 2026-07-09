# AMRipper

A simple web interface for the Apple Music Downloader, making it easier to download your favorite tracks with a user-friendly GUI.

## 🎵 About

AMRipper started as a fork of [lalit22km/alac-rip](https://github.com/lalit22km/alac-rip) and has since diverged into its own standalone project — fixed up, hardened, and extended. It's a humble web interface wrapper built around the excellent work of other developers in the Apple Music downloading community, providing a clean, browser-based UI to interact with the powerful Apple Music Downloader tools without needing to touch a command line.

**This project would not exist without the work of:**
- **[lalit22km/alac-rip](https://github.com/lalit22km/alac-rip)** - The original project this UI is based on
- **[zhaarey/apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)** - The core Go-based Apple Music downloader that powers all the downloading functionality
- **[WorldObservationLog/wrapper](https://github.com/WorldObservationLog/wrapper)** - The authentication wrapper that handles Apple Music login and session management

All credit for the actual downloading capabilities goes to these original creators — AMRipper is a convenience layer and bugfix pass on top of their tools.

## ✨ Features

- **🌐 Web-based Interface**: Clean, modern web UI accessible from any browser
- **🔐 Auto-Login**: Save credentials for automatic login on startup
- **🎵 Multiple Formats**: Support for ATMOS, AAC, and standard downloads
- **🏷️ Automatic Tagging**: Artist, album, title, track/disc number, track/disc total, composer, genre, lyrics, and cover art are embedded automatically on every download
- **🧹 Clean Single Naming**: Strips the trailing "- Single" Apple Music appends to single-track releases, in both folder names and the embedded album tag
- **📊 Real-time Logs**: Live streaming of download and wrapper status, without debug spam or raw ANSI escape codes cluttering the terminal view
- **🐧 Distro-Agnostic Setup**: Detects and uses whichever of apt/dnf/zypper/pacman is available, rather than assuming Debian/Ubuntu
- **👤 No Full-Root Requirement**: Only the system package install step elevates privileges; everything else runs as your own user so downloaded files aren't left root-owned
- **🎯 Artist Discography Downloads**: Artist URLs automatically grab the full discography instead of hanging on a terminal prompt the web server can't answer
- **⚙️ Settings Management**: Easy configuration of all downloader options via web interface
- **📱 Responsive Design**: Works on desktop and mobile browsers

## 🚀 Quick Start

### Prerequisites

- **Linux environment** (also works on WSL)
- **sudo access** (only needed for the one-time system package install)
- **Python 3.7+** with Flask
- **Go** (for running the Apple Music Downloader)
- **Git** (for cloning repositories)

### Installation

1. **Clone this repository:**
   ```bash
   git clone https://github.com/Geekshere/AMRipper.git
   cd AMRipper
   ```

2. **Run the setup:**
   ```bash
   python3 main.py
   ```

   You do **not** need to run this as root. The first run will automatically:
   - Detect your distro's package manager (apt/dnf/zypper/pacman) and install required system packages, prompting for `sudo` only for that step
   - Download and set up Bento4
   - Download the wrapper tool
   - Clone the Apple Music Downloader
   - Install Python dependencies

3. **Access the web interface:**
   - Open your browser and navigate to `http://localhost:5000`
   - The interface will be ready to use!

## 📖 Usage

### First Time Setup

1. **Login**: Click "Login to Wrapper" and enter your Apple Music credentials
2. **Wait for Success**: Watch the wrapper logs until you see a login-success message
3. **Configure Settings**: Click the ⚙️ Settings button to customize download preferences
4. **Start Downloading**: Paste Apple Music URLs and choose your format — artist URLs will automatically download the full discography

### Download Options

- **Standard Download**: Uncheck "Special Audio" for basic downloads
- **ATMOS**: Check "Special Audio" and select "ATMOS" for spatial audio
- **AAC**: Check "Special Audio" and select "AAC" for AAC format

### Tagging

Every downloaded track is automatically tagged with title, artist, album, album artist, track/disc number and totals, composer, genre, ISRC, release date, copyright, and cover art — no extra steps needed. Single-track releases also have the trailing "- Single" suffix Apple appends stripped from both the folder name and the embedded album tag.

### Settings

The settings page allows you to configure:
- Download folders and file naming
- Audio quality and format preferences
- Cover art and lyrics options
- Advanced downloader parameters

---

The application acts as a bridge between the web interface and the command-line tools, handling:
- Authentication state management
- Process lifecycle management
- Configuration file editing
- Real-time log streaming
- Download queue management
- Post-download folder/tag cleanup (single-suffix stripping)

## ⚠️ Disclaimer

This tool is for educational purposes and personal use only. Please respect Apple's Terms of Service and only download content you have the legal right to access. The developers of this UI wrapper are not responsible for any misuse of the underlying downloading tools.

**Security Note:** The setup script only requests elevated (`sudo`) privileges for the one-time system package install step. Please review the code before running it.

## 🙏 Acknowledgments

**Massive thanks to:**

- **[@lalit22km](https://github.com/lalit22km)** for the original [alac-rip](https://github.com/lalit22km/alac-rip) project this is based on
- **[@zhaarey](https://github.com/zhaarey)** for creating the [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) that makes this possible
- **[WorldObservationLog](https://github.com/WorldObservationLog)** for maintaining the authentication [wrapper](https://github.com/WorldObservationLog/wrapper)
- The entire Apple Music downloading community for their research and tools

## 🤖 Development Notes

Some of the Python/Flask code in this repo (the setup script and web UI, not the underlying downloader or wrapper tools) was written with AI coding assistance. Every change was reviewed and tested by hand before being merged — AI assistance was used for writing and iterating on code, not as a substitute for actually running it.

---
