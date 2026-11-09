"""Money, 2.12.0: the patient's advance (deposit) and paying invoices from it, refunds, payment schedules
(installments), memberships («абонементы»), the cash drawer by shifts with reconciliation, and voluntary
medical insurance (ДМС: insurers, policies and letters of guarantee, monthly registries).

The advance and refunds are rows of `payments`, so the cash report, revenue, salary and the tax certificate
count them without changes:
- an advance is a money payment without an invoice;
- paying an invoice from the advance is one operation (`link_id`) of rows with the method «Из аванса»: +sum on
  the invoice and −sum on the «pocket» the money came from — the advance itself or an overpaid invoice; the
  day's money does not change, the doctor gets the payment on his invoice;
- a refund is a negative payment (kind 'refund') taken from such a pocket.
Invoices paid by an insurance company (`invoices.insurer_id`) are not the patient's debt; the company pays them
by a registry, and then every invoice gets a payment «Страховая».
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS pay_schedules(
    id TEXT PRIMARY KEY, invoice_id TEXT, patient_id TEXT, items TEXT, note TEXT, created_at TEXT, created_by TEXT,
    updated_at TEXT);
CREATE TABLE IF NOT EXISTS membership_types(
    id TEXT PRIMARY KEY, name TEXT, items TEXT, price REAL, months INTEGER, note TEXT, active INTEGER DEFAULT 1,
    updated_at TEXT);
CREATE TABLE IF NOT EXISTS memberships(
    id TEXT PRIMARY KEY, type_id TEXT, patient_id TEXT, name TEXT, items TEXT, price REAL, invoice_id TEXT,
    sold_at TEXT, sold_by TEXT, expires TEXT, status TEXT DEFAULT 'active', note TEXT);
CREATE TABLE IF NOT EXISTS membership_uses(
    id TEXT PRIMARY KEY, membership_id TEXT, invoice_id TEXT, service_id TEXT, title TEXT, qty REAL, at TEXT);
CREATE TABLE IF NOT EXISTS cash_shifts(
    id TEXT PRIMARY KEY, opened_at TEXT, opened_by TEXT, open_cash REAL, closed_at TEXT, closed_by TEXT,
    expected_cash REAL, counted_cash REAL, card_expected REAL, card_terminal REAL, sbp_expected REAL, sbp_bank REAL,
    note TEXT, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS cash_moves(
    id TEXT PRIMARY KEY, shift_id TEXT, at TEXT, kind TEXT, amount REAL, reason TEXT, comment TEXT, by TEXT, expense_id TEXT);
CREATE TABLE IF NOT EXISTS insurers(
    id TEXT PRIMARY KEY, name TEXT, contract TEXT, phone TEXT, email TEXT, note TEXT, active INTEGER DEFAULT 1, updated_at TEXT);
CREATE TABLE IF NOT EXISTS insurance_docs(
    id TEXT PRIMARY KEY, patient_id TEXT, insurer_id TEXT, kind TEXT, number TEXT, date TEXT, valid_to TEXT,
    limit_sum REAL, note TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS insurance_registries(
    id TEXT PRIMARY KEY, insurer_id TEXT, number TEXT, date_from TEXT, date_to TEXT, invoice_ids TEXT, total REAL,
    status TEXT, created_at TEXT, created_by TEXT, sent_at TEXT, paid_at TEXT, paid_total REAL, note TEXT);
"""

DEPOSIT = "Из аванса"
INSURANCE = "Страховая"
MONEY = ("Наличные", "Карта", "СБП", "Перевод")
CASH, CARD, SBP = "Наличные", "Карта", "СБП"
MOVE_IN = ["Размен", "Внесение"]
MOVE_OUT = ["Инкассация", "Расход из кассы", "Размен", "Выдача"]
REG_STATUS = {"draft": "Сформирован", "sent": "Отправлен", "paid": "Оплачен"}
DOC_KINDS = {"policy": "Полис ДМС", "letter": "Гарантийное письмо"}
INV = "COALESCE(i.kind,'invoice')='invoice'"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _money(v, what="Сумма"):
    try:
        return round(float(str(v if v is not None else 0).replace(",", ".").replace(" ", "").replace(" ", "") or 0), 2)
    except ValueError:
        raise ValueError(f"{what} указана неверно") from None


def _day(v, what="Дата", required=True):
    s = str(v or "").strip()[:10]
    if not s:
        if required:
            raise ValueError(f"{what}: укажите дату")
        return None
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise ValueError(f"{what} указана неверно") from None


def _rub(x):
    return f"{x:,.2f}".replace(",", " ").replace(".00", "") + " ₽"


def _fmt(d):
    d = str(d or "")[:10]
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}" if len(d) == 10 else d


def _months(start: date, n: int) -> date:
    m = start.month - 1 + n
    y, m = start.year + m // 12, m % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(start.day, last))


