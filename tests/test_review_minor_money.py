"""Review 2026-11-13, «мелочи» about money: the tax certificate counts only money (М2), quantity 0 and a zero-sum
invoice (М3), a cash expense larger than the drawer (М4), payments after a shift was closed (М5), the same-second
shift boundary (М6), an advance spent twice offline (М7), deleting a payment of a past day (М8)."""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
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


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
auth.Auth(d)  # the action journal
F = a._fin
doc = d.doctors()[0]["id"]
N = [0]


def patient(last):
    return a.create_patient({"lname": last, "fname": "Тест"})["id"]


def invoice(pid, price, **kw):
    return a.save_invoice({"patient_id": pid, "doctor_id": doc, "items": [{"title": "Услуга", "price": price, "qty": 1}], **kw})


def ts(minutes=0, seconds=0):
    return (datetime.now() + timedelta(minutes=minutes, seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


def pay_row(pid, amount, method, at, invoice_id=None, kind=None, link=None):
    N[0] += 1
    pay_id = f"PT-{N[0]}"
    with d.tx() as c:
        c.execute("INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at, kind, link_id) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pay_id, invoice_id, pid, amount, method, "", at, kind, link))
    return pay_id


def shift_row(sid, opened, closed=None, open_cash=0.0):
    with d.tx() as c:
        c.execute("INSERT INTO cash_shifts(id, opened_at, opened_by, open_cash, closed_at, status) VALUES(?,?,?,?,?,?)",
                  (sid, opened, "", open_cash, closed, "closed" if closed else "open"))


def no_shifts():
    with d.tx() as c:
        c.execute("DELETE FROM cash_moves")
        c.execute("DELETE FROM cash_shifts")


# ======================================================================= М2
p2 = patient("Вычетов")
year = str(date.today().year)
i2 = invoice(p2, 10000)
for m, x in (("Наличные", 3000), ("Карта", 2000), ("Бонусы", 500), ("Сертификат", 1000), ("Безнал (организация)", 1500), ("Страховая", 700)):
    pay_row(p2, x, m, f"{year}-01-15 10:00:00", i2)
pay_row(p2, 400, "СБП", f"{year}-01-16 10:00:00")  # an advance is money
pay_row(p2, 400, "Из аванса", f"{year}-01-16 10:01:00", i2, "deposit_use", "G1")
pay_row(p2, -400, "Из аванса", f"{year}-01-16 10:01:00", None, "deposit_use", "G1")
t2 = a.taxcert_data(p2, int(year))
check("М2: only money in the tax certificate", t2["total"] == 5400, t2["total"])
check("М2: no bonuses or certificates in the list", not {x["method"] for x in t2["payments"]} & {"Бонусы", "Сертификат", "Страховая", "Безнал (организация)", "Из аванса"})
check("М2: what was left out is shown", t2["not_money"] == 3700, t2["not_money"])

# ======================================================================= М3
p3 = patient("Нулёв")
refuses("М3: quantity 0 is refused", lambda: a.save_invoice({"patient_id": p3, "doctor_id": doc, "items": [{"title": "Услуга", "price": 100, "qty": 0}]}),
        "больше нуля")
i3 = a.save_invoice({"patient_id": p3, "doctor_id": doc, "items": [{"title": "Услуга", "price": 100, "qty": ""}]})
check("М3: an empty quantity is 1", d.one("SELECT total FROM invoices WHERE id=?", (i3,))["total"] == 100)
i3z = a.save_invoice({"patient_id": p3, "doctor_id": doc, "items": [{"title": "Осмотр по абонементу", "price": 0, "qty": 1}]})
check("М3: a zero-sum invoice is paid", d.one("SELECT status FROM invoices WHERE id=?", (i3z,))["status"] == "Оплачен")
mt = a.membership_type_save({"name": "Гигиена", "items": [{"title": "Профгигиена", "qty": 2}], "price": 5000, "months": 12})
mt_id = mt["id"] if isinstance(mt, dict) and "id" in mt else d.one("SELECT id FROM membership_types WHERE name='Гигиена'")["id"]
ms = a.membership_sell({"patient_id": p3, "type_id": mt_id})
check("М3: a sold membership waits for the money", not ms["membership"]["paid"])
inv = d.one("SELECT * FROM invoices WHERE id=?", (ms["invoice_id"],))
import json  # noqa: E402
a._local.save_invoice({"id": inv["id"], "patient_id": p3, "doctor_id": doc, "items": json.loads(inv["items"]), "discount": 100})
check("М3: a membership given for free (100 % discount) is paid", F.membership(ms["membership"]["id"])["paid"])

# ======================================================================= М4
no_shifts()
F.shift_open({"open_cash": 100})
refuses("М4: a cash expense larger than the drawer is refused", lambda: a.day_expense_save({"amount": 500, "category": "Прочее", "method": "Наличные из кассы"}),
        "В кассе по расчёту")
check("М4: the refused expense is not written down", not d.one("SELECT 1 AS x FROM expenses WHERE amount=500"))
e4 = a.day_expense_save({"amount": 60, "category": "Прочее", "method": "Наличные из кассы", "comment": "вода"})
e4 = e4 if isinstance(e4, str) else (e4.get("id") if isinstance(e4, dict) else None) or d.one("SELECT id FROM expenses WHERE amount=60")["id"]
check("М4: a fitting expense leaves the drawer", F.shift_current()["shift"]["expected_cash"] == 40)
refuses("М4: raising it over the drawer is refused", lambda: a.day_expense_save({"id": e4, "amount": 110, "category": "Прочее", "method": "Наличные из кассы"}),
        "В кассе по расчёту")
a.day_expense_save({"id": e4, "amount": 90, "category": "Прочее", "method": "Наличные из кассы"})
check("М4: raising it within the drawer is fine", F.shift_current()["shift"]["expected_cash"] == 10)
a.day_expense_save({"amount": 700, "category": "Прочее", "method": "Карта клиники"})
check("М4: a card expense does not touch the drawer", F.shift_current()["shift"]["expected_cash"] == 10)
no_shifts()
a.day_expense_save({"amount": 800, "category": "Прочее", "method": "Наличные из кассы"})
check("М4: without an open shift the expense is still written down", d.one("SELECT 1 AS x FROM expenses WHERE amount=800"))

# ======================================================================= М5
no_shifts()
p5 = patient("Поздняков")
shift_row("SH-M5", ts(-120), open_cash=1000)
pay_row(p5, 500, "Наличные", ts(-60))
c5 = F.shift_close({"id": "SH-M5", "counted_cash": 1500})
check("М5: closed with matching cash", c5["diff_cash"] == 0 and not c5["late_warning"], c5)
pay_row(p5, 300, "Наличные", ts(-30))   # came by the network from a computer that worked offline
pay_row(p5, 200, "Карта", ts(-20))
s5 = F.shift("SH-M5")
check("М5: the closed figures are kept", s5["expected_cash"] == 1500 and s5["diff_cash"] == 0, s5)
check("М5: the late payments are flagged", s5["late"] == {"наличные": 300, "карта": 200}, s5["late"])
check("М5: the warning names the sum", "300 ₽" in s5["late_warning"] and "в сверку" in s5["late_warning"], s5["late_warning"])
pay_row(p5, 250, "СБП", ts(5))         # after the close, no shift open
s5 = F.shift("SH-M5")
check("М5: money outside any shift is flagged", s5["outside"] == 250 and "ни в одну смену" in s5["late_warning"], s5)
check("М5: the cash panel shows it", "ни в одну смену" in F.shift_current()["last_warning"])
check("М5: an open shift has no warning", "late_warning" not in (F.shift_open({"open_cash": 0}) or {}))

# ======================================================================= М6
no_shifts()
p6 = patient("Секундов")
t0 = datetime(2001, 3, 1, 10, 0, 0)  # away from the other payments
f = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
A_open, A_close = f(t0), f(t0 + timedelta(hours=1))
shift_row("SH-A", A_open, A_close)
shift_row("SH-B", A_close, f(t0 + timedelta(hours=2)))  # opened in the same second the first one closed
pay_row(p6, 100, "Наличные", A_close)
na, nb = F.shift("SH-A"), F.shift("SH-B")
check("М6: a payment at the boundary second is counted once", na["cash_in"] + nb["cash_in"] == 100, (na["cash_in"], nb["cash_in"]))
check("М6: it goes to the shift that opened then", nb["cash_in"] == 100)
no_shifts()
shift_row("SH-C", A_open, A_close)
shift_row("SH-D", f(t0 + timedelta(hours=1, seconds=1)), f(t0 + timedelta(hours=2)))
nc, nd = F.shift("SH-C"), F.shift("SH-D")
check("М6: at the closing second with a later next shift — only the closed one", nc["cash_in"] == 100 and nd["cash_in"] == 0, (nc["cash_in"], nd["cash_in"]))
no_shifts()

# ======================================================================= М7
p7 = patient("Двойнов")
r = a.add_payment({"patient_id": p7, "amount": 1000, "method": "Наличные"})
check("М7: advance taken", r.get("ok"), r)
i7a, i7b = invoice(p7, 1000), invoice(p7, 1000)
F.deposit_use(i7a)
# the second computer, without the network, spent the same advance on the other invoice
pay_row(p7, 1000, "Из аванса", ts(), i7b, "deposit_use", "DU-off")
pay_row(p7, -1000, "Из аванса", ts(), None, "deposit_use", "DU-off")
a._local._invoice_status(i7b)
check("М7: the advance is negative, not hidden", F.deposit(p7) == -1000, F.deposit(p7))
check("М7: the overspent pocket is listed", any(x["invoice_id"] is None and x["amount"] == -1000 for x in F.pockets(p7)))
debt = [x for x in a.report_debts()["debts"] if x["patient_id"] == p7]
check("М7: the debts report shows it", debt and debt[0]["debt"] == 1000, debt)
i7c = invoice(p7, 300)
pay_row(p7, 600, "Наличные", ts(), i7c)  # overpaid by 300 — it only covers part of the debt
i7d = invoice(p7, 200)
refuses("М7: an overpayment cannot be spent while the advance is negative", lambda: F.deposit_use(i7d), "нет аванса")
refuses("М7: nor given back", lambda: F.refund({"patient_id": p7, "invoice_id": i7c, "amount": 100, "reason": "ошибка"}), "должен")
check("М7: the net balance is −700", F.deposit(p7) == -700, F.deposit(p7))

# ======================================================================= М8
p8 = patient("Удалов")
i8 = invoice(p8, 1000)
today = a.add_payment({"invoice_id": i8, "amount": 100, "method": "Наличные"})["id"]
check("М8: a payment of today is deleted as before", a.delete_payment(today) is True)
yday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d 12:00:00")
old = pay_row(p8, 200, "Карта", yday, i8)
auth.set_current_user({"id": 77, "role": "admin", "login": "adm", "name": "Админ"})
refuses("М8: an administrator cannot delete a payment of a past day", lambda: a.delete_payment(old), "Бухгалтерия")
auth.set_current_user({"id": 78, "role": "director", "login": "dir", "name": "Директор"})
r8 = a.delete_payment(old)
check("М8: a reason is asked first", isinstance(r8, dict) and r8.get("need_reason") and d.one("SELECT 1 AS x FROM payments WHERE id=?", (old,)), r8)
check("М8: a blank reason is not a reason", isinstance(a.delete_payment(old, "   "), dict))
check("М8: with a reason it is deleted", a.delete_payment(old, "Ошибочно провели дважды") is True and not d.one("SELECT 1 AS x FROM payments WHERE id=?", (old,)))
j = d.one("SELECT * FROM audit WHERE action LIKE 'Удалена оплата%' ORDER BY rowid DESC LIMIT 1")
check("М8: the reason is in the journal", j and "Ошибочно провели дважды" in j["detail"] and old in j["detail"], j)
# today, but the cash shift is already closed
no_shifts()
shift_row("SH-M8", ts(-60))
late = a.add_payment({"invoice_id": i8, "amount": 50, "method": "Наличные"})["id"]
with d.tx() as c:
    c.execute("UPDATE payments SET created_at=? WHERE id=?", (ts(-30), late))
F.shift_close({"id": "SH-M8", "counted_cash": 50})
auth.set_current_user({"id": 77, "role": "admin", "login": "adm", "name": "Админ"})
refuses("М8: nor a payment of a closed shift", lambda: a.delete_payment(late), "закрытой кассовой смены")
auth.set_current_user(None)
check("М8: the accountant can, with a reason", a.delete_payment(late, "Пациент передумал") is True)
no_shifts()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print("  FAIL", x)
sys.exit(1 if FAIL else 0)
