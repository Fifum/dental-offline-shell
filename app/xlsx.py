"""A minimal .xlsx writer (no extra libraries): one sheet, a bold header row, numbers stay numbers.

Cells that look like money or counts on the screen («12 500 ₽», «37%», «2,5 мм») are written as numbers so
Excel can sum them; everything else is text.
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

_NUM = re.compile(r"^-?[\d\s  ]+(?:[.,]\d+)?$")


def _number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    s = str(v or "").strip()
    s = re.sub(r"\s*(₽|руб\.?|%|шт\.?|мм)$", "", s)
    if s and _NUM.match(s) and re.search(r"\d", s):
        s = re.sub(r"[\s  ]", "", s).replace(",", ".")
        if len(s.replace("-", "").split(".")[0]) >= 10 or (s.startswith("0") and len(s) > 1 and not s.startswith("0.")):
            return None  # phone numbers, INN, codes with leading zeros — keep as text
        try:
            return float(s) if "." in s else int(s)
        except ValueError:
            return None
    return None


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref, v, style=0):
    n = _number(v)
    st = f' s="{style}"' if style else ""
    if n is not None and style == 0:
        return f'<c r="{ref}"><v>{n}</v></c>'
    text = escape(str(v if v is not None else "")).replace("\n", "&#10;")
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{text}</t></is></c>'


def build(title: str, headers: list, rows: list) -> bytes:
    headers = [str(h) for h in headers][:200]
    rows = [list(r)[:200] for r in rows][:100000]
    ncol = max([len(headers)] + [len(r) for r in rows] + [1])
    widths = [min(60, max([len(str(headers[i])) if i < len(headers) else 0] + [len(str(r[i])) for r in rows if i < len(r)] + [6]) + 2)
              for i in range(ncol)]
    out_rows = []
    if headers:
        out_rows.append('<row r="1">' + "".join(_cell(f"{_col(i)}1", h, 1) for i, h in enumerate(headers)) + "</row>")
    off = 2 if headers else 1
    for j, r in enumerate(rows):
        out_rows.append(f'<row r="{j + off}">' + "".join(_cell(f"{_col(i)}{j + off}", v) for i, v in enumerate(r)) + "</row>")
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             + ('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' if headers else "")
             + f"<cols>{cols}</cols><sheetData>{''.join(out_rows)}</sheetData></worksheet>")
    name = escape(re.sub(r"[\[\]:*?/\\]", " ", title or "Таблица")[:31] or "Таблица")
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>",
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in files.items():
            z.writestr(k, v)
    return buf.getvalue()


def file_name(title) -> str:
    t = re.sub(r'[\\/:*?"<>|]+', " ", str(title or "Таблица")).strip()[:80] or "Таблица"
    return f"{t} {datetime.now():%Y-%m-%d}.xlsx"
