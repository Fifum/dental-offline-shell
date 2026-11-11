"""3.5 «Склад: автосписание, перемещения, себестоимость»: the services of a Dentist Plus visit in its usual shapes (service id,
nested service, code, title, the visit's title), drafts to confirm, the place by chair / branch / settings, never twice (also
by an invoice made here and across two computers that wrote off offline), reverting, skipping, services entered by hand,
the automatic mode only from the day it was switched on, places with balances and transfers (with checks), a write-off and
a count of one place, the place of an invoice's write-off, the cost of services (norms × prices + lab + doctor's percent)
with the month made, materials in the P&L by the stock, sync of the new tables, rights and the journal over HTTP, the UI."""
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
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import replica  # noqa: E402
import stock_auto  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402

UI = ROOT / "app" / "ui"


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
    except ValueError as e:
        check(name, text.lower() in str(e).lower(), str(e))
        return
    FAIL.append(f"{name}: no error")


T = date.today()
Y = (T - timedelta(days=1)).isoformat()
Y2 = (T - timedelta(days=2)).isoformat()
TD = T.isoformat()


def setup(d):
    """Doctors, a price list from Dentist Plus, materials with norms and a receipt."""
    d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}, {"id": 2, "lname": "Сидорова", "fname": "Анна"}])
    with d.tx() as c:
        for sid, code, title, price in (("api_101", "K-101", "Лечение кариеса", 5000), ("api_102", "K-102", "Удаление зуба", 3000),
                                        ("api_103", "K-103", "Консультация", 1000)):
            c.execute("INSERT OR REPLACE INTO services VALUES(?,?,?,?,?,?,1)", (sid, code, title, price, "Терапия", "api"))
        for pid, name in (("p1", "Иванов Иван"), ("p2", "Смирнова Ольга"), ("p7", "Кузнецов Пётр")):
            c.execute("INSERT OR REPLACE INTO patients(id, name, local) VALUES(?,?,0)", (pid, name))


def visit(vid, day, status="Завершён", services=None, title="", patient="p1", doctor=1, branch=1, chair="Кресло 1", hour=10, **extra):
    raw = {"id": vid, "patient_id": patient, "doctor_id": doctor, "branch_id": branch, "start": f"{day} {hour:02d}:00:00",
           "end": f"{day} {hour:02d}:30:00", "status": status, "title": title, "chair": chair, **extra}
    if services is not None:
        raw["services"] = services
    return {"id": vid, "patient_id": patient, "doctor_id": str(doctor), "branch_id": str(branch), "start": f"{day} {hour:02d}:00:00",
            "end": f"{day} {hour:02d}:30:00", "status": status, "title": title, "raw": raw}


VISITS = [
    visit("v1", Y, services=[{"service_id": 101, "count": 2}]),                                    # id of the service, 2 times
    visit("v2", Y, services=None, items=[{"id": 9, "service": {"id": 102, "title": "Удаление"}}], chair="", branch=2, hour=11),
    visit("v3", Y, status="Пришёл", title="Консультация", hour=12),                                # by the visit's title, no norms
    visit("v4", Y2, title="Что-то своё", patient="p2", hour=9),                                     # nothing from Dentist Plus
    visit("v5", Y, status="Отменён", services=[{"service_id": 101}], hour=13),                      # cancelled — not listed
    visit("v6", (T + timedelta(days=1)).isoformat(), services=[{"service_id": 101}]),              # tomorrow — not listed
    visit("v7", Y, services=[{"service_id": 101}], patient="p7", hour=14),                          # billed here the same day
    visit("v8", Y, services=[{"code": "K-102", "name": "что угодно"}], patient="p2", hour=15),       # by the code
    visit("v9", Y, services=[{"title": "Неизвестная услуга"}], patient="p2", hour=16),              # not in the price list
]

