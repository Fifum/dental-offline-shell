"""Reports: revenue by doctor and service, visit statistics, debts and advances, rights."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import db as dbm  # noqa: E402
import demo  # noqa: E402
from main import Api  # noqa: E402
from reports import status_kind  # noqa: E402
from server import ClinicServer  # noqa: E402


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
today = date.today().isoformat()
docs = d.doctors()
pats = d.q("SELECT id FROM patients ORDER BY id LIMIT 3")

# --- status groups match the calendar colours
check("status: done", status_kind("Завершён") == "done")
check("status: no-show", status_kind("Не пришёл") == "noshow")
check("status: cancel", status_kind("Отменён") == "cancel")
check("status: came", status_kind("Пришёл") == "came")
check("status: planned", status_kind("Запланирован") == "planned")

# --- empty period
r = a.report_revenue("2020-01-01", "2020-01-31")
check("empty period", r["billed"] == 0 and r["paid"] == 0 and r["by_doctor"] == [] and r["avg_check"] == 0, r)
refuses("bad date", lambda: a.report_revenue("2020-13-01", None), "дата")

# --- revenue: two invoices for two doctors, one with an invoice discount, partial payment
i1 = a.save_invoice({"patient_id": pats[0]["id"], "doctor_id": docs[0]["id"],
                     "items": [{"title": "Пломба", "code": "P1", "price": 3000, "qty": 2}, {"title": "Анестезия", "price": 500}]})
i2 = a.save_invoice({"patient_id": pats[1]["id"], "doctor_id": docs[1]["id"], "discount": 10,
                     "items": [{"title": "Пломба", "code": "P1", "price": 3000}]})
a.add_payment({"invoice_id": i1, "amount": 6500, "method": "Карта"})
a.add_payment({"invoice_id": i2, "amount": 1000, "method": "Наличные"})
r = a.report_revenue(today, today)
check("billed", abs(r["billed"] - (6500 + 2700)) < 0.01, r["billed"])
check("paid", abs(r["paid"] - 7500) < 0.01, r["paid"])
check("invoices and avg check", r["invoices"] == 2 and abs(r["avg_check"] - 4600) < 0.01, r)
d0 = next(x for x in r["by_doctor"] if x["doctor_id"] == docs[0]["id"])
check("doctor totals", d0["billed"] == 6500 and d0["paid"] == 6500 and d0["invoices"] == 1 and d0["patients"] == 1, d0)
fill = next(x for x in r["by_service"] if x["title"] == "Пломба")
check("service qty summed", fill["qty"] == 3, fill)
check("service sum with invoice discount", abs(fill["sum"] - (6000 + 2700)) < 0.01, fill)
check("by method", r["by_method"] == {"Карта": 6500, "Наличные": 1000}, r["by_method"])
check("by day", len(r["by_day"]) == 1 and r["by_day"][0]["day"] == today, r["by_day"])
check("plans are not revenue", a.save_invoice({"patient_id": pats[2]["id"], "kind": "plan", "items": [{"title": "X", "price": 99999}]})
      and a.report_revenue(today, today)["billed"] == r["billed"])
check("reversed period is fine", a.report_revenue(today, "2020-01-01")["billed"] == r["billed"])

# --- visits
v = a.report_visits((date.today() - timedelta(days=10)).isoformat(), today)
check("visits counted", v["total"] > 0 and v["total"] == v["done"] + v["came"] + v["planned"] + v["cancel"] + v["noshow"], v)
check("visits by doctor add up", sum(x["total"] for x in v["by_doctor"]) == v["total"])
check("cancelled are not hours", v["minutes"] > 0 and v["lost_share"] <= 100)
check("visits by day", sum(x["total"] for x in v["by_day"]) == v["total"])
lv = a.save_visit({"patient_id": pats[0]["id"], "doctor_id": docs[0]["id"], "start": f"{today} 08:00:00",
                   "end": f"{today} 09:00:00", "status": "Отменён"})
v2 = a.report_visits(today, today)
check("local cancelled visit counted", v2["cancel"] >= 1)

# --- debts and advances
db = a.report_debts()
p1 = next((x for x in db["debts"] if x["patient_id"] == pats[1]["id"]), None)
check("debt in program", p1 and abs(p1["debt"] - 1700) < 0.01, p1)
a.add_payment({"patient_id": pats[2]["id"], "amount": 5000, "method": "Карта", "comment": "аванс"})
db = a.report_debts()
adv = next((x for x in db["advances"] if x["patient_id"] == pats[2]["id"]), None)
check("advance without invoice", adv and adv["advance"] == 5000, adv)
check("demo debts from Dentist Plus", any(x["dp_debt"] > 0 for x in db["debts"]))
check("totals", abs(db["total_debt"] - sum(x["total"] for x in db["debts"])) < 0.01 and db["total_advance"] >= 5000)
check("paid in full is not a debt", all(x["patient_id"] != pats[0]["id"] or x["debt"] == 0 for x in db["debts"]))

# --- rights over HTTP
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
for login, role in (("adm", "admin"), ("doc", "doctor")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TA = call("auth", "login", "adm", "secret1")[1]["token"]
TDoc = call("auth", "login", "doc", "secret1")[1]["token"]
check("director sees revenue", call("api", "report_revenue", today, today, token=TD)[0] == 200)
check("director sees visits", call("api", "report_visits", token=TD)[0] == 200)
check("admin no revenue", call("api", "report_revenue", token=TA)[0] == 403)
check("doctor no debts", call("api", "report_debts", token=TDoc)[0] == 403)
st = call("auth", "state")[1]
check("perm listed", any(p["key"] == "reports" for p in st["perm_list"]))
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
