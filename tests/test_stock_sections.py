"""3.14 three sections of the stock: «Склад и материалы», «Оборудование» and «Инвентаризация». The equipment checked as a list
(found / not found, place, condition), the history of checks, «ТО и ремонт» (what is due, services and repairs with their
cost), the badge «Пора на ТО», and the rights of each section over HTTP (the nurse, the stock manager, the storekeeper)."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
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
S = a._stock
with d.tx() as c:
    c.execute("DELETE FROM equipment")
    c.execute("DELETE FROM equipment_events")
today = date.today()
cab = a.stock_location_save({"name": "Кабинет 3", "kind": "cabinet"})
e1 = a.save_equipment({"name": "Установка", "inv_number": "СТ-001", "location_id": cab, "next_service": (today - timedelta(days=3)).isoformat()})
e2 = a.save_equipment({"name": "Автоклав", "inv_number": "СТ-002", "next_service": (today + timedelta(days=20)).isoformat()})
e3 = a.save_equipment({"name": "Компрессор", "inv_number": "СТ-003", "next_service": (today + timedelta(days=200)).isoformat()})

# ------------------------------------------------------- inventory as a list --
refuses("nothing checked", lambda: a.equipment_inventory_batch([]), "Отметьте")
r = a.equipment_inventory_batch([{"id": e1, "found": True, "condition": "service", "comment": "царапина"},
                                 {"id": e2, "found": False}, {"id": e3, "found": True}])
check("batch: counts", r == {"done": 3, "diffs": 1, "not_found": 1}, r)
check("batch: the card takes the condition seen", a.equipment(e1)["condition"] == "service")
check("batch: e3 unchanged", a.equipment(e3)["condition"] == "ok")
log = a.equipment_inventory_log()
check("log: three checks", len(log) == 3, len(log))
by = {x["equipment_id"]: x for x in log}
check("log: not found", by[e2]["found"] is False and by[e2]["inv_number"] == "СТ-002")
check("log: differences", by[e1]["found"] and any("состояние" in x for x in by[e1]["diffs"]), by[e1])
check("log: nothing to say", by[e3]["found"] and not by[e3]["diffs"])
lst = {x["id"]: x for x in a.equipment_list()}
check("the list knows the last check", lst[e1]["last_inventory_date"] == today.isoformat() and lst[e2]["last_inventory_date"])

# ------------------------------------------------------- ТО и ремонт --
a.equipment_event({"equipment_id": e1, "kind": "service", "text": "Замена фильтров", "cost": 3000, "date": today.isoformat()})
a.equipment_event({"equipment_id": e2, "kind": "repair", "text": "Ремонт клапана", "cost": 12000, "date": (today - timedelta(days=10)).isoformat()})
a.equipment_event({"equipment_id": e3, "kind": "service", "text": "Давно", "cost": 999, "date": (today - timedelta(days=500)).isoformat()})
a.equipment_set({"id": e2, "status": "repair", "text": "не держит давление"})
sl = a.equipment_service_log()
check("due: overdue and within 60 days, the earliest first", [x["id"] for x in sl["due"]] == [e1, e2], [x["name"] for x in sl["due"]])
check("due: overdue marked", sl["due"][0]["due"] and sl["due"][0]["days"] == -3 and not sl["due"][1]["due"])
check("due: place by name", sl["due"][0]["location"] == "Кабинет 3", sl["due"][0])
texts = {x["text"] for x in sl["events"]}
check("events of the last year only", {"Замена фильтров", "Ремонт клапана"} <= texts and "Давно" not in texts
      and any(t.startswith("Отправлено на ремонт") for t in texts), texts)
check("costs", sl["cost"] == 15000 and sl["cost_service"] == 3000 and sl["cost_repair"] == 12000, sl)
check("in repair", [x["id"] for x in sl["in_repair"]] == [e2])
sl2 = a.equipment_service_log((today - timedelta(days=600)).isoformat(), today.isoformat())
check("a longer period takes the old one", sl2["cost"] == 15999, sl2["cost"])
refuses("a wrong date", lambda: a.equipment_service_log("вчера"))
summ = a.stock_summary()
check("summary: in repair", summ["eq_repair"] == 1 and summ["service_due"] == 1, summ)

# ------------------------------------------------------- over HTTP: the sections' rights --
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

code, st = call("api", "status", token=TD)
check("status: the badge «Пора на ТО»", code == 200 and st.get("eq_due") == 1, st.get("eq_due"))
code, _ = call("api", "equipment_service_log", token=TN)
check("nurse (stock_view) sees «ТО и ремонт»", code == 200, code)
code, _ = call("api", "equipment_inventory_log", token=TN)
check("nurse sees the history of checks", code == 200, code)
code, _ = call("api", "equipment_inventory_batch", [{"id": e3, "found": True}], token=TN)
check("nurse cannot check the equipment", code == 403, code)
code, _ = call("api", "equipment_inventory_batch", [{"id": e3, "found": True}], token=TM)
check("the stock manager (no «Оборудование») cannot either", code == 403, code)
code, r = call("api", "equipment_inventory_batch", [{"id": e3, "found": True}], token=TK)
check("the storekeeper («Оборудование») checks", code == 200 and r["done"] == 1, (code, r))
code, _ = call("api", "stock_inventory", {"lines": [{"material_id": "demo_m1", "actual": 5}]}, token=TN)
check("nurse: no count of materials", code == 403, code)
code, _ = call("api", "stock_scan", "Инв. № СТ-003", token=TK)
check("the scanner with «Оборудование»", code == 200, code)
code, sc = call("api", "stock_scan", "Инв. № СТ-003", token=TD)
check("the label's QR finds the piece", code == 200 and sc.get("equipment_id") == e3, sc)

srv.stop() if hasattr(srv, "stop") else None
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
