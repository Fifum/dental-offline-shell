"""Review 2026-11-13, group «security»: К9, К10, В7, В8, В9, В16, В20 — each bug as it was reproduced."""
import base64
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "cloud"))
import auth as A  # noqa: E402
import config  # noqa: E402
from db import DB  # noqa: E402
import server  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def refuses(name, fn, text=""):
    try:
        fn()
        FAIL.append(f"{name}: not refused")
    except Exception as e:  # noqa: BLE001
        check(name, text in str(e), repr(e))


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def burst(port, path, bodies):
    """Hold every request one byte short, then release them together (last-byte sync): the race of К9."""
    socks = []
    for b in bodies:
        s = socket.create_connection(("127.0.0.1", port))
        s.sendall(b"POST " + path.encode() + b" HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                  b"Content-Length: %d\r\n\r\n" % len(b) + b[:-1])
        socks.append((s, b[-1:]))
    time.sleep(0.5)
    for s, last in socks:
        s.sendall(last)
    codes = {}
    for s, _ in socks:
        s.settimeout(60)
        data = b""
        while True:
            d = s.recv(65536)
            if not d:
                break
            data += d
        s.close()
        c = int(data.split(b" ", 2)[1]) if data else 0
        codes[c] = codes.get(c, 0) + 1
    return codes


db = DB(os.path.join(os.environ["LOCALAPPDATA"], "t.db"))
PORT = free_port()
srv = server.ClinicServer(api=None, db=db, port=PORT, host="127.0.0.1").start()
au = srv.auth
au.bootstrap({"login": "boss", "name": "Boss", "password": "secret123"}, "127.0.0.1", "x", True)
boss = db.one("SELECT * FROM users WHERE login='boss'")
au.set_pin(boss, "secret123", "7319")
time.sleep(0.3)


def audits(action):
    return db.one("SELECT COUNT(*) AS n FROM audit WHERE action=?", (action,))["n"]


# ================================================================ К9: PIN / password guessing in parallel
N = 300
bodies = [json.dumps([boss["id"], f"{7100 + i:04d}"]).encode() for i in range(N)]  # 7319 is in the range
codes = burst(PORT, "/auth/pin_login", bodies)
evaluated = audits("Неверный ПИН-код") + audits("Вход по ПИН-коду")
check("К9: 300 parallel PIN guesses — at most PIN_MAX_FAILS checked", evaluated <= A.PIN_MAX_FAILS, (evaluated, codes))
check("К9: all answered", sum(codes.values()) == N, codes)
check("К9: the right PIN only if among the checked few", codes.get(200, 0) == audits("Вход по ПИН-коду") <= 1, codes)
check("К9: the rest refused (429 / locked)", codes.get(429, 0) + codes.get(403, 0) >= N - A.PIN_MAX_FAILS, codes)
if not codes.get(200):
    pf = db.one("SELECT pin_fails FROM users WHERE id=?", (boss["id"],))["pin_fails"]
    check("К9: the PIN is locked after the burst", pf == A.PIN_MAX_FAILS, pf)
# fresh state: another key per IP, the counter in the database alone
au._fails.clear()
with db.tx() as c:
    c.execute("UPDATE users SET pin_fails=0 WHERE id=?", (boss["id"],))
before = audits("Неверный ПИН-код")
errs = []


def guess(i):
    try:
        au.pin_login(boss["id"], f"{1000 + i:04d}", f"10.1.{i // 250}.{i % 250}", "t")  # every guess from its own IP
    except A.AuthError as e:
        errs.append(e.code)


ts = [threading.Thread(target=guess, args=(i,)) for i in range(60)]
[t.start() for t in ts]
[t.join() for t in ts]
check("К9: many IPs at once — the database counter still lets only PIN_MAX_FAILS through",
      audits("Неверный ПИН-код") - before <= A.PIN_MAX_FAILS, audits("Неверный ПИН-код") - before)
refuses("К9: locked PIN refuses even the right one", lambda: au.pin_login(boss["id"], "7319", "10.9.9.9", "t"), "заблокирован")
au.login("boss", "secret123", "10.9.9.8", "t")
check("К9: password sign-in unlocks the PIN", au.pin_login(boss["id"], "7319", "10.9.9.7", "t")["token"])
ok_in_row = sum(1 for _ in range(8) if au.pin_login(boss["id"], "7319", "127.0.0.1", "t")["token"])
check("К9: right PINs are not counted as fails (shared computer)", ok_in_row == 8, ok_in_row)
au._fails.clear()
before = audits("Неудачный вход")
codes = burst(PORT, "/auth/login", [json.dumps(["boss", f"wrong{i}"]).encode() for i in range(100)])
check("К9: 100 parallel password guesses — at most MAX_FAILS checked",
      audits("Неудачный вход") - before <= A.MAX_FAILS, (audits("Неудачный вход") - before, codes))
check("К9: others get 429", codes.get(429, 0) >= 100 - A.MAX_FAILS, codes)
au._fails.clear()
import installer  # noqa: E402
cmds = " ".join(installer.firewall_commands("C:\\x\\App.exe"))
check("К9: firewall rule not on «Public» networks", "public" not in cmds and "profile=private,domain" in cmds, cmds)

# ================================================================ В16: negative Content-Length, socket timeout
s = socket.create_connection(("127.0.0.1", PORT))
s.settimeout(10)
s.sendall(b"POST /auth/pin_users HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n" + b"x" * 1000)
try:
    first = s.recv(200).split(b"\r\n")[0]
except OSError as e:
    first = repr(e).encode()
s.close()
check("В16: Content-Length -1 → 400 at once", b" 400 " in first, first)
s = socket.create_connection(("127.0.0.1", PORT))
s.sendall(b"POST /auth/pin_users HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
check("В16: Content-Length not a number → 400", b" 400 " in s.recv(200), "")
s.close()
check("В16: clinic server handler has a socket timeout", srv.httpd.RequestHandlerClass.timeout == 30)
import cloud_server  # noqa: E402
CP = free_port()
chttpd, _cl = cloud_server.serve(tempfile.mkdtemp(), port=CP, background=True)
time.sleep(0.2)
s = socket.create_connection(("127.0.0.1", CP))
s.settimeout(10)
s.sendall(b"POST /v1/join HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\n" + b"x" * 1000)
try:
    first = s.recv(200).split(b"\r\n")[0]
except OSError as e:
    first = repr(e).encode()
s.close()
check("В16: cloud — Content-Length -1 → 400", b" 400 " in first, first)
check("В16: cloud handler has a socket timeout", chttpd.RequestHandlerClass.timeout == 30)
chttpd.shutdown()

# ================================================================ В9: the right «Сотрудники» is not the director
au.register({"login": "senior", "name": "Senior Admin", "password": "secret123"}, "10.0.0.5")
au.register({"login": "newbie", "name": "New Person", "password": "secret123"}, "10.0.0.6")
sid = db.one("SELECT id FROM users WHERE login='senior'")["id"]
nid = db.one("SELECT id FROM users WHERE login='newbie'")["id"]
boss = db.one("SELECT * FROM users WHERE login='boss'")
r = au.role_save(boss, {"title": "Старший администратор", "base": "admin", "perms": A.ROLES["admin"]["perms"] + ["staff"]})
au.staff_save(boss, {"id": sid, "role": r["key"], "status": "active"})
tok = au.login("senior", "secret123", "10.0.0.5", "x")["token"]


def as_senior(name, *args):
    return srv.call_auth(name, list(args), tok, "10.0.0.5", "x", False)


refuses("В9: staff right cannot make itself director", lambda: as_senior("staff_save", {"id": sid, "role": "director", "status": "active"}),
        "только директор")
refuses("В9: cannot reset the director's password",
        lambda: as_senior("staff_reset_password", boss["id"], "pwned12"), "директора")
check("В9: director's password unchanged",
      A.check_password("secret123", db.one("SELECT pass_hash FROM users WHERE id=?", (boss["id"],))["pass_hash"]))
refuses("В9: cannot block the director", lambda: as_senior("staff_save", {"id": boss["id"], "role": "director", "status": "blocked"}),
        "только директор")
refuses("В9: cannot give rights they do not have", lambda: as_senior("staff_save", {"id": nid, "role": "admin", "status": "active",
                                                                                       "perms": ["settings", "schedule_view"]}),
        "Нельзя выдать")
refuses("В9: cannot widen their own position", lambda: as_senior("role_save", {"key": r["key"], "title": "Старший администратор",
                                                                                "perms": A.ROLES["admin"]["perms"] + ["staff", "settings"]}),
        "Нельзя выдать")
refuses("В9: cannot make a new position with more rights", lambda: as_senior("role_save", {"title": "Хитрая", "base": "admin",
                                                                                           "perms": ["settings"]}), "Нельзя выдать")
ok = as_senior("staff_save", {"id": nid, "role": "admin", "status": "active"})
check("В9: approving with rights they hold works", ok["status"] == "active" and ok["role"] == "admin", ok)
check("В9: their own rights are unchanged", db.one("SELECT role FROM users WHERE id=?", (sid,))["role"] == r["key"])
check("В9: resetting a non-director password works", as_senior("staff_reset_password", nid, "newpass1") is True)
r2 = au.staff_save(boss, {"id": nid, "role": "admin", "status": "active", "perms": ["settings", "schedule_view"]})
check("В9: the director still may give any right", "settings" in r2["perms"], r2["perms"])
srv.stop()

# ================================================================ В20: unit of a material is escaped
js = (ROOT / "app" / "ui" / "stock.js").read_text(encoding="utf-8")
qty = re.search(r"const qtyFmt = .*", js).group(0)
check("В20: qtyFmt escapes the unit", "esc(u)" in qty, qty)
check("В20: unit list escaped", 'option value="${esc(u)}"' in js)
check("В20: no double escape of qtyFmt", "esc(qtyFmt(" not in js)
for f in ("stock.js", "stock-lots.js", "stock-auto.js"):
    t = (ROOT / "app" / "ui" / f).read_text(encoding="utf-8")
    raw = [m for ln in t.splitlines() if 'title="${esc(' not in ln  # a title built inside esc(...) is escaped as a whole
           for m in re.findall(r"\$\{[^{}]*\.unit[^{}]*\}", ln) if "qtyFmt(" not in m and "esc(" not in m and "lotsTable(" not in m]
    check(f"В20: {f} — no raw unit in HTML", not raw, raw)

# ================================================================ К10: pairing key swap
import p2p  # noqa: E402
from cloud import clinic_key, set_clinic_key  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402

config.save_settings({"demo": False})
set_clinic_key(secrets.token_bytes(32), "Clinic")


def kp():
    k = X25519PrivateKey.generate()
    return k, base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def try_open(priv, node):
    g = p2p._pair_poll({"node": node})
    try:
        box = base64.b64decode(g["box"])
        sh = priv.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(g["epk"])))
        s_ = json.loads(AESGCM(p2p._box_key(sh, node)).decrypt(box[:12], box[12:], node.encode()))
        return base64.b64decode(s_["key"]) == clinic_key()
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


