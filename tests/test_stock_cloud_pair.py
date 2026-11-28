"""3.18.3 a phone of one person (stock_cloud.StockCloud.pair, Api.stock_cloud_pair, the routes /v1/pair, /p/pair_info, /p/pair,
/p/login on a bound phone and /p/pin of cloud/stock/functions/stock/index.ts with dd.set_staff of cloud/stock/schema.sql):
«Подключить мой телефон» at the computer gives a one-time QR of that employee; the phone opens it, the person makes up a PIN of
their own (not a weak one) and the phone is theirs — later it opens by that PIN alone; everyone with a right of the stock goes to
the cloud with or without a PIN made at the computer; a PIN reset by the director, a dismissal and the rights taken away
disconnect the bound phones, a stale laptop does not undo a reset, an older laptop's list does not close a bound person; a PIN made
or reset at the computer wakes the worker at once. The fake cloud below follows dd.set_staff and the routes line by line.
With DD_STOCK_CLOUD_LIVE=1 the whole way is walked against the real cloud (Supabase) with a demo clinic made and dropped."""
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
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
import server  # noqa: E402
import stock_cloud  # noqa: E402
from main import Api  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:400]}")


class W:
    def __init__(self): self.n = 0
    def status(self): return {"running": False}
    def trigger(self): self.n += 1


E = stock_cloud.StockCloudError
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
A32 = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def weak(p):  # the rule of index.ts weakPin / app.js weakPin / auth._weak_pin
    return len(set(p)) <= 2 or p in "01234567890123" or p in "98765432109876" or p[:3] == p[3:] or p[:2] * 3 == p


