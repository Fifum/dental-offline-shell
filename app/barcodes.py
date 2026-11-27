"""3.14: linear barcodes of the stock labels, drawn as SVG (px only, explicit bars — prints the same everywhere).

EAN-13 / EAN-8 — the manufacturer's code of a material (what a desk scanner reads off the box). A material without one gets
an internal EAN-13 of the in-store range «2…» derived from its id, so two computers offline give it the same code and the
scanner finds the material by it like by any other barcode.
"""
from __future__ import annotations

import hashlib
import re

_L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"]
_G = ["0100111", "0110011", "0011011", "0100001", "0011101", "0111001", "0000101", "0010001", "0001001", "0010111"]
_R = ["1110010", "1100110", "1101100", "1000010", "1011100", "1001110", "1010000", "1000100", "1001000", "1110100"]
_PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"]


def check_digit(digits: str) -> int:
    """The check digit of an EAN-8 / EAN-13 body (7 or 12 digits): weights 3 and 1 from the right."""
    s = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return (10 - s % 10) % 10


def valid_ean(code: str) -> bool:
    code = str(code or "").strip()
    return bool(re.fullmatch(r"\d{8}|\d{13}", code)) and check_digit(code[:-1]) == int(code[-1])


def internal_ean(seed: str) -> str:
    """An internal EAN-13 «2…» (the range a shop may use for its own goods), stable for the same seed (the material id)."""
    n = int(hashlib.sha1(str(seed).encode("utf-8")).hexdigest(), 16) % 10 ** 10
    body = "29" + str(n).zfill(10)
    return body + str(check_digit(body))


def modules(code: str) -> str:
    """The bars of a valid EAN-13 or EAN-8 as '1' (bar) and '0' (space)."""
    if len(code) == 13:
        first, left, right = int(code[0]), code[1:7], code[7:]
        par = _PARITY[first]
        return ("101" + "".join((_L if par[i] == "L" else _G)[int(d)] for i, d in enumerate(left)) + "01010"
                + "".join(_R[int(d)] for d in right) + "101")
    left, right = code[:4], code[4:]
    return "101" + "".join(_L[int(d)] for d in left) + "01010" + "".join(_R[int(d)] for d in right) + "101"


def ean_svg(code: str, module: float = 2.0, height: float = 60.0, text: bool = True) -> str:
    """The SVG of an EAN-13 / EAN-8: the guard bars longer, the digits under the bars (as on a box)."""
    code = str(code or "").strip()
    if not valid_ean(code):
        raise ValueError(f"«{code}» — не штрихкод EAN-13 или EAN-8")
    bits = modules(code)
    quiet = 11 if len(code) == 13 else 7
    n = len(bits)
    guards = {0, 1, 2, n - 3, n - 2, n - 1, n // 2 - 2, n // 2 - 1, n // 2, n // 2 + 1, n // 2 + 2}
    w = (n + quiet * 2) * module
    font = module * 7.5
    h = height + (font + module * 2 if text else 0)
    rects = []
    i = 0
    while i < n:  # one rect per run of bars
        if bits[i] != "1":
            i += 1
            continue
        j = i
        while j < n and bits[j] == "1":
            j += 1
        long = any(k in guards for k in range(i, j))
        bh = height + (font * 0.55 if text and long else 0)
        rects.append(f'<rect x="{(quiet + i) * module:g}" y="0" width="{(j - i) * module:g}" height="{bh:g}"/>')
        i = j
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}px" height="{h:g}px" viewBox="0 0 {w:g} {h:g}">',
           f'<rect width="{w:g}" height="{h:g}" fill="#fff"/><g fill="#000">', *rects, "</g>"]
    if text:
        y = height + font + module * 0.5
        st = f'font-family="Arial, sans-serif" font-size="{font:g}" fill="#000" text-anchor="middle"'
        if len(code) == 13:
            out.append(f'<text x="{(quiet - 4) * module:g}" y="{y:g}" {st}>{code[0]}</text>')
            out.append(f'<text x="{(quiet + 3 + 21) * module:g}" y="{y:g}" {st} letter-spacing="{module * 1.6:g}">{code[1:7]}</text>')
            out.append(f'<text x="{(quiet + 50 + 21) * module:g}" y="{y:g}" {st} letter-spacing="{module * 1.6:g}">{code[7:]}</text>')
        else:
            out.append(f'<text x="{(quiet + 3 + 14) * module:g}" y="{y:g}" {st} letter-spacing="{module * 1.6:g}">{code[:4]}</text>')
            out.append(f'<text x="{(quiet + 36 + 14) * module:g}" y="{y:g}" {st} letter-spacing="{module * 1.6:g}">{code[4:]}</text>')
    out.append("</svg>")
    return "".join(out)
