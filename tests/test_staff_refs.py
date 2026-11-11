"""3.6.1: staff in the work schedules, the pay schemes and the salary payouts by login, not by the local account id.

Two laptops whose accounts have different local ids (the id of Anna on one is the id of Olga on the other) sync the
schedules, pay schemes and payouts both ways and every row stays with the right person; the migration on start
converts the rows written on this computer (idempotent), keeps the rows of accounts that are gone and the rows that
came from a computer with an older version as «неизвестный сотрудник» (never under somebody else), and the payroll and
the timesheet give the same results as with data entered under 3.6.1 from the start. Doctors stay «d:<id>»."""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import replica  # noqa: E402
import staffref  # noqa: E402
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
    except ValueError as e:
        check(name, text.lower() in str(e).lower(), str(e))
        return
    FAIL.append(f"{name}: no error")


def laptop(name, logins):
    """A computer of the clinic with its own database; accounts created here one by one (so ids differ)."""
    d = dbm.DB(Path(tempfile.mkdtemp()) / f"{name}.db")
    a = Api(d, W())
    auth.Auth(d)
    with d.tx() as c:
        for lg in logins:
            c.execute("INSERT INTO users(login, name, position, role, status, created_at) VALUES(?,?,?,?,?,?)",
                      (lg, lg.title(), "Администратор", "admin", "active", "2025-01-01"))
        c.execute("INSERT INTO doctors VALUES('1', 'Доктор', NULL, '{}', '2025-01-01')")  # from Dentist Plus: the same id everywhere
    replica.install(d)
    return d, a


def uid(d, login):
    return d.one("SELECT id FROM users WHERE login=?", (login,))["id"]


def sync(src, node_src, dst, node_dst):
    """Everything the source has that the destination does not, the way two computers sync (stamp → versions)."""
    replica.stamp(src, node_src)
    items = replica.changes_since(src, 0, limit=100000)
    return replica.apply_versions(dst, items, node_dst)


def both(da, db_, na="nodeA", nb="nodeB"):
    sync(da, na, db_, nb)
    sync(db_, nb, da, na)


T = date.today()
M = T.strftime("%Y-%m")
D1 = T.replace(day=1).isoformat()
D2 = T.replace(day=2).isoformat()
D3 = T.replace(day=3).isoformat()

# ------------------------------------------------------------------ the keys
dA, aA = laptop("a", ["zz", "anna", "olga"])        # A: zz=1, anna=2, olga=3
dB, aB = laptop("b", ["yy", "olga", "anna"])        # B: yy=1, olga=2, anna=3
annaA, olgaA, annaB, olgaB = (f"u:{uid(dA, 'anna')}", f"u:{uid(dA, 'olga')}", f"u:{uid(dB, 'anna')}", f"u:{uid(dB, 'olga')}")
check("the id of Anna on A is the id of Olga on B", annaA == olgaB and annaA != annaB, (annaA, olgaB, annaB))
check("screen key → stored login", staffref.to_store(dA, annaA) == "login:anna" and staffref.to_store(dB, annaB) == "login:anna")
check("stored login → the key of this computer", staffref.to_screen(dA, "login:anna") == annaA and staffref.to_screen(dB, "login:anna") == annaB)
check("a doctor stays as he is", staffref.to_store(dA, "d:7") == "d:7" and staffref.to_screen(dA, "d:7") == "d:7")
check("a leftover u: is never somebody here", staffref.to_screen(dA, annaA) == "x:" + annaA and staffref.is_unknown("x:" + annaA))
check("a login nobody here has is unknown", staffref.to_screen(dA, "login:petr") == "x:login:petr"
      and staffref.unknown_name("x:login:petr") == "неизвестный сотрудник (petr)" and staffref.unknown_name("x:u:9") == "неизвестный сотрудник")
check("an unknown key goes back to what is stored", staffref.to_store(dA, "x:u:9") == "u:9" and staffref.to_store(dA, "x:login:petr") == "login:petr")
asrc = (ROOT / "app" / "auth.py").read_text(encoding="utf-8")
check("a login is never changed (so it is a stable key)", "SET login" not in asrc and " login=?" not in asrc.split("def staff_save")[1].split("def ")[0])
check("accounts travel between computers by login", replica.BY_NAME["users"].key == ("login",))
check("doctors are not synced (the same Dentist Plus ids everywhere)", "doctors" not in replica.BY_NAME)

