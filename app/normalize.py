"""Tolerant extraction of common fields from Dentist Plus JSON objects.

The partner API field names are not fully public, so every field is looked up
by a list of candidate names. Raw JSON is always kept, nothing is lost.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone


def get(obj, *paths, default=None):
    """Return the first non-empty value among dotted paths ("patient.id")."""
    if not isinstance(obj, dict):
        return default
    for path in paths:
        cur = obj
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):  # "doctors.0.id"
                cur = cur[int(part)]
            else:
                ok = False
                break
        if ok and cur not in (None, "", [], {}):
            return cur
    return default


def as_id(v):
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("id")
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


_DT_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d", "%d.%m.%Y",
)


def parse_dt(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 10_000_000_000 else v
        return datetime.fromtimestamp(ts)
    s = str(v).strip()
    if re.fullmatch(r"\d{9,13}", s):
        return parse_dt(int(s))
    iso = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(iso)
        if d.tzinfo is not None:
            d = d.astimezone().replace(tzinfo=None)
        return d
    except ValueError:
        pass
    s = s.split(".")[0] if re.match(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\.", s) else s
    for f in _DT_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def fmt(d: datetime | None) -> str | None:
    return d.strftime("%Y-%m-%d %H:%M") if d else None


def person_name(o: dict) -> str:
    full = get(o, "fio", "full_name", "fullname", "fullName", "name_full", "title")
    if isinstance(full, str) and full.strip():
        return " ".join(full.split())
    parts = [
        get(o, "lname", "last_name", "lastname", "lastName", "surname", "family"),
        get(o, "fname", "first_name", "firstname", "firstName", "name"),
        get(o, "mname", "middle_name", "middlename", "middleName", "patronymic", "second_name"),
    ]
    name = " ".join(str(p).strip() for p in parts if p)
    return name or (str(o.get("id")) if o.get("id") is not None else "Без имени")


def phone(o: dict) -> str:
    p = get(o, "phone", "mphone", "mobile", "phone_mobile", "phones.0", "contacts.phone", "tel")
    if isinstance(p, list):
        p = ", ".join(str(x.get("phone", x) if isinstance(x, dict) else x) for x in p)
    if isinstance(p, dict):
        p = p.get("phone") or p.get("number") or ""
    return str(p or "")


def visit_fields(v: dict) -> dict:
    start = parse_dt(get(v, "start", "date_start", "start_at", "started_at", "datetime_start",
                         "time_start", "begin", "from", "datetime"))
    if start is None:
        d = get(v, "date", "visit_date", "day")
        t = get(v, "time", "time_from", "start_time")
        start = parse_dt(f"{d} {t}" if d and t else d)
    elif start.hour == 0 and start.minute == 0 and get(v, "time", "time_from", "start_time"):
        t = parse_dt(f"{start.date()} {get(v, 'time', 'time_from', 'start_time')}")
        start = t or start

    end = parse_dt(get(v, "end", "date_end", "end_at", "finished_at", "datetime_end", "time_end", "finish", "to"))
    if end is not None and start is not None and end.date() == date(1900, 1, 1):
        end = None
    if end is None and start is not None:
        t_end = get(v, "time_to", "end_time")
        if t_end:
            end = parse_dt(f"{start.date()} {t_end}")
    if end is None and start is not None:
        dur = get(v, "duration", "length", "minutes")
        try:
            end = start + timedelta(minutes=int(dur or 30))
        except (TypeError, ValueError):
            end = start + timedelta(minutes=30)
    if end is not None and start is not None and end <= start:
        end = start + timedelta(minutes=30)

    patient = v.get("patient") if isinstance(v.get("patient"), dict) else None
    doctor = v.get("doctor") if isinstance(v.get("doctor"), dict) else None
    if doctor is None and isinstance(v.get("doctors"), list) and v["doctors"]:
        d0 = v["doctors"][0]
        doctor = d0 if isinstance(d0, dict) else {"id": d0}

    status = get(v, "status.title", "status.name", "status_name", "status_title", "status", "state")
    return {
        "id": as_id(v.get("id")),
        "patient_id": as_id(get(v, "patient_id", "patientId", "client_id", "patient.id")),
        "doctor_id": as_id(get(v, "doctor_id", "doctorId", "user_id", "employee_id", "doctor.id", "doctors.0.id", "doctors.0")),
        "branch_id": as_id(get(v, "branch_id", "branchId", "clinic_id", "filial_id", "branch.id")),
        "start": fmt(start),
        "end": fmt(end),
        "status": str(status) if status is not None and not isinstance(status, (dict, list)) else "",
        "title": str(get(v, "title", "description", "comment", "note", "notes", "reason", default="") or ""),
        "patient": patient,
        "doctor": doctor,
    }


def iso_today() -> str:
    return date.today().isoformat()


def utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
