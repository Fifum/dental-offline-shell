"""Installing and updating the program for the current user (no admin rights).

Since 2.6.1 the program is installed as a folder (exe + _internal) in %LOCALAPPDATA%\\Programs\\<app>.
Earlier versions were a single exe that unpacked ~300 MB (speech recognition, AI, browser engine) into a
temporary folder on every start, and the antivirus re-checked those files each time — that was most of
the start time. The file sent to the clinic is still one exe: a small installer (setup_main.py) carrying
the program folder in a zip; it unpacks it once, makes shortcuts and starts the installed program.

Only the standard library is used here, so the installer stays small.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import time
import zipfile

import config

DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
NO_WINDOW = 0x08000000


def install_dir() -> str:
    base = os.environ.get("APP_INSTALL_DIR") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", config.APP_NAME)
    return os.path.abspath(base)


def target_exe() -> str:
    return os.path.join(install_dir(), config.BRAND["exe"] + ".exe")


def make_shortcuts(target):
    """Desktop + Start menu shortcuts via PowerShell (no extra dependencies)."""
    desktop = os.environ.get("APP_DESKTOP")
    desk_expr = f"'{desktop}'" if desktop else "[Environment]::GetFolderPath('Desktop')"
    progs_expr = f"'{desktop}'" if desktop else "[Environment]::GetFolderPath('Programs')"
    ps = f"""
$t = '{target}'
$sh = New-Object -ComObject WScript.Shell
foreach ($d in @({desk_expr}, {progs_expr})) {{
  $l = $sh.CreateShortcut((Join-Path $d '{config.BRAND["name"]}.lnk'))
  $l.TargetPath = $t; $l.WorkingDirectory = (Split-Path $t); $l.IconLocation = "$t,0"
  $l.Description = '{config.BRAND["name"]} — расписание и медкарты'; $l.Save()
}}"""
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                   creationflags=NO_WINDOW, timeout=60, check=False)


def message(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, config.APP_TITLE, 0x40)
    except Exception:  # noqa: BLE001
        print(text)


def _locked(path) -> bool:
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


def close_running(target, seconds=15) -> bool:
    """Ask an open copy of the program to close (it saves everything on close) and wait until it is gone."""
    if not _locked(target):
        return True
    try:
        import ctypes
        hwnd = ctypes.windll.user32.FindWindowW(None, config.APP_TITLE)
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    except Exception:  # noqa: BLE001
        pass
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(0.25)
        if not _locked(target):
            time.sleep(0.5)  # let the old process finish writing its last backup and exit
            return True
    return False


def _rmtree_quiet(path):
    shutil.rmtree(path, ignore_errors=True)


def install_zip(zip_path, target_dir) -> str:
    """Unpack the program folder from `zip_path` into `target_dir`, replacing an older version. Returns the exe path.

    New files go to a side folder first; then the old _internal is moved away and the new one moved in, so a
    failure halfway leaves either the old or the new version, never a mix."""
    os.makedirs(target_dir, exist_ok=True)
    stage = os.path.join(target_dir, f".new-{os.getpid()}")
    _rmtree_quiet(stage)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(stage)
    exe_name = config.BRAND["exe"] + ".exe"
    if not os.path.exists(os.path.join(stage, exe_name)):
        _rmtree_quiet(stage)
        raise RuntimeError("В установщике нет программы")
    for old in os.listdir(target_dir):  # leftovers of an earlier interrupted update
        if old.startswith((".old-", ".new-")) and old != os.path.basename(stage):
            _rmtree_quiet(os.path.join(target_dir, old))
    trash = os.path.join(target_dir, f".old-{os.getpid()}")
    os.makedirs(trash, exist_ok=True)
    for name in os.listdir(stage):
        dst = os.path.join(target_dir, name)
        if os.path.exists(dst):
            os.replace(dst, os.path.join(trash, name))
        os.replace(os.path.join(stage, name), dst)
    _rmtree_quiet(stage)
    _rmtree_quiet(trash)  # an old exe still held by the system is removed on the next update
    return os.path.join(target_dir, exe_name)


def launch(exe, args):
    subprocess.Popen([exe, *args], close_fds=True, creationflags=DETACHED)  # noqa: S603


def is_onedir() -> bool:
    """The program runs from an installed folder (exe + _internal), not from a self-unpacking single exe."""
    meipass = getattr(sys, "_MEIPASS", "")
    return bool(meipass) and os.path.normcase(os.path.dirname(os.path.abspath(meipass))) == \
        os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
