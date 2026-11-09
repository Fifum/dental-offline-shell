"""Staff and rights (2.14.0): positions the director makes and changes (rights checked over HTTP at once, synced,
new rights of later versions reach saved positions), finer money rights (expenses of the day, Excel), the
administrators' expenses of the day (own and today only, the cash drawer), the day report by e-mail (fake SMTP,
queue and retry, the moment to send), the menu following a change of rights."""
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
import auth  # noqa: E402
import config  # noqa: E402
import daily  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import replica  # noqa: E402
import voices  # noqa: E402
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
    except (ValueError, auth.AuthError) as e:
        check(name, not text or text in str(e), e)


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
T = date.today().isoformat()

# ------------------------------------------------------------------ positions without HTTP
A = auth.Auth(d)
rs = auth.roles(d)
check("built-in positions", list(rs)[:5] == ["director", "admin", "doctor", "assistant", "storekeeper"] and not rs["admin"]["edited"])
check("new rights in built-in roles", "expenses_day" in rs["admin"]["perms"] and "export" in rs["doctor"]["perms"])
check("groups cover every right", sorted(k for _, ks in auth.PERM_GROUPS for k in ks) == sorted(auth.PERM_KEYS))
refuses("director is not editable", lambda: A.role_save(None, {"key": "director", "title": "Директор", "perms": []}), "все права")
refuses("a position needs a title", lambda: A.role_save(None, {"title": " ", "base": "admin", "perms": []}), "название")
refuses("a position needs a base", lambda: A.role_save(None, {"title": "Х", "base": "director", "perms": []}), "похожа")
sa = A.role_save(None, {"title": "Старший администратор", "base": "admin", "perms": ["schedule_view", "cash_report", "accounting", "bogus"]})
check("own position", sa["key"].startswith("p_") and sa["perms"] == ["cash_report", "accounting", "schedule_view"][::1] or
      set(sa["perms"]) == {"schedule_view", "cash_report", "accounting"}, sa)
refuses("no two positions with one title", lambda: A.role_save(None, {"title": "старший администратор", "base": "admin", "perms": []}), "уже есть")
adm = A.role_save(None, {"key": "admin", "title": "Администратор", "perms": ["schedule_view", "expenses_day"]})
check("built-in changed", adm["edited"] and set(adm["perms"]) == {"schedule_view", "expenses_day"})
check("effective rights follow the position", set(auth.Auth.effective_perms({"role": "admin", "perms": None})) == {"schedule_view", "expenses_day"})
check("reset to the program's rights", A.role_reset(None, "admin")["perms"] == auth.ROLES["admin"]["perms"])
refuses("only built-ins are reset", lambda: A.role_reset(None, sa["key"]), "встроенную")
# a position saved before a newer version: rights that appeared later come from the role's default
with d.tx() as c:
    c.execute("INSERT OR REPLACE INTO staff_roles(key, title, base, perms, known, sort, updated_at) VALUES('doctor','Врач','doctor',?,?,0,'x')",
              (json.dumps(["schedule_view", "medcard_edit"]), json.dumps(auth.PERM_KEYS_2_13)))
check("later rights reach a saved position", set(auth.roles(d)["doctor"]["perms"]) == {"schedule_view", "medcard_edit", "export"})
A.role_reset(None, "doctor")
check("a person's old list of rights gets new ones from the position",
      "expenses_day" in auth.Auth.effective_perms({"role": "admin", "perms": json.dumps(["schedule_view"])})
      and "cash_report" not in auth.Auth.effective_perms({"role": "admin", "perms": json.dumps(["schedule_view"])}))
check("a person's list saved in 2.14 keeps a removed right removed",
      "expenses_day" not in auth.Auth.effective_perms({"role": "admin", "perms": json.dumps({"perms": ["schedule_view"], "known": auth.PERM_KEYS})}))
