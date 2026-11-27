"""3.15 «Оборудование» by the clinic's mockups: the accounting of a piece (with depreciation or by quantity), the doctors' and
any other use as someone else's property, the ways of disposal with their acts, the references (categories, the usual useful
life), the right «Оборудование: согласование», the new tables in the replica; the receipts, moves, service requests and the
schedule, the purchase plan, the overview and the register (each block adds its part)."""
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import replica  # noqa: E402
import stock as stockm  # noqa: E402
from main import Api  # noqa: E402


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
        if text and text not in str(e):
            FAIL.append(f"{name}: wrong refusal {e}")
        else:
            OK[0] += 1


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
S = a._stock
day = lambda n: (date.today() - timedelta(days=n)).isoformat()  # noqa: E731
mon = lambda n: (date.today().replace(day=1) - timedelta(days=1 + 31 * (n - 1))).strftime("%Y-%m") if n else date.today().strftime("%Y-%m")  # noqa: E731

# =========================================================== block 1: data --
cols = {r[1] for r in d.conn.execute("PRAGMA table_info(equipment)")}
check("new columns of equipment", {"accounting", "contractor", "use_start", "use_end", "contract_no", "receipt_id", "responsible_login",
                                   "qty", "disposal_responsible", "disposal_basis"} <= cols, cols)
for t in ("equipment_receipts", "equipment_moves", "equipment_requests", "equipment_plans", "equipment_purchases"):
    check(f"table {t}", d.one("SELECT 1 AS x FROM sqlite_master WHERE name=?", (t,)))
    check(f"{t} replicated after equipment", t in replica.BY_NAME and replica.ORDER[t] > replica.ORDER["equipment"])
check("catch-up 3.15 with the new columns", replica.CATCHUP == "3.15" and {"accounting", "contractor", "use_end", "qty"} <= set(replica.CATCHUP_COLS["equipment"]))

# ownership: the doctor's and any other use are someone else's property
check("ownership kinds", {"doctor", "other", "owner", "lease", "leasing", "own"} <= set(stockm.EQ_OWNERSHIP))
e_doc = S.save_equipment({"name": "Наконечник врача", "category": "Медицинские инструменты", "price": 90000, "purchase_date": day(400),
                          "in_service": day(400), "useful_months": 36, "ownership": "doctor", "contractor": "Иванов А. С.",
                          "use_start": day(400)})
e = S.equipment(e_doc)
check("the doctor's own keeps who owns it", e["ownership"] == "doctor" and e["contractor"] == "Иванов А. С." and e["use_start"] == day(400), e["ownership"])
check("someone else's property is off the books", not stockm.on_books(e) and stockm.amort_month(d, mon(1)) == stockm.amort_month(d, mon(1)))
P = {x["name"]: x for x in stockm.amort_month_detail(d, mon(1))}
check("the doctor's piece is not depreciated in the P&L", not any("Наконечник врача" in k for k in P))
e_oth = S.save_equipment({"name": "Кофемашина партнёра", "price": 50000, "ownership": "other", "use_end": day(-30)})
check("other use is off the books", not stockm.on_books(S.equipment(e_oth)) and S.equipment(e_oth)["use_end"] == day(-30))

# accounting: by quantity, without depreciation
e_q = S.save_equipment({"name": "Наконечники (комплект)", "category": "Медицинские инструменты", "price": 12000, "qty": 3,
                        "accounting": "qty", "purchase_date": day(200), "in_service": day(200), "useful_months": 24})
q = S.equipment(e_q)
check("quantity accounting kept", q["accounting"] == "qty" and q["qty"] == 3, (q["accounting"], q["qty"]))
check("no depreciation by quantity", not q["amort"]["on"] and q["amort"].get("qty"), q["amort"])
check("not in the P&L depreciation", not stockm.on_books(q) and not any("Наконечники (комплект)" in x["name"] for x in stockm.amort_month_detail(d, mon(1))))
e_a = S.save_equipment({"name": "Автоклав", "category": "Стерилизационное оборудование", "price": 350000, "purchase_date": day(400),
                        "in_service": day(400), "useful_months": 84})
check("a new piece is depreciated by default", S.equipment(e_a)["accounting"] == "amort" and S.equipment(e_a)["amort"]["on"])
nm = S.save_equipment({"id": e_a, "name": "Автоклав", "accounting": "qty"}, money=False)
check("without «Бухгалтерия» the accounting does not change", S.equipment(nm)["accounting"] == "amort")

# disposal: writeoff, utilization, sale, transfer, return — acts numbered on among the acts
com = ["Председатель", "Член комиссии"]
S.equipment_dispose({"id": e_a, "kind": "utilize", "reason": "Непригодно к эксплуатации", "commission": com,
                     "responsible": "Менеджер", "basis": "Акт технического состояния № 14"})
