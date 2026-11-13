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

VERSION = "3.8.1"

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

MIN_DAYS_FORWARD = 365   # 3.7.3: visits are booked months ahead — never fewer days ahead than a year
MAX_DAYS_FORWARD = 730

DEFAULT_SETTINGS = {
    "base_url": "https://api2.dentist-plus.com/partner",
    "login": "",
    "pass_enc": "",
    "demo": True,                 # demo data until real credentials are entered
    "interval_min": 5,            # full sync interval while online
    "days_back": 30,              # keep visits this many days in the past
    "days_forward": 365,          # and this many days ahead (3.7.3: at least MIN_DAYS_FORWARD)
    "chunk_days": 7,              # request visits in windows of N days
    "per_page": 100,
    "visit_from_param": "date_from",
    "visit_to_param": "date_to",
    "sync_all_patients": False,   # also download the full patient list (big clinics: slow)
    # per-patient endpoints, {id} is replaced by patient id. Empty: the partner API has no per-patient lists besides
    # visits and payments, which are synced anyway (/diagnoses is the ICD-10 dictionary, it ignores patient_id).
    "patient_extras": [],
    "dp_branch_id": "",          # Dentist Plus branch for patients created here (required by POST /patients); "" = the visit's or the only one
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
def _bak() -> Path:
    return SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".bak")


def _read_json(p: Path):
    try:
        v = json.loads(p.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _stored() -> dict:
    """Saved settings. A file damaged by a power cut → the copy of the previous save; both damaged → never the demo
    defaults (the demo wipes the database): demo off and `settings_damaged`, the director enters the settings again."""
    bak = _bak()
    if not SETTINGS_PATH.exists() and not bak.exists():
        return {}
    for p in (SETTINGS_PATH, bak):
        v = _read_json(p)
        if v is not None:
            if p is bak:
                _warn_once("settings.json is damaged: the previous copy (settings.json.bak) is used")
            return v
    _warn_once("settings.json and its copy are damaged: demo mode stays off")
    return {"demo": False, "settings_damaged": True}


_warned: set = set()


def _warn_once(text):
    if text not in _warned:
        _warned.add(text)
        import logging
        logging.getLogger("config").error(text)


def _write_durable(p: Path, data: bytes):
    with open(p, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def load_settings() -> dict:
    with _lock:
        s = dict(DEFAULT_SETTINGS)
        s.update(_stored())
        return _migrate(s)


def _migrate(s: dict) -> dict:
    """Settings saved by older versions: the «Диагнозы» extra asked the ICD-10 dictionary /diagnoses once per
    patient (it has no patient filter) — dropped."""
    try:  # 3.7.3: older versions kept 30 days ahead — a visit booked in two months was not seen
        s["days_forward"] = min(MAX_DAYS_FORWARD, max(MIN_DAYS_FORWARD, int(s.get("days_forward") or 0)))
    except (TypeError, ValueError):
        s["days_forward"] = MIN_DAYS_FORWARD
    ex = s.get("patient_extras")
    if isinstance(ex, list):
        s["patient_extras"] = [e for e in ex if not (isinstance(e, dict) and str(e.get("path", "")).strip("/") == "diagnoses")]
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
        cur.update(_stored())
        cur.update(new)
        if "settings_damaged" not in new:
            cur.pop("settings_damaged", None)
        # К1: the new file is on the disk before it replaces the old one; the last good file stays as .bak
        if _read_json(SETTINGS_PATH) is not None:
            _write_durable(_bak(), SETTINGS_PATH.read_bytes())
        tmp = SETTINGS_PATH.with_suffix(".tmp")
        _write_durable(tmp, json.dumps(cur, ensure_ascii=False, indent=2).encode("utf-8"))
        os.replace(tmp, SETTINGS_PATH)
        return _migrate(cur)
