"""Double bookings: the same doctor with two different patients at overlapping times.

Laptops work on their own during power cuts, so two people can book the same slot without seeing
each other. This module finds such overlaps — in the local calendar, in the transfer list and right
before an appointment is sent to Dentist Plus.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

CANCELLED = re.compile(r"отмен|cancel|не\s*приш|неявк|no.?show|удал", re.I)
DEFAULT_MIN = 30


def _t(s):
    try:
        return datetime.strptime(str(s)[:16].replace("T", " "), "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def span(v):
    """(start, end) as datetimes; a missing or broken end means a 30-minute appointment."""
    s = _t(v.get("start"))
    if not s:
        return None
    e = _t(v.get("end"))
    if not e or e <= s:
        e = s + timedelta(minutes=DEFAULT_MIN)
    return s, e


def is_cancelled(v):
    return bool(CANCELLED.search(str(v.get("status") or "")))


def clash(a, b):
    """True when a and b are a double booking: same doctor, different patient, times overlap."""
    if not a.get("doctor_id") or str(a.get("doctor_id")) != str(b.get("doctor_id") or ""):
        return False
    if is_cancelled(a) or is_cancelled(b):
        return False
    pa, pb = str(a.get("patient_id") or ""), str(b.get("patient_id") or "")
    if pa and pb and pa == pb:
        return False  # same patient: a duplicate, handled separately
    sa, sb = span(a), span(b)
    if not sa or not sb:
        return False
    return sa[0] < sb[1] and sb[0] < sa[1]


def find(v, others, ignore=()):
    """Appointments in `others` that clash with v (ignoring ids in `ignore` — v itself, its original)."""
    skip = {str(x) for x in ignore if x}
    return [o for o in others if str(o.get("id")) not in skip and str(o.get("origin_id") or "") not in skip and clash(v, o)]


def describe(found, source=""):
    """Short human text: «у врача в 14:00–14:30 уже Иванов И. (Dentist Plus)»."""
    parts = []
    for o in found[:3]:
        s, e = span(o)
        who = o.get("patient_name") or (f"пациент #{o['patient_id']}" if o.get("patient_id") else "другой пациент")
        parts.append(f"{s:%H:%M}–{e:%H:%M} {who}")
    more = f" и ещё {len(found) - 3}" if len(found) > 3 else ""
    return f"у врача в это время уже {'; '.join(parts)}{more}" + (f" ({source})" if source else "")


def mark_day(visits):
    """Adds v['conflict'] = True to every appointment of the day that clashes with another one."""
    by_doc = {}
    for v in visits:
        if v.get("doctor_id"):
            by_doc.setdefault(str(v["doctor_id"]), []).append(v)
    for group in by_doc.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if clash(a, b):
                    a["conflict"] = b["conflict"] = True
    return visits