# ------------------------------------------------------------------------------------------------ the fake cloud --
class Fake:
    def __init__(self):
        self.tenants, self.devices, self.keys, self.bodies = {}, {}, {}, []
        self.pairs, self.sessions, self.phones = {}, {}, {}

    def handle(self, path, f, token="", device="", session=""):
        self.bodies.append((path, copy.deepcopy(f)))
        if path.startswith("/p/"):
            return self.phone(path, f, device, session)
        if path == "/v1/register":
            hs = [sha("DDK" + k) for k in f.get("keys") or []]
            t = next((self.keys[h] for h in hs if h in self.keys), None)
            created = False
            if not t:
                if not f.get("create"):
                    return {"tenant": None}
                t = f"t{len(self.tenants) + 1}"
                self.tenants[t] = {"name": ("Демо · " if f.get("demo") else "") + (f.get("clinic") or ""), "demo": bool(f.get("demo")),
                                   "phone": "ABCDEFGH", "staff": {}, "rows": {}, "seq": 0}
                created = True
            for h in hs:
                self.keys[h] = t
            tok = "tok-" + secrets.token_hex(4)
            self.devices[tok] = {"id": "d" + tok[4:], "t": t, "revoked": False}
            return {"device": "d" + tok[4:], "token": tok, "tenant": t, "name": self.tenants[t]["name"],
                    "demo": self.tenants[t]["demo"], "phone_code": "ABCD-EFGH", "api": 1, "created": created}
        d = self.devices.get(token)
        if not d or d["revoked"]:
            raise E("Этот компьютер отключён от облака склада", 401)
        t, x = d["t"], self.tenants[d["t"]]
        if path == "/v1/status":
            devs = [{"id": "d1", "kind": "laptop"}] + [{"id": p["id"], "kind": "phone", "login": p["login"]}
                                                       for p in self.phones.values() if p["t"] == t and not p["revoked"]]
            return {"tenant": t, "name": x["name"], "seq": x["seq"], "phone_code": "ABCD-EFGH", "device": d["id"], "devices": devs,
                    "demo": x["demo"], "photos": 0}
        if path == "/v1/push":
            acc = [[c["t"], c["k"]] for c in f["changes"]]
            return {"accepted": acc, "rejected": [], "seq": x["seq"], "skipped": []}
        if path == "/v1/pull":
            return {"rows": [], "seq": x["seq"], "more": False}
        if path == "/v1/photos":
            return {"photos": [], "waiting": 0}
        if path == "/v1/staff":
            return {"ok": True, "staff": self.set_staff(t, f["staff"], int(f.get("v") or 0) >= 2)}
        if path == "/v1/pair":
            u = x["staff"].get(str(f.get("login") or "").lower())
            if not u or not u["perms"]:
                raise E("У этого сотрудника нет прав склада — телефон не подключить", 403)
            self.pairs = {h: p for h, p in self.pairs.items() if not (p["t"] == t and p["login"] == u["login"] and not p["used"])}
            raw = "".join(secrets.choice(A32) for _ in range(20))
            self.pairs[sha("DDP" + raw)] = {"t": t, "login": u["login"], "used": False, "old": False}
            return {"token": raw, "minutes": 15, "name": u["name"]}
        raise E("Не найдено", 404)

    # dd.set_staff of schema.sql (3.18.3)
    def bound(self, t, login):
        return [p for p in self.phones.values() if p["t"] == t and p["login"] == login and not p["revoked"]]

    def set_staff(self, t, lst, full):
        st, n = self.tenants[t]["staff"], 0
        for u in lst:
            lg, cur = u["login"], st.get(u["login"])
            had, closed = cur is not None, not u.get("perms")
            if closed and not full and self.bound(t, lg):
                continue
            reset = u.get("pin_hash") is None and bool(u.get("pin_at")) and u["pin_at"] > ((cur or {}).get("reset_at") or "")
            if had and cur["pin_hash"] != u.get("pin_hash"):
                for k in [k for k, s in self.sessions.items() if s["t"] == t and s["login"] == lg
                          and not (self.phones[s["dev"]]["login"] == lg and not self.phones[s["dev"]]["revoked"])]:
                    del self.sessions[k]
            if (closed and (not had or cur["perms"])) or (reset and had):
                for k in [k for k, s in self.sessions.items() if s["t"] == t and s["login"] == lg]:
                    del self.sessions[k]
                for p in self.bound(t, lg):
                    p["revoked"] = True
                self.pairs = {h: p for h, p in self.pairs.items() if not (p["t"] == t and p["login"] == lg)}
            st[lg] = {"login": lg, "name": u.get("name") or "", "role_title": u.get("role_title") or "", "perms": list(u.get("perms") or []),
                      "pin_hash": u.get("pin_hash"), "pin_at": u.get("pin_at"),
                      "reset_at": u["pin_at"] if reset else (cur or {}).get("reset_at")}
            n += 1
        for k in [k for k, s in self.sessions.items() if s["t"] == t]:
            s, u = self.sessions[k], st.get(self.sessions[k]["login"])
            p = self.phones[s["dev"]]
            if not u or not u["perms"] or not (u["pin_hash"] or (p["login"] == s["login"] and not p["revoked"])):
                del self.sessions[k]
        return n

    # the phone routes
    def pair_of(self, f):
        raw = re.sub(r"[^A-Z0-9]", "", str(f.get("token") or "").upper())
        p = self.pairs.get(sha("DDP" + raw)) if len(raw) == 20 else None
        if not p:
            raise E("QR-код не подходит. Нажмите на компьютере «Подключить мой телефон» ещё раз.", 403)
        if p["used"] or p["old"]:
            raise E("Этот QR-код уже использован или устарел.", 410)
        u = self.tenants[p["t"]]["staff"].get(p["login"])
        if not u or not u["perms"]:
            raise E("У вашей должности нет доступа к складу", 403)
        return p, u

    def phone(self, path, f, device, session):
        if path == "/p/pair_info":
            p, u = self.pair_of(f)
            return {"clinic": self.tenants[p["t"]]["name"], "demo": self.tenants[p["t"]]["demo"], "name": u["name"],
                    "role_title": u["role_title"], "minutes": 15}
        if path == "/p/pair":
            p, u = self.pair_of(f)
            pin = str(f.get("pin") or "")
            if not re.fullmatch(r"\d{6}", pin):
                raise E("ПИН-код — 6 цифр", 400)
            if weak(pin):
                raise E("Слишком простой ПИН-код (одинаковые цифры или подряд) — придумайте другой", 400)
            p["used"] = True
            dev, ses = "dev-" + secrets.token_hex(4), "ses-" + secrets.token_hex(4)
            self.phones[dev] = {"id": "p" + dev[4:], "t": p["t"], "login": u["login"], "pin": pin, "revoked": False}
            self.sessions[ses] = {"t": p["t"], "dev": dev, "login": u["login"]}
            return {"device": "p" + dev[4:], "token": dev, "session": ses, "login": u["login"], "clinic": self.tenants[p["t"]]["name"],
                    "user": {"login": u["login"], "name": u["name"], "role_title": u["role_title"], "perms": u["perms"]}}
        if path == "/p/login":
            d = self.phones.get(device)
            if not d or d["revoked"]:
                raise E("Телефон отключён от клиники. Подключите его заново: на компьютере «Подключить мой телефон».", 401)
            u = self.tenants[d["t"]]["staff"].get(d["login"])
            if not u or not u["perms"]:
                raise E("У вашей должности больше нет доступа к складу", 403)
            if str(f.get("pin") or "") != d["pin"]:
                raise E("Неверный ПИН-код", 403)
            ses = "ses-" + secrets.token_hex(4)
            self.sessions[ses] = {"t": d["t"], "dev": device, "login": d["login"]}
            return {"session": ses, "user": {"login": u["login"], "name": u["name"]}}
        s = self.sessions.get(session)
        if not s:
            raise E("Войдите по ПИН-коду заново", 401)
        d = self.phones[s["dev"]]
        if path == "/p/me":
            return {"user": {"login": s["login"]}}
        if path == "/p/pin":
            if str(f.get("old") or "") != d["pin"]:
                raise E("Текущий ПИН-код указан неверно", 403)
            if weak(str(f.get("pin") or "")):
                raise E("Слишком простой ПИН-код", 400)
            d["pin"] = str(f["pin"])
            return {"ok": True}
        raise E("Не найдено", 404)


