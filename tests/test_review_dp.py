"""Review 2026-11-13, group «dp» (Dentist Plus sync): regression checks for К3, К4, К5, В3, В4, В17.

A fake Dentist Plus in this process counts every request; no real Dentist Plus is called.
  К3  a visit sent from the main computer and moved on another one (the three-way merge keeps transferred=1) is sent
      again as a move of the same Dentist Plus visit — never lost, never created twice; a sent row stays a few days;
  К4  the temporary card of a new patient takes everything along to the Dentist Plus id (every table, its files);
  К5  a POST /patients whose connection dropped after the server took it is «unknown», never posted again;
      only a failure to connect means «offline, nothing sent»;
  В3  one re-login for parallel card threads; a 401 card is asked again; one doctor's schedule error does not drop the
      others; doctors gone from GET /doctors are pruned; a cloud-only computer of a clinic does not log in;
  В4  records and invoices of a visit made here move to its Dentist Plus id;
  В17 the main computer sends only after a fresh exchange with the clinic network; the follower says what to do."""
import json
import os
import socket
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
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
DP = {"token": "", "auths": 0, "writes": [], "drop_patient_post": False, "card401": set(), "sched404": set(),
      "sched_asked": set(), "delay": 0.0, "doctors": [{"id": 7, "name": "Врач Один"}, {"id": 8, "name": "Врач Два"}],
      "patients": {5: {"id": 5, "fname": "Олег", "lname": "Старый", "phone": "+79990000005"},
                   6: {"id": 6, "fname": "Ирина", "lname": "Вторая", "phone": "+79990000006"}},
      "visits": {100: {"id": 100, "patient_id": 5, "doctor_id": 7, "branch_id": 1, "start": f"{T} 09:00:00",
                       "end": f"{T} 09:30:00", "status": "confirmed"},
                 101: {"id": 101, "patient_id": 6, "doctor_id": 7, "branch_id": 1, "start": f"{T} 16:00:00",
                       "end": f"{T} 16:30:00", "status": "confirmed"}},
      "next": 500}


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
            DP["auths"] += 1
            DP["token"] = f"T{DP['auths']}"  # like Dentist Plus: a new token makes the previous one invalid
            return self.send(200, {"token": DP["token"]})
        if not self.authed():
            return self.send(401, {"error": "Авторизация не успешна"})
        DP["writes"].append(("POST", p, b))
        DP["next"] += 1
        nid = DP["next"]
        if p == "patients":
            DP["patients"][nid] = {"id": nid, "fname": b.get("fname"), "lname": b.get("lname"), "phone": b.get("phone")}
            if DP["drop_patient_post"]:  # the server did the write, then the link went down before the answer
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
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
        v.update({k: b[k] for k in ("start", "end", "doctor_id") if k in b})
        return self.send(200, {"data": v})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path.replace("/partner/", "")
        if DP["delay"]:
            time.sleep(DP["delay"])
        if not self.authed():
            return self.send(401, {"error": "Авторизация не успешна"})
        page = int(q.get("page", 1))

        def paged(items):
            return {"data": items if page == 1 else [], "meta": {"current_page": page, "last_page": 1}}
        if p == "branches":
            return self.send(200, paged([{"id": 1, "title": "Филиал"}]))
        if p == "doctors":
            return self.send(200, paged(DP["doctors"]))
        if p == "visits":
            f, t = q.get("date_from", ""), q.get("date_to", "9")
            return self.send(200, paged([v for v in DP["visits"].values() if f <= v["start"][:10] <= t]))
        if p.startswith("visits/"):
            v = DP["visits"].get(int(p.split("/")[1]))
            return self.send(200, v) if v else self.send(404, {"error": "Запись не найдена"})
        if p.startswith("patients/"):
            pid = p.split("/")[1]
            if pid in DP["card401"]:
                return self.send(401, {"error": "Авторизация не успешна"})
            return self.send(200, {"data": DP["patients"].get(int(pid), {"id": int(pid), "fname": "Без имени"})})
        if p == "schedule":
            doc = str(q.get("doctor_id"))
            DP["sched_asked"].add(doc)
            if doc in DP["sched404"]:
                return self.send(404, {"error": "Запись не найдена"})
            return self.send(200, [{"day": q["date_from"], "doctor_id": int(doc), "time_from": "09:00", "time_to": "18:00"}])
        if p in ("payments", "services", "chairs", "record_statuses"):
            return self.send(200, paged([]) if p in ("payments", "services") else [])
        self.send(404, {"error": "Запись не найдена"})


