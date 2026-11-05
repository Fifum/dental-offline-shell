"""Everything created in this app: visits, medical records, documents, invoices, payments.

Nothing here is sent to Dentist Plus. Every row has transferred=0 until staff mark it as
typed into Dentist Plus in the «Перенос» screen.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from normalize import person_name


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id():
    return "L-" + uuid.uuid4().hex[:10]


class Local:
    def __init__(self, db):
        self.db = db

    # ============================================================ patients
    def create_patient(self, f: dict):
        pid = new_id()
        raw = {"id": pid, "lname": f.get("lname", "").strip(), "fname": f.get("fname", "").strip(),
               "mname": f.get("mname", "").strip(), "phone": f.get("phone", "").strip(),
               "birth_date": f.get("birth_date") or "", "gender": f.get("gender", ""),
               "address": f.get("address", "").strip(), "comment": f.get("comment", "").strip(),
               "created_offline": now()}
        self.db.upsert_patients([raw], detail=True)
        with self.db.tx() as c:
            c.execute("UPDATE patients SET local=1 WHERE id=?", (pid,))
        return {"id": pid, "name": person_name(raw)}

    # ============================================================== visits
    def save_visit(self, f: dict):
        """Create a new visit, or edit/move/cancel an existing one (synced or local)."""
        vid = f.get("id")
        ts = now()
        fields = (f.get("patient_id"), f.get("doctor_id") or None, f.get("branch_id") or None,
                  f["start"], f["end"], f.get("status") or "Запланирован", f.get("title", ""), f.get("comment", ""),
                  f.get("chair") or None)
        with self.db.tx() as c:
            if vid and vid.startswith("L-"):
                row = c.execute("SELECT action, origin_id FROM local_visits WHERE id=?", (vid,)).fetchone()
                action = f.get("action") or (row["action"] if row else "create")
                if row and row["action"] == "create" and action != "cancel":
                    action = "create"
                c.execute("""UPDATE local_visits SET patient_id=?, doctor_id=?, branch_id=?, start=?, "end"=?, status=?,
                             title=?, comment=?, chair=?, action=?, updated_at=?, transferred=0, transferred_at=NULL, push_status=NULL, push_error=NULL WHERE id=?""",
                          (*fields, action, ts, vid))
                return vid
            new = new_id()
            action = f.get("action") or ("edit" if vid else "create")
            c.execute("""INSERT INTO local_visits(id, origin_id, patient_id, doctor_id, branch_id, start, "end", status,
                         title, comment, chair, action, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (new, vid, *fields, action, ts, ts))
            return new

    def set_visit_status(self, vid: str, status: str):
        v = self.db.visit(vid)
        if not v:
            return None
        action = "cancel" if status.lower().startswith("отмен") else "status"
        if v["local"] and v["action"] == "create":
            action = "create" if action != "cancel" else "cancel"
        return self.save_visit({"id": v["id"] if v["local"] else (v["origin_id"] or v["id"]),
                                "patient_id": v["patient_id"], "doctor_id": v["doctor_id"], "branch_id": v["branch_id"],
                                "start": v["start"], "end": v["end"], "status": status, "title": v["title"], "chair": v.get("chair"),
                                "comment": v.get("comment", ""), "action": action})

    def revert_visit(self, local_id: str):
        with self.db.tx() as c:
            c.execute("DELETE FROM local_visits WHERE id=?", (local_id,))

    # ============================================================= records
    def save_record(self, f: dict):
        rid = f.get("id") or new_id()
        ts = now()
        data = {k: f.get(k) for k in ("complaints", "anamnesis", "objective", "diagnoses", "teeth",
                                      "treatment", "recommendations", "services_done", "next_visit")}
        with self.db.tx() as c:
            exists = c.execute("SELECT 1 FROM records WHERE id=?", (rid,)).fetchone()
            if exists:
                c.execute("""UPDATE records SET doctor_id=?, date=?, data=?, updated_at=?, transferred=0, transferred_at=NULL
                             WHERE id=?""", (f.get("doctor_id"), f.get("date"), json.dumps(data, ensure_ascii=False), ts, rid))
            else:
                c.execute("""INSERT INTO records(id, patient_id, visit_id, doctor_id, date, data, created_at, updated_at)
                             VALUES(?,?,?,?,?,?,?,?)""",
                          (rid, f["patient_id"], f.get("visit_id"), f.get("doctor_id"), f.get("date"),
                           json.dumps(data, ensure_ascii=False), ts, ts))
        return rid

    def records(self, pid):
        rows = self.db.q("""SELECT r.*, d.name AS doctor_name FROM records r LEFT JOIN doctors d ON d.id=r.doctor_id
                            WHERE r.patient_id=? ORDER BY r.date DESC, r.created_at DESC""", (pid,))
        for r in rows:
            r["data"] = json.loads(r["data"] or "{}")
        return rows

    def record(self, rid):
        r = self.db.one("SELECT r.*, d.name AS doctor_name FROM records r LEFT JOIN doctors d ON d.id=r.doctor_id WHERE r.id=?", (rid,))
        if r:
            r["data"] = json.loads(r["data"] or "{}")
        return r

    def delete_record(self, rid):
        with self.db.tx() as c:
            c.execute("DELETE FROM records WHERE id=?", (rid,))

    def teeth_state(self, pid):
        """Latest status per tooth from local records (newest wins)."""
        out = {}
        for r in reversed(self.records(pid)):
            for t, s in (r["data"].get("teeth") or {}).items():
                if s:
                    out[t] = s
        return out

    # =========================================================== templates
    def templates(self, kind=None):
        sql, args = "SELECT * FROM templates", []
        if kind:
            sql += " WHERE kind=?"
            args.append(kind)
        return self.db.q(sql + " ORDER BY kind, category, sort, title", args)

    def save_template(self, t: dict):
        tid = t.get("id") or new_id()
        with self.db.tx() as c:
            c.execute("""INSERT INTO templates(id, kind, category, title, body, builtin, sort, updated_at)
                         VALUES(?,?,?,?,?,0,?,?) ON CONFLICT(id) DO UPDATE SET category=excluded.category,
                         title=excluded.title, body=excluded.body, updated_at=excluded.updated_at""",
                      (tid, t["kind"], t.get("category", ""), t["title"], t["body"], int(t.get("sort", 100)), now()))
        return tid

    def delete_template(self, tid):
        with self.db.tx() as c:
            c.execute("DELETE FROM templates WHERE id=?", (tid,))

    # =========================================================== documents
    def save_document(self, d: dict):
        did = d.get("id") or new_id()
        with self.db.tx() as c:
            exists = c.execute("SELECT 1 FROM documents WHERE id=?", (did,)).fetchone()
            if exists:
                c.execute("UPDATE documents SET title=?, html=?, data=?, transferred=0, transferred_at=NULL WHERE id=?",
                          (d["title"], d["html"], json.dumps(d.get("data") or {}, ensure_ascii=False), did))
            else:
                c.execute("""INSERT INTO documents(id, patient_id, template_id, title, html, data, created_at)
                             VALUES(?,?,?,?,?,?,?)""",
                          (did, d["patient_id"], d.get("template_id"), d["title"], d["html"],
                           json.dumps(d.get("data") or {}, ensure_ascii=False), now()))
        return did

    def documents(self, pid):
        return self.db.q("SELECT id, title, template_id, created_at, transferred FROM documents WHERE patient_id=? ORDER BY created_at DESC", (pid,))

    def document(self, did):
        return self.db.one("SELECT * FROM documents WHERE id=?", (did,))

    def delete_document(self, did):
        with self.db.tx() as c:
            c.execute("DELETE FROM documents WHERE id=?", (did,))

    # ============================================================ services
    def services(self, q=""):
        q = (q or "").strip().lower()
        rows = self.db.q("SELECT * FROM services WHERE active=1 ORDER BY category, code, title")
        if q:
            rows = [r for r in rows if q in f"{r['code']} {r['title']} {r['category']}".lower()]
        return rows

    def save_service(self, s: dict):
        sid = s.get("id") or new_id()
        with self.db.tx() as c:
            c.execute("""INSERT INTO services(id, code, title, price, category, source, active) VALUES(?,?,?,?,?,?,1)
                         ON CONFLICT(id) DO UPDATE SET code=excluded.code, title=excluded.title, price=excluded.price,
                         category=excluded.category""",
                      (sid, s.get("code", ""), s["title"], float(s.get("price") or 0), s.get("category", ""), s.get("source", "local")))
        return sid

    def delete_service(self, sid):
        with self.db.tx() as c:
            c.execute("UPDATE services SET active=0 WHERE id=?", (sid,))

    def import_services_csv(self, text: str):
        import csv
        import io
        sample = text[:2000]
        delim = ";" if sample.count(";") > sample.count(",") else ","
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        if not rows:
            return 0
        head = [h.strip().lower() for h in rows[0]]

        def col(*names):
            for i, h in enumerate(head):
                if any(n in h for n in names):
                    return i
            return None
        ic, it, ip, ig = col("код", "code", "артикул"), col("назв", "услуг", "title", "name"), col("цена", "стоим", "price"), col("катег", "раздел", "group", "category")
        start = 1
        if it is None or ip is None:  # no header: code;title;price;category
            ic, it, ip, ig, start = 0, 1, 2, 3, 0
        n = 0
        for r in rows[start:]:
            if len(r) <= max(it, ip) or not r[it].strip():
                continue
            try:
                price = float(r[ip].replace(" ", "").replace("\xa0", "").replace(",", ".") or 0)
            except ValueError:
                continue
            self.save_service({"code": r[ic].strip() if ic is not None and ic < len(r) else "", "title": r[it].strip(),
                               "price": price, "category": r[ig].strip() if ig is not None and ig < len(r) else "",
                               "source": "import"})
            n += 1
        return n

    # ======================================================= invoices/cash
    def save_invoice(self, inv: dict):
        iid = inv.get("id") or new_id()
        items = inv.get("items") or []
        total = 0.0
        for it in items:
            line = float(it.get("price") or 0) * float(it.get("qty") or 1)
            line -= line * float(it.get("discount") or 0) / 100
            it["sum"] = round(line, 2)
            total += line
        disc = float(inv.get("discount") or 0)
        total = round(total - total * disc / 100, 2)
        kind = inv.get("kind") or "invoice"
        with self.db.tx() as c:
            exists = c.execute("SELECT 1 FROM invoices WHERE id=?", (iid,)).fetchone()
            vals = (inv.get("doctor_id"), json.dumps(items, ensure_ascii=False), total, disc, inv.get("comment", ""),
                    inv.get("title") or "", inv.get("plan_status") or ("Предварительный" if kind == "plan" else None))
            if exists:
                c.execute("""UPDATE invoices SET doctor_id=?, items=?, total=?, discount=?, comment=?, title=?, plan_status=?,
                             transferred=0, transferred_at=NULL WHERE id=?""", (*vals, iid))
            else:
                c.execute("""INSERT INTO invoices(id, patient_id, visit_id, doctor_id, items, total, discount, comment, title,
                             plan_status, kind, status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (iid, inv["patient_id"], inv.get("visit_id"), *vals, kind,
                           "План" if kind == "plan" else "Не оплачен", now()))
        if kind != "plan":
            self._invoice_status(iid)
        return iid

    def plan_to_invoice(self, plan_id, item_indexes=None, visit_id=None):
        """Bill (part of) a treatment plan: copies chosen items into a new invoice."""
        plan = self.invoice(plan_id)
        if not plan:
            raise ValueError("План не найден")
        items = plan["items"] if item_indexes is None else [plan["items"][i] for i in item_indexes if i < len(plan["items"])]
        iid = self.save_invoice({"patient_id": plan["patient_id"], "visit_id": visit_id, "doctor_id": plan["doctor_id"],
                                 "items": [{k: v for k, v in it.items() if k != "sum"} for it in items],
                                 "comment": f"По плану лечения от {plan['created_at'][:10]}"})
        with self.db.tx() as c:
            c.execute("UPDATE invoices SET plan_status='Активен', transferred=0 WHERE id=? AND plan_status!='Лечение завершено'", (plan_id,))
        return iid

    def _invoice_status(self, iid):
        inv = self.db.one("SELECT total FROM invoices WHERE id=?", (iid,))
        if not inv:
            return
        paid = self.db.one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE invoice_id=?", (iid,))["s"]
        st = "Оплачен" if paid >= inv["total"] - 0.009 and inv["total"] > 0 else ("Частично оплачен" if paid > 0 else "Не оплачен")
        with self.db.tx() as c:
            c.execute("UPDATE invoices SET status=? WHERE id=?", (st, iid))

    def invoices(self, pid=None, day=None):
        sql = """SELECT i.*, d.name AS doctor_name, p.name AS patient_name,
                        (SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=i.id) AS paid
                 FROM invoices i LEFT JOIN doctors d ON d.id=i.doctor_id LEFT JOIN patients p ON p.id=i.patient_id"""
        args = []
        if pid:
            sql += " WHERE i.patient_id=?"
            args.append(pid)
        elif day:
            sql += " WHERE substr(i.created_at,1,10)=? AND COALESCE(i.kind,'invoice')='invoice'"
            args.append(day)
        rows = self.db.q(sql + " ORDER BY i.created_at DESC", args)
        for r in rows:
            r["items"] = json.loads(r["items"] or "[]")
            r["payments"] = self.db.q("SELECT * FROM payments WHERE invoice_id=? ORDER BY created_at", (r["id"],))
        return rows

    def invoice(self, iid):
        rows = [r for r in self.invoices() if r["id"] == iid]
        return rows[0] if rows else None

    def delete_invoice(self, iid):
        with self.db.tx() as c:
            c.execute("DELETE FROM payments WHERE invoice_id=?", (iid,))
            c.execute("DELETE FROM invoices WHERE id=?", (iid,))

    def add_payment(self, p: dict):
        amount = round(float(p.get("amount") or 0), 2)
        if amount <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        pid = new_id()
        inv = self.db.one("SELECT patient_id FROM invoices WHERE id=?", (p.get("invoice_id"),)) if p.get("invoice_id") else None
        with self.db.tx() as c:
            c.execute("""INSERT INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at)
                         VALUES(?,?,?,?,?,?,?)""",
                      (pid, p.get("invoice_id"), inv["patient_id"] if inv else p.get("patient_id"), amount,
                       p.get("method", "Наличные"), p.get("comment", ""), now()))
        if p.get("invoice_id"):
            self._invoice_status(p["invoice_id"])
        return pid

    def delete_payment(self, pay_id):
        row = self.db.one("SELECT invoice_id FROM payments WHERE id=?", (pay_id,))
        with self.db.tx() as c:
            c.execute("DELETE FROM payments WHERE id=?", (pay_id,))
        if row and row["invoice_id"]:
            self._invoice_status(row["invoice_id"])

    def balance(self, pid):
        billed = self.db.one("SELECT COALESCE(SUM(total),0) s FROM invoices WHERE patient_id=? AND COALESCE(kind,'invoice')='invoice'", (pid,))["s"]
        paid = self.db.one("SELECT COALESCE(SUM(amount),0) s FROM payments WHERE patient_id=?", (pid,))["s"]
        return round(paid - billed, 2)

    def cash_day(self, day):
        pays = self.db.q("""SELECT pay.*, p.name AS patient_name FROM payments pay LEFT JOIN patients p ON p.id=pay.patient_id
                            WHERE substr(pay.created_at,1,10)=? ORDER BY pay.created_at""", (day,))
        by = {}
        for x in pays:
            by[x["method"]] = round(by.get(x["method"], 0) + x["amount"], 2)
        return {"payments": pays, "by_method": by, "total": round(sum(by.values()), 2), "invoices": self.invoices(day=day)}

    # ============================================================= journal
    def journal(self, show_done=False):
        """Human-readable list of everything to re-enter into Dentist Plus."""
        flt = "" if show_done else "WHERE x.transferred=0"
        items = []
        pflt = "" if show_done else "AND COALESCE(x.transferred,0)=0"
        for r in self.db.q(f"SELECT x.* FROM patients x WHERE x.local=1 {pflt}"):
            items.append({"table": "patients", "id": r["id"], "kind": "patient", "what": "Новый пациент",
                          "details": f"{r['name']} · {r['phone'] or 'без телефона'}{' · д. р. ' + r['birth'] if r['birth'] else ''}",
                          "patient_id": r["id"], "patient_name": r["name"], "at": r["synced_at"] or "",
                          "transferred": r["transferred"] or 0, "push_status": r["push_status"], "push_error": r["push_error"],
                          "auto": True})
        for r in self.db.q(f"""SELECT x.*, p.name AS patient_name, d.name AS doctor_name, o.start AS old_start, o.status AS old_status
                               FROM local_visits x LEFT JOIN patients p ON p.id=x.patient_id
                               LEFT JOIN doctors d ON d.id=x.doctor_id LEFT JOIN visits o ON o.id=x.origin_id {flt}"""):
            what = {"create": "Новая запись", "edit": "Изменение записи", "move": "Перенос записи",
                    "cancel": "Отмена записи", "status": "Статус записи"}.get(r["action"], "Запись")
            det = f"{r['start'][:16]} · {r['doctor_name'] or 'без врача'} · {r['title'] or ''} · статус «{r['status']}»"
            if r["old_start"] and r["old_start"][:16] != r["start"][:16]:
                det = f"было {r['old_start'][:16]} → стало " + det
            items.append({"table": "local_visits", "id": r["id"], "kind": "visit", "what": what, "details": det,
                          "patient_id": r["patient_id"], "patient_name": r["patient_name"], "at": r["updated_at"],
                          "transferred": r["transferred"], "push_status": r["push_status"], "push_error": r["push_error"],
                          "auto": True})
        for r in self.db.q(f"""SELECT x.*, p.name AS patient_name, d.name AS doctor_name FROM records x
                               LEFT JOIN patients p ON p.id=x.patient_id LEFT JOIN doctors d ON d.id=x.doctor_id {flt}"""):
            data = json.loads(r["data"] or "{}")
            dg = ", ".join(f"{x.get('code', '')} {x.get('title', '')}".strip() for x in data.get("diagnoses") or [])
            items.append({"table": "records", "id": r["id"], "kind": "record", "what": "Запись в медкарту",
                          "details": f"{r['date']} · {r['doctor_name'] or ''}{' · ' + dg if dg else ''}",
                          "patient_id": r["patient_id"], "patient_name": r["patient_name"], "at": r["updated_at"],
                          "transferred": r["transferred"]})
        for r in self.db.q(f"""SELECT x.id, x.patient_id, x.title, x.created_at, x.transferred, p.name AS patient_name
                               FROM documents x LEFT JOIN patients p ON p.id=x.patient_id {flt}"""):
            items.append({"table": "documents", "id": r["id"], "kind": "document", "what": "Документ", "details": r["title"],
                          "patient_id": r["patient_id"], "patient_name": r["patient_name"], "at": r["created_at"],
                          "transferred": r["transferred"]})
        for r in self.db.q(f"""SELECT x.*, p.name AS patient_name FROM invoices x LEFT JOIN patients p ON p.id=x.patient_id {flt}"""):
            its = json.loads(r["items"] or "[]")
            items.append({"table": "invoices", "id": r["id"], "kind": "invoice",
                          "what": "План лечения" if (r.get("kind") == "plan") else "Счёт",
                          "details": f"{r['total']:.2f} ₽ · " + "; ".join(f"{i.get('title')} ×{i.get('qty', 1)}" for i in its)[:220],
                          "patient_id": r["patient_id"], "patient_name": r["patient_name"], "at": r["created_at"],
                          "transferred": r["transferred"]})
        for r in self.db.q(f"""SELECT x.*, p.name AS patient_name FROM payments x LEFT JOIN patients p ON p.id=x.patient_id {flt}"""):
            items.append({"table": "payments", "id": r["id"], "kind": "payment", "what": "Оплата",
                          "details": f"{r['amount']:.2f} ₽ · {r['method']} — пробить чек на кассе",
                          "patient_id": r["patient_id"], "patient_name": r["patient_name"], "at": r["created_at"],
                          "transferred": r["transferred"]})
        items.sort(key=lambda x: x["at"] or "")
        return items

    def mark_transferred(self, table: str, ids: list, done=True):
        if table not in self.db.LOCAL_TABLES + ("patients",):
            raise ValueError("bad table")
        extra = " AND local=1" if table == "patients" else ""
        with self.db.tx() as c:
            for i in ids:
                c.execute(f"UPDATE {table} SET transferred=?, transferred_at=? WHERE id=?{extra}",
                          (1 if done else 0, now() if done else None, i))
