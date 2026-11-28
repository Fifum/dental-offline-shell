"""3.16 photos of equipment from a phone: the phone sends a photo to the cloud of the stock (the edge function «stock», kind
«equipment_photo»), a laptop syncing takes it into the gallery of the card (the first photo of a card is the main one), the
history says it came from a phone and who took it, then the cloud forgets the photo. Without the network nothing is lost and
nothing is doubled: the photo waits in the cloud, a photo taken in but not confirmed is not added twice, two laptops make one
row of the gallery. A fake cloud in the process with the protocol of cloud/stock/functions/stock/index.ts — no network."""
import base64
import copy
import io
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
import db as dbm  # noqa: E402
import demo  # noqa: E402
import files as filesm  # noqa: E402
import replica  # noqa: E402
import stock_cloud  # noqa: E402
from main import Api  # noqa: E402
from PIL import Image  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:400]}")


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


def jpeg(color, size=(2000, 1500)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "JPEG", quality=80)
    return b.getvalue()


# ------------------------------------------------------------------------------------------------ the fake cloud --
class Fake:
    """dd.push / dd.pull and the photos of dd.photos with the bucket, in memory."""

    def __init__(self):
        self.rows, self.seq, self.devices, self.code = {}, 0, {}, "DDS-TEST-TEST-TEST-TEST"
        self.photos, self.objects = {}, {}
        self.offline = False         # no network at all
        self.fail_done = False       # the answer to /v1/photo_done is lost
        self.no_photos = False       # an old cloud without the routes of the photos
        self.calls = []

    def add_photo(self, eid, data, name="Иванова Анна", role="Медсестра", at="2026-11-28 14:05:31", inv=""):
        """What /p/op «equipment_photo» leaves: the picture in the bucket and its row."""
        pid = f"ph{len(self.photos) + len(self.objects) + 1:04d}{os.urandom(4).hex()}"
        self.objects[f"t1/{pid}.jpg"] = data
        self.photos[pid] = {"id": pid, "equipment_id": eid, "inv_number": inv, "size": len(data), "width": 0, "height": 0,
                            "taken_by": "nurse", "taken_name": name, "taken_role": role, "taken_at": at,
                            "created_at": time.time() + len(self.photos) * 1e-3, "claimed_by": None, "claimed_at": 0,
                            "path": f"t1/{pid}.jpg"}
        return pid

    def handle(self, path, f, token):
        self.calls.append(path)
        if self.offline:
            raise stock_cloud.StockCloudError("Нет связи с облаком склада", -1)
        if path == "/v1/join":
            dev = f"d{len(self.devices) + 1}"
            self.devices[f"tok-{dev}"] = dev
            return {"device": dev, "token": f"tok-{dev}", "tenant": "t1", "name": "Тестовая", "api": 1}
        dev = self.devices.get(token)
        if not dev:
            raise stock_cloud.StockCloudError("Этот компьютер отключён от облака склада", 401)
        if path == "/v1/status":
            return {"tenant": "t1", "name": "Тестовая", "seq": self.seq, "phone_code": "ABCD-EFGH", "device": dev,
                    "devices": [{"id": d, "kind": "laptop"} for d in self.devices.values()], "photos": len(self.photos)}
        if path == "/v1/push":
            acc, rej = [], []
            for c in f["changes"]:
                cur = self.rows.get((c["t"], c["k"]))
                if cur and cur["ver"] == c["ver"]:
                    acc.append([c["t"], c["k"]]); continue
                if (cur["ver"] if cur else None) != c.get("base"):
                    rej.append({"t": c["t"], "k": c["k"], "reason": "conflict"}); continue
                self.seq += 1
                self.rows[(c["t"], c["k"])] = {"t": c["t"], "k": c["k"], "ver": c["ver"], "vv": c["vv"], "row": c["row"],
                                               "pbase": c["pbase"], "pvv": c["pvv"], "origin": c["origin"], "seq": self.seq}
                acc.append([c["t"], c["k"]])
            return {"accepted": acc, "rejected": rej, "seq": self.seq, "skipped": []}
        if path == "/v1/pull":
            rows = sorted((r for r in self.rows.values() if r["seq"] > int(f.get("since") or 0)), key=lambda r: r["seq"])[:500]
            return {"rows": copy.deepcopy(rows), "seq": self.seq, "more": len(rows) >= 500}
        if path == "/v1/staff":
            return {"ok": True, "staff": len(f["staff"])}
        if path.startswith("/v1/photo") and self.no_photos:
            raise stock_cloud.StockCloudError("Не найдено", 404)
        if path == "/v1/photos":
            now, out = time.time(), []
            for p in sorted(self.photos.values(), key=lambda p: p["created_at"]):
                if p["claimed_by"] in (None, dev) or now - p["claimed_at"] > 600:
                    p["claimed_by"], p["claimed_at"] = dev, now
                    out.append({k: v for k, v in p.items() if k not in ("path", "claimed_by", "claimed_at")})
                if len(out) >= min(int(f.get("limit") or 10), 50):
                    break
            return {"photos": out, "waiting": len(self.photos)}
        if path == "/v1/photo":
            p = self.photos.get(f.get("id"))
            if not p:
                raise stock_cloud.StockCloudError("Снимка уже нет в облаке", 404)
            return {"id": p["id"], "data": base64.b64encode(self.objects[p["path"]]).decode()}
        if path == "/v1/photo_done":
            if self.fail_done:
                raise stock_cloud.StockCloudError("Нет связи с облаком склада", -1)
            n = 0
            for i in f.get("ids") or []:
                p = self.photos.pop(i, None)
                if p:
                    self.objects.pop(p["path"], None)
                    n += 1
            return {"done": n}
        raise stock_cloud.StockCloudError("Не найдено", 404)


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
    api = Api(d, W())
    replica.install(d)
    sc = stock_cloud.StockCloud(d, store=Mem(), node=f"n{name}", transport=FakeHttp, files=api._files, stock=api._stock)
    return d, api, sc


