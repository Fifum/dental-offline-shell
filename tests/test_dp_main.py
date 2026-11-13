"""3.7.2: one computer of the clinic talks to Dentist Plus, the others take the data from it over the clinic network.

Dentist Plus gives a clinic one API login, and every new token invalidates the previous one: two computers that sync
on their own log each other out («Авторизация не успешна»). Two real computers in miniature (separate processes,
tests/p2p_node.py) and a fake Dentist Plus that counts every request. Checked: the first computer with a login takes
the role by itself and the other one learns it over the network; the other computer — with the same login typed in —
never calls the API (no sync, no «Проверить подключение», no diagnostics) and gets visits, patients, doctors,
payments and the schedule from the main one; an unchanged copy is not sent again; with the main computer off the
other one says so and keeps its data; the director moves the role and the computers swap; the main computer sends
to Dentist Plus what was made on the other one. No real Dentist Plus is called."""
import json
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import p2p_harness as H  # noqa: E402

T = date.today()
DP = {"auth": 0, "calls": [], "token": ""}


def _visit(i, day, hour):
    s = f"{day} {hour:02d}:00:00"
    return {"id": i, "start": s, "end": f"{day} {hour:02d}:30:00", "doctor": {"id": 7, "fname": "Иван", "lname": "Врачев"},
            "patient": {"id": 5 + i % 3, "fname": "Олег", "lname": f"Пациент{i % 3}"}, "branch_id": 1,
            "status": "confirmed", "is_cancelled": False, "description": "Осмотр"}


VISITS = [_visit(100 + n, (T + timedelta(days=n % 5)).isoformat(), 9 + n % 8) for n in range(12)]


