"""Stock without documents (2.14.1): a receipt without an invoice, a write-off and a stock count without an act
still move the actual balance, the balance «по документам» leaves them out and is shown with «Бухгалтерия» only,
acts are numbered among documented ones, a receipt can be written down as an expense of the day, the day report
carries a «Склад» block."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402
from stock import Stock  # noqa: E402


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
    except (ValueError, auth.AuthError) as e:
        check(name, not text or text in str(e), e)


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
S = Stock(d)
T = date.today().isoformat()

# ------------------------------------------------------------------ the column and the demo base
check("nodoc column", "nodoc" in {r[1] for r in d.conn.execute("PRAGMA table_info(stock_docs)")})
check("demo documents are documented", d.one("SELECT COUNT(*) AS n FROM stock_docs WHERE COALESCE(nodoc,0)<>0")["n"] == 0)
Stock(d)  # the migration runs twice without harm
check("migration is idempotent", [r[1] for r in d.conn.execute("PRAGMA table_info(stock_docs)")].count("nodoc") == 1)

mid = S.save_material({"name": "Тестовый композит", "unit": "шт", "price": 100})
mid = mid if isinstance(mid, str) else mid["id"]
sup = S.save_supplier({"name": "Поставщик Тест"})
sup = sup if isinstance(sup, str) else sup["id"]


def bal(m=mid):
    r = next(x for x in S.materials(with_inactive=True) if x["id"] == m)
    return r["balance"], r["balance_doc"], r["value_doc"]


# ------------------------------------------------------------------ receipts
r1 = S.receive({"date": T, "number": "Н-1", "supplier_id": sup, "lines": [{"material_id": mid, "qty": 10, "price": 100}]}, "Кладовщик")
r2 = S.receive({"date": T, "supplier_id": sup, "nodoc": True, "lines": [{"material_id": mid, "qty": 3, "price": 100}]}, "Кладовщик")
check("documented receipt", not S.doc(r1)["nodoc"])
check("receipt without an invoice is marked", S.doc(r2)["nodoc"] == 1)
check("actual balance has both receipts", bal()[0] == 13, bal())
check("balance by documents leaves the grey receipt out", bal()[1] == 10 and bal()[2] == 1000, bal())

# ------------------------------------------------------------------ write-offs and act numbers
n_before = S._next_number("writeoff")
w1 = S.write_off({"date": T, "reason": "Брак", "nodoc": True, "lines": [{"material_id": mid, "qty": 2}]}, "Кладовщик")
check("write-off without an act takes no number", S.doc(w1)["number"] == "" and S.doc(w1)["nodoc"] == 1)
check("act numbering does not move", S._next_number("writeoff") == n_before)
w2 = S.write_off({"date": T, "reason": "Истёк срок", "lines": [{"material_id": mid, "qty": 1}]}, "Кладовщик")
check("next documented act has the next number, no gap", S.doc(w2)["number"] == n_before, S.doc(w2)["number"])
check("balances after write-offs", bal()[:2] == (10, 9), bal())
refuses("still cannot go below zero", lambda: S.write_off({"reason": "x", "nodoc": True, "lines": [{"material_id": mid, "qty": 99}]}), "нельзя")

# ------------------------------------------------------------------ stock count without an act
i_before = S._next_number("inventory")
inv = S.inventory({"nodoc": True, "lines": [{"material_id": mid, "actual": 12}]}, "Кладовщик")
check("internal stock count: no number", S.doc(inv["id"])["number"] == "" and S.doc(inv["id"])["nodoc"] == 1)
check("internal count moves the actual balance only", bal()[:2] == (12, 9), bal())
check("inventory numbering unchanged", S._next_number("inventory") == i_before)

# ------------------------------------------------------------------ moves and documents carry the mark
mv = S.moves(material_id=mid)
check("moves are marked", sorted(x["nodoc"] for x in mv) == [0, 0, 1, 1, 1], [x["nodoc"] for x in mv])
check("documents list marks them", {x["id"]: x["nodoc"] for x in S.docs() if x["id"] in (r1, r2)} == {r1: 0, r2: 1})

# ------------------------------------------------------------------ the day: sums with and without documents
dd = S.day_docs(T)
check("day receipts", dd["receipt"] >= 1300 and dd["receipt_nodoc"] == 300, dd)
check("day write-offs", dd["writeoff"] >= 300 and dd["writeoff_nodoc"] == 200, dd)
check("count is not in the day's documents", all(r["kind"] in ("receipt", "writeoff") for r in dd["rows"]))
rep = a._daily.report(T)
txt = a._daily.text(rep)
check("report has the stock block", rep.get("stock") and "Склад: приход" in txt and "без документов 300" in txt.replace(" ", " "), txt[-600:])
check("grey lines in the report", "без документа — Поставщик Тест" in txt and "Списание № " + n_before in txt, txt[-600:])
check("report Excel with stock", a._daily.xlsx(rep)[:2] == b"PK")
own = a._daily.report(T, login="anna", shifts=False)
check("an administrator's own report has no stock", not own.get("stock"))

# ------------------------------------------------------------------ a receipt written down as an expense of the day
n_exp = d.one("SELECT COUNT(*) AS n FROM expenses")["n"]
r3 = a.stock_receive({"date": T, "supplier_id": sup, "nodoc": True, "pay": "Карта клиники",
                      "lines": [{"material_id": mid, "qty": 2, "price": 150}]})
e = d.one("SELECT * FROM expenses ORDER BY rowid DESC LIMIT 1")
check("receipt → expense of the day", d.one("SELECT COUNT(*) AS n FROM expenses")["n"] == n_exp + 1 and e["amount"] == 300
      and e["category"] == "Материалы и закупки" and e["method"] == "Карта клиники" and not e["doc"], e)
check("expense names the supplier", "Приход на склад" in (e["comment"] or "") and "Поставщик Тест" in (e["comment"] or ""), e["comment"])
a.stock_receive({"date": T, "number": "Н-7", "supplier_id": sup, "pay": "Перевод", "lines": [{"material_id": mid, "qty": 1, "price": 50}]})
e = d.one("SELECT * FROM expenses ORDER BY rowid DESC LIMIT 1")
check("documented receipt → expense with a document", e["doc"] and "№ Н-7" in e["comment"], e)
n_exp = d.one("SELECT COUNT(*) AS n FROM expenses")["n"]
a.stock_receive({"date": T, "supplier_id": sup, "pay": "нечто", "lines": [{"material_id": mid, "qty": 1, "price": 50}]})
check("an unknown way of payment writes nothing", d.one("SELECT COUNT(*) AS n FROM expenses")["n"] == n_exp)
a.stock_receive({"date": T, "supplier_id": sup, "pay": "Перевод", "lines": [{"material_id": mid, "qty": 1, "price": 0}]})
check("a free receipt writes no expense", d.one("SELECT COUNT(*) AS n FROM expenses")["n"] == n_exp)
check("local mode sees the documents balance", "balance_doc" in a.material(mid) and "balance_doc" in a.materials()[0])

# ------------------------------------------------------------------ over HTTP: who sees what
sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
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
for login, role in (("klad", "storekeeper"), ("adm", "admin")):
    call("auth", "register", {"name": login.upper(), "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    check(f"position given: {login}", call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)[0] == 200)
TK, TA = (call("auth", "login", x, "secret1")[1]["token"] for x in ("klad", "adm"))
st_, rows = call("api", "materials", token=TK)
check("storekeeper sees balances", st_ == 200 and rows and "balance" in rows[0])
check("storekeeper does not see «по документам»", all("balance_doc" not in r and "value_doc" not in r for r in rows))
st_, m = call("api", "material", mid, token=TK)
check("material card without «по документам» for the storekeeper", st_ == 200 and "balance_doc" not in m and m["balance"] > 0, m.get("balance"))
st_, rows = call("api", "materials", token=TD)
check("director sees «по документам»", st_ == 200 and all("balance_doc" in r for r in rows))
check("director: the grey difference", next(r for r in rows if r["id"] == mid)["balance_doc"] < next(r for r in rows if r["id"] == mid)["balance"])
st_, r_ = call("api", "stock_receive", {"date": T, "supplier_id": sup, "nodoc": True, "pay": "Наличные из кассы",
                                        "lines": [{"material_id": mid, "qty": 1, "price": 10}]}, token=TK)
check("storekeeper cannot write an expense of the day", st_ == 400 and "Расходы за день" in r_.get("error", ""), r_)
st_, r_ = call("api", "stock_receive", {"date": T, "supplier_id": sup, "nodoc": True, "lines": [{"material_id": mid, "qty": 1, "price": 10}]}, token=TK)
check("storekeeper receives without an invoice", st_ == 200)
check("the refused receipt left nothing", sum(1 for x in S.docs() if x["total"] == 10) == 1)
st_, r_ = call("api", "stock_receive", {"date": T, "supplier_id": sup, "nodoc": True, "pay": "Наличные из кассы",
                                        "lines": [{"material_id": mid, "qty": 1, "price": 77}]}, token=TA)
e = d.one("SELECT * FROM expenses ORDER BY rowid DESC LIMIT 1")
check("admin's receipt goes to own expenses of the day", st_ == 200 and e["amount"] == 77 and e["login"] == "adm" and not e["doc"], e)
check("admin does not see «по документам»", all("balance_doc" not in r for r in call("api", "materials", token=TA)[1]))
check("receipt is in the journal", any(x["action"] == "Приход на склад" for x in d.q("SELECT action FROM audit")))
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
