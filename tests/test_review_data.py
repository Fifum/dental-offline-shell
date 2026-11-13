"""Review 2026-11-13, data integrity: damaged settings never turn a real database into demo data (К1), the merge
ancestor after several local edits (К2), raw schema scripts never commit another thread's transaction (В1), a
restore from a backup is not undone by the other computers (В2), patient files are written atomically and checked
(В15), the sync loop survives an error (В21)."""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import db as dbm  # noqa: E402
import replica  # noqa: E402

FAIL, OK = [], [0]
TMP = Path(os.environ["LOCALAPPDATA"])


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:600]}")


def mk(name):
    d = dbm.DB(str(TMP / (name + ".db")))
    replica.install(d)
    return d


def edit(d, sql, node, args=()):
    with d.tx() as c:
        c.execute(sql, args)
    time.sleep(0.01)
    replica.stamp(d, node)


def pull(dst, src, node, since=0):
    return replica.apply_versions(dst, replica.changes_since(src, since, 1000), node)


# ------------------------------------------------------------------ К2 --
A, B = mk("k2a"), mk("k2b")
edit(A, "INSERT INTO local_visits(id, patient_id, status, comment) VALUES('V1','P1','booked','')", "A")
pull(B, A, "B")
mA, mB = replica.top_seq(A), replica.top_seq(B)
edit(A, "UPDATE local_visits SET status='came' WHERE id='V1'", "A")
edit(A, "UPDATE local_visits SET status='done' WHERE id='V1'", "A")
time.sleep(0.05)
edit(B, "UPDATE local_visits SET comment='allergy: penicillin' WHERE id='V1'", "B")
pull(B, A, "B", mA)
pull(A, B, "A", mB)
for _ in range(2):
    pull(B, A, "B")
    pull(A, B, "A")
for n, d in (("A", A), ("B", B)):
    r = d.one("SELECT status, comment FROM local_visits WHERE id='V1'")
    check(f"К2 {n}: two edits on A and one on B keep A's status and B's comment",
          r == {"status": "done", "comment": "allergy: penicillin"}, r)
    check(f"К2 {n}: no false conflict", not d.q("SELECT * FROM sync_conflicts"), d.q("SELECT field, kept, other FROM sync_conflicts"))
check("К2: both computers end with the same version",
      A.one("SELECT ver FROM sync_rows WHERE tbl='local_visits'") == B.one("SELECT ver FROM sync_rows WHERE tbl='local_visits'"))

# B took A's first edit, then both edit again: the ancestor is that edit (B's own), not the row before it
A, B = mk("k2c"), mk("k2d")
edit(A, "INSERT INTO local_visits(id, patient_id, status, comment, title) VALUES('V1','P1','booked','','')", "A")
pull(B, A, "B")
edit(A, "UPDATE local_visits SET status='came' WHERE id='V1'", "A")
pull(B, A, "B")
edit(A, "UPDATE local_visits SET status='done' WHERE id='V1'", "A")
edit(A, "UPDATE local_visits SET title='crown' WHERE id='V1'", "A")
time.sleep(0.05)
edit(B, "UPDATE local_visits SET comment='call back' WHERE id='V1'", "B")
for _ in range(2):
    pull(B, A, "B")
    pull(A, B, "A")
for n, d in (("A", A), ("B", B)):
    r = d.one("SELECT status, comment, title FROM local_visits WHERE id='V1'")
    check(f"К2 {n}: an edit already taken by B is the ancestor", r == {"status": "done", "comment": "call back", "title": "crown"}, r)
    check(f"К2 {n}: no false conflict (2)", not d.q("SELECT * FROM sync_conflicts"), d.q("SELECT field, kept, other FROM sync_conflicts"))

# a real conflict is still a conflict
A, B = mk("k2e"), mk("k2f")
edit(A, "INSERT INTO local_visits(id, patient_id, status) VALUES('V1','P1','booked')", "A")
pull(B, A, "B")
edit(A, "UPDATE local_visits SET status='came' WHERE id='V1'", "A")
edit(A, "UPDATE local_visits SET status='done' WHERE id='V1'", "A")
time.sleep(0.05)
edit(B, "UPDATE local_visits SET status='cancelled' WHERE id='V1'", "B")
for _ in range(2):
    pull(B, A, "B")
    pull(A, B, "A")
