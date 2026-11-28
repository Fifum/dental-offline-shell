"""3.16 «Оборудование», four more mockups of the clinic: the references and the module's settings (they really change the
program), the log of actions with «было → стало», the analytics with the runtime from the chairs' appointments and the reports,
the documents with their number, date, term, counterparty and archive."""
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
import daily  # noqa: E402
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
ahead = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731
auth.set_current_user({"role": "director", "login": "dir", "name": "Ковалев А.В."})

# ================================================ block 1: references and the module's settings --
check("replica catches up 3.16", replica.CATCHUP == "3.16" and {"number", "doc_date", "valid_until", "counterparty", "archived"}
      <= set(replica.CATCHUP_COLS["equipment_docs"]) and replica.CATCHUP_COLS["equipment_plans"] == ["reg_id"])
check("new columns of the documents", {"number", "doc_date", "valid_until", "counterparty", "archived", "updated_at"}
      <= {r[1] for r in d.conn.execute("PRAGMA table_info(equipment_docs)")})
check("the plan has its regulation", "reg_id" in {r[1] for r in d.conn.execute("PRAGMA table_info(equipment_plans)")})
r = a.equipment_refs()
check("nine references", all(k in r for k in ("categories", "models", "groups", "works", "regs", "places", "ownership", "disp_reasons", "module")))
check("defaults of the references", len(r["works"]) == len(stockm.EQ_WORKS) and len(r["regs"]) == len(stockm.EQ_REGS)
      and all(g["checklist"] for g in r["regs"]) and len(r["disp_reasons"]) == len(stockm.EQ_DISP_REASONS))
check("the settings by default", r["module"]["control_to"] and r["module"]["to_days"] == 14 and r["module"]["round"] == "rub"
      and not r["module"]["no_doc_disposal"] and r["module"]["third_party"] and r["module"]["auto_amort"])
check("models from the cards", any(m["from_cards"] for m in r["models"]) or not any(e["model"] for e in S.equipment_list()))

# the module's settings: saved, logged, money only with «Бухгалтерия»
m = a.equipment_module_save({"round": "kop", "to_days": 30, "no_doc_disposal": True})
check("settings saved", m["round"] == "kop" and m["to_days"] == 30 and m["no_doc_disposal"])
lg = d.one("SELECT * FROM equipment_events WHERE kind='settings' ORDER BY id DESC")
data = json.loads(lg["data"])
check("a change of the settings is in the log", lg["equipment_id"] == "" and data["module"] == "Настройки"
      and any(c["t"] == "Округление сумм" and c["old"] == "До рублей" and c["new"] == "До копеек" for c in data["changes"]), data)
refuses("the period of the warning", lambda: a.equipment_module_save({"to_days": 0}), "1–90")
refuses("depreciation in the P&L only with «Бухгалтерия»", lambda: S.eq_module_save({"auto_amort": False}, "x", money=False), "Бухгалтерия")
m = a.equipment_module_save({"auto_amort": False})
check("the P&L switch is the old one", not m["auto_amort"] and d.one("SELECT v FROM stock_settings WHERE k='pnl_amort'")["v"] == "0")
a.equipment_module_save({"auto_amort": True})

# «Запрет списания без документа»
live = [e for e in S.equipment_list() if e["status"] != "written_off"]
victim = live[-1]
refuses("no disposal without a document", lambda: a.equipment_dispose({"id": victim["id"], "kind": "sale", "reason": "ООО Ромашка"}), "документ-основание")
a.equipment_module_save({"no_doc_disposal": False})
lg = json.loads(d.one("SELECT data FROM equipment_events WHERE kind='settings' ORDER BY id DESC")["data"])
check("switching the ban off is suspicious", lg.get("flag"), lg)

# references: saved, checked, logged
rr = a.equipment_ref_save("eq_groups", [{"code": "ст", "name": "Стоматологическое", "okof": "330.32.50", "categories": ["Стоматологическое оборудование"]}])
check("an inventory group", rr["groups"][0]["code"] == "СТ" and rr["groups"][0]["okof"] == "330.32.50")
check("the group's code numbers a new piece", a.equipment_next_inv("Стоматологическое оборудование") == "СТ-001"
      and a.equipment_next_inv("Мебель") != "СТ-001")
