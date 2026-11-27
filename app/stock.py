"""Stock of materials and the clinic's equipment.

Materials: every change of quantity is a row in stock_moves (receipt +, write-off −, inventory ±),
so the balance is always SUM(qty) and the history explains every number. Services can carry
consumption norms; billing a service writes the materials off automatically (and editing or
deleting the invoice puts them back).

Equipment: a register with inventory numbers, location, service history and a write-off act.

3.5 места хранения: the main stock plus cabinets and branches (`stock_locations`). Every move belongs to one place
(`stock_moves.location_id`, empty — the main stock), so the balance of a place is the sum of its moves and the clinic's balance
is still the sum of all moves. A transfer is a document with two moves (− there, + here); lots and expiry stay clinic-wide.

3.10 медсестра и амортизация: materials and equipment may carry a photo (`photo_id` — a row of `patient_files` owned by
«_stock», so the picture travels to the other computers like an X-ray); equipment has a straight-line depreciation (the cost
less the salvage value over the useful life, from the month after it was put into service, until it is written off).
Requests and write-offs waiting for approval are in stock_flow.py.

2.14.1 «без документа»: a receipt bought without an invoice, a write-off without an act or a stock count may be marked
`stock_docs.nodoc = 1`. The stock itself is always the real one (everything); «по документам» is the balance of the
documented moves only (plus services and starting balances) — seen with the «Бухгалтерия» right, for the accountant.
"""
from __future__ import annotations

import calendar
import json
import math
import re
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import quote, unquote

import barcodes

SCHEMA = """
CREATE TABLE IF NOT EXISTS materials(
    id TEXT PRIMARY KEY, code TEXT, name TEXT, unit TEXT, category TEXT, min_qty REAL DEFAULT 0,
    price REAL DEFAULT 0, barcode TEXT, comment TEXT, active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS suppliers(
    id TEXT PRIMARY KEY, name TEXT, phone TEXT, inn TEXT, comment TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS stock_docs(
    id TEXT PRIMARY KEY, kind TEXT, number TEXT, date TEXT, supplier_id TEXT, reason TEXT, comment TEXT,
    total REAL DEFAULT 0, user_name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS stock_moves(
    id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, qty REAL, price REAL DEFAULT 0, kind TEXT,
    doc_id TEXT, invoice_id TEXT, patient_id TEXT, reason TEXT, user_name TEXT, at TEXT);
CREATE INDEX IF NOT EXISTS ix_moves_mat ON stock_moves(material_id);
CREATE INDEX IF NOT EXISTS ix_moves_inv ON stock_moves(invoice_id);
CREATE TABLE IF NOT EXISTS service_materials(
    service_id TEXT, material_id TEXT, qty REAL, PRIMARY KEY(service_id, material_id));
CREATE TABLE IF NOT EXISTS equipment(
    id TEXT PRIMARY KEY, inv_number TEXT, name TEXT, category TEXT, model TEXT, serial TEXT,
    location TEXT, responsible TEXT, purchase_date TEXT, price REAL DEFAULT 0, warranty_until TEXT,
    next_service TEXT, status TEXT DEFAULT 'in_use', comment TEXT, created_at TEXT,
    writeoff_date TEXT, writeoff_reason TEXT, writeoff_act TEXT, writeoff_commission TEXT, residual REAL);
CREATE TABLE IF NOT EXISTS equipment_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, equipment_id TEXT, kind TEXT, date TEXT, text TEXT,
    cost REAL DEFAULT 0, user_name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS stock_lots(
    id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, move_id INTEGER, lot TEXT, expires TEXT,
    qty REAL, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_lots_mat ON stock_lots(material_id);
CREATE TABLE IF NOT EXISTS stock_locations(
    id TEXT PRIMARY KEY, name TEXT, kind TEXT, branch_id TEXT, chair TEXT, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0,
    comment TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS stock_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS equipment_docs(
    id TEXT PRIMARY KEY, equipment_id TEXT, kind TEXT, title TEXT, file_id TEXT, created_by TEXT, created_at TEXT,
    deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_eqdocs_eq ON equipment_docs(equipment_id);
CREATE TABLE IF NOT EXISTS stock_orders(
    id TEXT PRIMARY KEY, number TEXT, supplier_id TEXT, date TEXT, expected TEXT, lines TEXT, received TEXT, status TEXT,
    total REAL DEFAULT 0, comment TEXT, doc_ids TEXT, user_name TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_sorders_status ON stock_orders(status);
CREATE TABLE IF NOT EXISTS material_docs(
    id TEXT PRIMARY KEY, material_id TEXT, kind TEXT, title TEXT, file_id TEXT, created_by TEXT, created_at TEXT,
    deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_matdocs_mat ON material_docs(material_id);
CREATE TABLE IF NOT EXISTS material_analogs(
    id TEXT PRIMARY KEY, a TEXT, b TEXT, created_by TEXT, created_at TEXT, deleted INTEGER DEFAULT 0);
"""
SOON_DAYS = 30          # a lot expiring within this many days is highlighted
USAGE_DAYS = 60         # the average daily use for the purchase list is taken over this period
MIN_DAYS_LEFT = 14      # a material that lasts fewer days goes into the purchase list
EXPIRED_REASON = "Истёк срок годности"

MOVE_KINDS = {"receipt": "Приход", "writeoff": "Списание", "service": "По услуге", "inventory": "Инвентаризация",
              "return": "Возврат поставщику", "transfer": "Перемещение"}
MAIN = "Основной склад"   # the place of every move without a location (all of them before 3.5)
LOC_KINDS = {"store": "Склад", "cabinet": "Кабинет", "branch": "Филиал"}
EQ_STATUS = {"in_use": "В работе", "repair": "В ремонте", "storage": "На складе", "written_off": "Списано"}
EQ_EVENTS = {"service": "Обслуживание", "repair": "Ремонт", "move": "Перемещение", "note": "Заметка",
             "writeoff": "Списание", "status": "Статус", "inventory": "Инвентаризация", "replace_plan": "План замены",
             "disposal": "Выбытие", "doc": "Документ", "condition": "Состояние", "created": "Поставлено на учёт"}
# 3.13 «карточка оборудования»
EQ_OWNERSHIP = {"own": "Собственность клиники", "lease": "Аренда", "leasing": "Лизинг", "owner": "Имущество учредителя"}
EQ_CONDITION = {"ok": "Исправно", "service": "Требует обслуживания", "faulty": "Неисправно"}
EQ_DISPOSAL = {"writeoff": "Списание и утилизация", "sale": "Продажа", "return": "Возврат владельцу"}
EQ_DISPOSED = {"writeoff": "Списано", "sale": "Продано", "return": "Возвращено владельцу"}
EQ_DOC_KINDS = {"contract": "Договор купли-продажи", "waybill": "Товарная накладная", "act": "Акт ввода в эксплуатацию",
                "passport": "Технический паспорт", "reg": "Регистрационное удостоверение", "warranty": "Гарантийный талон",
                "service_act": "Акты ТО", "photo": "Фотографии", "other": "Другое"}
EQ_DOC_MAIN = [k for k in EQ_DOC_KINDS if k != "other"]   # «Документы (n/8)»
# the money of a piece of equipment: only someone with «Бухгалтерия» sees it, and only they may change it
EQ_MONEY = ("price", "salvage", "market_value", "replace_cost", "reserve_monthly", "disposal_amount", "residual")
EQ_NEW_COLS = ("manufacturer TEXT", "ownership TEXT", "condition TEXT", "location_id TEXT", "market_value REAL",
               "replace_cost REAL", "replace_date TEXT", "reserve_monthly REAL", "disposal_kind TEXT", "disposal_amount REAL")
CHAIR_HOURS = 154       # working hours of a chair in a month, for «амортизация на кресло-час»
INV_FIRST = "ОБ-001"
UNITS = ["шт", "уп", "мл", "г", "фл", "амп", "карп", "набор", "пара", "м"]
AMORT_METHODS = {"linear": "Линейный"}
# 3.14: rented equipment and the founder's own property are not the clinic's assets: no depreciation and no disposal in the P&L
OFF_BOOKS = ("lease", "owner")
CAPEX_DAYS = 45         # an expense this close to the purchase, of the same sum, looks like the purchase itself
MAX_USEFUL_MONTHS = 600  # 50 years
# 3.14 «карточка материала»: its own number (МТ-0001, as the equipment's inventory number), the details of the mockup,
# the orders to suppliers («в пути»), the documents and photos, the analogs
MAT_FIRST = "МТ-0001"
MAT_NEW_COLS = ("number TEXT", "manufacturer TEXT", "description TEXT", "form TEXT", "shelf_life TEXT", "storage TEXT",
                "opt_qty REAL DEFAULT 0", "lead_days INTEGER DEFAULT 0", "supplier_id TEXT")
MAT_TEXT = {"manufacturer": 120, "description": 200, "form": 120, "shelf_life": 80, "storage": 200}
MAT_DOC_KINDS = {"reg": "Регистрационное удостоверение", "cert": "Сертификат или декларация", "manual": "Инструкция",
                 "msds": "Паспорт безопасности", "waybill": "Накладная", "photo": "Фото", "other": "Другое"}
ORDER_STATUS = {"ordered": "Заказан", "partial": "Получен частично", "received": "Получен", "cancelled": "Отменён"}
ORDER_OPEN = ("ordered", "partial")
REQ_OPEN = ("new", "accepted", "partial")   # stock_flow.OPEN: the cabinets' requests still to be issued — the reserve


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _num(v, name="Количество"):
    try:
        x = float(str(v).replace(",", ".").replace(" ", "")) if v not in (None, "") else 0.0
    except ValueError:
        raise ValueError(f"{name}: введите число") from None
    return round(x, 3)


def _clean(s, n=300):
    return str(s or "").strip()[:n]


def _day(v, name="Годен до"):
    """A date from the form: 2027-03-31, 31.03.2027 or a month only (2027-03, 03.2027 → its last day)."""
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif (m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)):
        y, mo, d = int(m[3]), int(m[2]), int(m[1])
    elif (m := re.fullmatch(r"(\d{4})-(\d{1,2})", s)) or (m := re.fullmatch(r"(\d{1,2})\.(\d{4})", s)):
        y, mo = (int(m[1]), int(m[2])) if "-" in s else (int(m[2]), int(m[1]))
        d = calendar.monthrange(y, mo)[1] if 1 <= mo <= 12 else 0
    else:
        raise ValueError(f"{name}: укажите дату, например 31.12.2027")
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        raise ValueError(f"{name}: такой даты нет") from None


GS = "\x1d"  # GS1 group separator (FNC1) that scanners send between variable-length fields
_GS1_FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
_GS1_VAR = ("10", "21", "240", "91", "92", "93")


def parse_scan(code):
    """What a scanner typed: a plain EAN/UPC/internal code, or a GS1 code (DataMatrix «Честный знак», GS1-128)
    with the GTIN, the lot (10) and the expiry date (17, YYMMDD). Returns {code, barcode, gtin, lot, expires}."""
    raw = str(code or "").strip().replace("\\x1d", GS).replace("<GS>", GS)
    for pre in ("]d2", "]C1", "]Q3", "]e0"):  # symbology identifiers some scanners prefix
        if raw.startswith(pre):
            raw = raw[len(pre):]
    out = {"code": raw.replace(GS, ""), "barcode": raw.replace(GS, ""), "gtin": "", "lot": "", "expires": ""}
    s = raw.replace("(", GS).replace(")", "") if raw.startswith("(") else raw
    s = s.lstrip(GS)
    if not (s.startswith("01") and len(s) >= 16 and s[2:16].isdigit()):
        return out
    i, fields = 0, {}
    while i < len(s):
        if s[i] == GS:
            i += 1
            continue
        ai = s[i:i + 2]
        if ai in _GS1_FIXED:
            n = _GS1_FIXED[ai]
            fields[ai] = s[i + 2:i + 2 + n]
            i += 2 + n
            continue
        ai = next((a for a in _GS1_VAR if s.startswith(a, i)), None)
        if not ai:
            break
        end = s.find(GS, i)
        end = len(s) if end < 0 else end
        fields[ai] = s[i + len(ai):end]
        i = end
    gtin = fields.get("01", "")
    out.update(gtin=gtin, barcode=gtin[1:] if gtin.startswith("0") else gtin, lot=fields.get("10", "")[:60])
    exp = fields.get("17", "")
    if len(exp) == 6 and exp.isdigit():
        y, mo, d = 2000 + int(exp[:2]), int(exp[2:4]), int(exp[4:])
        if d == 0 and 1 <= mo <= 12:  # «00» in GS1 means the end of the month
            d = calendar.monthrange(y, mo)[1]
        try:
            out["expires"] = date(y, mo, d).isoformat()
        except ValueError:
            pass
    return out


def _jl(v, default):
    try:
        x = json.loads(v) if v else default
        return x if isinstance(x, type(default)) else default
    except (TypeError, ValueError):
        return default


def _mon(day):
    """'2026-11-18' or '2026-11' → month index (year * 12 + month − 1); '' → None."""
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", str(day or "")[:10])
    return int(m[1]) * 12 + int(m[2]) - 1 if m else None


def _mon_str(k):
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def amortization(e, month=None):
    """Straight-line depreciation of one piece of equipment as of `month` ('YYYY-MM', default — this month, inclusive).

    The cost less the salvage value is spread evenly over the useful life, from the month after the date it was put into
    service (or bought); a written-off piece is not depreciated after the month of the write-off. The sum of k months is
    rounded once (not k rounded months), so the last month takes the kopecks and the total is exactly the base."""
    cost = round(float(e.get("price") or 0), 2)
    n = int(e.get("useful_months") or 0)
    start = _mon(e.get("in_service") or e.get("purchase_date"))
    out = {"on": False, "cost": cost, "method": e.get("amort_method") or "linear", "useful_months": n,
           "salvage": round(float(e.get("salvage") or 0), 2), "in_service": e.get("in_service") or e.get("purchase_date") or "",
           "monthly": 0.0, "accumulated": 0.0, "residual": cost, "months_done": 0, "months_left": 0, "first": "", "last": "",
           "percent": 0.0, "done": False, "stopped": ""}
    if not (cost > 0 and n > 0 and start is not None):
        return out
    base = max(0.0, cost - min(out["salvage"], cost))
    first, last = start + 1, start + n
    stop = _mon(e.get("writeoff_date")) if e.get("status") == "written_off" else None
    now = _mon(month) if month else _mon(date.today().isoformat())
    upto = min(last, now, stop if stop is not None else last)
    k = max(0, upto - first + 1)
    acc = round(base * k / n, 2)
    out.update(on=True, monthly=round(base / n, 2), accumulated=acc, residual=round(cost - acc, 2), months_done=k,
               months_left=max(0, n - k) if stop is None else 0, first=_mon_str(first), last=_mon_str(last),
               percent=round(acc * 100 / base, 1) if base else 100.0, done=k >= n,
               stopped=_mon_str(stop) if stop is not None else "")
    return out