d = dbm.DB()
setup(d)
auth.Auth(d)  # the action journal
a = Api(d, W())
d.replace_visits((T - timedelta(days=5)).isoformat(), (T + timedelta(days=5)).isoformat(), VISITS)
M1 = a.save_material({"name": "Композит", "unit": "г", "price": 50})
M2 = a.save_material({"name": "Перчатки", "unit": "пара", "price": 10})
a.save_norms("api_101", [{"material_id": M1, "qty": 1}, {"material_id": M2, "qty": 2}])
a.save_norms("api_102", [{"material_id": M2, "qty": 3}])
a.stock_receive({"number": "1", "lines": [{"material_id": M1, "qty": 100, "price": 50}, {"material_id": M2, "qty": 100, "price": 10}]})
bal = lambda mid, loc=None: next(m["balance"] for m in a.materials(location=loc) if m["id"] == mid)  # noqa: E731

# ------------------------------------------------------------------ the services of a visit as Dentist Plus gives them
rs = stock_auto.raw_services
check("service id + count", rs({"services": [{"service_id": 5, "count": 2}]}) == [{"dp_id": "5", "line_id": "", "code": "", "title": "", "qty": 2.0}])
check("nested service", rs({"items": [{"service": {"id": 7, "title": "X"}, "qty": "1,5"}]})[0]["dp_id"] == "7"
      and rs({"items": [{"service": {"id": 7}, "qty": "1,5"}]})[0]["qty"] == 1.5)
check("inside an invoice", rs({"invoice": {"items": [{"code": "A1"}]}})[0]["code"] == "A1"
      and rs({"invoices": [{"services": [{"name": "Y"}]}]})[0]["title"] == "Y")
check("a plain list of names", rs({"works": ["Пломба"]})[0]["title"] == "Пломба")
check("nothing or garbage", rs({}) == [] and rs("not json") == [] and rs(None) == [] and rs({"services": "x"}) == [])

# ------------------------------------------------------------------ places
refuses("place needs a name", lambda: a.stock_location_save({"name": " "}), "название")
refuses("the main stock exists", lambda: a.stock_location_save({"name": "Основной склад"}), "уже есть")
CAB1 = a.stock_location_save({"name": "Кабинет 1", "kind": "cabinet", "chair": "Кресло 1", "branch_id": "1"})
NORTH = a.stock_location_save({"name": "Филиал Север", "kind": "branch", "branch_id": "2"})
refuses("a name once", lambda: a.stock_location_save({"name": "кабинет 1"}), "уже есть")
locs = a.stock_locations()
check("main first, then the places", [x["name"] for x in locs] == ["Основной склад", "Кабинет 1", "Филиал Север"], [x["name"] for x in locs])
check("everything is in the main stock", locs[0]["items"] >= 2 and locs[1]["items"] == 0 and locs[1]["value"] == 0, locs[:2])

# ------------------------------------------------------------------ transfers
refuses("same place", lambda: a.stock_transfer({"from_id": "", "to_id": "", "lines": [{"material_id": M1, "qty": 1}]}), "разные")
refuses("more than the place has", lambda: a.stock_transfer({"from_id": CAB1, "to_id": "", "lines": [{"material_id": M1, "qty": 1}]}), "нельзя")
refuses("zero", lambda: a.stock_transfer({"from_id": "", "to_id": CAB1, "lines": [{"material_id": M1, "qty": 0}]}), "больше нуля")
refuses("unknown place", lambda: a.stock_transfer({"from_id": "", "to_id": "nope", "lines": [{"material_id": M1, "qty": 1}]}), "не найдено")
U0 = stock_auto.stock_used(d, Y2, (T + timedelta(days=1)).isoformat())
TR = a.stock_transfer({"from_id": "", "to_id": CAB1, "lines": [{"material_id": M1, "qty": 10}, {"material_id": M2, "qty": 20}], "comment": "на неделю"})
check("transfer moves between places", bal(M1, "") == 90 and bal(M1, CAB1) == 10 and bal(M2, CAB1) == 20, (bal(M1, ""), bal(M1, CAB1)))
check("the clinic's balance does not change", bal(M1) == 100 and bal(M2) == 100)
doc = a.stock_doc(TR)
check("transfer document", doc["kind"] == "transfer" and doc["number"] == "1" and len(doc["moves"]) == 2
      and doc["location_name"] == "Основной склад" and doc["to_location_name"] == "Кабинет 1", doc)
