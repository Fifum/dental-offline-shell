"""3.12.2: the calendar as clean as Dentist Plus.

Cancelled visits and no-shows are hidden by default (the link by the count and the gear show them), «Не подтверждён» is
drawn as not confirmed (it was a green tick, like «Подтвердил»), the hours over a doctor without a schedule come from his
visits that are not cancelled, «выходной по графику» only inside the doctor's own schedule, and the past days of the
Dentist Plus schedule are loaded once a day (they were loaded from a week ago only)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import db as dbm  # noqa: E402
import sync  # noqa: E402
from shifts import Shifts  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


UI = ROOT / "app" / "ui"
app = (UI / "app.js").read_text(encoding="utf-8")
dp = (UI / "calendar-dp.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def body(src, start):
    """The text of the block that starts at `start` (up to its matching closing brace)."""
    i = src.index(start)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    return src[i:]


# ------------------------------------------------------------------ the hours: whose schedule, whose day off
d = dbm.DB()
sh = Shifts(d)
DAY = "2026-11-10"
with d.tx() as c:
    for person, day, a, b in (("d:1", "2026-11-09", "09:00", "18:00"), ("d:1", "2026-11-11", "09:00", "18:00"),
                              ("d:4", DAY, "10:00", "16:00"), ("d:5", "2026-09-01", "09:00", "18:00")):
        c.execute('INSERT INTO work_shifts(person, date, start, "end") VALUES(?,?,?,?)', (person, day, a, b))
    for doc, day in (("2", "2026-11-03"), ("2", "2026-11-18"), ("3", "2026-11-18"), ("3", "2026-11-25"), ("4", DAY)):
        c.execute("INSERT INTO dp_schedule VALUES(?,?,?,?,?,?,?)", (doc, day, "", "1", "08:00", "20:00", "x"))
got = sh.day(DAY)
check("own shift wins over Dentist Plus", got.get("4") == {"start": "10:00", "end": "16:00"}, got)
check("a day off inside the doctor's own schedule", got.get("1") == {"off": True}, got)
check("a day off inside the Dentist Plus schedule", got.get("2") == {"off": True, "source": "dp"}, got)
check("before the first loaded day of a schedule: no day off (hours from the visits)", "3" not in got, got)
check("a schedule far from the day does not count", "5" not in got, got)
check("a doctor with no schedule at all is left out", set(got) == {"1", "2", "4"}, got)
got = sh.day("2026-11-20")
check("inside the loaded Dentist Plus days: off", got.get("3") == {"off": True, "source": "dp"}, got)
check("the shift of the day itself", sh.day("2026-11-18").get("3") == {"start": "08:00", "end": "20:00", "source": "dp"})
check("nobody keeps a schedule: None", sh.day("2027-06-01") is None)

# ------------------------------------------------------------------ the past days of the Dentist Plus schedule
d2 = dbm.DB(os.path.join(tempfile.mkdtemp(), "s.db"))
d2.upsert_doctors([{"id": 7, "name": "Врач"}])
w = sync.SyncWorker(d2)


class Client:
    def __init__(self):
        self.calls = []

    def paged(self, path, params=None, per_page=None, max_pages=None):
        return []

    def request(self, path, params=None):
        self.calls.append((path, dict(params or {})))
        return []

    def _items(self, x):
        return [], None


T = date.today()
s = {"days_back": 30, "days_forward": 90}
c1 = Client()
w._pull_more(c1, s, {})
froms = sorted(p["date_from"] for path, p in c1.calls if path == "schedule")
check("first pull of the day: from the oldest visit day", froms and froms[0] == (T - timedelta(days=30)).isoformat(), froms[:2])
c2 = Client()
w._pull_more(c2, s, {})
froms = sorted(p["date_from"] for path, p in c2.calls if path == "schedule")
check("later pulls that day: from a week ago", froms and froms[0] == (T - timedelta(days=7)).isoformat(), froms[:2])
with d2.tx() as c:
    for day in (T - timedelta(days=40), T - timedelta(days=5)):
        c.execute("INSERT INTO dp_schedule VALUES(?,?,?,?,?,?,?)", ("7", day.isoformat(), "", "1", "08:00", "20:00", "x"))
d2.purge(30)
left = [r["day"] for r in d2.q("SELECT day FROM dp_schedule")]
check("old schedule days go with the old visits", left == [(T - timedelta(days=5)).isoformat()], left)

# ------------------------------------------------------------------ the page
ld = body(app, "async function loadDay()")
check("cancelled hidden unless the calendar setting says so", 'CAL.get("cancelled", "0") === "1"' in ld and "v.filter(live)" in ld)
check("the grid and the list get the shown visits only", "renderGrid(drawn)" in ld and "renderList(shown)" in ld)
check("the count says how many are hidden and shows them", "показать отменённые (${nc})" in ld and "скрыть отменённые" in ld
      and 'CAL.set("cancelled", showCancel ? "0" : "1")' in ld)
check("a day of cancelled visits only says so", "На этот день только отменённые записи" in ld)
check("the visit list of the day keeps the cancelled ones (menus, double bookings)", "S.dayData = res;" in ld)
cs = body(dp, "function calSettings()")
check("the gear: «Показывать отменённые записи», off by default", "Показывать отменённые записи" in cs
      and '"cancelled", "Показывать отменённые записи"' in cs and cs.count('"0")}') >= 1 and 'CAL.set("cancelled"' in cs)
check("printing follows the screen", 'CAL.get("cancelled", "0") === "1" || stClass(x.status) !== "st-cancel"' in app)
rg = body(app, "function renderGrid(res)")
check("the band uses colHours", "colHours(c.items, shift)" in rg and "выходной по графику" not in rg)
check("no schedule at all: hatched by the clinic's day, not the whole column", "sd.off ?" in rg)

# ------------------------------------------------------------------ node: statuses and the hours
if NODE:
    for n in ("app.js", "calendar-dp.js"):
        r = subprocess.run([NODE, "--check", str(UI / n)], capture_output=True, text=True)
        check(f"syntax {n}", r.returncode == 0, r.stderr[-300:])
    line = lambda name: app[app.index(name):app.index("\n", app.index(name))]  # noqa: E731
    code = "\n".join([line("const hm = "), body(app, "function stClass(s)"), body(app, "function colHours(items, shift)"), """
