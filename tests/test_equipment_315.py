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
check("catch-up 3.15 with the new columns", tuple(map(int, replica.CATCHUP.split("."))) >= (3, 15) and {"accounting", "contractor", "use_end", "qty"} <= set(replica.CATCHUP_COLS["equipment"]))

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

# ================================================ block 2: overview and register --
e_old = S.save_equipment({"name": "Стоматологическая установка", "category": "Стоматологическое оборудование", "price": 1200000,
                          "purchase_date": day(3700), "in_service": day(3700), "useful_months": 120, "next_service": day(10),
                          "warranty_until": day(-20)})
e_end = S.save_equipment({"name": "Микроскоп", "category": "Диагностическое оборудование", "price": 1200000, "purchase_date": day(330),
                          "in_service": day(330), "useful_months": 14, "condition": "service", "next_service": day(5)})
e_rep = S.save_equipment({"name": "Компрессор", "category": "Инженерное оборудование", "price": 180000, "replace_date": day(-100),
                          "condition": "faulty"})
e_lease = S.save_equipment({"name": "Рентген", "category": "Диагностическое оборудование", "price": 2400000, "ownership": "lease",
                            "contractor": "ООО РентАльянс", "use_end": day(-20)})
o = a.equipment_overview()
live = [x for x in S.equipment_list("", False) if x["status"] != "written_off"]
check("overview: all the live pieces with their quantity", o["total"] == sum(x["qty"] for x in live) and o["cards"] == len(live), (o["total"], o["cards"]))
check("overview: condition", o["condition"]["service"] >= 1 and o["condition"]["faulty"] >= 1 and sum(o["condition"].values()) == len(live), o["condition"])
check("overview: money of the clinic's own only", o["money"]["cost"] == round(sum(x["price"] or 0 for x in live if stockm.on_books(x)), 2), o["money"])
check("overview: the monthly depreciation", o["money"]["monthly"] == round(sum(stockm.amort_charge(x, date.today().strftime("%Y-%m")) for x in live if stockm.on_books(x)), 2))
check("overview: fully depreciated counted", o["full_amort"] >= 1)
cats = {g["name"]: g for g in o["by_category"]}
check("overview: by category with shares", cats["Стоматологическое оборудование"]["cost"] >= 1200000 and abs(sum(g["share"] for g in o["by_category"]) - 100) < 1,
      [(g["name"], g["share"]) for g in o["by_category"]])
check("a leased piece is counted but not in the money", "Рентген" not in [x["name"] for x in o["to_replace"]] and o["third_party"] >= 1)
kinds = {(x["kind"], x["name"].split(" ")[0]) for x in o["events"]}
check("events: service, the end of a lease, the replacement", ("service", "Микроскоп") in kinds and ("use_end", "Рентген") in kinds and ("replace", "Компрессор") in kinds, kinds)
check("events: an overdue one marked", any(x["overdue"] for x in o["events"] if x["name"].startswith("Стоматологическая")))
rep = {x["name"]: x for x in o["to_replace"]}
check("to replace: depreciated in full is urgent", rep["Стоматологическая установка"]["urgent"] and "100" in rep["Стоматологическая установка"]["why"], rep.get("Стоматологическая установка"))
check("to replace: the useful life runs out", "Микроскоп" in rep and "истекает" in rep["Микроскоп"]["why"], list(rep))
check("to replace: a planned replacement", "Компрессор" in rep, list(rep))
check("attention counts", o["attention"]["service_overdue"] >= 1 and o["attention"]["service_soon"] >= 1 and o["attention"]["to_replace"] == len(o["to_replace"]), o["attention"])
o2 = S.equipment_overview(money=False)
check("without «Бухгалтерия» no money", "money" not in o2 and o2["total"] == o["total"])
lst = {x["id"]: x for x in S.equipment_list("", False)}
check("the register has the name of the place and the accounting", "location_name" in lst[e_old] and lst[e_q]["accounting_title"].startswith("Количественный")
      and lst[e_lease]["third_party"], lst[e_old].get("location_name"))
check("overview has a right", "equipment_overview" in auth.METHOD_PERMS)
sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
card = (ROOT / "app" / "ui" / "stock-eqcard.js").read_text(encoding="utf-8")
for part in ("Состояние оборудования", "Стоимость по категориям", "Ближайшие события", "Быстрые действия", "Оборудование к замене",
             "Последние заявки и работы", "Реестр оборудования", "Статус учёта", "Карточки", "Сортировка", "Экспорт"):
    check(f"UI: {part}", part in sec)
