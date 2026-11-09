"""Money (2.12.0): the patient's advance and paying invoices from it, refunds (with receipts), payment schedules
and reminders, memberships, the cash drawer by shifts with reconciliation, ДМС (insurers, letters of guarantee,
registries), and the rights over HTTP."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import finance  # noqa: E402
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
F = a._fin
T = date.today()
TODAY = T.isoformat()
doc = d.doctors()[0]["id"]


def day(n):
    return (T + timedelta(days=n)).isoformat()


def patient(last, phone=""):
    return a.create_patient({"lname": last, "fname": "Тест", "phone": phone})["id"]


def invoice(pid, price, title="Лечение кариеса", **kw):
    return a.save_invoice({"patient_id": pid, "doctor_id": doc, "items": [{"title": title, "price": price, "qty": 1, "discount": 0, **kw.pop("item", {})}],
                           **kw})


def pay(iid=None, amount=0, method="Наличные", pid=None):
    r = a.add_payment({"invoice_id": iid, "patient_id": pid, "amount": amount, "method": method, "receipt": False})
    assert r["ok"], r
    return r["id"]


def status(iid):
    return d.one("SELECT status FROM invoices WHERE id=?", (iid,))["status"]


# ===================================================================== advance
P1 = patient("Авансова", "+7 900 111-22-33")
cash0 = a.cash_day(TODAY)
adv = pay(None, 5000, "Карта", P1)
check("advance without an invoice", F.deposit(P1) == 5000 and a.patient(P1)["deposit"] == 5000)
r = a.add_payment({"patient_id": P1, "amount": 100, "method": "Бонусы"})
check("advance only in money", not r["ok"] and "деньгами" in r["message"], r)
r = a.add_payment({"patient_id": P1, "amount": 100, "method": "Из аванса"})
check("«Из аванса» is not chosen by hand", not r["ok"], r)
i1 = invoice(P1, 3000)
inv = a.invoice(i1)
check("invoice shows the advance", inv["deposit"] == 5000 and inv["overpaid"] == 0)
refuses("more than the invoice", lambda: a.deposit_use(i1, 3500), "осталось оплатить")
u = a.deposit_use(i1)
check("invoice paid from the advance", status(i1) == "Оплачен" and u["amount"] == 3000, u)
check("advance left", F.deposit(P1) == 2000 and d.patient(P1) and a._local.balance(P1) == 2000)
rows = d.q("SELECT * FROM payments WHERE link_id=?", (u["group"],))
check("move = two rows of one operation", len(rows) == 2 and sum(x["amount"] for x in rows) == 0 and all(x["method"] == "Из аванса" for x in rows))
cash1 = a.cash_day(TODAY)
check("day's money unchanged by the move", round(cash1["money_total"] - cash0["money_total"], 2) == 5000 and "Из аванса" not in cash1["by_method"], cash1["by_method"])
refuses("invoice already paid", lambda: a.deposit_use(i1), "уже оплачен")
i2 = invoice(P1, 2500)
u2 = a.deposit_use(i2)
check("part of the invoice from the rest", u2["amount"] == 2000 and status(i2) == "Частично оплачен" and F.deposit(P1) == 0)
refuses("no advance left", lambda: a.deposit_use(i2), "нет аванса")
refuses("advance already spent cannot be deleted", lambda: a.delete_payment(adv), "уже потрачена")
a.delete_payment(rows[1]["id"])  # either row removes the whole move
check("deleting the move returns the advance", F.deposit(P1) == 3000 and status(i1) == "Не оплачен"
      and not d.one("SELECT 1 AS x FROM payments WHERE link_id=?", (u["group"],)))
a.delete_invoice(i2)
check("deleting an invoice returns its advance", F.deposit(P1) == 5000)
rep = a.report_debts()
check("advance in the debts report", any(x["patient_id"] == P1 and x["advance"] == 2000 for x in rep["advances"]) or
      any(x["patient_id"] == P1 for x in rep["debts"]))

# ===================================================================== refunds
P2 = patient("Возвратова")
pay(None, 4000, "Наличные", P2)
refuses("refund needs a reason", lambda: a.refund({"patient_id": P2, "amount": 500}), "причину")
refuses("refund more than the advance", lambda: a.refund({"patient_id": P2, "amount": 5000, "reason": "передумал"}), "не больше")
rf = a.refund({"patient_id": P2, "amount": 1500, "method": "Наличные", "reason": "Отказ от лечения"})
check("refund lowers the advance", F.deposit(P2) == 2500 and rf["amount"] == 1500)
row = d.one("SELECT * FROM payments WHERE id=?", (rf["ids"][0],))
check("refund is a negative payment", row["amount"] == -1500 and row["kind"] == "refund" and "Отказ" in row["comment"])
c2 = a.cash_day(TODAY)
check("refunds in the day's cash", c2["refunds"] >= 1500)
i3 = invoice(P2, 1000)
pay(i3, 1300, "Карта")
check("overpaid invoice is the patient's money", F.deposit(P2) == 2800 and a.invoice(i3)["overpaid"] == 300)
refuses("refund from an invoice: only its overpayment", lambda: a.refund({"invoice_id": i3, "amount": 400, "reason": "сдача"}), "не больше")
a.refund({"invoice_id": i3, "amount": 300, "method": "Карта", "reason": "переплата"})
check("overpayment refunded", a.invoice(i3)["overpaid"] == 0 and status(i3) == "Оплачен" and F.deposit(P2) == 2500)
a.delete_payment(rf["ids"][0])
check("refund deleted, money back on the advance", F.deposit(P2) == 4000)

# bonuses taken back with the refund
import loyalty  # noqa: E402
loyalty.save_settings({"bonus_percent": 5})
P3 = patient("Бонусова")
pay(None, 2000, "Наличные", P3)
b0 = a._loyal.bonus_balance(P3)
a.refund({"patient_id": P3, "amount": 1000, "reason": "возврат"})
check("bonuses of the refunded money go back", b0 == 100 and a._loyal.bonus_balance(P3) == 50, (b0, a._loyal.bonus_balance(P3)))
loyalty.save_settings({"bonus_percent": 0})

# receipts: offset of the advance and return of income for the refunded sum
a.fiscal_save_settings({"enabled": True, "driver": "emulator", "taxation": "usnIncome", "tax": "none", "auto": True})
P4 = patient("Чекова")
pr = a.add_payment({"patient_id": P4, "amount": 3000, "method": "Наличные"})
check("advance receipt", pr["receipt"]["status"] in ("done", "test") and pr["receipt"]["items"][0]["paymentMethod"] == "advance", pr.get("receipt"))
i4 = invoice(P4, 2000)
u4 = a.deposit_use(i4)
check("offset receipt: services, paid by the prepayment", u4["receipt"]["payments"][0]["type"] == "prepaid"
      and u4["receipt"]["items"][0]["paymentMethod"] == "fullPayment", u4.get("receipt"))
grp = d.q("SELECT id FROM payments WHERE link_id=? AND amount<0", (u4["group"],))
check("the minus row needs no receipt", a.fiscal_for_payment(grp[0]["id"])["status"] == "not_required")
r4 = a.refund({"patient_id": P4, "amount": 1000, "method": "Наличные", "reason": "возврат остатка"})
check("refund receipt for the refunded sum", r4["receipt"]["kind"] == "refund" and r4["receipt"]["total"] == 1000
      and r4["receipt"]["items"][0]["paymentMethod"] == "advance", r4.get("receipt"))
refuses("refund with a receipt is not deleted", lambda: a.delete_payment(r4["ids"][0]), "чек возврата")
refuses("second refund receipt", lambda: a._fiscal.for_refund(r4["ids"][0]), "уже пробит")
a.fiscal_save_settings({"enabled": False})

# ===================================================================== schedules
P5 = patient("Рассрочкина", "89001234567")
i5 = invoice(P5, 9000, "Имплантация")
pay(i5, 3000)
dr = a.schedule_draft(i5, 3)
check("draft: paid part first, equal rest", len(dr) == 3 and dr[0]["amount"] == 3000 and dr[1]["amount"] == 3000
      and round(sum(x["amount"] for x in dr), 2) == 9000 and dr[1]["date"] > dr[0]["date"], dr)
refuses("sum must match the invoice", lambda: a.schedule_save({"invoice_id": i5, "items": [{"date": day(0), "amount": 3000}, {"date": day(30), "amount": 1000}]}), "равна")
refuses("one payment is not a schedule", lambda: a.schedule_save({"invoice_id": i5, "items": [{"date": day(0), "amount": 9000}]}), "два платежа")
refuses("same date twice", lambda: a.schedule_save({"invoice_id": i5, "items": [{"date": day(0), "amount": 4500}, {"date": day(0), "amount": 4500}]}), "один день")
s5 = a.schedule_save({"invoice_id": i5, "items": [{"date": day(-40), "amount": 3000}, {"date": day(-10), "amount": 3000}, {"date": day(20), "amount": 3000}]})
check("schedule statuses", [x["status"] for x in s5["items"]] == ["paid", "late", "wait"] and s5["overdue"] == 3000 and s5["late_since"] == day(-10), s5["items"])
od = a.overdue_payments()
check("overdue list", any(x["invoice_id"] == i5 and x["amount"] == 3000 and x["days"] == 10 for x in od), od)
rep = a.report_debts()
row5 = next(x for x in rep["debts"] if x["patient_id"] == P5)
check("debts: the part not due yet", row5["debt"] == 6000 and row5["not_due"] == 3000 and any(x["invoice_id"] == i5 for x in rep["overdue"]), row5)
C = a._crm
C.auto(force=True)
tasks = d.q("SELECT * FROM crm_tasks WHERE patient_id=? AND status='open'", (P5,))
check("task «напомнить о платеже»", any(t["rule"] == "pay" for t in tasks), tasks)
check("no «долг» task while the debt is in the schedule", not any(t["rule"] == "debt" for t in tasks))
dash = a.director_dashboard()
check("director sees overdue installments", any("рассрочке" in x["text"] for x in dash["advice"]), dash["advice"])
pay(i5, 3000)
C.auto(force=True)
check("payment closes the task", not d.q("SELECT 1 AS x FROM crm_tasks WHERE patient_id=? AND status='open' AND rule='pay'", (P5,))
      and a.schedule(i5)["overdue"] == 0)
check("closed as done", d.one("SELECT result FROM crm_tasks WHERE patient_id=? AND rule='pay'", (P5,))["result"] == "Сделано")
# a plain old debt → «напомнить о долге»
P6 = patient("Должникова", "89005556677")
i6 = invoice(P6, 1500)
d.conn.execute("UPDATE invoices SET created_at=? WHERE id=?", (day(-12) + " 10:00:00", i6)); d.conn.commit()
C.auto(force=True)
check("debt task after debt_days", d.one("SELECT COUNT(*) AS n FROM crm_tasks WHERE patient_id=? AND rule='debt' AND status='open'", (P6,))["n"] == 1)
C.auto(force=True)
check("debt task once", d.one("SELECT COUNT(*) AS n FROM crm_tasks WHERE patient_id=? AND rule='debt'", (P6,))["n"] == 1)
pay(i6, 1500)
C.auto(force=True)
check("debt paid — task closed", d.one("SELECT status FROM crm_tasks WHERE patient_id=? AND rule='debt'", (P6,))["status"] == "done")
s = a.crm_settings_save({"debt_on": False, "debt_days": 3, "debt_text": "Долг {сумма}"})
check("debt settings", s["debt_on"] is False and s["debt_days"] == 3 and s["debt_text"] == "Долг {сумма}")
a.crm_settings_save({"debt_on": True})
a.schedule_delete(i5)
check("schedule removed", a.schedule(i5) is None)

# ===================================================================== memberships
svc = a.save_service({"title": "Профессиональная гигиена", "price": 4000, "code": "G1", "category": "Гигиена"})
svc_id = svc if isinstance(svc, str) else svc["id"]
refuses("membership needs services", lambda: a.membership_type_save({"name": "Пустой", "price": 1000}), "хотя бы одну")
mt = a.membership_type_save({"name": "Гигиена 2 раза в год", "price": 6500, "months": 12,
                             "items": [{"service_id": svc_id, "qty": 2}]})
check("membership type", mt["items"][0]["title"] == "Профессиональная гигиена" and mt["items"][0]["qty"] == 2)
P7 = patient("Абонементова")
ms = a.membership_sell({"type_id": mt["id"], "patient_id": P7})
m = ms["membership"]
check("sold: invoice for the price", a.invoice(ms["invoice_id"])["total"] == 6500 and m["items"][0]["left"] == 2 and not m["paid"])
pay(ms["invoice_id"], 6500)
check("membership paid", a.memberships(P7)[0]["paid"] and a.patient(P7)["memberships"][0]["id"] == m["id"])
line = {"service_id": svc_id, "title": "Профессиональная гигиена", "price": 4000, "qty": 1, "discount": 0, "membership": m["id"]}
iu = a.save_invoice({"patient_id": P7, "doctor_id": doc, "items": [dict(line)]})
check("line by the membership costs 0", a.invoice(iu)["total"] == 0 and a.invoice(iu)["items"][0]["discount"] == 100)
check("one visit used", a.memberships(P7)[0]["items"][0]["left"] == 1)
a.save_invoice({"id": iu, "patient_id": P7, "doctor_id": doc, "items": [dict(line)]})
check("saving again does not count twice", a.memberships(P7)[0]["items"][0]["left"] == 1)
refuses("no more than in the membership", lambda: a.save_invoice({"patient_id": P7, "doctor_id": doc, "items": [dict(line), dict(line)]}), "осталось")
P8 = patient("Чужаков")
refuses("another patient's membership", lambda: a.save_invoice({"patient_id": P8, "items": [dict(line)]}), "не найден")
refuses("service not in the membership", lambda: a.save_invoice({"patient_id": P7, "items": [{**line, "service_id": None, "title": "Пломба"}]}), "не входит")
refuses("sale invoice with used visits", lambda: a.delete_invoice(ms["invoice_id"]), "абонемент")
a.delete_invoice(iu)
check("deleted invoice gives the visit back", a.memberships(P7)[0]["items"][0]["left"] == 2)
d.conn.execute("UPDATE memberships SET expires=? WHERE id=?", (day(-1), m["id"])); d.conn.commit()
refuses("expired membership", lambda: a.save_invoice({"patient_id": P7, "items": [dict(line)]}), "истёк")
check("expired is not active", not a.memberships(P7, True))
d.conn.execute("UPDATE memberships SET expires=? WHERE id=?", (day(300), m["id"])); d.conn.commit()
a.membership_cancel(m["id"])
refuses("cancelled membership", lambda: a.save_invoice({"patient_id": P7, "items": [dict(line)]}), "аннулирован")
a.membership_type_delete(mt["id"])
check("type removed from sale", not a.membership_types() and a.membership_types(True))
refuses("removed type is not sold", lambda: a.membership_sell({"type_id": mt["id"], "patient_id": P7}), "не найден")

# ===================================================================== cash shifts
check("no shift yet", a.cash_shift()["shift"] is None)
# everything above happened «earlier today» — not in the shift opened now (the test runs within one second)
d.conn.execute("UPDATE payments SET created_at=datetime(created_at, '-1 hour')")
d.conn.execute("UPDATE certificates SET sold_at=datetime(sold_at, '-1 hour')"); d.conn.commit()
refuses("move without a shift", lambda: a.cash_move({"kind": "in", "amount": 100, "reason": "Размен"}), "откройте")
sh = a.cash_shift_open({"open_cash": 1000})
refuses("second shift", lambda: a.cash_shift_open({"open_cash": 0}), "уже открыта")
P9 = patient("Кассова")
i9 = invoice(P9, 2000)
pay(i9, 2000, "Наличные")
pay(None, 700, "Карта", P9)
a.refund({"patient_id": P9, "amount": 500, "method": "Наличные", "reason": "сдача"})
a.cert_sell({"amount": 3000, "method": "Наличные"})
cur = a.cash_shift()["shift"]
check("expected cash", cur["expected_cash"] == 1000 + 2000 - 500 + 3000 and cur["refunds_cash"] == 500 and cur["card"] == 700, cur)
refuses("take out more than in the drawer", lambda: a.cash_move({"kind": "out", "amount": 99999, "reason": "Инкассация"}), "по расчёту")
refuses("move needs a reason", lambda: a.cash_move({"kind": "out", "amount": 100, "reason": ""}), "зачем")
e0 = d.one("SELECT COUNT(*) AS n FROM expenses")["n"]
a.cash_move({"kind": "out", "amount": 300, "reason": "Расход из кассы", "comment": "вода", "expense": True, "category": "Прочее"})
a.cash_move({"kind": "out", "amount": 1200, "reason": "Инкассация"})
a.cash_move({"kind": "in", "amount": 200, "reason": "Размен"})
cur = a.cash_shift()["shift"]
check("moves counted", cur["expected_cash"] == 5500 - 300 - 1200 + 200 and len(cur["moves"]) == 3)
check("expense from the drawer in accounting", d.one("SELECT COUNT(*) AS n FROM expenses")["n"] == e0 + 1
      and d.one("SELECT method FROM expenses ORDER BY created_at DESC LIMIT 1")["method"] == "Наличные")
refuses("close needs counted cash", lambda: a.cash_shift_close({}), "Пересчитайте")
cl = a.cash_shift_close({"counted_cash": 4100, "card_terminal": 700, "sbp_bank": ""})
check("closed with the difference", cl["status"] == "closed" and cl["diff_cash"] == -100 and cl["diff_card"] == 0 and cl["diff_sbp"] is None, cl)
check("next shift offers what is left", a.cash_shift()["last_left"] == 4100 and a.cash_shift()["shift"] is None)
info = a.cash_shift_info(cl["id"])
check("shift details", len(info["payment_rows"]) >= 3 and a.cash_shifts()[0]["id"] == cl["id"])
check("cash day knows the shift", "shift" in a.cash_day(TODAY))

# ===================================================================== ДМС
refuses("insurer needs a name", lambda: a.insurer_save({"name": " "}), "название")
ins = a.insurer_save({"name": "СК «Здоровье»", "contract": "№ 15/26"})
P10 = patient("Страхова")
refuses("letter needs a number", lambda: a.ins_doc_save({"patient_id": P10, "insurer_id": ins["id"], "kind": "letter"}), "номер")
let = a.ins_doc_save({"patient_id": P10, "insurer_id": ins["id"], "kind": "letter", "number": "ГП-77", "valid_to": day(60), "limit_sum": 10000})
check("letter of guarantee", let["kind_title"] == "Гарантийное письмо" and let["left"] == 10000)
refuses("insurer invoice needs a document", lambda: invoice(P10, 1000, insurer_id=ins["id"]), "полис")
i10 = invoice(P10, 6000, insurer_id=ins["id"], ins_doc_id=let["id"])
check("invoice for the insurer", a.invoice(i10)["insurer_name"] == "СК «Здоровье»" and a.ins_docs(P10)[0]["left"] == 4000)
refuses("over the limit", lambda: invoice(P10, 5000, insurer_id=ins["id"], ins_doc_id=let["id"]), "Лимит")
i11 = invoice(P10, 3000, insurer_id=ins["id"], ins_doc_id=let["id"])
check("not the patient's debt", not any(x["patient_id"] == P10 for x in a.report_debts()["debts"]) and a._local.balance(P10) == 0)
summ = a.ins_summary()
check("insurer owes", summ["insurers"][0]["due"] == 9000 and summ["insurers"][0]["free"] == 2)
refuses("document with invoices is kept", lambda: a.ins_doc_delete(let["id"]), "нельзя")
P11 = patient("Чужой")
refuses("someone else's letter", lambda: invoice(P11, 100, insurer_id=ins["id"], ins_doc_id=let["id"]), "не принадлежит")
refuses("advance does not pay the insurer's invoice", lambda: a.deposit_use(i10), "страховая")
reg = a.registry_make({"insurer_id": ins["id"], "date_from": day(-31), "date_to": TODAY})
check("registry", reg["total"] == 9000 and len(reg["rows"]) == 2 and reg["status"] == "draft", reg.get("total"))
refuses("nothing left for a second registry", lambda: a.registry_make({"insurer_id": ins["id"], "date_from": day(-31), "date_to": TODAY}), "нет счетов")
x = a.registry_xlsx(reg["id"])
check("registry in Excel", x["url"].startswith("data:application/vnd.openxmlformats") and x["name"].endswith(".xlsx"))
title, head, rows = F.registry_table(reg["id"])
check("registry rows", rows[0][1] == a.patient(P10)["name"] and "ГП-77" in rows[0][3] and rows[-1][-1] == 9000, rows[:2])
check("sent", a.registry_status(reg["id"], "sent")["status"] == "sent")
paid = a.registry_pay(reg["id"], {"rejected": [i11]})
check("registry paid", paid["status"] == "paid" and paid["paid_total"] == 6000 and status(i10) == "Оплачен")
check("payment «Страховая»", d.one("SELECT method, kind FROM payments WHERE invoice_id=?", (i10,))["method"] == "Страховая")
check("refused invoice goes to the patient", d.one("SELECT insurer_id FROM invoices WHERE id=?", (i11,))["insurer_id"] is None
      and any(x["patient_id"] == P10 and x["debt"] == 3000 for x in a.report_debts()["debts"]))
refuses("paid registry is kept", lambda: a.registry_delete(reg["id"]), "Оплаченный")
check("insurance payment is not in the tax certificate", a._tax.data(P10, T.year)["total"] == 0)
check("advance move is not doubled in the tax certificate", a._tax.data(P1, T.year)["total"] == 5000, a._tax.data(P1, T.year))

# ===================================================================== sync and rights
names = {t.name for t in replica.TABLES}
check("new tables travel between laptops", {"pay_schedules", "memberships", "membership_types", "membership_uses", "cash_shifts", "cash_moves",
                                             "insurers", "insurance_docs", "insurance_registries"} <= names)
replica.install(d)
before = d.one("SELECT COUNT(*) AS n FROM sync_dirty WHERE tbl='insurers'")["n"]
a.insurer_save({"name": "СК «Вторая»"})
check("change is captured for sync", d.one("SELECT COUNT(*) AS n FROM sync_dirty WHERE tbl='insurers'")["n"] == before + 1)
for k in ("deposit_use", "refund", "schedule_save", "membership_sell", "cash_shift_close", "registry_pay"):
    check(f"{k} in the journal", k in auth.AUDITED and k in auth.METHOD_PERMS)

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
st, sh = call("api", "cash_shift_open", {"open_cash": 500}, token=TA)
check("admin opens the shift", st == 200 and sh["opened_by"] == "ADM", sh)
check("admin takes a refund", call("api", "refund", {"patient_id": P2, "amount": 100, "reason": "тест"}, token=TA)[0] == 200)
check("doctor: no refunds, no shift", call("api", "refund", {"patient_id": P2, "amount": 100, "reason": "x"}, token=TDoc)[0] == 403
      and call("api", "cash_shift_close", {"counted_cash": 0}, token=TDoc)[0] == 403)
check("admin: no registries (director only)", call("api", "registry_make", {}, token=TA)[0] == 403 and call("api", "ins_summary", token=TA)[0] == 403)
check("doctor sells a membership (billing)", call("api", "membership_types", token=TDoc)[0] == 200)
au = d.q("SELECT action, user_name FROM audit WHERE action IN ('Открытие кассовой смены', 'Возврат денег пациенту') ORDER BY id")
check("money changes in the journal", [x["action"] for x in au][-2:] == ["Открытие кассовой смены", "Возврат денег пациенту"] and au[-1]["user_name"] == "ADM", au)
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
