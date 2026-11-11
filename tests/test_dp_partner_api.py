"""3.7: the integration with Dentist Plus against a fake server that behaves as the partner documentation says
(https://api-balancer.dentist-plus.com/partner/docs/ — partner-doc.json): auth with expires_at, meta/data pages
with per_page <= 200, visit status codes and is_cancelled (with_deleted=1), /payments, /schedule (100 rows max),
/record_statuses, /chairs; writes with their required fields: POST /patients (branch_id, fname), PUT /patients/{id},
POST /visits and PUT /visits/{id} (branch_id, patient_id, doctor_id, start, end), POST /visits/{id}/cancel,
a medical record into the fields of its visit. No real Dentist Plus is called."""
from pathlib import Path
APP = str(Path(__file__).resolve().parents[1] / 'app')
import json, os, sys, threading, tempfile
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, APP)

T = date.today()
today = T.isoformat()
LOG = []          # (method, path, query or body)
STATE = {"auth": 0, "exp_s": 3600, "fail429": 0, "chairs": 2}
REQ_VISIT = ("branch_id", "patient_id", "doctor_id", "start", "end")
STATUSES = [{"id": 1, "title": "Не подтверждена"}, {"id": 2, "title": "Подтверждена"}, {"id": 3, "title": "Пришел"}]
CHAIRS = [{"id": 4, "title": "Кресло №1", "is_active": True}, {"id": 5, "title": "Кресло №2", "is_active": True}]
PATIENTS = {5: {"id": 5, "fname": "Олег", "lname": "Старый", "phone": "+79990000000", "date_of_birth": "1980-01-02",
                "gender": "male", "tags": [{"id": 9, "title": "VIP"}], "doctor": {"id": 7}}}


def visit(i, start, mins=30, **kw):
    s = datetime.strptime(start, "%Y-%m-%d %H:%M")
    v = {"id": i, "start": s.strftime("%Y-%m-%d %H:%M:%S"), "end": (s + timedelta(minutes=mins)).strftime("%Y-%m-%d %H:%M:%S"),
         "doctor": {"id": 7, "fname": "Иван", "lname": "Врачев"}, "patient": {"id": 5, "fname": "Олег", "lname": "Старый"},
         "chair": {"id": 4, "title": "Кресло №1"}, "branch_id": 1, "status": "confirmed", "is_cancelled": False,
         "description": "Осмотр", "teeth": [{"id": 1, "title": "16", "services": [{"id": 31, "final_price": 900, "price_original": 1000}],
                                            "diagnoses": [{"id": 2}]}]}
    v.update(kw)
    return v


VISITS = {100: visit(100, f"{today} 10:00"),
          101: visit(101, f"{today} 11:00", status="came"),
          102: visit(102, f"{today} 12:00", status="did_not_come"),
          103: visit(103, f"{today} 13:00", is_cancelled=True, cancel_reason="заболел"),
          104: visit(104, f"{today} 14:00", status="in_chair"),
          105: visit(105, f"{today} 16:00", description="")}
NEXT = {"v": 200, "p": 800}
CARD_FAIL = {}    # 3.7.1: patient id -> (HTTP code, how many times; -1 = always)