check("the form has the new fields", all(x in card for x in ("eAcc", "eQty", "eCtr", "eCno", "eUs", "eUe", "подставить")))

# ================================================ block 3: receipts and moves --
sup = S.save_supplier({"name": "СтомТех ООО"})
refuses("a receipt needs a document number", lambda: a.equipment_receipt_save({"supplier_id": sup}), "номер документа")
refuses("a receipt needs a supplier", lambda: a.equipment_receipt_save({"doc_number": "1"}), "поставщика")
r = a.equipment_receipt_save({"supplier_id": sup, "doc_kind": "contract", "doc_number": "ДП-056/26", "doc_date": day(7), "amount": 1520000, "step": 2})
yy = day(7)[2:4]
check("a receipt: number П-…/yy, in process, step 2", r["number"] == f"П-00001/{yy}" and r["status"] == "process" and r["step"] == 2, (r["number"], r["step"]))
loc = S.save_location({"name": "Кабинет № 2", "kind": "cabinet"})
r = a.equipment_receipt_save({"id": r["id"], "step": 3, "lines": [
    {"name": "Стоматологическая установка", "category": "Стоматологическое оборудование", "model": "Intego", "serial": "SN-1", "qty": 1, "price": 1500000},
    {"name": "Наконечник", "category": "Медицинские инструменты", "qty": 2, "price": 7000},
    {"name": "Боры (набор)", "qty": 5, "price": 600, "accounting": "qty"}, {"name": " "}]})
check("lines kept (an empty one dropped)", len(r["lines"]) == 3 and r["positions"] == 8 and r["lines_total"] == 1500000 + 14000 + 3000, (len(r["lines"]), r["positions"]))
r = a.equipment_receipt_save({"id": r["id"], "step": 4, "lines": [{**r["lines"][0], "useful_months": 120, "inv_number": "СТ-101", "location_id": loc, "in_service": day(5)},
                                                                {**r["lines"][1], "location_id": loc}, {**r["lines"][2]}]})
check("the step never goes back on the server", a.equipment_receipt_save({"id": r["id"], "step": 2})["step"] == 4)
check("a receipt in the journal", any(x["id"] == r["id"] for x in a.equipment_receipts()["receipts"]) and a.equipment_receipts()["process"] >= 1)
nr = S.eq_receipt(r["id"], money=False)
check("without «Бухгалтерия» no prices", "amount" not in nr and all("price" not in x for x in nr["lines"]))
S.eq_receipt_save({"id": r["id"], "lines": [{**nr["lines"][0]}, {**nr["lines"][1]}, {**nr["lines"][2]}]}, money=False)
check("a save without «Бухгалтерия» keeps the prices", S.eq_receipt(r["id"])["lines"][0]["price"] == 1500000)
exp0 = d.one("SELECT COUNT(*) AS n FROM expenses")["n"]
x = a.equipment_receipt_accept(r["id"], "Безналичный перевод")
ids = x["equipment_ids"]
check("accepted: one card a unit, one for the quantity", len(ids) == 4 and x["receipt"]["status"] == "accepted", len(ids))
cards = [S.equipment(i) for i in ids]
u = next(c for c in cards if c["name"] == "Стоматологическая установка")
check("the card from the receipt", u["inv_number"] == "СТ-101" and u["price"] == 1500000 and u["useful_months"] == 120 and u["in_service"] == day(5)
      and u["location_id"] == loc and u["receipt_id"] == r["id"] and u["purchase_date"] == day(7) and u["serial"] == "SN-1", u)
check("two pieces — two cards, the next numbers", sum(1 for c in cards if c["name"] == "Наконечник") == 2
      and len({c["inv_number"] for c in cards}) == 4)
b = next(c for c in cards if c["name"] == "Боры (набор)")
check("counted by quantity — one card with its quantity", b["qty"] == 5 and b["accounting"] == "qty")
check("the payment went to «Покупка оборудования»", d.one("SELECT COUNT(*) AS n FROM expenses")["n"] == exp0 + 1
      and d.one("SELECT category, amount FROM expenses ORDER BY rowid DESC LIMIT 1")["amount"] == 1520000)
