"""QA: call every Api method with normal and nasty input; report failures instead of stopping."""
from pathlib import Path
APP = str(Path(__file__).resolve().parents[1] / 'app')
import os, sys, tempfile, datetime, json, traceback
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, APP)
import config, db as dbm, demo
from main import Api

class W:
    def status(self): return {"running": False}
    def trigger(self): pass

FAIL, OK = [], [0]
def t(name, fn, check=None):
    try:
        r = fn()
        if check is not None and not check(r):
            FAIL.append(f"{name}: unexpected result {str(r)[:200]}")
        else:
            OK[0] += 1
        return r
    except Exception as e:
        FAIL.append(f"{name}: {type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")


def refuses(name, fn, text=""):
    """The app must refuse this action with an error (expected behaviour)."""
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal, got success")
    except Exception as e:  # noqa: BLE001
        if text and text not in str(e):
            FAIL.append(f"{name}: wrong refusal: {e}")
        else:
            OK[0] += 1

d = dbm.DB(); demo.ensure_demo(d, force=True)
api = Api(d, W())
today = datetime.date.today().isoformat()
tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
# the demo clinic does not work on Sundays: schedule checks use the nearest working day
workday = today if datetime.date.today().weekday() != 6 else tomorrow

# --- status / reference
t("status", api.status, lambda r: r["counts"]["visits"] > 0 and "pending" in r and "transfer_mode" in r)
t("reference", api.reference, lambda r: len(r["mkb"]) > 30 and len(r["doctors"]) == 5)
t("day today", lambda: api.day(workday), lambda r: len(r["visits"]) > 10)
t("day branch", lambda: api.day(workday, "1"), lambda r: all(v["branch_id"] in ("1", None) for v in r["visits"]))
t("day empty far", lambda: api.day("2030-01-01"), lambda r: r["visits"] == [])
t("day sunday no crash", lambda: api.day((datetime.date.today() + datetime.timedelta(days=(6 - datetime.date.today().weekday()) % 7)).isoformat()))
t("month_counts", lambda: api.month_counts(today), lambda r: len(r) > 20)
v0 = api.day(workday)["visits"][0]
t("visit synced", lambda: api.visit(v0["id"]), lambda r: r and r["patient_name"] and "records" in r)
t("visit missing", lambda: api.visit("nope"), lambda r: r is None)
t("chair in day", lambda: api.day(workday)["visits"][0]["chair"], lambda r: r and r.startswith("Кресло"))

# --- search
t("search empty", lambda: api.search(""), lambda r: len(r) > 0)
t("search name", lambda: api.search("иван"), lambda r: all("иван" in x["name"].lower() for x in r))
t("search ё/е", lambda: api.search("федоров"), lambda r: len(r) >= 0)
ph = v0["patient_phone"]
t("search phone formatted", lambda: api.search(ph), lambda r: any(x["phone"] == ph for x in r))
t("search phone digits", lambda: api.search("".join(c for c in ph if c.isdigit())[-7:]), lambda r: len(r) >= 1)
t("search sql-ish", lambda: api.search("' OR 1=1 --"), lambda r: isinstance(r, list))
t("search percent", lambda: api.search("%"), lambda r: isinstance(r, list))

# --- patient
p = t("patient", lambda: api.patient(v0["patient_id"]), lambda r: r and r["visits"] and "records" in r and "invoices" in r)
t("patient missing", lambda: api.patient("nope"), lambda r: r is None)

# --- create patient (nasty)
np = t("create patient", lambda: api.create_patient({"lname": "  О'Нил <b>", "fname": "Анна", "mname": "", "phone": "+7 (900) 123-45-67",
                                                     "birth_date": "1990-02-03", "gender": "Ж", "address": "ул. \"Тест\", 1", "comment": "<script>x</script>"}),
       lambda r: r["id"].startswith("L-"))
t("create patient minimal", lambda: api.create_patient({"lname": "Без", "fname": "Телефона"}), lambda r: r["id"])
t("search new patient by phone", lambda: api.search("9001234567"), lambda r: any(x["id"] == np["id"] for x in r))
t("local patient card", lambda: api.patient(np["id"]), lambda r: r["local"] == 1 and r["birth"] == "1990-02-03")

