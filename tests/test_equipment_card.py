"""3.13 «Карточка оборудования»: new fields, the inventory number with a prefix, money only with «Бухгалтерия» (also over
HTTP: never sent, never overwritten), quick actions, inventory, replacement plan, disposal (write-off, sale, return),
documents and photos of the card, the chair hour, replication of the new table and columns."""
import base64
import io
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
import stock  # noqa: E402
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
replica.install(d)
S = a._stock
with d.tx() as c:
    c.execute("DELETE FROM equipment")
    c.execute("DELETE FROM equipment_events")

# ------------------------------------------------------- schema, constants --
cols = {r[1] for r in d.conn.execute("PRAGMA table_info(equipment)")}
check("new columns", {"manufacturer", "ownership", "condition", "location_id", "market_value", "replace_cost", "replace_date",
                      "reserve_monthly", "disposal_kind", "disposal_amount"} <= cols, cols)
check("events: data", "data" in {r[1] for r in d.conn.execute("PRAGMA table_info(equipment_events)")})
check("docs table", d.one("SELECT name FROM sqlite_master WHERE name='equipment_docs'") is not None)
check("8 main document kinds", len(stock.EQ_DOC_MAIN) == 8 and "other" not in stock.EQ_DOC_MAIN)

# ------------------------------------------------------- inventory numbers --
check("first number ОБ-001", S.next_inv() == "ОБ-001", S.next_inv())
e1 = a.save_equipment({"name": "Стоматологическая установка", "inv_number": "СТ-001", "price": 1500000, "in_service": "2023-01-15",
                       "useful_months": 120, "manufacturer": "Fona", "ownership": "own", "condition": "ok"})
check("prefix goes on", S.next_inv() == "СТ-002", S.next_inv())
e2 = a.save_equipment({"name": "Автоклав"})
check("auto number with the prefix", a.equipment(e2)["inv_number"] == "СТ-002")
a.save_equipment({"name": "Компрессор", "inv_number": "СТ-0099"})
check("the widest number keeps its width", S.next_inv() == "СТ-0100", S.next_inv())
with d.tx() as c:
    c.execute("DELETE FROM equipment WHERE inv_number LIKE 'СТ-0099'")
d2 = dbm.DB(Path(tempfile.mkdtemp()) / "old.db")
S2 = stock.Stock(d2)
S2.save_equipment({"name": "Старое", "inv_number": "00007"})
check("digits only — as before", S2.next_inv() == "00008", S2.next_inv())
refuses("number taken", lambda: a.save_equipment({"name": "X", "inv_number": "СТ-001"}), "занят")
check("edit keeps the number when the field is empty", a.equipment(e2)["inv_number"] == a.equipment(
    a.save_equipment({"id": e2, "name": "Автоклав", "inv_number": ""}))["inv_number"])

# ------------------------------------------------------------- the card --
e = a.equipment(e1)
check("titles", e["condition_title"] == "Исправно" and e["ownership_title"] == "Собственность клиники")
check("history: put on the register", any(x["kind"] == "created" for x in e["events"]))
check("amortization on", e["amort"]["on"] and e["amort"]["monthly"] == 12500, e["amort"])
check("chair hour default 154", e["chair_hours"] == 154 and e["chair_hour_cost"] == round(12500 / 154, 2), e["chair_hour_cost"])
check("documents 0/8", e["doc_count"] == 0 and e["doc_total"] == 8)
check("chair hours setting", a.equipment_settings_save({"chair_hours": 160})["chair_hours"] == 160 and a.equipment(e1)["chair_hours"] == 160)
refuses("chair hours range", lambda: a.equipment_settings_save({"chair_hours": 0}), "744")
card = a.equipment_card(e1)
check("card lists", card["can"]["money"] and card["can"]["edit"] and "faulty" in card["conditions"] and "lease" in card["ownerships"])

# ------------------------------------------------------- quick actions --
cab = a.stock_location_save({"name": "Кабинет № 1", "kind": "cabinet"})
r = a.equipment_set({"id": e1, "location_id": cab})
check("move to a place", r["location_id"] == cab and r["location"] == "Кабинет № 1" and r["events"][0]["kind"] == "move", r["events"][0])
r = a.equipment_set({"id": e1, "condition": "service"})
check("condition saved + history", r["condition"] == "service" and r["events"][0]["kind"] == "condition")
r = a.equipment_set({"id": e1, "ownership": "leasing"})
check("ownership saved", r["ownership"] == "leasing")
r = a.equipment_set({"id": e1, "status": "repair", "text": "не греет"})
check("to repair", r["status"] == "repair" and r["events"][0]["kind"] == "repair" and "не греет" in r["events"][0]["text"])
refuses("disposal is not a status", lambda: a.equipment_set({"id": e1, "status": "written_off"}), "выбытие")
refuses("unknown place", lambda: a.equipment_set({"id": e1, "location_id": "nope"}), "мест")
r = a.equipment_event({"equipment_id": e1, "kind": "repair", "text": "Замена ТЭНа", "cost": 8000, "back_in_use": True,
                       "next_service": "2026-12-15"})
