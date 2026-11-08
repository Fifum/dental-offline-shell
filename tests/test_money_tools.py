"""Version 2.5 money: lab orders and payroll, gift certificates, bonuses, families, SBP, fiscal rules for the new methods."""
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import fiscal  # noqa: E402
import loyalty  # noqa: E402
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


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        return str(e)
    return None


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
pids = [r["id"] for r in d.q("SELECT id FROM patients LIMIT 4")]
pid, pid2, pid3 = pids[0], pids[1], pids[2]
doc = d.q("SELECT id FROM doctors LIMIT 1")[0]["id"]
today = date.today()

# ================================================================ lab
check("lab name required", raises(a.labs_save, {"name": ""}) is not None)
l1 = a.labs_save({"name": "Кристалл", "phone": "+7 949 000"})
l2 = a.labs_save({"name": "Дентал-Арт"})
check("labs listed", [x["name"] for x in a.lab_options()["labs"]] == ["Дентал-Арт", "Кристалл"])
check("patient required", raises(a.lab_save, {"work": "Коронка"}) is not None)
check("work required", raises(a.lab_save, {"patient_id": pid}) is not None)
check("bad status", raises(a.lab_save, {"patient_id": pid, "work": "x", "status": "lost"}) is not None)
check("due before sent", raises(a.lab_save, {"patient_id": pid, "work": "x", "sent_date": "2026-11-10", "due_date": "2026-11-01"}) is not None)
check("negative price", raises(a.lab_save, {"patient_id": pid, "work": "x", "price": -5}) is not None)
auth.set_current_user({"id": 4, "role": "doctor", "name": "Врач Анна"})
o1 = a.lab_save({"patient_id": pid, "doctor_id": doc, "lab_id": l1["id"], "work": "Коронка из диоксида циркония", "teeth": "36", "shade": "A2",
                 "price": "7 000", "due_date": (today - timedelta(days=1)).isoformat()})
auth.set_current_user(None)
o2 = a.lab_save({"patient_id": pid, "doctor_id": doc, "lab_id": l1["id"], "work": "Вкладка", "price": 3000, "fitting_date": today.isoformat()})
o3 = a.lab_save({"patient_id": pid2, "doctor_id": doc, "lab_id": l2["id"], "work": "Винир", "price": 9000, "status": "sent"})
check("numbering", (o1["number"], o2["number"], o3["number"]) == (1, 2, 3))
check("author", o1["created_by"] == "Врач Анна" and o1["lab_name"] == "Кристалл" and o1["price"] == 7000)
check("overdue", o1["overdue"] is True and o2["overdue"] is False)
check("fitting today", o2["fitting_today"] is True)
sm = a.lab_summary()
check("summary", sm["open"] == 3 and sm["overdue"] == 1 and sm["fitting_today"] == 1 and sm["unpaid"] == 19000, sm)
check("filter by patient", len(a.lab_orders("all", patient_id=pid)) == 2)
check("filter by lab", len(a.lab_orders("open", lab_id=l2["id"])) == 1)
a.lab_status(o1["id"], "ready")
check("status change", a.lab_order(o1["id"])["status_text"] == "Готов" and not a.lab_order(o1["id"])["overdue"])
check("open filter excludes ready", o1["id"] not in [x["id"] for x in a.lab_orders("open")])
check("pay needs one lab", "одной лаборатории" in (raises(a.lab_pay, [o1["id"], o3["id"]]) or ""))
pay = a.lab_pay([o1["id"], o2["id"]])
check("lab paid", pay["total"] == 10000 and pay["count"] == 2)
exp = d.one("SELECT * FROM expenses WHERE id=?", (pay["expense_id"],))
check("expense recorded", exp and exp["category"] == "Зуботехническая лаборатория" and exp["amount"] == 10000 and "№ 1, 2" in exp["comment"])
check("paid twice refused", raises(a.lab_pay, [o1["id"]]) is not None)
check("unpaid filter", [x["id"] for x in a.lab_orders("unpaid")] == [o3["id"]])
check("patient card count", a.patient(pid)["lab_count"] == 2)
plan = a._local.save_invoice({"patient_id": pid, "doctor_id": doc, "kind": "plan", "title": "План", "items": [{"title": "Коронка", "price": 25000, "qty": 1}]})
o4 = a.lab_save({"patient_id": pid, "doctor_id": doc, "lab_id": l2["id"], "work": "Коронка E.max", "plan_id": plan, "price": 6000})
check("order linked to the plan", a.lab_order(o4["id"])["plan_id"] == plan)