def amort_charge(e, month):
    """Depreciation of one piece for one month ('YYYY-MM'): the difference of the totals at its end and the month before."""
    k = _mon(month)
    if k is None:
        return 0.0
    a, b = amortization(e, _mon_str(k)), amortization(e, _mon_str(k - 1))
    return round(a["accumulated"] - b["accumulated"], 2) if a["on"] else 0.0


def amort_schedule(e):
    """Every month of the useful life (up to the write-off): charge, total so far and book value."""
    a = amortization(e)
    if not a["on"]:
        return []
    out, prev = [], 0.0
    base = max(0.0, a["cost"] - min(a["salvage"], a["cost"]))
    first, last = _mon(a["first"]), _mon(a["last"])
    stop = _mon(a["stopped"]) if a["stopped"] else None
    for k in range(first, last + 1):
        if stop is not None and k > stop:
            break
        acc = round(base * (k - first + 1) / a["useful_months"], 2)
        out.append({"month": _mon_str(k), "charge": round(acc - prev, 2), "accumulated": acc, "residual": round(a["cost"] - acc, 2)})
        prev = acc
    return out


def on_books(e) -> bool:
    """3.14: the piece is the clinic's own (or in leasing) — its depreciation and disposal go into the P&L."""
    return (e.get("ownership") or "own") not in OFF_BOOKS


def amort_month(db, month):
    """3.10: depreciation of all the equipment for one month ('YYYY-MM') — a line of the P&L (3.14: the clinic's own only)."""
    return round(sum(amort_charge(e, month) for e in db.q("SELECT * FROM equipment") if on_books(e)), 2)


def amort_month_detail(db, month):
    """3.14: the depreciation of one month by piece, the largest first — the detail of the P&L line."""
    out = [{"name": f"{e['name']}{' (' + e['inv_number'] + ')' if e['inv_number'] else ''}", "amount": amort_charge(e, month)}
           for e in db.q("SELECT * FROM equipment") if on_books(e)]
    return sorted([x for x in out if x["amount"]], key=lambda x: -x["amount"])


def disposal_month(db, month):
    """3.14: the equipment that left the clinic in the month ('YYYY-MM'): its book value at the disposal less what it was sold
    for — the P&L line «Выбытие оборудования» (a sale above the book value makes it negative: a gain)."""
    out = []
    for e in db.q("""SELECT * FROM equipment WHERE status='written_off' AND substr(COALESCE(writeoff_date,''),1,7)=?
                     ORDER BY writeoff_date, name""", (str(month or "")[:7],)):
        if not on_books(e):
            continue
        residual = e["residual"] if e["residual"] is not None else amortization(e)["residual"]
        sale = (e["disposal_amount"] or 0) if e.get("disposal_kind") == "sale" else 0
        out.append({"id": e["id"], "inv_number": e["inv_number"], "name": e["name"], "kind": e.get("disposal_kind") or "writeoff",
                    "date": e["writeoff_date"], "residual": round(residual or 0, 2), "sale": round(sale, 2),
                    "amount": round((residual or 0) - sale, 2)})
    return out


