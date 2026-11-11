"""3.2: the «Надстройка над Dentist Plus» mode (stage 0 of the add-on plan).

Checks: the setting and its default (also for an existing installation without the key), what the UI is told,
which document templates are official / draft / internal, hiding official ones, the director-only switch, that the
hidden SaaS methods stay callable (the decision: hide in the UI, block nothing), and the UI wiring: labels, hidden
panels, the clinic network and updates left visible. With the mode off everything is as before."""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT / "app"))
import addon  # noqa: E402
import auth  # noqa: E402
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


def raises(fn, *a, exc=ValueError):
    try:
        fn(*a)
    except exc as e:
        return str(e)
    return None


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


def ui(name):
    return (UI / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ the setting and its default
check("default on", config.DEFAULT_SETTINGS.get("addon_mode") is True)
check("docs default mark", config.DEFAULT_SETTINGS.get("addon_docs") == "mark")
check("version 3.2.0 or later", tuple(map(int, config.VERSION.split("."))) >= (3, 2, 0), config.VERSION)
# an existing installation: settings.json written by 3.1 without the new keys
config.SETTINGS_PATH.write_text(json.dumps({"demo": True, "login": "", "transfer_mode": "manual"}), encoding="utf-8")
check("old install: on", addon.enabled() is True)
check("old install: mark", addon.docs_mode() == "mark")
check("bad docs value falls back", addon.docs_mode({"addon_docs": "zzz"}) == "mark")

db = dbm.DB(config.DB_PATH)
api = Api(db, W())
PID = api.create_patient({"lname": "Иванов", "fname": "Иван", "phone": "+79001112233"})["id"]

ui0 = api.ui_settings()
check("ui_settings has mode", ui0.get("addon_mode") is True and ui0.get("addon_docs") == "mark", ui0)
check("ui_settings official list", {"doc_contract", "doc_consent_treatment", "doc_card043", "taxcert"} <= set(ui0["addon_official"]))
check("ui_settings draft list", set(ui0["addon_draft"]) == {"doc_recipe", "doc_referral"})
check("ui_settings notes", "Dentist Plus" in ui0["addon_notes"]["official"] and "черновик" in ui0["addon_notes"]["draft"].lower())
check("status has mode", api.status().get("addon", {}).get("addon_mode") is True)
gs = api.get_settings()
check("get_settings keeps the lists", gs.get("addon_mode") is True and "doc_contract" in gs.get("addon_official", []))

# ------------------------------------------------------------------ document templates
kinds = {t["id"]: t.get("addon_kind") for t in api.templates("document")}
check("all builtin docs listed", {"doc_contract", "doc_memo", "doc_plan", "doc_anketa", "doc_recipe"} <= set(kinds), sorted(kinds))
for tid in ("doc_contract", "doc_consent_treatment", "doc_consent_pd", "doc_card043", "doc_extract", "doc_refusal", "doc_visit_note"):
    check(f"official {tid}", kinds.get(tid) == "official", kinds.get(tid))
for tid in ("doc_recipe", "doc_referral"):
    check(f"draft {tid}", kinds.get(tid) == "draft", kinds.get(tid))
for tid in ("doc_memo", "doc_plan", "doc_anketa", "doc_receipt", "doc_consent_recording", "doc_act"):
    check(f"internal {tid}", kinds.get(tid) == "internal", kinds.get(tid))
other = [t for t in api.templates("exam")][:1]
check("exam templates untouched", other and "addon_kind" not in other[0])
check("all templates still 4 kinds", {t["kind"] for t in api.templates()} >= {"document", "phrase", "exam", "drug"})
n_all = len(api.templates("document"))

# ------------------------------------------------------------------ the switch: director only
auth.set_current_user({"role": "admin", "login": "adm", "name": "Админ"})
err = raises(api.save_settings, {"addon_mode": False})
check("admin may not switch", err and "директор" in err, err)
check("admin: still on", addon.enabled() is True)
check("admin: same value passes", raises(api.save_settings, {"addon_mode": True, "day_start": 9}) is None)
check("admin: other settings saved", config.load_settings()["day_start"] == 9)
err = raises(api.save_settings, {"addon_docs": "hide"})
check("admin may not hide docs", err and "директор" in err, err)
auth.set_current_user({"role": "director", "login": "dir", "name": "Директор"})
check("bad docs value refused", raises(api.save_settings, {"addon_docs": "burn"}) is not None)

# hide the official ones
api.save_settings({"addon_docs": "hide"})
check("saved hide", config.load_settings()["addon_docs"] == "hide")
ids = {t["id"] for t in api.templates("document")}
check("official hidden", not ids & set(addon.OFFICIAL_DOCS), ids & set(addon.OFFICIAL_DOCS))
check("internal stay", {"doc_memo", "doc_plan", "doc_anketa", "doc_recipe"} <= ids)
check("hidden count", len(ids) == n_all - len(addon.OFFICIAL_DOCS), (len(ids), n_all))
check("taxcert hidden flag", api.ui_settings()["addon_taxcert_hidden"] is True)
check("hidden template still fillable", api.doc_context(PID) is not None)
api.save_settings({"addon_docs": "mark"})
check("back to mark", len(api.templates("document")) == n_all and api.ui_settings()["addon_taxcert_hidden"] is False)

# ------------------------------------------------------------------ SaaS stays callable (decision: hidden, not blocked)
st = api.cloud_status()
check("cloud_status works", isinstance(st, dict) and st.get("configured") is False, st)
csv_text = "ФИО;Телефон;Дата рождения\nИванов Иван Иванович;+79001112233;01.02.1980\n"
pv = api.import_preview("base.csv", base64.b64encode(csv_text.encode("utf-8")).decode())
check("import_preview works", isinstance(pv, dict) and pv, pv)
for m in ("cloud_join", "cloud_code", "cloud_leave", "import_run", "import_dp_all", "taxcert_data", "taxcert_issue",
          "p2p_status", "update_status"):
    check(f"method kept {m}", callable(getattr(api, m, None)))
check("taxcert_data works", isinstance(api.taxcert_data(PID, 2025), dict))
check("update_status works", "configured" in api.update_status())

# ------------------------------------------------------------------ mode off: as before
api.save_settings({"addon_mode": False})
check("saved off", config.load_settings()["addon_mode"] is False and addon.enabled() is False)
u = api.ui_settings()
check("off: no lists", u["addon_mode"] is False and u["addon_official"] == [] and u["addon_draft"] == [])
check("off: all internal", all(t.get("addon_kind") == "internal" for t in api.templates("document")))
api.save_settings({"addon_docs": "hide"})
check("off + hide: nothing hidden", len(api.templates("document")) == n_all)
check("off + hide: taxcert shown", api.ui_settings()["addon_taxcert_hidden"] is False)
api.save_settings({"addon_mode": True, "addon_docs": "mark"})
check("on again", addon.enabled() is True)
auth.set_current_user(None)
check("no user (desktop window) may switch", raises(api.save_settings, {"addon_mode": True}) is None)

# ------------------------------------------------------------------ UI wiring
html = ui("index.html")
check("addon.js loaded", f'<script src="addon.js?v={config.VERSION}"></script>' in html)
check("addon.js before settings-nav", html.index("addon.js") < html.index("settings-nav.js"))
check("cache keys bumped", "?v=3.0.0" not in html)
check("settings panel", 'id="addonPanel"' in html and 'id="addonBody"' in html)
check("cloud panel is SaaS", re.search(r'id="cloudPanel"[^>]*data-saas', html))
check("updates stay", not re.search(r'id="updatePanel"[^>]*data-saas', html))
check("network stays", 'id="netBox"' in html and html.count("data-saas") == 1, html.count("data-saas"))
check("patients labelled", re.search(r"<h1>Пациенты<span class=\"dp-src\"", html))
check("schedule labelled", re.search(r'id="dayTitle">Расписание</h1><span class="dp-src"', html))
plat = ui("platform.js")
check("IDENT file import is SaaS", 'pl-file" data-saas' in plat)
check("DP full download stays", 'id="impDp"' in plat and "impDp\" data-saas" not in plat)
check("cloud kept when configured", "saas-keep" in plat)
app = ui("app.js")
check("mode applied at start", "applyAddon()" in app and "addonStatus(st)" in app and "loadAddonPanel()" in app)
check("records tab draft", 'dpDraft("Перенесите запись' in app)
check("print menu official", app.count("data-official-doc") >= 6, app.count("data-official-doc"))
check("card043 official", 'data-tpl="doc_card043" data-official-doc' in app)
check("visit drawer source", 'dpSrc("Запись на приём")' in app)
check("record editor draft", "dpDraft(" in ui("record.js"))
check("dictation / visit recording draft", "dpDraft()" in ui("dictate.js"))
check("AI record check draft", "dpDraft(" in ui("ai.js"))
refs = ui("refs.js")
check("visit templates draft", 'dpDraft("Шаблон приёма' in refs)
check("price from DP", 'dpSrc("Услуги и цены")' in refs)
check("template list tag", "docKindTag(t.id)" in refs)
docs = ui("docs.js")
check("doc picker tag", "${docKindTag(t.id)}" in docs)
check("doc fill line", "${docKindLine(tpl.id)}" in docs and "${docKindLine(d.template_id)}" in docs)
check("printed foot", "printDoc(page.innerHTML, tpl.id)" in docs and "addonPrintFoot(tid)" in docs)
check("taxcert official", 'addonDocKind("taxcert")' in ui("taxcert.js") and 'printDoc(r.html, "taxcert")' in ui("taxcert.js"))
css = ui("styles-platform.css")
check("css hides SaaS", "body.addon [data-saas]:not(.saas-keep){display:none!important}" in css)
check("css hides official docs", "body.addon-hide-docs [data-official-doc]{display:none!important}" in css)
check("css labels only in the mode", ".dp-src,.dp-draft,.dp-official,.dp-doc-tag,.dp-print-foot{display:none}" in css)
check("search skips hidden panels", 'p.matches("[data-saas]:not(.saas-keep)")' in ui("settings-nav.js"))
for f in ("app.js", "refs.js", "record.js", "dictate.js", "ai.js", "taxcert.js"):  # the page still opens without addon.js
    t = ui(f)
    calls = len(re.findall(r"\b(?:dpDraft|dpSrc|dpOfficial|addonDocKind)\(", t))
    guarded = len(re.findall(r'typeof (?:dpDraft|dpSrc|dpOfficial|addonDocKind) === "function"', t))
    check(f"{f}: helpers guarded", calls and guarded * 2 >= calls, (calls, guarded))

# ------------------------------------------------------------------ addon.js logic in node (when node is installed)
node = shutil.which("node")
if node:
    probe = Path(tempfile.mkdtemp()) / "probe.js"
    probe.write_text("""
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
const cls = new Set(); const document = {body: {classList: {toggle: (c, on) => on ? cls.add(c) : cls.delete(c), contains: c => cls.has(c)}}};
const $ = () => null, $$ = () => [];
var S = {settings: %s};
%s
const out = {};
applyAddon(); out.on = [...cls].sort();
out.contract = addonDocKind("doc_contract"); out.recipe = addonDocKind("doc_recipe"); out.memo = addonDocKind("doc_memo");
out.tax = addonDocKind("taxcert"); out.foot = addonPrintFoot("doc_contract"); out.footMemo = addonPrintFoot("doc_memo");
out.src = dpSrc("Пациенты"); out.draft = dpDraft();
S.settings.addon_docs = "hide"; applyAddon(); out.hide = [...cls].sort();
S.settings = {addon_mode: false, addon_official: [], addon_draft: []}; applyAddon(); out.off = [...cls].sort();
out.offContract = addonDocKind("doc_contract"); out.offFoot = addonPrintFoot("doc_contract");
addonStatus({addon: %s}); out.live = [...cls].sort();
console.log(JSON.stringify(out));
""" % (json.dumps(api.ui_settings(), ensure_ascii=False), ui("addon.js"), json.dumps(api.ui_settings(), ensure_ascii=False)),
        encoding="utf-8")
    r = subprocess.run([node, str(probe)], capture_output=True, text=True, encoding="utf-8")
    try:
        o = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        o = {}
        FAIL.append(f"node probe failed: {r.stderr[-400:]}")
    if o:
        check("js: on", o["on"] == ["addon"], o["on"])
        check("js: kinds", (o["contract"], o["recipe"], o["memo"], o["tax"]) == ("official", "draft", "internal", "official"), o)
        check("js: printed foot", "контролирующих" in o["foot"] and o["footMemo"] == "", o["foot"])
        check("js: labels", "из Dentist Plus" in o["src"] and "Черновик для Dentist Plus" in o["draft"])
        check("js: hide", o["hide"] == ["addon", "addon-hide-docs"], o["hide"])
        check("js: off", o["off"] == [] and o["offContract"] == "internal" and o["offFoot"] == "", o)
        check("js: switched back from status", o["live"] == ["addon"], o["live"])
else:
    print("node not found — the addon.js probe skipped")

print(f"OK: {OK[0]}, FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
