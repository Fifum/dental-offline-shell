"""Fiscal receipts: receipt lines by payment type, test mode, failures and retry, returns, ATOL web
server protocol (against a fake server) and Shtrih-M COM calls (against a fake driver object)."""
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
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
pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]


def invoice(total_items):
    return a.save_invoice({"patient_id": pid, "items": total_items})


# --- off by default: payments as before
iid = invoice([{"title": "Осмотр", "price": 1000, "qty": 1}])
r = a.add_payment({"invoice_id": iid, "amount": 1000, "method": "Наличные"})
check("no receipt while register is off", r["ok"] and "receipt" not in r)

# --- test mode
a.fiscal_save_settings({"enabled": True, "driver": "emulator", "taxation": "usnIncome", "tax": "none"})
check("ui knows register is on", a.ui_settings()["fiscal_enabled"] and a.ui_settings()["fiscal_test"])
refuses("unknown driver", lambda: a.fiscal_save_settings({"driver": "kassa-x"}))

# full payment: every service on the receipt, prices with discounts, sum matches
iid = invoice([{"title": "Лечение кариеса", "price": 5500, "qty": 1, "discount": 10}, {"title": "Анестезия", "price": 500, "qty": 2}])
inv = a.invoice(iid)
r = a.add_payment({"invoice_id": iid, "amount": inv["total"], "method": "Карта", "contact": "patient@example.com"})
rc = r["receipt"]
check("test receipt printed", rc["status"] == "test" and rc["fd"] and rc["fp"], rc)
check("itemized full payment", len(rc["items"]) == 2 and all(i["paymentMethod"] == "fullPayment" for i in rc["items"]), rc["items"])
check("line sums add up", abs(sum(i["amount"] for i in rc["items"]) - inv["total"]) < 0.001)
check("price × qty = amount", all(abs(i["price"] * i["quantity"] - i["amount"]) < 0.001 for i in rc["items"]))
check("card is electronic payment", rc["payments"] == [{"type": "electronically", "sum": inv["total"]}])
check("contact kept", rc["contact"] == "patient@example.com")
check("payment shows receipt", a.invoice(iid)["payments"][0]["receipt"]["status"] == "test")
refuses("second receipt for the same payment", lambda: a.fiscal_for_payment(r["id"]), "уже пробит")

# invoice-level discount spread over lines
iid = a.save_invoice({"patient_id": pid, "discount": 15, "items": [{"title": "A", "price": 1000, "qty": 3}, {"title": "B", "price": 333, "qty": 1}]})
tot = a.invoice(iid)["total"]
rc = a.add_payment({"invoice_id": iid, "amount": tot, "method": "Наличные"})["receipt"]
check("invoice discount: total exact", abs(sum(i["amount"] for i in rc["items"]) - tot) < 0.001, (tot, rc["items"]))
check("invoice discount: price × qty consistent", all(abs(i["price"] * i["quantity"] - i["amount"]) < 0.001 for i in rc["items"]), rc["items"])

# partial payment then the rest
iid = invoice([{"title": "Коронка", "price": 18000, "qty": 1}])
r1 = a.add_payment({"invoice_id": iid, "amount": 8000, "method": "Наличные"})["receipt"]
r2 = a.add_payment({"invoice_id": iid, "amount": 10000, "method": "Наличные"})["receipt"]
check("first part = partial payment", r1["items"][0]["paymentMethod"] == "partialPayment" and r1["items"][0]["paymentObject"] == "service", r1["items"])
check("rest = payment of credit", r2["items"][0]["paymentMethod"] == "creditPayment" and r2["items"][0]["paymentObject"] == "payment", r2["items"])

# money without an invoice = advance; company bank transfer needs no receipt
rc = a.add_payment({"patient_id": pid, "amount": 3000, "method": "Наличные"})["receipt"]
check("advance", rc["items"][0]["paymentMethod"] == "advance", rc["items"])
rc = a.add_payment({"invoice_id": iid, "amount": 1, "method": "Безнал (организация)"})["receipt"]
check("company transfer: no receipt", rc["status"] == "not_required", rc)
r = a.add_payment({"invoice_id": iid, "amount": 5, "method": "Наличные", "receipt": False})
check("cashier can skip the receipt", "receipt" not in r)

