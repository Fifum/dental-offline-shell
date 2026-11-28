"""3.18.2: text stays inside its box on every monitor, and the label of a material is its QR alone.

«63 пара/мес.» ran over the edge of its tile in the material card: the column of a tile grew with its number. Now the column
cannot grow wider than the tile, and fitNumbers() (responsive.js) makes a tile's number smaller until it fits — down to 65 %
of its size — and only then lets it wrap between words. The geometry of fitOne() is run in node on a model of the element.
The sticker 40 × 30 mm of a material carries the QR only (the number, the name and the barcode crowded it and the barcode
ran over the text)."""
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


resp = (UI / "responsive.js").read_text(encoding="utf-8")
css = (UI / "styles-responsive.css").read_text(encoding="utf-8")
eqcss = (UI / "styles-eqcard.css").read_text(encoding="utf-8")
mat = (UI / "stock-matcard.js").read_text(encoding="utf-8")
index = (UI / "index.html").read_text(encoding="utf-8")

# ---- 1. the numbers of the tiles fit
check("fitNumbers covers the tiles of the cards, the sections, the stats and the stock's side",
      all(s in resp for s in (".eqc-tile>b", ".eqs-tile>b", ".stat>b", ".sn-st>b")) and "const FIT_NUMS" in resp)
check("…measured again on a resize of the tile, a new number and the fonts", "ResizeObserver" in resp and "characterData: true" in resp
      and "document.fonts.ready" in resp)
check("the column of a tile cannot grow wider than the tile", ".eqc-tile,.eqs-tile{grid-template-columns:auto minmax(0,1fr)}" in css)
check("a number that still does not fit wraps between words", "b.fit-wrap{white-space:normal;overflow-wrap:anywhere" in css)
check("responsive.js is loaded", "responsive.js?v=" in index)

m = re.search(r"const fitOne = el => \{.*?\n  \};", resp, re.S)
check("fitOne found", bool(m))
JS = r"""
const fitOne = eval("(" + require("fs").readFileSync(process.argv[2], "utf8").replace(/^const fitOne = /, "").replace(/;\s*$/, "") + ")");
// a model of a tile's number: the text is `chars` wide per pixel of the font; the box is `box` px wide
const make = (chars, box, base) => {
  const cls = new Set();
  const el = {style: {fontSize: ""}, isConnected: true, clientWidth: box, base,
    classList: {add: c => cls.add(c), remove: c => cls.delete(c), has: c => cls.has(c)},
    get scrollWidth() { const fs = parseFloat(this.style.fontSize) || base; return cls.has("fit-wrap") ? box : Math.max(box, Math.ceil(chars * fs)); }};
  return el;
};
global.getComputedStyle = el => ({fontSize: (el.style.fontSize || el.base + "px")});
const run = (chars, box, base) => { const el = make(chars, box, base); fitOne(el); return {fs: parseFloat(el.style.fontSize) || base, wrap: el.classList.has("fit-wrap"), w: Math.ceil(chars * (parseFloat(el.style.fontSize) || base))}; };
console.log(JSON.stringify({
  fits: run(5, 140, 21),         // «0 пара»: as it is
  little: run(7, 120, 21),       // «63 пара/мес.» in a tile of 1366 px: a bit smaller
  much: run(14, 120, 21),        // a very long number: 65 % and wraps
  again: (() => { const el = make(7, 120, 21); fitOne(el); el.clientWidth = 300; fitOne(el); return parseFloat(el.style.fontSize) || 21; })()
}));
"""
if m:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "fit.js").write_text(m.group(0), encoding="utf-8")
    (tmp / "run.js").write_text(JS, encoding="utf-8")
    r = subprocess.run(["node", str(tmp / "run.js"), str(tmp / "fit.js")], capture_output=True, text=True, encoding="utf-8")
    try:
        g = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        g = None
        FAIL.append(f"node: {r.stdout[-400:]} {r.stderr[-800:]}")
    if g:
        check("a number that fits keeps its size", g["fits"]["fs"] == 21 and not g["fits"]["wrap"], g["fits"])
        x = g["little"]
        check("a number a bit too wide gets smaller and fits", 21 * .65 <= x["fs"] < 21 and x["w"] <= 121 and not x["wrap"], x)
        x = g["much"]
        check("a very long number stops at 65 % and wraps", abs(x["fs"] - 13.7) < .05 and x["wrap"], x)
        check("a wider tile gives the number its size back", g["again"] == 21, g["again"])

check("«Остаток по местам»: the places above the lots in a narrow card", "@container (max-width:820px){.eqc-two,.mtc .eqc-two{grid-template-columns:minmax(0,1fr)}}" in eqcss)
check("…and the amount of a place goes under a long name instead of over it",
      ".mtc-loc{display:flex;flex-wrap:wrap;align-items:center}" in eqcss and ".mtc-loc b{margin-left:auto}" in eqcss)

# ---- 2. the label of a material: the QR alone
lab = re.search(r"async function mtPrintLabel\(m\) \{.*?\n\}", mat, re.S)
body = lab.group(0) if lab else ""
check("the label takes the QR of the material", "api.material_qr(m.id)" in body)
check("…and prints the QR alone", '<div class="eq-sticker mt-sticker"><img src="${q.png}"' in body and "ean_svg" not in body and "q.name" not in body)
check("…after the picture is ready", "img.decode" in body and body.index("img.decode") < body.index("window.print()"))
check("the button says what it prints", "Печать QR-кода" in mat and "Печать штрихкода" not in mat)
check("the QR fills the sticker, in the middle", ".mt-sticker img{width:27mm;height:27mm" in eqcss and ".mt-sticker{justify-content:center;align-items:center" in eqcss)
check("the old parts of the label are gone", "mt-st-ean" not in eqcss and "mt-st-ean" not in mat)
check("the name on the equipment's sticker wraps instead of being cut", "overflow-wrap:anywhere;hyphens:auto}" in eqcss)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
