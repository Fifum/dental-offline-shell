"""3.18: the whole program in the client's red and white mockup (media/client-refs/design-2026-11-28).

Only the look changes: the tokens of styles-type.css (red on white, red on graphite in the dark), and styles-skin.css,
loaded after every other sheet — the white menu, the solid red main button, white secondary buttons, red chosen tabs.
Static checks: nothing of the layout is touched there, the teal of 3.13–3.17 is gone, every page loads the sheets."""
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


UI = ROOT / "app" / "ui"
ui = lambda n: (UI / n).read_text(encoding="utf-8")  # noqa: E731
html, typ, skin = ui("index.html"), ui("styles-type.css"), ui("styles-skin.css")


def tokens(block):
    return dict(re.findall(r"--([\w-]+):\s*([^;}]+)", block))


light = tokens(typ[typ.index("red and white"):typ.index("@media screen")])
dark = tokens(typ[typ.index(':root[data-theme="dark"]{'):])

# ------------------------------------------------------------------ the sheets on the pages
links = re.findall(r'<link rel="stylesheet" href="([\w-]+\.css)\?v=([\d.]+)">', html)
names = [n for n, _ in links]
check("skin on the page with the version tag", f'<link rel="stylesheet" href="styles-skin.css?v={config.VERSION}">' in html)
check("skin is the last sheet, after the tokens", names[-1] == "styles-skin.css" and names[-2] == "styles-type.css", names[-3:])
check("every sheet of the page carries the version", all(v == config.VERSION for _, v in links), {v for _, v in links})
for page in ("setup.html", "offline.html"):
    src = ui(page)
    check(f"{page}: the red tokens and the skin, last", src.index("styles-type.css") > src.index("styles-theme.css")
          and src.index("styles-skin.css") > src.index("styles-type.css"))
check("the patients' tablet in the same red", "--accent:#D9262B" in ui("tablet.html"))

# ------------------------------------------------------------------ the palette
check("light: red accent and main button, white text on it", light.get("accent") == "#D9262B" and light.get("primary") == "#D9262B"
      and light.get("on-primary") == "#FFFFFF", light)
check("light: grey page, white cards and menu", light.get("bg") == "#F3F4F6" and light.get("panel") == "#FFFFFF" and light.get("side") == "#FFFFFF")
check("light: the chosen menu item light red", light.get("side-on") == "#FDEDED")
check("dark: red on graphite", dark.get("accent") == "#DC3439" and dark.get("bg") == "#111316" and dark.get("on-accent") == "#FFFFFF", dark)
check("dark: the menu is graphite, not white", dark.get("side") not in (None, "#FFFFFF"))
teal = re.compile(r"#(167C76|11645F|145F5C|2DB3A5|4FC5B8|3FB3A6|0E4F52|102A2C)", re.I)
check("no teal left in the tokens", not teal.search(typ), teal.findall(typ))
check("no teal in the sheets of the program", not any(teal.search(ui(f.name)) for f in UI.glob("styles*.css")))


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4 for x in c]
    return .2126 * c[0] + .7152 * c[1] + .0722 * c[2]


def contrast(a, b):
    a, b = lum(a), lum(b)
    return (max(a, b) + .05) / (min(a, b) + .05)


for name, t in (("light", light), ("dark", dark)):
    check(f"{name}: white text on the red button readable (AA)", contrast(t["on-primary"], t["primary"]) >= 4.5, contrast(t["on-primary"], t["primary"]))
    check(f"{name}: text on the cards readable", contrast(t["ink"], t["panel"]) >= 12 and contrast(t["muted"], t["panel"]) >= 4.5,
          (contrast(t["ink"], t["panel"]), contrast(t["muted"], t["panel"])))
    check(f"{name}: red text on its light red readable", contrast(t["accent-ink"], t["accent-soft"]) >= 4.5, contrast(t["accent-ink"], t["accent-soft"]))

# ------------------------------------------------------------------ the look, not the layout
rules = re.sub(r"/\*.*?\*/", "", skin, flags=re.S)
props = set(re.findall(r"[{;]\s*([a-z-]+)\s*:", rules))
layout = {"display", "position", "width", "height", "min-width", "max-width", "margin", "padding", "grid-template-columns", "flex",
          "flex-direction", "top", "left", "right", "bottom", "order", "gap"}
check("the skin moves nothing: no layout properties", not (props & layout), props & layout)
check("menu: white, the chosen item light red with a red mark", ".rail{background:var(--side)" in skin
      and ".rail .nav.active,.rail .nav.active:hover{background:var(--side-on);color:var(--accent-ink);box-shadow:inset 3px 0 0 var(--accent)" in skin)
check("menu: waves drawn in CSS, light and dark", skin.count("--rail-waves:url(\"data:image/svg+xml") == 2)
check("main button solid red, radius 8", ".btn{background:var(--primary);border-color:var(--primary);color:var(--on-primary);border-radius:8px" in skin)
check("secondary buttons white with an edge and a shadow", ".btn.ghost{background:var(--panel);color:var(--ink);border-color:var(--line);box-shadow:" in skin)
check("chosen switch and tabs red", ".seg button.on{background:var(--accent);color:var(--on-accent)" in skin and ".eqc-tabs button.on," in skin
      and "#stockTabs.eqnav>button.on" in ui("styles-eqsection.css"))
check("«исправно» stays green in the charts", ".eqs-ring circle.ok{stroke:var(--ok-chart)}" in skin)
check("hints are calm, not the red of a warning", ".hint-bar{background:var(--panel)" in skin)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
