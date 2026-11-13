"""3.0, the clinic network: computers of one clinic find each other in the local network and sync directly.

Three real computers in miniature — separate processes, each with its own data folder, server and port — on this
machine (the UDP broadcast reaches 127.0.0.1). Checked: the first computer creates the clinic, a new one finds it
and asks to join, gets nothing until the director accepts (and the code matches), then gets everything; changes go
both ways at once; a staff request reaches the director and the approval comes back; two computers working apart
change the same rows and converge to the same data with the conflict in the journal; files arrive; a third
computer accepted on another computer of the director; LAN and the cloud together give no duplicates or false
conflicts; a stranger with a wrong key gets nothing."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.mkdtemp())
sys.path.insert(0, str(ROOT / "cloud"))
import cloud_server  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:600]}")


def free_port():
    while True:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            u.bind(("0.0.0.0", p + 1))
            return p
        except OSError:
            continue
        finally:
            u.close()


PORTS = {n: free_port() for n in "ABC"}
ENV = {**os.environ, "DD_DISCOVERY_PORTS": ",".join(str(p + 1) for p in PORTS.values()), "DD_P2P_DELAY": "0.3",
       "DD_P2P_INTERVAL": "4", "DD_P2P_TICK": "0.3", "DD_CLOUD_DELAY": "3600", "PYTHONIOENCODING": "utf-8"}


class Node:
    def __init__(self, name):
        self.name, self.port = name, PORTS[name]
        self.dir = BASE / name
        self.dir.mkdir()
        self.p = subprocess.Popen([sys.executable, str(ROOT / "tests" / "p2p_node.py"), str(self.dir), str(self.port)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=ENV, text=True, encoding="utf-8")
        hello = json.loads(self.p.stdout.readline())
        self.node = hello["node"]

    def run(self, code, quiet=False):
        self.p.stdin.write(json.dumps({"code": code}) + "\n")
        self.p.stdin.flush()
        ans = json.loads(self.p.stdout.readline())
        if not ans["ok"] and not quiet:
            FAIL.append(f"{self.name}: {ans['error']}\n{ans.get('tb', '')}")
        return ans.get("r") if ans["ok"] else ans

    def q(self, sql, args=()):
        return self.run(f"r = db.q({sql!r}, {tuple(args)!r})")

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def offline(self, on):
        """The router is off for this computer: it neither answers nor asks."""
        if on:
            self.run("import p2p as _p\n_p._h = _p.handle\ndef _off(*a, **k): raise _p.P2PError('нет сети', 503)\n"
                     "_p.handle = _off\nnode._r, node._n = node.round, node.notify_all\nnode.round = lambda full: None\n"
                     "node.notify_all = lambda: None")
        else:
            self.run("p2p.handle = p2p._h\nnode.round, node.notify_all = node._r, node._n\nnode.wake(full=True)")

    def stop(self):
        try:
            self.p.stdin.close()
            self.p.wait(5)
        except Exception:  # noqa: BLE001
            self.p.kill()


def wait(name, fn, timeout=25):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                OK[0] += 1
                return last
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.3)
    FAIL.append(f"{name} (timeout) {str(last)[:300]}")
    return None


SNAP = """
import json as _j
r = {}
for t in replica.TABLES:
    if t.name in ('audit',):
        continue
    try:
        rows = db.q(f"SELECT * FROM {t.name}" + (f" WHERE {t.where}" if t.where else ""))
    except Exception:
        continue
    r[t.name] = {_j.dumps([x[c] for c in t.key], ensure_ascii=False): _j.dumps(replica.read_row(db.conn, t, [x[c] for c in t.key]),
                 ensure_ascii=False, sort_keys=True) for x in rows}