ra, rb = A.one("SELECT status FROM local_visits"), B.one("SELECT status FROM local_visits")
check("К2: a status changed on both sides — the later one wins on both", ra == rb == {"status": "cancelled"}, (ra, rb))
check("К2: and the other value is in the journal", B.q("SELECT kept, other FROM sync_conflicts") == [{"kept": "cancelled", "other": "done"}],
      B.q("SELECT kept, other FROM sync_conflicts"))

# ------------------------------------------------------------------ К1 --
config.save_settings({"demo": False, "login": "first"})
config.save_settings({"login": "second"})
bak = config._bak()
check("К1: the previous settings are kept as settings.json.bak", json.loads(bak.read_text(encoding="utf-8")).get("login") == "first")
config.SETTINGS_PATH.write_bytes(b"\x00" * 300)  # NTFS after a power cut
s = config.load_settings()
check("К1: a damaged settings.json → the copy, not the demo defaults", s["demo"] is False and s["login"] == "first", s)
config.save_settings({"interval_min": 7})
s = config.load_settings()
check("К1: saving over a damaged file keeps the copy's settings", s["login"] == "first" and s["interval_min"] == 7 and not s["demo"], s)
check("К1: no temporary file left", not config.SETTINGS_PATH.with_suffix(".tmp").exists())
config.SETTINGS_PATH.write_bytes(b"\x00" * 300)
bak.write_bytes(b"{\"demo\": tr")
s = config.load_settings()
check("К1: both damaged → demo stays off", s["demo"] is False and s.get("settings_damaged") is True, s)
config.SETTINGS_PATH.unlink()
bak.unlink()
check("К1: a fresh install still starts in demo", config.load_settings()["demo"] is True)

import demo  # noqa: E402
import sync  # noqa: E402

R = dbm.DB(str(TMP / "k1real.db"))
replica.install(R)
with R.tx() as c:
    c.execute("INSERT INTO patients(id, name, local) VALUES('L-1', 'Real Patient', 1)")
    c.execute("INSERT INTO local_visits(id, patient_id, status) VALUES('V-1', 'L-1', 'booked')")
replica.stamp(R, "R")
R.meta_set("last_ok", "2026-11-12T10:00:00")
check("К1: a database of an older version with a sync from Dentist Plus counts as real", R.has_real_data())
check("К1: ensure_demo refuses to wipe it", demo.ensure_demo(R, force=True) is False)
check("К1: the patient is still there", R.one("SELECT name FROM patients WHERE id='L-1'") == {"name": "Real Patient"})
w = sync.SyncWorker(R)
check("К1: sync_once with «demo» does nothing to a real database", w.sync_once({"demo": True}) is True and
      "Демо-режим недоступен" in w.status()["phase"] and R.one("SELECT COUNT(*) n FROM local_visits")["n"] == 1, w.status())
R.meta_set("last_ok", None)
with R.tx() as c:
    c.execute("DELETE FROM meta WHERE key='last_ok'")
check("К1: rows that came from the clinic network count as real too", R.has_real_data())
w.sync_once({"demo": False, "login": "", "pass_enc": ""})
check("К1: a sync with demo off marks the database as real", R.data_kind() == "real", R.data_kind())

F = dbm.DB(str(TMP / "k1fresh.db"))
check("К1: a fresh database is not real", not F.has_real_data())
check("К1: demo data is built on a fresh database", demo.ensure_demo(F, force=True) is True and F.one("SELECT COUNT(*) n FROM patients")["n"] > 0)
F.wipe()
check("К1: after a full wipe the demo is allowed again", F.data_kind() == "none" and not F.has_real_data())

# _leave_demo: the wipe of demo data is not replicated
Q = dbm.DB(str(TMP / "k1quiet.db"))
replica.install(Q)
with Q.tx() as c:
    c.execute("INSERT INTO local_visits(id, patient_id, status) VALUES('V-9', 'P', 'booked')")
replica.stamp(Q, "Q")
Q.wipe(quiet=True)
check("К1: a quiet wipe leaves nothing to replicate", Q.one("SELECT COUNT(*) n FROM sync_dirty")["n"] == 0 and replica.stamp(Q, "Q") == 0)
check("К1: and switches the replication back on", Q.one("SELECT v FROM sync_state WHERE k='applying'")["v"] == "0")
config.save_settings({"demo": True})
import p2p  # noqa: E402
p2p._leave_demo(Q)
check("К1: leaving demo marks the database real", Q.data_kind() == "real" and config.load_settings()["demo"] is False)
config.save_settings({"demo": True})

