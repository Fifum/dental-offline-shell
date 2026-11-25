"""Closing the open program, putting a new program folder in place of the old one and opening it again.

Shared by the installer (installer.py / setup_main.py) and, since 3.12, the small helper that installs an update
«только изменения» (update_helper.py). Standard library only and no config: the helper gets the window title and the
names from the program that starts it, so the helper stays the very same file from version to version and an
update «только изменения» does not have to carry it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
CLOSE_WAIT_S = 120  # М17: how long to wait for the open program to save, back up and exit


def locked(path) -> bool:
    """True while the program runs from this exe (Windows keeps a running exe open)."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r+b"):
            return False
    except PermissionError:
        return True
    except OSError:
        return False


def ask_close(title):
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, title)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except Exception:  # noqa: BLE001
        pass


def close_running(target, title, seconds=CLOSE_WAIT_S) -> bool:
    """Ask an open copy of the program to close (it saves everything and makes a backup on close) and wait until it
    is gone. М17: the backup of a big database takes a while — wait long, and ask again every few seconds (a window
    that was minimized or still starting may have missed the first request)."""
    if not locked(target):
        return True
    ask_close(title)
    end, again = time.time() + seconds, time.time() + 10
    while time.time() < end:
        time.sleep(0.25)
        if not locked(target):
            time.sleep(0.5)  # let the old process finish writing its last backup and exit
            return True
        if time.time() >= again:
            ask_close(title)
            again = time.time() + 10
    return False


def message(text, title):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:  # noqa: BLE001
        print(text)


def ask_retry(text, title) -> bool:
    """«Повторить» / «Отмена» (no console, no Tk). False where there is no window."""
    try:
        import ctypes
        return ctypes.windll.user32.MessageBoxW(None, text, title, 0x5 | 0x30) == 4  # MB_RETRYCANCEL, IDRETRY
    except Exception:  # noqa: BLE001
        return False


def rmtree_quiet(path):
    shutil.rmtree(path, ignore_errors=True)


def fsync_tree(path):
    """Files reach the disk before the switch: a power cut right after it must not leave empty files."""
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                with open(os.path.join(root, f), "r+b") as fh:
                    os.fsync(fh.fileno())
            except OSError:
                pass


def swap_in(stage, target_dir, exe_name, keep_stage=False) -> str:
    """Put every item of the ready folder `stage` (inside `target_dir`) in place of the old one. Returns the exe path.

    Each old item is moved away and the new one moved in, the exe last (it starts the rest). If any move fails, the
    items already switched are put back, so the folder keeps the old version, never a mix. The error is raised as it
    was, with `restored` set on it: True when the folder is the old version as a whole again (a retry is safe)."""
    if not os.path.exists(os.path.join(stage, exe_name)):
        if not keep_stage:
            rmtree_quiet(stage)
        raise RuntimeError("В установщике нет программы")
    for old in os.listdir(target_dir):  # leftovers of an earlier interrupted update
        if old.startswith((".old-", ".new-")) and old != os.path.basename(stage):
            rmtree_quiet(os.path.join(target_dir, old))
    trash = os.path.join(target_dir, f".old-{os.getpid()}")
    rmtree_quiet(trash)
    os.makedirs(trash, exist_ok=True)
    done = []  # (name, old item moved to trash, new item moved in)
    try:
        for name in sorted(os.listdir(stage), key=lambda n: n == exe_name):
            dst = os.path.join(target_dir, name)
            step = [name, False, False]
            done.append(step)
            if os.path.lexists(dst):
                os.replace(dst, os.path.join(trash, name))
                step[1] = True
            os.replace(os.path.join(stage, name), dst)
            step[2] = True
    except Exception as e:
        restored = True
        for name, moved_old, moved_new in reversed(done):
            dst = os.path.join(target_dir, name)
            try:
                if moved_new:
                    os.replace(dst, os.path.join(stage, name))
                if moved_old:
                    os.replace(os.path.join(trash, name), dst)
            except OSError:
                restored = False
        if not keep_stage:
            rmtree_quiet(stage)
        if restored:
            rmtree_quiet(trash)
        e.restored = restored
        raise
    rmtree_quiet(stage)
    rmtree_quiet(trash)  # an old exe still held by the system is removed on the next update
    return os.path.join(target_dir, exe_name)


def launch(exe, args):
    subprocess.Popen([exe, *args], close_fds=True, creationflags=DETACHED)  # noqa: S603
