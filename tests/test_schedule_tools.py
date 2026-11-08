"""Version 2.2 schedule tools: moving visits, recurring visits, waiting list, reminder texts, disk encryption check."""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import security  # noqa: E402
from local import Local  # noqa: E402
from main import Api, Setup  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        return str(e)
    return None


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
day = date.today() + timedelta(days=1)
if day.weekday() == 6:
    day += timedelta(days=1)
D = day.isoformat()
visits = a.day(D)["visits"]
v = visits[0]
pid, doc = v["patient_id"], v["doctor_id"]
other_doc = next(x["id"] for x in a.reference()["doctors"] if x["id"] != doc)

# ---- moving a synced visit (what the calendar does on drop) keeps one row, marks it as a move
a.save_visit({"id": v["id"], "patient_id": pid, "doctor_id": other_doc, "branch_id": v["branch_id"],
              "start": f"{D} 20:00", "end": f"{D} 20:30", "title": v["title"], "status": v["status"], "action": "move"})
moved = [x for x in a.day(D)["visits"] if x["id"] == v["id"] or x["origin_id"] == v["id"]]
check("moved visit appears once", len(moved) == 1, moved)
check("moved to other doctor and time", moved and moved[0]["doctor_id"] == other_doc and moved[0]["start"] == f"{D} 20:00")
check("marked as a move for Dentist Plus", moved and moved[0]["action"] == "move" and moved[0]["local"] == 1)

# ---- series dates
check("weekly dates", Local.series_dates("2026-11-10", "week", 3) == ["2026-11-10", "2026-11-17", "2026-11-24"])
check("2 weeks", Local.series_dates("2026-11-10", "2weeks", 2) == ["2026-11-10", "2026-11-24"])
check("4 weeks", Local.series_dates("2026-11-10", "4weeks", 2)[1] == "2026-12-08")
check("monthly keeps the day, clamps to month end", Local.series_dates("2027-01-31", "month", 3) == ["2027-01-31", "2027-02-28", "2027-03-31"])
check("monthly over the new year", Local.series_dates("2026-11-15", "month", 3)[2] == "2027-01-15")

# ---- recurring visits
base = {"patient_id": pid, "doctor_id": doc, "branch_id": v["branch_id"], "start": f"{D} 07:00", "end": f"{D} 07:45",
        "title": "Ортодонтия: активация"}
check("bad period refused", raises(a.save_visit_series, base, "day", 3) is not None)
check("count limits", "от 2 до 24" in (raises(a.save_visit_series, base, "week", 1) or "")
      and "от 2 до 24" in (raises(a.save_visit_series, base, "week", 30) or ""))
check("series only for new visits", raises(a.save_visit_series, {**base, "id": v["id"]}, "week", 3) is not None)
r = a.save_visit_series(base, "week", 5)
check("five visits created", len(r["ids"]) == 5 and len(set(r["ids"])) == 5)
check("series dates returned", r["dates"][0] == D and r["dates"][4] == (day + timedelta(days=28)).isoformat())
check("every text", r["every"] == "каждую неделю")
check("no clashes at 07:00", r["clashes"] == [], r["clashes"])
v2 = a.visit(r["ids"][2])
check("each visit keeps time and length", v2["start"].endswith("07:00") and v2["end"].endswith("07:45") and v2["title"] == base["title"])
check("series id on visit", v2["series_id"] == r["series_id"])
check("new visits wait for transfer", v2["local"] == 1 and v2["action"] == "create")
lst = a.visit_series(r["series_id"])
check("series listing", [x["id"] for x in lst] == r["ids"])
a.set_visit_status(r["ids"][0], "Пришёл")
n = a.cancel_series(r["series_id"], a.visit(r["ids"][2])["start"])
st = [x["status"] for x in a.visit_series(r["series_id"])]
check("cancel this and following", n == 3 and st[:2] == ["Пришёл", "Запланирован"] and all(s == "Отменён" for s in st[2:]), st)
check("cancelled visits are transfer-ready cancels", a.visit(r["ids"][3])["action"] == "cancel")
busy = visits[1]  # an existing visit: a series at the same time with the same doctor overlaps it
clash = a.save_visit_series({**base, "doctor_id": busy["doctor_id"], "start": busy["start"], "end": busy["end"]}, "week", 2)
check("clash reported for an occupied doctor", len(clash["clashes"]) >= 1, clash)