# ------------------------------------------------------------------ В1 --
import voices  # noqa: E402

V = dbm.DB(str(TMP / "b1.db"))
err = []


def bg():
    try:
        with V.tx() as c:
            c.execute("INSERT INTO notes(patient_id, text) VALUES('P1', 'half of a transaction')")
            time.sleep(0.5)
            raise RuntimeError("second half failed")
    except Exception as e:  # noqa: BLE001
        err.append(repr(e))


t = threading.Thread(target=bg)
t.start()
time.sleep(0.1)
voices.ensure_schema(V)
t.join()
check("В1: the other thread's transaction rolled back as a whole", V.q("SELECT text FROM notes") == [] and
      err and "second half" in err[0], (V.q("SELECT text FROM notes"), err))
check("В1: the schema is there", V.one("SELECT name FROM sqlite_master WHERE name='voice_prints'") is not None)
# the same for the schema of the modules made when a background thread already works
from accounting import Accounting  # noqa: E402
from marketing import Marketing  # noqa: E402
from shifts import Shifts  # noqa: E402
from stock import Stock  # noqa: E402
for mod in (Accounting, Marketing, Shifts, Stock):
    err.clear()
    t = threading.Thread(target=bg)
    t.start()
    time.sleep(0.1)
    mod(V)
    t.join()
    check(f"В1: {mod.__name__}() does not commit another thread's transaction", V.q("SELECT text FROM notes") == [], mod.__name__)
src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
i = src.index("def start_server")
body = src[i:src.index("def stop", i)]
check("В1: the sync worker starts after Api, the server and the node are made",
      body.index("self.worker.start()") > max(body.index("Api(db"), body.index("ClinicServer("), body.index("p2p.Node(")))

# ------------------------------------------------------------------ В2 --
A, B = mk("b2a"), mk("b2b")
with A.tx() as c:
    c.execute("INSERT INTO records(id, patient_id, data) VALUES('R1', 'P1', '{\"text\": \"treatment\"}')")
    c.execute("INSERT INTO records(id, patient_id, data) VALUES('R2', 'P1', '{\"text\": \"first\"}')")
replica.stamp(A, "A")
pull(B, A, "B")
copy = str(TMP / "b2bak.db")
s3 = sqlite3.connect(copy)
A.conn.commit()
A.conn.backup(s3)
s3.close()
time.sleep(0.02)
edit(A, "DELETE FROM records WHERE id='R1'", "A")
pull(B, A, "B")
edit(B, "UPDATE records SET data='{\"text\": \"changed on B\"}' WHERE id='R2'", "B")
pull(A, B, "A")
check("В2: before the restore R1 is deleted everywhere", not A.q("SELECT id FROM records WHERE id='R1'") and not B.q("SELECT id FROM records WHERE id='R1'"))
known = replica.known_nodes(A)
check("В2: the computers known before the restore", known == {"A", "B"}, known)
src3 = sqlite3.connect(copy)
with A._lock:
    A.conn.commit()
    src3.backup(A.conn)
src3.close()
replica.install(A)
replica.new_epoch(A)
n = replica.restamp_all(A, "A", known)
check("В2: every row of the restored database got a new version", n == 2, n)
pull(A, B, "A")
pull(B, A, "B")
pull(A, B, "A")
for nm, d in (("A", A), ("B", B)):
    rows = {r["id"]: json.loads(r["data"])["text"] for r in d.q("SELECT id, data FROM records")}
    check(f"В2 {nm}: the restored state wins after the exchange", rows == {"R1": "treatment", "R2": "first"}, rows)
# a change made on B after the restore still arrives
time.sleep(0.02)
edit(B, "UPDATE records SET data='{\"text\": \"after the restore\"}' WHERE id='R2'", "B")
pull(A, B, "A")
check("В2: a later change on another computer still arrives",
      json.loads(A.one("SELECT data FROM records WHERE id='R2'")["data"])["text"] == "after the restore")
replica.HOLD = "test hold"
import cloud  # noqa: E402
check("В2: the exchange is paused until the restart", p2p.paused() == "test hold" and
      cloud.Cloud.sync.__code__.co_names.count("HOLD") >= 1)
replica.HOLD = ""
js = (ROOT / "app" / "ui" / "backup.js").read_text(encoding="utf-8")
check("В2: the restore confirmation warns about the other computers", "заменят их версии и на других компьютерах" in js
      and "На других компьютерах ничего не изменится" not in js)

