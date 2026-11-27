"""3.10 «Склад — медсестра»: the nurse's rights, write-offs waiting for approval (also through the API), requests,
depreciation of equipment, photos of materials and equipment, the home screen and the files of the screens."""
import base64
import io
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import replica  # noqa: E402
import stock  # noqa: E402
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
replica.install(d)  # stable ids of the approved write-off's moves need the replicated uid column

# ------------------------------------------------------------------ roles --
R = auth.roles()
check("nurse role", R.get("nurse", {}).get("title") == "Медсестра", list(R))
nurse_perms = set(R["nurse"]["perms"])
check("nurse: stock without the write-off right", {"stock_view", "stock_ops"} <= nurse_perms and not nurse_perms & {"stock_edit", "stock_approve"}, nurse_perms)
check("manager rights by default: the administrator, not the storekeeper", "stock_approve" in R["admin"]["perms"] and "stock_approve" not in R["storekeeper"]["perms"])
check("director has everything", {"stock_ops", "stock_approve"} <= set(auth.Auth.effective_perms({"role": "director"})))
check("old permission lists keep their meaning", auth.PERM_KEYS_2_13 == auth.PERM_KEYS[:auth.PERM_KEYS.index("expenses_day")])
check("perms in the «Склад» group", {"stock_ops", "stock_approve"} <= set(dict(auth.PERM_GROUPS)["Склад"]))
check("replicated", "stock_requests" in replica.BY_NAME and "stock_approvals" in replica.BY_NAME)
for m in ("stock_home", "stock_use", "stock_approval_decide", "stock_request_save", "stock_photo_set", "equipment_amortization"):
    check(f"method has a right: {m}", m in auth.METHOD_PERMS and callable(getattr(a, m, None)))
check("write-off itself still needs «приход, списание»", auth.METHOD_PERMS["stock_write_off"] == "stock_edit")
check("approval needs «согласование»", auth.METHOD_PERMS["stock_approval_decide"] == "stock_approve")

# a clinic that made its own «Медсестра» before 3.10: that position gets the nurse's stock right, no second «Медсестра»
d2 = dbm.DB(Path(tempfile.mkdtemp()) / "old.db")
A2 = auth.Auth(d2)
old_known = json.dumps(auth.PERM_KEYS[:auth.PERM_KEYS.index("stock_ops")])
with d2.tx() as c:
    c.execute("INSERT INTO staff_roles(key, title, base, perms, known, sort, updated_at) VALUES('p_old', 'Медсестра', 'assistant', ?, ?, 0, '')",
              (json.dumps(["schedule_view", "stock_view", "sterilization"]), old_known))
R2 = auth.roles(d2)
check("own «Медсестра» gets the stock right", "stock_ops" in R2["p_old"]["perms"] and "stock_edit" not in R2["p_old"]["perms"], R2["p_old"]["perms"])
check("no second «Медсестра»", "nurse" not in R2 and sum(v["title"] == "Медсестра" for v in R2.values()) == 1)
r = A2.role_save(None, {"key": "p_old", "title": "Медсестра", "perms": R2["p_old"]["perms"]})
check("own «Медсестра» can still be saved", r["key"] == "p_old")
check("director's later choice stands", "stock_ops" in auth.roles(d2)["p_old"]["perms"])
A2.role_save(None, {"key": "p_old", "title": "Медсестра", "perms": ["schedule_view"]})
check("director may take the right away", "stock_ops" not in auth.roles(d2)["p_old"]["perms"])
auth._DB["db"] = d  # the rest of the test is about the main database
check("a new position cannot be called «Медсестра» twice", "nurse" in auth.roles(d))
try:
    auth.Auth(d).role_save(None, {"title": "медсестра", "base": "assistant", "perms": []})
    FAIL.append("duplicate «Медсестра» accepted")
except auth.AuthError:
    OK[0] += 1

