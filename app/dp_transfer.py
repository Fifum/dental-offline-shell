"""3.3 «Без двойного ввода» — stage 1 of the add-on over Dentist Plus.

The API of Dentist Plus does not take medical records, so a record made here (by hand, a visit template, dictation
or the AI) is typed into Dentist Plus by the doctor. This module makes that quick and keeps it from being forgotten:

- the text of a record split into the sections of the Dentist Plus record form, in its order: one copy for the whole
  record or one per section. Sections, their order and names are a clinic setting (`dp_settings`, synced between the
  clinic's computers like the rest of the data, see replica.TABLES);
- the mark «перенесено в Dentist Plus» on a record (records.transferred / transferred_at / transferred_by) — the row
  travels to the other computers by itself; the mark goes to the action journal (auth.AUDITED);
- the list «Не перенесено» by day and doctor with a counter for the last N days (30 by default), the reminder at the
  end of the day (20:00 by default) and a line in the day report;
- «Сверка»: what is in the program against what is marked transferred, and finished Dentist Plus visits that have no
  record here (from the visits already synced from Dentist Plus). Payments of Dentist Plus are not in its API:
  the screen says «нет данных из Dentist Plus».

Who sees what (scope): the director and staff with «Отчёты» or «Перенос в Dentist Plus» — everything; a doctor —
only the records of the doctor his account is linked to (users.doctor_id). Everything works offline.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

import reports

NO_DP = "нет данных из Dentist Plus"
SECTION_TITLES = {
    "complaints": "Жалобы", "anamnesis": "Анамнез", "objective": "Объективно", "diagnoses": "Диагноз (МКБ-10)",
    "treatment": "Лечение", "recommendations": "Рекомендации", "rx": "Назначения", "next_visit": "Следующий визит",
}
DEFAULT_ON = ("complaints", "anamnesis", "objective", "diagnoses", "treatment", "recommendations")
DEFAULTS = {"sections": [{"key": k, "title": t, "on": k in DEFAULT_ON} for k, t in SECTION_TITLES.items()],
            "auto_mark": False, "remind": True, "remind_time": "20:00", "days": 30}
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DAY = "COALESCE(NULLIF(r.date,''), substr(r.created_at,1,10))"
DONE_KINDS = ("done", "came")
MAX_LIST = 500


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ settings --
def _norm_sections(raw) -> list[dict]:
    """Known sections in the saved order; unknown keys and doubles dropped; sections missing from a saved list are
    added at the end switched off (or as by default when nothing was saved)."""
    out, seen = [], set()
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict) or s.get("key") not in SECTION_TITLES or s["key"] in seen:
            continue
        seen.add(s["key"])
        title = " ".join(str(s.get("title") or "").split())[:60] or SECTION_TITLES[s["key"]]
        out.append({"key": s["key"], "title": title, "on": bool(s.get("on", True))})
    saved = bool(out)
    for k, t in SECTION_TITLES.items():
        if k not in seen:
            out.append({"key": k, "title": t, "on": (k in DEFAULT_ON) if not saved else False})
    return out


def settings(db) -> dict:
    saved = {}
    try:
        for r in db.q("SELECT k, v FROM dp_settings"):
            try:
                saved[r["k"]] = json.loads(r["v"])
            except (TypeError, ValueError):
                pass
    except Exception:  # noqa: BLE001 — a bare database without the table
        pass
    s = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    s["sections"] = _norm_sections(saved.get("sections"))
    s["auto_mark"], s["remind"] = bool(s["auto_mark"]), bool(s["remind"])
    if not _TIME.match(str(s["remind_time"])):
        s["remind_time"] = DEFAULTS["remind_time"]
    try:
        s["days"] = min(365, max(1, int(s["days"])))
    except (TypeError, ValueError):
        s["days"] = DEFAULTS["days"]
    s["titles"] = dict(SECTION_TITLES)  # the built-in names, for «вернуть название»
    return s


def clean_settings(f: dict) -> dict:
    out = {}
    if "sections" in f:
        secs = _norm_sections(f["sections"])
        if not any(s["on"] for s in secs):
            raise ValueError("Оставьте хотя бы один раздел для переноса")
        out["sections"] = secs
    for k in ("auto_mark", "remind"):
        if k in f:
            out[k] = bool(f[k])
    if "remind_time" in f:
        t = str(f["remind_time"] or "").strip()
        if len(t) == 4 and t[1] == ":":
            t = "0" + t
        if not _TIME.match(t):
            raise ValueError("Время напоминания — в виде ЧЧ:ММ, например 20:00")
        out["remind_time"] = t
    if "days" in f:
        try:
            d = int(f["days"])
        except (TypeError, ValueError):
            raise ValueError("Сколько дней показывать — целое число") from None
        if not 1 <= d <= 365:
            raise ValueError("Сколько дней показывать — от 1 до 365")
        out["days"] = d
    return out


def save_settings(db, f: dict) -> dict:
    upd = clean_settings(f if isinstance(f, dict) else {})
    with db.tx() as c:
        for k, v in upd.items():
            c.execute("INSERT INTO dp_settings(k, v, updated_at) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, "
                      "updated_at=excluded.updated_at", (k, json.dumps(v, ensure_ascii=False), _now()))
    return settings(db)


# ---------------------------------------------------------------------- text --
def _s(v) -> str:
    """A short one-line value (a code, a name, a tooth): spaces and line breaks squeezed."""
    return " ".join(str(v or "").split())


def _diag_text(d) -> str:
    if not isinstance(d, dict):
        return _s(d)
    line = " ".join(x for x in (_s(d.get("code")), _s(d.get("title"))) if x)
    tooth = _s(d.get("tooth"))
    if tooth and line:
        line += f" (зуб {tooth})"
    return line


def _rx_text(r) -> str:
    if not isinstance(r, dict):
        return _s(r)
    head = " ".join(x for x in (_s(r.get("name")), _s(r.get("dose"))) if x)
    tail = ", ".join(x for x in (_s(r.get("how")), _s(r.get("days"))) if x)
    return f"{head} — {tail}" if head and tail else head or tail


def section_text(key: str, data: dict) -> str:
    v = data.get(key)
    if key == "diagnoses":
        lines = [x for x in (_diag_text(d) for d in (v if isinstance(v, list) else [])) if x]
        if not lines and _s(data.get("diagnosis_text")):
            lines = [_s(data["diagnosis_text"])]
        return "\n".join(lines)
    if key == "rx":
        return "\n".join(x for x in (_rx_text(r) for r in (v if isinstance(v, list) else [])) if x)
    return str(v or "").strip()


def build(data: dict, s: dict) -> dict:
    """{'text': the whole record with section titles, 'sections': [{key, title, text}] (switched-on sections in the
    clinic's order), 'empty'}. One section copied alone is its text without the title — it goes into one field."""
    data = data if isinstance(data, dict) else {}
    secs = [{"key": x["key"], "title": x["title"], "text": section_text(x["key"], data)} for x in s["sections"] if x["on"]]
    text = "\n\n".join(f"{x['title']}:\n{x['text']}" for x in secs if x["text"])
    return {"text": text, "sections": secs, "empty": not text}


def from_form(f: dict) -> dict:
    """An unsaved form (the record editor, a dictation or AI result) → the data of a record."""
    f = f if isinstance(f, dict) else {}
    data = dict(f["fields"]) if isinstance(f.get("fields"), dict) else {}
    for k in (*SECTION_TITLES, "diagnosis_text"):
        if k in f and k not in data:
            data[k] = f[k]
    return data


# -------------------------------------------------------------------- scope --
def can_see(scope, doctor_id) -> bool:
    return bool(scope.get("all")) or (bool(scope.get("doctor_id")) and str(doctor_id or "") == str(scope["doctor_id"]))


def _scope_sql(scope, alias="r"):
    if scope.get("all"):
        return "", []
    if scope.get("doctor_id"):
        return f" AND {alias}.doctor_id=?", [str(scope["doctor_id"])]
    return " AND 0", []


def _period(date_from, date_to, days):
    today = date.today()
    try:
        b = date.fromisoformat(str(date_to)[:10]) if date_to else today
        a = date.fromisoformat(str(date_from)[:10]) if date_from else b - timedelta(days=max(1, int(days)) - 1)
    except ValueError:
        raise ValueError("Неверная дата периода") from None
    if b < a:
        a, b = b, a
    if (b - a).days > 400:
        raise ValueError("Слишком длинный период — не больше 400 дней")
    return a, b


# --------------------------------------------------------------------- marks --
def mark(db, ids, done=True, who="") -> int:
    """Mark records transferred (or take the mark off). A record already marked keeps who and when marked it first."""
    ids = [str(i) for i in (ids if isinstance(ids, (list, tuple)) else [ids]) if i]
    n = 0
    with db.tx() as c:
        for i in ids:
            if done:
                cur = c.execute("""UPDATE records SET transferred=1, transferred_at=?, transferred_by=?
                                   WHERE id=? AND COALESCE(transferred,0)=0""", (_now(), who or None, i))
            else:
                cur = c.execute("""UPDATE records SET transferred=0, transferred_at=NULL, transferred_by=NULL
                                   WHERE id=? AND COALESCE(transferred,0)=1""", (i,))
            n += cur.rowcount
    return n


def copied(db, rid, who="", auto=True, s=None) -> dict:
    """The record was copied for Dentist Plus: remember who and when; with «auto_mark» on (and `auto`) it is marked
    transferred right away."""
    s = s or settings(db)
    r = db.one("SELECT id, transferred FROM records WHERE id=?", (str(rid),))
    if not r:
        raise ValueError("Запись медкарты не найдена")
    with db.tx() as c:
        c.execute("UPDATE records SET dp_copied_at=?, dp_copied_by=? WHERE id=?", (_now(), who or None, r["id"]))
    marked = bool(auto and s["auto_mark"] and not r["transferred"] and mark(db, [r["id"]], True, who))
    return {"marked": marked, "auto_mark": s["auto_mark"]}


# --------------------------------------------------------------- the list --
def count(db, scope, s=None, today=None) -> int:
    """Records not transferred in the last `days` days (the counter on the menu and in the list)."""
    s = s or settings(db)
    where, args = _scope_sql(scope)
    today = today or date.today()
    since = (today - timedelta(days=s["days"] - 1)).isoformat()
    return db.one(f"SELECT COUNT(*) AS n FROM records r WHERE COALESCE(r.transferred,0)=0 AND {DAY} >= ? AND {DAY} <= ?{where}",
                  [since, today.isoformat(), *args])["n"]


def remind(db, doctor_id, now=None, s=None) -> int:
    """Today's records of the doctor not transferred — once the reminder time has come (0 before it or when off)."""
    s = s or settings(db)
    now = now or datetime.now()
    if not s["remind"] or not doctor_id or now.strftime("%H:%M") < s["remind_time"]:
        return 0
    return db.one(f"SELECT COUNT(*) AS n FROM records r WHERE COALESCE(r.transferred,0)=0 AND {DAY}=? AND r.doctor_id=?",
                  (now.date().isoformat(), str(doctor_id)))["n"]


def status(db, scope, user=None, now=None) -> dict:
    s = settings(db)
    out = {"pending": count(db, scope, s, (now or datetime.now()).date()), "days": s["days"], "remind_time": s["remind_time"],
           "remind_on": s["remind"], "remind": 0}
    did = (user or {}).get("doctor_id")
    if did:
        out["remind"] = remind(db, did, now, s)
    return out


def _brief(data) -> str:
    dg = "; ".join(x for x in (_diag_text(d) for d in (data.get("diagnoses") or [] if isinstance(data.get("diagnoses"), list) else [])) if x)
    return dg or _s(data.get("treatment"))[:120] or _s(data.get("complaints"))[:120]


def _item(r, s) -> dict:
    try:
        data = json.loads(r["data"] or "{}")
    except (TypeError, ValueError):
        data = {}
    b = build(data, s)
    return {"id": r["id"], "patient_id": r["patient_id"], "patient_name": r.get("patient_name") or "", "visit_id": r["visit_id"],
            "doctor_id": r["doctor_id"], "doctor_name": r.get("doctor_name") or "", "date": r["day"],
            "brief": _brief(data), "sections": sum(1 for x in b["sections"] if x["text"]), "empty": b["empty"],
            "transferred": int(r["transferred"] or 0), "transferred_at": r["transferred_at"], "transferred_by": r["transferred_by"] or "",
            "copied_at": r["dp_copied_at"], "copied_by": r["dp_copied_by"] or "", "updated_at": r["updated_at"]}


def pending(db, scope, date_from=None, date_to=None, doctor_id=None, show_done=False) -> dict:
    """Records of a period (the last `days` days by default) not transferred, by day and doctor."""
    s = settings(db)
    a, b = _period(date_from, date_to, s["days"])
    where, args = _scope_sql(scope)
    if doctor_id and scope.get("all"):
        where += " AND r.doctor_id=?"
        args.append(str(doctor_id))
    done = "" if show_done else " AND COALESCE(r.transferred,0)=0"
    rows = db.q(f"""SELECT r.*, {DAY} AS day, p.name AS patient_name, d.name AS doctor_name FROM records r
                    LEFT JOIN patients p ON p.id=r.patient_id LEFT JOIN doctors d ON d.id=r.doctor_id
                    WHERE {DAY} >= ? AND {DAY} <= ?{done}{where}
                    ORDER BY day DESC, COALESCE(d.name, ''), COALESCE(p.name, ''), r.created_at""",
                [a.isoformat(), b.isoformat(), *args])
    items = [_item(r, s) for r in rows]
    days, by_doc = [], {}
    for it in items:
        if not days or days[-1]["day"] != it["date"]:
            days.append({"day": it["date"], "doctors": []})
        docs = days[-1]["doctors"]
        if not docs or docs[-1]["doctor_id"] != it["doctor_id"]:
            docs.append({"doctor_id": it["doctor_id"], "doctor_name": it["doctor_name"] or "Врач не указан", "items": []})
        docs[-1]["items"].append(it)
        if not it["transferred"]:
            k = it["doctor_id"] or ""
            x = by_doc.setdefault(k, {"doctor_id": it["doctor_id"], "doctor_name": it["doctor_name"] or "Врач не указан", "n": 0})
            x["n"] += 1
    return {"from": a.isoformat(), "to": b.isoformat(), "days_back": s["days"], "items": items[:MAX_LIST], "groups": days,
            "left": sum(1 for x in items if not x["transferred"]), "count": count(db, scope, s),
            "by_doctor": sorted(by_doc.values(), key=lambda x: (-x["n"], x["doctor_name"])), "all": bool(scope.get("all")),
            "remind_time": s["remind_time"], "remind": s["remind"]}


# --------------------------------------------------------------- day report --
def day_summary(db, day, s=None) -> dict:
    s = s or settings(db)
    rows = db.q(f"""SELECT r.doctor_id, d.name AS doctor_name, COALESCE(r.transferred,0) AS t FROM records r
                    LEFT JOIN doctors d ON d.id=r.doctor_id WHERE {DAY}=?""", (str(day)[:10],))
    by = {}
    for r in rows:
        if not r["t"]:
            k = r["doctor_name"] or "врач не указан"
            by[k] = by.get(k, 0) + 1
    try:
        today = date.fromisoformat(str(day)[:10])
    except ValueError:
        today = date.today()
    return {"day": str(day)[:10], "total": len(rows), "pending": sum(by.values()),
            "by_doctor": [{"doctor_name": k, "n": v} for k, v in sorted(by.items(), key=lambda x: (-x[1], x[0]))],
            "window": count(db, {"all": True}, s, today), "days": s["days"]}


def report_lines(sm) -> list[str]:
    """Lines for the day report (empty when there were no records and nothing is left to transfer)."""
    if not sm or (not sm["total"] and not sm["window"]):
        return []
    if not sm["pending"]:
        head = f"Медкарта: записей за день — {sm['total']}, все перенесены в Dentist Plus" if sm["total"] else \
            "Медкарта: за день записей нет"
    else:
        head = f"Медкарта: записей за день — {sm['total']}, не перенесено в Dentist Plus — {sm['pending']}"
    lines = [head] + [f"  {x['doctor_name']} — {x['n']}" for x in sm["by_doctor"]]
    if sm["window"] > sm["pending"]:
        lines.append(f"  За {sm['days']} дн. не перенесено всего: {sm['window']}")
    return lines


# --------------------------------------------------------------- reconciliation --
def _dp_visits(db, a, b, doctor_id=None):
    """Dentist Plus visits of the period, as synced (the mirror + the archive of visits that left it)."""
    end = (b + timedelta(days=1)).isoformat()
    dw, dargs = (" AND v.doctor_id=?", [str(doctor_id)]) if doctor_id else ("", [])
    hw = dw.replace("v.", "h.")
    return db.q(f"""SELECT v.id, v.patient_id, v.doctor_id, v.start, v.status FROM visits v WHERE v.start >= ? AND v.start < ?{dw}
                    UNION ALL
                    SELECT h.id, h.patient_id, h.doctor_id, h.start, h.status FROM visits_archive h
                    WHERE h.id NOT IN (SELECT id FROM visits) AND h.start >= ? AND h.start < ?{hw}""",
                [a.isoformat(), end, *dargs, a.isoformat(), end, *dargs])


def _dp_span(db):
    r = db.one("""SELECT MIN(s) AS a, MAX(s) AS b FROM (SELECT start AS s FROM visits UNION ALL SELECT start AS s FROM visits_archive)""")
    return (str(r["a"])[:10], str(r["b"])[:10]) if r and r["a"] else None


def _row(key, title, dd, marked, dp=NO_DP, note="", total=None):
    row = {"key": key, "title": title, "dd": dd, "marked": marked, "left": max(0, dd - marked), "dp": dp, "note": note}
    if total is not None:
        row["sum"] = round(total, 2)
    return row


def reconcile(db, date_from=None, date_to=None, doctor_id=None) -> dict:
    """What is in the program against what is marked transferred, and the Dentist Plus visits without a record here."""
    s = settings(db)
    a, b = _period(date_from, date_to, s["days"])
    a_s, b_s, end = a.isoformat(), b.isoformat(), (b + timedelta(days=1)).isoformat()
    dw, dargs = (" AND r.doctor_id=?", [str(doctor_id)]) if doctor_id else ("", [])
    recs = db.q(f"""SELECT r.*, {DAY} AS day, p.name AS patient_name, d.name AS doctor_name FROM records r
                    LEFT JOIN patients p ON p.id=r.patient_id LEFT JOIN doctors d ON d.id=r.doctor_id
                    WHERE {DAY} >= ? AND {DAY} <= ?{dw} ORDER BY day DESC, r.created_at""", [a_s, b_s, *dargs])
    rows = [_row("records", "Записи медкарты", len(recs), sum(1 for r in recs if r["transferred"]),
                 note="Медкарту Dentist Plus через API не отдаёт — сверка по отметкам «перенесено»")]

    # finished Dentist Plus visits that have a record here: by the visit (also a visit changed here) or patient + day
    lv = {r["id"]: r for r in db.q("SELECT id, origin_id, remote_id FROM local_visits")}
    ids, pairs = set(), set()
    for r in recs:
        if r["visit_id"]:
            ids.add(str(r["visit_id"]))
            x = lv.get(r["visit_id"])
            if x:
                ids.update(str(v) for v in (x["origin_id"], x["remote_id"]) if v)
        pairs.add((str(r["patient_id"] or ""), r["day"]))
    span = _dp_span(db)
    today = date.today().isoformat()
    without, dp_done = [], 0
    if span:
        names = {p["id"]: p["name"] for p in db.q("SELECT id, name FROM patients")}
        docs = {d["id"]: d["name"] for d in db.q("SELECT id, name FROM doctors")}
        for v in _dp_visits(db, a, b, doctor_id):
            day = str(v["start"])[:10]
            if day > today or reports.status_kind(v["status"]) not in DONE_KINDS:
                continue
            dp_done += 1
            if str(v["id"]) in ids or (str(v["patient_id"] or ""), day) in pairs:
                continue
            without.append({"visit_id": v["id"], "start": v["start"], "status": v["status"], "patient_id": v["patient_id"],
                            "patient_name": names.get(v["patient_id"]) or "", "doctor_id": v["doctor_id"],
                            "doctor_name": docs.get(v["doctor_id"]) or ""})
        without.sort(key=lambda x: x["start"], reverse=True)
        covered = {"from": max(a_s, span[0]), "to": min(b_s, span[1])}
        rows.append({"key": "visits", "title": "Завершённые приёмы в Dentist Plus", "dd": dp_done - len(without), "marked": None,
                     "left": len(without), "dp": dp_done,
                     "note": "С записью медкарты в программе / всего по данным Dentist Plus"
                             + ("" if (covered["from"], covered["to"]) == (a_s, b_s) else
                                f". Данные из Dentist Plus есть только за {covered['from']} — {covered['to']}")})
    else:
        covered = None
        rows.append({"key": "visits", "title": "Завершённые приёмы в Dentist Plus", "dd": None, "marked": None, "left": None,
                     "dp": NO_DP, "note": "Приёмы из Dentist Plus ещё не загружены"})

    # money and documents made here: Dentist Plus does not give its invoices and payments through the API
    iw, iargs = (" AND doctor_id=?", [str(doctor_id)]) if doctor_id else ("", [])
    inv = db.q(f"""SELECT total, transferred FROM invoices WHERE COALESCE(kind,'invoice')='invoice'
                   AND created_at >= ? AND created_at < ?{iw}""", [a_s, end, *iargs])
    rows.append(_row("invoices", "Счета", len(inv), sum(1 for x in inv if x["transferred"]), total=sum(x["total"] or 0 for x in inv),
                     note="Счета Dentist Plus в API нет"))
    pw, pargs = (" AND pay.invoice_id IN (SELECT id FROM invoices WHERE doctor_id=?)", [str(doctor_id)]) if doctor_id else ("", [])
    pays = db.q(f"""SELECT pay.amount, pay.transferred FROM payments pay WHERE COALESCE(pay.kind,'') != 'deposit_use'
                    AND pay.created_at >= ? AND pay.created_at < ?{pw}""", [a_s, end, *pargs])
    rows.append(_row("payments", "Оплаты", len(pays), sum(1 for x in pays if x["transferred"]), total=sum(x["amount"] or 0 for x in pays),
                     note="Оплаты Dentist Plus в API нет — сверьте с кассой Dentist Plus вручную"))
    if not doctor_id:
        docs_ = db.q("SELECT transferred FROM documents WHERE created_at >= ? AND created_at < ?", [a_s, end])
        rows.append(_row("documents", "Документы", len(docs_), sum(1 for x in docs_ if x["transferred"]),
                         note="Официальные документы печатаются из Dentist Plus"))
    left = [_item(r, s) for r in recs if not r["transferred"]]
    return {"from": a_s, "to": b_s, "no_dp": NO_DP, "dp_span": {"from": span[0], "to": span[1]} if span else None,
            "covered": covered, "rows": rows, "not_transferred": left[:MAX_LIST], "not_transferred_total": len(left),
            "visits_without_record": without[:MAX_LIST], "visits_without_record_total": len(without),
            "payments_dp": NO_DP}