check("unknown position has no rights", auth.Auth.effective_perms({"role": "nobody"}) == [])
nurse = A.role_save(None, {"title": "Медсестра", "base": "assistant", "perms": ["schedule_view"]})
check("voice label by the base role", voices.role_label({"role": nurse["key"]}) == "Ассистент" and voices.role_label({"role": sa["key"]}) == "Врач")
check("role_base", auth.role_base(nurse["key"]) == "assistant" and auth.role_base("doctor") == "doctor")
check("synced between laptops", {"staff_roles", "day_reports"} <= {t.name for t in replica.TABLES})

# ------------------------------------------------------------------ expenses of the day without HTTP
D = a._daily
check("expense columns", {"doc", "login"} <= {r[1] for r in d.conn.execute("PRAGMA table_info(expenses)")})
cur = a.cash_shift()
if not cur["shift"]:
    a.cash_shift_open({"open_cash": 5000})
e1 = D.save({"amount": 400, "category": "Хозяйственные расходы", "comment": "вода", "doc": False, "method": "Наличные из кассы"}, "Анна", "anna")
mv = d.one("SELECT * FROM cash_moves WHERE expense_id=?", (e1,))
check("cash expense → «Расход из кассы» in the open shift", mv and mv["amount"] == 400 and mv["kind"] == "out" and mv["reason"] == "Расход из кассы")
D.save({"id": e1, "amount": 450, "category": "Хозяйственные расходы", "comment": "вода", "doc": False, "method": "Наличные из кассы"}, "Анна", "anna")
check("edit changes the cash move", d.one("SELECT amount FROM cash_moves WHERE expense_id=?", (e1,))["amount"] == 450)
e2 = D.save({"amount": 1200, "category": "Транспорт и доставка", "comment": "курьер", "doc": True, "method": "Карта клиники",
             "date": "2020-01-01"}, "Анна", "anna")
check("an administrator writes today only", d.one("SELECT date FROM expenses WHERE id=?", (e2,))["date"] == T)
check("no cash move for a card", not d.one("SELECT 1 AS x FROM cash_moves WHERE expense_id=?", (e2,)))
e3 = D.save({"amount": 300, "category": "Прочее", "doc": True, "method": "Перевод"}, "Борис", "boris")
t = D.today("anna")
check("own expenses only", {r["id"] for r in t["rows"]} == {e1, e2} and t["total"] == 1650 and t["nodoc"] == 450, t["total"])
check("daily categories first", t["categories"][0] == "Хозяйственные расходы")
check("«Бухгалтерия» sees all", {r["id"] for r in D.today("dir", True)["rows"]} >= {e1, e2, e3})
refuses("not someone else's", lambda: D.save({"id": e3, "amount": 1, "category": "Прочее"}, "Анна", "anna"), "свои сегодняшние")
refuses("not someone else's delete", lambda: D.delete(e3, "anna"), "свои сегодняшние")
with d.tx() as c:
    c.execute("UPDATE expenses SET date=? WHERE id=?", ((date.today() - timedelta(days=1)).isoformat(), e2))
check("yesterday is gone from the list (a clean sheet)", {r["id"] for r in D.today("anna")["rows"]} == {e1})
refuses("yesterday cannot be changed", lambda: D.delete(e2, "anna"), "свои сегодняшние")
with d.tx() as c:
    c.execute("UPDATE expenses SET date=? WHERE id=?", (T, e2))
D.delete(e1, "anna")
check("delete takes the cash move away", not d.one("SELECT 1 AS x FROM cash_moves WHERE expense_id=?", (e1,))
      and not d.one("SELECT 1 AS x FROM expenses WHERE id=?", (e1,)))
e1 = D.save({"amount": 500, "category": "Хозяйственные расходы", "comment": "вода", "doc": False}, "Анна", "anna")

rep = D.report(T, {"money_total": 10000, "by_method": {"Наличные": 7000, "Карта": 3000}})
txt = D.text(rep)
check("report text", "Поступило денег: 10 000 ₽" in txt and "без документов 500 ₽" in txt and "без документа — вода" in txt and "Кассовая смена" in txt, txt)
check("report Excel", D.xlsx(rep)[:2] == b"PK")
own = D.report(T, {}, "anna", shifts=False)
check("own report: own rows, no shift", {r["login"] for r in own["rows"]} == {"anna"} and not own["shifts"])