check("back from repair", r["status"] == "in_use" and r["condition"] == "ok" and r["next_service"] == "2026-12-15")
check("service cost of the year", r["service_cost_year"] == 8000 and r["service_count_year"] == 2, r["service_cost_year"])

r = a.equipment_inventory({"id": e1, "found": True, "location": "Кабинет № 2", "condition": "service", "comment": "царапина"})
inv = r["last_inventory"]
check("inventory: differences", inv and inv["found"] and len(inv["diffs"]) == 2 and r["location"] == "Кабинет № 2", inv)
check("inventory: data kept", r["events"][0]["data"]["condition"] == "service")
r = a.equipment_inventory({"id": e1, "found": False})
check("inventory: not found", r["last_inventory"]["found"] is False and r["location"] == "Кабинет № 2")

refuses("replacement in the past", lambda: a.equipment_replace_plan({"id": e1, "replace_date": "2020-01-01"}), "будущем")
r = a.equipment_replace_plan({"id": e1, "replace_date": "2030-01-31", "replace_cost": 2000000, "market_value": 800000})
check("replacement plan + reserve worked out", r["replace_date"] == "2030-01-31" and r["reserve_monthly"] > 0, r.get("reserve_monthly"))

# ------------------------------------------------------- documents --
png = io.BytesIO()
from PIL import Image  # noqa: E402
Image.new("RGB", (40, 30), (20, 150, 140)).save(png, "PNG")
b64 = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
r = a.equipment_doc_add(e1, "photo", "установка.png", b64)
check("first photo is the main one", r["photo_id"] and r["photos"] == [r["photo_id"]], r["photos"])
pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
r = a.equipment_doc_add(e1, "contract", "договор.pdf", base64.b64encode(pdf).decode(), "Договор № 5")
doc = next(x for x in r["docs"] if x["kind"] == "contract")
check("pdf stored", doc["title"] == "Договор № 5" and doc["ext"] == ".pdf" and r["doc_count"] == 2, (doc, r["doc_count"]))
check("pdf opens", a.equipment_doc_open(doc["id"])["url"].startswith("data:application/pdf;base64,"))
refuses("not a document", lambda: a.equipment_doc_add(e1, "other", "x.exe", base64.b64encode(b"MZ...").decode()), "PDF")
ph = next(x for x in r["docs"] if x["kind"] == "photo")
r = a.equipment_doc_delete(ph["id"])
check("photo removed → no main photo", not r["photo_id"] and r["doc_count"] == 1)
check("doc file is a stock file", d.one("SELECT patient_id FROM patient_files WHERE id=?", (doc["file_id"],))["patient_id"] == "_stock")

# ------------------------------------------------------- disposal --
e3 = a.save_equipment({"name": "Лампа", "price": 50000, "in_service": "2025-01-10", "useful_months": 24})
r = a.equipment_dispose({"id": e3, "kind": "sale", "reason": "ООО Ромашка, договор 7", "amount": 20000, "date": "2026-11-20"})
check("sale", r["status"] == "written_off" and r["disposal_kind"] == "sale" and r["status_title"] == "Продано" and r["disposal_amount"] == 20000)
check("sale: no act number", not r["writeoff_act"])
refuses("disposed cannot change", lambda: a.equipment_set({"id": e3, "condition": "ok"}), "выбыло")
refuses("no docs after disposal", lambda: a.equipment_doc_add(e3, "other", "a.pdf", base64.b64encode(pdf).decode()), "выбыло")
e4 = a.save_equipment({"name": "Аренда", "ownership": "lease"})
refuses("return needs whom", lambda: a.equipment_dispose({"id": e4, "kind": "return", "reason": ""}), "кому")
r = a.equipment_dispose({"id": e4, "kind": "return", "reason": "Арендодателю по акту 3"})
check("return", r["status_title"] == "Возвращено владельцу" and r["events"][0]["kind"] == "disposal")
e5 = a.save_equipment({"name": "Скалер"})
r = a.write_off_equipment({"id": e5, "reason": "Износ", "commission": ["А", "Б"]})
check("write-off as before: act № 1", r["writeoff_act"] == "1" and r["status_title"] == "Списано", r["writeoff_act"])

