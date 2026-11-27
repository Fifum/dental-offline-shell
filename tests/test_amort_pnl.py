"""3.14 «финотчёт правильнее»: the purchase of equipment is not a cost of its month («Покупка оборудования» stays in the cash
flow, out of the P&L); the P&L takes the depreciation every month and the book value less the sale when a piece leaves;
rented equipment and the founder's property are not depreciated; materials go in as they are written off, the household
goods into «Хозяйственные расходы»; old purchases written down as costs are found and moved in one go; the accounting summary
counts the same way; a new piece may write its payment down at once (only with «Бухгалтерия»)."""
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
import accounting  # noqa: E402
import db as dbm  # noqa: E402
import finreport  # noqa: E402
import stock  # noqa: E402
import stock_auto  # noqa: E402
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


def line(p, key, part="fixed"):
    return next((x for x in p[part] if x["key"] == key), None)


d = dbm.DB()
a = Api(d, W())

# ------------------------------------------------------- the defaults of 3.14 --
check("depreciation in the P&L by default", stock_auto.amort_in_pnl(d))
check("materials by the write-off by default", stock_auto.pnl_mode(d) == "stock")
check("switched once (fin_314)", d.one("SELECT v FROM stock_settings WHERE k='fin_314'")["v"] == "1")
check("a category of its own", accounting.CAPEX in accounting.CATEGORIES and accounting.CAPEX in a._acc.categories())
stock_auto.set_amort_in_pnl(d, False)
stock_auto.StockAuto(d, a._stock) if hasattr(stock_auto, "StockAuto") else None
check("a switch made by hand stays after a restart", not stock_auto.amort_in_pnl(d))
stock_auto.set_amort_in_pnl(d, True)
d2 = dbm.DB(Path(tempfile.mkdtemp()) / "old.db")
with d2.tx() as c:
    c.execute("CREATE TABLE IF NOT EXISTS stock_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT)")
    c.execute("INSERT INTO stock_settings(k, v) VALUES('pnl_amort','0'),('pnl_materials','expenses'),('split_313','1')")
Api(d2, W())
check("an old computer is switched on update", stock_auto.amort_in_pnl(d2) and stock_auto.pnl_mode(d2) == "stock")

# ------------------------------------------------------- buying a piece --
eq = a.save_equipment({"name": "Автоклав", "inv_number": "СТ-001", "price": 120000, "useful_months": 12,
                       "purchase_date": "2025-01-15", "pay": "Безналичный перевод"})
exp = a._acc.expenses("2025-01-01", "2025-01-31")
check("the payment is written down into «Покупка оборудования» on the purchase day",
      len(exp["rows"]) == 1 and exp["rows"][0]["category"] == accounting.CAPEX and exp["rows"][0]["date"] == "2025-01-15"
      and exp["rows"][0]["amount"] == 120000 and "СТ-001" in exp["rows"][0]["comment"], exp["rows"])
fm = a._fm() if hasattr(a, "_fm") else None
jan = fm.pnl("2025-01")
check("January: the purchase is not a cost", jan["fixed_total"] == 0 and not line(jan, accounting.CAPEX), jan["fixed"])
check("January: shown apart as an investment", jan["capex"] == 120000)
check("January: no depreciation yet (from the next month)", not line(jan, "amortization") and jan["amortization"] == 0)
feb = fm.pnl("2025-02")
am = line(feb, "amortization")
check("February: depreciation 10 000", am and am["amount"] == 10000 and feb["fixed_total"] == 10000, feb["fixed"])
check("depreciation detail by piece", am["detail"] and am["detail"][0]["name"].startswith("Автоклав (СТ-001)"), am.get("detail"))

# a second piece, rented: neither depreciated nor disposed in the P&L
rent = a.save_equipment({"name": "Компрессор в аренде", "price": 60000, "useful_months": 12, "purchase_date": "2025-01-10", "ownership": "lease"})
check("rented: not in the depreciation", fm.pnl("2025-02")["amortization"] == 10000)
rep = a.equipment_amortization("2025-01", "2025-03")
check("the depreciation report leaves the rented out", [x["id"] for x in rep["rows"]] == [eq] and rep["off_books"] == 1, rep["rows"])

