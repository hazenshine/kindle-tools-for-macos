"""Client that manages the Kindle's MTP session.

When an MTP session is closed the Kindle leaves USB mode and only charges.
So the session is opened in the mtp_worker.py process and stays open as long
as that process lives. release() (on server shutdown) ends the process and
the Kindle leaves "connected" mode. If the cable is unplugged and plugged
back in, the next request starts a fresh process.
"""
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

WORKER = Path(__file__).resolve().parent / "mtp_worker.py"
SCREENSHOT_RE = re.compile(r"^screenshot_.*\.png$", re.IGNORECASE)
OPEN_TIMEOUT = 30
SYNC_TIMEOUT = 600


class MTPError(Exception):
    pass


_proc = None
_lock = threading.Lock()


def _read(timeout):
    """Read one reply line from the worker; None if it died or went silent."""
    result = []
    t = threading.Thread(target=lambda: result.append(_proc.stdout.readline()), daemon=True)
    t.start()
    t.join(timeout)
    if not result or not result[0]:
        return None
    return json.loads(result[0])


def _stop():
    global _proc
    if _proc:
        try:
            _proc.stdin.close()
            _proc.wait(timeout=10)
        except Exception:
            _proc.kill()
        _proc = None


def _start():
    global _proc
    _proc = subprocess.Popen(
        [sys.executable, "-I", str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
        text=True, bufsize=1,
    )
    msg = _read(OPEN_TIMEOUT)
    if not msg or msg.get("error"):
        _stop()
        raise MTPError(msg["error"] if msg else "open_failed")


def is_open():
    return _proc is not None and _proc.poll() is None


def worker_pid():
    """PID of the process holding the Kindle, or None."""
    return _proc.pid if is_open() else None


def release():
    with _lock:
        _stop()


def _request(cmd: dict):
    """Send a command to the worker and return its reply.

    Opens a session if there is none. If the session was lost (cable
    unplugged and plugged back in), retries once with a fresh one.
    """
    with _lock:
        for attempt in range(2):
            if not is_open():
                _stop()
                _start()
            try:
                _proc.stdin.write(json.dumps(cmd) + "\n")
                _proc.stdin.flush()
                msg = _read(SYNC_TIMEOUT)
            except BrokenPipeError:
                msg = None
            if msg and "error" not in msg:
                return msg
            if msg and msg["error"] != "disconnected":
                raise MTPError(msg["error"])  # the session stays open
            _stop()
        raise MTPError("not_connected")


def sync_screenshots(dest: Path):
    """Mirror the device's screenshots into dest and return their names."""
    return _request({"cmd": "sync", "dest": str(dest)})["names"]


def delete_screenshots(names):
    """Permanently delete screenshots from the Kindle; returns (deleted, failed)."""
    msg = _request({"cmd": "delete", "names": list(names)})
    return msg["deleted"], msg["failed"]
