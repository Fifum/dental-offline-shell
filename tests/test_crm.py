"""CRM (2.11.0): tasks by hand and by rules (after a service, an unfinished plan, a bad score), requests and their
funnel, segments, after-visit scores (NPS) with review links and the tablet, payback of advertising, rights."""
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
import crm as crmm  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import replica  # noqa: E402
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
C = a._crm
T = date.today()
doc = d.doctors()[0]["id"]


def day(n):
    return (T + timedelta(days=n)).isoformat()


def patient(last, phone="", **kw):
    return a.create_patient({"lname": last, "fname": "Тест", "phone": phone, **kw})["id"]


def invoice(pid, title, n, price=3000):
    iid = a.save_invoice({"patient_id": pid, "doctor_id": doc, "items": [{"title": title, "price": price}]})
    d.conn.execute("UPDATE invoices SET created_at=? WHERE id=?", (day(n) + " 10:00:00", iid)); d.conn.commit()
    return iid


def visit(pid, n, status="Запланирован", title="Осмотр", h=10):
    return a.save_visit({"patient_id": pid, "doctor_id": doc, "start": f"{day(n)} {h:02d}:00:00", "end": f"{day(n)} {h:02d}:30:00",
                         "status": status, "title": title})


def open_tasks(pid):
    return d.q("SELECT * FROM crm_tasks WHERE patient_id=? AND status='open'", (pid,))


# --- settings
s = a.crm_settings()
check("default rules", {r["id"] for r in s["rules"]} >= {"r_extract", "r_hygiene", "r_implant"} and s["plan_on"], s["rules"])
check("default texts", "{имя}" in s["nps_text"] and "{ссылка}" in s["review_text"])
refuses("rule without words", lambda: a.crm_settings_save({"rules": [{"title": "Позвонить", "match": "", "days": 1}]}), "услуга")
refuses("rule days", lambda: a.crm_settings_save({"rules": [{"title": "Позвонить", "match": "x", "days": 5000}]}), "1100")
refuses("link must be http", lambda: a.crm_settings_save({"links": {"yandex": "yandex.ru/maps"}}), "https://")
refuses("bad below good", lambda: a.crm_settings_save({"bad_score": 9, "good_score": 8}), "ниже")
s = a.crm_settings_save({"links": {"yandex": "https://yandex.ru/maps/org/123", "gis": "https://2gis.ru/firm/456"}})
check("links saved, QR made", len(s["review_links"]) == 2 and s["review_links"][0]["qr"].startswith("data:image/png;base64,"), s["review_links"][:1])
check("settings synced table", d.one("SELECT COUNT(*) AS n FROM crm_settings")["n"] >= 1)

# --- automatic tasks after a service
p1 = patient("Удалёнов", "+7 900 100-00-01")
invoice(p1, "Удаление зуба простое", -1)
C._gen_at = 0
added = C.auto(force=True)
t1 = open_tasks(p1)
check("task after extraction", len(t1) == 1 and "удаления" in t1[0]["title"] and t1[0]["due"] == T.isoformat(), t1)
check("deterministic id (two laptops make the same row)", t1 and t1[0]["id"] == crmm._auto_id("r_extract", p1, day(-1)), t1)
C.auto(force=True)
check("no duplicate on the next pass", len(open_tasks(p1)) == 1)
p2 = patient("Давнишний")
invoice(p2, "Удаление зуба", -20)
C.auto(force=True)
check("old short-rule service makes no task", not open_tasks(p2))
p3 = patient("Гигиенова", "+7 900 100-00-03")
invoice(p3, "Профессиональная гигиена полости рта", -181)
C.auto(force=True)
check("hygiene recall after half a year", any("профгигиену" in t["title"] for t in open_tasks(p3)), open_tasks(p3))
check("a task made today is not overdue at once", all(t["due"] == T.isoformat() for t in open_tasks(p3)), open_tasks(p3))
visit(p3, 5)
C.auto(force=True)
check("booked patient: recall closed by itself", not open_tasks(p3) and d.one("SELECT result FROM crm_tasks WHERE patient_id=?", (p3,))["result"] == "Записался")
p4 = patient("Незвонящий")
invoice(p4, "Удаление зуба", -1)
a.set_patient_marketing(p4, {"no_calls": True})
C.auto(force=True)
check("«do not call» patient: no task", not open_tasks(p4))
p5 = patient("Скрытый")
invoice(p5, "Удаление зуба", -1)
C.auto(force=True)
tid5 = open_tasks(p5)[0]["id"]
a.crm_task_delete(tid5)
C.auto(force=True)
check("hidden auto task stays hidden", not open_tasks(p5) and d.one("SELECT status FROM crm_tasks WHERE id=?", (tid5,))["status"] == "dismissed")
# a rule switched off makes nothing; an own rule works
rules = a.crm_settings()["rules"]
for r in rules:
    r["on"] = r["id"] != "r_extract"
