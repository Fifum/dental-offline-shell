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

# ============================================== 3.14: the card by the mockup --
import barcodes  # noqa: E402
import replica  # noqa: E402
import stock as stockm  # noqa: E402
import auth  # noqa: E402

# numbers «МТ-…»: the materials there were got them once, in the order they were made; a new one goes on
nums = [r["number"] for r in d.q("SELECT number FROM materials ORDER BY COALESCE(created_at,''), rowid")]
check("every material has a number", all(nums) and len(set(nums)) == len(nums), nums[:5])
n1 = S.save_material({"name": "Filtek Bulk Fill", "unit": "шт", "price": 1950, "min_qty": 5})
n2 = S.save_material({"name": "Filtek Z250", "unit": "шт", "price": 1800})
r1, r2 = d.one("SELECT number FROM materials WHERE id=?", (n1,))["number"], d.one("SELECT number FROM materials WHERE id=?", (n2,))["number"]
check("a new material gets the next number", r1.startswith("МТ-") and int(r2[3:]) == int(r1[3:]) + 1, (r1, r2))
try:
    S.save_material({"name": "Дубль", "number": r1})
    check("duplicate number refused", False)
except ValueError:
    check("duplicate number refused", True)
tmp = tempfile.mkdtemp()
od = dbm.DB(os.path.join(tmp, "old.db"))
od.conn.executescript("""CREATE TABLE materials(id TEXT PRIMARY KEY, code TEXT, name TEXT, unit TEXT, category TEXT, min_qty REAL DEFAULT 0,
    price REAL DEFAULT 0, barcode TEXT, comment TEXT, active INTEGER DEFAULT 1, created_at TEXT);
    INSERT INTO materials(id, name, created_at) VALUES('M-b', 'Второй', '2025-02-01 10:00:00'), ('M-a', 'Первый', '2025-01-01 10:00:00');""")
stockm.Stock(od)
check("old materials numbered by the time they were made", [r["number"] for r in od.q("SELECT number FROM materials ORDER BY id")] == ["МТ-0001", "МТ-0002"],
      od.q("SELECT id, number FROM materials"))
stockm.Stock(od)
check("numbering runs once", od.one("SELECT COUNT(DISTINCT number) AS n FROM materials")["n"] == 2)
od.conn.execute("INSERT INTO materials(id, name, created_at) VALUES('M-c', 'От старой версии', '2024-01-01 10:00:00')")
stockm.Stock(od)
check("a material without a number (from an old computer) gets the next one", od.one("SELECT number FROM materials WHERE id='M-c'")["number"] == "МТ-0003")

# the new details, and a partial save never wipes them
S.save_material({"id": n1, "name": "Filtek Bulk Fill (универсальный композит)", "manufacturer": "3M", "description": "Композит светового отверждения",
                 "form": "Шприц 4 г", "shelf_life": "2 года", "storage": "+15…+25 °C, защищать от света", "code": "4862A2",
                 "category": "Пломбировочные материалы", "unit": "шт", "price": 1950, "min_qty": 5})
S.save_material({"id": n1, "name": "Filtek Bulk Fill (универсальный композит)", "barcode": ""})
m = a.material(n1)
check("details kept by a partial save", m["manufacturer"] == "3M" and m["form"] == "Шприц 4 г" and m["storage"].startswith("+15")
      and m["description"] and m["code"] == "4862A2" and m["min_qty"] == 5 and m["number"] == r1, {k: m[k] for k in ("manufacturer", "form", "code", "min_qty")})

# the four fields saved at once
a.material_set(n1, "opt_qty", "20")
a.material_set(n1, "lead_days", 3)
a.material_set(n1, "supplier_id", s2)
a.material_set(n1, "min_qty", 5)
m = a.material(n1)
check("quick fields saved", m["opt_qty"] == 20 and m["lead_days"] == 3 and m["supplier_id"] == s2 and m["supplier"]["name"] == "ООО Иванова", m["supplier"])
for bad in (("price", 1), ("supplier_id", "S-нет"), ("opt_qty", "abc")):
    try:
        a.material_set(n1, *bad)
        check(f"material_set refuses {bad}", False)
    except ValueError:
        check(f"material_set refuses {bad}", True)
