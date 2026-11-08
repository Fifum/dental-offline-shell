"""«Отчёт для разработчика»: what the developer needs to adapt the app to the real Dentist Plus API,
without any patient data, passwords or keys.

The clinic presses one button, gets a .json file and sends it over a messenger. The file keeps the
*shape* of API answers (field names, value types, date formats, enum-like codes) and replaces every
value that could identify a person with a placeholder such as «<текст, 13 симв.>» or «<телефон>».
"""
from __future__ import annotations

import platform
import re
from collections import deque
from datetime import datetime

import config

# Strings kept as is: short machine codes such as "completed" or "cash" (status values are needed for
# the write map). Anything with Cyrillic, spaces, digits or capitals is masked.
_CODE = re.compile(r"^[a-z][a-z0-9_\-]{0,23}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$")
_DATE_RU = re.compile(r"^\d{2}\.\d{2}\.\d{4}( \d{2}:\d{2}(:\d{2})?)?$")
_TIME = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
_PHONE = re.compile(r"^\+?[\d\s\-()]{7,20}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL = re.compile(r"^https?://", re.I)

# Free-text scrubbing for log lines and error messages.
_S_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_S_PHONE = re.compile(r"\+?\d[\d\s\-()]{8,}\d")
_S_LONGNUM = re.compile(r"\d{5,}")
_S_RU_WORDS = re.compile(r"[А-ЯЁ][а-яё]+(?:[ \-][А-ЯЁ][а-яё]+){1,2}")  # «Иванова Мария Петровна»
_S_QUOTED = re.compile(r"(['\"«])([^'\"»\n]{1,80})(['\"»])")
_S_BEARER = re.compile(r"(?i)\bbearer\s+[^\s\"',}]+")
_S_JWT = re.compile(r"\beyJ[\w-]*\.[\w-]+\.[\w-]+")
_S_TOKEN = re.compile(r"(?i)(bearer|token|pass(word)?|key|secret|authorization)([\"'=:\s]+)([^\s\"',}]+)")

LIST_SAMPLE = 2
LOG_LINES = 200


def _date_shape(s: str) -> str:
    out = re.sub(r"\d", "9", s)
    return f"<дата {out}>"


def mask_value(v, key: str = ""):
    """Recursively replace values with type placeholders, keeping keys and structure."""
    if isinstance(v, dict):
        return {str(k): mask_value(x, str(k)) for k, x in v.items()}
    if isinstance(v, list):
        out = [mask_value(x, key) for x in v[:LIST_SAMPLE]]
        if len(v) > LIST_SAMPLE:
            out.append(f"<ещё {len(v) - LIST_SAMPLE}>")
        return out
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return "<целое>"
    if isinstance(v, float):
        return "<дробное>"
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return ""
        if _DATE.match(s) or _DATE_RU.match(s) or _TIME.match(s):
            return _date_shape(s)
        if _EMAIL.match(s):
            return "<email>"
        if _URL.match(s):
            return "<ссылка>"
        if s.isdigit():
            return f"<цифры, {len(s)}>"
        if _PHONE.match(s) and sum(c.isdigit() for c in s) >= 7:
            return "<телефон>"
        if _CODE.match(s):
            return s
        return f"<текст, {len(s)} симв.>"
    return f"<{type(v).__name__}>"


def scrub_text(text: str) -> str:
    """Remove personal data and secrets from a free-text line (log, error message)."""
    if not text:
        return text
    t = _S_BEARER.sub("Bearer <скрыто>", text)
    t = _S_JWT.sub("<скрыто>", t)
    t = _S_TOKEN.sub(lambda m: m.group(1) + m.group(3) + "<скрыто>", t)
    t = _S_EMAIL.sub("<email>", t)
    t = _S_PHONE.sub("<телефон>", t)
    t = _S_LONGNUM.sub("<число>", t)
    t = _S_RU_WORDS.sub("<ФИО?>", t)
    t = _S_QUOTED.sub(lambda m: m.group(1) + ("<текст>" if re.search(r"[а-яёА-ЯЁ]", m.group(2)) else m.group(2)) + m.group(3), t)
    return t


def _mask_diagnostics(diag: dict) -> dict:
    """sync.diagnostics() output: {endpoint: "OK" | "Ошибка: …" | probe dict | raw answer}.
    Status strings are scrubbed, probe counters and envelope keys kept, API data masked."""
    out = {}
    for path, v in diag.items():
        if isinstance(v, str):
            out[path] = scrub_text(v)
        elif isinstance(v, dict) and "count_on_page" in v:
            out[path] = {"count_on_page": v.get("count_on_page"),
                         "envelope_keys": v.get("envelope_keys"),
                         "sample": mask_value(v.get("sample"))}
        else:
            out[path] = mask_value(v)
    return out


def _settings_summary(s: dict) -> dict:
    return {
        "demo": bool(s.get("demo")),
        "login_set": bool(s.get("login")),
        "password_set": bool(s.get("pass_enc")),
        "base_url": s.get("base_url"),
        "transfer_mode": s.get("transfer_mode", "manual"),
        "interval_min": s.get("interval_min"),
        "days_back": s.get("days_back"),
        "days_forward": s.get("days_forward"),
        "chunk_days": s.get("chunk_days"),
        "per_page": s.get("per_page"),
        "visit_from_param": s.get("visit_from_param"),
        "visit_to_param": s.get("visit_to_param"),
        "sync_all_patients": bool(s.get("sync_all_patients")),
        "patient_extras": [{"key": e.get("key"), "path": e.get("path"), "params": list((e.get("params") or {}).keys())}
                           for e in s.get("patient_extras") or []],
        "write_map_overridden": sorted((s.get("write_map") or {}).keys()),
    }


def _log_tail(n: int = LOG_LINES) -> list[str]:
    try:
        with open(config.LOG_PATH, encoding="utf-8", errors="replace") as f:
            lines = deque(f, maxlen=n)
    except OSError:
        return []
    return [scrub_text(x.rstrip("\n")) for x in lines]


def _push_summary(db) -> dict:
    out = {}
    for table in ("local_visits", "patients"):
        try:
            rows = db.q(f"SELECT COALESCE(push_status,'') st, COUNT(*) n FROM {table} GROUP BY st")
            out[table] = {r["st"] or "none": r["n"] for r in rows}
        except Exception:  # noqa: BLE001
            pass
    return out


def build(db, sync_state: dict, settings: dict | None = None, probe_api: bool = True) -> dict:
    """The whole report as a JSON-ready dict. probe_api=False skips network calls (tests, offline)."""
    s = settings if settings is not None else config.load_settings()
    report = {
        "report": "Отчёт для разработчика",
        "about": "Без данных пациентов, паролей и ключей: только названия полей и типы значений.",
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": config.VERSION,
        "windows": platform.platform(),
        "settings": _settings_summary(s),
        "sync": {
            "online": sync_state.get("online"),
            "running": sync_state.get("running"),
            "last_ok": sync_state.get("last_ok"),
            "last_attempt": sync_state.get("last_attempt"),
            "last_error": scrub_text(sync_state.get("last_error") or ""),
        },
        "counts": db.counts(),
        "pending_transfer": db.pending_count(),
        "push_status": _push_summary(db),
    }
    if s.get("demo"):
        report["api"] = "Включён демо-режим: к Dentist Plus программа не обращается."
    elif not (s.get("login") and s.get("pass_enc")):
        report["api"] = "Логин и пароль API не указаны."
    elif probe_api:
        from sync import diagnostics
        try:
            report["api"] = _mask_diagnostics(diagnostics(s))
        except Exception as e:  # noqa: BLE001
            report["api"] = scrub_text(f"Ошибка: {e.__class__.__name__}: {e}")
    report["log_tail"] = _log_tail()
    return report


def filename() -> str:
    return f"Отчёт для разработчика {datetime.now().strftime('%Y-%m-%d %H-%M')}.json"
