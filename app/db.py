"""Local SQLite storage. WAL + short transactions keep the file safe on power loss."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta

from config import DB_PATH
from normalize import person_name, phone, get, parse_dt, utcnow

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=FULL;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS branches(id TEXT PRIMARY KEY, name TEXT, data TEXT, synced_at TEXT);
CREATE TABLE IF NOT EXISTS doctors(id TEXT PRIMARY KEY, name TEXT, branch_id TEXT, data TEXT, synced_at TEXT);
CREATE TABLE IF NOT EXISTS patients(
    id TEXT PRIMARY KEY, name TEXT, phone TEXT, birth TEXT, search TEXT,
    data TEXT, detail TEXT, synced_at TEXT, detail_synced_at TEXT);
CREATE TABLE IF NOT EXISTS visits(
    id TEXT PRIMARY KEY, patient_id TEXT, doctor_id TEXT, branch_id TEXT,
    start TEXT, "end" TEXT, status TEXT, title TEXT, data TEXT, synced_at TEXT);
CREATE INDEX IF NOT EXISTS ix_visits_start ON visits(start);
CREATE INDEX IF NOT EXISTS ix_visits_patient ON visits(patient_id);
CREATE TABLE IF NOT EXISTS patient_extras(
    patient_id TEXT, kind TEXT, data TEXT, synced_at TEXT, PRIMARY KEY(patient_id, kind));
CREATE TABLE IF NOT EXISTS notes(
    id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, visit_id TEXT,
    text TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS sync_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, started TEXT, finished TEXT,
    ok INTEGER, message TEXT, counts TEXT);

-- ===== data created in this app (offline). transferred=1 -> manually entered into Dentist Plus
CREATE TABLE IF NOT EXISTS local_visits(
    id TEXT PRIMARY KEY, origin_id TEXT, patient_id TEXT, doctor_id TEXT, branch_id TEXT,
    start TEXT, "end" TEXT, status TEXT, title TEXT, comment TEXT, action TEXT,
    created_at TEXT, updated_at TEXT, transferred INTEGER DEFAULT 0, transferred_at TEXT);
CREATE INDEX IF NOT EXISTS ix_lv_start ON local_visits(start);
CREATE TABLE IF NOT EXISTS records(
    id TEXT PRIMARY KEY, patient_id TEXT, visit_id TEXT, doctor_id TEXT, date TEXT,
    data TEXT, created_at TEXT, updated_at TEXT, transferred INTEGER DEFAULT 0, transferred_at TEXT);
CREATE TABLE IF NOT EXISTS documents(
    id TEXT PRIMARY KEY, patient_id TEXT, template_id TEXT, title TEXT, html TEXT, data TEXT,
    created_at TEXT, transferred INTEGER DEFAULT 0, transferred_at TEXT);
CREATE TABLE IF NOT EXISTS templates(
    id TEXT PRIMARY KEY, kind TEXT, category TEXT, title TEXT, body TEXT, builtin INTEGER DEFAULT 0,
    sort INTEGER DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS services(
    id TEXT PRIMARY KEY, code TEXT, title TEXT, price REAL, category TEXT, source TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS invoices(
    id TEXT PRIMARY KEY, patient_id TEXT, visit_id TEXT, doctor_id TEXT, items TEXT,
    total REAL, discount REAL DEFAULT 0, status TEXT, comment TEXT, created_at TEXT,
    transferred INTEGER DEFAULT 0, transferred_at TEXT);
CREATE TABLE IF NOT EXISTS payments(
    id TEXT PRIMARY KEY, invoice_id TEXT, patient_id TEXT, amount REAL, method TEXT,
    comment TEXT, created_at TEXT, transferred INTEGER DEFAULT 0, transferred_at TEXT);
-- ===== history of Dentist Plus visits for the director's analytics: like `visits`, but never purged
CREATE TABLE IF NOT EXISTS visits_archive(
    id TEXT PRIMARY KEY, patient_id TEXT, doctor_id TEXT, branch_id TEXT, start TEXT, "end" TEXT,
    status TEXT, title TEXT, chair TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_va_start ON visits_archive(start);
"""