legit, lpub = kp()
evil, epub = kp()
NODE = "a1b2c3d4e5f6"
p2p._pair_request({"node": NODE, "name": "PC-2", "pub": lpub}, "10.0.0.5")
shown = p2p.pending_pairs()[0]["code"]
try:
    p2p._pair_request({"node": NODE, "name": "PC-2", "pub": epub}, "10.0.0.66")
    FAIL.append("К10: second key for a waiting computer accepted")
except p2p.P2PError as e:
    check("К10: second key for a waiting computer refused", e.code == 409, e.code)
check("К10: the waiting request is cancelled, not re-keyed", p2p.pending_pairs() == [], p2p.pending_pairs())
refuses("К10: accept of the cancelled request refused", lambda: p2p.accept_pair(NODE, shown), "устарел")
check("К10: nobody got a grant", p2p._pair_poll({"node": NODE})["state"] == "rejected")
# a new request after that: the director sees its own code and must type/compare exactly it
legit2, lpub2 = kp()
p2p._pair_request({"node": NODE, "name": "PC-2", "pub": lpub2}, "10.0.0.5")
code2 = p2p.pending_pairs()[0]["code"]
refuses("К10: accept with another code refused", lambda: p2p.accept_pair(NODE, shown if shown != code2 else "000000"), "Код")
refuses("К10: accept without the code refused", lambda: p2p.accept_pair(NODE, ""), "Код")
check("К10: still waiting after wrong codes", p2p.pending_pairs() and p2p.pending_pairs()[0]["code"] == code2)
p2p.accept_pair(NODE, code2[:3] + " " + code2[3:])  # as shown on screen, with the space
check("К10: the right computer opens the grant", try_open(legit2, NODE) is True)
check("К10: the attacker's key cannot", try_open(evil, NODE) != True)  # noqa: E712
hits = []
for i in range(p2p.PAIR_PER_IP + 1):
    _, pb = kp()
    try:
        p2p._pair_request({"node": f"n{i:011d}", "name": "X", "pub": pb}, "10.7.7.7")
        hits.append(200)
    except p2p.P2PError as e:
        hits.append(e.code)
