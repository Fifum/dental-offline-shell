"""Stock and equipment: balances, receipts, write-offs, stock count, norms with automatic write-off, rights."""
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
import db as dbm  # noqa: E402
import demo  # noqa: E402
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


def refuses(name, fn, text=""):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except ValueError as e:
        check(name, not text or text in str(e), e)


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
bal = lambda mid: next(m["balance"] for m in a.materials() if m["id"] == mid)  # noqa: E731

# --- demo stock
s = a.stock_summary()
check("demo materials", s["materials"] == 13 and s["equipment"] == 8, s)
check("low stock counted", s["low"] >= 1, s)

# --- catalogue
mid = a.save_material({"name": "Бонд тест", "unit": "мл", "min_qty": 5, "price": 100, "start_qty": 8})
check("start balance", bal(mid) == 8)
refuses("material without name", lambda: a.save_material({"name": " "}))
refuses("bad number", lambda: a.save_material({"name": "X", "price": "abc"}), "число")

# --- receipt
sid = a.save_supplier({"name": "Поставщик тест"})
did = a.stock_receive({"supplier_id": sid, "number": "Н-1", "lines": [{"material_id": mid, "qty": 12, "price": 110}]})
check("receipt adds", bal(mid) == 20)
check("last price remembered", a.material(mid)["price"] == 110)
check("receipt doc", a.stock_doc(did)["total"] == 1320 and a.stock_doc(did)["supplier_name"] == "Поставщик тест")
refuses("receipt with zero qty", lambda: a.stock_receive({"lines": [{"material_id": mid, "qty": 0}]}))
refuses("receipt unknown material", lambda: a.stock_receive({"lines": [{"material_id": "nope", "qty": 1}]}))
refuses("receipt empty", lambda: a.stock_receive({"lines": []}))

# --- manual write-off
refuses("write-off needs reason", lambda: a.stock_write_off({"lines": [{"material_id": mid, "qty": 1}]}), "причину")
refuses("write-off over balance", lambda: a.stock_write_off({"reason": "брак", "lines": [{"material_id": mid, "qty": 21}]}), "нельзя")
refuses("write-off split lines over balance", lambda: a.stock_write_off({"reason": "брак", "lines": [{"material_id": mid, "qty": 15}, {"material_id": mid, "qty": 6}]}), "нельзя")
wid = a.stock_write_off({"reason": "Истёк срок", "lines": [{"material_id": mid, "qty": 3}]})
check("write-off subtracts", bal(mid) == 17)
check("write-off act numbered", a.stock_doc(wid)["number"] == "1")

# --- stock count
r = a.stock_inventory({"lines": [{"material_id": mid, "actual": 15}, {"material_id": "demo_m1", "actual": ""}]})
check("inventory diff", r["diffs"] == [{"material_id": mid, "book": 17, "actual": 15, "diff": -2}], r)
check("inventory sets balance", bal(mid) == 15)
refuses("inventory nothing counted", lambda: a.stock_inventory({"lines": [{"material_id": mid, "actual": ""}]}))
refuses("inventory negative", lambda: a.stock_inventory({"lines": [{"material_id": mid, "actual": -1}]}))

# --- norms + automatic write-off with invoices
a.save_norms("demo_0", [{"material_id": mid, "qty": 1.5}, {"material_id": "demo_m8", "qty": 2}])
check("norms saved", len(a.norms("demo_0")) == 2)
gloves = bal("demo_m8")
pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]
iid = a.save_invoice({"patient_id": pid, "items": [{"service_id": "demo_0", "title": "Консультация", "price": 1000, "qty": 2},
                                                   {"title": "Без услуги из прайса", "price": 100, "qty": 1}]})
check("invoice writes off by norm × qty", bal(mid) == 12 and bal("demo_m8") == gloves - 4, (bal(mid), bal("demo_m8")))
a.save_invoice({"id": iid, "patient_id": pid, "items": [{"service_id": "demo_0", "title": "Консультация", "price": 1000, "qty": 1}]})
check("editing invoice recalculates", bal(mid) == 13.5 and bal("demo_m8") == gloves - 2)
mv = a.stock_moves({"kind": "service"})
check("service move has patient", any(m["patient_name"] and m["invoice_id"] == iid for m in mv))
a.delete_invoice(iid)
check("deleting invoice returns stock", bal(mid) == 15 and bal("demo_m8") == gloves)
plan = a.save_invoice({"patient_id": pid, "kind": "plan", "items": [{"service_id": "demo_0", "title": "К", "price": 1000, "qty": 1}]})
check("plan does not write off", bal(mid) == 15)
inv2 = a.plan_to_invoice(plan)
check("bill from plan writes off", bal(mid) == 13.5)
for _ in range(20):
    a.save_invoice({"patient_id": pid, "items": [{"service_id": "demo_0", "title": "К", "price": 1000, "qty": 1}]})