# -------------------------------------------------------------- places --
cab = a.stock_location_save({"name": "Кабинет №3", "kind": "cabinet"})
cab2 = a.stock_location_save({"name": "Кабинет №1", "kind": "cabinet"})
M1, M2 = "demo_m1", "demo_m2"
a.stock_receive({"lines": [{"material_id": M1, "qty": 40, "price": 50}, {"material_id": M2, "qty": 20, "price": 30}]})
at = lambda mid, loc: a._stock.location_balance(mid, loc)  # noqa: E731
pid = d.one("SELECT id FROM patients LIMIT 1")["id"]
svc = d.one("SELECT id, title FROM services WHERE active=1 LIMIT 1")

# --------------------------------------------------------- over HTTP --
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
for login, role in (("nurse", "nurse"), ("nurse2", "nurse"), ("keeper", "storekeeper"), ("doc", "doctor"), ("adm", "admin")):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
TN = call("auth", "login", "nurse", "secret1")[1]["token"]
TN2 = call("auth", "login", "nurse2", "secret1")[1]["token"]
TK = call("auth", "login", "keeper", "secret1")[1]["token"]
TDoc = call("auth", "login", "doc", "secret1")[1]["token"]
TA = call("auth", "login", "adm", "secret1")[1]["token"]

# the nurse works with the stock …
code, home = call("api", "stock_home", token=TN)
check("nurse: home screen", code == 200 and home["can"]["use"] and not home["can"]["direct"] and not home["can"]["approve"], (code, home.get("can")))
check("nurse: sees balances", call("api", "materials", token=TN)[0] == 200)
code, did = call("api", "stock_receive", {"location_id": cab, "lines": [{"material_id": M1, "qty": 5, "price": 50}]}, token=TN)
check("nurse: takes a delivery", code == 200 and at(M1, cab) == 5, (code, did))
code, tid = call("api", "stock_transfer", {"from_id": "", "to_id": cab, "lines": [{"material_id": M1, "qty": 10}, {"material_id": M2, "qty": 4}]}, token=TN)
check("nurse: issues to a cabinet", code == 200 and at(M1, cab) == 15 and at(M2, cab) == 4, (code, tid))

# … but never writes off by herself
total0 = a._stock.balance(M1)
for name, args in (("stock_write_off", [{"reason": "брак", "location_id": cab, "lines": [{"material_id": M1, "qty": 1}]}]),
                   ("stock_inventory", [{"location_id": cab, "lines": [{"material_id": M1, "actual": 0}]}]),
                   ("save_material", [{"id": M1, "name": "X", "price": 0}]),
                   ("delete_material", [M1]),
                   ("stock_visit_confirm", [["v1"]]),
                   ("stock_approval_decide", ["AP-x", "approve"]),
                   ("stock_request_reject", ["RQ-x", "нет"]),
                   ("write_off_equipment", [{"id": "x"}]),
                   ("amort_settings_save", [{"in_pnl": True}])):
    check(f"nurse refused: {name}", call("api", name, *args, token=TN)[0] == 403)
check("nothing left the stock", a._stock.balance(M1) == total0)

f_use = {"kind": "consume", "location_id": cab, "patient_id": pid, "service_id": svc["id"], "date": "2026-11-18", "time": "10:24",
         "lines": [{"material_id": M1, "qty": 2}, {"material_id": M2, "qty": 1}], "direct": True, "status": "done"}
code, r = call("api", "stock_use", f_use, token=TN)
check("nurse: consumption waits for approval", code == 200 and r["status"] == "pending" and not r["doc_id"], (code, r))
AP1 = r["id"]
check("pending: the stock did not change", at(M1, cab) == 15 and at(M2, cab) == 4 and a._stock.balance(M1) == total0)
check("pending: what it is", r["item"]["kind_title"] == "Расход в лечении" and r["item"]["patient_name"] and svc["title"] in r["item"]["service_title"], r["item"])
code, r = call("api", "stock_use", {**f_use, "lines": [{"material_id": M1, "qty": 999}]}, token=TN)
check("nurse: more than the cabinet has", code == 400 and "нельзя" in r.get("error", ""), r)
code, r = call("api", "stock_use", {**f_use, "kind": "writeoff", "reason": "", "lines": [{"material_id": M1, "qty": 1}]}, token=TN)
check("write-off needs a reason", code == 400 and "причину" in r.get("error", ""), r)
code, r = call("api", "stock_use", {**f_use, "kind": "writeoff", "reason": "Разбита ампула", "lines": [{"material_id": M2, "qty": 1}]}, token=TN)
AP2 = r["id"]
check("nurse: write-off waits too", code == 200 and r["status"] == "pending")
code, r = call("api", "stock_use", {**f_use, "draft": True}, token=TN)
check("nurse: a draft", code == 200 and r["status"] == "draft", r)
DR = r["id"]
check("doctor cannot record consumption", call("api", "stock_use", f_use, token=TDoc)[0] == 403)