# ------------------------------------------------------- money over HTTP --
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
for login, role in (("keeper", "storekeeper"), ("nurse", "nurse")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TK = call("auth", "login", "keeper", "secret1")[1]["token"]
TN = call("auth", "login", "nurse", "secret1")[1]["token"]

code, eq = call("api", "equipment", e1, token=TK)
check("keeper sees the card", code == 200 and eq["name"] == "Стоматологическая установка", code)
check("keeper: no money in the card", not ({"price", "amort", "market_value", "replace_cost", "reserve_monthly", "salvage",
                                            "residual", "chair_hour_cost", "amort_schedule"} & set(eq)) and eq["money"] is False, set(eq) & {"price", "amort"})
code, lst = call("api", "equipment_list", "", True, token=TK)
check("keeper: no money in the list", code == 200 and all("price" not in x and "amort" not in x for x in lst))
code, summ = call("api", "stock_summary", token=TK)
check("keeper: no money in the summary", code == 200 and "eq_cost" not in summ and "eq_residual" not in summ and summ["eq_money"] is False)
check("keeper: no depreciation report", call("api", "equipment_amortization", token=TK)[0] == 403)
check("keeper: no chair hours setting", call("api", "equipment_settings_save", {"chair_hours": 10}, token=TK)[0] == 403)
code, _ = call("api", "save_equipment", {"id": e1, "name": "Стоматологическая установка", "price": 1, "useful_months": 1, "salvage": 0,
                                        "market_value": 1, "replace_cost": 1, "reserve_monthly": 1, "model": "S300"}, token=TK)
e = a.equipment(e1)
check("keeper cannot overwrite the money", code == 200 and e["price"] == 1500000 and e["useful_months"] == 120 and e["replace_cost"] == 2000000
      and e["model"] == "S300", (code, e["price"], e["useful_months"], e["replace_cost"]))
code, new = call("api", "save_equipment", {"name": "Новый от кладовщика", "price": 999}, token=TK)
check("keeper's new equipment has no cost", code == 200 and a.equipment(new)["price"] == 0)
code, card = call("api", "equipment_card", e1, token=TK)
check("keeper: card without money right", code == 200 and card["can"]["money"] is False and card["can"]["edit"] is True)
code, _ = call("api", "equipment_set", {"id": e1, "condition": "faulty"}, token=TN)
check("nurse cannot change equipment", code == 403, code)
code, eq = call("api", "equipment", e1, token=TD)
check("director sees the money", code == 200 and eq["price"] == 1500000 and eq["amort"]["on"] and eq["money"] is True)

# ------------------------------------------------------- replication --
check("table replicated", "equipment_docs" in replica.BY_NAME and replica.ORDER["equipment_docs"] > replica.ORDER["equipment"])
check("catch-up bumped", tuple(map(int, replica.CATCHUP.split("."))) >= (3, 13), replica.CATCHUP)
check("catch-up lists the new columns", {"manufacturer", "condition", "location_id", "disposal_kind"} <= set(replica.CATCHUP_COLS["equipment"])
      and replica.CATCHUP_COLS["equipment_events"] == ["data"])
check("catch-up done", d.one("SELECT v FROM sync_state WHERE k='catchup'")["v"] == replica.CATCHUP)
check("docs are captured", d.one("SELECT COUNT(*) AS n FROM sync_dirty WHERE tbl='equipment_docs'")["n"] >= 1)
# a row synced by an older computer without the new columns gets them from the synced copy
row = d.one("SELECT * FROM equipment WHERE id=?", (e2,))
with d.tx() as c:
    c.execute("UPDATE equipment SET manufacturer=NULL WHERE id=?", (e2,))
    c.execute("DELETE FROM sync_dirty WHERE tbl='equipment'")
    c.execute("INSERT OR REPLACE INTO sync_rows(tbl, k, ver, base) VALUES('equipment', ?, '1', ?)",
              (json.dumps([e2]), json.dumps({**row, "manufacturer": "W&H", "condition": "faulty"})))
    c.execute("UPDATE sync_state SET v='3.10' WHERE k='catchup'")
replica.install(d)
check("catch-up fills the empty column", d.one("SELECT manufacturer FROM equipment WHERE id=?", (e2,))["manufacturer"] == "W&H")

# the scripts of the screen share one global scope: a name declared twice stops the later script entirely
import re  # noqa: E402
seen = {}
for f in sorted((ROOT / "app" / "ui").glob("*.js")):
    for m in re.finditer(r"^(?:const|let|class|(?:async\s+)?function)\s+([A-Za-z_$][\w$]*)", f.read_text(encoding="utf-8"), re.M):
        seen.setdefault(m[1], []).append(f.name)
dups = {k: v for k, v in seen.items() if len(v) > 1}
check("no global name declared twice in the screen scripts", not dups, dups)

srv.stop() if hasattr(srv, "stop") else None
print("\n".join("FAIL " + f for f in FAIL))
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
sys.exit(1 if FAIL else 0)
