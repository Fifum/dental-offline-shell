"""Reports: revenue by doctor / service / day, visit statistics, patient debts and advances.

Money comes from the invoices and payments made in this program; visits come from the combined
schedule (Dentist Plus + local changes). Nothing here writes to the database.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from db import DB


def _period(date_from, date_to):
    """Validated ISO dates; `to` is inclusive. Defaults: the current month."""
    today = date.today()
    try:
        a = date.fromisoformat(str(date_from)[:10]) if date_from else today.replace(day=1)
        b = date.fromisoformat(str(date_to)[:10]) if date_to else today
    except ValueError:
        raise ValueError("Неверная дата периода") from None
    if b < a:
        a, b = b, a
    if (b - a).days > 3700:
        raise ValueError("Слишком длинный период")
    return a.isoformat(), (b + timedelta(days=1)).isoformat()


# Same groups as the calendar colours (stClass in app.js), with no-shows split from cancellations.
_KINDS = (("noshow", r"не\s*приш|неявк|no.?show"), ("cancel", r"отмен|cancel|удал"),
          ("done", r"заверш|done|finish|complet|оплач|закрыт"),
          ("came", r"пришел|пришёл|в кресле|при[её]м|arriv|в клиник"))


def status_kind(status) -> str:
    s = str(status or "").lower()
    for kind, rx in _KINDS:
        if re.search(rx, s):
            return kind
    return "planned"


def _mins(start, end):
    try:
        a = int(start[11:13]) * 60 + int(start[14:16])
        b = int(end[11:13]) * 60 + int(end[14:16])
        return max(0, b - a)
    except (TypeError, ValueError, IndexError):
        return 0


class Reports:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------- revenue --
    def revenue(self, date_from=None, date_to=None):
        a, b = _period(date_from, date_to)
        inv = self.db.q("""SELECT i.id, i.doctor_id, i.patient_id, i.items, i.total, substr(i.created_at,1,10) AS day,
                                  d.name AS doctor_name
                           FROM invoices i LEFT JOIN doctors d ON d.id=i.doctor_id
                           WHERE COALESCE(i.kind,'invoice')='invoice' AND i.created_at >= ? AND i.created_at < ?""", (a, b))
        pays = self.db.q("""SELECT pay.amount, pay.method, substr(pay.created_at,1,10) AS day, pay.patient_id,
                                   i.doctor_id, d.name AS doctor_name
                            FROM payments pay LEFT JOIN invoices i ON i.id=pay.invoice_id LEFT JOIN doctors d ON d.id=i.doctor_id
                            WHERE pay.created_at >= ? AND pay.created_at < ?""", (a, b))
        docs, services, days, methods = {}, {}, {}, {}

        def doc(did, name):
            k = did or "_"
            return docs.setdefault(k, {"doctor_id": did, "name": name or ("Без врача" if not did else f"Врач #{did}"),
                                       "billed": 0.0, "paid": 0.0, "invoices": 0, "patients": set()})
        for i in inv:
            d = doc(i["doctor_id"], i["doctor_name"])
            d["billed"] += i["total"] or 0
            d["invoices"] += 1
            d["patients"].add(i["patient_id"])
            days.setdefault(i["day"], {"day": i["day"], "billed": 0.0, "paid": 0.0})["billed"] += i["total"] or 0
            items = json.loads(i["items"] or "[]")
            line_sum = sum(float(it.get("sum") or 0) for it in items) or 1
            k = (i["total"] or 0) / line_sum  # invoice-level discount spread over its lines
            for it in items:
                title = str(it.get("title") or "Без названия").strip()
                s = services.setdefault(title, {"title": title, "code": it.get("code") or "", "qty": 0.0, "sum": 0.0})
                s["qty"] += float(it.get("qty") or 1)
                s["sum"] += float(it.get("sum") or 0) * k
        for p in pays:
            d = doc(p["doctor_id"], p["doctor_name"])
            d["paid"] += p["amount"] or 0
            days.setdefault(p["day"], {"day": p["day"], "billed": 0.0, "paid": 0.0})["paid"] += p["amount"] or 0
            m = p["method"] or "Другое"
            methods[m] = methods.get(m, 0) + (p["amount"] or 0)
        by_doc = sorted(({**d, "patients": len(d["patients"]), "billed": round(d["billed"], 2), "paid": round(d["paid"], 2)}
                         for d in docs.values()), key=lambda x: -x["billed"] - x["paid"])
        by_srv = sorted(({**s, "sum": round(s["sum"], 2), "qty": round(s["qty"], 3)} for s in services.values()),
                        key=lambda x: -x["sum"])
        billed = round(sum(i["total"] or 0 for i in inv), 2)
        paid = round(sum(p["amount"] or 0 for p in pays), 2)
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(),
                "billed": billed, "paid": paid, "invoices": len(inv),
                "avg_check": round(billed / len(inv), 2) if inv else 0,
                "patients": len({i["patient_id"] for i in inv}),
                "by_doctor": by_doc, "by_service": by_srv,
                "by_day": [{**v, "billed": round(v["billed"], 2), "paid": round(v["paid"], 2)} for _, v in sorted(days.items())],
                "by_method": {k: round(v, 2) for k, v in sorted(methods.items(), key=lambda x: -x[1])}}

    # -------------------------------------------------------------- visits --
    def visits(self, date_from=None, date_to=None):
        a, b = _period(date_from, date_to)
        rows = self.db.q(f"""SELECT a.id, a.patient_id, a.doctor_id, a.start, a."end", a.status, d.name AS doctor_name
                             FROM ({DB.ALL_VISITS}) a LEFT JOIN doctors d ON d.id=a.doctor_id
                             WHERE a.start >= ? AND a.start < ?""", (a, b))
        first = {r["patient_id"]: r["f"] for r in self.db.q(
            f"SELECT patient_id, MIN(start) AS f FROM ({DB.ALL_VISITS}) WHERE patient_id IS NOT NULL GROUP BY patient_id")}
        tot = {"total": 0, "done": 0, "came": 0, "planned": 0, "cancel": 0, "noshow": 0, "minutes": 0}
        docs, days = {}, {}
        for r in rows:
            k = status_kind(r["status"])
            m = _mins(r["start"], r["end"]) if k not in ("cancel", "noshow") else 0
            d = docs.setdefault(r["doctor_id"] or "_", {"doctor_id": r["doctor_id"], "name": r["doctor_name"] or "Без врача",
                                                        "total": 0, "done": 0, "came": 0, "planned": 0, "cancel": 0,
                                                        "noshow": 0, "minutes": 0, "patients": set()})
            day = days.setdefault(r["start"][:10], {"day": r["start"][:10], "total": 0, "cancel": 0, "noshow": 0})
            for x in (tot, d):
                x["total"] += 1
                x[k] += 1
                x["minutes"] += m
            day["total"] += 1
            if k in ("cancel", "noshow"):
                day[k] += 1
            d["patients"].add(r["patient_id"])
        new = len({r["patient_id"] for r in rows if r["patient_id"] and a <= (first.get(r["patient_id"]) or "") < b})
        by_doc = sorted(({**d, "patients": len(d["patients"])} for d in docs.values()), key=lambda x: -x["total"])
        lost = tot["cancel"] + tot["noshow"]
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(), **tot,
                "new_patients": new, "patients": len({r["patient_id"] for r in rows if r["patient_id"]}),
                "lost_share": round(lost * 100 / tot["total"], 1) if tot["total"] else 0,
                "by_doctor": by_doc, "by_day": [v for _, v in sorted(days.items())]}

    # --------------------------------------------------- debts and advances --
    def debts(self):
        """Patients who owe money (billed > paid) and who paid in advance (paid > billed)."""
        rows = self.db.q("""
            SELECT p.id, p.name, p.phone, COALESCE(b.billed,0) AS billed, COALESCE(pp.paid,0) AS paid,
                   b.last_invoice, pp.last_payment, json_extract(COALESCE(p.detail,p.data),'$.balance') AS dp_balance,
                   json_extract(COALESCE(p.detail,p.data),'$.debt') AS dp_debt
            FROM patients p
            LEFT JOIN (SELECT patient_id, SUM(total) AS billed, MAX(created_at) AS last_invoice FROM invoices
                       WHERE COALESCE(kind,'invoice')='invoice' AND COALESCE(insurer_id,'')='' GROUP BY patient_id) b ON b.patient_id=p.id
            LEFT JOIN (SELECT pay.patient_id, SUM(pay.amount) AS paid, MAX(pay.created_at) AS last_payment FROM payments pay
                       LEFT JOIN invoices iv ON iv.id=pay.invoice_id WHERE COALESCE(iv.insurer_id,'')=''
                       GROUP BY pay.patient_id) pp ON pp.patient_id=p.id
            WHERE b.billed IS NOT NULL OR pp.paid IS NOT NULL
               OR CAST(json_extract(COALESCE(p.detail,p.data),'$.balance') AS REAL) < 0
               OR CAST(json_extract(COALESCE(p.detail,p.data),'$.debt') AS REAL) > 0""")
        debts, advances = [], []
        for r in rows:
            local = round((r["paid"] or 0) - (r["billed"] or 0), 2)
            dp = 0.0
            try:
                if r["dp_debt"] not in (None, ""):
                    dp = max(0.0, float(r["dp_debt"]))
                elif r["dp_balance"] not in (None, ""):
                    dp = max(0.0, -float(r["dp_balance"]))
            except (TypeError, ValueError):
                dp = 0.0
            base = {"patient_id": r["id"], "name": r["name"], "phone": r["phone"], "billed": round(r["billed"] or 0, 2),
                    "paid": round(r["paid"] or 0, 2), "last": max(r["last_invoice"] or "", r["last_payment"] or "")}
            if local < -0.009 or dp > 0.009:
                debts.append({**base, "debt": round(max(0.0, -local), 2), "dp_debt": round(dp, 2),
                              "total": round(max(0.0, -local) + dp, 2)})
            if local > 0.009:
                advances.append({**base, "advance": local})
        debts.sort(key=lambda x: -x["total"])
        advances.sort(key=lambda x: -x["advance"])
        return {"debts": debts, "advances": advances,
                "total_debt": round(sum(x["total"] for x in debts), 2),
                "total_advance": round(sum(x["advance"] for x in advances), 2)}