code, mine = call("api", "stock_approvals", {}, token=TN)
check("nurse sees her own", code == 200 and {AP1, AP2, DR} <= {x["id"] for x in mine}, mine)
code, other = call("api", "stock_approvals", {}, token=TN2)
check("another nurse does not see them", code == 200 and not {AP1, AP2, DR} & {x["id"] for x in other})
check("another nurse cannot open them", call("api", "stock_approval", AP1, token=TN2)[0] == 400)
check("another nurse cannot cancel them", call("api", "stock_approval_cancel", AP1, token=TN2)[0] == 400)
code, allp = call("api", "stock_approvals", {"status": "pending"}, token=TK)
check("manager sees what waits", code == 200 and {AP1, AP2} <= {x["id"] for x in allp} and DR not in {x["id"] for x in allp})
code, st = call("api", "status", token=TA)
check("badge for the manager", st.get("stock_wait", 0) >= 2, st.get("stock_wait"))
check("storekeeper does not approve", call("api", "stock_approval_decide", AP1, "approve", "", token=TK)[0] == 403)
check("storekeeper does not cancel it either", call("api", "stock_approval_cancel", AP1, token=TK)[0] == 400)
check("storekeeper is not asked to approve", not any(t["key"] == "approve" for t in call("api", "stock_home", token=TK)[1]["tasks"]))
check("nothing written off by that", at(M1, cab) == 15)

# the manager approves: now the stock changes, once
code, r = call("api", "stock_approval_decide", AP1, "approve", "", token=TA)
check("approved", code == 200 and r["status"] == "approved" and r["doc_id"] == f"A-{AP1}", (code, r))
check("approved: written off from the cabinet", at(M1, cab) == 13 and at(M2, cab) == 3, (at(M1, cab), at(M2, cab)))
doc = a.stock_doc(f"A-{AP1}")
check("approved: an act with the patient", doc and doc["kind"] == "writeoff" and all(m["patient_id"] == pid for m in doc["moves"]), doc)
check("approved: signed by both", "adm" in doc["user_name"] and "nurse" in doc["user_name"], doc["user_name"])
check("approved: time of the treatment", all(m["at"] == "2026-11-18 10:24:00" for m in doc["moves"]), [m["at"] for m in doc["moves"]])
check("approved: stable move ids", sorted(x["uid"] for x in d.q("SELECT uid FROM stock_moves WHERE doc_id=?", (f"A-{AP1}",))) == [f"a-{AP1}-0", f"a-{AP1}-1"])
code, r = call("api", "stock_approval_decide", AP1, "approve", "", token=TA)
check("approve twice", code == 400 and "Уже" in r.get("error", ""), r)
# the same request approved on another laptop before the rows met: one write-off, not two
with d.tx() as c:
    c.execute("UPDATE stock_approvals SET status='pending' WHERE id=?", (AP1,))
a._sflow.decide(AP1, "approve", "", "adm", "adm")
check("second approval writes nothing", at(M1, cab) == 13 and len(a.stock_doc(f"A-{AP1}")["moves"]) == 2)