rules.append({"title": "Пригласить на коррекцию брекетов", "match": "брекет", "days": 30, "on": True})
a.crm_settings_save({"rules": rules})
p6 = patient("Брекетов")
invoice(p6, "Установка брекет-системы", -31)
p7 = patient("Выключенный")
invoice(p7, "Удаление зуба", -1)
C.auto(force=True)
check("own rule", any("брекетов" in t["title"] for t in open_tasks(p6)), open_tasks(p6))
check("rule off", not open_tasks(p7))
rules[0]["on"] = True
a.crm_settings_save({"rules": rules})

# --- unfinished plan (6.5)
p8 = patient("Планов", "+7 900 100-00-08")
plan = a.save_invoice({"patient_id": p8, "doctor_id": doc, "kind": "plan", "title": "Имплантация",
                       "items": [{"title": "Имплант", "price": 40000}, {"title": "Коронка", "price": 30000}]})
inv8 = a.plan_to_invoice(plan, [0])
for tbl, col, iid in (("invoices", "created_at", plan), ("invoices", "created_at", inv8)):
    d.conn.execute(f"UPDATE {tbl} SET {col}=? WHERE id=?", (day(-45) + " 10:00:00", iid))
d.conn.commit()
C.auto(force=True)
tp = [t for t in open_tasks(p8) if t["rule"] == "plan"]
check("unfinished plan task", len(tp) == 1 and tp[0]["plan_id"] == plan, open_tasks(p8))
cl = a.call_list("unfinished")
check("call list «План не завершён»", any(x["patient_id"] == p8 and "осталось на 30 000" in x["info"] for x in cl["rows"]), cl["rows"][:2])
visit(p8, 3)
C.auto(force=True)
check("booked: plan task closed", not [t for t in open_tasks(p8) if t["rule"] == "plan"])
check("booked: out of the call list", not any(x["patient_id"] == p8 for x in a.call_list("unfinished")["rows"]))

# --- tasks by hand
refuses("task needs a title", lambda: a.crm_task_save({"title": " "}), "Напишите")
refuses("task unknown patient", lambda: a.crm_task_save({"title": "x", "patient_id": "nope"}), "не найден")
refuses("task unknown employee", lambda: a.crm_task_save({"title": "x", "assignee": "ghost"}), "Сотрудник")
p9 = patient("Ручной", "+7 900 100-00-09")
tid = a.crm_task_save({"title": "Перезвонить про рассрочку", "patient_id": p9, "due": day(-2), "comment": "просила после зарплаты"})
r = a.crm_tasks({"scope": "overdue"})
check("overdue scope", any(x["id"] == tid and x["overdue"] for x in r["rows"]), r["counts"])
check("my scope has shared tasks", any(x["id"] == tid for x in a.crm_tasks({"scope": "my"})["rows"]))
refuses("done needs a known result", lambda: a.crm_task_done(tid, "??"), "результат")
a.crm_task_done(tid, "Перезвонить позже", "занята", day(2))
t = d.one("SELECT * FROM crm_tasks WHERE id=?", (tid,))
check("call later: moved, still open", t["status"] == "open" and t["due"] == day(2) and "занята" in t["comment"], t)
a.crm_task_done(tid, "Записался", "на четверг")
t = d.one("SELECT * FROM crm_tasks WHERE id=?", (tid,))
check("done", t["status"] == "done" and t["result"] == "Записался" and t["done_at"], t)
calls = a.patient(p9)["marketing"]["calls"]
check("task result in the call log", calls and calls[0]["result"] == "Записался" and calls[0]["list"] == "tasks", calls)
check("done scope", any(x["id"] == tid for x in a.crm_tasks({"scope": "done"})["rows"]))
a.crm_task_reopen(tid)
check("reopen", d.one("SELECT status FROM crm_tasks WHERE id=?", (tid,))["status"] == "open")
a.crm_task_delete(tid)
check("manual task deleted", not d.one("SELECT 1 AS x FROM crm_tasks WHERE id=?", (tid,)))
refuses("delete unknown", lambda: a.crm_task_delete(tid), "не найдена")

