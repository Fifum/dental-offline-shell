"""3.18.2 the cloud of the stock without a code (stock_cloud.py, /v1/register of cloud/stock/functions/stock/index.ts with
dd.register and dd.bind_keys of cloud/stock/schema.sql): the tab «Телефон» of a fresh computer connects it and shows the QR
(an https link the ordinary camera of a phone opens); the other computers of the clinic network join the same clinic of the
cloud by themselves and see the same operations; a computer outside the network joins by a code a connected one makes; the
director's «Отключить» is not undone by itself; the demo stock goes to a demo clinic of its own and that connection ends when
the program leaves the demo; a real connection is never used in the demo; the provider's DDS codes keep working.
With DD_STOCK_CLOUD_LIVE=1 the same is done against the real cloud (Supabase): a demo clinic is made and dropped, a phone
connects by its QR code, and a second computer with the same secret comes into the same clinic."""
import base64
import copy
import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
os.environ.pop("DD_STOCK_CLOUD_DEMO", None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import config  # noqa: E402
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


E = stock_cloud.StockCloudError
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731


# ------------------------------------------------------------------------------------------------ the fake cloud --
class Fake:
    """The laptop routes of the edge function with dd.register / dd.bind_keys / dd.push / dd.pull, in memory."""

    def __init__(self):
        self.tenants, self.devices, self.keys, self.invites, self.bodies = {}, {}, {}, {}, []
        self.provider = "DDS-PROV-IDER-CODE-AAAA"
        self.t_old = self._tenant("Клиника по коду", False, join=self.provider)

    def _tenant(self, name, demo_, join=None):
        t = f"t{len(self.tenants) + 1}"
        self.tenants[t] = {"name": name, "demo": demo_, "phone": secrets.token_hex(4).upper(), "rows": {}, "seq": 0, "staff": [],
                           "join": sha("".join(ch for ch in join.upper() if ch.isalnum())) if join else None}
        return t

    def laptops(self, t):
        return [d for d in self.devices.values() if d["t"] == t and d["kind"] == "laptop" and not d["revoked"]]

    def bind(self, t, hs):
        for h in hs:
            cur = self.keys.get(h)
            if cur is None or (cur != t and not self.laptops(cur)):
                self.keys[h] = t

    def hashes(self, f):
        return [sha("DDK" + k) for k in f.get("keys") or []]

    def new_laptop(self, t, f):
        tok = "tok-" + secrets.token_hex(4)
        self.devices[tok] = {"id": "d" + tok[4:], "t": t, "kind": "laptop", "revoked": False, "name": f.get("name")}
        x = self.tenants[t]
        return {"device": "d" + tok[4:], "token": tok, "tenant": t, "name": x["name"], "demo": x["demo"],
                "phone_code": x["phone"][:4] + "-" + x["phone"][4:], "api": 1}

    def handle(self, path, f, token):
        self.bodies.append((path, copy.deepcopy(f)))
        if path == "/v1/register":
            hs = self.hashes(f)
            assert hs and all(len(k) >= 40 for k in f["keys"]), f
            found = sorted({self.keys[h] for h in hs if h in self.keys}, key=lambda t: not self.laptops(t))
            created = False
            if found:
                t = found[0]
            elif not f.get("create"):
                return {"tenant": None}
            else:
                t = self._tenant(("Демо · " if f.get("demo") else "") + (f.get("clinic") or ""), bool(f.get("demo")))
                created = True
            if self.tenants[t]["demo"] != bool(f.get("demo")):
                raise E("Демо-склад и настоящий склад не смешиваются", 409)
            self.bind(t, hs)
            return {**self.new_laptop(t, f), "created": created}
        if path == "/v1/join":
            h = sha("".join(ch for ch in f["code"].upper() if ch.isalnum()))
            t = next((k for k, x in self.tenants.items() if x["join"] == h), None) or self.invites.get(h)
            if not t:
                raise E("Код подключения не подходит или устарел. Проверьте его.", 403)
            if self.tenants[t]["demo"] != bool(f.get("demo")):
                raise E("demo", 409)
            self.bind(t, self.hashes(f))
            return self.new_laptop(t, f)
        d = self.devices.get(token)
        if not d or d["revoked"]:
            raise E("Этот компьютер отключён от облака склада. Подключите его заново.", 401)
        t, x = d["t"], self.tenants[d["t"]]
        if path == "/v1/status":
            self.bind(t, self.hashes(f))
            devs = [{"id": v["id"], "kind": v["kind"]} for v in self.devices.values() if v["t"] == t and not v["revoked"]]
            return {"tenant": t, "name": x["name"], "seq": x["seq"], "phone_code": x["phone"][:4] + "-" + x["phone"][4:],
                    "device": d["id"], "devices": devs, "demo": x["demo"], "photos": 0}
        if path == "/v1/invite":
            raw = secrets.token_hex(6).upper()
            self.invites[sha("DDS" + raw)] = t
            return {"code": f"DDS-{raw[:4]}-{raw[4:8]}-{raw[8:]}", "hours": 24}
        if path == "/v1/leave":
            d["revoked"] = True
            if x["demo"] and not self.laptops(t):
                del self.tenants[t]
                self.keys = {h: v for h, v in self.keys.items() if v != t}
            return {"ok": True}
        if path == "/v1/push":
            acc, rej = [], []
            for c in f["changes"]:
                cur = x["rows"].get((c["t"], c["k"]))
                if cur and cur["ver"] == c["ver"]:
                    acc.append([c["t"], c["k"]]); continue
                if (cur["ver"] if cur else None) != c.get("base"):
                    rej.append({"t": c["t"], "k": c["k"], "reason": "conflict"}); continue
                x["seq"] += 1
                x["rows"][(c["t"], c["k"])] = {"t": c["t"], "k": c["k"], "ver": c["ver"], "vv": c["vv"], "row": c["row"],
                                               "pbase": c["pbase"], "pvv": c["pvv"], "origin": (cur or c)["origin"] or c["origin"], "seq": x["seq"]}
                acc.append([c["t"], c["k"]])
            return {"accepted": acc, "rejected": rej, "seq": x["seq"], "skipped": []}
        if path == "/v1/pull":
            lim = min(int(f.get("limit") or 500), 1000)
            rows = sorted((r for r in x["rows"].values() if r["seq"] > int(f.get("since") or 0)), key=lambda r: r["seq"])[:lim]
            return {"rows": copy.deepcopy(rows), "seq": x["seq"], "more": len(rows) >= lim}
        if path == "/v1/staff":
            x["staff"] = f["staff"]
            return {"ok": True, "staff": len(f["staff"])}
        if path == "/v1/photos":
            return {"photos": [], "waiting": 0}
        raise E("Не найдено", 404)


FAKE = Fake()


class FakeHttp:
    def __init__(self, url, token=""):
        self.token = token

    def post(self, path, body=None):
        return json.loads(json.dumps(FAKE.handle(path, json.loads(json.dumps(body or {})), self.token)))


class Mem:
    def __init__(self): self.d = {}
    def load(self):
        return {"url": "", "token": "", "device": "", "tenant": "", "name": "", "last_tenant": "", "demo": False, "off": False,
                "demo_key": "", "own_key": "", **self.d}
    def save(self, x): self.d.update(x)


def laptop(name, key, with_demo=False):
    d = dbm.DB(Path(tempfile.mkdtemp()) / f"{name}.db")
    was = config.load_settings().get("demo")
    if with_demo:  # the demo stock as test data (the demo setting only while it is made: Api seeds the stock)
        config.save_settings({"demo": True})
        demo.ensure_demo(d, force=True)
    Api(d, W())
    config.save_settings({"demo": was})
    auth.Auth(d)
    replica.install(d)
    sc = stock_cloud.StockCloud(d, store=Mem(), node=f"n{name}", transport=FakeHttp, clinic_key=key)
    return d, sc


def worker(sc):
    w = stock_cloud.StockCloudWorker.__new__(stock_cloud.StockCloudWorker)
    w.cloud = sc
    return w


def tenant_of(sc):
    return sc.store.load()["tenant"]


def materials(d):
    return d.one("SELECT COUNT(*) AS n FROM materials")["n"]


config.save_settings({"demo": False, "clinic_name": "Тестовая клиника"})
K1, K2, K3 = secrets.token_bytes(32), secrets.token_bytes(32), secrets.token_bytes(32)

# ------------------------------------------------------------------------- the secret --
s1 = stock_cloud.clinic_secret(K1)
check("the secret: the same for the same key, another for another key",
      s1 == stock_cloud.clinic_secret(K1) and s1 != stock_cloud.clinic_secret(K2) and len(s1) == 43, s1)
check("the secret tells nothing of the key", base64.b64encode(K1).decode() not in s1 and K1.hex() not in s1)

# ------------------------------------------------------------------------- a fresh computer: the QR at once --
A, ca = laptop("A", K1, with_demo=True)
B, cb = laptop("B", K1)
r = ca.connect(create=True)
check("A connects with no code and makes the clinic", r["ok"] and r["created"] and ca.configured(), r)
st = ca.status()
check("the phone code is known at once", len(st["phone_code"]) == 9 and st["configured"] and not st["demo"], st)
p = ca.phone()
check("the QR is an https link of the phone app with the clinic code (the ordinary camera opens it)",
      p["url"].startswith("https://") and p["url"].endswith("/j#" + st["phone_code"]) and p["qr"].startswith("data:image/png"), p["url"])
sent = [b for path, b in FAKE.bodies if path == "/v1/register"]
check("the raw key of the clinic never goes to the cloud",
      all(base64.b64encode(K1).decode() not in json.dumps(b) and K1.hex() not in json.dumps(b) for b in sent))
check("A sends its stock", ca.sync(True)["ok"] and materials(A) > 5)
check("connecting again does nothing", ca.connect()["already"])

# ------------------------------------------------------------------------- another computer of the network --
check("B is not connected before the worker asks", not cb.configured())
worker(cb).step()
check("B (the same network) joins the same clinic by itself", cb.configured() and tenant_of(cb) == tenant_of(ca), (tenant_of(cb), tenant_of(ca)))
check("… and has A's stock", materials(B) == materials(A), (materials(B), materials(A)))
mid = A.one("SELECT id FROM materials LIMIT 1")["id"]
with B.tx() as c:
    c.execute("UPDATE materials SET name='Изменено на B' WHERE id=?", (mid,))
cb.sync()
ca.sync()
check("A sees what B did", A.one("SELECT name FROM materials WHERE id=?", (mid,))["name"] == "Изменено на B")
check("both laptops are counted", ca.status()["laptops"] == 2 if ca.refresh_status() else False)
check("the worker asks again only after a while", cb.next_auto > time.time() + 3600)

# ------------------------------------------------------------------------- a computer outside the network --
C, cc = laptop("C", K2)
worker(cc).step()
check("C (another key) does not join by itself and makes nothing", not cc.configured() and len(FAKE.tenants) == 2, FAKE.tenants.keys())
check("without the director a clinic is not made", cc.connect(create=False) == {"ok": False, "none": True})
inv = ca.invite()
check("a code for another computer", inv["code"].startswith("DDS-") and len(inv["code"]) == 18, inv)
r = cc.join(inv["code"])
check("C joins A's clinic by the code", r["ok"] and tenant_of(cc) == tenant_of(ca))
D, cd = laptop("D", K2)
worker(cd).step()
check("D (C's network) then joins the same clinic by itself", tenant_of(cd) == tenant_of(ca), tenant_of(cd))
try:
    cc.join(inv["code"])
    check("joined twice", False)
except E:
    check("joined twice", True)

# ------------------------------------------------------------------------- a computer that made a clinic of its own --
Ee, ce = laptop("E", K3)
r = ce.connect(create=True)
own = tenant_of(ce)
check("E made a clinic of its own", r["created"] and own != tenant_of(ca))
r = ce.join(ca.invite()["code"], switch=True)
check("E goes over to A's clinic by a code", r["ok"] and tenant_of(ce) == tenant_of(ca) and not FAKE.laptops(own))
ce.sync(True)
F, cf = laptop("F", K3)
worker(cf).step()
check("F (E's network) comes to A's clinic too, not to the one E left", tenant_of(cf) == tenant_of(ca), (tenant_of(cf), own))
try:
    ce.join("DDS-WRON-GCOD-EXXX", switch=True)
    check("a wrong code keeps the old connection", False)
except E:
    check("a wrong code keeps the old connection", ce.configured() and tenant_of(ce) == tenant_of(ca))

# ------------------------------------------------------------------------- the director disconnects --
phone_code = ca.status()["phone_code"]
ca.leave()
check("disconnected", not ca.configured() and ca.status()["off"])
ca.next_auto = 0
worker(ca).step()
check("a disconnected computer does not connect by itself", not ca.configured())
api = Api(A, W())
api._stock_cloud = ca
check("the tab says it is off", api.stock_cloud_connect() == {"ok": False, "off": True})
r = api.stock_cloud_connect(True)
check("«Подключить снова» — the same clinic, the same QR for the phones", r["ok"] and ca.status()["phone_code"] == phone_code, r)

# ------------------------------------------------------------------------- not the director --
G, cg = laptop("G", secrets.token_bytes(32))
apig = Api(G, W())
apig._stock_cloud = cg
auth.set_current_user({"id": 99, "login": "nurse", "role": "nurse", "perms": "[]"})
try:
    check("a nurse's tab does not make a clinic", apig.stock_cloud_connect() == {"ok": False, "none": True} and not cg.configured())
    try:
        apig.stock_cloud_invite()
        check("a nurse makes no code", False)
    except ValueError:
        check("a nurse makes no code", True)
finally:
    auth.set_current_user(None)
check("the director's tab makes it", apig.stock_cloud_connect()["ok"] and cg.configured())

# ------------------------------------------------------------------------- the demo --
config.save_settings({"demo": True})
H, ch = laptop("H", K1, with_demo=True)
r = ch.connect(create=True)
check("in the demo: a demo clinic of its own, not the clinic of its network", r["ok"] and r["demo"] and tenant_of(ch) != tenant_of(ca)
      and FAKE.tenants[tenant_of(ch)]["demo"] and FAKE.tenants[tenant_of(ch)]["name"].startswith("Демо"), r)
check("the demo QR", ch.status()["demo"] and ch.phone()["url"].startswith("https://"))
check("the demo stock goes there", ch.sync(True)["ok"] and len(FAKE.tenants[tenant_of(ch)]["rows"]) > 5)
for what, fn in (("no code for other computers in the demo", ch.invite), ("no joining by a code in the demo", lambda: ch.join(FAKE.provider))):
    try:
        fn()
        check(what, False)
    except E:
        check(what, True)
demo_t = tenant_of(ch)
# a real computer while the program shows the demo: its connection is not used
pushed_before = FAKE.tenants[tenant_of(ca)]["seq"]
with A.tx() as c:
    c.execute("UPDATE materials SET name='Демо не должно уйти' WHERE id=?", (mid,))
r = ca.sync()
check("a real connection is never synced in the demo", r["ok"] is False and not ca.configured()
      and FAKE.tenants[tenant_of(cb)]["seq"] == pushed_before, r)
config.save_settings({"demo": False})
st = ch.status()
check("leaving the demo ends the demo connection, the demo clinic goes", not st["configured"] and demo_t not in FAKE.tenants and not st["off"], st)
worker(ch).step()
check("… and the real stock connects by itself to the clinic of the network", ch.configured() and tenant_of(ch) == tenant_of(cb)
      and not ch.store.load()["demo"], tenant_of(ch))
worker(ca).step()
check("A comes back by itself too", ca.configured() and tenant_of(ca) == tenant_of(cb))

# ------------------------------------------------------------------------- the provider's code (before 3.18.2) --
I, ci = laptop("I", secrets.token_bytes(32))
r = ci.join(FAKE.provider.lower())
check("a DDS code of the provider still works", r["ok"] and tenant_of(ci) == FAKE.t_old)
ci.sync(True)
J, cj = laptop("J", ci._clinic_key)
worker(cj).step()
check("the network of a computer joined by the provider's code comes to that clinic by itself", tenant_of(cj) == FAKE.t_old)

check("API: the new methods have rights", auth.METHOD_PERMS.get("stock_cloud_invite") == "settings"
      and "stock_view" in auth.METHOD_PERMS.get("stock_cloud_connect", ()))
ui = (ROOT / "app" / "ui" / "stock-phone.js").read_text(encoding="utf-8")
check("the tab: no code field before the QR, the PIN as in the profile",
      "stock_cloud_connect" in ui and "«Телефон: склад и сканер» → «Создать ПИН»" in ui and "ПИН для телефона" not in ui)
ph = (ROOT / "phone" / "app.js").read_text(encoding="utf-8")
check("the phone: one screen for who and the PIN, the same words for the PIN",
      "function viewWho" not in ph and "«Телефон: склад и сканер» → «Создать ПИН»" in ph and "ПИН для телефона" not in ph)


# ------------------------------------------------------------------------- the real cloud --
def live():
    import requests
    url = (os.environ.get("DD_STOCK_CLOUD_URL") or stock_cloud.DEFAULT_URL).rstrip("/")
    config.save_settings({"demo": True})
    key = secrets.token_bytes(32)
    L1, c1 = laptop("L1", key, with_demo=True)
    c1.transport = stock_cloud.Http
    r = c1.connect(create=True)
    check("live: a demo clinic is made with no code", r["ok"] and r["created"] and r["demo"], r)
    st = c1.status()
    check("live: its phone code", len(st["phone_code"]) == 9, st)
    check("live: the demo stock goes up", c1.sync(True)["ok"])
    q = requests.post(url + "/p/hello", json={"code": st["phone_code"], "name": "test"}, timeout=20)
    check("live: a phone connects by the code of the QR", q.status_code == 200 and q.json()["clinic"].startswith("Демо"), q.text[:200])
    dev = q.json().get("token", "")
    L2, c2 = laptop("L2", key)
    c2.transport = stock_cloud.Http
    c2.store.save({"demo_key": c1.store.load()["demo_key"]})  # the same demo secret: the same clinic
    r2 = c2.connect(create=False)
    check("live: a computer with the same secret comes into the same clinic", r2["ok"] and not r2["created"]
          and tenant_of(c2) == tenant_of(c1), r2)
    check("live: it sees the stock", c2.sync(True)["ok"] and materials(L2) == materials(L1), (materials(L2), materials(L1)))
    L3, c3 = laptop("L3", key)
    c3.transport = stock_cloud.Http
    check("live: an unknown secret makes nothing without «create»", c3.connect(create=False) == {"ok": False, "none": True})
    try:
        c1.invite()
        check("live: no codes in the demo", False)
    except E:
        check("live: no codes in the demo", True)
    requests.post(url + "/p/leave", headers={"X-DD-Device": dev}, json={}, timeout=20)
    c2.leave()
    c1.leave()
    q = requests.post(url + "/p/hello", json={"code": st["phone_code"], "name": "test"}, timeout=20)
    check("live: the demo clinic its last laptop left is gone", q.status_code == 403, q.text[:200])
    config.save_settings({"demo": False})


if os.environ.get("DD_STOCK_CLOUD_LIVE") == "1":
    live()

print(f"stock cloud register: {OK[0]} ok, {len(FAIL)} failed")
for f in FAIL:
    print("FAIL", f)
sys.exit(1 if FAIL else 0)