A, apiA, ca = laptop("A", True)
B, apiB, cb = laptop("B", False)
check("join A", ca.join(FAKE.code, "A")["ok"])
check("join B", cb.join(FAKE.code, "B")["ok"])
check("A sends its stock", ca.sync()["ok"])
check("B takes it", cb.sync()["ok"] and B.one("SELECT COUNT(*) AS n FROM equipment")["n"] == A.one("SELECT COUNT(*) AS n FROM equipment")["n"] > 0)

pieces = A.q("SELECT id, inv_number, photo_id FROM equipment WHERE status<>'written_off' ORDER BY id")
check("the demo has pieces of equipment", len(pieces) >= 3, len(pieces))
with A.tx() as c:  # cards without photos: the first photo from the phone becomes the main one
    c.execute("UPDATE equipment SET photo_id=NULL")
    c.execute("UPDATE equipment_docs SET deleted=1 WHERE kind='photo'")
ca.sync(); cb.sync()
e1, e2 = pieces[0]["id"], pieces[1]["id"]


def gallery(db_api, eid):
    st = db_api._stock
    return st._eq_gallery(st.db.one("SELECT * FROM equipment WHERE id=?", (eid,)))


# ------------------------------------------------------------------------- a photo is taken in --
p1 = FAKE.add_photo(e1, jpeg((200, 30, 30)), inv=pieces[0]["inv_number"])
r = ca.sync()
check("A synced and took one photo", r["ok"] and r["photos"] == 1, r)
d1 = A.one("SELECT * FROM equipment_docs WHERE id=?", ("EDP-" + p1,))
check("the gallery row has the cloud photo's id", d1 and d1["kind"] == "photo" and d1["equipment_id"] == e1 and not d1["deleted"], d1)
check("…the title and who took it", d1 and d1["title"] == "Фото с телефона" and d1["created_by"] == "Иванова Анна", d1)
f1 = A.one("SELECT * FROM patient_files WHERE id=?", (d1["file_id"],)) if d1 else None
check("the file is a photo of the stock, never of a patient", f1 and f1["patient_id"] == filesm.STOCK_OWNER and f1["kind"] == "photo", f1)
check("…made smaller to 1200 px as a JPEG", f1 and max(f1["width"], f1["height"]) <= 1200 and f1["ext"] == ".jpg", f1)
check("the first photo of the card is the main one", A.one("SELECT photo_id FROM equipment WHERE id=?", (e1,))["photo_id"] == d1["file_id"])
ev = A.one("SELECT * FROM equipment_events WHERE equipment_id=? AND kind='doc' ORDER BY id DESC LIMIT 1", (e1,))
check("the history: from a phone, who took it and when",
      ev and ev["text"] == "Фото с телефона: снял(а) Иванова Анна (Медсестра), 28.11.2026 14:05" and ev["user_name"] == "Иванова Анна", ev)
