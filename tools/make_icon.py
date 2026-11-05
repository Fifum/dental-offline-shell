"""Generate the app icon: white tile, serif mark, burgundy line.

python tools/make_icon.py           -> app/assets/app.ico   (neutral "DD", committed)
python tools/make_icon.py --brand   -> app/assets/brand.ico (mark from app/brand.json, git-ignored)
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
brand = "--brand" in sys.argv
text = "DD"
if brand:
    text = json.loads((ROOT / "app" / "brand.json").read_text(encoding="utf-8")).get("short", "DD")

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((0, 0, S - 1, S - 1), radius=200, fill=(255, 255, 255, 255), outline=(229, 227, 223, 255), width=14)
font = None
for f in ("C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/times.ttf"):
    try:
        font = ImageFont.truetype(f, 400 if len(text) > 2 else 470)
        break
    except OSError:
        continue
box = d.textbbox((0, 0), text, font=font)
w, h = box[2] - box[0], box[3] - box[1]
d.text(((S - w) / 2 - box[0], S * 0.40 - h / 2 - box[1]), text, font=font, fill=(30, 30, 30, 255))
d.rectangle((S * 0.17, S * 0.66, S * 0.83, S * 0.66 + 22), fill=(109, 1, 0, 255))
out = ROOT / "app" / "assets" / ("brand.ico" if brand else "app.ico")
img.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
if not brand:
    img.resize((256, 256), Image.LANCZOS).save(out.with_suffix(".png"))
print(out)