# ---- waiting list
check("patient required", "пациента" in (raises(a.waitlist_save, {}) or ""))
check("unknown patient", "не найден" in (raises(a.waitlist_save, {"patient_id": "nope"}) or ""))
check("bad dates", "раньше" in (raises(a.waitlist_save, {"patient_id": pid, "date_from": "2026-12-10", "date_to": "2026-12-01"}) or ""))
auth.set_current_user({"id": 1, "role": "director", "name": "Директор Тест"})
w1 = a.waitlist_save({"patient_id": pid, "doctor_id": doc, "wish": "утро, чистка", "date_from": D, "date_to": (day + timedelta(days=7)).isoformat()})
auth.set_current_user(None)
w2 = a.waitlist_save({"patient_id": visits[2]["patient_id"], "wish": "любое время"})
w3 = a.waitlist_save({"patient_id": visits[3]["patient_id"], "doctor_id": other_doc, "date_from": (day + timedelta(days=30)).isoformat()})
rows = a.waitlist()
check("three waiting", len(rows) == 3 and rows[0]["id"] == w1)
check("names joined", rows[0]["patient_name"] and rows[0]["doctor_name"] and rows[0]["status_text"] == "ждёт")
check("author kept", rows[0]["created_by"] == "Директор Тест", rows[0]["created_by"])
check("count for doctor includes any-doctor entries", a.waitlist_count(doc) == 2)
check("count for doctor and day", a.waitlist_count(other_doc, D) == 1)  # w3 starts in a month, w2 is any doctor
check("count by day", a.waitlist_count(None, (day + timedelta(days=30)).isoformat()) == 2)
a.waitlist_save({"id": w2, "patient_id": visits[2]["patient_id"], "wish": "только вечер"})
check("edit entry", next(x for x in a.waitlist() if x["id"] == w2)["wish"] == "только вечер")
check("edit unknown entry", raises(a.waitlist_save, {"id": "W-x", "patient_id": pid}) is not None)
a.waitlist_done(w1, r["ids"][1])
a.waitlist_remove(w3)
check("booked and removed leave the list", [x["id"] for x in a.waitlist()] == [w2])
booked = a.waitlist("booked")
check("booked keeps the visit", booked and booked[0]["visit_id"] == r["ids"][1] and booked[0]["status_text"] == "записан")
check("all statuses", len(a.waitlist("all")) == 3)
check("unknown id", raises(a.waitlist_remove, "W-none") is not None)

# ---- reminder template
t = a.reminder_template()
check("default template", "{имя}" in t["text"] and t["text"] == t["default"])
a.save_clinic({"name": "Клиника Улыбка", "phone": "+7 949 000-00-00", "address": "ул. Мира, 1"})
t = a.reminder_template_save("Здравствуйте, {имя}! Ждём вас {дата} в {время}.")
check("template saved", t["text"].startswith("Здравствуйте, {имя}") and t["clinic"]["name"] == "Клиника Улыбка")
check("too long refused", raises(a.reminder_template_save, "x" * 1001) is not None)
check("empty resets to default", a.reminder_template_save("")["text"] == t["default"])

# ---- links are limited to messengers and phone calls
s = Setup.__new__(Setup)
check("open_url refuses other sites", s.open_url("https://example.com/") is False and s.open_url("file:///C:/") is False)

# ---- disk encryption check
sec = a.security_status()
check("encryption state", sec["state"] in ("on", "off", "encrypting", "decrypting", "suspended", "locked", "unknown"))
check("encryption explained", sec["text"] and len(sec["how"]) == 3 and sec["drive"].endswith(":"))
check("ok only when protected", sec["ok"] == (sec["state"] in ("on", "encrypting")))
check("cached", security.disk_status() is sec)

# ---- permissions
for m in ("save_visit_series", "visit_series", "cancel_series", "waitlist", "waitlist_count", "waitlist_save", "waitlist_done",
          "waitlist_remove", "reminder_template", "reminder_template_save", "security_status"):
    check(f"perm {m}", m in auth.METHOD_PERMS)
check("assistant can see the list, not change it", "schedule_view" in auth.METHOD_PERMS["waitlist"] and auth.METHOD_PERMS["waitlist_save"] == "schedule_edit")
for m in ("save_visit_series", "cancel_series", "waitlist_save", "waitlist_done", "waitlist_remove", "reminder_template_save"):
    check(f"audited {m}", m in auth.AUDITED)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