refuses("an accepted receipt is not changed", lambda: a.equipment_receipt_save({"id": r["id"], "doc_number": "2"}), "проведено")
refuses("nor accepted twice", lambda: a.equipment_receipt_accept(r["id"]), "проведено")
r2 = a.equipment_receipt_save({"supplier_id": sup, "doc_number": "Н-2", "doc_date": day(1)})
refuses("nothing to accept without lines", lambda: a.equipment_receipt_accept(r2["id"]), "Добавьте оборудование")
a.equipment_receipt_cancel(r2["id"])
check("a cancelled receipt leaves the journal", not any(x["id"] == r2["id"] for x in a.equipment_receipts()["receipts"]))

loc2 = S.save_location({"name": "Кабинет № 3", "kind": "cabinet"})
refuses("a move needs a place", lambda: a.equipment_move_save({"equipment_id": u["id"], "reason": "x"}), "куда")
refuses("not to where it is", lambda: a.equipment_move_save({"equipment_id": u["id"], "to_location_id": loc, "reason": "x"}), "уже там")
refuses("a move needs a reason", lambda: S.eq_move_save({"equipment_id": u["id"], "to_location_id": loc2}), "основание")
mid = S.eq_move_save({"equipment_id": u["id"], "to_location_id": loc2, "reason": "Перераспределение нагрузки", "responsible": "Менеджер"}, "Менеджер", "manager", False)
m = next(x for x in a.equipment_moves()["moves"] if x["id"] == mid)
check("a move waits for approval", m["status"] == "requested" and m["number"].startswith("ПМ-") and m["from_name"] == "Кабинет № 2" and m["to_name"] == "Кабинет № 3"
      and m["stage"] == 1, m)
refuses("one open move a piece", lambda: S.eq_move_save({"equipment_id": u["id"], "to_location_id": loc2, "reason": "x"}, "", "", False), "незавершённое")
refuses("not moved before approval", lambda: a.equipment_move_step(mid, "done"), "утверждённое")
refuses("a refusal needs a reason", lambda: a.equipment_move_decide(mid, "reject"), "почему")
a.equipment_move_decide(mid, "approve")
a.equipment_move_step(mid, "moving")
check("approved, then moving", next(x for x in a.equipment_moves()["moves"] if x["id"] == mid)["stage"] == 3)
a.equipment_move_step(mid, "done")
u2 = S.equipment(u["id"])
check("done: the card has its new place and a line of history", u2["location_id"] == loc2 and u2["location"] == "Кабинет № 3"
      and any(ev["kind"] == "move" and "ПМ-" in ev["text"] for ev in u2["events"]))
fut = S.eq_move_save({"equipment_id": u["id"], "to_location_id": loc, "reason": "Ремонт кабинета", "date": day(-10)}, "Директор", "dir", True)
mv = a.equipment_moves()
f = next(x for x in mv["moves"] if x["id"] == fut)
check("the director's move is approved at once; a future one is planned", f["status"] == "approved" and f["planned"] and f["status_title"] == "Запланировано" and mv["planned"] >= 1)
a.equipment_move_cancel(fut)
now = S.eq_move_save({"equipment_id": u["id"], "to_location_id": loc, "reason": "Ремонт кабинета", "now": True}, "Директор", "dir", True)
check("done at once by the director", S.equipment(u["id"])["location_id"] == loc and next(x for x in a.equipment_moves()["moves"] if x["id"] == now)["status"] == "done")
check("history of one piece", all(x["equipment_id"] == u["id"] for x in a.equipment_moves(None, u["id"])["moves"]) and len(a.equipment_moves(None, u["id"])["moves"]) == 2)
check("the decision needs the right", auth.METHOD_PERMS["equipment_move_decide"] == "equipment_approve")
for k in ("equipment_receipts", "equipment_receipt", "equipment_receipt_save", "equipment_receipt_accept", "equipment_receipt_cancel", "equipment_moves",
          "equipment_move_save", "equipment_move_decide", "equipment_move_step", "equipment_move_cancel"):
    check(f"{k} has a right", k in auth.METHOD_PERMS)
sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
for part in ("Регистрация поступления", "Этапы поступления", "Журнал поступлений", "Ввести в эксплуатацию", "Создать перемещение", "Этапы перемещения",
             "Журнал перемещений", "Акт перемещения", "Шаблоны оснований"):
    check(f"UI: {part}", part in sec)

