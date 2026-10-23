"""Kindle Tools local server (127.0.0.1 only).

While the page is open it pings /api/ping every minute. After IDLE_EXIT
seconds without any request the server shuts itself down, so nothing keeps
running in the background. On shutdown it releases the MTP session and the
Kindle leaves "connected" mode.
"""
import io
import json
import os
import signal
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import pymupdf

import mtp
import pdf_cutter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WEB = HERE / "web"
SHOTS = ROOT / ".cache" / "screenshots"
THUMBS = ROOT / ".cache" / "thumbs"
PORT = 8765
IDLE_EXIT = 300

last_request = time.monotonic()

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# The macOS file picker via AppleScript. Returns a POSIX path, or "" when
# the user cancels (error -128).
PICK_PDF = '''
on run argv
    activate
    try
        return POSIX path of (choose file with prompt "Choose a Kindle notebook PDF" of type {"com.adobe.pdf"})
    on error number -128
        return ""
    end try
end run
'''


def applescript(script, *args):
    global last_request
    out = subprocess.run(["osascript", "-e", script, *args], capture_output=True, text=True).stdout.strip()
    last_request = time.monotonic()  # the dialog may have been open for a while
    return out


def display_path(path) -> str:
    """Path for display, with the home folder shortened to ~."""
    home = str(Path.home())
    path = str(path).rstrip("/") or "/"
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def make_thumbs():
    THUMBS.mkdir(parents=True, exist_ok=True)
    names = {p.name for p in SHOTS.glob("*.png")}
    for t in THUMBS.glob("*.png"):
        if t.name not in names:
            t.unlink()
    for name in names:
        t = THUMBS / name
        if not t.exists():
            pix = pymupdf.Pixmap(str(SHOTS / name))
            pix.shrink(2)  # quarter size
            pix.save(str(t))


def shot_list():
    shots = []
    for p in sorted(SHOTS.glob("*.png"), reverse=True):
        try:
            stamp = datetime.strptime(p.stem[len("screenshot_"):len("screenshot_") + 19], "%Y_%m_%dT%H_%M_%S")
            label = f"{stamp.day} {MONTHS[stamp.month - 1]} {stamp.year} · {stamp:%H:%M:%S}"
        except ValueError:
            label = p.stem
        shots.append({"name": p.name, "label": label})
    return shots


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, *a):
        pass

    def end_headers(self):
        # The page itself must never come from the browser's cache, or an
        # updated Kindle Tools keeps showing the old interface.
        if urlparse(self.path).path in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data, ctype, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if filename:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.end_headers()
        self.wfile.write(data)

    def safe_shot(self, base, name):
        p = (base / name).resolve()
        if p.parent != base.resolve() or not p.is_file():
            return None
        return p

    def do_GET(self):
        global last_request
        last_request = time.monotonic()
        url = urlparse(self.path)
        q = parse_qs(url.query)

        if url.path == "/api/ping":
            # Which copy of Kindle Tools this is, so the launcher of another
            # copy can tell it apart and take over (see `kindle`).
            return self.send_json({"ok": True, "root": str(ROOT), "pid": os.getpid(), "worker": mtp.worker_pid()})

        if url.path == "/api/gallery":
            try:
                mtp.sync_screenshots(SHOTS)
            except mtp.MTPError as e:
                return self.send_json({"error": str(e), "cached": shot_list()}, 409)
            make_thumbs()
            return self.send_json({"shots": shot_list()})

        if url.path == "/api/gallery/cached":
            make_thumbs()
            return self.send_json({"shots": shot_list()})

        if url.path.startswith("/thumb/") or url.path.startswith("/shot/"):
            base = THUMBS if url.path.startswith("/thumb/") else SHOTS
            p = self.safe_shot(base, unquote(url.path.split("/", 2)[2]))
            if not p:
                return self.send_error(404)
            return self.send_bytes(p.read_bytes(), "image/png")

        if url.path == "/api/download":
            names = q.get("n", [])
            files = [p for n in names if (p := self.safe_shot(SHOTS, n))]
            if not files:
                return self.send_error(404)
            if len(files) == 1:
                return self.send_bytes(files[0].read_bytes(), "image/png", files[0].name)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
                for p in files:
                    z.write(p, p.name)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
            return self.send_bytes(buf.getvalue(), "application/zip", f"kindle-screenshots_{stamp}.zip")

        return super().do_GET()

    def do_POST(self):
        global last_request
        last_request = time.monotonic()
        path = urlparse(self.path).path
        if path == "/api/delete":
            return self.delete_shots()
        if path == "/api/pdf-cutter":
            return self.pdf_cutter()
        return self.send_error(404)

    def delete_shots(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            names = json.loads(body)["names"]
        except (ValueError, KeyError, TypeError):
            return self.send_error(400)
        names = [n for n in names if isinstance(n, str) and mtp.SCREENSHOT_RE.match(n) and "/" not in n]
        if not names:
            return self.send_error(400)
        try:
            deleted, failed = mtp.delete_screenshots(names)
            mtp.sync_screenshots(SHOTS)  # bring the cache in line with the device
        except mtp.MTPError as e:
            return self.send_json({"error": str(e)}, 409)
        make_thumbs()
        return self.send_json({"deleted": deleted, "failed": failed, "shots": shot_list()})

    def pdf_cutter(self):
        picked = applescript(PICK_PDF)
        if not picked:
            return self.send_json({"cancelled": True})
        src = Path(picked)
        try:
            doc = pdf_cutter.clean(src)
        except pdf_cutter.NotKindleNotebook:
            return self.send_json({"error": "not_notebook", "file": src.name}, 422)
        except pdf_cutter.NothingToClean:
            return self.send_json({"error": "nothing_to_clean", "file": src.name}, 422)

        # The cleaned copy goes next to the original.
        dst = src.parent / f"{src.stem}_clean.pdf"
        try:
            pdf_cutter.save(doc, dst)
        except OSError:
            return self.send_json({"error": "save_failed", "file": src.name, "folder": display_path(dst.parent)}, 500)
        return self.send_json({"file": src.name, "saved": dst.name, "folder": display_path(dst.parent)})


def idle_watchdog(server):
    while True:
        time.sleep(15)
        if time.monotonic() - last_request > IDLE_EXIT:
            server.shutdown()
            return


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=idle_watchdog, args=(server,), daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    try:
        server.serve_forever()
    finally:
        mtp.release()


if __name__ == "__main__":
    main()
