"""2.15 «Финмодель»: profit of a month by steps (revenue → variable costs → margin → fixed costs → operating profit →
taxes → net profit), accrued salaries without double counting the payouts, guide ranges, break-even, the «what if»
scenario, money ahead, months without data, the director's tile and rights."""
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
import auth  # noqa: E402
import db as dbm  # noqa: E402
import finmodel  # noqa: E402
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


def near(a, b, eps=0.02):
    return a is not None and b is not None and abs(a - b) <= eps


d = dbm.DB()
d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}, {"id": 2, "lname": "Сидорова", "fname": "Анна"},
                  {"id": 3, "lname": "Орлов", "fname": "Денис"}])
a = Api(d, W())
M = "2025-03"
with d.tx() as c:
    for iid, doc, total in (("i1", "1", 600000), ("i2", "2", 400000)):
        c.execute("INSERT INTO invoices(id, patient_id, doctor_id, items, total, status, created_at, kind) VALUES(?,?,?,?,?,?,?,?)",
                  (iid, "1", doc, "[]", total, "Оплачен", f"{M}-10 10:00:00", "invoice"))
    for pid, iid, amount, method in (("p1", "i1", 500000, "Карта"), ("p2", "i2", 300000, "Наличные"), ("p3", "i2", 5000, "Бонусы")):
        c.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, created_at) VALUES(?,?,?,?,?,?)",
                  (pid, iid, "1", amount, method, f"{M}-12 12:00:00"))
    # plans: confirmed and draft in the last year count as money ahead, an old one does not
    recent = (date.today() - timedelta(days=20)).isoformat() + " 10:00:00"
    old = (date.today() - timedelta(days=500)).isoformat() + " 10:00:00"
    for iid, st, total, at in (("pl1", "Подтверждён", 70000, recent), ("pl2", "Предварительный", 30000, recent),
                               ("pl3", "Подтверждён", 99000, old), ("pl4", "Активен", 55000, recent)):
        c.execute("INSERT INTO invoices(id, patient_id, doctor_id, items, total, status, created_at, kind, plan_status) VALUES(?,?,?,?,?,?,?,?,?)",
                  (iid, "1", "1", "[]", total, "", at, "plan", st))

a.save_salary_scheme({"person": "d:1", "percent": 30, "base": "paid"})
a.save_salary_scheme({"person": "d:2", "percent": 25, "fixed": 20000, "base": "paid"})
for f in ({"category": "Зарплата", "person": "d:1", "period": M, "amount": 100000, "date": f"{M}-31"},   # payout of the accrued pay
          {"category": "Зарплата", "person": "d:3", "period": M, "amount": 50000, "date": f"{M}-31"},    # no scheme: by the payout
          {"category": "Зарплата", "amount": 15000, "date": f"{M}-20", "comment": "уборщица"},           # nobody accrues it
          {"category": "Материалы и закупки", "amount": 40000, "date": f"{M}-05"},
          {"category": "Зуботехническая лаборатория", "amount": 60000, "date": f"{M}-15"},
          {"category": "Банк и эквайринг", "amount": 8000, "date": f"{M}-31"},
          {"category": "Аренда", "amount": 120000, "date": f"{M}-01"},
          {"category": "Реклама", "amount": 30000, "date": f"{M}-03"},
          {"category": "Налоги и взносы", "amount": 48000, "date": f"{M}-25"},
          {"category": "Аренда", "amount": 999999, "date": "2025-04-01"}):                              # another month
    a.save_expense(f)
a._daily.save({"category": "Прочее", "amount": 5000, "date": f"{M}-18", "doc": False}, "Админ", "adm", see_all=True)  # without a document

# --------------------------------------------------------------- the month
p = a.finmodel(M)
var = {x["key"]: x for x in p["variable"]}
fixed = {x["key"]: x for x in p["fixed"]}
check("revenue: payments without bonuses", p["revenue"] == 800000, p["revenue"])
check("billed", p["billed"] == 1000000, p["billed"])
# the doctor's percent is counted by «Зарплата» (from all the doctor's payments): 30 % of 500 000, 25 % of 305 000
DOC = 150000 + 76250 + 50000
SH = DOC / 800000
check("doctors: accrued percent + payout without a scheme", near(var["doctors"]["amount"], DOC), var["doctors"])
check("doctors detail", {x["name"] for x in var["doctors"]["detail"]} == {"Петров Пётр", "Сидорова Анна", "Орлов Денис"}, var["doctors"]["detail"])
check("materials", var["materials"]["amount"] == 40000)
check("laboratory", var["lab"]["amount"] == 60000)
check("acquiring", var["acquiring"]["amount"] == 8000)
check("variable total", near(p["variable_total"], DOC + 108000), p["variable_total"])
check("salary payout with a person not counted twice", near(fixed["staff"]["amount"], 20000 + 15000), fixed["staff"])
check("rent", fixed["Аренда"]["amount"] == 120000, fixed.get("Аренда"))
check("expense without a document counts", fixed["Прочее"]["amount"] == 5000, fixed.get("Прочее"))
check("other month not counted", "999999" not in json.dumps(p))
check("fixed total", near(p["fixed_total"], 190000), p["fixed_total"])
check("taxes below operating profit", p["taxes"]["amount"] == 48000)
check("margin", near(p["margin"]["amount"], 800000 - DOC - 108000) and near(p["margin"]["share"], 52.0, 0.05), p["margin"])
check("operating profit", near(p["operating"]["amount"], 225750), p["operating"])
check("net profit", near(p["net"]["amount"], 177750), p["net"])
check("break-even", near(p["break_even"], 190000 / (1 - SH - 108000 / 800000)), p["break_even"])
check("safety margin", near(p["safety"], round((800000 - p["break_even"]) * 100 / 800000, 1), 0.05), p["safety"])
check("nothing left to break-even", p["to_break_even"] == 0)
check("past month", not p["current"] and not p["future"])
check("workdays Mon–Sat without visits", p["workdays"] == 26 and p["workdays_done"] == 26, (p["workdays"], p["workdays_done"]))
check("break-even per workday", near(p["per_day_break_even"], p["break_even"] / 26), p["per_day_break_even"])
check("schemes are set", p["no_schemes"] is False)

