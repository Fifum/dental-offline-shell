"""Dental lab orders (заказ-наряды): what is made, for which teeth, shade, deadlines, status and the lab's price.

The lab's price is the clinic's cost: it is subtracted from the doctor's pay when the salary scheme says so,
and paying the lab is recorded as an expense of the «Зуботехническая лаборатория» category.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS labs(
    id TEXT PRIMARY KEY, name TEXT, phone TEXT, contact TEXT, note TEXT, active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS lab_orders(
    id TEXT PRIMARY KEY, number INTEGER, patient_id TEXT, doctor_id TEXT, lab_id TEXT, plan_id TEXT, work TEXT, teeth TEXT,
    shade TEXT, material TEXT, sent_date TEXT, fitting_date TEXT, due_date TEXT, status TEXT DEFAULT 'new', price REAL DEFAULT 0,
    paid INTEGER DEFAULT 0, paid_at TEXT, expense_id TEXT, note TEXT, created_at TEXT, created_by TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_lab_orders_patient ON lab_orders(patient_id);
CREATE INDEX IF NOT EXISTS ix_lab_orders_status ON lab_orders(status);
"""
STATUSES = {"new": "Новый", "sent": "Отправлен в лабораторию", "fitting": "Примерка", "redo": "Переделка",
            "ready": "Готов", "delivered": "Сдан пациенту", "cancelled": "Отменён"}
OPEN = ("new", "sent", "fitting", "redo")
WORKS = ["Коронка металлокерамическая", "Коронка из диоксида циркония", "Коронка E.max", "Вкладка культевая", "Вкладка керамическая",
         "Винир", "Мост", "Коронка на имплантате", "Съёмный протез", "Бюгельный протез", "Временная коронка", "Каппа / ретейнер",
         "Ночная шина", "Хирургический шаблон"]
SHADES = ["A1", "A2", "A3", "A3.5", "A4", "B1", "B2", "B3", "B4", "C1", "C2", "C3", "C4", "D2", "D3", "D4", "BL1", "BL2"]


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _day(v, what):
    v = str(v or "").strip()[:10]
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(f"{what}: дата указана неверно") from None


def _money(v):
    try:
        x = round(float(str(v or 0).replace(",", ".").replace(" ", "")), 2)
    except ValueError:
        raise ValueError("Стоимость указана неверно") from None
    if x < 0:
        raise ValueError("Стоимость не может быть отрицательной")
    return x


def _label_dups(db, rows):
    """М1: each computer numbers its own orders (MAX+1), so two computers without a connection can give the same
    number. The order made first keeps it; the later ones show «15-2», «15-3» (the same on every computer)."""
    dups = {r["number"] for r in db.q("SELECT number FROM lab_orders WHERE number IS NOT NULL GROUP BY number HAVING COUNT(*)>1")}
    if not dups or not any(r.get("number") in dups for r in rows):
        return rows
    rank = {}
    for n in dups:
        for i, x in enumerate(db.q("SELECT id FROM lab_orders WHERE number=? ORDER BY created_at, id", (n,))):
            rank[x["id"]] = i + 1
    for r in rows:
        k = rank.get(r["id"], 1) if r.get("number") in dups else 1
        r["dup"] = k > 1
        if k > 1:
            r["number"] = f"{r['number']}-{k}"
    return rows


