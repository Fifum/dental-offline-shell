"""Loyalty: gift certificates, bonus points and family groups with a shared bonus account and a discount.

Certificates: sold for money (the sale is shown in the day's cash), redeemed as a payment method
«Сертификат» with the certificate's code; the balance goes down and comes back if the payment is deleted.

Bonuses: a percent of every money payment is credited (off until the clinic sets the percent); bonuses pay
a part of an invoice («Бонусы», at most `max_share` percent of it). A family shares one bonus account.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS certificates(
    id TEXT PRIMARY KEY, code TEXT UNIQUE, amount REAL, balance REAL, buyer TEXT, patient_id TEXT, method TEXT,
    sold_at TEXT, sold_by TEXT, expires TEXT, status TEXT DEFAULT 'active', note TEXT);
CREATE TABLE IF NOT EXISTS cert_moves(
    id INTEGER PRIMARY KEY AUTOINCREMENT, cert_id TEXT, payment_id TEXT, amount REAL, at TEXT);
CREATE TABLE IF NOT EXISTS bonus_moves(
    id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT, patient_id TEXT, amount REAL, kind TEXT, payment_id TEXT,
    comment TEXT, at TEXT, by TEXT);
CREATE INDEX IF NOT EXISTS ix_bonus_account ON bonus_moves(account);
CREATE TABLE IF NOT EXISTS families(id TEXT PRIMARY KEY, name TEXT, discount REAL DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS family_members(patient_id TEXT PRIMARY KEY, family_id TEXT, added_at TEXT);
"""
MONEY_METHODS = {"Наличные", "Карта", "Перевод", "СБП"}
CERT, BONUS = "Сертификат", "Бонусы"
DEFAULTS = {"bonus_percent": 0, "bonus_max_share": 30, "cert_months": 12}
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _money(v, what="Сумма"):
    try:
        x = round(float(str(v or 0).replace(",", ".").replace(" ", "")), 2)
    except ValueError:
        raise ValueError(f"{what} указана неверно") from None
    return x


def norm_code(code) -> str:
    c = "".join(ch for ch in str(code or "").upper() if ch.isalnum())
    return f"{c[:4]}-{c[4:8]}" if len(c) == 8 else c


def settings() -> dict:
    s = config.load_settings().get("loyalty") or {}
    return {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}


def save_settings(f) -> dict:
    cur = settings()
    for k, lo, hi in (("bonus_percent", 0, 30), ("bonus_max_share", 0, 100), ("cert_months", 1, 60)):
        if k in f and f[k] not in (None, ""):
            v = _money(f[k], "Значение")
            if not lo <= v <= hi:
                raise ValueError(f"Допустимо от {lo} до {hi}")
            cur[k] = v
    config.save_settings({"loyalty": cur})
    return cur


