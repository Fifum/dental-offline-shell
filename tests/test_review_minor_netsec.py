"""Review 2026-11-13, minors «net-sec»: duplicate numbers across computers (М1), clocks (М14), the cloud version sealed
(М15), the clinic network node under threads (М16), the update that never leaves a computer without the program (М17),
no user = refuse inside a request (М18), journal gaps and login timing (М19), installing updates (М20), tablets (М21)."""
import base64
import email.utils
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import cloud  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import installer  # noqa: E402
import p2p  # noqa: E402
import replica  # noqa: E402
import server  # noqa: E402
import setup_main  # noqa: E402
import updates  # noqa: E402
from main import Api  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def refuses(name, fn, text="", exc=(ValueError, auth.AuthError)):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except exc as e:
        check(name, not text or text in str(e), e)


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
auth.Auth(d)  # the action journal
DIRECTOR = {"id": 1, "role": "director", "login": "dir", "name": "Директор"}
ADMIN = {"id": 2, "role": "admin", "login": "adm", "name": "Админ", "perms": None}

# ======================================================================= М1: duplicate numbers after a merge
pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]
o1 = a._lab.save({"patient_id": pid, "work": "Коронка"}, "x")
n = o1["number"]
with d.tx() as c:  # the same number made on another computer without a connection, a minute later
    c.execute("INSERT INTO lab_orders(id, number, patient_id, work, status, created_at) VALUES('LO-other', ?, ?, 'Винир', 'new', ?)",
              (n, pid, "2999-01-01 00:00:00"))
rows = {r["id"]: r for r in a._lab.orders("all")}
check("М1: the first order keeps its number", rows[o1["id"]]["number"] == n and not rows[o1["id"]]["dup"], rows[o1["id"]]["number"])
check("М1: the later one shows N-2", rows["LO-other"]["number"] == f"{n}-2" and rows["LO-other"]["dup"], rows["LO-other"]["number"])
check("М1: the next order still takes MAX+1", a._lab.save({"patient_id": pid, "work": "Мост"}, "x")["number"] == n + 1)
with d.tx() as c:
    for cid, at in (("TC-a", "2026-03-01 10:00:00"), ("TC-b", "2026-03-01 10:05:00"), ("TC-c", "2026-03-02 10:00:00")):
        c.execute("INSERT INTO tax_certs(id, number, year, patient_id, payer_fio, sum1, sum2, issued_at) VALUES(?,?,?,?,?,?,?,?)",
                  (cid, 7 if cid != "TC-c" else 8, 2026, pid, "Тест", 100, 0, at))
tl = {r["id"]: r["number"] for r in a._tax.list(2026)["rows"]}
check("М1: tax certificates — duplicate shown as 7-2, others plain", tl == {"TC-a": 7, "TC-b": "7-2", "TC-c": 8}, tl)

# ======================================================================= М14: clocks
check("М14: message in hours", p2p.clock_message("ПК-2", -30 * 3600) ==
      "Часы этого компьютера расходятся с компьютером «ПК-2» на 30 ч — проверьте дату и время", p2p.clock_message("ПК-2", -30 * 3600))
check("М14: message in minutes", "на 20 мин" in p2p.clock_message("ПК-2", 1200))
K = cloud.Keys(secrets.token_bytes(32))
ts = int(time.time()) + 30 * 3600
body = {"n": "nodeX", "c": K.clinic_id(), "t": ts, "d": base64.b64encode(K.seal(b"{}", p2p._req_aad("pull", "nodeX", ts))).decode()}
try:
    p2p.open_request(K, "pull", body)
    FAIL.append("М14: a request 30 h ahead accepted")
except p2p.P2PError as e:
    check("М14: the refusal names the clock difference", "Часы этого компьютера расходятся" in str(e) and "30 ч" in str(e), e)
check("М14: the sender's clock is remembered (sealed time)", abs(p2p.skew_of("nodeX") - 30 * 3600) < 5, p2p.skew_of("nodeX"))
bad = dict(body, t=ts + 1)
refuses("М14: a forged time is not even decrypted", lambda: p2p.open_request(K, "pull", bad), "не расшифрован", p2p.P2PError)


class Old(BaseHTTPRequestHandler):  # a 3.8.0 computer whose clock is 30 hours ahead
    def date_time_string(self, timestamp=None):
        return email.utils.formatdate(time.time() + 30 * 3600, usegmt=True)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        b = json.dumps({"error": "Неверное время запроса"}).encode()
        self.send_response(403)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *x):
        pass


hs = ThreadingHTTPServer(("127.0.0.1", 0), Old)
threading.Thread(target=hs.serve_forever, daemon=True).start()
try:
    p2p.call(f"http://127.0.0.1:{hs.server_port}", "pull", {}, timeout=5, sealed=False)
    FAIL.append("М14: expected an error")