# chair of a synced visit, from the raw Dentist Plus record (same fields as DB.CHAIR)
_RAW_CHAIR = """COALESCE(json_extract(data,'$.chair.title'), json_extract(data,'$.chair.name'), json_extract(data,'$.chair_name'),
                json_extract(data,'$.chair_title'), json_extract(data,'$.chair'), json_extract(data,'$.cabinet'),
                json_extract(data,'$.room'))"""
_TO_ARCHIVE = f"""INSERT OR REPLACE INTO visits_archive(id, patient_id, doctor_id, branch_id, start, "end", status, title, chair, updated_at)
                  SELECT id, patient_id, doctor_id, branch_id, start, "end", status, title, {_RAW_CHAIR}, synced_at FROM visits"""


class DB:
    def __init__(self, path=DB_PATH):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(patients)")}
        if "local" not in cols:
            self.conn.execute("ALTER TABLE patients ADD COLUMN local INTEGER DEFAULT 0")
        icols = {r[1] for r in self.conn.execute("PRAGMA table_info(invoices)")}
        if "kind" not in icols:  # 'invoice' or 'plan' (treatment plan)
            self.conn.execute("ALTER TABLE invoices ADD COLUMN kind TEXT DEFAULT 'invoice'")
            self.conn.execute("ALTER TABLE invoices ADD COLUMN plan_status TEXT")
            self.conn.execute("ALTER TABLE invoices ADD COLUMN title TEXT")
        lcols = {r[1] for r in self.conn.execute("PRAGMA table_info(local_visits)")}
        if "chair" not in lcols:
            self.conn.execute("ALTER TABLE local_visits ADD COLUMN chair TEXT")
        # automatic transfer to Dentist Plus: remote id + last send result
        for table, extra in (("local_visits", ()), ("patients", ("transferred INTEGER DEFAULT 0", "transferred_at TEXT"))):
            have = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            for col in ("remote_id TEXT", "push_status TEXT", "push_error TEXT", "push_at TEXT", *extra):
                if col.split()[0] not in have:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        lv = {r[1] for r in self.conn.execute("PRAGMA table_info(local_visits)")}
        if "push_force" not in lv:  # «send anyway» despite a double booking in Dentist Plus
            self.conn.execute("ALTER TABLE local_visits ADD COLUMN push_force INTEGER DEFAULT 0")
        if "series_id" not in lv:  # recurring visits: every visit of one series shares the id
            self.conn.execute("ALTER TABLE local_visits ADD COLUMN series_id TEXT")
        if "plan_id" not in {r[1] for r in self.conn.execute("PRAGMA table_info(invoices)")}:
            self.conn.execute("ALTER TABLE invoices ADD COLUMN plan_id TEXT")  # invoice billed from a treatment plan
        icols = {r[1] for r in self.conn.execute("PRAGMA table_info(invoices)")}
        if "variants" not in icols:  # plan options «эконом / стандарт / премиум» (JSON) and the chosen one
            self.conn.execute("ALTER TABLE invoices ADD COLUMN variants TEXT")
        if "variant" not in icols:
            self.conn.execute("ALTER TABLE invoices ADD COLUMN variant TEXT")
        # 2.12: who pays the invoice — an insurance company (ДМС) by a policy or a letter of guarantee
        for col in ("insurer_id TEXT", "ins_doc_id TEXT"):
            if col.split()[0] not in icols:
                self.conn.execute(f"ALTER TABLE invoices ADD COLUMN {col}")
        pcols = {r[1] for r in self.conn.execute("PRAGMA table_info(payments)")}
        for col in ("kind TEXT", "link_id TEXT"):  # 2.12: '' payment, 'refund', 'deposit_use', 'insurance'; rows of one operation
            if col.split()[0] not in pcols:
                self.conn.execute(f"ALTER TABLE payments ADD COLUMN {col}")
        if self.conn.execute("SELECT value FROM meta WHERE key='visits_archive'").fetchone() is None:
            self.conn.execute(_TO_ARCHIVE)  # first start: what is already in the mirror
            self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('visits_archive','1')")
        self.conn.commit()

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                self.conn.execute("BEGIN")
                yield self.conn
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def q(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    # ------------------------------------------------------------ meta --
    def meta_get(self, key, default=None):
        r = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return r["value"] if r else default

    def meta_set(self, key, value):
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    # ---------------------------------------------------------- writes --
    def upsert_branches(self, items):
        now = utcnow()
        with self.tx() as c:
            for b in items:
                if b.get("id") is None:
                    continue
                c.execute("INSERT OR REPLACE INTO branches VALUES(?,?,?,?)",
                          (str(b["id"]), str(get(b, "title", "name", "address", default=b["id"])),
                           json.dumps(b, ensure_ascii=False), now))

    def upsert_doctors(self, items):
        now = utcnow()
        with self.tx() as c:
            for d in items:
                if d.get("id") is None:
                    continue
                br = get(d, "branch_id", "branch.id", "branches.0.id", "branches.0")
                c.execute("INSERT OR REPLACE INTO doctors VALUES(?,?,?,?,?)",
                          (str(d["id"]), person_name(d), str(br) if br is not None and not isinstance(br, dict) else None,
                           json.dumps(d, ensure_ascii=False), now))

    def _patient_row(self, p: dict):
        name = person_name(p)
        ph = phone(p)
        birth = get(p, "birth_date", "birthday", "date_of_birth", "dob", "birth", "birthdate")
        bd = parse_dt(birth)
        birth_s = bd.strftime("%Y-%m-%d") if bd else (str(birth) if birth else "")
        digits = "".join(ch for ch in ph if ch.isdigit())
        card = get(p, "card_number", "card", "medcard_number", "number", default="")
        search = f"{name} {digits} {ph} {card} {p.get('id')}".lower().replace("ё", "е")
        return name, ph, birth_s, search

    def upsert_patients(self, items, detail=False):
        now = utcnow()
        with self.tx() as c:
            for p in items:
                if not isinstance(p, dict) or p.get("id") is None:
                    continue
                pid = str(p["id"])
                name, ph, birth, search = self._patient_row(p)
                raw = json.dumps(p, ensure_ascii=False)
                exists = c.execute("SELECT detail FROM patients WHERE id=?", (pid,)).fetchone()
                if exists is None:
                    c.execute("""INSERT INTO patients(id,name,phone,birth,search,data,detail,synced_at,detail_synced_at)
                                 VALUES(?,?,?,?,?,?,?,?,?)""",
                              (pid, name, ph, birth, search, raw, raw if detail else None, now, now if detail else None))
                elif detail:
                    c.execute("UPDATE patients SET name=?,phone=?,birth=?,search=?,detail=?,detail_synced_at=?,synced_at=? WHERE id=?",
                              (name, ph, birth, search, raw, now, now, pid))
                else:
                    c.execute("UPDATE patients SET name=?,phone=?,birth=?,search=?,data=?,synced_at=? WHERE id=?",
                              (name, ph, birth, search, raw, now, pid))

    def replace_visits(self, date_from: str, date_to: str, visits: list[dict]):
        """Atomically replace all visits in [date_from, date_to] with the fresh list."""
        now = utcnow()
        with self.tx() as c:
            c.execute('DELETE FROM visits WHERE start >= ? AND start < ?',
                      (date_from, (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()))
            for v in visits:
                if not v["id"] or not v["start"]:
                    continue
                c.execute('INSERT OR REPLACE INTO visits VALUES(?,?,?,?,?,?,?,?,?,?)',
                          (v["id"], v["patient_id"], v["doctor_id"], v["branch_id"], v["start"], v["end"],
                           v["status"], v["title"], json.dumps(v["raw"], ensure_ascii=False), now))
            # the archive follows the same window (a visit deleted in Dentist Plus goes from it too), but keeps the past
            end = (date.fromisoformat(date_to) + timedelta(days=1)).isoformat()
            c.execute('DELETE FROM visits_archive WHERE start >= ? AND start < ?', (date_from, end))
            c.execute(_TO_ARCHIVE + ' WHERE start >= ? AND start < ?', (date_from, end))

    def upsert_extra(self, patient_id, kind, data):
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO patient_extras VALUES(?,?,?,?)",
                      (str(patient_id), kind, json.dumps(data, ensure_ascii=False), utcnow()))

    def purge(self, days_back: int):
        border = (date.today() - timedelta(days=days_back)).isoformat()
        with self.tx() as c:
            c.execute("DELETE FROM visits WHERE start < ?", (border,))
            # keep patients that still have visits or local notes
            c.execute("""DELETE FROM patient_extras WHERE patient_id NOT IN (SELECT patient_id FROM visits WHERE patient_id IS NOT NULL)
                         AND patient_id NOT IN (SELECT patient_id FROM notes)""")
            c.execute("""DELETE FROM patients WHERE COALESCE(local,0)=0
                         AND id NOT IN (SELECT patient_id FROM visits WHERE patient_id IS NOT NULL)
                         AND id NOT IN (SELECT patient_id FROM notes WHERE patient_id IS NOT NULL)
                         AND id NOT IN (SELECT patient_id FROM local_visits WHERE patient_id IS NOT NULL)
                         AND id NOT IN (SELECT patient_id FROM records WHERE patient_id IS NOT NULL)
                         AND id NOT IN (SELECT patient_id FROM documents WHERE patient_id IS NOT NULL)
                         AND id NOT IN (SELECT patient_id FROM invoices WHERE patient_id IS NOT NULL)
                         AND (detail_synced_at IS NULL OR detail_synced_at < ?)""", (border,))

    def log_sync(self, started, ok, message, counts):
        with self.tx() as c:
            c.execute("INSERT INTO sync_log(started,finished,ok,message,counts) VALUES(?,?,?,?,?)",
                      (started, utcnow(), 1 if ok else 0, message, json.dumps(counts, ensure_ascii=False)))
            c.execute("DELETE FROM sync_log WHERE id NOT IN (SELECT id FROM sync_log ORDER BY id DESC LIMIT 200)")

    LOCAL_TABLES = ("local_visits", "records", "documents", "invoices", "payments")

    def wipe(self, with_local=True):
        with self.tx() as c:
            for t in ("branches", "doctors", "patients", "visits", "visits_archive", "patient_extras", "sync_log", "meta"):
                c.execute(f"DELETE FROM {t}")
            if with_local:
                for t in self.LOCAL_TABLES + ("notes",):
                    c.execute(f"DELETE FROM {t}")
                c.execute("DELETE FROM services WHERE source='demo'")
                # demo stock and equipment (tables exist once the stock module started)
                for sql in ("DELETE FROM stock_moves WHERE material_id LIKE 'demo_%'",
                            "DELETE FROM stock_docs WHERE id LIKE 'demo_%'",
                            "DELETE FROM service_materials WHERE service_id LIKE 'demo_%' OR material_id LIKE 'demo_%'",
                            "DELETE FROM materials WHERE id LIKE 'demo_%'", "DELETE FROM suppliers WHERE id LIKE 'demo_%'",
                            "DELETE FROM equipment_events WHERE equipment_id LIKE 'demo_%'",
                            "DELETE FROM equipment WHERE id LIKE 'demo_%'",
                            # demo accounting, shifts and marketing (patients are gone, so are their sources and calls)
                            "DELETE FROM expenses WHERE id LIKE 'demo_%'", "DELETE FROM work_shifts WHERE user_name='Демо'",
                            "DELETE FROM salary_schemes WHERE person IN ('d:11','d:12','d:13','d:14','d:15')",
                            "DELETE FROM patient_marketing WHERE patient_id NOT IN (SELECT id FROM patients)",
                            "DELETE FROM kpi_targets WHERE user_name='Демо'",
                            "DELETE FROM marketing_calls WHERE patient_id NOT IN (SELECT id FROM patients)",
                            # demo CRM: requests, scores and tasks of patients that are gone
                            "DELETE FROM crm_leads WHERE created_by='Демо' OR patient_id NOT IN (SELECT id FROM patients)",
                            "DELETE FROM crm_reviews WHERE patient_id NOT IN (SELECT id FROM patients)",
                            "DELETE FROM crm_tasks WHERE created_by='Демо' OR patient_id NOT IN (SELECT id FROM patients)"):
                    try:
                        c.execute(sql)
                    except sqlite3.OperationalError:
                        pass

    def pending_count(self):
        n = sum(self.one(f"SELECT COUNT(*) n FROM {t} WHERE transferred=0")["n"] for t in self.LOCAL_TABLES)
        return n + self.one("SELECT COUNT(*) n FROM patients WHERE local=1 AND COALESCE(transferred,0)=0")["n"]

    def cleanup_transferred(self, before: str):
        """Visit edits already typed into Dentist Plus are dropped once a later sync brought them back."""
        with self.tx() as c:
            c.execute("DELETE FROM local_visits WHERE transferred=1 AND transferred_at < ?", (before,))

    # ----------------------------------------------------------- reads --
    def counts(self):
        out = {}
        for t in ("visits", "patients", "doctors", "branches", "notes"):
            out[t] = self.one(f"SELECT COUNT(*) n FROM {t}")["n"]
        r = self.one("SELECT MIN(start) a, MAX(start) b FROM visits")
        out["range"] = [r["a"], r["b"]] if r else [None, None]
        return out

    # synced visits hidden by a local edit + local visits (new or edited), one combined view.
    # A local row that was sent automatically and already came back from Dentist Plus is hidden:
    # the Dentist Plus version is shown instead (no duplicates).
    LV_ACTIVE = """NOT (lv.transferred=1 AND lv.push_status IN ('sent','warn')
                        AND COALESCE(lv.remote_id, lv.origin_id) IN (SELECT id FROM visits))"""
    ALL_VISITS = f"""
        SELECT v.id, NULL AS origin_id, v.patient_id, v.doctor_id, v.branch_id, v.start, v."end",
               v.status, v.title, '' AS comment, 0 AS local, NULL AS action, v.data AS data, NULL AS chair_local,
               NULL AS series_id
        FROM visits v WHERE v.id NOT IN (SELECT lv.origin_id FROM local_visits lv WHERE lv.origin_id IS NOT NULL AND {LV_ACTIVE})
        UNION ALL
        SELECT lv.id, lv.origin_id, lv.patient_id, lv.doctor_id, lv.branch_id, lv.start, lv."end",
               lv.status, lv.title, lv.comment, 1 AS local, lv.action,
               (SELECT data FROM visits o WHERE o.id = lv.origin_id) AS data, lv.chair AS chair_local,
               lv.series_id
        FROM local_visits lv WHERE {LV_ACTIVE}"""
    CHAIR = """COALESCE(NULLIF(a.chair_local,''), json_extract(a.data,'$.chair.title'), json_extract(a.data,'$.chair.name'),
               json_extract(a.data,'$.chair_name'), json_extract(a.data,'$.chair_title'), json_extract(a.data,'$.chair'),
               json_extract(a.data,'$.cabinet'), json_extract(a.data,'$.room'))"""
    VISIT_COLS = """a.id, a.origin_id, a.patient_id, a.doctor_id, a.branch_id, a.start, a."end", a.status, a.title,
                    a.comment, a.local, a.action, a.series_id, """ + CHAIR + """ AS chair, p.name AS patient_name, p.phone AS patient_phone,
                    p.birth AS patient_birth, d.name AS doctor_name, b.name AS branch_name"""
    VISIT_JOINS = """LEFT JOIN patients p ON p.id = a.patient_id LEFT JOIN doctors d ON d.id = a.doctor_id
                     LEFT JOIN branches b ON b.id = a.branch_id"""

    def day(self, day: str, branch_id: str | None = None):
        nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
        args = [day, nxt]
        sql = f"SELECT {self.VISIT_COLS} FROM ({self.ALL_VISITS}) a {self.VISIT_JOINS} WHERE a.start >= ? AND a.start < ?"
        if branch_id:
            sql += " AND (a.branch_id = ? OR a.branch_id IS NULL)"
            args.append(branch_id)
        sql += " ORDER BY a.start"
        return self.q(sql, args)

    def day_counts(self, date_from: str, date_to: str):
        return self.q(f"""SELECT substr(start,1,10) d, COUNT(*) n FROM ({self.ALL_VISITS})
                          WHERE start >= ? AND start < ? GROUP BY d""", (date_from, date_to))

    def visit(self, vid):
        r = self.one(f"SELECT {self.VISIT_COLS}, a.data FROM ({self.ALL_VISITS}) a {self.VISIT_JOINS} WHERE a.id=?", (vid,))
        if r is None:  # synced id that is hidden by a local edit
            r = self.one(f"""SELECT {self.VISIT_COLS}, a.data FROM ({self.ALL_VISITS}) a {self.VISIT_JOINS}
                             WHERE a.origin_id=?""", (vid,))
        if r:
            r["data"] = json.loads(r["data"] or "{}")
            r["records"] = self.q("SELECT id, date FROM records WHERE visit_id IN (?,?)", (r["id"], r["origin_id"] or r["id"]))
            r["invoices"] = self.q("SELECT id, total, status FROM invoices WHERE COALESCE(kind,'invoice')='invoice' AND visit_id IN (?,?)",
                                   (r["id"], r["origin_id"] or r["id"]))
        return r

    def search_patients(self, query: str, limit=500):
        q = (query or "").strip().lower().replace("ё", "е")
        base = f"""SELECT p.id, p.name, p.phone, p.birth, p.local,
                         (SELECT MAX(start) FROM ({self.ALL_VISITS}) v WHERE v.patient_id=p.id AND v.start < datetime('now','localtime')) AS last_visit,
                         (SELECT MIN(start) FROM ({self.ALL_VISITS}) v WHERE v.patient_id=p.id AND v.start >= datetime('now','localtime')) AS next_visit
                  FROM patients p"""
        if not q:
            return self.q(base + " ORDER BY p.name LIMIT ?", (limit,))
        where, args = [], []
        for w in q.split():
            # "+7 (999) 123" -> search by digits only, words -> substring
            if any(ch.isdigit() for ch in w) and all(ch.isdigit() or ch in "+()-" for ch in w):
                w = "".join(ch for ch in w if ch.isdigit())
            where.append("p.search LIKE ?")
            args.append(f"%{w}%")
        return self.q(base + " WHERE " + " AND ".join(where) + " ORDER BY p.name LIMIT ?", (*args, limit))

    def patient(self, pid):
        p = self.one("SELECT * FROM patients WHERE id=?", (pid,))
        if not p:
            return None
        p["data"] = json.loads(p["detail"] or p["data"] or "{}")
        del p["detail"]
        p["visits"] = self.q(f"""SELECT {self.VISIT_COLS} FROM ({self.ALL_VISITS}) a {self.VISIT_JOINS}
                                 WHERE a.patient_id=? ORDER BY a.start DESC""", (pid,))
        p["extras"] = [{"kind": e["kind"], "data": json.loads(e["data"]), "synced_at": e["synced_at"]}
                       for e in self.q("SELECT * FROM patient_extras WHERE patient_id=?", (pid,))]
        p["notes"] = self.q("SELECT * FROM notes WHERE patient_id=? ORDER BY id DESC", (pid,))
        return p

    def add_note(self, pid, text, visit_id=None):
        with self.tx() as c:
            c.execute("INSERT INTO notes(patient_id,visit_id,text,created_at) VALUES(?,?,?,?)",
                      (str(pid), visit_id, text, datetime.now().strftime("%Y-%m-%d %H:%M")))

    def delete_note(self, nid):
        with self.tx() as c:
            c.execute("DELETE FROM notes WHERE id=?", (nid,))

    def branches(self):
        return self.q("SELECT id, name FROM branches ORDER BY name")

    def doctors(self):
        return self.q("SELECT id, name, branch_id FROM doctors ORDER BY name")

    def sync_history(self, limit=20):
        rows = self.q("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["counts"] = json.loads(r["counts"] or "{}")
        return rows
