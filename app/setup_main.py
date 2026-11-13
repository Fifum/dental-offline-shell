"""The exe sent to the clinic: installs (or updates) the program folder for this user and starts it.

Built by build.ps1 as a single small-code exe that carries app.zip (the program folder). Running it:
closes an open older version, unpacks the new one into %LOCALAPPDATA%\\Programs\\<app>, makes shortcuts and
starts the installed program with the same arguments. With --no-install it unpacks into a temporary
folder and runs from there without touching the installed copy (used for checks).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import config
import installer


def _payload() -> str:
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "app.zip")


def main():
    args = sys.argv[1:]
    if "--no-install" in args:
        where = os.path.join(tempfile.gettempdir(), f"{config.APP_NAME}-{config.VERSION}-run")
        exe = os.path.join(where, config.BRAND["exe"] + ".exe")
        if not os.path.exists(exe):
            installer.install_zip(_payload(), where)
        return subprocess.call([exe, *args])  # stay as the parent: killing this process tree stops the program
    target = installer.target_exe()
    name = config.BRAND["name"]
    # М17: wait as long as the open program needs to save and back up; never leave the computer without it
    while not installer.close_running(target):
        if installer.ask_retry(f"{name} ещё закрывается: сохраняет данные и резервную копию.\n\n«Повторить» — подождать ещё.\n"
                               "«Отмена» — не обновлять сейчас: программа останется открытой."):
            continue
        if installer.close_running(target, seconds=1):  # it closed while the question was on the screen
            installer.launch(target, args)
        return 1
    exe, failed = target, None
    try:
        exe = installer.install_zip(_payload(), installer.install_dir())
    except Exception as e:  # noqa: BLE001 — install_zip put the old version back
        failed = e
    if not failed:
        try:
            installer.make_shortcuts(exe)
        except Exception:  # noqa: BLE001
            pass
        try:  # 3.0: the clinic's computers reach each other — one UAC prompt now instead of «Разрешить доступ?» later
            installer.add_firewall_rule(exe)
        except Exception:  # noqa: BLE001
            pass
    if os.path.exists(exe):  # М17: the new version, or the old one when the update failed — always open again
        installer.launch(exe, args)
    if failed:
        # this same file repairs the folder when run again
        installer.message(f"Не удалось установить обновление {name}: {failed}\n\n"
                          + ("Программа открыта в прежней версии. " if os.path.exists(exe) else "")
                          + "Закройте программу и запустите этот файл ещё раз:\n"
                          f"{os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else sys.argv[0])}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