# payroll: percent of billed minus the lab cost
a.save_salary_scheme({"person": f"d:{doc}", "percent": 30, "base": "billed", "minus_lab": True})
check("scheme keeps minus_lab", next(s for s in a.salary_schemes() if s["key"] == f"d:{doc}")["minus_lab"] is True)
inv = a._local.save_invoice({"patient_id": pid, "doctor_id": doc, "items": [{"title": "Лечение", "price": 40000, "qty": 1}]})
row = next(r for r in a.payroll()["rows"] if r["key"] == f"d:{doc}")
lab_cost = 7000 + 3000 + 9000 + 6000
check("lab cost subtracted", row["lab"] == lab_cost and row["base_sum"] == round(row["billed"] - lab_cost, 2), row)
a.lab_status(o3["id"], "cancelled")
row = next(r for r in a.payroll()["rows"] if r["key"] == f"d:{doc}")
check("cancelled order not subtracted", row["lab"] == lab_cost - 9000)
a.save_salary_scheme({"person": f"d:{doc}", "percent": 30, "base": "billed", "minus_lab": False})
check("off: nothing subtracted", next(r for r in a.payroll()["rows"] if r["key"] == f"d:{doc}")["lab"] == 0)

# ================================================================ certificates
check("nominal limits", raises(a.cert_sell, {"amount": 50}) is not None)
check("past expiry", raises(a.cert_sell, {"amount": 1000, "expires": "2020-01-01"}) is not None)
c = a.cert_sell({"amount": "5 000", "buyer": "Иванов И.", "method": "Карта"})
check("certificate", len(c["code"]) == 9 and c["code"][4] == "-" and c["balance"] == 5000 and c["method"] == "Карта")
check("expires in a year", c["expires"] >= (today + timedelta(days=360)).isoformat())
check("code typed loosely", a.cert_info(c["code"].replace("-", "").lower())["id"] == c["id"])
check("unknown code", raises(a.cert_info, "ZZZZ-ZZZZ") is not None)
r = a.add_payment({"invoice_id": inv, "amount": 3000, "method": "Сертификат", "cert_code": c["code"]})
check("paid by certificate", r["ok"] and a.cert_info(c["code"])["balance"] == 2000)
check("payment says which certificate", c["code"] in d.one("SELECT comment FROM payments WHERE id=?", (r["id"],))["comment"])
check("over balance refused", "осталось 2000" in a.add_payment({"invoice_id": inv, "amount": 2500, "method": "Сертификат", "cert_code": c["code"]})["message"])
check("no payment left behind on refusal", d.one("SELECT COUNT(*) AS n FROM payments WHERE method='Сертификат'")["n"] == 1)
a.delete_payment(r["id"])
check("deleted payment gives the balance back", a.cert_info(c["code"])["balance"] == 5000 and not a.cert_info(c["code"])["moves"])
c2 = a.cert_sell({"amount": 1000})
with d.tx() as cx:
    cx.execute("UPDATE certificates SET expires=? WHERE id=?", ((today - timedelta(days=1)).isoformat(), c2["id"]))
check("expired refused", "истёк" in a.add_payment({"invoice_id": inv, "amount": 100, "method": "Сертификат", "cert_code": c2["code"]})["message"])
c3 = a.cert_sell({"amount": 1000})
a.cert_cancel(c3["code"])
check("cancelled refused", "аннулирован" in a.add_payment({"invoice_id": inv, "amount": 100, "method": "Сертификат", "cert_code": c3["code"]})["message"].lower())
lst = a.cert_list()
check("active list", [x["code"] for x in lst["rows"]] == [c["code"]] and lst["balance"] == 5000)
check("all list", len(a.cert_list("all")["rows"]) == 3)

# ================================================================ bonuses
check("bonuses off by default", loyalty.settings()["bonus_percent"] == 0)
a.add_payment({"invoice_id": inv, "amount": 1000, "method": "Наличные"})
check("no accrual when off", a.bonus_info(pid)["balance"] == 0)
check("settings validated", raises(a.loyalty_settings_save, {"bonus_percent": 50}) is not None)
a.loyalty_settings_save({"bonus_percent": 5, "bonus_max_share": 10})
r1 = a.add_payment({"invoice_id": inv, "amount": 10000, "method": "Карта"})
check("accrual 5 %", a.bonus_info(pid)["balance"] == 500)
r2 = a.add_payment({"invoice_id": inv, "amount": 2000, "method": "Безнал (организация)"})
check("no accrual from organisation payments", a.bonus_info(pid)["balance"] == 500)
check("share limit (10 % of 40 000 = 4 000) — balance limit first", "500.00 бонусов" in a.add_payment({"invoice_id": inv, "amount": 600, "method": "Бонусы"})["message"])
a.bonus_adjust(pid, 5000, "подарок на день рождения")
check("share limit", "10 %" in a.add_payment({"invoice_id": inv, "amount": 4500, "method": "Бонусы"})["message"])
rb = a.add_payment({"invoice_id": inv, "amount": 4000, "method": "Бонусы"})
check("spend", rb["ok"] and a.bonus_info(pid)["balance"] == 1500)
check("no bonus accrual on bonus payments", a.bonus_info(pid)["balance"] == 1500)
check("bonuses only for invoices", raises(a._loyal.check_spend, pid, None, 10) is not None)
a.delete_payment(rb["id"])
check("deleted bonus payment returns bonuses", a.bonus_info(pid)["balance"] == 5500)
a.delete_payment(r1["id"])
check("deleted money payment takes accrual back", a.bonus_info(pid)["balance"] == 5000)
check("manual needs reason", raises(a.bonus_adjust, pid, 100, "") is not None)
check("cannot go below zero", raises(a.bonus_adjust, pid, -99999, "x") is not None)
check("history", a.bonus_info(pid)["history"][0]["kind"] == "manual")