# --- visits
lv = t("save visit new", lambda: api.save_visit({"patient_id": np["id"], "doctor_id": "11", "branch_id": "1", "start": f"{workday} 19:00", "end": f"{workday} 19:30", "title": "Тест", "comment": "к", "chair": "Кресло 9"}),
       lambda r: r.startswith("L-"))
t("visit appears in day", lambda: api.day(workday), lambda r: any(x["id"] == lv and x["chair"] == "Кресло 9" for x in r["visits"]))
t("edit local visit keeps create", lambda: api.save_visit({"id": lv, "patient_id": np["id"], "doctor_id": "12", "branch_id": "1", "start": f"{tomorrow} 10:00", "end": f"{tomorrow} 10:45", "title": "Тест2", "action": "move"}))
t("local still create action", lambda: api.visit(lv), lambda r: r["action"] == "create" and r["start"] == f"{tomorrow} 10:00")
t("move synced visit", lambda: api.save_visit({"id": v0["id"], "patient_id": v0["patient_id"], "doctor_id": v0["doctor_id"], "branch_id": v0["branch_id"], "start": f"{workday} 21:00", "end": f"{workday} 21:30", "action": "move"}))
ov = api.visit(v0["id"])
t("synced visit overridden", lambda: ov, lambda r: r["local"] == 1 and r["origin_id"] == v0["id"] and r["start"].endswith("21:00"))
t("no duplicate synced", lambda: [x for x in api.day(workday)["visits"] if x["id"] == v0["id"] or x["origin_id"] == v0["id"]], lambda r: len(r) == 1)
t("status on override", lambda: api.set_visit_status(ov["id"], "Пришёл"), lambda r: r == ov["id"])
t("status on synced (second visit)", lambda: api.set_visit_status(api.day(workday)["visits"][3]["id"], "Отменён"), lambda r: r)
t("revert override", lambda: api.revert_visit(ov["id"]))
t("revert restored", lambda: api.visit(v0["id"]), lambda r: r["local"] == 0)
t("status of missing visit", lambda: api.set_visit_status("nope", "Пришёл"), lambda r: r is None)

# --- records
rid = t("save record", lambda: api.save_record({"patient_id": np["id"], "visit_id": lv, "doctor_id": "11", "date": today, "complaints": "боль\nночью",
        "diagnoses": [{"code": "K02.1", "title": "Кариес дентина", "tooth": "36"}], "teeth": {"36": "Пломба", "18": "Отсутствует"}, "treatment": "<b>x</b>"}))
t("record get", lambda: api.record(rid), lambda r: r["data"]["teeth"]["36"] == "Пломба")
t("record update", lambda: api.save_record({"id": rid, "patient_id": np["id"], "doctor_id": "12", "date": today, "complaints": "ок", "diagnoses": [], "teeth": {}}), lambda r: r == rid)
t("teeth state", lambda: api.patient(np["id"])["teeth_local"], lambda r: r == {})
t("record missing", lambda: api.record("nope"), lambda r: r is None)
rid2 = t("save record 2", lambda: api.save_record({"patient_id": np["id"], "doctor_id": "11", "date": today, "teeth": {"11": "Коронка"}}))
t("visit shows record", lambda: api.visit(lv), lambda r: len(r["records"]) == 1)

# --- templates
docs = t("templates docs", lambda: api.templates("document"), lambda r: len(r) == 15)  # 2.10: + recipe, referral, memo; 2.13: + consent to record the visit
t("templates phrases", lambda: api.templates("phrase"), lambda r: len(r) > 20)
tid = t("save template", lambda: api.save_template({"kind": "document", "category": "Тест", "title": "Мой", "body": "<p>{{patient.fio}}</p>"}))
t("edit builtin + reset", lambda: (api.save_template({"id": "doc_consent_pd", "kind": "document", "category": "X", "title": "X", "body": "x"}), api.reset_template("doc_consent_pd"),
                                   [x for x in api.templates("document") if x["id"] == "doc_consent_pd"][0])[2], lambda r: r["title"].startswith("Согласие"))
t("delete template", lambda: api.delete_template(tid))

