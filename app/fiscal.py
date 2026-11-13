"""Fiscal receipts (54-FZ) through an online cash register.

Drivers:
  emulator  — test mode, no device; receipts are marked as not fiscal
  atol      — ATOL via the web server of driver DTO 10 (JSON tasks, http://<pc>:16732)
  shtrih    — Shtrih-M via its COM driver (DrvFR), on the computer the register is attached to

The payment is always saved first. A receipt that failed (no paper, shift over 24 h, device off)
stays in the list with the reason and can be printed again from the cash screen.

A receipt whose result is not known (the register did not answer in time, the program was closed while printing)
is «unknown», never printed again by itself: the cashier checks the register first. ATOL tasks keep their uuid,
so a repeat asks the register about the same task instead of printing a second receipt. Every payment carries
`receipt_state` (payments are replicated, receipts are not), so the other computers see that it has a receipt.
"""
from __future__ import annotations

import json
import random
import sqlite3
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
LIVE = ("pending", "unknown", "done", "test")  # a receipt that is (or may be) on paper
# one live receipt per payment and kind (and per returned receipt)
LIVE_INDEX = """CREATE UNIQUE INDEX IF NOT EXISTS ux_receipts_live ON receipts(payment_id, kind, COALESCE(refund_of, ''))
                WHERE status IN ('pending','unknown','done','test')"""
UNKNOWN_MSG = ("Результат этого чека неизвестен: касса могла его напечатать. Проверьте на кассе последний чек, "
               "затем отметьте, напечатан ли он.")

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
PAY_TYPE = {"Наличные": "cash", "Карта": "electronically", "Перевод": "electronically", "СБП": "electronically",
            "Безнал (организация)": None, "Сертификат": "prepaid", "Бонусы": None,
            "Из аванса": "prepaid",  # 2.12: an invoice paid from the patient's advance — offset of the prepayment
            "Страховая": None}       # ДМС: the insurance company pays by bank transfer, no receipt
METHOD_TITLES = {"fullPayment": "Полный расчёт", "partialPayment": "Частичный расчёт", "creditPayment": "Оплата кредита",
                 "advance": "Аванс"}


class FiscalError(ValueError):
    """Shown to the user as is (the server turns ValueError into a readable 400 answer)."""


