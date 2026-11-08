"""Marketing: patient sources and their report, call lists with call log, birthdays, «do not call», rights."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
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


def refuses(name, fn, text=""):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except ValueError as e:
        check(name, not text or text in str(e), e)


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
today = date.today()
doc = d.doctors()[0]["id"]

# --- sources
src = a.mk_sources()
check("default sources", "Яндекс Карты" in src and len(src) >= 5)
refuses("empty source list", lambda: a.save_mk_sources(["", " "]), "хотя бы один")
check("sources saved, deduplicated", a.save_mk_sources(["Сайт", "Сайт", " Карты ", "Друзья"]) == ["Сайт", "Карты", "Друзья"])
new = a.create_patient({"lname": "Новикова", "fname": "Анна", "phone": "+7 900 111-22-33",
                        "birth_date": (today + timedelta(days=2)).replace(year=(today + timedelta(days=2)).year - 30).isoformat()})
pid = new["id"]
check("set source", a.set_patient_marketing(pid, {"source": "Карты"}))
check("source in patient card", a.patient(pid)["marketing"]["source"] == "Карты")
refuses("unknown patient", lambda: a.set_patient_marketing("nope", {"source": "Сайт"}), "не найден")
a.add_payment({"patient_id": pid, "amount": 4000, "method": "Карта"})
rep = a.mk_sources_report(today.isoformat(), today.isoformat())
row = next((r for r in rep["rows"] if r["source"] == "Карты"), None)
check("source report: new patient and money", row and row["new"] == 1 and row["patients"] == 1 and row["paid"] == 4000, rep["rows"])
check("source report: with source count", rep["with_source"] == 1)
# a source that Dentist Plus already knows is picked up, a local choice wins
some = d.q("SELECT id FROM patients WHERE local=0 LIMIT 2")
d.conn.execute("UPDATE patients SET detail=json_set(COALESCE(detail,data),'$.source','Реклама в лифте') WHERE id IN (?,?)",
               (some[0]["id"], some[1]["id"])); d.conn.commit()
a.set_patient_marketing(some[1]["id"], {"source": "Сайт"})
rep = a.mk_sources_report(today.isoformat(), today.isoformat())
check("source from Dentist Plus", any(r["source"] == "Реклама в лифте" and r["patients"] == 1 for r in rep["rows"]), rep["rows"])

# --- call list: remind about tomorrow's visits (cancelled ones are not called)
tomorrow = (today + timedelta(days=1)).isoformat()
a.save_visit({"patient_id": pid, "doctor_id": doc, "start": f"{tomorrow} 07:00:00", "end": f"{tomorrow} 07:30:00", "title": "Осмотр"})
a.save_visit({"patient_id": some[0]["id"], "doctor_id": doc, "start": f"{tomorrow} 07:30:00", "end": f"{tomorrow} 08:00:00",
              "status": "Отменён"})
r = a.call_list("remind", {"day": tomorrow})
check("remind list has the visit", any(x["patient_id"] == pid and "07:00" in x["info"] for x in r["rows"]), r["rows"][:2])
check("remind skips cancelled", all(not (x["patient_id"] == some[0]["id"] and x["start"].endswith("07:30:00")) for x in r["rows"]))
refuses("call needs a result", lambda: a.log_call({"patient_id": pid, "result": "??"}), "результат")
check("log call", a.log_call({"patient_id": pid, "list": "remind", "result": "Дозвонились", "comment": "подтвердила"}))
r = a.call_list("remind", {"day": tomorrow})
x = next(x for x in r["rows"] if x["patient_id"] == pid)
check("last call shown", x["last_call"]["result"] == "Дозвонились" and x["last_call"]["comment"] == "подтвердила", x)
check("done counter", r["done"] >= 1)

# --- lapsed patients: an old visit and nothing planned
old = (today - timedelta(days=300)).isoformat()
lost = a.create_patient({"lname": "Давний", "fname": "Пациент", "phone": "+7 900 000-00-01"})["id"]
a.save_visit({"patient_id": lost, "doctor_id": doc, "start": f"{old} 10:00:00", "end": f"{old} 10:30:00", "status": "Завершён"})
check("lapsed after 6 months", any(x["patient_id"] == lost for x in a.call_list("lost", {"months": 6})["rows"]))
check("not lapsed after 12 months", not any(x["patient_id"] == lost for x in a.call_list("lost", {"months": 12})["rows"]))
a.save_visit({"patient_id": lost, "doctor_id": doc, "start": f"{tomorrow} 12:00:00", "end": f"{tomorrow} 12:30:00"})
check("booked patient leaves the list", not any(x["patient_id"] == lost for x in a.call_list("lost", {"months": 6})["rows"]))

# --- unstarted plans
pl = a.create_patient({"lname": "План", "fname": "Тест"})["id"]
plan = a.save_invoice({"patient_id": pl, "kind": "plan", "title": "Имплантация", "items": [{"title": "Имплант", "price": 50000}]})
d.conn.execute("UPDATE invoices SET created_at=? WHERE id=?", ((today - timedelta(days=20)).isoformat() + " 10:00", plan)); d.conn.commit()
r = a.call_list("plans")
check("unstarted plan listed", any(x["patient_id"] == pl and "Имплантация" in x["info"] for x in r["rows"]), r["rows"][:1])
a.save_invoice({"patient_id": pl, "items": [{"title": "Имплант", "price": 50000}]})
check("billed plan leaves the list", not any(x["patient_id"] == pl for x in a.call_list("plans")["rows"]))

# --- birthdays
b = a.call_list("birthdays", {"days": 7})
me = next((x for x in b["rows"] if x["patient_id"] == pid), None)
check("birthday in 2 days", me and me["in_days"] == 2 and me["age"] == 30, me)
check("birthdays sorted", [x["in_days"] for x in b["rows"]] == sorted(x["in_days"] for x in b["rows"]))
check("not in 1 day window", not any(x["patient_id"] == pid for x in a.call_list("birthdays", {"days": 1})["rows"]))

# --- debts list and «do not call»
debtor = d.q("SELECT id FROM patients WHERE local=0 LIMIT 1 OFFSET 5")[0]["id"]
a.save_invoice({"patient_id": debtor, "items": [{"title": "Коронка", "price": 20000}]})
check("debtor in call list", any(x["patient_id"] == debtor for x in a.call_list("debts")["rows"]))
a.log_call({"patient_id": debtor, "list": "debts", "result": "Отказ", "no_calls": True})
check("do not call: hidden from lists", not any(x["patient_id"] == debtor for x in a.call_list("debts")["rows"]))
check("do not call: in card", a.patient(debtor)["marketing"]["no_calls"] is True)
refuses("unknown list", lambda: a.call_list("spam"), "Неизвестный")
s = a.mk_summary()
check("summary", s["calls_today"] == 2 and "sources" in s, s)

# --- demo sources and wipe
demo.ensure_office(d)
check("demo sources", d.one("SELECT COUNT(*) AS n FROM patient_marketing")["n"] > 50)
d.wipe()
check("wipe drops sources of removed patients", d.one("SELECT COUNT(*) AS n FROM patient_marketing")["n"] == 0)
demo.ensure_demo(d, force=True)

# --- rights over HTTP
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
for login, role in (("adm", "admin"), ("doc", "doctor")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TA = call("auth", "login", "adm", "secret1")[1]["token"]
TDoc = call("auth", "login", "doc", "secret1")[1]["token"]
p0 = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]
check("admin sees call lists", call("api", "call_list", "remind", {}, token=TA)[0] == 200)
check("admin logs a call", call("api", "log_call", {"patient_id": p0, "result": "Перезвонить"}, token=TA)[0] == 200)
check("doctor no call lists", call("api", "call_list", "remind", {}, token=TDoc)[0] == 403)
check("doctor reads source list", call("api", "mk_sources", token=TDoc)[0] == 200)
check("doctor sets source (patients_edit)", call("api", "set_patient_marketing", p0, {"source": "Сайт"}, token=TDoc)[0] == 200)
calls = a.patient(p0)["marketing"]["calls"]
check("call signed by employee", calls and calls[0]["user_name"] == "adm", calls)
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