# ================================================================ families
check("family name required", raises(a.family_save, {"name": ""}) is not None)
check("discount limit", raises(a.family_save, {"name": "Ф", "discount": 80}) is not None)
f = a.family_save({"name": "Ивановы", "discount": 5, "add": [pid, pid2]})
check("family bonuses merged", a.bonus_info(pid2)["balance"] == 5000 and a.bonus_info(pid)["family"]["name"] == "Ивановы")
check("card shows family", a.patient(pid2)["family"]["discount"] == 5 and a.patient(pid2)["family"]["members"] == 2)
f2 = a.family_save({"name": "Петровы"})
check("one family at a time", raises(a.family_save, {"id": f2["id"], "name": "Петровы", "add": [pid]}) is not None)
a.family_leave(pid2)
check("leaving keeps family bonuses", a.bonus_info(pid)["balance"] == 5000 and a.bonus_info(pid2)["balance"] == 0)
a.family_leave(pid)
check("last member takes the bonuses", a.bonus_info(pid)["balance"] == 5000 and a.bonus_info(pid)["family"] is None)
check("not in a family", raises(a.family_leave, pid3) is not None)

# ================================================================ cash day and accounting
day = today.isoformat()
cd = a.cash_day(day)
non_money = sum(v for k, v in cd["by_method"].items() if k in ("Сертификат", "Бонусы"))
check("money total = payments − certificate/bonus + certificates sold", cd["money_total"] == round(cd["total"] - non_money + cd["cert_sold"], 2), cd)
check("certificate sales listed", cd["cert_sold"] == 7000 and len(cd["cert_sales"]) == 3)
rb2 = a.add_payment({"invoice_id": inv, "amount": 1000, "method": "Бонусы"})
inc = a.acc_summary(day, day)
cash_inc = d.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE method<>'Бонусы' AND substr(created_at,1,10)=?", (day,))["s"]
check("bonuses are not income", abs(inc["income"] - cash_inc) < 0.01 if "income" in inc else True, inc.get("income"))

# ================================================================ fiscal rules
check("SBP receipt is electronic", fiscal.PAY_TYPE["СБП"] == "electronically")
check("certificate payment offsets an advance", fiscal.PAY_TYPE["Сертификат"] == "prepaid")
check("bonus payment needs no receipt", a._fiscal.build_for_payment(rb2["id"]) is None)
check("bonus message", "бонусами" in a._fiscal.for_payment(rb2["id"])["message"])
rc = a.add_payment({"invoice_id": inv, "amount": 500, "method": "Сертификат", "cert_code": c["code"]})
body = a._fiscal.build_for_payment(rc["id"])
check("certificate receipt body", body["payments"] == [{"type": "prepaid", "sum": 500.0}])

# ================================================================ SBP
check("SBP needs an image", raises(a.sbp_settings_save, {"qr": "hello"}) is not None)
qr = "data:image/png;base64,iVBORw0KGgo="
check("SBP saved", a.sbp_settings_save({"qr": qr, "label": "ООО Улыбка"})["qr"] == qr)
code = a.tablet_code("Планшет")["code"]
key = a._tablet_public("pair", [code], "", "10.0.0.2")["key"]
tid = a.tablets_list()[0]["id"]
a.sbp_to_tablet(tid, 1500, pid)
t = a._tablet_public("task", [], key, "10.0.0.2")["task"]
check("QR on the tablet", t["kind"] == "qr" and t["qr"] == qr and t["amount"] == 1500 and t["label"] == "ООО Улыбка")
check("no SBP QR, no tablet task", (a.sbp_settings_save({"qr": ""}) or True) and raises(a.sbp_to_tablet, tid, 100) is not None)

# ================================================================ permissions
for m in ("lab_options", "lab_orders", "lab_order", "lab_summary", "lab_save", "lab_status", "labs_save", "lab_pay", "loyalty_settings",
          "loyalty_settings_save", "cert_sell", "cert_info", "cert_list", "cert_cancel", "bonus_info", "bonus_adjust", "family_save",
          "family_leave", "sbp_settings", "sbp_settings_save", "sbp_to_tablet"):
    check(f"perm {m}", m in auth.METHOD_PERMS)
for m in ("lab_save", "lab_pay", "cert_sell", "cert_cancel", "bonus_adjust", "family_save", "sbp_settings_save"):
    check(f"audited {m}", m in auth.AUDITED)
check("doctors and admins have the lab", "lab" in auth.ROLES["doctor"]["perms"] and "lab" in auth.ROLES["admin"]["perms"])
check("paying the lab is accounting", auth.METHOD_PERMS["lab_pay"] == "accounting")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