FAKE = Fake()


class FakeHttp:
    def __init__(self, url, token=""):
        self.token = token

    def post(self, path, body=None):
        return json.loads(json.dumps(FAKE.handle(path, json.loads(json.dumps(body or {})), self.token)))


def ph(path, f=None, device="", session=""):
    """A call of the phone: the answer, or the error with its code."""
    try:
        return json.loads(json.dumps(FAKE.handle(path, f or {}, device=device, session=session)))
    except E as e:
        return {"error": str(e), "code": e.code}


class Mem:
    def __init__(self): self.d = {}
    def load(self):
        return {"url": "", "token": "", "device": "", "tenant": "", "name": "", "last_tenant": "", "demo": False, "off": False,
                "demo_key": "", "own_key": "", **self.d}
    def save(self, x): self.d.update(x)


def laptop(name, key, transport=FakeHttp, with_demo=False):
    d = dbm.DB(Path(tempfile.mkdtemp()) / f"{name}.db")
    was = config.load_settings().get("demo")
    if with_demo:
        config.save_settings({"demo": True})
        demo.ensure_demo(d, force=True)
    api = Api(d, W())
    config.save_settings({"demo": was})
    auth.Auth(d)
    replica.install(d)
    sc = stock_cloud.StockCloud(d, store=Mem(), node=f"n{name}", transport=transport, clinic_key=key)
    api._stock_cloud = sc
    return d, sc, api


def people(d, rows):
    with d.tx() as c:
        for login, name, role, pin in rows:
            c.execute("INSERT INTO users(login, name, role, status, created_at, pass_hash, phone_pin_hash, phone_pin_at) "
                      "VALUES(?,?,?,'active','2026-11-27',?,?,?)",
                      (login, name, role, auth.hash_password("pass-" + login), auth.hash_password(pin) if pin else None,
                       "2026-11-27 10:00:00" if pin else None))


def user(d, login):
    return d.one("SELECT * FROM users WHERE login=?", (login,))


config.save_settings({"demo": False, "clinic_name": "Тестовая клиника"})
A, ca, api = laptop("A", secrets.token_bytes(32))
people(A, [("anna", "Анна Петрова", "nurse", None), ("boris", "Борис Иванов", "stock_manager", None),
           ("olga", "Ольга Смирнова", "nurse", "246810"), ("doc", "Доктор Кто", "doctor", None)])
with A.tx() as c:
    c.execute("UPDATE users SET perms=? WHERE login='doc'", ('["schedule_view"]',))
r = ca.connect(create=True)
check("A connects", r["ok"] and ca.configured(), r)

# ------------------------------------------------------------------------- the staff go with their rights --
ca.sync(True)
sent = [b for p, b in FAKE.bodies if p == "/v1/staff"][-1]
by = {s["login"]: s for s in sent["staff"]}
check("the whole list (v 2): everyone with a stock right with the rights, a PIN made at the computer or not",
      sent.get("v") == 2 and by["anna"]["perms"] and by["anna"]["pin_hash"] is None and by["anna"]["name"] == "Анна Петрова"
      and by["olga"]["pin_hash"].startswith("pbkdf2$") and not by["doc"]["perms"] and not by["doc"]["name"], sent)

