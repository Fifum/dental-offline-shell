"""Stock, block 5: lots and expiry dates (FEFO), expired write-off, purchase list with the cheapest supplier, barcode scanner."""
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
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import db as dbm  # noqa: E402
import demo  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402
from stock import parse_scan  # noqa: E402


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


day = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731
d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
mat = lambda mid: next(m for m in a.materials() if m["id"] == mid)  # noqa: E731

# --- demo: one expired lot, two expiring soon, barcodes
s = a.stock_summary()
check("demo expired counted", s["expired"] == 1 and s["expiring"] == 2, s)
check("demo alerts", s["alerts"] >= s["low"] + 1, s)
check("demo expiring filter", {m["id"] for m in a.materials(only_expiring=True)} == {"demo_m1", "demo_m4", "demo_m5"})
check("demo barcode", len(mat("demo_m8")["barcode"]) == 13)
demo.ensure_stock_lots(a._stock)  # second run does nothing
check("demo lots once", d.one("SELECT COUNT(*) AS n FROM stock_lots")["n"] == 5)

# --- receipt with lots: FEFO
mid = a.save_material({"name": "Анестетик тест", "unit": "карп", "min_qty": 10, "price": 50, "start_qty": 5})  # 5 without a lot
sid1 = a.save_supplier({"name": "Альфа"})
sid2 = a.save_supplier({"name": "Бета"})
a.stock_receive({"supplier_id": sid1, "lines": [
    {"material_id": mid, "qty": 10, "price": 55, "lot": "L-OLD", "expires": day(-3)},     # expired
    {"material_id": mid, "qty": 10, "price": 55, "lot": "L-SOON", "expires": day(20)},    # soon
    {"material_id": mid, "qty": 10, "price": 55, "lot": "L-NEW", "expires": day(400)}]})  # fine
ll = a.stock_lots(mid)
check("three lots + undated stock", [g["lot"] for g in ll["lots"]] == ["L-OLD", "L-SOON", "L-NEW"] and ll["no_lot"] == 5, ll)
check("lot states", [g["state"] for g in ll["lots"]] == ["expired", "soon", "ok"])
m = mat(mid)
check("material flags", m["exp_state"] == "expired" and m["expired_qty"] == 10 and m["soon_qty"] == 10 and m["expires"] == day(-3), m)
check("material card has lots", len(a.material(mid)["lot_list"]["lots"]) == 3)
a.stock_receive({"lines": [{"material_id": mid, "qty": 2, "price": 55, "expires": "31.12.2099"}]})
check("lot from a date only, dd.mm.yyyy", any(g["expires"] == "2099-12-31" and g["lot"] == "" for g in a.stock_lots(mid)["lots"]))
a.stock_receive({"lines": [{"material_id": mid, "qty": 2, "price": 55, "expires": "2099-11"}]})
check("month only = its last day", any(g["expires"] == "2099-11-30" for g in a.stock_lots(mid)["lots"]))
refuses("bad expiry date", lambda: a.stock_receive({"lines": [{"material_id": mid, "qty": 1, "expires": "31.02.2027"}]}), "такой даты нет")
refuses("bad expiry text", lambda: a.stock_receive({"lines": [{"material_id": mid, "qty": 1, "expires": "скоро"}]}), "Годен до")
check("receipt without lot makes no lot", d.one("SELECT COUNT(*) AS n FROM stock_lots WHERE material_id=?", (mid,))["n"] == 5)

# use takes the earliest expiry first (the undated rest is used up before any lot)
pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]
a.save_norms("demo_0", [{"material_id": mid, "qty": 1}])
iid = a.save_invoice({"patient_id": pid, "items": [{"service_id": "demo_0", "title": "К", "price": 100, "qty": 12}]})
ll = {g["lot"]: g["left"] for g in a.stock_lots(mid)["lots"]}
check("FEFO: 5 undated + 7 of the expired lot used", a.stock_lots(mid)["no_lot"] == 0 and ll.get("L-OLD") == 3 and ll["L-SOON"] == 10, ll)
# editing the invoice deletes and re-creates its moves: the lots follow the ledger
a.save_invoice({"id": iid, "patient_id": pid, "items": [{"service_id": "demo_0", "title": "К", "price": 100, "qty": 2}]})
ll2 = a.stock_lots(mid)
check("lots recomputed after invoice edit", ll2["no_lot"] == 3 and {g["lot"]: g["left"] for g in ll2["lots"]}["L-OLD"] == 10, ll2)
a.delete_invoice(iid)
check("lots back after invoice delete", a.stock_lots(mid)["no_lot"] == 5)

