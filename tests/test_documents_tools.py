"""Version 2.4 documents: signatures, health questionnaire, patient tablet, tax deduction certificate, Excel export."""
import base64
import io
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import tablet as tbm  # noqa: E402
import xlsx  # noqa: E402
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


def raises(fn, *a, exc=ValueError, **k):
    try:
        fn(*a, **k)
    except exc as e:
        return str(e)
    return None


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]
pname = d.patient(pid)["name"]

from PIL import Image, ImageDraw  # noqa: E402


def sig_png(strokes=True):
    im = Image.new("RGBA", (500, 200), (0, 0, 0, 0))
    if strokes:
        ImageDraw.Draw(im).line([(20, 150), (120, 40), (220, 160), (320, 30), (460, 140)], fill=(0, 0, 0, 255), width=4)
    b = io.BytesIO()
    im.save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


SIG = sig_png()

# ================================================================ signatures
did = a._local.save_document({"patient_id": pid, "title": "Согласие на лечение", "html": "<p>Я согласен на лечение.</p>"})
check("empty pad refused", "пустое" in (raises(a.document_sign, did, pname, sig_png(False)) or ""))
check("not a png refused", raises(a.document_sign, did, pname, "data:image/png;base64," + base64.b64encode(b"GIF89a....").decode()) is not None)
check("signer required", raises(a.document_sign, did, "", SIG) is not None)
check("unknown document", raises(a.document_sign, "nope", pname, SIG) is not None)
check("bad role", raises(a.document_sign, did, pname, SIG, "boss") is not None)
auth.set_current_user({"id": 2, "role": "admin", "name": "Админ Ольга"})
s = a.document_sign(did, pname, SIG, "patient")
auth.set_current_user(None)
check("signed", s["signer"] == pname and s["place"] == "screen" and s["image"].startswith("data:image/png") and s["changed"] is False)
check("who took the signature", s["created_by"] == "Админ Ольга")
a.save_document({"id": did, "patient_id": pid, "title": "Согласие на лечение", "html": "<p>Я согласен на лечение и оплату.</p>"})
check("edit after signing is flagged", a.document_signatures(did)[0]["changed"] is True)
a.document_sign(did, "Петрова А. А.", SIG, "representative")
check("two signatures", [x["role"] for x in a.document_signatures(did)] == ["patient", "representative"])
check("card shows signed", next(x for x in a.patient(pid)["documents"] if x["id"] == did)["signed"] is True)

# ================================================================ questionnaire
qs = a.questionnaire_questions()
check("questions", len(qs) == 11 and qs[0]["key"] == "allergy" and qs[0]["extra"])
ans = {q["key"]: {"yes": False} for q in qs}
check("all answers required", "все вопросы" in (raises(a.questionnaire_save, pid, {"allergy": {"yes": True}}, SIG) or ""))
check("signature required", raises(a.questionnaire_save, pid, ans, sig_png(False)) is not None)
ans["allergy"] = {"yes": True, "text": "лидокаин"}
ans["diabetes"] = {"yes": True}
ans["smoking"] = {"yes": True}
ans["heart"] = {"yes": False, "text": "should be dropped"}
r = a.questionnaire_save(pid, ans, SIG)
check("alerts", r["alerts"] == ["Аллергия: лидокаин", "Сахарный диабет"], r["alerts"])
doc = a.document(r["document_id"])
check("saved as a document", "Анкета о состоянии здоровья" in doc["html"] and "лидокаин" in doc["html"])
check("questionnaire document signed", len(a.document_signatures(r["document_id"])) == 1)
check("allergy from the questionnaire is checked", a.allergy_check(pid, "Анестезия лидокаин")["warnings"][0]["level"] == "stop")
check("allergy shown on the visit", "лидокаин" in a._allergies(pid))
lt = a.questionnaire_latest(pid)
check("latest", lt["answers"]["heart"] == {"yes": False, "text": ""} and lt["alerts"] == r["alerts"])
check("card has it", a.patient(pid)["questionnaire"]["id"] == r["id"])

