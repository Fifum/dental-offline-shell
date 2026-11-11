"""3.4: motivation of the administrators — a bonus for bookings that came, new patients, CRM requests brought to a visit,
own sales and the clinic's plan, on top of the salary scheme («Бухгалтерия» → «Зарплата»).

Rules are set by the director per employee or once for all administrators (person «*»: every active account whose
position stands on «Администратор»; an employee's own rule replaces it). Everything is 0 until the director sets it,
so nothing changes in the payroll by itself.

What is counted, for a month:
- a booking made in this program by the employee (`staff_bookings`, written when the visit is created) whose visit took
  place — the status «пришёл» / «завершён» in the schedule or in the archive of Dentist Plus visits. The visit is found by
  its id, by the doctor and the minute, or by the patient and the day (the local visit disappears once Dentist Plus
  has it). Bookings made directly in Dentist Plus are not known here: its API does not say who booked;
- a new patient: the booking was the patient's first visit;
- a CRM request with the stage «пришёл» closed in the month, of which the employee is in charge (or that he created);
- own sales: payments in the month for invoices the employee made (`invoices.created_by`), plus gift certificates he sold;
- a percent of the clinic's payments of the month, and a fixed bonus when the clinic's revenue plan is met.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

from accounting import _money, _month_range
from reports import status_kind
from timesheet import stable

SCHEMA = """
CREATE TABLE IF NOT EXISTS motivation_rules(
    person TEXT PRIMARY KEY, per_visit REAL DEFAULT 0, per_new REAL DEFAULT 0, lead_came REAL DEFAULT 0,
    sales_pct REAL DEFAULT 0, revenue_pct REAL DEFAULT 0, plan_bonus REAL DEFAULT 0, active INTEGER DEFAULT 1,
    note TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS staff_bookings(
    id TEXT PRIMARY KEY, patient_id TEXT, doctor_id TEXT, start TEXT, login TEXT, name TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_staff_bookings_start ON staff_bookings(start);
"""
ALL = "*"
RULES = [
    ("per_visit", "За запись, по которой пациент пришёл", "₽"),
    ("per_new", "Доплата за нового пациента", "₽"),
    ("lead_came", "За заявку CRM, доведённую до визита", "₽"),
    ("sales_pct", "От своих продаж (счета, абонементы, сертификаты)", "%"),
    ("revenue_pct", "От поступлений клиники за месяц", "%"),
    ("plan_bonus", "Премия за выполнение плана клиники по поступлениям", "₽"),
]
KEYS = [k for k, _, _ in RULES]
CAME = ("done", "came")
NOT_MONEY = ("Бонусы", "Сертификат", "Из аванса")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _r(x):
    return round(x or 0, 2)


class Motivation:
    def __init__(self, db, director=None):
        self.db, self.dir = db, director
        with db._lock:
            db.conn.executescript(SCHEMA)
            if "created_by" not in {r[1] for r in db.conn.execute("PRAGMA table_info(invoices)")}:
                db.conn.execute("ALTER TABLE invoices ADD COLUMN created_by TEXT")  # login of who made the invoice
            db.conn.commit()

    # ------------------------------------------------------------ the log --
    def log_booking(self, vid, f, u):
        """A visit created here by the signed-in employee (not a move or a status change)."""
        if not vid or not u or not u.get("login") or not isinstance(f, dict) or not f.get("start"):
            return
        with self.db.tx() as c:
            c.execute("""INSERT OR IGNORE INTO staff_bookings(id, patient_id, doctor_id, start, login, name, created_at)
                         VALUES(?,?,?,?,?,?,?)""", (str(vid), str(f.get("patient_id") or ""), str(f.get("doctor_id") or ""),
                                                   str(f["start"])[:16], u["login"].lower(), u.get("name") or "", _now()))

    def stamp_invoice(self, iid, u):
        if iid and u and u.get("login"):
            with self.db.tx() as c:
                c.execute("UPDATE invoices SET created_by=? WHERE id=? AND COALESCE(created_by,'')=''", (u["login"].lower(), str(iid)))

    # ------------------------------------------------------------ rules --
    def _staff(self):
        """Active accounts that are not doctors: [{key, skey, login, name, position, admin}]."""
        import auth  # noqa: PLC0415
        try:
            rows = self.db.q("SELECT id, login, name, position, role FROM users WHERE status='active' AND COALESCE(doctor_id,'')='' ORDER BY name")
        except sqlite3.OperationalError:
            return []
        return [{"key": f"u:{r['id']}", "skey": "login:" + (r["login"] or "").lower(), "login": (r["login"] or "").lower(),
                 "name": r["name"] or r["login"], "position": r["position"] or "", "role": r["role"] or "",
                 "admin": auth.role_base(r["role"]) == "admin"} for r in rows]

    def _rule_rows(self):
        return {r["person"]: r for r in self.db.q("SELECT * FROM motivation_rules")}

    @staticmethod
    def _clean(r):
        return {k: _r((r or {}).get(k)) for k in KEYS} | {"active": bool((r or {}).get("active", 1)), "note": (r or {}).get("note") or ""}

    def rules(self) -> dict:
        saved = self._rule_rows()
        staff = []
        for s in self._staff():
            own = saved.get(s["skey"])
            rule = self._clean(own) if own else (self._clean(saved.get(ALL)) if s["admin"] else None)
            staff.append({**{k: s[k] for k in ("key", "name", "position", "login", "admin")}, "own": bool(own),
                          "rule": rule, "from_all": bool(not own and s["admin"])})
        return {"all": self._clean(saved.get(ALL)), "staff": staff, "fields": [{"key": k, "title": t, "unit": u} for k, t, u in RULES]}

    def save_rule(self, f) -> dict:
        f = f or {}
        person = str(f.get("person") or "")
        if person != ALL:
            if not any(s["key"] == person for s in self._staff()):
                raise ValueError("Сотрудник не найден")
            person = stable(self.db, person)
        if f.get("reset") and person != ALL:
            with self.db.tx() as c:
                c.execute("DELETE FROM motivation_rules WHERE person=?", (person,))
            return self.rules()
        vals = {}
        for k, title, unit in RULES:
            v = _money(f.get(k) or 0, title)
            if v < 0:
                raise ValueError(f"{title}: не может быть отрицательным")
            if unit == "%" and v > 100:
                raise ValueError(f"{title}: от 0 до 100 %")
            vals[k] = v
        with self.db.tx() as c:
            c.execute(f"""INSERT INTO motivation_rules(person, {', '.join(KEYS)}, active, note, updated_at) VALUES(?{',?' * len(KEYS)},?,?,?)
                          ON CONFLICT(person) DO UPDATE SET {', '.join(f'{k}=excluded.{k}' for k in KEYS)}, active=excluded.active,
                          note=excluded.note, updated_at=excluded.updated_at""",
                      (person, *vals.values(), 0 if f.get("active") is False else 1, str(f.get("note") or "").strip()[:200], _now()))
        return self.rules()

    # ------------------------------------------------------------ the month --
    def _visits(self, a, b):
        from director import HIST  # noqa: PLC0415
        rows = self.db.q(f"SELECT id, patient_id, doctor_id, start, status FROM ({HIST}) WHERE start >= ? AND start < ?", (a, b))
        by_id, by_slot, by_day = {}, {}, {}
        for r in rows:
            r["kind"] = status_kind(r["status"])
            by_id[str(r["id"])] = r
            by_slot.setdefault((str(r["doctor_id"] or ""), (r["start"] or "")[:16]), r)
            by_day.setdefault((str(r["patient_id"] or ""), (r["start"] or "")[:10]), r)
        remote = {r["id"]: r["remote_id"] for r in self.db.q("SELECT id, remote_id FROM local_visits WHERE remote_id IS NOT NULL")}
        return by_id, by_slot, by_day, remote

    def _first(self):
        if self.dir is not None:
            try:
                return self.dir._first_visits()
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def _clinic_revenue(self, a, b):
        return _r(self.db.one("""SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE created_at >= ? AND created_at < ?
                                 AND method<>'Бонусы'""", (a, b))["s"])

    def _plan(self, mon):
        if self.dir is None:
            return None, None
        try:
            k = self.dir.kpi(mon)["clinic"]["metrics"]["revenue"]
            return k["plan"], k["fact"]
        except Exception:  # noqa: BLE001
            return None, None

    def month(self, month=None) -> dict:
        mon, a, b = _month_range(month)
        saved = self._rule_rows()
        staff = []
        for s in self._staff():
            own = saved.get(s["skey"])
            r = own if own else (saved.get(ALL) if s["admin"] else None)
            if r and r["active"] and any((r[k] or 0) > 0 for k in KEYS):
                staff.append((s, self._clean(r), bool(own)))
        out = {"month": mon, "rows": [], "total": 0.0, "fields": [{"key": k, "title": t, "unit": u} for k, t, u in RULES],
               "note": "Записи считаются те, что сделаны в этой программе: Dentist Plus в своём API не сообщает, кто записал пациента."}
        if not staff:
            return out
        need = lambda k: any(rule[k] > 0 for _, rule, _ in staff)  # noqa: E731
        vis = self._visits(a, b) if need("per_visit") or need("per_new") else None
        first = self._first() if need("per_new") else {}
        revenue = self._clinic_revenue(a, b) if need("revenue_pct") else 0.0
        plan, fact = self._plan(mon) if need("plan_bonus") else (None, None)
        for s, rule, own in staff:
            items = []
            if vis is not None and (rule["per_visit"] or rule["per_new"]):
                came, new, booked = self._bookings(s["login"], a, b, vis, first)
                if rule["per_visit"]:
                    items.append({"rule": "per_visit", "count": came, "of": booked, "rate": rule["per_visit"], "amount": _r(came * rule["per_visit"])})
                if rule["per_new"]:
                    items.append({"rule": "per_new", "count": new, "rate": rule["per_new"], "amount": _r(new * rule["per_new"])})
            if rule["lead_came"]:
                n = self._leads(s, a, b)
                items.append({"rule": "lead_came", "count": n, "rate": rule["lead_came"], "amount": _r(n * rule["lead_came"])})
            if rule["sales_pct"]:
                base = self._sales(s, a, b)
                items.append({"rule": "sales_pct", "base": base, "rate": rule["sales_pct"], "amount": _r(base * rule["sales_pct"] / 100)})
            if rule["revenue_pct"]:
                items.append({"rule": "revenue_pct", "base": revenue, "rate": rule["revenue_pct"], "amount": _r(revenue * rule["revenue_pct"] / 100)})
            if rule["plan_bonus"]:
                done = bool(plan) and (fact or 0) >= plan
                items.append({"rule": "plan_bonus", "plan": plan, "fact": fact, "done": done, "rate": rule["plan_bonus"],
                              "amount": _r(rule["plan_bonus"] if done else 0)})
            total = _r(sum(x["amount"] for x in items))
            out["rows"].append({"key": s["key"], "name": s["name"], "position": s["position"], "own": own, "items": items, "total": total})
        out["total"] = _r(sum(x["total"] for x in out["rows"]))
        return out

    def bonuses(self, month=None) -> dict:
        """{people key: bonus} for the payroll."""
        try:
            return {r["key"]: r["total"] for r in self.month(month)["rows"] if r["total"]}
        except Exception:  # noqa: BLE001 — a bare database (tests without accounts)
            return {}

    def _bookings(self, login, a, b, vis, first):
        by_id, by_slot, by_day, remote = vis
        rows = self.db.q("SELECT * FROM staff_bookings WHERE login=? AND start >= ? AND start < ?", (login, a, b))
        came = new = 0
        today = date.today().isoformat()
        for bk in rows:
            v = (by_id.get(bk["id"]) or by_id.get(str(remote.get(bk["id"]) or "")) or by_slot.get((bk["doctor_id"] or "", bk["start"][:16]))
                 or by_day.get((bk["patient_id"] or "", bk["start"][:10])))
            if not v or v["kind"] not in CAME or bk["start"][:10] > today:
                continue
            came += 1
            f = first.get(v["patient_id"])
            if f and f[0] == (v["start"] or "")[:10]:
                new += 1
        return came, new, len(rows)

    def _leads(self, s, a, b):
        try:
            return self.db.one("""SELECT COUNT(*) AS n FROM crm_leads WHERE stage='came' AND closed_at >= ? AND closed_at < ?
                                  AND (lower(COALESCE(assignee,''))=? OR (COALESCE(assignee,'')='' AND created_by=?))""",
                               (a, b, s["login"], s["name"]))["n"]
        except sqlite3.OperationalError:
            return 0

    def _sales(self, s, a, b):
        marks = ",".join("?" * len(NOT_MONEY))
        inv = self.db.one(f"""SELECT COALESCE(SUM(pay.amount),0) AS s FROM payments pay JOIN invoices i ON i.id=pay.invoice_id
                              WHERE i.created_by=? AND pay.created_at >= ? AND pay.created_at < ? AND pay.method NOT IN ({marks})""",
                          (s["login"], a, b, *NOT_MONEY))["s"] or 0
        try:
            cert = self.db.one(f"""SELECT COALESCE(SUM(amount),0) AS s FROM certificates WHERE sold_by=? AND sold_at >= ? AND sold_at < ?
                                   AND COALESCE(method,'') NOT IN ({marks})""", (s["name"], a, b, *NOT_MONEY))["s"] or 0
        except sqlite3.OperationalError:
            cert = 0
        return _r(inv + cert)