# --- write off the expired
exp = [x for x in a.stock_expired() if x["material_id"] == mid]
check("expired lines", len(exp) == 1 and exp[0]["qty"] == 10 and exp[0]["lot"] == "L-OLD", exp)
refuses("lot write-off over lot", lambda: a.stock_write_off({"reason": "Истёк срок годности", "lines": [{**exp[0], "qty": 11}]}), "партия")
refuses("unknown lot", lambda: a.stock_write_off({"reason": "x", "lines": [{"material_id": mid, "qty": 1, "lot_id": 999999}]}), "Партия")
bal0 = mat(mid)["balance"]
wid = a.stock_write_off({"reason": "Истёк срок годности", "lines": exp})
doc = a.stock_doc(wid)
check("ordinary write-off doc", doc["kind"] == "writeoff" and doc["reason"] == "Истёк срок годности" and "L-OLD" in doc["moves"][0]["reason"], doc)
ll = a.stock_lots(mid)
check("expired lot gone, undated stock kept", "L-OLD" not in [g["lot"] for g in ll["lots"]] and ll["no_lot"] == 5 and ll["balance"] == bal0 - 10, ll)
check("material no longer expired", mat(mid)["exp_state"] == "soon")
check("nothing expired left for it", not [x for x in a.stock_expired() if x["material_id"] == mid])
a.stock_write_off({"reason": "Истёк срок годности", "lines": a.stock_expired()})  # the demo lot too
check("summary: no expired", a.stock_summary()["expired"] == 0)

# --- purchase list
# a material used 60 per 60 days (1 a day), minimum 5, 10 on hand -> 10 days left < 14 -> order
p = a.save_material({"name": "Перчатки тест", "unit": "пара", "min_qty": 5, "price": 10})
a.stock_receive({"supplier_id": sid1, "date": day(-50), "lines": [{"material_id": p, "qty": 40, "price": 12}]})
a.stock_receive({"supplier_id": sid2, "date": day(-40), "lines": [{"material_id": p, "qty": 20, "price": 9.5}]})
a.stock_receive({"supplier_id": sid1, "date": day(-30), "lines": [{"material_id": p, "qty": 10, "price": 11}]})  # Alpha's last price 11
d.conn.execute("INSERT INTO stock_moves(material_id, qty, price, kind, reason, at) VALUES(?,?,?,?,?,?)", (p, -60, 10, "service", "т", day(-5) + " 10:00:00"))
d.conn.execute("INSERT INTO stock_moves(material_id, qty, price, kind, reason, at) VALUES(?,?,?,?,?,?)", (p, -100, 10, "service", "давно", day(-90) + " 10:00:00"))
d.conn.execute("INSERT INTO stock_moves(material_id, qty, price, kind, reason, at) VALUES(?,?,?,?,?,?)", (p, 100, 10, "inventory", "т", day(-91) + " 10:00:00"))
d.conn.commit()
pl = a.purchase_list(30)
line = next((ln for g in pl["groups"] for ln in g["lines"] if ln["material_id"] == p), None)
grp = next((g for g in pl["groups"] if any(ln["material_id"] == p for ln in g["lines"])), None)
check("ordered: lasts < 14 days", line and line["daily"] == 1 and line["days_left"] == 10, line)
check("target = max(2·min, min + daily·30)", line and line["target"] == 35 and line["qty"] == 25, line)
check("cheapest supplier by last price", grp and grp["supplier_name"] == "Бета" and line["price"] == 9.5, grp and grp["supplier_name"])
check("other offers shown", line and [o["supplier_name"] for o in line["offers"]] == ["Бета", "Альфа"] and line["offers"][1]["price"] == 11, line and line["offers"])
check("group total", grp and abs(grp["total"] - sum(ln["sum"] for ln in grp["lines"])) < 0.01)
check("cover days used", a.purchase_list(60)["cover_days"] == 60 and next(ln for g in a.purchase_list(60)["groups"] for ln in g["lines"] if ln["material_id"] == p)["qty"] == 55)
check("bad cover days → 30", a.purchase_list("abc")["cover_days"] == 30)
# a material without use: ordered only at / below the minimum, target 2 × minimum, rounded up
q = a.save_material({"name": "Штифты тест", "unit": "уп", "min_qty": 2.5, "price": 300, "start_qty": 2})
ln = next(ln for g in a.purchase_list()["groups"] for ln in g["lines"] if ln["material_id"] == q)
check("below minimum, no use: ceil(2·min − have)", ln["qty"] == 3 and ln["why"] == "ниже минимума" and ln["days_left"] is None, ln)
check("no purchases yet → no supplier", any(g["supplier_id"] == "" and any(x["material_id"] == q for x in g["lines"]) for g in a.purchase_list()["groups"]))
r = a.save_material({"name": "Запас тест", "min_qty": 2, "start_qty": 50})
check("enough stock → not ordered", all(x["material_id"] != r for g in a.purchase_list()["groups"] for x in g["lines"]))
# expired stock does not count as usable
e = a.save_material({"name": "Гель тест", "min_qty": 3})
a.stock_receive({"lines": [{"material_id": e, "qty": 10, "lot": "G1", "expires": day(-1)}]})
ln = next((x for g in a.purchase_list()["groups"] for x in g["lines"] if x["material_id"] == e), None)
check("expired is not usable stock", ln and ln["usable"] == 0 and ln["expired_qty"] == 10 and ln["qty"] == 6, ln)