class Lab:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    # ---------------------------------------------------------------- labs --
    def labs(self, all_=False) -> list[dict]:
        return self.db.q(f"SELECT * FROM labs {'' if all_ else 'WHERE active=1'} ORDER BY name")

    def save_lab(self, f) -> dict:
        name = str(f.get("name") or "").strip()[:120]
        if not name:
            raise ValueError("Укажите название лаборатории")
        vals = (name, str(f.get("phone") or "")[:60], str(f.get("contact") or "")[:120], str(f.get("note") or "")[:300],
                0 if f.get("active") is False else 1)
        with self.db.tx() as c:
            lid = f.get("id")
            if lid:
                if not c.execute("UPDATE labs SET name=?, phone=?, contact=?, note=?, active=? WHERE id=?", (*vals, lid)).rowcount:
                    raise ValueError("Лаборатория не найдена")
            else:
                lid = "LB-" + uuid.uuid4().hex[:8]
                c.execute("INSERT INTO labs(id, name, phone, contact, note, active, created_at) VALUES(?,?,?,?,?,?,?)", (lid, *vals, _now()))
        return self.db.one("SELECT * FROM labs WHERE id=?", (lid,))

    # -------------------------------------------------------------- orders --
    def _rows(self, where="1=1", args=()):
        rows = self.db.q(f"""SELECT o.*, p.name AS patient_name, d.name AS doctor_name, l.name AS lab_name
                             FROM lab_orders o LEFT JOIN patients p ON p.id=o.patient_id LEFT JOIN doctors d ON d.id=o.doctor_id
                             LEFT JOIN labs l ON l.id=o.lab_id WHERE {where}
                             ORDER BY CASE WHEN o.status IN ('new','sent','fitting','redo') THEN 0 ELSE 1 END, COALESCE(o.due_date,'9999'), o.created_at DESC""",
                          args)
        today = date.today().isoformat()
        _label_dups(self.db, rows)
        for r in rows:
            r["status_text"] = STATUSES.get(r["status"], r["status"])
            r["overdue"] = bool(r["status"] in OPEN and r["due_date"] and r["due_date"] < today)
            r["fitting_today"] = bool(r["status"] in OPEN and r["fitting_date"] == today)
        return rows

    def orders(self, status="open", lab_id=None, patient_id=None, doctor_id=None) -> list[dict]:
        w, a = [], []
        if status == "open":
            w.append("o.status IN ('new','sent','fitting','redo')")
        elif status == "unpaid":
            w.append("o.paid=0 AND o.status NOT IN ('cancelled') AND o.price>0")
        elif status and status != "all":
            w.append("o.status=?")
            a.append(status)
        for col, v in (("o.lab_id", lab_id), ("o.patient_id", patient_id), ("o.doctor_id", doctor_id)):
            if v:
                w.append(f"{col}=?")
                a.append(v)
        return self._rows(" AND ".join(w) or "1=1", a)

    def order(self, oid) -> dict:
        r = self._rows("o.id=?", (oid,))
        if not r:
            raise ValueError("Заказ-наряд не найден")
        return r[0]

    def save(self, f, who="") -> dict:
        pid = str(f.get("patient_id") or "")
        if not pid or not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Выберите пациента")
        work = str(f.get("work") or "").strip()[:200]
        if not work:
            raise ValueError("Укажите, что изготавливает лаборатория")
        status = f.get("status") or "new"
        if status not in STATUSES:
            raise ValueError("Неизвестный статус")
        vals = {"patient_id": pid, "doctor_id": f.get("doctor_id") or None, "lab_id": f.get("lab_id") or None,
                "plan_id": f.get("plan_id") or None, "work": work, "teeth": str(f.get("teeth") or "")[:60],
                "shade": str(f.get("shade") or "")[:20], "material": str(f.get("material") or "")[:120],
                "sent_date": _day(f.get("sent_date"), "Отправлен"), "fitting_date": _day(f.get("fitting_date"), "Примерка"),
                "due_date": _day(f.get("due_date"), "Срок"), "status": status, "price": _money(f.get("price")),
                "note": str(f.get("note") or "")[:500]}
        if vals["sent_date"] and vals["due_date"] and vals["due_date"] < vals["sent_date"]:
            raise ValueError("Срок готовности раньше даты отправки")
        oid = f.get("id")
        with self.db.tx() as c:
            if oid:
                if not c.execute("SELECT 1 FROM lab_orders WHERE id=?", (oid,)).fetchone():
                    raise ValueError("Заказ-наряд не найден")
                c.execute(f"UPDATE lab_orders SET {', '.join(k + '=?' for k in vals)}, updated_at=? WHERE id=?", (*vals.values(), _now(), oid))
            else:
                oid = "LO-" + uuid.uuid4().hex[:10]
                n = (c.execute("SELECT MAX(number) FROM lab_orders").fetchone()[0] or 0) + 1
                c.execute(f"""INSERT INTO lab_orders(id, number, {', '.join(vals)}, created_at, created_by, updated_at)
                              VALUES(?, ?, {', '.join('?' * len(vals))}, ?, ?, ?)""", (oid, n, *vals.values(), _now(), who or "", _now()))
        return self.order(oid)

    def set_status(self, oid, status) -> dict:
        if status not in STATUSES:
            raise ValueError("Неизвестный статус")
        with self.db.tx() as c:
            if not c.execute("UPDATE lab_orders SET status=?, updated_at=? WHERE id=?", (status, _now(), oid)).rowcount:
                raise ValueError("Заказ-наряд не найден")
        return self.order(oid)

    def mark_paid(self, oids, accounting, method="Безналичный перевод", who="") -> dict:
        """Pay the lab for several orders at once: one expense, the orders marked as paid."""
        rows = [self.order(o) for o in oids or []]
        if not rows:
            raise ValueError("Отметьте заказ-наряды")
        if any(r["paid"] for r in rows):
            raise ValueError("Среди отмеченных есть уже оплаченные")
        labs = {r["lab_id"] for r in rows}
        if len(labs) > 1:
            raise ValueError("Оплачивайте заказ-наряды одной лаборатории за раз")
        total = round(sum(r["price"] or 0 for r in rows), 2)
        if total <= 0:
            raise ValueError("У отмеченных заказ-нарядов не указана стоимость")
        lab = rows[0]["lab_name"] or "лаборатория"
        exp = accounting.save_expense({"date": date.today().isoformat(), "category": "Зуботехническая лаборатория", "amount": total,
                                       "method": method, "comment": f"{lab}: заказ-наряды № " + ", ".join(str(r["number"]) for r in rows)}, who)
        eid = exp if isinstance(exp, str) else (exp or {}).get("id")
        with self.db.tx() as c:
            for r in rows:
                c.execute("UPDATE lab_orders SET paid=1, paid_at=?, expense_id=? WHERE id=?", (_now(), eid, r["id"]))
        return {"total": total, "count": len(rows), "expense_id": eid}

    def summary(self) -> dict:
        today = date.today().isoformat()
        rows = self._rows("o.status IN ('new','sent','fitting','redo')")
        return {"open": len(rows), "overdue": sum(1 for r in rows if r["overdue"]), "fitting_today": sum(1 for r in rows if r["fitting_date"] == today),
                "ready_today": len(self.db.q("SELECT 1 FROM lab_orders WHERE status='ready' AND due_date=?", (today,))),
                "unpaid": round(self.db.one("SELECT COALESCE(SUM(price),0) AS s FROM lab_orders WHERE paid=0 AND status<>'cancelled'")["s"], 2)}
