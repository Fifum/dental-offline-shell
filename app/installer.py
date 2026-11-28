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
import subprocess
import sys
import zipfile

import config
import swap

DETACHED = swap.DETACHED
NO_WINDOW = 0x08000000
CLOSE_WAIT_S = swap.CLOSE_WAIT_S  # М17: how long the installer waits for the open program to save, back up and exit


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
    swap.message(text, config.APP_TITLE)


def _locked(path) -> bool:
    """True while the program runs from this exe (Windows keeps a running exe open)."""
    return swap.locked(path)


def _ask_close():
    swap.ask_close(config.APP_TITLE)


def close_running(target, seconds=CLOSE_WAIT_S) -> bool:
    """Ask an open copy of the program to close (it saves everything and makes a backup on close) and wait until it
    is gone (swap.close_running: М17, wait long and ask again every few seconds)."""
    return swap.close_running(target, config.APP_TITLE, seconds)


def ask_retry(text) -> bool:
    """«Повторить» / «Отмена» (no console, no Tk: the installer stays small). False where there is no window."""
    return swap.ask_retry(text, config.APP_TITLE)


def _rmtree_quiet(path):
    swap.rmtree_quiet(path)


def _fsync_tree(path):
    swap.fsync_tree(path)


def install_zip(zip_path, target_dir) -> str:
    """Unpack the program folder from `zip_path` into `target_dir`, replacing an older version. Returns the exe path.

    New files go to a side folder first; then each old item is moved away and the new one moved in. If any move
    fails, the items already switched are put back, so the folder keeps the old version, never a mix (swap.swap_in)."""
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
    return swap.swap_in(stage, target_dir, config.BRAND["exe"] + ".exe")


# ------------------------------------------------------------- firewall (3.0) --
TCP_PORT, UDP_PORT = 8765, 8766   # the program's server and the «who is there?» broadcasts of the clinic network
HTTPS_PORT = 8767                  # 3.19: the stock app of the phones with the scanner (the clinic's certificate)
TCP_PORTS = f"{TCP_PORT},{HTTPS_PORT}"


def firewall_rule_name() -> str:
    return f"{config.BRAND['name']} — сеть клиники"


def firewall_commands(exe, tcp=TCP_PORTS, udp=UDP_PORT) -> list[str]:
    """netsh commands for an inbound rule: the program's ports, Private and Public networks (and a domain one).
    Without it Windows shows «Разрешить доступ?» on the first start, and on a «Public» network blocks the clinic.
    Public stays open on purpose: many clinic Wi-Fi networks are «Public» in Windows and the computers must see
    each other (3.7.2+: only the main one talks to Dentist Plus). Sign-in attempts are limited atomically instead."""
    name = firewall_rule_name()
    base = f'netsh advfirewall firewall add rule name="{name}" dir=in action=allow program="{exe}" profile=private,public,domain enable=yes'
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
    return (r.returncode == 0 and os.path.normcase(exe).lower() in out and str(TCP_PORT) in out and str(UDP_PORT) in out
            and str(HTTPS_PORT) in out)  # 3.19: an older rule without the phones' https → the program offers to update it


def add_firewall_rule(exe, tcp=TCP_PORTS, udp=UDP_PORT, wait=True) -> bool:
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
    swap.launch(exe, args)


def is_onedir() -> bool:
    """The program runs from an installed folder (exe + _internal), not from a self-unpacking single exe."""
    meipass = getattr(sys, "_MEIPASS", "")
    return bool(meipass) and os.path.normcase(os.path.dirname(os.path.abspath(meipass))) == \
        os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
