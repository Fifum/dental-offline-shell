"""Work schedules: shifts per person and day, weekday fill, totals, calendar hours, staff accounts, rights."""
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
docs = d.doctors()
k1, k2 = f"d:{docs[0]['id']}", f"d:{docs[1]['id']}"
M = "2026-03"  # March 2026: starts on a Sunday, 31 days

m = a.shifts_month(M)
check("month days", len(m["days"]) == 31 and m["days"][0] == "2026-03-01")
check("doctors are people", sum(1 for p in m["people"] if p["kind"] == "doctor") == len(docs))
check("no shifts yet", m["shifts"] == {})

# --- single shift
r = a.save_shift({"person": k1, "date": "2026-03-02", "start": "9", "end": "15.30", "note": "каб. 2"})
check("time normalised", r["start"] == "09:00" and r["end"] == "15:30", r)
refuses("end before start", lambda: a.save_shift({"person": k1, "date": "2026-03-02", "start": "18:00", "end": "09:00"}), "позже")
refuses("bad time", lambda: a.save_shift({"person": k1, "date": "2026-03-02", "start": "25:00", "end": "26:00"}), "ЧЧ:ММ")
refuses("bad date", lambda: a.save_shift({"person": k1, "date": "2026-02-30", "start": "9", "end": "10"}), "дата")
refuses("unknown person", lambda: a.save_shift({"person": "d:none", "date": "2026-03-02", "start": "9", "end": "10"}), "не найден")
a.save_shift({"person": k1, "date": "2026-03-02", "start": "10:00", "end": "16:00"})
m = a.shifts_month(M)
check("one shift per day (updated)", m["shifts"][k1]["2026-03-02"]["start"] == "10:00" and m["totals"][k1]["days"] == 1, m["shifts"])
check("hours", m["totals"][k1]["hours"] == 6)
a.save_shift({"person": k1, "date": "2026-03-02", "start": ""})
check("empty start removes", k1 not in a.shifts_month(M)["shifts"])

# --- weekday fill: Mon–Fri for two doctors
n = a.fill_shifts({"people": [k1, k2], "month": M, "weekdays": [0, 1, 2, 3, 4], "start": "09:00", "end": "18:00"})
check("fill count (22 weekdays x 2)", n == 44, n)
m = a.shifts_month(M)
check("no weekend shifts", all(date.fromisoformat(x).weekday() < 5 for x in m["shifts"][k1]))
check("fill totals", m["totals"][k2]["days"] == 22 and m["totals"][k2]["hours"] == 22 * 9, m["totals"][k2])
a.save_shift({"person": k1, "date": "2026-03-03", "start": "12:00", "end": "20:00"})
n = a.fill_shifts({"people": [k1], "month": M, "weekdays": [1], "start": "09:00", "end": "13:00"})
check("fill keeps existing", n == 0 and a.shifts_month(M)["shifts"][k1]["2026-03-03"]["start"] == "12:00")
n = a.fill_shifts({"people": [k1], "month": M, "weekdays": [1], "start": "09:00", "end": "13:00", "overwrite": True})
check("fill overwrites on request", n == 5 and a.shifts_month(M)["shifts"][k1]["2026-03-03"]["end"] == "13:00", n)
n = a.fill_shifts({"people": [k2], "month": M, "weekdays": [5], "start": "10:00", "end": "14:00", "every": 2})
check("every other week", n == 2, n)  # Saturdays 7 and 21: days 1-7 and 15-21 (29-31 has no Saturday)
refuses("fill needs weekdays", lambda: a.fill_shifts({"people": [k1], "month": M, "weekdays": [], "start": "9", "end": "10"}), "дни недели")
refuses("fill needs people", lambda: a.fill_shifts({"people": [], "month": M, "weekdays": [0], "start": "9", "end": "10"}), "сотрудников")

# --- calendar gets the shifts of the day
day = a.day("2026-03-03")
check("calendar shifts", day["shifts"] and day["shifts"][str(docs[0]["id"])] == {"start": "09:00", "end": "13:00"}, day["shifts"])
check("calendar: no schedule that day", a.day("2026-03-01")["shifts"] is None)
check("clear month", a.clear_shifts(k1, M) > 0 and k1 not in a.shifts_month(M)["shifts"])
check("other doctor kept", k2 in a.shifts_month(M)["shifts"])

# --- demo shifts for the current month
demo.ensure_office(d)
cur = a.shifts_month(date.today().strftime("%Y-%m"))
check("demo shifts", len(cur["shifts"]) == 5 and all(v["days"] > 10 for v in cur["totals"].values()), cur["totals"])

# --- rights and staff accounts over HTTP
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
ids = {}
for login, role in (("adm", "admin"), ("doc", "doctor"), ("keeper", "storekeeper")):
    call("auth", "register", {"name": "Сотрудник " + login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    ids[login] = u["id"]
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TA, TDoc, TK = (call("auth", "login", x, "secret1")[1]["token"] for x in ("adm", "doc", "keeper"))
ppl = call("api", "shifts_month", M, token=TA)[1]["people"]
check("staff accounts in schedule", any(p["key"] == f"u:{ids['adm']}" and p["kind"] == "staff" for p in ppl))
check("admin edits schedule", call("api", "save_shift", {"person": f"u:{ids['adm']}", "date": "2026-03-04", "start": "8", "end": "20"}, token=TA)[0] == 200)
check("doctor sees schedule", call("api", "shifts_month", M, token=TDoc)[0] == 200)
check("doctor cannot edit", call("api", "save_shift", {"person": k1, "date": "2026-03-04", "start": "8", "end": "9"}, token=TDoc)[0] == 403)
check("storekeeper no schedule", call("api", "shifts_month", M, token=TK)[0] == 403)
call("auth", "staff_save", {"id": ids["doc"], "role": "doctor", "status": "active", "doctor_id": docs[2]["id"]}, token=TD)
ppl = call("api", "shifts_month", M, token=TD)[1]["people"]
check("account linked to a doctor is not doubled", not any(p["key"] == f"u:{ids['doc']}" for p in ppl))
audit = call("auth", "audit_list", token=TD)[1]
check("audit: shift", any(x["action"] == "Смена в графике" and x["user_name"] == "Сотрудник adm" for x in audit))
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