# --- requests (leads)
refuses("lead needs name or phone", lambda: a.crm_lead_save({}), "имя или телефон")
refuses("lead short phone", lambda: a.crm_lead_save({"name": "Ира", "phone": "123"}), "10–11")
known = patient("Известная", "+7 (901) 222-33-44")
m = a.crm_match("8 901 222 33 44")
check("match by phone in any format", [x["id"] for x in m] == [known], m)
l1 = a.crm_lead_save({"name": "Известная Тест", "phone": "89012223344", "channel": "Звонок", "source": "2ГИС", "interest": "Болит зуб"})
check("lead offers the existing card", [x["id"] for x in a.crm_lead(l1)["matches"]] == [known])
a.crm_lead_link(l1, known)
check("link: source copied to the patient", a.patient(known)["marketing"]["source"] == "2ГИС")
visit(known, 2)
lr = a.crm_leads({})
x1 = next(x for x in lr["rows"] if x["id"] == l1)
check("lead booked by itself", x1["stage"] == "booked", x1["stage"])
l2 = a.crm_lead_save({"name": "Новикова Ольга Петровна", "phone": "+7 902 000-11-22", "channel": "WhatsApp", "source": "Соцсети",
                      "interest": "Профгигиена", "next_at": day(-1)})
check("late request flagged", next(x for x in a.crm_leads({})["rows"] if x["id"] == l2)["late"])
np_ = a.crm_lead_patient(l2)
pp = a.patient(np_["id"])
check("card from request", pp["name"].startswith("Новикова Ольга") and "000-11-22" in (pp["phone"] or "") and pp["marketing"]["source"] == "Соцсети", pp["name"])
check("same request again — same card", a.crm_lead_patient(l2)["id"] == np_["id"])
vid = visit(np_["id"], 0, status="Завершён", h=0)
d.conn.execute("UPDATE crm_leads SET created_at=? WHERE id=?", (day(-1) + " 09:00:00", l2)); d.conn.commit()
check("lead came by itself", next(x for x in a.crm_leads({})["rows"] if x["id"] == l2)["stage"] == "came")
l3 = a.crm_lead_save({"phone": "+7 903 000-00-00", "channel": "Сайт", "source": "2ГИС"})
refuses("refusal needs a reason", lambda: a.crm_lead_stage(l3, "lost"), "причину")
refuses("unknown stage", lambda: a.crm_lead_stage(l3, "zzz"), "этап")
a.crm_lead_stage(l3, "lost", "Дорого")
check("lost lead stays lost", next(x for x in a.crm_leads({})["rows"] if x["id"] == l3)["stage"] == "lost")
f = a.crm_funnel(day(-5), day(0))
steps = {s["key"]: s["count"] for s in f["steps"]}
check("funnel", f["total"] >= 3 and steps["new"] == f["total"] and steps["booked"] >= 2 and steps["came"] >= 1 and f["lost"] >= 1, (f["total"], steps))
g = next((x for x in f["by_source"] if x["name"] == "2ГИС"), None)
check("funnel by source", g and g["leads"] == 2 and g["lost"] == 1 and g["booked"] == 1, g)
check("refusal reasons", any(x["reason"] == "Дорого" for x in f["reasons"]))
lt = a.crm_task_save({"title": "Перезвонить по заявке", "lead_id": l3})
check("task of a request", any(t["id"] == lt for t in a.crm_lead(l3)["tasks"]))