# shift
st = a.fiscal_status()
check("shift opened by first receipt", st["shift"]["state"] == "opened", st)
a.fiscal_x_report()
a.fiscal_close_shift()
check("Z closes shift", a.fiscal_status()["shift"]["state"] == "closed")
refuses("close closed shift", a.fiscal_close_shift, "не открыта")
a.fiscal_open_shift()
emu = json.loads(d.meta_get("fiscal_emulator")); emu["opened_at"] = "2000-01-01 09:00:00"; d.meta_set("fiscal_emulator", json.dumps(emu))
check("24 h shift expired", a.fiscal_status()["shift"]["state"] == "expired")
iid = invoice([{"title": "Осмотр", "price": 700, "qty": 1}])
r = a.add_payment({"invoice_id": iid, "amount": 700, "method": "Наличные"})
check("payment saved even if receipt fails", r["ok"] and r["receipt"]["status"] == "error" and "24" in r["receipt"]["error"], r)
check("failed receipt counted", a.fiscal_status()["failed"] == 1)
a.fiscal_close_shift()
again = a.fiscal_retry(a.fiscal_receipts(status="error")[0]["id"])
check("retry after Z", again["status"] == "test" and a.fiscal_status()["failed"] == 0, again)

# returns and deleting payments
refuses("payment with receipt cannot be deleted", lambda: a.delete_payment(r["id"]), "возврата")
refuses("invoice with receipts cannot be deleted", lambda: a.delete_invoice(iid), "возврата")
ref = a.fiscal_refund(again["id"])
check("refund receipt", ref["kind"] == "refund" and ref["status"] == "test" and ref["total"] == 700)
refuses("double refund", lambda: a.fiscal_refund(again["id"]), "уже")
check("payment shows refunded", a.invoice(iid)["payments"][0]["receipt"]["status"] == "refunded")
check("delete after refund", a.delete_payment(r["id"]) is True)
check("all receipts listed", len(a.fiscal_receipts(day=None)) == 7, len(a.fiscal_receipts()))

# --- ATOL web server protocol against a fake DTO 10 web server
TASKS = []