# ------------------------------------------------------- disposal --
a.equipment_dispose({"id": eq, "kind": "sale", "date": "2025-06-20", "reason": "ООО «Ромашка», договор 5", "amount": 30000})
e = a.equipment(eq)
check("residual at the disposal: 5 months charged", e["residual"] == 70000, e["residual"])
jun = fm.pnl("2025-06")
dl = line(jun, "disposal")
check("June: the disposal = book value − sale", dl and dl["amount"] == 40000, jun["fixed"])
check("June: still the depreciation of June", line(jun, "amortization")["amount"] == 10000)
check("disposal detail says sold", "продано за 30 000" in dl["detail"][0]["name"], dl["detail"])
check("July: nothing more", fm.pnl("2025-07")["fixed_total"] == 0, fm.pnl("2025-07")["fixed"])
eq2 = a.save_equipment({"name": "Лампа", "price": 24000, "useful_months": 24, "purchase_date": "2025-01-05"})
a.equipment_dispose({"id": eq2, "kind": "writeoff", "date": "2025-03-10", "reason": "сгорела", "commission": ["А", "Б"]})
mar = fm.pnl("2025-03")
check("a write-off: the whole book value", line(mar, "disposal")["amount"] == 22000, line(mar, "disposal"))
a.equipment_dispose({"id": rent, "kind": "return", "date": "2025-04-01", "reason": "арендодателю по акту 1"})
check("a rented piece given back: nothing in the P&L", not line(fm.pnl("2025-04"), "disposal"))
check("module: disposal_month", [x["name"] for x in stock.disposal_month(d, "2025-06")] == ["Автоклав"])

# ------------------------------------------------------- old purchases among the costs --
old = a.save_equipment({"name": "Кресло", "price": 900000, "useful_months": 84, "purchase_date": "2024-05-10"})
x1 = a._acc.save_expense({"date": "2024-05-12", "category": "Прочее", "amount": 900000, "comment": "кресло Fona"})
a._acc.save_expense({"date": "2024-09-12", "category": "Прочее", "amount": 900000, "comment": "не то: далеко от покупки"})
a._acc.save_expense({"date": "2024-05-12", "category": "Аренда", "amount": 50000})
cand = a.equipment_capex_candidates()
check("the old purchase is found, once", [c["expense_id"] for c in cand] == [x1], cand)
check("candidate says which piece", cand and cand[0]["equipment_id"] == old and cand[0]["category"] == "Прочее")
may = fm.pnl("2024-05")
check("before: counted as a cost", line(may, "Прочее") and line(may, "Прочее")["amount"] == 900000)
r = a.expenses_to_capex([x1])
check("moved", r["moved"] == 1 and r["left"] == [], r)
may = fm.pnl("2024-05")
check("after: out of the costs, an investment", not line(may, "Прочее") and may["capex"] == 900000, may["fixed"])
check("June 2024: the chair depreciates", line(fm.pnl("2024-06"), "amortization")["amount"] == round(900000 / 84, 2))

# ------------------------------------------------------- the accounting summary --
summ = a.acc_summary("2025-01-01", "2025-06-30")
check("summary: the purchase is not an expense", accounting.CAPEX not in summ["by_category"] and summ["capex"] == 120000, summ["by_category"])
am6 = sum(fm.pnl(m)["amortization"] for m in ("2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"))
ds6 = sum(fm.pnl(m)["disposal"] for m in ("2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"))
check("summary: depreciation and disposal are expenses", abs(summ["amortization"] - am6) < 0.02 and abs(summ["disposal"] - ds6) < 0.02
      and summ["by_category"].get("Амортизация оборудования") == summ["amortization"], (summ["amortization"], am6, summ["disposal"], ds6))
check("summary: the expense total", abs(summ["expense"] - round(am6 + ds6, 2)) < 0.02, summ["expense"])
stock_auto.set_amort_in_pnl(d, False)
off = a.acc_summary("2025-01-01", "2025-06-30")
check("switched off: no depreciation in the summary, the purchase still not an expense", off["amortization"] == 0 and off["expense"] == 0
      and not off["in_pnl"], off)