# ------------------------------------------------------------------ 3.6.1 writes logins
aA.save_shift({"person": annaA, "date": D1, "start": "09:00", "end": "18:00"})
aA.save_shift({"person": olgaA, "date": D1, "start": "12:00", "end": "20:00"})
aA.save_shift({"person": "d:1", "date": D1, "start": "10:00", "end": "16:00"})
check("shift stored under the login", dA.one("SELECT 1 AS x FROM work_shifts WHERE person='login:anna' AND date=?", (D1,)) is not None)
check("doctor's shift stored as before", dA.one("SELECT 1 AS x FROM work_shifts WHERE person='d:1'") is not None)
check("no new u: references", dA.one("SELECT COUNT(*) AS n FROM work_shifts WHERE person LIKE 'u:%'")["n"] == 0)
m = aA.shifts_month(M)
check("the grid shows the shift under the screen key", m["shifts"].get(annaA, {}).get(D1, {}).get("start") == "09:00", list(m["shifts"]))
check("calendar hours of doctors unchanged", aA._shifts.day(D1) == {"1": {"start": "10:00", "end": "16:00"}})
aA.fill_shifts({"people": [annaA], "month": M, "weekdays": [T.replace(day=2).weekday()], "start": "08:00", "end": "14:00"})
check("fill stores logins", dA.one("SELECT COUNT(*) AS n FROM work_shifts WHERE person LIKE 'u:%'")["n"] == 0
      and dA.one("SELECT 1 AS x FROM work_shifts WHERE person='login:anna' AND date=?", (D2,)) is not None)
aA.save_salary_scheme({"person": annaA, "fixed": 40000})
aA.save_salary_scheme({"person": olgaA, "fixed": 30000})
aA.save_salary_scheme({"person": "d:1", "percent": 30})
check("scheme stored under the login", dA.one("SELECT fixed FROM salary_schemes WHERE person='login:anna'")["fixed"] == 40000)
aA.pay_salary({"person": annaA, "month": M, "amount": 10000, "date": D1, "method": "Наличные"})
check("payout stored under the login", dA.one("SELECT COUNT(*) AS n FROM expenses WHERE person='login:anna'")["n"] == 1)
exA = aA.expenses(D1, T.isoformat())
check("payout shown with the name and the screen key", any(r["person"] == annaA and r["person_name"] == "Anna" for r in exA["rows"]), exA["rows"])
prA = aA.payroll(M)
pa = next((r for r in prA["rows"] if r["key"] == annaA), None)
check("payroll: earned, paid out, due", pa and pa["earned"] == 40000 and pa["paid_out"] == 10000 and pa["due"] == 30000, pa)
check("payroll: nothing unknown", prA["unknown"] == [])
check("schemes list by screen key", next(s for s in aA.salary_schemes() if s["key"] == olgaA)["fixed"] == 30000)

# ------------------------------------------------------------------ two laptops: the person stays right
both(dA, dB)
mB = aB.shifts_month(M)
check("B: Anna's shift under Anna", mB["shifts"].get(annaB, {}).get(D1, {}).get("start") == "09:00", list(mB["shifts"]))
check("B: Olga's shift under Olga", mB["shifts"].get(olgaB, {}).get(D1, {}).get("start") == "12:00")
check("B: the id of Anna on A does not get her shift", mB["shifts"].get(olgaB, {}).get(D1, {}).get("start") != "09:00")
check("B: no unknown people", not any(p["kind"] == "unknown" for p in mB["people"]))
prB = aB.payroll(M)
rb = {r["key"]: r for r in prB["rows"]}
check("B: Anna's scheme and payout", rb.get(annaB, {}).get("earned") == 40000 and rb[annaB]["paid_out"] == 10000 and rb[annaB]["due"] == 30000, rb)
check("B: Olga keeps her own scheme", rb.get(olgaB, {}).get("earned") == 30000 and rb[olgaB]["paid_out"] == 0, rb.get(olgaB))
check("B: payroll totals equal A", (prB["earned"], prB["paid_out"], prB["due"]) == (prA["earned"], prA["paid_out"], prA["due"]))
# B changes Anna's shift and Olga's scheme, A gets it
aB.save_shift({"person": annaB, "date": D1, "start": "10:00", "end": "18:00"})
aB.save_salary_scheme({"person": olgaB, "fixed": 35000})
both(dA, dB)
mA = aA.shifts_month(M)
check("A: B's edit lands on Anna", mA["shifts"].get(annaA, {}).get(D1, {}).get("start") == "10:00", mA["shifts"].get(annaA))
check("A: Olga's shift untouched", mA["shifts"].get(olgaA, {}).get(D1, {}).get("start") == "12:00")
check("A: B's scheme change lands on Olga", next(s for s in aA.salary_schemes() if s["key"] == olgaA)["fixed"] == 35000
      and next(s for s in aA.salary_schemes() if s["key"] == annaA)["fixed"] == 40000)