class Srv(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, *a):
        pass


srv = Srv(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}/partner"

import config  # noqa: E402
import db as dbm  # noqa: E402
import dp_main  # noqa: E402
import replica  # noqa: E402
from api_client import ApiError, DentistPlusClient, OfflineError, connect_failed  # noqa: E402
from local import Local  # noqa: E402
from pusher import Pusher  # noqa: E402
from sync import SyncWorker  # noqa: E402

config.save_settings({"demo": False, "base_url": BASE, "login": "u", "pass_enc": config.protect("p"),
                      "transfer_mode": "auto", "patient_extras": [], "days_back": 30})
d = dbm.DB()
w = SyncWorker(d)
L = Local(d)


def lv(vid):
    return d.one("SELECT * FROM local_visits WHERE id=?", (vid,))


def posts(path):
    return [x for x in DP["writes"] if x[0] == "POST" and x[1] == path]


def merge_in(vid, base, **edit):
    """What the clinic network does with an edit made on another computer from `base` (an older copy of the row)."""
    mine = lv(vid)
    theirs = {**base, **edit, "transferred": 0, "transferred_at": None, "push_status": None, "push_error": None}
    merged, _ = replica.merge(base, mine, theirs, mine_newer=False)
    with d.tx() as c:
        replica.write_row(c, replica.BY_NAME["local_visits"], [vid], merged)
    return merged