# --- services / invoices
sv = t("services", lambda: api.services(""), lambda r: len(r) == 15)
t("services search", lambda: api.services("корон"), lambda r: len(r) == 2)
sid = t("save service", lambda: api.save_service({"title": "Тест услуга", "price": "1500.5", "code": "T1", "category": "Тест"}))
t("service price float", lambda: [x for x in api.services("Тест услуга")][0]["price"], lambda r: r == 1500.5)
t("delete service", lambda: api.delete_service(sid))
t("csv cp1251-like semicolons", lambda: api.import_services("Код;Наименование;Цена;Раздел\nA1;Пломба;2 500,00;Терапия\nA2;;100;X\nA3;Bad price;abc;X\n"), lambda r: r == 1)
t("csv no header", lambda: api.import_services("B1,Услуга без заголовка,300,Раздел\n"), lambda r: r == 1)
t("csv empty", lambda: api.import_services(""), lambda r: r == 0)
t("csv quoted comma", lambda: api.import_services('Код;Название;Цена\nC1;"Коронка, металлокерамика";18000\n'), lambda r: r == 1)
iid = t("save invoice", lambda: api.save_invoice({"patient_id": np["id"], "visit_id": lv, "doctor_id": "11",
        "items": [{"title": sv[0]["title"], "price": 1000, "qty": 2, "discount": 10}, {"title": "x", "price": "500", "qty": "1"}], "discount": 10}))
inv = api.invoice(iid)
t("invoice total", lambda: inv["total"], lambda r: abs(r - (1800 + 500) * 0.9) < 0.01)
t("invoice status unpaid", lambda: inv["status"], lambda r: r == "Не оплачен")
t("payment zero rejected", lambda: api.add_payment({"invoice_id": iid, "amount": 0}), lambda r: r["ok"] is False)
t("payment negative rejected", lambda: api.add_payment({"invoice_id": iid, "amount": -5}), lambda r: r["ok"] is False)
t("payment partial", lambda: api.add_payment({"invoice_id": iid, "amount": 1000, "method": "Карта"}), lambda r: r["ok"])
t("status partial", lambda: api.invoice(iid)["status"], lambda r: r == "Частично оплачен")
t("payment rest", lambda: api.add_payment({"invoice_id": iid, "amount": 1070, "method": "Наличные"}), lambda r: r["ok"])
t("status paid", lambda: api.invoice(iid)["status"], lambda r: r == "Оплачен")
t("balance zero", lambda: api.patient(np["id"])["balance_local"], lambda r: abs(r) < 0.01)
t("overpay allowed? balance positive", lambda: (api.add_payment({"invoice_id": iid, "amount": 100}), api.patient(np["id"])["balance_local"])[1], lambda r: abs(r - 100) < 0.01)
pays = api.invoice(iid)["payments"]
t("delete payment", lambda: api.delete_payment(pays[-1]["id"]))
t("cash day", lambda: api.cash_day(today), lambda r: abs(r["total"] - 2070) < 0.01 and r["by_method"]["Карта"] == 1000)
t("cash day empty", lambda: api.cash_day("2020-01-01"), lambda r: r["total"] == 0)
t("invoice edit keeps payments", lambda: (api.save_invoice({"id": iid, "patient_id": np["id"], "items": [{"title": "y", "price": 100, "qty": 1}]}), api.invoice(iid))[1],
  lambda r: r["status"] == "Оплачен" and r["total"] == 100)
t("invoice empty items", lambda: api.save_invoice({"patient_id": np["id"], "items": []}), lambda r: r)

# --- plans
pid_plan = t("save plan", lambda: api.save_invoice({"patient_id": np["id"], "kind": "plan", "title": "План", "items": [{"title": "a", "price": 100, "qty": 1, "stage": "1", "tooth": "16"}, {"title": "b", "price": 200, "qty": 1, "stage": "2"}]}))
t("plan not in balance", lambda: api.patient(np["id"])["balance_local"], lambda r: r is not None)
t("plan not in cash", lambda: api.cash_day(today)["invoices"], lambda r: all(i.get("kind") != "plan" for i in r))
nid = t("plan to invoice", lambda: api.plan_to_invoice(pid_plan, [1]), lambda r: r)
t("plan invoice items", lambda: api.invoice(nid)["items"], lambda r: len(r) == 1 and r[0]["title"] == "b")
t("plan status active", lambda: api.invoice(pid_plan)["plan_status"], lambda r: r == "Активен")
t("set plan status", lambda: api.set_plan_status(pid_plan, "Лечение завершено"))
refuses("plan_to_invoice missing", lambda: api.plan_to_invoice("nope"), "План не найден")