check("one shift row per person and day after the round trip", dA.one("SELECT COUNT(*) AS n FROM work_shifts WHERE person='login:anna' AND date=?", (D1,))["n"] == 1
      and dB.one("SELECT COUNT(*) AS n FROM work_shifts WHERE person='login:anna' AND date=?", (D1,))["n"] == 1)

# ------------------------------------------------------------------ the timesheet against the schedule on the other laptop
past = T - timedelta(days=1)
aB.save_shift({"person": annaB, "date": past.isoformat(), "start": "09:00", "end": "18:00"})
aB.time_mark_save({"person": annaB, "date": past.isoformat(), "came": "09:30", "left": "18:00"})
both(dA, dB)
for who, api, key in (("A", aA, annaA), ("B", aB, annaB)):
    row = next((r for r in api._ts.period(past, past)["rows"] if r["key"] == key), None)
    c = (row or {}).get("cells", {}).get(past.isoformat(), {})
    check(f"{who}: timesheet plan from the login schedule", c.get("plan") == ["09:00", "18:00"] and c.get("plan_min") == 540, c)
    check(f"{who}: lateness against it", c.get("status") == "late" and c.get("late") == 30, c)
me = aA._ts.me({"login": "anna", "name": "Anna"}, now=__import__("datetime").datetime.combine(T.replace(day=1), __import__("datetime").time(9)))
check("«Я пришёл» sees today's shift by login", (me.get("shift") or {}).get("start") == "10:00" and me["person"] == annaA, me)

# ------------------------------------------------------------------ migration of 3.6.0 data
d0, a0 = laptop("old", ["zz", "anna", "olga"])
ann0, olg0 = uid(d0, "anna"), uid(d0, "olga")
with d0.tx() as c:  # rows as 3.6.0 wrote them
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              (f"u:{ann0}", D1, "09:00", "18:00", "", "", "2026-01-01 10:00:00"))
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              (f"u:{olg0}", D1, "12:00", "20:00", "", "", "2026-01-01 10:00:00"))
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              ("u:999", D2, "09:00", "13:00", "", "", "2026-01-01 10:00:00"))  # an account that is gone
    for p, fx in ((f"u:{ann0}", 40000), (f"u:{olg0}", 30000), ("u:999", 25000), ("d:1", 0)):
        c.execute("INSERT INTO salary_schemes(person, percent, fixed, base, minus_materials, updated_at) VALUES(?,?,?,?,?,?)",
                  (p, 30 if p == "d:1" else 0, fx, "paid", 0, "2026-01-01 10:00:00"))
    for i, (p, amt) in enumerate(((f"u:{ann0}", 10000), ("u:999", 5000))):
        c.execute("INSERT INTO expenses(id, date, category, amount, method, person, period, comment, user_name, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)", (f"E-old{i}", D1, "Зарплата", amt, "Наличные", p, M, "", "", "2026-01-01 10:00:00"))
