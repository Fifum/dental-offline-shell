"""Fiscal receipts (54-FZ) through an online cash register.

Drivers:
  emulator  — test mode, no device; receipts are marked as not fiscal
  atol      — ATOL via the web server of driver DTO 10 (JSON tasks, http://<pc>:16732)
  shtrih    — Shtrih-M via its COM driver (DrvFR), on the computer the register is attached to

The payment is always saved first. A receipt that failed (no paper, shift over 24 h, device off)
stays in the list with the reason and can be printed again from the cash screen.
"""
from __future__ import annotations

import json
import random
import threading
import time
import uuid
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts(
    id TEXT PRIMARY KEY, kind TEXT, payment_id TEXT, invoice_id TEXT, patient_id TEXT, refund_of TEXT,
    items TEXT, payments TEXT, total REAL, contact TEXT, status TEXT, error TEXT, driver TEXT,
    fn TEXT, fd TEXT, fp TEXT, shift TEXT, number TEXT, fiscal_at TEXT, user_name TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_receipts_payment ON receipts(payment_id);
"""

DEFAULTS = {
    "enabled": False,
    "driver": "emulator",            # emulator | atol | shtrih
    "atol_url": "http://127.0.0.1:16732",
    "shtrih_password": 30,
    "taxation": "usnIncome",         # osn | usnIncome | usnIncomeOutcome | esn | patent
    "tax": "none",                   # VAT of medical services: usually "none" (exempt)
    "auto": True,                    # print a receipt when a payment is taken
    "cashier_inn": "",
}
TAXATION = {"osn": "ОСН", "usnIncome": "УСН доход", "usnIncomeOutcome": "УСН доход − расход", "esn": "ЕСХН", "patent": "Патент"}
TAXES = {"none": "Без НДС", "vat0": "НДС 0%", "vat5": "НДС 5%", "vat7": "НДС 7%", "vat10": "НДС 10%", "vat22": "НДС 22%"}
DRIVERS = {"emulator": "Тестовый режим (без кассы)", "atol": "АТОЛ (веб-сервер драйвера ДТО 10)", "shtrih": "Штрих-М (драйвер ККТ)"}
# how the clinic's payment methods map to receipt payment types; None = no receipt needed
PAY_TYPE = {"Наличные": "cash", "Карта": "electronically", "Перевод": "electronically", "Безнал (организация)": None}
METHOD_TITLES = {"fullPayment": "Полный расчёт", "partialPayment": "Частичный расчёт", "creditPayment": "Оплата кредита",
                 "advance": "Аванс"}


class FiscalError(ValueError):
    """Shown to the user as is (the server turns ValueError into a readable 400 answer)."""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def settings() -> dict:
    return {**DEFAULTS, **(config.load_settings().get("fiscal") or {})}


# ======================================================================= drivers --
class EmulatorDriver:
    """Behaves like a register: shift opens with the first receipt, expires after 24 h."""
    test = True

    def __init__(self, db):
        self.db = db

    def _st(self):
        raw = self.db.meta_get("fiscal_emulator")
        return json.loads(raw) if raw else {"open": False, "shift": 0, "fd": 0, "receipt": 0, "opened_at": None}

    def _save(self, st):
        self.db.meta_set("fiscal_emulator", json.dumps(st))

    def shift_status(self):
        st = self._st()
        state = "closed"
        if st["open"]:
            age = time.time() - datetime.strptime(st["opened_at"], "%Y-%m-%d %H:%M:%S").timestamp()
            state = "expired" if age > 24 * 3600 else "opened"
        return {"state": state, "number": st["shift"], "receipts": st["receipt"], "opened_at": st["opened_at"]}

    def open_shift(self, operator):
        st = self._st()
        if st["open"]:
            raise FiscalError("Смена уже открыта")
        st.update(open=True, shift=st["shift"] + 1, receipt=0, opened_at=_now(), fd=st["fd"] + 1)
        self._save(st)
        return {"shift": st["shift"]}

    def close_shift(self, operator):
        st = self._st()
        if not st["open"]:
            raise FiscalError("Смена не открыта")
        st.update(open=False, fd=st["fd"] + 1)
        self._save(st)
        return {"shift": st["shift"]}

    def x_report(self, operator):
        return {"shift": self._st()["shift"]}

    def receipt(self, r):
        s = self.shift_status()
        if s["state"] == "expired":
            raise FiscalError("Смена открыта больше 24 часов. Закройте смену (Z-отчёт) и откройте новую.")
        if s["state"] == "closed":
            self.open_shift(r["operator"])
        st = self._st()
        st["fd"] += 1
        st["receipt"] += 1
        self._save(st)
        return {"fn": "9999078900000000", "fd": str(st["fd"]), "fp": str(random.randint(10 ** 9, 10 ** 10 - 1)),
                "shift": str(st["shift"]), "number": str(st["receipt"]), "fiscal_at": _now()}

    def check(self):
        return "Тестовый режим: чеки не уходят в налоговую"


class AtolWebDriver:
    """ATOL DTO 10 web server: POST /api/v2/requests with a JSON task, then poll for the result."""
    test = False

    def __init__(self, url, timeout=60, session=None):
        import requests
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.http = session or requests.Session()

    def _task(self, task):
        import requests
        uid = str(uuid.uuid4())
        try:
            r = self.http.post(f"{self.url}/api/v2/requests", json={"uuid": uid, "request": [task]}, timeout=10)
        except requests.RequestException as e:
            raise FiscalError(f"Нет связи с веб-сервером драйвера АТОЛ ({self.url}). Проверьте, что драйвер запущен.") from e
        if r.status_code not in (200, 201):
            raise FiscalError(f"Драйвер АТОЛ отклонил задание: HTTP {r.status_code} {r.text[:200]}")
        end = time.time() + self.timeout
        while time.time() < end:
            try:
                res = self.http.get(f"{self.url}/api/v2/requests/{uid}", timeout=10).json()
            except (requests.RequestException, ValueError) as e:
                raise FiscalError("Драйвер АТОЛ перестал отвечать. Результат чека проверьте на кассе.") from e
            items = res.get("results") or []
            if items and items[0].get("status") in ("ready", "error", "interrupted", "blocked"):
                it = items[0]
                if it.get("status") != "ready":
                    msg = it.get("errorDescription") or (it.get("error") or {}).get("description") or it.get("status")
                    raise FiscalError(f"Касса: {msg}")
                return it.get("result") or {}
            time.sleep(0.4)
        raise FiscalError("Касса не ответила за минуту. Проверьте на кассе, напечатан ли чек, прежде чем пробивать снова.")

    @staticmethod
    def _operator(op):
        o = {"name": op.get("name") or "Кассир"}
        if op.get("vatin"):
            o["vatin"] = op["vatin"]
        return o

    def shift_status(self):
        res = self._task({"type": "getShiftStatus"})
        s = res.get("shiftStatus") or {}
        return {"state": s.get("state", "closed"), "number": s.get("number"), "opened_at": None,
                "expires": s.get("expiredTime") or s.get("expirationDateTime")}

    def open_shift(self, operator):
        res = self._task({"type": "openShift", "operator": self._operator(operator)})
        return {"shift": (res.get("fiscalParams") or {}).get("shiftNumber")}

    def close_shift(self, operator):
        res = self._task({"type": "closeShift", "operator": self._operator(operator)})
        return {"shift": (res.get("fiscalParams") or {}).get("shiftNumber")}

    def x_report(self, operator):
        self._task({"type": "reportX", "operator": self._operator(operator)})
        return {}

    def receipt(self, r):
        task = {"type": "sell" if r["kind"] == "sell" else "sellReturn", "taxationType": r["taxation"],
                "electronically": bool(r.get("electronically")), "operator": self._operator(r["operator"]),
                "items": [{"type": "position", "name": it["name"][:128], "price": it["price"], "quantity": it["quantity"],
                           "amount": it["amount"], "measurementUnit": "piece", "paymentMethod": it["paymentMethod"],
                           "paymentObject": it["paymentObject"], "tax": {"type": it["tax"]}} for it in r["items"]],
                "payments": [{"type": p["type"], "sum": p["sum"]} for p in r["payments"]], "total": r["total"]}
        if r.get("contact"):
            task["clientInfo"] = {"emailOrPhone": r["contact"]}
        fp = (self._task(task).get("fiscalParams") or {})
        return {"fn": str(fp.get("fnNumber", "")), "fd": str(fp.get("fiscalDocumentNumber", "")),
                "fp": str(fp.get("fiscalDocumentSign", "")), "shift": str(fp.get("shiftNumber", "")),
                "number": str(fp.get("fiscalReceiptNumber", "")), "fiscal_at": str(fp.get("fiscalDocumentDateTime", "") or _now())}

    def check(self):
        s = self.shift_status()
        return f"Касса АТОЛ отвечает. Смена: {'открыта' if s['state'] == 'opened' else 'истекла' if s['state'] == 'expired' else 'закрыта'}"


class ShtrihDriver:
    """Shtrih-M through the DrvFR COM object (driver «Драйвер ККТ» installed and set up on this computer)."""
    test = False
    TAX = {"none": 8, "vat0": 4, "vat10": 2, "vat22": 1}
    TAXATION = {"osn": 1, "usnIncome": 2, "usnIncomeOutcome": 4, "esn": 16, "patent": 32}
    METHOD = {"advance": 3, "fullPayment": 4, "partialPayment": 5, "creditPayment": 7}
    OBJECT = {"service": 4, "payment": 10}

    def __init__(self, password=30, factory=None):
        self.password = int(password or 30)
        self.factory = factory

    def _dev(self):
        if self.factory:
            d = self.factory()
        else:
            try:
                import win32com.client  # noqa: PLC0415
                d = win32com.client.Dispatch("Addin.DrvFR")
            except Exception as e:  # noqa: BLE001
                raise FiscalError("Не найден драйвер Штрих-М на этом компьютере. Установите «Драйвер ККТ» Штрих-М и настройте подключение к кассе.") from e
        d.Password = self.password
        d.Connect()
        self._ok(d)
        return d

    @staticmethod
    def _ok(d):
        if int(d.ResultCode) != 0:
            raise FiscalError(f"Касса: {d.ResultCodeDescription} (код {d.ResultCode})")

    def _run(self, d, method):
        getattr(d, method)()
        self._ok(d)

    def shift_status(self):
        d = self._dev()
        self._run(d, "FNGetCurrentSessionParams")
        state = "opened" if int(d.SessionState) == 1 else "closed"
        return {"state": state, "number": int(d.SessionNumber), "opened_at": None}

    def open_shift(self, operator):
        d = self._dev()
        d.FNOperatorName = operator.get("name") or ""
        self._run(d, "OpenSession")
        return {}

    def close_shift(self, operator):
        d = self._dev()
        self._run(d, "PrintReportWithCleaning")
        return {}

    def x_report(self, operator):
        d = self._dev()
        self._run(d, "PrintReportWithoutCleaning")
        return {}

    def receipt(self, r):
        tax = self.TAX.get(r["items"][0]["tax"]) if r["items"] else 8
        if tax is None:
            raise FiscalError("Эта ставка НДС не настроена для Штрих-М")
        d = self._dev()
        for it in r["items"]:
            d.CheckType = 1 if r["kind"] == "sell" else 2
            d.Price = it["price"]
            d.Quantity = it["quantity"]
            d.Summ1Enabled = True
            d.Summ1 = it["amount"]
            d.TaxValueEnabled = False
            d.Tax1 = tax
            d.Department = 1
            d.PaymentTypeSign = self.METHOD[it["paymentMethod"]]
            d.PaymentItemSign = self.OBJECT[it["paymentObject"]]
            d.StringForPrinting = it["name"][:128]
            self._run(d, "FNOperation")
        if r.get("contact"):
            d.CustomerEmail = r["contact"]
            self._run(d, "FNSendCustomerEmail")
        sums = {p["type"]: p["sum"] for p in r["payments"]}
        d.Summ1 = sums.get("cash", 0)
        d.Summ2 = sums.get("electronically", 0)
        for i in range(3, 17):
            setattr(d, f"Summ{i}", 0)
        d.TaxType = self.TAXATION.get(r["taxation"], 2)
        d.StringForPrinting = ""
        self._run(d, "FNCloseCheckEx")
        return {"fn": "", "fd": str(getattr(d, "DocumentNumber", "")), "fp": str(getattr(d, "FiscalSignAsString", "") or getattr(d, "FiscalSign", "")),
                "shift": "", "number": "", "fiscal_at": _now()}

    def check(self):
        s = self.shift_status()
        return f"Касса Штрих-М отвечает. Смена № {s['number']}: {'открыта' if s['state'] == 'opened' else 'закрыта'}"


# ====================================================================== service --
class Fiscal:
    def __init__(self, db, driver_override=None):
        self.db = db
        db.conn.executescript(SCHEMA)
        db.conn.commit()
        self._lock = threading.Lock()  # one register, one operation at a time
        self._override = driver_override

    def driver(self, s=None):
        if self._override:
            return self._override
        s = s or settings()
        if s["driver"] == "atol":
            return AtolWebDriver(s["atol_url"])
        if s["driver"] == "shtrih":
            return ShtrihDriver(s.get("shtrih_password", 30))
        return EmulatorDriver(self.db)

    def _operator(self, user_name):
        return {"name": user_name or "Кассир", "vatin": settings().get("cashier_inn") or ""}

    def _call(self, fn):
        with self._lock:
            try:
                return fn()
            except FiscalError:
                raise
            except Exception as e:  # noqa: BLE001
                raise FiscalError(f"Ошибка кассы: {e}") from e

    # ------------------------------------------------------------ shift --
    def status(self):
        s = settings()
        out = {"enabled": s["enabled"], "driver": s["driver"], "driver_title": DRIVERS.get(s["driver"]),
               "test": s["driver"] == "emulator", "auto": s["auto"], "shift": None, "error": None,
               "failed": self.db.one("SELECT COUNT(*) AS n FROM receipts WHERE status='error'")["n"]}
        if s["enabled"]:
            try:
                out["shift"] = self._call(lambda: self.driver(s).shift_status())
            except FiscalError as e:
                out["error"] = str(e)
        return out

    def open_shift(self, user):
        return self._call(lambda: self.driver().open_shift(self._operator(user)))

    def close_shift(self, user):
        return self._call(lambda: self.driver().close_shift(self._operator(user)))

    def x_report(self, user):
        return self._call(lambda: self.driver().x_report(self._operator(user)))

    def check(self):
        return self._call(lambda: self.driver().check())

    # --------------------------------------------------------- receipts --
    def build_for_payment(self, payment_id):
        """Receipt lines for one payment, following how the clinic bills: a full payment of an invoice
        lists every service; a part of an invoice is one line «partial payment / payment of credit»;
        money without an invoice is an advance."""
        p = self.db.one("SELECT * FROM payments WHERE id=?", (payment_id,))
        if not p:
            raise FiscalError("Оплата не найдена")
        ptype = PAY_TYPE.get(p["method"], "cash")
        if ptype is None:
            return None
        s = settings()
        amount = round(p["amount"], 2)
        inv = self.db.one("SELECT * FROM invoices WHERE id=?", (p["invoice_id"],)) if p["invoice_id"] else None
        items = []
        if inv:
            before = self.db.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE invoice_id=? AND id<>? AND created_at<=?",
                                 (inv["id"], p["id"], p["created_at"]))["s"]
            lines = json.loads(inv["items"] or "[]")
            if before < 0.009 and abs(amount - inv["total"]) < 0.009 and lines:
                gross = sum(float(x.get("sum") or 0) for x in lines) or 1
                left = amount
                for i, x in enumerate(lines):
                    qty = float(x.get("qty") or 1)
                    line = round(float(x.get("sum") or 0) * amount / gross, 2) if i < len(lines) - 1 else round(left, 2)
                    left -= line
                    items.append({"name": x.get("title") or "Стоматологическая услуга", "quantity": qty,
                                  "price": round(line / qty, 2) if qty else line, "amount": line,
                                  "paymentMethod": "fullPayment", "paymentObject": "service", "tax": s["tax"]})
                # price × quantity must give the amount exactly; otherwise print as one quantity
                for it in items:
                    if abs(round(it["price"] * it["quantity"], 2) - it["amount"]) > 0.001:
                        it["price"], it["quantity"] = it["amount"], 1
            else:
                method = "partialPayment" if before < 0.009 else "creditPayment"
                titles = ", ".join(x.get("title", "") for x in lines)[:80]
                items.append({"name": f"Стоматологические услуги ({titles})" if titles else "Стоматологические услуги",
                              "quantity": 1, "price": amount, "amount": amount, "paymentMethod": method,
                              "paymentObject": "service" if method == "partialPayment" else "payment", "tax": s["tax"]})
        else:
            items.append({"name": "Аванс за стоматологические услуги", "quantity": 1, "price": amount, "amount": amount,
                          "paymentMethod": "advance", "paymentObject": "payment", "tax": s["tax"]})
        return {"items": items, "payments": [{"type": ptype, "sum": amount}], "total": amount, "taxation": s["taxation"],
                "patient_id": p["patient_id"], "invoice_id": p["invoice_id"]}

    def _print(self, rid, body, user):
        """Send a stored receipt to the register and record the result."""
        r = self.db.one("SELECT * FROM receipts WHERE id=?", (rid,))
        task = {"kind": r["kind"], "items": json.loads(r["items"]), "payments": json.loads(r["payments"]), "total": r["total"],
                "taxation": body.get("taxation") or settings()["taxation"], "operator": self._operator(user),
                "contact": r["contact"] or "", "electronically": bool(body.get("electronically"))}
        drv = self.driver()
        try:
            res = self._call(lambda: drv.receipt(task))
        except FiscalError as e:
            with self.db.tx() as c:
                c.execute("UPDATE receipts SET status='error', error=?, driver=? WHERE id=?", (str(e), settings()["driver"], rid))
            return self.receipt(rid)
        with self.db.tx() as c:
            c.execute("""UPDATE receipts SET status=?, error=NULL, driver=?, fn=?, fd=?, fp=?, shift=?, number=?, fiscal_at=?
                         WHERE id=?""", ("test" if drv.test else "done", settings()["driver"], res["fn"], res["fd"], res["fp"],
                                        res["shift"], res["number"], res["fiscal_at"], rid))
        return self.receipt(rid)

    def for_payment(self, payment_id, contact="", user="", electronically=False):
        if self.db.one("SELECT 1 AS x FROM receipts WHERE payment_id=? AND kind='sell' AND status IN ('done','test')", (payment_id,)):
            raise FiscalError("Чек по этой оплате уже пробит")
        body = self.build_for_payment(payment_id)
        if body is None:
            return {"status": "not_required", "message": "Оплата от организации по безналу — чек не нужен"}
        rid = "C-" + uuid.uuid4().hex[:10]
        with self.db.tx() as c:
            c.execute("DELETE FROM receipts WHERE payment_id=? AND kind='sell' AND status='error'", (payment_id,))
            c.execute("""INSERT INTO receipts(id, kind, payment_id, invoice_id, patient_id, items, payments, total, contact, status,
                         user_name, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (rid, "sell", payment_id, body["invoice_id"], body["patient_id"], json.dumps(body["items"], ensure_ascii=False),
                       json.dumps(body["payments"]), body["total"], str(contact or "").strip()[:100], "pending", user, _now()))
        return self._print(rid, {**body, "electronically": electronically}, user)

    def retry(self, rid, user=""):
        r = self.db.one("SELECT * FROM receipts WHERE id=?", (rid,))
        if not r:
            raise FiscalError("Чек не найден")
        if r["status"] in ("done", "test"):
            raise FiscalError("Чек уже пробит")
        return self._print(rid, {}, user)

    def refund(self, rid, user=""):
        """Receipt «return of income» for a printed receipt (patient got the money back)."""
        r = self.db.one("SELECT * FROM receipts WHERE id=?", (rid,))
        if not r or r["kind"] != "sell" or r["status"] not in ("done", "test"):
            raise FiscalError("Возврат можно оформить только по пробитому чеку прихода")
        if self.db.one("SELECT 1 AS x FROM receipts WHERE refund_of=? AND status IN ('done','test')", (rid,)):
            raise FiscalError("По этому чеку возврат уже оформлен")
        nid = "C-" + uuid.uuid4().hex[:10]
        with self.db.tx() as c:
            c.execute("DELETE FROM receipts WHERE refund_of=? AND status='error'", (rid,))
            c.execute("""INSERT INTO receipts(id, kind, payment_id, invoice_id, patient_id, refund_of, items, payments, total, contact,
                         status, user_name, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (nid, "refund", r["payment_id"], r["invoice_id"], r["patient_id"], rid, r["items"], r["payments"], r["total"],
                       r["contact"], "pending", user, _now()))
        return self._print(nid, {}, user)

    def receipt(self, rid):
        r = self.db.one("""SELECT r.*, p.name AS patient_name FROM receipts r LEFT JOIN patients p ON p.id=r.patient_id
                           WHERE r.id=?""", (rid,))
        if r:
            r["items"] = json.loads(r["items"] or "[]")
            r["payments"] = json.loads(r["payments"] or "[]")
            r["refunded"] = bool(self.db.one("SELECT 1 AS x FROM receipts WHERE refund_of=? AND status IN ('done','test')", (rid,)))
        return r

    def receipts(self, day=None, status=None):
        sql = "SELECT r.id FROM receipts r WHERE 1=1"
        args = []
        if day:
            sql += " AND substr(r.created_at,1,10)=?"
            args.append(day)
        if status:
            sql += " AND r.status=?"
            args.append(status)
        return [self.receipt(x["id"]) for x in self.db.q(sql + " ORDER BY r.created_at DESC", args)]

    def payment_has_receipt(self, payment_id):
        """True while the payment has a printed receipt that was not returned."""
        for r in self.db.q("SELECT id FROM receipts WHERE payment_id=? AND kind='sell' AND status IN ('done','test')", (payment_id,)):
            if not self.db.one("SELECT 1 AS x FROM receipts WHERE refund_of=? AND status IN ('done','test')", (r["id"],)):
                return True
        return False

    def payment_states(self, payment_ids):
        out = {}
        for pid in payment_ids:
            rows = self.db.q("SELECT id, kind, status, refund_of FROM receipts WHERE payment_id=? ORDER BY created_at", (pid,))
            st = None
            for r in rows:
                if r["kind"] == "sell":
                    st = {"id": r["id"], "status": r["status"]}
                elif r["kind"] == "refund" and r["status"] in ("done", "test") and st:
                    st["status"] = "refunded"
            if st:
                out[pid] = st
        return out
