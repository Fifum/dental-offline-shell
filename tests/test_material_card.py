"""3.13 «Карточка материала»: the history of suppliers by each delivery (date, supplier, quantity, price, invoice, lot), the
summary per supplier, the last supplier and the best price, how long the stock lasts, a new material «от поставщика», what an
employee may do on the card (also over HTTP: a nurse sees the card but not as a storekeeper)."""
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


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
S = a._stock
day = lambda n: (date.today() - timedelta(days=n)).isoformat()  # noqa: E731

# ------------------------------------------- a material from three suppliers --
mid = S.save_material({"name": "Коффердам латексный", "code": "KD-1", "unit": "уп", "min_qty": 2, "price": 0})
s1 = S.save_supplier({"name": "ИП Марченко"})
s2 = S.save_supplier({"name": "ООО Иванова"})
s3 = S.save_supplier({"name": "Петров и К"})
S.receive({"supplier_id": s1, "number": "М-17", "date": day(40), "lines": [{"material_id": mid, "qty": 5, "price": 900, "lot": "L1", "expires": day(-200)}]})
S.receive({"supplier_id": s2, "number": "И-3", "date": day(20), "lines": [{"material_id": mid, "qty": 4, "price": 780}]})
S.receive({"supplier_id": s3, "number": "П-90", "date": day(5), "lines": [{"material_id": mid, "qty": 3, "price": 850}]})
S.receive({"supplier_id": s1, "number": "М-21", "date": day(2), "lines": [{"material_id": mid, "qty": 2, "price": 950}]})
S.receive({"date": day(1), "lines": [{"material_id": mid, "qty": 1, "price": 700}]})  # no supplier

m = a.material(mid)
sp = m["supplies"]
check("every delivery is a row", len(sp) == 5 and m["supply_count"] == 5, len(sp))
check("newest delivery first", [r["day"] for r in sp] == sorted([r["day"] for r in sp], reverse=True), [r["day"] for r in sp])
check("a row has supplier, qty, price, sum, invoice", sp[1]["supplier_name"] == "ИП Марченко" and sp[1]["qty"] == 2 and sp[1]["price"] == 950
      and sp[1]["sum"] == 1900 and sp[1]["doc_number"] == "М-21" and sp[1]["doc_id"], sp[1])
check("a delivery without a supplier is listed too", sp[0]["supplier_name"] == "" and sp[0]["supplier_id"] is None, sp[0])
check("lot and expiry of the delivery", sp[-1]["lot"] == "L1" and sp[-1]["expires"] == day(-200), sp[-1])
st = {g["supplier_name"]: g for g in m["supplier_stats"]}
check("summary per supplier (without the nameless one)", set(st) == {"ИП Марченко", "ООО Иванова", "Петров и К"}, list(st))
check("Marchenko: two deliveries, last 950, min 900", st["ИП Марченко"]["count"] == 2 and st["ИП Марченко"]["last_price"] == 950
      and st["ИП Марченко"]["min_price"] == 900 and st["ИП Марченко"]["qty"] == 7, st["ИП Марченко"])
check("average price per supplier", abs(st["ИП Марченко"]["avg_price"] - round((5 * 900 + 2 * 950) / 7, 2)) < 0.01, st["ИП Марченко"]["avg_price"])
check("suppliers sorted by the last delivery", [g["supplier_name"] for g in m["supplier_stats"]] == ["ИП Марченко", "Петров и К", "ООО Иванова"],
      [g["supplier_name"] for g in m["supplier_stats"]])
check("last supplier", m["last_supply"]["supplier_name"] == "ИП Марченко" and m["last_supply"]["price"] == 950 and m["last_supply"]["doc_number"] == "М-21",
      m["last_supply"])
check("best price = the cheapest last purchase", m["best_offer"]["supplier_name"] == "ООО Иванова" and m["best_offer"]["price"] == 780, m["best_offer"])
check("one supplier is marked best", [g["supplier_name"] for g in m["supplier_stats"] if g["best"]] == ["ООО Иванова"])
check("best offer agrees with the purchase list", S.offers()[mid][0]["supplier_name"] == "ООО Иванова")
check("the card keeps the old parts", m["balance"] == 15 and m["lot_list"]["lots"] and "norms" in m and "moves" in m and "by_location" in m)