# before the migration nothing is attached to anybody by a local id
m0 = a0.shifts_month(M)
check("before: a leftover u: is shown as unknown", any(p["kind"] == "unknown" for p in m0["people"]) and f"u:{ann0}" not in m0["shifts"])
res = staffref.migrate(d0, node="nodeOld")
check("migration converts the rows written here", res == {"work_shifts": 2, "salary_schemes": 2, "expenses": 1}, res)
check("migration is idempotent", staffref.migrate(d0, node="nodeOld") == {})
check("shifts converted", {r["person"] for r in d0.q("SELECT person FROM work_shifts")} == {"login:anna", "login:olga", "u:999"})
check("schemes converted, the doctor kept", {r["person"] for r in d0.q("SELECT person FROM salary_schemes")} == {"login:anna", "login:olga", "u:999", "d:1"})
check("payouts converted", {r["person"] for r in d0.q("SELECT person FROM expenses")} == {"login:anna", "u:999"})
check("the old scheme key is marked to go away on the other computers",
      d0.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='salary_schemes' AND k=?", (replica.ks([f"u:{ann0}"]),)) is not None)
m0 = a0.shifts_month(M)
unk = [p for p in m0["people"] if p["kind"] == "unknown"]
check("a gone account: «неизвестный сотрудник», not deleted", len(unk) == 1 and unk[0]["name"] == "неизвестный сотрудник"
      and m0["shifts"][unk[0]["key"]][D2]["start"] == "09:00", unk)
check("converted shifts under the right people", m0["shifts"][f"u:{ann0}"][D1]["start"] == "09:00" and m0["shifts"][f"u:{olg0}"][D1]["start"] == "12:00")
# the payroll is what 3.6.0 gave and what the same data typed in 3.6.1 gives
pr0 = a0.payroll(M)
r0 = {r["key"]: r for r in pr0["rows"]}
check("payroll after the migration: Anna", r0[f"u:{ann0}"]["earned"] == 40000 and r0[f"u:{ann0}"]["paid_out"] == 10000 and r0[f"u:{ann0}"]["due"] == 30000)
check("payroll after the migration: Olga", r0[f"u:{olg0}"]["earned"] == 30000 and r0[f"u:{olg0}"]["due"] == 30000)
check("a gone account's scheme is shown apart, not counted", pr0["unknown"] == [{"key": "x:u:999", "name": "неизвестный сотрудник", "percent": 0, "fixed": 25000}]
      and pr0["earned"] == 70000, (pr0["unknown"], pr0["earned"]))
dN, aN = laptop("new", ["zz", "anna", "olga"])
aN.save_salary_scheme({"person": f"u:{uid(dN, 'anna')}", "fixed": 40000})
aN.save_salary_scheme({"person": f"u:{uid(dN, 'olga')}", "fixed": 30000})
aN.save_salary_scheme({"person": "d:1", "percent": 30})
aN.pay_salary({"person": f"u:{uid(dN, 'anna')}", "month": M, "amount": 10000, "date": D1, "method": "Наличные"})
prN = aN.payroll(M)
check("payroll equals data entered under 3.6.1", (prN["earned"], prN["paid_out"], prN["due"]) == (pr0["earned"], pr0["paid_out"], pr0["due"]),
      ((prN["earned"], prN["paid_out"], prN["due"]), (pr0["earned"], pr0["paid_out"], pr0["due"])))
ex0 = {r["id"]: r for r in a0.expenses(D1, T.isoformat())["rows"]}
check("a payout of a gone account: «неизвестный сотрудник»", ex0["E-old1"]["person_name"] == "неизвестный сотрудник" and ex0["E-old1"]["person"] == "x:u:999")
# an edited payout keeps its unknown person; a new one cannot take it
a0.save_expense({"id": "E-old1", "date": D1, "category": "Зарплата", "amount": 6000, "method": "Наличные", "person": "x:u:999", "period": M})
check("edit keeps the unknown person", d0.one("SELECT person, amount FROM expenses WHERE id='E-old1'")["person"] == "u:999"
      and d0.one("SELECT amount FROM expenses WHERE id='E-old1'")["amount"] == 6000)
refuses("a new payout to an unknown person", lambda: a0.save_expense({"date": D1, "category": "Зарплата", "amount": 1, "person": "x:u:999"}), "не найден")
refuses("an unknown person's shift cannot be set", lambda: a0.save_shift({"person": "x:u:999", "date": D2, "start": "9", "end": "10"}), "удалить")
refuses("unknown cannot be filled", lambda: a0.fill_shifts({"people": ["x:u:999"], "month": M, "weekdays": [0], "start": "9", "end": "10"}), "не найден")
a0.save_shift({"person": "x:u:999", "date": D2, "start": ""})
check("an unknown person's shift can be removed", d0.one("SELECT 1 AS x FROM work_shifts WHERE person='u:999'") is None)
check("the timesheet does not attach unknown rows", all(not staffref.is_unknown(r["key"]) for r in a0._ts.period(T.replace(day=1), T)["rows"]))

# ------------------------------------------------------------------ an old-version laptop sends u: rows
# A gets a shift, a scheme and a payout written on «nodeOld2» with ITS ids: u:<annaA> there is not Anna here
dO = dbm.DB(Path(tempfile.mkdtemp()) / "o.db")
aO = Api(dO, W())
auth.Auth(dO)
with dO.tx() as c:
    for lg in ("anna", "zz", "olga"):  # here anna=1, zz=2 (the id of Anna on A), olga=3
        c.execute("INSERT INTO users(login, name, role, status, created_at) VALUES(?,?,?,?,?)", (lg, lg.title(), "admin", "active", "2025-01-01"))
replica.install(dO)
zzO = uid(dO, "zz")
check("the old laptop's zz has the id of Anna on A", f"u:{zzO}" == annaA)
with dO.tx() as c:  # 3.6.0 there: a shift and a scheme of zz
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              (f"u:{zzO}", D3, "07:00", "11:00", "", "", "2026-01-02 10:00:00"))
    c.execute("INSERT INTO salary_schemes(person, percent, fixed, base, minus_materials, updated_at) VALUES(?,?,?,?,?,?)",
              (f"u:{zzO}", 0, 99000, "paid", 0, "2026-01-02 10:00:00"))
    c.execute("INSERT INTO expenses(id, date, category, amount, method, person, period, comment, user_name, created_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?)", ("E-zz", D3, "Зарплата", 7000, "Наличные", f"u:{zzO}", M, "", "", "2026-01-02 10:00:00"))