a.material_set(n1, "supplier_id", "")
check("the main supplier may be cleared", a.material(n1)["supplier_id"] is None)
a.material_set(n1, "supplier_id", s2)

# reserve (the cabinets' requests), in transit (the orders), free stock and coverage
S.receive({"supplier_id": s2, "date": day(40), "lines": [{"material_id": n1, "qty": 12, "price": 1900}]})
S.receive({"supplier_id": s1, "date": day(200), "lines": [{"material_id": n1, "qty": 10, "price": 2000}]})
S.write_off({"reason": "Использовано", "date": day(10), "lines": [{"material_id": n1, "qty": 4}]})
S.write_off({"reason": "Расход в лечении", "date": day(15), "lines": [{"material_id": n1, "qty": 2}]})
S.write_off({"reason": "Брак", "date": day(400), "lines": [{"material_id": n1, "qty": 1}]})  # older than a year
rq = a._sflow.save_request({"lines": [{"material_id": n1, "qty": 5}], "send": True}, "nurse", "Медсестра", True)
a._sflow.save_request({"lines": [{"material_id": n1, "qty": 7}]}, "nurse", "Медсестра", True)  # a draft reserves nothing
m = a.material(n1)
check("reserve = open requests", m["reserve"] == 5, m["reserve"])
check("free = balance − reserve", m["balance"] == 15 and m["free"] == 10, (m["balance"], m["free"]))
check("monthly use from 60 days", abs(m["monthly"] - 3.0) < 1e-9, m["monthly"])
check("coverage by the free stock", m["cover_days"] == 100.0 and m["cover_pct"] == 50.0, (m["cover_days"], m["cover_pct"]))
check("status in stock", list(m["status"]) == ["ok", "В наличии"], m["status"])
check("weighted purchase price of 12 months", m["avg_price"] == round((12 * 1900 + 10 * 2000) / 22, 2), m["avg_price"])
check("unit cost is the price it is written off at", m["unit_cost"] == m["price"], m["unit_cost"])
check("use in 30 days", m["used30"] == 6, m["used30"])
check("12 months of use", len(m["use_months"]) == 12 and m["use_months"][-1]["month"] == date.today().strftime("%Y-%m"))
check("use split: write-off and treatment", m["use_total"]["writeoff"] == 4 and m["use_total"]["treatment"] == 2 and m["use_total"]["service"] == 0,
      m["use_total"])
oid = a.stock_order_save({"supplier_id": s2, "lines": [{"material_id": n1, "qty": 10, "price": 1900}]})
o = a.stock_order(oid)
check("an order: number, status, expected = day + delivery term", o["number"].startswith("З-") and o["status"] == "ordered"
      and o["expected"] == (date.today() + timedelta(days=3)).isoformat() and o["total"] == 19000, o)
m = a.material(n1)
check("in transit from the open order", m["in_transit"] == 10 and [x["id"] for x in m["orders"]] == [oid], m["in_transit"])
pl = S.purchase_list()
check("ordered stock is not ordered again", not any(ln["material_id"] == n1 for g in pl["groups"] for ln in g["lines"]))
did = a.stock_receive({"supplier_id": s2, "order_id": oid, "lines": [{"material_id": n1, "qty": 4, "price": 1900}]})
o = a.stock_order(oid)
check("a receipt by the order: partly received", o["status"] == "partial" and o["lines"][0]["received"] == 4 and o["lines"][0]["left"] == 6
      and o["doc_ids"] == [did], o["status"])
check("in transit goes down", a.material(n1)["in_transit"] == 6)
a.stock_receive({"supplier_id": s2, "order_id": oid, "lines": [{"material_id": n1, "qty": 6, "price": 1900}]})
check("received in full closes it", a.stock_order(oid)["status"] == "received" and a.material(n1)["in_transit"] == 0)
try:
    a.stock_receive({"order_id": oid, "lines": [{"material_id": n1, "qty": 1}]})
    check("a closed order takes no receipt", False)
except ValueError:
    check("a closed order takes no receipt", True)