check("К10: pair_request rate-limited per IP", hits[-1] == 429 and hits[:-1] == [200] * p2p.PAIR_PER_IP, hits)
_, pb = kp()
check("К10: another IP is not limited", p2p._pair_request({"node": "zz0000000001", "name": "Y", "pub": pb}, "10.7.7.8")["ok"])
js = (ROOT / "app" / "ui" / "platform.js").read_text(encoding="utf-8")
check("К10: the dialog passes the code it showed", "api.p2p_accept(r.node, r.code)" in js)

# ================================================================ В8: saved secrets never go to another address
got = {}


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        got["body"] = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(401); self.end_headers()

    def log_message(self, *a): pass


evil_srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=evil_srv.serve_forever, daemon=True).start()
config.save_settings({"demo": False, "login": "clinic-api-login", "pass_enc": config.protect("FAKE-test-password"),
                      "base_url": "https://api2.dentist-plus.com/partner"})
from main import Api  # noqa: E402


class W:
    def trigger(self): pass
    def status(self): return {}


api = Api(db, W())
r = api.test_connection("", "", f"http://127.0.0.1:{evil_srv.server_port}")
check("В8: other address + empty fields → refused", not r["ok"] and "заново" in r["message"], r)
check("В8: nothing sent to the other address", "body" not in got, got)
r = api.test_connection("me", "typed", "http://203.0.113.5/partner")
check("В8: plain http to another computer refused", not r["ok"] and "https" in r["message"], r)
refuses("В8: save_settings — new address without the password", lambda: api.save_settings({"base_url": "https://evil.example/partner"}),
        "пароль")
