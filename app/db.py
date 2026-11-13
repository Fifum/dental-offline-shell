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
CREATE TABLE IF NOT EXISTS db_flags(k TEXT PRIMARY KEY, v TEXT);
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
-- ===== mirror of Dentist Plus payments (GET /payments) for «Сверка»; replaced by date window on every sync
CREATE TABLE IF NOT EXISTS dp_payments(
    id TEXT PRIMARY KEY, date TEXT, sum REAL, patient_id TEXT, visit_id TEXT, payment_type TEXT, data TEXT, synced_at TEXT);
CREATE INDEX IF NOT EXISTS ix_dpp_date ON dp_payments(date);
-- ===== doctors' work schedule in Dentist Plus (GET /schedule): one row per doctor, day, chair and start
-- (3.7.1: a doctor may have two shifts a day, and chair_id is often empty)
CREATE TABLE IF NOT EXISTS dp_schedule(
    doctor_id TEXT, day TEXT, chair_id TEXT, branch_id TEXT, time_from TEXT, time_to TEXT, synced_at TEXT,
    PRIMARY KEY(doctor_id, day, chair_id, time_from));
CREATE INDEX IF NOT EXISTS ix_dps_day ON dp_schedule(day);
-- ===== changes of a patient card made here (name, phone, birth date…) to send to Dentist Plus (PUT /patients/{id})
CREATE TABLE IF NOT EXISTS patient_edits(
    id TEXT PRIMARY KEY, patient_id TEXT, data TEXT, created_at TEXT, updated_at TEXT,
    transferred INTEGER DEFAULT 0, transferred_at TEXT, remote_id TEXT, push_status TEXT, push_error TEXT, push_at TEXT);