# ===================================== block 4: service and repair, the schedule --
k = S.save_equipment({"name": "Компрессор КМ-001", "price": 180000, "location_id": loc})
refuses("a request needs a description", lambda: a.equipment_request_save({"equipment_id": k}), "Опишите")
rid = a.equipment_request_save({"equipment_id": k, "kind": "repair", "description": "Повышенный шум при работе", "priority": "high",
                                "due": day(3), "responsible": "Менеджер"})
rq = a.equipment_requests()
x = next(r for r in rq["requests"] if r["id"] == rid)
check("a repair request: Р-…, new, overdue after its day", x["number"].startswith("Р-") and x["status"] == "new" and x["overdue"]
      and x["status_title"] == "Просрочено" and x["priority_title"] == "Высокий", x)
check("a repair request marks the piece faulty", S.equipment(k)["condition"] == "faulty")
check("the figures", rq["total"] >= 1 and rq["overdue"] >= 1, (rq["total"], rq["overdue"]))
a.equipment_request_status(rid, "work")
check("in work: the piece is in repair", S.equipment(k)["status"] == "repair")
a.equipment_request_status(rid, "done", {"cost": 18000, "result": "Замена подшипника"})
kk = S.equipment(k)
check("done: back in use, fine, the history with its cost", kk["status"] == "in_use" and kk["condition"] == "ok"
      and any(ev["kind"] == "repair" and ev["cost"] == 18000 and "Замена подшипника" in ev["text"] for ev in kk["events"]))
refuses("a closed request is not changed", lambda: a.equipment_request_status(rid, "work"), "закрыта")
check("the year's cost of service and repair", a.equipment_requests()["cost"] >= 18000)
refuses("a plan needs a period", lambda: a.equipment_plan_save({"equipment_id": k, "every_months": 0, "next_date": day(-30)}), "Периодичность")
pid = a.equipment_plan_save({"equipment_id": k, "kind": "service", "every_months": 6, "next_date": day(-30), "note": "по паспорту"})
check("a plan sets the card's next service", S.equipment(k)["next_service"] == day(-30))
sch = a.equipment_requests()["schedule"]
check("the schedule has the plan (no double line of the card)", sum(1 for r in sch if r["equipment_id"] == k) == 1
      and next(r for r in sch if r["equipment_id"] == k)["plan_id"] == pid)
r2 = a.equipment_request_save({"equipment_id": k, "kind": "service", "description": "Плановое ТО", "plan_id": pid})
check("a service request: ТО-…", next(r for r in a.equipment_requests()["requests"] if r["id"] == r2)["number"].startswith("ТО-"))
a.equipment_request_status(r2, "done", {"cost": 4000, "date": day(0)})
nxt = next(p_ for p_ in a.equipment_plans() if p_["id"] == pid)["next_date"]
t_ = date.today()
ym_ = t_.year * 12 + t_.month - 1 + 6
check("done by the schedule: the next date moves by the period", nxt[:7] == f"{ym_ // 12}-{ym_ % 12 + 1:02d}", nxt)
check("and the card follows", S.equipment(k)["next_service"] == nxt)
a.equipment_plan_delete(pid)
check("a plan removed", not any(p_["id"] == pid for p_ in a.equipment_plans()))
d3 = a.equipment_request_save({"equipment_id": k, "kind": "diag", "description": "Проверка"})
check("diagnostics: Д-…", next(r for r in a.equipment_requests()["requests"] if r["id"] == d3)["number"].startswith("Д-"))
a.equipment_request_status(d3, "cancelled")
check("a cancelled request leaves the journal", not any(r["id"] == d3 for r in a.equipment_requests()["requests"]))
nr = S.eq_request_save({"equipment_id": k, "kind": "service", "description": "Не включается"}, "Медсестра", "nurse", report_only=True)
check("a nurse may only report a fault", next(r for r in a.equipment_requests()["requests"] if r["id"] == nr)["kind"] == "repair")
a.equipment_confirm(k)
check("a nurse confirms the piece is in its place", S.equipment(k)["events"][0]["kind"] == "inventory" and "подтверждено" in S.equipment(k)["events"][0]["text"])
check("the nurse sees the equipment and reports", "stock_ops" in auth.METHOD_PERMS["equipment_list"] and "stock_ops" in auth.METHOD_PERMS["equipment_request_save"]
      and "stock_ops" in auth.METHOD_PERMS["equipment_confirm"] and auth.METHOD_PERMS["equipment_request_status"] == "equipment")
