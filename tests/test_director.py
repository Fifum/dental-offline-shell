"""Director's analytics: visit history that outlives the mirror, main screen, new and repeat patients, retention,
chair and doctor load, conversion «consultation → plan → treatment», materials in revenue, plan vs fact, rights."""
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
import replica  # noqa: E402
from director import HIST  # noqa: E402
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


T = date.today()


def day(n):
    return (T + timedelta(days=n)).isoformat()


def visit(vid, pid, did, n, status="Завершён", h=10, chair="1"):
    s, e = f"{day(n)} {h:02d}:00:00", f"{day(n)} {h + 1:02d}:00:00"
    return {"id": vid, "patient_id": pid, "doctor_id": did, "branch_id": None, "start": s, "end": e, "status": status,
            "title": "Приём", "raw": {"id": vid, "chair": chair}}


d = dbm.DB()
d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр", "mname": "Петрович"}, {"id": 2, "lname": "Сидорова", "fname": "Анна"}])
d.upsert_patients([{"id": i, "lname": f"Пациент{i}", "fname": "Тест"} for i in range(1, 8)])
VIS = [
    visit("v1a", "1", "1", -200), visit("v1b", "1", "1", -150),   # P1: new long ago, came back within 90 days
    visit("v2a", "2", "1", -200),                                 # P2: one visit 200 days ago, nothing booked → gone
    visit("v3", "3", "2", -10),                                   # P3: new in the period, doctor 2
    visit("v1c", "1", "1", -9),                                   # P1 again: repeat
    visit("v4", "4", "2", -8, status="Не пришёл"),                # P4: missed — not a patient yet
    visit("v6", "6", "2", -12),                                   # removed from Dentist Plus later
    visit("v5", "5", "2", 3, status="Запланирован"),              # booked ahead
]
d.replace_visits(day(-400), day(10), VIS)
a = Api(d, W())
check("archive filled", d.one("SELECT COUNT(*) AS n FROM visits_archive")["n"] == len(VIS))

# --- the mirror keeps 30 days, the history stays
d.purge(30)
check("mirror purged", d.one("SELECT COUNT(*) AS n FROM visits WHERE start < ?", (day(-30),))["n"] == 0)
hist = d.q(f"SELECT id FROM ({HIST})")
check("history keeps old visits", {"v1a", "v1b", "v2a"} <= {r["id"] for r in hist}, hist)
check("no duplicates in history", len(hist) == len({r["id"] for r in hist}), hist)
d.replace_visits(day(-12), day(-12), [])  # v6 was deleted in Dentist Plus
check("deleted visit leaves the archive", not d.one("SELECT 1 AS x FROM visits_archive WHERE id='v6'"))
check("visits outside the window stay", d.one("SELECT 1 AS x FROM visits_archive WHERE id='v1a'"))
lv = a._local.save_visit({"id": "v3", "patient_id": "3", "doctor_id": "2", "start": f"{day(-10)} 10:00:00",
                          "end": f"{day(-10)} 11:00:00", "status": "Завершён"})
p3 = [r for r in d.q(f"SELECT id, patient_id FROM ({HIST})") if r["patient_id"] == "3"]
check("a local edit replaces the synced visit once", len(p3) == 1 and p3[0]["id"] == lv, p3)
first = a._dir._first_visits()
check("first visit from the archive", first["1"] == (day(-200), "1") and first["3"] == (day(-10), "2"), first)
check("missed visit is not a first visit", "4" not in first, first)

# --- new and repeat patients, retention, gone
pr = a.report_patients(day(-20), day(-1))
check("patients in period", pr["patients"] == 2 and pr["new"] == 1 and pr["repeat"] == 1, pr)
check("new by doctor", any(x["doctor_id"] == "2" and x["new"] == 1 for x in pr["by_doctor"]), pr["by_doctor"])
coh = {c["month"]: c for c in pr["cohorts"]}
old = coh.get(day(-200)[:7])
check("cohort of 200 days ago", old and old["new"] == 2 and old["r90"] == 1 and old["p90"] == 50.0, pr["cohorts"])
check("fresh cohort is too early to judge", coh.get(day(-10)[:7], {}).get("p180") is None, pr["cohorts"])
check("gone patients", pr["gone"] == 1, pr["gone"])
check("history start", pr["history_from"] == day(-200), pr["history_from"])