class FiscalUnknown(FiscalError):
    """The task may have reached the register: the receipt may be on paper. Never printed again by itself."""


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

    def _task(self, task, uid=None):
        """`uid` of an earlier task: the web server keeps tasks by uuid (409 on a repeat), so its result is read
        instead of printing again."""
        import requests
        uid = uid or str(uuid.uuid4())
        try:
            r = self.http.post(f"{self.url}/api/v2/requests", json={"uuid": uid, "request": [task]}, timeout=10)
        except requests.RequestException as e:
            if isinstance(e, requests.ConnectTimeout) or "NewConnectionError" in repr(e) or "establish a new connection" in str(e):
                raise FiscalError(f"Нет связи с веб-сервером драйвера АТОЛ ({self.url}). Проверьте, что драйвер запущен.") from e
            raise FiscalUnknown("Драйвер АТОЛ не ответил на задание. Результат чека проверьте на кассе.") from e
        if r.status_code == 409:
            pass  # this uuid is already there: a repeat of the same task — read its result
        elif r.status_code not in (200, 201):
            raise FiscalError(f"Драйвер АТОЛ отклонил задание: HTTP {r.status_code} {r.text[:200]}")
        end = time.time() + self.timeout
        while time.time() < end:
            try:
                res = self.http.get(f"{self.url}/api/v2/requests/{uid}", timeout=10).json()
            except (requests.RequestException, ValueError) as e:
                raise FiscalUnknown("Драйвер АТОЛ перестал отвечать. Результат чека проверьте на кассе.") from e
            items = res.get("results") or []
            if items and items[0].get("status") in ("ready", "error", "interrupted", "blocked"):
                it = items[0]
                if it.get("status") != "ready":
                    msg = it.get("errorDescription") or (it.get("error") or {}).get("description") or it.get("status")
                    raise FiscalError(f"Касса: {msg}")
                return it.get("result") or {}
            time.sleep(0.4)
        raise FiscalUnknown("Касса не ответила за минуту. Проверьте на кассе, напечатан ли чек, прежде чем пробивать снова.")

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
        fp = (self._task(task, r.get("uuid")).get("fiscalParams") or {})
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
        d.Summ14 = sums.get("prepaid", 0)  # offset of an advance (gift certificate)
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
        with db._lock:
            db.conn.executescript(SCHEMA)
            if "ext_uuid" not in {r[1] for r in db.conn.execute("PRAGMA table_info(receipts)")}:
                db.conn.execute("ALTER TABLE receipts ADD COLUMN ext_uuid TEXT")  # the ATOL task of the receipt
            if "receipt_state" not in {r[1] for r in db.conn.execute("PRAGMA table_info(payments)")}:
                db.conn.execute("ALTER TABLE payments ADD COLUMN receipt_state TEXT")
            try:
                db.conn.execute(LIVE_INDEX)
            except sqlite3.IntegrityError:  # receipts printed twice before the index: the checks in code still hold
                pass
            db.conn.commit()
        self._lock = threading.Lock()  # one register, one operation at a time
        self._override = driver_override
        self._busy = set()  # receipts being sent to the register now
        self._busy_lock = threading.Lock()
        for r in db.q("SELECT DISTINCT payment_id FROM receipts WHERE payment_id IS NOT NULL"):  # marks of older receipts
            with db.tx() as c:
                self._mark(c, r["payment_id"])

    @staticmethod
    def _mark(c, payment_id):
        """Copy the receipt state of a payment to the payment row (replicated): done / test / refunded / unknown."""
        if not payment_id:
            return
        rows = c.execute("SELECT id, kind, status, refund_of FROM receipts WHERE payment_id=?", (payment_id,)).fetchall()
        own = [r for r in rows if r[1] == "sell" or (r[1] == "refund" and not r[3])]
        done = [r for r in own if r[2] in ("done", "test")]
        st = None
        if done:
            back = all(any(x[3] == d[0] and x[2] in ("done", "test") for x in rows) for d in done)
            st = "refunded" if back else done[0][2]
        elif any(r[2] in ("pending", "unknown") for r in own):
            st = "unknown"
        c.execute("UPDATE payments SET receipt_state=? WHERE id=? AND COALESCE(receipt_state,'')<>COALESCE(?,'')",
                  (st, payment_id, st))

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
               "failed": self.db.one("SELECT COUNT(*) AS n FROM receipts WHERE status='error'")["n"],
               "unknown": self.db.one("SELECT COUNT(*) AS n FROM receipts WHERE status IN ('pending','unknown')")["n"]}
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
        """Send a stored receipt to the register and record the result. The receipt is «pending» (with the uuid of
        its ATOL task) before anything goes to the register; an answer that may hide a printed receipt makes it
        «unknown», a clear refusal of the register makes it «error» (safe to print again)."""
        with self._busy_lock:
            if rid in self._busy:
                raise FiscalError("Этот чек сейчас печатается — подождите")
            self._busy.add(rid)
        try:
            r = self.db.one("SELECT * FROM receipts WHERE id=?", (rid,))
            s = settings()
            task = {"kind": r["kind"], "items": json.loads(r["items"]), "payments": json.loads(r["payments"]), "total": r["total"],
                    "taxation": body.get("taxation") or s["taxation"], "operator": self._operator(user),
                    "contact": r["contact"] or "", "electronically": bool(body.get("electronically")),
                    "uuid": r.get("ext_uuid") or str(uuid.uuid4())}
            drv = self.driver(s)
            try:
                with self.db.tx() as c:
                    c.execute("UPDATE receipts SET status='pending', error=NULL, ext_uuid=?, driver=? WHERE id=?", (task["uuid"], s["driver"], rid))
                    self._mark(c, r["payment_id"])
            except sqlite3.IntegrityError:
                raise FiscalError("По этой оплате уже есть пробитый чек") from None
            try:
                with self._lock:
                    res = drv.receipt(task)
            except FiscalUnknown as e:
                self._set(rid, r["payment_id"], "unknown", str(e))
                return self.receipt(rid)
            except FiscalError as e:  # the register refused: nothing printed, the next try is a new task
                self._set(rid, r["payment_id"], "error", str(e), clear_uuid=True)
                return self.receipt(rid)
            except Exception as e:  # noqa: BLE001 — failed somewhere in the middle: the result is not known
                self._set(rid, r["payment_id"], "unknown", f"Ошибка кассы: {e}. Результат чека проверьте на кассе.")
                return self.receipt(rid)
            with self.db.tx() as c:
                c.execute("""UPDATE receipts SET status=?, error=NULL, fn=?, fd=?, fp=?, shift=?, number=?, fiscal_at=?
                             WHERE id=?""", ("test" if drv.test else "done", res["fn"], res["fd"], res["fp"],
                                            res["shift"], res["number"], res["fiscal_at"], rid))
                self._mark(c, r["payment_id"])
            return self.receipt(rid)
        finally:
            with self._busy_lock:
                self._busy.discard(rid)

    def _set(self, rid, payment_id, status, error, clear_uuid=False):
        with self.db.tx() as c:
            c.execute(f"UPDATE receipts SET status=?, error=?{', ext_uuid=NULL' if clear_uuid else ''} WHERE id=?", (status, error, rid))
            self._mark(c, payment_id)

    def _new(self, rid, kind, payment_id, invoice_id, patient_id, items, pays, total, contact, user, refund_of=None):
        """Insert a «pending» receipt; refuses when the payment already has a live one (checked and written in
        one transaction, and the unique index guards the same)."""
        try:
            with self.db.tx() as c:
                live = c.execute(f"""SELECT status FROM receipts WHERE payment_id=? AND kind=? AND COALESCE(refund_of,'')=?
                                     AND status IN ({','.join('?' * len(LIVE))})""", (payment_id, kind, refund_of or "", *LIVE)).fetchone()
                mark = None
                if not refund_of:
                    m = c.execute("SELECT receipt_state FROM payments WHERE id=?", (payment_id,)).fetchone()
                    mark = m[0] if m else None
                if live or mark:
                    st = live[0] if live else mark
                    what = "Возврат по этому чеку" if refund_of else "Чек возврата по этой операции" if kind == "refund" else "Чек по этой оплате"
                    if st in ("pending", "unknown"):
                        raise FiscalError(f"{what} уже отправлен на кассу, результат неизвестен. Проверьте кассу и решите в разделе «Касса».")
                    raise FiscalError(f"{what} уже {'оформлен' if refund_of else 'пробит'}" + ("" if live else " на другом компьютере"))
                c.execute(f"DELETE FROM receipts WHERE payment_id=? AND kind=? AND COALESCE(refund_of,'')=? AND status='error'",
                          (payment_id, kind, refund_of or ""))
                c.execute("""INSERT INTO receipts(id, kind, payment_id, invoice_id, patient_id, refund_of, items, payments, total, contact,
                             status, user_name, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (rid, kind, payment_id, invoice_id, patient_id, refund_of, items, pays, total,
                           str(contact or "").strip()[:100], "pending", user, _now()))
                self._mark(c, payment_id)
        except sqlite3.IntegrityError:
            raise FiscalError("Чек по этой оплате уже печатается") from None

    def for_payment(self, payment_id, contact="", user="", electronically=False):
        p = self.db.one("SELECT amount, kind FROM payments WHERE id=?", (payment_id,))
        if p and (p["amount"] or 0) < 0:  # 2.12: a refund gets a «return» receipt; moving an advance needs none
            if p["kind"] == "refund":
                return self.for_refund(payment_id, contact, user, electronically)
            return {"status": "not_required", "message": "Перенос аванса между счетами — чек не нужен"}
        body = self.build_for_payment(payment_id)
        if body is None:
            m = (self.db.one("SELECT method FROM payments WHERE id=?", (payment_id,)) or {}).get("method")
            return {"status": "not_required", "message": "Оплата бонусами — отдельный чек не нужен" if m == "Бонусы" else "Оплата от организации по безналу — чек не нужен"}
        rid = "C-" + uuid.uuid4().hex[:10]
        self._new(rid, "sell", payment_id, body["invoice_id"], body["patient_id"], json.dumps(body["items"], ensure_ascii=False),
                  json.dumps(body["payments"]), body["total"], contact, user)
        return self._print(rid, {**body, "electronically": electronically}, user)

    def for_refund(self, payment_id, contact="", user="", electronically=False):
        """2.12: «return of income» for a refund row (a negative payment): money given back from the advance or
        from an overpaid invoice — for the refunded sum, not for a whole earlier receipt."""
        p = self.db.one("SELECT * FROM payments WHERE id=?", (payment_id,))
        if not p or (p["amount"] or 0) >= 0 or p["kind"] != "refund":
            raise FiscalError("Возврат не найден")
        ptype = PAY_TYPE.get(p["method"], "cash")
        if ptype is None:
            return {"status": "not_required", "message": "Возврат по безналу организации — чек не нужен"}
        s = settings()
        amount = round(-p["amount"], 2)
        adv = not p["invoice_id"]
        items = [{"name": "Возврат аванса за стоматологические услуги" if adv else "Возврат за стоматологические услуги",
                  "quantity": 1, "price": amount, "amount": amount, "paymentMethod": "advance" if adv else "fullPayment",
                  "paymentObject": "payment" if adv else "service", "tax": s["tax"]}]
        rid = "C-" + uuid.uuid4().hex[:10]
        self._new(rid, "refund", payment_id, p["invoice_id"], p["patient_id"], json.dumps(items, ensure_ascii=False),
                  json.dumps([{"type": ptype, "sum": amount}]), amount, contact, user)
        return self._print(rid, {"taxation": s["taxation"], "electronically": electronically}, user)

    def _state(self, payment_id):
        p = self.db.one("SELECT amount, receipt_state FROM payments WHERE id=?", (payment_id,))
        return (p or {}).get("amount") or 0, (p or {}).get("receipt_state")

    def refund_printed(self, payment_id) -> bool:
        """True while a refund row has a return receipt (or one whose result is unknown) — here or on another computer."""
        amount, st = self._state(payment_id)
        if amount < 0 and st in ("done", "test", "unknown"):
            return True
        return bool(self.db.one("SELECT 1 AS x FROM receipts WHERE payment_id=? AND kind='refund' AND refund_of IS NULL "
                                "AND status IN ('pending','unknown','done','test')", (payment_id,)))

    def retry(self, rid, user="", checked=None):
        """Print a failed receipt again. A receipt with an unknown result needs the cashier's answer after checking
        the register: checked='printed' marks it printed, 'not_printed' sends it again (ATOL: the same task)."""
        r = self.db.one("SELECT * FROM receipts WHERE id=?", (rid,))
        if not r:
            raise FiscalError("Чек не найден")
        if r["status"] in ("done", "test"):
            raise FiscalError("Чек уже пробит")
        with self._busy_lock:
            if rid in self._busy:
                raise FiscalError("Этот чек сейчас печатается — подождите")
        if r["status"] in ("pending", "unknown"):
            if checked == "printed":
                with self.db.tx() as c:
                    c.execute("UPDATE receipts SET status=?, error=? WHERE id=?",
                              ("test" if (r["driver"] or settings()["driver"]) == "emulator" else "done",
                               f"Кассир проверил кассу: чек напечатан ({user or 'без имени'}, {_now()})", rid))
                    self._mark(c, r["payment_id"])
                return self.receipt(rid)
            if checked != "not_printed":
                raise FiscalError(UNKNOWN_MSG)
        return self._print(rid, {}, user)

    def refund(self, rid, user=""):
        """Receipt «return of income» for a printed receipt (patient got the money back)."""
        r = self.db.one("SELECT * FROM receipts WHERE id=?", (rid,))
        if not r or r["kind"] != "sell" or r["status"] not in ("done", "test"):
            raise FiscalError("Возврат можно оформить только по пробитому чеку прихода")
        nid = "C-" + uuid.uuid4().hex[:10]
        self._new(nid, "refund", r["payment_id"], r["invoice_id"], r["patient_id"], r["items"], r["payments"], r["total"],
                  r["contact"], user, refund_of=rid)
        return self._print(nid, {}, user)

    def receipt(self, rid):
        r = self.db.one("""SELECT r.*, p.name AS patient_name FROM receipts r LEFT JOIN patients p ON p.id=r.patient_id
                           WHERE r.id=?""", (rid,))
        if r:
            r.pop("ext_uuid", None)
            r["items"] = json.loads(r["items"] or "[]")
            r["payments"] = json.loads(r["payments"] or "[]")
            r["refunded"] = bool(self.db.one("SELECT 1 AS x FROM receipts WHERE refund_of=? AND status IN ('done','test')", (rid,)))
            if r["status"] == "pending":
                with self._busy_lock:
                    if rid not in self._busy:  # left «pending» by a closed program: the result is not known
                        r["status"] = "unknown"
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
        """True while the payment has a receipt that was not returned — printed, being printed or with an unknown
        result — here or on another computer (the mark on the payment travels with it)."""
        amount, st = self._state(payment_id)
        if amount >= 0 and st in ("done", "test", "unknown"):
            return True
        for r in self.db.q("SELECT id FROM receipts WHERE payment_id=? AND kind='sell' AND status IN ('pending','unknown','done','test')",
                           (payment_id,)):
            if not self.db.one("SELECT 1 AS x FROM receipts WHERE refund_of=? AND status IN ('done','test')", (r["id"],)):
                return True
        return False

    def payment_states(self, payment_ids):
        out = {}
        for pid in payment_ids:
            rows = self.db.q("SELECT id, kind, status, refund_of FROM receipts WHERE payment_id=? ORDER BY created_at", (pid,))
            st = None
            for r in rows:
                if r["kind"] == "sell" or (r["kind"] == "refund" and not r["refund_of"]):  # 2.12: receipt of a refund row
                    st = {"id": r["id"], "status": r["status"]}
                elif r["kind"] == "refund" and r["status"] in ("done", "test") and st:
                    st["status"] = "refunded"
            if st and st["status"] == "pending":
                with self._busy_lock:
                    if st["id"] not in self._busy:
                        st["status"] = "unknown"
            if not st:  # printed on another computer: only the mark of the payment is here
                mark = self._state(pid)[1]
                if mark:
                    st = {"id": None, "status": mark, "elsewhere": True}
            if st:
                out[pid] = st
        return out