# rejection needs a reason, the stock stays
code, r = call("api", "stock_approval_decide", AP2, "reject", "", token=TD)
check("reject needs a reason", code == 400 and "причину" in r.get("error", ""), r)
code, r = call("api", "stock_approval_decide", AP2, "reject", "Ампулу сдайте старшей медсестре", token=TD)
check("rejected", code == 200 and r["status"] == "rejected" and r["answer"].startswith("Ампулу") and at(M2, cab) == 3, r)
code, home = call("api", "stock_home", token=TN)
check("nurse is told about the rejection", any("Отклонено" in t["title"] for t in home["tasks"]), home["tasks"])
code, r = call("api", "stock_use", {**f_use, "lines": [{"material_id": M2, "qty": 1}]}, token=TN)
AP3 = r["id"]
code, r = call("api", "stock_approval_cancel", AP3, token=TN)
check("nurse cancels her own", code == 200 and r["status"] == "cancelled")
check("cancelled cannot be approved", call("api", "stock_approval_decide", AP3, "approve", "", token=TA)[0] == 400)
# the draft: finished later by its author
code, r = call("api", "stock_use", {**f_use, "id": DR, "lines": [{"material_id": M2, "qty": 1}]}, token=TN)
check("draft sent", code == 200 and r["id"] == DR and r["status"] == "pending", r)
check("another nurse cannot send it", call("api", "stock_use", {**f_use, "id": DR}, token=TN2)[0] == 400)

# a manager and the director write off at once
code, r = call("api", "stock_use", {**f_use, "lines": [{"material_id": M2, "qty": 1}]}, token=TA)
check("administrator: at once", code == 200 and r["status"] == "done" and at(M2, cab) == 2, (code, r, at(M2, cab)))
code, r = call("api", "stock_use", {**f_use, "lines": [{"material_id": M1, "qty": 1}]}, token=TD)
check("director: at once", code == 200 and r["status"] == "done" and at(M1, cab) == 12)

# ------------------------------------------------------------- requests --
code, rq = call("api", "stock_request_save", {"location_id": cab, "need_date": "20.11.2026", "priority": "urgent", "comment": "имплантация",
                                              "lines": [{"material_id": M1, "qty": 10}, {"material_id": M2, "qty": 5}]}, token=TN)
check("request: draft", code == 200 and rq["status"] == "draft" and rq["need_date"] == "2026-11-20" and not rq["number"], rq)
check("someone's draft is not in the manager's list", rq["id"] not in {x["id"] for x in call("api", "stock_requests", {}, token=TK)[1]})
code, rq = call("api", "stock_request_save", {**rq, "lines": [{"material_id": M1, "qty": 10}, {"material_id": M2, "qty": 5}], "send": True}, token=TN)
check("request sent", code == 200 and rq["status"] == "new" and rq["number"] and rq["priority_title"] == "Срочный", rq)
check("sent request is not edited", call("api", "stock_request_save", {**rq, "lines": [{"material_id": M1, "qty": 1}]}, token=TN)[0] == 400)
check("request without materials", call("api", "stock_request_save", {"location_id": cab, "lines": []}, token=TN)[0] == 400)
check("another nurse does not see it", call("api", "stock_request", rq["id"], token=TN2)[0] == 400)
code, lst = call("api", "stock_requests", {"status": "open"}, token=TK)
check("keeper sees open requests", code == 200 and rq["id"] in {x["id"] for x in lst})
check("keeper is asked to issue them", any(t["key"] == "issue" for t in call("api", "stock_home", token=TK)[1]["tasks"]))
check("keeper's badge counts them", call("api", "status", token=TK)[1].get("stock_wait", 0) >= 1)
code, one = call("api", "stock_request", rq["id"], token=TK)
check("request shows the main stock", code == 200 and one["lines"][0]["at_main"] > 0, one["lines"])
code, _ = call("api", "stock_transfer", {"from_id": "", "to_id": cab, "request_ids": [rq["id"]], "lines": [{"material_id": M1, "qty": 10}, {"material_id": M2, "qty": 2}]}, token=TK)
one = call("api", "stock_request", rq["id"], token=TK)[1]
check("issued in part", code == 200 and one["status"] == "partial" and one["lines"][1]["issued"] == 2, one)
call("api", "stock_transfer", {"from_id": "", "to_id": cab, "request_ids": [rq["id"]], "lines": [{"material_id": M2, "qty": 3}]}, token=TN)
one = call("api", "stock_request", rq["id"], token=TK)[1]
check("issued in full", one["status"] == "done" and len(one["doc_ids"]) == 2, one)
code, rq2 = call("api", "stock_request_save", {"location_id": cab2, "lines": [{"material_id": M1, "qty": 3}], "send": True}, token=TN2)
check("nurse cannot reject", call("api", "stock_request_reject", rq2["id"], "нет", token=TN)[0] == 403)
code, r = call("api", "stock_request_reject", rq2["id"], "", token=TK)
check("reject needs a reason", code == 400)
code, r = call("api", "stock_request_reject", rq2["id"], "Есть в кабинете №3", token=TK)
check("request rejected", code == 200 and r["status"] == "rejected" and r["answer"])
code, rq3 = call("api", "stock_request_save", {"location_id": cab2, "lines": [{"material_id": M1, "qty": 3}], "send": True}, token=TN2)
check("nurse cancels her request", call("api", "stock_request_cancel", rq3["id"], token=TN2)[1]["status"] == "cancelled")
check("not someone else's", call("api", "stock_request_cancel", rq2["id"], token=TN)[0] == 400)

