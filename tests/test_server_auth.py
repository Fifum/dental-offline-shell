"""Clinic server: accounts, approval, permissions, sessions and the action journal over real HTTP."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth as authm  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer, discover, ping  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


d = dbm.DB(); demo.ensure_demo(d, force=True)
api = Api(d, W())
PORT = free_port()
srv = ClinicServer(api, d, port=PORT, host="127.0.0.1").start()
BASE = f"http://127.0.0.1:{PORT}"


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"{BASE}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


# --- static + ping
with urllib.request.urlopen(BASE + "/", timeout=5) as r:
    html = r.read().decode()
check("index served", "authScreen" in html)
check("ping", (ping(BASE) or {}).get("app") == "dentaldesk")
check("discovery finds loopback server", any(x["server_id"] == ping(BASE)["server_id"] for x in discover(port=PORT)))

# --- nobody yet
code, st = call("auth", "state")
check("state before users", code == 200 and st["has_users"] is False and st["can_bootstrap"] is True, st)
code, r = call("api", "day", "2026-01-01")
check("api without login refused", code == 401, code)
code, r = call("auth", "register", {"name": "Иван", "login": "ivan", "password": "123456"})
check("register before director refused", code == 403, (code, r))
try:
    authm.Auth(d).bootstrap({"name": "X", "login": "x", "password": "123456"}, "10.0.0.5", "", is_local=False)
    FAIL.append("bootstrap from another computer must be refused")
except authm.AuthError:
    OK[0] += 1

# --- director
code, r = call("auth", "bootstrap", {"name": "Анна Директор", "login": "Anna", "password": "123"})
check("short password refused", code == 400, code)
code, r = call("auth", "bootstrap", {"name": "Анна Директор", "login": "Anna", "password": "secret1"})
check("bootstrap", code == 200 and r["user"]["role"] == "director", (code, r))
TD = r["token"]
code, _ = call("auth", "bootstrap", {"name": "B", "login": "b", "password": "secret1"})
check("second bootstrap refused", code == 403, code)
code, r = call("api", "cash_day", "2026-01-01", token=TD)
check("director cash", code == 200, code)
code, r = call("api", "get_settings", token=TD)
check("director settings", code == 200 and "pass_enc" not in r, code)

# --- registration + approval
code, r = call("auth", "register", {"name": "Пётр Врач", "login": "petr", "password": "doctor1", "role": "doctor", "position": "Врач"})
check("register", code == 200 and r["ok"], (code, r))
code, r = call("auth", "register", {"name": "Другой", "login": "PETR", "password": "doctor1"})
check("duplicate login (case) refused", code == 409, code)
code, r = call("auth", "register", {"name": "Хакер", "login": "boss", "password": "doctor1", "role": "director"})
check("register cannot ask for director", code == 200, code)
code, r = call("auth", "login", "petr", "doctor1")
check("pending cannot log in", code == 403 and "одобрен" in r["error"], (code, r))
code, r = call("auth", "login", "petr", "wrong")
check("wrong password", code == 401, code)

code, lst = call("auth", "staff_list", token=TD)
check("staff list", code == 200 and len(lst["staff"]) == 3, (code, lst))
boss = next(u for u in lst["staff"] if u["login"] == "boss")
check("self-registered never director", boss["role"] != "director", boss)
petr = next(u for u in lst["staff"] if u["login"] == "petr")
code, r = call("auth", "staff_save", {"id": petr["id"], "role": "doctor", "status": "active"}, token=TD)
check("approve", code == 200 and r["status"] == "active", (code, r))
code, r = call("auth", "staff_reject", boss["id"], token=TD)
check("reject", code == 200, code)

code, r = call("auth", "login", "Petr", "doctor1")
check("doctor login (login case-insensitive)", code == 200, (code, r))
TP = r["token"]
check("doctor perms", "medcard_edit" in r["user"]["perms"] and "payments" not in r["user"]["perms"], r["user"]["perms"])

# --- permissions enforced on the server
code, r = call("api", "day", "2026-01-01", token=TP)
check("doctor sees schedule", code == 200, code)
code, r = call("api", "cash_day", "2026-01-01", token=TP)
check("doctor no cash report", code == 403, code)
code, r = call("api", "add_payment", {"invoice_id": "x", "amount": 1}, token=TP)
check("doctor cannot take payment", code == 403, code)
code, r = call("api", "save_settings", {"demo": False}, token=TP)
check("doctor cannot change settings", code == 403, code)
code, r = call("auth", "staff_list", token=TP)
check("doctor no staff section", code == 403, code)
code, r = call("api", "_autostart_set", True, token=TD)
check("private method hidden", code == 404, code)
code, r = call("api", "nonexistent", token=TD)
check("unknown method", code == 404, code)

pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]
api.save_invoice({"patient_id": pid, "items": [{"title": "Осмотр", "price": 500, "qty": 1}]})
code, r = call("api", "patient", pid, token=TP)
check("doctor sees card with plans and invoices", code == 200 and len(r["invoices"]) >= 1, code)

# assistant-like custom perms: only schedule
code, r = call("auth", "register", {"name": "Ольга", "login": "olga", "password": "assist1"})
olga = next(u for u in call("auth", "staff_list", token=TD)[1]["staff"] if u["login"] == "olga")
call("auth", "staff_save", {"id": olga["id"], "role": "assistant", "status": "active", "perms": ["schedule_view", "patients_view"]}, token=TD)
TO = call("auth", "login", "olga", "assist1")[1]["token"]
check("custom perms: schedule ok", call("api", "day", "2026-01-01", token=TO)[0] == 200)
code, r = call("api", "patient", pid, token=TO)
check("custom perms: card without medcard and money", code == 200 and r["invoices"] == [] and r["records"] == [] and r["documents"] == [], code)
check("custom perms: cash closed", call("api", "cash_day", "2026-01-01", token=TO)[0] == 403)

# --- journal of actions
code, r = call("api", "add_note", pid, "Позвонить пациенту", token=TP)
check("doctor adds note", code == 200, code)
code, rows = call("auth", "audit_list", token=TD)
check("audit has note by doctor", any(x["action"] == "Примечание" and x["user_name"] == "Пётр Врач" for x in rows), rows[:3])
check("audit has failed login", any(x["action"] == "Неудачный вход" for x in rows))

# --- blocking ends the session, last director protected
call("auth", "staff_save", {"id": petr["id"], "role": "doctor", "status": "blocked"}, token=TD)
check("blocked session dead", call("api", "day", "2026-01-01", token=TP)[0] == 401)
check("blocked cannot log in", call("auth", "login", "petr", "doctor1")[0] == 403)
me = next(u for u in call("auth", "staff_list", token=TD)[1]["staff"] if u["login"] == "anna")
code, r = call("auth", "staff_save", {"id": me["id"], "role": "admin", "status": "active"}, token=TD)
check("last director cannot be demoted", code == 400, (code, r))

# --- password change, logout, brute force
code, r = call("auth", "change_password", "bad", "newpass1", token=TD)
check("change password needs old", code == 400, code)
code, r = call("auth", "change_password", "secret1", "newpass1", token=TD)
check("change password", code == 200, code)
call("auth", "logout", token=TD)
check("logout kills token", call("api", "day", "2026-01-01", token=TD)[0] == 401)
codes = [call("auth", "login", "anna", "nope")[0] for _ in range(6)]
check("throttle after 5 fails", codes[-1] == 429, codes)

# --- every Api method used by the UI has a permission rule
public = {n for n in dir(Api) if not n.startswith("_") and callable(getattr(Api, n))}
missing = sorted(public - set(authm.METHOD_PERMS))
check("all Api methods have permission rules", not missing, missing)

srv.stop()
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
