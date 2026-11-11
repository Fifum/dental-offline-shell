"""Paths, settings and Windows DPAPI password protection."""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
from pathlib import Path

VERSION = "3.4.0"

# Updates: latest.json signed with Ed25519 (tools/update_sign.py). The secret key stays with the developer outside
# every repository; this public key only checks signatures. The address can also come from brand.json or settings
# (the clinic's build: brand.json → update_url, a GitHub release feed, and update_key that decrypts its installer).
UPDATE_PUBKEY = "623f2977c806d462e1cb10b557927ba529e0fb7cafa6167aa638cb9533b9eeee"
UPDATE_URL = ""

# Clinic branding lives in app/brand.json (not in the public repo). Without it the app is
# a neutral "Dental Desk"; the clinic's build ships its own name, mark and data folder.
DEFAULT_BRAND = {"name": "Dental Desk", "short": "DD", "sub": "offline", "exe": "DentalDesk", "folder": "DentalDesk"}


def _load_brand() -> dict:
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for p in (here / "brand.json", Path(__file__).resolve().parent / "brand.json"):
        try:
            return {**DEFAULT_BRAND, **json.loads(p.read_text(encoding="utf-8"))}
        except (OSError, ValueError):
            continue
    return dict(DEFAULT_BRAND)


BRAND = _load_brand()
APP_NAME = BRAND["folder"]
APP_TITLE = f"{BRAND['name']} — программа клиники"
UPDATE_KEY = str(BRAND.get("update_key") or "")  # hex AES-256 key of this build's updates; never in git


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def resource_dir() -> Path:
    """Folder with bundled resources (ui/) both in dev and inside PyInstaller exe."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


DB_PATH = data_dir() / "clinic.db"
SETTINGS_PATH = data_dir() / "settings.json"
LOG_PATH = data_dir() / "app.log"

DEFAULT_SETTINGS = {
    "base_url": "https://api2.dentist-plus.com/partner",
    "login": "",
    "pass_enc": "",
    "demo": True,                 # demo data until real credentials are entered
    "interval_min": 5,            # full sync interval while online
    "days_back": 30,              # keep visits this many days in the past
    "days_forward": 30,           # and this many days ahead
    "chunk_days": 7,              # request visits in windows of N days
    "per_page": 100,
    "visit_from_param": "date_from",
    "visit_to_param": "date_to",
    "sync_all_patients": False,   # also download the full patient list (big clinics: slow)
    "patient_extras": [           # per-patient endpoints, {id} is replaced by patient id
        {"key": "diagnoses", "title": "Диагнозы", "path": "diagnoses", "params": {"patient_id": "{id}"}},
    ],
    "day_start": 8,
    "day_end": 21,
    "transfer_mode": "manual",   # "manual": staff re-enter via journal; "auto": send to Dentist Plus when online
    "write_map": {},            # overrides for pusher.DEFAULT_WRITE_MAP (endpoints / field names)
    "addon_mode": True,         # 3.2: «Надстройка над Dentist Plus» (addon.py); on for existing installations too
    "addon_docs": "mark",       # 3.2: official document templates in that mode: "mark" (signed) or "hide"
}

_lock = threading.Lock()


# ---------------------------------------------------------------- DPAPI ----
class _BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def protect(text: str) -> str:
    if not text:
        return ""
    if os.name != "nt":
        return "plain:" + base64.b64encode(text.encode()).decode()
    src, out = _blob(text.encode("utf-8")), _BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData failed")
    try:
        return "dpapi:" + base64.b64encode(ctypes.string_at(out.pbData, out.cbData)).decode()
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def unprotect(value: str) -> str:
    if not value:
        return ""
    kind, _, payload = value.partition(":")
    raw = base64.b64decode(payload)
    if kind == "plain":
        return raw.decode()
    src, out = _blob(raw), _BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        return ""
    try:
        return ctypes.string_at(out.pbData, out.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


# ------------------------------------------------------------- settings ----
def load_settings() -> dict:
    with _lock:
        s = dict(DEFAULT_SETTINGS)
        if SETTINGS_PATH.exists():
            try:
                s.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
            except Exception:
                pass
        return s


def node_id() -> str:
    """3.0: this computer in the clinic network (part of every row version made here). Never changes."""
    s = load_settings()
    if not s.get("node_id"):
        import secrets
        s = save_settings({"node_id": s.get("cloud_device") or secrets.token_hex(6)})
    return s["node_id"]


def save_settings(new: dict) -> dict:
    with _lock:
        cur = dict(DEFAULT_SETTINGS)
        if SETTINGS_PATH.exists():
            try:
                cur.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
            except Exception:
                pass
        cur.update(new)
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_PATH)
        return cur
