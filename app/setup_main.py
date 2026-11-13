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
    if not installer.close_running(target):
        installer.message(f"{config.BRAND['name']} уже открыта.\n\nЗакройте программу (значок в панели задач, правый щелчок → "
                          "Закрыть окно) и запустите этот файл ещё раз — программа обновится.")
        return 1
    try:
        exe = installer.install_zip(_payload(), installer.install_dir())
    except Exception as e:  # noqa: BLE001
        # install_zip put the old version back; this same file repairs the folder when run again
        installer.message(f"Не удалось установить {config.BRAND['name']}: {e}\n\nЗакройте программу и запустите этот файл ещё раз:\n"
                          f"{os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else sys.argv[0])}")
        return 1
    try:
        installer.make_shortcuts(exe)
    except Exception:  # noqa: BLE001
        pass
    try:  # 3.0: the clinic's computers reach each other — one UAC prompt now instead of «Разрешить доступ?» later
        installer.add_firewall_rule(exe)
    except Exception:  # noqa: BLE001
        pass
    installer.launch(exe, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