except p2p.P2PError as e:
    check("М14: a 3.8.0 answer becomes the clock message", "расходятся" in str(e) and "30 ч" in str(e), e)
    check("М14: the difference travels with the error", abs(e.skew - 30 * 3600) < 10, getattr(e, "skew", None))
hs.shutdown()

# ======================================================================= М15: the cloud version is sealed
kk = cloud.Keys(secrets.token_bytes(32))
cl = cloud.Cloud(d)
real = (replica.stamp, replica.cloud_outgoing, replica.apply_versions, replica.cloud_pushed)
V = replica.make_ver("nodeA", 1700000000000)
sent = {}


class H:
    def __init__(self, rows=None):
        self.rows = rows or []

    def post(self, path, payload=None):
        if path == "/v1/push":
            sent["changes"] = payload["changes"]
            return {"accepted": [], "rejected": []}
        return {"rows": self.rows, "more": False, "subscription": {}}


replica.stamp = lambda db, node: 0
replica.cloud_outgoing = lambda db, limit=400: [{"t": "labs", "k": ["LB-1"], "ks": '["LB-1"]', "row": {"id": "LB-1"}, "ver": V,
                                                  "vv": {"nodeA": 1}, "pbase": None, "pvv": None, "origin": "nodeA", "base": None}]
cl._upload_files = lambda *x: None
cl._push(H(), kk, "dev")
ch = sent["changes"][0]
check("М15: the version is inside the sealed row", kk.open_row(ch["data"], ch["key"]).get("ver") == V)
got = []
replica.apply_versions = lambda db, items, node, cloud=False: got.extend(items) or {}
rk = kk.row_key("labs", '["LB-1"]')
new_row = {"key": rk, "ver": "999999999999999.evil.000000", "seq": 1,
           "data": kk.seal_row({"t": "labs", "k": ["LB-1"], "row": {"id": "LB-1"}, "vv": {"nodeA": 1}, "ver": V}, rk)}
old_row = {"key": rk, "ver": V, "seq": 2, "data": kk.seal_row({"t": "labs", "k": ["LB-1"], "row": {"id": "LB-1"}, "vv": {"nodeA": 1}}, rk)}
cl._pull(H([new_row, old_row]), kk)
check("М15: the sealed version wins over the cloud's", got and got[0]["ver"] == V, got[:1])
check("М15: a row sealed by 3.8.0 (no inner version) still reads", len(got) == 2 and got[1]["ver"] == V)
replica.stamp, replica.cloud_outgoing, replica.apply_versions, replica.cloud_pushed = real

# ======================================================================= М16: the node's lists under threads
node = p2p.Node(d)
errs = []


def hammer(i):
    try:
        for j in range(150):
            node.seen(f"n{i}-{j}", "10.0.0.9", 8765) if j % 3 else node.seen(None, f"10.1.{i}.{j}", 8765)
            node.wake(node=f"n{i}-{j}")
    except Exception as e:  # noqa: BLE001
        errs.append(e)


ths = [threading.Thread(target=hammer, args=(i,)) for i in range(4)]
for t in ths:
    t.start()
try:
    while any(t.is_alive() for t in ths):
        node.live_list()
        with node._lock:
            node._wanted = set()
except RuntimeError as e:  # «dictionary changed size during iteration»
    errs.append(e)
for t in ths:
    t.join()
check("М16: no «changed size during iteration»", not errs, errs[:1])
lst = node.live_list()
lst[0]["ip"] = "x"
check("М16: live_list gives copies", all(p["ip"] != "x" for p in node.live.values()))
p2p.NODE = None

# ======================================================================= М17: updating never leaves the computer without the program
check("М17: the installer waits long enough", installer.CLOSE_WAIT_S >= 60)
calls = {"launch": [], "msg": []}
tmp = Path(tempfile.mkdtemp())
target = tmp / "app.exe"
target.write_bytes(b"x")
saved = {k: getattr(installer, k) for k in ("target_exe", "close_running", "install_zip", "launch", "message", "ask_retry",
                                             "make_shortcuts", "add_firewall_rule", "install_dir")}
installer.target_exe = lambda: str(target)
installer.install_dir = lambda: str(tmp)
installer.launch = lambda exe, args: calls["launch"].append(exe)
installer.message = lambda text: calls["msg"].append(text)
installer.make_shortcuts = installer.add_firewall_rule = lambda *x, **k: None
sys.argv = ["setup.exe"]
installer.close_running = lambda t, seconds=0: True


def boom(*x):
    raise OSError("диск занят")