# ------------------------------------------------------------------------- «Подключить мой телефон» --
FAKE.bodies.clear()
q = ca.pair("ANNA")
paths = [p for p, _ in FAKE.bodies]
check("pair: the staff go up first, then the token", "/v1/staff" in paths and paths.index("/v1/staff") < paths.index("/v1/pair"), paths)
m = re.fullmatch(r"(https://[^#]+)/j#([A-Z0-9]{20})", q["url"])
check("pair: an https link of the phone app with 20 letters (the clinic code is 8)", m and m.group(1) == stock_cloud.PHONE_URL
      and q["qr"].startswith("data:image/png") and q["minutes"] == 15 and q["name"] == "Анна Петрова", q["url"])
tok = m.group(2) if m else ""
try:
    ca.pair("doc")
    check("pair: nobody without a stock right", False)
except E as e:
    check("pair: nobody without a stock right", "прав склада" in str(e), e)

# the Api: for the employee signed in, only
auth.set_current_user(None)
try:
    api.stock_cloud_pair()
    check("Api: the program itself has nobody to bind the phone to", False)
except ValueError as e:
    check("Api: the program itself has nobody to bind the phone to", "под своим именем" in str(e), e)
W0 = W()
api._stock_cloud_worker = W0
auth.set_current_user(user(A, "boris"))
rb = api.stock_cloud_pair()
auth.set_current_user(None)
check("Api: Boris gets his own QR, the worker is woken", rb["name"] == "Борис Иванов" and "/j#" in rb["url"] and W0.n == 1, rb)
check("Api: the method has its rights", "stock_view" in auth.METHOD_PERMS.get("stock_cloud_pair", ()))
tok_b = rb["url"].rsplit("#", 1)[1]

# ------------------------------------------------------------------------- the phone: make up a PIN --
info = ph("/p/pair_info", {"token": tok.lower()})
check("pair_info: the name and the clinic for «Здравствуйте, …!»", info.get("name") == "Анна Петрова" and info.get("clinic"), info)
check("pair_info: a wrong token is refused", ph("/p/pair_info", {"token": "A" * 20}).get("code") == 403)
for bad in ("111111", "123456", "987654", "121212", "123123", "12345", "abcdef"):
    check(f"pair: a weak or wrong PIN {bad} is refused", ph("/p/pair", {"token": tok, "pin": bad}).get("code") == 400)
pa = ph("/p/pair", {"token": tok, "pin": "582014", "name": "iPhone"})
check("pair: the phone is Anna's and signed in", pa.get("login") == "anna" and pa.get("session") and pa.get("token"), pa)
dev_a = pa.get("token")
check("pair: one phone per QR", ph("/p/pair", {"token": tok, "pin": "582014"}).get("code") == 410)
check("the session works", ph("/p/me", session=pa["session"]).get("user", {}).get("login") == "anna")

# later: the PIN alone
check("login on her phone: a wrong PIN", ph("/p/login", {"pin": "000001"}, device=dev_a).get("code") == 403)
lg = ph("/p/login", {"login": "boris", "pin": "582014"}, device=dev_a)
check("login on her phone: her PIN, always as her (another login is ignored)", lg.get("user", {}).get("login") == "anna", lg)
s_a = lg.get("session", "")
check("a new PIN: the old one first", ph("/p/pin", {"old": "111222", "pin": "639047"}, session=s_a).get("code") == 403)
check("a new PIN: not a weak one", ph("/p/pin", {"old": "582014", "pin": "555555"}, session=s_a).get("code") == 400)
check("a new PIN", ph("/p/pin", {"old": "582014", "pin": "639047"}, session=s_a).get("ok"))
check("… the old PIN no longer opens it, the new one does", ph("/p/login", {"pin": "582014"}, device=dev_a).get("code") == 403
      and ph("/p/login", {"pin": "639047"}, device=dev_a).get("session"))

# the second person, on their own phone
pb = ph("/p/pair", {"token": tok_b, "pin": "730581", "name": "Android"})
dev_b = pb.get("token")
check("Boris binds his phone the same way", pb.get("login") == "boris" and ph("/p/login", {"pin": "730581"}, device=dev_b).get("session"), pb)
check("Anna's PIN does not open Boris's phone", ph("/p/login", {"pin": "639047"}, device=dev_b).get("code") == 403)

