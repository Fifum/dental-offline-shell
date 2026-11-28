"""3.17.2: «money is not a function» in «Редактировать» of a piece of equipment, and the popup menus pinned to their buttons.

The form of the equipment kept «can see money» in a local `money`, so its hint «в месяц …» called a boolean instead of the
helper of app.js and the page showed the error. Now no screen script hides a helper of app.js behind a local name.
The menus («⋮» of the cards, «Ещё», the bell, «Период», «.dd», the user's menu, the nurse's row menu, the medical record's
menu) are placed by one popOpen(): under the button, by its edge, turned up or the other way at the window's edge, never out
of the window; the geometry of popPlace() is run in node."""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "ui"
FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


src = {f.name: f.read_text(encoding="utf-8") for f in sorted(UI.glob("*.js"))}
app = src["app.js"]

# ---- 1. no local name hides a helper of app.js (the cause of «money is not a function»)
HELPERS = ["money", "esc", "toast", "plural", "fmtDate", "fmtDT", "fmtShort", "errText", "ask", "askInput", "modal",
           "closeModal", "api", "can", "canAny", "iso", "pad", "hm", "busy", "popOpen", "popPlace", "ddToggle"]
allsrc = "\n".join(src.values())
for h in HELPERS:
    check(f"helper {h} is global in the screen scripts",
          re.search(rf"^(?:const|let|(?:async\s+)?function)\s+{h}\b", allsrc, re.M) or h == "api", h)
shadows = []
for name, s in src.items():
    if name == "theme.js":  # runs before app.js: its `api` is the window's bridge, read on purpose
        continue
    for i, line in enumerate(s.split("\n"), 1):
        if not line.startswith((" ", "\t")):
            continue
        for m in re.finditer(r"(?:\b(?:const|let|var)\s+|,\s*)([A-Za-z_$][\w$]*)\s*=(?![=>])", line):
            if m[1] in HELPERS:
                shadows.append(f"{name}:{i} {m[1]}")
        for m in re.finditer(r"\(\s*([A-Za-z_$][\w$]*(?:\s*,\s*[A-Za-z_$][\w$]*)*)\s*\)\s*=>", line):
            for p in re.split(r"\s*,\s*", m[1]):
                if p in ("money", "esc", "toast", "plural", "api", "modal"):
                    shadows.append(f"{name}:{i} parameter {p}")
check("no screen script hides a helper of app.js behind a local name", not shadows, shadows[:10])
eq = src["stock-eqcard.js"]
form = eq[eq.index("async function editEquipment("):]
form = form[:form.index("\n}\n")]
check("the equipment form keeps «can see money» in withMoney", "const withMoney = isNew ? !!STK.eq_money : !!e.money" in form)
check("its hint «в месяц» calls the money helper", "в месяц ${money(Math.max(0, p - sv) / n)}" in form)
check("the card keeps the flag in withMoney too", "withMoney = !!e.money" in eq and not re.search(r"\bmoney = !!", eq))

# ---- 2. every popup menu is opened by popOpen()
def body(s, head):
    i = s.index(head)
    return s[i:s.index("\n}\n", i)]


OPENERS = [("stock-eqcard.js", "function eqMoreMenu(", 'popOpen(m, btn, {align: "end"})'),
           ("stock-matcard.js", "function mtCodesMenu(", 'popOpen(menu, btn, {align: "end"})'),
           ("stock-matcard.js", "function mtMoreMenu(", 'popOpen(menu, btn, {align: "end"})'),
           ("stock-eqsection.js", "function eqNavWire(", 'popOpen(m, b, {align: "end"})'),
           ("stock-eqsection.js", "function eqNavWire(", 'popOpen(bm, bb, {align: "end"})'),
           ("stock-eqsection.js", "function eqPeriodWire(", 'popOpen(pop, b, {align: "end"})'),
           ("stock-nurse.js", "function snMoreMenu(", 'popOpen(menu, btn, {align: "end", gap: 4})'),
           ("record.js", "function recDocMenu(", 'popOpen(m, btn, {align: "start", prefer: "up"})'),
           ("app.js", "function ddToggle(", "popOpen($(\".dd-menu\", dd), $(\".dd-btn\", dd)")]