# ----------------------------------------------------------------- В15 --
import base64  # noqa: E402

good = os.urandom(5000)
sha = hashlib.sha256(good).hexdigest()
fp = TMP / "files" / "F-1.jpg"
row = {"size": len(good), "sha256": sha}
check("В15: a missing file is missing", not cloud.file_whole(fp, row))
cloud.save_file(fp, good)
check("В15: saved through .part", fp.read_bytes() == good and not (TMP / "files" / "F-1.jpg.part").exists())
check("В15: a whole file is whole", cloud.file_whole(fp, row))
fp.write_bytes(good[:1000])
check("В15: a cut file counts as missing", not cloud.file_whole(fp, row))
fp.write_bytes(b"\x00" * len(good))
check("В15: zeros of the right size count as missing", not cloud.file_whole(fp, row))

P = mk("b15")
import files  # noqa: E402
files.Files(P)
with P.tx() as c:
    c.execute("INSERT INTO patient_files(id, patient_id, ext, size, sha256, deleted) VALUES('F-2', 'P9', '.bin', ?, ?, 0)", (len(good), sha))
node = p2p.Node(P, 0)
pth = p2p._file_path(P.one("SELECT * FROM patient_files WHERE id='F-2'"))
pth.parent.mkdir(parents=True, exist_ok=True)
pth.write_bytes(good[:100])  # a power cut while it was written
try:
    node.on_blob("x", {"sha": sha}, "127.0.0.1")
    check("В15: a damaged file is not given to another computer", False)
except p2p.P2PError as e:
    check("В15: a damaged file is not given to another computer", e.code == 404)
real_call = p2p.call
p2p.call = lambda url, method, payload, **kw: {"data": base64.b64encode(good).decode()}
try:
    node._fetch_files("http://peer")
finally:
    p2p.call = real_call
check("В15: a damaged file is taken again from the other computer", pth.read_bytes() == good)
check("В15: and then given", base64.b64decode(node.on_blob("x", {"sha": sha}, "127.0.0.1")["data"]) == good)

sys.path.insert(0, str(ROOT / "cloud"))
import cloud_server  # noqa: E402
cs = cloud_server.Cloud(str(TMP / "cloudsrv"))
cs._writable = lambda tid, write=True: None
dev = {"tenant_id": "t1"}
bid = "ab" * 32
blob = os.urandom(3000)
try:
    cs.blob_put(dev, bid, blob[:100], hashlib.sha256(blob).hexdigest())
    check("В15: a blob cut on the way is refused", False)
except cloud_server.CloudError:
    check("В15: a blob cut on the way is refused", cs.blob_has(dev, [bid]) == [])
cs.blob_put(dev, bid, blob, hashlib.sha256(blob).hexdigest())
check("В15: a whole blob is kept", cs.blob_get(dev, bid) == blob and cs.blob_has(dev, [bid]) == [bid])
cs.blob_put(dev, bid, os.urandom(3000))
check("В15: a whole blob is never overwritten", cs.blob_get(dev, bid) == blob)
with open(os.path.join(cs._blob_dir("t1"), bid), "wb") as f:
    f.write(blob[:500])  # the server's disk lost the end
check("В15: a damaged blob is reported missing", cs.blob_has(dev, [bid]) == [])
try:
    cs.blob_get(dev, bid)
    check("В15: a damaged blob is not given", False)
except cloud_server.CloudError as e:
    check("В15: a damaged blob is not given", e.code == 404)
cs.blob_put(dev, bid, blob, hashlib.sha256(blob).hexdigest())
check("В15: a damaged blob is replaced by a whole one", cs.blob_get(dev, bid) == blob)

# ----------------------------------------------------------------- В21 --
class Boom(sync.SyncWorker):
    calls = 0

    def sync_once(self, s=None):
        Boom.calls += 1
        if Boom.calls == 1:
            raise RuntimeError("boom")
        self.stop_flag = True
        return True


bw = Boom(mk("b21"))
bw.start()
end = time.time() + 10
while bw.is_alive() and time.time() < end:
    bw.wake.set()
    time.sleep(0.05)
check("В21: the sync loop survives an error and goes on", Boom.calls >= 2 and not bw.is_alive(), Boom.calls)
check("В21: the error is shown", "boom" in (bw.status().get("last_error") or ""), bw.status())


print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