g = gallery(apiA, e1)
check("the card shows the photo as the main one", len(g) == 1 and g[0]["main"] and g[0]["file_id"] == d1["file_id"], g)
check("the cloud forgot the photo (the row and the picture)", p1 not in FAKE.photos and not FAKE.objects, (FAKE.photos, list(FAKE.objects)))
check("the gallery row went to the cloud before the photo was forgotten",
      FAKE.calls.index("/v1/photo_done") > max(i for i, c in enumerate(FAKE.calls) if c == "/v1/push"))
check("…and is in the cloud", ("equipment_docs", replica.ks(["EDP-" + p1])) in FAKE.rows)
check("A has nothing left to send", ca.pending() == 0, ca.pending())

# a second photo of the same card: in the gallery, not the main one
p2 = FAKE.add_photo(e1, jpeg((30, 30, 200), (900, 1600)), name="Петров Пётр", role="Менеджер склада", at="2026-11-28 15:20:00")
r = ca.sync()
g = gallery(apiA, e1)
check("the second photo is in the gallery, the first stays the main one",
      r["photos"] == 1 and len(g) == 2 and g[0]["file_id"] == d1["file_id"] and g[0]["main"] and not g[1]["main"], g)
ev = A.one("SELECT text FROM equipment_events WHERE equipment_id=? AND kind='doc' ORDER BY id DESC LIMIT 1", (e1,))
check("…with its own photographer", ev and ev["text"] == "Фото с телефона: снял(а) Петров Пётр (Менеджер склада), 28.11.2026 15:20", ev)
f2 = A.one("SELECT width, height FROM patient_files WHERE id=?", (g[1]["file_id"],))
check("an upright photo keeps its shape", f2 and f2["height"] == 1200 and f2["width"] == 675, f2)

# ------------------------------------------------------------------------- without the network --
p3 = FAKE.add_photo(e2, jpeg((20, 160, 60)))
FAKE.offline = True
r = ca.sync()
check("no network: the sync says so", not r["ok"] and ca.state["offline"], (r, ca.state))
check("…and the photo waits in the cloud", p3 in FAKE.photos and not A.one("SELECT 1 AS x FROM equipment_docs WHERE id=?", ("EDP-" + p3,)))
FAKE.offline = False
r = ca.sync()
check("the network is back: the photo is taken", r["ok"] and r["photos"] == 1 and p3 not in FAKE.photos, r)
check("…and it is the main photo of its card", A.one("SELECT photo_id FROM equipment WHERE id=?", (e2,))["photo_id"]
      == A.one("SELECT file_id FROM equipment_docs WHERE id=?", ("EDP-" + p3,))["file_id"])

# the answer to «done» is lost: the next sync does not add the photo again, it only tells the cloud
p4 = FAKE.add_photo(e2, jpeg((240, 200, 20)))
FAKE.fail_done = True
r = ca.sync()
check("taken in, but the cloud was not told", not r["ok"] and p4 in FAKE.photos
      and A.one("SELECT 1 AS x FROM equipment_docs WHERE id=?", ("EDP-" + p4,)), r)
FAKE.fail_done = False
n_docs = A.one("SELECT COUNT(*) AS n FROM equipment_docs WHERE equipment_id=? AND kind='photo' AND deleted=0", (e2,))["n"]
r = ca.sync()
check("the next sync: nothing added twice, the cloud forgets it", r["ok"] and r["photos"] == 0 and p4 not in FAKE.photos
      and A.one("SELECT COUNT(*) AS n FROM equipment_docs WHERE equipment_id=? AND kind='photo' AND deleted=0", (e2,))["n"] == n_docs, r)
check("one line in the history for it", A.one("SELECT COUNT(*) AS n FROM equipment_events WHERE equipment_id=? AND kind='doc' "
                                              "AND text LIKE 'Фото с телефона%'", (e2,))["n"] == 2)