for f, head, call in OPENERS:
    check(f"{f} {head} pins its menu with popOpen", call in body(src[f], head), call)
check("the «⋮» menus: a second click on the icon inside the button closes them",
      all("!btn.contains(ev.target)" in body(src[f], h) for f, h in [("stock-eqcard.js", "function eqMoreMenu("),
                                                                      ("stock-matcard.js", "function mtCodesMenu("),
                                                                      ("stock-matcard.js", "function mtMoreMenu(")]))
dd_openers = re.findall(r'\bdd\w*\.classList\.(?:add|toggle)\("open"\)', allsrc)
check("every «.dd» opens through ddToggle", not dd_openers and app.count("ddToggle(dd)") >= 2
      and "ddToggle(ddT)" in src["tpl-editor.js"], dd_openers)
check("the user's menu is pinned to its button", 'popOpen(m, e.currentTarget, {align: "end"})' in app)
css = (UI / "styles-responsive.css").read_text(encoding="utf-8")
check("the popups are fixed to the window (no frame cuts them)",
      ".dd-menu,.eqc-menu,.eqnav-menu,.eqs-perpop,.sn-menu,.rec-dmenu,.user-menu{position:fixed;max-width:calc(100vw - 16px)}" in css)
check("they follow the button while anything scrolls and when the window changes",
      'addEventListener("scroll", popsFollow, {capture: true, passive: true})' in app and 'addEventListener("resize", popsFollow)' in app)

# ---- 2b. monitors of any width: bars of tabs keep one line, wide tables scroll inside their frame
fit = body(app, "function tabsFit(")
check("tabsFit: the open tab stays on the bar", 'if (tabs[i].classList.contains("on")) continue;' in fit)
check("tabsFit: a tab in «Ещё» clicks the tab it stands for", "const t = tabs[+x.dataset.fit]; if (t) t.click();" in fit)
check("tabsFit: fitted again when the window changes size", "FIT_BARS.forEach(b => { if (!b.isConnected) FIT_BARS.delete(b); else tabsFit(b); })" in app)
stock_js = src["stock.js"]
check("the stock, equipment and inventory bars are fitted (the equipment's into its own «Ещё»)",
      'tabsFit(tabs, a.more ? $("#eqMoreMenu") : null)' in body(stock_js, "function stockHead(")
      and 'tabsFit($("#stockTabs"))' in body(stock_js, "function stockSetTab("))
check("the patient card's tabs are fitted", 'tabsFit($("#patientCard .tabs"))' in app)
resp = src["responsive.js"]
check("a table wider than its frame scrolls inside it at any width",
      'box.classList.toggle("x", t.offsetWidth > box.clientWidth + 1)' in resp and "requestAnimationFrame(fit)" in resp
      and ".tbl-scroll.x{overflow-x:auto}" in css and ".tbl-scroll.x>.tbl th{position:static}" in css)
check("the narrow menu hides the two-line «Склад и материалы» too",
      '@media (max-width:1180px){.rail .nav[data-view="stock"] span{display:none}}' in css
      and '.app.rail-mini .rail .nav[data-view="stock"] span{display:none}' in css)
eqcss = (UI / "styles-eqcard.css").read_text(encoding="utf-8")
check("the tabs of a card fit a narrow column", ".eqc-main{container-type:inline-size}" in eqcss and "@container (max-width:780px)" in eqcss)