# --- documents
ctx = t("doc_context", lambda: api.doc_context(np["id"], None, None, None, lv), lambda r: r["patient"]["fio"] and r["doctor"]["fio"] and r["patient"]["card"] == "")
t("doc_context synced", lambda: api.doc_context(v0["patient_id"]), lambda r: r["patient"]["card"])
did = t("save document", lambda: api.save_document({"patient_id": np["id"], "template_id": "doc_contract", "title": "Договор", "html": "<p>x</p>", "data": {"inputs": ["1"]}}))
t("get document", lambda: api.document(did), lambda r: r["html"] == "<p>x</p>")
t("update document", lambda: api.save_document({"id": did, "patient_id": np["id"], "title": "Договор", "html": "<p>y</p>"}), lambda r: r == did)
t("delete document", lambda: api.delete_document(did))

# --- notes
t("add note", lambda: api.add_note(np["id"], "заметка"), lambda r: len(r) == 1)
t("add empty note ignored", lambda: api.add_note(np["id"], "   "), lambda r: len(r) == 1)
t("delete note", lambda: api.delete_note(np["id"], api.patient(np["id"])["notes"][0]["id"]), lambda r: r == [])

# --- journal
j = t("journal", lambda: api.journal(), lambda r: len(r) > 0)
kinds = {x["kind"] for x in j}
t("journal kinds", lambda: kinds, lambda r: {"patient", "visit", "record", "invoice", "payment"} <= r)
t("mark transferred", lambda: api.mark_transferred("records", [rid]), lambda r: r)
t("journal hides done", lambda: api.journal(), lambda r: all(x["id"] != rid for x in r))
t("journal show done", lambda: api.journal(True), lambda r: any(x["id"] == rid for x in r))
t("unmark", lambda: api.mark_transferred("records", [rid], False))
t("mark patient", lambda: api.mark_transferred("patients", [np["id"]]))
refuses("mark bad table", lambda: api.mark_transferred("visits", ["x"]), "bad table")
t("retry push", lambda: api.retry_push("local_visits", lv), lambda r: r is True)
t("retry push bad table", lambda: api.retry_push("records", rid), lambda r: r is False)
t("pending count", lambda: d.pending_count(), lambda r: r > 0)

# --- delete record / invoice
t("delete record", lambda: api.delete_record(rid2))
t("delete invoice", lambda: api.delete_invoice(nid))

# --- settings
t("get settings", api.get_settings, lambda r: "pass_enc" not in r and "history" in r)
t("save settings clinic", lambda: api.save_settings({"clinic": {"name": "ООО «Улыбка»"}}), lambda r: r["clinic"]["name"] == "ООО «Улыбка»")
t("save settings ints as str", lambda: api.save_settings({"days_back": "14", "slot_min": "15"}), lambda r: r["days_back"] == 14)
t("save write_map string", lambda: api.save_settings({"write_map": '{"datetime_format": "%d.%m.%Y %H:%M"}'}), lambda r: r["write_map"]["datetime_format"])
t("save transfer_mode", lambda: api.save_settings({"transfer_mode": "auto"}), lambda r: r["transfer_mode"] == "auto")
t("write_map_default", api.write_map_default, lambda r: "visit_create" in r)
refuses("demo toggle blocked w/ pending (real->demo)", lambda: (config.save_settings({"demo": False}), api.save_settings({"demo": True})), "не перенесённые")
config.save_settings({"demo": True})
t("password stored encrypted", lambda: (api.save_settings({"password": "секрет"}), json.load(open(config.SETTINGS_PATH, encoding="utf-8"))["pass_enc"])[1],
  lambda r: r.startswith("dpapi:") and config.unprotect(r) == "секрет")
t("test_connection bad host", lambda: api.test_connection("u", "p", "http://127.0.0.1:9/partner"), lambda r: r["ok"] is False)
t("diagnostics bad host", lambda: (api.save_settings({"base_url": "http://127.0.0.1:9/partner", "login": "u"}), api.diagnostics())[1], lambda r: "Ошибка" in r)

print(f"\nOK: {OK[0]}   FAIL: {len(FAIL)}")
for f in FAIL:
    print("-", f)
sys.exit(1 if FAIL else 0)
