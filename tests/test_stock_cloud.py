"""3.13 the cloud of the stock (stock_cloud.py): two laptops and a fake cloud with the protocol of the edge function «stock»
(cloud/stock/functions/stock/index.ts, the SQL of cloud/stock/schema.sql) — rows go there and back with their versions,
a clash is merged field by field, patients never go there and are never lost, a phone's version comes to the laptops, the
staff with a phone PIN. With DD_STOCK_CLOUD_LIVE=1 and DD_STOCK_CLOUD_CODE=<laptop code of a test clinic> the same is done
against the real cloud (Supabase), with a phone signing in by PIN and sending a request."""
import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
os.environ["DD_STOCK_CLOUD_DEMO"] = "1"  # the laptops of the test have the demo stock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import replica  # noqa: E402
import stock_cloud  # noqa: E402
from main import Api  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:400]}")


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


# ------------------------------------------------------------------------------------------------ the fake cloud --
class Fake:
    """dd.push / dd.pull / dd.write / dd.set_staff of cloud/stock/schema.sql, in memory."""

    def __init__(self):
        self.rows, self.seq, self.staff, self.devices, self.code = {}, 0, [], {}, "DDS-TEST-TEST-TEST-TEST"

    def handle(self, path, f, token):
        if path == "/v1/join":
            if f["code"] != self.code:
                raise stock_cloud.StockCloudError("Код подключения не подходит. Проверьте его.", 403)
            dev = f"d{len(self.devices) + 1}"
            self.devices[f"tok-{dev}"] = dev
            return {"device": dev, "token": f"tok-{dev}", "tenant": "t1", "name": "Тестовая", "api": 1}
        dev = self.devices.get(token)
        if not dev:
            raise stock_cloud.StockCloudError("Этот компьютер отключён от облака склада", 401)
        if path == "/v1/status":
            return {"tenant": "t1", "name": "Тестовая", "seq": self.seq, "phone_code": "ABCD-EFGH", "device": dev,
                    "devices": [{"id": d, "kind": "laptop"} for d in self.devices.values()] + [{"id": "p1", "kind": "phone"}]}
        if path == "/v1/push":
            acc, rej = [], []
            for c in f["changes"]:
                assert c["t"] in stock_cloud.TABLES and isinstance(c["k"], str) and c["k"].startswith("[")
                cur = self.rows.get((c["t"], c["k"]))
                if cur and cur["ver"] == c["ver"]:
                    acc.append([c["t"], c["k"]]); continue
                if (cur["ver"] if cur else None) != c.get("base"):
                    rej.append({"t": c["t"], "k": c["k"], "reason": "conflict"}); continue
                self.seq += 1
                self.rows[(c["t"], c["k"])] = {"t": c["t"], "k": c["k"], "ver": c["ver"], "vv": c["vv"], "row": c["row"],
                                               "pbase": c["pbase"], "pvv": c["pvv"], "origin": (cur or c)["origin"] or c["origin"], "seq": self.seq}
                acc.append([c["t"], c["k"]])
            return {"accepted": acc, "rejected": rej, "seq": self.seq, "skipped": []}
        if path == "/v1/pull":
            lim = min(int(f.get("limit") or 500), 1000)
            rows = sorted((r for r in self.rows.values() if r["seq"] > int(f.get("since") or 0)), key=lambda r: r["seq"])[:lim]
            return {"rows": copy.deepcopy(rows), "seq": self.seq, "more": len(rows) >= lim}
        if path == "/v1/staff":
            self.staff = f["staff"]
            return {"ok": True, "staff": len(self.staff)}
        if path == "/v1/leave":
            self.devices.pop(token, None)
            return {"ok": True}
        raise stock_cloud.StockCloudError("Не найдено", 404)

    def phone_write(self, node, items):
        """dd.write: a phone's operation — new versions made in the cloud on behalf of the phone."""
        for it in items:
            cur = self.rows.get((it["t"], it["k"]))
            if "expect" in it and (cur["ver"] if cur else None) != it["expect"]:
                raise ValueError("changed")
        for it in items:
            cur = self.rows.get((it["t"], it["k"]))
            vv = dict(cur["vv"] or {}) if cur else {}
            n = max(vv.get(node, 0) + 1, int(time.time() * 1000))
            vv[node] = n
            self.seq += 1
            self.rows[(it["t"], it["k"])] = {"t": it["t"], "k": it["k"], "ver": f"{n:015d}.{node}.abcdef", "vv": vv, "row": it["row"],
                                             "pbase": cur["row"] if cur else None, "pvv": cur["vv"] if cur else None,
                                             "origin": cur["origin"] if cur else node, "seq": self.seq}

    def get(self, t, key):
        return self.rows.get((t, replica.ks(key)))


