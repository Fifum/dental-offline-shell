"""«Отчёт для разработчика»: keeps the API shape, never leaks patient data, passwords or tokens."""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import config  # noqa: E402
import db as dbm  # noqa: E402
import devreport  # noqa: E402
import sync  # noqa: E402
from main import Api  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


SECRETS = ["Иванова", "Мария", "Петровна", "+7 (949) 123-45-67", "79491234567", "1985-03-14", "14.03.1985",
           "maria@mail.ru", "ул. Артёма, 12", "Аллергия на лидокаин", "Гусева Анна", "dp_login_42", "S3cretPass!",
           "eyJhbGciOiJIUzI1NiJ9.abc.def", "4510 123456", "1234567890"]

PATIENT = {"id": 15873, "lname": "Иванова", "fname": "Мария", "mname": "Петровна",
           "phone": "+7 (949) 123-45-67", "phone2": "79491234567", "birth_date": "1985-03-14",
           "birthday_ru": "14.03.1985", "email": "maria@mail.ru", "address": "ул. Артёма, 12",
           "comment": "Аллергия на лидокаин", "gender": "female", "status": "active", "balance": -1250.5,
           "passport": "4510 123456", "snils": "1234567890", "is_vip": False, "card": None,
           "doctor": {"id": 7, "name": "Гусева Анна"},
           "visits": [{"id": i, "start": "2026-11-07 10:30:00", "status": "completed"} for i in range(5)]}

# --- mask_value: structure kept, values hidden
m = devreport.mask_value(PATIENT)
dump = json.dumps(m, ensure_ascii=False)
check("keys kept", set(m) == set(PATIENT) and set(m["doctor"]) == {"id", "name"})
check("no personal data in masked", not [x for x in SECRETS if x in dump], [x for x in SECRETS if x in dump])
check("enum codes kept", m["gender"] == "female" and m["status"] == "active" and m["visits"][0]["status"] == "completed")
check("types shown", m["id"] == "<целое>" and m["balance"] == "<дробное>" and m["is_vip"] is False and m["card"] is None)
check("date format shown", m["visits"][0]["start"] == "<дата 9999-99-99 99:99:99>" and m["birthday_ru"] == "<дата 99.99.9999>")
check("phone and email", m["phone"] == "<телефон>" and m["email"] == "<email>")
check("text length", m["lname"] == "<текст, 7 симв.>", m["lname"])
check("lists sampled", len(m["visits"]) == 3 and m["visits"][2] == "<ещё 3>", m["visits"])

# --- scrub_text: log lines and error messages
line = ('2026-11-07 10:00:01 ERROR sync: ApiError: HTTP 422: lname: "Иванова Мария" phone +7 (949) 123-45-67 '
        'maria@mail.ru patient 15873 Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def password=S3cretPass!')
sc = devreport.scrub_text(line)
check("scrub keeps context", "ERROR sync" in sc and "HTTP 422" in sc and "lname" in sc, sc)
check("scrub removes data", not [x for x in SECRETS if x in sc], [x for x in SECRETS if x in sc])

# --- full report with a real-shaped API answer
d = dbm.DB()
config.save_settings({"demo": False, "login": "dp_login_42", "pass_enc": config.protect("S3cretPass!"), "transfer_mode": "manual"})
logging.getLogger("sync").error("push failed for Иванова Мария, tel 79491234567, token=eyJhbGciOiJIUzI1NiJ9.abc.def")
for h in logging.getLogger().handlers:
    h.flush()


def fake_diag(s):
    check("diag gets settings", s.get("login") == "dp_login_42")
    return {"auth": "OK",
            "patients": {"count_on_page": 3, "sample": [PATIENT], "envelope_keys": ["data", "meta"]},
            "visits": "Ошибка: HTTP 403 для visits — нет доступа у Гусева Анна",
            "patients/15873": {"data": PATIENT}}


sync.diagnostics = fake_diag
logging.basicConfig(filename=str(config.LOG_PATH), level=logging.INFO, encoding="utf-8", force=True)
logging.getLogger("sync").error("sync failed: Иванова Мария 79491234567 maria@mail.ru Bearer eyJhbGciOiJIUzI1NiJ9.abc.def")
logging.shutdown()

rep = devreport.build(d, {"online": True, "last_ok": "2026-11-07T09:00:00", "last_error": "HTTP 500 для Иванова Мария"})
txt = json.dumps(rep, ensure_ascii=False)
check("report has no personal data or secrets", not [x for x in SECRETS if x in txt], [x for x in SECRETS if x in txt])
check("report settings", rep["settings"]["login_set"] is True and rep["settings"]["password_set"] is True
      and rep["settings"]["transfer_mode"] == "manual" and "login" not in rep["settings"])
check("api probe kept", rep["api"]["auth"] == "OK" and rep["api"]["patients"]["count_on_page"] == 3
      and rep["api"]["patients"]["envelope_keys"] == ["data", "meta"], rep["api"])
check("api sample masked", rep["api"]["patients"]["sample"][0]["lname"] == "<текст, 7 симв.>")
check("api error scrubbed", rep["api"]["visits"].startswith("Ошибка: HTTP 403") and "Гусева" not in rep["api"]["visits"])
check("log tail present", any("sync failed" in x for x in rep["log_tail"]), rep["log_tail"][-3:])
check("counts present", "visits" in rep["counts"] and isinstance(rep["pending_transfer"], int))

# demo mode: no network
config.save_settings({"demo": True})
sync.diagnostics = lambda s: FAIL.append("demo must not call API") or {}
rep2 = devreport.build(d, {})
check("demo note", isinstance(rep2["api"], str) and "демо" in rep2["api"].lower())

# --- Api.dev_report writes the file to the Desktop
desk = tempfile.mkdtemp()
Api._desktop_dir = staticmethod(lambda: desk)


class W:
    def status(self): return {"running": False, "online": None}
    def trigger(self): pass


a = Api(d, W())
r = a.dev_report()
check("dev_report ok", r["ok"] and r["on_desktop"] and Path(r["path"]).parent == Path(desk), r.get("message"))
check("file on desktop", Path(r["path"]).exists() and json.loads(Path(r["path"]).read_text(encoding="utf-8"))["report"])
check("copy in data dir", (config.data_dir() / "reports" / r["name"]).exists())
check("file name", r["name"].startswith("Отчёт для разработчика ") and r["name"].endswith(".json"))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