eid = a.save_equipment({"name": "Установка Sirona C8", "category": "Стоматологическое оборудование", "manufacturer": "Sirona", "model": "C8",
                        "price": 1200000, "useful_months": 96, "in_service": day(400)})
check("the card took the group's number", S.equipment(eid)["inv_number"] == "СТ-001")
check("the next one goes on", a.equipment_next_inv("Стоматологическое оборудование") == "СТ-002")
refuses("a category in two groups", lambda: a.equipment_ref_save("eq_groups", [{"code": "А", "categories": ["Мебель"]}, {"code": "Б", "categories": ["Мебель"]}]), "другой")
refuses("a bad code", lambda: a.equipment_ref_save("eq_groups", [{"code": "СТОМАТОЛОГ", "categories": []}]), "до 6")
refuses("a regulation without a period", lambda: a.equipment_ref_save("eq_regs", [{"name": "ТО", "every_months": 0}]), "120")
rr = a.equipment_ref_save("eq_regs", r["regs"][:1] + [{"name": "ТО микроскопа", "kind": "service", "every_months": 6, "category": "Диагностическое оборудование",
                                                       "checklist": ["Оптика", "Освещение", "Оптика"]}])
reg = next(g for g in rr["regs"] if g["name"] == "ТО микроскопа")
check("a regulation with its checklist", reg["id"] and reg["checklist"] == ["Оптика", "Освещение"] and len(rr["regs"]) == 2)
lg = json.loads(d.one("SELECT data FROM equipment_events WHERE kind='settings' ORDER BY id DESC")["data"])
check("added and removed regulations in the log", lg["object"] == "Регламенты обслуживания" and any(c["t"] == "Добавлено" and "ТО микроскопа" in c["new"] for c in lg["changes"])
      and any(c["t"] == "Убрано" for c in lg["changes"]), lg)
rr = a.equipment_ref_save("eq_models", [{"manufacturer": "Sirona", "model": "C8", "article": "6543210", "category": "Стоматологическое оборудование"}])
mo = next(x for x in rr["models"] if x["model"] == "C8")
check("a model of the list counts its cards", not mo["from_cards"] and mo["count"] == 1 and "Sirona" in rr["manufacturers"])
rr = a.equipment_ref_save("eq_disp_reasons", ["Износ", "Поломка", "износ"])
check("reasons of disposal without repeats", [x["name"] for x in rr["disp_reasons"]] == ["Износ", "Поломка"])
refuses("no empty list of reasons", lambda: a.equipment_ref_save("eq_disp_reasons", []), "хотя бы одну")
refuses("an unknown reference", lambda: a.equipment_ref_save("users", []), "Неизвестный")
rr = a.equipment_ref_save("eq_works", [{"name": "Калибровка", "kind": "diag"}, {"name": "Замена турбины", "kind": "repair"}])
check("kinds of work", [w["kind"] for w in rr["works"]] == ["diag", "repair"])

# the regulation in the schedule: its checklist is ticked when the work is done
pid = S.eq_plan_save({"equipment_id": eid, "kind": "service", "every_months": 6, "next_date": ahead(5), "reg_id": reg["id"]})
check("the plan keeps its regulation", next(p for p in S.eq_plans() if p["id"] == pid)["reg_name"] == "ТО микроскопа")
rid = a.equipment_request_save({"equipment_id": eid, "kind": "service", "description": "ТО по графику", "plan_id": pid, "due": ahead(5)})
rq = next(x for x in a.equipment_requests()["requests"] if x["id"] == rid)
check("the request carries the checklist", rq["checklist"] == ["Оптика", "Освещение"] and rq["reg_name"] == "ТО микроскопа")
check("a request is in the log", d.one("SELECT 1 AS x FROM equipment_events WHERE equipment_id=? AND kind='request'", (eid,)))
a.equipment_request_status(rid, "done", {"cost": 3000, "result": "Сделано", "checklist": [{"t": "Оптика", "ok": True}, {"t": "Освещение", "ok": False}]})
ev = d.one("SELECT * FROM equipment_events WHERE equipment_id=? AND kind='service' ORDER BY id DESC", (eid,))
check("the checklist went to the history", "Чек-лист: 1 из 2" in ev["text"] and json.loads(ev["data"])["checklist"][0]["ok"], ev)