FAKE = Fake()


class FakeHttp:
    def __init__(self, url, token=""):
        self.token = token

    def post(self, path, body=None):
        out = FAKE.handle(path, json.loads(json.dumps(body or {})), self.token)  # through JSON, as on the wire
        return json.loads(json.dumps(out))


class Mem:
    def __init__(self): self.d = {"url": "", "token": "", "device": "", "tenant": "", "name": "", "last_tenant": ""}
    def load(self): return dict(self.d)
    def save(self, x): self.d.update(x)


def laptop(name, with_demo):
    d = dbm.DB(Path(tempfile.mkdtemp()) / f"{name}.db")
    if with_demo:
        demo.ensure_demo(d, force=True)
    Api(d, W())
    auth.Auth(d)
    replica.install(d)
    sc = stock_cloud.StockCloud(d, store=Mem(), node=f"n{name}", transport=FakeHttp)
    return d, sc


def lan(src, dst, node):
    """What the clinic network does: every version of `src` goes to `dst`."""
    replica.stamp(src, "n" + node)
    return replica.apply_versions(dst, replica.changes_since(src, 0, 100000), "x")


A, ca = laptop("A", True)
B, cb = laptop("B", False)

# ------------------------------------------------------------------------- joining --
try:
    ca.join("wrong")
    check("a wrong code is refused", False)
except stock_cloud.StockCloudError as e:
    check("a wrong code is refused", "не подходит" in str(e), e)
check("join A", ca.join(FAKE.code, "A")["ok"] and ca.configured())
check("join B", cb.join(" dds-test-test-test-test ".upper())["ok"])
try:
    ca.join(FAKE.code)
    check("joined twice", False)
except stock_cloud.StockCloudError:
    check("joined twice", True)

# a move with a patient (a write-off in treatment) and a write-off on approval with the patient in its payload
mat = A.one("SELECT id, name FROM materials LIMIT 1")
pid = "pat-test-7731"  # a patient id found nowhere else
with A.tx() as c:
    c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, patient_id, reason, user_name, at) "
              "VALUES(?, -1, 10, 'writeoff', 'W-pat', ?, 'Расход в лечении', 'Тест', '2026-11-27 10:00:00')", (mat["id"], pid))
    payload = {"kind": "consume", "date": "2026-11-27", "time": "", "location_id": "", "patient_id": pid, "patient_name": "Иванов И.",
               "service_id": "", "service_title": "", "reason": "Расход в лечении", "comment": "",
               "lines": [{"material_id": mat["id"], "qty": 1}]}
    c.execute("INSERT INTO stock_approvals(id, kind, status, payload, total, location_id, patient_id, summary, created_by, created_name, "
              "created_at, sent_at, updated_at) VALUES('AP-test1', 'consume', 'pending', ?, 10, '', ?, 'x', 'nurse', 'Медсестра', "
              "'2026-11-27 10:00:00', '2026-11-27 10:00:00', '2026-11-27 10:00:00')", (json.dumps(payload, ensure_ascii=False), pid))