# ------------------------------------------------------------------------- two laptops --
cb.sync()
check("B has the gallery rows of A through the cloud", B.one("SELECT COUNT(*) AS n FROM equipment_docs WHERE id LIKE 'EDP-%' AND deleted=0")["n"] == 4)
# a photo A took in but could not confirm, and A is gone: after its claim B gets it, sees the row and only confirms
p5 = FAKE.add_photo(e1, jpeg((90, 90, 90)))
FAKE.fail_done = True
ca.sync()
FAKE.fail_done = False
check("B does not get a photo claimed by A", cb.sync()["photos"] == 0 and p5 in FAKE.photos and FAKE.photos[p5]["claimed_by"] == "d1")
FAKE.photos[p5]["claimed_at"] -= 3600  # A did not come back for an hour
nb = B.one("SELECT COUNT(*) AS n FROM equipment_docs WHERE equipment_id=? AND kind='photo' AND deleted=0", (e1,))["n"]
r = cb.sync()
check("after the claim B confirms the photo already in the card, adding nothing",
      r["ok"] and r["photos"] == 0 and p5 not in FAKE.photos
      and B.one("SELECT COUNT(*) AS n FROM equipment_docs WHERE equipment_id=? AND kind='photo' AND deleted=0", (e1,))["n"] == nb, r)
check("one row of that photo on both laptops", A.one("SELECT COUNT(*) AS n FROM equipment_docs WHERE id=?", ("EDP-" + p5,))["n"] == 1
      and B.one("SELECT COUNT(*) AS n FROM equipment_docs WHERE id=?", ("EDP-" + p5,))["n"] == 1)
# B takes a photo itself: it is in B's card and comes to A through the cloud
p6 = FAKE.add_photo(e2, jpeg((10, 10, 10), (800, 600)), name="Сидорова Ольга", role="")
r = cb.sync()
check("B takes a photo", r["photos"] == 1 and B.one("SELECT 1 AS x FROM equipment_docs WHERE id=?", ("EDP-" + p6,)))
ev = B.one("SELECT text FROM equipment_events WHERE equipment_id=? ORDER BY id DESC LIMIT 1", (e2,))
check("…without a position the history has just the name", ev and ev["text"] == "Фото с телефона: снял(а) Сидорова Ольга, 28.11.2026 14:05", ev)
ca.sync()
check("A gets B's gallery row", A.one("SELECT equipment_id FROM equipment_docs WHERE id=?", ("EDP-" + p6,))["equipment_id"] == e2)

# ------------------------------------------------------------------------- photos that cannot go into a card --
p7 = FAKE.add_photo("EQ-not-here-yet", jpeg((1, 2, 3)))
gone = pieces[2]["id"]
with A.tx() as c:
    c.execute("UPDATE equipment SET status='written_off' WHERE id=?", (gone,))
p8 = FAKE.add_photo(gone, jpeg((4, 5, 6)))
p9 = FAKE.add_photo(e1, b"\xff\xd8\xff not really a picture" * 10)
p10 = FAKE.add_photo(e1, jpeg((7, 8, 9), (640, 480)))
n_ev = A.one("SELECT COUNT(*) AS n FROM equipment_events WHERE equipment_id=?", (gone,))["n"]
r = ca.sync()
check("a piece not on this computer yet: the photo waits", p7 in FAKE.photos, r)
check("a disposed piece: the photo is dropped, the card is not touched", p8 not in FAKE.photos
      and A.one("SELECT COUNT(*) AS n FROM equipment_events WHERE equipment_id=?", (gone,))["n"] == n_ev
      and not A.one("SELECT 1 AS x FROM equipment_docs WHERE id=?", ("EDP-" + p8,)))
check("a file that is not a picture is dropped without stopping the sync", r["ok"] and p9 not in FAKE.photos
      and not A.one("SELECT 1 AS x FROM equipment_docs WHERE id=?", ("EDP-" + p9,)), r)
check("…and the photo after it is taken", r["photos"] == 1 and A.one("SELECT 1 AS x FROM equipment_docs WHERE id=?", ("EDP-" + p10,)))
check("status: photos waiting in the cloud", ca.state["photos_waiting"] == 1, ca.state)

# ------------------------------------------------------------------------- an old cloud, a note --
FAKE.no_photos = True
r = ca.sync()
check("a cloud without the photo routes: the stock is synced all the same", r["ok"] and r["photos"] == 0, r)
FAKE.no_photos = False
check("photo_note: no date", stock_cloud.photo_note({"taken_by": "boss"}) == "Фото с телефона: снял(а) boss")
check("photo_note: nobody", stock_cloud.photo_note({}) == "Фото с телефона: снял(а) сотрудник")
check("the program gives the laptop its own Files and Stock", apiA._scloud()._files is apiA._files and apiA._scloud()._stock is apiA._stock)

print(f"OK: {OK[0]} FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
