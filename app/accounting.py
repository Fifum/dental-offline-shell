"""Accounting: clinic expenses, staff pay (percent of services plus a monthly salary) and the profit summary.

Income is what patients paid in this program. Expenses are entered by hand; paying out a salary is an
expense of the «Зарплата» category tied to a person and a month, so «к выплате» = начислено − выплачено.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from reports import _period
from shifts import people

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses(
    id TEXT PRIMARY KEY, date TEXT, category TEXT, amount REAL, method TEXT, person TEXT, period TEXT,
    comment TEXT, user_name TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_exp_date ON expenses(date);
CREATE TABLE IF NOT EXISTS salary_schemes(
    person TEXT PRIMARY KEY, percent REAL DEFAULT 0, fixed REAL DEFAULT 0, base TEXT DEFAULT 'paid',
    minus_materials INTEGER DEFAULT 0, updated_at TEXT);
"""
CATEGORIES = ["Аренда", "Зарплата", "Материалы и закупки", "Зуботехническая лаборатория", "Коммунальные услуги",
              "Связь и интернет", "Реклама", "Налоги и взносы", "Банк и эквайринг", "Ремонт и обслуживание",
              "Хозяйственные расходы", "Транспорт и доставка", "Прочее"]  # 2.14: the last two — for the front desk's day
