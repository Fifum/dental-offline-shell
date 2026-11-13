"""Review 2026-11-13, money: a receipt never printed twice (К6), invoice checks (К7), deleting a paid invoice (К8),
a money action sent twice (В6), two open cash shifts (В10), certificate balance across computers (В11), the plan's
discount (В12), a payment to a deleted invoice (В13), editing a paid invoice (В14)."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import fiscal  # noqa: E402
from main import Api  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def refuses(name, fn, text=""):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except ValueError as e:
        check(name, not text or text in str(e), e)


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
auth.Auth(d)  # the action journal
F = a._fin
doc = d.doctors()[0]["id"]


def patient(last):
    return a.create_patient({"lname": last, "fname": "Тест"})["id"]


def invoice(pid, price, **kw):
    return a.save_invoice({"patient_id": pid, "doctor_id": doc, "items": [{"title": "Услуга", "price": price, "qty": 1}], **kw})


def ago(minutes):
    return (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


# ======================================================================= К6
class Drv:
    test = False

    def __init__(self):
        self.printed, self.mode = 0, "ok"

    def receipt(self, r):
        if self.mode == "slow":
            time.sleep(0.3)
        self.printed += 1  # the paper is out
        if self.mode == "timeout":
            raise fiscal.FiscalUnknown("Касса не ответила за минуту")
        if self.mode == "refused":
            self.printed -= 1
            raise fiscal.FiscalError("Касса: нет бумаги")
        if self.mode == "crash":
            raise SystemExit("power lost after printing")
        return {"fn": "1", "fd": str(self.printed), "fp": "1", "shift": "1", "number": "1", "fiscal_at": "x"}


config.save_settings({"fiscal": {"enabled": True, "driver": "atol", "auto": False}})
drv = Drv()
a._fiscal = Fx = fiscal.Fiscal(d, driver_override=drv)
P = patient("Чеков")


def pay(amount):
    iid = invoice(P, amount)
    return iid, a.add_payment({"invoice_id": iid, "amount": amount, "method": "Наличные", "receipt": False})["id"]


check("unique index on live receipts", d.one("SELECT 1 AS x FROM sqlite_master WHERE name='ux_receipts_live'"))
# (а) timeout → «unknown», never printed again by itself
iid, p = pay(1000); drv.mode = "timeout"
r = Fx.for_payment(p)
check("timeout: unknown, not error", r["status"] == "unknown" and drv.printed == 1, r)
check("timeout: not in the failed count", a.fiscal_status()["failed"] == 0 and a.fiscal_status()["unknown"] == 1)
drv.mode = "ok"
refuses("unknown: plain retry refused", lambda: Fx.retry(r["id"]), "неизвестен")
refuses("unknown: second receipt refused", lambda: Fx.for_payment(p), "неизвестен")
check("unknown blocks deleting the payment", Fx.payment_has_receipt(p))
refuses("unknown: payment cannot be deleted", lambda: a.delete_payment(p), "чек")
r2 = Fx.retry(r["id"], "", "printed")
check("cashier marks it printed: no second print", r2["status"] == "done" and drv.printed == 1, (r2, drv.printed))
# a definite refusal of the register is safe to print again (with a new task)
iid, p = pay(1100); drv.mode = "refused"
r = Fx.for_payment(p)
check("refused: error", r["status"] == "error" and drv.printed == 1)
drv.mode = "ok"
check("refused: retry prints", Fx.retry(r["id"])["status"] == "done" and drv.printed == 2)
# (б) power lost after printing, before the result was written
iid, p = pay(2000); drv.mode = "crash"
try:
    Fx.for_payment(p)
except SystemExit:
    pass
drv.mode = "ok"
st = Fx.payment_states([p])[p]
check("crash: shown as unknown", st["status"] == "unknown", st)
refuses("crash: no second receipt", lambda: Fx.for_payment(p))
check("crash: payment_has_receipt", Fx.payment_has_receipt(p))
before = drv.printed
Fx.retry(st["id"], "", "not_printed")
check("crash: cashier says not printed → printed again", drv.printed == before + 1)
# (в) two requests at once
drv.printed = 0; drv.mode = "slow"
iid, p = pay(3000)
errs = []


def go():
    try:
        Fx.for_payment(p)
    except ValueError as e:
        errs.append(str(e))


ts = [threading.Thread(target=go) for _ in range(3)]
[t.start() for t in ts]; [t.join() for t in ts]
check("concurrent: one paper receipt", drv.printed == 1 and len(errs) == 2, (drv.printed, errs))
drv.mode = "ok"
# (г) another computer sees the mark of the payment (receipts are not replicated, payments are)
check("mark on the payment", d.one("SELECT receipt_state FROM payments WHERE id=?", (p,))["receipt_state"] == "done")
with d.tx() as c:
    c.execute("DELETE FROM receipts WHERE payment_id=?", (p,))  # as on a computer that never had this receipt
check("other computer: payment has receipt", Fx.payment_has_receipt(p))
check("other computer: state from the mark", Fx.payment_states([p]).get(p, {}).get("status") == "done")
refuses("other computer: no second receipt", lambda: Fx.for_payment(p), "другом компьютере")
refuses("other computer: invoice cannot be deleted", lambda: a.delete_invoice(iid), "чек")
refuses("other computer: payment cannot be deleted", lambda: a.delete_payment(p), "чек")

# ATOL: a repeat sends the same uuid; the web server answers 409 and the result of the first task is read
SEEN = {"posts": [], "ready": False}


class FakeAtol(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN["posts"].append(body["uuid"])
        self.send_response(409 if SEEN["posts"].count(body["uuid"]) > 1 else 201); self.end_headers()

    def do_GET(self):
        res = ({"status": "ready", "result": {"fiscalParams": {"fiscalDocumentNumber": 77, "fiscalDocumentSign": "9"}}}
               if SEEN["ready"] else {"status": "inProgress"})
        out = json.dumps({"results": [res]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)

    def log_message(self, *x): pass


s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
httpd = ThreadingHTTPServer(("127.0.0.1", port), FakeAtol)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
a._fiscal = Fx = fiscal.Fiscal(d, driver_override=fiscal.AtolWebDriver(f"http://127.0.0.1:{port}", timeout=1))
iid, p = pay(4000)
r = Fx.for_payment(p)
check("ATOL no answer in time: unknown", r["status"] == "unknown", r)
SEEN["ready"] = True
r = Fx.retry(r["id"], "", "not_printed")
check("ATOL repeat: same uuid, result read", r["status"] == "done" and r["fd"] == "77" and len(SEEN["posts"]) == 2
      and SEEN["posts"][0] == SEEN["posts"][1], (r, SEEN))
httpd.shutdown()
config.save_settings({"fiscal": {"enabled": False}})

# ======================================================================= К7
P7 = patient("Минусов")
refuses("negative price", lambda: invoice(P7, -5000), "меньше нуля")
refuses("zero quantity", lambda: a.save_invoice({"patient_id": P7, "items": [{"title": "X", "price": 100, "qty": 0}]}), "больше нуля")
refuses("negative quantity", lambda: a.save_invoice({"patient_id": P7, "items": [{"title": "X", "price": 100, "qty": -1}]}), "больше нуля")
refuses("line discount 250 %", lambda: a.save_invoice({"patient_id": P7, "items": [{"title": "X", "price": 100, "qty": 1, "discount": 250}]}), "до 100")
refuses("invoice discount 150 %", lambda: invoice(P7, 100, discount=150), "до 100")
refuses("plan with a negative price", lambda: a.save_invoice({"patient_id": P7, "kind": "plan", "items": [{"title": "X", "price": -1}]}), "меньше нуля")
check("zero price is fine (membership lines)", invoice(P7, 0))
with d.tx() as c:  # an old negative invoice made before the checks
    c.execute("INSERT INTO invoices(id, patient_id, items, total, kind, status, created_at) VALUES('L-neg', ?, '[]', -5000, 'invoice', 'x', ?)",
              (P7, ago(5)))
check("negative invoice is not an overpayment", F.pockets(P7) == [], F.pockets(P7))

# ======================================================================= К8
config.save_settings({"loyalty": {"bonus_percent": 10, "bonus_max_share": 30, "cert_months": 12}})
P8 = patient("Удалёнов")
i8 = invoice(P8, 10000)
a.add_payment({"invoice_id": i8, "amount": 10000, "method": "Наличные"})
refuses("invoice with payments cannot be deleted", lambda: a.delete_invoice(i8), "Сначала удалите оплаты")
check("payments stay", d.one("SELECT COUNT(*) AS n FROM payments WHERE invoice_id=?", (i8,))["n"] == 1)
check("doctor still cannot delete payments", "payments" not in auth.ROLES["doctor"]["perms"])
a.add_payment({"patient_id": P8, "amount": 3000, "method": "Наличные"})  # advance
i8b = invoice(P8, 2000)
u = a.deposit_use(i8b)
with d.tx() as c:  # whatever a payment changed in loyalty goes back with it
    c.execute("INSERT INTO bonus_moves(account, patient_id, amount, kind, payment_id, at) VALUES(?,?,?,?,?,?)",
              (f"P:{P8}", P8, 5, "accrual", u["id"], ago(1)))
check("invoice paid from the advance can be deleted", a.delete_invoice(i8b) is True)
check("advance is back", F.deposit(P8) == 3000, F.deposit(P8))
check("loyalty of removed rows undone", not d.one("SELECT 1 AS x FROM bonus_moves WHERE payment_id=?", (u["id"],)))

# ======================================================================= В6
P6 = patient("Двойкин")
i6 = invoice(P6, 5000)
r1 = a.add_payment({"invoice_id": i6, "amount": 1000, "method": "Наличные", "request_id": "rq-1"})
r2 = a.add_payment({"invoice_id": i6, "amount": 1000, "method": "Наличные", "request_id": "rq-1"})
check("same request id: one payment", r1["ok"] and r1["id"] == r2["id"]
      and d.one("SELECT COUNT(*) AS n FROM payments WHERE invoice_id=?", (i6,))["n"] == 1)
res = []
ts = [threading.Thread(target=lambda: res.append(a.add_payment({"invoice_id": i6, "amount": 500, "method": "Карта", "request_id": "rq-2"})))
      for _ in range(4)]
[t.start() for t in ts]; [t.join() for t in ts]
check("same request id at once: one payment", len({x["id"] for x in res}) == 1
      and d.one("SELECT COUNT(*) AS n FROM payments WHERE invoice_id=?", (i6,))["n"] == 2, res)
bad = a.add_payment({"invoice_id": i6, "amount": 0, "method": "Наличные", "request_id": "rq-3"})
good = a.add_payment({"invoice_id": i6, "amount": 700, "method": "Наличные", "request_id": "rq-3"})
check("a refused try does not block the fixed one", not bad["ok"] and good["ok"])
check("no request id: as before", a.add_payment({"invoice_id": i6, "amount": 1, "method": "Наличные"})["ok"])
a.add_payment({"patient_id": P6, "amount": 2000, "method": "Наличные"})
f1 = a.refund({"patient_id": P6, "amount": 500, "reason": "x", "receipt": False, "request_id": "rf-1"})
f2 = a.refund({"patient_id": P6, "amount": 500, "reason": "x", "receipt": False, "request_id": "rf-1"})
check("refund once", f1["ids"] == f2["ids"] and d.one("SELECT COUNT(*) AS n FROM payments WHERE patient_id=? AND kind='refund'", (P6,))["n"] == 1)
a.cash_shift_open({"open_cash": 1000})
m1 = a.cash_move({"kind": "in", "amount": 100, "reason": "Размен", "request_id": "cm-1"})
m2 = a.cash_move({"kind": "in", "amount": 100, "reason": "Размен", "request_id": "cm-1"})
check("cash move once", len(m2["moves"]) == 1 and m1["moves_in"] == 100, m2["moves"])
a.cash_shift_close({"counted_cash": a.cash_shift()["shift"]["expected_cash"]})

# ======================================================================= В10
with d.tx() as c:  # two computers opened a shift each without the network; both came by replication
    c.execute("DELETE FROM cash_shifts")  # the shift of the В6 checks above is not part of this story
    c.execute("INSERT INTO cash_shifts(id, opened_at, opened_by, open_cash, status) VALUES('SH-a', ?, 'A', 0, 'open')", (ago(30),))
    c.execute("INSERT INTO cash_shifts(id, opened_at, opened_by, open_cash, status) VALUES('SH-b', ?, 'B', 0, 'open')", (ago(20),))
P10 = patient("Сменов")
a.add_payment({"patient_id": P10, "amount": 700, "method": "Наличные"})  # after both opened
cur = a.cash_shift()
check("two open shifts: flagged", cur["shift"]["id"] == "SH-b" and [x["id"] for x in cur["extra"]] == ["SH-a"] and cur["warning"], cur.get("warning"))
since = d.one("SELECT opened_at FROM cash_shifts WHERE id='SH-b'")["opened_at"]
cash_b = round(d.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE method='Наличные' AND COALESCE(kind,'')<>'refund' AND created_at>=?", (since,))["s"], 2)
check("money counted by one shift only", cur["shift"]["cash_in"] == cash_b and cash_b >= 700 and cur["extra"][0]["cash_in"] == 0,
      (cur["shift"]["cash_in"], cash_b, cur["extra"][0]["cash_in"]))
cl = a.cash_shift_close({"id": "SH-a", "counted_cash": 0})
check("close the extra shift by id", cl["id"] == "SH-a" and cl["status"] == "closed" and a.cash_shift()["shift"]["id"] == "SH-b")
check("closed older shift does not take the money", F.shift("SH-a")["cash_in"] == 0 and F.shift("SH-b")["cash_in"] == cash_b)
refuses("closing a closed shift", lambda: a.cash_shift_close({"id": "SH-a", "counted_cash": 0}), "закрыта")
a.cash_shift_close({"counted_cash": cash_b})
check("no open shifts left", a.cash_shift()["shift"] is None)

# ======================================================================= В11
c11 = a._loyal.sell({"amount": 1000, "method": "Наличные"})
P11 = patient("Сертификатов")
i11 = invoice(P11, 5000)
pay11 = a.add_payment({"invoice_id": i11, "amount": 300, "method": "Сертификат", "cert_code": c11["code"]})
check("redeemed here", pay11["ok"] and a._loyal.certificate(c11["code"])["balance"] == 700)
with d.tx() as c:  # 400 spent on another computer; the merge kept that computer's copy of the balance (600)
    c.execute("INSERT INTO cert_moves(cert_id, payment_id, amount, at) VALUES(?,?,?,?)", (c11["id"], "P-other", 400, ago(1)))
    c.execute("UPDATE certificates SET balance=600 WHERE id=?", (c11["id"],))
check("balance from the redemptions", a._loyal.certificate(c11["code"])["balance"] == 300)
check("stored copy fixed", d.one("SELECT balance FROM certificates WHERE id=?", (c11["id"],))["balance"] == 300)
check("list shows the real balance", next(x for x in a._loyal.certificates("all")["rows"] if x["id"] == c11["id"])["balance"] == 300)
bad = a.add_payment({"invoice_id": i11, "amount": 400, "method": "Сертификат", "cert_code": c11["code"]})
check("cannot spend what was spent elsewhere", not bad["ok"] and "300" in bad["message"], bad)
a.delete_payment(pay11["id"])
check("deleted payment gives its part back", a._loyal.certificate(c11["code"])["balance"] == 600)

# ======================================================================= В12
P12 = patient("Планов")
plan = a.save_invoice({"patient_id": P12, "kind": "plan", "discount": 10,
                       "items": [{"title": "Имплант", "price": 50000, "qty": 1}, {"title": "Коронка", "price": 30000, "qty": 1}]})
i12 = a.plan_to_invoice(plan)
check("invoice keeps the plan's discount", d.one("SELECT total, discount FROM invoices WHERE id=?", (i12,)) == {"total": 72000, "discount": 10})

# ======================================================================= В13
P13 = patient("Висяков")
r = a.add_payment({"invoice_id": "L-deletedinv", "patient_id": P13, "amount": 4000, "method": "Наличные"})
check("payment to a deleted invoice refused", not r["ok"] and "удалён" in r["message"], r)
check("nothing saved", not d.one("SELECT 1 AS x FROM payments WHERE patient_id=?", (P13,)))
refuses("local layer refuses too", lambda: a._local.add_payment({"invoice_id": "L-deletedinv", "amount": 1}), "удалён")

# ======================================================================= В14
P14 = patient("Правкин")
i14 = invoice(P14, 5000)
a.add_payment({"invoice_id": i14, "amount": 5000, "method": "Наличные"})
auth.set_current_user({"id": 7, "role": "doctor", "login": "doc", "name": "Врач"})
refuses("doctor cannot make a paid invoice cheaper", lambda: invoice(P14, 100, id=i14), "Оплаты")
check("doctor may save it unchanged", a.save_invoice({"id": i14, "patient_id": P14, "doctor_id": doc, "comment": "ок",
                                                      "items": [{"title": "Услуга", "price": "5000", "qty": "1"}]}) == i14)
check("doctor may edit an unpaid invoice", invoice(P14, 100, id=invoice(P14, 200)))
auth.set_current_user({"id": 1, "role": "director", "login": "dir", "name": "Директор"})
invoice(P14, 4000, id=i14)
auth.set_current_user(None)
check("director changed it", d.one("SELECT total FROM invoices WHERE id=?", (i14,))["total"] == 4000)
j = d.one("SELECT * FROM audit WHERE action='Изменён счёт с оплатами' ORDER BY id DESC LIMIT 1")
check("old → new sum in the journal", j and "5000 → 4000" in j["detail"] and j["user_name"] == "Директор", j)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