check("transfer in the list", any(x["id"] == TR and x["lines"] == 2 and x["to_location_name"] == "Кабинет 1" for x in a.stock_docs("transfer")))
mv = a.stock_moves({"kind": "transfer", "location": CAB1})
check("moves of a place", len(mv) == 2 and all(x["qty"] > 0 and x["location_name"] == "Кабинет 1" for x in mv), mv)
check("transfers are not consumption", stock_auto.stock_used(d, Y2, (T + timedelta(days=1)).isoformat()) == U0
      and all(ln["material_id"] not in (M1, M2) for g in a.purchase_list()["groups"] for ln in g["lines"]))
refuses("write-off over the place", lambda: a.stock_write_off({"reason": "брак", "location_id": CAB1, "lines": [{"material_id": M1, "qty": 11}]}),
        "Кабинет 1")
a.stock_write_off({"reason": "брак", "location_id": CAB1, "lines": [{"material_id": M1, "qty": 1}]})
check("write-off from the place", bal(M1, CAB1) == 9 and bal(M1, "") == 90 and bal(M1) == 99)
r = a.stock_inventory({"location_id": CAB1, "lines": [{"material_id": M2, "actual": 18}]})
check("count of one place against its balance", r["diffs"] and r["diffs"][0]["book"] == 20 and bal(M2, CAB1) == 18 and bal(M2, "") == 80, r)
refuses("a place with materials is not closed", lambda: a.stock_location_delete(CAB1), "переместите")

# ------------------------------------------------------------------ the list of visits
with d.tx() as c:  # an invoice made here for the patient of v7 on that day: the invoice wrote the materials off
    c.execute("INSERT INTO invoices(id, patient_id, items, total, status, created_at, kind) VALUES(?,?,?,?,?,?,?)",
              ("inv7", "p7", "[]", 5000, "Выставлен", f"{Y} 14:40:00", "invoice"))
L = a.stock_visits({"from": Y2, "to": TD})
R = {r["id"]: r for r in L["rows"]}
check("finished visits only", set(R) == {"v1", "v2", "v3", "v4", "v7", "v8", "v9"}, sorted(R))
check("data from Dentist Plus", L["has_dp"] and L["settings"]["mode"] == "draft")
check("v1: by the service id, twice", R["v1"]["status"] == "draft" and R["v1"]["source"] == "dp"
      and {x["material_id"]: x["qty"] for x in R["v1"]["lines"]} == {M1: 2, M2: 4} and R["v1"]["total"] == 2 * 50 + 4 * 10, R["v1"])
check("v1: the cabinet of the chair", R["v1"]["location_id"] == CAB1 and R["v1"]["location_name"] == "Кабинет 1", R["v1"]["location_name"])
check("v2: nested service, the place of the branch", R["v2"]["status"] == "draft" and R["v2"]["location_id"] == NORTH
      and R["v2"]["lines"][0]["qty"] == 3, R["v2"])
check("v3: by the visit's title, no norms", R["v3"]["source"] == "title" and R["v3"]["status"] == "no_norms", R["v3"])
check("v4: nothing from Dentist Plus", R["v4"]["status"] == "no_services" and R["v4"]["source"] == "none")
check("v7: billed here — skipped", R["v7"]["status"] == "invoice", R["v7"]["status"])
check("v8: by the code", R["v8"]["status"] == "draft" and R["v8"]["services"][0]["service_id"] == "api_102")
check("v9: not in the price list", R["v9"]["status"] == "no_services" and R["v9"]["unknown"] == ["Неизвестная услуга"], R["v9"])
check("names", R["v1"]["patient_name"] == "Иванов Иван" and R["v1"]["doctor_name"])
check("counts", L["counts"]["draft"] == 3 and L["counts"]["invoice"] == 1, L["counts"])
check("filter by state", {r["id"] for r in a.stock_visits({"from": Y2, "to": TD, "status": "draft"})["rows"]} == {"v1", "v2", "v8"})
check("status: drafts for the tab", a.status().get("stock_visits") == 3 or a._sauto.draft_count() == 3, a.status().get("stock_visits"))