check("the failed receipt left no stock", a.material(n1)["balance"] == 25, a.material(n1)["balance"])
o2 = a.stock_order_save({"supplier_id": s1, "lines": [{"material_id": n1, "qty": 3, "price": 2000}], "expected": day(2)})
check("late order marked", a.stock_order(o2)["late"])
check("open orders listed first", a.stock_orders()["orders"][0]["id"] == o2)
a.stock_order_cancel(o2)
check("a cancelled order is not on its way", a.stock_order(o2)["status"] == "cancelled" and a.material(n1)["in_transit"] == 0)

# the purchase list: the optimal stock, the delivery term and the main supplier
pm = S.save_material({"name": "Анестетик Ультракаин", "unit": "уп", "price": 300, "min_qty": 2, "opt_qty": 9, "lead_days": 30, "supplier_id": s3})
S.receive({"supplier_id": s1, "date": day(50), "lines": [{"material_id": pm, "qty": 8, "price": 280}]})
S.write_off({"reason": "Использовано", "date": day(5), "lines": [{"material_id": pm, "qty": 3}]})  # 5 left, 0.05 a day → 100 days
pl = S.purchase_list()
check("not ordered while it lasts longer than the delivery term", not any(x["material_id"] == pm for g in pl["groups"] for x in g["lines"]))
S.write_off({"reason": "Использовано", "date": day(4), "lines": [{"material_id": pm, "qty": 3}]})  # 2 left = the minimum
g = next(g for g in S.purchase_list()["groups"] if any(x["material_id"] == pm for x in g["lines"]))
ln = next(x for x in g["lines"] if x["material_id"] == pm)
check("ordered up to the optimal stock from the main supplier", ln["qty"] == 7 and g["supplier_id"] == s3 and ln["main"], (ln["qty"], g["supplier_name"]))

# documents and photos, analogs
PDF = "data:application/pdf;base64," + __import__("base64").b64encode(b"%PDF-1.4 test").decode()
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
m = a.material_doc_add(n1, "reg", "РУ.pdf", PDF)
check("a document added", [x["kind"] for x in m["docs"]] == ["reg"] and m["doc_kinds"][0]["count"] == 1, m["docs"])
m = a.material_doc_add(n1, "photo", "box.png", PNG)
check("the first photo becomes the main one and is in the gallery", m["photo_id"] and m["photos"] == [m["photo_id"]], m["photos"])
fo = a.material_doc_open(m["docs"][0]["id"])
check("a document opens", fo["url"].startswith("data:"), fo.get("mime"))
m = a.material_doc_delete(next(x["id"] for x in m["docs"] if x["kind"] == "photo"))
check("removing the photo clears the main one", not m["photo_id"] and len(m["docs"]) == 1)
al = a.material_analog_add(n1, n2)
check("an analog added both ways", [x["id"] for x in al] == [n2] and [x["id"] for x in a.material(n2)["analogs"]] == [n1])
check("an analog shows its balance and price", al[0]["price"] == 1800 and "balance" in al[0])
a.material_analog_add(n2, n1)
check("the pair is one row", d.one("SELECT COUNT(*) AS n FROM material_analogs")["n"] == 1)
a.material_analog_delete(n2, n1)
check("an analog removed", a.material(n1)["analogs"] == [])
a.material_analog_add(n1, n2)
check("and added again", len(a.material(n1)["analogs"]) == 1)
try:
    a.material_analog_add(n1, n1)
    check("a material is not its own analog", False)
except ValueError:
    check("a material is not its own analog", True)

# barcode, QR and the scanner by the number
q = a.material_qr(n1)
check("no barcode: the internal EAN-13 is shown", q["ean_internal"] and barcodes.valid_ean(q["ean"]) and q["ean"].startswith("29")
      and q["ean_svg"].startswith("<svg") and "mm" not in q["ean_svg"], q["ean"])