SALARY = "Зарплата"
AD = "Реклама"  # these expenses can name the patient source they paid for (CRM: payback of advertising)
METHODS = ["Наличные", "Безналичный перевод", "Карта"]
BASES = {"paid": "от оплаченного", "billed": "от выставленных счетов"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _money(v, what="Сумма"):
    try:
        x = round(float(str(v).replace(",", ".").replace(" ", "").replace("\xa0", "")), 2)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: введите число") from None
    return x


def _month_range(month):
    try:
        y, m = map(int, str(month or date.today().strftime("%Y-%m"))[:7].split("-"))
        a = date(y, m, 1)
    except ValueError:
        raise ValueError("Неверный месяц") from None
    b = date(y + (m == 12), m % 12 + 1, 1)
    return f"{y:04d}-{m:02d}", a.isoformat(), b.isoformat()


class Accounting:
    def __init__(self, db):
        self.db = db
        db.conn.executescript(SCHEMA)
        if "minus_lab" not in {r[1] for r in db.conn.execute("PRAGMA table_info(salary_schemes)")}:
            db.conn.execute("ALTER TABLE salary_schemes ADD COLUMN minus_lab INTEGER DEFAULT 0")
        if "source" not in {r[1] for r in db.conn.execute("PRAGMA table_info(expenses)")}:  # 2.11: which ad channel was paid for
            db.conn.execute("ALTER TABLE expenses ADD COLUMN source TEXT")
        db.conn.commit()

    # ------------------------------------------------------------ expenses --
    def categories(self):
        used = [r["category"] for r in self.db.q("SELECT DISTINCT category FROM expenses WHERE category<>'' ORDER BY category")]
        return CATEGORIES + [c for c in used if c not in CATEGORIES]

    def expenses(self, date_from=None, date_to=None, category=None):
        a, b = _period(date_from, date_to)
        sql, args = "SELECT * FROM expenses WHERE date >= ? AND date < ?", [a, b]
        if category:
            sql += " AND category=?"
            args.append(category)
        rows = self.db.q(sql + " ORDER BY date DESC, created_at DESC", args)
        names = {p["key"]: p["name"] for p in people(self.db)}
        by = {}
        for r in rows:
            r["person_name"] = names.get(r["person"] or "", "")
            by[r["category"]] = round(by.get(r["category"], 0) + r["amount"], 2)
        return {"rows": rows, "total": round(sum(r["amount"] for r in rows), 2),
                "by_category": dict(sorted(by.items(), key=lambda x: -x[1]))}

    def save_expense(self, f, who=""):
        amount = _money(f.get("amount"))
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        cat = str(f.get("category") or "").strip()[:80]
        if not cat:
            raise ValueError("Укажите статью расхода")
        day = str(f.get("date") or date.today().isoformat())[:10]
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError("Неверная дата") from None
        person = str(f.get("person") or "") or None
        if person and not any(p["key"] == person for p in people(self.db)):
            raise ValueError("Сотрудник не найден")
        period = str(f.get("period") or "")[:7] or None
        source = (str(f.get("source") or "").strip()[:60] or None) if cat == AD else None
        eid = f.get("id") or f"E-{uuid.uuid4().hex[:10]}"
        vals = (day, cat, amount, str(f.get("method") or METHODS[0])[:40], person, period,
                str(f.get("comment") or "").strip()[:300], source)
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM expenses WHERE id=?", (eid,)).fetchone():
                c.execute("UPDATE expenses SET date=?, category=?, amount=?, method=?, person=?, period=?, comment=?, source=? WHERE id=?",
                          (*vals, eid))
            else:
                c.execute("""INSERT INTO expenses(id, date, category, amount, method, person, period, comment, source, user_name, created_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (eid, *vals, who, _now()))
        return eid

    def delete_expense(self, eid):
        with self.db.tx() as c:
            c.execute("DELETE FROM expenses WHERE id=?", (eid,))
        return True

    # -------------------------------------------------------------- salary --
    def schemes(self):
        sch = {r["person"]: r for r in self.db.q("SELECT * FROM salary_schemes")}
        return [{**p, "percent": (sch.get(p["key"]) or {}).get("percent") or 0, "fixed": (sch.get(p["key"]) or {}).get("fixed") or 0,
                 "base": (sch.get(p["key"]) or {}).get("base") or "paid",
                 "minus_materials": bool((sch.get(p["key"]) or {}).get("minus_materials")),
                 "minus_lab": bool((sch.get(p["key"]) or {}).get("minus_lab"))} for p in people(self.db)]

    def save_scheme(self, f):
        key = str(f.get("person") or "")
        if not any(p["key"] == key for p in people(self.db)):
            raise ValueError("Сотрудник не найден")
        pct, fixed = _money(f.get("percent") or 0, "Процент"), _money(f.get("fixed") or 0, "Оклад")
        if not 0 <= pct <= 100:
            raise ValueError("Процент: от 0 до 100")
        if fixed < 0:
            raise ValueError("Оклад не может быть отрицательным")
        base = f.get("base") if f.get("base") in BASES else "paid"
        with self.db.tx() as c:
            c.execute("""INSERT INTO salary_schemes(person, percent, fixed, base, minus_materials, minus_lab, updated_at) VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(person) DO UPDATE SET percent=excluded.percent, fixed=excluded.fixed, base=excluded.base,
                         minus_materials=excluded.minus_materials, minus_lab=excluded.minus_lab, updated_at=excluded.updated_at""",
                      (key, pct, fixed, base, 1 if f.get("minus_materials") else 0, 1 if f.get("minus_lab") else 0, _now()))
        return True

    def _lab_cost(self, doctor_id, a, b):
        """Lab orders of the doctor created in the month: their price is the clinic's cost."""
        try:
            return round(self.db.one("""SELECT COALESCE(SUM(price),0) AS s FROM lab_orders WHERE doctor_id=? AND status<>'cancelled'
                                        AND created_at >= ? AND created_at < ?""", (str(doctor_id), a, b))["s"], 2)
        except Exception:  # noqa: BLE001  (no lab table yet)
            return 0.0

    def _materials_cost(self, invoice_ids):
        if not invoice_ids:
            return 0.0
        try:
            marks = ",".join("?" * len(invoice_ids))
            r = self.db.one(f"SELECT COALESCE(SUM(-qty*price),0) AS s FROM stock_moves WHERE kind='service' AND invoice_id IN ({marks})",
                            tuple(invoice_ids))
            return round(r["s"] or 0, 2)
        except Exception:  # noqa: BLE001 - no stock module tables
            return 0.0

    def payroll(self, month=None):
        """Pay for one month: percent of the doctor's services (paid or billed) plus the monthly salary."""
        mon, a, b = _month_range(month)
        out = []
        for s in self.schemes():
            billed = paid = materials = lab = 0.0
            if s["kind"] == "doctor":
                inv = self.db.q("""SELECT id, total FROM invoices WHERE doctor_id=? AND COALESCE(kind,'invoice')='invoice'
                                   AND created_at >= ? AND created_at < ?""", (str(s["id"]), a, b))
                billed = round(sum(i["total"] or 0 for i in inv), 2)
                paid = round(self.db.one("""SELECT COALESCE(SUM(pay.amount),0) AS s FROM payments pay JOIN invoices i ON i.id=pay.invoice_id
                                            WHERE i.doctor_id=? AND pay.created_at >= ? AND pay.created_at < ?""",
                                         (str(s["id"]), a, b))["s"], 2)
                if s["minus_materials"]:
                    materials = self._materials_cost([i["id"] for i in inv])
                if s.get("minus_lab"):
                    lab = self._lab_cost(s["id"], a, b)
            base_sum = max(0.0, (paid if s["base"] == "paid" else billed) - materials - lab)
            by_percent = round(base_sum * s["percent"] / 100, 2)
            earned = round(by_percent + s["fixed"], 2)
            paid_out = round(self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM expenses WHERE category=? AND person=? AND period=?",
                                         (SALARY, s["key"], mon))["s"], 2)
            if not earned and not paid_out and not s["percent"] and not s["fixed"]:
                continue
            out.append({**s, "billed": billed, "paid": paid, "materials": materials, "lab": lab, "base_sum": round(base_sum, 2),
                        "by_percent": by_percent, "earned": earned, "paid_out": paid_out, "due": round(earned - paid_out, 2)})
        unset = [s for s in self.schemes() if not s["percent"] and not s["fixed"]]
        return {"month": mon, "rows": out, "unset": unset,
                "earned": round(sum(r["earned"] for r in out), 2), "paid_out": round(sum(r["paid_out"] for r in out), 2),
                "due": round(sum(r["due"] for r in out), 2)}

    def pay_salary(self, f, who=""):
        mon, _, _ = _month_range(f.get("month"))
        name = next((p["name"] for p in people(self.db) if p["key"] == f.get("person")), "")
        return self.save_expense({"date": f.get("date"), "category": SALARY, "amount": f.get("amount"), "method": f.get("method"),
                                  "person": f.get("person"), "period": mon,
                                  "comment": f.get("comment") or f"Зарплата за {mon}: {name}"}, who)

    # ------------------------------------------------------------- summary --
    def summary(self, date_from=None, date_to=None):
        """Income (patients' payments) minus expenses, by month inside the period."""
        a, b = _period(date_from, date_to)
        pays = self.db.q("""SELECT substr(created_at,1,7) AS m, SUM(amount) AS s FROM payments WHERE created_at >= ? AND created_at < ?
                            AND method<>'Бонусы' GROUP BY m""",  # bonuses are a discount, not income
                         (a, b))
        exps = self.db.q("SELECT substr(date,1,7) AS m, SUM(amount) AS s FROM expenses WHERE date >= ? AND date < ? GROUP BY m", (a, b))
        billed = self.db.one("""SELECT COALESCE(SUM(total),0) AS s FROM invoices WHERE COALESCE(kind,'invoice')='invoice'
                                AND created_at >= ? AND created_at < ?""", (a, b))["s"]
        months = {}
        for r in pays:
            months.setdefault(r["m"], {"month": r["m"], "income": 0.0, "expense": 0.0})["income"] = round(r["s"] or 0, 2)
        for r in exps:
            months.setdefault(r["m"], {"month": r["m"], "income": 0.0, "expense": 0.0})["expense"] = round(r["s"] or 0, 2)
        rows = [{**v, "result": round(v["income"] - v["expense"], 2)} for _, v in sorted(months.items())]
        income = round(sum(r["income"] for r in rows), 2)
        expense = round(sum(r["expense"] for r in rows), 2)
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(),
                "income": income, "billed": round(billed or 0, 2), "expense": expense, "result": round(income - expense, 2),
                "margin": round((income - expense) * 100 / income, 1) if income else 0,
                "by_month": rows, "by_category": self.expenses(date_from, date_to)["by_category"]}