# ------------------------------------------------------------------ confirm, never twice, revert
res = a.stock_visit_confirm(["v1", "v7", "v4"])
check("confirmed one, the others left with reasons", res["done"] == ["v1"] and {x["id"]: x["why"] for x in res["left"]} ==
      {"v7": "Списано по счёту", "v4": "Нет услуг"}, res)
check("materials left the cabinet", bal(M1, CAB1) == 7 and bal(M2, CAB1) == 14 and bal(M1) == 97, (bal(M1, CAB1), bal(M2, CAB1)))
dv = a.stock_doc("V-v1")
check("the visit's document", dv and dv["kind"] == "visit" and len(dv["moves"]) == 2 and dv["total"] == 140 and dv["location_name"] == "Кабинет 1", dv)
mv = [x for x in a.stock_moves({"from": Y2, "to": TD, "kind": "service"}) if x["doc_id"] == "V-v1"]
check("moves «по приёму» at the visit's time", len(mv) == 2 and all(x["kind_title"] == "По приёму" and x["at"].startswith(Y) for x in mv), mv)
res = a.stock_visit_confirm("v1")
check("never twice", res["done"] == [] and res["left"][0]["why"] == "Списано" and bal(M1) == 97, res)
check("written off: who and when", a.stock_visit("v1")["status"] == "done" and a.stock_visit("v1")["auto"] == 0)
a._sauto.tick(force=True)  # the draft mode: the tick does nothing
check("draft mode: nothing by itself", a.stock_visit("v2")["status"] == "draft")
a.save_norms("api_101", [{"material_id": M1, "qty": 5}])  # norms changed after the write-off: what was written off stays
check("done keeps its lines", {x["material_id"]: x["qty"] for x in a.stock_visit("v1")["lines"]} == {M1: 2, M2: 4})
a.save_norms("api_101", [{"material_id": M1, "qty": 1}, {"material_id": M2, "qty": 2}])
r = a.stock_visit_revert("v1")
check("revert puts the materials back", r["status"] == "reverted" and bal(M1, CAB1) == 9 and bal(M1) == 99 and a.stock_doc("V-v1") is None, r)
refuses("revert twice", lambda: a.stock_visit_revert("v1"), "не списан")
refuses("revert a draft", lambda: a.stock_visit_revert("v2"), "не списан")
r = a.stock_visit_restore("v1")
check("back to drafts", r["status"] == "draft")
refuses("restore a draft", lambda: a.stock_visit_restore("v1"), "черновик")
check("confirm again after a revert", a.stock_visit_confirm(["v1"])["done"] == ["v1"] and bal(M1, CAB1) == 7)
check("one document, two moves", len([x for x in a.stock_moves({"kind": "service"}) if x["doc_id"] == "V-v1"]) == 2)

r = a.stock_visit_skip("v8", "пациент принёс свой материал")
check("skip", r["status"] == "skipped" and r["note"] == "пациент принёс свой материал" and r["base_status"] == "draft")
check("a skipped visit can still be written off by hand", a.stock_visit_confirm("v8")["done"] == ["v8"])
refuses("skip a written-off visit", lambda: a.stock_visit_skip("v8"), "отмените")
refuses("unknown visit", lambda: a.stock_visit_skip("nope"), "не найден")

# ------------------------------------------------------------------ services by hand
refuses("unknown service", lambda: a.stock_visit_save("v4", [{"service_id": "nope", "qty": 1}]), "не найдена")
r = a.stock_visit_save("v4", [{"service_id": "api_102", "qty": 2}], "")
check("services by hand make a draft", r["status"] == "draft" and r["source"] == "manual" and r["lines"][0]["qty"] == 6
      and r["location_id"] == "", r)
check("…in the main stock as chosen", a.stock_visit_confirm("v4")["done"] == ["v4"] and bal(M2, "") == 80 - 6, bal(M2, ""))
refuses("a written-off visit is not edited", lambda: a.stock_visit_save("v4", [{"service_id": "api_101"}]), "отмените")