mv_uid = A.one("SELECT uid FROM stock_moves WHERE doc_id='W-pat'")["uid"]
# a nurse with a phone PIN and a doctor without a stock right
with A.tx() as c:
    for login, role, pin in (("nurse", "nurse", "123456"), ("doc", "doctor", "654321"), ("noph", "nurse", None)):
        c.execute("INSERT INTO users(login, name, role, perms, status, created_at, phone_pin_hash, phone_pin_at) "
                  "VALUES(?,?,?,?,'active','2026-11-27',?,?)", (login, login.title(), role,
                  '["schedule_view"]' if login == "doc" else None, auth.hash_password(pin) if pin else None, "2026-11-27" if pin else None))

# ------------------------------------------------------------------------- there --
r = ca.sync()
check("A synced", r["ok"] and r["pushed"] > 10, r)
n_mat = A.one("SELECT COUNT(*) AS n FROM materials")["n"]
check("every material is in the cloud", sum(1 for (t, _k) in FAKE.rows if t == "materials") == n_mat)
check("no table of patients or money goes there", {t for (t, _k) in FAKE.rows} <= set(stock_cloud.TABLES), {t for (t, _k) in FAKE.rows})
cm = FAKE.get("stock_moves", [mv_uid])
check("a move goes without its patient", cm and "patient_id" not in cm["row"] and cm["row"]["material_id"] == mat["id"], cm)
cap = FAKE.get("stock_approvals", ["AP-test1"])
cpl = json.loads(cap["row"]["payload"])
check("a write-off on approval: no patient, the payload keeps empty keys",
      "patient_id" not in cap["row"] and cpl["patient_id"] == "" and cpl["patient_name"] == "" and cpl["lines"][0]["qty"] == 1, cap["row"])
check("nothing of a patient anywhere in the cloud", pid not in json.dumps(list(FAKE.rows.values()), ensure_ascii=False)
      and "Иванов" not in json.dumps(list(FAKE.rows.values()), ensure_ascii=False))
check("the nurse with a PIN is sent, without a PIN or a stock right — not",
      [s["login"] for s in FAKE.staff if s["pin_hash"]] == ["nurse"] and FAKE.staff[[s["login"] for s in FAKE.staff].index("nurse")]["pin_hash"].startswith("pbkdf2$")
      and {s["login"] for s in FAKE.staff if not s["pin_hash"]} >= {"doc", "noph"}
      and all(not s["name"] and not s["perms"] for s in FAKE.staff if not s["pin_hash"]), FAKE.staff)
check("the phone address is written once", A.one("SELECT v FROM stock_settings WHERE k='phone_url'")["v"] == stock_cloud.PHONE_URL)
check("nothing left to send", ca.pending() == 0 and ca.sync()["pushed"] == 0, ca.pending())
st = ca.status()
check("status: the phone code and the devices", st["phone_code"] == "ABCD-EFGH" and st["laptops"] == 2 and st["phones"] == 1 and st["staff"] == 1, st)
ph = ca.phone()
check("QR for phones", ph["url"] == stock_cloud.PHONE_URL + "/j#ABCD-EFGH" and ph["code"] == "ABCD-EFGH", ph)

# ------------------------------------------------------------------------- and back --
r = cb.sync()
check("B took the stock", r["ok"] and B.one("SELECT COUNT(*) AS n FROM materials")["n"] == n_mat, r)
bm = B.one("SELECT * FROM stock_moves WHERE uid=?", (mv_uid,))
check("B has the move, without the patient (it came through the cloud)", bm and bm["patient_id"] is None and bm["qty"] == -1, bm)
check("B sends nothing back of what it took", cb.pending() == 0 and cb.sync()["pushed"] == 0, cb.pending())
replica.stamp(B, "nB")
check("a row without patient_id is not a change of B", B.one("SELECT COUNT(*) AS n FROM sync_dirty")["n"] == 0)
# the clinic network then brings the full copy: the patient is filled in, nothing new goes anywhere
lan(A, B, "A")
bm = B.one("SELECT patient_id FROM stock_moves WHERE uid=?", (mv_uid,))
bap = B.one("SELECT patient_id, payload FROM stock_approvals WHERE id='AP-test1'")
check("the network fills the patient of the move on B", bm["patient_id"] == pid, bm)
check("and of the write-off on approval", bap["patient_id"] == pid and json.loads(bap["payload"])["patient_name"] == "Иванов И.", bap)
check("filling is not a new version", cb.pending() == 0 and B.one("SELECT COUNT(*) AS n FROM sync_dirty")["n"] == 0, cb.pending())