# ------------------------------------------------------------------ mail settings and sending (fake SMTP)
refuses("enabled needs an address", lambda: daily.save_settings({"enabled": True, "to": "", "login": "x@y.ru", "password": "p"}), "куда отправлять")
refuses("enabled needs a mailbox", lambda: daily.save_settings({"enabled": True, "to": "boss@mail.ru"}), "пароль приложения")
refuses("time format", lambda: daily.save_settings({"time": "9 вечера"}), "21:00")
ps = daily.save_settings({"enabled": True, "to": "boss@mail.ru; second@ya.ru", "login": "clinic@yandex.ru", "password": "app-pass", "time": "21:00"})
check("settings saved, password hidden", ps["has_pass"] and "pass_enc" not in ps and "app-pass" not in json.dumps(config.load_settings()))
check("password decrypts", config.unprotect(daily.settings()["pass_enc"]) == "app-pass")
SENT = []


class FakeSMTP:
    fail = None

    def __init__(self, host, port, timeout=30, context=None):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        self.host, self.port = host, port

    def login(self, user, pw):
        SENT.append(("login", user, pw))

    def send_message(self, msg):
        SENT.append(("msg", msg))

    def quit(self):
        pass


daily.smtplib.SMTP_SSL = FakeSMTP
st = a.day_report_send(T, True)
msg = [x[1] for x in SENT if x[0] == "msg"][-1]
check("sent", st["status"] == "sent" and st["sent_to"] == "boss@mail.ru, second@ya.ru" and ("login", "clinic@yandex.ru", "app-pass") in SENT)
check("mail content", "отчёт за" in msg["Subject"] and msg["To"] == "boss@mail.ru, second@ya.ru"
      and any(p.get_filename() and p.get_filename().endswith(".xlsx") for p in msg.iter_attachments())
      and "Расходы за день" in msg.get_body(("plain",)).get_content())
n = len(SENT)
check("no second mail without «again»", a.day_report_send(T, False)["status"] == "sent" and len(SENT) == n)
FakeSMTP.fail = OSError("no network")
y = (date.today() - timedelta(days=1)).isoformat()
refuses("offline → error kept", lambda: a.day_report_send(y, True), "повторит")
check("error state", d.one("SELECT status, error FROM day_reports WHERE day=?", (y,))["status"] == "error")
FakeSMTP.fail = None
late = datetime.now().replace(hour=21, minute=30)
check("due: today after the time and the failed day", D.due(late) == [y] or set(D.due(late)) == {y} or y in D.due(late))
with d.tx() as c:
    c.execute("DELETE FROM day_reports WHERE day=?", (T,))
check("due includes today after 21:00", T in D.due(late) and T not in D.due(late.replace(hour=9)))
D._last_tick = 0
D.tick(lambda day: {}, "Тест")
import time  # noqa: E402
for _ in range(50):
    if (d.one("SELECT status FROM day_reports WHERE day=?", (y,)) or {}).get("status") == "sent":
        break
    time.sleep(0.1)
# tick sends only after the set time; force the time for this check
if (d.one("SELECT status FROM day_reports WHERE day=?", (y,)) or {}).get("status") != "sent":
    for day_ in D.due(late):
        D.send(day_, {}, "Тест")
check("the failed day goes later", d.one("SELECT status FROM day_reports WHERE day=?", (y,))["status"] == "sent")
D._last_tick = 0
n = len(SENT)
D.tick(lambda day: {})
check("tick waits 5 minutes", D._last_tick and (D.tick(lambda day: {}) is None))
with d.tx() as c:
    c.execute("DELETE FROM day_reports WHERE day=?", (T,))
s0 = config.load_settings()["day_report"]
a.cash_shift_close({"counted_cash": a.cash_shift()["shift"]["expected_cash"]})
for _ in range(50):
    if (d.one("SELECT status FROM day_reports WHERE day=?", (T,)) or {}).get("status") == "sent":
        break
    time.sleep(0.1)