# export and import
ex = a.equipment_refs_export()
check("export holds every reference", ex["format"] == "dental-desk-equipment-refs" and ex["eq_groups"] and ex["eq_regs"] and "module" in ex)
a.equipment_ref_save("eq_works", [{"name": "Только это", "kind": "service"}])
im = a.equipment_refs_import(json.loads(json.dumps(ex)))
check("import brings them back", [w["name"] for w in im["refs"]["works"]] == ["Калибровка", "Замена турбины"] and "Виды работ (ТО)" in im["imported"])
refuses("not our file", lambda: a.equipment_refs_import({"format": "x"}), "Dental Desk")

# «Контроль сроков ТО»: the bell, the badge, the day report
S.eq_plan_save({"equipment_id": eid, "kind": "verify", "every_months": 12, "next_date": day(3)})
du = a.equipment_due()
check("overdue and soon in the bell", du["on"] and du["overdue"] >= 1 and any(x["equipment_id"] == eid and x["overdue"] for x in du["items"]))
check("the badge counts them", a.status().get("eq_due") == len(du["items"]) and a.status().get("eq_overdue") == du["overdue"])
rep = a._daily.report(date.today().isoformat())
check("a line of the day report", rep["eq"] and "Оборудование: просрочено ТО" in a._daily.text(rep))
a.equipment_module_save({"to_report": False})
check("…unless switched off", not a._daily.report(date.today().isoformat())["eq"])
a.equipment_module_save({"control_to": False})
check("control off — no bell", not a.equipment_due()["items"] and not a.status().get("eq_due"))
a.equipment_module_save({"control_to": True, "to_report": True})

# rights and integrations
rt = a.equipment_rights()
check("rights: positions and users", rt["positions"][0]["title"] == "Директор" and all(len(p["perms"]) == len(rt["keys"]) for p in rt["positions"]))
it = a.equipment_integrations()
check("integrations", {"dp", "pnl", "report", "phone"} <= set(it) and it["pnl"]["amort"] is True)
for k_ in ("equipment_ref_save", "equipment_module_save", "equipment_refs_export", "equipment_refs_import", "equipment_due",
           "equipment_rights", "equipment_integrations"):
    check(f"{k_} has a right", k_ in auth.METHOD_PERMS)
for k_ in ("equipment_ref_save", "equipment_module_save", "equipment_refs_import"):
    check(f"{k_} is audited", k_ in auth.AUDITED)

# the card's changes: «было → стало»
a.save_equipment({"id": eid, "name": "Установка Sirona C8", "category": "Стоматологическое оборудование", "useful_months": 120, "price": 1250000,
                  "serial": "SN-77", "in_service": day(400)})
ev = d.one("SELECT * FROM equipment_events WHERE equipment_id=? AND kind='edit' ORDER BY id DESC", (eid,))
ch = {c["t"]: c for c in json.loads(ev["data"])["changes"]}
check("the change of the life", ch["Срок службы"]["old"] == "8 лет" and ch["Срок службы"]["new"] == "10 лет", ch)
check("the change of the price is money", ch["Стоимость"]["m"] and ch["Стоимость"]["old"] == "1 200 000 ₽" and ch["Стоимость"]["new"] == "1 250 000 ₽", ch)
check("a new serial", ch["Серийный номер"]["old"] == "—" and ch["Серийный номер"]["new"] == "SN-77")
check("changing the past depreciation is suspicious", "задним числом" in json.loads(ev["data"]).get("flag", ""))
n0 = d.one("SELECT COUNT(*) AS n FROM equipment_events WHERE equipment_id=? AND kind='edit'", (eid,))["n"]
a.save_equipment({"id": eid, "name": "Установка Sirona C8", "category": "Стоматологическое оборудование", "useful_months": 120, "price": 1250000,
                  "in_service": day(400)})
check("nothing changed — no line", d.one("SELECT COUNT(*) AS n FROM equipment_events WHERE equipment_id=? AND kind='edit'", (eid,))["n"] == n0)
a.equipment_set({"id": eid, "condition": "service"})
ev = d.one("SELECT * FROM equipment_events WHERE equipment_id=? ORDER BY id DESC", (eid,))
check("a quick change has its pair", json.loads(ev["data"])["changes"][0] == {"t": "Состояние", "old": "Исправно", "new": "Требует обслуживания"}, ev)

