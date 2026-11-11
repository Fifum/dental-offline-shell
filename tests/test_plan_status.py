"""3.6 «Статусы планов лечения» (stage 4 of the add-on over Dentist Plus): the history of a plan's status (made, chosen, billed,
by hand, automatic), the automatic rules — a bill or a Dentist Plus visit with a plan service → «в работе», everything billed →
«завершён», no visit / bill / booking for N days → «брошен», back to work on a visit, a bill or a booking — and that a manual
status wins; the call list for abandoned plans (who, why, money, last visit; reached / not reached / call back on a date /
refused / booked) linked to the call journal and the CRM tasks; the report by status and doctor, conversion and the money left
in abandoned plans; the motivation for plans brought back; the director's hint; two computers offline; rights over HTTP, the
journal and the UI."""
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
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import plan_status as psm  # noqa: E402
import replica  # noqa: E402
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


def day(n):
    return (T + timedelta(days=n)).isoformat()


def setup(d):
    d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}, {"id": 2, "lname": "Сидорова", "fname": "Анна"}])
    with d.tx() as c:
        for sid, code, title, price in (("api_201", "I-1", "Имплантация", 40000), ("api_202", "I-2", "Коронка на имплант", 30000),
                                        ("api_203", "G-1", "Профгигиена", 5000)):
            c.execute("INSERT OR REPLACE INTO services VALUES(?,?,?,?,?,?,1)", (sid, code, title, price, "Хирургия", "api"))
        for pid, name, phone in (("p1", "Иванов Иван", "+7 900 000-00-01"), ("p2", "Смирнова Ольга", "+7 900 000-00-02"),
                                 ("p3", "Кузнецов Пётр", "+7 900 000-00-03"), ("p4", "Орлова Мария", "+7 900 000-00-04"),
                                 ("p5", "Волков Олег", "+7 900 000-00-05"), ("p6", "Зайцева Нина", "+7 900 000-00-06")):
            c.execute("INSERT OR REPLACE INTO patients(id, name, phone, local) VALUES(?,?,?,0)", (pid, name, phone))


ITEMS = [{"service_id": "api_201", "title": "Имплантация", "price": 40000, "tooth": "36"},
         {"service_id": "api_202", "title": "Коронка на имплант", "price": 30000, "tooth": "36"}]


def plan(a, pid, doctor="1", items=None, status=None, **kw):
    return a.save_invoice({"patient_id": pid, "doctor_id": doctor, "kind": "plan", "title": kw.pop("title", "Имплантация 36"),
                           "items": [dict(x) for x in (items or ITEMS)], **({"plan_status": status} if status else {}), **kw})


def age(d, plan_id, days):
    """Move the plan, its bills and its history `days` back, as if nothing happened since."""
    at = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with d.tx() as c:
        c.execute("UPDATE invoices SET created_at=? WHERE id=? OR plan_id=?", (at, plan_id, plan_id))
        c.execute("UPDATE plan_status_log SET at=? WHERE plan_id=?", (at, plan_id))


def st(d, plan_id):
    return d.one("SELECT plan_status FROM invoices WHERE id=?", (plan_id,))["plan_status"]


def hist(a, plan_id):
    return [(h["old"], h["new"], bool(h["auto"])) for h in a.plan_history(plan_id)]


d = dbm.DB()
setup(d)
auth.Auth(d)  # the action journal
a = Api(d, W())
P = a._pst

# ------------------------------------------------------------------ settings
s = a.plan_status_meta()["settings"]
check("defaults", s == {"on": True, "days": 60, "proposed_days": 0, "done_auto": True, "visit_auto": True, "call_months": 12}, s)
check("six statuses with labels", [x["label"] for x in a.plan_status_meta()["statuses"]] ==
      ["Предложен", "Продан", "В работе", "Завершён", "Брошен", "Отказ"])
refuses("days too few", lambda: a.plan_status_settings_save({"days": 3}), "14")
refuses("days not a number", lambda: a.plan_status_settings_save({"days": "x"}), "число")
check("settings saved", a.plan_status_settings_save({"days": 45})["days"] == 45 and P.settings()["days"] == 45)
a.plan_status_settings_save({"days": 60})

