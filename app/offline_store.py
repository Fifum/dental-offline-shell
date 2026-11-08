"""Read-only copy of the schedule and patient cards on a client computer, for when the server is down.

Each employee's copy is cut to their rights on the server, encrypted with Windows DPAPI (readable only
under this Windows account) and opened with the same login and password as the program. Copies older
than KEEP_DAYS are deleted.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import config
from auth import check_password, hash_password

KEEP_DAYS = 14
MAX_FAILS = 5


def _dir() -> Path:
    p = config.data_dir() / "offline"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _key(login) -> str:
    return hashlib.sha256(str(login or "").strip().lower().encode()).hexdigest()[:24]


def _read(path: Path):
    try:
        return json.loads(config.unprotect(path.read_text(encoding="ascii")) or "null")
    except (OSError, ValueError):
        return None


def _write(path: Path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(config.protect(json.dumps(obj, ensure_ascii=False)), encoding="ascii")
    tmp.replace(path)


def remember_login(login, password):
    """Called right after a successful sign-in on the server: lets this person open their copy offline."""
    login = str(login or "").strip().lower()
    if not login or not password:
        return False
    users = _read(_dir() / "users.bin") or {}
    users[_key(login)] = {"login": login, "hash": hash_password(str(password)), "at": time.time()}
    _write(_dir() / "users.bin", users)
    return True


def save(login, snapshot_json: str):
    snap = json.loads(snapshot_json)
    if not isinstance(snap, dict) or "visits" not in snap:
        raise ValueError("Неверная копия")
    snap["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(_dir() / f"{_key(login)}.bin", snap)
    return {"ok": True, "visits": len(snap["visits"]), "patients": len(snap.get("patients") or {})}


def cleanup():
    now = time.time()
    for f in _dir().glob("*.bin"):
        if f.name != "users.bin" and now - f.stat().st_mtime > KEEP_DAYS * 86400:
            f.unlink(missing_ok=True)


def available():
    """Who has a copy on this computer and how fresh it is (no patient data)."""
    cleanup()
    users = _read(_dir() / "users.bin") or {}
    out = []
    for k, u in users.items():
        f = _dir() / f"{k}.bin"
        if f.exists():
            out.append({"login": u["login"], "saved_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))})
    return out


_fails: dict[str, list] = {}


def open_copy(login, password):
    login = str(login or "").strip().lower()
    recent = [t for t in _fails.get(login, []) if time.time() - t < 60]
    if len(recent) >= MAX_FAILS:
        raise ValueError("Слишком много неудачных попыток. Подождите минуту.")
    users = _read(_dir() / "users.bin") or {}
    u = users.get(_key(login))
    if not u or not check_password(str(password or ""), u["hash"]):
        _fails.setdefault(login, []).append(time.time())
        raise ValueError("Неверный логин или пароль, или на этом компьютере нет вашей сохранённой копии")
    snap = _read(_dir() / f"{_key(login)}.bin")
    if not snap:
        raise ValueError("Сохранённой копии нет: войдите в программу хотя бы раз, пока сервер доступен")
    return snap


def forget(login):
    login = str(login or "").strip().lower()
    users = _read(_dir() / "users.bin") or {}
    users.pop(_key(login), None)
    _write(_dir() / "users.bin", users)
    (_dir() / f"{_key(login)}.bin").unlink(missing_ok=True)
    return True