class Stock:
    def __init__(self, db):
        self.db = db
        with db._lock:  # В1: raw schema statements never interleave with another thread's transaction
            db.conn.executescript(SCHEMA)
            if "nodoc" not in {r[1] for r in db.conn.execute("PRAGMA table_info(stock_docs)")}:  # 2.14.1: without a document
                db.conn.execute("ALTER TABLE stock_docs ADD COLUMN nodoc INTEGER DEFAULT 0")
            dcols = {r[1] for r in db.conn.execute("PRAGMA table_info(stock_docs)")}
            for col in ("location_id TEXT", "to_location_id TEXT"):  # 3.5: where a document took or put the materials
                if col.split()[0] not in dcols:
                    db.conn.execute(f"ALTER TABLE stock_docs ADD COLUMN {col}")
            if "location_id" not in {r[1] for r in db.conn.execute("PRAGMA table_info(stock_moves)")}:  # 3.5: the place of a move
                db.conn.execute("ALTER TABLE stock_moves ADD COLUMN location_id TEXT")
            # 3.10: photos of materials and equipment, depreciation of equipment
            if "photo_id" not in {r[1] for r in db.conn.execute("PRAGMA table_info(materials)")}:
                db.conn.execute("ALTER TABLE materials ADD COLUMN photo_id TEXT")
            ecols = {r[1] for r in db.conn.execute("PRAGMA table_info(equipment)")}
            for col in ("photo_id TEXT", "in_service TEXT", "useful_months INTEGER", "salvage REAL DEFAULT 0", "amort_method TEXT",
                        *EQ_NEW_COLS):  # 3.13: the equipment card
                if col.split()[0] not in ecols:
                    db.conn.execute(f"ALTER TABLE equipment ADD COLUMN {col}")
            if "data" not in {r[1] for r in db.conn.execute("PRAGMA table_info(equipment_events)")}:  # 3.13: inventory details
                db.conn.execute("ALTER TABLE equipment_events ADD COLUMN data TEXT")
            mcols = {r[1] for r in db.conn.execute("PRAGMA table_info(materials)")}
            for col in MAT_NEW_COLS:  # 3.14: the material card
                if col.split()[0] not in mcols:
                    db.conn.execute(f"ALTER TABLE materials ADD COLUMN {col}")
            self._fill_numbers(db.conn)
            db.conn.commit()

    service_location = None  # 3.5: callable(invoice row) -> place of the automatic write-off by an invoice (set by Api)

    @staticmethod
    def _fill_numbers(conn):
        """3.14: a material without a number (made before 3.14, by the demo, or on a computer not updated yet) gets the next one,
        in the order the materials were made: every computer numbers the same materials the same way."""
        todo = conn.execute("SELECT id FROM materials WHERE COALESCE(number,'')='' ORDER BY COALESCE(created_at,''), id").fetchall()
        if not todo:
            return 0
        used = {str(r[0]) for r in conn.execute("SELECT number FROM materials WHERE COALESCE(number,'')<>''")}
        n = max([int(m[1]) for x in used if (m := re.match(r"^МТ-(\d+)$", x))] or [0])
        for (mid,) in todo:
            n += 1
            while f"МТ-{n:04d}" in used:
                n += 1
            conn.execute("UPDATE materials SET number=? WHERE id=?", (f"МТ-{n:04d}", mid))
        return len(todo)

    def fill_numbers(self):
        with self.db.tx() as c:
            return self._fill_numbers(c)

    # ============================================================ materials --
    def materials(self, q="", only_low=False, with_inactive=False, only_expiring=False, location=None):
        """`location` (3.5): the balance and its value in that place («» — the main stock); the minimum stays clinic-wide."""
        rows = self.db.q("""
            SELECT m.*, COALESCE(SUM(s.qty), 0) AS balance,
                   COALESCE(SUM(CASE WHEN COALESCE(d.nodoc, 0) = 0 THEN s.qty END), 0) AS balance_doc,
                   MAX(CASE WHEN s.kind IN ('service','writeoff') THEN s.at END) AS last_used
            FROM materials m LEFT JOIN stock_moves s ON s.material_id = m.id LEFT JOIN stock_docs d ON d.id = s.doc_id
            WHERE (? OR m.active = 1)
            GROUP BY m.id ORDER BY m.category, m.name""", (1 if with_inactive else 0,))
        q = (q or "").strip().lower()
        lots = self._lots_by_material({r["id"]: r["balance"] for r in rows})
        for r in rows:
            r["balance"] = round(r["balance"], 3)
            r["balance_doc"] = round(r["balance_doc"], 3)   # by documents only (2.14.1)
            r["value_doc"] = round(r["balance_doc"] * (r["price"] or 0), 2)
            r["low"] = r["min_qty"] > 0 and r["balance"] <= r["min_qty"]
            r["value"] = round(r["balance"] * (r["price"] or 0), 2)
            ls = [x for x in lots.get(r["id"], {}).get("lots", []) if x["left"] > 0]
            r["lots"] = len(ls)
            r["expired_qty"] = round(sum(x["left"] for x in ls if x["state"] == "expired"), 3)
            r["soon_qty"] = round(sum(x["left"] for x in ls if x["state"] == "soon"), 3)
            r["expires"] = min((x["expires"] for x in ls if x["expires"]), default="")
            r["exp_state"] = "expired" if r["expired_qty"] > 0 else "soon" if r["soon_qty"] > 0 else ""
        if location is not None:
            at = self.location_balances()
            for r in rows:
                r["total_balance"] = r["balance"]
                r["balance"] = round(at.get(r["id"], {}).get(location or "", 0), 3)
                r["value"] = round(r["balance"] * (r["price"] or 0), 2)
        if q:
            rows = [r for r in rows if q in f"{r['code']} {r['name']} {r['category']} {r['barcode']} {r.get('number') or ''} "
                                             f"{r.get('manufacturer') or ''}".lower()]
        if only_low:
            rows = [r for r in rows if r["low"]]
        if only_expiring:
            rows = [r for r in rows if r["exp_state"]]
        return rows

    # ------------------------------------------------- lots and expiry dates --
    def _lots_by_material(self, balances, mid=None):
        """Lots left on hand, worked out from the move ledger instead of being stored (FEFO).

        Whatever leaves the stock is taken from the lot that expires first. So, going from the latest expiry to
        the earliest, each lot keeps min(its quantity, what is still unassigned of the balance); what no lot covers
        is stock «без срока». A write-off of a specific expired lot is stored as a negative row of that lot.
        Nothing here depends on move ids staying put, so on_invoice can delete and re-create its moves freely."""
        sql = """SELECT l.id, l.material_id, l.lot, l.expires, l.qty, l.created_at, s.at, s.doc_id, d.number AS doc_number,
                        sp.name AS supplier_name
                 FROM stock_lots l JOIN stock_moves s ON s.id = l.move_id
                 LEFT JOIN stock_docs d ON d.id = s.doc_id LEFT JOIN suppliers sp ON sp.id = d.supplier_id"""
        rows = self.db.q(sql + (" WHERE l.material_id=?" if mid else "") + " ORDER BY l.id", (mid,) if mid else ())
        groups = {}
        for r in rows:  # one lot = one material + lot number + expiry date, however many receipts brought it
            key = (r["material_id"], r["lot"] or "", r["expires"] or "")
            g = groups.get(key)
            if g is None:
                if r["qty"] <= 0:
                    continue
                g = groups[key] = {"id": r["id"], "material_id": r["material_id"], "lot": r["lot"] or "", "expires": r["expires"] or "",
                                   "qty": 0.0, "received": r["at"][:10] if r["at"] else "", "doc_number": r["doc_number"] or "",
                                   "supplier_name": r["supplier_name"] or ""}
            g["qty"] += r["qty"]
        today = date.today()
        soon = (today.toordinal() + SOON_DAYS)
        out = {}
        for g in groups.values():
            out.setdefault(g["material_id"], {"lots": []})["lots"].append(g)
        for m_id, rec in out.items():
            left = max(0.0, balances.get(m_id, 0) or 0)
            # latest expiry first; a lot without a date is consumed last of all; among equal dates the newest is kept
            rec["lots"].sort(key=lambda g: (g["expires"] or "9999-12-31", g["id"]), reverse=True)
            for g in rec["lots"]:
                g["qty"] = round(max(0.0, g["qty"]), 3)
                g["left"] = round(min(g["qty"], left), 3)
                left = round(left - g["left"], 3)
                if g["expires"]:
                    e = date.fromisoformat(g["expires"])
                    g["days"] = (e - today).days
                    g["state"] = "expired" if e < today else "soon" if e.toordinal() <= soon else "ok"
                else:
                    g["days"], g["state"] = None, "ok"
            rec["lots"].reverse()  # show the earliest expiry first
            rec["no_lot"] = round(left, 3)
        return out

    def lots(self, mid):
        """The lots of one material on hand: earliest expiry first, plus the part not covered by any lot."""
        bal = self.balance(mid)
        rec = self._lots_by_material({mid: bal}, mid).get(mid, {"lots": [], "no_lot": max(0.0, bal)})
        return {"lots": [g for g in rec["lots"] if g["left"] > 0], "no_lot": rec["no_lot"], "balance": bal}

    def expired_lines(self):
        """Ready lines for «Списать просроченное»: every expired lot that is still on hand."""
        out = []
        mats = {m["id"]: m for m in self.materials()}
        bal = {k: v["balance"] for k, v in mats.items()}
        for mid, rec in self._lots_by_material(bal).items():
            if mid not in mats:
                continue
            for g in rec["lots"]:
                if g["state"] == "expired" and g["left"] > 0:
                    m = mats[mid]
                    out.append({"material_id": mid, "name": m["name"], "unit": m["unit"], "qty": g["left"], "lot_id": g["id"],
                                "lot": g["lot"], "expires": g["expires"], "price": m["price"]})
        out.sort(key=lambda x: (x["expires"], x["name"]))
        return out

    def material(self, mid):
        rows = [r for r in self.materials(with_inactive=True) if r["id"] == mid]
        if not rows:
            return None
        m = rows[0]
        m["lot_list"] = self.lots(mid)
        m["moves"] = self.moves(material_id=mid, limit=1000)  # 3.14: «История» — every move
        names = self._loc_names()  # 3.5: where it is
        m["by_location"] = [{"id": k, "name": names.get(k, MAIN), "qty": v}
                            for k, v in sorted(self.location_balances().get(mid, {}).items(), key=lambda x: (x[0] != "", names.get(x[0], "")))
                            if abs(v) > 1e-9]
        m["norms"] = self.db.q("""SELECT sm.service_id, sm.qty, s.title, s.code FROM service_materials sm
                                  JOIN services s ON s.id = sm.service_id WHERE sm.material_id=? ORDER BY s.title""", (mid,))
        m.update(self.material_supplies(mid))   # 3.13 «карточка материала»
        m.update(self.material_usage(mid, m["balance"] - (m.get("expired_qty") or 0)))
        m.update(self.material_card(m))         # 3.14: by the mockup
        return m

    # ------------------------------------------------------ 3.14: the material card --
    def reserve(self, mid=None):
        """«Резервный остаток»: what the cabinets asked for and did not get yet (new, accepted and partly issued requests)."""
        if not self.db.one("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name='stock_requests'"):
            return {}
        out = {}
        for r in self.db.q(f"SELECT lines, issued FROM stock_requests WHERE status IN ({','.join('?' * len(REQ_OPEN))})", REQ_OPEN):
            issued = _jl(r["issued"], {})
            for ln in _jl(r["lines"], []):
                k = str((ln or {}).get("material_id") or "")
                if not k or (mid and k != mid):
                    continue
                try:
                    left = float(ln.get("qty") or 0) - float(issued.get(k, 0) or 0)
                except (TypeError, ValueError):
                    continue
                if left > 1e-9:
                    out[k] = round(out.get(k, 0) + left, 3)
        return out

    def in_transit(self, mid=None):
        """«В пути (заказано)»: ordered from suppliers and not received yet, by the open orders."""
        out = {}
        for o in self.db.q(f"SELECT lines, received FROM stock_orders WHERE status IN ({','.join('?' * len(ORDER_OPEN))})", ORDER_OPEN):
            got = _jl(o["received"], {})
            for ln in _jl(o["lines"], []):
                k = str((ln or {}).get("material_id") or "")
                if not k or (mid and k != mid):
                    continue
                left = float(ln.get("qty") or 0) - float(got.get(k, 0) or 0)
                if left > 1e-9:
                    out[k] = round(out.get(k, 0) + left, 3)
        return out

    def material_card(self, m):
        """What the 3.14 card adds: reserve, in transit, the coverage by days, the analytics, the use by month, the orders,
        the documents and photos, the analogs, the barcode and the services it is used in."""
        mid, today = m["id"], date.today()
        usable = max(0.0, (m["balance"] or 0) - (m.get("expired_qty") or 0))
        reserve = self.reserve(mid).get(mid, 0.0)
        free = round(max(0.0, usable - reserve), 3)
        transit = self.in_transit(mid).get(mid, 0.0)
        daily = (m.get("usage") or {}).get("daily") or 0
        days = round(free / daily, 1) if daily > 0 else None
        opt = m.get("opt_qty") or 0
        full = opt or (m["min_qty"] or 0) * 2
        # by month for a year: services, the use in treatment (the nurse's «Расход в лечении») and the other write-offs
        ym = []
        y, mo = today.year, today.month
        for _ in range(12):
            ym.append(f"{y}-{mo:02d}")
            y, mo = (y, mo - 1) if mo > 1 else (y - 1, 12)
        ym.reverse()
        months = {}
        for r in self.db.q("""SELECT substr(at,1,7) AS mon, kind, reason, -SUM(qty) AS q, -SUM(qty*price) AS v FROM stock_moves
                              WHERE material_id=? AND kind IN ('service','writeoff') AND substr(at,1,10) >= ?
                              GROUP BY mon, kind, reason""", (mid, ym[0] + "-01")):
            k = "service" if r["kind"] == "service" else "treatment" if str(r["reason"] or "").startswith("Расход в лечении") else "writeoff"
            g = months.setdefault(r["mon"], {"month": r["mon"], "service": 0.0, "treatment": 0.0, "writeoff": 0.0, "sum": 0.0})
            g[k] = round(g[k] + (r["q"] or 0), 3)
            g["sum"] = round(g["sum"] + (r["v"] or 0), 2)
        use_months = [months.get(k) or {"month": k, "service": 0.0, "treatment": 0.0, "writeoff": 0.0, "sum": 0.0} for k in ym]
        tot = {k: round(sum(x[k] for x in use_months), 3) for k in ("service", "treatment", "writeoff")}
        m30 = (today - timedelta(days=30)).isoformat()
        used30 = -(self.db.one("""SELECT COALESCE(SUM(qty),0) AS q FROM stock_moves WHERE material_id=? AND kind IN ('service','writeoff')
                                 AND substr(at,1,10) > ?""", (mid, m30))["q"] or 0)
        y365 = (today - timedelta(days=365)).isoformat()
        buy = self.db.one("""SELECT COALESCE(SUM(qty*price),0) AS v, COALESCE(SUM(qty),0) AS q FROM stock_moves
                             WHERE material_id=? AND kind='receipt' AND qty > 0 AND price > 0 AND substr(at,1,10) > ?""", (mid, y365))
        orders = [o for o in self.orders(open_only=True) if any(ln["material_id"] == mid for ln in o["lines"])]
        docs = self.db.q("""SELECT d.*, f.ext, f.size FROM material_docs d LEFT JOIN patient_files f ON f.id = d.file_id
                            WHERE d.material_id=? AND d.deleted=0 ORDER BY d.created_at, d.id""", (mid,))
        for d in docs:
            d["kind_title"] = MAT_DOC_KINDS.get(d["kind"], d["kind"])
            d["image"] = (d.get("ext") or "") in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
        photos = list(dict.fromkeys(x for x in [m.get("photo_id")] + [d["file_id"] for d in docs if d["kind"] == "photo"] if x))
        sup = self.db.one("SELECT id, name, phone FROM suppliers WHERE id=?", (m.get("supplier_id"),)) if m.get("supplier_id") else None
        bar = m.get("barcode") or ""
        ean = bar if barcodes.valid_ean(bar) else ("" if bar else barcodes.internal_ean(mid))
        if m["balance"] <= 0:
            status = ("bad", "Нет в наличии")
        elif usable <= 0:
            status = ("bad", "Просрочено")
        elif m["low"] or (m["min_qty"] and free <= m["min_qty"]):
            status = ("warn", "Заканчивается")
        else:
            status = ("ok", "В наличии")
        return {"reserve": round(reserve, 3), "free": free, "in_transit": round(transit, 3), "status": status,
                "monthly": round(daily * 30, 1), "used30": round(max(0.0, used30), 3), "cover_days": days,
                "cover_pct": round(max(0.0, min(100.0, free / full * 100)), 1) if full else (100.0 if free > 0 else 0.0),
                "cover_full": full, "unit_cost": m["price"] or 0,
                "avg_price": round(buy["v"] / buy["q"], 2) if buy["q"] else (m["price"] or 0), "avg_price_qty": round(buy["q"] or 0, 3),
                "use_months": use_months, "use_total": tot, "orders": orders, "docs": docs, "photos": photos,
                "doc_kinds": [{"kind": k, "title": t, "count": sum(1 for d in docs if d["kind"] == k)} for k, t in MAT_DOC_KINDS.items()],
                "analogs": self.analogs(mid), "supplier": sup,
                "ean": ean, "ean_svg": barcodes.ean_svg(ean) if ean else "", "ean_internal": bool(ean and ean != bar)}

    # ---------------------------------------------------- 3.14: orders to suppliers --
    def orders(self, status=None, open_only=False, limit=300):
        sql, args = "SELECT o.*, s.name AS supplier_name, s.phone AS supplier_phone FROM stock_orders o LEFT JOIN suppliers s ON s.id = o.supplier_id", []
        if open_only:
            sql += f" WHERE o.status IN ({','.join('?' * len(ORDER_OPEN))})"
            args += list(ORDER_OPEN)
        elif status:
            sql += " WHERE o.status=?"
            args.append(status)
        rows = self.db.q(sql + " ORDER BY CASE WHEN o.status IN ('ordered','partial') THEN 0 ELSE 1 END, o.date DESC, o.created_at DESC LIMIT ?",
                         (*args, int(limit)))
        mats = {r["id"]: r for r in self.db.q("SELECT id, name, unit, number, code FROM materials")}
        today = date.today().isoformat()
        for o in rows:
            got = _jl(o["received"], {})
            lines = []
            for ln in _jl(o["lines"], []):
                mm = mats.get(ln.get("material_id")) or {}
                rec = round(float(got.get(ln.get("material_id"), 0) or 0), 3)
                lines.append({**ln, "name": mm.get("name") or "удалённый материал", "unit": mm.get("unit") or "", "number": mm.get("number") or "",
                              "code": mm.get("code") or "", "received": rec, "left": round(max(0.0, float(ln.get("qty") or 0) - rec), 3)})
            o["lines"] = lines
            o["received"] = got
            o["doc_ids"] = _jl(o["doc_ids"], [])
            o["status_title"] = ORDER_STATUS.get(o["status"], o["status"])
            o["late"] = o["status"] in ORDER_OPEN and bool(o["expected"]) and o["expected"] < today
            o["supplier_name"] = o["supplier_name"] or ""
        return rows

    def order(self, oid):
        o = next((x for x in self.orders(limit=100000) if x["id"] == oid), None)
        if not o:
            raise ValueError("Заказ не найден")
        return o

    def save_order(self, f, user=""):
        """«Сформировать закупку»: an order to one supplier. The expected day is the order's day plus the longest delivery term
        of its materials (or the day typed in the form). What is ordered and not received yet is «в пути»."""
        lines = self._lines(f.get("lines"))
        if any(q <= 0 for _, q, _ in lines):
            raise ValueError("Количество в заказе должно быть больше нуля")
        merged = {}
        for mid, q, pr in lines:
            g = merged.setdefault(mid, {"material_id": mid, "qty": 0.0, "price": pr})
            g["qty"] = round(g["qty"] + q, 3)
        sid = str(f.get("supplier_id") or "").strip() or None
        if sid and not self.db.one("SELECT 1 AS x FROM suppliers WHERE id=?", (sid,)):
            raise ValueError("Поставщик не найден")
        day = _day(f.get("date"), "Дата заказа") or date.today().isoformat()
        exp = _day(f.get("expected"), "Ожидается")
        if not exp:
            lead = max([int(r["lead_days"] or 0) for r in self.db.q(
                f"SELECT lead_days FROM materials WHERE id IN ({','.join('?' * len(merged))})", tuple(merged))] or [0])
            exp = (date.fromisoformat(day) + timedelta(days=lead)).isoformat() if lead else ""
        oid, at = _id("PO"), _now()
        n = self.db.one("SELECT COUNT(*) AS n FROM stock_orders")["n"]
        total = round(sum(g["qty"] * g["price"] for g in merged.values()), 2)
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_orders(id, number, supplier_id, date, expected, lines, received, status, total, comment, doc_ids,
                         user_name, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (oid, _clean(f.get("number"), 30) or f"З-{n + 1:04d}", sid, day, exp, json.dumps(list(merged.values()), ensure_ascii=False),
                       "{}", "ordered", total, _clean(f.get("comment"), 500), "[]", user, at, at))
        return oid

    def cancel_order(self, oid):
        o = self.db.one("SELECT * FROM stock_orders WHERE id=?", (str(oid or ""),))
        if not o:
            raise ValueError("Заказ не найден")
        if o["status"] not in ORDER_OPEN:
            raise ValueError("Заказ уже закрыт")
        with self.db.tx() as c:
            c.execute("UPDATE stock_orders SET status='cancelled', updated_at=? WHERE id=?", (_now(), o["id"]))
        return True

    def _order_received(self, c, oid, did, lines):
        """A receipt by an order counts against it: «получен частично» or «получен»."""
        o = c.execute("SELECT lines, received, doc_ids, status FROM stock_orders WHERE id=?", (oid,)).fetchone()
        if not o or o[3] not in ORDER_OPEN:
            raise ValueError("Заказ не найден или уже закрыт")
        want, got, docs = _jl(o[0], []), _jl(o[1], {}), _jl(o[2], [])
        for mid, q, _ in lines:
            got[mid] = round(float(got.get(mid, 0) or 0) + q, 3)
        full = all(float(got.get(ln["material_id"], 0) or 0) + 1e-9 >= float(ln["qty"]) for ln in want)
        c.execute("UPDATE stock_orders SET received=?, doc_ids=?, status=?, updated_at=? WHERE id=?",
                  (json.dumps(got), json.dumps(docs + [did]), "received" if full else "partial", _now(), oid))

    # ------------------------------------------------- 3.14: documents and analogs --
    def material_doc_add(self, mid, kind, title, file_id, user=""):
        m = self.db.one("SELECT id, photo_id FROM materials WHERE id=? AND active=1", (str(mid or ""),))
        if not m:
            raise ValueError("Материал не найден или убран из справочника")
        kind = kind if kind in MAT_DOC_KINDS else "other"
        did = _id("MD")
        with self.db.tx() as c:
            c.execute("INSERT INTO material_docs(id, material_id, kind, title, file_id, created_by, created_at, deleted) VALUES(?,?,?,?,?,?,?,0)",
                      (did, m["id"], kind, _clean(title, 200) or MAT_DOC_KINDS[kind], file_id, user, _now()))
            if kind == "photo" and not m["photo_id"]:
                c.execute("UPDATE materials SET photo_id=? WHERE id=?", (file_id, m["id"]))
        return did

    def material_doc_delete(self, did):
        d = self.db.one("SELECT * FROM material_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        with self.db.tx() as c:
            c.execute("UPDATE material_docs SET deleted=1 WHERE id=?", (d["id"],))
            if c.execute("SELECT 1 FROM materials WHERE id=? AND photo_id=?", (d["material_id"], d["file_id"])).fetchone():
                nxt = c.execute("SELECT file_id FROM material_docs WHERE material_id=? AND kind='photo' AND deleted=0 AND file_id<>? "
                                "ORDER BY created_at LIMIT 1", (d["material_id"], d["file_id"])).fetchone()
                c.execute("UPDATE materials SET photo_id=? WHERE id=?", (nxt[0] if nxt else None, d["material_id"]))
        return d["material_id"]

    def material_doc_file(self, did):
        d = self.db.one("SELECT * FROM material_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        return d

    @staticmethod
    def _pair(a, b):
        a, b = sorted((str(a or ""), str(b or "")))
        return f"{a}|{b}"[:120], a, b

    def analogs(self, mid):
        rows = self.db.q("""SELECT CASE WHEN x.a=? THEN x.b ELSE x.a END AS id FROM material_analogs x
                            WHERE x.deleted=0 AND (x.a=? OR x.b=?)""", (mid, mid, mid))
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        mats = {r["id"]: r for r in self.materials(with_inactive=True) if r["id"] in ids}
        return sorted([{"id": k, "name": mats[k]["name"], "number": mats[k].get("number") or "", "code": mats[k]["code"] or "",
                        "unit": mats[k]["unit"], "balance": mats[k]["balance"], "price": mats[k]["price"] or 0, "active": mats[k]["active"],
                        "photo_id": mats[k].get("photo_id") or ""} for k in ids if k in mats], key=lambda x: x["name"])

    def analog_add(self, mid, other, user=""):
        if not mid or not other or mid == other:
            raise ValueError("Выберите другой материал")
        for x in (mid, other):
            if not self.db.one("SELECT 1 AS x FROM materials WHERE id=? AND active=1", (x,)):
                raise ValueError("Материал не найден")
        key, a, b = self._pair(mid, other)
        with self.db.tx() as c:
            c.execute("""INSERT INTO material_analogs(id, a, b, created_by, created_at, deleted) VALUES(?,?,?,?,?,0)
                         ON CONFLICT(id) DO UPDATE SET deleted=0, created_by=excluded.created_by, created_at=excluded.created_at""",
                      (key, a, b, user, _now()))
        return key

    def analog_delete(self, mid, other):
        key, _, _ = self._pair(mid, other)
        with self.db.tx() as c:
            c.execute("UPDATE material_analogs SET deleted=1 WHERE id=?", (key,))
        return True

    # ------------------------------------------------ 3.14: the label of a material --
    def material_qr_text(self, m, clinic=""):
        """Like the equipment's: a link `<app>/m/<номер>` or the text with the number first."""
        url = self.phone_url()
        if url:
            return f"{url.rstrip('/')}/m/{quote(str(m.get('number') or ''), safe='')}"
        lines = [str(m.get("number") or ""), m["name"], m.get("code") and f"Арт.: {m['code']}",
                 m.get("manufacturer") and f"Производитель: {m['manufacturer']}", clinic]
        return "\n".join(str(x) for x in lines if x)

    def material_by_code(self, code):
        """The material a scanned label points to: the link, the text of the QR or just the number «МТ-0147»."""
        s = str(code or "").strip()
        if not s:
            return None
        m = re.search(r"/m/([^/?#\s]+)", s)
        num = unquote(m[1]) if m else s.splitlines()[0].strip()
        if not num:
            return None
        r = self.db.one("SELECT id FROM materials WHERE number=? AND active=1", (num,))
        if not r:  # «мт-0147» typed by hand: SQLite lower() knows no Cyrillic
            r = next((x for x in self.db.q("SELECT id, number FROM materials WHERE active=1 AND COALESCE(number,'')<>''")
                      if x["number"].casefold() == num.casefold()), None)
        return r["id"] if r else None

    def material_label(self, mid):
        """Printing the label of a material without a barcode writes its internal EAN-13 down, so a desk scanner finds it."""
        m = self.db.one("SELECT * FROM materials WHERE id=?", (str(mid or ""),))
        if not m:
            raise ValueError("Материал не найден")
        if not m["barcode"]:
            ean = barcodes.internal_ean(m["id"])
            if not self.db.one("SELECT 1 AS x FROM materials WHERE barcode=? AND id<>?", (ean, m["id"])):
                with self.db.tx() as c:
                    c.execute("UPDATE materials SET barcode=? WHERE id=? AND COALESCE(barcode,'')=''", (ean, m["id"]))
        return m["id"]

    def material_supplies(self, mid):
        """3.13 «Карточка материала»: every receipt of the material — when, from whom, how much, at what price, by which invoice;
        per supplier: how many deliveries, the last one and the best price; the last supplier and the best current offer.

        A material is bought from different suppliers over time (Marchenko, then Ivanova, then Petrov), so the supplier lives on
        each receipt (`stock_docs.supplier_id`), not on the material."""
        rows = self.db.q("""SELECT m.id, m.qty, m.price, m.at, m.doc_id, m.location_id, m.user_name, d.number AS doc_number,
                                   COALESCE(NULLIF(d.date,''), substr(m.at,1,10)) AS day, d.supplier_id, COALESCE(d.nodoc,0) AS nodoc,
                                   s.name AS supplier_name, l.lot, l.expires
                            FROM stock_moves m LEFT JOIN stock_docs d ON d.id = m.doc_id LEFT JOIN suppliers s ON s.id = d.supplier_id
                            LEFT JOIN stock_lots l ON l.id = (SELECT MIN(x.id) FROM stock_lots x WHERE x.move_id = m.id AND x.qty > 0)
                            WHERE m.material_id=? AND m.kind='receipt' AND m.qty > 0
                            ORDER BY day DESC, m.at DESC, m.id DESC""", (mid,))
        names = self._loc_names()
        by = {}
        for r in rows:
            r["qty"] = round(r["qty"], 3)
            r["sum"] = round(r["qty"] * (r["price"] or 0), 2)
            r["supplier_name"] = r["supplier_name"] or ""
            r["location_name"] = names.get(r.get("location_id") or "", MAIN)
            if not r["supplier_id"]:
                continue
            g = by.get(r["supplier_id"])
            if g is None:  # rows go from the newest, so the first row of a supplier is its last delivery
                g = by[r["supplier_id"]] = {"supplier_id": r["supplier_id"], "supplier_name": r["supplier_name"], "count": 0, "qty": 0.0,
                                            "sum": 0.0, "last_date": r["day"], "last_price": r["price"] or 0, "min_price": None}
            g["count"] += 1
            g["qty"] = round(g["qty"] + r["qty"], 3)
            g["sum"] = round(g["sum"] + r["sum"], 2)
            if (r["price"] or 0) > 0 and (g["min_price"] is None or r["price"] < g["min_price"]):
                g["min_price"] = r["price"]
        sups = sorted(by.values(), key=lambda g: g["last_date"] or "", reverse=True)
        for g in sups:
            g["avg_price"] = round(g["sum"] / g["qty"], 2) if g["qty"] else 0
        priced = [g for g in sups if g["last_price"] > 0]
        best = min(priced, key=lambda g: (g["last_price"], -(date.fromisoformat(g["last_date"]).toordinal() if g["last_date"] else 0))) \
            if priced else None
        for g in sups:
            g["best"] = best is not None and g["supplier_id"] == best["supplier_id"]
        last = next((r for r in rows if r["supplier_id"]), None)
        return {"supplies": rows[:300], "supply_count": len(rows), "supplier_stats": sups,
                "last_supply": last and {"supplier_id": last["supplier_id"], "supplier_name": last["supplier_name"], "date": last["day"],
                                         "price": last["price"] or 0, "qty": last["qty"], "doc_id": last["doc_id"],
                                         "doc_number": last["doc_number"] or ""},
                "best_offer": best and {"supplier_id": best["supplier_id"], "supplier_name": best["supplier_name"],
                                        "price": best["last_price"], "date": best["last_date"]}}

    def material_usage(self, mid, usable):
        """How fast the material goes: services and write-offs over the last 60 days, and how many days the usable stock lasts."""
        since = date.fromordinal(date.today().toordinal() - USAGE_DAYS).isoformat()
        used = -(self.db.one("""SELECT COALESCE(SUM(qty),0) AS q FROM stock_moves WHERE material_id=? AND kind IN ('service','writeoff')
                                AND substr(at,1,10) > ?""", (mid, since))["q"] or 0)
        used = round(max(0.0, used), 3)
        daily = used / USAGE_DAYS
        return {"usage": {"days": USAGE_DAYS, "used": used, "daily": round(daily, 3),
                          "days_left": round(max(0.0, usable) / daily, 1) if daily > 0 else None}}

    def save_material(self, f):
        """3.14: the fields not sent keep their values (the nurse's quick form, the scanner and the importer send only some);
        a new material gets the next number «МТ-…»."""
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите название материала")
        mid = f.get("id") or _id("M")
        old = self.db.one("SELECT * FROM materials WHERE id=?", (mid,)) or {}
        val = lambda k, fn: fn(f[k]) if k in f and f[k] is not None else old.get(k)  # noqa: E731
        bar = _clean(f.get("barcode"), 60) if "barcode" in f and f["barcode"] is not None else (old.get("barcode") or "")
        if bar:
            dup = self.db.one("SELECT name FROM materials WHERE barcode=? AND id<>? AND active=1", (bar, mid))
            if dup:
                raise ValueError(f"Штрихкод {bar} уже указан у материала «{dup['name']}»")
        number = _clean(f.get("number"), 30) if f.get("number") else (old.get("number") or self._next_mat_number())
        if number != old.get("number"):  # only a number being given is checked: two offline computers may have made a pair
            dup = self.db.one("SELECT name FROM materials WHERE number=? AND id<>? AND active=1", (number, mid))
            if dup:
                raise ValueError(f"Номер {number} уже у материала «{dup['name']}»")
        sup_id = val("supplier_id", lambda v: str(v or "").strip() or None)
        if sup_id and not self.db.one("SELECT 1 AS x FROM suppliers WHERE id=?", (sup_id,)):
            sup_id = None
        extra = {k: val(k, lambda v, n=n: _clean(v, n)) or "" for k, n in MAT_TEXT.items()}
        opt = val("opt_qty", lambda v: max(0, _num(v, "Оптимальный остаток"))) or 0
        lead = val("lead_days", lambda v: max(0, min(365, int(_num(v, "Срок поставки"))))) or 0
        with self.db.tx() as c:
            c.execute("""INSERT INTO materials(id, code, name, unit, category, min_qty, price, barcode, comment, active, created_at,
                         number, manufacturer, description, form, shelf_life, storage, opt_qty, lead_days, supplier_id)
                         VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name, unit=excluded.unit,
                         category=excluded.category, min_qty=excluded.min_qty, price=excluded.price,
                         barcode=excluded.barcode, comment=excluded.comment, active=1, number=excluded.number,
                         manufacturer=excluded.manufacturer, description=excluded.description, form=excluded.form,
                         shelf_life=excluded.shelf_life, storage=excluded.storage, opt_qty=excluded.opt_qty,
                         lead_days=excluded.lead_days, supplier_id=excluded.supplier_id""",
                      (mid, val("code", lambda v: _clean(v, 50)) or "", name, val("unit", lambda v: _clean(v, 20)) or "шт",
                       val("category", lambda v: _clean(v, 100)) or "", val("min_qty", lambda v: max(0, _num(v, "Минимальный остаток"))) or 0,
                       val("price", lambda v: max(0, _num(v, "Цена"))) or 0, bar, val("comment", lambda v: _clean(v, 500)) or "",
                       old.get("created_at") or _now(), number, *extra.values(), opt, lead, sup_id))
            sup = f.get("supplier_id") if f.get("supplier_id") and self.db.one("SELECT 1 AS x FROM suppliers WHERE id=?", (f.get("supplier_id"),)) else None
            if f.get("start_qty") and not f.get("id") and not sup:
                q = _num(f["start_qty"])
                if q:
                    c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, reason, user_name, at) VALUES(?,?,?,?,?,?,?)",
                              (mid, q, _num(f.get("price")), "inventory", "Начальный остаток", f.get("_user", ""), _now()))
        if f.get("start_qty") and not f.get("id") and sup and _num(f["start_qty"]) > 0:
            # 3.13: a new material «от поставщика» — the starting stock is that supplier's receipt, so the card shows who it was
            self.receive({"supplier_id": sup, "number": f.get("doc_number"), "lines": [{"material_id": mid, "qty": f["start_qty"], "price": f.get("price")}],
                          "comment": "Начальный остаток"}, f.get("_user", ""))
        return mid

    _MAT_SET = {"min_qty": "Минимальный остаток", "opt_qty": "Оптимальный остаток", "lead_days": "Срок поставки",
                "supplier_id": "Основной поставщик"}

    def material_set(self, mid, field, value):
        """3.14: the four fields under «Общие сведения» are saved at once, one by one (no form, no «Сохранить»)."""
        m = self.db.one("SELECT * FROM materials WHERE id=? AND active=1", (str(mid or ""),))
        if not m:
            raise ValueError("Материал не найден или убран из справочника")
        if field not in self._MAT_SET:
            raise ValueError("Это поле так не меняется")
        if field == "supplier_id":
            v = str(value or "").strip() or None
            if v and not self.db.one("SELECT 1 AS x FROM suppliers WHERE id=? AND active=1", (v,)):
                raise ValueError("Поставщик не найден")
        elif field == "lead_days":
            v = int(max(0, min(365, _num(value, self._MAT_SET[field]))))
        else:
            v = max(0, _num(value, self._MAT_SET[field]))
        with self.db.tx() as c:
            c.execute(f"UPDATE materials SET {field}=? WHERE id=?", (v, m["id"]))
        return v

    _MNUM = re.compile(r"^(.*?)(\d+)$")

    def _next_mat_number(self):
        """The next number of a material: the prefix of the last numbered one goes on (МТ-0147 → МТ-0148), first МТ-0001."""
        rows = self.db.q("SELECT number FROM materials WHERE COALESCE(number,'')<>'' ORDER BY COALESCE(created_at,''), rowid")
        parsed = [(m[1], m[2]) for r in rows if (m := self._MNUM.match(str(r["number"]).strip()))]
        if not parsed:
            return MAT_FIRST
        prefix = parsed[-1][0]
        same = [n for p, n in parsed if p == prefix]
        nxt, width = max(int(n) for n in same) + 1, max(len(n) for n in same)
        used = {str(r["number"]).strip() for r in rows}
        while f"{prefix}{str(nxt).zfill(width)}" in used:
            nxt += 1
        return f"{prefix}{str(nxt).zfill(width)}"

    def delete_material(self, mid):
        with self.db.tx() as c:
            c.execute("UPDATE materials SET active=0 WHERE id=?", (mid,))
            c.execute("DELETE FROM service_materials WHERE material_id=?", (mid,))
        return True

    def balance(self, mid):
        return round(self.db.one("SELECT COALESCE(SUM(qty),0) AS b FROM stock_moves WHERE material_id=?", (mid,))["b"], 3)

    # ============================================================ suppliers --
    def suppliers(self):
        return self.db.q("SELECT * FROM suppliers WHERE active=1 ORDER BY name")

    def save_supplier(self, f):
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите поставщика")
        sid = f.get("id") or _id("S")
        with self.db.tx() as c:
            c.execute("""INSERT INTO suppliers(id, name, phone, inn, comment, active) VALUES(?,?,?,?,?,1)
                         ON CONFLICT(id) DO UPDATE SET name=excluded.name, phone=excluded.phone, inn=excluded.inn,
                         comment=excluded.comment, active=1""",
                      (sid, name, _clean(f.get("phone"), 50), _clean(f.get("inn"), 20), _clean(f.get("comment"), 500)))
        return sid

    def delete_supplier(self, sid):
        with self.db.tx() as c:
            c.execute("UPDATE suppliers SET active=0 WHERE id=?", (sid,))
        return True

    # ============================================== documents: in / out / count --
    def _lines(self, lines):
        out = []
        for ln in lines or []:
            mid = ln.get("material_id")
            if not mid or not self.db.one("SELECT 1 AS x FROM materials WHERE id=?", (mid,)):
                raise ValueError("В документе есть материал, которого нет в справочнике")
            out.append((mid, _num(ln.get("qty")), max(0, _num(ln.get("price"), "Цена"))))
        if not out:
            raise ValueError("Добавьте хотя бы один материал")
        return out

    def receive(self, f, user=""):
        """Supplier invoice (накладная): stock goes up, last purchase price is remembered."""
        lines = self._lines(f.get("lines"))
        if any(q <= 0 for _, q, _ in lines):
            raise ValueError("Количество в приходе должно быть больше нуля")
        # lot number and expiry date of each line (optional; any of the two makes a lot)
        lots = [(_clean(ln.get("lot"), 60), _day(ln.get("expires"))) for ln in f.get("lines") or []]
        did, at = _id("R"), _now()
        day = f.get("date") or date.today().isoformat()
        total = round(sum(q * p for _, q, p in lines), 2)
        loc = self._loc(f.get("location_id"))
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "receipt", _clean(f.get("number"), 50), day, f.get("supplier_id") or None, "",
                       _clean(f.get("comment"), 500), total, user, at, 1 if f.get("nodoc") else 0, loc))
            for (mid, q, p), (lot, exp) in zip(lines, lots):
                cur = c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, user_name, at, location_id)
                                   VALUES(?,?,?,?,?,?,?,?)""", (mid, q, p, "receipt", did, user, f"{day} {at[11:]}", loc))
                if lot or exp:
                    c.execute("INSERT INTO stock_lots(material_id, move_id, lot, expires, qty, created_at) VALUES(?,?,?,?,?,?)",
                              (mid, cur.lastrowid, lot, exp, q, at))
                if p > 0:
                    c.execute("UPDATE materials SET price=? WHERE id=?", (p, mid))
            if f.get("order_id"):  # 3.14: the receipt by an order to a supplier closes it (or a part of it)
                self._order_received(c, str(f["order_id"]), did, lines)
        return did

    def write_off(self, f, user="", did=None, uid=None):
        """Manual write-off (spoiled, expired, used outside a service). Cannot go below zero.

        3.10: `patient_id` of the form goes to the moves (consumption in treatment); `did` and `uid` give the document and its
        moves fixed ids, so a write-off approved on two computers at once stays one write-off after syncing."""
        lines = self._lines(f.get("lines"))
        reason = _clean(f.get("reason"), 300)
        if not reason:
            raise ValueError("Укажите причину списания")
        need = {}
        for mid, q, _ in lines:
            if q <= 0:
                raise ValueError("Количество для списания должно быть больше нуля")
            need[mid] = need.get(mid, 0) + q
        # 3.5: a write-off from a named place cannot take more than that place has; without a place — the clinic's balance
        by_place = "location_id" in f
        loc = self._loc(f.get("location_id"))
        for mid, q in need.items():
            bal = self.location_balance(mid, loc) if by_place else self.balance(mid)
            if q > bal + 1e-9:
                name = self.db.one("SELECT name FROM materials WHERE id=?", (mid,))["name"]
                where = f"в месте «{self.location_name(loc)}»" if by_place else "на складе"
                raise ValueError(f"«{name}»: {where} {bal:g}, списать {q:g} нельзя")
        # a line may name the lot it takes from (write-off of an expired lot): that lot shrinks, not the undated stock
        lot_of, taken = [], {}
        for (mid, q, _), ln in zip(lines, f.get("lines") or []):
            lid = ln.get("lot_id")
            if not lid:
                lot_of.append(None)
                continue
            g = next((x for x in self.lots(mid)["lots"] if str(x["id"]) == str(lid)), None)
            if not g:
                raise ValueError("Партия не найдена или уже списана")
            taken[g["id"]] = taken.get(g["id"], 0) + q
            if taken[g["id"]] > g["left"] + 1e-9:
                q = taken[g["id"]]
                name = self.db.one("SELECT name FROM materials WHERE id=?", (mid,))["name"]
                raise ValueError(f"«{name}», партия {g['lot'] or '—'}: осталось {g['left']:g}, списать {q:g} нельзя")
            lot_of.append(g)
        did, at = did or _id("W"), _now()
        day = f.get("date") or date.today().isoformat()
        tm = str(f.get("time") or "").strip()
        tm = f"{tm}:00"[:8] if re.fullmatch(r"\d{2}:\d{2}", tm) else at[11:]
        pid = _clean(f.get("patient_id"), 60) or None
        has_uid = bool(uid) and "uid" in {r[1] for r in self.db.conn.execute("PRAGMA table_info(stock_moves)")}
        prices = {r["id"]: r["price"] for r in self.db.q("SELECT id, price FROM materials")}
        total = round(sum(q * (prices.get(mid) or 0) for mid, q, _ in lines), 2)
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "writeoff", "" if f.get("nodoc") else self._next_number("writeoff"), day, None, reason,
                       _clean(f.get("comment"), 500), total, user, at, 1 if f.get("nodoc") else 0, loc))
            for i, ((mid, q, _), g) in enumerate(zip(lines, lot_of)):
                why = reason + (f" (партия {g['lot']})" if g and g["lot"] else "")
                cols, vals = ("material_id, qty, price, kind, doc_id, reason, user_name, at, location_id, patient_id",
                              [mid, -q, prices.get(mid) or 0, "writeoff", did, why[:300], user, f"{day} {tm}", loc, pid])
                if has_uid:
                    cols += ", uid"
                    vals.append(f"{uid}-{i}"[:120])
                cur = c.execute(f"INSERT INTO stock_moves({cols}) VALUES({', '.join('?' * len(vals))})", vals)
                if g:
                    c.execute("INSERT INTO stock_lots(material_id, move_id, lot, expires, qty, created_at) VALUES(?,?,?,?,?,?)",
                              (mid, cur.lastrowid, g["lot"], g["expires"], -q, at))
        return did

    def inventory(self, f, user=""):
        """Stock count: actual quantities replace the book ones; differences become moves."""
        counted = []
        for ln in f.get("lines") or []:
            if ln.get("actual") in (None, ""):
                continue
            mid = ln.get("material_id")
            if not self.db.one("SELECT 1 AS x FROM materials WHERE id=?", (mid,)):
                continue
            actual = _num(ln["actual"], "Фактический остаток")
            if actual < 0:
                raise ValueError("Фактический остаток не может быть отрицательным")
            counted.append((mid, actual))
        if not counted:
            raise ValueError("Введите фактический остаток хотя бы по одному материалу")
        did, at = _id("I"), _now()
        diffs = []
        by_place = "location_id" in f  # 3.5: a count of one place compares with that place's balance
        loc = self._loc(f.get("location_id"))
        with self.db.tx() as c:
            for mid, actual in counted:
                if by_place:
                    book = c.execute("SELECT COALESCE(SUM(qty),0) FROM stock_moves WHERE material_id=? AND COALESCE(location_id,'')=?",
                                     (mid, loc or "")).fetchone()[0]
                else:
                    book = c.execute("SELECT COALESCE(SUM(qty),0) FROM stock_moves WHERE material_id=?", (mid,)).fetchone()[0]
                book = round(book, 3)
                d = round(actual - book, 3)
                if abs(d) > 1e-9:
                    price = c.execute("SELECT price FROM materials WHERE id=?", (mid,)).fetchone()[0] or 0
                    c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, reason, user_name, at, location_id)
                                 VALUES(?,?,?,?,?,?,?,?,?)""", (mid, d, price, "inventory", did, "Инвентаризация", user, at, loc))
                    diffs.append({"material_id": mid, "book": book, "actual": actual, "diff": d})
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "inventory", "" if f.get("nodoc") else self._next_number("inventory"), at[:10], None, "Инвентаризация",
                       _clean(f.get("comment"), 500), 0, user, at, 1 if f.get("nodoc") else 0, loc))
        return {"id": did, "counted": len(counted), "diffs": diffs}

    def _next_number(self, kind):
        """Acts are numbered among documented ones only: an internal write-off does not leave a gap in them."""
        n = self.db.one("SELECT COUNT(*) AS n FROM stock_docs WHERE kind=? AND COALESCE(nodoc,0)=0", (kind,))["n"]
        return str(n + 1)

    def day_docs(self, day) -> dict:
        """Receipts and write-offs of a day for the day report: sums with and without documents."""
        rows = self.db.q("""SELECT d.kind, d.number, d.total, COALESCE(d.nodoc,0) AS nodoc, d.reason, d.user_name, s.name AS supplier_name
                            FROM stock_docs d LEFT JOIN suppliers s ON s.id=d.supplier_id
                            WHERE d.date=? AND d.kind IN ('receipt','writeoff') ORDER BY d.created_at""", (day,))
        svc = self.db.one("""SELECT COALESCE(SUM(-qty*price),0) AS v FROM stock_moves WHERE kind='service' AND substr(at,1,10)=?""", (day,))["v"]
        out = {"rows": rows, "service": round(svc or 0, 2)}
        for k in ("receipt", "writeoff"):
            out[k] = round(sum(r["total"] or 0 for r in rows if r["kind"] == k), 2)
            out[k + "_nodoc"] = round(sum(r["total"] or 0 for r in rows if r["kind"] == k and r["nodoc"]), 2)
        return out

    def docs(self, kind=None, limit=200):
        sql = """SELECT d.*, s.name AS supplier_name, (SELECT COUNT(*) FROM stock_moves m WHERE m.doc_id=d.id) AS lines
                 FROM stock_docs d LEFT JOIN suppliers s ON s.id=d.supplier_id"""
        args = []
        if kind:
            sql += " WHERE d.kind=?"
            args.append(kind)
        rows = self.db.q(sql + " ORDER BY d.created_at DESC LIMIT ?", (*args, int(limit)))
        names = self._loc_names()
        for r in rows:
            r["location_name"] = names.get(r.get("location_id") or "", MAIN)
            r["to_location_name"] = names.get(r.get("to_location_id") or "", MAIN) if r["kind"] == "transfer" else ""
            if r["kind"] == "transfer":
                r["lines"] = (r["lines"] or 0) // 2  # two moves per line: − there, + here
        return rows

    def doc(self, did):
        d = self.db.one("""SELECT d.*, s.name AS supplier_name, s.inn AS supplier_inn FROM stock_docs d
                           LEFT JOIN suppliers s ON s.id=d.supplier_id WHERE d.id=?""", (did,))
        if d:
            d["moves"] = self.db.q("""SELECT m.*, t.name, t.unit, t.code FROM stock_moves m JOIN materials t ON t.id=m.material_id
                                      WHERE m.doc_id=? ORDER BY m.id""", (did,))
            names = self._loc_names()
            d["location_name"] = names.get(d.get("location_id") or "", MAIN)
            d["to_location_name"] = names.get(d.get("to_location_id") or "", MAIN)
            for m in d["moves"]:
                m["location_name"] = names.get(m.get("location_id") or "", MAIN)
            if d["kind"] == "transfer":  # one line per material: what went from there to here
                d["moves"] = [m for m in d["moves"] if m["qty"] > 0]
        return d

    def moves(self, material_id=None, day_from=None, day_to=None, kind=None, limit=500, location=None):
        sql = """SELECT m.*, t.name, t.unit, p.name AS patient_name, d.number AS doc_number, COALESCE(d.nodoc,0) AS nodoc
                 FROM stock_moves m JOIN materials t ON t.id = m.material_id
                 LEFT JOIN patients p ON p.id = m.patient_id LEFT JOIN stock_docs d ON d.id = m.doc_id WHERE 1=1"""
        args = []
        if material_id:
            sql += " AND m.material_id=?"
            args.append(material_id)
        if day_from:
            sql += " AND substr(m.at,1,10) >= ?"
            args.append(day_from)
        if day_to:
            sql += " AND substr(m.at,1,10) <= ?"
            args.append(day_to)
        if kind:
            sql += " AND m.kind=?"
            args.append(kind)
        if location is not None:
            sql += " AND COALESCE(m.location_id,'')=?"
            args.append(location or "")
        rows = self.db.q(sql + " ORDER BY m.at DESC, m.id DESC LIMIT ?", (*args, int(limit)))
        names = self._loc_names()
        for r in rows:
            r["kind_title"] = MOVE_KINDS.get(r["kind"], r["kind"])
            r["location_name"] = names.get(r.get("location_id") or "", MAIN)
            if r["kind"] == "service" and str(r.get("doc_id") or "").startswith("V-"):
                r["kind_title"] = "По приёму"  # 3.5: the write-off by a Dentist Plus visit
        return rows

    # ======================================================= places (3.5) --
    def _loc(self, lid):
        """A place id from the form: «» (or nothing) is the main stock; an unknown or closed place is an error."""
        lid = str(lid or "").strip()
        if not lid:
            return None
        if not self.db.one("SELECT 1 AS x FROM stock_locations WHERE id=? AND active=1", (lid,)):
            raise ValueError("Место хранения не найдено")
        return lid

    def _loc_names(self):
        return {"": MAIN, **{r["id"]: r["name"] for r in self.db.q("SELECT id, name FROM stock_locations")}}

    def location_name(self, lid):
        return self._loc_names().get(lid or "", MAIN)

    def location_balance(self, mid, lid):
        return round(self.db.one("SELECT COALESCE(SUM(qty),0) AS b FROM stock_moves WHERE material_id=? AND COALESCE(location_id,'')=?",
                                 (mid, lid or ""))["b"], 3)

    def location_balances(self):
        """{material id: {place id («» — main): balance}} — only places where something is or was."""
        out = {}
        for r in self.db.q("""SELECT material_id, COALESCE(location_id,'') AS loc, SUM(qty) AS q FROM stock_moves
                              GROUP BY material_id, COALESCE(location_id,'')"""):
            out.setdefault(r["material_id"], {})[r["loc"]] = round(r["q"] or 0, 3)
        return out

    def locations(self, with_inactive=False):
        """The main stock first, then the cabinets and branches: how many materials are there and for how much."""
        rows = self.db.q("SELECT * FROM stock_locations WHERE (? OR active=1) ORDER BY sort, name", (1 if with_inactive else 0,))
        prices = {m["id"]: m["price"] or 0 for m in self.db.q("SELECT id, price FROM materials WHERE active=1")}
        bal = self.location_balances()
        stat = {}
        for mid, by in bal.items():
            if mid not in prices:
                continue
            for loc, q in by.items():
                s = stat.setdefault(loc, {"items": 0, "value": 0.0, "negative": 0})
                if abs(q) > 1e-9:
                    s["items"] += 1
                if q > 0:
                    s["value"] += q * prices[mid]
                elif q < -1e-9:
                    s["negative"] += 1
        main = {"id": "", "name": MAIN, "kind": "main", "kind_title": "Основной", "branch_id": "", "chair": "", "active": 1, "comment": ""}
        out = []
        for r in [main] + rows:
            s = stat.get(r["id"], {"items": 0, "value": 0.0, "negative": 0})
            out.append({**r, "kind_title": r.get("kind_title") or LOC_KINDS.get(r["kind"], r["kind"]),
                        "items": s["items"], "value": round(s["value"], 2), "negative": s["negative"]})
        return out

    def save_location(self, f):
        name = _clean(f.get("name"), 100)
        if not name:
            raise ValueError("Укажите название места хранения")
        if name.lower() == MAIN.lower():
            raise ValueError(f"«{MAIN}» уже есть")
        lid = str(f.get("id") or "") or _id("L")
        # SQLite lower() knows only Latin letters: compare in Python so that «кабинет 1» is «Кабинет 1»
        dup = any(r["name"].casefold() == name.casefold() for r in self.db.q("SELECT name FROM stock_locations WHERE id<>? AND active=1", (lid,)))
        if dup:
            raise ValueError(f"Место «{name}» уже есть")
        kind = f.get("kind") if f.get("kind") in LOC_KINDS else "cabinet"
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_locations(id, name, kind, branch_id, chair, active, sort, comment, created_at, updated_at)
                         VALUES(?,?,?,?,?,1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind,
                         branch_id=excluded.branch_id, chair=excluded.chair, sort=excluded.sort, comment=excluded.comment, active=1,
                         updated_at=excluded.updated_at""",
                      (lid, name, kind, _clean(f.get("branch_id"), 40), _clean(f.get("chair"), 100), int(_num(f.get("sort"), "Порядок")),
                       _clean(f.get("comment"), 300), _now(), _now()))
        return lid

    def delete_location(self, lid):
        """A place is closed only when it is empty: move what is left first (the history stays)."""
        if not self.db.one("SELECT 1 AS x FROM stock_locations WHERE id=?", (lid,)):
            raise ValueError("Место хранения не найдено")
        left = [m for m, by in self.location_balances().items() if abs(by.get(lid, 0)) > 1e-9
                and self.db.one("SELECT 1 AS x FROM materials WHERE id=? AND active=1", (m,))]
        if left:
            raise ValueError(f"В этом месте ещё есть материалы ({len(left)}). Сначала переместите их на другое место")
        with self.db.tx() as c:
            c.execute("UPDATE stock_locations SET active=0, updated_at=? WHERE id=?", (_now(), lid))
        return True

    def transfer(self, f, user=""):
        """Move materials from one place to another: one document, − there and + here; the clinic's balance does not change."""
        src, dst = self._loc(f.get("from_id")), self._loc(f.get("to_id"))
        if (src or "") == (dst or ""):
            raise ValueError("Выберите разные места: откуда и куда")
        lines = self._lines(f.get("lines"))
        need = {}
        for mid, q, _ in lines:
            if q <= 0:
                raise ValueError("Количество для перемещения должно быть больше нуля")
            need[mid] = need.get(mid, 0) + q
        for mid, q in need.items():
            have = self.location_balance(mid, src)
            if q > have + 1e-9:
                name = self.db.one("SELECT name FROM materials WHERE id=?", (mid,))["name"]
                raise ValueError(f"«{name}»: в месте «{self.location_name(src)}» {have:g}, переместить {q:g} нельзя")
        did, at = _id("T"), _now()
        day = f.get("date") or date.today().isoformat()
        prices = {r["id"]: r["price"] or 0 for r in self.db.q("SELECT id, price FROM materials")}
        total = round(sum(q * prices.get(mid, 0) for mid, q in need.items()), 2)
        why = f"{self.location_name(src)} → {self.location_name(dst)}"
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id, to_location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "transfer", self._next_number("transfer"), day, None, why, _clean(f.get("comment"), 500), total, user, at,
                       0, src, dst))
            for mid, q in need.items():
                for qty, loc in ((-q, src), (q, dst)):
                    c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, reason, user_name, at, location_id)
                                 VALUES(?,?,?,?,?,?,?,?,?)""", (mid, qty, prices.get(mid, 0), "transfer", did, why, user, f"{day} {at[11:]}", loc))
        return did

    # ================================================ norms + auto write-off --
    def norms(self, service_id=None):
        sql = """SELECT sm.*, m.name, m.unit, m.price, s.title AS service_title FROM service_materials sm
                 JOIN materials m ON m.id=sm.material_id JOIN services s ON s.id=sm.service_id WHERE m.active=1"""
        args = ()
        if service_id:
            sql += " AND sm.service_id=?"
            args = (service_id,)
        return self.db.q(sql + " ORDER BY s.title, m.name", args)

    def save_norms(self, service_id, items):
        if not self.db.one("SELECT 1 AS x FROM services WHERE id=?", (service_id,)):
            raise ValueError("Услуга не найдена")
        with self.db.tx() as c:
            c.execute("DELETE FROM service_materials WHERE service_id=?", (service_id,))
            for it in items or []:
                q = _num(it.get("qty"))
                if it.get("material_id") and q > 0:
                    c.execute("INSERT OR REPLACE INTO service_materials VALUES(?,?,?)", (service_id, it["material_id"], q))
        return self.norms(service_id)

    def on_invoice(self, invoice_id, user=""):
        """Bring the automatic write-off of an invoice in line with its current services."""
        inv = self.db.one("SELECT id, patient_id, visit_id, items, kind, created_at FROM invoices WHERE id=?", (invoice_id,))
        with self.db.tx() as c:
            c.execute("DELETE FROM stock_moves WHERE invoice_id=? AND kind='service'", (invoice_id,))
            if not inv or (inv["kind"] or "invoice") != "invoice":
                return 0
            need = {}
            titles = {}
            for it in json.loads(inv["items"] or "[]"):
                sid = it.get("service_id")
                if not sid:
                    continue
                qty = float(it.get("qty") or 1)
                for n in c.execute("SELECT material_id, qty FROM service_materials WHERE service_id=?", (sid,)).fetchall():
                    need[n[0]] = need.get(n[0], 0) + n[1] * qty
                    titles.setdefault(n[0], []).append(it.get("title") or "")
            loc = None
            if need and self.service_location is not None:
                try:
                    loc = self.service_location(inv) or None
                except Exception:  # noqa: BLE001 — the place never stops the write-off
                    loc = None
            for mid, q in need.items():
                price = (c.execute("SELECT price FROM materials WHERE id=? AND active=1", (mid,)).fetchone() or [None])[0]
                if price is None:
                    continue
                c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, invoice_id, patient_id, reason, user_name, at, location_id)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (mid, -round(q, 3), price or 0, "service", invoice_id, inv["patient_id"],
                           "; ".join(dict.fromkeys(titles[mid]))[:200], user, _now(), loc))
        return len(need)

    # ======================================================= purchase list --
    def offers(self):
        """The last purchase price of every material from every supplier: {material_id: [offer, …] cheapest first}."""
        rows = self.db.q("""SELECT m.material_id, d.supplier_id, s.name AS supplier_name, m.price, substr(m.at,1,10) AS day, m.id
                            FROM stock_moves m JOIN stock_docs d ON d.id = m.doc_id JOIN suppliers s ON s.id = d.supplier_id
                            WHERE m.kind='receipt' AND m.price > 0 AND s.active = 1 ORDER BY m.at, m.id""")
        last = {}
        for r in rows:  # later receipts overwrite earlier ones: one, latest price per supplier
            last[(r["material_id"], r["supplier_id"])] = r
        out = {}
        for r in last.values():
            out.setdefault(r["material_id"], []).append({"supplier_id": r["supplier_id"], "supplier_name": r["supplier_name"],
                                                         "price": r["price"], "date": r["day"]})
        for v in out.values():
            v.sort(key=lambda o: (o["price"], -date.fromisoformat(o["date"]).toordinal() if o["date"] else 0))
        return out

    def purchase_list(self, cover_days=30):
        """What to order now, grouped by the supplier: the material's main one (3.14) or the cheapest.

        Daily use = what services and write-offs took over the last 60 days / 60. Target stock = the optimal stock of the card
        (3.14) or max(2 × minimum, minimum + daily use × cover_days). A material is ordered when its usable stock (expired lots
        do not count) is at or below the minimum, or lasts fewer days than max(14, its delivery term). What is already ordered
        and on its way (3.14) counts as stock: neither ordered twice nor a reason to order."""
        try:
            cover = max(1, min(365, int(float(cover_days or 30))))
        except (TypeError, ValueError):
            cover = 30
        since = date.fromordinal(date.today().toordinal() - USAGE_DAYS).isoformat()
        used = {r["material_id"]: -r["q"] for r in self.db.q(
            """SELECT material_id, SUM(qty) AS q FROM stock_moves WHERE kind IN ('service','writeoff') AND substr(at,1,10) > ?
               GROUP BY material_id""", (since,))}
        offers = self.offers()
        sups = {s["id"]: s for s in self.suppliers()}
        transit = self.in_transit()
        groups = {}
        for m in self.materials():
            daily = max(0.0, used.get(m["id"], 0) or 0) / USAGE_DAYS
            on_way = transit.get(m["id"], 0.0)
            have = round(m["balance"] - m["expired_qty"], 3)
            soon = round(have + on_way, 3)
            days_left = round(soon / daily, 1) if daily > 0 else None
            mn = m["min_qty"] or 0
            lead = int(m.get("lead_days") or 0)
            if not (soon <= mn or (days_left is not None and days_left < max(MIN_DAYS_LEFT, lead))):
                continue
            target = (m.get("opt_qty") or 0) or max(mn * 2, mn + daily * cover)
            qty = math.ceil(round(target - max(0.0, soon), 6))
            if qty <= 0:
                continue
            offs = offers.get(m["id"], [])
            main = m.get("supplier_id") if m.get("supplier_id") in sups else None
            best = next((o for o in offs if o["supplier_id"] == main), None) if main else (offs[0] if offs else None)
            price = best["price"] if best else (m["price"] or 0)
            sid = main or (best["supplier_id"] if best else "")
            g = groups.setdefault(sid, {"supplier_id": sid, "supplier_name": (sups.get(sid) or {}).get("name") or "Поставщик не выбран",
                                        "phone": (sups.get(sid) or {}).get("phone", ""), "inn": (sups.get(sid) or {}).get("inn", ""),
                                        "lines": [], "total": 0})
            g["lines"].append({"material_id": m["id"], "code": m["code"], "number": m.get("number") or "", "name": m["name"], "unit": m["unit"],
                               "category": m["category"], "in_transit": on_way, "lead_days": lead, "main": bool(main),
                               "balance": m["balance"], "usable": have, "expired_qty": m["expired_qty"], "min_qty": mn,
                               "daily": round(daily, 3), "days_left": days_left, "target": round(target, 3), "qty": qty,
                               "price": price, "sum": round(qty * price, 2), "offers": offs,
                               "why": "ниже минимума" if soon <= mn else f"хватит на {days_left:g} дн."})
            g["total"] = round(g["total"] + qty * price, 2)
        out = sorted(groups.values(), key=lambda g: (not g["supplier_id"], g["supplier_name"]))
        return {"cover_days": cover, "groups": out, "count": sum(len(g["lines"]) for g in out),
                "total": round(sum(g["total"] for g in out), 2)}

    # ============================================================ scanner --
    def scan(self, code):
        """A barcode from the scanner → the material with this code (plain EAN or GTIN of a GS1 code) + lot and expiry."""
        p = parse_scan(code)
        if not p["code"]:
            raise ValueError("Пустой штрихкод")
        keys = [k for k in dict.fromkeys((p["code"], p["barcode"], p["gtin"], p["gtin"].lstrip("0"),
                                                  "0" + p["code"] if len(p["code"]) == 13 and p["code"].isdigit() else "")) if k]
        m = None
        for k in keys:
            m = self.db.one("SELECT id FROM materials WHERE barcode=? AND active=1", (k,))
            if m:
                break
        if not m and barcodes.valid_ean(p["code"]) and p["code"].startswith("29"):  # 3.14: the internal EAN of a label
            m = next(({"id": r["id"]} for r in self.db.q("SELECT id FROM materials WHERE active=1 AND COALESCE(barcode,'')=''")
                      if barcodes.internal_ean(r["id"]) == p["code"]), None)
        if not m:  # 3.14: the QR or the number «МТ-0147» of a material label
            k = self.material_by_code(code)
            m = {"id": k} if k else None
        mat = next((x for x in self.materials() if x["id"] == m["id"]), None) if m else None
        # 3.13: the QR of an equipment label opens its card
        return {**p, "material": mat, "equipment_id": None if mat else self.equipment_by_code(code)}

    def summary(self):
        mats = self.materials()
        today = date.today().isoformat()
        eq = self.equipment_list()
        return {"materials": len(mats), "low": sum(1 for m in mats if m["low"]),
                "expired": sum(1 for m in mats if m["exp_state"] == "expired"),
                "expiring": sum(1 for m in mats if m["exp_state"] == "soon"),
                "alerts": sum(1 for m in mats if m["low"] or m["balance"] < 0 or m["exp_state"]),
                "value": round(sum(m["value"] for m in mats if m["balance"] > 0), 2),
                "equipment": sum(1 for e in eq if e["status"] != "written_off"),
                "eq_repair": sum(1 for e in eq if e["status"] == "repair"),  # 3.14
                "eq_residual": round(sum(e["amort"]["residual"] for e in eq if e["status"] != "written_off"), 2),  # 3.10
                "eq_cost": round(sum(e["price"] or 0 for e in eq if e["status"] != "written_off"), 2),
                "service_due": sum(1 for e in eq if e["status"] != "written_off" and e["next_service"] and e["next_service"] <= today)}

    # ============================================================ equipment --
    def _eq_titles(self, r, today=None):
        today = today or date.today().isoformat()
        off = r["status"] == "written_off"
        r["status_title"] = EQ_DISPOSED.get(r.get("disposal_kind") or "writeoff", "Выбыло") if off else EQ_STATUS.get(r["status"], r["status"])
        r["service_due"] = bool(r["next_service"] and r["next_service"] <= today and not off)
        r["condition"] = r.get("condition") or "ok"
        r["ownership"] = r.get("ownership") or "own"
        r["condition_title"] = EQ_CONDITION.get(r["condition"], r["condition"])
        r["ownership_title"] = EQ_OWNERSHIP.get(r["ownership"], r["ownership"])
        r["amort"] = amortization(r)  # 3.10
        r["money"] = True
        return r

    @staticmethod
    def hide_money(e):
        """3.13: the equipment without its money — for someone without «Бухгалтерия»."""
        for r in e if isinstance(e, list) else [e]:
            if not r:
                continue
            for k in (*EQ_MONEY, "amort", "amort_schedule", "chair_hour_cost"):
                r.pop(k, None)
            r["money"] = False
        return e

    def equipment_list(self, q="", show_written_off=False, money=True):
        rows = self.db.q("SELECT * FROM equipment ORDER BY CASE status WHEN 'written_off' THEN 1 ELSE 0 END, location, name")
        today = date.today().isoformat()
        last = {r["equipment_id"]: r["d"] for r in self.db.q(  # 3.14: «Инвентаризация → Оборудование»
            "SELECT equipment_id, MAX(date) AS d FROM equipment_events WHERE kind='inventory' GROUP BY equipment_id")}
        for r in rows:
            self._eq_titles(r, today)
            r["last_inventory_date"] = last.get(r["id"], "")
        if not show_written_off:
            rows = [r for r in rows if r["status"] != "written_off"]
        q = (q or "").strip().lower()
        if q:
            rows = [r for r in rows if q in f"{r['inv_number']} {r['name']} {r['model']} {r['serial']} {r['location']} {r['manufacturer']}".lower()]
        return rows if money else self.hide_money(rows)

    def equipment(self, eid, money=True):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (eid,))
        if not e:
            return e
        self._eq_titles(e)
        e["amort_schedule"] = amort_schedule(e)  # 3.10: depreciation and its months
        e["events"] = self.db.q("SELECT * FROM equipment_events WHERE equipment_id=? ORDER BY date DESC, id DESC", (eid,))
        for ev in e["events"]:
            ev["kind_title"] = EQ_EVENTS.get(ev["kind"], ev["kind"])
            try:
                ev["data"] = json.loads(ev.get("data") or "null")
            except ValueError:
                ev["data"] = None
        # 3.13: documents, the photo gallery, the year's service costs, the chair hour
        docs = self.db.q("""SELECT d.*, f.ext, f.size, f.orig_name FROM equipment_docs d LEFT JOIN patient_files f ON f.id = d.file_id
                            WHERE d.equipment_id=? AND d.deleted=0 ORDER BY d.created_at, d.id""", (eid,))
        for d in docs:
            d["kind_title"] = EQ_DOC_KINDS.get(d["kind"], d["kind"])
            d["image"] = (d.get("ext") or "") in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
        e["docs"] = docs
        have = {d["kind"] for d in docs} | ({"photo"} if e.get("photo_id") else set())
        e["doc_kinds"] = [{"kind": k, "title": EQ_DOC_KINDS[k], "count": sum(1 for d in docs if d["kind"] == k)} for k in EQ_DOC_KINDS]
        e["doc_count"], e["doc_total"] = sum(1 for k in EQ_DOC_MAIN if k in have), len(EQ_DOC_MAIN)
        e["photos"] = list(dict.fromkeys(x for x in [e.get("photo_id")] + [d["file_id"] for d in docs if d["kind"] == "photo"] if x))
        year_ago = (date.today() - timedelta(days=365)).isoformat()
        work = [ev for ev in e["events"] if ev["kind"] in ("service", "repair")]
        e["service_cost_year"] = round(sum(ev["cost"] or 0 for ev in work if (ev["date"] or "") >= year_ago), 2)
        e["service_count_year"] = sum(1 for ev in work if (ev["date"] or "") >= year_ago)
        inv = next((ev for ev in e["events"] if ev["kind"] == "inventory"), None)
        e["last_inventory"] = {"date": inv["date"], "found": bool((inv["data"] or {}).get("found", True)),
                               "diffs": (inv["data"] or {}).get("diffs", []), "user_name": inv["user_name"]} if inv else None
        e["chair_hours"] = self.chair_hours()
        a = e["amort"]
        e["chair_hour_cost"] = round(a["monthly"] / e["chair_hours"], 2) if a["on"] and e["chair_hours"] else 0.0
        if e.get("location_id"):
            p = self.db.one("SELECT name FROM stock_locations WHERE id=?", (e["location_id"],))
            e["location_name"] = p["name"] if p else e["location"]
        else:
            e["location_name"] = e["location"] or ""
        return e if money else self.hide_money(e)

    def _eq_live(self, eid):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (str(eid or ""),))
        if not e:
            raise ValueError("Оборудование не найдено")
        if e["status"] == "written_off":
            raise ValueError("Оборудование выбыло — изменить его нельзя")
        return e

    def _eq_place(self, f, old=None):
        """(location_id, location text): a place of «Места хранения» or a free text («Кабинет 1 · Кресло 1»)."""
        old = old or {}
        if "location_id" in f and f.get("location_id") not in (None, ""):
            p = self.db.one("SELECT id, name FROM stock_locations WHERE id=?", (str(f.get("location_id")),))
            if not p:
                raise ValueError("Такого места нет в «Местах хранения»")
            return p["id"], p["name"]
        if "location" in f:
            loc = _clean(f.get("location"), 100)
            keep = "location_id" not in f and loc == (old.get("location") or "")
            return (old.get("location_id") or "") if keep else "", loc
        if "location_id" in f:  # «— не указано —»
            return "", ""
        return old.get("location_id") or "", old.get("location") or ""

    def save_equipment(self, f, user="", money=True):
        """The card of a piece of equipment. `money` (3.13) — the author has «Бухгалтерия»: without it the cost, the
        depreciation and the replacement money are neither taken from the form nor changed."""
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите название оборудования")
        eid = f.get("id")
        old = self.db.one("SELECT * FROM equipment WHERE id=?", (eid,)) if eid else None
        if old and old["status"] == "written_off":
            raise ValueError("Списанное оборудование изменить нельзя")
        inv = _clean(f.get("inv_number"), 50) or (old["inv_number"] if old and old["inv_number"] else self._next_inv())
        dup = self.db.one("SELECT id FROM equipment WHERE inv_number=? AND id<>?", (inv, eid or ""))
        if dup:
            raise ValueError(f"Инвентарный номер {inv} уже занят")
        status = f.get("status") or (old["status"] if old else "in_use")
        if status not in EQ_STATUS or status == "written_off":
            status = old["status"] if old else "in_use"
        o = old or {}
        lid, loc = self._eq_place(f, o)
        price = max(0, _num(f.get("price"), "Стоимость")) if money else float(o.get("price") or 0)

        def keep(k, fn):
            return fn(f.get(k)) if k in f else (o.get(k) if o.get(k) is not None else "")
        cut = lambda n: (lambda v: _clean(v, n))  # noqa: E731
        vals = (inv, name, keep("category", cut(100)), keep("model", cut(100)), keep("serial", cut(100)), loc,
                keep("responsible", cut(100)), keep("purchase_date", cut(10)), price, keep("warranty_until", cut(10)),
                keep("next_service", cut(10)), status, keep("comment", cut(1000)))
        cond = f.get("condition") if f.get("condition") in EQ_CONDITION else (o.get("condition") or "ok")
        own = f.get("ownership") if f.get("ownership") in EQ_OWNERSHIP else (o.get("ownership") or "own")
        extra = {"manufacturer": keep("manufacturer", cut(100)), "ownership": own, "condition": cond, "location_id": lid,
                 "replace_date": keep("replace_date", lambda v: _day(v, "Плановая дата замены") if v else "")}
        if money:
            for k, title in (("market_value", "Рыночная стоимость"), ("replace_cost", "Стоимость замены"),
                             ("reserve_monthly", "Резерв на обновление")):
                if k in f:
                    extra[k] = max(0, _num(f.get(k), title))
        amort = self._amort_fields(f, price) if money else None
        in_service = _day(f.get("in_service"), "Дата ввода в эксплуатацию") if not money and f.get("in_service") else None
        today = date.today().isoformat()
        ev = "INSERT INTO equipment_events(equipment_id, kind, date, text, user_name, created_at) VALUES(?,?,?,?,?,?)"
        with self.db.tx() as c:
            if old:
                c.execute("""UPDATE equipment SET inv_number=?, name=?, category=?, model=?, serial=?, location=?, responsible=?,
                             purchase_date=?, price=?, warranty_until=?, next_service=?, status=?, comment=? WHERE id=?""", (*vals, eid))
            else:
                eid = _id("E")
                c.execute("""INSERT INTO equipment(inv_number, name, category, model, serial, location, responsible, purchase_date,
                             price, warranty_until, next_service, status, comment, id, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (*vals, eid, _now()))
                c.execute(ev, (eid, "created", today, f"Инв. № {inv}" + (f" · {loc}" if loc else ""), user, _now()))
            c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in extra)} WHERE id=?", (*extra.values(), eid))
            if amort is not None:
                c.execute("UPDATE equipment SET in_service=?, useful_months=?, salvage=?, amort_method=? WHERE id=?", (*amort, eid))
            elif in_service:
                c.execute("UPDATE equipment SET in_service=? WHERE id=?", (in_service, eid))
            if old and (old["location"] or "") != loc:
                c.execute(ev, (eid, "move", today, f"{old['location'] or '—'} → {loc or '—'}", user, _now()))
            if old and old["status"] != status:
                c.execute(ev, (eid, "status", today, f"{EQ_STATUS[old['status']]} → {EQ_STATUS[status]}", user, _now()))
            if old and (old.get("condition") or "ok") != cond:
                c.execute(ev, (eid, "condition", today, f"{EQ_CONDITION[old.get('condition') or 'ok']} → {EQ_CONDITION[cond]}", user, _now()))
        return eid

    @staticmethod
    def _amort_fields(f, price):
        """3.10: (in service, useful life in months, salvage value, method) from the form; None — the form has none of them."""
        keys = ("in_service", "useful_months", "useful_years", "salvage", "amort_method")
        if not any(k in f for k in keys):
            return None
        months = f.get("useful_months")
        if months in (None, "") and f.get("useful_years") not in (None, ""):
            months = _num(f.get("useful_years"), "Срок полезного использования") * 12
        months = int(round(_num(months, "Срок полезного использования"))) if months not in (None, "") else 0
        if months < 0 or months > MAX_USEFUL_MONTHS:
            raise ValueError(f"Срок полезного использования — от 1 месяца до {MAX_USEFUL_MONTHS // 12} лет")
        salvage = max(0, _num(f.get("salvage"), "Ликвидационная стоимость"))
        if months and salvage > price:
            raise ValueError("Ликвидационная стоимость больше стоимости оборудования")
        day = _day(f.get("in_service"), "Дата ввода в эксплуатацию") if f.get("in_service") else ""
        method = f.get("amort_method") if f.get("amort_method") in AMORT_METHODS else "linear"
        return day or None, months or None, salvage, method

    def amort_month(self, month):
        return amort_month(self.db, month)

    def capex_candidates(self):
        """3.14: expenses that look like the purchase of a piece of equipment — the same sum (±1 ₽) within 45 days of its
        purchase or putting into service — but are written down under another category. Next to the depreciation they would
        count the equipment twice; «Перенести» moves them into «Покупка оборудования»."""
        from accounting import CAPEX, SALARY
        eq = [e for e in self.db.q("SELECT * FROM equipment WHERE COALESCE(price,0) > 0") if on_books(e)]
        if not eq:
            return []
        try:
            exps = self.db.q("SELECT * FROM expenses WHERE category NOT IN (?, ?) ORDER BY date", (CAPEX, SALARY))
        except Exception:  # noqa: BLE001 — no accounting tables
            return []
        out, used = [], set()
        for x in exps:
            try:
                xd = date.fromisoformat(str(x["date"])[:10])
            except ValueError:
                continue
            for e in eq:
                day = e.get("purchase_date") or e.get("in_service")
                if e["id"] in used or not day or abs((x["amount"] or 0) - (e["price"] or 0)) > 1:
                    continue
                try:
                    if abs((xd - date.fromisoformat(str(day)[:10])).days) > CAPEX_DAYS:
                        continue
                except ValueError:
                    continue
                used.add(e["id"])
                out.append({"expense_id": x["id"], "date": x["date"], "category": x["category"], "amount": x["amount"],
                            "comment": x["comment"] or "", "equipment_id": e["id"], "name": e["name"], "inv_number": e["inv_number"],
                            "purchase_date": day})
                break
        return out

    def amort_report(self, m_from=None, m_to=None):
        """Depreciation by months for every piece: the charge of each month, the total so far and the book value today."""
        t = date.today()
        a = _mon(m_to) if m_to else _mon(t.isoformat())
        b = _mon(m_from) if m_from else (a - 11 if a is not None else None)
        if a is None or b is None:
            raise ValueError("Укажите месяцы, например 2026-01")
        b, a = min(a, b), max(a, b)
        b = max(b, a - 35)  # at most three years at a time
        months = [_mon_str(k) for k in range(b, a + 1)]
        rows = []
        off = 0
        for e in self.db.q("SELECT * FROM equipment ORDER BY name"):
            am = amortization(e)
            if not am["on"]:
                continue
            if not on_books(e):  # 3.14: rented or the founder's — not in the clinic's depreciation
                off += 1
                continue
            vals = [amort_charge(e, m) for m in months]
            rows.append({"id": e["id"], "inv_number": e["inv_number"], "name": e["name"], "status": e["status"],
                         "status_title": EQ_STATUS.get(e["status"], e["status"]), "cost": am["cost"], "monthly": am["monthly"],
                         "accumulated": am["accumulated"], "residual": am["residual"], "last": am["last"], "done": am["done"],
                         "values": vals, "total": round(sum(vals), 2)})
        no = self.db.one("""SELECT COUNT(*) AS n FROM equipment WHERE status<>'written_off' AND COALESCE(price,0)>0
                            AND COALESCE(useful_months,0)=0""")["n"]
        return {"months": months, "rows": rows, "totals": [round(sum(r["values"][i] for r in rows), 2) for i in range(len(months))],
                "total": round(sum(r["total"] for r in rows), 2), "cost": round(sum(r["cost"] for r in rows), 2),
                "accumulated": round(sum(r["accumulated"] for r in rows), 2), "residual": round(sum(r["residual"] for r in rows), 2),
                "this_month": self.amort_month(t.strftime("%Y-%m")), "without_life": no, "off_books": off}

    # ---------------------------------------- 3.13: inventory numbers, settings --
    _INV = re.compile(r"^(.*?)(\d+)$")

    def _next_inv(self):
        """The next inventory number: the prefix of the last numbered piece goes on (СТ-001 → СТ-002, the width of the
        digits kept); numbers of digits only go on as before (00001 → 00002); the very first one is ОБ-001."""
        rows = self.db.q("SELECT inv_number, created_at FROM equipment WHERE COALESCE(inv_number,'')<>'' ORDER BY created_at, rowid")
        if not rows:
            return INV_FIRST
        parsed = [(m[1], m[2]) for r in rows if (m := self._INV.match(str(r["inv_number"]).strip()))]
        pref = [p for p in parsed if p[0]]
        if pref:
            prefix = pref[-1][0]
            same = [n for p, n in pref if p == prefix]
            nxt, width = max(int(n) for n in same) + 1, max(len(n) for n in same)
            used = {str(r["inv_number"]).strip() for r in rows}
            while f"{prefix}{str(nxt).zfill(width)}" in used:
                nxt += 1
            return f"{prefix}{str(nxt).zfill(width)}"
        nums = [int(n) for p, n in parsed if not p]
        return str(max(nums, default=0) + 1).zfill(5) if nums else INV_FIRST

    def next_inv(self):
        return self._next_inv()

    def chair_hours(self):
        try:
            r = self.db.one("SELECT v FROM stock_settings WHERE k='chair_hours'")
            n = float(r["v"]) if r and r["v"] not in (None, "") else CHAIR_HOURS
        except (ValueError, TypeError):
            n = CHAIR_HOURS
        return n if 0 < n <= 744 else CHAIR_HOURS

    def set_chair_hours(self, n):
        n = _num(n, "Часы кресла в месяц")
        if not 1 <= n <= 744:
            raise ValueError("Часы работы кресла в месяц — от 1 до 744")
        with self.db.tx() as c:
            c.execute("INSERT INTO stock_settings(k, v, updated_at) VALUES('chair_hours', ?, ?) ON CONFLICT(k) DO UPDATE SET "
                      "v=excluded.v, updated_at=excluded.updated_at", (f"{n:g}", _now()))
        return self.chair_hours()

    # -------------------------------------------------- 3.13: events and quick actions --
    def _ev(self, c, eid, kind, text, user, day=None, cost=0, data=None):
        c.execute("INSERT INTO equipment_events(equipment_id, kind, date, text, cost, user_name, created_at, data) VALUES(?,?,?,?,?,?,?,?)",
                  (eid, kind, day or date.today().isoformat(), text, cost, user, _now(),
                   json.dumps(data, ensure_ascii=False) if data is not None else None))

    def equipment_event(self, f, user=""):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (f.get("equipment_id"),))
        if not e:
            raise ValueError("Оборудование не найдено")
        kind = f.get("kind") if f.get("kind") in ("service", "repair", "note") else "note"
        text = _clean(f.get("text"), 1000)
        if not text:
            raise ValueError("Опишите, что сделано")
        day = _day(f.get("date"), "Дата") if f.get("date") else date.today().isoformat()
        with self.db.tx() as c:
            self._ev(c, e["id"], kind, text, user, day, max(0, _num(f.get("cost"), "Стоимость")))
            if f.get("next_service") is not None:
                c.execute("UPDATE equipment SET next_service=? WHERE id=?", (_clean(f.get("next_service"), 10), e["id"]))
            if f.get("back_in_use") and e["status"] == "repair":  # «из ремонта — в работу»
                c.execute("UPDATE equipment SET status='in_use', condition='ok' WHERE id=?", (e["id"],))
                self._ev(c, e["id"], "status", f"{EQ_STATUS['repair']} → {EQ_STATUS['in_use']}", user, day)
        return e["id"]

    def equipment_set(self, f, user=""):
        """The quick changes of the card, saved at once: the place («Переместить»), the condition, who owns it, the status
        («Отправить на ремонт»). Every change is a line of the history."""
        e = self._eq_live(f.get("id"))
        note = _clean(f.get("text"), 500)
        sets, evs = {}, []
        if "location_id" in f or "location" in f:
            lid, loc = self._eq_place(f, e)
            if loc != (e["location"] or "") or lid != (e["location_id"] or ""):
                sets.update(location_id=lid, location=loc)
                evs.append(("move", f"{e['location'] or '—'} → {loc or '—'}"))
        if "condition" in f:
            cond = f.get("condition")
            if cond not in EQ_CONDITION:
                raise ValueError("Выберите техническое состояние")
            if cond != (e["condition"] or "ok"):
                sets["condition"] = cond
                evs.append(("condition", f"{EQ_CONDITION[e['condition'] or 'ok']} → {EQ_CONDITION[cond]}"))
        if "ownership" in f:
            own = f.get("ownership")
            if own not in EQ_OWNERSHIP:
                raise ValueError("Выберите принадлежность")
            if own != (e["ownership"] or "own"):
                sets["ownership"] = own
                evs.append(("note", f"Принадлежность: {EQ_OWNERSHIP[e['ownership'] or 'own']} → {EQ_OWNERSHIP[own]}"))
        if "status" in f:
            st = f.get("status")
            if st not in EQ_STATUS or st == "written_off":
                raise ValueError("Выбытие оформляется отдельно: «Оформить выбытие»")
            if st != e["status"]:
                sets["status"] = st
                if st == "repair":
                    if "condition" not in sets and (e["condition"] or "ok") == "ok":
                        sets["condition"] = "faulty"
                    evs.append(("repair", "Отправлено на ремонт"))
                else:
                    evs.append(("status", f"{EQ_STATUS[e['status']]} → {EQ_STATUS[st]}"))
        if note and evs:
            k, t = evs[-1]
            evs[-1] = (k, f"{t}. {note}")
        if not sets:
            return e["id"]
        with self.db.tx() as c:
            c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), e["id"]))
            for k, t in evs:
                self._ev(c, e["id"], k, t, user)
        return e["id"]

    def equipment_inventory(self, f, user=""):
        """«Провести инвентаризацию»: found or not, where and in what condition; the differences are written down and the card
        takes the place and the condition that were seen."""
        e = self._eq_live(f.get("id"))
        found = f.get("found", True) not in (False, 0, "0", "false", "no")
        comment = _clean(f.get("comment"), 500)
        day = _day(f.get("date"), "Дата") if f.get("date") else date.today().isoformat()
        data, diffs, sets = {"found": found}, [], {}
        if found:
            lid, loc = self._eq_place(f, e) if ("location_id" in f or "location" in f) else (e["location_id"] or "", e["location"] or "")
            if loc != (e["location"] or ""):
                diffs.append(f"место: {e['location'] or '—'} → {loc or '—'}")
                sets.update(location_id=lid, location=loc)
            cond = f.get("condition") or e["condition"] or "ok"
            if cond not in EQ_CONDITION:
                raise ValueError("Выберите техническое состояние")
            if cond != (e["condition"] or "ok"):
                diffs.append(f"состояние: {EQ_CONDITION[e['condition'] or 'ok']} → {EQ_CONDITION[cond]}")
                sets["condition"] = cond
            data.update(location=loc, condition=cond)
        else:
            diffs.append("не найдено на месте")
        data["diffs"] = diffs
        text = ("Найдено" if found else "Не найдено") + ("; расхождения: " + "; ".join(diffs) if found and diffs else
                                                         "; расхождений нет" if found else "") + (f". {comment}" if comment else "")
        with self.db.tx() as c:
            if sets:
                c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), e["id"]))
            self._ev(c, e["id"], "inventory", text, user, day, data=data)
        return e["id"]

    def equipment_inventory_batch(self, lines, user=""):
        """3.14 «Инвентаризация → Оборудование»: several pieces checked in one go (only the rows that were looked at)."""
        out = {"done": 0, "diffs": 0, "not_found": 0}
        for ln in lines or []:
            if not isinstance(ln, dict) or not ln.get("id"):
                continue
            self.equipment_inventory(ln, user)
            ev = self.db.one("SELECT data FROM equipment_events WHERE equipment_id=? AND kind='inventory' ORDER BY id DESC LIMIT 1", (ln["id"],))
            data = json.loads((ev or {}).get("data") or "{}")
            out["done"] += 1
            if not data.get("found", True):
                out["not_found"] += 1
            elif data.get("diffs"):
                out["diffs"] += 1
        if not out["done"]:
            raise ValueError("Отметьте, что найдено и что не найдено")
        return out

    def equipment_inventory_log(self, limit=300):
        """3.14 «Инвентаризация → История»: every check of the equipment, the newest first."""
        rows = self.db.q("""SELECT ev.id, ev.equipment_id, ev.date, ev.text, ev.user_name, ev.data, e.name, e.inv_number
                            FROM equipment_events ev JOIN equipment e ON e.id = ev.equipment_id
                            WHERE ev.kind='inventory' ORDER BY ev.date DESC, ev.id DESC LIMIT ?""", (int(limit),))
        for r in rows:
            try:
                d = json.loads(r.pop("data") or "{}") or {}
            except ValueError:
                d = {}
            r["found"], r["diffs"] = bool(d.get("found", True)), d.get("diffs") or []
        return rows

    def equipment_service_log(self, day_from=None, day_to=None):
        """3.14 «Оборудование → ТО и ремонт»: what is due for service (overdue and within 60 days), and every service and repair
        of the period with its cost."""
        today = date.today()
        a = _day(day_from, "С") if day_from else (today - timedelta(days=365)).isoformat()
        b = _day(day_to, "По") if day_to else today.isoformat()
        a, b = min(a, b), max(a, b)
        soon = (today + timedelta(days=60)).isoformat()
        eq = [e for e in self.equipment_list(money=False) if e["status"] != "written_off"]
        names = self._loc_names()
        due = []
        for e in eq:
            if e["next_service"] and e["next_service"] <= soon:
                due.append({"id": e["id"], "inv_number": e["inv_number"], "name": e["name"], "next_service": e["next_service"],
                            "days": (date.fromisoformat(e["next_service"]) - today).days, "due": e["service_due"],
                            "status": e["status"], "status_title": e["status_title"],
                            "location": names.get(e.get("location_id") or "", "") if e.get("location_id") else e["location"] or ""})
        due.sort(key=lambda x: x["next_service"])
        events = self.db.q("""SELECT ev.id, ev.equipment_id, ev.kind, ev.date, ev.text, ev.cost, ev.user_name, e.name, e.inv_number
                              FROM equipment_events ev JOIN equipment e ON e.id = ev.equipment_id
                              WHERE ev.kind IN ('service','repair') AND ev.date >= ? AND ev.date <= ?
                              ORDER BY ev.date DESC, ev.id DESC""", (a, b))
        for ev in events:
            ev["kind_title"] = EQ_EVENTS.get(ev["kind"], ev["kind"])
        return {"from": a, "to": b, "due": due, "events": events,
                "in_repair": [{"id": e["id"], "inv_number": e["inv_number"], "name": e["name"]} for e in eq if e["status"] == "repair"],
                "cost": round(sum(ev["cost"] or 0 for ev in events), 2),
                "cost_service": round(sum(ev["cost"] or 0 for ev in events if ev["kind"] == "service"), 2),
                "cost_repair": round(sum(ev["cost"] or 0 for ev in events if ev["kind"] == "repair"), 2)}

    def equipment_replace_plan(self, f, user="", money=True):
        """«Запланировать замену»: the date; with «Бухгалтерия» also the market value, the cost of a new one and the monthly
        reserve (empty — worked out: what is missing for a new one over the months left)."""
        e = self._eq_live(f.get("id"))
        day = _day(f.get("replace_date"), "Плановая дата замены") if f.get("replace_date") else ""
        if not day:
            raise ValueError("Укажите плановую дату замены")
        if day <= date.today().isoformat():
            raise ValueError("Плановая дата замены должна быть в будущем")
        sets = {"replace_date": day}
        if money:
            mv = max(0, _num(f.get("market_value"), "Рыночная стоимость")) if "market_value" in f else float(e["market_value"] or 0)
            rc = max(0, _num(f.get("replace_cost"), "Стоимость замены")) if "replace_cost" in f else float(e["replace_cost"] or 0)
            rm = f.get("reserve_monthly")
            if rm in (None, ""):
                months = max(1, (_mon(day) or 0) - (_mon(date.today().isoformat()) or 0))
                rm = round(max(0.0, rc - mv) / months, 2)
            sets.update(market_value=mv, replace_cost=rc, reserve_monthly=max(0, _num(rm, "Резерв на обновление")))
        comment = _clean(f.get("comment"), 300)
        with self.db.tx() as c:
            c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), e["id"]))
            self._ev(c, e["id"], "replace_plan", f"Замена запланирована на {day[8:10]}.{day[5:7]}.{day[:4]}" + (f". {comment}" if comment else ""), user)
        return e["id"]

    def equipment_dispose(self, f, user="", money=True):
        """«Оформить выбытие»: списание и утилизация (the act of the commission, as before), продажа or возврат владельцу
        (leased or the founder's). The piece stays in the register as «выбыло» and is not depreciated after that month."""
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (f.get("id"),))
        if not e:
            raise ValueError("Оборудование не найдено")
        if e["status"] == "written_off":
            raise ValueError("Оборудование уже списано" if (e["disposal_kind"] or "writeoff") == "writeoff" else "Оборудование уже выбыло")
        kind = f.get("kind") if f.get("kind") in EQ_DISPOSAL else "writeoff"
        reason = _clean(f.get("reason"), 500)
        if not reason:
            raise ValueError({"writeoff": "Укажите причину списания", "sale": "Укажите покупателя и основание продажи",
                              "return": "Укажите, кому и по какому документу возвращено"}[kind])
        commission = [_clean(x, 150) for x in (f.get("commission") or []) if _clean(x)]
        if kind == "writeoff" and len(commission) < 2:
            raise ValueError("Укажите председателя и хотя бы одного члена комиссии")
        day = _day(f.get("date"), "Дата") if f.get("date") else date.today().isoformat()
        act = ""
        if kind == "writeoff":
            n = self.db.one("SELECT COUNT(*) AS n FROM equipment WHERE status='written_off' AND COALESCE(disposal_kind,'writeoff')='writeoff'")["n"] + 1
            act = _clean(f.get("act_number"), 30) or str(n)
        # 3.14: the book value is the depreciation's as of the day of the disposal (not of today — a disposal entered later)
        book = amortization({**e, "status": "written_off", "writeoff_date": day})["residual"]
        if money:
            residual = max(0, _num(f.get("residual"), "Остаточная стоимость")) if f.get("residual") not in (None, "") else book
            amount = max(0, _num(f.get("amount"), "Сумма продажи")) if kind == "sale" else 0
        else:  # without «Бухгалтерия» the book value is the depreciation's, the price of a sale is not taken
            residual, amount = book, 0
        text = {"writeoff": f"Акт № {act}: {reason}", "sale": f"Продано: {reason}", "return": f"Возвращено владельцу: {reason}"}[kind]
        with self.db.tx() as c:
            c.execute("""UPDATE equipment SET status='written_off', writeoff_date=?, writeoff_reason=?, writeoff_act=?,
                         writeoff_commission=?, residual=?, disposal_kind=?, disposal_amount=? WHERE id=?""",
                      (day, reason, act, json.dumps(commission, ensure_ascii=False), residual, kind, amount, e["id"]))
            self._ev(c, e["id"], "writeoff" if kind == "writeoff" else "disposal", text, user, day)
        return e["id"]

    def write_off_equipment(self, f, user="", money=True):
        return self.equipment_dispose({**f, "kind": "writeoff"}, user, money)

    # ----------------------------------------------------------- 3.13: documents --
    def equipment_doc_add(self, eid, kind, title, file_id, user=""):
        """A document (or a photo) of the card: the file is a row of patient_files owned by «_stock», so it travels to the
        other computers like the stock photos; the first photo becomes the main one."""
        e = self._eq_live(eid)
        kind = kind if kind in EQ_DOC_KINDS else "other"
        did = _id("ED")
        title = _clean(title, 200) or EQ_DOC_KINDS[kind]
        with self.db.tx() as c:
            c.execute("INSERT INTO equipment_docs(id, equipment_id, kind, title, file_id, created_by, created_at, deleted) VALUES(?,?,?,?,?,?,?,0)",
                      (did, e["id"], kind, title, file_id, user, _now()))
            if kind == "photo" and not e["photo_id"]:
                c.execute("UPDATE equipment SET photo_id=? WHERE id=?", (file_id, e["id"]))
            self._ev(c, e["id"], "doc", f"{EQ_DOC_KINDS[kind]}: {title}", user)
        return did

    def equipment_doc_delete(self, did, user=""):
        d = self.db.one("SELECT * FROM equipment_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        e = self._eq_live(d["equipment_id"])
        with self.db.tx() as c:
            c.execute("UPDATE equipment_docs SET deleted=1 WHERE id=?", (d["id"],))
            if e["photo_id"] == d["file_id"]:
                nxt = c.execute("SELECT file_id FROM equipment_docs WHERE equipment_id=? AND kind='photo' AND deleted=0 AND file_id<>? "
                                "ORDER BY created_at LIMIT 1", (e["id"], d["file_id"])).fetchone()
                c.execute("UPDATE equipment SET photo_id=? WHERE id=?", (nxt[0] if nxt else None, e["id"]))
            self._ev(c, e["id"], "doc", f"Убран документ: {EQ_DOC_KINDS.get(d['kind'], d['kind'])} — {d['title']}", user)
        return e["id"]

    def equipment_doc_file(self, did):
        d = self.db.one("SELECT * FROM equipment_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        return d

    # ------------------------------------------------- 3.13: QR of the inventory label --
    def phone_url(self):
        """The address of the stock's phone app (empty — not set up): a QR then holds a link to the card there."""
        r = self.db.one("SELECT v FROM stock_settings WHERE k='phone_url'")
        u = str((r or {}).get("v") or "").strip()
        return u if re.match(r"^https://[^\s/]+", u) else ""

    def qr_text(self, e, clinic=""):
        """What the QR of a label holds: a link `<app>/e/<инв. №>`, or (no app yet) the text a phone camera shows as it is —
        the number first, so a desk scanner that stops at the line break still types the number."""
        url = self.phone_url()
        if url:
            return f"{url.rstrip('/')}/e/{quote(str(e['inv_number'] or ''), safe='')}"
        lines = [f"Инв. № {e['inv_number']}", e["name"], e.get("model") and f"Модель: {e['model']}",
                 e.get("serial") and f"S/N: {e['serial']}", e.get("location") and f"Место: {e['location']}", clinic]
        return "\n".join(str(x) for x in lines if x)

    def equipment_by_code(self, code):
        """The equipment a scanned label points to: the link of the phone app or the text of the label (or just the number)."""
        s = str(code or "").strip()
        if not s:
            return None
        m = re.search(r"/e/([^/?#\s]+)", s)
        if m:
            inv = unquote(m[1])
        else:
            first = s.splitlines()[0].strip()
            m = re.match(r"^(?:инв\.?\s*№?|inv\.?\s*n?o?\.?)\s*(.+)$", first, re.I)
            inv = (m[1] if m else first).strip()
        r = self.db.one("SELECT id FROM equipment WHERE inv_number=?", (inv,)) or \
            self.db.one("SELECT id FROM equipment WHERE lower(inv_number)=lower(?)", (inv,))
        return r["id"] if r else None