# ------------------------------------------------------------------ the history: made, chosen, by hand, billed
p1 = plan(a, "p1")
check("a new plan is proposed", st(d, p1) == "Предварительный" and hist(a, p1) == [("", "Предварительный", False)], hist(a, p1))
check("who made it — by login (no account here: empty)", a.plan_history(p1)[0]["reason"] == "план составлен")
inv = a.invoice(p1)
a.save_invoice({**inv, "plan_status": "Подтверждён"})
check("sold by hand", st(d, p1) == "Подтверждён" and hist(a, p1)[-1] == ("Предварительный", "Подтверждён", False), hist(a, p1))
check("labels in the history", a.plan_history(p1)[-1]["new_label"] == "Продан" and a.plan_history(p1)[-1]["reason"] == "вручную")
a.save_invoice({**a.invoice(p1), "comment": "без изменения статуса"})
check("saving without a change adds nothing", len(hist(a, p1)) == 2)
refuses("unknown status", lambda: a.set_plan_status(p1, "Непонятно"), "неизвестный")
refuses("not a plan", lambda: a.set_plan_status("nope", "Брошен"), "не найден")
pv = plan(a, "p6", variants=[{"key": "a", "name": "Эконом"}, {"key": "b", "name": "Премиум"}],
          items=[{**ITEMS[0], "opt": "a"}, {**ITEMS[0], "price": 60000, "opt": "b"}])
a.plan_choose(pv, "b")
check("the choice of an option is in the history", hist(a, pv)[-1] == ("Предварительный", "Подтверждён", False)
      and a.plan_history(pv)[-1]["reason"] == "выбран вариант", a.plan_history(pv))

# a bill by the plan → «в работе»; everything billed → «завершён»
i1 = a.plan_to_invoice(p1, [0])
check("billed → in work", st(d, p1) == "Активен" and hist(a, p1)[-1] == ("Подтверждён", "Активен", False), hist(a, p1))
check("…with the reason", a.plan_history(p1)[-1]["reason"] == "счёт по плану")
a.plan_to_invoice(p1, [1])
check("everything billed → finished (automatically)", st(d, p1) == "Лечение завершено" and hist(a, p1)[-1] == ("Активен", "Лечение завершено", True),
      hist(a, p1))
age(d, p1, 1 / 1440)  # the bills were a minute ago
a.set_plan_status(p1, "Активен", "пациент вернётся на коррекцию")
P.evaluate()
check("a manual status wins over «everything billed»", st(d, p1) == "Активен" and a.plan_history(p1)[-1]["reason"] == "пациент вернётся на коррекцию")
pvv = plan(a, "p6", variants=[{"key": "a", "name": "Эконом"}, {"key": "b", "name": "Премиум"}],
           items=[ITEMS[0], {**ITEMS[1], "opt": "a"}, {**ITEMS[1], "price": 50000, "opt": "b"}])
a.plan_to_invoice(pvv, [0])
check("options not chosen: not «finished» after the common items", st(d, pvv) == "Активен")

# ------------------------------------------------------------------ abandoned: no visit, bill or booking for 60 days
p2 = plan(a, "p2", doctor="2")
a.set_plan_status(p2, "Подтверждён")
d.conn.execute("UPDATE invoices SET transferred=1 WHERE id=?", (p2,)); d.conn.commit()
a.crm_settings_save({"plan_days": 30})
age(d, p2, 40)
a._crm.auto(force=True)
check("CRM «пригласить продолжить» at 30 days (as before)", d.one("SELECT COUNT(*) AS n FROM crm_tasks WHERE plan_id=? AND rule='plan' AND status='open'", (p2,))["n"] == 1)
P.evaluate()
check("40 days — not abandoned yet", st(d, p2) == "Подтверждён")
age(d, p2, 70)
res = P.evaluate()
check("70 days — abandoned", st(d, p2) == "Брошен" and res.get("Брошен") >= 1, (st(d, p2), res))
h = a.plan_history(p2)[-1]
check("automatic, with the reason", h["auto"] == 1 and "нет визитов" in h["reason"] and h["who"] == "Программа", h)
check("the mark «перенесено в Dentist Plus» stays", d.one("SELECT transferred FROM invoices WHERE id=?", (p2,))["transferred"] == 1)
check("the CRM task is closed with a pointer to the call list",
      d.one("SELECT status, comment FROM crm_tasks WHERE plan_id=? AND rule='plan'", (p2,))["status"] == "done"
      and "Брошенные планы" in d.one("SELECT comment FROM crm_tasks WHERE plan_id=? AND rule='plan'", (p2,))["comment"])
