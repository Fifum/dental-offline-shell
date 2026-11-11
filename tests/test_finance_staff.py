"""3.4 «Финансы и персонал»: profit and loss by months (the financial model side by side, salaries with the motivation, no
double counting), the cash flow (real money only, accounts, refunds, certificates, expenses with and without documents,
moves inside the drawer, days / months, the shift reconciliation, «нет данных из Dentist Plus»), the administrators'
motivation (rules for all and own, bookings that came, new patients, CRM requests, own sales, the clinic's percent and
plan bonus, into the payroll and the profit), the timesheet (own marks, corrections, late / early / absent / outside the
schedule / no leaving, grace, people who never mark, stable keys between computers), the week and month report (content,
the moment to send, fake SMTP and Telegram, sent once, errors kept, quiet without channels), sync of the new tables,
rights over HTTP and the UI wiring."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import config  # noqa: E402
import daily  # noqa: E402
import db as dbm  # noqa: E402
import finreport  # noqa: E402
import replica  # noqa: E402
import timesheet as tsm  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402

UI = ROOT / "app" / "ui"


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
    except ValueError as e:
        check(name, text.lower() in str(e).lower(), str(e))
        return
    FAIL.append(f"{name}: no error")


def near(a, b, eps=0.02):
    return a is not None and b is not None and abs(a - b) <= eps


d = dbm.DB()
d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}, {"id": 2, "lname": "Сидорова", "fname": "Анна"}])
a = Api(d, W())
T = date.today()
TM = T.strftime("%Y-%m")
k = T.year * 12 + T.month - 2
PM = f"{k // 12:04d}-{k % 12 + 1:02d}"   # the previous month
P1 = f"{PM}-10"

# ------------------------------------------------------------------ data of the previous month
with d.tx() as c:
    c.execute("INSERT INTO invoices(id, patient_id, doctor_id, items, total, status, created_at, kind) VALUES(?,?,?,?,?,?,?,?)",
              ("i1", "p1", "1", "[]", 300000, "Оплачен", f"{P1} 10:00:00", "invoice"))
    for pid, amount, method, kind in (("pay1", 100000, "Наличные", ""), ("pay2", 150000, "Карта", ""), ("pay3", 30000, "СБП", ""),
                                      ("pay4", 5000, "Бонусы", ""), ("pay5", 7000, "Сертификат", ""), ("pay6", 20000, "Из аванса", "deposit_use"),
                                      ("pay7", -20000, "Из аванса", "deposit_use"), ("pay8", -10000, "Наличные", "refund"),
                                      ("pay9", 12000, "Страховая", "insurance")):
        c.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, created_at, kind) VALUES(?,?,?,?,?,?,?)",
                  (pid, "i1", "p1", amount, method, f"{P1} 12:00:00", kind))
    c.execute("INSERT INTO certificates(id, code, amount, balance, method, sold_at, sold_by, status) VALUES(?,?,?,?,?,?,?,?)",
              ("c1", "AAAA1", 8000, 8000, "Карта", f"{PM}-11 11:00:00", "Анна", "active"))
    c.execute("""INSERT INTO cash_shifts(id, opened_at, opened_by, open_cash, closed_at, closed_by, expected_cash, counted_cash, status)
                 VALUES(?,?,?,?,?,?,?,?,?)""", ("sh1", f"{PM}-10 09:00:00", "Анна", 5000, f"{PM}-10 21:00:00", "Анна", 95000, 94500, "closed"))
    c.execute("INSERT INTO cash_moves(id, shift_id, at, kind, amount, reason) VALUES(?,?,?,?,?,?)",
              ("mv1", "sh1", f"{PM}-10 20:00:00", "out", 50000, "Инкассация"))
a.save_salary_scheme({"person": "d:1", "percent": 30, "base": "paid"})
for f in ({"category": "Аренда", "amount": 60000, "date": f"{PM}-01", "method": "Безналичный перевод"},
          {"category": "Материалы и закупки", "amount": 20000, "date": f"{PM}-05", "method": "Карта"},
          {"category": "Налоги и взносы", "amount": 9000, "date": f"{PM}-25", "method": "Безналичный перевод"},
          {"category": "Зарплата", "person": "d:1", "period": PM, "amount": 50000, "date": f"{PM}-28", "method": "Наличные"}):
    a.save_expense(f)
a._daily.save({"category": "Хозяйственные расходы", "amount": 3000, "date": f"{PM}-12", "doc": False, "method": "Наличные из кассы"},
              "Админ", "anna", see_all=True)
a._daily.save({"category": "Транспорт и доставка", "amount": 700, "date": f"{PM}-12", "doc": True, "method": "Свои деньги сотрудника"},
              "Админ", "anna", see_all=True)

# ------------------------------------------------------------------ profit and loss by months
pl = a.fin_pnl(PM, TM)
R = {r["key"]: r for r in pl["rows"]}
fm = a._fm().pnl(PM)
check("two months", pl["months"] == [PM, TM] and len(pl["titles"]) == 2, pl["months"])
REV = 100000 + 150000 + 30000 + 7000 + 20000 - 20000 - 10000 + 12000  # everything but bonuses (a certificate was paid for before)
check("revenue as in the financial model", R["revenue"]["values"][0] == fm["revenue"] == REV, (R["revenue"], fm["revenue"]))
DOC = next(r for r in a.payroll(PM)["rows"] if r["key"] == "d:1")["by_percent"]
check("rows in order", [r["key"] for r in pl["rows"]][:2] == ["revenue", "variable"] and pl["rows"][-1]["key"] == "net", [r["key"] for r in pl["rows"]])
check("net equals the model", near(R["net"]["values"][0], fm["net"]["amount"]) and near(R["net"]["total"], fm["net"]["amount"] + R["net"]["values"][1]))
check("doctors' percent, payout not counted twice", near(R["doctors"]["values"][0], DOC) and DOC > 0 and "Зарплата" not in R, R["doctors"])
check("rent and the expense without a document", R["Аренда"]["values"][0] == 60000 and R["Хозяйственные расходы"]["values"][0] == 3000)
check("staff row first among fixed costs", [r["key"] for r in pl["rows"]].index("staff") == [r["key"] for r in pl["rows"]].index("fixed") + 1)
check("taxes", R["taxes"]["values"][0] == 9000)
check("salaries line", near(pl["salaries"][0], DOC), pl["salaries"])
check("share of revenue", R["revenue"]["share"] == 100.0)
check("current month flagged", pl["current"] == [False, True])
d6 = a.fin_pnl()
check("default — six months to this one", len(d6["months"]) == 6 and d6["months"][-1] == TM, d6["months"])
check("at most 24 months", len(a.fin_pnl("2000-01", "2030-12")["months"]) == 24)
check("the note about Dentist Plus payments", "Dentist Plus" in pl["note"])

# ------------------------------------------------------------------ cash flow
_, ma, mb = finreport._month_range(PM)
last = (date.fromisoformat(mb) - timedelta(days=1)).isoformat()
cf = a.fin_cashflow(ma, last)
check("money in: real money and certificates sold", cf["in"] == 100000 + 150000 + 30000 + 12000 + 8000, cf["in"])
check("not money: bonuses, certificate payments, advance moves", "Бонусы" not in cf["in_by_method"] and "Сертификат" not in cf["in_by_method"]
      and "Из аванса" not in cf["in_by_method"], cf["in_by_method"])
check("certificates sold", cf["certs"] == 8000 and cf["in_by_method"]["Продажа сертификатов"] == 8000)
check("refund goes out", cf["refunds"] == 10000 and cf["out_by_category"]["Возвраты пациентам"] == 10000)
OUT = 10000 + 60000 + 20000 + 9000 + 50000 + 3000 + 700
check("money out", cf["out"] == OUT and cf["net"] == cf["in"] - OUT, (cf["out"], OUT))
check("expenses without a document apart", cf["out_nodoc"] == 3000 and cf["out_doc"] == OUT - 10000 - 3000, (cf["out_doc"], cf["out_nodoc"]))
acc = {x["key"]: x for x in cf["accounts"]}
check("cash drawer", acc["cash"]["in"] == 100000 and acc["cash"]["out"] == 10000 + 50000 + 3000, acc["cash"])
check("bank: card, SBP, insurer, certificate by card", acc["bank"]["in"] == 150000 + 30000 + 12000 + 8000 and acc["bank"]["out"] == 60000 + 20000 + 9000, acc["bank"])
check("employee's own money", acc["staff"]["out"] == 700, acc.get("staff"))
check("collection is a move inside the drawer", acc["cash"]["moves_out"] == 50000 and cf["moves"] == {"Изъято: Инкассация": 50000}
      and acc["cash"]["net"] == 100000 - 63000 - 50000, (acc["cash"], cf["moves"]))
check("by days", cf["group"] == "day" and {r["period"] for r in cf["rows"]} >= {f"{PM}-10", f"{PM}-11", f"{PM}-12"}, [r["period"] for r in cf["rows"]])
check("running total", near(cf["rows"][-1]["cum"], cf["net"]), cf["rows"][-1])
day10 = next(r for r in cf["rows"] if r["period"] == f"{PM}-10")
check("a day by accounts", day10["by_acc"]["cash"]["in"] == 100000 and day10["by_acc"]["cash"]["out"] == 10000, day10)
cm = a.fin_cashflow(ma, last, "month")
check("by months", cm["group"] == "month" and [r["period"] for r in cm["rows"]] == [PM] and cm["net"] == cf["net"], cm["rows"])
check("long period becomes months", a.fin_cashflow(f"{T.year - 1}-01-01", T.isoformat(), "day")["group"] == "month")
sh = cf["shifts"][0] if cf["shifts"] else {}
check("shift reconciliation", cf["shift_diffs"] == 1 and near(sh["diff_cash"], sh["counted_cash"] - sh["expected_cash"]), cf["shifts"])
check("Dentist Plus payments: no data", cf["dp"]["payments"] is None and "API" in cf["dp"]["note"])

# ------------------------------------------------------------------ accounts for motivation and the timesheet
auth.Auth(d)
with d.tx() as c:
    for login, name, role, doc in (("anna", "Анна", "admin", None), ("olga", "Ольга", "admin", None), ("ira", "Ирина", "assistant", None),
                                   ("doc1", "Петров", "doctor", "1")):
        c.execute("INSERT INTO users(login, name, position, role, pass_hash, status, created_at, doctor_id) VALUES(?,?,?,?,?,?,?,?)",
                  (login, name, auth.ROLES[role]["title"], role, auth.hash_password("secret1"), "active", "2025-01-01 00:00:00", doc))
U = {r["login"]: r for r in d.q("SELECT * FROM users")}
K = {lg: f"u:{U[lg]['id']}" for lg in ("anna", "olga", "ira")}

# ------------------------------------------------------------------ motivation
pr0 = a.payroll(TM)
check("no rules — nothing changes", a.motivation_month(TM)["rows"] == [] and pr0["bonus"] == 0, pr0.get("bonus"))
r0 = a.motivation_rules()
check("rules list: staff without doctors, admins get the common rule", {s["login"] for s in r0["staff"]} == {"anna", "olga", "ira"}
      and next(s for s in r0["staff"] if s["login"] == "anna")["from_all"] and not next(s for s in r0["staff"] if s["login"] == "ira")["from_all"], r0["staff"])
refuses("percent up to 100", lambda: a.motivation_save({"person": "*", "sales_pct": 120}), "100")
refuses("no negative", lambda: a.motivation_save({"person": "*", "per_visit": -5}), "отрицательным")
refuses("unknown employee", lambda: a.motivation_save({"person": "u:999", "per_visit": 5}), "не найден")
a.motivation_save({"person": "*", "per_visit": 100, "per_new": 300, "lead_came": 200, "sales_pct": 5, "revenue_pct": 1, "plan_bonus": 2000})
check("own rule stored under the login", d.one("SELECT person FROM motivation_rules WHERE person='*'") is not None)

auth.set_current_user(U["anna"])
v1 = a.save_visit({"patient_id": "pnew", "doctor_id": "1", "start": f"{T.isoformat()}T08:00", "end": f"{T.isoformat()}T08:30"})
v2 = a.save_visit({"patient_id": "pold", "doctor_id": "2", "start": f"{T.isoformat()}T08:30", "end": f"{T.isoformat()}T09:00"})
v3 = a.save_visit({"patient_id": "pno", "doctor_id": "2", "start": f"{T.isoformat()}T07:00", "end": f"{T.isoformat()}T07:30"})
a.save_visit({"id": v2, "patient_id": "pold", "doctor_id": "2", "start": f"{T.isoformat()}T08:40", "end": f"{T.isoformat()}T09:10"})  # a move: not a booking
check("bookings logged for the employee", d.one("SELECT COUNT(*) AS n FROM staff_bookings WHERE login='anna'")["n"] == 3)
inv = a.save_invoice({"patient_id": "pold", "doctor_id": "2", "items": [{"title": "Отбеливание", "qty": 1, "price": 20000, "sum": 20000}], "total": 20000})
check("invoice stamped with who made it", d.one("SELECT created_by FROM invoices WHERE id=?", (inv,))["created_by"] == "anna")
auth.set_current_user(U["olga"])
a.save_visit({"patient_id": "pz", "doctor_id": "1", "start": f"{T.isoformat()}T07:00", "end": f"{T.isoformat()}T07:20"})
auth.set_current_user(None)
with d.tx() as c:  # pold had a visit before: not new
    c.execute("INSERT INTO visits_archive(id, patient_id, doctor_id, start, \"end\", status) VALUES(?,?,?,?,?,?)",
              ("old1", "pold", "2", "2024-01-10T10:00", "2024-01-10T10:30", "Завершён"))
    c.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, created_at) VALUES(?,?,?,?,?,?)",
              ("payS", inv, "pold", 20000, "Карта", f"{T.isoformat()} 08:50:00"))
    c.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, created_at) VALUES(?,?,?,?,?,?)",
              ("payB", inv, "pold", 1000, "Бонусы", f"{T.isoformat()} 08:51:00"))
    c.execute("INSERT INTO certificates(id, code, amount, balance, method, sold_at, sold_by, status) VALUES(?,?,?,?,?,?,?,?)",
              ("c2", "BBBB2", 5000, 5000, "Наличные", f"{T.isoformat()} 08:55:00", "Анна", "active"))
    c.execute("""INSERT INTO crm_leads(id, name, stage, assignee, created_at, created_by, closed_at) VALUES(?,?,?,?,?,?,?)""",
              ("L1", "Заявка", "came", "anna", f"{T.isoformat()} 07:00:00", "Ольга", f"{T.isoformat()} 09:00:00"))
    c.execute("""INSERT INTO crm_leads(id, name, stage, assignee, created_at, created_by, closed_at) VALUES(?,?,?,?,?,?,?)""",
              ("L2", "Заявка 2", "came", "", f"{T.isoformat()} 07:00:00", "Ольга", f"{T.isoformat()} 09:00:00"))
    c.execute("""INSERT INTO crm_leads(id, name, stage, assignee, created_at, created_by, closed_at) VALUES(?,?,?,?,?,?,?)""",
              ("L3", "Заявка 3", "lost", "anna", f"{T.isoformat()} 07:00:00", "Анна", f"{T.isoformat()} 09:00:00"))
a.set_visit_status(v1, "Пришёл")
a.set_visit_status(v2, "Завершён")
a.set_visit_status(v3, "Не пришёл")
mo = a.motivation_month(TM)
rows = {r["name"]: r for r in mo["rows"]}
an = {i["rule"]: i for i in rows["Анна"]["items"]}
check("admins with the common rule", set(rows) == {"Анна", "Ольга"}, list(rows))
check("bookings that came (a no-show does not count)", an["per_visit"]["count"] == 2 and an["per_visit"]["of"] == 3 and an["per_visit"]["amount"] == 200, an["per_visit"])
check("new patient: only a first visit", an["per_new"]["count"] == 1 and an["per_new"]["amount"] == 300, an["per_new"])
check("CRM requests that came: in charge", an["lead_came"]["count"] == 1, an["lead_came"])
ol = {i["rule"]: i for i in rows["Ольга"]["items"]}
check("CRM request without a person in charge goes to who created it", ol["lead_came"]["count"] == 1, ol["lead_came"])
check("visit not taken place: not counted for the other admin", ol["per_visit"]["count"] == 0 and ol["per_visit"]["of"] == 1, ol["per_visit"])
check("own sales: invoice payments without bonuses + certificate", an["sales_pct"]["base"] == 25000 and an["sales_pct"]["amount"] == 1250, an["sales_pct"])
rev_now = d.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE created_at >= ? AND method<>'Бонусы'", (f"{TM}-01",))["s"]
check("percent of the clinic's revenue", near(an["revenue_pct"]["amount"], rev_now / 100), an["revenue_pct"])
check("plan bonus without a plan", an["plan_bonus"]["amount"] == 0 and an["plan_bonus"]["plan"] is None, an["plan_bonus"])
a.kpi_save(TM, [{"scope": "clinic", "metric": "revenue", "value": 1000}])
an2 = {i["rule"]: i for i in a.motivation_month(TM)["rows"][0]["items"]}
check("plan met — bonus", an2["plan_bonus"]["done"] and an2["plan_bonus"]["amount"] == 2000, an2["plan_bonus"])
a.kpi_save(TM, [{"scope": "clinic", "metric": "revenue", "value": 10 ** 9}])
mo = a.motivation_month(TM)
total_anna = next(r["total"] for r in mo["rows"] if r["name"] == "Анна")
check("total of a person", near(total_anna, 200 + 300 + 200 + 1250 + rev_now / 100), total_anna)
pr = a.payroll(TM)
pa = next(r for r in pr["rows"] if r["key"] == K["anna"])
check("bonus in the payroll", near(pa["bonus"], total_anna) and near(pa["earned"], total_anna) and near(pr["bonus"], mo["total"]), pa)
check("an admin with a bonus is not «без схемы»", K["anna"] not in {u["key"] for u in pr["unset"]})
fmn = a._fm().pnl(TM)
staff = next(x for x in fmn["fixed"] if x["key"] == "staff")
check("bonus in the profit as staff pay", near(staff["amount"], mo["total"]), (staff["amount"], mo["total"]))
a.motivation_save({"person": K["olga"], "per_visit": 0, "revenue_pct": 2})
r1 = a.motivation_rules()
ol_rule = next(s for s in r1["staff"] if s["login"] == "olga")
check("own rule replaces the common one", ol_rule["own"] and ol_rule["rule"]["revenue_pct"] == 2 and ol_rule["rule"]["per_visit"] == 0, ol_rule)
check("own rule is kept under the login", d.one("SELECT 1 AS x FROM motivation_rules WHERE person='login:olga'") is not None)
ol2 = next(r for r in a.motivation_month(TM)["rows"] if r["name"] == "Ольга")
check("own rule counted", [i["rule"] for i in ol2["items"]] == ["revenue_pct"] and ol2["own"], ol2)
a.motivation_save({"person": K["ira"], "per_visit": 50})
check("an assistant with an own rule", any(r["name"] == "Ирина" for r in a.motivation_month(TM)["rows"]))
a.motivation_save({"person": K["olga"], "reset": True})
check("reset to the common rule", not next(s for s in a.motivation_rules()["staff"] if s["login"] == "olga")["own"])
a.motivation_save({"person": K["ira"], "reset": True})

# ------------------------------------------------------------------ timesheet
refuses("clock without an account", lambda: a._ts.clock(None, "in"), "своей учётной записью")
auth.set_current_user(U["ira"])
me = a.time_me()
check("me: not marked yet", me["can"] and me["state"] == "out" and me["person"] == K["ira"], me)
refuses("leaving before coming", lambda: a.time_clock("out"), "приход")
me = a._ts.clock(U["ira"], "in", datetime.combine(T, datetime.min.time()).replace(hour=9, minute=12))
check("arrival", me["state"] == "in" and me["came"] == "09:12", me)
me = a._ts.clock(U["ira"], "in", datetime.combine(T, datetime.min.time()).replace(hour=9, minute=40))
check("second «пришёл» keeps the first time", me["came"] == "09:12", me)
me = a._ts.clock(U["ira"], "out", datetime.combine(T, datetime.min.time()).replace(hour=17, minute=30))
check("leaving", me["state"] == "left" and me["left"] == "17:30", me)
me = a._ts.clock(U["ira"], "in", datetime.combine(T, datetime.min.time()).replace(hour=17, minute=45))
check("coming back reopens the day", me["state"] == "in" and me["came"] == "09:12" and not me["left"], me)
a._ts.clock(U["ira"], "out", datetime.combine(T, datetime.min.time()).replace(hour=18, minute=10))
check("stored under the login", d.one("SELECT person FROM time_marks WHERE id=?", (f"login:ira|{T.isoformat()}",))["person"] == "login:ira")
a._ts.clock(U["doc1"], "in", datetime.combine(T, datetime.min.time()).replace(hour=8, minute=55))
check("a doctor's account marks as the doctor", d.one("SELECT 1 AS x FROM time_marks WHERE id=?", (f"d:1|{T.isoformat()}",)) is not None)
auth.set_current_user(None)

# a past week with a schedule
D0 = T - timedelta(days=T.weekday() + 7)       # Monday of last week
days = [(D0 + timedelta(days=i)).isoformat() for i in range(7)]
for i in range(5):
    a.save_shift({"person": K["anna"], "date": days[i], "start": "09:00", "end": "18:00"})
a.save_shift({"person": "d:2", "date": days[0], "start": "10:00", "end": "16:00"})
refuses("future marks are refused", lambda: a.time_mark_save({"person": K["anna"], "date": (T + timedelta(days=2)).isoformat(), "came": "09:00"}), "будущий")
refuses("leaving before coming refused", lambda: a.time_mark_save({"person": K["anna"], "date": days[0], "came": "10:00", "left": "09:00"}), "позже")
refuses("unknown person", lambda: a.time_mark_save({"person": "u:999", "date": days[0], "came": "09:00"}), "не найден")
a.time_mark_save({"person": K["anna"], "date": days[0], "came": "09:03", "left": "18:00"})          # ok (grace 5)
a.time_mark_save({"person": K["anna"], "date": days[1], "came": "09:20", "left": "18:00"})          # late 20
a.time_mark_save({"person": K["anna"], "date": days[2], "came": "09:00", "left": "17:00", "note": "отпросилась"})  # early 60
a.time_mark_save({"person": K["anna"], "date": days[3], "came": "09:00"})                         # no leaving
a.time_mark_save({"person": K["anna"], "date": days[5], "came": "10:00", "left": "14:00"})          # Saturday, outside
# days[4]: planned, nothing — absent
p = a._ts.period(days[0], days[6])
an = next(r for r in p["rows"] if r["key"] == K["anna"])
st = {dd: c["status"] for dd, c in an["cells"].items()}
check("statuses", st == {days[0]: "ok", days[1]: "late", days[2]: "early", days[3]: "noleave", days[4]: "absent", days[5]: "extra"}, st)
t = an["totals"]
check("totals", t["late_n"] == 1 and t["late_min"] == 20 and t["early_n"] == 1 and t["early_min"] == 60 and t["absent_n"] == 1
      and t["noleave_n"] == 1 and t["extra_n"] == 1 and t["days"] == 5 and t["plan_h"] == 45 and t["fact_h"] == round((537 + 520 + 480 + 240) / 60, 2), t)
check("corrections are flagged", t["edited_n"] == 5 and an["cells"][days[2]]["edited"] and an["cells"][days[2]]["note"] == "отпросилась")
doc2 = next(r for r in p["rows"] if r["key"] == "d:2")
check("who never marks is not absent", not doc2["tracked"] and doc2["cells"][days[0]]["status"] == "untracked" and doc2["totals"]["absent_n"] == 0, doc2)
check("those who mark come first", p["rows"][-1]["key"] == "d:2")
tsm.save_settings(d, {"late_grace": 25})
an = next(r for r in a._ts.period(days[0], days[6])["rows"] if r["key"] == K["anna"])
check("grace changes the lateness", an["cells"][days[1]]["status"] == "ok" and an["totals"]["late_n"] == 0)
refuses("grace limits", lambda: tsm.save_settings(d, {"late_grace": 500}), "120")
tsm.save_settings(d, {"late_grace": 5})
a.time_mark_save({"person": K["anna"], "date": days[5], "came": "", "left": ""})
check("empty correction removes the mark", d.one("SELECT 1 AS x FROM time_marks WHERE id=?", (f"login:anna|{days[5]}",)) is None)
sm = a._ts.summary(days[0], days[6])
check("summary for the report: only those who mark", [x["name"] for x in sm] == ["Анна"] and sm[0]["late_n"] == 1, sm)
tm = a.timesheet(D0.strftime("%Y-%m"))
check("month for the director", tm["all"] and tm["can_edit"] and any(r["key"] == K["anna"] for r in tm["rows"]))
check("stable keys", tsm.stable(d, K["anna"]) == "login:anna" and tsm.local(d, "login:anna") == K["anna"] and tsm.stable(d, "d:1") == "d:1")

# ------------------------------------------------------------------ the week and month report
key, wa, wb = finreport.period_of("week", today=T)
check("last full week", wa.weekday() == 0 and (wb - wa).days == 6 and wb < T and key == f"week:{wa.isoformat()}")
key, ma_, mb_ = finreport.period_of("month", today=T)
check("last month", key == f"month:{PM}" and ma_.day == 1 and (mb_ + timedelta(days=1)).day == 1)
rp = a.period_report("month", f"{PM}-15")
check("month report: money, P&L, payroll, timesheet", rp["key"] == f"month:{PM}" and rp["money"]["in"] == cf["in"] and "pnl" in rp
      and "Прибыль и убытки" in rp["text"] and "Зарплата: начислено" in rp["text"] and "Dentist Plus" in rp["text"], rp["text"][:400])
pm0 = (date.fromisoformat(rp["from"]) - timedelta(days=1)).replace(day=1).isoformat()
check("month report compares with the month before", rp["prev_from"] == pm0 and rp["prev_to"] < rp["from"], (rp["prev_from"], rp["prev_to"]))
rw = a.period_report("week", days[2])
check("week report: from Monday, the week's lines, the timesheet", rw["from"] == days[0] and rw["to"] == days[6] and "Табель:" in rw["text"]
      and "Анна" in rw["text"] and "опозданий 1" in rw["text"] and rw["lines"], rw["text"][-600:])
check("no channels — nothing due, sending explains", a._prep.due(datetime.combine(T, datetime.min.time()).replace(hour=23)) == [])
refuses("not configured", lambda: a.period_report_send("week"), "не настроена")
check("report xlsx", a._prep.xlsx(rw)[:2] == b"PK")
check("subject neutral", rw["subject"].startswith((config.BRAND.get("name") or "Клиника") + ": отчёт за неделю"), rw["subject"])

daily.save_settings({"enabled": True, "to": "boss@mail.ru", "login": "clinic@yandex.ru", "password": "app-pass", "time": "21:00"})
SENT = []


class FakeSMTP:
    fail = None

    def __init__(self, host, port, timeout=30, context=None):
        if FakeSMTP.fail:
            raise FakeSMTP.fail

    def login(self, user, pw):
        SENT.append(("login", user, pw))

    def send_message(self, msg):
        SENT.append(("msg", msg))

    def quit(self):
        pass


daily.smtplib.SMTP_SSL = FakeSMTP
st = a.period_report_send("week", days[0])
msg = [x[1] for x in SENT if x[0] == "msg"][-1]
check("week report sent by mail", st["status"] == "sent" and st["where"] == "почта: boss@mail.ru" and "отчёт за неделю" in msg["Subject"]
      and any((pp.get_filename() or "").endswith(".xlsx") for pp in msg.iter_attachments()) and "Табель" in msg.get_body(("plain",)).get_content(), st)
n = len(SENT)
check("sent once without «again»", a._prep.send("week", days[0])["status"] == "sent" and len(SENT) == n)
mon_ = D0 + timedelta(days=7)  # this week's Monday
check("due on Monday after the time", ("week", days[0]) not in a._prep.due(datetime.combine(mon_, datetime.min.time()).replace(hour=22)))
with d.tx() as c:
    c.execute("DELETE FROM period_reports")
check("due on Monday after the time (not sent)", ("week", days[0]) in a._prep.due(datetime.combine(mon_, datetime.min.time()).replace(hour=22)))
check("not before the time on Monday", not any(k_ == "week" for k_, _ in a._prep.due(datetime.combine(mon_, datetime.min.time()).replace(hour=9))))
check("Tuesday catches up", ("week", days[0]) in a._prep.due(datetime.combine(mon_ + timedelta(days=1), datetime.min.time()).replace(hour=9)))
check("Thursday — too late", not any(k_ == "week" for k_, _ in a._prep.due(datetime.combine(mon_ + timedelta(days=3), datetime.min.time()).replace(hour=22))))
first = T.replace(day=1)
check("month due on the 1st after the time", any(k_ == "month" for k_, _ in a._prep.due(datetime.combine(first, datetime.min.time()).replace(hour=22))))
check("month not on the 5th", not any(k_ == "month" for k_, _ in a._prep.due(datetime.combine(first + timedelta(days=4), datetime.min.time()).replace(hour=22))))
daily.save_settings({"week_on": False})
check("week switched off", not any(k_ == "week" for k_, _ in a._prep.due(datetime.combine(mon_, datetime.min.time()).replace(hour=22))))
check("settings carry the switches", daily.public_settings()["week_on"] is False and daily.public_settings()["month_on"] is True)
daily.save_settings({"week_on": True})
FakeSMTP.fail = OSError("no network")
refuses("offline: error, retried later", lambda: a.period_report_send("month", f"{PM}-01"), "повторит")
check("error kept", a._prep.state(f"month:{PM}")["status"] == "error")
FakeSMTP.fail = None
st = a.period_report_send("month", f"{PM}-01", False)
check("month sent after the error", st["status"] == "sent", st)
check("journal label", "period_report_send" in auth.AUDITED)

# Telegram (fake Bot API)
import requests  # noqa: E402
TG = []


class FakeResp:
    def __init__(self, code, j):
        self.status_code, self._j = code, j

    def json(self):
        return self._j


def fake_post(url, data=None, files=None, timeout=None):
    method = url.rsplit("/", 1)[1]
    TG.append((method, data, bool(files)))
    if method == "sendMessage":
        return FakeResp(200, {"ok": True, "result": {"chat": {"id": data["chat_id"], "first_name": "Владелец"}}})
    return FakeResp(200, {"ok": True, "result": {}})


requests.post = fake_post
daily.save_settings({"enabled": False, "tg_on": True, "tg_token": "123456:ABCdef", "tg_chats": [{"id": 501, "name": "Владелец"}]})
with d.tx() as c:
    c.execute("DELETE FROM period_reports")
st = a.period_report_send("week", days[0])
check("week report in Telegram", st["status"] == "sent" and "Telegram" in st["where"] and any(m == "sendDocument" for m, _, _ in TG)
      and any("Поступило денег" in (dd or {}).get("text", "") for m, dd, _ in TG if m == "sendMessage"), (st, TG[:2]))
a._prep._last_tick = 0
a._prep.tick()
check("tick waits 5 minutes", a._prep._last_tick > 0 and a._prep.tick() is None)
daily.save_settings({"tg_on": False})

# ------------------------------------------------------------------ sync of the new tables
names = {t.name for t in replica.TABLES}
check("new tables are synced", {"time_marks", "staff_settings", "motivation_rules", "staff_bookings", "period_reports"} <= names)
replica.install(d)
d2 = dbm.DB(Path(tempfile.mkdtemp()) / "b.db")
a2 = Api(d2, W())
auth.Auth(d2)
auth.Auth(d)  # role lookups of the first computer
replica.install(d2)
with d2.tx() as c:  # the same accounts with other integer ids on the other computer
    for login in ("zz", "olga", "ira", "anna"):
        c.execute("INSERT INTO users(login, name, role, status, created_at) VALUES(?,?,?,?,?)", (login, login.title(), "admin", "active", "2025-01-01"))
replica.set_applying(d2.conn, True)
for tn in ("time_marks", "motivation_rules", "staff_bookings", "period_reports", "staff_settings"):
    t_ = replica.BY_NAME[tn]
    for row in d.q(f"SELECT {', '.join(t_.key)} FROM {tn}"):
        kk = [row[x] for x in t_.key]
        replica.write_row(d2.conn, t_, kk, replica.read_row(d.conn, t_, kk))
t_inv = replica.BY_NAME["invoices"]
row = replica.read_row(d.conn, t_inv, [inv])
check("invoice travels with who made it", row.get("created_by") == "anna", row)
replica.write_row(d2.conn, t_inv, [inv], row)
replica.set_applying(d2.conn, False)
d2.conn.commit()
anna2 = f"u:{d2.one('SELECT id FROM users WHERE login=?', ('anna',))['id']}"
check("ids differ between computers", anna2 != K["anna"])
p2 = a2._ts.period(days[0], days[6])
check("the other computer shows the marks under its own key", any(r["key"] == anna2 and len(r["cells"]) == 4 for r in p2["rows"]), [r["key"] for r in p2["rows"]])
check("motivation rule arrives", a2.motivation_rules()["all"]["per_visit"] == 100)
check("sent reports known on the other computer", a2._prep.state(f"week:{days[0]}")["status"] == "sent")

# ------------------------------------------------------------------ rights over HTTP
check("every new method has a right", all(m in auth.METHOD_PERMS for m in (
    "fin_pnl", "fin_cashflow", "motivation_rules", "motivation_save", "motivation_month", "period_report", "period_report_send",
    "time_me", "time_clock", "timesheet", "time_mark_save", "timesheet_settings_save")))
check("changes in the journal", {"motivation_save", "time_clock", "time_mark_save", "timesheet_settings_save"} <= set(auth.AUDITED))
check("reading not journaled", not {"fin_pnl", "fin_cashflow", "timesheet", "time_me", "motivation_month", "period_report"} & set(auth.AUDITED))
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
d3 = dbm.DB(Path(tempfile.mkdtemp()) / "c.db")
d3.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}])
a3 = Api(d3, W())
srv = ClinicServer(a3, d3, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
tok = {}
for login, role in (("adm", "admin"), ("asst", "assistant"), ("acc", "admin")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
    tok[login] = call("auth", "login", login, "secret1")[1]["token"]
for m in ("fin_pnl", "fin_cashflow", "motivation_rules", "motivation_month", "period_report"):
    check(f"director: {m}", call("api", m, token=TD)[0] == 200, call("api", m, token=TD))
    check(f"administrator without «Бухгалтерия»: {m}", call("api", m, token=tok["adm"])[0] == 403)
check("administrator cannot change motivation", call("api", "motivation_save", {"person": "*", "per_visit": 1}, token=tok["adm"])[0] == 403)
st_, body = call("api", "time_clock", "in", token=tok["asst"])
check("assistant marks own arrival", st_ == 200 and body["state"] == "in", (st_, body))
st_, body = call("api", "timesheet", token=tok["asst"])
check("assistant sees only own days", st_ == 200 and not body["all"] and [r["name"] for r in body["rows"]] == ["asst"], (st_, str(body)[:200]))
check("assistant cannot correct", call("api", "time_mark_save", {}, token=tok["asst"])[0] == 403)
st_, body = call("api", "timesheet", token=tok["adm"])
check("administrator (makes schedules) sees everyone", st_ == 200 and body["all"] and body["can_edit"], (st_, str(body)[:200]))
asst_key = next(r["key"] for r in body["rows"] if r["name"] == "asst")
st_, body = call("api", "time_mark_save", {"person": asst_key, "date": T.isoformat(), "came": "08:00", "left": ""}, token=tok["adm"])
check("administrator corrects a mark", st_ == 200 and body["came"] == "08:00" and body["edited"] == 1, (st_, body))
st_, body = call("api", "timesheet", token=TD)
check("director sees everyone", st_ == 200 and body["all"])
au = call("auth", "audit_list", token=TD)[1]
check("arrival in the action journal", any(x["action"] == auth.AUDITED["time_clock"] and x["user_name"] == "asst" for x in au))
check("correction in the action journal", any(x["action"] == auth.AUDITED["time_mark_save"] and x["user_name"] == "adm" for x in au))
auth.set_current_user(None)
st_, body = call("api", "save_visit", {"patient_id": "1", "doctor_id": "1", "start": f"{T.isoformat()}T10:00", "end": f"{T.isoformat()}T10:30"}, token=tok["adm"])
check("a booking over HTTP is logged for its author", st_ == 200 and d3.one("SELECT login FROM staff_bookings WHERE id=?", (body,))["login"] == "adm", (st_, body))
st_, body = call("api", "status", token=tok["asst"])
check("status still fine for staff", st_ == 200)
srv.stop()

# ------------------------------------------------------------------ the UI
html = (UI / "index.html").read_text(encoding="utf-8")
js = (UI / "finstaff.js").read_text(encoding="utf-8")
check("version 3.4.0 or later", tuple(map(int, config.VERSION.split("."))) >= (3, 4, 0), config.VERSION)
check("finstaff.js with the cache tag", f'<script src="finstaff.js?v={config.VERSION}"></script>' in html)
check("no old cache tags", "?v=3.3.0" not in html)
check("tabs in «Бухгалтерия»", all(f'data-k="{k}"' in html for k in ("pnl", "cashflow", "motivation")))
check("«График | Табель»", 'id="shTabs"' in html and 'data-k="fact"' in html)
check("«Я пришёл» in the user menu", 'id="ucClock"' in html)
check("screens", all(f"function {f}" in js for f in ("accPnl", "accCashflow", "accMotivation", "openPeriodReport", "loadTimesheet", "editMark")))
check("the screens say Dentist Plus gives no payments", "в API Dentist Plus нет оплат" in js and "нет данных из Dentist Plus" in js)
acc_js = (UI / "accounting.js").read_text(encoding="utf-8")
check("tabs wired", "accPnl" in acc_js and "accCashflow" in acc_js and "accMotivation" in acc_js)
check("timesheet tab wired", "loadTimesheet" in (UI / "shifts.js").read_text(encoding="utf-8"))
check("report switches in the settings", 'id="drWeek"' in (UI / "daily.js").read_text(encoding="utf-8"))
notes = ROOT / "docs" / f"Что нового в версии {'.'.join(config.VERSION.split('.')[:2])}.txt"
check("what's new", notes.exists() and "Dental Desk" in notes.read_text(encoding="utf-8"), notes)
check("README section", "## Finance and staff (3.4)" in (ROOT / "README.md").read_text(encoding="utf-8"))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  ✗", f)
sys.exit(1 if FAIL else 0)