# ---- 3. the geometry of popPlace(), run in node with a tiny window
geo = app[app.index("function popPlace("):app.index("/** Shows a popup by its button")]
JS = r"""
const fs = require("fs"), vm = require("vm");
const code = fs.readFileSync(process.argv[2], "utf8");
function run({vw = 1600, vh = 900, a, w, h, o = {}, cb = [0, 0], clip = null}) {
  const pop = {isConnected: true, style: {}, offsetWidth: w, parentNode: {insertBefore() {}}, up: null,
               classList: {toggle(c, v) { pop.up = v; }}};
  Object.defineProperty(pop, "offsetHeight", {get() { return pop.style.maxHeight ? Math.min(h, parseFloat(pop.style.maxHeight)) : h; }});
  const r = {left: a[0], top: a[1], right: a[2], bottom: a[3], width: a[2] - a[0], height: a[3] - a[1]};
  const frame = clip ? {getBoundingClientRect: () => ({left: clip[0], top: clip[1], right: clip[2], bottom: clip[3]}), parentElement: null} : null;
  const anchor = {isConnected: true, getBoundingClientRect: () => r, parentElement: frame};
  const ctx = {document: {documentElement: {clientWidth: vw, clientHeight: vh}, body: {},
                          createElement: () => ({style: {}, getBoundingClientRect: () => ({left: cb[0], top: cb[1]}), remove() {}})},
               getComputedStyle: el => el === frame ? {overflowX: "auto", overflowY: "auto"} : {overflowX: "visible", overflowY: "visible"}};
  vm.createContext(ctx); vm.runInContext(code, ctx);
  ctx.popPlace(pop, anchor, o);
  const s = pop.style;
  return {left: parseFloat(s.left), top: parseFloat(s.top), maxHeight: s.maxHeight || "", up: pop.up, hidden: s.visibility === "hidden"};
}
console.log(JSON.stringify({
  more: run({a: [1013, 241, 1053, 281], w: 273, h: 167, o: {align: "end"}}),
  leftEdge: run({a: [10, 100, 50, 140], w: 250, h: 160, o: {align: "end"}}),
  rightEdge: run({a: [1500, 100, 1590, 140], w: 250, h: 160, o: {align: "start"}}),
  bottom: run({a: [700, 820, 760, 860], w: 220, h: 200, o: {align: "end"}}),
  tall: run({vh: 700, a: [700, 300, 760, 340], w: 220, h: 900, o: {align: "end"}}),
  wide: run({vw: 300, a: [100, 100, 140, 140], w: 400, h: 100, o: {align: "end"}}),
  moved: run({a: [1013, 241, 1053, 281], w: 273, h: 167, o: {align: "end"}, cb: [100, 50]}),
  above: run({a: [400, 500, 480, 530], w: 200, h: 120, o: {align: "start", prefer: "up"}}),
  aboveNoRoom: run({a: [400, 60, 480, 90], w: 200, h: 120, o: {align: "start", prefer: "up"}}),
  scrolledAway: run({a: [400, 500, 480, 530], w: 200, h: 120, o: {}, clip: [0, 0, 1600, 450]})
}));
"""
tmp = Path(tempfile.mkdtemp())
(tmp / "geo.js").write_text(geo, encoding="utf-8")
(tmp / "run.js").write_text(JS, encoding="utf-8")
r = subprocess.run(["node", str(tmp / "run.js"), str(tmp / "geo.js")], capture_output=True, text=True, encoding="utf-8")
try:
    g = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    g = None
    FAIL.append(f"node: {r.stdout[-400:]} {r.stderr[-800:]}")
if g:
    m = g["more"]
    check("«⋮»: under the button, right edges together", m["left"] == 1053 - 273 and m["top"] == 281 + 6 and not m["up"], m)
    m = g["leftEdge"]
    check("at the left edge it opens to the right", m["left"] == 10 and m["top"] == 146, m)
    m = g["rightEdge"]
    check("at the right edge it opens to the left", m["left"] == 1590 - 250, m)
    m = g["bottom"]
    check("at the bottom it opens upwards", m["up"] and m["top"] == 820 - 6 - 200, m)
    m = g["tall"]
    check("a menu taller than the room scrolls inside", m["maxHeight"] and m["top"] >= 8 and m["top"] + float(m["maxHeight"][:-2]) <= 700 - 8, m)
    m = g["wide"]
    check("a menu wider than the window starts at its edge", m["left"] == 8, m)
    m = g["moved"]
    check("inside a moved frame (a drawer) it still stands by the button", m["left"] == 1053 - 273 - 100 and m["top"] == 287 - 50, m)
    m = g["above"]
    check("the medical record's menu opens above its button", m["up"] and m["top"] == 500 - 6 - 120 and m["left"] == 400, m)
    m = g["aboveNoRoom"]
    check("…and under it when there is no room above", not m["up"] and m["top"] == 96, m)
    check("a button scrolled out of its frame hides its menu", g["scrolledAway"]["hidden"], g["scrolledAway"])

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