class FakeAtol(BaseHTTPRequestHandler):
    results = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        TASKS.append(body["request"][0])
        t = body["request"][0]
        if t["type"] in ("sell", "sellReturn") and t["total"] == 13:
            res = {"status": "error", "errorCode": 44, "errorDescription": "Нет бумаги"}
        elif t["type"] == "getShiftStatus":
            res = {"status": "ready", "result": {"shiftStatus": {"state": "opened", "number": 12}}}
        else:
            res = {"status": "ready", "result": {"fiscalParams": {"fnNumber": "7380440700000001", "fiscalDocumentNumber": 101,
                                                                   "fiscalDocumentSign": "3826380000", "shiftNumber": 12,
                                                                   "fiscalReceiptNumber": 5, "fiscalDocumentDateTime": "2026-11-07T12:00:00+03:00"}}}
        FakeAtol.results[body["uuid"]] = res
        self.send_response(201); self.end_headers()

    def do_GET(self):
        uid = self.path.rsplit("/", 1)[-1]
        out = json.dumps({"results": [FakeAtol.results[uid]]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)

    def log_message(self, *x): pass


s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
httpd = ThreadingHTTPServer(("127.0.0.1", port), FakeAtol)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
a.fiscal_save_settings({"driver": "atol", "atol_url": f"http://127.0.0.1:{port}", "taxation": "osn", "tax": "none", "cashier_inn": "500100732259"})
check("ATOL check", "АТОЛ" in a.fiscal_check() and "открыта" in a.fiscal_check())
iid = invoice([{"title": "Профгигиена", "price": 4500, "qty": 1}])
rc = a.add_payment({"invoice_id": iid, "amount": 4500, "method": "Наличные", "contact": "+79990000000"})["receipt"]
sell = [t for t in TASKS if t["type"] == "sell"][-1]
check("ATOL receipt done with fiscal data", rc["status"] == "done" and rc["fd"] == "101" and rc["fp"] == "3826380000" and rc["fn"] == "7380440700000001", rc)
check("ATOL task: taxation, operator, client", sell["taxationType"] == "osn" and sell["operator"]["vatin"] == "500100732259"
      and sell["clientInfo"] == {"emailOrPhone": "+79990000000"}, sell)
it = sell["items"][0]
check("ATOL task: position", it["type"] == "position" and it["tax"] == {"type": "none"} and it["paymentObject"] == "service"
      and it["paymentMethod"] == "fullPayment" and it["amount"] == 4500, it)
check("ATOL task: payments and total", sell["payments"] == [{"type": "cash", "sum": 4500}] and sell["total"] == 4500)
iid = invoice([{"title": "Тест ошибки", "price": 13, "qty": 1}])
rc = a.add_payment({"invoice_id": iid, "amount": 13, "method": "Наличные"})["receipt"]
check("ATOL error text shown", rc["status"] == "error" and "Нет бумаги" in rc["error"], rc)
a.fiscal_close_shift()
check("ATOL close shift task", TASKS[-1]["type"] == "closeShift" and TASKS[-1]["operator"]["name"])
ref = a.fiscal_refund([x for x in a.fiscal_receipts() if x["status"] == "done"][0]["id"])
check("ATOL refund = sellReturn", TASKS[-1]["type"] == "sellReturn" and ref["status"] == "done")
httpd.shutdown()
a.fiscal_save_settings({"atol_url": "http://127.0.0.1:1"})
refuses("ATOL offline: clear message", a.fiscal_check, "веб-сервером драйвера АТОЛ")


# --- Shtrih-M COM calls against a fake driver object
class FakeDrv:
    def __init__(self):
        object.__setattr__(self, "log", [])
        object.__setattr__(self, "props", {"ResultCode": 0, "ResultCodeDescription": "Ошибок нет", "SessionState": 1,
                                            "SessionNumber": 7, "DocumentNumber": 55, "FiscalSignAsString": "1234567890"})

    def __setattr__(self, k, v):
        self.props[k] = v
        self.log.append(("set", k, v))

    def __getattr__(self, k):
        if k in self.props:
            return self.props[k]
        return lambda: self.log.append(("call", k, dict(self.props)))


drv = FakeDrv()
f = fiscal.Fiscal(d, driver_override=fiscal.ShtrihDriver(30, factory=lambda: drv))
a._fiscal = f
a.fiscal_save_settings({"driver": "shtrih", "taxation": "usnIncome", "tax": "none"})
check("Shtrih status", f.status()["shift"] == {"state": "opened", "number": 7, "opened_at": None})
iid = invoice([{"title": "Удаление зуба", "price": 3000, "qty": 1}, {"title": "Анестезия", "price": 500, "qty": 1}])
rc = a.add_payment({"invoice_id": iid, "amount": 3500, "method": "Карта"})["receipt"]
ops = [x for x in drv.log if x[0] == "call" and x[1] == "FNOperation"]
close = [x for x in drv.log if x[0] == "call" and x[1] == "FNCloseCheckEx"]
check("Shtrih: one FNOperation per line", len(ops) == 2, len(ops))
check("Shtrih: line props", ops[0][2]["CheckType"] == 1 and ops[0][2]["Tax1"] == 8 and ops[0][2]["PaymentTypeSign"] == 4
      and ops[0][2]["PaymentItemSign"] == 4 and ops[0][2]["Summ1"] == 3000, ops[0][2])
check("Shtrih: close with card sum + USN", close and close[0][2]["Summ2"] == 3500 and close[0][2]["Summ1"] == 0 and close[0][2]["TaxType"] == 2, close)
check("Shtrih: fiscal data", rc["status"] == "done" and rc["fd"] == "55" and rc["fp"] == "1234567890", rc)
drv.props["ResultCode"] = -1; drv.props["ResultCodeDescription"] = "Нет связи"
rc = a.add_payment({"invoice_id": invoice([{"title": "X", "price": 100, "qty": 1}]), "amount": 100, "method": "Наличные"})["receipt"]
check("Shtrih error text", rc["status"] == "error" and "Нет связи" in rc["error"], rc)
refuses("Shtrih without driver installed", lambda: fiscal.ShtrihDriver(30)._dev(), "Штрих-М")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