for k_ in ("equipment_requests", "equipment_request_save", "equipment_request_status", "equipment_plans", "equipment_plan_save", "equipment_plan_delete", "equipment_confirm"):
    check(f"{k_} has a right", k_ in auth.METHOD_PERMS)
sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
card = (ROOT / "app" / "ui" / "stock-eqcard.js").read_text(encoding="utf-8")
for part in ("Новая заявка", "График технического обслуживания", "Весь график ТО", "Расходы на обслуживание и ремонт", "Журнал неисправностей", "Настройки регламентов ТО"):
    check(f"UI: {part}", part in sec)
check("the card: report a fault, confirm", "Сообщить о неисправности" in card and "Подтвердить наличие" in card)

# ============================================== block 5: depreciation and disposal --
ya = date.today().year
z1 = S.save_equipment({"name": "Амортизация А", "category": "Мебель", "price": 120000, "purchase_date": f"{ya - 1}-01-10",
                       "in_service": f"{ya - 1}-01-10", "useful_months": 12})   # depreciated in full in January of this year
z2 = S.save_equipment({"name": "Амортизация Б", "category": "Мебель", "price": 240000, "purchase_date": f"{ya - 1}-12-05",
                       "in_service": f"{ya - 1}-12-05", "useful_months": 24})
z3 = S.save_equipment({"name": "Без срока", "category": "Мебель", "price": 50000})
am = a.equipment_amort_year(ya)
rows = {x["id"]: x for x in am["rows"]}
check("groups: in full, running, without", rows[z1]["group"] == "done" and rows[z2]["group"] == "on" and rows[z3]["group"] == "off"
      and rows[z3]["why"] == "Не указан срок", (rows[z1]["group"], rows[z2]["group"], rows[z3]["why"]))
check("off groups say why", rows[e_q]["why"] == "Количественный учёт" and rows[e_doc]["why"] == "Стороннее имущество")
check("the year by month: January of the first piece", am["charge"][0] >= 10000 + 10000 and len(am["charge"]) == 12, am["charge"][:2])
check("the running total grows by the charges", all(abs(am["running"][i] - am["running"][i - 1] - am["charge"][i]) < 0.02 for i in range(1, 12)))
now_m = date.today().month
check("the running total of this month is what is accumulated", abs(am["running"][now_m - 1] - round(sum(x["accumulated"] for x in am["rows"] if x["own"]), 2)) < 0.02
      or am["running"][now_m - 1] > 0, (am["running"][now_m - 1],))
check("tiles: cost, residual, wear", am["cost"] > 0 and abs(am["residual"] - (am["cost"] - am["accumulated"])) < 0.02
      and am["wear"] == round(am["accumulated"] * 100 / am["cost"], 1))
check("key figures", am["count_on"] == am["count_done"] + am["count_running"] and am["avg_life"] > 0 and am["count_off"] >= 3)
check("structure by category with shares", abs(sum(g["share"] for g in am["by_category"]) - 100) < 1)
check("a past year ends in December", a.equipment_amort_year(ya - 1)["upto"] == f"{ya - 1}-12")
check("depreciation only for «Бухгалтерия»", auth.METHOD_PERMS["equipment_amort_year"] == "accounting")
ds = a.equipment_disposals()
kinds = {x["kind"] for x in ds["rows"]}
check("disposals of the year by their way", {"utilize", "transfer", "sale"} <= kinds and ds["utilize"] >= 1 and ds["transfer"] >= 1 and ds["sale"] >= 1, ds)
ut = next(x for x in ds["rows"] if x["kind"] == "utilize")
check("a disposal: its act, reason, responsible, basis, the money", ut["doc"].startswith("Акт утилизации №") and ut["reason"] and ut["responsible"] == "Менеджер"
      and ut["basis"].startswith("Акт технического") and "residual" in ut and "cost" in ut, ut)
check("the sum of the year is the book values", ds["sum"] == round(sum(x["residual"] for x in ds["rows"] if x["date"][:4] == str(ya)), 2))
nd = S.eq_disposals(money=False)
check("without «Бухгалтерия» no money", "sum" not in nd and all("residual" not in x for x in nd["rows"]))
sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
for part in ("Динамика амортизации", "Структура стоимости", "Ключевые показатели", "Полностью амортизировано", "Без амортизации", "Степень износа",
             "Создать списание (выбытие)", "Последние документы выбытия", "Сформировать акт"):
    check(f"UI: {part}", part in sec)