# --- load: chairs × working hours, doctor by the work schedule, weekday × hour
refuses("chairs must be a number", lambda: a.director_settings_save({"chairs": "много"}), "Кресел")
a.director_settings_save({"chairs": "2"})
check("chairs saved", a.director_settings()["chairs"] == 2)
with d.tx() as c:
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              ("d:2", day(-10), "09:00", "15:00", "", "тест", "now"))
ld = a.report_load(day(-10), day(-10))
cap = 2 * (21 - 8) * 60
check("capacity", ld["capacity"] == cap and ld["workdays"] == 1, ld)
check("load share", ld["booked"] == 60 and abs(ld["load"] - round(60 * 100 / cap, 1)) < 0.01, ld)
doc2 = next(x for x in ld["by_doctor"] if x["doctor_id"] == "2")
check("doctor load by schedule", doc2["by_shifts"] and doc2["available"] == 360 and doc2["load"] == 16.7, doc2)
row = next(x for x in ld["heat"] if x["days"] == 1)
check("heat cell at 10:00", row["cells"][10 - 8] == 50.0, row)
ld2 = a.report_load(day(-10), day(-8))
check("missed visit is lost time", ld2["lost"] == 60, ld2["lost"])

# --- conversion: consultation → plan → treatment; a bill from a plan points to it
pl = a.save_invoice({"patient_id": "3", "doctor_id": "2", "kind": "plan", "items": [{"title": "Имплант", "price": 50000}]})
inv = a.plan_to_invoice(pl)
check("invoice keeps its plan", d.one("SELECT plan_id FROM invoices WHERE id=?", (inv,))["plan_id"] == pl)
pl2 = a.save_invoice({"patient_id": "1", "doctor_id": "1", "kind": "plan", "items": [{"title": "Коронка", "price": 20000}]})
a.set_plan_status(pl2, "Отказ")
cv = a.report_conversion(day(-20), day(0))
c2 = next(x for x in cv["by_doctor"] if x["doctor_id"] == "2")
c1 = next(x for x in cv["by_doctor"] if x["doctor_id"] == "1")
check("consultation with a plan, started", c2["consult"] == 1 and c2["with_plan"] == 1 and c2["started"] == 1, c2)
check("plan billed", c2["plans"] == 1 and c2["plans_started"] == 1 and c2["billed"] == 50000 and c2["sum_rate"] == 100.0, c2)
check("refused plan", c1["plans"] == 1 and c1["refused"] == 1 and c1["plans_started"] == 0, c1)
check("totals", cv["total"]["plans"] == 2 and cv["total"]["plans_rate"] == 50.0, cv["total"])

# --- materials in revenue: the real write-off, or the norms for an invoice made before them
with d.tx() as c:
    c.execute("INSERT INTO materials(id, name, unit, price, active, created_at) VALUES('m1','Композит','г',100,1,'now')")
    c.execute("INSERT INTO services(id, code, title, price, active) VALUES('s1','P1','Пломба',3000,1)")
    c.execute("INSERT INTO service_materials(service_id, material_id, qty) VALUES('s1','m1',2)")
i1 = a.save_invoice({"patient_id": "1", "doctor_id": "2", "items": [{"service_id": "s1", "title": "Пломба", "price": 3000}]})
with d.tx() as c:
    c.execute("""INSERT INTO invoices(id, patient_id, doctor_id, items, total, kind, status, created_at)
                 VALUES('old1','1','2',?,6000,'invoice','Оплачен',?)""",
              (json.dumps([{"service_id": "s1", "title": "Пломба", "price": 3000, "qty": 2, "sum": 6000}]), f"{day(0)} 09:00"))
mt = a.report_materials(day(0), day(0))
check("material cost", mt["cost"] == 600 and mt["by_service"].get("Пломба") == 600, mt)
check("estimated invoice counted", mt["estimated"] == 1 and mt["has_norms"], mt)
check("share", mt["share"] == round(600 * 100 / mt["billed"], 1), mt)

# --- plan vs fact
a.add_payment({"invoice_id": i1, "amount": 3000, "method": "Карта"})
month = T.strftime("%Y-%m")
refuses("bad month", lambda: a.kpi_save("2026-13", []), "Месяц")
refuses("bad metric", lambda: a.kpi_save(month, [{"scope": "clinic", "metric": "profit", "value": 1}]), "показатель")
refuses("unknown doctor", lambda: a.kpi_save(month, [{"scope": "d:99", "metric": "revenue", "value": 1}]), "врачу")
refuses("negative", lambda: a.kpi_save(month, [{"scope": "clinic", "metric": "revenue", "value": -5}]), "от 0")
refuses("not a number", lambda: a.kpi_save(month, [{"scope": "clinic", "metric": "revenue", "value": "сто"}]), "число")
a.kpi_save(month, [{"scope": "clinic", "metric": "revenue", "value": "100 000"}, {"scope": "d:2", "metric": "revenue", "value": 6000},
                   {"scope": "d:2", "metric": "visits", "value": "10"}])