const v = (t, a, b, status) => ({start: "2026-11-10 " + a, end: "2026-11-10 " + b, status});
const st = ["Не подтверждён", "Подтверждён", "Пришёл", "В кресле", "Не пришёл", "Отменён", "Завершён", "Запланирован",
            "not_confirmed", "confirmed", "Не подтвержден"].map(stClass);
const day = [v(1, "08:00", "08:15", "Не подтверждён"), v(2, "15:30", "17:30", "Отменён"), v(3, "15:00", "17:00", "Пришёл"),
             v(4, "07:30", "08:00", "Не пришёл")];
console.log(JSON.stringify({st, visits: colHours(day, undefined), cancelledOnly: colHours([day[1]], undefined),
  off: colHours(day, {off: true, source: "dp"}), offOwn: colHours([], {off: true}),
  dp: colHours(day, {start: "08:00", end: "20:00", source: "dp"}), own: colHours([], {start: "10:00", end: "16:00"})}));
"""])
    js = Path(tempfile.mkdtemp()) / "clean.js"
    js.write_text(code, encoding="utf-8")
    r = subprocess.run([NODE, str(js)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    check("node ran", r.returncode == 0, r.stderr[-400:])
    if r.returncode == 0:
        o = json.loads(r.stdout)
        check("statuses: «Не подтверждён» is not confirmed",
              o["st"] == ["", "st-ok", "st-come", "st-come", "st-cancel", "st-cancel", "st-done", "", "", "st-ok", ""], o["st"])
        check("hours from the visits that are not cancelled", o["visits"] == {"hours": "08:00 - 17:00", "why": "первая и последняя запись дня"}, o["visits"])
        check("only cancelled visits: no hours", o["cancelledOnly"]["hours"] == "нет записей", o["cancelledOnly"])
        check("a day off by the Dentist Plus schedule", o["off"] == {"hours": "выходной по графику", "why": "по графику Dentist Plus выходной"}, o["off"])
        check("a day off by the own schedule", o["offOwn"]["why"] == "по графику работы выходной", o["offOwn"])
        check("the schedule of Dentist Plus", o["dp"] == {"hours": "08:00 - 20:00", "why": "график из Dentist Plus"}, o["dp"])
        check("the own schedule", o["own"] == {"hours": "10:00 - 16:00", "why": "смена по графику работы"}, o["own"])
else:
    print("node not found: JS checks skipped")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