def page(items, q):
    pp, n = int(q.get("per_page", 20)), int(q.get("page", 1))
    return {"meta": {"current_page": n, "last_page": max(1, -(-len(items) // pp)), "per_page": pp, "total": len(items)},
            "data": items[(n - 1) * pp: n * pp]}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path.replace("/partner/", "")
        b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        DP["calls"].append(("POST", p))
        if p == "auth":
            if b != {"login": "u", "pass": "p"}:
                return self.send(401, {"error": "Авторизация не успешна"})
            DP["auth"] += 1
            DP["token"] = f"T{DP['auth']}"  # like Dentist Plus: the new token makes the previous one invalid
            exp = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            return self.send(200, {"token": DP["token"], "expires_at": exp})
        if self.headers.get("Authorization") != f"Bearer {DP['token']}":
            return self.send(401, {"error": "Авторизация не успешна"})
        if p == "patients":
            return self.send(200, {"id": 900, **b})
        self.send(404, {"error": "Запись не найдена"})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path.replace("/partner/", "")
        DP["calls"].append(("GET", p))
        if self.headers.get("Authorization") != f"Bearer {DP['token']}":
            return self.send(401, {"error": "Авторизация не успешна"})
        if p == "branches":
            return self.send(200, page([{"id": 1, "title": "Филиал №1"}], q))
        if p == "doctors":
            return self.send(200, page([{"id": 7, "fname": "Иван", "lname": "Врачев", "branches": [{"id": 1}]},
                                        {"id": 8, "fname": "Пётр", "lname": "Второй", "branches": [{"id": 1}]}], q))
        if p == "services":
            return self.send(200, page([{"id": 31, "title": "Пломба", "code": "A-1", "price": 1000}], q))
        if p == "chairs":
            return self.send(200, page([{"id": 4, "title": "Кресло №1"}], q))
        if p == "record_statuses":
            return self.send(200, [{"id": 2, "title": "Подтверждена"}])
        if p == "visits":
            vs = [v for v in VISITS if q.get("date_from", "") <= v["start"][:10] <= q.get("date_to", "9")]
            return self.send(200, page(vs, q))
        if p.startswith("patients/"):
            pid = int(p.split("/")[1])
            return self.send(200, {"id": pid, "fname": "Олег", "lname": f"Пациент{pid - 5}", "phone": f"+7999000000{pid}"})
        if p == "patients":
            return self.send(200, page([], q))
        if p == "payments":
            return self.send(200, page([{"id": 1, "date": f"{T} 10:00:00", "sum": 1500, "patient_id": 5, "visit_id": 100,
                                         "payment_type": "cash"}], q))
        if p == "schedule":
            return self.send(200, [{"doctor_id": 7, "date": T.isoformat(), "time_from": "09:00", "time_to": "18:00",
                                    "chair_id": 4, "branch_id": 1}])
        self.send(404, {"error": "Запись не найдена"})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}/partner"
check, wait, FAIL, OK = H.check, H.wait, H.FAIL, H.OK

SETUP = f"""
config.save_settings({{'login': 'u', 'pass_enc': config.protect('p'), 'base_url': {BASE!r}, 'demo': False,
                       'days_back': 7, 'days_forward': 7, 'chunk_days': 31}})
import sync, dp_main
w = sync.SyncWorker(db)
r = True
"""
SYNC = "ok = w.sync_once()\nr = {'ok': ok, 'role': dp_main.role(db), 'phase': w.state['phase'], 'err': w.state['last_error'], " \
       "'last_ok': db.meta_get('last_ok')}"
COUNTS = "r = {t: db.one(f'SELECT COUNT(*) AS n FROM {t}')['n'] for t in ('visits', 'doctors', 'branches', 'dp_payments', " \
         "'dp_schedule', 'visits_archive')}\nr['dp_patients'] = db.one('SELECT COUNT(*) AS n FROM patients WHERE COALESCE(local,0)=0')['n']"

A, B = H.Node("A"), H.Node("B")
try:
    # ------------------------------------------------------------ one clinic network of two computers
    A.run("r = p2p.create_clinic(db=db, fresh=True)")
    B.run(f"r = node.join([{{'ip': '127.0.0.1', 'port': {A.port}}}])")
    wait("A sees B asking to join", lambda: A.run("r = p2p.pending_pairs()"))
    A.run(f"r = p2p.accept_pair({B.node!r}, {B.run('r = node.joiner.code')!r})")  # the code on B's screen
    wait("B joined", lambda: B.run("r = node.joiner.state == 'done' and p2p.configured()"))
    A.run(SETUP)
    B.run(SETUP)  # the same login typed in on the second computer too — as in the clinic
    check("nobody has the role yet", A.run("r = dp_main.role(db)") == "solo" and B.run("r = dp_main.role(db)") == "solo")

    # ------------------------------------------------------------ the first computer to sync takes the role
    ra = A.run(SYNC)
    check("A synced with Dentist Plus", ra and ra["ok"] and not ra["err"], ra)
    check("A took the role by itself", ra and ra["role"] == "main", ra)
    ca = A.run(COUNTS)
    check("A has the data", ca["visits"] == 12 and ca["doctors"] == 2 and ca["dp_payments"] == 1 and ca["dp_patients"] == 3, ca)
    wait("B learns over the network that A talks to Dentist Plus", lambda: B.run("r = dp_main.role(db) == 'follower'"))

    # ------------------------------------------------------------ B never calls the API, takes the copy from A
    before = len(DP["calls"])
    rb = B.run(SYNC)
    check("B: no request to Dentist Plus at all", len(DP["calls"]) == before, DP["calls"][before:])
    check("B: sync is fine, no error", rb and rb["ok"] and not rb["err"], rb)
    check("B: phase names A", rb and "через компьютер" in rb["phase"], rb)
    cb = B.run(COUNTS)
    check("B has the same Dentist Plus data as A", cb == ca, (cb, ca))
    check("B shows the time of A's last sync", rb and rb["last_ok"] == ra["last_ok"], (rb, ra))
    check("B: patient cards with phones came too",
          B.one("SELECT phone FROM patients WHERE id='5'") == A.one("SELECT phone FROM patients WHERE id='5'") != None)
    st = B.run("r = api.status()")
    check("B status: configured, follower of A", st["configured"] and st["dp_main"]["role"] == "follower"
          and st["dp_main"]["online"] is True, st.get("dp_main"))
    tc = B.run("r = api.test_connection()")
    check("B: «Проверить подключение» does not log in (it would log A out)",
          len(DP["calls"]) == before and not tc["ok"] and "обменивается компьютер" in tc["message"], tc)
    dg = B.run("r = api.diagnostics()")
    check("B: diagnostics / developer report do not log in either", len(DP["calls"]) == before and "обменивается" in dg, dg[:200])
    nlog = B.one("SELECT COUNT(*) AS n FROM sync_log")["n"]
    B.run(SYNC)
    check("unchanged copy is not taken again", B.one("SELECT COUNT(*) AS n FROM sync_log")["n"] == nlog)

    # ------------------------------------------------------------ a change in Dentist Plus reaches B through A
    VISITS.append(_visit(150, T.isoformat(), 18))
    A.run(SYNC)
    calls = len(DP["calls"])
    B.run(SYNC)
    check("new Dentist Plus visit came to B via A", B.one("SELECT id FROM visits WHERE id='150'") is not None)
    check("…still without B calling the API", len(DP["calls"]) == calls, DP["calls"][calls:])

    # ------------------------------------------------------------ A's error is shown on B as A's
    A.run("db.meta_set('last_error', 'Ошибка API: Авторизация не успешна')\ndb.meta_set('last_ok', '2099-01-01 00:00:00')")
    rb = B.run(SYNC)
    check("B tells that the error is on A", rb and "на компьютере" in rb["err"], rb)
    A.run("db.meta_set('last_error', '')")

    # ------------------------------------------------------------ A off: B says so and keeps its data
    A.offline(True)
    B.run("node.live.clear()")
    rb = B.run(SYNC)
    check("A off: B explains, no API call", rb and "не в сети" in rb["err"] and len([c for c in DP["calls"] if c[1] == "auth"]) == DP["auth"], rb)
    check("A off: B keeps the data", B.run(COUNTS)["visits"] == 13)
    A.offline(False)
    wait("A back in the network", lambda: B.run("r = dp_main.status(db)['online']"))

    # ------------------------------------------------------------ the director moves the role to B
    B.run("r = api.dp_main_claim()")
    check("B is main now", B.run("r = dp_main.role(db)") == "main")
    wait("A learns it is not main any more", lambda: A.run("r = dp_main.role(db) == 'follower'"))
    n_auth = DP["auth"]
    rb = B.run(SYNC)
    check("B syncs with Dentist Plus itself now", rb and rb["ok"] and not rb["err"] and DP["auth"] == n_auth + 1, (rb, DP["auth"]))
    calls = len(DP["calls"])
    ra = A.run(SYNC)
    check("A no longer calls Dentist Plus", len(DP["calls"]) == calls and ra and ra["ok"] and not ra["err"], (ra, DP["calls"][calls:]))

    # ------------------------------------------------------------ the main computer sends what was made on the other one
    pid = A.run("r = api.create_patient({'lname': 'Новый', 'fname': 'Пациент', 'phone': '+79990001111'})['id']")
    wait("patient made on A reached B", lambda: B.one("SELECT id FROM patients WHERE id=?", (pid,)))
    own_b = B.run(f"from pusher import Pusher\nr = [x['id'] for x in Pusher(db, None, config.load_settings())._own(db.q('SELECT * FROM patients WHERE local=1'), 'patients')]")
    check("main computer B sends the patient made on A", pid in (own_b or []), own_b)
    own_a = A.run("import dp_main\nr = dp_main.role(db)")
    check("A, not main, would not send (role follower)", own_a == "follower")
finally:
    A.stop()
    B.stop()
    srv.shutdown()
    print(f"test_dp_main: {OK[0]} ok, {len(FAIL)} failed")
    for f in FAIL:
        print("FAIL", f)
sys.exit(1 if FAIL else 0)