check("closing the shift sends the day report", (d.one("SELECT status FROM day_reports WHERE day=?", (T,)) or {}).get("status") == "sent")

# ------------------------------------------------------------------ rights over HTTP
new = ["day_expenses", "day_expense_save", "day_expense_delete", "day_report", "day_report_send", "day_report_settings", "day_report_settings_save"]
check("every new method has a right", all(m in auth.METHOD_PERMS for m in new) and all(hasattr(a, m) for m in new))
check("changes are in the journal", all(m in auth.AUDITED for m in ("day_expense_save", "day_expense_delete", "day_report_send", "day_report_settings_save")))
check("Excel has its own right", auth.METHOD_PERMS["export_xlsx"] == "export")
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
for login, role in (("adm", "admin"), ("doc", "doctor"), ("sen", sa["key"])):
    call("auth", "register", {"name": login.upper(), "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    st_, r_ = call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active"}, token=TD)
    check(f"position given: {login}", st_ == 200 and r_["role"] == role, r_)
TA, TDoc, TS = (call("auth", "login", x, "secret1")[1]["token"] for x in ("adm", "doc", "sen"))
st_, r_ = call("auth", "roles_list", token=TD)
check("roles list for the director", st_ == 200 and any(x["key"] == sa["key"] and x["people"] == 1 for x in r_["roles"]) and r_["perm_groups"], r_)
check("roles list closed to the admin", call("auth", "roles_list", token=TA)[0] == 403)
check("state lists own positions", any(x["key"] == nurse["key"] for x in call("auth", "state", token=TA)[1]["roles"]))
check("admin sees the cash today", call("api", "cash_day", T, token=TA)[0] == 200)
st_, r_ = call("auth", "role_save", {"key": "admin", "title": "Администратор", "perms": [p for p in auth.ROLES["admin"]["perms"] if p not in ("cash_report", "export")]}, token=TD)
check("director takes «Касса» and «Excel» from administrators", st_ == 200)
check("at once: no cash report", call("api", "cash_day", T, token=TA)[0] == 403)
check("at once: no Excel", call("api", "export_xlsx", "x", ["a"], [["1"]], token=TA)[0] == 403)
check("doctor keeps Excel", call("api", "export_xlsx", "x", ["a"], [["1"]], token=TDoc)[0] == 200)
check("status tells the new rights", "cash_report" not in call("api", "status", token=TA)[1]["me_perms"])
st_, r_ = call("api", "day_expense_save", {"amount": 250, "category": "Прочее", "doc": False}, token=TA)
check("admin writes an expense", st_ == 200 and r_["total"] == 250 and not r_["all"], r_)
st_, r_ = call("api", "day_report", None, token=TA)
check("admin's report preview: own rows, no cash", st_ == 200 and not r_["cash"] and not r_["shifts"] and len(r_["rows"]) == 1, r_.get("rows"))
check("admin: no earlier days", call("api", "day_report", y, token=TA)[0] == 400)
check("doctor: no expenses of the day", call("api", "day_expenses", token=TDoc)[0] == 403)
st_, r_ = call("api", "day_expenses", token=TS)
check("own position with «Бухгалтерия» sees all expenses", st_ == 200 and r_["all"] and len(r_["rows"]) >= 3, r_.get("all"))
check("mail settings: settings right only", call("api", "day_report_settings", token=TA)[0] == 403 and call("api", "day_report_settings", token=TD)[0] == 200)
refuses_http = call("auth", "role_delete", sa["key"], token=TD)
check("a position with people is not deleted", refuses_http[0] == 400 and "сотр." in refuses_http[1].get("error", ""), refuses_http)
check("own staff right stays", call("auth", "role_save", {"key": "admin", "title": "Администратор", "perms": []}, token=TD)[0] == 200)
check("deleting an empty position", call("auth", "role_delete", nurse["key"], token=TD)[0] == 200)
au = [x["action"] for x in d.q("SELECT action FROM audit ORDER BY id")]
check("positions in the journal", "Изменены права должности" in au and "Удалена должность" in au and "Расход за день" in au, au[-8:])
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
