"""3.19: the stock app of a phone on the clinic's Wi-Fi, straight to this computer, without the internet (phone_lan.py, server.py
/s/, clinic_ca.py). Over real HTTP and HTTPS on this computer: the files of the app under /s/ and their config, the PIN of a
bound phone (checked against the cloud's copy) and of an unbound one (users.phone_pin_hash), the pause after 5 wrong PINs, the
operations through the program's own methods with the rights of the computer's own staff, a repeat done once, the filters of
/p/pull, a phone the computer does not know yet (409, the app keeps itself), the certificate of the clinic (the chain, the Name
Constraints, the addresses, a new one when the address changes) and https that gives only /s/. Then stock_cloud: a photo of a
material from the cloud into the card, the phones' list from the cloud, the address of this computer for the cloud app."""
import base64
import hashlib
import io
import json
import os
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth as authm  # noqa: E402
import clinic_ca  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import phone_lan  # noqa: E402
import server as srvm  # noqa: E402
import stock_cloud  # noqa: E402
from main import Api  # noqa: E402
from PIL import Image  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:500]}")


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


def free_port():
    """A port whose +2 (https for the phones) is free too."""
    for _ in range(50):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
        try:
            t = socket.socket(); t.bind(("127.0.0.1", p + 2)); t.close()
            return p
        except OSError:
            continue
    raise RuntimeError("no free ports")


def jpeg(color=(200, 30, 30), size=(1200, 900)):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "JPEG", quality=80)
    return base64.b64encode(b.getvalue()).decode()


d = dbm.DB(); demo.ensure_demo(d, force=True)
api = Api(d, W())
PORT = free_port()
srv = srvm.ClinicServer(api, d, port=PORT, host="127.0.0.1").start()
BASE = f"http://127.0.0.1:{PORT}"
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731