def page(items, q):
    pp = int(q.get("per_page", 20))
    assert pp <= 200, "per_page above the documented maximum"
    n = int(q.get("page", 1))
    chunk = items[(n - 1) * pp: n * pp]
    return {"meta": {"current_page": n, "last_page": max(1, -(-len(items) // pp)), "per_page": pp, "total": len(items)}, "data": chunk}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, obj=None, headers=None):
        b = json.dumps(obj, ensure_ascii=False).encode() if obj is not None else b""
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_HEAD(self):
        self.send_response(200); self.end_headers()

    def ok(self):
        return self.headers.get("Authorization") == f"Bearer T{STATE['auth']}"

    def path_(self):
        return urlparse(self.path).path.replace("/partner/", "")

    def do_POST(self):
        p, b = self.path_(), self.body()
        if p == "auth":
            if b != {"login": "u", "pass": "p"}:
                return self.send(401, {"error": "Неверные логин / пароль"})
            STATE["auth"] += 1
            exp = (datetime.now(timezone.utc) + timedelta(seconds=STATE["exp_s"])).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            return self.send(200, {"token": f"T{STATE['auth']}", "expires_at": exp})
        if not self.ok():
            return self.send(401, {"error": "Unauthenticated"})
        if STATE["fail429"]:
            STATE["fail429"] -= 1
            return self.send(429, {"error": "Too Many Attempts."}, {"Retry-After": "0"})
        LOG.append(("POST", p, b))
        if p == "patients":
            if not b.get("branch_id") or not b.get("fname"):
                return self.send(422, {"message": "The given data was invalid.", "errors": {"branch_id": ["required"]}})
            NEXT["p"] += 1
            PATIENTS[NEXT["p"]] = {"id": NEXT["p"], **b}
            return self.send(200, PATIENTS[NEXT["p"]])
        if p == "visits":
            miss = [k for k in REQ_VISIT if not b.get(k)]
            if miss:
                return self.send(422, {"message": "The given data was invalid.", "errors": {miss[0]: ["required"]}})
            NEXT["v"] += 1
            v = visit(NEXT["v"], b["start"][:16], description=b.get("description", ""), teeth=[])
            v.update(patient={"id": b["patient_id"]}, doctor={"id": b["doctor_id"]}, branch_id=b["branch_id"])
            VISITS[NEXT["v"]] = v
            return self.send(200, v)
        if p.startswith("visits/") and p.endswith("/cancel"):
            vid = int(p.split("/")[1])
            VISITS[vid]["is_cancelled"] = True
            VISITS[vid]["cancel_reason"] = b.get("reason")
            return self.send(200, True)
        self.send(404, {"error": "Запись не найдена"})

    def do_PUT(self):
        p, b = self.path_(), self.body()
        if not self.ok():
            return self.send(401, {"error": "Unauthenticated"})
        LOG.append(("PUT", p, b))
        kind, rid = p.split("/")[0], int(p.split("/")[1])
        if kind == "visits":
            miss = [k for k in REQ_VISIT if not b.get(k)]
            if miss or rid not in VISITS:
                return self.send(422 if miss else 404, {"error": f"{miss[0]} required" if miss else "Запись не найдена"})
            v = VISITS[rid]
            for k in ("start", "end", "description", "complaints", "objectively", "disease_history", "description_doctor"):
                if k in b:
                    v[k] = b[k]
            v["doctor"] = {"id": b["doctor_id"]}
            if "status_id" in b:
                v["status"] = {1: "not_confirmed", 2: "confirmed", 3: "came"}[b["status_id"]]
            return self.send(200, v)
        if kind == "patients":
            if not b.get("branch_id") or not b.get("fname"):
                return self.send(422, {"error": "branch_id, fname required"})
            PATIENTS[rid].update({k: v for k, v in b.items() if k != "branch_id"})
            return self.send(200, PATIENTS[rid])
        self.send(404, {"error": "Запись не найдена"})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self.ok():
            return self.send(401, {"error": "Unauthenticated"})
        p = self.path_()
        LOG.append(("GET", p, q))
        if "per_page" in q and int(q["per_page"]) > 200:
            return self.send(422, {"error": "per_page max 200"})
        if p == "branches": return self.send(200, page([{"id": 1, "title": "Филиал №1"}], q))
        if p == "doctors": return self.send(200, page([{"id": 7, "fname": "Иван", "lname": "Врачев", "branches": [{"id": 1}]},
                                                       {"id": 8, "fname": "Пётр", "lname": "Второй", "branches": [{"id": 1}]}], q))
        if p == "services": return self.send(200, page([{"id": 31, "title": "Пломба", "code": "A-1", "price": 1000, "price_id": 1,
                                                         "category": {"id": 1, "title": "Терапия"}}], q))
        if p == "chairs": return self.send(200, page(CHAIRS, q))
        if p == "record_statuses": return self.send(200, STATUSES)
        if p == "diagnoses": return self.send(200, page([{"id": i, "title": f"Д{i}", "code": f"K{i}"} for i in range(500)], q))
        if p == "visits":
            vs = [v for v in VISITS.values() if q["date_from"] <= v["start"][:10] <= q["date_to"]
                  and (q.get("with_deleted") == "1" or not v["is_cancelled"])]
            return self.send(200, page(sorted(vs, key=lambda v: v["id"]), q))
        if p.startswith("visits/"):
            vid = int(p.split("/")[1])
            return self.send(200, VISITS[vid]) if vid in VISITS else self.send(404, {"error": "Запись не найдена"})
        if p.startswith("patients/"):
            pid = int(p.split("/")[1])
            fail = CARD_FAIL.get(pid)
            if fail and fail[1] != 0:
                CARD_FAIL[pid] = (fail[0], fail[1] - 1)
                return self.send(fail[0], {"error": "Too Many Attempts." if fail[0] == 429 else "Server Error"}, {"Retry-After": "0"})
            return self.send(200, PATIENTS[pid]) if pid in PATIENTS else self.send(404, {"error": "Запись не найдена"})
        if p == "patients": return self.send(200, page(list(PATIENTS.values()), q))
        if p == "payments":
            return self.send(200, page([{"id": 1, "sum": 12000, "date": f"{today} 12:05:00", "client_id": 5, "visit_id": 101, "payment_type": "cash"},
                                        {"id": 2, "sum": 3000.5, "date": f"{today} 13:00:00", "client_id": 5, "visit_id": 104, "payment_type": "card"}], q))
        if p == "schedule":
            a, b = date.fromisoformat(q["date_from"]), date.fromisoformat(q["date_to"])
            rows = []
            d = a
            while d <= b and STATE.get("two_shifts"):   # 3.7.1: two shifts a day without a chair, one row without time
                rows += [{"doctor_id": int(q["doctor_id"]), "chair_id": None, "branch_id": 1, "day": d.isoformat(),
                          "time_from": f, "time_to": t} for f, t in (("09:00:00", "13:00:00"), ("15:00:00", "19:00:00"))]
                rows.append({"doctor_id": int(q["doctor_id"]), "chair_id": None, "branch_id": 1, "day": d.isoformat(),
                             "time_from": None, "time_to": None})
                d += timedelta(days=1)
            while d <= b:
                for chair in (4, 5, 6, 7)[:STATE["chairs"]]:   # 2 chairs: a 31-day window gives 62 rows; 4 chairs: 124, capped
                    rows.append({"doctor_id": int(q["doctor_id"]), "chair_id": chair, "branch_id": 1, "day": d.isoformat(),
                                 "time_from": "09:00:00" if chair == 4 else "14:00:00", "time_to": "14:00:00" if chair == 4 else "19:30:00",
                                 "minutes": 300})
                d += timedelta(days=1)
            return self.send(200, rows[:100])
        self.send(404, {"error": "Запись не найдена"})


srv = ThreadingHTTPServer(("127.0.0.1", 8811), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

import config, db as dbm, reports, dp_transfer
from api_client import DentistPlusClient
from sync import SyncWorker
from local import Local
from shifts import Shifts

BASE = "http://127.0.0.1:8811/partner"
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


# ---- 1. client: token expiry and per_page cap
c = DentistPlusClient(BASE, "u", "p")
STATE["exp_s"] = 30        # expires in 30 s: closer than the margin, renewed before the next call
c.auth(); n0 = STATE["auth"]
c.request("branches", {"per_page": 500})
check("token close to expires_at is renewed before a call", STATE["auth"] == n0 + 1)
check("per_page capped at 200", LOG[-1][2]["per_page"] == "200", LOG[-1])
STATE["exp_s"] = 3600
c.auth(); n0 = STATE["auth"]
c.request("branches"); c.request("doctors")
check("a fresh token is reused", STATE["auth"] == n0)
try:
    DentistPlusClient(BASE, "u", "bad").auth()
    check("wrong password raises", False)
except Exception as e:  # noqa: BLE001
    check("wrong password -> the server's error text", "Неверные" in str(e), str(e))

# ---- 2. sync: statuses, cancelled visits, no ICD dictionary per patient, payments, schedule
# settings of an older version: the «Диагнозы» extra (it asked /diagnoses for every patient) and per_page 500
config.save_settings({"demo": False, "base_url": BASE, "login": "u", "pass_enc": config.protect("p"), "transfer_mode": "manual",
                      "per_page": 500, "patient_extras": [{"key": "diagnoses", "title": "Диагнозы", "path": "diagnoses",
                                                           "params": {"patient_id": "{id}"}}]})
check("old «Диагнозы» extra dropped from settings", config.load_settings()["patient_extras"] == [])
d = dbm.DB(); w = SyncWorker(d); L = Local(d)
LOG.clear()
check("first sync ok", w.sync_once(), d.meta_get("last_error"))
st = {r["id"]: r["status"] for r in d.q("SELECT id, status FROM visits")}
check("status codes translated", (st.get("100"), st.get("101"), st.get("102"), st.get("104")) ==
      ("Подтверждён", "Пришёл", "Не пришёл", "В кресле"), st)
check("cancelled visit kept as «Отменён» (with_deleted=1)", st.get("103") == "Отменён", st)
check("reports count them right", [reports.status_kind(st[k]) for k in ("101", "102", "103", "104")] == ["came", "noshow", "cancel", "came"])
check("no /diagnoses requests", not [x for x in LOG if x[1] == "diagnoses"])
check("visits asked with with_deleted=1", all(x[2].get("with_deleted") == "1" for x in LOG if x[1] == "visits"))
check("no page asked above 200", all(int(x[2].get("per_page", 20)) <= 200 for x in LOG if x[0] == "GET"))
check("patient birth date from date_of_birth", d.one("SELECT birth FROM patients WHERE id='5'")["birth"] == "1980-01-02")
check("dictionaries kept", json.loads(d.meta_get("dp_record_statuses"))[1]["title"] == "Подтверждена" and len(json.loads(d.meta_get("dp_chairs"))) == 2)
check("DP payments mirrored", d.one("SELECT COUNT(*) n, SUM(sum) s FROM dp_payments")["s"] == 15000.5)
rec = dp_transfer.reconcile(d, today, today)
prow = next(r for r in rec["rows"] if r["key"] == "payments")
check("«Сверка» shows DP payments", prow.get("dp_ok") and prow["dp_count"] == 2 and prow["dp_sum"] == 15000.5, prow)
sch = d.q("SELECT * FROM dp_schedule WHERE doctor_id='7' AND day=?", (today,))
check("schedule synced (both chairs)", len(sch) == 2, sch)
far = (T + timedelta(days=int(config.load_settings()["days_forward"]))).isoformat()
check("schedule window not cut by the 100-row cap", d.one("SELECT COUNT(*) n FROM dp_schedule WHERE doctor_id='7' AND day=?", (far,))["n"] == 2)
sh = Shifts(d)
check("calendar uses the DP schedule", sh.day(today).get("7") == {"start": "09:00", "end": "19:30", "source": "dp"}, sh.day(today))
d.q("SELECT 1")
with d.tx() as cx:
    cx.execute("INSERT INTO work_shifts(person, date, start, \"end\") VALUES('d:7', ?, '10:00', '15:00')", (today,))
check("a shift set here wins", sh.day(today)["7"] == {"start": "10:00", "end": "15:00"}, sh.day(today))
n_sched = len([x for x in LOG if x[1] == "schedule"])
STATE["chairs"] = 4
w._pull_schedule(c, T, T + timedelta(days=30))
check("a capped /schedule answer is asked again in halves", d.one("SELECT COUNT(*) n FROM dp_schedule WHERE doctor_id='7' AND day >= ?",
                                                                (today,))["n"] == 31 * 4)
STATE["chairs"] = 2
w._pull_schedule(c, T - timedelta(days=7), T + timedelta(days=int(config.load_settings()["days_forward"])))
LOG.clear(); w.sync_once()
check("schedule and dictionaries not asked again within the hour",
      not [x for x in LOG if x[1] in ("schedule", "chairs", "record_statuses")], n_sched)

# ---- 3. automatic transfer
np = L.create_patient({"lname": "Новикова", "fname": "Анна", "phone": "+7 900 111-22-33", "birth_date": "1990-05-06",
                       "gender": "Ж", "comment": "аллергия на лидокаин"})
L.save_visit({"patient_id": np["id"], "doctor_id": "7", "start": f"{today} 17:00", "end": f"{today} 17:30",
              "title": "Консультация", "comment": "первичная", "status": "Подтверждён", "chair": "Кресло №2"})
L.save_visit({"id": "100", "patient_id": "5", "doctor_id": "8", "branch_id": "1", "start": f"{today} 18:00", "end": f"{today} 18:30",
              "title": "Осмотр", "action": "move"})
L.set_visit_status("101", "Подтверждён")
L.set_visit_status("104", "Отменён")
gone = L.save_visit({"patient_id": "5", "doctor_id": "7", "start": f"{today} 19:00", "end": f"{today} 19:30"})
L.set_visit_status(gone, "Отменён")
L.edit_patient("5", {"phone": "+79991112233", "lname": "Старый", "birth_date": "1980-01-02", "gender": "М"})
rid = L.save_record({"patient_id": "5", "visit_id": "105", "doctor_id": "7", "date": today, "complaints": "Боль при накусывании",
                     "objective": "Кариес 16", "treatment": "Пломба", "recommendations": "Не есть 2 часа"})
L.save_record({"patient_id": "5", "doctor_id": "7", "date": today, "complaints": "без визита"})   # not linked: stays manual
config.save_settings({"transfer_mode": "auto"})
STATE["fail429"] = 1   # the first write gets 429: repeated, not lost
LOG.clear(); w.sync_once()
writes = [x for x in LOG if x[0] != "GET"]
pb = next(b for m, p, b in writes if (m, p) == ("POST", "patients"))
check("POST /patients: branch_id, fname, date_of_birth, gender, description",
      pb.get("branch_id") == 1 and pb.get("fname") == "Анна" and pb.get("date_of_birth") == "1990-05-06"
      and pb.get("gender") == "female" and pb.get("description") == "аллергия на лидокаин" and "birth_date" not in pb, pb)
vb = next(b for m, p, b in writes if (m, p) == ("POST", "visits"))
check("POST /visits: required fields, status_id, chair_id, description",
      all(vb.get(k) for k in REQ_VISIT) and vb["patient_id"] == 801 and vb["start"] == f"{today} 17:00:00"
      and vb.get("status_id") == 2 and vb.get("chair_id") == 5 and vb.get("description") == "Консультация\nпервичная", vb)
mv = next(b for m, p, b in writes if (m, p) == ("PUT", "visits/100"))
check("move: PUT with all required fields", all(mv.get(k) for k in REQ_VISIT) and mv["doctor_id"] == 8
      and mv["start"] == f"{today} 18:00:00" and mv["patient_id"] == 5, mv)
check("move: teeth not sent, services kept", "teeth" not in mv and len(VISITS[100]["teeth"][0]["services"]) == 1)
sv = next(b for m, p, b in writes if (m, p) == ("PUT", "visits/101"))
check("status: PUT keeps time and doctor, sets status_id", sv["status_id"] == 2 and sv["start"] == VISITS[101]["start"]
      and sv["doctor_id"] == 7, sv)
cv = next(((m, b) for m, p, b in writes if p == "visits/104/cancel"), None)
check("cancel: POST /visits/{id}/cancel with a reason", cv and cv[0] == "POST" and cv[1].get("reason") and VISITS[104]["is_cancelled"], cv)
check("a visit cancelled before sending is not created", len([1 for m, p, b in writes if (m, p) == ("POST", "visits")]) == 1)
pe = next(b for m, p, b in writes if (m, p) == ("PUT", "patients/5"))
check("patient edit: PUT /patients/5 with the card kept and the change on top",
      pe.get("phone") == "+79991112233" and pe.get("fname") == "Олег" and pe.get("branch_id") == 1 and pe.get("tags") == [9]
      and pe.get("doctor_id") == 7 and pe.get("gender") == "male", pe)
rv = next(b for m, p, b in writes if (m, p) == ("PUT", "visits/105"))
check("record -> PUT /visits/105: complaints, objectively, the rest in description_doctor",
      rv.get("complaints") == "Боль при накусывании" and rv.get("objectively") == "Кариес 16"
      and "Лечение:\nПломба" in rv.get("description_doctor", "") and "Рекомендации:" in rv.get("description_doctor", "")
      and all(rv.get(k) for k in REQ_VISIT), rv)
j = {(x["kind"], x["id"]): x for x in L.journal(show_done=True)}
recs = [x for x in j.values() if x["kind"] == "record"]
check("record marked transferred by the auto transfer", d.one("SELECT transferred, transferred_by FROM records WHERE id=?", (rid,)) ==
      {"transferred": 1, "transferred_by": "Автоперенос"})
check("unlinked record stays manual", any(x["push_status"] == "manual" and not x["transferred"] for x in recs), recs)
bad = [(x["what"], x["push_status"], x["push_error"]) for x in j.values() if x.get("auto") and x["push_status"] not in ("sent", "manual")]
check("nothing failed", not bad, bad)

# the record changed again: our old text in Dentist Plus is replaced, not doubled; a doctor's own text stays
VISITS[105]["complaints"] = "Боль при накусывании\n\nврач: со слов пациента"
L.save_record({"id": rid, "patient_id": "5", "visit_id": "105", "doctor_id": "7", "date": today, "complaints": "Боль ночью",
               "objective": "Кариес 16", "treatment": "Пломба", "recommendations": "Не есть 2 часа"})
LOG.clear(); w.sync_once()
rv2 = next(b for m, p, b in LOG if (m, p) == ("PUT", "visits/105"))
check("record edited: old text replaced, doctor's text kept", rv2["complaints"] == "Боль ночью\n\nврач: со слов пациента"
      and "objectively" in rv2, rv2)

# the card shows the edit even after the next sync brought the old card from Dentist Plus
PATIENTS[5]["phone"] = "+79990000000"
L.edit_patient("5", {"address": "ул. Новая, 1"})
config.save_settings({"transfer_mode": "manual"})
w.sync_once()
check("pending edit stays on the card after a sync", "Новая" in (d.one("SELECT detail FROM patients WHERE id='5'")["detail"] or ""))
check("pending edit listed in «Перенос»", any(x["kind"] == "patient_edit" and not x["transferred"] for x in L.journal()))

# manual mode: nothing is written to Dentist Plus
LOG.clear(); w.sync_once()
check("manual mode writes nothing", not [x for x in LOG if x[0] != "GET"])

# ---- 4. 3.7.1: patient cards that did not load — the reason is kept, 429/5xx are asked again, not lost
import logging  # noqa: E402
import sync as syncmod  # noqa: E402
syncmod.CARD_PAUSE_S = 0
LOGGED = []


class _Cap(logging.Handler):
    def emit(self, rec): LOGGED.append(rec.getMessage())


logging.getLogger("sync").addHandler(_Cap())
for pid in (60, 61, 62):
    PATIENTS[pid] = {"id": pid, "fname": f"П{pid}", "lname": "Карточкин", "date_of_birth": "1990-01-01"}
for i, pid in enumerate((60, 61, 62, 63)):
    VISITS[300 + i] = visit(300 + i, f"{today} 0{8 + i // 2}:{(i % 2) * 30:02d}", patient={"id": pid, "fname": "Т", "lname": "Т"})
CARD_FAIL.update({61: (429, -1), 62: (500, 3)})   # 61: always «too many requests»; 62: the server fails 3 times
w.sync_once()
last = json.loads(d.one("SELECT counts FROM sync_log ORDER BY id DESC LIMIT 1")["counts"])
check("card errors counted with their reasons", last.get("patient_errors") == 2
      and last.get("patient_error_reasons") == {"HTTP 404": 1, "HTTP 429": 1}, last)
check("a 5xx card is asked again one by one and loaded", d.one("SELECT detail FROM patients WHERE id='62'")["detail"]
      and last.get("patient_retried_slowly", 0) >= 1, last)
check("cards without errors loaded", d.one("SELECT detail FROM patients WHERE id='60'")["detail"] is not None)
check("the 429 card waits for the next sync, the 404 one does not", json.loads(d.meta_get("patients_retry")) == ["61"]
      and last.get("patient_retry_next_sync") == 1, d.meta_get("patients_retry"))
check("the reason is in the log", any("HTTP 429" in m and "HTTP 404" in m for m in LOGGED), LOGGED)
CARD_FAIL.clear()
del VISITS[301]          # patient 61 is no longer among the visits: asked only because the last sync failed it
w.sync_once()
last = json.loads(d.one("SELECT counts FROM sync_log ORDER BY id DESC LIMIT 1")["counts"])
check("the failed card is loaded by the next sync", d.one("SELECT detail FROM patients WHERE id='61'")["detail"]
      and last.get("patient_retry_from_last_sync") == 1 and json.loads(d.meta_get("patients_retry")) == [], last)

# ---- 5. 3.7.1: two shifts of a doctor a day without a chair — both kept; rows without time are counted
STATE["two_shifts"] = True
tm = T + timedelta(days=1)
n = w._pull_schedule(c, tm, tm + timedelta(days=2))
STATE["two_shifts"] = False
rows = d.q("SELECT time_from, time_to FROM dp_schedule WHERE doctor_id='7' AND day=? ORDER BY time_from", (tm.isoformat(),))
check("second shift of the day does not replace the first", rows == [{"time_from": "09:00", "time_to": "13:00"},
                                                                     {"time_from": "15:00", "time_to": "19:00"}], rows)
check("received = saved + skipped", n == {"received": 2 * 3 * 3, "saved": 2 * 2 * 3, "skipped": 2 * 3}, n)
check("calendar spans both shifts", Shifts(d).day(tm.isoformat()).get("7") == {"start": "09:00", "end": "19:00", "source": "dp"})

# the table of 3.7.0 (key without time_from) is migrated with its rows
import sqlite3  # noqa: E402
old_path = os.path.join(tempfile.mkdtemp(), "old.db")
cx = sqlite3.connect(old_path)
cx.executescript("""CREATE TABLE dp_schedule(doctor_id TEXT, day TEXT, chair_id TEXT, branch_id TEXT, time_from TEXT, time_to TEXT,
                    synced_at TEXT, PRIMARY KEY(doctor_id, day, chair_id));
                    INSERT INTO dp_schedule VALUES('7','2026-11-12','','1','09:00','13:00','x');""")
cx.commit(); cx.close()
d2 = dbm.DB(old_path)
pk = [r[1] for r in d2.conn.execute("PRAGMA table_info(dp_schedule)") if r[5]]
d2.conn.execute("INSERT INTO dp_schedule VALUES('7','2026-11-12','','1','15:00','19:00','x')")
check("old dp_schedule migrated: key with time_from, rows kept", "time_from" in pk
      and d2.one("SELECT COUNT(*) n FROM dp_schedule")["n"] == 2, pk)
d2.conn.close()

# ---- 6. 3.7.1: the developer's report shows what the sync stored, without personal data
import devreport  # noqa: E402
w.sync_once()
rep = devreport.build(d, w.status(), config.load_settings(), probe_api=False)
data = rep["data"]
dump = json.dumps(rep, ensure_ascii=False)
check("report: services, payments, schedule, dictionaries", data["services"].get("api") == 1 and data["dp_payments"]["count"] == 2
      and data["dp_schedule"]["count"] > 0 and data["dp_chairs"]["count"] == 2
      and data["dp_record_statuses"]["titles"] == ["Не подтверждена", "Подтверждена", "Пришел"], data)
check("report: patient edits and the last sync", isinstance(data["patient_edits"], dict) and data["last_sync"]["ok"]
      and "visits" in data["last_sync"]["counts"], data["last_sync"])
check("report: no patient names or phones", not any(x in dump for x in ("Олег", "Старый", "Карточкин", "+7999", "Новикова")))
d.conn.execute("INSERT INTO sync_log(started,finished,ok,message,counts) VALUES('a','b',0,'Ошибка API: HTTP 500',"
               "'{\"payments_error\": \"Ошибка у Иванова Мария Петровна\", \"patient_error_reasons\": {\"HTTP 429\": 3}}')")
d.conn.commit()
data = devreport.data_summary(d)
check("report: a failed last sync with its section errors, scrubbed, and the last good one",
      not data["last_sync"]["ok"] and "payments_error" in data["last_sync"]["counts"]
      and "Иванова" not in json.dumps(data, ensure_ascii=False) and data["last_sync_ok"]["ok"], data["last_sync"])

srv.shutdown()
print("FAILED:", fails) if fails else print("ALL OK")
sys.exit(1 if fails else 0)