u = S.equipment(e_a)
check("utilization: its act and status", u["disposal_kind"] == "utilize" and u["writeoff_act"] and u["status_title"] == "Утилизировано"
      and u["disposal_responsible"] == "Менеджер" and u["disposal_basis"].startswith("Акт технического"), (u["writeoff_act"], u["status_title"]))
refuses("utilization needs a commission", lambda: S.equipment_dispose({"id": e_q, "kind": "utilize", "reason": "x"}), "комиссии")
e_t = S.save_equipment({"name": "Моноблок", "price": 45000})
S.equipment_dispose({"id": e_t, "kind": "transfer", "reason": "Передан партнёру по договору"})
t = S.equipment(e_t)
check("transfer: the next act number", t["status_title"] == "Передано" and int(t["writeoff_act"]) == int(u["writeoff_act"]) + 1, t["writeoff_act"])
e_s = S.save_equipment({"name": "Компрессор", "price": 180000})
S.equipment_dispose({"id": e_s, "kind": "sale", "reason": "ООО Покупатель", "amount": 20000})
check("a sale has no act", not S.equipment(e_s)["writeoff_act"] and S.equipment(e_s)["status_title"] == "Продано")

# references: categories and the usual useful life
r = a.equipment_refs()
names = [c["name"] for c in r["categories"]]
check("13 categories by default", names[:13] == stockm.EQ_CATS, names[:3])
check("a category counts its pieces", next(c for c in r["categories"] if c["name"] == "Медицинские инструменты")["count"] >= 2)
check("the usual life is a hint", next(c for c in r["categories"] if c["name"] == "Стоматологическое оборудование")["life"] == 120)
check("the lists of the section", set(r["ownership"]) >= {"doctor", "other"} and set(r["accounting"]) == {"amort", "qty"}
      and "utilize" in r["disposals"] and r["receipt_docs"] and r["move_reasons"] and r["plan_kinds"])
r = a.equipment_refs_save({"categories": ["Мебель", "Стоматологическое оборудование", "Мебель", " "], "life": {"Мебель": 100}})
names = [c["name"] for c in r["categories"]]
check("own list kept in its order, the used ones after it", names[:2] == ["Мебель", "Стоматологическое оборудование"] and "Медицинские инструменты" in names, names)
check("the norm saved", next(c for c in r["categories"] if c["name"] == "Мебель")["life"] == 100)
refuses("an empty list is refused", lambda: a.equipment_refs_save({"categories": []}))
refuses("a norm over 50 years is refused", lambda: a.equipment_refs_save({"life": {"Мебель": 700}}))

# the right «Оборудование: согласование»
check("the right is known", "equipment_approve" in auth.PERM_KEYS and any("equipment_approve" in g[1] for g in auth.PERM_GROUPS))
check("the director has it", "equipment_approve" in auth.roles(d)["director"]["perms"])
check("an admin does not", "equipment_approve" not in auth.roles(d)["admin"]["perms"])
auth.Auth(d)  # the positions table
d.conn.execute("""INSERT INTO staff_roles(key, title, base, perms, known, sort, updated_at) VALUES('founder', 'Учредитель', 'admin', ?, ?, 50, '')""",
               (json.dumps(["reports", "accounting", "equipment"]), json.dumps(auth.PERM_KEYS[:-1])))
d.conn.commit()
check("a position with «Бухгалтерия» saved before 3.15 gets it once", "equipment_approve" in auth.roles(d)["founder"]["perms"], auth.roles(d)["founder"]["perms"])
d.conn.execute("UPDATE staff_roles SET known=? WHERE key='founder'", (json.dumps(auth.PERM_KEYS),))
d.conn.commit()
check("taken away later, it stays away", "equipment_approve" not in auth.roles(d)["founder"]["perms"])

NEW = ["equipment_refs", "equipment_refs_save"]
check("every new method has a right", all(k in auth.METHOD_PERMS for k in NEW), [k for k in NEW if k not in auth.METHOD_PERMS])
check("changes in the journal", "equipment_refs_save" in auth.AUDITED)

# the UI: the bar of the section
js = (ROOT / "app" / "ui" / "stock.js").read_text(encoding="utf-8")
sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
html = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("the section's script and styles on the page", "stock-eqsection.js" in html and "styles-eqsection.css" in html
      and html.index("stock-eqcard.js") < html.index("stock-eqsection.js"))
check("the bar has «Ещё»", "more: [" in js and "eqNavHtml" in sec and "Справочники и настройки" in js)

print(f"OK: {OK[0]} FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