# ------------------------------------------------------------------------- a clash, merged --
mid = mat["id"]
with A.tx() as c:
    c.execute("UPDATE materials SET min_qty=7 WHERE id=?", (mid,))
with B.tx() as c:
    c.execute("UPDATE materials SET unit='уп' WHERE id=?", (mid,))
check("A sends its change", ca.sync()["pushed"] == 1)
r = cb.sync()
check("B: refused, merged, sent", r["ok"] and r["pushed"] == 1, r)
ca.sync()
ra, rb = A.one("SELECT min_qty, unit FROM materials WHERE id=?", (mid,)), B.one("SELECT min_qty, unit FROM materials WHERE id=?", (mid,))
check("both changes are on both laptops", ra["min_qty"] == 7 and ra["unit"] == "уп" and rb["min_qty"] == 7 and rb["unit"] == "уп", (ra, rb))
check("…and the same version", A.one("SELECT ver FROM sync_rows WHERE tbl='materials' AND k=?", (replica.ks([mid]),))["ver"]
      == B.one("SELECT ver FROM sync_rows WHERE tbl='materials' AND k=?", (replica.ks([mid]),))["ver"])

# ------------------------------------------------------------------------- a phone's operation --
cap = FAKE.get("stock_approvals", ["AP-test1"])
row = dict(cap["row"], status="rejected", decided_by="boss", decided_name="Менеджер", answer="Нет на складе", updated_at="2026-11-27 11:00:00")
FAKE.phone_write("pdev1", [{"t": "stock_approvals", "k": cap["k"], "row": row, "expect": cap["ver"]},
                           {"t": "stock_requests", "k": replica.ks(["RQ-ph1"]), "row": {
                               "id": "RQ-ph1", "number": "1", "location_id": "", "need_date": "", "priority": "urgent", "comment": "с телефона",
                               "lines": json.dumps([{"material_id": mid, "qty": 3}]), "issued": "{}", "status": "new", "created_by": "nurse",
                               "created_name": "Nurse", "created_at": "2026-11-27 11:00:00", "sent_at": "2026-11-27 11:00:00",
                               "updated_at": "2026-11-27 11:00:00"}}])
ca.sync()
aap = A.one("SELECT status, answer, patient_id, payload FROM stock_approvals WHERE id='AP-test1'")
check("the phone's decision came to A", aap["status"] == "rejected" and aap["answer"] == "Нет на складе", aap)
check("…and A keeps its patient (field and payload)", aap["patient_id"] == pid and json.loads(aap["payload"])["patient_id"] == pid, aap)
check("the phone's request came to A", (A.one("SELECT status, priority FROM stock_requests WHERE id='RQ-ph1'") or {}).get("priority") == "urgent")
check("A sends nothing back of it", ca.pending() == 0 and ca.sync()["pushed"] == 0)
cb.sync()
check("and to B", (B.one("SELECT status FROM stock_approvals WHERE id='AP-test1'") or {}).get("status") == "rejected")
check("B keeps the patient it got from the network", B.one("SELECT patient_id FROM stock_approvals WHERE id='AP-test1'")["patient_id"] == pid)
# a laptop answers the phone's request: a new version on top of the phone's
with A.tx() as c:
    c.execute("UPDATE stock_requests SET status='accepted', accepted_by='boss' WHERE id='RQ-ph1'")
ca.sync()
check("the laptop's answer is in the cloud", FAKE.get("stock_requests", ["RQ-ph1"])["row"]["status"] == "accepted")

# ------------------------------------------------------------------------- staff changes --
with A.tx() as c:
    c.execute("UPDATE users SET phone_pin_hash=NULL WHERE login='nurse'")