au = d.q("SELECT * FROM audit WHERE action='Статусы планов лечения (автоматически)'")
check("the journal", au and au[-1]["user_name"] == "Программа" and "Смирнова" in au[-1]["detail"], au[-1:] if au else au)
n = len(hist(a, p2))
P.evaluate()
check("one more pass changes nothing", len(hist(a, p2)) == n and st(d, p2) == "Брошен")
check("abandoned plans are unfinished for the director's week", a._dir.db.one(
    "SELECT COUNT(*) AS n FROM invoices WHERE kind='plan' AND plan_status IN ('Предварительный','Подтверждён','Активен','Брошен')")["n"] >= 2)

# a proposed plan is never abandoned by default; with proposed_days it is
p3 = plan(a, "p3")
age(d, p3, 100)
P.evaluate()
check("proposed: untouched by default", st(d, p3) == "Предварительный")
a.plan_status_settings_save({"proposed_days": 90})
P.evaluate()
check("proposed_days 90 → abandoned", st(d, p3) == "Брошен")
a.plan_status_settings_save({"proposed_days": 0})

# a booking brings an automatically abandoned plan back; a manual one stays until something happens after it
fut = a.save_visit({"patient_id": "p2", "doctor_id": "2", "start": f"{day(3)} 10:00:00", "end": f"{day(3)} 10:30:00", "status": "Запланирован",
                    "title": "Осмотр"})
P.evaluate()
check("booked → back to «продан»", st(d, p2) == "Подтверждён" and hist(a, p2)[-1] == ("Брошен", "Подтверждён", True), hist(a, p2))
check("…«снова в работе: запись»", "запись" in a.plan_history(p2)[-1]["reason"])
a.set_plan_status(p2, "Брошен", "пациент сказал, что подумает")
P.evaluate()
check("manually abandoned: a booking made before does not bring it back", st(d, p2) == "Брошен")
age(d, p2, 3)
with d.tx() as c:  # abandoned by hand two days ago, everything else three days ago
    c.execute("UPDATE plan_status_log SET at=? WHERE plan_id=? AND new='Брошен' AND auto=0", ((datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), p2))
a.save_visit({"patient_id": "p2", "doctor_id": "2", "start": f"{day(-1)} 11:00:00", "end": f"{day(-1)} 11:30:00", "status": "Завершён", "title": "Осмотр"})
P.evaluate()
check("…a visit after it does", st(d, p2) == "Подтверждён" and "визит" in a.plan_history(p2)[-1]["reason"], a.plan_history(p2)[-1])

