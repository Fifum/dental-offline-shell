"""2.13 (14.4): what is missing in the patient's records for an inspection or the insurance company —
no diagnosis, no X-ray for root canal or extraction, no signed consent, a paid visit without a record.
Simple rules on this computer, no AI: the answers must be exact."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

TOOTH_CODES = ("K02", "K03", "K04", "K08.3", "S02.5", "S03.2")   # diagnoses that need a tooth number
XRAY_CODES = ("K04", "K08.3", "K10.3", "S02.5")                   # root canals, roots, fractures: an X-ray is expected
XRAY_WORDS = re.compile(r"канал|эндодонт|удален|экстракц|имплант|резекц|штифт", re.I)


def _fmt(d):
    d = str(d or "")[:10]
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}" if len(d) == 10 else d


def _day(v):
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _needs_xray(data: dict) -> bool:
    codes = [str(x.get("code") or "") for x in data.get("diagnoses") or []]
    return any(c.startswith(XRAY_CODES) for c in codes) or bool(XRAY_WORDS.search(str(data.get("treatment") or "")))


def check_record(f: dict, xray_days=()) -> list[dict]:
    """The record form before saving. `xray_days` — dates of the patient's X-rays (to check «no X-ray»)."""
    out = []
    dg = [x for x in f.get("diagnoses") or [] if str(x.get("code") or x.get("title") or "").strip()]
    treat = str(f.get("treatment") or "").strip()
    if not dg:
        out.append({"level": "warn", "short": "нет диагноза по МКБ-10", "text": "Не указан диагноз по МКБ-10 — без него запись не примут ни проверка, ни страховая."})
    for x in dg:
        if str(x.get("code") or "").startswith(TOOTH_CODES) and not str(x.get("tooth") or "").strip():
            out.append({"level": "warn", "short": f"{x.get('code')} без зуба", "text": f"Диагноз {x.get('code')} без номера зуба."})
    if not str(f.get("objective") or "").strip():
        out.append({"level": "warn", "short": "нет осмотра", "text": "Не заполнен осмотр («Объективно»)."})
    if not str(f.get("complaints") or "").strip():
        out.append({"level": "info", "short": "нет жалоб", "text": "Не записаны жалобы (если жалоб нет — напишите «Жалоб нет», «Профилактический осмотр»)."})
    if not treat:
        out.append({"level": "info", "short": "нет лечения", "text": "Не записано проведённое лечение."})
    an = re.search(r"анестез[^.;]*", treat, re.I)  # the drug and the amount should be in the same sentence
    if an and not re.search(r"мл\b|карпул|каин\w{0,3}\b|нест\w{0,3}\b|убистезин|\d\s*%", an.group(0), re.I):  # «анестезия» itself has «нест»
        out.append({"level": "info", "short": "анестезия без препарата и дозы", "text": "Анестезия без препарата и количества (например: «Ультракаин DS 1,7 мл»)."})
    for r in f.get("rx") or []:
        if str(r.get("name") or "").strip() and not (str(r.get("dose") or "").strip() and str(r.get("how") or "").strip()):
            out.append({"level": "info", "short": f"«{r['name'][:24]}» без дозы", "text": f"Назначение «{r['name']}» без дозы или способа приёма."})
    day = _day(f.get("date")) or date.today()
    if _needs_xray(f) and not any(d and day - timedelta(days=60) <= d <= day + timedelta(days=7) for d in map(_day, xray_days)):
        out.append({"level": "warn", "short": "нет рентгеновского снимка", "text": "Для лечения каналов, удаления или перелома нужен рентгеновский снимок — в карте его нет. "
                                             "Добавьте снимок во вкладке «Снимки и файлы»."})
    return out


def check_patient(db, local, pid) -> dict:
    """Everything worth fixing in the patient's card: {'items': [...], 'warn': n, 'info': n}."""
    out = []
    recs = local.records(pid)
    xr = [r["taken_at"] or r["created_at"] for r in db.q(
        "SELECT taken_at, created_at FROM patient_files WHERE patient_id=? AND kind='xray'", (pid,))] if _has(db, "patient_files") else []
    for r in recs:
        d = r["data"] or {}
        when = _fmt(r["date"])
        for it in check_record({**d, "date": r["date"]}, xr):
            if it["level"] == "warn" or "назначение" in it["text"].lower():
                out.append({**it, "text": f"Лечение от {when}: {it['text'][0].lower() + it['text'][1:]}", "go": {"record": r["id"]}})
    docs = local.documents(pid)
    tids = {d.get("template_id") for d in docs}
    if recs and "doc_consent_treatment" not in tids:
        out.append({"level": "warn", "text": "Нет информированного согласия на лечение.", "go": {"doc": "doc_consent_treatment"}})
    if (recs or docs) and "doc_consent_pd" not in tids:
        out.append({"level": "warn", "text": "Нет согласия на обработку персональных данных.", "go": {"doc": "doc_consent_pd"}})
    if recs and _has(db, "questionnaires"):
        q = db.one("SELECT MAX(created_at) AS t FROM questionnaires WHERE patient_id=?", (pid,))["t"]
        if not q:
            out.append({"level": "info", "text": "Анкета о здоровье не заполнена (аллергии, болезни, лекарства).", "go": {"anketa": 1}})
        elif str(q)[:10] < (date.today() - timedelta(days=365)).isoformat():
            out.append({"level": "info", "text": f"Анкета о здоровье заполнена {_fmt(q)} — больше года назад, обновите.", "go": {"anketa": 1}})
    rec_visits = {r["visit_id"] for r in recs if r.get("visit_id")}
    rec_days = {str(r["date"] or "")[:10] for r in recs}
    for i in local.invoices(pid):
        if (i.get("kind") or "invoice") != "invoice" or not i.get("items"):
            continue
        day = str(i.get("created_at") or "")[:10]
        if i.get("visit_id") in rec_visits or day in rec_days:
            continue
        ins = bool(i.get("insurer_id"))
        # «info»: the record may be kept in Dentist Plus; an insurance invoice without a diagnosis is a real problem
        out.append({"level": "warn" if ins else "info", "text": f"Счёт от {_fmt(day)} ({_items(i)}) без записи в медкарте программы"
                                             + (" — страховая не примет его без диагноза." if ins else " (если лечение записано в Dentist Plus — всё в порядке)."), "go": {"invoice": i["id"]}})
    warn = sum(1 for x in out if x["level"] == "warn")
    return {"items": out, "warn": warn, "info": len(out) - warn}


def _items(inv):
    items = inv["items"] if isinstance(inv["items"], list) else json.loads(inv["items"] or "[]")
    t = ", ".join(str(x.get("title") or "") for x in items[:2])
    return t + ("…" if len(items) > 2 else "")


def _has(db, table):
    return bool(db.one("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name=?", (table,)))