# ================================================================ tablet (Api level)
c = a.tablet_code("Планшет ресепшена")
check("6-digit code", len(c["code"]) == 6 and c["code"].isdigit())
check("wrong code", raises(a._tablet_public, "pair", ["000000" if c["code"] != "000000" else "111111"], "", "10.0.0.5", exc=tbm.TabletError) is not None)
pr = a._tablet_public("pair", [c["code"]], "", "10.0.0.5")
check("paired", pr["name"] == "Планшет ресепшена" and len(pr["key"]) > 30)
check("code works once", raises(a._tablet_public, "pair", [c["code"]], "", "10.0.0.5", exc=tbm.TabletError) is not None)
key = pr["key"]
tid = a.tablets_list()[0]["id"]
check("no task yet", a._tablet_public("task", [], key, "10.0.0.5")["task"] is None)
check("bad key", raises(a._tablet_public, "task", [], "nope", "10.0.0.6", exc=tbm.TabletError) is not None)
did2 = a._local.save_document({"patient_id": pid, "title": "Договор", "html": "<p>Договор на оказание услуг</p>"})
check("document of another patient refused", raises(a.tablet_send, tid, "sign", d.q("SELECT id FROM patients LIMIT 1 OFFSET 1")[0]["id"], did2) is not None)
st = a.tablet_send(tid, "sign", pid, did2)
check("waiting", a.tablet_status(tid, st["task_id"])["state"] == "waiting")
t = a._tablet_public("task", [], key, "10.0.0.5")["task"]
check("tablet sees the document", t["kind"] == "sign" and "Договор" in t["html"] and t["patient"] == pname)
check("no internal ids on the tablet", "document_id" not in t and "patient_id" not in t)
check("opened", a.tablet_status(tid, st["task_id"])["state"] == "opened")
check("empty signature refused on tablet", raises(a._tablet_public, "submit", [t["id"], {"image": sig_png(False)}], key, "10.0.0.5") is not None)
a._tablet_public("submit", [t["id"], {"image": SIG}], key, "10.0.0.5")
check("done", a.tablet_status(tid, st["task_id"])["state"] == "done")
sg = a.document_signatures(did2)
check("signed on the tablet", len(sg) == 1 and sg[0]["place"] == "планшет «Планшет ресепшена»" and sg[0]["ip"] == "10.0.0.5")
check("task closed after submit", a._tablet_public("task", [], key, "10.0.0.5")["task"] is None)
check("second submit refused", raises(a._tablet_public, "submit", [t["id"], {"image": SIG}], key, "10.0.0.5") is not None)
st2 = a.tablet_send(tid, "anketa", pid)
t2 = a._tablet_public("task", [], key, "10.0.0.5")["task"]
check("questionnaire on the tablet", t2["kind"] == "anketa" and len(t2["questions"]) == 11)
ans2 = {q["key"]: {"yes": False} for q in qs}
a._tablet_public("submit", [t2["id"], {"image": SIG, "answers": ans2}], key, "10.0.0.5")
res = a.tablet_status(tid, st2["task_id"])
check("questionnaire done", res["state"] == "done" and res["result"]["alerts"] == [] and res["result"]["document_id"])
st3 = a.tablet_send(tid, "anketa", pid)
a.tablet_cancel(tid, st3["task_id"])
check("cancelled", a.tablet_status(tid, st3["task_id"])["state"] == "cancelled" and a._tablet_public("task", [], key, "1")["task"] is None)
st4 = a.tablet_send(tid, "anketa", pid)
a._tablets._tasks[tid]["expires"] = time.time() - 1
check("expired", a.tablet_status(tid, st4["task_id"])["state"] == "expired")
check("unknown task kind", raises(a.tablet_send, tid, "pay", pid) is not None)
# throttle: many wrong keys from one address
ip = "10.9.9.9"
for _ in range(tbm.MAX_FAILS):
    raises(a._tablet_public, "task", [], "bad", ip, exc=tbm.TabletError)
check("throttled", "попыток" in (raises(a._tablet_public, "task", [], key, ip, exc=tbm.TabletError) or ""))
a.tablet_revoke(tid)
check("revoked tablet locked out", raises(a._tablet_public, "task", [], key, "10.0.0.7", exc=tbm.TabletError) is not None and a.tablets_list() == [])

# ================================================================ tablet over HTTP
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); PORT = s_.getsockname()[1]; s_.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def http(path, args=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", data=json.dumps(args or []).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


try:
    urllib.request.build_opener(NoRedirect).open(f"http://127.0.0.1:{PORT}/t", timeout=5)
    loc = None
except urllib.error.HTTPError as e:
    loc = e.headers.get("Location")
check("short address /t", loc == "/tablet.html", loc)
with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/tablet.html", timeout=5) as r:
    check("tablet page served", "Планшет пациента" in r.read().decode())
code = a.tablet_code("Планшет 2")["code"]
st_, j = http("/tablet/pair", [code])
check("pair over HTTP", st_ == 200 and j["key"])
st_, j2 = http("/tablet/task", [], {"X-Tablet-Key": j["key"]})
check("task over HTTP", st_ == 200 and j2["task"] is None and j2["tablet"] == "Планшет 2")
st_, j3 = http("/tablet/task", [], {"X-Tablet-Key": "wrong"})
check("wrong key is 403", st_ == 403 and j3.get("tablet") is True)
st_, j4 = http("/api/tablet_send", [a.tablets_list()[0]["id"], "anketa", pid])
check("staff methods still need a login", st_ == 401)
st_, j5 = http("/api/_tablet_public", ["task", [], j["key"], "x"])
check("private entry point closed on /api", st_ == 404)
srv.stop()

# ================================================================ tax certificate
check("requisites required", "Реквизиты" in (raises(a.taxcert_issue, {"patient_id": pid, "year": date.today().year, "sum1": 100}) or ""))
a.save_clinic({"name": "ООО «Улыбка»", "inn": "7700000000", "kpp": "770001001", "address": "г. Москва"})
yr = date.today().year
with d.tx() as cx:
    cx.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at) VALUES('P1','I1',?,1500.5,'Наличные','',?)", (pid, f"{yr}-02-03 10:00:00"))
    cx.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at) VALUES('P2','I1',?,2000,'Карта','',?)", (pid, f"{yr}-05-03 10:00:00"))
    cx.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at) VALUES('P3','I1',?,999,'Карта','',?)", (pid, f"{yr - 1}-05-03 10:00:00"))