refuses("В8: save_settings — plain http refused", lambda: api.save_settings({"base_url": "http://203.0.113.5/p", "password": "x"}), "https")
check("В8: address unchanged after refusals", config.load_settings()["base_url"] == "https://api2.dentist-plus.com/partner")
check("В8: same address, no password — fine", api.save_settings({"base_url": "https://api2.dentist-plus.com/partner/"}) is not None)
import ai  # noqa: E402
ai.save({"enabled": True, "provider": "openai", "base_url": "https://llm.example/v1", "model": "m", "key": "sk-test"})
check("В8: AI key saved", ai.settings()["key_enc"])
ai.save({"base_url": "https://other.example/v1"})
check("В8: AI — another address drops the saved key", not ai.settings()["key_enc"])
ai.save({"base_url": "https://other.example/v1", "key": "sk-test2"})
check("В8: AI — key typed for the new address kept", config.unprotect(ai.settings()["key_enc"]) == "sk-test2")
ai.save({"model": "m2"})
check("В8: AI — other changes keep the key", ai.settings()["key_enc"])
refuses("В8: AI — plain http to another computer refused", lambda: ai.save({"base_url": "http://192.0.2.10:11434/v1", "key": "k"}), "https")
check("В8: AI — http to this computer (local model) allowed",
      ai.save({"base_url": "http://127.0.0.1:11434/v1"})["base_url"] == "http://127.0.0.1:11434/v1")
evil_srv.shutdown()

# ================================================================ В7: update swaps the folder all or nothing
exe = config.BRAND["exe"] + ".exe"
tmp = Path(tempfile.mkdtemp())
target = tmp / "App"


def rd(p):
    return p.read_text() if p.exists() else "MISSING"


def mk(p, v):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(exe, f"exe {v}"); z.writestr("_internal/base_library.zip", f"lib {v}"); z.writestr("_internal/ui/index.html", f"ui {v}")
    return p


installer.install_zip(mk(tmp / "v1.zip", "1"), str(target))
h = open(target / "_internal" / "base_library.zip", "rb")  # a helper process / antivirus still holds a file
try:
    installer.install_zip(mk(tmp / "v2.zip", "2"), str(target))
    failed = False
except Exception:  # noqa: BLE001
    failed = True
h.close()
if failed:
    check("В7: failed update — old exe back", rd(target / exe) == "exe 1", rd(target / exe))
    check("В7: failed update — old _internal back", rd(target / "_internal" / "base_library.zip") == "lib 1")
    check("В7: failed update — no .new-/.old- leftovers", sorted(os.listdir(target)) == sorted([exe, "_internal"]), os.listdir(target))
else:
    check("В7: (this system let the folder move) new version whole", rd(target / exe) == "exe 2"
          and rd(target / "_internal" / "base_library.zip") == "lib 2")
installer.install_zip(mk(tmp / "v2.zip", "2"), str(target))
check("В7: next update goes through", rd(target / exe) == "exe 2" and rd(target / "_internal" / "ui" / "index.html") == "ui 2")
check("В7: and leaves no side folders", sorted(os.listdir(target)) == sorted([exe, "_internal"]), os.listdir(target))
# a failure while moving the exe (the last item): _internal goes back too
real_replace, calls = os.replace, []


def flaky(a, b):
    calls.append((a, b))
    if os.path.basename(str(a)) == exe and ".new-" in str(a):
        raise PermissionError("exe busy")
    return real_replace(a, b)


installer.os.replace = flaky
try:
    installer.install_zip(mk(tmp / "v3.zip", "3"), str(target))
    FAIL.append("В7: busy exe not reported")
except PermissionError:
    pass
finally:
    installer.os.replace = real_replace
check("В7: busy exe — _internal of the old version back", rd(target / "_internal" / "base_library.zip") == "lib 2")
check("В7: busy exe — old exe in place", rd(target / exe) == "exe 2")
check("В7: busy exe — no leftovers", sorted(os.listdir(target)) == sorted([exe, "_internal"]), os.listdir(target))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