# --- advertising payback
eid = a.save_expense({"date": T.isoformat(), "category": "Реклама", "amount": 6000, "source": "Соцсети", "comment": "таргет"})
a.save_expense({"date": T.isoformat(), "category": "Аренда", "amount": 50000, "source": "Соцсети"})
check("source kept only for advertising", d.one("SELECT COUNT(*) AS n FROM expenses WHERE source='Соцсети'")["n"] == 1)
a.add_payment({"patient_id": np_["id"], "amount": 9000, "method": "Карта"})
rep = a.mk_sources_report(day(-5), day(0))
row = next((r for r in rep["rows"] if r["source"] == "Соцсети"), None)
check("payback in sources report", row and row["spent"] == 6000 and row["leads"] == 1 and row["leads_came"] == 1 and row["roi"] == 150, row)
check("cost of a new patient", row and row["new"] >= 1 and row["cost_new"] == round(6000 / row["new"]), row)
check("ad total", rep["spent"] >= 6000)
check("sources in accounting", "Соцсети" in a.acc_summary()["sources"] and a.acc_summary()["ad_category"] == "Реклама")

# --- after-visit scores
refuses("score range", lambda: a.crm_review_save({"patient_id": p9, "score": 11}), "от 0 до 10")
refuses("score unknown patient", lambda: a.crm_review_save({"patient_id": "x", "score": 5}), "не найден")
r10 = a.crm_review_save({"patient_id": np_["id"], "score": 10, "comment": "Всё отлично"})
check("good score offers review links", r10["ask_review"] and len(r10["links"]) == 2, r10)
check("score tied to the latest visit and doctor", d.one("SELECT visit_id, doctor_id FROM crm_reviews WHERE id=?", (r10["id"],))["doctor_id"] == doc)
r3 = a.crm_review_save({"patient_id": p9, "score": 3, "comment": "долго ждал"})
check("bad score: no links", not r3["ask_review"] and not r3["links"])
bad = [t for t in open_tasks(p9) if t["rule"] == "review"]
check("bad score: task for the director", len(bad) == 1 and "оценка 3" in bad[0]["title"], bad)
a.crm_review_save({"patient_id": known, "score": 8})
rv = a.crm_reviews(day(0), day(0))
check("NPS", rv["count"] == 3 and rv["nps"] == 0 and rv["promoters"] == 1 and rv["detractors"] == 1 and rv["dist"][10] == 1, rv)
check("NPS by doctor", any(x["doctor_id"] == doc and x["count"] >= 1 for x in rv["by_doctor"]), rv["by_doctor"])
q = a.crm_review_queue(day(0))
qx = next((x for x in q["rows"] if x["patient_id"] == np_["id"]), None)
check("who to ask: today's visit, rated", qx and qx["rated"], q["rows"][:3])
a.crm_review_delete(r3["id"])
check("score deleted", a.crm_reviews(day(0), day(0))["count"] == 2)

# --- tablet survey
code = a.tablet_code("Ресепшен")["code"]
key = a._tablet_public("pair", [code], "", "127.0.0.1")["key"]
tb = a.tablets_list()[0]["id"]
sent = a.tablet_send(tb, "nps", p1, None, {"visit_id": None})
task = a._tablet_public("task", [], key, "127.0.0.1")["task"]
check("tablet shows the question", task["kind"] == "nps" and "порекомендуете" in task["question"], task)
res = a._tablet_public("submit", [sent["task_id"], {"score": 9, "comment": "Спасибо"}], key, "127.0.0.1")
check("tablet answer: QR codes of review pages", res["ok"] and len(res["links"]) == 2 and res["links"][0]["qr"].startswith("data:image/png"), res.get("links", [{}])[0].get("title"))
check("tablet score saved", d.one("SELECT channel, score FROM crm_reviews WHERE patient_id=?", (p1,)) == {"channel": "tablet", "score": 9})
check("employee sees the result", a.tablet_status(tb, sent["task_id"])["result"]["score"] == 9)