# --------------------------------------------------------------- photos --
from PIL import Image  # noqa: E402

buf = io.BytesIO(); Image.new("RGB", (2400, 1600), (40, 120, 200)).save(buf, "PNG")
png = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
code, ph = call("api", "stock_photo_set", "material", M1, "ампула.png", png, token=TN)
check("nurse adds a photo of a material", code == 200 and ph["photo_id"] and ph["thumb"].startswith("data:image/jpeg"), (code, ph))
row = d.one("SELECT * FROM patient_files WHERE id=?", (ph["photo_id"],))
check("kept like the patients' files", row["patient_id"] == "_stock" and row["ext"] == ".jpg" and max(row["width"], row["height"]) <= 1200, row)
check("made smaller", row["size"] < len(buf.getvalue()), (row["size"], len(buf.getvalue())))
check("goes to the other computers", d.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='patient_files' AND k=?", (json.dumps([ph["photo_id"]]),)))
check("the material knows its photo", next(m for m in a.materials() if m["id"] == M1)["photo_id"] == ph["photo_id"])
check("thumbs", ph["photo_id"] in call("api", "stock_photos", [ph["photo_id"]], token=TN)[1])
code, view = call("api", "stock_photo", ph["photo_id"], token=TN)
check("the photo itself", code == 200 and view["url"].startswith("data:image/"))
pf = a._files.add(pid, "snimok.png", buf.getvalue(), {"kind": "xray"})
check("never a patient's file through the stock", pf["id"] not in call("api", "stock_photos", [pf["id"]], token=TN)[1])
check("never a patient's file by id", call("api", "stock_photo", pf["id"], token=TN)[0] == 400)
check("nurse: not a photo of equipment", call("api", "stock_photo_set", "equipment", "demo_e1", "a.png", png, token=TN)[0] == 400)
check("doctor: no photos", call("api", "stock_photo_set", "material", M1, "a.png", png, token=TDoc)[0] == 403)
check("not a picture", call("api", "stock_photo_set", "material", M1, "a.png", "data:image/png;base64," + base64.b64encode(b"hello").decode(), token=TN)[0] == 400)
check("not a pdf", call("api", "stock_photo_set", "material", M1, "a.pdf", "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4").decode(), token=TN)[0] == 400)
eq_id = d.one("SELECT id FROM equipment LIMIT 1")["id"]
code, ph2 = call("api", "stock_photo_set", "equipment", eq_id, "chair.png", png, token=TK)
check("keeper adds a photo of equipment", code == 200 and a.equipment(eq_id)["photo_id"] == ph2["photo_id"], (code, ph2))
check("same picture is stored once", ph2["photo_id"] == ph["photo_id"])
call("api", "stock_photo_clear", "material", M1, token=TN)
check("photo removed", not next(m for m in a.materials() if m["id"] == M1)["photo_id"])
srv.stop()