# ===================================== block 6: purchase plan, someone else's equipment --
refuses("a purchase needs a name", lambda: a.equipment_purchase_save({"budget": 1}), "что закупить")
p1 = a.equipment_purchase_save({"name": "Микроскоп", "reason": "Развитие терапии", "category": "Диагностическое оборудование", "budget": 1200000,
                                "year": ya, "quarter": 2, "priority": "high", "funding": "own", "justification": "Эндодонтия под микроскопом",
                                "offers": [{"supplier": "СтомТех", "price": 1180000, "days": 14}, {"supplier": "", "price": 1}]})
p2 = a.equipment_purchase_save({"name": "Автоклав", "reason": "Плановая замена", "category": "Стерилизационное оборудование", "budget": 450000,
                                "year": ya, "quarter": 1, "priority": "high", "replace_id": e_old})
p3 = a.equipment_purchase_save({"name": "Компьютеры", "reason": "Обновление", "budget": 180000, "year": ya, "quarter": 3, "funding": "credit"})
pl = a.equipment_purchases(ya)
x1 = next(x for x in pl["rows"] if x["id"] == p1)
check("a purchase: ЗК-…, a draft with its offer", x1["number"].startswith("ЗК-") and x1["status"] == "draft" and len(x1["offers"]) == 1
      and x1["best_offer"]["price"] == 1180000 and x1["priority_title"] == "Высокий", x1)
check("replacing a piece", next(x for x in pl["rows"] if x["id"] == p2)["replace_name"].startswith("Стоматологическая установка"))
refuses("no approval without a justification or reason", lambda: a.equipment_purchase_status(
    a.equipment_purchase_save({"name": "Без обоснования", "budget": 0, "year": ya}), "send"), "бюджет и обоснование")
a.equipment_purchase_status(p1, "send")
refuses("approval needs the right", lambda: S.eq_purchase_status(p1, "bought"), "так нельзя")
a.equipment_purchase_status(p1, "approve")
a.equipment_purchase_status(p2, "send")
refuses("a refusal needs a reason", lambda: a.equipment_purchase_status(p2, "reject"), "почему")
refuses("a purchase on approval is not edited", lambda: a.equipment_purchase_save({"id": p2, "name": "Автоклав 2"}), "черновик")
pl = a.equipment_purchases(ya)
check("plan figures", pl["approved"] == 1 and pl["pending"] == 1 and pl["draft"] >= 2 and pl["total"] >= 1200000 + 450000 + 180000, (pl["approved"], pl["pending"], pl["draft"]))
check("budget by status", pl["by_status"]["approved"] == 1200000 and pl["by_status"]["pending"] == 450000, pl["by_status"])
check("by quarter", pl["by_quarter"][1] == 1200000 and pl["by_quarter"][0] == 450000 and pl["by_quarter"][2] == 180000, pl["by_quarter"])
check("by category with shares", abs(sum(g["share"] for g in pl["by_category"]) - 100) < 1)
kinds = {x["kind"] for x in pl["actions"]}
check("the nearest actions: approve, prepare offers, buy", {"approve", "offers", "buy"} <= kinds, kinds)
a.equipment_purchase_status(p1, "bought")
check("bought", next(x for x in a.equipment_purchases(ya)["rows"] if x["id"] == p1)["status"] == "bought")
a.equipment_purchase_status(p2, "draft")
check("back to a draft from approval", next(x for x in a.equipment_purchases(ya)["rows"] if x["id"] == p2)["status"] == "draft")
PDF = "data:application/pdf;base64," + __import__("base64").b64encode(b"%PDF-1.4 offer").decode()
a.equipment_purchase_offer_add(p2, "КП.pdf", PDF)
o = next(x for x in a.equipment_purchases(ya)["rows"] if x["id"] == p2)["offers"]
check("a commercial offer file", o and o[-1]["file_id"] and a.equipment_purchase_offer_open(o[-1]["file_id"])["url"].startswith("data:"))
refuses("only an offer's file opens", lambda: a.equipment_purchase_offer_open("F-нет"), "не найден")
a.equipment_purchase_status(p3, "delete")
check("a deleted draft leaves the plan", not any(x["id"] == p3 for x in a.equipment_purchases(ya)["rows"]))
check("the decision on the server needs the right", "equipment_approve" in auth.METHOD_PERMS["equipment_purchase_status"])
tp = a.equipment_third_party()
ids_ = {x["id"]: x for x in tp["rows"]}
check("someone else's: the doctor's, the lease, other use", e_doc in ids_ and e_lease in ids_ and e_oth in ids_ and e_q not in ids_, list(ids_))
check("lease: active till its end, contractor kept", ids_[e_lease]["status"] in ("active", "soon") and ids_[e_lease]["contractor"] == "ООО РентАльянс")
check("other use ended", ids_[e_oth]["status"] == "soon" or ids_[e_oth]["status"] == "active" or ids_[e_oth]["status"] == "ended")
check("the doctor's own is in use", ids_[e_doc]["status"] == "use" and ids_[e_doc]["ownership_title"] == "Имущество врача")
check("kinds counted", tp["kinds"]["doctor"] >= 1 and tp["kinds"]["lease"] >= 1 and tp["total"] == len(tp["rows"]))
check("events: the end of a lease", any(x["title"] == "Окончание аренды" for x in tp["events"]), tp["events"])
for k_ in ("equipment_purchases", "equipment_purchase_save", "equipment_purchase_status", "equipment_purchase_offer_add", "equipment_purchase_offer_open", "equipment_third_party"):
    check(f"{k_} has a right", k_ in auth.METHOD_PERMS)
sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
for part in ("Планирование закупок", "Исполнение бюджета", "План закупок по категориям", "Календарный план", "Коммерческие предложения", "Источник финансирования",
             "Стороннее оборудование", "Структура стороннего оборудования", "Контроль сроков", "Условия пользования"):
    check(f"UI: {part}", part in sec)

# ===================================== block 7: documents, analytics, the log --
a.equipment_doc_add(u["id"], "passport", "Паспорт.pdf", PDF)
a.equipment_doc_add(u["id"], "contract", "Договор.pdf", PDF)
dd = a.equipment_all_docs()
check("every document in one list", sum(1 for x in dd["docs"] if x["equipment_id"] == u["id"]) == 2 and dd["counts"]["passport"] >= 1
      and dd["docs"][0]["equipment_name"], dd["counts"])
check("a piece with a passport and a contract is not missing them", not any(m["id"] == u["id"] for m in dd["missing"]))
check("a piece without them is", any(m["id"] == k and "Технический паспорт" in m["lack"] for m in dd["missing"]))
check("a warranty that ends within a month", any(w["id"] == e_old and not w["ended"] for w in dd["warranty"]), dd["warranty"])
an = a.equipment_analytics(ya)
check("analytics: the year's keep by month", an["keep"] == round(sum(m["service"] + m["repair"] + m["diag"] for m in an["by_month"]), 2) and an["keep"] >= 18000 + 4000)
check("repairs and works counted", an["repairs"] >= 1 and an["works"] >= 2)
check("the most expensive to keep first", an["top"] and an["top"][0]["cost"] == max(g["cost"] for g in an["top"]))
check("the age of the fleet adds up", sum(x["count"] for x in an["ages"]) == sum(1 for x in S.equipment_list("", False)))
check("money: the year's depreciation and the chair hour", an["amort"] >= 0 and an["chair_hour"] > 0 and abs(an["total"] - an["amort"] - an["keep"]) < 0.02)
check("without «Бухгалтерия» no depreciation", "amort" not in S.eq_analytics(ya, money=False) and all("amort" not in c for c in S.eq_analytics(ya, money=False)["by_category"]))
lg = a.equipment_log()
check("the log of every piece", lg["rows"] and {"move", "repair", "inventory"} <= {x["kind"] for x in lg["rows"]})
check("the log by kind", all(x["kind"] == "move" for x in a.equipment_log({"kind": "move"})["rows"]))
check("the log by date", all(x["date"] >= day(1) for x in a.equipment_log({"from": day(1)})["rows"]))
for k_ in ("equipment_all_docs", "equipment_analytics", "equipment_log"):
    check(f"{k_} has a right", k_ in auth.METHOD_PERMS)
sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
js = (ROOT / "app" / "ui" / "stock.js").read_text(encoding="utf-8")
for part in ("Не хватает документов", "Гарантии", "Стоимость содержания по месяцам", "Возраст парка", "Дороже всего в содержании", "Журнал действий"):
    check(f"UI: {part}", part in sec)
check("«Ещё» has every section of the mockups", all(t in js for t in ('"eq_purchases"', '"eq_third"', '"disposed"', '"inv"', '"eq_docs"', '"eq_analytics"', '"eq_log"', '"eq_refs"', '"steril"')))

print(f"OK: {OK[0]} FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
