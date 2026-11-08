"""Stock of materials and the clinic's equipment.

Materials: every change of quantity is a row in stock_moves (receipt +, write-off −, inventory ±),
so the balance is always SUM(qty) and the history explains every number. Services can carry
consumption norms; billing a service writes the materials off automatically (and editing or
deleting the invoice puts them back).

Equipment: a register with inventory numbers, location, service history and a write-off act.
"""
from __future__ import annotations

import calendar
import json
import math
import re
import uuid
from datetime import date, datetime

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
"""
SOON_DAYS = 30          # a lot expiring within this many days is highlighted
USAGE_DAYS = 60         # the average daily use for the purchase list is taken over this period
MIN_DAYS_LEFT = 14      # a material that lasts fewer days goes into the purchase list
EXPIRED_REASON = "Истёк срок годности"

MOVE_KINDS = {"receipt": "Приход", "writeoff": "Списание", "service": "По услуге", "inventory": "Инвентаризация",
              "return": "Возврат поставщику"}
EQ_STATUS = {"in_use": "В работе", "repair": "В ремонте", "storage": "На складе", "written_off": "Списано"}
EQ_EVENTS = {"service": "Обслуживание", "repair": "Ремонт", "move": "Перемещение", "note": "Заметка",
             "writeoff": "Списание", "status": "Статус"}
UNITS = ["шт", "уп", "мл", "г", "фл", "амп", "карп", "набор", "пара", "м"]


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


class Stock:
    def __init__(self, db):
        self.db = db
        db.conn.executescript(SCHEMA)
        db.conn.commit()

    # ============================================================ materials --
    def materials(self, q="", only_low=False, with_inactive=False, only_expiring=False):
        rows = self.db.q("""
            SELECT m.*, COALESCE(SUM(s.qty), 0) AS balance,
                   MAX(CASE WHEN s.kind IN ('service','writeoff') THEN s.at END) AS last_used
            FROM materials m LEFT JOIN stock_moves s ON s.material_id = m.id
            WHERE (? OR m.active = 1)
            GROUP BY m.id ORDER BY m.category, m.name""", (1 if with_inactive else 0,))
        q = (q or "").strip().lower()
        lots = self._lots_by_material({r["id"]: r["balance"] for r in rows})
        for r in rows:
            r["balance"] = round(r["balance"], 3)
            r["low"] = r["min_qty"] > 0 and r["balance"] <= r["min_qty"]
            r["value"] = round(r["balance"] * (r["price"] or 0), 2)
            ls = [x for x in lots.get(r["id"], {}).get("lots", []) if x["left"] > 0]
            r["lots"] = len(ls)
            r["expired_qty"] = round(sum(x["left"] for x in ls if x["state"] == "expired"), 3)
            r["soon_qty"] = round(sum(x["left"] for x in ls if x["state"] == "soon"), 3)
            r["expires"] = min((x["expires"] for x in ls if x["expires"]), default="")
            r["exp_state"] = "expired" if r["expired_qty"] > 0 else "soon" if r["soon_qty"] > 0 else ""
        if q:
            rows = [r for r in rows if q in f"{r['code']} {r['name']} {r['category']} {r['barcode']}".lower()]
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
        m["moves"] = self.moves(material_id=mid, limit=200)
        m["norms"] = self.db.q("""SELECT sm.service_id, sm.qty, s.title, s.code FROM service_materials sm
                                  JOIN services s ON s.id = sm.service_id WHERE sm.material_id=? ORDER BY s.title""", (mid,))
        return m

    def save_material(self, f):
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите название материала")
        mid = f.get("id") or _id("M")
        bar = _clean(f.get("barcode"), 60)
        if bar:
            dup = self.db.one("SELECT name FROM materials WHERE barcode=? AND id<>? AND active=1", (bar, mid))
            if dup:
                raise ValueError(f"Штрихкод {bar} уже указан у материала «{dup['name']}»")
        with self.db.tx() as c:
            c.execute("""INSERT INTO materials(id, code, name, unit, category, min_qty, price, barcode, comment, active, created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,1,?)
                         ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name, unit=excluded.unit,
                         category=excluded.category, min_qty=excluded.min_qty, price=excluded.price,
                         barcode=excluded.barcode, comment=excluded.comment, active=1""",
                      (mid, _clean(f.get("code"), 50), name, _clean(f.get("unit"), 20) or "шт", _clean(f.get("category"), 100),
                       max(0, _num(f.get("min_qty"), "Минимальный остаток")), max(0, _num(f.get("price"), "Цена")),
                       bar, _clean(f.get("comment"), 500), _now()))
            if f.get("start_qty") and not f.get("id"):
                q = _num(f["start_qty"])
                if q:
                    c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, reason, user_name, at) VALUES(?,?,?,?,?,?,?)",
                              (mid, q, _num(f.get("price")), "inventory", "Начальный остаток", f.get("_user", ""), _now()))
        return mid

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
        with self.db.tx() as c:
            c.execute("INSERT INTO stock_docs VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (did, "receipt", _clean(f.get("number"), 50), day, f.get("supplier_id") or None, "",
                       _clean(f.get("comment"), 500), total, user, at))
            for (mid, q, p), (lot, exp) in zip(lines, lots):
                cur = c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, user_name, at) VALUES(?,?,?,?,?,?,?)",
                                (mid, q, p, "receipt", did, user, f"{day} {at[11:]}"))
                if lot or exp:
                    c.execute("INSERT INTO stock_lots(material_id, move_id, lot, expires, qty, created_at) VALUES(?,?,?,?,?,?)",
                              (mid, cur.lastrowid, lot, exp, q, at))
                if p > 0:
                    c.execute("UPDATE materials SET price=? WHERE id=?", (p, mid))
        return did

    def write_off(self, f, user=""):
        """Manual write-off (spoiled, expired, used outside a service). Cannot go below zero."""
        lines = self._lines(f.get("lines"))
        reason = _clean(f.get("reason"), 300)
        if not reason:
            raise ValueError("Укажите причину списания")
        need = {}
        for mid, q, _ in lines:
            if q <= 0:
                raise ValueError("Количество для списания должно быть больше нуля")
            need[mid] = need.get(mid, 0) + q
        for mid, q in need.items():
            bal = self.balance(mid)
            if q > bal + 1e-9:
                name = self.db.one("SELECT name FROM materials WHERE id=?", (mid,))["name"]
                raise ValueError(f"«{name}»: на складе {bal:g}, списать {q:g} нельзя")
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
        did, at = _id("W"), _now()
        day = f.get("date") or date.today().isoformat()
        prices = {r["id"]: r["price"] for r in self.db.q("SELECT id, price FROM materials")}
        total = round(sum(q * (prices.get(mid) or 0) for mid, q, _ in lines), 2)
        with self.db.tx() as c:
            c.execute("INSERT INTO stock_docs VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (did, "writeoff", self._next_number("writeoff"), day, None, reason, _clean(f.get("comment"), 500),
                       total, user, at))
            for (mid, q, _), g in zip(lines, lot_of):
                why = reason + (f" (партия {g['lot']})" if g and g["lot"] else "")
                cur = c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, reason, user_name, at) VALUES(?,?,?,?,?,?,?,?)",
                                (mid, -q, prices.get(mid) or 0, "writeoff", did, why[:300], user, f"{day} {at[11:]}"))
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
        with self.db.tx() as c:
            for mid, actual in counted:
                book = round(c.execute("SELECT COALESCE(SUM(qty),0) FROM stock_moves WHERE material_id=?", (mid,)).fetchone()[0], 3)
                d = round(actual - book, 3)
                if abs(d) > 1e-9:
                    price = c.execute("SELECT price FROM materials WHERE id=?", (mid,)).fetchone()[0] or 0
                    c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, reason, user_name, at) VALUES(?,?,?,?,?,?,?,?)",
                              (mid, d, price, "inventory", did, "Инвентаризация", user, at))
                    diffs.append({"material_id": mid, "book": book, "actual": actual, "diff": d})
            c.execute("INSERT INTO stock_docs VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (did, "inventory", self._next_number("inventory"), at[:10], None, "Инвентаризация",
                       _clean(f.get("comment"), 500), 0, user, at))
        return {"id": did, "counted": len(counted), "diffs": diffs}

    def _next_number(self, kind):
        n = self.db.one("SELECT COUNT(*) AS n FROM stock_docs WHERE kind=?", (kind,))["n"]
        return str(n + 1)

    def docs(self, kind=None, limit=200):
        sql = """SELECT d.*, s.name AS supplier_name, (SELECT COUNT(*) FROM stock_moves m WHERE m.doc_id=d.id) AS lines
                 FROM stock_docs d LEFT JOIN suppliers s ON s.id=d.supplier_id"""
        args = []
        if kind:
            sql += " WHERE d.kind=?"
            args.append(kind)
        return self.db.q(sql + " ORDER BY d.created_at DESC LIMIT ?", (*args, int(limit)))

    def doc(self, did):
        d = self.db.one("""SELECT d.*, s.name AS supplier_name, s.inn AS supplier_inn FROM stock_docs d
                           LEFT JOIN suppliers s ON s.id=d.supplier_id WHERE d.id=?""", (did,))
        if d:
            d["moves"] = self.db.q("""SELECT m.*, t.name, t.unit, t.code FROM stock_moves m JOIN materials t ON t.id=m.material_id
                                      WHERE m.doc_id=? ORDER BY m.id""", (did,))
        return d

    def moves(self, material_id=None, day_from=None, day_to=None, kind=None, limit=500):
        sql = """SELECT m.*, t.name, t.unit, p.name AS patient_name, d.number AS doc_number
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
        rows = self.db.q(sql + " ORDER BY m.at DESC, m.id DESC LIMIT ?", (*args, int(limit)))
        for r in rows:
            r["kind_title"] = MOVE_KINDS.get(r["kind"], r["kind"])
        return rows

    # ================================================ norms + auto write-off --
    def norms(self, service_id=None):
        sql = """SELECT sm.*, m.name, m.unit, s.title AS service_title FROM service_materials sm
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
        inv = self.db.one("SELECT id, patient_id, items, kind, created_at FROM invoices WHERE id=?", (invoice_id,))
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
            for mid, q in need.items():
                price = (c.execute("SELECT price FROM materials WHERE id=? AND active=1", (mid,)).fetchone() or [None])[0]
                if price is None:
                    continue
                c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, invoice_id, patient_id, reason, user_name, at)
                             VALUES(?,?,?,?,?,?,?,?,?)""",
                          (mid, -round(q, 3), price or 0, "service", invoice_id, inv["patient_id"],
                           "; ".join(dict.fromkeys(titles[mid]))[:200], user, _now()))
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
        """What to order now, grouped by the cheapest supplier.

        Daily use = what services and write-offs took over the last 60 days / 60. Target stock =
        max(2 × minimum, minimum + daily use × cover_days). A material is ordered when its usable stock
        (expired lots do not count) is at or below the minimum, or lasts fewer than 14 days."""
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
        groups = {}
        for m in self.materials():
            daily = max(0.0, used.get(m["id"], 0) or 0) / USAGE_DAYS
            have = round(m["balance"] - m["expired_qty"], 3)
            days_left = round(have / daily, 1) if daily > 0 else None
            mn = m["min_qty"] or 0
            if not (have <= mn or (days_left is not None and days_left < MIN_DAYS_LEFT)):
                continue
            target = max(mn * 2, mn + daily * cover)
            qty = math.ceil(round(target - max(0.0, have), 6))
            if qty <= 0:
                continue
            offs = offers.get(m["id"], [])
            best = offs[0] if offs else None
            price = best["price"] if best else (m["price"] or 0)
            sid = best["supplier_id"] if best else ""
            g = groups.setdefault(sid, {"supplier_id": sid, "supplier_name": best["supplier_name"] if best else "Поставщик не выбран",
                                        "phone": (sups.get(sid) or {}).get("phone", ""), "inn": (sups.get(sid) or {}).get("inn", ""),
                                        "lines": [], "total": 0})
            g["lines"].append({"material_id": m["id"], "code": m["code"], "name": m["name"], "unit": m["unit"], "category": m["category"],
                               "balance": m["balance"], "usable": have, "expired_qty": m["expired_qty"], "min_qty": mn,
                               "daily": round(daily, 3), "days_left": days_left, "target": round(target, 3), "qty": qty,
                               "price": price, "sum": round(qty * price, 2), "offers": offs,
                               "why": "ниже минимума" if have <= mn else f"хватит на {days_left:g} дн."})
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
        mat = next((x for x in self.materials() if x["id"] == m["id"]), None) if m else None
        return {**p, "material": mat}

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
                "service_due": sum(1 for e in eq if e["status"] != "written_off" and e["next_service"] and e["next_service"] <= today)}

    # ============================================================ equipment --
    def equipment_list(self, q="", show_written_off=False):
        rows = self.db.q("SELECT * FROM equipment ORDER BY CASE status WHEN 'written_off' THEN 1 ELSE 0 END, location, name")
        today = date.today().isoformat()
        for r in rows:
            r["status_title"] = EQ_STATUS.get(r["status"], r["status"])
            r["service_due"] = bool(r["next_service"] and r["next_service"] <= today and r["status"] != "written_off")
        if not show_written_off:
            rows = [r for r in rows if r["status"] != "written_off"]
        q = (q or "").strip().lower()
        if q:
            rows = [r for r in rows if q in f"{r['inv_number']} {r['name']} {r['model']} {r['serial']} {r['location']}".lower()]
        return rows

    def equipment(self, eid):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (eid,))
        if e:
            e["status_title"] = EQ_STATUS.get(e["status"], e["status"])
            e["events"] = self.db.q("SELECT * FROM equipment_events WHERE equipment_id=? ORDER BY date DESC, id DESC", (eid,))
            for ev in e["events"]:
                ev["kind_title"] = EQ_EVENTS.get(ev["kind"], ev["kind"])
        return e

    def save_equipment(self, f, user=""):
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите название оборудования")
        eid = f.get("id")
        old = self.db.one("SELECT * FROM equipment WHERE id=?", (eid,)) if eid else None
        if old and old["status"] == "written_off":
            raise ValueError("Списанное оборудование изменить нельзя")
        inv = _clean(f.get("inv_number"), 50) or self._next_inv()
        dup = self.db.one("SELECT id FROM equipment WHERE inv_number=? AND id<>?", (inv, eid or ""))
        if dup:
            raise ValueError(f"Инвентарный номер {inv} уже занят")
        status = f.get("status") or "in_use"
        if status not in EQ_STATUS or status == "written_off":
            status = old["status"] if old else "in_use"
        vals = (inv, name, _clean(f.get("category"), 100), _clean(f.get("model"), 100), _clean(f.get("serial"), 100),
                _clean(f.get("location"), 100), _clean(f.get("responsible"), 100), _clean(f.get("purchase_date"), 10),
                max(0, _num(f.get("price"), "Стоимость")), _clean(f.get("warranty_until"), 10), _clean(f.get("next_service"), 10),
                status, _clean(f.get("comment"), 1000))
        with self.db.tx() as c:
            if old:
                c.execute("""UPDATE equipment SET inv_number=?, name=?, category=?, model=?, serial=?, location=?, responsible=?,
                             purchase_date=?, price=?, warranty_until=?, next_service=?, status=?, comment=? WHERE id=?""", (*vals, eid))
            else:
                eid = _id("E")
                c.execute("""INSERT INTO equipment(inv_number, name, category, model, serial, location, responsible, purchase_date,
                             price, warranty_until, next_service, status, comment, id, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (*vals, eid, _now()))
            if old and old["location"] != vals[5]:
                c.execute("INSERT INTO equipment_events(equipment_id, kind, date, text, user_name, created_at) VALUES(?,?,?,?,?,?)",
                          (eid, "move", date.today().isoformat(), f"{old['location'] or '—'} → {vals[5] or '—'}", user, _now()))
            if old and old["status"] != status:
                c.execute("INSERT INTO equipment_events(equipment_id, kind, date, text, user_name, created_at) VALUES(?,?,?,?,?,?)",
                          (eid, "status", date.today().isoformat(), f"{EQ_STATUS[old['status']]} → {EQ_STATUS[status]}", user, _now()))
        return eid

    def _next_inv(self):
        nums = [int(r["inv_number"]) for r in self.db.q("SELECT inv_number FROM equipment") if str(r["inv_number"] or "").isdigit()]
        return str(max(nums, default=0) + 1).zfill(5)

    def equipment_event(self, f, user=""):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (f.get("equipment_id"),))
        if not e:
            raise ValueError("Оборудование не найдено")
        kind = f.get("kind") if f.get("kind") in ("service", "repair", "note") else "note"
        text = _clean(f.get("text"), 1000)
        if not text:
            raise ValueError("Опишите, что сделано")
        day = f.get("date") or date.today().isoformat()
        with self.db.tx() as c:
            c.execute("INSERT INTO equipment_events(equipment_id, kind, date, text, cost, user_name, created_at) VALUES(?,?,?,?,?,?,?)",
                      (e["id"], kind, day, text, max(0, _num(f.get("cost"), "Стоимость")), user, _now()))
            if f.get("next_service") is not None:
                c.execute("UPDATE equipment SET next_service=? WHERE id=?", (_clean(f.get("next_service"), 10), e["id"]))
        return self.equipment(e["id"])

    def write_off_equipment(self, f, user=""):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (f.get("id"),))
        if not e:
            raise ValueError("Оборудование не найдено")
        if e["status"] == "written_off":
            raise ValueError("Оборудование уже списано")
        reason = _clean(f.get("reason"), 500)
        if not reason:
            raise ValueError("Укажите причину списания")
        commission = [_clean(x, 150) for x in (f.get("commission") or []) if _clean(x)]
        if len(commission) < 2:
            raise ValueError("Укажите председателя и хотя бы одного члена комиссии")
        day = f.get("date") or date.today().isoformat()
        n = self.db.one("SELECT COUNT(*) AS n FROM equipment WHERE status='written_off'")["n"] + 1
        act = _clean(f.get("act_number"), 30) or str(n)
        with self.db.tx() as c:
            c.execute("""UPDATE equipment SET status='written_off', writeoff_date=?, writeoff_reason=?, writeoff_act=?,
                         writeoff_commission=?, residual=? WHERE id=?""",
                      (day, reason, act, json.dumps(commission, ensure_ascii=False), max(0, _num(f.get("residual"), "Остаточная стоимость")), e["id"]))
            c.execute("INSERT INTO equipment_events(equipment_id, kind, date, text, user_name, created_at) VALUES(?,?,?,?,?,?)",
                      (e["id"], "writeoff", day, f"Акт № {act}: {reason}", user, _now()))
        return self.equipment(e["id"])