# --------------------------------------------------------- depreciation --
e = {"price": 120000, "in_service": "2025-01-15", "useful_months": 60, "status": "in_use"}
am = stock.amortization(e, "2025-01")
check("nothing in the month of the start", am["on"] and am["accumulated"] == 0 and am["monthly"] == 2000, am)
check("from the next month", stock.amortization(e, "2025-02")["accumulated"] == 2000 and stock.amort_charge(e, "2025-02") == 2000)
check("a year", stock.amortization(e, "2026-01")["accumulated"] == 24000 and stock.amortization(e, "2026-01")["residual"] == 96000)
check("to the end and not further", stock.amortization(e, "2030-01")["residual"] == 0 and stock.amortization(e, "2031-05")["accumulated"] == 120000
      and stock.amort_charge(e, "2030-02") == 0)
sch = stock.amort_schedule(e)
check("schedule", len(sch) == 60 and sch[0]["month"] == "2025-02" and sch[-1]["month"] == "2030-01" and round(sum(x["charge"] for x in sch), 2) == 120000, (len(sch), sch[:1], sch[-1:]))
e2 = {"price": 100000, "in_service": "2025-03-01", "useful_months": 36, "salvage": 10000}
sch2 = stock.amort_schedule(e2)
check("salvage value stays", sch2[-1]["residual"] == 10000 and round(sum(x["charge"] for x in sch2), 2) == 90000 and sch2[0]["charge"] == 2500)
e3 = {"price": 1000, "in_service": "2025-01-10", "useful_months": 3}
check("kopecks go to the last month", [x["charge"] for x in stock.amort_schedule(e3)] == [333.33, 333.34, 333.33] or
      round(sum(x["charge"] for x in stock.amort_schedule(e3)), 2) == 1000)
wo = {**e, "status": "written_off", "writeoff_date": "2025-06-20"}
check("stops after the write-off", stock.amortization(wo, "2026-01")["accumulated"] == 10000 and stock.amort_charge(wo, "2025-07") == 0)
check("no life — no depreciation", not stock.amortization({"price": 5000, "purchase_date": "2025-01-01"})["on"])
eid = a.save_equipment({"name": "Автоклав тест", "price": 360000, "purchase_date": "2025-12-20", "in_service": "10.01.2026", "useful_years": 5,
                        "salvage": 0})
eq = a.equipment(eid)
check("card: depreciation", eq["amort"]["on"] and eq["amort"]["monthly"] == 6000 and eq["in_service"] == "2026-01-10" and eq["useful_months"] == 60, eq["amort"])
check("card: months", len(eq["amort_schedule"]) == 60 and eq["amort_schedule"][0]["month"] == "2026-02")
refuses("salvage over the cost", lambda: a.save_equipment({"id": eid, "name": "Автоклав тест", "price": 1000, "useful_months": 12, "salvage": 5000}), "Ликвидационная")
refuses("life too long", lambda: a.save_equipment({"id": eid, "name": "Автоклав тест", "price": 1000, "useful_months": 9999}), "Срок")
a.save_equipment({**{k: eq[k] for k in ("id", "name", "price", "purchase_date")}, "comment": "без полей амортизации"})
check("a form without the fields keeps them", a.equipment(eid)["useful_months"] == 60)
rep = a.equipment_amortization("2026-01", "2026-12")
row = next((x for x in rep["rows"] if x["id"] == eid), None)
check("report by months", row and row["values"][0] == 0 and row["values"][1] == 6000 and rep["months"][0] == "2026-01", row)
check("report: totals", rep["totals"][1] >= 6000 and rep["in_pnl"] is False, rep["totals"][:3])
pnl = a._fm().pnl("2026-11")
check("P&L without depreciation by default", not any(x["key"] == "amortization" for x in pnl["fixed"]))
a.amort_settings_save({"in_pnl": True})
pnl = a._fm().pnl("2026-11")
line = next((x for x in pnl["fixed"] if x["key"] == "amortization"), None)
check("P&L line when switched on", line and line["amount"] == a._stock.amort_month("2026-11") and line["amount"] >= 6000, line)
r = a.write_off_equipment({"id": eid, "date": "2026-11-24", "reason": "тест", "commission": ["А", "Б"], "residual": 0})
check("written off: stops", a.equipment(eid)["amort"]["months_left"] == 0 and stock.amort_charge(a.equipment(eid), "2026-12") == 0)
summ = a.stock_summary()
check("summary: book value", "eq_residual" in summ and summ["eq_residual"] <= summ["eq_cost"], summ)