# the sync keeps bound phones: a minute's list changes nothing, nor does a new PIN made at the computer
ca.sync(True)
s_a = ph("/p/login", {"pin": "639047"}, device=dev_a).get("session")
with A.tx() as c:
    c.execute("UPDATE users SET phone_pin_hash=?, phone_pin_at='2026-11-28 09:00:00' WHERE login='anna'", (auth.hash_password("975310"),))
ca.sync(True)
check("a PIN made at the computer leaves her bound phone and its session", ph("/p/me", session=s_a).get("user")
      and ph("/p/login", {"pin": "639047"}, device=dev_a).get("session"))
st = ca.status()
check("status: the phones and who they are bound to", st["phones"] == 2 and ca.phones_of("anna") == 1 and ca.phones_of("doc") == 0, st)

# an older laptop (3.18.2) sends everybody without a computer PIN as closed: Boris's bound phone stays
x = FAKE.tenants[ca.store.load()["tenant"]]
FAKE.set_staff(ca.store.load()["tenant"], [{"login": "boris", "name": "", "perms": [], "pin_hash": None, "pin_at": ""}], False)
check("an older laptop's list does not close a person with a bound phone", ph("/p/login", {"pin": "730581"}, device=dev_b).get("session")
      and x["staff"]["boris"]["perms"])

# ------------------------------------------------------------------------- the director resets the PIN --
a = auth.Auth(A)
director = {"id": 0, "login": "dir", "name": "Директор", "role": "director"}
a.staff_phone_pin_reset(director, user(A, "anna")["id"])
ua = user(A, "anna")
check("the reset keeps its time (no hash)", ua["phone_pin_hash"] is None and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", ua["phone_pin_at"] or ""), ua)
ca.sync(True)
check("the reset disconnects her bound phone and its sessions", ph("/p/login", {"pin": "639047"}, device=dev_a).get("code") == 401
      and ph("/p/me", session=s_a).get("code") == 401)
check("… Boris's phone stays", ph("/p/login", {"pin": "730581"}, device=dev_b).get("session"))
q2 = ca.pair("anna")
p2 = ph("/p/pair", {"token": q2["url"].rsplit("#", 1)[1], "pin": "480162"})
check("after the reset she binds again with a new PIN", p2.get("login") == "anna", p2)
dev_a2 = p2.get("token")
# a laptop that has not heard of the reset sends the older time — nothing happens
FAKE.set_staff(ca.store.load()["tenant"], [{**by["anna"], "pin_hash": None, "pin_at": "2026-11-27 10:00:00"}], True)
ca.sync(True)
check("a stale laptop and the same list again do not undo the new binding", ph("/p/login", {"pin": "480162"}, device=dev_a2).get("session"))

# ------------------------------------------------------------------------- a dismissal, the rights taken away --
with A.tx() as c:
    c.execute("UPDATE users SET status='blocked' WHERE login='boris'")
ca.sync(True)
check("a dismissal disconnects his phone", ph("/p/login", {"pin": "730581"}, device=dev_b).get("code") == 401)
with A.tx() as c:
    c.execute("UPDATE users SET perms=? WHERE login='anna'", (json.dumps({"perms": ["schedule_view"], "known": auth.PERM_KEYS}),))
ca.sync(True)
check("the rights of the stock taken away disconnect hers", ph("/p/login", {"pin": "480162"}, device=dev_a2).get("code") == 401)
try:
    ca.pair("anna")
    check("… and no new QR for her", False)
except E:
    check("… and no new QR for her", True)

# ------------------------------------------------------------------------- the server wakes the worker --
srv = server.ClinicServer.__new__(server.ClinicServer)
W1 = W()
srv.api, srv.db, srv.auth = type("Api", (), {"_stock_cloud_worker": W1})(), A, auth.Auth(A)
with A.tx() as c:
    c.execute("UPDATE users SET role='director', perms=NULL, status='active' WHERE login='olga'")
t_o = srv.call_auth("login", ["olga", "pass-olga"], "", "127.0.0.1", "test", True)["token"]
pin = srv.call_auth("phone_pin_new", ["pass-olga"], t_o, "127.0.0.1", "test", True)
check("a PIN made at the computer wakes the worker", len(pin["pin"]) == 6 and W1.n == 1, W1.n)
srv.call_auth("staff_phone_pin_reset", [user(A, "olga")["id"]], t_o, "127.0.0.1", "test", True)
check("a PIN reset wakes it", W1.n == 2, W1.n)
u = srv.auth.public_user(user(A, "olga"))
srv.call_auth("staff_save", [{"id": u["id"], "name": u["name"], "role": "director", "status": "active"}], t_o, "127.0.0.1", "test", True)
check("a change of an employee wakes it", W1.n == 3, W1.n)
check("no worker (tests, startup): nothing breaks", server.ClinicServer._stock_kick(type("S", (), {"api": None})(), 5) == 5)

# ------------------------------------------------------------------------- one rule for a weak PIN --
src_ts = (ROOT / "cloud/stock/functions/stock/index.ts").read_text(encoding="utf-8")
src_ph = (ROOT / "phone/app.js").read_text(encoding="utf-8")
node = shutil.which("node")
if node:
    fn_ts = re.search(r"function weakPin\(pin: string\): boolean \{\n  return (.+?);\n\}", src_ts, re.S).group(1)
    fn_ph = re.search(r"const weakPin = \(p\) => (.+?);\n", src_ph).group(1)
    pins = ["111111", "123456", "987654", "121212", "123123", "112211", "582014", "639047", "012345", "890123", "000000", "135790"]
    js = (f"const a=(pin)=>{fn_ts};const b=(p)=>{fn_ph};"
          f"console.log(JSON.stringify({json.dumps(pins)}.map(x=>[a(x),b(x)])))")
    got = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30).stdout)
    want = [auth._weak_pin(p) for p in pins]
    check("a weak PIN: the cloud, the phone and the program agree", [g[0] for g in got] == want and [g[1] for g in got] == want, (got, want))