CREATE INDEX IF NOT EXISTS ix_pe_patient ON patient_edits(patient_id);
"""

# chair of a synced visit, from the raw Dentist Plus record (same fields as DB.CHAIR)
_RAW_CHAIR = """COALESCE(json_extract(data,'$.chair.title'), json_extract(data,'$.chair.name'), json_extract(data,'$.chair_name'),
                json_extract(data,'$.chair_title'), json_extract(data,'$.chair'), json_extract(data,'$.cabinet'),
                json_extract(data,'$.room'))"""
_TO_ARCHIVE = f"""INSERT OR REPLACE INTO visits_archive(id, patient_id, doctor_id, branch_id, start, "end", status, title, chair, updated_at)
                  SELECT id, patient_id, doctor_id, branch_id, start, "end", status, title, {_RAW_CHAIR}, synced_at FROM visits"""

# What Dentist Plus got of a local visit: its working fields. `pushed_sig` keeps this text as sent; a row whose fields
# differ from it (changed here during the send, or merged with an edit from another computer) is to be sent again.
VISIT_SIG_COLS = ("patient_id", "doctor_id", "branch_id", "start", "end", "status", "title", "comment", "chair", "action")


def visit_sig_sql(alias="lv"):
    return "json_array(" + ", ".join(f'{alias}."{c}"' for c in VISIT_SIG_COLS) + ")"


KEEP_PUSHED_DAYS = 7   # a sent visit stays (hidden) this long, so an edit made meanwhile on another computer finds it


def tables_with(conn, col, skip=()) -> list[str]:
    """Every table of the database that has the column `col`."""
    out = []
    for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        if t not in skip and any(r[1] == col for r in conn.execute(f'PRAGMA table_info("{t}")')):
            out.append(t)
    return out


def repoint(conn, col, old, new, skip=()) -> int:
    """References `col`=old -> new in every table that has the column (inside the caller's transaction). A table whose
    key holds the column gets the row copied and the old one deleted (so the other computers see both); a row that
    already exists under the new id stays as it is."""
    import sqlite3 as _sq
    n = 0
    for t in tables_with(conn, col, skip):
        info = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
        if any(r[1] == col and r[5] for r in info):
            names = ", ".join(f'"{r[1]}"' for r in info)
            sel = ", ".join("?" if r[1] == col else f'"{r[1]}"' for r in info)
            n += conn.execute(f'INSERT OR IGNORE INTO "{t}"({names}) SELECT {sel} FROM "{t}" WHERE "{col}"=?', (new, old)).rowcount
            conn.execute(f'DELETE FROM "{t}" WHERE "{col}"=?', (old,))
            continue
        try:
            n += conn.execute(f'UPDATE "{t}" SET "{col}"=? WHERE "{col}"=?', (new, old)).rowcount
        except _sq.IntegrityError:
            n += conn.execute(f'UPDATE OR IGNORE "{t}" SET "{col}"=? WHERE "{col}"=?', (new, old)).rowcount
    return n


# tables whose visit_id is not ours to move: the Dentist Plus mirror, and the stock write-off keyed by the visit id itself
VISIT_REF_SKIP = ("visits", "visits_archive", "local_visits", "dp_payments", "stock_visit_use")
# tables whose patient_id does not keep a card in purge(): the cached card details themselves, and the Dentist Plus
# history that is never purged (it would keep every card for ever)
PATIENT_REF_SKIP = ("patient_extras", "visits_archive", "dp_payments")


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
        if "pushed_sig" not in lv:  # review 2026-11: what Dentist Plus got (replicated with the row), see VISIT_SIG_COLS
            self.conn.execute("ALTER TABLE local_visits ADD COLUMN pushed_sig TEXT")
        # 3.3: who marked a record «перенесено в Dentist Plus» and when it was last copied for Dentist Plus
        # (the columns travel to the other computers with the row, see replica.read_row)
        rcols = {r[1] for r in self.conn.execute("PRAGMA table_info(records)")}
        # 3.7: a record sent by itself into its Dentist Plus visit (PUT /visits/{id}) — the result like for visits
        for col in ("transferred_by TEXT", "dp_copied_at TEXT", "dp_copied_by TEXT",
                    "push_status TEXT", "push_error TEXT", "push_at TEXT", "remote_id TEXT"):
            if col.split()[0] not in rcols:
                self.conn.execute(f"ALTER TABLE records ADD COLUMN {col}")
        if "dp_sent" not in rcols:
            # review minor 11: what a record put into its Dentist Plus visit (JSON of fields) travels with the row, so a
            # computer that becomes the main one does not append the same text again; the old local marks move over
            self.conn.execute("ALTER TABLE records ADD COLUMN dp_sent TEXT")
            self.conn.execute("""UPDATE records SET dp_sent=(SELECT value FROM meta WHERE key='dp_record_sent:' || records.id)
                                 WHERE EXISTS(SELECT 1 FROM meta WHERE key='dp_record_sent:' || records.id)""")
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_records_date ON records(date)")
        # 3.3: the clinic's settings of the transfer to Dentist Plus (sections, reminder) — the same on every computer
        self.conn.execute("CREATE TABLE IF NOT EXISTS dp_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT)")
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
        # 3.7.1: dp_schedule of 3.7.0 had the key (doctor, day, chair) — the second shift of a day replaced the first
        pk = {r[1] for r in self.conn.execute("PRAGMA table_info(dp_schedule)") if r[5]}
        if "time_from" not in pk:
            self.conn.executescript("""
                ALTER TABLE dp_schedule RENAME TO dp_schedule_370;
                CREATE TABLE dp_schedule(
                    doctor_id TEXT, day TEXT, chair_id TEXT, branch_id TEXT, time_from TEXT, time_to TEXT, synced_at TEXT,
                    PRIMARY KEY(doctor_id, day, chair_id, time_from));
                INSERT OR REPLACE INTO dp_schedule SELECT doctor_id, day, chair_id, branch_id, time_from, time_to, synced_at
                    FROM dp_schedule_370;
                DROP TABLE dp_schedule_370;
                DROP INDEX IF EXISTS ix_dps_day;
                CREATE INDEX IF NOT EXISTS ix_dps_day ON dp_schedule(day);
                DELETE FROM meta WHERE key='dp_dicts_at';
            """)
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

    def script(self, sql):
        """Run a raw script (schema) under the lock: executescript commits first, so without the lock it would commit
        another thread's open transaction half-done."""
        with self._lock:
            self.conn.executescript(sql)
            self.conn.commit()

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
                c.execute("INSERT OR REPLACE INTO doctors(id, name, branch_id, data, synced_at) VALUES(?,?,?,?,?)",
                          (str(d["id"]), person_name(d), str(br) if br is not None and not isinstance(br, dict) else None,
                           json.dumps(d, ensure_ascii=False), now))

    def prune_doctors(self, keep_ids) -> dict:
        """Review 2026-11 (В3): doctors that GET /doctors no longer returns are deleted when nothing here names them,
        else kept for the names of old visits and records but listed in meta «doctors_inactive» (the schedule skips them)."""
        keep = {str(x) for x in keep_ids}
        out = {"deleted": 0, "inactive": 0}
        if not keep:  # an empty or failed list never wipes the doctors
            return out
        with self.tx() as c:
            gone = [str(r[0]) for r in c.execute("SELECT id FROM doctors") if str(r[0]) not in keep]
            refs = tables_with(c, "doctor_id", skip=("doctors", "dp_schedule"))
            persons = tables_with(c, "person")
            inactive = []
            for did in gone:
                used = any(c.execute(f'SELECT 1 FROM "{t}" WHERE doctor_id=? LIMIT 1', (did,)).fetchone() for t in refs) or \
                    any(c.execute(f'SELECT 1 FROM "{t}" WHERE person=? LIMIT 1', (f"d:{did}",)).fetchone() for t in persons)
                if used:
                    inactive.append(did)
                else:
                    c.execute("DELETE FROM doctors WHERE id=?", (did,))
                    out["deleted"] += 1
            out["inactive"] = len(inactive)
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('doctors_inactive', ?)", (json.dumps(sorted(inactive)),))
        return out

    def active_doctor_ids(self) -> list[str]:
        try:
            off = set(json.loads(self.meta_get("doctors_inactive") or "[]"))
        except ValueError:
            off = set()
        return [str(d["id"]) for d in self.q("SELECT id FROM doctors ORDER BY id") if str(d["id"]) not in off]

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
            # review minor 10: a card stays while any table of ours names it (payments, edits, memberships, consents,
            # CRM…), found by the column like db.repoint; the Dentist Plus mirrors that are never purged do not count
            refs = tables_with(c, "patient_id", skip=PATIENT_REF_SKIP)
            used = "".join(f'\n AND id NOT IN (SELECT patient_id FROM "{t}" WHERE patient_id IS NOT NULL)' for t in refs)
            c.execute(f"""DELETE FROM patients WHERE COALESCE(local,0)=0{used}
                          AND (detail_synced_at IS NULL OR detail_synced_at < ?)""", (border,))

    def log_sync(self, started, ok, message, counts):
        with self.tx() as c:
            c.execute("INSERT INTO sync_log(started,finished,ok,message,counts) VALUES(?,?,?,?,?)",
                      (started, utcnow(), 1 if ok else 0, message, json.dumps(counts, ensure_ascii=False)))
            c.execute("DELETE FROM sync_log WHERE id NOT IN (SELECT id FROM sync_log ORDER BY id DESC LIMIT 200)")

    LOCAL_TABLES = ("local_visits", "records", "documents", "invoices", "payments", "patient_edits")

    # К1: a database with the clinic's real data is never replaced by demo data (damaged settings say «demo»)
    def data_kind(self, kind=None):
        """'real' / 'none' (just wiped, demo allowed) / '' unknown (older database). `kind` sets it."""
        with self._lock:
            if kind is not None:
                self.conn.execute("INSERT OR REPLACE INTO db_flags(k, v) VALUES('data', ?)", (kind,))
                self.conn.commit()
                return kind
            r = self.conn.execute("SELECT v FROM db_flags WHERE k='data'").fetchone()
            return r[0] if r else ""

    def has_real_data(self) -> bool:
        kind = self.data_kind()
        if kind:
            return kind == "real"
        with self._lock:  # a database of an older version: synced from Dentist Plus, or rows from other computers
            meta = {r[0] for r in self.conn.execute("SELECT key FROM meta WHERE key IN ('last_ok', 'demo_built')")}
            if "last_ok" in meta and "demo_built" not in meta:
                return True
            try:
                return self.conn.execute("SELECT 1 FROM sync_rows WHERE ver IS NOT NULL LIMIT 1").fetchone() is not None
            except sqlite3.OperationalError:
                return False

    def wipe(self, with_local=True, quiet=False):
        """`quiet`: the deletions are not replicated (demo data never left this computer)."""
        with self.tx() as c:
            if quiet:
                try:
                    c.execute("UPDATE sync_state SET v='1' WHERE k='applying'")
                except sqlite3.OperationalError:
                    pass
            for t in ("branches", "doctors", "patients", "visits", "visits_archive", "patient_extras", "sync_log", "meta",
                      "dp_payments", "dp_schedule"):
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
            if quiet:
                try:
                    c.execute("UPDATE sync_state SET v='0' WHERE k='applying'")
                except sqlite3.OperationalError:
                    pass
        if with_local:
            self.data_kind("none")

    def pending_count(self):
        n = sum(self.one(f"SELECT COUNT(*) n FROM {t} WHERE transferred=0")["n"] for t in self.LOCAL_TABLES)
        return n + self.one("SELECT COUNT(*) n FROM patients WHERE local=1 AND COALESCE(transferred,0)=0")["n"]

    def visit_sig(self, row: dict) -> str:
        """The pushed_sig text of a local visit row (the same text SQLite makes in visit_sig_sql)."""
        return self.one("SELECT json_array(" + ", ".join("?" for _ in VISIT_SIG_COLS) + ") AS s",
                        [row.get(c) for c in VISIT_SIG_COLS])["s"]

    def reopen_changed_visits(self) -> int:
        """Review 2026-11 (К3): a sent visit whose fields are no longer what Dentist Plus got — an edit merged in from
        another computer, or one made here while it was being sent — is pending again (its remote id stays, so the
        change goes as an edit of that Dentist Plus visit)."""
        with self.tx() as c:
            return c.execute(f"""UPDATE local_visits SET transferred=0, transferred_at=NULL, push_status=NULL, push_error=NULL,
                                 push_force=0 WHERE id IN (SELECT lv.id FROM local_visits lv WHERE lv.transferred=1
                                 AND lv.pushed_sig IS NOT NULL AND lv.pushed_sig <> {visit_sig_sql()})""").rowcount

    def cleanup_transferred(self, before: str, days_back: int | None = None):
        """Visit edits already in Dentist Plus are dropped once a later sync brought them back.
        Review 2026-11 (К3, В4): a visit sent automatically (it has its Dentist Plus id) goes only when that id is in
        `visits`, and only KEEP_PUSHED_DAYS after the send (an edit made meanwhile on a computer without the network
        then merges into it instead of coming back as a new visit) or once it is older than the mirror; references
        to it (records, invoices…) move to the Dentist Plus id first. Rows changed since the send stay."""
        keep = (datetime.now() - timedelta(days=KEEP_PUSHED_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        past = (date.today() - timedelta(days=int(days_back if days_back is not None else 30))).isoformat()
        with self.tx() as c:
            rows = c.execute(f"""SELECT lv.id, lv.remote_id FROM local_visits lv WHERE lv.transferred=1 AND lv.transferred_at < ?
                                 AND (lv.pushed_sig IS NULL OR lv.pushed_sig = {visit_sig_sql()})
                                 AND (lv.remote_id IS NULL OR lv.start < ?
                                      OR (lv.remote_id IN (SELECT id FROM visits) AND lv.transferred_at < ?))""",
                             (before, past, keep)).fetchall()
            for r in rows:
                if r["remote_id"] and str(r["remote_id"]) != str(r["id"]):
                    repoint(c, "visit_id", r["id"], str(r["remote_id"]), VISIT_REF_SKIP)
                c.execute("DELETE FROM local_visits WHERE id=?", (r["id"],))
        return len(rows)

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
    # Review 2026-11: a sent row changed since (pushed_sig differs) stays shown, and hides the Dentist Plus visit it was sent as.
    LV_ACTIVE = f"""NOT (lv.transferred=1 AND lv.push_status IN ('sent','warn')
                        AND COALESCE(lv.remote_id, lv.origin_id) IN (SELECT id FROM visits)
                        AND (lv.pushed_sig IS NULL OR lv.pushed_sig = {visit_sig_sql()}))"""
    ALL_VISITS = f"""
        SELECT v.id, NULL AS origin_id, v.patient_id, v.doctor_id, v.branch_id, v.start, v."end",
               v.status, v.title, '' AS comment, 0 AS local, NULL AS action, v.data AS data, NULL AS chair_local,
               NULL AS series_id
        FROM visits v WHERE v.id NOT IN (SELECT lv.origin_id FROM local_visits lv WHERE lv.origin_id IS NOT NULL AND {LV_ACTIVE})
              AND v.id NOT IN (SELECT lv.remote_id FROM local_visits lv WHERE lv.remote_id IS NOT NULL AND {LV_ACTIVE})
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