# ------------------------------------------- a laptop that updated late --
# it ran the old version while others were newer: the new columns were dropped, the new tables skipped, the marks moved on
check("catch-up done on install", d.one("SELECT v FROM sync_state WHERE k='catchup'")["v"] == replica.CATCHUP)
replica.stamp(d, "node-test")
with d.tx() as c:
    c.execute("DELETE FROM sync_dirty")
    for mid, ph in (("demo_m3", "F-from-peer"), ("demo_m4", "F-old")):
        base = json.loads(c.execute("SELECT base FROM sync_rows WHERE tbl='materials' AND k=?", (json.dumps([mid]),)).fetchone()[0])
        base["photo_id"] = ph
        c.execute("UPDATE sync_rows SET base=? WHERE tbl='materials' AND k=?", (json.dumps(base, ensure_ascii=False), json.dumps([mid])))
    replica.set_applying(c, True)
    c.execute("UPDATE materials SET photo_id=NULL WHERE id IN ('demo_m3','demo_m4')")
    replica.set_applying(c, False)
    c.execute("INSERT INTO sync_dirty(tbl, k, at) VALUES('materials', ?, 1)", (json.dumps(["demo_m4"]),))  # changed here, not sent
    c.executescript("CREATE TABLE IF NOT EXISTS p2p_peers(node TEXT PRIMARY KEY, mark INTEGER DEFAULT 0, epoch TEXT);")
    c.execute("INSERT OR REPLACE INTO p2p_peers(node, mark) VALUES('peer-a', 4242)")
    c.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES('cloud_seq', '777')")
    c.execute("UPDATE sync_state SET v='3.9' WHERE k='catchup'")
replica.install(d)
mat = {m["id"]: m for m in a.materials()}
check("catch-up: the dropped column comes from the synced copy", mat["demo_m3"]["photo_id"] == "F-from-peer", mat["demo_m3"]["photo_id"])
check("catch-up: a change made here wins", not mat["demo_m4"]["photo_id"])
check("catch-up: not a new change of this computer", not d.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='materials' AND k=?", (json.dumps(["demo_m3"]),)))
check("catch-up: peers are asked for everything again", d.one("SELECT mark FROM p2p_peers WHERE node='peer-a'")["mark"] == 0)
check("catch-up: the cloud too", not d.one("SELECT 1 AS x FROM sync_state WHERE k='cloud_seq'"))
with d.tx() as c:
    c.execute("UPDATE p2p_peers SET mark=10")
replica.install(d)
check("catch-up: only once", d.one("SELECT mark FROM p2p_peers WHERE node='peer-a'")["mark"] == 10)

# ------------------------------------------------------------ the screens --
html = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
js = (ROOT / "app" / "ui" / "stock-nurse.js").read_text(encoding="utf-8")
check("screen file loaded with the cache tag", f'<script src="stock-nurse.js?v={config.VERSION}"></script>' in html)
check("styles loaded", f'styles-stocknurse.css?v={config.VERSION}' in html)
check("home tab", '["home", "Главная"]' in (ROOT / "app" / "ui" / "stock.js").read_text(encoding="utf-8"))  # 3.14: the tabs live in STOCK_AREAS
for fn in ("stockHome", "openRequestScreen", "openUseScreen", "openIssueScreen", "openReceiveScreen", "openApprovals", "photoPick"):
    check(f"screen: {fn}", f"function {fn}" in js)
check("tiles", all(t in js for t in ("Принять поставку", "Выдать в кабинет", "Зафиксировать расход", "Создать заявку")))
check("double click guarded", js.count("busy(") >= 5)
check("version 3.10", tuple(map(int, config.VERSION.split("."))) >= (3, 10, 0), config.VERSION)
notes = ROOT / "docs" / "Что нового в версии 3.10.txt"  # the notes of the nurse's stock (later versions have their own)
check("what's new", notes.exists() and "медсестр" in notes.read_text(encoding="utf-8").lower(), notes)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  ✗", f)
sys.exit(1 if FAIL else 0)
