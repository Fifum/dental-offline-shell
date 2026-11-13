"""Review 2026-11-13, minors «ui»: stuck UI states on an exception (М22), the SBP QR not erased when its settings did not
load (М23), an untouched phone kept in mphone not queued as a change (М24), document templates substituted in one pass
(М25), offline copy dates parsed as local days (М26)."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import db as dbm  # noqa: E402
import main  # noqa: E402
from local import Local  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


UI = ROOT / "app" / "ui"
src = {n: (UI / n).read_text(encoding="utf-8") for n in ("app.js", "setup.html", "money.js", "docs.js", "offline.html")}
NODE = shutil.which("node")


def node(code, tz=None):
    env = dict(os.environ)
    if tz:
        env["TZ"] = tz
    r = subprocess.run([NODE, "-e", code], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    if r.returncode:
        FAIL.append(f"node failed: {r.stderr[-500:]}")
        return None
    return r.stdout.strip()


# ---------------------------------------------------------------- М24: phone in mphone
d = dbm.DB()
L = Local(d)
d.upsert_patients([{"id": "900", "lname": "Тестов", "fname": "Пётр", "mphone": "+79990001122", "gender": "male"}], detail=True)
pend = lambda: d.one("SELECT COUNT(*) AS n FROM patient_edits WHERE patient_id='900' AND transferred=0")["n"]  # noqa: E731
p = d.one("SELECT phone FROM patients WHERE id='900'")
check("М24 the card shows the phone from mphone", p and p["phone"] == "+79990001122", p)
r = L.edit_patient("900", {"lname": "Тестов", "fname": "Пётр", "mname": "", "phone": "+79990001122", "gender": "М",
                           "birth_date": "", "address": "", "email": ""})
check("М24 unchanged form (phone from mphone) -> nothing changed", r == {"changed": 0}, r)
check("М24 no phone change queued for «Перенос»", pend() == 0, pend())
r = L.edit_patient("900", {"phone": "+79990003344"})
row = d.one("SELECT data FROM patient_edits WHERE patient_id='900' AND transferred=0")
check("М24 a real phone change is still queued", r.get("changed") == 1 and row and json.loads(row["data"]) == {"phone": "+79990003344"},
      (r, row))
r = L.edit_patient("900", {"phone": "+79990003344"})
check("М24 the same phone again -> no change", r == {"changed": 0}, r)

# ---------------------------------------------------------------- М22: join with the port busy, stuck UI states
class FakeHost:
    def port(self): return 8765
    def start_server(self): raise OSError("address in use")


try:
    r = main.Setup(FakeHost()).join_clinic("c1")
except OSError as e:
    r = {"error": str(e)}
check("М22 join_clinic: busy port -> readable refusal, no exception", r.get("ok") is False and "порт" in r.get("message", ""), r)
a = src["app.js"]
check("М22 #sTest catches a failed test_connection", re.search(r'\$\("#sTest"\)\.onclick[\s\S]{0,400}?catch \(e\) \{ msg\(', a))
check("М22 #sDiag catches a failed diagnostics", re.search(r'\$\("#sDiag"\)\.onclick[\s\S]{0,300}?catch \(e\)', a))
check("М22 #netFw catches a failed allow_firewall", re.search(r"try \{ r = await pw\.allow_firewall\(\); \} catch", a))
s = src["setup.html"]
check("М22 setup: join has a busy guard", "if (joining) return;" in s and "finally { joining = false;" in s)
check("М22 setup: create_clinic failure re-enables #create", re.search(r"try \{ r = await api\.create_clinic\(\); \} catch", s))

# ---------------------------------------------------------------- М23: SBP not loaded -> not saved
m = src["money.js"]
check("М23 sbp_settings_save only when the SBP block loaded", re.search(r"if \(q\) await api\.sbp_settings_save\(", m)
      and "await api.sbp_settings_save({qr" not in m.replace("if (q) await api.sbp_settings_save(", ""))
check("М23 the failed SBP load is shown", "Не удалось загрузить настройки СБП" in m)

if NODE:
    for n in ("app.js", "money.js", "docs.js"):
        r = subprocess.run([NODE, "--check", str(UI / n)], capture_output=True, text=True)
        check(f"syntax {n}", r.returncode == 0, r.stderr[-300:])
    for n in ("setup.html", "offline.html"):  # inline scripts
        js = "\n".join(re.findall(r"<script>([\s\S]*?)</script>", src[n]))
        f = Path(tempfile.mkdtemp()) / (n + ".js")
        f.write_text(js, encoding="utf-8")
        r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
        check(f"syntax {n}", r.returncode == 0, r.stderr[-300:])

    # ------------------------------------------------------------ М25: one pass over the template
    stubs = r"""
const vm = require("vm"), fs = require("fs");
const ctx = {console, esc: v => String(v ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c])),
  fmtDate: s => String(s || ""), iso: d => d.toISOString().slice(0, 10), plural: (n, a, b, c) => c};
vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
"""
    code = stubs.replace("process.argv[1]", json.dumps(str(UI / "docs.js"))) + r"""
const out = ctx.renderDoc("A {{patient.fio}} {{table:records}} {{input:Зуб|}} {{input:Срок|}} {{today}}", {
  patient: {fio: "Иванов"}, doctor: {}, visit: {}, clinic: {name: "Клиника"},
  record: {}, records_full: [{date: "2026-11-01", doctor_name: "Врач", data: {complaints: "текст {{patient.fio}} {{input:x|}} {{clinic.name}} {{table:rx}}"}}],
}, ["16", "2 недели"]);
console.log(JSON.stringify(out));
"""
    out = node(code)
    if out:
        out = json.loads(out)
        check("М25 record text keeps its {{…}} as typed", "текст {{patient.fio}} {{input:x|}} {{clinic.name}} {{table:rx}}" in out, out)
        check("М25 inputs go to the template's own fields in order", "Иванов" in out and " 16 " in out and "2 недели" in out
              and out.count("Иванов") == 1, out)

    # ------------------------------------------------------------ М26: local days in the offline copy
    pd = re.search(r"const parseDay = [^\n]*", src["offline.html"])
    code = (pd.group(0) if pd else "const parseDay = s => new Date(s);") + r"""
const pad = n => String(n).padStart(2, "0");
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const d = parseDay("2026-03-01"); const x = parseDay("2026-03-01"); x.setDate(x.getDate() + 1);
console.log(JSON.stringify([d.getDate(), d.getDay(), iso(x)]));
"""
    for tz in ("America/New_York", "Asia/Vladivostok"):
        out = node(code, tz)
        check(f"М26 parseDay is a local day ({tz})", out and json.loads(out) == [1, 0, "2026-03-02"], out)
else:
    print("node not found: the JS checks are skipped")
o = src["offline.html"]
check("М26 no UTC parsing of a bare date left", "new Date(S.day)" not in o and "new Date(b.slice(0, 10))" not in o)

print("\n".join("FAIL: " + f for f in FAIL))
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
sys.exit(1 if FAIL else 0)