try:
    check("first sync", w.sync_once(), w.status())

    # =========================================================== К3 + В4: a visit moved on another computer
    v1 = L.save_visit({"patient_id": "5", "doctor_id": "7", "branch_id": "1", "start": f"{T} 10:00", "end": f"{T} 10:30"})
    base = lv(v1)  # the copy another computer had before the main one sent it
    with d.tx() as c:  # В4: a record and an invoice made on the visit before it was sent
        c.execute("INSERT INTO records(id, patient_id, visit_id, doctor_id, date, data, created_at) VALUES('R-1','5',?,'7',?,'{}',?)",
                  (v1, T, T))
        c.execute("INSERT INTO invoices(id, patient_id, visit_id, items, total, status, created_at) VALUES('I-1','5',?,'[]',0,'new',?)",
                  (v1, T))
    w.sync_once()
    row = lv(v1)
    rid = row["remote_id"]
    check("К3: visit sent, Dentist Plus id kept", row["transferred"] == 1 and rid and row["pushed_sig"], row)
    check("В4: the record points to the Dentist Plus visit", d.one("SELECT visit_id FROM records WHERE id='R-1'")["visit_id"] == rid)
    check("В4: the invoice too", d.one("SELECT visit_id FROM invoices WHERE id='I-1'")["visit_id"] == rid)
    n_post = len(posts("visits"))

    merged = merge_in(v1, base, start=f"{T} 11:00", end=f"{T} 11:30")
    check("К3 premise: the merge keeps transferred=1 with the new time", merged["transferred"] == 1
          and merged["start"] == f"{T} 11:00", merged)
    day = {(x["start"][11:16], x["local"]) for x in d.day(T)}
    check("К3: the moved visit is shown at once (not the old Dentist Plus time)", (f"11:00", 1) in day
          and not any(s == "10:00" for s, _ in day), day)
    w.sync_once()
    check("К3: the move went to Dentist Plus as a move of the same visit", DP["visits"][int(rid)]["start"] == f"{T} 11:00:00"
          and len(posts("visits")) == n_post, (DP["visits"][int(rid)], posts("visits")[n_post:]))
    row = lv(v1)
    check("К3: sent again, nothing pending", row["transferred"] == 1 and row["push_status"] == "sent"
          and not d.q("SELECT id FROM local_visits WHERE transferred=0"), row)

    w.sync_once()
    check("К3: the sent row stays a few days (hidden)", lv(v1) is not None
          and [x["start"][11:16] for x in d.day(T) if x["patient_id"] == "5" and x["start"][11:13] == "11"] == ["11:00"])
    # scenario B: an edit of the very first copy arrives after another sync — no second visit in Dentist Plus
    merge_in(v1, base, start=f"{T} 12:00", end=f"{T} 12:30")
    w.sync_once()
    check("К3: a late edit is a move again, never a new visit", len(posts("visits")) == n_post
          and DP["visits"][int(rid)]["start"] == f"{T} 12:00:00", posts("visits")[n_post:])

    # cleanup: only once the Dentist Plus id is in the mirror and the row is old enough; references move first
    with d.tx() as c:
        c.execute("INSERT INTO records(id, patient_id, visit_id, doctor_id, date, data, created_at) VALUES('R-2','5',?,'7',?,'{}',?)",
                  (v1, T, T))
        c.execute("UPDATE local_visits SET transferred_at=? WHERE id=?",
                  ((datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"), v1))
    w.sync_once()
    check("К3: an old sent row back in Dentist Plus is dropped", lv(v1) is None)
    check("В4: a record that still named the dropped row follows it", d.one("SELECT visit_id FROM records WHERE id='R-2'")["visit_id"] == rid)
    ghost = "L-ghost00001"
    with d.tx() as c:
        c.execute("""INSERT INTO local_visits(id, patient_id, doctor_id, branch_id, start, "end", status, title, comment, action,
                     created_at, updated_at, transferred, transferred_at, push_status, remote_id)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,'sent','99999')""",
                  (ghost, "5", "7", "1", f"{T} 18:00", f"{T} 18:30", "Запланирован", "", "", "create", T, T, "2000-01-01 00:00:00"))
    d.cleanup_transferred(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 30)
    check("К3: a sent row whose Dentist Plus id never came back is not dropped", lv(ghost) is not None)
    with d.tx() as c:
        c.execute("DELETE FROM local_visits WHERE id=?", (ghost,))

    # =========================================================== К4: the new patient's card follows the Dentist Plus id
    with d._lock:
        d.conn.executescript("""
            CREATE TABLE IF NOT EXISTS patient_consents(id TEXT PRIMARY KEY, patient_id TEXT, kind TEXT);
            CREATE TABLE IF NOT EXISTS questionnaires(id TEXT PRIMARY KEY, patient_id TEXT, answers TEXT);
            CREATE TABLE IF NOT EXISTS memberships(id TEXT PRIMARY KEY, type_id TEXT, patient_id TEXT);
            CREATE TABLE IF NOT EXISTS family_members(patient_id TEXT PRIMARY KEY, family_id TEXT, added_at TEXT);
            CREATE TABLE IF NOT EXISTS patient_marketing(patient_id TEXT PRIMARY KEY, source TEXT, no_calls INTEGER DEFAULT 0, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS patient_files(id TEXT PRIMARY KEY, patient_id TEXT, ext TEXT, deleted INTEGER DEFAULT 0);
        """)
    np = L.create_patient({"lname": "Новая", "fname": "Анна", "phone": "+7 900 111-22-33"})["id"]
    with d.tx() as c:
        c.execute("INSERT INTO patient_consents VALUES('C-1', ?, 'pd')", (np,))
        c.execute("INSERT INTO questionnaires VALUES('Q-1', ?, '{}')", (np,))
        c.execute("INSERT INTO memberships VALUES('M-1', 't', ?)", (np,))
        c.execute("INSERT INTO family_members VALUES(?, 'F-1', ?)", (np, T))
        c.execute("INSERT INTO patient_marketing(patient_id, source) VALUES(?, 'Сайт')", (np,))
        c.execute("INSERT INTO patient_files VALUES('PF-1', ?, '.jpg', 0)", (np,))
    import files  # noqa: E402
    (files._pdir(np) / "PF-1.jpg").write_bytes(b"jpeg")
    L.save_visit({"patient_id": np, "doctor_id": "7", "branch_id": "1", "start": f"{T} 14:00", "end": f"{T} 14:30"})
    w.sync_once()
    w.sync_once()
    rp = [k for k, v in DP["patients"].items() if v.get("lname") == "Новая"]
    real = str(rp[0]) if rp else None
    check("К4: the patient went to Dentist Plus once", len(rp) == 1, rp)
    check("К4: the temporary card is gone", d.one("SELECT 1 AS x FROM patients WHERE id=?", (np,)) is None)
    left = {t: d.one(f"SELECT COUNT(*) AS n FROM {t} WHERE patient_id=?", (np,))["n"]
            for t in dbm.tables_with(d.conn, "patient_id")}
    check("К4: nothing points to the temporary id any more", not any(left.values()), {k: v for k, v in left.items() if v})
    moved = {t: d.one(f"SELECT COUNT(*) AS n FROM {t} WHERE patient_id=?", (real,))["n"]
             for t in ("patient_consents", "questionnaires", "memberships", "family_members", "patient_marketing", "patient_files")}
    check("К4: consents, questionnaires, memberships, family, marketing, files moved", all(moved.values()), moved)
    check("К4: the file itself moved to the new card's folder", (files._pdir(real) / "PF-1.jpg").exists()
          and not (files.root() / np).exists())

    # =========================================================== К5: no duplicate patient after a dropped connection
    n_pp = len(posts("patients"))
    DP["drop_patient_post"] = True
    p2 = L.create_patient({"lname": "Обрыв", "fname": "Связи", "phone": "+7 900 000-00-01"})["id"]
    w.sync_once()
    DP["drop_patient_post"] = False
    st = d.one("SELECT push_status, push_error, transferred FROM patients WHERE id=?", (p2,))
    check("К5: the server got the POST once", len(posts("patients")) == n_pp + 1)
    check("К5: a connection dropped after sending = unknown (staff check)", st["push_status"] == "unknown", st)
    w.sync_once()
    check("К5: and it is not posted again", len(posts("patients")) == n_pp + 1, posts("patients")[n_pp:])
    p3 = L.create_patient({"lname": "Прерван", "fname": "Процесс"})["id"]
    with d.tx() as c:  # the program was closed (or the power went) while the POST was on the way
        c.execute("UPDATE patients SET push_status='sending' WHERE id=?", (p3,))
    w.sync_once()
    check("К5: a row left «sending» is unknown, not posted", d.one("SELECT push_status FROM patients WHERE id=?", (p3,))["push_status"]
          == "unknown" and len(posts("patients")) == n_pp + 1)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
    p4 = L.create_patient({"lname": "Нет", "fname": "Сети"})["id"]
    off = DentistPlusClient(f"http://127.0.0.1:{dead}/partner", "u", "p", timeout=3)
    off.token = "x"
    try:
        Pusher(d, off, config.load_settings()).push_patients()
        check("К5: no connection raises offline", False)
    except OfflineError:
        pass
    check("К5: no connection at all = offline, nothing sent, stays pending",
          d.one("SELECT push_status FROM patients WHERE id=?", (p4,))["push_status"] is None)
    import requests  # noqa: E402
    from urllib3.exceptions import ProtocolError  # noqa: E402
    from http.client import RemoteDisconnected  # noqa: E402
    try:
        requests.post(f"http://127.0.0.1:{dead}/x", timeout=3)
    except requests.RequestException as e:
        check("К5: refused connection is a connect failure", connect_failed(e), repr(e))
    dropped = requests.ConnectionError(ProtocolError("Connection aborted.", RemoteDisconnected("closed")))
    check("К5: a dropped answer is not a connect failure", not connect_failed(dropped))
    with d.tx() as c:  # the rest of the test does not need these
        c.execute("UPDATE patients SET transferred=1 WHERE id IN (?,?,?)", (p2, p3, p4))

    # =========================================================== В3: one re-login for parallel card threads
    c4 = DentistPlusClient(BASE, "u", "p")
    c4.auth()
    a0 = DP["auths"]
    DP["token"] = "renewed-elsewhere"  # the token stops working (expired)
    DP["delay"] = 0.05
    with ThreadPoolExecutor(max_workers=4) as pool:
        res = list(pool.map(lambda i: c4.request(f"patients/{5 + i % 2}"), range(24)))
    DP["delay"] = 0.0
    check("В3: four threads, one re-login", DP["auths"] - a0 == 1, DP["auths"] - a0)
    check("В3: every card answered", all(isinstance(r, dict) and r.get("data") for r in res))

    DP["card401"] = {"6"}
    w.sync_once()
    last = json.loads(d.one("SELECT counts FROM sync_log ORDER BY id DESC LIMIT 1")["counts"])
    check("В3: a card with 401 is kept for the next sync", "6" in json.loads(d.meta_get("patients_retry") or "[]"), last)
    DP["card401"] = set()
    w.sync_once()
    check("В3: and loaded by it", json.loads(d.meta_get("patients_retry") or "[]") == [])

    # schedule: one doctor fails — the others are saved, his old rows stay; doctors gone from Dentist Plus pruned
    d.upsert_doctors([{"id": 9, "name": "Ушёл Сзаписями"}, {"id": 10, "name": "Ушёл Совсем"}])
    with d.tx() as c:
        c.execute("INSERT INTO records(id, patient_id, visit_id, doctor_id, date, data, created_at) VALUES('R-9','5',NULL,'9',?,'{}',?)",
                  (T, T))
        c.execute("INSERT OR REPLACE INTO dp_schedule VALUES('8', ?, '', '1', '08:00', '12:00', 'old')", (T,))
    DP["sched404"] = {"8"}
    DP["sched_asked"] = set()
    d.meta_set("dp_dicts_at", "0")
    w.sync_once()
    last = json.loads(d.one("SELECT counts FROM sync_log ORDER BY id DESC LIMIT 1")["counts"])
    check("В3: the failing doctor is logged with his HTTP code", last.get("dp_schedule_failed") == {"8": "HTTP 404"}, last)
    check("В3: the other doctor's schedule saved", d.one("SELECT 1 AS x FROM dp_schedule WHERE doctor_id='7' AND synced_at<>'old'"))
    check("В3: the failing doctor keeps his rows", d.one("SELECT time_from FROM dp_schedule WHERE doctor_id='8' AND day=?", (T,)))
    check("В3: a doctor gone from Dentist Plus and named by nothing is deleted",
          d.one("SELECT 1 AS x FROM doctors WHERE id='10'") is None)
    check("В3: one still named by a record is kept, inactive, and not asked for a schedule",
          d.one("SELECT name FROM doctors WHERE id='9'") and json.loads(d.meta_get("doctors_inactive")) == ["9"]
          and "9" not in DP["sched_asked"] and "10" not in DP["sched_asked"], (d.meta_get("doctors_inactive"), DP["sched_asked"]))
    DP["sched404"] = set()

    # a computer joined to the clinic only through the cloud never logs in while another computer is the main one
    real_net, real_cloud = dp_main._in_network, dp_main._in_cloud
    with d.tx() as c:
        c.execute("INSERT OR REPLACE INTO dp_settings(k, v, updated_at) VALUES('dp_main', ?, ?)",
                  (json.dumps({"node": "other-node", "name": "Ресепшн"}), T))
    dp_main._in_network, dp_main._in_cloud = (lambda: False), (lambda: True)
    a0 = DP["auths"]
    check("В3: cloud-only computer of the clinic is a follower", dp_main.role(d) == "follower")
    w.sync_once()
    check("В3: and its sync does not log in", DP["auths"] == a0 and "облак" in w.status()["phase"], w.status()["phase"])
    check("В3: it explains why", "облак" in dp_main.blocked_reason(d))
    dp_main._in_cloud = lambda: False
    check("В3: a computer of no clinic works on its own", dp_main.role(d) == "solo")

    # =========================================================== В17: the follower's message; the main waits for the network
    dp_main._in_network = lambda: True
    w.sync_once()
    ph = w.status()["phase"]
    check("В17: main computer off — the follower says so and what the director can do",
          "недоступен" in ph and "директор" in ph and "Обмен с Dentist Plus ведёт этот компьютер" in ph, ph)
    import p2p  # noqa: E402
    d.conn.executescript(p2p.SCHEMA)
    dp_main.claim(d)
    check("В17: this computer is the main one now", dp_main.role(d) == "main")
    with d.tx() as c:
        c.execute("INSERT OR REPLACE INTO p2p_peers(node, name, ip, port, last_seen, last_sync) VALUES('peer-1','Ноутбук','10.0.0.2',8765,?,?)",
                  ("2000-01-01 00:00:00", "2000-01-01 00:00:00"))
    n_post = len(posts("visits"))
    v2 = L.save_visit({"patient_id": "6", "doctor_id": "7", "branch_id": "1", "start": f"{T} 19:00", "end": f"{T} 19:30"})
    w.sync_once()
    last = json.loads(d.one("SELECT counts FROM sync_log ORDER BY id DESC LIMIT 1")["counts"])
    check("В17: no fresh exchange with the clinic network — nothing sent yet", len(posts("visits")) == n_post
          and lv(v2)["transferred"] == 0 and last.get("push_waiting"), last)
    with d.tx() as c:
        c.execute("UPDATE p2p_peers SET last_sync=?", (time.strftime("%Y-%m-%d %H:%M:%S"),))
    w.sync_once()
    check("В17: after the exchange it is sent", len(posts("visits")) == n_post + 1 and lv(v2)["transferred"] == 1)
    dp_main._in_network, dp_main._in_cloud = real_net, real_cloud
finally:
    srv.shutdown()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
