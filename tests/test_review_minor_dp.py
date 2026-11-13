"""Review 2026-11-13, «мелочи» of the group «dp»: М9, М10, М11, М12, М13.

A fake Dentist Plus in this process; no real Dentist Plus is called.
  М9  a failed login inside a write (POST /auth answers 503) leaves the row a plain retryable error, never «unknown»;
  М10 purge keeps a patient card any table of ours still names (found by the column), drops an unused one;
  М11 the «record already sent» mark lives on the record row (replicated), old local marks move over, and a record
      edited after the send replaces its text in the Dentist Plus visit instead of appending it twice;
  М12 the first sync of a fresh base loads branches before it sends (no «Не известен филиал»);
  М13 the copy for the other computers is built once per stamp, outside the app's lock, in the same wire format."""
import json
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")
        print("FAIL", name, info)


T = date.today().isoformat()
DP = {"token": "", "auths": 0, "auth_code": 200, "writes": [], "next": 500,
      "visits": {100: {"id": 100, "patient_id": 5, "doctor_id": 7, "branch_id": 1, "start": f"{T} 09:00:00",
                       "end": f"{T} 09:30:00", "status": "confirmed"}}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def authed(self):
        return self.headers.get("Authorization") == f"Bearer {DP['token']}"

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path.replace("/partner/", "")
        b = self.body()
        if p == "auth":
            if DP["auth_code"] != 200:
                return self.send(DP["auth_code"], {"error": "Сервис временно недоступен"})
            DP["auths"] += 1
            DP["token"] = f"T{DP['auths']}"
            exp = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            return self.send(200, {"token": DP["token"], "expires_at": exp})
        if not self.authed():
            return self.send(401, {"error": "Авторизация не успешна"})
        DP["writes"].append(("POST", p, b))
        DP["next"] += 1
        nid = DP["next"]
        if p == "patients":
            if not b.get("branch_id"):
                return self.send(422, {"error": "branch_id обязателен"})
            return self.send(201, {"data": {"id": nid}})
        if p == "visits":
            DP["visits"][nid] = {"id": nid, "patient_id": int(b["patient_id"]), "doctor_id": int(b["doctor_id"]),
                                 "branch_id": 1, "start": b["start"], "end": b["end"], "status": "confirmed"}
            return self.send(201, {"id": nid})
        self.send(404, {"error": "Запись не найдена"})

    def do_PUT(self):
        p = urlparse(self.path).path.replace("/partner/", "")
        if not self.authed():
            return self.send(401, {"error": "Авторизация не успешна"})
        b = self.body()
        DP["writes"].append(("PUT", p, b))
        v = DP["visits"].get(int(p.split("/")[1]))
        if not v:
            return self.send(404, {"error": "Запись не найдена"})
        v.update(b)
        return self.send(200, {"data": v})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path.replace("/partner/", "")
        if not self.authed():
            return self.send(401, {"error": "Авторизация не успешна"})
        page = int(q.get("page", 1))

        def paged(items):
            return {"data": items if page == 1 else [], "meta": {"current_page": page, "last_page": 1}}
        if p == "branches":
            return self.send(200, paged([{"id": 1, "title": "Филиал"}]))
        if p == "doctors":
            return self.send(200, paged([{"id": 7, "name": "Врач Один"}]))
        if p == "visits":
            f, t = q.get("date_from", ""), q.get("date_to", "9")
            return self.send(200, paged([v for v in DP["visits"].values() if f <= v["start"][:10] <= t]))
        if p.startswith("visits/"):
            v = DP["visits"].get(int(p.split("/")[1]))
            return self.send(200, v) if v else self.send(404, {"error": "Запись не найдена"})
        if p.startswith("patients/"):
            pid = int(p.split("/")[1])
            return self.send(200, {"data": {"id": pid, "fname": "Олег", "lname": "Старый"}})
        if p == "schedule":
            return self.send(200, [])
        if p in ("payments", "services", "chairs", "record_statuses", "patients"):
            return self.send(200, paged([]) if p in ("payments", "services", "patients") else [])
        self.send(404, {"error": "Запись не найдена"})


class Srv(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, *a):
        pass


srv = Srv(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/partner"

import config  # noqa: E402
import db as dbm  # noqa: E402
import dp_main  # noqa: E402
import replica  # noqa: E402
from api_client import ApiError, AuthError, DentistPlusClient  # noqa: E402
from pusher import Pusher  # noqa: E402
from sync import SyncWorker  # noqa: E402

S = {"demo": False, "base_url": BASE, "login": "u", "pass_enc": config.protect("p"), "transfer_mode": "auto",
     "patient_extras": [], "days_back": 30}
config.save_settings(S)


def new_patient(d, pid, fname="Анна"):
    with d.tx() as c:
        c.execute("""INSERT INTO patients(id, name, data, local, transferred) VALUES(?,?,?,1,0)""",
                  (pid, fname, json.dumps({"id": pid, "fname": fname, "lname": "Новая"}, ensure_ascii=False)))


try:
    d = dbm.DB()
    w = SyncWorker(d)

    # ================================================================== М12: branches before the first send
    new_patient(d, "L-P1")
    check("М12: the base has no branches yet", d.one("SELECT 1 FROM branches LIMIT 1") is None)
    check("М12: first sync", w.sync_once(), w.status())
    p1 = d.one("SELECT * FROM patients WHERE id='L-P1'") or d.one("SELECT * FROM patients WHERE remote_id IS NOT NULL")
    posted = [x for x in DP["writes"] if x[0] == "POST" and x[1] == "patients"]
    check("М12: the new patient went with the branch", len(posted) == 1 and posted[0][2].get("branch_id") == 1, posted)
    check("М12: no «Не известен филиал»", "филиал" not in str((p1 or {}).get("push_error") or "").lower(), p1)
    check("М12: sent", (p1 or {}).get("push_status") == "sent", p1)

    # ================================================================== М9: a failed login inside a write
    s = config.load_settings()
    client = DentistPlusClient(s["base_url"], s["login"], "p")
    client.auth()
    new_patient(d, "L-P2", "Борис")
    client.token_exp = datetime.now(timezone.utc) - timedelta(minutes=1)  # the token ran out: write() logs in first
    DP["auth_code"] = 503
    n_posts = len(DP["writes"])
    try:
        Pusher(d, client, s).run()
        raised = None
    except AuthError as e:
        raised = e
    p2 = d.one("SELECT * FROM patients WHERE id='L-P2'")
    check("М9: the login error goes up (the run stops)", isinstance(raised, AuthError) and raised.status == 503, raised)
    check("М9: nothing was posted", len(DP["writes"]) == n_posts)
    check("М9: the row is a plain error, not «unknown»", p2["push_status"] == "error", p2["push_status"])
    # a 401 to the write itself, then the new login fails: still not sent
    DP["auth_code"] = 200
    client.auth()
    DP["token"] = "other"  # another login made our token invalid
    DP["auth_code"] = 503
    try:
        Pusher(d, client, s).run()
    except AuthError:
        pass
    p2 = d.one("SELECT * FROM patients WHERE id='L-P2'")
    check("М9: 401 + failed re-login is an error too", p2["push_status"] == "error", p2["push_status"])
    check("М9: ApiError still catches it (older callers)", issubclass(AuthError, ApiError))
    # the next run with a working login sends it
    DP["auth_code"] = 200
    client.token = None
    Pusher(d, client, s).run()
    p2 = d.one("SELECT * FROM patients WHERE id='L-P2'")
    check("М9: retried and sent later", p2["push_status"] == "sent" and p2["remote_id"], p2["push_status"])

    # ================================================================== М11: the record mark is replicated
    rcols = [r[1] for r in d.conn.execute("PRAGMA table_info(records)")]
    check("М11: records.dp_sent exists", "dp_sent" in rcols)
    # migration of a 3.8.0 base: the meta mark moves onto the row
    old = Path(tempfile.mkdtemp()) / "old.db"
    cx = sqlite3.connect(old)
    cx.executescript(dbm.SCHEMA)
    cx.execute("INSERT INTO records(id, patient_id, visit_id, data) VALUES('R-OLD','5','100','{}')")
    cx.execute("INSERT INTO meta(key, value) VALUES('dp_record_sent:R-OLD', ?)", (json.dumps({"complaints": "болит"}),))
    cx.commit()
    cx.close()
    d_old = dbm.DB(old)
    check("М11: the old meta mark moved onto the record",
          json.loads(d_old.one("SELECT dp_sent FROM records WHERE id='R-OLD'")["dp_sent"] or "{}") == {"complaints": "болит"})
    d_old.conn.close()

    # a record sent by the former main computer: the mark came with the row, no meta key here
    DP["visits"][100]["complaints"] = "Болит зуб"
    with d.tx() as c:
        c.execute("""INSERT INTO records(id, patient_id, visit_id, doctor_id, date, data, created_at, dp_sent)
                     VALUES('R-1','5','100','7',?,?,?,?)""",
                  (T, json.dumps({"complaints": "Болит зуб, ночью сильнее"}, ensure_ascii=False), T,
                   json.dumps({"complaints": "Болит зуб"}, ensure_ascii=False)))
    check("М11: no local meta mark", d.meta_get("dp_record_sent:R-1") is None)
    Pusher(d, client, s).push_records()
    check("М11: the text is replaced, not appended twice",
          DP["visits"][100].get("complaints") == "Болит зуб, ночью сильнее", DP["visits"][100].get("complaints"))
    r1 = d.one("SELECT * FROM records WHERE id='R-1'")
    check("М11: the record is sent", r1["push_status"] == "sent", r1["push_status"])
    check("М11: the new mark is on the row",
          json.loads(r1["dp_sent"] or "{}") == {"complaints": "Болит зуб, ночью сильнее"}, r1["dp_sent"])
    check("М11: no new meta mark", d.meta_get("dp_record_sent:R-1") is None)
    row = replica.read_row(d.conn, replica.BY_NAME["records"], ["R-1"])
    check("М11: the mark travels with the row", row and row.get("dp_sent") == r1["dp_sent"])
    # fallback: a record with only the old meta mark (written here by 3.8.0)
    DP["visits"][100]["objectively"] = "Кариес"
    with d.tx() as c:
        c.execute("""INSERT INTO records(id, patient_id, visit_id, doctor_id, date, data, created_at)
                     VALUES('R-2','5','100','7',?,?,?)""", (T, json.dumps({"objective": "Кариес 3.6"}, ensure_ascii=False), T))
    d.meta_set("dp_record_sent:R-2", json.dumps({"objectively": "Кариес"}, ensure_ascii=False))
    Pusher(d, client, s).push_records()
    check("М11: the old meta mark is still read", DP["visits"][100].get("objectively") == "Кариес 3.6",
          DP["visits"][100].get("objectively"))

    # ================================================================== М10: purge keeps cards still named
    old_day = "2000-01-01T00:00:00"
    with d.tx() as c:
        c.execute("CREATE TABLE IF NOT EXISTS zz_memberships(id TEXT PRIMARY KEY, patient_id TEXT)")
        for pid in ("901", "902", "903", "904"):
            c.execute("INSERT OR REPLACE INTO patients(id, name, local, detail_synced_at) VALUES(?,?,0,?)", (pid, "П" + pid, old_day))
        c.execute("INSERT INTO payments(id, patient_id, amount, created_at) VALUES('PAY-1','901',100,?)", (T,))
        c.execute("INSERT INTO zz_memberships(id, patient_id) VALUES('M-1','902')")
        c.execute("INSERT INTO patient_edits(id, patient_id, data, transferred) VALUES('E-1','903','{}',1)")
        c.execute("""INSERT OR REPLACE INTO visits_archive(id, patient_id, start) VALUES('VA-1','904','2001-01-01 10:00')""")
    d.purge(30)
    left = {r["id"] for r in d.q("SELECT id FROM patients WHERE id IN ('901','902','903','904')")}
    check("М10: kept — a payment names it", "901" in left, left)
    check("М10: kept — a table found by its column (memberships…)", "902" in left, left)
    check("М10: kept — a card edit names it", "903" in left, left)
    check("М10: dropped — only the never-purged history names it", "904" not in left, left)

    # ================================================================== М13: the copy for the other computers
    dp_main.role = lambda db: "main"
    d.meta_set("last_ok", "2026-11-13T10:00:00Z")
    builds = [0]
    real_read = dp_main._read

    def counting_read(db, full, border):
        builds[0] += 1
        return real_read(db, full, border)
    dp_main._read = counting_read
    lock_free = []
    real_dumps = dp_main.json.dumps

    def dumps_checking_lock(obj, **kw):
        got = []

        def probe():  # another thread (the UI) can take the app's lock while the copy is serialised
            ok = d._lock.acquire(timeout=2)
            if ok:
                d._lock.release()
            got.append(ok)
        t = threading.Thread(target=probe)
        t.start()
        t.join()
        lock_free.append(bool(got and got[0]))
        return real_dumps(obj, **kw)
    dp_main.json.dumps = dumps_checking_lock
    try:
        a = dp_main.snapshot(d, since="")
    finally:
        dp_main.json.dumps = real_dumps
    check("М13: the copy is serialised outside the app's lock", lock_free and all(lock_free), lock_free)
    b = dp_main.snapshot(d, since="old")
    check("М13: built once per stamp", builds[0] == 1 and a["z"] == b["z"], builds[0])
    check("М13: the same stamp still answers «same»", dp_main.snapshot(d, since=a["stamp"])["same"] is True)
    d.meta_set("last_ok", "2026-11-13T10:05:00Z")
    c3 = dp_main.snapshot(d, since=a["stamp"])
    check("М13: a new stamp builds a new copy", builds[0] == 2 and not c3["same"], builds[0])
    dp_main.snapshot(d, since="", full=True)
    check("М13: the full copy is its own entry", builds[0] == 3, builds[0])
    body = json.loads(dp_main.zlib.decompress(dp_main.base64.b64decode(c3["z"])).decode("utf-8"))
    check("М13: wire format unchanged", set(body) == {"tables", "meta", "archive_from"} and
          set(body["tables"]) == set(dp_main.TABLES) | {"patients", "visits_archive"} and
          set(body["tables"]["visits"]) == {"cols", "rows"}, sorted(body))
    # a follower applies it
    d2 = dbm.DB(Path(tempfile.mkdtemp()) / "f.db")
    counts = dp_main.apply(d2, c3)
    check("М13: a follower applies the copy", counts.get("branches") == 1 and
          d2.one("SELECT COUNT(*) n FROM visits")["n"] == d.one("SELECT COUNT(*) n FROM visits")["n"], counts)
    dp_main._read = real_read
except Exception:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    FAIL.append("exception")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  -", f)
sys.exit(1 if FAIL else 0)