sec = (ROOT / "app" / "ui" / "stock-eqsection.js").read_text(encoding="utf-8")
for part in ("Справочники оборудования", "Быстрые действия", "Ключевые справочники", "Основные настройки модуля", "Справочная информация",
             "Настройки системы", "Пользователи и права", "Интеграции", "Журнал изменений"):
    check(f"UI: {part}", part in sec)

# ================================================ block 2: «Журнал действий» --
lg = a.equipment_log({"from": day(0), "to": day(0)})
check("the log of today", lg["rows"] and all(x["at"][:10] == day(0) for x in lg["rows"]))
check("tiles", lg["tiles"]["total"] == len(lg["rows"]) and lg["tiles"]["users"] >= 1 and lg["tiles"]["today"] >= lg["tiles"]["total"])
ed = next(x for x in lg["rows"] if x["action"] == "edit" and x["equipment_id"] == eid)
check("an edit: the action, the module, the cabinet, the changes", ed["action_title"] == "Редактирование" and ed["module"] == "Оборудование"
      and ed["changes"] and ed["object"] == "Установка Sirona C8" and ed["inv_number"] == "СТ-001", ed)
check("the suspicious edit", ed["suspicious"] and lg["tiles"]["suspicious"] >= 1)
check("only the suspicious", all(x["suspicious"] for x in a.equipment_log({"from": day(0), "suspicious": True})["rows"]))
st = next(x for x in lg["rows"] if x["kind"] == "settings")
check("a change of the settings: its object and module", st["object"] and st["module"] in ("Настройки", "Справочники") and st["equipment_id"] == "")
check("filters: user, action, object, module", all(x["user_name"] == "Ковалев А.В." for x in a.equipment_log({"user": "Ковалев А.В."})["rows"])
      and all(x["action_title"] == "Редактирование" for x in a.equipment_log({"action": "Редактирование"})["rows"])
      and all(x["equipment_id"] == eid for x in a.equipment_log({"object": eid})["rows"])
      and all(x["module"] == "Обслуживание" for x in a.equipment_log({"module": "Обслуживание"})["rows"]))
check("lists of the filters", {"users", "actions", "objects", "modules", "places"} <= set(lg["lists"]) and any(o["id"] == eid for o in lg["lists"]["objects"]))
hidden = S.eq_log({"object": eid}, money=False)
ch = [c for x in hidden["rows"] for c in x["changes"] if c.get("m")]
check("without «Бухгалтерия» the sums are hidden", ch and all(c["old"] == "скрыто" and c["new"] == "скрыто" for c in ch) and all(not x["cost"] for x in hidden["rows"]))
rq_ = next(x for x in a.equipment_log({"object": eid})["rows"] if x["kind"] == "service")
check("the checklist of a work in the log", rq_["checklist"] and rq_["module"] == "Обслуживание")
pid_ = a.equipment_purchase_save({"name": "Новый автоклав", "budget": 500000, "year": date.today().year + 1, "quarter": 1, "justification": "Старый изношен"})
a.equipment_purchase_status(pid_, "send")
pu = [x for x in a.equipment_log({"module": "Планирование"})["rows"] if x["kind"] == "purchase"]
check("the purchase plan in the log", len(pu) >= 2 and any(x["action_title"] == "Создание" and "План закупок" in x["object"] for x in pu)
      and any(x["action_title"] == "На согласование" for x in pu), pu[:2])
ev_ = d.one("SELECT id FROM equipment_events WHERE equipment_id=? ORDER BY id DESC", (eid,))["id"]
d.conn.execute("UPDATE equipment_events SET created_at=? WHERE id=?", (day(0) + " 23:40:00", ev_)); d.conn.commit()
check("an action at night is suspicious", "ночью" in next(x for x in a.equipment_log({"object": eid})["rows"] if x["id"] == ev_)["suspicious"])
old_card = {"ownership": None, "accounting": None, "qty": None, "name": "x"}
check("an empty column of an old card is not a change", stockm.eq_changes(old_card, {"ownership": "own", "accounting": "amort", "qty": 1, "name": "x"}) == [])
for part in ("Журнал действий", "Детали действия", "История изменений по объекту", "Подозрительных действий", "Активных пользователей"):
    check(f"UI log: {part}", part in sec)

print(f"OK: {OK[0]} FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