# ------------------------------------------------------------------ the automatic mode
s = a.stock_auto_settings_save({"mode": "auto", "location": NORTH, "days": 3})
check("auto from today", s["mode"] == "auto" and s["auto_since"] == TD and s["location"] == NORTH and s["days"] == "3", s)
refuses("unknown default place", lambda: a.stock_auto_settings_save({"location": "nope"}), "не найдено")
d.replace_visits(Y2, TD, VISITS[:4] + VISITS[6:] + [
    visit("v10", TD, services=[{"service_id": 102}], patient="p2", hour=8, chair="Кресло 9", branch=5),   # finished today
    visit("v11", TD, status="Пришёл", services=[{"service_id": 102}], patient="p1", hour=9)])           # still in the chair
res = a._sauto.tick(force=True)
check("auto: today's finished visit", res and res["done"] == ["v10"], res)
v10 = a.stock_visit("v10")
check("auto: marked as automatic, the default place", v10["status"] == "done" and v10["auto"] == 1 and v10["done_by"] == "auto"
      and v10["location_id"] == NORTH and bal(M2, NORTH) == -3, (v10, bal(M2, NORTH)))
check("auto: yesterday's drafts stay drafts", a.stock_visit("v2")["status"] == "draft")
check("auto: a visit still in the chair waits", a.stock_visit("v11")["status"] == "draft")
check("auto: in the journal", d.one("SELECT COUNT(*) AS n FROM audit WHERE user_name=?", (stock_auto.AUTO_USER,))["n"] == 1)
check("auto: the tick waits 5 minutes", a._sauto.tick() is None)
a.stock_visit_revert("v10")
a._sauto.tick(force=True)
check("auto: a reverted visit is left alone", a.stock_visit("v10")["status"] == "reverted" and bal(M2, NORTH) == 0)
s = a.stock_auto_settings_save({"mode": "draft"})
s = a.stock_auto_settings_save({"mode": "auto"})
check("switching on again moves the day", s["auto_since"] == TD)
a.stock_auto_settings_save({"mode": "draft", "location": ""})

# ------------------------------------------------------------------ the place of an invoice's write-off
with d.tx() as c:
    c.execute("INSERT INTO local_visits(id, patient_id, doctor_id, start, \"end\", status, chair, created_at) VALUES(?,?,?,?,?,?,?,?)",
              ("lv1", "p1", "1", f"{TD} 15:00:00", f"{TD} 15:30:00", "Завершён", "Кресло 1", f"{TD} 09:00:00"))
iid = a.save_invoice({"patient_id": "p1", "visit_id": "lv1", "doctor_id": "1", "items": [{"service_id": "api_101", "title": "Лечение кариеса",
                                                                                          "qty": 1, "price": 5000}]})
im = d.q("SELECT location_id, qty FROM stock_moves WHERE invoice_id=?", (iid,))
check("an invoice writes off in the cabinet of its visit", im and all(x["location_id"] == CAB1 for x in im), im)

# ------------------------------------------------------------------ the cost of services
a.save_salary_scheme({"person": "d:1", "percent": 30, "base": "paid"})
a.save_salary_scheme({"person": "d:2", "percent": 20, "base": "paid"})
c0 = a.service_costs()
C = {r["service_id"]: r for r in c0["rows"]}
check("doctor's percent: the average of the schemes", c0["doctor_pct"] == 25 and c0["doctor_pct_src"] == "schemes", c0["doctor_pct"])
check("materials by the norm × price", C["api_101"]["materials"] == 50 + 2 * 10 and len(C["api_101"]["lines"]) == 2, C["api_101"])
check("cost and margin", C["api_101"]["doctor"] == 1250 and C["api_101"]["cost"] == 70 + 1250 and C["api_101"]["margin"] == 5000 - 1320
      and C["api_101"]["margin_pct"] == round(3680 * 100 / 5000, 1), C["api_101"])
