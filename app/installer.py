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


def _fsync_tree(path):
    """Unpacked files reach the disk before the switch: a power cut right after it must not leave empty files."""
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                with open(os.path.join(root, f), "r+b") as fh:
                    os.fsync(fh.fileno())
            except OSError:
                pass


def install_zip(zip_path, target_dir) -> str:
    """Unpack the program folder from `zip_path` into `target_dir`, replacing an older version. Returns the exe path.

    New files go to a side folder first; then each old item is moved away and the new one moved in. If any move
    fails, the items already switched are put back, so the folder keeps the old version, never a mix."""
    os.makedirs(target_dir, exist_ok=True)
    stage = os.path.join(target_dir, f".new-{os.getpid()}")
    _rmtree_quiet(stage)
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(stage)
        _fsync_tree(stage)
    except Exception:
        _rmtree_quiet(stage)
        raise
    exe_name = config.BRAND["exe"] + ".exe"
    if not os.path.exists(os.path.join(stage, exe_name)):
        _rmtree_quiet(stage)
        raise RuntimeError("В установщике нет программы")
    for old in os.listdir(target_dir):  # leftovers of an earlier interrupted update
        if old.startswith((".old-", ".new-")) and old != os.path.basename(stage):
            _rmtree_quiet(os.path.join(target_dir, old))
    trash = os.path.join(target_dir, f".old-{os.getpid()}")
    os.makedirs(trash, exist_ok=True)
    done = []  # (name, old item moved to trash, new item moved in)
    try:
        for name in sorted(os.listdir(stage), key=lambda n: n == exe_name):  # the exe last: it starts the rest
            dst = os.path.join(target_dir, name)
            step = [name, False, False]
            done.append(step)
            if os.path.lexists(dst):
                os.replace(dst, os.path.join(trash, name))
                step[1] = True
            os.replace(os.path.join(stage, name), dst)
            step[2] = True
    except Exception:
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
        _rmtree_quiet(stage)
        if restored:
            _rmtree_quiet(trash)
        raise
    _rmtree_quiet(stage)
    _rmtree_quiet(trash)  # an old exe still held by the system is removed on the next update
    return os.path.join(target_dir, exe_name)


# ------------------------------------------------------------- firewall (3.0) --
TCP_PORT, UDP_PORT = 8765, 8766   # the program's server and the «who is there?» broadcasts of the clinic network


def firewall_rule_name() -> str:
    return f"{config.BRAND['name']} — сеть клиники"


def firewall_commands(exe, tcp=TCP_PORT, udp=UDP_PORT) -> list[str]:
    """netsh commands for an inbound rule: the program's ports, Private and domain networks only.
    Without it Windows shows «Разрешить доступ?» on the first start. A «Public» network (a café, a hotel) stays
    closed: there the clinic's server must not be reachable — the clinic's Wi-Fi is made «Private» instead."""
    name = firewall_rule_name()
    base = f'netsh advfirewall firewall add rule name="{name}" dir=in action=allow program="{exe}" profile=private,domain enable=yes'
    return [f'netsh advfirewall firewall delete rule name="{name}"',
            f"{base} protocol=TCP localport={tcp}",
            f"{base} protocol=UDP localport={udp}"]


def firewall_ok(exe) -> bool:
    """The rule is there for this exe (reading rules needs no administrator rights)."""
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={firewall_rule_name()}", "verbose"],
                           capture_output=True, timeout=20, creationflags=NO_WINDOW, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    out = (r.stdout or b"").decode("cp866", "replace").lower()
    if any(("public" in ln or "общ" in ln) for ln in out.splitlines()
           if ln.strip().startswith(("profiles", "профил"))):
        return False  # a rule of an older version also open on «Public» networks: made again without it
    return r.returncode == 0 and os.path.normcase(exe).lower() in out and str(TCP_PORT) in out and str(UDP_PORT) in out


def add_firewall_rule(exe, tcp=TCP_PORT, udp=UDP_PORT, wait=True) -> bool:
    """One UAC prompt («Разрешить этому приложению вносить изменения?») when the rule is missing; nothing otherwise."""
    if os.name != "nt" or firewall_ok(exe):
        return True
    script = " & ".join(firewall_commands(exe, tcp, udp))
    ps = (f"Start-Process cmd -Verb RunAs -WindowStyle Hidden {'-Wait ' if wait else ''}"
          f"-ArgumentList '/c {script.replace(chr(39), chr(39) * 2)}'")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], creationflags=NO_WINDOW,
                           timeout=180, check=False, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def launch(exe, args):
    subprocess.Popen([exe, *args], close_fds=True, creationflags=DETACHED)  # noqa: S603


def is_onedir() -> bool:
    """The program runs from an installed folder (exe + _internal), not from a self-unpacking single exe."""
    meipass = getattr(sys, "_MEIPASS", "")
    return bool(meipass) and os.path.normcase(os.path.dirname(os.path.abspath(meipass))) == \
        os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