# ------------------------------------------------------------------------- the screens --
ui = (ROOT / "app/ui/stock-phone.js").read_text(encoding="utf-8")
pf = (ROOT / "app/ui/platform.js").read_text(encoding="utf-8")
sf = (ROOT / "app/ui/staff.js").read_text(encoding="utf-8")
check("the tab: «Подключить мой телефон» first, the clinic QR folded", "stock_cloud_pair" in ui and "Подключить мой телефон" in ui
      and "Общий QR-код клиники" in ui and "sp-clinic" in ui)
check("the profile: the same button", 'spMyPhoneHtml("pfPairBox")' in pf and "spBindMyPhone(box" in pf)
check("«Сотрудники»: the reset disconnects the phones", "Сбросить ПИН и отключить телефоны" in sf)
check("the phone: the personal QR, make up and repeat the PIN, a bound phone asks the PIN alone",
      "function viewPair" in src_ph and "code.length === 20" in src_ph and "Придумайте ПИН-код из 6 цифр" in src_ph
      and "Повторите ПИН-код" in src_ph and "const bound = () =>" in src_ph and '"/p/pin"' in src_ph and "это ваш телефон" in src_ph)
css = (ROOT / "phone/styles.css").read_text(encoding="utf-8")
html = (ROOT / "phone/index.html").read_text(encoding="utf-8")
check("the phone looks like the program: its red, no teal left, the bar follows the theme",
      "--accent:#D9262B" in css and "--accent:#DC3439" in css and not re.search(r"167C76|0E4F52|4FC5B8", css + html)
      and 'content="#111316" media="(prefers-color-scheme: dark)"' in html)
check("the cloud: the routes and the migration", all(x in src_ts for x in ('case "/v1/pair"', 'case "/p/pair_info"', 'case "/p/pair"',
                                                                            'case "/p/pin"', "makePin(pin)")))
sch = (ROOT / "cloud/stock/schema.sql").read_text(encoding="utf-8")
check("the schema: bound phones, one-time tokens, the full list", "create table if not exists dd.pairs" in sch
      and "p_full boolean default false" in sch and "drop function if exists dd.set_staff(text, jsonb)" in sch)