check("no norms flagged", C["api_103"]["no_norms"] and c0["no_norms"] >= 1)
refuses("lab not negative", lambda: a.service_cost_save({"service_id": "api_101", "lab": -1}), "отрицательн")
refuses("percent up to 100", lambda: a.service_cost_save({"service_id": "api_101", "doctor_pct": 120}), "100")
refuses("unknown service", lambda: a.service_cost_save({"service_id": "x"}), "не найдена")
r = a.service_cost_save({"service_id": "api_101", "lab": 300, "other": 30, "doctor_pct": "10"})
check("own lab, other and percent", r["lab"] == 300 and r["other"] == 30 and r["doctor_pct"] == 10 and r["doctor_pct_own"]
      and r["cost"] == 70 + 300 + 30 + 500, r)
a.stock_cost_settings_save({"doctor_pct": "35"})
c1 = a.service_costs()
C = {r["service_id"]: r for r in c1["rows"]}
check("the clinic's percent for the others", c1["doctor_pct"] == 35 and c1["doctor_pct_src"] == "setting" and C["api_102"]["doctor"] == 1050
      and C["api_101"]["doctor_pct"] == 10, (c1["doctor_pct"], C["api_102"]["doctor"]))
refuses("clinic's percent up to 100", lambda: a.stock_cost_settings_save({"doctor_pct": "101"}), "100")
r = a.service_cost_save({"service_id": "api_101", "lab": 300, "other": 30, "doctor_pct": ""})
check("empty own percent — the clinic's", r["doctor_pct"] == 35 and not r["doctor_pct_own"])
mY = Y[:7]
cm = a.service_costs(mY)
C = {r["service_id"]: r for r in cm["rows"]}
made101 = (2 if mY == Y[:7] else 0) + (1 if TD[:7] == mY else 0)  # v1 (2 times) + the invoice of today
check("made in the month: visits written off and invoices", C["api_101"]["made"] == made101 and cm["made_from"]["visits"] >= 2, (C["api_101"]["made"], cm["made_from"]))
check("month totals", cm["revenue"] == round(sum(r["made"] * r["price"] for r in cm["rows"]), 2) and cm["margin"] == round(cm["revenue"] - cm["cost"], 2))

# ------------------------------------------------------------------ materials in the P&L
_, ma, mb = __import__("accounting")._month_range(mY)
a.save_expense({"category": "Материалы и закупки", "amount": 7000, "date": f"{mY}-01", "method": "Карта"})
p = a._fm().pnl(mY)
mat = next(x for x in p["variable"] if x["key"] == "materials")
used = stock_auto.stock_used(d, ma, mb)
check("by default the purchases", p["materials_mode"] == "expenses" and mat["amount"] == 7000 and p["materials_used"] == used, (mat, used))
check("the stock for comparison", any("Списано со склада" in x["name"] and x["amount"] == used for x in mat["detail"]), mat["detail"])
a.stock_cost_settings_save({"pnl_materials": "stock"})
p = a._fm().pnl(mY)
mat = next(x for x in p["variable"] if x["key"] == "materials")
check("by the stock: what was written off, purchases not twice", p["materials_mode"] == "stock" and mat["amount"] == used and used > 0
      and "не входят" in mat["detail"][0]["name"], (mat, used))
check("P&L by months follows", next(r for r in a.fin_pnl(mY, mY)["rows"] if r["key"] == "materials")["values"][0] == used)
a.stock_cost_settings_save({"pnl_materials": "nonsense"})
check("unknown mode — purchases", a._sauto.settings()["pnl_materials"] == "expenses")