class Finance:
    def __init__(self, db, local=None, loyalty=None):
        self.db = db
        self.local = local
        self.loyal = loyalty
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def _status(self, iid):
        if iid and self.local:
            self.local._invoice_status(iid)

    def _patient(self, pid):
        p = self.db.one("SELECT id, name, phone FROM patients WHERE id=?", (pid,)) if pid else None
        if not p:
            raise ValueError("Пациент не найден")
        return p

    # ================================================================ advance --
    def pockets(self, pid) -> list[dict]:
        """The patient's money not used yet: the advance (payments without an invoice) and overpaid invoices."""
        out = []
        free = self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE patient_id=? AND COALESCE(invoice_id,'')=''",
                           (pid,))["s"]
        if free > 0.009:
            out.append({"invoice_id": None, "amount": round(free, 2), "title": "Аванс"})
        for r in self.db.q(f"""SELECT i.id, i.total, i.created_at, (SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=i.id) AS paid
                               FROM invoices i WHERE i.patient_id=? AND {INV} AND COALESCE(i.insurer_id,'')=''
                               ORDER BY i.created_at""", (pid,)):
            over = round((r["paid"] or 0) - (r["total"] or 0), 2)
            if over > 0.009:
                out.append({"invoice_id": r["id"], "amount": over, "title": f"Переплата по счёту от {_fmt(r['created_at'])}"})
        return out

    def deposit(self, pid) -> float:
        return round(sum(x["amount"] for x in self.pockets(pid)), 2)

    def _due(self, iid):
        inv = self.db.one("SELECT i.*, (SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=i.id) AS paid "
                          "FROM invoices i WHERE i.id=?", (iid,))
        if not inv or (inv["kind"] or "invoice") != "invoice":
            raise ValueError("Счёт не найден")
        return inv, round((inv["total"] or 0) - (inv["paid"] or 0), 2)

    def _take(self, pockets, amount, skip=None):
        """Split the sum between pockets: the advance first, then overpaid invoices."""
        parts, left = [], amount
        for p in pockets:
            if left < 0.009:
                break
            if skip and p["invoice_id"] == skip:
                continue
            x = round(min(p["amount"], left), 2)
            if x > 0.009:
                parts.append((p["invoice_id"], x))
                left = round(left - x, 2)
        return parts, left

    def deposit_use(self, invoice_id, amount=None, who="") -> dict:
        """Pay an invoice from the patient's advance. Returns {"id": payment on the invoice, "group": operation}."""
        inv, due = self._due(invoice_id)
        if inv["insurer_id"]:
            raise ValueError("Этот счёт оплачивает страховая компания")
        if due < 0.009:
            raise ValueError("Счёт уже оплачен")
        pockets = [p for p in self.pockets(inv["patient_id"]) if p["invoice_id"] != invoice_id]
        have = round(sum(p["amount"] for p in pockets), 2)
        if have < 0.009:
            raise ValueError("У пациента нет аванса")
        amount = round(min(have, due), 2) if amount in (None, "") else _money(amount)
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        if amount > due + 0.009:
            raise ValueError(f"По счёту осталось оплатить {_rub(due)}")
        if amount > have + 0.009:
            raise ValueError(f"Аванс пациента — {_rub(have)}")
        parts, _ = self._take(pockets, amount)
        g, at, pay_id = _id("DU"), _now(), _id("P")
        when = _fmt(inv["created_at"])
        with self.db.tx() as c:
            c.execute("""INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at, kind, link_id)
                         VALUES(?,?,?,?,?,?,?,?,?)""", (pay_id, invoice_id, inv["patient_id"], amount, DEPOSIT, "из аванса пациента", at,
                                                       "deposit_use", g))
            for src, x in parts:
                c.execute("""INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at, kind, link_id)
                             VALUES(?,?,?,?,?,?,?,?,?)""", (_id("P"), src, inv["patient_id"], -x, DEPOSIT, f"в оплату счёта от {when}", at,
                                                           "deposit_use", g))
        self._status(invoice_id)
        for src, _ in parts:
            self._status(src)
        return {"id": pay_id, "group": g, "amount": amount}

    def refund(self, f, who="") -> dict:
        """Give money back to the patient from the advance (or from one overpaid invoice)."""
        f = f or {}
        pid = f.get("patient_id")
        iid = f.get("invoice_id") or None
        if iid and not pid:
            pid = (self.db.one("SELECT patient_id FROM invoices WHERE id=?", (iid,)) or {}).get("patient_id")
        self._patient(pid)
        amount = _money(f.get("amount"))
        if amount <= 0:
            raise ValueError("Сумма возврата должна быть больше нуля")
        method = f.get("method") if f.get("method") in MONEY else CASH
        reason = " ".join(str(f.get("reason") or "").split())[:200]
        if not reason:
            raise ValueError("Укажите причину возврата")
        pockets = self.pockets(pid)
        if iid:
            pockets = [p for p in pockets if p["invoice_id"] == iid]
        have = round(sum(p["amount"] for p in pockets), 2)
        if have < 0.009:
            raise ValueError("Возвращать нечего: у пациента нет аванса и переплаты" if not iid else "По этому счёту нет переплаты")
        if amount > have + 0.009:
            raise ValueError(f"Можно вернуть не больше {_rub(have)}")
        parts, _ = self._take(pockets, amount)
        g, at, ids = _id("RF"), _now(), []
        with self.db.tx() as c:
            for src, x in parts:
                rid = _id("P")
                ids.append(rid)
                c.execute("""INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at, kind, link_id)
                             VALUES(?,?,?,?,?,?,?,?,?)""", (rid, src, pid, -x, method, f"Возврат: {reason}", at, "refund", g))
        for src, _ in parts:
            self._status(src)
        if self.loyal:  # bonuses earned on the money that went back are taken back too (never below zero)
            import loyalty
            pct = float(loyalty.settings()["bonus_percent"])
            if pct > 0:
                back = round(min(self.loyal.bonus_balance(pid), amount * pct / 100), 2)
                if back > 0.009:
                    self.loyal._move(pid, -back, "refund", ids[0], f"Возврат денег {_rub(amount)}", who)
        return {"ids": ids, "group": g, "amount": amount}

    def group_rows(self, pay_id) -> list[dict]:
        """All rows of the operation the payment belongs to (an advance move or a refund), or just the payment."""
        p = self.db.one("SELECT * FROM payments WHERE id=?", (pay_id,))
        if not p:
            return []
        if p["link_id"] and p["kind"] in ("deposit_use", "refund"):
            return self.db.q("SELECT * FROM payments WHERE link_id=? AND kind=?", (p["link_id"], p["kind"]))
        return [p]

    def can_delete(self, pay_id):
        """An advance that was already spent cannot disappear: the money went to other invoices or back."""
        p = self.db.one("SELECT * FROM payments WHERE id=?", (pay_id,))
        if p and not p["invoice_id"] and (p["kind"] or "") == "" and p["amount"] > 0:
            free = self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE patient_id=? AND COALESCE(invoice_id,'')=''",
                               (p["patient_id"],))["s"]
            if free - p["amount"] < -0.009:
                raise ValueError("Часть этого аванса уже потрачена на счета или возвращена. Сначала удалите оплату из аванса или возврат.")

    def delete_group(self, pay_id):
        rows = self.group_rows(pay_id)
        with self.db.tx() as c:
            for r in rows:
                c.execute("DELETE FROM payments WHERE id=?", (r["id"],))
        for iid in {r["invoice_id"] for r in rows if r["invoice_id"]}:
            self._status(iid)
        return rows

    def before_invoice_delete(self, iid):
        """Deleting an invoice gives the advance spent on it back to the patient (both sides of the move go)."""
        used = self.db.one("""SELECT COUNT(*) AS n FROM membership_uses u JOIN memberships m ON m.id=u.membership_id
                              WHERE m.invoice_id=? AND u.invoice_id<>?""", (iid, iid))["n"]
        if used:
            raise ValueError("Этим счётом продан абонемент, и по нему уже были услуги. Сначала уберите услуги «по абонементу» из других счетов.")
        for g in {r["link_id"] for r in self.db.q("SELECT link_id FROM payments WHERE invoice_id=? AND kind='deposit_use'", (iid,))}:
            rows = self.db.q("SELECT id, invoice_id FROM payments WHERE link_id=? AND kind='deposit_use'", (g,))
            with self.db.tx() as c:
                c.execute("DELETE FROM payments WHERE link_id=? AND kind='deposit_use'", (g,))
            for r in rows:
                if r["invoice_id"] and r["invoice_id"] != iid:
                    self._status(r["invoice_id"])

    def after_invoice_delete(self, iid):
        with self.db.tx() as c:
            c.execute("DELETE FROM membership_uses WHERE invoice_id=?", (iid,))
            c.execute("DELETE FROM memberships WHERE invoice_id=?", (iid,))
            c.execute("DELETE FROM pay_schedules WHERE id=?", (iid,))

    # ============================================================ schedules --
    def _paid(self, iid):
        return round(self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE invoice_id=?", (iid,))["s"], 2)

    def _lay(self, items, total, paid, today=None):
        """Status of every planned payment: what the payments made so far cover, in date order."""
        today = today or date.today().isoformat()
        out, cum, left_paid = [], 0.0, paid
        for it in sorted(items, key=lambda x: x["date"]):
            amt = round(float(it["amount"]), 2)
            cum += amt
            covered = round(max(0.0, min(amt, left_paid)), 2)
            left_paid = round(left_paid - covered, 2)
            left = round(amt - covered, 2)
            st = "paid" if left < 0.009 else ("late" if it["date"] < today else ("part" if covered > 0.009 else "wait"))
            out.append({"date": it["date"], "amount": amt, "paid": covered, "left": left, "status": st})
        return out

    def schedule(self, invoice_id) -> dict | None:
        s = self.db.one("SELECT * FROM pay_schedules WHERE id=?", (invoice_id,))
        if not s:
            return None
        inv = self.db.one("SELECT total FROM invoices WHERE id=?", (invoice_id,))
        if not inv:
            return None
        paid = self._paid(invoice_id)
        items = self._lay(json.loads(s["items"] or "[]"), inv["total"], paid)
        nxt = next((x for x in items if x["status"] != "paid"), None)
        late = [x for x in items if x["status"] == "late"]
        return {**s, "items": items, "total": round(inv["total"], 2), "paid": paid, "left": round(inv["total"] - paid, 2),
                "next": nxt, "overdue": round(sum(x["left"] for x in late), 2), "late_since": late[0]["date"] if late else None}

    def schedule_save(self, f, who="") -> dict:
        f = f or {}
        inv, due = self._due(f.get("invoice_id"))
        if inv["insurer_id"]:
            raise ValueError("Счёт оплачивает страховая — рассрочка не нужна")
        raw = f.get("items") or []
        items = []
        for i, it in enumerate(raw, 1):
            d = _day(it.get("date"), f"Платёж {i}")
            a = _money(it.get("amount"), f"Платёж {i}")
            if a <= 0:
                raise ValueError(f"Платёж {i}: сумма должна быть больше нуля")
            items.append({"date": d, "amount": a})
        if len(items) < 2:
            raise ValueError("В графике нужно хотя бы два платежа")
        if len(items) > 60:
            raise ValueError("Не больше 60 платежей")
        if len({x["date"] for x in items}) != len(items):
            raise ValueError("Два платежа в один день — объедините их")
        s = round(sum(x["amount"] for x in items), 2)
        if abs(s - round(inv["total"], 2)) > 0.01:
            raise ValueError(f"Сумма платежей {_rub(s)} должна быть равна сумме счёта {_rub(inv['total'])}")
        items.sort(key=lambda x: x["date"])
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM pay_schedules WHERE id=?", (inv["id"],)).fetchone():
                c.execute("UPDATE pay_schedules SET items=?, note=?, updated_at=? WHERE id=?",
                          (json.dumps(items), str(f.get("note") or "")[:300], _now(), inv["id"]))
            else:
                c.execute("""INSERT INTO pay_schedules(id, invoice_id, patient_id, items, note, created_at, created_by, updated_at)
                             VALUES(?,?,?,?,?,?,?,?)""", (inv["id"], inv["id"], inv["patient_id"], json.dumps(items),
                                                         str(f.get("note") or "")[:300], _now(), who or "", _now()))
        return self.schedule(inv["id"])

    @staticmethod
    def schedule_draft(total, paid=0, count=3, first=None, step="month") -> list[dict]:
        """Equal payments; what is paid already is the first one (today)."""
        total, paid, count = round(float(total), 2), round(float(paid or 0), 2), max(2, min(60, int(count)))
        start = date.fromisoformat(first) if first else date.today()
        out = []
        n = count - (1 if paid > 0.009 else 0)
        rest = round(total - paid, 2)
        if paid > 0.009:
            out.append({"date": date.today().isoformat(), "amount": paid})
        part = round(rest / n, 2) if n else 0
        for i in range(n):
            d = _months(start, i) if step == "month" else start + timedelta(days=14 * i)
            amt = part if i < n - 1 else round(rest - part * (n - 1), 2)
            out.append({"date": d.isoformat(), "amount": amt})
        if paid > 0.009 and out[1]["date"] <= out[0]["date"]:
            out[1:] = [{"date": (_months(date.fromisoformat(x["date"]), 1) if step == "month"
                                 else date.fromisoformat(x["date"]) + timedelta(days=14)).isoformat(), "amount": x["amount"]} for x in out[1:]]
        return out

    def schedule_delete(self, invoice_id):
        with self.db.tx() as c:
            c.execute("DELETE FROM pay_schedules WHERE id=?", (invoice_id,))
        return True

    def schedules(self, pid=None) -> list[dict]:
        rows = self.db.q("SELECT id FROM pay_schedules" + (" WHERE patient_id=?" if pid else ""), (pid,) if pid else ())
        out = []
        for r in rows:
            s = self.schedule(r["id"])
            if s:
                out.append(s)
        return out

    def overdue(self) -> list[dict]:
        """Installments whose date has passed and that are not paid in full."""
        out = []
        for s in self.schedules():
            if s["overdue"] < 0.009:
                continue
            p = self.db.one("SELECT name, phone FROM patients WHERE id=?", (s["patient_id"],)) or {}
            out.append({"invoice_id": s["invoice_id"], "patient_id": s["patient_id"], "name": p.get("name") or "",
                        "phone": p.get("phone") or "", "due": s["late_since"], "amount": s["overdue"], "left": s["left"],
                        "days": (date.today() - date.fromisoformat(s["late_since"])).days,
                        "next": s["next"]["date"] if s["next"] else None})
        out.sort(key=lambda x: x["due"])
        return out

    def not_due(self) -> dict:
        """Per patient: the part of debts that is in a schedule and whose date has not come yet."""
        out = {}
        for s in self.schedules():
            v = round(sum(x["left"] for x in s["items"] if x["status"] in ("wait", "part")), 2)
            if v > 0.009:
                out[s["patient_id"]] = round(out.get(s["patient_id"], 0) + v, 2)
        return out

    # ========================================================== memberships --
    def mtypes(self, all_=False) -> list[dict]:
        rows = self.db.q("SELECT * FROM membership_types" + ("" if all_ else " WHERE active=1") + " ORDER BY name")
        for r in rows:
            r["items"] = json.loads(r["items"] or "[]")
        return rows

    def mtype_save(self, f) -> dict:
        f = f or {}
        name = " ".join(str(f.get("name") or "").split())[:120]
        if not name:
            raise ValueError("Назовите абонемент, например «Профгигиена 2 раза в год»")
        items = []
        for it in f.get("items") or []:
            title = " ".join(str(it.get("title") or "").split())[:200]
            sid = str(it.get("service_id") or "") or None
            if sid and not title:
                s = self.db.one("SELECT title FROM services WHERE id=?", (sid,))
                title = s["title"] if s else ""
            if not title:
                continue
            try:
                qty = int(float(it.get("qty") or 1))
            except (TypeError, ValueError):
                raise ValueError("Количество: введите число") from None
            if not 1 <= qty <= 100:
                raise ValueError("Количество услуги — от 1 до 100")
            items.append({"service_id": sid, "title": title, "qty": qty})
        if not items:
            raise ValueError("Добавьте в абонемент хотя бы одну услугу из прайса")
        price = _money(f.get("price"), "Цена")
        if price <= 0:
            raise ValueError("Укажите цену абонемента")
        try:
            months = int(f.get("months") or 12)
        except (TypeError, ValueError):
            raise ValueError("Срок действия: введите число месяцев") from None
        if not 1 <= months <= 60:
            raise ValueError("Срок действия — от 1 до 60 месяцев")
        mid = f.get("id") or _id("MT")
        vals = (name, json.dumps(items, ensure_ascii=False), price, months, str(f.get("note") or "")[:300],
                0 if f.get("active") is False else 1, _now())
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM membership_types WHERE id=?", (mid,)).fetchone():
                c.execute("UPDATE membership_types SET name=?, items=?, price=?, months=?, note=?, active=?, updated_at=? WHERE id=?",
                          (*vals, mid))
            else:
                c.execute("INSERT INTO membership_types(id, name, items, price, months, note, active, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                          (mid, *vals))
        return next(x for x in self.mtypes(True) if x["id"] == mid)

    def mtype_delete(self, mid):
        """Sold memberships keep working; the type just is not offered any more."""
        with self.db.tx() as c:
            c.execute("UPDATE membership_types SET active=0, updated_at=? WHERE id=?", (_now(), mid))
        return True

    def membership_sell(self, f, who="") -> dict:
        f = f or {}
        t = self.db.one("SELECT * FROM membership_types WHERE id=? AND active=1", (f.get("type_id"),))
        if not t:
            raise ValueError("Абонемент не найден")
        pid = f.get("patient_id")
        self._patient(pid)
        if not self.local:
            raise ValueError("Нет модуля счетов")
        price = _money(f.get("price") if f.get("price") not in (None, "") else t["price"], "Цена")
        if price <= 0:
            raise ValueError("Укажите цену абонемента")
        mid = _id("MB")
        iid = self.local.save_invoice({"patient_id": pid, "doctor_id": f.get("doctor_id") or None,
                                       "items": [{"title": f"Абонемент «{t['name']}»", "price": price, "qty": 1, "discount": 0,
                                                  "code": "", "membership_sale": mid}],
                                       "comment": "Продажа абонемента"})
        sold = date.today()
        expires = _months(sold, int(t["months"])).isoformat()
        with self.db.tx() as c:
            c.execute("""INSERT INTO memberships(id, type_id, patient_id, name, items, price, invoice_id, sold_at, sold_by, expires, status, note)
                         VALUES(?,?,?,?,?,?,?,?,?,?, 'active', ?)""",
                      (mid, t["id"], pid, t["name"], t["items"], price, iid, _now(), who or "", expires, str(f.get("note") or "")[:300]))
        return {"membership": self.membership(mid), "invoice_id": iid}

    def _uses(self, mid, exclude_invoice=None):
        sql, args = "SELECT service_id, title, SUM(qty) AS n FROM membership_uses WHERE membership_id=?", [mid]
        if exclude_invoice:
            sql += " AND invoice_id<>?"
            args.append(exclude_invoice)
        out = {}
        for r in self.db.q(sql + " GROUP BY service_id, title", args):
            out[r["service_id"] or r["title"]] = out.get(r["service_id"] or r["title"], 0) + (r["n"] or 0)
        return out

    def membership(self, mid) -> dict | None:
        m = self.db.one("""SELECT m.*, i.status AS invoice_status FROM memberships m LEFT JOIN invoices i ON i.id=m.invoice_id
                           WHERE m.id=?""", (mid,))
        if not m:
            return None
        used = self._uses(mid)
        items = []
        for it in json.loads(m["items"] or "[]"):
            u = used.get(it.get("service_id") or it["title"], 0)
            items.append({**it, "used": u, "left": max(0, it["qty"] - u)})
        m["items"] = items
        m["expired"] = bool(m["expires"] and m["expires"] < date.today().isoformat())
        m["active"] = m["status"] == "active" and not m["expired"] and any(x["left"] > 0 for x in items)
        m["paid"] = m["invoice_status"] == "Оплачен"
        return m

    def memberships(self, pid, active_only=False) -> list[dict]:
        out = [self.membership(r["id"]) for r in self.db.q("SELECT id FROM memberships WHERE patient_id=? ORDER BY sold_at DESC", (pid,))]
        return [m for m in out if m and (m["active"] or not active_only)]

    def membership_cancel(self, mid):
        with self.db.tx() as c:
            if not c.execute("UPDATE memberships SET status='cancelled' WHERE id=?", (mid,)).rowcount:
                raise ValueError("Абонемент не найден")
        return self.membership(mid)

    @staticmethod
    def _match(it, m_item):
        if it.get("service_id") and m_item.get("service_id"):
            return it["service_id"] == m_item["service_id"]
        return str(it.get("title") or "").strip().lower() == str(m_item.get("title") or "").strip().lower()

    def check_uses(self, inv: dict):
        """Lines «по абонементу»: the membership is the patient's, valid and has visits left. Such lines cost 0."""
        want = {}
        for it in inv.get("items") or []:
            mid = it.get("membership")
            if not mid:
                continue
            m = self.membership(mid)
            if not m or m["patient_id"] != inv.get("patient_id"):
                raise ValueError("Абонемент не найден у этого пациента")
            if m["status"] != "active":
                raise ValueError(f"Абонемент «{m['name']}» аннулирован")
            if m["expired"]:
                raise ValueError(f"Срок абонемента «{m['name']}» истёк {_fmt(m['expires'])}")
            mi = next((x for x in m["items"] if self._match(it, x)), None)
            if not mi:
                raise ValueError(f"Услуга «{it.get('title')}» не входит в абонемент «{m['name']}»")
            key = (mid, mi.get("service_id") or mi["title"])
            want[key] = want.get(key, 0) + float(it.get("qty") or 1)
            it["discount"] = 100
        for (mid, key), n in want.items():
            m = self.membership(mid)
            mi = next(x for x in m["items"] if (x.get("service_id") or x["title"]) == key)
            used = self._uses(mid, inv.get("id")).get(key, 0)
            if used + n > mi["qty"] + 1e-9:
                raise ValueError(f"По абонементу «{m['name']}» осталось «{mi['title']}»: {max(0, mi['qty'] - used):g}")

    def write_uses(self, iid, items):
        with self.db.tx() as c:
            c.execute("DELETE FROM membership_uses WHERE invoice_id=?", (iid,))
            for i, it in enumerate(items or []):
                if it.get("membership"):
                    c.execute("""INSERT INTO membership_uses(id, membership_id, invoice_id, service_id, title, qty, at)
                                 VALUES(?,?,?,?,?,?,?)""",
                              (f"{iid}:{i}", it["membership"], iid, it.get("service_id"), it.get("title") or "",
                               float(it.get("qty") or 1), _now()))

    # ============================================================ cash shifts --
    def _shift_numbers(self, sh) -> dict:
        a, b = sh["opened_at"], sh["closed_at"] or "9999"
        def pays(method):
            return round(self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE method=? AND created_at>=? AND created_at<=?",
                                     (method, a, b))["s"], 2)
        def certs(method):
            return round(self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM certificates WHERE method=? AND sold_at>=? AND sold_at<=?",
                                     (method, a, b))["s"], 2) if self._has("certificates") else 0.0
        refunds = round(self.db.one("""SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE kind='refund' AND method=?
                                       AND created_at>=? AND created_at<=?""", (CASH, a, b))["s"], 2)
        moves = self.db.q("SELECT * FROM cash_moves WHERE shift_id=? ORDER BY at", (sh["id"],))
        m_in = round(sum(m["amount"] for m in moves if m["kind"] == "in"), 2)
        m_out = round(sum(m["amount"] for m in moves if m["kind"] == "out"), 2)
        cash = pays(CASH)
        cert_cash = certs(CASH)
        expected = round((sh["open_cash"] or 0) + cash + cert_cash + m_in - m_out, 2)
        card = round(pays(CARD) + certs(CARD), 2)
        sbp = round(pays(SBP) + certs(SBP), 2)
        n = self.db.one("SELECT COUNT(*) AS n FROM payments WHERE created_at>=? AND created_at<=? AND amount>0 AND COALESCE(kind,'')=''",
                        (a, b))["n"]
        return {"cash_in": round(cash - refunds, 2), "refunds_cash": round(-refunds, 2), "cert_cash": cert_cash, "moves_in": m_in,
                "moves_out": m_out, "expected_cash": expected, "card": card, "sbp": sbp, "moves": moves, "payments": n}

    def _has(self, table):
        return bool(self.db.one("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name=?", (table,)))

    def shift(self, sid) -> dict | None:
        sh = self.db.one("SELECT * FROM cash_shifts WHERE id=?", (sid,))
        if not sh:
            return None
        sh.update(self._shift_numbers(sh))
        if sh["status"] == "closed":
            sh["diff_cash"] = round((sh["counted_cash"] or 0) - (sh["expected_cash"] or 0), 2)
            sh["diff_card"] = None if sh["card_terminal"] is None else round(sh["card_terminal"] - (sh["card_expected"] or 0), 2)
            sh["diff_sbp"] = None if sh["sbp_bank"] is None else round(sh["sbp_bank"] - (sh["sbp_expected"] or 0), 2)
        return sh

    def shift_current(self) -> dict:
        r = self.db.one("SELECT id FROM cash_shifts WHERE status='open' ORDER BY opened_at DESC LIMIT 1")
        last = self.db.one("SELECT counted_cash, closed_at, closed_by FROM cash_shifts WHERE status='closed' ORDER BY closed_at DESC LIMIT 1")
        return {"shift": self.shift(r["id"]) if r else None, "last_left": round(last["counted_cash"] or 0, 2) if last else 0.0,
                "last_closed": last["closed_at"] if last else None, "in_reasons": MOVE_IN, "out_reasons": MOVE_OUT}

    def shift_open(self, f, who="") -> dict:
        f = f or {}
        cur = self.shift_current()["shift"]
        if cur:
            raise ValueError(f"Смена уже открыта: {_fmt(cur['opened_at'])} {cur['opened_at'][11:16]}, {cur['opened_by'] or ''}".rstrip(", "))
        cash = _money(f.get("open_cash"), "Остаток в кассе")
        if cash < 0:
            raise ValueError("Остаток не может быть меньше нуля")
        sid = _id("SH")
        with self.db.tx() as c:
            c.execute("""INSERT INTO cash_shifts(id, opened_at, opened_by, open_cash, note, status) VALUES(?,?,?,?,?, 'open')""",
                      (sid, _now(), who or "", cash, str(f.get("note") or "")[:300]))
        return self.shift(sid)

    def shift_move(self, f, who="", expense_id=None) -> dict:
        f = f or {}
        cur = self.shift_current()["shift"]
        if not cur:
            raise ValueError("Сначала откройте смену")
        kind = f.get("kind") if f.get("kind") in ("in", "out") else None
        if not kind:
            raise ValueError("Выберите: внести или изъять")
        amount = _money(f.get("amount"))
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        reason = " ".join(str(f.get("reason") or "").split())[:80]
        if not reason:
            raise ValueError("Укажите, зачем")
        if kind == "out" and amount > cur["expected_cash"] + 0.009:
            raise ValueError(f"В кассе по расчёту {_rub(cur['expected_cash'])} — столько изъять нельзя")
        with self.db.tx() as c:
            c.execute("""INSERT INTO cash_moves(id, shift_id, at, kind, amount, reason, comment, by, expense_id)
                         VALUES(?,?,?,?,?,?,?,?,?)""", (_id("CM"), cur["id"], _now(), kind, amount, reason,
                                                       str(f.get("comment") or "").strip()[:300], who or "", expense_id))
        return self.shift(cur["id"])

    def shift_close(self, f, who="") -> dict:
        f = f or {}
        cur = self.shift_current()["shift"]
        if not cur:
            raise ValueError("Открытой смены нет")
        if f.get("counted_cash") in (None, ""):
            raise ValueError("Пересчитайте наличные в кассе и введите сумму")
        counted = _money(f.get("counted_cash"), "Наличные в кассе")
        if counted < 0:
            raise ValueError("Сумма не может быть меньше нуля")
        card_t = None if f.get("card_terminal") in (None, "") else _money(f.get("card_terminal"), "Итог терминала")
        sbp_b = None if f.get("sbp_bank") in (None, "") else _money(f.get("sbp_bank"), "СБП по выписке")
        at = _now()
        sh = {**cur, "closed_at": at}
        nums = self._shift_numbers(sh)
        with self.db.tx() as c:
            c.execute("""UPDATE cash_shifts SET closed_at=?, closed_by=?, expected_cash=?, counted_cash=?, card_expected=?, card_terminal=?,
                         sbp_expected=?, sbp_bank=?, note=?, status='closed' WHERE id=?""",
                      (at, who or "", nums["expected_cash"], counted, nums["card"], card_t, nums["sbp"], sbp_b,
                       str(f.get("note") or cur.get("note") or "")[:300], cur["id"]))
        return self.shift(cur["id"])

    def shifts(self, limit=40) -> list[dict]:
        return [self.shift(r["id"]) for r in self.db.q("SELECT id FROM cash_shifts ORDER BY opened_at DESC LIMIT ?", (int(limit),))]

    # ============================================================= insurance --
    def insurers(self, all_=False) -> list[dict]:
        rows = self.db.q("SELECT * FROM insurers" + ("" if all_ else " WHERE active=1") + " ORDER BY name")
        return rows

    def insurer_save(self, f) -> dict:
        f = f or {}
        name = " ".join(str(f.get("name") or "").split())[:150]
        if not name:
            raise ValueError("Укажите название страховой компании")
        email = str(f.get("email") or "").strip()[:120]
        if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("Электронная почта указана неверно")
        iid = f.get("id") or _id("IN")
        vals = (name, str(f.get("contract") or "").strip()[:150], str(f.get("phone") or "").strip()[:40], email,
                str(f.get("note") or "").strip()[:300], 0 if f.get("active") is False else 1, _now())
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM insurers WHERE id=?", (iid,)).fetchone():
                c.execute("UPDATE insurers SET name=?, contract=?, phone=?, email=?, note=?, active=?, updated_at=? WHERE id=?", (*vals, iid))
            else:
                c.execute("INSERT INTO insurers(id, name, contract, phone, email, note, active, updated_at) VALUES(?,?,?,?,?,?,?,?)", (iid, *vals))
        return self.db.one("SELECT * FROM insurers WHERE id=?", (iid,))

    def ins_docs(self, pid) -> list[dict]:
        rows = self.db.q("""SELECT d.*, s.name AS insurer_name FROM insurance_docs d LEFT JOIN insurers s ON s.id=d.insurer_id
                            WHERE d.patient_id=? ORDER BY d.created_at DESC""", (pid,))
        today = date.today().isoformat()
        for r in rows:
            r["used"] = round(self.db.one("SELECT COALESCE(SUM(total),0) AS s FROM invoices WHERE ins_doc_id=?", (r["id"],))["s"], 2)
            r["expired"] = bool(r["valid_to"] and r["valid_to"] < today)
            r["left"] = None if not r["limit_sum"] else round(r["limit_sum"] - r["used"], 2)
            r["kind_title"] = DOC_KINDS.get(r["kind"], r["kind"])
        return rows

    def ins_doc_save(self, f) -> dict:
        f = f or {}
        self._patient(f.get("patient_id"))
        if not self.db.one("SELECT 1 AS x FROM insurers WHERE id=?", (f.get("insurer_id"),)):
            raise ValueError("Выберите страховую компанию")
        kind = f.get("kind") if f.get("kind") in DOC_KINDS else "policy"
        number = " ".join(str(f.get("number") or "").split())[:60]
        if not number:
            raise ValueError("Укажите номер полиса или гарантийного письма")
        lim = None if f.get("limit_sum") in (None, "", 0, "0") else _money(f.get("limit_sum"), "Лимит")
        if lim is not None and lim < 0:
            raise ValueError("Лимит не может быть меньше нуля")
        did = f.get("id") or _id("ID")
        vals = (f["patient_id"], f["insurer_id"], kind, number, _day(f.get("date"), "Дата", False), _day(f.get("valid_to"), "Действует до", False),
                lim, str(f.get("note") or "").strip()[:300])
        with self.db.tx() as c:
            if c.execute("SELECT 1 FROM insurance_docs WHERE id=?", (did,)).fetchone():
                c.execute("UPDATE insurance_docs SET patient_id=?, insurer_id=?, kind=?, number=?, date=?, valid_to=?, limit_sum=?, note=? WHERE id=?",
                          (*vals, did))
            else:
                c.execute("""INSERT INTO insurance_docs(id, patient_id, insurer_id, kind, number, date, valid_to, limit_sum, note, created_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""", (did, *vals, _now()))
        return next(d for d in self.ins_docs(f["patient_id"]) if d["id"] == did)

    def ins_doc_delete(self, did):
        if self.db.one("SELECT 1 AS x FROM invoices WHERE ins_doc_id=?", (did,)):
            raise ValueError("По этому документу уже есть счета — его нельзя удалить")
        with self.db.tx() as c:
            c.execute("DELETE FROM insurance_docs WHERE id=?", (did,))
        return True

    def check_payer(self, inv: dict, total=None):
        """An invoice for the insurance company: the policy or letter is the patient's, the letter's limit holds."""
        ins = inv.get("insurer_id") or None
        if not ins:
            return
        if not self.db.one("SELECT 1 AS x FROM insurers WHERE id=?", (ins,)):
            raise ValueError("Страховая компания не найдена")
        did = inv.get("ins_doc_id") or None
        if not did:
            raise ValueError("Выберите полис или гарантийное письмо пациента")
        d = self.db.one("SELECT * FROM insurance_docs WHERE id=?", (did,))
        if not d or d["patient_id"] != inv.get("patient_id") or d["insurer_id"] != ins:
            raise ValueError("Полис или гарантийное письмо не принадлежит этому пациенту и страховой")
        if d["valid_to"] and d["valid_to"] < date.today().isoformat():
            raise ValueError(f"{DOC_KINDS.get(d['kind'], 'Документ')} № {d['number']} действовал до {_fmt(d['valid_to'])}")
        if d["limit_sum"] and total is not None:
            used = self.db.one("SELECT COALESCE(SUM(total),0) AS s FROM invoices WHERE ins_doc_id=? AND id<>?", (did, inv.get("id") or ""))["s"]
            if used + total > d["limit_sum"] + 0.009:
                raise ValueError(f"Лимит гарантийного письма № {d['number']} — {_rub(d['limit_sum'])}, "
                                 f"осталось {_rub(max(0, d['limit_sum'] - used))}")

    def set_payer(self, iid, insurer_id=None, ins_doc_id=None):
        with self.db.tx() as c:
            c.execute("UPDATE invoices SET insurer_id=?, ins_doc_id=? WHERE id=?", (insurer_id or None, ins_doc_id if insurer_id else None, iid))

    def _in_registries(self):
        out = set()
        for r in self.db.q("SELECT invoice_ids FROM insurance_registries"):
            out.update(json.loads(r["invoice_ids"] or "[]"))
        return out

    def ins_invoices(self, insurer_id, date_from=None, date_to=None, free_only=True) -> list[dict]:
        sql = f"""SELECT i.id, i.patient_id, i.created_at, i.total, i.items, i.ins_doc_id, p.name AS patient_name, d.name AS doctor_name,
                         (SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=i.id) AS paid,
                         x.number AS doc_number, x.kind AS doc_kind
                  FROM invoices i LEFT JOIN patients p ON p.id=i.patient_id LEFT JOIN doctors d ON d.id=i.doctor_id
                  LEFT JOIN insurance_docs x ON x.id=i.ins_doc_id WHERE {INV} AND i.insurer_id=?"""
        args = [insurer_id]
        if date_from:
            sql += " AND substr(i.created_at,1,10)>=?"
            args.append(date_from)
        if date_to:
            sql += " AND substr(i.created_at,1,10)<=?"
            args.append(date_to)
        rows = self.db.q(sql + " ORDER BY i.created_at", args)
        busy = self._in_registries() if free_only else set()
        out = []
        for r in rows:
            if free_only and (r["id"] in busy or r["paid"] >= r["total"] - 0.009):
                continue
            r["items"] = json.loads(r["items"] or "[]")
            out.append(r)
        return out

    def ins_summary(self) -> dict:
        busy = self._in_registries()
        rows = []
        for s in self.insurers(True):
            inv = self.ins_invoices(s["id"], free_only=False)
            billed = round(sum(x["total"] for x in inv), 2)
            paid = round(sum(min(x["paid"], x["total"]) for x in inv), 2)
            rows.append({**s, "billed": billed, "paid": paid, "due": round(billed - paid, 2),
                         "free": sum(1 for x in inv if x["id"] not in busy and x["paid"] < x["total"] - 0.009)})
        return {"insurers": rows, "total_due": round(sum(x["due"] for x in rows), 2)}

    def registry_make(self, f, who="") -> dict:
        f = f or {}
        ins = self.db.one("SELECT * FROM insurers WHERE id=?", (f.get("insurer_id"),))
        if not ins:
            raise ValueError("Выберите страховую компанию")
        a, b = _day(f.get("date_from"), "Начало периода"), _day(f.get("date_to"), "Конец периода")
        if a > b:
            raise ValueError("Начало периода позже конца")
        inv = self.ins_invoices(ins["id"], a, b)
        if not inv:
            raise ValueError("За этот период нет счетов для страховой, которые ещё не вошли в реестр")
        n = self.db.one("SELECT COUNT(*) AS n FROM insurance_registries WHERE insurer_id=?", (ins["id"],))["n"] + 1
        rid = _id("RG")
        number = f"{b[:7].replace('-', '')}-{n}"
        total = round(sum(x["total"] - x["paid"] for x in inv), 2)
        with self.db.tx() as c:
            c.execute("""INSERT INTO insurance_registries(id, insurer_id, number, date_from, date_to, invoice_ids, total, status, created_at,
                         created_by, note) VALUES(?,?,?,?,?,?,?, 'draft', ?,?,?)""",
                      (rid, ins["id"], number, a, b, json.dumps([x["id"] for x in inv]), total, _now(), who or "",
                       str(f.get("note") or "")[:300]))
        return self.registry(rid)

    def registries(self, insurer_id=None) -> list[dict]:
        sql = "SELECT r.*, s.name AS insurer_name FROM insurance_registries r LEFT JOIN insurers s ON s.id=r.insurer_id"
        rows = self.db.q(sql + (" WHERE r.insurer_id=?" if insurer_id else "") + " ORDER BY r.created_at DESC", (insurer_id,) if insurer_id else ())
        for r in rows:
            r["count"] = len(json.loads(r["invoice_ids"] or "[]"))
            r["status_title"] = REG_STATUS.get(r["status"], r["status"])
        return rows

    def registry(self, rid) -> dict:
        r = self.db.one("SELECT r.*, s.name AS insurer_name, s.contract FROM insurance_registries r LEFT JOIN insurers s ON s.id=r.insurer_id "
                        "WHERE r.id=?", (rid,))
        if not r:
            raise ValueError("Реестр не найден")
        ids = json.loads(r["invoice_ids"] or "[]")
        rows = []
        for iid in ids:
            x = self.db.one(f"""SELECT i.id, i.patient_id, i.created_at, i.total, i.items, p.name AS patient_name, p.birth,
                                     d.name AS doctor_name, x.number AS doc_number, x.kind AS doc_kind,
                                     (SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=i.id) AS paid
                                FROM invoices i LEFT JOIN patients p ON p.id=i.patient_id LEFT JOIN doctors d ON d.id=i.doctor_id
                                LEFT JOIN insurance_docs x ON x.id=i.ins_doc_id WHERE i.id=?""", (iid,))
            if x:
                x["items"] = json.loads(x["items"] or "[]")
                rows.append(x)
        r["rows"] = rows
        r["status_title"] = REG_STATUS.get(r["status"], r["status"])
        return r

    def registry_status(self, rid, status):
        if status not in ("draft", "sent"):
            raise ValueError("Неизвестный статус")
        r = self.registry(rid)
        if r["status"] == "paid":
            raise ValueError("Реестр уже оплачен")
        with self.db.tx() as c:
            c.execute("UPDATE insurance_registries SET status=?, sent_at=? WHERE id=?", (status, _now() if status == "sent" else None, rid))
        return self.registry(rid)

    def registry_pay(self, rid, f=None, who="") -> dict:
        """The company paid the registry. Invoices it refused (`rejected`) go to the patient: they pay themselves."""
        f = f or {}
        r = self.registry(rid)
        if r["status"] == "paid":
            raise ValueError("Реестр уже оплачен")
        rejected = set(f.get("rejected") or [])
        at = _now()
        paid_total, keep = 0.0, []
        with self.db.tx() as c:
            for x in r["rows"]:
                if x["id"] in rejected:
                    c.execute("UPDATE invoices SET insurer_id=NULL, ins_doc_id=NULL, comment=TRIM(COALESCE(comment,'') || ' Страховая отказала в оплате.') "
                              "WHERE id=?", (x["id"],))
                    continue
                keep.append(x["id"])
                due = round(x["total"] - x["paid"], 2)
                if due > 0.009:
                    c.execute("""INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at, kind, link_id)
                                 VALUES(?,?,?,?,?,?,?,?,?)""", (_id("P"), x["id"], x["patient_id"], due, INSURANCE,
                                                               f"реестр {r['number']} {r['insurer_name'] or ''}".strip(), at, "insurance", rid))
                    paid_total += due
            c.execute("UPDATE insurance_registries SET status='paid', paid_at=?, paid_total=?, invoice_ids=?, total=? WHERE id=?",
                      (at, round(paid_total, 2), json.dumps(keep), round(paid_total, 2), rid))
        for x in r["rows"]:
            self._status(x["id"])
        return self.registry(rid)

    def registry_delete(self, rid):
        r = self.registry(rid)
        if r["status"] == "paid":
            raise ValueError("Оплаченный реестр удалить нельзя")
        with self.db.tx() as c:
            c.execute("DELETE FROM insurance_registries WHERE id=?", (rid,))
        return True

    def registry_table(self, rid) -> tuple[str, list, list]:
        r = self.registry(rid)
        head = ["№", "Пациент", "Дата рождения", "Полис / гарантийное письмо", "Дата услуги", "Врач", "Код", "Услуга", "Зуб",
                "Кол-во", "Цена", "Скидка, %", "Сумма"]
        rows, n = [], 0
        for x in r["rows"]:
            n += 1
            doc = f"{DOC_KINDS.get(x['doc_kind'], '')} № {x['doc_number']}".strip() if x["doc_number"] else ""
            for j, it in enumerate(x["items"]):
                rows.append([n if j == 0 else "", x["patient_name"] if j == 0 else "", _fmt(x["birth"]) if j == 0 and x["birth"] else "",
                             doc if j == 0 else "", _fmt(x["created_at"]), x["doctor_name"] or "", it.get("code") or "", it.get("title") or "",
                             it.get("tooth") or "", it.get("qty") or 1, it.get("price") or 0, it.get("discount") or 0, it.get("sum") or 0])
        rows.append(["", "Итого", "", "", "", "", "", "", "", "", "", "", round(sum(x["total"] for x in r["rows"]), 2)])
        return f"Реестр {r['number']}", head, rows