"""


def same_data(a, b):
    sa, sb = a.run(SNAP), b.run(SNAP)
    diff = [f"{t}:{k}" for t in set(sa) | set(sb) for k in set(sa.get(t, {})) | set(sb.get(t, {}))
            if sa.get(t, {}).get(k) != sb.get(t, {}).get(k)]
    return diff


A, B = Node("A"), Node("B")
C = None
try:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    # ================================================================= first computer creates the clinic
    check("fresh computer is not in a clinic", not A.run("r = p2p.configured()"))
    check("nobody found yet", A.run("r = p2p.scan(1.5)") == [])
    A.run("r = p2p.create_clinic(db=db, fresh=True)")
    check("clinic created, demo data gone", A.run("r = [p2p.configured(), config.load_settings()['demo']]") == [True, False])
    st = A.run("r = auth.state('', True)")
    check("first computer may make the director", st["can_bootstrap"], st)
    A.run("r = auth.bootstrap({'login': 'director', 'name': 'Иван Директоров', 'password': 'devtest1'}, '127.0.0.1', 't', True)['user']['role']")
    A.run("pid = api.create_patient({'lname': 'Иванов', 'fname': 'Пётр', 'phone': '+79990001122'})['id']\nr = pid")
    pid = A.run("r = pid")

    # ================================================================= a new computer finds it and asks
    found = wait("B finds the clinic of A in the network", lambda: B.run("r = p2p.scan(1.5)"))
    check("found clinic is A's", found and found[0]["computers"][0]["node"] == A.node, found)
    clinic = found[0]["clinic"]
    check("clinic id is not the key", clinic == A.run("r = p2p.clinic_id()") and len(clinic) == 16)
    jr = B.run(f"r = node.join([{{'ip': '127.0.0.1', 'port': {A.port}}}])")
    pend = wait("A shows the pairing request", lambda: A.run("r = p2p.pending_pairs()"))
    check("request shows the same code as the new computer", pend and pend[0]["code"] == jr["code"] and pend[0]["node"] == B.node,
          (pend, jr))
    time.sleep(1.5)
    check("not accepted yet: B has no clinic key and no data", B.run("r = [p2p.configured(), db.one('SELECT COUNT(*) AS n FROM users')['n']]") == [False, 0])
    # a stranger in the Wi-Fi without the key gets nothing
    ans = B.run(f"""
import secrets
from cloud import Keys
k = Keys(secrets.token_bytes(32))
body = p2p.seal_request(k, 'pull', {{'since': 0}})
body['c'] = {clinic!r}
try:
    p2p.call  # same wire, wrong key
    import urllib.request, json
    req = urllib.request.Request('http://127.0.0.1:{A.port}/p2p/pull', data=json.dumps(body).encode(), method='POST')
    urllib.request.urlopen(req, timeout=5)
    r = 'answered'
except Exception as e:
    r = str(getattr(e, 'code', e))