# ------------------------------------------------------------------ sync: two computers, the same visit written off offline
names = {t.name for t in replica.TABLES}
check("new tables are synced", {"stock_locations", "stock_settings", "stock_visit_use", "service_costs"} <= names)
check("places before the moves", replica.ORDER["stock_locations"] < replica.ORDER["stock_docs"] < replica.ORDER["stock_moves"])
replica.install(d)
d2 = dbm.DB(Path(tempfile.mkdtemp()) / "b.db")
setup(d2)
a2 = Api(d2, W())
replica.install(d2)
replica.stamp(d, "A")
st = replica.apply_versions(d2, replica.changes_since(d, 0, 100000), "B")
check("everything arrives", st["conflicts"] == 0 and d2.one("SELECT COUNT(*) AS n FROM stock_locations")["n"] == 2, st)
d2.replace_visits(Y2, TD, [  # each computer loads the visits from Dentist Plus itself (the mirror is not synced)
    {"id": v["id"], "patient_id": v["patient_id"], "doctor_id": v["doctor_id"], "branch_id": v["branch_id"], "start": v["start"],
     "end": v["end"], "status": v["status"], "title": v["title"], "raw": json.loads(v["data"])}
    for v in d.q("SELECT id, patient_id, doctor_id, branch_id, start, \"end\", status, title, data FROM visits")])
check("the other computer sees the same", a2.stock_visit("v1")["status"] == "done" and a2.stock_visit("v2")["status"] == "draft"
      and a2.materials(location=CAB1) and next(m["balance"] for m in a2.materials(location=CAB1) if m["id"] == M1) == bal(M1, CAB1))
check("settings and costs arrive", a2.service_costs()["doctor_pct"] == 35 and a2._sauto.settings()["pnl_materials"] == "expenses")
# both write off v2 without the network
r1, r2 = a.stock_visit_confirm("v2"), a2.stock_visit_confirm("v2")
check("both wrote off offline", r1["done"] == ["v2"] and r2["done"] == ["v2"])
replica.stamp(d, "A")
replica.stamp(d2, "B")
s1 = replica.apply_versions(d2, replica.changes_since(d, 0, 100000), "B")
s2 = replica.apply_versions(d, replica.changes_since(d2, 0, 100000), "A")
n1 = d.one("SELECT COUNT(*) AS n FROM stock_moves WHERE doc_id='V-v2'")["n"]
n2 = d2.one("SELECT COUNT(*) AS n FROM stock_moves WHERE doc_id='V-v2'")["n"]
check("one write-off after the sync", n1 == 1 and n2 == 1, (n1, n2, s1, s2))
check("the balances agree", next(m["balance"] for m in a2.materials() if m["id"] == M2) == bal(M2), (bal(M2),))
check("no conflicts to show for the same write-off", not [c for c in replica.conflicts(d) if c["tbl"] in ("stock_moves", "stock_docs")],
      [(c["tbl"], c["field"]) for c in replica.conflicts(d)])

# ------------------------------------------------------------------ rights over HTTP and the journal
NEW = ("stock_locations", "stock_location_save", "stock_location_delete", "stock_transfer", "stock_auto_settings", "stock_auto_settings_save",
       "stock_visits", "stock_visit", "stock_visit_save", "stock_visit_confirm", "stock_visit_revert", "stock_visit_skip",
       "stock_visit_restore", "service_costs", "service_cost_save", "stock_cost_settings_save")
check("every new method has a right", all(m in auth.METHOD_PERMS for m in NEW), [m for m in NEW if m not in auth.METHOD_PERMS])
check("changes in the journal", {"stock_location_save", "stock_transfer", "stock_visit_confirm", "stock_visit_revert", "stock_visit_skip",
                                 "stock_visit_save", "stock_auto_settings_save", "service_cost_save", "stock_cost_settings_save"} <= set(auth.AUDITED))
check("reading not journaled", not {"stock_visits", "stock_visit", "service_costs", "stock_locations"} & set(auth.AUDITED))
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
d3 = dbm.DB(Path(tempfile.mkdtemp()) / "c.db")
setup(d3)
d3.replace_visits(Y2, TD, VISITS)
a3 = Api(d3, W())
srv = ClinicServer(a3, d3, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TDIR = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
tok = {}
for login, role in (("klad", "storekeeper"), ("asst", "assistant"), ("adm", "admin")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TDIR)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TDIR)
    tok[login] = call("auth", "login", login, "secret1")[1]["token"]
