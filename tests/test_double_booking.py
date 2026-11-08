"""Double bookings: detection rules, calendar flags, transfer list, and no sending to Dentist Plus
until the user resolves it or says «send anyway»."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import conflicts  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
from main import Api  # noqa: E402
from pusher import Pusher  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


# --- rules
a = {"id": "1", "doctor_id": "7", "patient_id": "p1", "start": "2026-12-01 14:00", "end": "2026-12-01 14:30", "status": "Запланирован"}
check("overlap", conflicts.clash(a, {**a, "id": "2", "patient_id": "p2", "start": "2026-12-01 14:15", "end": "2026-12-01 15:00"}))
check("touching is fine", not conflicts.clash(a, {**a, "id": "2", "patient_id": "p2", "start": "2026-12-01 14:30", "end": "2026-12-01 15:00"}))
check("other doctor fine", not conflicts.clash(a, {**a, "id": "2", "patient_id": "p2", "doctor_id": "8"}))
check("same patient is not a double booking", not conflicts.clash(a, {**a, "id": "2"}))
check("cancelled ignored", not conflicts.clash(a, {**a, "id": "2", "patient_id": "p2", "status": "Отменён"}))
check("no end = 30 min", conflicts.clash({**a, "end": None}, {**a, "id": "2", "patient_id": "p2", "start": "2026-12-01 14:20", "end": None}))
check("no doctor: unknown, not a clash", not conflicts.clash({**a, "doctor_id": None}, {**a, "id": "2", "patient_id": "p2", "doctor_id": None}))
day = conflicts.mark_day([dict(a), {**a, "id": "2", "patient_id": "p2", "start": "2026-12-01 14:10"}, {**a, "id": "3", "patient_id": "p3", "start": "2026-12-01 16:00"}])
check("mark_day", [bool(x.get("conflict")) for x in day] == [True, True, False])

# --- in the app: two laptops booked the same slot; here we simulate it with a synced + a local visit
d = dbm.DB(); demo.ensure_demo(d, force=True)
api = Api(d, W())
syn = d.q("SELECT * FROM visits WHERE doctor_id IS NOT NULL AND status NOT LIKE '%тмен%' ORDER BY start DESC LIMIT 1")[0]
other = d.q("SELECT id, name FROM patients WHERE id<>? LIMIT 1", (syn["patient_id"],))[0]
lid = api.save_visit({"patient_id": other["id"], "doctor_id": syn["doctor_id"], "start": syn["start"][:16], "end": syn["end"][:16] if syn["end"] else None, "title": "Осмотр"})
lid = lid if isinstance(lid, str) else lid.get("id")
vis = [v for v in api.day(syn["start"][:10])["visits"] if v["doctor_id"] == syn["doctor_id"] and v["start"][:16] == syn["start"][:16]]
check("calendar flags both", len(vis) >= 2 and all(v.get("conflict") for v in vis), [(v["id"], v.get("conflict")) for v in vis])
check("visit card explains", "у врача в это время уже" in (api.visit(lid)["conflict_text"] or ""), api.visit(lid).get("conflict_text"))
j = [x for x in api.journal() if x["id"] == lid][0]
check("transfer list warns (manual mode)", "у врача" in (j.get("conflict_text") or ""), j)


# --- automatic sending: fake Dentist Plus with the slot already taken
class FakeDP:
    def __init__(self, day_rows):
        self.rows, self.writes = day_rows, []

    def paged(self, path, params, per_page=200, max_pages=10):
        return list(self.rows)

    def write(self, method, path, body):
        self.writes.append((method, path, body))
        return 201, {"id": "NEW1"}


busy = [{"id": "dp-55", "patient": {"id": "dp-pat-9", "name": "Занятой Пациент"}, "patient_id": "dp-pat-9", "doctor_id": syn["doctor_id"],
         "start": syn["start"][:16], "end": (syn["end"] or syn["start"])[:16], "status": "Подтверждён"}]
fake = FakeDP(busy)
Pusher(d, fake, {}).push_visits()
row = d.one("SELECT * FROM local_visits WHERE id=?", (lid,))
check("not sent while busy", row["push_status"] == "conflict" and row["transferred"] == 0 and not fake.writes, (row["push_status"], fake.writes))
check("reason readable", "двойная запись" in row["push_error"] and "Отправить всё равно" in row["push_error"], row["push_error"])
j = [x for x in api.journal() if x["id"] == lid][0]
check("journal shows conflict status", j["push_status"] == "conflict")

# slot freed in Dentist Plus (other appointment cancelled) -> goes out on next sync by itself
fake.rows = [{**busy[0], "status": "Отменён"}]
Pusher(d, fake, {}).push_visits()
row = d.one("SELECT * FROM local_visits WHERE id=?", (lid,))
check("sent after slot freed", row["transferred"] == 1 and len(fake.writes) == 1, (row["push_status"], fake.writes))

# «send anyway»
lid2 = api.save_visit({"patient_id": other["id"], "doctor_id": syn["doctor_id"], "start": syn["start"][:16], "end": None, "title": "Срочно"})
lid2 = lid2 if isinstance(lid2, str) else lid2.get("id")
fake = FakeDP(busy)
Pusher(d, fake, {}).push_visits()
check("second booking blocked", d.one("SELECT push_status FROM local_visits WHERE id=?", (lid2,))["push_status"] == "conflict")
api.force_push(lid2)
Pusher(d, fake, {}).push_visits()
r2 = d.one("SELECT * FROM local_visits WHERE id=?", (lid2,))
check("send anyway works", r2["transferred"] == 1 and any(w[1] == "visits" for w in fake.writes), (r2["push_status"], fake.writes))

# moving an existing Dentist Plus visit onto a busy slot is blocked too
mv = d.q("SELECT * FROM visits WHERE doctor_id=? AND id<>? AND patient_id<>? LIMIT 1", (syn["doctor_id"], syn["id"], "dp-pat-9"))[0]
api.save_visit({"id": mv["id"], "patient_id": mv["patient_id"], "doctor_id": syn["doctor_id"], "start": syn["start"][:16], "end": None, "title": "перенос", "action": "move"})
fake = FakeDP(busy)
Pusher(d, fake, {}).push_visits()
moved = d.one("SELECT * FROM local_visits WHERE origin_id=? ORDER BY created_at DESC", (mv["id"],))
check("move onto busy slot blocked", moved and moved["push_status"] == "conflict" and not any(w[0] == "PUT" for w in fake.writes), moved and (moved["action"], moved["push_status"]))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
