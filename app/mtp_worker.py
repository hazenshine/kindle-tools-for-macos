"""Helper process that holds the Kindle's MTP session.

Why a separate process: libmtp's connection-error path can crash on macOS
(segfault during the USB reset). A crash only takes down this process; the
server stays up and starts a new one on the next request.

Protocol: JSON commands on stdin, one per line; JSON replies, one per line,
on a copy of the original stdout. libmtp prints its own messages to stdout
too, so the real stdout is redirected to stderr.

    {"cmd": "sync", "dest": "/path"}  ->  {"names": [...]} | {"error": "..."}
    {"cmd": "delete", "names": [...]} ->  {"deleted": [...], "failed": [...]}
    The session stays open after errors; the process only exits if the
    Kindle stops responding ("disconnected"). When stdin closes the session
    is released and the Kindle leaves "connected" mode.
"""
import ctypes
import ctypes.util
import json
import os
import re
import sys
import time
from pathlib import Path

proto = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)

SCREENSHOT_RE = re.compile(r"^screenshot_.*\.png$", re.IGNORECASE)
ERROR_NO_DEVICE_ATTACHED = 5


class LIBMTP_file_t(ctypes.Structure):
    pass


LIBMTP_file_t._fields_ = [
    ("item_id", ctypes.c_uint32),
    ("parent_id", ctypes.c_uint32),
    ("storage_id", ctypes.c_uint32),
    ("filename", ctypes.c_char_p),
    ("filesize", ctypes.c_uint64),
    ("modificationdate", ctypes.c_long),
    ("filetype", ctypes.c_int),
    ("next", ctypes.POINTER(LIBMTP_file_t)),
]

class LIBMTP_devicestorage_t(ctypes.Structure):
    pass


LIBMTP_devicestorage_t._fields_ = [
    ("id", ctypes.c_uint32),
    ("StorageType", ctypes.c_uint16),
    ("FilesystemType", ctypes.c_uint16),
    ("AccessCapability", ctypes.c_uint16),
    ("MaxCapacity", ctypes.c_uint64),
    ("FreeSpaceInBytes", ctypes.c_uint64),
    ("FreeSpaceInObjects", ctypes.c_uint64),
    ("StorageDescription", ctypes.c_char_p),
    ("VolumeIdentifier", ctypes.c_char_p),
    ("next", ctypes.POINTER(LIBMTP_devicestorage_t)),
    ("prev", ctypes.POINTER(LIBMTP_devicestorage_t)),
]


class LIBMTP_mtpdevice_t(ctypes.Structure):
    # Only the leading fields we need; the rest of the struct is never touched.
    _fields_ = [
        ("object_bitsize", ctypes.c_uint8),
        ("params", ctypes.c_void_p),
        ("usbinfo", ctypes.c_void_p),
        ("storage", ctypes.POINTER(LIBMTP_devicestorage_t)),
    ]


DEVICE_P = ctypes.POINTER(LIBMTP_mtpdevice_t)
FILETYPE_FOLDER = 0

def _load_libmtp():
    """libmtp from Homebrew: /opt/homebrew on Apple Silicon, /usr/local on Intel."""
    for path in (ctypes.util.find_library("mtp"),
                 "/opt/homebrew/lib/libmtp.dylib", "/usr/local/lib/libmtp.dylib"):
        if path and os.path.exists(path):
            return ctypes.CDLL(path)
    proto.write(json.dumps({"error": "libmtp_missing"}) + "\n")
    sys.exit("libmtp not found. Install it with: brew install libmtp")


lib = _load_libmtp()
lib.LIBMTP_Detect_Raw_Devices.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)]
lib.LIBMTP_Detect_Raw_Devices.restype = ctypes.c_int
lib.LIBMTP_Open_Raw_Device_Uncached.argtypes = [ctypes.c_void_p]
lib.LIBMTP_Open_Raw_Device_Uncached.restype = DEVICE_P
lib.LIBMTP_Get_Storage.argtypes = [DEVICE_P, ctypes.c_int]
lib.LIBMTP_Get_Storage.restype = ctypes.c_int
lib.LIBMTP_Get_Files_And_Folders.argtypes = [DEVICE_P, ctypes.c_uint32, ctypes.c_uint32]
lib.LIBMTP_Get_Files_And_Folders.restype = ctypes.POINTER(LIBMTP_file_t)
lib.LIBMTP_Get_File_To_File.argtypes = [DEVICE_P, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p]
lib.LIBMTP_Get_File_To_File.restype = ctypes.c_int
lib.LIBMTP_destroy_file_t.argtypes = [ctypes.POINTER(LIBMTP_file_t)]
lib.LIBMTP_Delete_Object.argtypes = [DEVICE_P, ctypes.c_uint32]
lib.LIBMTP_Delete_Object.restype = ctypes.c_int
lib.LIBMTP_Release_Device.argtypes = [DEVICE_P]
lib.LIBMTP_Clear_Errorstack.argtypes = [DEVICE_P]
libc = ctypes.CDLL(None)

# Screenshot folders found in this session: [(storage_id, folder_id)]
screenshot_dirs = None