# ------------------------------------------------------------ usage --
check("no usage yet", m["usage"]["used"] == 0 and m["usage"]["days_left"] is None, m["usage"])
S.write_off({"reason": "Использовано", "lines": [{"material_id": mid, "qty": 6}]})
m = a.material(mid)
check("usage over 60 days", m["usage"]["used"] == 6 and m["usage"]["days"] == 60 and abs(m["usage"]["daily"] - 0.1) < 1e-9, m["usage"])
check("days the stock lasts", m["usage"]["days_left"] == 90.0, m["usage"])

# ------------------------------------------- a new material «от поставщика» --
m2 = S.save_material({"name": "Ретракционная нить", "unit": "шт", "price": 420, "start_qty": 3, "supplier_id": s2, "doc_number": "И-5", "_user": "Тест"})
c2 = a.material(m2)
check("start stock from a supplier is a receipt", c2["balance"] == 3 and len(c2["supplies"]) == 1 and c2["supplies"][0]["supplier_name"] == "ООО Иванова"
      and c2["supplies"][0]["doc_number"] == "И-5" and c2["supplies"][0]["price"] == 420, c2["supplies"])
check("no inventory move for it", not [x for x in c2["moves"] if x["kind"] == "inventory"])
m3 = S.save_material({"name": "Без поставщика", "unit": "шт", "price": 10, "start_qty": 2})
c3 = a.material(m3)
check("start stock without a supplier stays «Начальный остаток»", c3["balance"] == 2 and not c3["supplies"]
      and c3["moves"][0]["kind"] == "inventory", c3["moves"])
m4 = S.save_material({"name": "Чужой поставщик", "unit": "шт", "start_qty": 2, "supplier_id": "S-нет"})
check("an unknown supplier is ignored", a.material(m4)["balance"] == 2 and not a.material(m4)["supplies"])
S.save_material({"id": m2, "name": "Ретракционная нить №0", "unit": "шт", "price": 420, "start_qty": 5, "supplier_id": s1})
check("editing never adds stock", a.material(m2)["balance"] == 3)

# ------------------------------------------------------ removed material --
S.delete_material(m3)
check("a removed material still opens with its history", a.material(m3) and not a.material(m3)["active"] and a.material(m3)["moves"])

# --------------------------------------------------------- rights, HTTP --
check("local: the director may do everything", a.material(mid)["can"] == {"edit": True, "ops": True, "direct": True, "photo": True}, a.material(mid)["can"])
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
for login, role in (("nurse", "nurse"), ("keeper", "storekeeper"), ("doc", "doctor")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TN = call("auth", "login", "nurse", "secret1")[1]["token"]
TK = call("auth", "login", "keeper", "secret1")[1]["token"]
TDoc = call("auth", "login", "doc", "secret1")[1]["token"]
code, mn = call("api", "material", mid, token=TN)
check("nurse: opens the card with the suppliers", code == 200 and len(mn["supplies"]) == 5 and mn["best_offer"], code)
check("nurse: may take deliveries and use, not edit, not at once", mn["can"] == {"edit": False, "ops": True, "direct": False, "photo": True}, mn.get("can"))
code, mk = call("api", "material", mid, token=TK)
check("storekeeper: edits and writes off at once", code == 200 and mk["can"]["edit"] and mk["can"]["direct"], mk.get("can"))
check("only «Бухгалтерия» gets the documents balance", "balance_doc" not in mk and "balance_doc" in call("api", "material", mid, token=TD)[1])
code, md = call("api", "material", mid, token=TDoc)
check("a doctor (only «Склад: просмотр») sees the card read-only", code == 200 and md["can"] == {"edit": False, "ops": False, "direct": False, "photo": False},
      (code, md.get("can")))
srv.stop() if hasattr(srv, "stop") else None

# ------------------------------------------------------------ the UI --
js = (ROOT / "app" / "ui" / "stock-matcard.js").read_text(encoding="utf-8")
html = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("the card script is on the page after the equipment card", html.index("stock-eqcard.js") < html.index("stock-matcard.js"))
check("openMaterial lives only in the card script", "function openMaterial" in js
      and "function openMaterial" not in (ROOT / "app" / "ui" / "stock.js").read_text(encoding="utf-8"))
for part in ("История поставок", "Последний поставщик", "Лучшая цена", "Партии и сроки", "Нормы по услугам", "Движение", "Остаток по местам"):
    check(f"UI: {part}", part in js)

print(f"OK: {OK[0]} FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