ca.sync()
check("a PIN taken away is said to the cloud", [s["login"] for s in FAKE.staff if s["pin_hash"]] == [] and "nurse" in [s["login"] for s in FAKE.staff], FAKE.staff)

# ------------------------------------------------------------------------- leaving --
check("leave", ca.leave() and not ca.configured() and ca.sync()["ok"] is False)
check("API: the methods have rights", all(m in auth.METHOD_PERMS for m in
      ("stock_cloud_status", "stock_cloud_join", "stock_cloud_leave", "stock_cloud_sync", "stock_cloud_phone")))


# ------------------------------------------------------------------------- the real cloud --
def live():
    import requests
    code = os.environ.get("DD_STOCK_CLOUD_CODE", "")
    P = (os.environ.get("DD_STOCK_CLOUD_URL") or stock_cloud.DEFAULT_URL).rstrip("/")
    L1, c1 = laptop("L1", True)
    L2, c2 = laptop("L2", False)
    c1.transport = c2.transport = stock_cloud.Http
    with L1.tx() as c:
        for login, name, role, pin in (("livenurse", "Медсестра Тест", "nurse", "246810"), ("liveboss", "Менеджер Тест", "stock_manager", "135790"),
                                       ("livedir", "Директор Тест", "director", "975310")):
            c.execute("INSERT INTO users(login, name, role, status, created_at, phone_pin_hash, phone_pin_at) VALUES(?,?,?,'active','2026-11-27',?,'2026-11-27')",
                      (login, name, role, auth.hash_password(pin)))
    check("live: join 1", c1.join(code, "live-1")["ok"])
    check("live: join 2", c2.join(code, "live-2")["ok"])
    r = c1.sync(True)
    check("live: laptop 1 sends the stock", r["ok"] and r["pushed"] > 10, r)
    r = c2.sync(True)
    n = L1.one("SELECT COUNT(*) AS n FROM materials")["n"]
    check("live: laptop 2 takes it", r["ok"] and L2.one("SELECT COUNT(*) AS n FROM materials")["n"] == n, r)
    st = c1.status()
    check("live: the phone code", len(st["phone_code"]) == 9 and st["laptops"] >= 2 and st["staff"] == 3, st)
    if not st["phone_code"]:
        return
    s = requests.Session()
    run = os.urandom(3).hex()  # operation ids are unique per run: the cloud does a repeated id only once

    def post(path, body, hh):
        x = s.post(P + path, json=body, headers=hh, timeout=60)
        return x.status_code, x.json()

    _, h = post("/p/hello", {"code": st["phone_code"].lower().replace("-", " "), "name": "test phone"}, {})
    check("live: the phone is in", h.get("token") and {x["login"] for x in h.get("staff", [])} == {"livenurse", "liveboss", "livedir"}, h)
    if not h.get("token"):
        return
    hd = {"X-DD-Device": h["token"]}
    code_, bad = post("/p/login", {"login": "livenurse", "pin": "000000"}, hd)
    check("live: a wrong PIN is refused", code_ == 403, bad)

    def sign(login, pin):
        _, x = post("/p/login", {"login": login, "pin": pin}, hd)
        return {"X-DD-Session": x.get("session", "")}, x.get("user") or {}

    hs, un = sign("livenurse", "246810")
    check("live: the nurse signs in", un.get("can", {}).get("use") and not un["can"]["direct"] and not un["can"]["approve"], un)
    _, pl = post("/p/pull", {"since": 0}, hs)
    if "rows" not in pl:
        check("live: the phone pulls", False, pl)
        return
    mats = [x for x in pl["rows"] if x["t"] == "materials" and x["row"]]
    check("live: the phone sees the materials", len(mats) == n, len(mats))
    check("live: no patients on the phone", all("patient_id" not in (x["row"] or {}) for x in pl["rows"]))
    check("live: no money of the equipment without Accounting",
          all("price" not in (x["row"] or {}) for x in pl["rows"] if x["t"] == "equipment"))

    def bal(db, mid):
        return round(db.one("SELECT COALESCE(SUM(qty), 0) AS q FROM stock_moves WHERE material_id=? AND COALESCE(location_id, '')=''",
                            (mid,))["q"], 3)

    m0 = max(L1.q("SELECT id FROM materials"), key=lambda m: bal(L1, m["id"]))["id"]
    b0 = bal(L1, m0)
    code_, rq = post("/p/op", {"op": f"lt{run}-req-0001", "kind": "request", "priority": "urgent", "comment": "live",
                               "lines": [{"material_id": m0, "qty": 2}]}, hs)
    check("live: the nurse sends a request", code_ == 200 and rq.get("id", "").startswith("RQ-"), rq)
    _, again = post("/p/op", {"op": f"lt{run}-req-0001", "kind": "request", "lines": [{"material_id": m0, "qty": 2}]}, hs)
    check("live: the same operation twice is done once", again.get("repeated") and again.get("id") == rq.get("id"), again)
    code_, use = post("/p/op", {"op": f"lt{run}-use-0001", "kind": "use", "lines": [{"material_id": m0, "qty": 1}]}, hs)
    check("live: the nurse's use waits for approval", code_ == 200 and use.get("status") == "pending", use)
    code_, no = post("/p/op", {"op": f"lt{run}-dec-0001", "kind": "decide", "id": use.get("id"), "action": "approve"}, hs)
    check("live: a nurse may not approve", code_ == 403, no)
    code_, rc = post("/p/op", {"op": f"lt{run}-rcv-0001", "kind": "receive", "number": "Т-1", "lines": [
        {"material_id": m0, "qty": 5, "price": 100, "lot": "LIVE-L1", "expires": "12.2028"}]}, hs)
    check("live: the nurse receives a delivery", code_ == 200 and rc.get("doc_id", "").startswith("R-"), rc)
    hb, ub = sign("liveboss", "135790")
    check("live: the manager may approve", ub.get("can", {}).get("approve"), ub)
    code_, dc = post("/p/op", {"op": f"lt{run}-dec-0002", "kind": "decide", "id": use.get("id"), "action": "approve"}, hb)
    check("live: the manager approves", code_ == 200, dc)
    code_, ra = post("/p/op", {"op": f"lt{run}-rqa-0001", "kind": "request_accept", "id": rq.get("id")}, hb)
    check("live: the manager accepts the request", code_ == 200, ra)
    hdir, udir = sign("livedir", "975310")
    eq = L1.one("SELECT id FROM equipment WHERE status<>'written_off' LIMIT 1")["id"]
    code_, es = post("/p/op", {"op": f"lt{run}-eqs-0001", "kind": "equipment_set", "id": eq, "condition": "service", "text": "живой тест"}, hdir)
    check("live: the director changes the equipment", code_ == 200 and udir["can"]["money"], es)
    code_, bc = post("/p/op", {"op": f"lt{run}-bar-0001", "kind": "barcode", "id": m0, "barcode": "4600000000017"}, hdir)
    check("live: a barcode is linked", code_ == 200, bc)
    code_, wo = post("/p/op", {"op": f"lt{run}-wro-0001", "kind": "use", "what": "writeoff", "reason": "Брак упаковки",
                               "lines": [{"material_id": m0, "qty": 1}]}, hb)
    check("live: the manager writes off with a reason at once", code_ == 200 and wo.get("status") == "done", wo)
    code_, ev = post("/p/op", {"op": f"lt{run}-eve-0001", "kind": "equipment_event", "id": eq, "event": "service",
                               "text": "ТО живой тест", "next_service": "30.06.2027"}, hdir)
    check("live: a service of the equipment", code_ == 200, ev)
    c1.sync()
    wa = L1.one("SELECT kind, status, doc_id FROM stock_approvals WHERE id=?", (wo.get("id"),)) or {}
    wd = L1.one("SELECT kind, reason FROM stock_docs WHERE id=?", (wa.get("doc_id") or "-",)) or {}
    check("live: the write-off is a write-off with its reason", wa.get("kind") == "writeoff" and wa.get("status") == "done"
          and wd.get("kind") == "writeoff" and wd.get("reason") == "Брак упаковки", (wa, wd))
    evr = L1.one("SELECT kind FROM equipment_events WHERE equipment_id=? AND text='ТО живой тест'", (eq,)) or {}
    check("live: the event is a service and the next service is set", evr.get("kind") == "service"
          and L1.one("SELECT next_service FROM equipment WHERE id=?", (eq,))["next_service"] == "2027-06-30", evr)
    got_in = L1.one("SELECT SUM(qty) AS q FROM stock_moves WHERE doc_id=? AND material_id=?", (rc.get("doc_id"), m0))["q"]
    got_out = L1.one("SELECT SUM(qty) AS q FROM stock_moves WHERE doc_id=? AND material_id=?", ("A-" + str(use.get("id")), m0))["q"]
    check("live: laptop 1 has the delivery and the approved use", got_in == 5 and got_out == -1, (got_in, got_out))
    lot = L1.one("SELECT l.lot, l.expires, m.doc_id FROM stock_lots l JOIN stock_moves m ON m.id=l.move_id WHERE l.lot='LIVE-L1' AND m.doc_id=?",
                 (rc.get("doc_id"),))
    check("live: the lot points to its move", lot and lot["doc_id"] == rc.get("doc_id") and lot["expires"] == "2028-12-31", lot)
    ap = L1.one("SELECT status, doc_id FROM stock_approvals WHERE id=?", (use.get("id"),))
    check("live: the use is approved with its act", ap and ap["status"] == "approved"
          and L1.one("SELECT 1 AS x FROM stock_docs WHERE id=?", (ap["doc_id"],)), ap)
    rq1 = L1.one("SELECT status, accepted_by, created_by FROM stock_requests WHERE id=?", (rq.get("id"),))
    check("live: the request is accepted on laptop 1", rq1 and rq1["status"] == "accepted" and rq1["created_by"] == "livenurse", rq1)
    check("live: the equipment and the barcode", L1.one("SELECT condition FROM equipment WHERE id=?", (eq,))["condition"] == "service"
          and L1.one("SELECT barcode FROM materials WHERE id=?", (m0,))["barcode"] == "4600000000017")
    with L1.tx() as c:
        c.execute("UPDATE stock_requests SET comment='с ноутбука' WHERE id=?", (rq.get("id"),))
    c1.sync()
    _, pl2 = post("/p/pull", {"since": pl["next"]}, hs)
    got = [x for x in pl2["rows"] if x["t"] == "stock_requests" and json.loads(x["k"])[0] == rq.get("id")]
    check("live: the phone sees the laptop's change", got and got[-1]["row"]["comment"] == "с ноутбука",
          ({k: (len(v) if k == "rows" else v) for k, v in pl2.items() if k != "user"}, pl["next"], pl.get("more"), c1.state))
    c2.sync()
    check("live: laptop 2 has everything", bal(L2, m0) == bal(L1, m0)
          and (L2.one("SELECT comment FROM stock_requests WHERE id=?", (rq.get("id"),)) or {}).get("comment") == "с ноутбука")
    check("live: nothing left to send", c1.pending() == 0 and c2.pending() == 0 and c1.sync()["pushed"] == 0, (c1.pending(), c2.pending()))
    for hh in (hs, hb, hdir):
        post("/p/logout", {}, hh)
    code_, _ = post("/p/pull", {"since": 0}, hs)
    check("live: a closed session is refused", code_ == 401)
    post("/p/leave", {}, hd)
    check("live: leave", c1.leave() and c2.leave())


if os.environ.get("DD_STOCK_CLOUD_LIVE") == "1":
    live()

print(f"stock cloud: {OK[0]} ok, {len(FAIL)} failed")
for f in FAIL:
    print("FAIL", f)
sys.exit(1 if FAIL else 0)