class Disconnected(Exception):
    pass


def reply(**data):
    proto.write(json.dumps(data) + "\n")


def open_device():
    raw = ctypes.c_void_p()
    count = ctypes.c_int(0)
    err = lib.LIBMTP_Detect_Raw_Devices(ctypes.byref(raw), ctypes.byref(count))
    if err == ERROR_NO_DEVICE_ATTACHED or count.value == 0:
        return None, "not_connected"
    if err != 0:
        return None, "detect_failed"
    try:
        device = lib.LIBMTP_Open_Raw_Device_Uncached(raw)
    finally:
        libc.free(raw)
    return (device, None) if device else (None, "busy")


def storages(device):
    """Storage IDs. Raises Disconnected if the Kindle doesn't respond."""
    if lib.LIBMTP_Get_Storage(device, 0) != 0:
        lib.LIBMTP_Clear_Errorstack(device)
        raise Disconnected
    out = []
    node = device.contents.storage
    while node:
        st = node.contents
        out.append(st.id)
        node = st.next
    return out


def children(device, storage, parent):
    """Contents of a folder: [(id, parent_id, name, size, is_folder)].

    In PTP, parent=0 means "everything in the storage, regardless of folders".
    """
    out = []
    node = lib.LIBMTP_Get_Files_And_Folders(device, storage, parent)
    while node:
        f = node.contents
        out.append((f.item_id, f.parent_id, (f.filename or b"").decode("utf-8", "replace"),
                    f.filesize, f.filetype == FILETYPE_FOLDER))
        # f.next is not a copy but a view into the node's memory: take the
        # address as a plain number before freeing the node, or the list
        # breaks off after the first item.
        nxt = ctypes.cast(f.next, ctypes.c_void_p).value
        lib.LIBMTP_destroy_file_t(node)
        node = ctypes.cast(nxt, ctypes.POINTER(LIBMTP_file_t)) if nxt else None
    lib.LIBMTP_Clear_Errorstack(device)
    return out


def log(*a):
    print("[mtp_worker]", *a, file=sys.stderr, flush=True)


def shots_in(items):
    return {n: (i, size) for i, _, n, size, d in items if not d and SCREENSHOT_RE.match(n)}


def full_scan(device):
    """Ask for everything in the storage as one flat list (parent=0) and learn
    the screenshot folder from it. Later calls only look in that folder."""
    global screenshot_dirs
    remote, dirs = {}, set()
    for storage in storages(device):
        t = time.monotonic()
        items = children(device, storage, 0)
        found = shots_in(items)
        remote.update(found)
        dirs |= {(storage, p) for i, p, n, _, d in items if n in found and not d}
        log(f"full scan storage={storage:#x} items={len(items)} shots={len(found)} "
            f"dirs={sorted(dirs)} {time.monotonic() - t:.1f}s")
    screenshot_dirs = sorted(dirs) or None
    return remote


def list_screenshots(device):
    """Look in the known folders; full scan if none is known or they come back empty."""
    if screenshot_dirs:
        storages(device)  # liveness check
        remote = {}
        for storage, folder in screenshot_dirs:
            remote.update(shots_in(children(device, storage, folder)))
        if remote:
            return remote
        log("known dirs empty, falling back to full scan")
    return full_scan(device)


def sync(device, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    remote = list_screenshots(device)
    for name, (item_id, size) in remote.items():
        target = dest / name
        if target.exists() and target.stat().st_size == size:
            continue
        tmp = target.with_suffix(".part")
        if lib.LIBMTP_Get_File_To_File(device, item_id, str(tmp).encode(), None, None) != 0:
            tmp.unlink(missing_ok=True)
            lib.LIBMTP_Clear_Errorstack(device)
            storages(device)  # raises Disconnected if the device is gone
            return {"error": "download_failed"}
        tmp.replace(target)
    for stale in dest.glob("*.png"):
        if stale.name not in remote:
            stale.unlink()
    return {"names": sorted(remote)}


def delete(device, names):
    """Permanently delete screenshots from the device (the Kindle has no trash)."""
    remote = list_screenshots(device)
    deleted, failed = [], []
    for name in names:
        if name not in remote:
            deleted.append(name)  # already gone
        elif lib.LIBMTP_Delete_Object(device, remote[name][0]) == 0:
            deleted.append(name)
        else:
            lib.LIBMTP_Clear_Errorstack(device)
            failed.append(name)
    return {"deleted": deleted, "failed": failed}


def main():
    lib.LIBMTP_Init()
    device, err = open_device()
    if err:
        reply(error=err)
        return
    reply(ready=True)
    try:
        for line in sys.stdin:
            cmd = json.loads(line)
            try:
                if cmd.get("cmd") == "sync":
                    reply(**sync(device, Path(cmd["dest"])))
                elif cmd.get("cmd") == "delete":
                    reply(**delete(device, cmd["names"]))
            except Disconnected:
                reply(error="disconnected")
                return
    finally:
        lib.LIBMTP_Release_Device(device)


if __name__ == "__main__":
    main()
