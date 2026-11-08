"""Stock of materials and the clinic's equipment.

Materials: every change of quantity is a row in stock_moves (receipt +, write-off −, inventory ±),
so the balance is always SUM(qty) and the history explains every number. Services can carry
consumption norms; billing a service writes the materials off automatically (and editing or
deleting the invoice puts them back).

Equipment: a register with inventory numbers, location, service history and a write-off act.
"""
from __future__ import annotations

import json
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
"""

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


class Stock:
    def __init__(self, db):
        self.db = db
        db.conn.executescript(SCHEMA)
        db.conn.commit()

    # ============================================================ materials --
    def materials(self, q="", only_low=False, with_inactive=False):
        rows = self.db.q("""
            SELECT m.*, COALESCE(SUM(s.qty), 0) AS balance,
                   MAX(CASE WHEN s.kind IN ('service','writeoff') THEN s.at END) AS last_used
            FROM materials m LEFT JOIN stock_moves s ON s.material_id = m.id
            WHERE (? OR m.active = 1)
            GROUP BY m.id ORDER BY m.category, m.name""", (1 if with_inactive else 0,))
        q = (q or "").strip().lower()
        for r in rows:
            r["balance"] = round(r["balance"], 3)
            r["low"] = r["min_qty"] > 0 and r["balance"] <= r["min_qty"]
            r["value"] = round(r["balance"] * (r["price"] or 0), 2)
        if q:
            rows = [r for r in rows if q in f"{r['code']} {r['name']} {r['category']} {r['barcode']}".lower()]
        if only_low:
            rows = [r for r in rows if r["low"]]
        return rows

    def material(self, mid):
        rows = [r for r in self.materials(with_inactive=True) if r["id"] == mid]
        if not rows:
            return None
        m = rows[0]
        m["moves"] = self.moves(material_id=mid, limit=200)
        m["norms"] = self.db.q("""SELECT sm.service_id, sm.qty, s.title, s.code FROM service_materials sm
                                  JOIN services s ON s.id = sm.service_id WHERE sm.material_id=? ORDER BY s.title""", (mid,))
        return m

    def save_material(self, f):
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите название материала")
        mid = f.get("id") or _id("M")
        with self.db.tx() as c:
            c.execute("""INSERT INTO materials(id, code, name, unit, category, min_qty, price, barcode, comment, active, created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,1,?)
                         ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name, unit=excluded.unit,
                         category=excluded.category, min_qty=excluded.min_qty, price=excluded.price,
                         barcode=excluded.barcode, comment=excluded.comment, active=1""",
                      (mid, _clean(f.get("code"), 50), name, _clean(f.get("unit"), 20) or "шт", _clean(f.get("category"), 100),
                       max(0, _num(f.get("min_qty"), "Минимальный остаток")), max(0, _num(f.get("price"), "Цена")),
                       _clean(f.get("barcode"), 60), _clean(f.get("comment"), 500), _now()))
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
        did, at = _id("R"), _now()
        day = f.get("date") or date.today().isoformat()
        total = round(sum(q * p for _, q, p in lines), 2)
        with self.db.tx() as c:
            c.execute("INSERT INTO stock_docs VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (did, "receipt", _clean(f.get("number"), 50), day, f.get("supplier_id") or None, "",
                       _clean(f.get("comment"), 500), total, user, at))
            for mid, q, p in lines:
                c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, user_name, at) VALUES(?,?,?,?,?,?,?)",
                          (mid, q, p, "receipt", did, user, f"{day} {at[11:]}"))
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
        did, at = _id("W"), _now()
        day = f.get("date") or date.today().isoformat()
        prices = {r["id"]: r["price"] for r in self.db.q("SELECT id, price FROM materials")}
        total = round(sum(q * (prices.get(mid) or 0) for mid, q, _ in lines), 2)
        with self.db.tx() as c:
            c.execute("INSERT INTO stock_docs VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (did, "writeoff", self._next_number("writeoff"), day, None, reason, _clean(f.get("comment"), 500),
                       total, user, at))
            for mid, q, _ in lines:
                c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, reason, user_name, at) VALUES(?,?,?,?,?,?,?,?)",
                          (mid, -q, prices.get(mid) or 0, "writeoff", did, reason, user, f"{day} {at[11:]}"))
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

    def summary(self):
        mats = self.materials()
        today = date.today().isoformat()
        eq = self.equipment_list()
        return {"materials": len(mats), "low": sum(1 for m in mats if m["low"]),
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