""")
    check("wrong key: refused", ans == "403", ans)
    raw = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{A.port}/p2p/pair_poll", data=json.dumps({"node": "x"}).encode(),
                                                        method="POST"), timeout=5).read()
    check("poll for an unknown computer tells nothing", json.loads(raw) == {"state": "unknown"})

    A.run(f"r = p2p.accept_pair({B.node!r}, {B.run('r = node.joiner.code')!r})")  # the code on B's screen
    wait("B joined the clinic", lambda: B.run("r = node.joiner.state == 'done' and p2p.configured()"))
    check("same clinic now", B.run("r = p2p.clinic_id()") == clinic)
    check("B is a member, may not make a second director", B.run("r = auth.state('', True)['can_bootstrap']") is False)
    wait("director account arrived on B", lambda: B.one("SELECT role FROM users WHERE login='director'"))
    check("director signs in on B with the same password",
          B.run("r = auth.login('director', 'devtest1', '127.0.0.1', 't')['user']['role']") == "director")
    wait("patient of A arrived on B", lambda: B.one("SELECT name FROM patients WHERE id=?", (pid,)))
    check("request done on A", A.run("r = p2p.pending_pairs()") == [])

    # ================================================================= changes go both ways at once
    t0 = time.time()
    vid = B.run(f"r = api.save_visit({{'patient_id': {pid!r}, 'doctor_id': '12', 'start': '{tomorrow} 10:00', 'end': '{tomorrow} 10:30', 'title': 'Осмотр'}})")
    vid = vid["id"] if isinstance(vid, dict) else vid
    wait("appointment made on B reached A", lambda: A.one("SELECT title FROM local_visits WHERE id=?", (vid,)), timeout=10)
    check("…within a few seconds (by event, not by the minute)", time.time() - t0 < 4, time.time() - t0)
    A.run(f"db.conn.execute(\"UPDATE patients SET phone='+79995550000' WHERE id=?\", ({pid!r},)); db.conn.commit()")
    wait("edit on A reached B", lambda: (B.one("SELECT phone FROM patients WHERE id=?", (pid,)) or {}).get("phone") == "+79995550000")

    # ================================================================= staff request → director → back
    B.run("r = auth.register({'login': 'olga', 'name': 'Ольга Админ', 'password': 'olga12345', 'position': 'Администратор'}, '127.0.0.1')")
    u = wait("staff request reached the director's computer", lambda: A.one("SELECT * FROM users WHERE login='olga' AND status='pending'"))
    if u:
        A.run(f"d = db.one(\"SELECT * FROM users WHERE login='director'\")\n"
              f"r = auth.staff_save(d, {{'id': {u['id']}, 'name': 'Ольга Админ', 'role': 'admin', 'status': 'active'}})")
    wait("approval came back to B", lambda: (B.one("SELECT status FROM users WHERE login='olga'") or {}).get("status") == "active")
    check("approved employee signs in on B", B.run("r = auth.login('olga', 'olga12345', '127.0.0.1', 't')['user']['login']") == "olga")

    # ================================================================= files
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    fid = A.run(f"import base64\nr = api._files.add({pid!r}, 'снимок.png', base64.b64decode({png!r}))['id']")
    got = wait("X-ray file arrived on B, the same bytes", lambda: B.run(
        f"import base64, files\nrow = db.one('SELECT * FROM patient_files WHERE id=?', ({fid!r},))\n"
        f"p = files._pdir({pid!r}) / (row['id'] + row['ext']) if row else None\n"
        f"r = bool(p and p.exists() and p.read_bytes() == base64.b64decode({png!r}))"))

    # ================================================================= apart, then together: conflicts
    inv = A.run(f"r = api.save_invoice({{'patient_id': {pid!r}, 'items': [{{'title': 'Осмотр', 'price': 1000, 'qty': 1}}], 'comment': 'начало'}})")
    inv = inv["id"] if isinstance(inv, dict) else inv
    A.run(f"r = api.add_note({pid!r}, 'Боится уколов')", quiet=True)
    wait("invoice reached B", lambda: B.one("SELECT id FROM invoices WHERE id=?", (inv,)))
    wait("both converged before the outage", lambda: not same_data(A, B))
    A.offline(True)
    B.offline(True)
    A.run(f"db.conn.execute(\"UPDATE patients SET phone='+79990009999' WHERE id=?\", ({pid!r},)); db.conn.commit()")
    A.run(f"r = api.save_invoice({{'id': {inv!r}, 'patient_id': {pid!r}, 'items': [{{'title': 'Осмотр', 'price': 1000, 'qty': 1}}], 'comment': 'от A'}})")
    va = A.run(f"r = api.save_visit({{'patient_id': {pid!r}, 'doctor_id': '12', 'start': '{tomorrow} 15:00', 'end': '{tomorrow} 15:30', 'title': 'A'}})")
    time.sleep(0.05)
    B.run(f"db.conn.execute(\"UPDATE patients SET birth='1980-05-02' WHERE id=?\", ({pid!r},)); db.conn.commit()")
    B.run(f"r = api.save_invoice({{'id': {inv!r}, 'patient_id': {pid!r}, 'items': [{{'title': 'Осмотр', 'price': 1000, 'qty': 1}}], 'comment': 'от B'}})")
    vb = B.run(f"r = api.save_visit({{'patient_id': {pid!r}, 'doctor_id': '12', 'start': '{tomorrow} 15:00', 'end': '{tomorrow} 15:30', 'title': 'B'}})")
    time.sleep(1.2)
    check("apart: nothing travelled", (A.one("SELECT comment FROM invoices WHERE id=?", (inv,)) or {}).get("comment") == "от A")
    A.offline(False)
    B.offline(False)
    wait("THE BLOCK: both computers converged to the same data", lambda: not same_data(A, B), timeout=30)
    d = same_data(A, B)
    check("no difference left", not d, d[:5])
    p = A.one("SELECT phone, birth FROM patients WHERE id=?", (pid,))
    check("edits of different fields of one patient both kept", p and p["phone"] == "+79990009999" and p["birth"] == "1980-05-02", p)
    check("same field: the later change wins", (A.one("SELECT comment FROM invoices WHERE id=?", (inv,)) or {}).get("comment") == "от B")
    both = A.q("SELECT id FROM local_visits WHERE start=?", (f"{tomorrow} 15:00",))
    va, vb = (va["id"] if isinstance(va, dict) else va), (vb["id"] if isinstance(vb, dict) else vb)
    check("two bookings of one slot: both kept", {v["id"] for v in both} == {va, vb}, both)
    conf = A.q("SELECT * FROM sync_conflicts WHERE tbl='invoices' AND field='comment'") + \
        B.q("SELECT * FROM sync_conflicts WHERE tbl='invoices' AND field='comment'")
    check("the overwritten value is in the conflict journal", conf and conf[0]["other"] == "от A", conf)
    noise = A.q("SELECT tbl, field FROM sync_conflicts WHERE tbl<>'invoices'") + B.q("SELECT tbl, field FROM sync_conflicts WHERE tbl<>'invoices'")
    check("no false conflicts (seed data, timestamps, merges coming back)", not noise, noise)
    n1 = A.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"]
    time.sleep(5)  # another full round: merged versions must not bounce
    check("merged rows do not bounce between computers", A.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"] == n1
          and not A.q("SELECT * FROM sync_dirty") and not same_data(A, B))
    cid = (A.one("SELECT id FROM sync_conflicts WHERE tbl='invoices' AND field='comment'") or {}).get("id")
    if cid:
        A.run(f"r = replica.conflict_restore(db, {cid})")
        wait("value brought back from the journal reached B",
             lambda: (B.one("SELECT comment FROM invoices WHERE id=?", (inv,)) or {}).get("comment") == "от A")
    own = B.run(f"import pusher\nr = [x['id'] for x in pusher.Pusher(db, None, {{}})._own([{{'id': {vid!r}}}, {{'id': {va!r}}}], 'local_visits')]")
    check("Dentist Plus: B sends only what was made on B", own == [vid], own)

    # ================================================================= a third computer, accepted on B
    C = Node("C")
    C.run(f"r = node.join([{{'ip': '127.0.0.1', 'port': {A.port}}}, {{'ip': '127.0.0.1', 'port': {B.port}}}])")
    wait("B shows the request too", lambda: B.run("r = p2p.pending_pairs()"))
    B.run(f"r = p2p.accept_pair({C.node!r}, {C.run('r = node.joiner.code')!r})")  # the code on C's screen
    wait("C joined via B", lambda: C.run("r = p2p.clinic_id()") == clinic)
    wait("C has the same data as A", lambda: not same_data(A, C), timeout=30)
    wait("A's pending request for C is cleared", lambda: A.run("r = p2p.pending_pairs()") == [])

    # ================================================================= LAN + cloud together
    CPORT = free_port()
    httpd, CL = cloud_server.serve(str(BASE / "cloud"), port=CPORT, background=True)
    t1 = CL.create_tenant("Клиника")
    j = A.run(f"r = api._cloud_obj().join('http://127.0.0.1:{CPORT}', {t1['invite']!r}, 'A')")
    check("cloud joined with the clinic key", j and j.get("ok"), j)
    code = A.run("r = api._cloud_obj().code_for_others()")
    B.run(f"r = api._cloud_obj().join('', {code!r}, 'B')")
    ra = A.run("r = api._cloud_obj().sync()")
    check("A pushed its versions to the cloud", ra and ra.get("ok") and ra["pushed"] > 0, ra)
    rb = B.run("r = api._cloud_obj().sync()")
    check("B: the same versions came by LAN — nothing new to push, nothing to merge", rb and rb.get("ok") and rb["pushed"] == 0
          and rb["conflicts"] == 0, rb)
    c0 = A.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"] + B.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"]
    B.run(f"db.conn.execute(\"UPDATE patients SET phone='+70000000001' WHERE id=?\", ({pid!r},)); db.conn.commit()")
    time.sleep(1.5)
    B.run("r = api._cloud_obj().sync()")
    ra = A.run("r = api._cloud_obj().sync()")
    check("A got B's change by LAN first: the cloud copy is the same version", ra and ra["conflicts"] == 0 and ra["pushed"] == 0, ra)
    c1 = A.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"] + B.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"]
    check("LAN and cloud together: no false conflicts", c1 == c0, (c0, c1))
    check("phone the same everywhere", A.one("SELECT phone FROM patients WHERE id=?", (pid,))["phone"] == "+70000000001")
    httpd.shutdown()
finally:
    for n in (A, B, C):
        if n:
            n.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
