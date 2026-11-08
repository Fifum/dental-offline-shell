"""Accounting: expenses, pay schemes, payroll with percent and salary, payouts, profit summary, rights."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import db as dbm  # noqa: E402
import demo  # noqa: E402
from main import Api  # noqa: E402
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
month = today[:7]
doc = d.doctors()[0]
key = f"d:{doc['id']}"
pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]

# --- expenses
e1 = a.save_expense({"date": today, "category": "Аренда", "amount": "150 000", "comment": "офис"})
a.save_expense({"date": today, "category": "Реклама", "amount": 20000.5, "method": "Карта"})
refuses("zero amount", lambda: a.save_expense({"category": "Аренда", "amount": 0}), "больше нуля")
refuses("no category", lambda: a.save_expense({"category": " ", "amount": 10}), "статью")
refuses("bad number", lambda: a.save_expense({"category": "X", "amount": "abc"}), "число")
refuses("bad date", lambda: a.save_expense({"category": "X", "amount": 1, "date": "2026-02-30"}), "дата")
refuses("unknown person", lambda: a.save_expense({"category": "X", "amount": 1, "person": "d:nobody"}), "не найден")
ex = a.expenses(today, today)
check("expense list", len(ex["rows"]) == 2 and abs(ex["total"] - 170000.5) < 0.01, ex["total"])
check("by category", ex["by_category"]["Аренда"] == 150000)
check("filter by category", len(a.expenses(today, today, "Реклама")["rows"]) == 1)
a.save_expense({"id": e1, "date": today, "category": "Аренда", "amount": 140000})
check("edit expense", a.expenses(today, today, "Аренда")["total"] == 140000)
check("own category offered", "Реклама" in a.acc_summary()["categories"])
a.save_expense({"date": today, "category": "Своя статья", "amount": 1})
check("custom category remembered", "Своя статья" in a.acc_summary()["categories"])

# --- pay scheme and payroll
refuses("percent over 100", lambda: a.save_salary_scheme({"person": key, "percent": 120}), "100")
refuses("negative salary", lambda: a.save_salary_scheme({"person": key, "fixed": -1}), "отрицательным")
check("scheme saved", a.save_salary_scheme({"person": key, "percent": 30, "fixed": 10000, "base": "paid"}))
check("scheme listed", next(s for s in a.salary_schemes() if s["key"] == key)["percent"] == 30)
inv = a.save_invoice({"patient_id": pid, "doctor_id": doc["id"], "items": [{"title": "Пломба", "price": 10000}]})
a.add_payment({"invoice_id": inv, "amount": 6000, "method": "Карта"})
pr = a.payroll(month)
row = next(r for r in pr["rows"] if r["key"] == key)
check("percent of paid", row["paid"] == 6000 and row["by_percent"] == 1800, row)
check("earned = percent + salary", row["earned"] == 11800 and row["due"] == 11800, row)
a.save_salary_scheme({"person": key, "percent": 30, "fixed": 10000, "base": "billed"})
check("percent of billed", next(r for r in a.payroll(month)["rows"] if r["key"] == key)["by_percent"] == 3000)
check("unset people listed", all(not (s["percent"] or s["fixed"]) for s in pr["unset"]) and len(pr["unset"]) >= 1)
check("other month empty", not any(r["key"] == key and r["by_percent"] for r in a.payroll("2020-01")["rows"]))
refuses("bad month", lambda: a.payroll("2026-13"), "месяц")

# --- materials subtracted (norm of a service written off when the invoice is billed)
mid = a.save_material({"name": "Композит", "unit": "г", "price": 500, "start_qty": 10})
sid = a.save_service({"title": "Реставрация", "price": 8000})
a.save_norms(sid, [{"material_id": mid, "qty": 2}])
inv2 = a.save_invoice({"patient_id": pid, "doctor_id": doc["id"], "items": [{"service_id": sid, "title": "Реставрация", "price": 8000}]})
a.save_salary_scheme({"person": key, "percent": 50, "fixed": 0, "base": "billed", "minus_materials": True})
row = next(r for r in a.payroll(month)["rows"] if r["key"] == key)
check("materials subtracted", row["materials"] == 1000 and row["by_percent"] == round((18000 - 1000) * 0.5, 2), row)

# --- payout
a.pay_salary({"person": key, "month": month, "amount": 5000, "method": "Наличные"})
row = next(r for r in a.payroll(month)["rows"] if r["key"] == key)
check("payout reduces due", row["paid_out"] == 5000 and row["due"] == row["earned"] - 5000, row)
sal = a.expenses(today, today, "Зарплата")["rows"]
check("payout is an expense", len(sal) == 1 and sal[0]["person"] == key and sal[0]["period"] == month and sal[0]["person_name"] == doc["name"], sal)

# --- summary
s = a.acc_summary(today, today)
paid = sum(p["amount"] for p in d.q("SELECT amount FROM payments WHERE substr(created_at,1,10)=?", (today,)))
check("income = payments", abs(s["income"] - paid) < 0.01, s)
check("expense total", abs(s["expense"] - a.expenses(today, today)["total"]) < 0.01)
check("result", abs(s["result"] - (s["income"] - s["expense"])) < 0.01 and s["by_month"][0]["month"] == month, s)
check("debts in summary", "total_debt" in s["debts"])
check("delete expense", a.delete_expense(e1) and not any(x["id"] == e1 for x in a.expenses(today, today)["rows"]))

# --- demo office data is created once and marked as already transferred
demo.ensure_office(d)
n = d.one("SELECT COUNT(*) AS n FROM expenses WHERE id LIKE 'demo_%'")["n"]
demo.ensure_office(d)
check("demo expenses once", n > 0 and d.one("SELECT COUNT(*) AS n FROM expenses WHERE id LIKE 'demo_%'")["n"] == n)
check("demo invoices not pending", d.one("SELECT COUNT(*) AS n FROM invoices WHERE id LIKE 'demo_%' AND transferred=0")["n"] == 0)
check("demo money not today", d.one("SELECT COUNT(*) AS n FROM payments WHERE id LIKE 'demo_%' AND substr(created_at,1,10)=?", (today,))["n"] == 0)

# --- rights over HTTP
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
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
call("auth", "register", {"name": "Админ Тест", "login": "adm", "password": "secret1"})
u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == "adm")
call("auth", "staff_save", {"id": u["id"], "role": "admin", "status": "active"}, token=TD)
TA = call("auth", "login", "adm", "secret1")[1]["token"]
check("admin cannot see accounting", call("api", "acc_summary", token=TA)[0] == 403)
check("admin cannot add expense", call("api", "save_expense", {"category": "X", "amount": 1}, token=TA)[0] == 403)
check("director pays", call("api", "pay_salary", {"person": key, "month": month, "amount": 100}, token=TD)[0] == 200)
check("staff account has a pay scheme", any(p["key"] == f"u:{u['id']}" for p in call("api", "salary_schemes", token=TD)[1]))
code, _ = call("api", "save_salary_scheme", {"person": f"u:{u['id']}", "fixed": 45000}, token=TD)
check("salary for administrator", code == 200 and any(r["key"] == f"u:{u['id']}" and r["earned"] == 45000
                                                       for r in call("api", "payroll", month, token=TD)[1]["rows"]))
audit = call("auth", "audit_list", token=TD)[1]
check("audit: payout", any(x["action"] == "Выплата зарплаты" for x in audit))
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