sync(dO, "nodeOld2", dA, "nodeA")
check("the foreign rows arrived", dA.one("SELECT 1 AS x FROM work_shifts WHERE person=? AND date=?", (annaA, D3)) is not None)
res = staffref.migrate(dA, node="nodeA")
check("foreign u: rows are not converted here", res == {} and dA.one("SELECT 1 AS x FROM work_shifts WHERE person=? AND date=?", (annaA, D3)) is not None, res)
mA = aA.shifts_month(M)
check("A: the foreign shift is not Anna's", D3 not in mA["shifts"].get(annaA, {}), mA["shifts"].get(annaA))
check("A: it is shown as unknown", any(p["kind"] == "unknown" and D3 in mA["shifts"].get(p["key"], {}) for p in mA["people"]))
prA2 = aA.payroll(M)
ra = {r["key"]: r for r in prA2["rows"]}
check("A: Anna's pay is not changed by the foreign scheme", ra[annaA]["earned"] == 40000 and ra[annaA]["paid_out"] == 10000, ra[annaA])
check("A: the foreign scheme is listed apart", any(u["fixed"] == 99000 and u["name"] == "неизвестный сотрудник" for u in prA2["unknown"]), prA2["unknown"])
check("A: the foreign payout is not Anna's", next(r for r in aA.expenses(D3, D3)["rows"] if r["id"] == "E-zz")["person_name"] == "неизвестный сотрудник")
# the old laptop is updated: it converts its own rows, and A gets zz's shift under zz
check("the old laptop converts its own rows", staffref.migrate(dO, node="nodeOld2") == {"work_shifts": 1, "salary_schemes": 1, "expenses": 1})
sync(dO, "nodeOld2", dA, "nodeA")
check("A: zz's shift is now under zz (the login)", dA.one("SELECT person FROM work_shifts WHERE date=? AND start='07:00'", (D3,))["person"] == "login:zz")
check("A: the old scheme key is gone", dA.one("SELECT 1 AS x FROM salary_schemes WHERE person=?", (annaA,)) is None
      and dA.one("SELECT fixed FROM salary_schemes WHERE person='login:zz'")["fixed"] == 99000)
prA3 = aA.payroll(M)
check("A: nothing unknown is left", prA3["unknown"] == [] and not any(p["kind"] == "unknown" for p in aA.shifts_month(M)["people"]))
check("A: zz's payout under zz", next(r for r in aA.expenses(D3, D3)["rows"] if r["id"] == "E-zz")["person"] == f"u:{uid(dA, 'zz')}")

