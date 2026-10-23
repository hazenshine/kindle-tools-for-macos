# Changelog

All notable changes to Kindle Tools are listed here. Versions follow [Semantic Versioning](https://semver.org): new features raise the minor number, fixes the patch number.

## [1.0.0] - 2026-10-23

The first release: a local web app for the Kindle Scribe on macOS with two tools, **PDF Cutter** and **Gallery**. It runs entirely on your Mac and talks to the Kindle over USB.

### PDF Cutter

- Cleans notebook PDFs exported from the Scribe:
  - removes the "N of M" page number (redacted, not just covered),
  - crops the empty bottom strip so each page has the notebook's own 3:4 size (595 × 794 pt).
- The handwriting image isn't re-encoded and the searchable OCR text layer is kept.
- The original is never modified: the cleaned copy is saved next to it as `<name>_clean.pdf`.
- Rejects PDFs that aren't Scribe notebook exports, and says so when a file has already been cleaned.

### Gallery

- Lists the screenshots on the Kindle as thumbnails. Only new screenshots are copied, so later visits are quick.
- Dates are shown as "20 October 2026 · 20:20".
- Preview at full size and move between screenshots with ← / →.
- Select one, several or all; **Download** gives one PNG, or a ZIP for several.
- **Delete** removes screenshots from the Kindle after a confirmation.
- When the Kindle isn't connected, the screenshots fetched last time can still be opened.

### Kindle connection (USB / MTP)

- Talks to the Kindle through **libmtp** (via `ctypes`) in a separate worker process.
  - **One session is kept open while the server runs.** The Scribe leaves USB mode whenever an MTP session closes, so opening a new session for each request would disconnect it.
  - **A libmtp crash on macOS only takes down the worker, not the server.**
- If the cable is unplugged and plugged back in, the next request reconnects by itself.
- Clear messages for the usual problems: Kindle not connected, another MTP app (such as Calibre) holding it, libmtp missing.
- **Read-only** except Delete, which asks first.

### App

- **`kindle`** launcher: starts the local server on `127.0.0.1:8765` and opens the page in your browser.
  - If another copy of Kindle Tools is already running, it takes over from it without disconnecting the Kindle.
  - The page pings the server every minute. After 5 minutes without requests the server stops and releases the Kindle.
- **`install.sh`**: one-step setup that is safe to run again.
  - Installs libmtp with Homebrew and checks for Python 3.10+.
  - Creates a project-local `.venv`.
  - Optionally adds a `kindle` terminal command.
- One simple page: a cream theme with ink and orange accents, Baloo 2 and Quicksand fonts, one button style. Keyboard support, and it works at phone width.
- Everything stays on your Mac; the only outside request is for the Google Fonts.

[1.0.0]: https://github.com/hazenshine/kindle-tools-for-macos/releases/tag/v1.0.0