k = a.kpi(month)
check("clinic plan", k["clinic"]["metrics"]["revenue"]["plan"] == 100000, k["clinic"])
check("clinic fact", k["clinic"]["metrics"]["revenue"]["fact"] >= 3000, k["clinic"])
kd = next(x for x in k["doctors"] if x["scope"] == "d:2")
check("doctor fact and percent", kd["metrics"]["revenue"]["fact"] == 3000 and kd["metrics"]["revenue"]["pct"] == 50.0, kd)
check("forecast not below fact", kd["metrics"]["revenue"]["forecast"] >= 3000, kd)
a.kpi_save(month, [{"scope": "d:2", "metric": "visits", "value": ""}])
check("empty value removes the plan", next(x for x in a.kpi(month)["doctors"] if x["scope"] == "d:2")["metrics"]["visits"]["plan"] is None)
nxt = (T.replace(day=1) + timedelta(days=32)).strftime("%Y-%m")
refuses("nothing to copy", lambda: a.kpi_save((T.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"), [], copy_prev=True), "не задан")
a.kpi_save(nxt, [], copy_prev=True)
k2 = a.kpi(nxt)
check("copied from the previous month", k2["clinic"]["metrics"]["revenue"]["plan"] == 100000 and k2["prev_has_plan"], k2["clinic"])
check("future month has no facts", k2["clinic"]["metrics"]["revenue"]["fact"] == 0, k2["clinic"])

# --- main screen
ds = a.director_dashboard()
check("dashboard parts", {"today", "month", "ahead", "doctors", "advice", "plans_open", "debts", "chairs"} <= set(ds), list(ds))
check("month paid", ds["month"]["paid"] >= 3000 and ds["month"]["plan"] == 100000, ds["month"])
check("forecast from pace", ds["month"]["forecast"] >= ds["month"]["paid"], ds["month"])
check("doctor on the screen", any(x["doctor_id"] == "2" and x["paid"] == 3000 and x["plan"] == 6000 for x in ds["doctors"]), ds["doctors"])
check("advice about the plan", any(x["go"] == "plan" for x in ds["advice"]), ds["advice"])
check("week ahead", all(0 <= x["load"] for x in ds["ahead"]) and len(ds["ahead"]) <= 7, ds["ahead"])
check("chairs from the setting", ds["chairs"] == 2)

# --- synced between laptops, permissions, journal
check("plans are synced", "kpi_targets" in replica.BY_NAME)
for m in ("director_dashboard", "report_patients", "report_load", "report_conversion", "report_materials", "kpi", "kpi_save",
          "director_settings", "director_settings_save"):
    check(f"perm {m}", m in auth.METHOD_PERMS and hasattr(a, m))
check("changes are journaled", "kpi_save" in auth.AUDITED and "director_settings_save" in auth.AUDITED)

# --- change capture: an UPSERT twice before a sync must not fail (2.7.0 triggers broke on it)
with d.tx() as c:  # an old-style trigger left by 2.7.0
    c.execute("""CREATE TRIGGER IF NOT EXISTS rp_kpi_targets_u AFTER UPDATE ON kpi_targets BEGIN
                 INSERT OR REPLACE INTO sync_dirty(tbl, k, at) VALUES('kpi_targets', json_array(NEW.id), 0); END""")
replica.install(d)
check("old triggers replaced", "DELETE FROM sync_dirty" in d.one("SELECT sql FROM sqlite_master WHERE name='rp_kpi_targets_u'")["sql"])
check("trigger version stored", d.one("SELECT v FROM sync_state WHERE k='trigger_ver'")["v"] == replica.TRIGGER_VER)
try:
    for _ in range(2):
        a.kpi_save(month, [{"scope": "clinic", "metric": "visits", "value": 50}])
        a.save_material({"id": "m1", "name": "Композит", "unit": "г", "price": 110})
        a.save_supplier({"id": "sup1", "name": "Поставщик"})
    check("upsert twice before a sync", True)
except Exception as e:  # noqa: BLE001
    check("upsert twice before a sync", False, e)
check("change captured once", d.one("SELECT COUNT(*) AS n FROM sync_dirty WHERE tbl='materials' AND k=?", (json.dumps(["m1"]),))["n"] == 1)
check("plan update captured", d.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='kpi_targets' AND k=?", (json.dumps([f"{month}:clinic:visits"]),)))

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
check("director sees the screen", call("api", "director_dashboard", token=TD)[0] == 200)
check("director saves a plan", call("api", "kpi_save", month, [{"scope": "clinic", "metric": "new_patients", "value": 5}], token=TD)[0] == 200)
check("plan save journaled", d.one("SELECT 1 AS x FROM audit WHERE action='План на месяц'"))
check("admin has no director screen", call("api", "director_dashboard", token=TA)[0] == 403)
check("doctor cannot set plans", call("api", "kpi_save", month, [], token=TDoc)[0] == 403)
check("doctor no load report", call("api", "report_load", token=TDoc)[0] == 403)
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