# guide ranges
check("rent above the guide", fixed["Аренда"]["flag"] == "high", fixed["Аренда"])
check("doctors above the guide", var["doctors"]["flag"] == "high", var["doctors"]["share"])
check("acquiring inside the guide", var["acquiring"]["flag"] == "ok")
check("margin is fine", p["margin"]["flag"] == "ok")
check("no guide — no flag", fixed["Прочее"]["flag"] is None)
check("guide shown", var["materials"]["guide"] == finmodel.GUIDE["materials"])

# history and months without data
h = p["history"]
check("six months of history", len(h) == 6 and h[-1]["month"] == M and h[0]["month"] == "2024-10", [x["month"] for x in h])
check("last month of history is the month", near(h[-1]["net"], 177750) and h[-1]["has_data"], h[-1])
check("empty months marked", not any(x["has_data"] for x in h[:-1]), h)
empty = a._fm().pnl("2025-01")
check("month without data", empty["revenue"] == 0 and not empty["has_data"] and empty["break_even"] is None, empty)

# money ahead
r = p["reserve"]
check("confirmed plans of the last year", r["plans_confirmed"] == 70000 and r["plans_confirmed_n"] == 1, r)
check("draft plans", r["plans_draft"] == 30000 and r["plans_draft_n"] == 1, r)
check("patients' debts", r["debts"] >= 0, r)

# ------------------------------------------------------------- what if
s0 = a.finmodel_scenario(M, {})
check("no change — the same profit", near(s0["operating"], 225750) and near(s0["delta"], 0) and near(s0["break_even"], p["break_even"]), s0)
s1 = a.finmodel_scenario(M, {"price": 10})
check("prices +10 %: revenue", near(s1["revenue"], 880000), s1)
check("prices +10 %: doctors' percent follows revenue, materials do not", near(s1["variable"], SH * 880000 + 100000 + 8800), s1["variable"])
check("prices +10 %: profit", near(s1["operating"], 880000 - SH * 880000 - 108800 - 190000) and near(s1["delta"], 51575), s1)
s2 = a.finmodel_scenario(M, {"doctors": -5})
check("doctors −5 points", near(s2["doctors"], (SH - 0.05) * 800000) and near(s2["operating"], 265750), s2)
s3 = a.finmodel_scenario(M, {"visits": -20})
check("fewer visits: materials and lab follow", near(s3["variable"], 640000 * SH + 80000 + 6400), s3["variable"])
s4 = a.finmodel_scenario(M, {"fixed": 50})
check("fixed costs +50 %", near(s4["fixed"], 285000) and near(s4["operating"], 130750), s4)
s5 = a.finmodel_scenario(M, {"target": "500 000"})
check("revenue for the wanted profit", near(s5["need"], 690000 / (1 - SH - 108000 / 800000), 0.05), s5)
check("per workday and growth", near(s5["need_per_day"], s5["need"] / 26, 0.05) and s5["need_growth"] > 0, s5)
s6 = a.finmodel_scenario(M, {"price": 1000, "doctors": "-99"})
check("limits", near(s6["revenue"], 1600000) and near(s6["doctors"], (SH - 0.30) * 1600000), s6)
try:
    a.finmodel_scenario(M, {"price": "abc"})
    check("bad number refused", False)
except ValueError as e:
    check("bad number refused", "Сценарий" in str(e), e)
s7 = finmodel.scenario(empty, {"target": 100000})
check("no revenue: no break-even, no crash", s7["revenue"] == 0 and s7["break_even"] is None and s7["need"] is None, s7)

# ------------------------------------------------- current month and the tile
cur = a.finmodel()
check("current month", cur["current"] and cur["month"] == date.today().strftime("%Y-%m"), cur["month"])
b = a.finmodel_brief()
check("brief", b["month"] == cur["month"] and set(b) >= {"operating", "break_even", "to_break_even", "net", "safety"}, b)

# ------------------------------------------------------------------ rights
check("methods need «Бухгалтерия»", all(auth.METHOD_PERMS.get(m) == "accounting" for m in ("finmodel", "finmodel_scenario", "finmodel_brief")))
check("read-only: not in the journal", not {"finmodel", "finmodel_scenario", "finmodel_brief"} & set(auth.AUDITED))
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
call("auth", "register", {"name": "adm", "login": "adm", "password": "secret1"})
u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == "adm")
call("auth", "staff_save", {"id": u["id"], "role": "admin", "status": "active"}, token=TD)
TA = call("auth", "login", "adm", "secret1")[1]["token"]
st, body = call("api", "finmodel", M, token=TD)
check("director gets the model", st == 200 and near(body.get("operating", {}).get("amount"), 225750), (st, str(body)[:200]))
st, body = call("api", "finmodel_scenario", M, {"price": 10}, token=TD)
check("director runs a scenario", st == 200 and near(body.get("operating"), 277325), (st, body))
check("director gets the tile", call("api", "finmodel_brief", token=TD)[0] == 200)
for m, args in (("finmodel", [M]), ("finmodel_scenario", [M, {}]), ("finmodel_brief", [])):
    check(f"admin has no {m}", call("api", m, *args, token=TA)[0] == 403)
check("no session — no model", call("api", "finmodel", M)[0] in (401, 403))
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
