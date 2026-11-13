"""Review 2026-11-13, group "ui": В5, В18, В19.

В5: «Что хранить» saves on its own — without the API login (computers that take the Dentist Plus data from the main one
have none since 3.7.2) and without the JSON of «Для специалиста»; an empty or non-numeric number is refused with a
Russian message instead of crashing int(''). В18: a click beside a dialog closes it only while nothing was typed in it.
В19: a save refreshes only the Dentist Plus fields, not every settings panel. The JS parts are checked statically."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import db as dbm  # noqa: E402
from main import Api  # noqa: E402

FAIL, OK = [], [0]
UI = ROOT / "app" / "ui"


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def raises(fn, *a, exc=Exception):
    try:
        fn(*a)
    except exc as e:
        return e
    return None


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


db = dbm.DB(config.DB_PATH)
api = Api(db, W())
AUTO = []
api._autostart_get = lambda: bool(AUTO and AUTO[-1])  # never touch the real Run key
api._autostart_set = lambda on: AUTO.append(on)
config.save_settings({"demo": False, "login": "", "days_back": 30, "day_start": 8, "day_end": 21})

# ------------------------------------------------------------------ В5: server side, numbers
for key, bad in (("days_back", ""), ("days_forward", "  "), ("interval_min", None), ("day_start", "abc"),
                 ("day_end", "9.5"), ("chunk_days", "1e3"), ("per_page", "")):
    e = raises(api.save_settings, {key: bad})
    check(f"{key}={bad!r}: ValueError, not a crash", isinstance(e, ValueError), repr(e))
    t = str(e or "")
    check(f"{key}={bad!r}: Russian message names the field", re.search("[А-Яа-я]", t) and "«" in t
          and ("Заполните" in t or "целое число" in t), t)
check("empty → «Заполните поле»", "Заполните поле «Дней назад»" in str(raises(api.save_settings, {"days_back": ""})))
check("text → «целое число»", "целое число" in str(raises(api.save_settings, {"day_start": "abc"})))
check("refused save wrote nothing", config.load_settings()["days_back"] == 30 and config.load_settings()["day_start"] == 8)
# a refused number refuses the whole save (nothing half-saved)
raises(api.save_settings, {"day_start": 7, "day_end": ""})
check("half-bad save writes nothing", config.load_settings()["day_start"] == 8)

# ------------------------------------------------------------------ В5: only the «Что хранить» fields, no login
store = {"days_back": " 45 ", "days_forward": "400", "interval_min": "7", "day_start": "9", "day_end": "20",
         "sync_all_patients": True, "autostart": True}
e = raises(api.save_settings, store)
check("store fields save without a login", e is None, repr(e))
s = config.load_settings()
check("store values saved as ints", (s["days_back"], s["days_forward"], s["interval_min"], s["day_start"], s["day_end"])
      == (45, 400, 7, 9, 20), s)
check("sync_all_patients saved", s.get("sync_all_patients") is True)
check("autostart applied", AUTO == [True], AUTO)
check("login untouched", s.get("login") == "" and not s.get("pass_enc"))
check("numbers from JS as numbers still pass", raises(api.save_settings, {"day_start": 10, "slot_min": 15.0}) is None)
check("numbers kept", config.load_settings()["day_start"] == 10 and config.load_settings()["slot_min"] == 15)

# ------------------------------------------------------------------ JS (static)
js = (UI / "app.js").read_text(encoding="utf-8")
html = (UI / "index.html").read_text(encoding="utf-8")


def body(src, start):
    """The text of the block that starts at `start` (up to its matching closing brace)."""
    i = src.index(start)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    return src[i:]


s2 = body(js, '$("#sSave2").onclick')
check("#sSave2 has its own handler", "saveSettings()" not in s2, s2[:200])
check("#sSave2: no login check", "sLogin" not in s2 and "логин" not in s2)
check("#sSave2: no JSON of «Для специалиста»", "JSON.parse" not in s2 and "sExtras" not in s2 and "sWriteMap" not in s2)
check("#sSave2: checks the numbers first", s2.index("badNumber(") < s2.index("api.save_settings"))
check("#sSave2: refreshes only «Что хранить»", 'fillDpSettings(s, ["store"])' in s2 and "loadSettings()" not in s2)
store_js = body(js, "const storeFields")
for k in ("days_back", "days_forward", "interval_min", "day_start", "day_end", "sync_all_patients", "autostart"):
    check(f"storeFields sends {k}", k + ":" in store_js)
for k in ("login", "password", "base_url", "demo", "patient_extras", "write_map"):
    check(f"storeFields does not send {k}", k not in store_js)
for id_ in re.findall(r'\$\("(#s\w+)"\)', store_js):
    panel = html[html.index("<h3>Что хранить</h3>"):html.index('id="sSave2"')]
    check(f"storeFields reads {id_} from «Что хранить»", f'id="{id_[1:]}"' in panel)
bn = body(js, "function badNumber")
check("badNumber: empty and non-integer", "Заполните поле" in bn and "целое число" in bn and "badInput" in bn)
ss = body(js, "async function saveSettings")
check("#sSave: numbers checked before JSON", ss.index("badNumber(") < ss.index("JSON.parse"))
check("#sSave: follower skips the login demand", re.search(r"!demo && !dpFollower\(\) && !\$\(\"#sLogin\"\)", ss) is not None)
check("dpFollower reads the role", re.search(r'const dpFollower = .*dp_main\.role === "follower"', js) is not None)
# В19: no full panel rebuild after a save
check("#sSave: no loadSettings()", "loadSettings()" not in ss and "fillDpSettings(s)" in ss)
demo = body(js, '$("#sDemo").onchange')
check("demo switch: no loadSettings()", "loadSettings()" not in demo and 'fillDpSettings(s, ["conn"])' in demo)
fill = body(js, "function fillDpSettings")
for f in ("loadFiscalSettings", "loadVoiceSettings", "loadBackupSettings", "loadMoneySettings", "loadDpSettings", "network_info"):
    check(f"fillDpSettings leaves {f} alone", f not in fill)
check("loadSettings still builds everything", all(f in body(js, "async function loadSettings")
                                                  for f in ("fillDpSettings(s)", "loadFiscalSettings", "loadMoneySettings")))
check("only loadSettings caller: opening the view", js.count("loadSettings();") == 1, js.count("loadSettings();"))

# В18: backdrop closes only an untouched dialog
md = body(js, 'document.getElementById("modal").addEventListener("mousedown"')
check("backdrop: asks when dirty", "_dirty" in md and "Закрыть без сохранения?" in md and "ask(" in md)
check("backdrop: still closes", "closeModal()" in md)
check("dirty mark on input and change", re.search(r'modalBox"\)\.addEventListener\("input"', js)
      and re.search(r'modalBox"\)\.addEventListener\("change"', js))
check("new dialog starts clean", "box._dirty = false" in js[js.index("function modal("):js.index("function closeModal(")])

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