check("switched off: no depreciation in the P&L", fm.pnl("2025-02")["fixed_total"] == 0)
stock_auto.set_amort_in_pnl(d, True)

# ------------------------------------------------------- multi-month P&L --
pm = finreport.pnl_months(fm, "2025-01", "2025-06")
row = next((x for x in pm["rows"] if x["key"] == "capex"), None)
check("P&L by months: the investment for reference", row and row["kind"] == "info" and row["values"][0] == 120000, row)
check("P&L by months: depreciation row", any(x["key"] == "amortization" and x["total"] > 0 for x in pm["rows"]))
net0 = next(x for x in pm["rows"] if x["key"] == "net")["values"][0]
am0 = next(x for x in pm["rows"] if x["key"] == "amortization")["values"][0]
check("P&L by months: the net takes the depreciation, not the investment", abs(net0 + am0) < 0.01 and net0 > -120000, (net0, am0))

# ------------------------------------------------------- materials: by the write-off, household apart --
S = a._stock
med = S.save_material({"name": "Композит", "category": "Пломбировочные материалы", "price": 1000})
nap = S.save_material({"name": "Салфетки", "category": "Хозяйственные товары", "price": 50})
S.receive({"date": "2025-08-01", "lines": [{"material_id": med, "qty": 10, "price": 1000}, {"material_id": nap, "qty": 100, "price": 50}]})
a._acc.save_expense({"date": "2025-08-01", "category": "Материалы и закупки", "amount": 15000})
a._acc.save_expense({"date": "2025-08-03", "category": "Хозяйственные расходы", "amount": 700, "comment": "вода"})
with d.tx() as c:
    c.execute("UPDATE stock_moves SET at='2025-08-01 10:00:00' WHERE kind='receipt'")
S.write_off({"reason": "Расход в лечении", "lines": [{"material_id": med, "qty": 2}, {"material_id": nap, "qty": 20}]})
with d.tx() as c:
    c.execute("UPDATE stock_moves SET at='2025-08-05 10:00:00' WHERE kind='writeoff'")
check("household: recognized by the category", stock_auto.is_household("Хозяйственные товары") and not stock_auto.is_household("Анестезия"))
aug = fm.pnl("2025-08")
mat = line(aug, "materials", "variable")
check("materials: what was written off, without the household goods", mat["amount"] == 2000, mat)
check("materials: the purchases are not counted twice", aug["materials_mode"] == "stock")
hh = line(aug, accounting.HOUSEHOLD)
check("household goods written off go into «Хозяйственные расходы»", hh and hh["amount"] == 1700 and aug["household_used"] == 1000, hh)
check("household detail", hh and len(hh["detail"]) == 2, hh)
a.stock_cost_settings_save({"pnl_materials": "expenses"})
aug2 = fm.pnl("2025-08")
check("by the purchases (the old way) still works", line(aug2, "materials", "variable")["amount"] == 15000
      and line(aug2, accounting.HOUSEHOLD)["amount"] == 700)
a.stock_cost_settings_save({"pnl_materials": "stock"})

# ------------------------------------------------------- rights over HTTP --
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
call("auth", "register", {"name": "Кладовщик", "login": "keeper", "password": "secret1"})
u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == "keeper")
call("auth", "staff_save", {"id": u["id"], "role": "storekeeper", "status": "active"}, token=TD)
TK = call("auth", "login", "keeper", "secret1")[1]["token"]
n0 = d.one("SELECT COUNT(*) AS n FROM expenses")["n"]
code, _ = call("api", "save_equipment", {"name": "Сканер", "price": 5000, "pay": "Наличные"}, token=TK)
check("without «Бухгалтерия» no payment is written", code != 200 and d.one("SELECT COUNT(*) AS n FROM expenses")["n"] == n0, code)
code, _ = call("api", "equipment_capex_candidates", token=TK)
check("candidates only with «Бухгалтерия»", code == 403, code)
code, _ = call("api", "expenses_to_capex", [], token=TK)
check("moving only with «Бухгалтерия»", code == 403, code)
code, r = call("api", "equipment_capex_candidates", token=TD)
check("the director sees them", code == 200 and isinstance(r, list), code)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