# ------------------------------------------------------------------ A was 3.6.0 and synced before; then updated
dP, aP = laptop("p", ["zz", "anna", "olga"])     # P: anna=2
dQ, aQ = laptop("q", ["yy", "olga", "anna"])     # Q: olga=2, anna=3
with dP.tx() as c:
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              (f"u:{uid(dP, 'anna')}", D1, "09:00", "18:00", "", "", "2026-01-01 10:00:00"))
    c.execute("INSERT INTO salary_schemes(person, percent, fixed, base, minus_materials, updated_at) VALUES(?,?,?,?,?,?)",
              (f"u:{uid(dP, 'anna')}", 0, 40000, "paid", 0, "2026-01-01 10:00:00"))
both(dP, dQ, "nodeP", "nodeQ")  # synced while P was 3.6.0
mQ = aQ.shifts_month(M)
check("Q before P is updated: not Olga's", D1 not in mQ["shifts"].get(f"u:{uid(dQ, 'olga')}", {}))
check("Q: Q does not convert P's rows", staffref.migrate(dQ, node="nodeQ") == {})
check("P converts after the update", staffref.migrate(dP, node="nodeP") == {"work_shifts": 1, "salary_schemes": 1})
both(dP, dQ, "nodeP", "nodeQ")
mQ = aQ.shifts_month(M)
check("Q: Anna's shift under Anna", mQ["shifts"].get(f"u:{uid(dQ, 'anna')}", {}).get(D1, {}).get("start") == "09:00", mQ["shifts"])
check("Q: no unknown rows left", not any(p["kind"] == "unknown" for p in mQ["people"]))
check("Q: the old key «u:2» is gone, Olga has no scheme", dQ.one("SELECT 1 AS x FROM salary_schemes WHERE person LIKE 'u:%'") is None
      and next(s for s in aQ.salary_schemes() if s["key"] == f"u:{uid(dQ, 'olga')}")["fixed"] == 0
      and next(s for s in aQ.salary_schemes() if s["key"] == f"u:{uid(dQ, 'anna')}")["fixed"] == 40000)

# a duplicate of the same person and day: the later row stays
dR, aR = laptop("r", ["anna"])
with dR.tx() as c:
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              (f"u:{uid(dR, 'anna')}", D1, "09:00", "18:00", "", "", "2026-01-01 10:00:00"))
    c.execute('INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)',
              ("login:anna", D1, "11:00", "19:00", "", "", "2026-01-05 10:00:00"))
staffref.migrate(dR, node="nodeR")
rows = dR.q("SELECT person, start FROM work_shifts WHERE date=?", (D1,))
check("duplicate day: one row, the later one", rows == [{"person": "login:anna", "start": "11:00"}], rows)

# ------------------------------------------------------------------ the app runs the migration on start
dS = dbm.DB(Path(tempfile.mkdtemp()) / "s.db")
Api(dS, W())
auth.Auth(dS)
with dS.tx() as c:
    c.execute("INSERT INTO users(login, name, role, status, created_at) VALUES('anna','Anna','admin','active','2025-01-01')")
    c.execute("INSERT INTO salary_schemes(person, percent, fixed, base, minus_materials, updated_at) VALUES(?,?,?,?,?,?)",
              (f"u:{uid(dS, 'anna')}", 0, 1000, "paid", 0, "2026-01-01"))
Api(dS, W())
check("Api start converts", dS.one("SELECT person FROM salary_schemes")["person"] == "login:anna")

# ------------------------------------------------------------------ version, UI, notes
check("version 3.6.1 or later", tuple(map(int, config.VERSION.split("."))) >= (3, 6, 1), config.VERSION)
html = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("cache tag is the version", f"shifts.js?v={config.VERSION}" in html and "v=3.6.0" not in html)
sj = (ROOT / "app" / "ui" / "shifts.js").read_text(encoding="utf-8")
check("schedule: unknown rows can only be removed", 'p.kind === "unknown"' in sj and "Удалить смену" in sj and 'filter(p => p.kind !== "unknown")' in sj)
aj = (ROOT / "app" / "ui" / "accounting.js").read_text(encoding="utf-8")
check("payroll: schemes without a person shown apart", "Схемы без сотрудника" in aj and "r.unknown" in aj)
check("expense: an unknown person is kept in the list", "!people.some(p => p.key === x.person)" in aj)
notes = (ROOT / "docs" / "Что нового в версии 3.6.txt").read_text(encoding="utf-8")
check("notes: 3.6.1 fixes", "3.6.1" in notes and "неизвестный сотрудник" in notes.lower())

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