# --- segments
old = patient("Давно", "+7 900 300-00-01", birth_date=(T + timedelta(days=3)).replace(year=T.year - 40).isoformat())
visit(old, -300, status="Завершён", title="Профгигиена")
seg = a.crm_segment_run({"months": 6, "no_future": True})
check("segment: not seen for 6 months", any(x["patient_id"] == old for x in seg["rows"]) and seg["with_phone"] >= 1, seg["count"])
check("segment: not for 12 months", not any(x["patient_id"] == old for x in a.crm_segment_run({"months": 12})["rows"]))
check("segment: service long ago", any(x["patient_id"] == old for x in a.crm_segment_run({"service": "гигиен", "service_months": 6})["rows"]))
check("segment: service recently", not any(x["patient_id"] == old for x in a.crm_segment_run({"service": "гигиен", "service_months": 12})["rows"]))
check("segment: birthday soon", any(x["patient_id"] == old and "день рождения" in x["info"] for x in a.crm_segment_run({"birthday_days": 7})["rows"]))
check("segment: age", any(x["patient_id"] == old for x in a.crm_segment_run({"age_min": 39, "age_max": 41})["rows"])
      and not any(x["patient_id"] == old for x in a.crm_segment_run({"age_min": 41})["rows"]))
refuses("segment: age from > to", lambda: a.crm_segment_run({"age_min": 50, "age_max": 20}), "Возраст")
plan_pat = patient("ПланНеНачат")
a.save_invoice({"patient_id": plan_pat, "kind": "plan", "items": [{"title": "Коронка", "price": 20000}]})
check("segment: plan not started", any(x["patient_id"] == plan_pat for x in a.crm_segment_run({"plan": "not_started"})["rows"]))
check("segment: plan started", any(x["patient_id"] == p8 for x in a.crm_segment_run({"plan": "unfinished"})["rows"])
      and not any(x["patient_id"] == plan_pat for x in a.crm_segment_run({"plan": "unfinished"})["rows"]))
check("segment: source", {x["patient_id"] for x in a.crm_segment_run({"source": "Соцсети"})["rows"]} == {np_["id"]})
check("segment: debt", any(x["patient_id"] == p1 for x in a.crm_segment_run({"debt": True})["rows"]))
check("segment: «do not call» left out", not any(x["patient_id"] == p4 for x in a.crm_segment_run({})["rows"])
      and any(x["patient_id"] == p4 for x in a.crm_segment_run({"with_no_calls": True})["rows"]))
check("segment: paid", {x["patient_id"] for x in a.crm_segment_run({"paid_min": 9000})["rows"]} >= {np_["id"]})
refuses("segment needs a title", lambda: a.crm_segment_save({"title": "", "filters": {}}), "Назовите")
sid = a.crm_segment_save({"title": "Гигиена полгода", "filters": {"service": "гигиен", "service_months": "6", "junk": 1}})
sv = a.crm_segments()
check("segment saved, filters cleaned", any(x["id"] == sid and x["filters"] == {"service": "гигиен", "service_months": 6} for x in sv["saved"])
      and len(sv["presets"]) >= 5, sv["saved"])
for p in sv["presets"]:
    a.crm_segment_run(p["filters"])
OK[0] += 1  # every preset runs
a.crm_segment_delete(sid)
check("segment deleted", not a.crm_segments()["saved"])
check("mailing mark goes to the call log", a.log_call({"patient_id": old, "list": "segment", "result": "Написали", "comment": "Гигиена"})
      and a.patient(old)["marketing"]["calls"][0]["list"] == "segment")