check("QR holds the number first", q["text"].splitlines()[0] == r1 and q["png"].startswith("data:image/png"), q["text"])
check("scanner: the internal EAN before it is written", (S.scan(q["ean"])["material"] or {}).get("id") == n1)
check("scanner: the number", (S.scan(r1)["material"] or {}).get("id") == n1)
check("scanner: the QR text", (S.scan(q["text"])["material"] or {}).get("id") == n1)
check("scanner: the number in small letters", (S.scan(r1.lower())["material"] or {}).get("id") == n1)
d.conn.execute("INSERT OR REPLACE INTO stock_settings(k, v) VALUES('phone_url', 'https://sklad.example.ru/app')")
d.conn.commit()
q2 = a.material_qr(n1)
check("QR is a link to the phone app", q2["link"] and "/m/" in q2["text"], q2["text"])
check("scanner: the link", (S.scan(q2["text"])["material"] or {}).get("id") == n1)
d.conn.execute("DELETE FROM stock_settings WHERE k='phone_url'")
d.conn.commit()
lb = a.material_label(n1)
check("printing writes the internal barcode down", d.one("SELECT barcode FROM materials WHERE id=?", (n1,))["barcode"] == q["ean"]
      and not lb["ean_internal"], lb["barcode"])
check("scanner: by the written barcode", (S.scan(q["ean"])["material"] or {}).get("id") == n1)
S.save_material({"id": n2, "name": "Filtek Z250", "barcode": "5901234123457"})
check("a box EAN is shown as it is", a.material_qr(n2)["ean"] == "5901234123457" and not a.material_qr(n2)["ean_internal"])

# statuses
z = S.save_material({"name": "Пустой", "unit": "шт"})
check("status: out of stock", list(a.material(z)["status"]) == ["bad", "Нет в наличии"])
S.receive({"lines": [{"material_id": z, "qty": 2, "price": 1, "lot": "Z", "expires": day(3)}]})
check("status: expired", list(a.material(z)["status"]) == ["bad", "Просрочено"], a.material(z)["status"])

# replication and the journal
for tb in ("stock_orders", "material_docs", "material_analogs"):
    check(f"{tb} replicated", tb in replica.BY_NAME and replica.ORDER[tb] > replica.ORDER["materials"])
check("catch-up 3.14 with the new columns", replica.CATCHUP == "3.14" and {"number", "opt_qty", "lead_days", "supplier_id", "manufacturer"}
      <= set(replica.CATCHUP_COLS["materials"]))
NEW = ["material_set", "material_qr", "material_label", "material_doc_add", "material_doc_delete", "material_doc_open", "material_analog_add",
       "material_analog_delete", "stock_orders", "stock_order", "stock_order_save", "stock_order_cancel"]
check("every new method has a right", all(k in auth.METHOD_PERMS for k in NEW), [k for k in NEW if k not in auth.METHOD_PERMS])
check("the changes are in the journal", all(k in auth.AUDITED for k in NEW if k not in ("material_qr", "material_doc_open", "stock_orders", "stock_order")))

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
for part in ("История поставок", "Лучшая цена", "Партии и сроки", "Остаток по местам",
             # 3.14: the mockup
             "Остатки и партии", "Расход", "Закупки", "Аналоги", "Документы", "История", "Штрихкод / QR-код", "Резервный остаток",
             "В пути (заказано)", "Средний расход", "Обеспеченность запасом", "Быстрые действия", "Сформировать закупку", "Поступление на склад",
             "Списание (расход)", "Перемещение", "Провести инвентаризацию", "Установить минимальный остаток", "Учёт и аналитика",
             "Себестоимость за единицу", "Средняя цена закупки", "Расход за месяц", "Остаток на", "Используется в услугах",
             "Минимальный остаток", "Оптимальный остаток", "Срок поставки", "Основной поставщик", "material_set", "mt-sticker"):
    check(f"UI: {part}", part in js)

stock_js = (ROOT / "app" / "ui" / "stock.js").read_text(encoding="utf-8")
check("the section has the tab «Закупки»", '["orders", "Закупки"' in stock_js and "orders: stockOrders" in stock_js)
check("the material form has the new fields", all(x in stock_js for x in ("mMan", "mDesc", "mForm", "mLife", "mStore", "mOpt", "mLead", "mNum")))
check("a receipt passes its order", "order_id: opts.order_id" in stock_js)

print(f"OK: {OK[0]} FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