class Loyalty:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    # -------------------------------------------------------- certificates --
    def sell(self, f, who="") -> dict:
        amount = _money(f.get("amount"))
        if not 100 <= amount <= 1_000_000:
            raise ValueError("Номинал сертификата — от 100 до 1 000 000 ₽")
        method = f.get("method") if f.get("method") in MONEY_METHODS else "Наличные"
        months = int(settings()["cert_months"])
        expires = str(f.get("expires") or (date.today() + timedelta(days=round(months * 30.44))).isoformat())[:10]
        try:
            if date.fromisoformat(expires) <= date.today():
                raise ValueError("Срок действия должен быть в будущем")
        except ValueError as e:
            raise ValueError(str(e) if "будущем" in str(e) else "Срок действия указан неверно") from None
        pid = f.get("patient_id") or None
        if pid and not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Пациент не найден")
        for _ in range(20):
            code = "".join(secrets.choice(_ALPHABET) for _ in range(8))
            code = f"{code[:4]}-{code[4:]}"
            if not self.db.one("SELECT 1 AS x FROM certificates WHERE code=?", (code,)):
                break
        cid = "CT-" + uuid.uuid4().hex[:10]
        with self.db.tx() as c:
            c.execute("""INSERT INTO certificates(id, code, amount, balance, buyer, patient_id, method, sold_at, sold_by, expires, status, note)
                         VALUES(?,?,?,?,?,?,?,?,?,?, 'active', ?)""",
                      (cid, code, amount, amount, str(f.get("buyer") or "").strip()[:200], pid, method, _now(), who or "", expires,
                       str(f.get("note") or "")[:300]))
        return self.certificate(code)

    def certificate(self, code) -> dict:
        r = self.db.one("SELECT * FROM certificates WHERE code=?", (norm_code(code),))
        if not r:
            raise ValueError("Сертификат с таким номером не найден")
        r["expired"] = bool(r["expires"] and r["expires"] < date.today().isoformat())
        r["usable"] = r["status"] == "active" and not r["expired"] and r["balance"] > 0.009
        r["moves"] = self.db.q("""SELECT m.amount, m.at, p.name AS patient_name FROM cert_moves m LEFT JOIN payments pay ON pay.id=m.payment_id
                                  LEFT JOIN patients p ON p.id=pay.patient_id WHERE m.cert_id=? ORDER BY m.at""", (r["id"],))
        return r

    def certificates(self, status="active") -> dict:
        rows = self.db.q("SELECT * FROM certificates ORDER BY sold_at DESC")
        today = date.today().isoformat()
        for r in rows:
            r["expired"] = bool(r["expires"] and r["expires"] < today)
        if status == "active":
            rows = [r for r in rows if r["status"] == "active" and not r["expired"] and r["balance"] > 0.009]
        return {"rows": rows, "balance": round(sum(r["balance"] for r in rows if r["status"] == "active" and not r["expired"]), 2)}

    def check_redeem(self, code, amount) -> dict:
        c = self.certificate(code)
        if c["status"] != "active":
            raise ValueError("Сертификат аннулирован")
        if c["expired"]:
            raise ValueError(f"Срок действия сертификата истёк {c['expires'][8:10]}.{c['expires'][5:7]}.{c['expires'][:4]}")
        if amount > c["balance"] + 0.009:
            raise ValueError(f"На сертификате осталось {c['balance']:.2f} ₽")
        return c

    def redeem(self, code, amount, payment_id):
        c = self.check_redeem(code, amount)
        with self.db.tx() as cx:
            cx.execute("UPDATE certificates SET balance=ROUND(balance-?,2) WHERE id=?", (amount, c["id"]))
            cx.execute("INSERT INTO cert_moves(cert_id, payment_id, amount, at) VALUES(?,?,?,?)", (c["id"], payment_id, amount, _now()))

    def cancel_certificate(self, code) -> dict:
        c = self.certificate(code)
        with self.db.tx() as cx:
            cx.execute("UPDATE certificates SET status='cancelled' WHERE id=?", (c["id"],))
        return self.certificate(code)

    def sales_day(self, day) -> list[dict]:
        return self.db.q("SELECT code, amount, method, buyer, sold_at, sold_by FROM certificates WHERE substr(sold_at,1,10)=? ORDER BY sold_at", (day,))

    # ------------------------------------------------------------- families --
    def family_of(self, pid) -> dict | None:
        m = self.db.one("SELECT family_id FROM family_members WHERE patient_id=?", (pid,))
        if not m:
            return None
        f = self.db.one("SELECT * FROM families WHERE id=?", (m["family_id"],))
        if not f:
            return None
        f["members"] = self.db.q("""SELECT p.id, p.name FROM family_members m JOIN patients p ON p.id=m.patient_id
                                    WHERE m.family_id=? ORDER BY p.name""", (f["id"],))
        return f

    def save_family(self, f) -> dict:
        name = str(f.get("name") or "").strip()[:120]
        if not name:
            raise ValueError("Назовите семью, например «Ивановы»")
        disc = _money(f.get("discount"), "Скидка")
        if not 0 <= disc <= 50:
            raise ValueError("Семейная скидка — от 0 до 50 %")
        with self.db.tx() as c:
            fid = f.get("id")
            if fid:
                if not c.execute("UPDATE families SET name=?, discount=? WHERE id=?", (name, disc, fid)).rowcount:
                    raise ValueError("Семья не найдена")
            else:
                fid = "FM-" + uuid.uuid4().hex[:8]
                c.execute("INSERT INTO families(id, name, discount, created_at) VALUES(?,?,?,?)", (fid, name, disc, _now()))
            for pid in f.get("add") or []:
                if not c.execute("SELECT 1 FROM patients WHERE id=?", (pid,)).fetchone():
                    raise ValueError("Пациент не найден")
                other = c.execute("SELECT family_id FROM family_members WHERE patient_id=?", (pid,)).fetchone()
                if other and other[0] != fid:
                    raise ValueError("Пациент уже состоит в другой семье — сначала уберите его оттуда")
                c.execute("INSERT OR REPLACE INTO family_members(patient_id, family_id, added_at) VALUES(?,?,?)", (pid, fid, _now()))
                c.execute("UPDATE bonus_moves SET account=? WHERE account=?", (f"F:{fid}", f"P:{pid}"))  # own bonuses join the family's
        return self.db.one("SELECT * FROM families WHERE id=?", (fid,))

    def leave_family(self, pid) -> bool:
        """Leaves the family; the bonuses stay with the family."""
        with self.db.tx() as c:
            fam = c.execute("SELECT family_id FROM family_members WHERE patient_id=?", (pid,)).fetchone()
            if not fam:
                raise ValueError("Пациент не состоит в семье")
            c.execute("DELETE FROM family_members WHERE patient_id=?", (pid,))
            if not c.execute("SELECT 1 FROM family_members WHERE family_id=?", (fam[0],)).fetchone():
                # last member left: the family's bonuses move to them so nothing is lost
                c.execute("UPDATE bonus_moves SET account=? WHERE account=?", (f"P:{pid}", f"F:{fam[0]}"))
                c.execute("DELETE FROM families WHERE id=?", (fam[0],))
        return True

    # -------------------------------------------------------------- bonuses --
    def account(self, pid) -> str:
        m = self.db.one("SELECT family_id FROM family_members WHERE patient_id=?", (pid,))
        return f"F:{m['family_id']}" if m else f"P:{pid}"

    def bonus_balance(self, pid) -> float:
        return round(self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM bonus_moves WHERE account=?", (self.account(pid),))["s"], 2)

    def bonus_history(self, pid) -> list[dict]:
        return self.db.q("""SELECT b.*, p.name AS patient_name FROM bonus_moves b LEFT JOIN patients p ON p.id=b.patient_id
                            WHERE b.account=? ORDER BY b.at DESC LIMIT 200""", (self.account(pid),))

    def _move(self, pid, amount, kind, payment_id=None, comment="", who=""):
        with self.db.tx() as c:
            c.execute("INSERT INTO bonus_moves(account, patient_id, amount, kind, payment_id, comment, at, by) VALUES(?,?,?,?,?,?,?,?)",
                      (self.account(pid), pid, round(amount, 2), kind, payment_id, comment[:200], _now(), who or ""))

    def adjust(self, pid, amount, comment, who="") -> float:
        amount = _money(amount)
        if not amount:
            raise ValueError("Укажите, сколько бонусов начислить (или списать со знаком минус)")
        if not str(comment or "").strip():
            raise ValueError("Укажите причину")
        if self.bonus_balance(pid) + amount < -0.009:
            raise ValueError("Бонусов меньше, чем вы хотите списать")
        self._move(pid, amount, "manual", None, str(comment).strip(), who)
        return self.bonus_balance(pid)

    def check_spend(self, pid, invoice_id, amount):
        bal = self.bonus_balance(pid)
        if amount > bal + 0.009:
            raise ValueError(f"У пациента {bal:.2f} бонусов")
        share = float(settings()["bonus_max_share"])
        inv = self.db.one("SELECT total FROM invoices WHERE id=?", (invoice_id,)) if invoice_id else None
        if not inv:
            raise ValueError("Бонусами можно оплатить только счёт")
        spent = self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE invoice_id=? AND method=?", (invoice_id, BONUS))["s"]
        limit = round(inv["total"] * share / 100, 2)
        if spent + amount > limit + 0.009:
            raise ValueError(f"Бонусами можно оплатить не больше {share:g} % счёта — {max(0, limit - spent):.2f} ₽")

    def on_payment(self, payment, who=""):
        """After a payment is saved: spend or credit bonuses."""
        if payment["method"] == BONUS:
            self._move(payment["patient_id"], -payment["amount"], "spend", payment["id"], "Оплата бонусами", who)
        elif payment["method"] in MONEY_METHODS and payment.get("patient_id"):
            pct = float(settings()["bonus_percent"])
            if pct > 0:
                self._move(payment["patient_id"], payment["amount"] * pct / 100, "accrual", payment["id"], f"{pct:g} % от оплаты", who)

    def on_payment_deleted(self, payment_id):
        """A deleted payment gives back what it changed: bonuses and the certificate balance."""
        with self.db.tx() as c:
            c.execute("DELETE FROM bonus_moves WHERE payment_id=?", (payment_id,))
            for m in c.execute("SELECT id, cert_id, amount FROM cert_moves WHERE payment_id=?", (payment_id,)).fetchall():
                c.execute("UPDATE certificates SET balance=ROUND(balance+?,2) WHERE id=?", (m[2], m[1]))
                c.execute("DELETE FROM cert_moves WHERE id=?", (m[0],))
