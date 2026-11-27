"""3.13 roles of the stock: the built-in «Менеджер склада», the request status «Принята», a nurse writes off only through
approval (over HTTP), the personal PIN of the stock app on a phone (6 digits, shown once, only its hash kept and replicated,
reset by the director)."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import replica  # noqa: E402
import stock_flow  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
replica.install(d)

# ------------------------------------------------------------- the role --
R = auth.roles(d)
check("built-in «Менеджер склада»", R.get("stock_manager", {}).get("title") == "Менеджер склада" and R["stock_manager"]["builtin"])
check("its rights", set(R["stock_manager"]["perms"]) == {"stock_view", "stock_edit", "stock_approve", "export"}, R["stock_manager"]["perms"])
check("a position can be built on it", "stock_manager" in auth.BASE_ROLES)
check("the nurse still cannot approve or write off at once", not {"stock_edit", "stock_approve"} & set(R["nurse"]["perms"]))

# ---------------------------------------------------------- over HTTP --
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
for login, role in (("nurse", "nurse"), ("mgr", "stock_manager"), ("keeper", "storekeeper")):
    call("auth", "register", {"name": login.title(), "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TN = call("auth", "login", "nurse", "secret1")[1]["token"]
TM = call("auth", "login", "mgr", "secret1")[1]["token"]
TK = call("auth", "login", "keeper", "secret1")[1]["token"]
staff = {x["login"]: x for x in call("auth", "staff_list", token=TD)[1]["staff"]}
check("the manager got the position", staff["mgr"]["role_title"] == "Менеджер склада", staff["mgr"])

cab = a.stock_location_save({"name": "Кабинет №2", "kind": "cabinet"})
M1 = "demo_m1"
a.stock_receive({"lines": [{"material_id": M1, "qty": 30, "price": 50}]})
a.stock_transfer({"from_id": "", "to_id": cab, "lines": [{"material_id": M1, "qty": 10}]})
bal = lambda: a._stock.location_balance(M1, cab)  # noqa: E731

# a nurse writes off only through approval
code, home = call("api", "stock_home", token=TN)
check("nurse: not direct", code == 200 and not home["can"]["direct"] and not home["can"]["approve"], home.get("can"))
code, _ = call("api", "stock_write_off", {"reason": "брак", "location_id": cab, "lines": [{"material_id": M1, "qty": 1}]}, token=TN)
check("nurse: no write-off of her own", code == 403 and bal() == 10, (code, bal()))
code, ap = call("api", "stock_use", {"kind": "writeoff", "reason": "Разбита ампула", "location_id": cab, "lines": [{"material_id": M1, "qty": 2}]}, token=TN)
check("nurse: her write-off waits", code == 200 and ap["status"] == "pending" and bal() == 10, (code, ap.get("status"), bal()))
code, _ = call("api", "stock_approval_decide", ap["id"], "approve", "", token=TN)
check("nurse: cannot approve her own", code == 403 and bal() == 10, code)
code, mh = call("api", "stock_home", token=TM)
check("manager: sees what waits", code == 200 and mh["can"]["approve"] and mh["can"]["direct"] and mh["counts"]["to_approve"] == 1, mh.get("counts"))
code, ok = call("api", "stock_approval_decide", ap["id"], "approve", "", token=TM)
check("manager: approves — only now it leaves the stock", code == 200 and bal() == 8, (code, bal()))
code, ap2 = call("api", "stock_use", {"kind": "consume", "location_id": cab, "lines": [{"material_id": M1, "qty": 1}]}, token=TN)
code, _ = call("api", "stock_approval_decide", ap2["id"], "reject", "Не по протоколу", token=TM)
check("manager: rejects with a reason, nothing leaves", code == 200 and bal() == 8 and a._sflow.approval(ap2["id"])["answer"] == "Не по протоколу")
code, direct = call("api", "stock_use", {"kind": "consume", "location_id": cab, "lines": [{"material_id": M1, "qty": 1}]}, token=TM)
check("manager: own consumption at once", code == 200 and direct["status"] in ("approved", "done") and bal() == 7, (code, direct.get("status"), bal()))

# the request: Новая → Принята → Выдана
code, rq = call("api", "stock_request_save", {"location_id": cab, "lines": [{"material_id": M1, "qty": 5}], "send": True}, token=TN)
check("nurse: a new request", code == 200 and rq["status"] == "new", rq.get("status"))
check("«Принята» is a status", stock_flow.REQ_STATUS["accepted"] == "Принята")
code, _ = call("api", "stock_request_accept", rq["id"], token=TN)
check("nurse: cannot accept", code == 403, code)
code, _ = call("api", "stock_request_accept", rq["id"], token=TK)
check("storekeeper (stock_edit) may accept", code == 200)
a._sflow.db.conn.execute("UPDATE stock_requests SET status='new', accepted_by=NULL, accepted_name=NULL, accepted_at=NULL WHERE id=?", (rq["id"],))
a._sflow.db.conn.commit()
code, acc = call("api", "stock_request_accept", rq["id"], token=TM)
check("manager: accepts", code == 200 and acc["status"] == "accepted" and acc["status_title"] == "Принята" and acc["accepted_by"] == "mgr"
      and acc["accepted_at"], acc)
code, again = call("api", "stock_request_accept", rq["id"], token=TM)
check("accepting twice is harmless", code == 200 and again["status"] == "accepted")
code, mine = call("api", "stock_requests", {}, token=TN)
check("nurse sees «Принята»", any(x["id"] == rq["id"] and x["status_title"] == "Принята" for x in mine))
check("an accepted request is still open", any(x["id"] == rq["id"] for x in a._sflow.requests("open")))
check("counts: my open requests", a._sflow.counts("nurse")["my_requests"] == 1)
check("counts: to issue / to accept", a._sflow.counts(None, approver=True)["to_issue"] == 1 and a._sflow.counts(None, approver=True)["to_accept"] == 0)
code, err = call("api", "stock_request_cancel", rq["id"], token=TN)
check("nurse: cannot cancel an accepted request alone", code != 200 and a._sflow.request(rq["id"])["status"] == "accepted", (code, err))
code, _ = call("api", "stock_transfer", {"from_id": "", "to_id": cab, "lines": [{"material_id": M1, "qty": 5}], "request_ids": [rq["id"]]}, token=TM)
check("issuing an accepted request makes it «Выдана»", code == 200 and a._sflow.request(rq["id"])["status"] == "done", a._sflow.request(rq["id"])["status"])
code, rq2 = call("api", "stock_request_save", {"location_id": cab, "lines": [{"material_id": M1, "qty": 1}], "send": True}, token=TN)
call("api", "stock_request_accept", rq2["id"], token=TM)
code, rj = call("api", "stock_request_reject", rq2["id"], "Нет на складе", token=TM)
check("an accepted request can be rejected", code == 200 and rj["status"] == "rejected", rj.get("status"))
code, rq3 = call("api", "stock_request_save", {"location_id": cab, "lines": [{"material_id": M1, "qty": 1}], "send": True}, token=TN)
call("api", "stock_request_accept", rq3["id"], token=TM)
code, cc = call("api", "stock_request_cancel", rq3["id"], token=TM)
check("the manager may cancel an accepted request", code == 200 and cc["status"] == "cancelled", cc.get("status"))
code, _ = call("api", "stock_request_accept", rq3["id"], token=TM)
check("a cancelled request is not accepted", code != 200)
code, rq4 = call("api", "stock_request_save", {"location_id": cab, "lines": [{"material_id": M1, "qty": 1}], "send": True}, token=TN)
t = [x for x in call("api", "stock_home", token=TM)[1]["tasks"] if x["key"] == "issue"]
check("home task: «новых: 1»", t and "новых: 1" in t[0]["sub"], t)

# ------------------------------------------------- the phone PIN --
code, _ = call("auth", "phone_pin_new", "wrong", token=TN)
check("phone PIN needs the password", code == 400, code)
code, r = call("auth", "phone_pin_new", "secret1", token=TN)
pin = r.get("pin", "")
check("6 digits, shown once", code == 200 and len(pin) == 6 and pin.isdigit() and r.get("at"), r)
row = d.one("SELECT phone_pin_hash, phone_pin_at, pin_hash FROM users WHERE login='nurse'")
check("only the hash is kept, in its own column", row["phone_pin_hash"] and pin not in row["phone_pin_hash"] and auth.check_password(pin, row["phone_pin_hash"])
      and row["pin_hash"] is None, row)
check("not a weak PIN", not auth._weak_pin(pin))
check("weak PINs are refused", all(auth._weak_pin(x) for x in ("000000", "111111", "123456", "654321", "121212", "123123", "112112", "890123")))
check("an ordinary PIN is fine", not auth._weak_pin("305817"))
me = call("auth", "state", token=TN)[1]["user"]
check("profile says it exists, never shows it", me["has_phone_pin"] and me["phone_pin_at"] and pin not in json.dumps(me), me)
code, r2 = call("auth", "phone_pin_new", "secret1", token=TN)
row2 = d.one("SELECT phone_pin_hash FROM users WHERE login='nurse'")
check("a new PIN replaces the old one", code == 200 and auth.check_password(r2["pin"], row2["phone_pin_hash"])
      and (r2["pin"] == pin or not auth.check_password(pin, row2["phone_pin_hash"])))
check("the quick sign-in PIN is untouched", d.one("SELECT pin_hash FROM users WHERE login='nurse'")["pin_hash"] is None)
nid = staff["nurse"]["id"]
code, _ = call("auth", "staff_phone_pin_reset", nid, token=TM)
check("only «Сотрудники» may reset it", code == 403 and d.one("SELECT phone_pin_hash FROM users WHERE id=?", (nid,))["phone_pin_hash"])
code, _ = call("auth", "staff_phone_pin_reset", nid, token=TD)
row3 = d.one("SELECT phone_pin_hash, phone_pin_at FROM users WHERE id=?", (nid,))
check("the director resets it", code == 200 and row3["phone_pin_hash"] is None and row3["phone_pin_at"] is None, row3)
check("the journal has it", d.one("SELECT 1 AS x FROM audit WHERE action='Сброс ПИН-кода телефона'") is not None)
check("staff list shows it", call("auth", "staff_list", token=TD)[1]["staff"] and "has_phone_pin" in call("auth", "staff_list", token=TD)[1]["staff"][0])

# ------------------------------------------------------- replication --
check("the hash goes to the other computers", "phone_pin_hash" not in replica.BY_NAME["users"].skip)
check("a conflict never shows it", "phone_pin_hash" in replica.SECRET_COLS)
check("catch-up for the new columns", replica.CATCHUP == "3.13" and replica.CATCHUP_COLS.get("users") == ["phone_pin_hash", "phone_pin_at"]
      and replica.CATCHUP_COLS.get("stock_requests") == ["accepted_by", "accepted_name", "accepted_at"])
cols = {r[1] for r in d.conn.execute("PRAGMA table_info(stock_requests)")}
check("request columns", {"accepted_by", "accepted_name", "accepted_at"} <= cols)

# ------------------------------------------------------------- the UI --
ui = ROOT / "app" / "ui"
nurse_js = (ui / "stock-nurse.js").read_text(encoding="utf-8")
check("UI: «Принять» on requests", "stock_request_accept" in nurse_js and 'data-acc=' in nurse_js and "rqAcc" in nurse_js)
check("UI: the approval flow is shown to a nurse", "Списание через согласование" in nurse_js and "snFlowHtml()" in nurse_js)
plat = (ui / "platform.js").read_text(encoding="utf-8")
check("UI: «Мой профиль» with the phone PIN", "Мой профиль" in plat and "phone_pin_new" in plat and "показан один раз" in plat)
check("UI: menu item", 'id="ucProfile"' in (ui / "index.html").read_text(encoding="utf-8"))
check("UI: reset in «Сотрудники»", "staff_phone_pin_reset" in (ui / "staff.js").read_text(encoding="utf-8"))

print(f"OK: {OK[0]} FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
