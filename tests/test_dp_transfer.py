"""3.3 «Без двойного ввода» (stage 1 of the add-on over Dentist Plus).

Checks: the clinic settings of the transfer (sections, order, names, reminder, the 30-day window) and their errors;
the text «Скопировать для Dentist Plus» — whole and by sections, diagnoses with ICD-10 codes and teeth, prescriptions,
an unsaved form and a dictation result; the mark «перенесено в Dentist Plus» (who / when, the first mark kept, the
mark kept when a record is saved again unchanged and dropped when it changes, the old «Перенос» screen); copying with
and without «отмечать после копирования»; the list «Не перенесено» by day and doctor, the counter, the reminder at the
end of the day, the line in the day report; «Сверка» (records, Dentist Plus visits matched by visit / local visit /
patient + day, invoices and payments with «нет данных из Dentist Plus»); the rows travelling to another computer
(replica); rights over HTTP: the director and «Перенос» see everyone, a doctor only own records, the action journal;
the UI wiring."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import dp_transfer as dpt  # noqa: E402
import replica  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402

FAIL, OK = [], [0]
UI = ROOT / "app" / "ui"


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def raises(fn, *a, exc=ValueError):
    try:
        fn(*a)
    except exc as e:
        return str(e) or "error"
    return None


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


TODAY = date.today()
T = TODAY.isoformat()
Y = (TODAY - timedelta(days=1)).isoformat()
OLD = (TODAY - timedelta(days=45)).isoformat()

d = dbm.DB()
d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}, {"id": 2, "lname": "Сидорова", "fname": "Анна"}])
with d.tx() as c:
    for pid, name in (("101", "Иванов Иван"), ("102", "Смирнова Ольга"), ("103", "Кузнецов Олег"), ("104", "Попова Мария")):
        c.execute("INSERT INTO patients(id, name, phone) VALUES(?,?,?)", (pid, name, ""))
a = Api(d, W())

# ------------------------------------------------------------------ settings
s = dpt.settings(d)
check("default sections in the order of the Dentist Plus form",
      [x["key"] for x in s["sections"] if x["on"]] == ["complaints", "anamnesis", "objective", "diagnoses", "treatment", "recommendations"],
      s["sections"])
check("default titles", [x["title"] for x in s["sections"] if x["on"]] ==
      ["Жалобы", "Анамнез", "Объективно", "Диагноз (МКБ-10)", "Лечение", "Рекомендации"])
check("prescriptions and next visit available but off", {x["key"]: x["on"] for x in s["sections"]}.get("rx") is False
      and {x["key"]: x["on"] for x in s["sections"]}.get("next_visit") is False)
check("defaults: no auto mark, reminder 20:00, 30 days", not s["auto_mark"] and s["remind"] and s["remind_time"] == "20:00" and s["days"] == 30, s)
check("error: no section", "хотя бы один" in (raises(dpt.clean_settings, {"sections": [{"key": k, "on": False} for k in dpt.SECTION_TITLES]}) or ""))
check("error: bad time", "ЧЧ:ММ" in (raises(dpt.clean_settings, {"remind_time": "25:00"}) or ""))
check("error: days out of range", raises(dpt.clean_settings, {"days": 0}) and raises(dpt.clean_settings, {"days": "x"}))
check("short time 9:30 → 09:30", dpt.clean_settings({"remind_time": "9:30"})["remind_time"] == "09:30")
check("unknown and doubled sections dropped", [x["key"] for x in dpt._norm_sections(
    [{"key": "treatment"}, {"key": "nope"}, {"key": "treatment"}])][:1] == ["treatment"] and len(dpt._norm_sections([{"key": "treatment"}])) == 8)
check("garbage in the table does not break", (d.conn.execute("INSERT INTO dp_settings(k, v) VALUES('days', 'oops')"), d.conn.commit(),
                                              dpt.settings(d)["days"])[2] == 30)
d.conn.execute("DELETE FROM dp_settings"); d.conn.commit()

# ------------------------------------------------------------------ text
FULL = {"complaints": "Боль при накусывании", "anamnesis": "Болит 3 дня", "objective": "Глубокая кариозная полость 36",
        "diagnoses": [{"code": "K02.1", "title": "Кариес дентина", "tooth": "36"}, {"code": "K04.0", "title": "Пульпит", "tooth": ""}],
        "treatment": "Анестезия. Пломба.\nПолировка.", "recommendations": "Не есть 2 часа",
        "rx": [{"name": "Нимесил", "dose": "100 мг", "how": "после еды", "days": "3 дня"}], "next_visit": "через неделю"}
b = dpt.build(FULL, s)
check("whole text with titles in order", b["text"].startswith("Жалобы:\nБоль при накусывании\n\nАнамнез:\nБолит 3 дня\n\nОбъективно:"), b["text"][:120])
check("diagnosis: code, name, tooth", "Диагноз (МКБ-10):\nK02.1 Кариес дентина (зуб 36)\nK04.0 Пульпит" in b["text"], b["text"])
check("multi-line treatment kept", "Лечение:\nАнестезия. Пломба.\nПолировка." in b["text"])
check("switched-off sections are not in the text", "Назначения" not in b["text"] and "через неделю" not in b["text"])
check("sections: one per switched-on section", [x["key"] for x in b["sections"]] == [x["key"] for x in s["sections"] if x["on"]])
check("one section without title", b["sections"][0]["text"] == "Боль при накусывании")
s2 = dpt.save_settings(d, {"sections": [{"key": "diagnoses", "title": "Диагноз", "on": True}, {"key": "treatment", "title": "  Проведено  ", "on": True},
                                        {"key": "rx", "on": True}, {"key": "complaints", "on": False}], "days": 14, "remind_time": "19:30"})
b2 = dpt.build(FULL, s2)
check("own order and names", b2["text"].startswith("Диагноз:\nK02.1") and "\n\nПроведено:\nАнестезия" in b2["text"], b2["text"][:90])
check("prescriptions when on", "Назначения:\nНимесил 100 мг — после еды, 3 дня" in b2["text"], b2["text"])
check("sections left out of a saved list are off", not any(x["on"] for x in s2["sections"] if x["key"] in ("anamnesis", "objective", "complaints")))
check("saved: days and time", s2["days"] == 14 and s2["remind_time"] == "19:30")
check("empty record", dpt.build({}, s)["empty"] and dpt.build({}, s)["text"] == "")
check("dictation result (fields + diagnoses)", "Жалобы:\nНоет зуб" in dpt.build(dpt.from_form({"fields": {"complaints": "Ноет зуб"},
      "diagnoses": [{"code": "K02.1", "title": "Кариес дентина"}]}), s)["text"])
check("old diagnosis text", "Кариес 46" in dpt.build({"diagnosis_text": "Кариес 46"}, s)["text"])
dpt.save_settings(d, {"sections": dpt.DEFAULTS["sections"], "days": 30, "remind_time": "20:00"})
check("dp_text of an unsaved form", "Жалобы:\nБоль" in a.dp_text({"complaints": "Боль", "treatment": "Пломба"})["text"])

# ------------------------------------------------------------------ records and the mark
r1 = a.save_record({"patient_id": "101", "doctor_id": "1", "date": T, **FULL})
r2 = a.save_record({"patient_id": "102", "doctor_id": "2", "date": T, "complaints": "Скол", "treatment": "Реставрация"})
r3 = a.save_record({"patient_id": "103", "doctor_id": "1", "date": Y, "complaints": "Осмотр"})
r_old = a.save_record({"patient_id": "104", "doctor_id": "1", "date": OLD, "complaints": "Давно"})
c = a.dp_copy(r1)
check("copy: the whole text", c["text"] == dpt.build(FULL, dpt.settings(d))["text"] and not c["marked"])
row = d.one("SELECT * FROM records WHERE id=?", (r1,))
check("copy remembered (who / when), not marked", row["dp_copied_at"] and not row["transferred"], row)
check("copy one section", a.dp_copy(r1, "objective")["text"] == "Глубокая кариозная полость 36")
check("copy a switched-off section — error", "выключен" in (raises(a.dp_copy, r1, "rx") or ""))
check("copy a missing record — error", raises(a.dp_copy, "nope"))
n = a.dp_mark([r1])
row = d.one("SELECT * FROM records WHERE id=?", (r1,))
check("marked: when", row["transferred"] == 1 and row["transferred_at"], row)
first_at = row["transferred_at"]
with d.tx() as cx:
    cx.execute("UPDATE records SET transferred_at='2000-01-01 10:00:00' WHERE id=?", (r1,))
a.dp_mark([r1])
check("a second mark keeps the first one", d.one("SELECT transferred_at FROM records WHERE id=?", (r1,))["transferred_at"] == "2000-01-01 10:00:00")
check("dp_mark answers the counter", n["changed"] == 1 and isinstance(n["pending"], int), n)
a.save_record({"id": r1, "patient_id": "101", "doctor_id": "1", "date": T, **FULL})
check("saved again unchanged — the mark stays", d.one("SELECT transferred FROM records WHERE id=?", (r1,))["transferred"] == 1)
a.save_record({"id": r1, "patient_id": "101", "doctor_id": "1", "date": T, **{**FULL, "treatment": "Другое лечение"}})
check("changed — the mark goes (Dentist Plus must get the new text)",
      d.one("SELECT transferred, transferred_at, transferred_by FROM records WHERE id=?", (r1,)) == {"transferred": 0, "transferred_at": None, "transferred_by": None})
a.dp_mark([r1])
a.dp_mark([r1], False)
check("mark taken off", d.one("SELECT transferred, transferred_at FROM records WHERE id=?", (r1,)) == {"transferred": 0, "transferred_at": None})
a.mark_transferred("records", [r3], True)
check("old «Перенос» screen marks records the same way", d.one("SELECT transferred FROM records WHERE id=?", (r3,))["transferred"] == 1)
a.mark_transferred("records", [r3], False)
dpt.save_settings(d, {"auto_mark": True})
c = a.dp_copy(r2, "treatment")
check("auto mark: not after one section", not c["marked"] and not d.one("SELECT transferred FROM records WHERE id=?", (r2,))["transferred"])
c = a.dp_copy(r2)
check("auto mark after copying the whole record", c["marked"] and d.one("SELECT transferred FROM records WHERE id=?", (r2,))["transferred"] == 1)
dpt.save_settings(d, {"auto_mark": False})
a.dp_mark([r2], False)

# ------------------------------------------------------------------ the list, the counter, the reminder
p = a.dp_pending()
check("list: the last 30 days, not transferred", {x["id"] for x in p["items"]} == {r1, r2, r3}, [x["id"] for x in p["items"]])
check("counter over 30 days", p["count"] == 3 and p["left"] == 3, (p["count"], p["left"]))
check("grouped: today first, then yesterday", [g["day"] for g in p["groups"]] == [T, Y], [g["day"] for g in p["groups"]])
check("grouped by doctor within the day", [x["doctor_name"] for x in p["groups"][0]["doctors"]] == sorted(x["doctor_name"] for x in p["groups"][0]["doctors"])
      and len(p["groups"][0]["doctors"]) == 2)
check("by doctor summary", {x["doctor_id"]: x["n"] for x in p["by_doctor"]} == {"1": 2, "2": 1}, p["by_doctor"])
check("item: patient, brief, sections", next(x for x in p["items"] if x["id"] == r1)["patient_name"] == "Иванов Иван"
      and "K02.1" in next(x for x in p["items"] if x["id"] == r1)["brief"])
check("a longer period finds the old record", r_old in {x["id"] for x in a.dp_pending(OLD, T)["items"]})
check("doctor filter", {x["id"] for x in a.dp_pending(None, None, "2")["items"]} == {r2})
a.dp_mark([r3])
check("transferred are hidden, shown on request", r3 not in {x["id"] for x in a.dp_pending()["items"]}
      and r3 in {x["id"] for x in a.dp_pending(None, None, None, True)["items"]})
check("bad period", raises(a.dp_pending, "2020-01-01", "2026-01-01") and raises(a.dp_pending, "nope"))
late, early = datetime.combine(TODAY, datetime.min.time()).replace(hour=20, minute=5), datetime.combine(TODAY, datetime.min.time()).replace(hour=12)
check("reminder after the time: the doctor's records of today", dpt.remind(d, "1", late) == 1 and dpt.remind(d, "2", late) == 1)
check("no reminder before the time", dpt.remind(d, "1", early) == 0)
dpt.save_settings(d, {"remind": False})
check("reminder off", dpt.remind(d, "1", late) == 0)
dpt.save_settings(d, {"remind": True})
st = a.status()
check("status: the counter", st.get("dp", {}).get("pending") == 2, st.get("dp"))

# ------------------------------------------------------------------ the day report
rep = a.day_report(T)
check("day report: the line about the medical card", "Медкарта: записей за день — 2, не перенесено в Dentist Plus — 2" in rep["text"], rep["text"])
check("day report: by doctor", "Петров Пётр — 1" in rep["text"] and "Сидорова Анна — 1" in rep["text"], rep["text"])
check("day report: the 30-day window", rep["dp"]["window"] == 2)
a.dp_mark([r1, r2])
rep = a.day_report(T)
check("day report: all transferred", "все перенесены в Dentist Plus" in rep["text"], rep["text"])
check("day report xlsx builds", a._daily.xlsx(rep)[:2] == b"PK")
a.dp_mark([r1, r2], False)
check("no records at all: no line", dpt.report_lines({"total": 0, "window": 0, "pending": 0, "by_doctor": [], "days": 30}) == [])

# ------------------------------------------------------------------ reconciliation
rc = a.dp_reconcile()
check("no Dentist Plus visits yet → «нет данных из Dentist Plus»", next(x for x in rc["rows"] if x["key"] == "visits")["dp"] == dpt.NO_DP)
check("payments of Dentist Plus: no data", rc["payments_dp"] == dpt.NO_DP and next(x for x in rc["rows"] if x["key"] == "payments")["dp"] == dpt.NO_DP)
with d.tx() as cx:
    for vid, pid, doc, start, status in (("v1", "101", "1", f"{T} 10:00", "Завершён"), ("v2", "102", "2", f"{T} 11:00", "Завершён"),
                                         ("v3", "103", "1", f"{Y} 12:00", "Пришёл"), ("v4", "104", "2", f"{T} 13:00", "Завершён"),
                                         ("v5", "104", "1", f"{T} 14:00", "Отменён")):
        cx.execute('INSERT INTO visits(id, patient_id, doctor_id, start, "end", status) VALUES(?,?,?,?,?,?)', (vid, pid, doc, start, start, status))
    cx.execute('INSERT INTO visits_archive(id, patient_id, doctor_id, start, "end", status) VALUES(?,?,?,?,?,?)',
               ("v6", "102", "2", f"{Y} 09:00", f"{Y} 09:30", "Завершён"))
    cx.execute("INSERT INTO local_visits(id, origin_id, patient_id, doctor_id, start, status, action) VALUES('L-1','v6','102','2',?,?, 'status')",
               (f"{Y} 09:00", "Завершён"))
    cx.execute("INSERT INTO invoices(id, patient_id, doctor_id, items, total, status, created_at, kind, transferred) VALUES('i1','101','1','[]',5000,'Оплачен',?, 'invoice', 1)",
               (f"{T} 10:30:00",))
    cx.execute("INSERT INTO invoices(id, patient_id, doctor_id, items, total, status, created_at, kind) VALUES('i2','102','2','[]',3000,'',?, 'invoice')",
               (f"{T} 11:30:00",))
    cx.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, created_at) VALUES('p1','i1','101',5000,'Карта',?)", (f"{T} 10:31:00",))
    cx.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, created_at, kind) VALUES('p2','i1','101',-100,'Из аванса',?, 'deposit_use')",
               (f"{T} 10:32:00",))
r6 = a.save_record({"patient_id": "102", "doctor_id": "2", "date": T, "visit_id": "L-1", "complaints": "по местной записи"})  # another day: only the visit links it
rc = a.dp_reconcile()
vis = next(x for x in rc["rows"] if x["key"] == "visits")
without = {x["visit_id"] for x in rc["visits_without_record"]}
check("finished visits of Dentist Plus counted (cancelled and planned are not)", vis["dp"] == 5, vis)
check("matched: patient + day, a visit changed here (origin)", without == {"v4"}, without)
check("visits row: with / without a record", vis["dd"] == 4 and vis["left"] == 1, vis)
recs = next(x for x in rc["rows"] if x["key"] == "records")
check("records row: in the program, marked, left", recs["dd"] == 4 and recs["marked"] == 1 and recs["left"] == 3, recs)
inv = next(x for x in rc["rows"] if x["key"] == "invoices")
check("invoices: count, sum, marked", inv["dd"] == 2 and inv["sum"] == 8000 and inv["marked"] == 1 and inv["left"] == 1 and inv["dp"] == dpt.NO_DP, inv)
pay = next(x for x in rc["rows"] if x["key"] == "payments")
check("payments: moves of the advance left out", pay["dd"] == 1 and pay["sum"] == 5000, pay)
check("not transferred list", {x["id"] for x in rc["not_transferred"]} == {r1, r2, r6}, [x["id"] for x in rc["not_transferred"]])
check("days with Dentist Plus data", rc["dp_span"] and rc["dp_span"]["from"] == Y and rc["dp_span"]["to"] == T, rc["dp_span"])
rc2 = a.dp_reconcile(None, None, "2")
check("reconciliation by doctor", {x["visit_id"] for x in rc2["visits_without_record"]} == {"v4"}
      and next(x for x in rc2["rows"] if x["key"] == "invoices")["dd"] == 1, rc2["rows"])
r7 = a.save_record({"patient_id": "104", "doctor_id": "2", "date": T, "visit_id": "v4", "complaints": "по визиту"})
check("matched by the Dentist Plus visit id", not a.dp_reconcile()["visits_without_record"])

# ------------------------------------------------------------------ another computer gets the marks and settings
names = {t.name for t in replica.TABLES}
check("records and dp_settings are synced", {"records", "dp_settings"} <= names)
replica.install(d)
a.dp_mark([r7])
d2path = Path(tempfile.mkdtemp()) / "b.db"
d2 = dbm.DB(d2path)
replica.install(d2)
t_rec, t_set = replica.BY_NAME["records"], replica.BY_NAME["dp_settings"]
row = replica.read_row(d.conn, t_rec, [r7])
check("the travelling row carries who / when", row.get("transferred") == 1 and "transferred_by" in row and "dp_copied_at" in row, row)
replica.set_applying(d2.conn, True)
replica.write_row(d2.conn, t_rec, [r7], row)
for k in [x["k"] for x in d.q("SELECT k FROM dp_settings")]:
    replica.write_row(d2.conn, t_set, [k], replica.read_row(d.conn, t_set, [k]))
replica.set_applying(d2.conn, False)
d2.conn.commit()
check("the other computer sees the mark", d2.one("SELECT transferred, transferred_at FROM records WHERE id=?", (r7,))["transferred"] == 1)
check("the other computer has the same settings", dpt.settings(d2)["sections"] == dpt.settings(d)["sections"])
a.dp_mark([r7], False)

# ------------------------------------------------------------------ rights over HTTP
check("every new method has a right", all(m in auth.METHOD_PERMS for m in
      ("dp_transfer_settings", "dp_transfer_settings_save", "dp_text", "dp_copy", "dp_mark", "dp_pending", "dp_reconcile")))
check("the mark and the settings are in the action journal", "dp_mark" in auth.AUDITED and "dp_transfer_settings_save" in auth.AUDITED)
check("reading is not journaled", not {"dp_copy", "dp_pending", "dp_reconcile", "dp_text"} & set(auth.AUDITED))
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
staff = {}
for login, role, doc in (("doc1", "doctor", "1"), ("doc0", "doctor", None), ("adm", "admin", None), ("asst", "assistant", None)):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active", "doctor_id": doc}, token=TD)
    staff[login] = call("auth", "login", login, "secret1")[1]["token"]
st, body = call("api", "dp_pending", token=TD)
check("director sees everyone's records", st == 200 and {x["doctor_id"] for x in body["items"]} == {"1", "2"} and body["all"], (st, str(body)[:200]))
st, body = call("api", "dp_pending", token=staff["adm"])
check("«Перенос» (administrator) sees everyone's", st == 200 and {x["doctor_id"] for x in body["items"]} == {"1", "2"}, (st, str(body)[:200]))
st, body = call("api", "dp_pending", token=staff["doc1"])
check("a doctor sees only own records", st == 200 and body["items"] and {x["doctor_id"] for x in body["items"]} == {"1"} and not body["all"]
      and body["doctors"] == [], (st, str(body)[:300]))
st, body = call("api", "dp_pending", None, None, "2", token=staff["doc1"])
check("a doctor cannot look at another doctor by the filter", st == 200 and {x["doctor_id"] for x in body["items"]} <= {"1"}, body.get("items"))
st, body = call("api", "dp_pending", token=staff["doc0"])
check("a doctor without a linked doctor sees nothing and is told", st == 200 and not body["items"] and body["linked"] is False, body)
check("assistant has no list", call("api", "dp_pending", token=staff["asst"])[0] == 403)
st, body = call("api", "dp_mark", [r2], True, token=staff["doc1"])
check("a doctor cannot mark another doctor's record", st == 400 and "свои" in body.get("error", ""), (st, body))
st, body = call("api", "dp_mark", [r1], True, token=staff["doc1"])
check("a doctor marks own record", st == 200 and body["changed"] == 1, (st, body))
check("who marked it", d.one("SELECT transferred_by FROM records WHERE id=?", (r1,))["transferred_by"] == "doc1")
au = call("auth", "audit_list", token=TD)[1]
check("the mark is in the action journal", any(x["action"] == auth.AUDITED["dp_mark"] and x["user_name"] == "doc1" and "да" in (x["detail"] or "") for x in au),
      [(x["action"], x["detail"]) for x in au[:5]])
check("a doctor without a linked doctor cannot mark", call("api", "dp_mark", [r3], True, token=staff["doc0"])[0] == 400)
check("assistant cannot mark", call("api", "dp_mark", [r3], True, token=staff["asst"])[0] == 403)
st, body = call("api", "dp_copy", r2, token=staff["asst"])
check("assistant (medcard view) may copy the text", st == 200 and "Скол" in body["text"], (st, body))
dpt.save_settings(d, {"auto_mark": True})
call("api", "dp_copy", r2, token=staff["asst"])
check("…but the copy does not mark for someone who may not mark", not d.one("SELECT transferred FROM records WHERE id=?", (r2,))["transferred"])
a.dp_mark([r3], False)
call("api", "dp_copy", r3, token=staff["doc1"])
check("auto mark for the doctor's own record", d.one("SELECT transferred, transferred_by FROM records WHERE id=?", (r3,)) == {"transferred": 1, "transferred_by": "doc1"})
dpt.save_settings(d, {"auto_mark": False})
check("reconciliation: director yes", call("api", "dp_reconcile", token=TD)[0] == 200)
check("reconciliation: administrator («Перенос») yes", call("api", "dp_reconcile", token=staff["adm"])[0] == 200)
check("reconciliation: doctor no", call("api", "dp_reconcile", token=staff["doc1"])[0] == 403)
check("settings: a doctor reads", call("api", "dp_transfer_settings", token=staff["doc1"])[0] == 200)
check("settings: a doctor cannot change", call("api", "dp_transfer_settings_save", {"days": 7}, token=staff["doc1"])[0] == 403)
st, body = call("api", "dp_transfer_settings_save", {"remind_time": "00:00"}, token=TD)
check("settings: the director changes", st == 200 and body["remind_time"] == "00:00", (st, body))
st, body = call("api", "status", token=staff["doc1"])
check("doctor's status: own counter and the reminder", st == 200 and body["dp"]["pending"] >= 0 and body["dp"]["remind"] == 0
      and body["dp"]["remind_time"] == "00:00", body.get("dp"))
a.save_record({"patient_id": "103", "doctor_id": "1", "date": T, "complaints": "Новый приём"})
st, body = call("api", "status", token=staff["doc1"])
check("doctor's status: the reminder counts today's own records", body["dp"]["remind"] == 1, body.get("dp"))
check("assistant's status has no counter", "dp" not in call("api", "status", token=staff["asst"])[1])
check("administrator's status: the clinic counter", call("api", "status", token=staff["adm"])[1]["dp"]["pending"] >= 1)
srv.stop()

# ------------------------------------------------------------------ the UI
html = (UI / "index.html").read_text(encoding="utf-8")
js = (UI / "dp.js").read_text(encoding="utf-8")
check("version 3.3.0 or later", tuple(map(int, config.VERSION.split("."))) >= (3, 3, 0), config.VERSION)
check("dp.js loaded with the cache tag", f'<script src="dp.js?v={config.VERSION}"></script>' in html)
check("no old cache tags", "?v=3.2.0" not in html)
check("tabs in «Перенос»", 'id="jTabs"' in html and 'data-jt="med"' in html and 'data-jt="check"' in html)
check("a doctor reaches «Перенос»", 'data-view="journal" data-perm-any="transfer,reports,medcard_edit"' in html)
check("settings panel", 'id="dpSetBody"' in html and "Перенос медкарты в Dentist Plus" in html)
appjs = (UI / "app.js").read_text(encoding="utf-8")
check("app.js: view rights, status, record tools, settings", 'journal: ["transfer", "reports", "medcard_edit"]' in appjs and "dpStatus(st)" in appjs
      and "dpRecTools(r)" in appjs and "dpBindRecTools(" in appjs and "loadDpSettings()" in appjs)
check("record editor: copy what is in the form", 'id="rDpCopy"' in (UI / "record.js").read_text(encoding="utf-8"))
check("journal tabs call the lists", "dpLoadPending(" in (UI / "journal.js").read_text(encoding="utf-8") and "dpLoadCheck(" in (UI / "journal.js").read_text(encoding="utf-8"))
for fn in ("dpClip", "dpCopyRecord", "dpTransferModal", "dpRecTools", "dpBindRecTools", "dpEditorCopy", "dpLoadPending", "dpLoadCheck", "dpStatus", "loadDpSettings"):
    check(f"dp.js: {fn}", re.search(rf"function {fn}\(", js) is not None)
check("the words «нет данных из Dentist Plus» come from the server", "no_dp" in js)
node = shutil.which("node")
if node:
    for f in ("dp.js", "journal.js", "app.js", "record.js"):
        r = subprocess.run([node, "--check", str(UI / f)], capture_output=True, text=True)
        check(f"{f} parses", r.returncode == 0, r.stderr[:300])
css = (UI / "styles-medcard.css").read_text(encoding="utf-8")
check("styles", ".dp-rt{" in css and ".dp-line{" in css and ".j-row.dp-row{" in css)
notes = ROOT / "docs" / "Что нового в версии 3.3.txt"
check("what's new 3.3", notes.exists() and "Dental Desk" in notes.read_text(encoding="utf-8"))
readme = (ROOT / "README.md").read_text(encoding="utf-8")
check("README section and test", "No double entry (3.3)" in readme and "test_dp_transfer.py" in readme)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