dd = a.taxcert_data(pid, yr)
check("payments of the year", dd["total"] == 3500.5 and len(dd["payments"]) == 2)
base = {"patient_id": pid, "year": yr, "sum1": "3 500,50", "sum2": "0", "patient_inn": "", "patient_birth": "1990-01-01", "patient_doc": ""}
check("INN or passport required", "ИНН" in (raises(a.taxcert_issue, base) or ""))
check("INN is 12 digits", "12 цифр" in (raises(a.taxcert_issue, {**base, "patient_inn": "123"}) or ""))
check("zero sum refused", raises(a.taxcert_issue, {**base, "patient_inn": "123456789012", "sum1": 0}) is not None)
check("future year refused", raises(a.taxcert_issue, {**base, "patient_inn": "123456789012", "year": yr + 1}) is not None)
check("payer needed when not the patient", raises(a.taxcert_issue, {**base, "patient_inn": "123456789012", "payer_same": False}) is not None)
c1 = a.taxcert_issue({**base, "patient_inn": "123456789012", "responsible": "Администратор Ольга"})
check("issued", c1["number"] == 1 and c1["sum1"] == 3500.5 and "3 500 руб. 50 коп." in c1["html"] and "770001001" in c1["html"])
check("one person line", "Налогоплательщик и пациент являются одним лицом" in c1["html"])
c2 = a.taxcert_issue({**base, "payer_same": False, "payer_fio": "Иванова Мария Петровна", "payer_inn": "", "payer_birth": "1965-04-04",
                      "payer_doc": "паспорт 4510 123456 от 01.02.2010", "patient_inn": "123456789012", "sum1": 1000, "sum2": 25000})
check("numbering", c2["number"] == 2 and "Иванова Мария Петровна" in c2["html"] and "паспорт 4510" in c2["html"])
check("certificate in the card", any(x["title"].startswith("Справка для налогового вычета № 2") for x in a.patient(pid)["documents"]))
check("issued listed for the year", len(a.taxcert_data(pid, yr)["issued"]) == 2)
reg = a.taxcert_list(yr)
check("register", len(reg["rows"]) == 2 and reg["total1"] == 4500.5 and reg["total2"] == 25000)
c3 = a.taxcert_issue({**base, "year": yr - 1, "patient_inn": "123456789012", "sum1": 999})
check("numbering restarts per year", c3["number"] == 1)

# ================================================================ Excel
x = a.export_xlsx("Выручка: по врачам", ["Врач", "Сумма", "Телефон"], [["Петров", "12 500 ₽", "89491112233"], ["Иванова", "1 200,50 ₽", "+7 949 1"]])
check("xlsx name", x["name"].startswith("Выручка  по врачам") and x["name"].endswith(".xlsx"), x["name"])
raw = base64.b64decode(x["url"].split(",", 1)[1])
z = zipfile.ZipFile(io.BytesIO(raw))
sheet = z.read("xl/worksheets/sheet1.xml").decode()
check("xlsx parts", {"[Content_Types].xml", "xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/styles.xml"} <= set(z.namelist()))
check("numbers are numbers", "<v>12500</v>" in sheet and "<v>1200.5</v>" in sheet)
check("phones stay text", "89491112233</t>" in sheet)
check("header bold style", 'r="A1" t="inlineStr" s="1"' in sheet)
check("escaping", "&lt;" in xlsx.build("t", ["<a>"], [])[0:0].decode() or "&lt;a&gt;" in zipfile.ZipFile(io.BytesIO(xlsx.build("t", ["<a>"], []))).read("xl/worksheets/sheet1.xml").decode())

# ================================================================ permissions
for m in ("document_signatures", "document_sign", "questionnaire_questions", "questionnaire_save", "questionnaire_latest", "tablet_code",
          "tablets_list", "tablet_revoke", "tablet_send", "tablet_status", "tablet_cancel", "taxcert_data", "taxcert_issue", "taxcert_list", "export_xlsx"):
    check(f"perm {m}", m in auth.METHOD_PERMS)
for m in ("document_sign", "questionnaire_save", "tablet_code", "tablet_revoke", "tablet_send", "taxcert_issue"):
    check(f"audited {m}", m in auth.AUDITED)
check("pairing only with settings rights", auth.METHOD_PERMS["tablet_code"] == "settings")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
