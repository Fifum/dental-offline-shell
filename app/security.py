"""Is the disk with the clinic database encrypted (BitLocker / «Шифрование устройства»)?

Patient data lives on laptops that can be lost or stolen; without disk encryption anyone can copy the
database. Windows reports the state of each drive through the shell property
System.Volume.BitLockerProtection, readable without administrator rights.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import config

log = logging.getLogger("security")

# System.Volume.BitLockerProtection values
STATES = {1: "on", 2: "off", 3: "encrypting", 4: "decrypting", 5: "suspended", 6: "locked"}
TEXT = {
    "on": "Диск зашифрован (BitLocker).",
    "encrypting": "Диск сейчас шифруется — дождитесь окончания, компьютер можно использовать.",
    "decrypting": "Шифрование диска отключается — данные останутся без защиты.",
    "suspended": "Шифрование диска приостановлено — защита не работает, включите её снова.",
    "locked": "Диск заблокирован BitLocker.",
    "off": "Диск не зашифрован: если ноутбук украдут, базу пациентов можно будет прочитать.",
    "unknown": "Не удалось узнать, зашифрован ли диск.",
}
_cache = {"at": 0.0, "value": None}
CACHE_SECONDS = 600


def _drive_state(drive: str) -> str:
    """'on' | 'off' | ... | 'unknown' for a drive like 'C:'."""
    if os.name != "nt":
        return "unknown"
    try:
        import pythoncom  # noqa: PLC0415
        import win32com.client  # noqa: PLC0415
        pythoncom.CoInitialize()
        try:
            shell = win32com.client.Dispatch("Shell.Application")
            folder = shell.NameSpace(drive + "\\")
            val = folder.Self.ExtendedProperty("System.Volume.BitLockerProtection") if folder else None
        finally:
            pythoncom.CoUninitialize()
        return STATES.get(int(val), "unknown") if val is not None else "unknown"
    except Exception as e:  # noqa: BLE001
        log.info("BitLocker state unknown for %s: %s", drive, e)
        return "unknown"


def disk_status(force=False) -> dict:
    """State of the drive that holds the database, with a plain-language explanation."""
    if not force and _cache["value"] and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    drive = Path(config.data_dir()).drive or "C:"
    state = _drive_state(drive)
    out = {"drive": drive, "state": state, "ok": state in ("on", "encrypting"), "text": TEXT[state],
           "how": HOW}
    _cache.update(at=time.time(), value=out)
    return out


HOW = [
    "Windows 10/11 Pro: Пуск → введите «BitLocker» → «Управление BitLocker» → «Включить BitLocker» для диска C:. "
    "Ключ восстановления сохраните в учётной записи Microsoft или распечатайте и уберите в сейф — без него данные не вернуть.",
    "Windows 10/11 Домашняя: Параметры → «Конфиденциальность и защита» (в Windows 10: «Обновление и безопасность») → "
    "«Шифрование устройства» → включить. Нужен вход в Windows через учётную запись Microsoft.",
    "Если такого пункта нет, компьютер не поддерживает шифрование без обновления до Windows Pro. Тогда хотя бы "
    "поставьте пароль на вход в Windows и не оставляйте ноутбук без присмотра.",
]