check("automatic write-off may go below zero", bal(mid) < 0)
check("negative shows in low", any(m["id"] == mid and m["low"] for m in a.materials(only_low=True)))
a.delete_material(mid)
check("removed material hidden", all(m["id"] != mid for m in a.materials()))
check("removed material keeps history", len(a.material(mid)["moves"]) > 5)
check("removed material drops norms", a.norms("demo_0") == [m for m in a.norms("demo_0") if m["material_id"] != mid])

# --- equipment
eid = a.save_equipment({"name": "Автоклав тест", "location": "Стерилизационная", "price": 300000, "next_service": "2000-01-01"})
e = a.equipment(eid)
check("inventory number assigned", e["inv_number"].isdigit() and len(e["inv_number"]) == 5, e["inv_number"])
refuses("duplicate inventory number", lambda: a.save_equipment({"name": "X", "inv_number": e["inv_number"]}), "занят")
check("service due flagged", any(x["id"] == eid and x["service_due"] for x in a.equipment_list()))
a.save_equipment({**e, "location": "Кабинет 3", "status": "repair"})
ev = [x["kind"] for x in a.equipment(eid)["events"]]
check("move and status logged", "move" in ev and "status" in ev, ev)
a.equipment_event({"equipment_id": eid, "kind": "service", "text": "Замена уплотнителя", "cost": 2500, "next_service": "2099-01-01"})
check("service event + next date", a.equipment(eid)["next_service"] == "2099-01-01")
refuses("event without text", lambda: a.equipment_event({"equipment_id": eid, "text": ""}))
refuses("write-off needs commission", lambda: a.write_off_equipment({"id": eid, "reason": "износ", "commission": ["Иванов"]}), "комиссии")
refuses("write-off needs reason", lambda: a.write_off_equipment({"id": eid, "reason": "", "commission": ["А", "Б"]}), "причину")
w = a.write_off_equipment({"id": eid, "reason": "Износ", "commission": ["Иванов, гл. врач", "Петров, техник"], "residual": 0})
check("written off", w["status"] == "written_off" and w["writeoff_act"] and json.loads(w["writeoff_commission"])[1].startswith("Петров"))
check("written off hidden by default", all(x["id"] != eid for x in a.equipment_list()))
check("written off shown on request", any(x["id"] == eid for x in a.equipment_list("", True)))
refuses("written off cannot be edited", lambda: a.save_equipment({**e, "name": "Новое"}), "Списанное")
refuses("double write-off", lambda: a.write_off_equipment({"id": eid, "reason": "x", "commission": ["А", "Б"]}), "уже")

# --- rights over HTTP
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
for login, role in (("doc", "doctor"), ("keeper", "storekeeper")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TDoc = call("auth", "login", "doc", "secret1")[1]["token"]
TK = call("auth", "login", "keeper", "secret1")[1]["token"]
check("doctor sees balances", call("api", "materials", token=TDoc)[0] == 200)
check("doctor cannot receive", call("api", "stock_receive", {"lines": []}, token=TDoc)[0] == 403)
check("doctor cannot write off equipment", call("api", "write_off_equipment", {"id": "x"}, token=TDoc)[0] == 403)
check("storekeeper receives", call("api", "stock_receive", {"lines": [{"material_id": "demo_m1", "qty": 5, "price": 60}]}, token=TK)[0] == 200)
check("storekeeper no patients", call("api", "patient", pid, token=TK)[0] == 403)
check("storekeeper no schedule", call("api", "day", "2026-01-01", token=TK)[0] == 403)
moves = call("api", "stock_moves", {"kind": "receipt"}, token=TK)[1]
check("move signed with employee name", moves[0]["user_name"] == "keeper", moves[0])
audit = call("auth", "audit_list", token=TD)[1]
check("audit: receipt by storekeeper", any(x["action"] == "Приход на склад" and x["user_name"] == "keeper" for x in audit))
code, st = call("api", "status", token=TK)
check("status shows low stock to storekeeper", code == 200 and "stock_low" in st)
code, st = call("api", "status", token=call("auth", "login", "dir", "secret1")[1]["token"])
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