m3 = a3.save_material({"name": "Перчатки", "unit": "пара", "price": 10, "start_qty": 50})
a3.save_norms("api_101", [{"material_id": m3, "qty": 2}])
st_, body = call("api", "stock_visits", {"from": Y2, "to": TD}, token=tok["asst"])
check("assistant sees the list", st_ == 200 and any(r["id"] == "v1" for r in body["rows"]), (st_, str(body)[:200]))
check("assistant cannot write off", call("api", "stock_visit_confirm", ["v1"], token=tok["asst"])[0] == 403)
check("assistant cannot move", call("api", "stock_transfer", {}, token=tok["asst"])[0] == 403)
st_, body = call("api", "stock_visit_confirm", ["v1"], token=tok["klad"])
check("storekeeper writes off", st_ == 200 and body["done"] == ["v1"], (st_, body))
v1 = a3.stock_visit("v1")
check("by login, not by the local number", v1["done_by"] == "klad" and v1["done_name"] == "klad", v1)
st_, body = call("api", "stock_visit_revert", "v1", token=tok["klad"])
check("storekeeper reverts", st_ == 200 and body["status"] == "reverted")
check("storekeeper: no cost of services", call("api", "service_costs", token=tok["klad"])[0] == 403)
check("administrator without «Бухгалтерия»: no cost", call("api", "service_costs", token=tok["adm"])[0] == 403)
check("administrator cannot change the P&L mode", call("api", "stock_cost_settings_save", {"pnl_materials": "stock"}, token=tok["adm"])[0] == 403)
st_, body = call("api", "service_costs", token=TDIR)
check("director sees the cost", st_ == 200 and body["rows"], st_)
st_, body = call("api", "stock_location_save", {"name": "Кабинет 2", "chair": "Кресло 2"}, token=tok["klad"])
check("storekeeper adds a place", st_ == 200 and body)
au = call("auth", "audit_list", token=TDIR)[1]
for m in ("stock_visit_confirm", "stock_visit_revert", "stock_location_save"):
    check(f"journal: {m}", any(x["action"] == auth.AUDITED[m] and x["user_name"] == "klad" for x in au), [x["action"] for x in au][:6])
st_, body = call("api", "status", token=tok["klad"])
check("status shows the drafts to the storekeeper", st_ == 200 and "stock_visits" in body, list(body)[:40])
st_, body = call("api", "status", token=tok["asst"])
check("…not to the assistant", st_ == 200 and "stock_visits" not in body)
srv.stop()

# ------------------------------------------------------------------ the UI
html = (UI / "index.html").read_text(encoding="utf-8")
js = (UI / "stock-auto.js").read_text(encoding="utf-8") if (UI / "stock-auto.js").exists() else ""
check("version 3.5.0 or later", tuple(map(int, config.VERSION.split("."))) >= (3, 5, 0), config.VERSION)
check("stock-auto.js with the cache tag", f'<script src="stock-auto.js?v={config.VERSION}"></script>' in html)
check("no old cache tags", "?v=3.4.0" not in html)
check("stock tabs", all(f'data-k="{k}"' in html for k in ("visits", "places")))
check("cost tab in «Бухгалтерия»", 'data-k="cost"' in html)
check("screens", all(f"function {f}" in js for f in ("stockVisits", "editVisitServices", "stockPlaces", "editPlace", "openTransfer", "accCost",
                                                     "editServiceCost", "visitSettings")))
check("the screen says when Dentist Plus gives nothing", "нет данных из Dentist Plus" in js)
stock_js = (UI / "stock.js").read_text(encoding="utf-8")
check("tabs wired", "stockVisits" in stock_js and "stockPlaces" in stock_js and "openTransfer" in stock_js)
check("cost wired", "accCost" in (UI / "accounting.js").read_text(encoding="utf-8"))
notes = ROOT / "docs" / f"Что нового в версии {'.'.join(config.VERSION.split('.')[:2])}.txt"
check("what's new", notes.exists() and "Dental Desk" in notes.read_text(encoding="utf-8"), notes)
check("README section", "## Stock automation (3.5)" in (ROOT / "README.md").read_text(encoding="utf-8"))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  ✗", f)
sys.exit(1 if FAIL else 0)
