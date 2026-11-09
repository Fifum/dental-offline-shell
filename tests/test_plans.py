"""Treatment plans 2.9.0: options «эконом / стандарт / премиум» in one plan, the patient's choice (screen and tablet),
billing only the chosen option, the presentation PDF, the tooth formula by surfaces, migration and rights."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import catalog  # noqa: E402
import db as dbm  # noqa: E402
import local as localm  # noqa: E402
import plans  # noqa: E402
import replica  # noqa: E402
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
        check(name, not text or text in str(e), e)


# ------------------------------------------------------------- pure helpers
v = plans.norm_variants([{"key": "A", "name": " Эконом "}, {"key": "a", "name": "дубль"}, {"key": "b", "name": ""},
                         {"key": "b!", "name": "Стандарт", "warranty": "3 года"}, {"key": "c", "name": "Премиум"},
                         {"key": "d", "name": "Четвёртый"}, {"key": "e", "name": "Пятый"}, "мусор"])
check("options cleaned", [x["key"] for x in v] == ["a", "b", "c", "d"], v)
check("option name trimmed", v[0]["name"] == "Эконом")
check("option details kept", v[1]["warranty"] == "3 года" and v[1]["note"] == "")
check("options from json text", plans.norm_variants('[{"key":"x","name":"Икс"}]')[0]["key"] == "x")
check("broken json is empty", plans.norm_variants("{oops") == [])

VS = [{"key": "a", "name": "Эконом"}, {"key": "b", "name": "Стандарт"}, {"key": "c", "name": "Премиум"}]
ITEMS = [
    {"title": "Осмотр", "price": 1000, "qty": 1, "stage": "1"},                                       # common
    {"title": "Гигиена", "price": 4000, "qty": 1, "discount": 25, "stage": "1"},                      # common: 3000
    {"title": "Пломба", "price": 5000, "qty": 2, "tooth": "36, 37", "opt": "a", "stage": "2"},        # 10000
    {"title": "Вкладка", "price": 18000, "qty": 2, "tooth": "36, 37", "opt": "b", "stage": "2"},      # 36000
    {"title": "Коронка", "price": 35000, "qty": 2, "tooth": "36, 37", "opt": "c", "stage": "2"},      # 70000
    {"title": "Старый вариант", "price": 999, "qty": 1, "opt": "zz"},                                # unknown → common
]
t = plans.totals(ITEMS, VS)
check("common sum", t["common"] == 4999, t)
check("sum per option", t["by_variant"] == {"a": 14999, "b": 40999, "c": 74999}, t)
check("total before choice = cheapest", t["total"] == 14999)
check("total of the chosen option", plans.totals(ITEMS, VS, 0, "c")["total"] == 74999)
check("plan discount on every option", plans.totals(ITEMS, VS, 10, "b")["by_variant"]["b"] == 36899.1)
check("no options: everything", plans.totals(ITEMS, [])["total"] == round(sum(plans.line_sum(i) for i in ITEMS), 2))
check("billable before choice: common only", plans.billable(ITEMS, VS) == [0, 1, 5])
check("billable after choice", plans.billable(ITEMS, VS, "b") == [0, 1, 3, 5])
check("billable without options: all", plans.billable(ITEMS, []) == list(range(6)))

# ---------------------------------------------------------------- migration
old = os.path.join(tempfile.mkdtemp(), "old.db")
c = sqlite3.connect(old)
c.execute("""CREATE TABLE invoices(id TEXT PRIMARY KEY, patient_id TEXT, visit_id TEXT, doctor_id TEXT, items TEXT, total REAL,
             discount REAL DEFAULT 0, status TEXT, comment TEXT, created_at TEXT, transferred INTEGER DEFAULT 0, transferred_at TEXT)""")
c.execute("INSERT INTO invoices(id, patient_id, items, total, status, created_at) VALUES('old1', '1', '[]', 100, 'Не оплачен', '2026-01-01')")
c.commit(); c.close()
od = dbm.DB(old)
cols = {r[1] for r in od.conn.execute("PRAGMA table_info(invoices)")}
check("migration adds option columns", {"variants", "variant", "kind", "plan_id"} <= cols, cols)
check("old invoice survives", od.one("SELECT total FROM invoices WHERE id='old1'")["total"] == 100)
od.conn.close()
check("second start does not fail", dbm.DB(old) is not None)

# ------------------------------------------------------------- the plan itself
d = dbm.DB()
d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}])
d.upsert_patients([{"id": 1, "lname": "Иванова", "fname": "Мария"}, {"id": 2, "lname": "Смирнов", "fname": "Олег"}])
a = Api(d, W())
replica.install(d)
PID = "1"
pid_ok = a.patient(PID)
check("patient found", pid_ok and pid_ok["id"] == PID, pid_ok and pid_ok.get("id"))

plan_id = a.save_invoice({"patient_id": PID, "doctor_id": "1", "kind": "plan", "title": "Лечение 36, 37", "items": json.loads(json.dumps(ITEMS)),
                          "variants": VS + [{"key": "bad key!", "name": ""}]})
row = d.one("SELECT * FROM invoices WHERE id=?", (plan_id,))
check("plan saved as one row", row["kind"] == "plan" and d.one("SELECT COUNT(*) AS n FROM invoices WHERE kind='plan'")["n"] == 1)
check("options stored", [x["key"] for x in json.loads(row["variants"])] == ["a", "b", "c"], row["variants"])
check("no choice yet", row["variant"] is None)
check("plan total = cheapest option (counted once)", row["total"] == 14999, row["total"])
check("status stays preliminary", row["plan_status"] == "Предварительный")
items = json.loads(row["items"])
check("unknown option became common", items[5]["opt"] == "")
check("item sums kept", items[3]["sum"] == 36000)

inv = a.invoice(plan_id)
check("invoice returns options", [x["name"] for x in inv["variants"]] == ["Эконом", "Стандарт", "Премиум"])
check("invoice returns sums per option", inv["totals"]["by_variant"]["c"] == 74999)
check("invoice choice empty", inv["variant"] == "")

refuses("billing an option before the choice", lambda: a.plan_to_invoice(plan_id, [0, 3]), "выбрал пациент")
inv1 = a.plan_to_invoice(plan_id, [0])
b1 = a.invoice(inv1)
check("common item billed before choice", [x["title"] for x in b1["items"]] == ["Осмотр"] and b1["plan_id"] == plan_id)
check("bill items have no option mark", "opt" not in b1["items"][0])
check("plan became active", d.one("SELECT plan_status FROM invoices WHERE id=?", (plan_id,))["plan_status"] == "Активен")

refuses("unknown option", lambda: a.plan_choose(plan_id, "x"), "Такого варианта")
with d.tx() as cx:
    cx.execute("UPDATE invoices SET plan_status='Предварительный' WHERE id=?", (plan_id,))
    cx.execute("DELETE FROM sync_dirty")
p2 = a.plan_choose(plan_id, "b")
check("choice stored", p2["variant"] == "b")
check("choice confirms the plan", p2["plan_status"] == "Подтверждён")
check("total follows the choice", d.one("SELECT total FROM invoices WHERE id=?", (plan_id,))["total"] == 40999)
check("choice goes to the other laptops", d.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='invoices' AND k=?", (json.dumps([plan_id]),)))
check("choice journaled", "plan_choose" in auth.AUDITED and auth.METHOD_PERMS.get("plan_choose") == "billing")
refuses("other option after the choice", lambda: a.plan_to_invoice(plan_id, [2]), "Отметьте")
inv2 = a.plan_to_invoice(plan_id, [2, 3])
check("only the chosen option billed", [x["title"] for x in a.invoice(inv2)["items"]] == ["Вкладка"])
p3 = a.plan_choose(plan_id, "")
check("choice cancelled, treatment status kept", p3["variant"] == "" and p3["plan_status"] == "Активен", p3["plan_status"])
check("total back to cheapest", d.one("SELECT total FROM invoices WHERE id=?", (plan_id,))["total"] == 14999)

# choice made in the editor (save_invoice with variant) also confirms the plan
with d.tx() as cx:
    cx.execute("UPDATE invoices SET plan_status='Предварительный' WHERE id=?", (plan_id,))
cur = a.invoice(plan_id)
a.save_invoice({"id": plan_id, "patient_id": PID, "doctor_id": "1", "kind": "plan", "title": cur["title"], "items": cur["items"],
                "variants": cur["variants"], "variant": "c", "plan_status": "Предварительный"})
r = d.one("SELECT variant, plan_status, total FROM invoices WHERE id=?", (plan_id,))
check("editor choice", r["variant"] == "c" and r["plan_status"] == "Подтверждён" and r["total"] == 74999, dict(r))
a.save_invoice({"id": plan_id, "patient_id": PID, "doctor_id": "1", "kind": "plan", "title": cur["title"], "items": cur["items"],
                "variants": cur["variants"], "variant": "c", "plan_status": "Активен"})
check("status set by hand stays", d.one("SELECT plan_status FROM invoices WHERE id=?", (plan_id,))["plan_status"] == "Активен")
a.save_invoice({"id": plan_id, "patient_id": PID, "doctor_id": "1", "kind": "plan", "title": cur["title"], "items": cur["items"],
                "variants": [], "variant": "c"})
r = d.one("SELECT variants, variant, total FROM invoices WHERE id=?", (plan_id,))
check("options removed: one plan with every item", r["variants"] is None and r["variant"] is None and r["total"] == round(sum(plans.line_sum(i) for i in cur["items"]), 2), dict(r))

p4 = a.save_invoice({"patient_id": PID, "kind": "plan", "items": json.loads(json.dumps(ITEMS)), "variants": VS, "variant": "a"})
check("plan made with a choice is agreed", d.one("SELECT plan_status FROM invoices WHERE id=?", (p4,))["plan_status"] == "Подтверждён")
check("cancelled choice of an agreed plan: preliminary again", a.plan_choose(p4, "")["plan_status"] == "Предварительный")
a.delete_invoice(p4)

# an ordinary invoice is not touched by options
iid = a.save_invoice({"patient_id": PID, "items": [{"title": "Осмотр", "price": 500, "qty": 1, "opt": "a"}], "variants": VS, "variant": "a"})
r = d.one("SELECT kind, variants, total FROM invoices WHERE id=?", (iid,))
check("invoice ignores options", r["kind"] == "invoice" and r["variants"] is None and r["total"] == 500)

# director's analytics count a plan with options once, by the cheapest option
plan2 = a.save_invoice({"patient_id": "2", "kind": "plan", "items": json.loads(json.dumps(ITEMS)), "variants": VS})
dash = a.director_dashboard()
check("director dashboard still works", isinstance(dash, dict))
nplans = d.one("SELECT COUNT(*) AS n, SUM(total) AS s FROM invoices WHERE kind='plan' AND id=?", (plan2,))
check("analytics see one plan at the cheapest sum", nplans["n"] == 1 and nplans["s"] == 14999)

# ------------------------------------------------------------- tablet
code = a.tablet_code("Планшет")["code"]
key = a._tablet_public("pair", [code], "", "127.0.0.1")["key"]
tid = d.one("SELECT id FROM tablets WHERE revoked=0")["id"]
refuses("tablet: plan of another patient", lambda: a.tablet_send(tid, "plan", "1", None, {"plan_id": plan2, "html": "<p>x</p>"}), "План не найден")
refuses("tablet: empty presentation", lambda: a.tablet_send(tid, "plan", "2", None, {"plan_id": plan2, "html": ""}), "Пустая")
sent = a.tablet_send(tid, "plan", "2", None, {"plan_id": plan2, "html": "<div class='pp'>План</div>"})
task = a._tablet_public("task", [], key, "127.0.0.1")["task"]
check("tablet shows the plan", task and task["kind"] == "plan" and "План" in task["html"])
check("tablet gets options with sums", [(x["name"], x["total"]) for x in task["variants"]] == [("Эконом", 14999), ("Стандарт", 40999), ("Премиум", 74999)], task.get("variants"))
check("tablet task has no inner ids", "plan_id" not in task and "patient_id" not in task)
check("tablet: nothing preselected", task.get("chosen") == "")
def sig_png(strokes=True):
    import base64
    import io
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (500, 200), (0, 0, 0, 0))
    if strokes:
        ImageDraw.Draw(im).line([(20, 150), (120, 40), (220, 160), (320, 30), (460, 140)], fill=(0, 0, 0, 255), width=4)
    b = io.BytesIO()
    im.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


PNG = sig_png()
ndocs = d.one("SELECT COUNT(*) AS n FROM documents")["n"]
refuses("tablet: empty signature", lambda: a._tablet_public("submit", [sent["task_id"], {"image": sig_png(False), "variant": "b"}], key, "127.0.0.1"), "пустое")
check("empty signature saves nothing", d.one("SELECT COUNT(*) AS n FROM documents")["n"] == ndocs)
refuses("tablet: option required", lambda: a._tablet_public("submit", [sent["task_id"], {"image": PNG, "variant": ""}], key, "127.0.0.1"), "Выберите вариант")
a._tablet_public("submit", [sent["task_id"], {"image": PNG, "variant": "b"}], key, "127.0.0.1")
st = a.tablet_status(tid, sent["task_id"])
check("tablet task done", st["state"] == "done" and st["result"]["variant"] == "b", st)
doc = d.one("SELECT * FROM documents WHERE id=?", (st["result"]["document_id"],))
check("signed plan saved to the card", doc and doc["patient_id"] == "2" and doc["title"] == "План лечения — Стандарт", doc and doc["title"])
check("document names the choice", "Пациент выбрал вариант: <b>Стандарт</b> — 40 999 ₽" in doc["html"], doc["html"][-120:])
check("document signed by the patient", d.one("SELECT role, place FROM document_signatures WHERE document_id=?", (doc["id"],))["place"].startswith("планшет"))
r = d.one("SELECT variant, plan_status, total FROM invoices WHERE id=?", (plan2,))
check("tablet choice set in the plan", r["variant"] == "b" and r["plan_status"] == "Подтверждён" and r["total"] == 40999, dict(r))
# a plan without options: signing on the tablet confirms it
plan3 = a.save_invoice({"patient_id": "2", "kind": "plan", "items": [{"title": "Осмотр", "price": 800, "qty": 1}]})
s3 = a.tablet_send(tid, "plan", "2", None, {"plan_id": plan3, "html": "<p>План</p>"})
check("no options on the tablet", a._tablet_public("task", [], key, "127.0.0.1")["task"]["variants"] == [])
a._tablet_public("submit", [s3["task_id"], {"image": PNG}], key, "127.0.0.1")
check("signed plan confirmed", d.one("SELECT plan_status FROM invoices WHERE id=?", (plan3,))["plan_status"] == "Подтверждён")

# --------------------------------------------------- tooth formula by surfaces
check("new tooth states", {"Каналы запломбированы", "Штифт", "Промежуточная часть моста"} <= set(catalog.TOOTH_STATUSES))
check("surface cleaning", localm.clean_surf({"36": {"o": "Кариес", "m": "Пломба", "x": "Кариес", "d": "Сломан"}, "3": {"o": "Кариес"},
                                              "47": "Кариес", "11": {"v": ""}}) == {"36": {"o": "Кариес", "m": "Пломба"}, "11": {"v": ""}})
r1 = a.save_record({"patient_id": PID, "doctor_id": "1", "date": "2026-11-01", "teeth": {"36": "Кариес"},
                    "surf": {"36": {"o": "Кариес", "m": "Кариес"}, "21": {"v": "Пломба"}}})
check("record keeps surfaces", a.record(r1)["data"]["surf"]["36"] == {"o": "Кариес", "m": "Кариес"})
a.save_record({"patient_id": PID, "doctor_id": "1", "date": "2026-11-05", "teeth": {"36": "Пломба"},
               "surf": {"36": {"o": "Пломба", "m": ""}}})
p = a.patient(PID)
check("newest surface wins", p["surf_local"]["36"] == {"o": "Пломба"}, p["surf_local"])
check("older surface kept", p["surf_local"]["21"] == {"v": "Пломба"})
check("cleared surface gone", "m" not in p["surf_local"]["36"])
check("tooth state still newest", p["teeth_local"]["36"] == "Пломба")
r3 = a.save_record({"patient_id": PID, "date": "2026-11-06", "teeth": {}, "surf": {}})
check("record without surfaces has no key", "surf" not in a.record(r3)["data"])

# ------------------------------------------------------------- PDF
check("pdf method readable only", "plan_pdf" in auth.METHOD_PERMS and "plan_pdf" not in auth.AUDITED)
refuses("pdf: not text", lambda: a.plan_pdf(None), "большой")
if plans.find_edge():
    out = a.plan_pdf("<!doctype html><html><head><meta charset='utf-8'></head><body><h1>План лечения</h1><p>Проверка</p></body></html>",
                     'План: Иванова / 2026')
    check("pdf made", out["url"].startswith("data:application/pdf;base64,JVBER") and out["size"] > 1000, out.get("size"))
    check("pdf file name safe", out["name"] == "План  Иванова   2026.pdf" or ("/" not in out["name"] and ":" not in out["name"]), out["name"])
else:
    print("(Edge не найден — проверка PDF пропущена)")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