installer.install_zip = boom
check("М17: a failed install returns 1", setup_main.main() == 1)
check("М17: … and opens the old version again", calls["launch"] == [str(target)], calls)
check("М17: … and says so", calls["msg"] and "прежней версии" in calls["msg"][0], calls["msg"])
calls["launch"].clear()
installer.install_zip = lambda z, where: str(target)
check("М17: a good install opens the program", setup_main.main() == 0 and calls["launch"] == [str(target)])
calls["launch"].clear()
seq = iter([False, True])  # still closing → «Повторить» → closed
answers = iter([True])
installer.close_running = lambda t, seconds=0: next(seq)
installer.ask_retry = lambda text: next(answers)
check("М17: «Повторить» waits again, then installs", setup_main.main() == 0 and calls["launch"] == [str(target)])
calls["launch"].clear()
seq = iter([False, True])  # «Отмена», but it closed meanwhile → opened again, not left closed
installer.close_running = lambda t, seconds=0: next(seq)
installer.ask_retry = lambda text: False
check("М17: «Отмена» after it closed opens it again", setup_main.main() == 1 and calls["launch"] == [str(target)])
for k, v in saved.items():
    setattr(installer, k, v)
U = updates.UPDATER
U.state["installing"] = True
U._installing_at = time.time() - updates.INSTALL_GIVE_UP_S - 5
check("М17: «installing» does not stay forever", U.installing() is False and "не установилось" in U.state["error"])
U.state["error"] = ""

# ======================================================================= М18: no user inside a request = refuse
check("М18: the program itself (no request) keeps full access", a._ts_all() is True)
with auth.request_scope("10.0.0.5"):
    refuses("М18: a request without a user is refused (timesheet)", a._ts_all, "Войдите")
    refuses("М18: … director checks too", lambda: a._director("Тест"), "Войдите")
    refuses("М18: … backup restore", lambda: a.backup_restore("local", "x"), "Войдите")
    st = a.status()
    check("М18: status still answers, without the guarded parts", "stock_alerts" not in st and "backup_warn" not in st, list(st)[:5])
    auth.set_current_user(DIRECTOR)
    check("М18: with a user the request works", a._ts_all() is True)
    auth.set_current_user(None)
check("М18: the scope ends with the request", not auth.in_request())

# ======================================================================= М19: journal and login timing
for m in ("voice_enroll", "voice_delete", "local_ai_install", "local_ai_pull", "local_ai_delete", "speech_use", "tablet_cancel",
          "patient", "file_get"):
    check(f"М19: {m} is journaled", m in auth.AUDITED)
srv = server.ClinicServer(a, d, port=0)
srv.auth.require = lambda token, name: DIRECTOR
srv.call_api("patient", [pid], "t", "10.0.0.5")
srv.call_api("patient", [pid], "t", "10.0.0.5")
j = d.q("SELECT * FROM audit WHERE action='Открыта карточка пациента'")
check("М19: opening a card is journaled once in 10 minutes, with the id only", len(j) == 1 and j[0]["detail"] == pid, j)
check("М19: thumbnails are not journaled", not server._worth_logging(DIRECTOR, "file_get", ["F1", "thumb"]))
check("М19: opening a file is", server._worth_logging(DIRECTOR, "file_get", ["F1", "view"]))
A2 = auth.Auth(d)
seen = []
real_check = auth.check_password
auth.check_password = lambda pw, stored: seen.append(stored) or real_check(pw, stored)
refuses("М19: unknown login refused", lambda: A2.login("нет-такого", "x", "1.2.3.4", ""), "Неверный логин", auth.AuthError)
check("М19: an unknown login still runs PBKDF2", len(seen) == 1 and seen[0].startswith("pbkdf2$"), seen)
auth.check_password = real_check
src = (ROOT / "app" / "auth.py").read_text(encoding="utf-8")
check("М19: register hashes before telling the login is taken",
      src.index("ph = hash_password(pw)") < src.index('raise AuthError("Такой логин уже занят", 409)'))

# ======================================================================= М20: installing updates, local-only actions
check("М20: update_install needs «Настройки»", auth.METHOD_PERMS["update_install"] == "settings")
auth.set_current_user(DIRECTOR)
with auth.request_scope("10.0.0.5"):
    refuses("М20: not from another device", a.update_install, "только на этом компьютере")
    refuses("М20: open_data_dir not from another device", a.open_data_dir, "только на этом компьютере")
    refuses("М20: show_dev_report not from another device", a.show_dev_report, "только на этом компьютере")
with auth.request_scope("127.0.0.1"):
    refuses("М20: in this computer's window — refused only for want of a file", a.update_install, "Сначала скачайте")
auth.set_current_user(ADMIN)
with auth.request_scope("127.0.0.1"):
    refuses("М20: an employee without «Настройки» may not", a.update_install, "Настройки")
auth.set_current_user(None)
js = (ROOT / "app" / "ui" / "platform.js").read_text(encoding="utf-8")
check("М20: the banner offers «Обновить» only where it may work", "updMay()" in js and 'can("settings")' in js)

# ======================================================================= М21: tablets stay on the clinic's own Wi-Fi
check("М21: the tablet pairing screen says so", "гостевой" in (ROOT / "app" / "ui" / "tablet.html").read_text(encoding="utf-8"))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