# a Dentist Plus visit with a service of the plan → «в работе»
p4 = plan(a, "p4")
a.set_plan_status(p4, "Подтверждён")
with d.tx() as c:  # sold two days ago
    c.execute("UPDATE plan_status_log SET at=? WHERE plan_id=?", ((datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), p4))
    c.execute("UPDATE invoices SET created_at=? WHERE id=?", ((datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"), p4))
y = day(-1)
d.replace_visits(day(-5), day(5), [
    {"id": "dv1", "patient_id": "p4", "doctor_id": "1", "branch_id": "1", "start": f"{y} 10:00:00", "end": f"{y} 11:00:00", "status": "Завершён",
     "title": "Приём", "raw": {"id": "dv1", "services": [{"service_id": 203}]}},
])
P.evaluate()
check("a DP visit with another service: still sold", st(d, p4) == "Подтверждён")
d.replace_visits(day(-5), day(5), [
    {"id": "dv1", "patient_id": "p4", "doctor_id": "1", "branch_id": "1", "start": f"{y} 10:00:00", "end": f"{y} 11:00:00", "status": "Завершён",
     "title": "Приём", "raw": {"id": "dv1", "services": [{"service_id": 201}]}},
])
P.evaluate()
check("a DP visit with a plan service → in work", st(d, p4) == "Активен" and "Dentist Plus" in a.plan_history(p4)[-1]["reason"]
      and "Имплантация" in a.plan_history(p4)[-1]["reason"], a.plan_history(p4)[-1])
a.plan_status_settings_save({"on": False})
p5 = plan(a, "p5", status="Подтверждён")
age(d, p5, 90)
check("rules off: nothing changes", P.evaluate() == {} and st(d, p5) == "Подтверждён")
a.plan_status_settings_save({"on": True})
P.evaluate()
check("rules on again", st(d, p5) == "Брошен")

# ------------------------------------------------------------------ the call list
cl = a.plan_calls({})
rows = {r["plan_id"]: r for r in cl["rows"]}
check("abandoned plans in the list", p5 in rows and p3 in rows, list(rows))
r5 = rows.get(p5) or {}
check("who, why, money, last visit", r5.get("name") == "Волков Олег" and r5.get("phone") and r5.get("left") == 70000
      and "нет визитов" in r5.get("reason", "") and r5.get("due") and r5.get("last_call") is None and r5.get("idle", 0) >= 89, r5)
check("doctor filter", all(r["doctor_id"] == "2" for r in a.plan_calls({"doctor_id": "2"})["rows"]))
check("…sum left", cl["sum_left"] >= 70000)
check("old plans out by months", p5 not in {r["plan_id"] for r in a.plan_calls({"months": 2})["rows"]}
      and p5 in {r["plan_id"] for r in a.plan_calls({"months": 0})["rows"]})
refuses("result needed", lambda: a.plan_call({"plan_id": p5}), "результат")
refuses("call back needs a date", lambda: a.plan_call({"plan_id": p5, "result": "callback"}), "когда")
refuses("call back not in the past", lambda: a.plan_call({"plan_id": p5, "result": "callback", "call_on": day(-1)}), "сегодня")
refuses("refusal needs a reason", lambda: a.plan_call({"plan_id": p5, "result": "refused"}), "причину")
a.plan_call({"plan_id": p5, "result": "no_answer"})
r5 = next(r for r in a.plan_calls({})["rows"] if r["plan_id"] == p5)
check("not reached: not due again today", not r5["due"] and r5["last_call"]["result"] == "Не дозвонились", r5)
check("…«к звонку» hides it", p5 not in {r["plan_id"] for r in a.plan_calls({"due_only": True})["rows"]})
a.plan_call({"plan_id": p5, "result": "callback", "call_on": day(5), "comment": "в отпуске"})
r5 = next(r for r in a.plan_calls({})["rows"] if r["plan_id"] == p5)
check("call back on a date", r5["next_call"] == day(5) and not r5["due"], r5)
tk = d.one("SELECT * FROM crm_tasks WHERE plan_id=? AND rule='plan_call'", (p5,))
check("a CRM task due on that day (the reminder)", tk and tk["status"] == "open" and tk["due"] == day(5) and "в отпуске" in tk["comment"], tk)
a.plan_call({"plan_id": p5, "result": "callback", "call_on": day(1)})
check("one task per plan, moved", d.one("SELECT COUNT(*) AS n FROM crm_tasks WHERE plan_id=? AND rule='plan_call'", (p5,))["n"] == 1
      and d.one("SELECT due FROM crm_tasks WHERE plan_id=? AND rule='plan_call'", (p5,))["due"] == day(1))
calls = d.q("SELECT * FROM marketing_calls WHERE plan_id=? ORDER BY id", (p5,))
check("calls are in the call journal with the plan", len(calls) == 3 and calls[-1]["list"] == "abandoned" and calls[-1]["call_on"] == day(1), calls)
check("…and in the patient's call history", a._mk.patient_info("p5")["calls"][0]["result"] == "Перезвонить")
a.plan_call({"plan_id": p5, "result": "reached", "comment": "думает"})
check("reached closes the CRM task", d.one("SELECT status, result FROM crm_tasks WHERE plan_id=? AND rule='plan_call'", (p5,))["result"] == "Дозвонились")
a.plan_call({"plan_id": p5, "result": "refused", "reason": "Дорого"})
check("refused → «Отказ» with the reason", st(d, p5) == "Отказ" and "Дорого" in a.plan_history(p5)[-1]["reason"]
      and not a.plan_history(p5)[-1]["auto"], a.plan_history(p5)[-1])
check("…out of the list", p5 not in {r["plan_id"] for r in a.plan_calls({})["rows"]})
# booked: the visit is already in the schedule → back to work at once, the call counts for the caller
a.save_visit({"patient_id": "p3", "doctor_id": "1", "start": f"{day(4)} 12:00:00", "end": f"{day(4)} 12:30:00", "status": "Запланирован", "title": "Х"})
a.plan_status_settings_save({"proposed_days": 90})
res = P.call({"plan_id": p3, "result": "booked"}, "adm", "Администратор")
check("booked with a visit → back", res["status"] == "Предварительный" and st(d, p3) == "Предварительный", res)
check("…credited to the caller", a.plan_history(p3)[-1]["credit"] == "adm", a.plan_history(p3)[-1])
a.plan_status_settings_save({"proposed_days": 0})
# no_calls patients are not listed
p6 = plan(a, "p6", status="Подтверждён")
age(d, p6, 80)
P.evaluate()
check("p6 abandoned", st(d, p6) == "Брошен")
a.set_patient_marketing("p6", {"no_calls": True})
check("«не звонить» — not in the list", p6 not in {r["plan_id"] for r in a.plan_calls({})["rows"]})
a.set_patient_marketing("p6", {"no_calls": False})
# a CRM task «перезвонить» closed with «Отказ» on the tasks screen refuses the plan too
a.plan_call({"plan_id": p6, "result": "callback", "call_on": day(0)})
tid = d.one("SELECT id FROM crm_tasks WHERE plan_id=? AND rule='plan_call'", (p6,))["id"]
a.crm_task_done(tid, "Отказ", "уехал")
check("task «Отказ» → plan refused", st(d, p6) == "Отказ" and "задача CRM" in a.plan_history(p6)[-1]["reason"])
check("…the task call has the plan", d.one("SELECT plan_id FROM marketing_calls WHERE list='tasks' ORDER BY id DESC LIMIT 1")["plan_id"] == p6)

# ------------------------------------------------------------------ the report
rep = a.plan_report(day(-400), day(0))
bs = {x["key"]: x for x in rep["by_status"]}
check("by status", bs["Отказ"]["n"] == 2 and bs["Активен"]["n"] >= 2 and sum(x["n"] for x in rep["by_status"]) == rep["funnel"]["proposed"], bs)
f = rep["funnel"]
check("funnel proposed ≥ sold ≥ started ≥ done", f["proposed"] >= f["sold"] >= f["started"] >= f["done"] >= 0 and f["sold"] >= 4, f)
check("an abandoned (once sold) plan counts as sold", f["sold"] >= 5, f)
docs = {x["doctor_id"]: x for x in rep["by_doctor"]}
check("by doctor", "1" in docs and "2" in docs and docs["2"]["n"] == 1 and docs["2"]["name"].startswith("Сидорова"), docs.keys())
check("conversion in %", docs["1"]["sold_rate"] is not None and 0 <= docs["1"]["sold_rate"] <= 100)
a.set_plan_status(p2, "Брошен", "тест")
rep = a.plan_report(day(-400), day(0))
check("money in abandoned now", rep["lost_now"]["n"] >= 1 and rep["lost_now"]["left"] >= 70000, rep["lost_now"])
check("brought back in the period, by staff", rep["back"]["n"] >= 2 and any(x["login"] == "adm" for x in rep["back"]["by_staff"]), rep["back"])
check("plans list filtered by status", all(p["status"] == "Брошен" for p in a.plan_report(day(-400), day(0), {"status": "Брошен"})["plans"]))
check("doctor filter in the report", a.plan_report(day(-400), day(0), {"doctor_id": "2"})["funnel"]["proposed"] == 1)
check("summary for the director", psm.abandoned_summary(d)["n"] == rep["lost_now"]["n"])
adv = a._dir.dashboard()["advice"]
check("director's hint", any(x["go"] == "plans" and "Брошено" in x["text"] for x in adv), [x["text"] for x in adv])

# ------------------------------------------------------------------ motivation: a plan brought back by a call
mon = T.strftime("%Y-%m")
check("motivation rule exists", any(x["key"] == "plan_back" for x in a.motivation_rules()["fields"]))
check("…counted for the caller", a._mot._plans_back("adm", f"{mon}-01", day(1)) >= 1)

# ------------------------------------------------------------------ two computers: the same abandonment offline → one history row
names = {t.name for t in replica.TABLES}
check("new tables are synced", {"plan_status_log", "plan_settings"} <= names)
replica.install(d)
d2 = dbm.DB(Path(tempfile.mkdtemp()) / "b.db")
setup(d2)
a2 = Api(d2, W())
replica.install(d2)
replica.stamp(d, "A")
sres = replica.apply_versions(d2, replica.changes_since(d, 0, 100000), "B")
check("everything arrives", sres["conflicts"] == 0 and d2.one("SELECT COUNT(*) AS n FROM plan_status_log")["n"] == d.one("SELECT COUNT(*) AS n FROM plan_status_log")["n"], sres)
check("settings arrive", a2._pst.settings()["days"] == 60)
q = plan(a, "p1", title="Второй план", status="Подтверждён")
replica.stamp(d, "A")
replica.apply_versions(d2, replica.changes_since(d, 0, 100000), "B")
for x in (d, d2):
    age(x, q, 75)
r1, r2 = a._pst.evaluate([q]), a2._pst.evaluate([q])
check("both abandon offline", r1.get("Брошен") == 1 and r2.get("Брошен") == 1, (r1, r2))
replica.stamp(d, "A")
replica.stamp(d2, "B")
replica.apply_versions(d2, replica.changes_since(d, 0, 100000), "B")
replica.apply_versions(d, replica.changes_since(d2, 0, 100000), "A")
n1 = d.one("SELECT COUNT(*) AS n FROM plan_status_log WHERE plan_id=? AND new='Брошен'", (q,))["n"]
n2 = d2.one("SELECT COUNT(*) AS n FROM plan_status_log WHERE plan_id=? AND new='Брошен'", (q,))["n"]
check("one history row after the sync", n1 == 1 and n2 == 1, (n1, n2))
check("the same status", st(d, q) == st(d2, q) == "Брошен")
check("calls carry the plan to the other computer", d2.one("SELECT COUNT(*) AS n FROM marketing_calls WHERE plan_id=?", (p5,))["n"] >= 3)

# ------------------------------------------------------------------ rights over HTTP and the journal
NEW = ("plan_status_meta", "plan_history", "plan_status_settings_save", "plan_calls", "plan_call", "plan_report")
check("every new method has a right", all(m in auth.METHOD_PERMS for m in NEW), [m for m in NEW if m not in auth.METHOD_PERMS])
check("changes in the journal", {"plan_call", "plan_status_settings_save", "set_plan_status"} <= set(auth.AUDITED))
check("reading not journaled", not {"plan_calls", "plan_report", "plan_history", "plan_status_meta"} & set(auth.AUDITED))
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
d3 = dbm.DB(Path(tempfile.mkdtemp()) / "c.db")
setup(d3)
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
for login, role, doctor in (("adm", "admin", ""), ("asst", "assistant", ""), ("doc2", "doctor", "2"), ("doc0", "doctor", "")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TDIR)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active", "doctor_id": doctor}, token=TDIR)
    tok[login] = call("auth", "login", login, "secret1")[1]["token"]
h1 = plan(a3, "p1", status="Подтверждён")
h2 = plan(a3, "p2", doctor="2", status="Подтверждён")
for x in (h1, h2):
    age(d3, x, 90)
a3._pst.evaluate()
st_, body = call("api", "plan_calls", {}, token=tok["adm"])
check("administrator sees the call list", st_ == 200 and {h1, h2} <= {r["plan_id"] for r in body["rows"]}, (st_, str(body)[:200]))
check("assistant: no call list", call("api", "plan_calls", {}, token=tok["asst"])[0] == 403)
st_, body = call("api", "plan_call", {"plan_id": h1, "result": "callback", "call_on": day(2)}, token=tok["adm"])
check("administrator logs a call", st_ == 200 and body["ok"], (st_, body))
c = d3.one("SELECT * FROM marketing_calls WHERE plan_id=?", (h1,))
check("the caller by login and name", c["login"] == "adm" and c["user_name"] == "adm", c)
check("the CRM task is assigned to the caller", d3.one("SELECT assignee FROM crm_tasks WHERE plan_id=? AND rule='plan_call'", (h1,))["assignee"] == "adm")
check("administrator cannot change the rules", call("api", "plan_status_settings_save", {"days": 30}, token=tok["adm"])[0] == 403)
check("director changes the rules", call("api", "plan_status_settings_save", {"days": 30}, token=TDIR)[0] == 200)
st_, body = call("api", "plan_report", day(-400), day(0), {}, token=tok["doc2"])
check("doctor sees own plans only", st_ == 200 and body["own"] and body["funnel"]["proposed"] == 1, (st_, str(body)[:200]))
st_, body = call("api", "plan_report", day(-400), day(0), {"doctor_id": "1"}, token=tok["doc2"])
check("…even when asking for another doctor", st_ == 200 and body["funnel"]["proposed"] == 1)
st_, body = call("api", "plan_report", day(-400), day(0), {}, token=tok["doc0"])
check("doctor without a doctor link — refused", st_ != 200 and "связана с врачом" in json.dumps(body, ensure_ascii=False), (st_, body))
st_, body = call("api", "plan_report", day(-400), day(0), {}, token=TDIR)
check("director sees all", st_ == 200 and body["funnel"]["proposed"] == 2 and not body["own"])
st_, body = call("api", "plan_report", day(-400), day(0), {}, token=tok["adm"])
check("administrator: no report", st_ != 200 and "Отчёты" in json.dumps(body, ensure_ascii=False), (st_, body))
st_, body = call("api", "plan_history", h1, token=tok["doc2"])
check("doctor sees the history", st_ == 200 and body[-1]["new"] == "Брошен")
st_, body = call("api", "set_plan_status", h2, "Отказ", "передумал", token=tok["doc2"])
check("doctor sets a status by hand", st_ == 200 and st(d3, h2) == "Отказ")
h = a3.plan_history(h2)[-1]
check("…by login, with the reason", h["login"] == "doc2" and h["reason"] == "передумал" and not h["auto"], h)
au = call("auth", "audit_list", token=TDIR)[1]
for m, who in (("plan_call", "adm"), ("set_plan_status", "doc2"), ("plan_status_settings_save", "Директор")):
    check(f"journal: {m}", any(x["action"] == auth.AUDITED[m] and x["user_name"] == who for x in au), [(x["action"], x["user_name"]) for x in au][:6])
st_, body = call("api", "status", token=tok["adm"])
check("status: abandoned plans to call for CRM", st_ == 200 and "plan_calls" in body, list(body)[:40])
st_, body = call("api", "status", token=tok["asst"])
check("…not for the assistant", st_ == 200 and "plan_calls" not in body)
srv.stop()

# ------------------------------------------------------------------ the UI
html = (UI / "index.html").read_text(encoding="utf-8")
js = (UI / "plan-status.js").read_text(encoding="utf-8") if (UI / "plan-status.js").exists() else ""
check("version 3.6.0 or later", tuple(map(int, config.VERSION.split("."))) >= (3, 6, 0), config.VERSION)
check("plan-status.js with the cache tag", f'<script src="plan-status.js?v={config.VERSION}"></script>' in html)
check("no old cache tags", "?v=3.5.0" not in html)
check("reports tab", 'data-k="plans"' in html)
check("screens", all(f"function {fn}" in js for fn in ("planCalls", "planCallDialog", "planStatusSettings", "repPlans", "planHistoryInto",
                                                       "pstOptions", "planCallsStatus")))
mk = (UI / "marketing.js").read_text(encoding="utf-8")
check("call list wired", '"abandoned"' in mk and "planCalls(body)" in mk)
check("plan editor wired", "pstOptions" in (UI / "billing.js").read_text(encoding="utf-8") and '"Брошен"' in (UI / "billing.js").read_text(encoding="utf-8"))
check("report wired", "repPlans" in (UI / "reports.js").read_text(encoding="utf-8"))
check("status badge wired", "planCallsStatus" in (UI / "app.js").read_text(encoding="utf-8"))
notes = ROOT / "docs" / f"Что нового в версии {'.'.join(config.VERSION.split('.')[:2])}.txt"
check("what's new", notes.exists() and "Dental Desk" in notes.read_text(encoding="utf-8"), notes)
check("README section", "## Treatment plan statuses (3.6)" in (ROOT / "README.md").read_text(encoding="utf-8"))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  ✗", f)
sys.exit(1 if FAIL else 0)
