"""3.18 pictures of the usual equipment and materials for what has no photo of its own: every picture the rules of
stock-nurse.js name is in app/ui/img/stock (cut out: a transparent corner, so it fits the dark theme), every picture there is
used by a rule, and the clinic server sends them as image/webp."""
import os
import re
import socket
import sys
import tempfile
import urllib.request
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from PIL import Image  # noqa: E402

import db as dbm  # noqa: E402
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


UI = ROOT / "app" / "ui"
js = (UI / "stock-nurse.js").read_text(encoding="utf-8")
block = js[js.index("const EQ_PIC_RULES"):js.index("function stockPicBy")]
keys = set(re.findall(r'\["([a-z-]+)", \[', block)) | set(re.findall(r'": "([a-z-]+)"', block)) | {"box"}
files = {p.stem for p in (UI / "img" / "stock").glob("*.webp")}
check("every picture of the rules is there", keys <= files, sorted(keys - files))
check("every picture there is used", files <= keys, sorted(files - keys))
check("equipment and materials", {"chair", "autoclave", "apex", "xray", "opg"} <= files and {"tube", "syringe", "carpule", "napkins"} <= files)
for f in sorted(files):
    im = Image.open(UI / "img" / "stock" / f"{f}.webp")
    check(f"{f}: cut out", im.mode == "RGBA" and im.getpixel((2, 2))[3] == 0, im.mode)
    check(f"{f}: square and small", im.size == (384, 384) and (UI / "img" / "stock" / f"{f}.webp").stat().st_size < 60_000, im.size)
check("the call sites pass a picture", js.count("matPic(") >= 6 and "eqPic(" in (UI / "stock-eqsection.js").read_text(encoding="utf-8"))
check("cards show it too", "eqPic(e.name, e.category)" in (UI / "stock-eqphotos.js").read_text(encoding="utf-8")
      and "matPic(m.name, m.category)" in (UI / "stock-matcard.js").read_text(encoding="utf-8"))

d = dbm.DB()
a = Api(d, W())
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()
with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/img/stock/chair.webp", timeout=20) as r:
    check("served as image/webp", r.status == 200 and r.headers.get("Content-Type") == "image/webp", r.headers.get("Content-Type"))
    check("the bytes are the file", r.read() == (UI / "img" / "stock" / "chair.webp").read_bytes())

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