# ------------------------------------------------------------------------- the real cloud --
def live():
    import requests
    url = (os.environ.get("DD_STOCK_CLOUD_URL") or stock_cloud.DEFAULT_URL).rstrip("/")
    config.save_settings({"demo": True})
    L, c, _ = laptop("L", secrets.token_bytes(32), transport=stock_cloud.Http, with_demo=True)
    people(L, [("live-anna", "Анна Тест", "nurse", None), ("live-boris", "Борис Тест", "stock_manager", None)])
    r = c.connect(create=True)
    check("live: a demo clinic", r["ok"] and r["created"] and r["demo"], r)
    check("live: the stock goes up", c.sync(True)["ok"])

    def post(path, body, **h):
        q = requests.post(url + path, json=body, headers={k.replace("_", "-"): v for k, v in h.items()}, timeout=30)
        try:
            return q.status_code, q.json()
        except ValueError:
            return q.status_code, {}

    try:
        qa = c.pair("live-anna")
        ta = qa["url"].rsplit("#", 1)[1]
        check("live: Anna's QR", re.fullmatch(r"[A-Z0-9]{20}", ta) and qa["url"].startswith(stock_cloud.PHONE_URL + "/j#"), qa["url"])
        code, info = post("/p/pair_info", {"token": ta})
        check("live: pair_info", code == 200 and info.get("name") == "Анна Тест" and info.get("demo"), info)
        code, bad = post("/p/pair", {"token": ta, "pin": "123456"})
        check("live: a weak PIN is refused", code == 400 and "простой" in bad.get("error", ""), bad)
        code, pa = post("/p/pair", {"token": ta, "pin": "582014", "name": "test"})
        check("live: Anna's phone is bound and signed in", code == 200 and pa.get("login") == "live-anna" and pa.get("session"), pa)
        dev = pa.get("token", "")
        code, _ = post("/p/pair", {"token": ta, "pin": "582014"})
        check("live: one phone per QR", code == 410, code)
        code, me = post("/p/me", {}, X_DD_Session=pa.get("session", ""))
        check("live: her session", code == 200 and me["user"]["login"] == "live-anna" and me["user"]["can"]["use"], me)
        code, _ = post("/p/login", {"pin": "000001"}, X_DD_Device=dev)
        check("live: a wrong PIN", code == 403, code)
        code, lg = post("/p/login", {"login": "live-boris", "pin": "582014"}, X_DD_Device=dev)
        check("live: her PIN alone, as her", code == 200 and lg["user"]["login"] == "live-anna", lg)
        code, np_ = post("/p/pin", {"old": "582014", "pin": "639047"}, X_DD_Session=lg.get("session", ""))
        check("live: a new PIN", code == 200 and np_.get("ok"), np_)
        code, _ = post("/p/login", {"pin": "582014"}, X_DD_Device=dev)
        code2, _ = post("/p/login", {"pin": "639047"}, X_DD_Device=dev)
        check("live: the old PIN is gone, the new one opens", code == 403 and code2 == 200, (code, code2))
        qb = c.pair("live-boris")
        code, pb = post("/p/pair", {"token": qb["url"].rsplit("#", 1)[1], "pin": "730581", "name": "test-2"})
        check("live: Boris binds his own phone", code == 200 and pb.get("login") == "live-boris", pb)
        devb = pb.get("token", "")
        c.sync(True)
        code, _ = post("/p/login", {"pin": "639047"}, X_DD_Device=dev)
        check("live: the minute's sync keeps the bound phones", code == 200, code)
        st = c.status()
        check("live: the cloud tells whose the phones are", c.phones_of("live-anna") == 1 and c.phones_of("live-boris") == 1, st)
        a = auth.Auth(L)
        a.staff_phone_pin_reset({"id": 0, "login": "dir", "name": "Директор", "role": "director"}, user(L, "live-anna")["id"])
        c.sync(True)
        code, _ = post("/p/login", {"pin": "639047"}, X_DD_Device=dev)
        check("live: the reset disconnects her phone", code == 401, code)
        code, _ = post("/p/login", {"pin": "730581"}, X_DD_Device=devb)
        check("live: … not his", code == 200, code)
        with L.tx() as cx:
            cx.execute("UPDATE users SET status='blocked' WHERE login='live-boris'")
        c.sync(True)
        code, _ = post("/p/login", {"pin": "730581"}, X_DD_Device=devb)
        check("live: a dismissal disconnects his", code == 401, code)
    finally:
        c.leave()
        q = requests.post(url + "/p/pair_info", json={"token": "Z" * 20}, timeout=20)
        check("live: the demo clinic is gone with its tokens", q.status_code in (403, 429), q.status_code)
        config.save_settings({"demo": False})


if os.environ.get("DD_STOCK_CLOUD_LIVE") == "1":
    live()

print(f"stock cloud pair: {OK[0]} ok, {len(FAIL)} failed")
for f in FAIL:
    print("FAIL", f)
sys.exit(1 if FAIL else 0)