# --- scanner
refuses("duplicate barcode", lambda: a.save_material({"name": "Дубль", "barcode": mat("demo_m8")["barcode"]}), "уже указан")
hit = a.stock_scan(mat("demo_m8")["barcode"])
check("scan finds material", hit["material"] and hit["material"]["id"] == "demo_m8")
miss = a.stock_scan("2000000000017")
check("scan unknown → no material", miss["material"] is None and miss["barcode"] == "2000000000017")
new = a.save_material({"name": "Новый по штрихкоду", "barcode": miss["barcode"]})
check("material created with barcode is found", a.stock_scan("2000000000017")["material"]["id"] == new)
gs = "0104607000000083" + "17" + "271200" + "10" + "AB-12" + "\x1d" + "21" + "SER1"
pr = parse_scan(gs)
check("GS1 parsed", pr["gtin"] == "04607000000083" and pr["barcode"] == "4607000000083" and pr["lot"] == "AB-12" and pr["expires"] == "2027-12-31", pr)
check("GS1 with brackets", parse_scan("(01)04607000000083(17)280315(10)X9")["expires"] == "2028-03-15")
code8 = mat("demo_m8")["barcode"]
hit = a.stock_scan(f"]d201{'0' + code8}17{day(500)[2:4]}{day(500)[5:7]}{day(500)[8:10]}10LOT5")
check("GS1 DataMatrix finds the material by GTIN", hit["material"] and hit["material"]["id"] == "demo_m8" and hit["lot"] == "LOT5" and hit["expires"] == day(500), hit)
refuses("empty scan", lambda: a.stock_scan("  "), "Пустой")
# scan → receipt: lot and expiry from the code are stored
a.stock_receive({"lines": [{"material_id": "demo_m8", "qty": 3, "price": 9, "lot": hit["lot"], "expires": hit["expires"]}]})
check("scanned lot stored", any(g["lot"] == "LOT5" and g["left"] == 3 for g in a.stock_lots("demo_m8")["lots"]))

# --- badge and rights over HTTP
st = a.status()
check("status counters", "stock_exp" in st and "stock_alerts" in st and st["stock_alerts"] >= st["stock_low"], st.get("stock_alerts"))
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
call("auth", "register", {"name": "doc", "login": "doc", "password": "secret1"})
u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == "doc")
call("auth", "staff_save", {"id": u["id"], "role": "doctor", "status": "active"}, token=TD)
TDoc = call("auth", "login", "doc", "secret1")[1]["token"]
for meth, args in (("purchase_list", (30,)), ("stock_lots", ("demo_m1",)), ("stock_expired", ()), ("stock_scan", ("123",))):
    check(f"doctor may {meth}", call("api", meth, *args, token=TDoc)[0] == 200)
    check(f"no session → {meth} refused", call("api", meth, *args)[0] in (401, 403))
code, body = call("api", "stock_write_off", {"reason": "x", "lines": []}, token=TDoc)
check("doctor cannot write off", code == 403)
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