def get(path, base=BASE, ctx=None):
    req = urllib.request.Request(base + path, method="GET")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), NoRedirect) if ctx else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def P(name, body=None, dev="", sess="", base=BASE, ctx=None):
    h = {"Content-Type": "application/json"}
    if dev:
        h["X-DD-Device"] = dev
    if sess:
        h["X-DD-Session"] = sess
    req = urllib.request.Request(f"{base}/s/api/p/{name}", data=json.dumps(body or {}).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# ------------------------------------------------------------------------------------------------ the staff --
with d.tx() as c:
    for login, name, role in (("director", "Анна Директор", "director"), ("nurse", "Ольга Медсестра", "nurse"),
                              ("manager", "Пётр Менеджер", "stock_manager"), ("keeper", "Иван Кладовщик", "storekeeper"),
                              ("doctor", "Мария Врач", "assistant")):
        c.execute("INSERT INTO users(login, name, position, role, pass_hash, status, created_at, approved_at) VALUES(?,?,?,?,?,?,?,?)",
                  (login, name, "", role, authm.hash_password("secret1"), "active", "2026-11-28 10:00:00", "2026-11-28 10:00:00"))
    c.execute("UPDATE users SET phone_pin_hash=?, phone_pin_at=? WHERE login='nurse'", (authm.hash_password("135792"), "2026-11-28 10:00:00"))
cab = api.stock_location_save({"name": "Кабинет 1"})
cab = cab if isinstance(cab, str) else (cab or {}).get("id") or d.one("SELECT id FROM stock_locations WHERE name='Кабинет 1'")["id"]
mats = [r["id"] for r in d.q("SELECT id FROM materials WHERE active=1 ORDER BY id LIMIT 3")]
eq = d.one("SELECT id, inv_number FROM equipment WHERE status<>'written_off' ORDER BY id LIMIT 1")

# the cloud's list of the phones (/v1/phones): a bound phone of the manager, a bound one of the storekeeper, an unbound one,
# a disconnected one
TOK = {"man": "tok-manager-phone-000001", "keep": "tok-keeper-phone-0000002", "free": "tok-unbound-phone-000003", "old": "tok-revoked-phone-00004"}
PINS = {"man": "482915", "keep": "604817"}
n = phone_lan.store_devices(d, [
    {"id": "dev-man", "name": "iPhone", "login": "Manager", "pin_hash": authm.hash_password(PINS["man"]), "token_hash": sha(TOK["man"]), "revoked": False},
    {"id": "dev-keep", "name": "Android", "login": "keeper", "pin_hash": authm.hash_password(PINS["keep"]), "token_hash": sha(TOK["keep"]), "revoked": False},
    {"id": "dev-free", "name": "Android", "login": "", "pin_hash": "", "token_hash": sha(TOK["free"]), "revoked": False},
    {"id": "dev-old", "name": "Телефон", "login": "nurse", "pin_hash": authm.hash_password("111222"), "token_hash": sha(TOK["old"]), "revoked": True},
])
check("the cloud's phones are copied", n == 4 and d.one("SELECT COUNT(*) AS n FROM phone_local_devices")["n"] == 4, n)
check("…the login is kept in lower case", d.one("SELECT login FROM phone_local_devices WHERE id='dev-man'")["login"] == "manager")

# ------------------------------------------------------------------------------------------------ the files --
code, body, h = get("/s/")
html = body.decode("utf-8", "ignore")
check("/s/ gives the app", code == 200 and "Склад клиники" in html, code)
check("…its files under /s/", 'src="/s/app.js"' in html and 'href="/s/styles.css"' in html and 'src="/s/config.js"' in html
      and 'href="/s/manifest.webmanifest"' in html and '="/app.js' not in html, html[:600])
check("…with its own CSP and no-cache", "default-src 'self'" in h.get("Content-Security-Policy", "") and h.get("Cache-Control") == "no-cache", h)
code, body, h = get("/s")
check("/s → /s/", code == 302 and h.get("Location") == "/s/", (code, h))
for p in ("/s/e/00001", "/s/m/МТ-0001".encode("utf-8").decode("latin-1") if False else "/s/m/MT-0001", "/s/j"):
    code, body, _ = get(p)
    check(f"{p} is the app's page", code == 200 and b"/s/app.js" in body, code)
code, body, _ = get("/s/config.js")
cfg = body.decode()
check("config.js: the API is this computer", code == 200 and 'location.origin + "/s/api"' in cfg and "DD_LOCAL = true" in cfg
      and 'DD_BASE = "/s/"' in cfg and "DD_SECURE = false" in cfg and "DD_HTTPS_PORT = 0" in cfg and "DD_CLOUD_APP" in cfg, cfg)
code, body, _ = get("/s/manifest.webmanifest")
man = json.loads(body)
check("the manifest under /s/", man["start_url"] == "/s/" and man["scope"] == "/s/" and man["icons"][0]["src"].startswith("/s/icons/"), man)
code, body, _ = get("/s/app.js")
check("app.js served", code == 200 and b"takeLink" in body and b"material_photo" in body, code)
code, body, _ = get("/s/sw.js")
check("sw.js served (its base from its own place)", code == 200 and b"self.location.pathname" in body, code)
for bad in ("/s/vercel.json", "/s/deploy.ps1", "/s/dev_server.py", "/s/make_icons.py", "/s/.vercel/project.json",
            "/s/../app/main.py", "/s/%2e%2e/app/main.py", "/s/nothing.js"):
    code, _, _ = get(bad)
    check(f"{bad} is not given", code == 404, code)
code, body, _ = get("/s/ca")
check("/s/ca while the scanner mode is off: says who turns it on", code == 200 and "Со сканером" in body.decode() and "Зачем устанавливать сертификат клиники" in body.decode(), code)
code, _, _ = get("/s/ca.crt")
check("…and no certificate", code == 404, code)

# ------------------------------------------------------------------------------------------------ sign-in --
code, r = P("hello", {"code": "ABCD-EFGH"})
check("connecting by the clinic code needs the internet", code == 400 and "интернет" in r.get("error", ""), (code, r))
code, r = P("pair", {"token": "X" * 20, "pin": "482915"})
check("…and so does the personal QR", code == 400, (code, r))
code, r = P("staff", {}, dev="tok-unknown-phone-0000009")
check("a phone this computer does not know: 409, not 401 (the app keeps itself)", code == 409 and "ещё не получил" in r.get("error", ""), (code, r))
code, r = P("staff", {})
check("no device: 401", code == 401, (code, r))
code, r = P("login", {"pin": "111222"}, dev=TOK["old"])
check("a disconnected phone: 401", code == 401 and "отключён" in r.get("error", ""), (code, r))

code, r = P("staff", {}, dev=TOK["man"])
check("a bound phone: no list of staff, says whose it is", code == 200 and r["staff"] == [] and r["bound"] == "manager" and r["local"], r)
code, r = P("login", {"login": "director", "pin": PINS["man"]}, dev=TOK["man"])
check("the bound phone signs in as its owner whatever login is sent", code == 200 and r["user"]["login"] == "manager", (code, r))
MAN = r.get("session", "")
u = r.get("user") or {}
check("…me(): the rights of this computer, local", u.get("local") and u["can"]["approve"] and u["can"]["direct"] and u["can"]["photo_mat"]
      and not u["can"]["photo"] and not u["can"]["money"] and r.get("hours") == 12, u)
code, r = P("me", {}, sess=MAN)
check("/p/me", code == 200 and r["user"]["login"] == "manager", (code, r))
code, r = P("login", {"pin": "000000"}, dev=TOK["man"])
check("a wrong PIN", code == 403 and r.get("error") == "Неверный ПИН-код", (code, r))

code, r = P("staff", {}, dev=TOK["free"])
check("an unbound phone: those with a PIN made at this computer", code == 200 and [x["login"] for x in r["staff"]] == ["nurse"] and r["bound"] is None, r)
code, r = P("login", {"login": "nurse", "pin": "135792"}, dev=TOK["free"])
check("…the nurse signs in with the PIN of the computer", code == 200 and r["user"]["login"] == "nurse", (code, r))
NUR = r.get("session", "")
nu = r.get("user") or {}
check("…the nurse's rights", nu["can"]["use"] and not nu["can"]["direct"] and not nu["can"]["approve"] and nu["can"]["equipment"]
      and not nu["can"]["equipment_edit"] and nu["can"]["photo_mat"], nu)
code, r = P("login", {"login": "doctor", "pin": "135792"}, dev=TOK["free"])
check("…someone without a PIN cannot", code == 403, (code, r))

# five wrong PINs: a pause of 15 minutes for the phone
for i in range(5):
    code, r = P("login", {"pin": "999999"}, dev=TOK["keep"])
check("the fifth wrong PIN", code == 403, (code, r))
code, r = P("login", {"pin": PINS["keep"]}, dev=TOK["keep"])
check("…then even the right one waits", code == 429 and "Подождите" in r.get("error", ""), (code, r))
with d.tx() as c:
    c.execute("DELETE FROM phone_local_fails")
code, r = P("login", {"pin": PINS["keep"]}, dev=TOK["keep"])
check("after the pause the storekeeper signs in", code == 200 and r["user"]["can"]["photo"] and r["user"]["can"]["barcode"], (code, r))
KEEP = r.get("session", "")
code, r = P("pin", {"old": PINS["keep"], "pin": "582047"}, sess=KEEP)
check("changing the PIN needs the internet", code == 400 and "интернет" in r.get("error", ""), (code, r))

# ------------------------------------------------------------------------------------------------ operations --
oid = lambda: "op" + os.urandom(10).hex()  # noqa: E731
bal = lambda mid, loc="": d.one("SELECT COALESCE(SUM(qty),0) AS q FROM stock_moves WHERE material_id=? AND COALESCE(location_id,'')=?", (mid, loc))["q"]  # noqa: E731
q0 = bal(mats[0])
op1 = oid()
rec = {"op": op1, "kind": "receive", "location_id": "", "number": "Н-19", "lines": [{"material_id": mats[0], "qty": "10", "price": "50", "lot": "L19", "expires": "2027-12-31"}]}
code, r = P("op", rec, sess=MAN)
check("receive by the manager", code == 200 and r.get("message") == "Поставка принята" and bal(mats[0]) == q0 + 10, (code, r, bal(mats[0])))
code, r2 = P("op", rec, sess=MAN)
check("…sent again: done once", code == 200 and r2.get("repeated") and bal(mats[0]) == q0 + 10, (code, r2))
j = d.one("SELECT * FROM audit WHERE action LIKE '%(телефон)%' ORDER BY id DESC LIMIT 1")
check("…the journal says it came from a phone, and who", j and j["action"] == "Приход на склад (телефон)" and j["user_name"] == "Пётр Менеджер"
      and j["ip"] == "127.0.0.1", j)
check("…once for the two copies", d.one("SELECT COUNT(*) AS n FROM audit WHERE action='Приход на склад (телефон)'")["n"] == 1)

code, r = P("op", {"op": oid(), "kind": "use", "location_id": "", "lines": [{"material_id": mats[0], "qty": 2}]}, sess=NUR)
check("the nurse's use waits for approval", code == 200 and r.get("status") == "pending" and bal(mats[0]) == q0 + 10, (code, r))
ap = r.get("id")
code, r = P("op", {"op": oid(), "kind": "decide", "id": ap, "action": "approve"}, sess=NUR)
check("…the nurse cannot approve", code == 403, (code, r))
code, r = P("op", {"op": oid(), "kind": "decide", "id": ap, "action": "approve"}, sess=MAN)
check("…the manager approves: written off", code == 200 and bal(mats[0]) == q0 + 8, (code, r, bal(mats[0])))
code, r = P("op", {"op": oid(), "kind": "use", "what": "writeoff", "reason": "Брак", "location_id": "", "lines": [{"material_id": mats[0], "qty": 1}]}, sess=MAN)
check("a write-off by the manager: at once", code == 200 and r.get("status") == "done" and bal(mats[0]) == q0 + 7, (code, r))
mv = d.one("SELECT kind, reason FROM stock_moves WHERE material_id=? ORDER BY rowid DESC LIMIT 1", (mats[0],))
check("…as a write-off with its reason", mv and mv["kind"] == "writeoff" and mv["reason"] == "Брак", mv)

code, r = P("op", {"op": oid(), "kind": "request", "location_id": cab, "priority": "urgent", "lines": [{"material_id": mats[1], "qty": 3}]}, sess=NUR)
check("the nurse's request", code == 200 and r.get("number"), (code, r))
rq_n = r.get("id")
code, r = P("op", {"op": oid(), "kind": "request", "location_id": cab, "lines": [{"material_id": mats[2], "qty": 1}]}, sess=MAN)
rq_m = r.get("id")
check("the manager's request", code == 200 and rq_m, (code, r))
code, r = P("op", {"op": oid(), "kind": "request_accept", "id": rq_n}, sess=NUR)
check("…the nurse cannot accept requests", code == 403, (code, r))
code, r = P("op", {"op": oid(), "kind": "request_accept", "id": rq_n}, sess=MAN)
check("…the manager accepts it", code == 200 and d.one("SELECT status FROM stock_requests WHERE id=?", (rq_n,))["status"] == "accepted", (code, r))
P("op", {"op": oid(), "kind": "receive", "location_id": "", "lines": [{"material_id": mats[1], "qty": "5"}]}, sess=MAN)
code, r = P("op", {"op": oid(), "kind": "transfer", "from_id": "", "to_id": cab, "request_ids": [rq_n], "lines": [{"material_id": mats[1], "qty": 3}]}, sess=MAN)
check("a transfer to the cabinet by the request", code == 200 and bal(mats[1], cab) == 3, (code, r, bal(mats[1], cab)))
check("…the request is issued", d.one("SELECT status FROM stock_requests WHERE id=?", (rq_n,))["status"] == "done",
      d.one("SELECT status, issued FROM stock_requests WHERE id=?", (rq_n,)))

code, r = P("op", {"op": oid(), "kind": "barcode", "id": mats[2], "barcode": "4600000000193"}, sess=MAN)
check("a barcode bound", code == 200 and d.one("SELECT barcode FROM materials WHERE id=?", (mats[2],))["barcode"] == "4600000000193", (code, r))
other = d.one("SELECT barcode FROM materials WHERE id=?", (mats[1],))["barcode"]
code, r = P("op", {"op": oid(), "kind": "barcode", "id": mats[2], "barcode": other}, sess=MAN)
check("…a barcode of another material is refused", code == 400 and "уже указан" in r.get("error", ""), (code, r))
code, r = P("op", {"op": oid(), "kind": "barcode", "id": mats[2], "barcode": "4600000000209"}, sess=NUR)
check("…the nurse cannot bind barcodes", code == 403, (code, r))

op_e = oid()
code, r = P("op", {"op": op_e, "kind": "equipment_photo", "id": eq["id"], "data": jpeg(), "taken_at": "2026-11-28 12:00:00"}, sess=KEEP)
dd = d.one("SELECT * FROM equipment_docs WHERE id=?", ("EDP-" + op_e,))
check("a photo of equipment into its card", code == 200 and dd and dd["kind"] == "photo" and not dd["deleted"], (code, r, dd))
code, r = P("op", {"op": oid(), "kind": "equipment_photo", "id": eq["id"], "data": jpeg()}, sess=MAN)
check("…the manager has no right of equipment", code == 403, (code, r))
op_m = oid()
had_photo = d.one("SELECT photo_id FROM materials WHERE id=?", (mats[0],))["photo_id"]
code, r = P("op", {"op": op_m, "kind": "material_photo", "id": mats[0], "data": jpeg((30, 30, 200)), "taken_at": "2026-11-28 12:05:00"}, sess=NUR)
md = d.one("SELECT * FROM material_docs WHERE id=?", ("MDP-" + op_m,))
check("a photo of a material by the nurse into its card", code == 200 and md and md["kind"] == "photo" and md["material_id"] == mats[0]
      and "Ольга Медсестра" in (md["title"] or "") and md["created_by"] == "Ольга Медсестра", (code, r, md))
f = d.one("SELECT * FROM patient_files WHERE id=?", (md["file_id"],)) if md else None
check("…the file is the stock's, not a patient's", f and f["kind"] == "photo" and f["ext"] == ".jpg", f)
now_photo = d.one("SELECT photo_id FROM materials WHERE id=?", (mats[0],))["photo_id"]
check("…the first photo of a material is its main one, a later one is not", now_photo == (had_photo or (md or {}).get("file_id")), (had_photo, now_photo))
code, r = P("op", {"op": op_m, "kind": "material_photo", "id": mats[0], "data": jpeg((30, 30, 200))}, sess=NUR)
check("…sent again: one photo", code == 200 and r.get("repeated") and d.one("SELECT COUNT(*) AS n FROM material_docs WHERE id LIKE 'MDP-%'")["n"] == 1, (code, r))
code, r = P("op", {"op": oid(), "kind": "material_photo", "id": "nope", "data": jpeg()}, sess=NUR)
check("…of an unknown material: 404", code == 404, (code, r))
code, r = P("op", {"op": oid(), "kind": "material_photo", "id": mats[0], "data": ""}, sess=NUR)
check("…without a picture: refused", code == 400 and "снимка" in r.get("error", "").lower(), (code, r))
code, r = P("op", {"op": "bad op!", "kind": "receive"}, sess=MAN)
check("a broken op id", code == 400, (code, r))
code, r = P("op", {"op": oid(), "kind": "drop_table"}, sess=MAN)
check("an unknown operation", code == 400, (code, r))

# ------------------------------------------------------------------------------------------------ /p/pull --
def pull_all(sess):
    rows, since = {}, 0
    for _ in range(50):
        code, r = P("pull", {"since": since}, sess=sess)
        assert code == 200, (code, r)
        for x in r["rows"]:
            rows[(x["t"], x["k"])] = x["row"]
        since = r["next"]
        if not r["more"]:
            return rows, r
    return rows, r


rows_n, last = pull_all(NUR)
reqs = [v for (t, _), v in rows_n.items() if t == "stock_requests" and v]
check("the nurse sees only her own requests", reqs and all(x["created_by"] == "nurse" for x in reqs), [(x["created_by"], x["number"]) for x in reqs])
eqs = [v for (t, _), v in rows_n.items() if t == "equipment" and v]
check("…the equipment without its money", eqs and not any("price" in x for x in eqs), sorted(eqs[0]) if eqs else eqs)
check("…the material photo's row is there (the phone's preview turns «в карточке»)", any(t == "material_docs" and v and v.get("id") == "MDP-" + op_m for (t, _), v in rows_n.items()))
check("…no tables of patients or users", not {t for t, _ in rows_n} - set(stock_cloud.TABLES), {t for t, _ in rows_n})
check("…and the user with it", last["user"]["login"] == "nurse")
rows_m, _ = pull_all(MAN)
check("the manager sees all requests", {x["created_by"] for (t, _), x in rows_m.items() if t == "stock_requests" and x} >= {"nurse", "manager"})
check("…the equipment without money for the manager too (no right of accounting)",
      not any("price" in x for (t, _), x in rows_m.items() if t == "equipment" and x))
code, r = P("pull", {"since": 10 ** 9}, sess=MAN)
check("pull from the end: nothing", code == 200 and r["rows"] == [] and r["next"] == 10 ** 9, r)

# ------------------------------------------------------------------------------------------------ rights change at once --
with d.tx() as c:
    c.execute("UPDATE users SET status='blocked' WHERE login='nurse'")
code, r = P("me", {}, sess=NUR)
check("a dismissed nurse: her session ends (401)", code == 401, (code, r))
code, r = P("login", {"login": "nurse", "pin": "135792"}, dev=TOK["free"])
check("…and she cannot sign in", code == 403, (code, r))
with d.tx() as c:
    c.execute("UPDATE users SET status='active' WHERE login='nurse'")
code, r = P("logout", {}, sess=MAN)
code, r = P("me", {}, sess=MAN)
check("logout ends the session", code == 401, (code, r))
code, r = P("login", {"pin": PINS["man"]}, dev=TOK["man"])
MAN = r.get("session", "")
check("signed in again", P("me", {}, sess=MAN)[0] == 200)
code, r = P("leave", {}, dev=TOK["man"])
code2, r2 = P("me", {}, sess=MAN)
check("leave: the phone's sessions here end", code == 200 and r.get("ok") and code2 == 401, (code, r, code2, r2))
check("…the phone stays known (it is disconnected only in the cloud)", d.one("SELECT revoked FROM phone_local_devices WHERE id='dev-man'")["revoked"] == 0)
phone_lan.store_devices(d, [{"id": "dev-keep", "name": "Android", "login": "keeper", "pin_hash": authm.hash_password(PINS["keep"]), "token_hash": sha(TOK["keep"])}])
check("a phone the cloud no longer lists is disconnected here", d.one("SELECT revoked FROM phone_local_devices WHERE id='dev-man'")["revoked"] == 1)
code, r = P("me", {}, sess=KEEP)
check("…the other one keeps working", code == 200, (code, r))
code, r = P("login", {"pin": PINS["man"]}, dev=TOK["man"])
check("…the disconnected one cannot sign in", code == 401, (code, r))

# ------------------------------------------------------------------------------------------------ the clinic's certificate --
x509 = clinic_ca._x509()[0]
tmp = Path(tempfile.mkdtemp())
ca = clinic_ca.ClinicCA(tmp / "ca", password="test-password")
made = ca.ensure_server(["192.168.1.14", "26.90.93.2", "10.0.0.7"])
root = ca.ca_cert()
nc = root.extensions.get_extension_for_class(x509.NameConstraints)
check("the root: Name Constraints, critical", nc.critical and any(str(x.value) == "192.168.0.0/16" for x in nc.value.permitted_subtrees)
      and any(x.value == "local" for x in nc.value.permitted_subtrees), nc)
bc = root.extensions.get_extension_for_class(x509.BasicConstraints)
check("…a CA that signs no other CA", bc.critical and bc.value.ca and bc.value.path_length == 0)
addrs, names = ca.server_names()
check("the computer's certificate: its private addresses and 127.0.0.1, no VPN address", made and addrs == ["10.0.0.7", "127.0.0.1", "192.168.1.14"], addrs)
check("…<name>.local and localhost, not the bare name", names and all(n == "localhost" or n.endswith(".local") for n in names), names)
check("…397 days", (ca.server_cert().not_valid_after_utc - ca.server_cert().not_valid_before_utc).days in (396, 397))
check("the same addresses: no new certificate", ca.ensure_server(["10.0.0.7", "192.168.1.14"]) is False)
check("a new address: a new certificate", ca.ensure_server(["192.168.0.33"]) is True and ca.server_names()[0] == ["127.0.0.1", "192.168.0.33"], ca.server_names())
key_pem = (tmp / "ca" / "ca.key").read_text()
check("the keys are kept encrypted", "ENCRYPTED" in key_pem)
check("the mobileconfig for an iPhone: a root payload", b"com.apple.security.root" in ca.mobileconfig())
check("the title fits 64 bytes", len(ca.title().encode()) <= 64 and ca.title().startswith("Склад клиники"), ca.title())
st = ca.state()
check("state: fingerprint in groups", st["ca"] and len(st["short"]) == 19 and st["fingerprint"].startswith(st["short"].replace(" ", "")), st)
ca2 = clinic_ca.ClinicCA(tmp / "ca", password="wrong")
try:
    ca2._load_key("ca.key")
    FAIL.append("a wrong password must not open the key")
except (ValueError, TypeError):
    OK[0] += 1

# ------------------------------------------------------------------------------------------------ https «со сканером» --
w = api.phone_wifi_state()
check("phone_wifi_state: off at first", not w["full"] and not w["want_full"] and w["https"] == "" and w["ca_qr"] == "", w)
w = api.phone_wifi_full(True)
check("«Со сканером» turned on", w["full"] and w["want_full"] and srv.httpsd is not None and w["ca"]["ca"], w)
SBASE = f"https://127.0.0.1:{srv.https_port}"
cactx = ssl.create_default_context(cadata=clinic_ca.get().ca_pem().decode())
code, body, h = get("/s/", base=SBASE, ctx=cactx)
check("https with the clinic's certificate verifies and gives the app", code == 200 and b"/s/app.js" in body, code)
code, body, _ = get("/s/config.js", base=SBASE, ctx=cactx)
check("…its config says secure", b"DD_SECURE = true" in body, body[:300])
code, body, _ = get("/s/config.js")
check("the http config knows where the scanner mode is", f"DD_HTTPS_PORT = {srv.https_port}".encode() in body, body)
code, body, h = get("/", base=SBASE, ctx=cactx)
check("https: the program itself is not there (→ /s/)", code == 302 and h.get("Location") == "/s/", (code, h))
code, body, h = get("/ping", base=SBASE, ctx=cactx)
check("…nor /ping", code == 302, code)
req = urllib.request.Request(SBASE + "/api/day", data=b"[]", headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req, timeout=10, context=cactx) as r_:
        c_ = r_.status
except urllib.error.HTTPError as e:
    c_ = e.code
check("…nor its API", c_ == 404, c_)
code, r = P("login", {"pin": PINS["keep"]}, dev=TOK["keep"], base=SBASE, ctx=cactx)
check("the phone API over https", code == 200 and r["user"]["login"] == "keeper", (code, r))
plain = ssl.create_default_context()
try:
    urllib.request.urlopen(SBASE + "/s/", timeout=10, context=plain)
    FAIL.append("a phone that does not trust the clinic must not get the page")
except (urllib.error.URLError, ssl.SSLError, ConnectionError):
    OK[0] += 1
code, body, _ = get("/s/", base=SBASE, ctx=cactx)
check("…and the server goes on after a refused handshake", code == 200, code)
code, body, h = get("/s/ca.crt")
check("the certificate for Android (DER)", code == 200 and h.get("Content-Type") == "application/x-x509-ca-cert"
      and x509.load_der_x509_certificate(body).fingerprint(clinic_ca._x509()[1].SHA256()).hex().upper() == clinic_ca.get().fingerprint(), code)
code, body, h = get("/s/ca.mobileconfig")
check("the profile for an iPhone", code == 200 and h.get("Content-Type") == "application/x-apple-aspen-config", code)
code, body, _ = get("/s/ca")
page = body.decode()
check("the certificate's page: both phones, the fingerprint, the way on to the scanner", code == 200 and "Android" in page and "iPhone" in page
      and clinic_ca.get().state()["short"] in page and "/s/#/tohttps" in page and "Зачем устанавливать сертификат клиники" in page, page[:400])
w = api.phone_wifi_state()
check("phone_wifi_state: the QR of the certificate's page", w["ca_qr"].startswith("data:image") and w["ca_url"].endswith("/s/ca") or not w["http"], w)
w = api.phone_wifi_full(False)
time.sleep(0.5)
check("«Со сканером» off", not w["full"] and srv.httpsd is None, w)
try:
    urllib.request.urlopen(SBASE + "/s/", timeout=3, context=cactx)
    FAIL.append("https must be closed")
except (urllib.error.URLError, ConnectionError, OSError):
    OK[0] += 1

# ------------------------------------------------------------------------------------------------ stock_cloud --
class Mem:
    def __init__(self): self.d = {"url": "", "token": "", "device": "", "tenant": "", "name": "", "last_tenant": ""}
    def load(self): return dict(self.d)
    def save(self, x): self.d.update(x)


class H:
    def __init__(self, phones=None, fail=None):
        self.phones, self.fail, self.calls = phones or [], fail, []

    def post(self, path, body=None):
        self.calls.append(path)
        if self.fail:
            raise self.fail
        if path == "/v1/photo":
            return {"id": body["id"], "data": jpeg((10, 150, 10), (800, 600))}
        if path == "/v1/phones":
            return {"phones": self.phones}
        raise stock_cloud.StockCloudError("Не найдено", 404)


sc = stock_cloud.StockCloud(d, store=Mem(), node="nA", transport=None, files=api._files, stock=api._stock)
check("material_docs go to the cloud", "material_docs" in stock_cloud.TABLES)
p = {"id": "ph19test0001", "material_id": mats[1], "equipment_id": "", "taken_name": "Иванова Анна", "taken_by": "nurse2",
     "taken_role": "Медсестра", "taken_at": "2026-11-28 14:05:31"}
check("a photo of a material from the cloud: into the card", sc._take_photo(H(), p) == 1)
md = d.one("SELECT * FROM material_docs WHERE id='MDP-ph19test0001'")
check("…as MDP-<the cloud photo's id>, who took it", md and md["kind"] == "photo" and md["material_id"] == mats[1] and md["created_by"] == "Иванова Анна"
      and "Иванова Анна" in md["title"], md)
check("…the same photo again: nothing to add", sc._take_photo(H(), p) == 0)
check("…of a material not here yet: later", sc._take_photo(H(), {**p, "id": "ph19test0002", "material_id": "not-here"}) is None)
with d.tx() as c:
    c.execute("UPDATE materials SET active=0 WHERE id=?", (mats[2],))
check("…of a material removed from the list: dropped", sc._take_photo(H(), {**p, "id": "ph19test0003", "material_id": mats[2]}) == 0)
with d.tx() as c:
    c.execute("UPDATE materials SET active=1 WHERE id=?", (mats[2],))
check("a photo of equipment still goes the 3.16 way", sc._take_photo(H(), {**p, "id": "ph19test0004", "material_id": "", "equipment_id": eq["id"]}) == 1
      and d.one("SELECT 1 AS x FROM equipment_docs WHERE id='EDP-ph19test0004'"))
got = sc._phones(H(phones=[{"id": "dev-n1", "name": "iPhone", "login": "nurse", "pin_hash": authm.hash_password("246813"), "token_hash": sha("tok-new-phone-00000001")}]))
check("the phones from the cloud with a sync", got == 1 and d.one("SELECT login FROM phone_local_devices WHERE id='dev-n1'")["login"] == "nurse", got)
code, r = P("login", {"pin": "246813"}, dev="tok-new-phone-00000001")
check("…the new phone signs in here at once", code == 200 and r["user"]["login"] == "nurse", (code, r))
check("an old cloud without /v1/phones: nothing breaks", sc._phones(H(fail=stock_cloud.StockCloudError("Не найдено", 404))) == 0)
try:
    sc._phones(H(fail=stock_cloud.StockCloudError("Нет связи", -1)))
    FAIL.append("no network must stop the sync, as for the other routes")
except stock_cloud.StockCloudError:
    OK[0] += 1

_la = srvm.local_addresses
srvm.local_addresses = lambda: ["192.168.1.14"]
try:
    check("this computer's address for the cloud app", sc._publish_lan() is True)
    v = json.loads(d.one("SELECT v FROM stock_settings WHERE k='lan:nA'")["v"])
    check("…lan:<node> = {name, http, https, at}", v["http"] == f"http://192.168.1.14:{PORT}/s/" and v["https"] == "" and v["at"] and v["name"], v)
    check("…not written again while the same", sc._publish_lan() is False)
    api.phone_wifi_full(True)
    check("…the scanner mode on: written with https", sc._publish_lan() is True
          and json.loads(d.one("SELECT v FROM stock_settings WHERE k='lan:nA'")["v"])["https"] == f"https://192.168.1.14:{srv.https_port}/s/")
    api.phone_wifi_full(False)
    import replica
    replica.stamp(d, "nA")
    sync_row = d.one("SELECT base FROM sync_rows WHERE tbl='stock_settings' AND k=?", (replica.ks(["lan:nA"]),))
    check("…it is a replicated row (goes to the cloud and the other computers)", sync_row and "192.168.1.14" in (sync_row["base"] or ""), sync_row)
finally:
    srvm.local_addresses = _la

srv.stop()
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f_ in FAIL:
    print(" -", f_)
sys.exit(1 if FAIL else 0)
