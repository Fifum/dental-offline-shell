"""Draws the app icons (phone/icons): a red tile (the red of the program, 3.18) with the white corners of a viewfinder.
Run once: python make_icons.py"""
from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).parent / "icons"
HERE.mkdir(exist_ok=True)
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#D9262B"/>
<g fill="none" stroke="#FFFFFF" stroke-width="34" stroke-linecap="round" stroke-linejoin="round">
<path d="M136 200v-48a16 16 0 0 1 16-16h48M312 136h48a16 16 0 0 1 16 16v48M376 312v48a16 16 0 0 1-16 16h-48M200 376h-48a16 16 0 0 1-16-16v-48"/></g>
<path d="M176 256h160" stroke="#FFD2D3" stroke-width="30" stroke-linecap="round"/></svg>"""
(HERE / "icon.svg").write_text(SVG, encoding="utf-8")


def png(size, pad=0.0):
    k = 4  # drawn large and scaled down: smooth edges
    s = size * k
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill="#D9262B")
    u = s / 512
    w = int(34 * u)
    for (x, y, dx, dy) in ((136, 136, 1, 1), (376, 136, -1, 1), (376, 376, -1, -1), (136, 376, 1, -1)):
        d.line([(x * u, (y + 64 * dy) * u), (x * u, y * u), ((x + 64 * dx) * u, y * u)], fill="#FFFFFF", width=w, joint="curve")
        for px, py in ((x, y + 64 * dy), (x + 64 * dx, y)):
            d.ellipse([px * u - w / 2, py * u - w / 2, px * u + w / 2, py * u + w / 2], fill="#FFFFFF")
    d.line([(176 * u, 256 * u), (336 * u, 256 * u)], fill="#FFD2D3", width=int(30 * u))
    for px in (176, 336):
        d.ellipse([px * u - 15 * u, 241 * u, px * u + 15 * u, 271 * u], fill="#FFD2D3")
    return im.resize((size, size), Image.LANCZOS)


png(192).save(HERE / "icon-192.png")
png(512).save(HERE / "icon-512.png")
print("icons ok")
