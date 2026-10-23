# Kindle Tools for macOS

A small local web app for the **Kindle Scribe** on **macOS**. Type `kindle` in the terminal and a page opens in your browser with two tools:

| Tool | What it does |
|---|---|
| **PDF Cutter** | Cleans notebook PDFs exported from the Scribe: removes the "1 of 1" page number and cuts off the empty strip at the bottom, so the page has the notebook's own 3:4 size. Handwriting and the searchable OCR text stay untouched. |
| **Gallery** | Shows the screenshots on your Kindle. Preview them, pick the ones you want, download them (one PNG, or a ZIP for several), or delete them from the Kindle. |

Everything runs on your Mac. The server only listens on `127.0.0.1`, and nothing is uploaded anywhere.

> Not affiliated with or endorsed by Amazon. Kindle and Kindle Scribe are trademarks of Amazon.com, Inc.

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Uninstall](#uninstall)
- [License and credits](#license-and-credits)
- [Changelog](CHANGELOG.md)

---

## Requirements

| | Version | Notes |
|---|---|---|
| macOS | tested on 15.7 | Uses macOS dialogs (`osascript`) and `open`; other systems are not supported. |
| [Homebrew](https://brew.sh) | any | Used to install libmtp. |
| Python | 3.10 or newer | `brew install python` if you don't have it. |
| [libmtp](https://github.com/libmtp/libmtp) | 1.1.x | System library for talking to the Kindle over USB (MTP). |
| [PyMuPDF](https://pymupdf.readthedocs.io) | 1.28.2 | Python package for the PDF work and thumbnails. |
| Kindle | Scribe | Any Kindle that connects over **MTP** should work for the Gallery (Scribe since firmware 5.16.3, newer Paperwhites, Colorsoft, Kindle 2022+). PDF Cutter is specific to the Scribe. |

**Tested with:** macOS 15.7 (Apple Silicon), Kindle Scribe (1st gen) firmware 5.20.1, Python 3.14, libmtp 1.1.23, PyMuPDF 1.28.2.

## Installation

```bash
cd ~
git clone https://github.com/hazenshine/kindle-tools-for-macos.git
cd kindle-tools-for-macos
zsh install.sh
```

Or download the latest version from [Releases](https://github.com/hazenshine/kindle-tools-for-macos/releases/latest) (*Source code (zip)*), unzip it, and run `zsh install.sh` in that folder from Terminal.

### What install.sh does

It's safe to run again, and finished steps are skipped:

1. checks for Homebrew and installs **libmtp** (`brew install libmtp`),
2. checks for **Python 3.10+**,
3. creates a virtual environment in `.venv/` inside the project and installs `requirements.txt` into it,
4. optionally adds a `kindle` terminal command to `~/.zshrc`, so you can start Kindle Tools from any folder.

Nothing else is installed outside the project folder.

### Manual install

If you'd rather run each step yourself:

```bash
brew install libmtp                         # USB/MTP library
python3 -m venv .venv                       # project-local Python environment
.venv/bin/pip install -r requirements.txt   # PyMuPDF
chmod +x kindle
```

Optionally, add a terminal command (use the real path of your clone):

```bash
echo "alias kindle='\"$PWD/kindle\"'" >> ~/.zshrc
source ~/.zshrc
```

## Usage

```bash
./kindle          # from the project folder
kindle            # anywhere, if you added the terminal command
```

This starts the local server in the background (if it isn't already running) and opens `http://127.0.0.1:8765` in your browser. Close the tab when you're done; the server stops by itself about 5 minutes later.

### PDF Cutter

1. On the Kindle Scribe, share a notebook as PDF (for example by e-mail) and save it on your Mac.
2. Click **PDF Cutter** and pick the PDF in the dialog.
3. The cleaned copy is saved next to the original as `<name>_clean.pdf`.

The original file is never modified. A PDF that isn't a Scribe notebook export is rejected with *"This file is not a Kindle notebook PDF."*

What exactly changes, per page:

- The `N of M` page number is **redacted**: removed from the file, not just covered.
- The page is resized from A4 (595 × 842 pt) to the handwriting image (595 × 794 pt, 3:4) by setting the PDF MediaBox, so every PDF viewer shows the new size.
- The handwriting image is not re-encoded, and the OCR text layer stays searchable.

### Gallery

1. Connect the Kindle with a USB cable and wait until it shows that it's connected to a computer.
2. Click **Gallery**. New screenshots are copied to a local cache (only new ones, so it's fast after the first time) and shown as thumbnails.
3. Click a thumbnail to select it. Hover over a thumbnail and click the **magnifier** in its corner to see it full size; use ← / → to move between screenshots.
4. **Download** saves one PNG, or a ZIP if several are selected.
5. **Delete** removes the selected screenshots from the Kindle after a confirmation. The Kindle has no trash, so this can't be undone.

If the Kindle isn't connected, you can still open the screenshots fetched last time.

## How it works

```
Browser ── http://127.0.0.1:8765 ──▶ app/server.py ──▶ app/mtp.py ──▶ app/mtp_worker.py ──▶ libmtp ──▶ Kindle (USB/MTP)
                                          │
                                          └──▶ app/pdf_cutter.py (PyMuPDF)
```

- **`kindle`** is the launcher. It starts `app/server.py` with the project's `.venv` Python and opens the browser. If another copy of Kindle Tools (a second clone, for example) is already running, it stops that one first, without disconnecting the Kindle.
- **`app/server.py`** is a small HTTP server from the Python standard library. It serves the page in `app/web/` and a JSON API. While the page is open it pings the server every minute; after 5 minutes without any request the server exits.
- **The Kindle connection lives in a separate process (`app/mtp_worker.py`)** that calls libmtp through `ctypes`. There are two reasons:
  - **The Kindle leaves USB mode when an MTP session is closed.** It drops off USB and only charges until the cable is plugged in again. So the session is opened once and kept open while the server runs, which is also why command-line tools like `mtp-files` can't be chained.
  - **libmtp can crash on macOS** when opening a session fails, because the USB reset in its error path segfaults. In a separate process, a crash doesn't take the server down.
- **MTP is exclusive.** Only one program can talk to the Kindle at a time: Calibre, Android File Transfer, OpenMTP, or Kindle Tools.

Screenshots are stored in `.cache/screenshots`, with thumbnails in `.cache/thumbs`. The cache mirrors the Kindle: screenshots deleted on the Kindle disappear from it on the next Gallery refresh.

The only request that leaves your Mac is for the Google Fonts used by the page (Baloo 2 and Quicksand). Without internet the page falls back to the system font.

## Troubleshooting

| Problem | What to do |
|---|---|
| *"The Kindle isn't connected"* | Plug in the cable and wait for the Kindle's "connected to computer" screen, then try again. |
| *"Couldn't connect to the Kindle"* | Another app is using it. Quit **Calibre** (and Android File Transfer / OpenMTP), unplug and replug the cable, try again. |
| The Kindle went back to "charging only" | Expected when the server stops (after the page has been closed for ~5 min) or when another MTP app closes its session. Unplug and replug the cable. |
| Calibre doesn't see the Kindle | Kindle Tools still holds the connection. Close the page and wait ~5 minutes, or unplug and replug the cable. |
| *"libmtp isn't installed"* | `brew install libmtp` |
| macOS asks whether Terminal may access a folder | PDF Cutter reads and saves PDFs in the folder you pick. Click **Allow**; macOS asks once per protected folder (Documents, Desktop, Downloads). |
| `kindle: command not found` | Open a new terminal window, or run `source ~/.zshrc`. Check that `~/.zshrc` has the `alias kindle=…` line. Or run `./kindle` from the project folder. |
| The page doesn't open / port 8765 is busy | Something else uses the port. Change `PORT` in `app/server.py` and the URL in `kindle`. |
| Anything else | The server log is in `.cache/server.log`. |

## Project structure

```
kindle-tools-for-macos/
├── kindle                  # launcher: starts the server, opens the browser
├── install.sh              # one-step installer
├── requirements.txt        # Python packages (PyMuPDF)
├── CHANGELOG.md            # what changed in each version
└── app/
    ├── server.py           # local HTTP server and JSON API
    ├── pdf_cutter.py       # notebook PDF cleaning (PyMuPDF)
    ├── mtp.py              # starts/talks to the MTP worker process
    ├── mtp_worker.py       # holds the Kindle session (libmtp via ctypes)
    └── web/index.html      # the whole UI (HTML, CSS, JS; no build step)
```

Created while running (ignored by git): `.venv/`, `.cache/` (screenshots, thumbnails, server log).

## Uninstall

1. If you added the terminal command, remove the `# Kindle Tools` and `alias kindle=…` lines from `~/.zshrc`.
2. Delete the project folder.
3. Optionally: `brew uninstall libmtp`.

## License and credits

Kindle Tools is free software under the **GNU General Public License v3**. See [LICENSE](LICENSE).

- [libmtp](https://github.com/libmtp/libmtp) (LGPL) and [PyMuPDF](https://pymupdf.readthedocs.io) (AGPL / commercial) are installed separately and keep their own licenses.
- Fonts: [Baloo 2](https://fonts.google.com/specimen/Baloo+2) and [Quicksand](https://fonts.google.com/specimen/Quicksand) via Google Fonts (SIL Open Font License).