# --- patient card, summary, director, status
pc = a.crm_patient(p9)
check("patient card: tasks, scores, calls", pc["open"] >= 1 and pc["calls"] and isinstance(pc["reviews"], list), pc["open"])
check("open tasks count in the card", a.patient(p9)["crm_open"] >= 1)
sm = a.crm_summary()
check("summary", sm["tasks_open"] >= 3 and sm["tasks_overdue"] >= 0 and "leads_new" in sm, sm)
late = a.crm_task_save({"title": "Просроченная", "due": day(-3)})
adv = a.director_dashboard()["advice"]
check("director: overdue tasks advice", any(x.get("go") == "crm" and "Просрочено" in x["text"] for x in adv), [x["text"] for x in adv])
st = a.status()
check("menu badge", st.get("crm_due", 0) >= 1, st.get("crm_due"))

# --- sync between laptops: CRM tables are captured
replica.install(d)
names = {t.name for t in replica.TABLES}
check("CRM tables in sync", {"crm_leads", "crm_tasks", "crm_reviews", "crm_segments", "crm_settings"} <= names)
d.conn.execute("DELETE FROM sync_dirty"); d.conn.commit()
a.crm_task_save({"title": "Синхронизация"})
a.crm_settings_save({"plan_days": 40})
dirty = {r["tbl"] for r in d.q("SELECT tbl FROM sync_dirty")}
check("changes go to the cloud queue", {"crm_tasks", "crm_settings"} <= dirty, dirty)

# --- demo data and wipe
demo.ensure_crm(d)
check("demo requests and scores", d.one("SELECT COUNT(*) AS n FROM crm_leads WHERE created_by='Демо'")["n"] == 16
      and d.one("SELECT COUNT(*) AS n FROM crm_reviews WHERE user_name='Демо'")["n"] == 20)
demo.ensure_crm(d)
check("demo only once", d.one("SELECT COUNT(*) AS n FROM crm_leads WHERE created_by='Демо'")["n"] == 16)
check("demo advertising", d.one("SELECT COUNT(*) AS n FROM expenses WHERE id LIKE 'demo_ad%' AND source<>''")["n"] == 4)
d.wipe()
check("wipe removes demo CRM", d.one("SELECT COUNT(*) AS n FROM crm_leads")["n"] == 0 and d.one("SELECT COUNT(*) AS n FROM crm_reviews")["n"] == 0)
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
    call("auth", "register", {"name": login.upper(), "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TA = call("auth", "login", "adm", "secret1")[1]["token"]
TDoc = call("auth", "login", "doc", "secret1")[1]["token"]
st, staff = call("api", "crm_tasks", {"scope": "all"}, token=TA)
check("admin opens tasks", st == 200 and {s["login"] for s in staff["staff"]} == {"dir", "adm"}, staff.get("staff"))
st, tid = call("api", "crm_task_save", {"title": "Позвонить Ивановой", "assignee": "adm"}, token=TD)
check("director gives a task to the admin", st == 200)
mine = call("api", "crm_tasks", {"scope": "my"}, token=TA)[1]["rows"]
check("admin sees own task", any(x["id"] == tid and x["assignee_name"] == "ADM" for x in mine))
check("director's «my» has no admin task", not any(x["id"] == tid for x in call("api", "crm_tasks", {"scope": "my"}, token=TD)[1]["rows"]))
check("doctor: no CRM", call("api", "crm_tasks", {}, token=TDoc)[0] == 403 and call("api", "crm_lead_save", {"name": "x"}, token=TDoc)[0] == 403)
check("badge per employee", call("api", "status", token=TA)[1].get("crm_due", 0) >= 1 and "crm_due" not in call("api", "status", token=TDoc)[1])
check("admin closes the task", call("api", "crm_task_done", tid, "Дозвонились", "", None, token=TA)[0] == 200)
au = d.q("SELECT action, user_name FROM audit WHERE action IN ('Задача CRM', 'Задача CRM выполнена') ORDER BY id")
check("CRM changes in the journal", [x["action"] for x in au][-2:] == ["Задача CRM", "Задача CRM выполнена"] and au[-1]["user_name"] == "ADM", au)
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
