"""Two-way replication of the clinic's own data between computers (directly in the clinic network — p2p.py —
and through the cloud server, with the same row versions; see «versions (3.0)» below).

Every laptop works on its own and keeps its own SQLite database. Triggers write the key of every changed row
of a replicated table into `sync_dirty`. Syncing (cloud.py) pushes those rows and pulls the rows changed on
other computers. Each row has a version `<time ms>.<device>`; the cloud only accepts a row whose base version
is the one it has, so two computers never silently overwrite each other.

When a row was changed here and on another computer since the last sync, it is merged field by field against
the last synced copy (`sync_rows.base`, a three-way merge): a field changed on one side only takes that change,
a field changed on both sides takes the later change and the other value is kept in `sync_conflicts`, where the
director can bring it back. A row deleted on one side and edited on the other is kept. Two appointments at the
same time are two different rows — both stay, and the usual double-booking warning shows them.

Not replicated: the mirror of Dentist Plus (visits, patients loaded from it, doctors, branches), sessions,
tablets, the visiograph inbox, voice prints, fiscal receipts (they belong to one cash register) and settings.
"""
from __future__ import annotations

import base64
import json
import time

APPLYING = "(SELECT v FROM sync_state WHERE k='applying')='0'"

# Seed data and timestamps differ between computers without anyone editing them: never a conflict to show.
QUIET_COLS = {"updated_at", "synced_at", "created_at", "detail_synced_at", "search", "last_seen", "push_at", "at"}


class T:
    def __init__(self, name, key=("id",), intpk=False, where="", skip=(), refs=None, title=""):
        self.name, self.where, self.title = name, where, title or name
        self.intpk = intpk
        self.key = key if (not intpk or key != ("id",)) else ("uid",)
        self.skip = set(skip) | ({"id"} if intpk else set())
        self.refs = refs or {}  # column -> table whose integer id it holds


# Order matters: rows of a table go after the tables they point to.
TABLES = [
    T("users", key=("login",), intpk=True, skip=("last_login", "pin_fails"), refs={"approved_by": "users"}, title="Сотрудник"),
    T("patients", where="local=1", title="Пациент"),
    T("patient_edits", title="Изменение карточки пациента"),  # 3.7: sent to Dentist Plus by the computer it was made on
    T("local_visits", title="Запись на приём"),
    T("records", title="Лечение в медкарте"),
    T("documents", title="Документ"),
    T("templates", title="Шаблон"),
    T("services", title="Услуга"),
    T("invoices", title="Счёт или план"),
    T("payments", title="Оплата"),
    T("notes", intpk=True, title="Примечание"),
    T("patient_files", title="Файл пациента"),
    T("document_signatures", title="Подпись документа"),
    T("questionnaires", title="Анкета о здоровье"),
    T("labs", title="Лаборатория"),
    T("lab_orders", title="Заказ-наряд"),
    T("certificates", title="Сертификат"),
    T("cert_moves", intpk=True, title="Движение по сертификату"),
    T("bonus_moves", intpk=True, title="Бонусы"),
    T("families", title="Семья"),
    T("family_members", key=("patient_id",), title="Член семьи"),
    T("patient_marketing", key=("patient_id",), title="Источник пациента"),
    T("marketing_calls", intpk=True, title="Звонок"),
    T("perio_charts", title="Пародонтограмма"),
    T("steril_cycles", title="Цикл стерилизации"),
    T("tax_certs", title="Справка для вычета"),
    T("waitlist", title="Лист ожидания"),
    T("expenses", title="Расход"),
    T("salary_schemes", key=("person",), title="Схема зарплаты"),
    T("materials", title="Материал"),
    T("suppliers", title="Поставщик"),
    T("stock_locations", title="Место хранения"),  # 3.5: before the documents and moves that name it
    T("stock_docs", title="Складской документ"),
    T("stock_moves", intpk=True, title="Движение по складу"),
    T("stock_lots", intpk=True, refs={"move_id": "stock_moves"}, title="Партия"),
    T("service_materials", key=("service_id", "material_id"), title="Норма списания"),
    # 3.5: the write-off by Dentist Plus visits (one row per visit, the same id everywhere), its settings, the cost of services
    T("stock_settings", key=("k",), title="Настройка склада"),
    T("stock_visit_use", title="Списание по приёму"),
    T("service_costs", key=("service_id",), title="Себестоимость услуги"),
    T("equipment", title="Оборудование"),
    T("equipment_events", intpk=True, title="Обслуживание оборудования"),
    T("work_shifts", intpk=True, title="Смена"),
    T("kpi_targets", title="План клиники"),
    T("crm_leads", title="Заявка"),
    T("crm_tasks", title="Задача"),
    T("crm_reviews", title="Оценка визита"),
    T("crm_segments", title="Сегмент пациентов"),
    T("crm_settings", key=("k",), title="Настройка CRM"),
    T("pay_schedules", title="График платежей"),
    T("membership_types", title="Вид абонемента"),
    T("memberships", title="Абонемент"),
    T("membership_uses", title="Услуга по абонементу"),
    T("cash_shifts", title="Кассовая смена"),
    T("cash_moves", title="Внесение или изъятие из кассы"),
    T("insurers", title="Страховая компания"),
    T("insurance_docs", title="Полис или гарантийное письмо"),
    T("insurance_registries", title="Реестр для страховой"),
    T("patient_consents", title="Согласие пациента"),
    T("staff_roles", key=("key",), title="Должность"),
    T("day_reports", key=("day",), title="Отчёт за день"),
    T("dp_settings", key=("k",), title="Настройка переноса в Dentist Plus"),
    # 3.4: the timesheet, the administrators' motivation and the week / month report already sent
    T("time_marks", title="Отметка прихода и ухода"),
    T("staff_settings", key=("k",), title="Настройка табеля"),
    T("motivation_rules", key=("person",), title="Правило мотивации"),
    T("staff_bookings", title="Запись, сделанная сотрудником"),
    T("period_reports", key=("key",), title="Отчёт за неделю или месяц"),
    # 3.6: the history of plan statuses (automatic rows have the same id on every computer) and their settings
    T("plan_status_log", title="Статус плана лечения"),
    T("plan_settings", key=("k",), title="Настройка статусов планов"),
    T("audit", intpk=True, refs={"user_id": "users"}, title="Журнал действий"),
]
BY_NAME = {t.name: t for t in TABLES}
ORDER = {t.name: i for i, t in enumerate(TABLES)}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state(k TEXT PRIMARY KEY, v TEXT);
INSERT OR IGNORE INTO sync_state(k, v) VALUES('applying', '0');
CREATE TABLE IF NOT EXISTS sync_dirty(tbl TEXT, k TEXT, at INTEGER, PRIMARY KEY(tbl, k));
CREATE TABLE IF NOT EXISTS sync_rows(tbl TEXT, k TEXT, ver TEXT, base TEXT, origin TEXT, PRIMARY KEY(tbl, k));
CREATE TABLE IF NOT EXISTS sync_conflicts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, tbl TEXT, k TEXT, title TEXT, field TEXT,
    kept TEXT, other TEXT, other_device TEXT, kind TEXT, seen INTEGER DEFAULT 0);
"""

NOW_MS = "CAST((julianday('now') - 2440587.5) * 86400000 AS INTEGER)"
# Version of the change-capture triggers. 2: the key is deleted and inserted again instead of INSERT OR REPLACE —
# an UPSERT (INSERT … ON CONFLICT DO UPDATE) on a data table makes SQLite use its own ABORT policy for the
# statements of the trigger, and the second edit of a row that was not synced yet failed on sync_dirty.
TRIGGER_VER = "2"


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _key_expr(t, alias):
    return "json_array(" + ", ".join(f"{alias}.{c}" for c in t.key) + ")"


def install(db):
    """Create the bookkeeping tables and triggers (idempotent). Tables that do not exist yet are skipped."""
    conn = db.conn
    with db._lock:
        conn.executescript(SCHEMA)
        rcols = set(_cols(conn, "sync_rows"))
        for col in ("vv TEXT", "pbase TEXT", "seq INTEGER", "cver TEXT", "pvv TEXT"):  # 3.0: versions for peer-to-peer sync
            if col.split()[0] not in rcols:
                conn.execute(f"ALTER TABLE sync_rows ADD COLUMN {col}")
        if "cver" not in rcols:  # before 3.0 every known version came from (or went to) the cloud
            conn.execute("UPDATE sync_rows SET cver=ver")
        if conn.execute("SELECT 1 FROM sync_rows WHERE seq IS NULL AND ver IS NOT NULL LIMIT 1").fetchone():
            top = int((conn.execute("SELECT v FROM sync_state WHERE k='seq'").fetchone() or [0])[0])
            for i, (rid,) in enumerate(conn.execute("SELECT rowid FROM sync_rows WHERE seq IS NULL AND ver IS NOT NULL").fetchall(), 1):
                conn.execute("UPDATE sync_rows SET seq=? WHERE rowid=?", (top + i, rid))
            conn.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES('seq', ?)",
                         (str(conn.execute("SELECT COALESCE(MAX(seq), 0) FROM sync_rows").fetchone()[0]),))
        conn.execute("CREATE INDEX IF NOT EXISTS ix_sync_rows_seq ON sync_rows(seq)")
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ver = conn.execute("SELECT v FROM sync_state WHERE k='trigger_ver'").fetchone()
        if not ver or ver[0] != TRIGGER_VER:  # older triggers are replaced once
            for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'rp\\_%' ESCAPE '\\' "
                                        "AND name NOT LIKE '%\\_uid' ESCAPE '\\'").fetchall():
                conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            conn.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES('trigger_ver', ?)", (TRIGGER_VER,))
        for t in TABLES:
            if t.name not in have:
                continue
            cols = _cols(conn, t.name)
            first = conn.execute("SELECT v FROM sync_state WHERE k=?", ("installed:" + t.name,)).fetchone() is None
            if t.intpk and "uid" in t.key and "uid" not in cols:
                conn.execute(f"ALTER TABLE {t.name} ADD COLUMN uid TEXT")
                conn.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{t.name}_uid ON {t.name}(uid)")
            cond_new = f" AND NEW.{t.where}" if t.where else ""
            cond_old = f" AND OLD.{t.where}" if t.where else ""
            ins = (f"DELETE FROM sync_dirty WHERE tbl='{t.name}' AND k={{k}}; "
                   f"INSERT INTO sync_dirty(tbl, k, at) VALUES('{t.name}', {{k}}, {NOW_MS})")
            if t.intpk and "uid" in t.key:
                conn.execute(f"""CREATE TRIGGER IF NOT EXISTS rp_{t.name}_uid AFTER INSERT ON {t.name} WHEN NEW.uid IS NULL
                    BEGIN UPDATE {t.name} SET uid=lower(hex(randomblob(12))) WHERE rowid=NEW.rowid; END""")
                conn.execute(f"UPDATE {t.name} SET uid=lower(hex(randomblob(12))) WHERE uid IS NULL")
            not_null_new = " AND ".join(f"NEW.{c} IS NOT NULL" for c in t.key)
            not_null_old = " AND ".join(f"OLD.{c} IS NOT NULL" for c in t.key)
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS rp_{t.name}_i AFTER INSERT ON {t.name}
                WHEN {APPLYING} AND {not_null_new}{cond_new} BEGIN {ins.format(k=_key_expr(t, 'NEW'))}; END""")
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS rp_{t.name}_u AFTER UPDATE ON {t.name}
                WHEN {APPLYING} AND {not_null_new}{cond_new} BEGIN {ins.format(k=_key_expr(t, 'NEW'))}; END""")
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS rp_{t.name}_d AFTER DELETE ON {t.name}
                WHEN {APPLYING} AND {not_null_old}{cond_old} BEGIN {ins.format(k=_key_expr(t, 'OLD'))}; END""")
            if first:  # everything that existed before replication was switched on goes up once
                where = f" WHERE {t.where}" if t.where else ""
                conn.execute(f"INSERT OR IGNORE INTO sync_dirty(tbl, k, at) SELECT '{t.name}', {_key_expr(t, t.name)}, {NOW_MS} "
                             f"FROM {t.name}{where}")
                conn.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES(?, '1')", ("installed:" + t.name,))
        conn.commit()


def pending(db) -> int:
    try:
        return db.one("SELECT COUNT(*) AS n FROM sync_dirty")["n"]
    except Exception:  # noqa: BLE001 — not installed yet
        return 0


# ------------------------------------------------------------------ values --
def _enc(v):
    if isinstance(v, bytes):
        return {"$b": base64.b64encode(v).decode()}
    return v


def _dec(v):
    if isinstance(v, dict) and "$b" in v:
        return base64.b64decode(v["$b"])
    return v


def _where(t):
    return " AND ".join(f"{c}=?" for c in t.key)


def read_row(conn, t: T, key: list):
    """The row as it travels: without local-only columns, integer references replaced by stable keys."""
    r = conn.execute(f"SELECT * FROM {t.name} WHERE {_where(t)}", key).fetchone()
    if r is None:
        return None
    row = {k: _enc(r[k]) for k in r.keys() if k not in t.skip}
    for col, ref in t.refs.items():
        if col in row and row[col] is not None:
            rt = BY_NAME[ref]
            x = conn.execute(f"SELECT {', '.join(rt.key)} FROM {ref} WHERE id=?", (row[col],)).fetchone()
            row[col] = {"$ref": list(x)} if x else None
    return row


def _local_ref(conn, ref, value):
    if not isinstance(value, dict) or "$ref" not in value:
        return value
    rt = BY_NAME[ref]
    x = conn.execute(f"SELECT id FROM {ref} WHERE {_where(rt)}", value["$ref"]).fetchone()
    return x[0] if x else None


def write_row(conn, t: T, key: list, row):
    """Put a row coming from another computer into the local table (or delete it when row is None)."""
    if row is None:
        conn.execute(f"DELETE FROM {t.name} WHERE {_where(t)}", key)
        return
    local = set(_cols(conn, t.name))
    vals = {}
    for c, v in row.items():
        if c not in local or c in t.skip:
            continue
        v = _dec(v)
        if c in t.refs:
            v = _local_ref(conn, t.refs[c], v)
        vals[c] = v
    for c, v in zip(t.key, key):
        vals[c] = v
    if t.intpk:
        ex = conn.execute(f"SELECT rowid FROM {t.name} WHERE {_where(t)}", key).fetchone()
        if ex:
            sets = [c for c in vals if c not in t.key]
            if sets:
                conn.execute(f"UPDATE {t.name} SET {', '.join(c + '=?' for c in sets)} WHERE rowid=?",
                             [vals[c] for c in sets] + [ex[0]])
            return
        cols = list(vals)
        conn.execute(f"INSERT INTO {t.name}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", [vals[c] for c in cols])
        return
    cols = list(vals)
    upd = [c for c in cols if c not in t.key]
    tail = f"DO UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in upd)}" if upd else "DO NOTHING"
    conn.execute(f'INSERT INTO {t.name}({", ".join(cols)}) VALUES({", ".join("?" * len(cols))}) '
                 f'ON CONFLICT({", ".join(t.key)}) {tail}', [vals[c] for c in cols])


# ------------------------------------------------------------------ merge --
def ver_time(ver) -> int:
    try:
        return int(str(ver).split(".")[0])
    except (TypeError, ValueError):
        return 0


def describe(t: T, row) -> str:
    if not row:
        return t.title
    for c in ("name", "title", "work", "code", "number", "login", "start", "date", "text", "comment"):
        v = row.get(c)
        if v not in (None, "") and not isinstance(v, dict):
            return f"{t.title}: {str(v)[:60]}"
    return t.title


def merge(base, mine, theirs, mine_newer: bool):
    """Three-way merge of two versions of a row. Returns (merged row or None, [(field, kept, other)])."""
    base = base or {}
    if mine is None and theirs is None:
        return None, []
    if mine is None or theirs is None:  # deleted on one side, edited (or kept) on the other: keep the data
        alive = mine if theirs is None else theirs
        return alive, [("*", "оставлена", "удалена")]
    out, lost = {}, []
    for c in sorted(set(mine) | set(theirs)):
        a, b, o = mine.get(c), theirs.get(c), base.get(c)
        if a == b:
            out[c] = a
        elif a == o:
            out[c] = b
        elif b == o:
            out[c] = a
        else:
            keep, other = (a, b) if mine_newer else (b, a)
            out[c] = keep
            if c not in QUIET_COLS:
                lost.append((c, keep, other))
    return out, lost


def _txt(v):
    if v is None:
        return ""
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


SECRET_COLS = {"pass_hash", "pin_hash", "key_hash", "token_hash"}


def log_conflict(conn, t, k, row, items, other_device, kind="field"):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for field, kept, other in items:
        if field in SECRET_COLS:  # a password changed on two computers: say so, never keep the hashes around
            conn.execute("INSERT INTO sync_conflicts(at, tbl, k, title, field, kept, other, other_device, kind) VALUES(?,?,?,?,?,?,?,?,?)",
                         (now, t.name, k, describe(t, row), field, "новое значение", "другое значение (скрыто)", other_device, "secret"))
            continue
        conn.execute("INSERT INTO sync_conflicts(at, tbl, k, title, field, kept, other, other_device, kind) VALUES(?,?,?,?,?,?,?,?,?)",
                     (now, t.name, k, describe(t, row), field, _txt(kept)[:4000], _txt(other)[:4000], other_device,
                      "deleted" if field == "*" else kind))


def set_applying(conn, on: bool):
    conn.execute("UPDATE sync_state SET v=? WHERE k='applying'", ("1" if on else "0",))


# ------------------------------------------------------- versions (3.0) --
# Every computer is a peer: it takes rows from any other computer of the clinic (LAN) and from the cloud.
# A local change becomes a version when it is «stamped»: `ver` = «<time ms>.<node>.<random>», `vv` = version
# vector {node: counter} (the counter is a time in ms, so it keeps growing after a restore from a backup),
# `base` = the row as of this version, `pbase` = the last version of the row this computer took from another one
# (or merged) before its own changes, with its vector `pvv` — the ancestor for a three-way merge; consecutive local
# changes keep it, so two edits here against one edit there still merge against what both sides had.
# `seq` = local change number. A computer gives its peers «rows with seq > what you already have from me»;
# what came from a third computer goes on with a new local seq, so every change reaches everyone.
# Two versions: one vector covers the other → the newer one is kept, the older one is ignored; neither covers
# the other (changed on two computers) → merged field by field, the result gets the union of the vectors and a
# version made from its content, so two computers merging the same pair end up with the same row.
# `cver` = the version the cloud has, so the cloud gets only what it does not have yet.

def ks(key) -> str:
    """Row key as stored in sync_dirty / sync_rows — the same text SQLite json_array() makes."""
    return json.dumps(list(key), ensure_ascii=False, separators=(",", ":"))


def make_ver(node, at) -> str:
    import secrets
    return f"{int(at):015d}.{node}.{secrets.token_hex(3)}"


def ver_device(ver) -> str:
    p = str(ver or "").split(".")
    return p[1] if len(p) > 2 and p[1] != "m" else ""


def _vv(meta) -> dict:
    if meta is None:
        return {}
    if meta["vv"]:
        try:
            return {k: int(v) for k, v in json.loads(meta["vv"]).items()}
        except (ValueError, TypeError, AttributeError):
            pass
    return vv_of_ver(meta["ver"])


def vv_of_ver(ver) -> dict:
    """A version written before 3.0 (cloud only): what its own text tells."""
    p = str(ver or "").split(".")
    return {p[1]: ver_time(ver)} if len(p) > 2 and p[1] != "m" else ({"?": ver_time(ver)} if ver else {})


def vv_cmp(a: dict, b: dict) -> str:
    """'eq', 'gt' (a covers b), 'lt' (b covers a) or 'cc' (concurrent)."""
    ge = all(a.get(k, 0) >= v for k, v in b.items())
    le = all(b.get(k, 0) >= v for k, v in a.items())
    return "eq" if ge and le else "gt" if ge else "lt" if le else "cc"


def _canon(row) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _next_seq(conn) -> int:
    r = conn.execute("SELECT v FROM sync_state WHERE k='seq'").fetchone()
    n = (int(r[0]) if r else 0) + 1
    conn.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES('seq', ?)", (str(n),))
    return n


def top_seq(db) -> int:
    r = db.one("SELECT v FROM sync_state WHERE k='seq'")
    return int(r["v"]) if r else 0


def epoch(db) -> str:
    """Changes with every restore from a backup: peers then take everything again instead of trusting old numbers."""
    r = db.one("SELECT v FROM sync_state WHERE k='epoch'")
    if r:
        return r["v"]
    return new_epoch(db)


def new_epoch(db) -> str:
    import secrets
    e = secrets.token_hex(6)
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES('epoch', ?)", (e,))
    return e


def _js(v):
    return None if v is None else (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, separators=(",", ":")))


def _save_meta(conn, tbl, k, ver, vv, base, pbase, origin, pvv=None):
    conn.execute("INSERT INTO sync_rows(tbl, k, ver, base, pbase, pvv, vv, seq, origin) VALUES(?,?,?,?,?,?,?,?,?) "
                 "ON CONFLICT(tbl, k) DO UPDATE SET ver=excluded.ver, base=excluded.base, vv=excluded.vv, "
                 "pbase=excluded.pbase, pvv=excluded.pvv, seq=excluded.seq, "
                 "origin=COALESCE(NULLIF(sync_rows.origin, ''), excluded.origin)",
                 (tbl, k, ver, None if base is None else json.dumps(base, ensure_ascii=False), _js(pbase), _js(pvv),
                  json.dumps(vv, separators=(",", ":")), _next_seq(conn), origin or ""))


def stamp_conn(conn, node, only=None) -> int:
    """Turn local changes (sync_dirty) into versions. `only` = (table, key text) for one row. Inside a transaction."""
    sql, args = "SELECT tbl, k, at FROM sync_dirty", ()
    if only:
        sql, args = sql + " WHERE tbl=? AND k=?", only
    n = 0
    for d in conn.execute(sql, args).fetchall():
        t = BY_NAME.get(d["tbl"])
        conn_del = ("DELETE FROM sync_dirty WHERE tbl=? AND k=? AND at=?", (d["tbl"], d["k"], d["at"]))
        if not t:
            conn.execute(*conn_del)
            continue
        key = json.loads(d["k"])
        row = read_row(conn, t, key)
        meta = conn.execute("SELECT * FROM sync_rows WHERE tbl=? AND k=?", (t.name, d["k"])).fetchone()
        base = json.loads(meta["base"]) if meta and meta["base"] else None
        if (meta and meta["ver"] and row is not None and base is not None and _canon(row) == _canon(base)) or \
                (row is None and (not meta or meta["base"] is None)):
            conn.execute(*conn_del)  # nothing really changed (saved again as it was) or a row that never left
            continue
        vv = _vv(meta)
        vv[node] = max(vv.get(node, 0) + 1, int(d["at"]))
        if meta and meta["ver"] and ver_device(meta["ver"]) == node:  # an earlier change made here: keep its ancestor
            pbase, pvv = meta["pbase"], meta["pvv"]
        else:  # the version taken from another computer (or merged) is what both sides have
            pbase, pvv = (meta["base"], meta["vv"] or _js(_vv(meta))) if meta else (None, None)
        _save_meta(conn, t.name, d["k"], make_ver(node, d["at"]), vv, row, pbase, node, pvv)
        conn.execute(*conn_del)
        n += 1
    return n


def stamp(db, node) -> int:
    with db.tx() as conn:
        return stamp_conn(conn, node)


# В2: set after a restore from a backup — no exchange with the other computers and the cloud until the restart
HOLD = ""


def known_nodes(db) -> set:
    """Computers whose versions this database has seen or that are known in the clinic network."""
    out = set()
    with db._lock:
        try:
            for (v,) in db.conn.execute("SELECT vv FROM sync_rows WHERE vv IS NOT NULL").fetchall():
                out |= set(_pvv(v) or {})
        except Exception:  # noqa: BLE001 — not installed yet
            pass
        try:
            out |= {r[0] for r in db.conn.execute("SELECT node FROM p2p_peers WHERE COALESCE(node, '')<>''")}
        except Exception:  # noqa: BLE001 — never joined a clinic network
            pass
    return out


def restamp_all(db, node, nodes=()) -> int:
    """В2: after a restore from a backup every row of the restored database becomes a new version of this computer
    that covers everything the other computers had made by now, so they take the restored rows instead of bringing
    their newer ones back. Their changes made after this moment still merge as usual; rows that are not in the copy
    at all (made later elsewhere) come back from them. `nodes`: computers known before the restore (the copy may
    not know the ones that joined later)."""
    now = int(time.time() * 1000)
    n = 0
    with db.tx() as conn:
        stamp_conn(conn, node)  # changes not stamped when the copy was made (deletions among them) go first
        nodes = {node} | set(nodes) | known_nodes(db)
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in TABLES:
            if t.name not in have:
                continue
            where = f" WHERE {t.where}" if t.where else ""
            for r in conn.execute(f"SELECT {', '.join(t.key)} FROM {t.name}{where}").fetchall():
                key = list(r)
                if any(x is None for x in key):
                    continue
                k = ks(key)
                row = read_row(conn, t, key)
                meta = conn.execute("SELECT * FROM sync_rows WHERE tbl=? AND k=?", (t.name, k)).fetchone()
                vv = _vv(meta)
                for x in nodes:
                    vv[x] = max(vv.get(x, 0), now)
                vv[node] = max(vv[node], now) + 1
                _save_meta(conn, t.name, k, make_ver(node, now), vv, row, meta["base"] if meta else None,
                           (meta["origin"] if meta else "") or node, (meta["vv"] if meta else None))
                n += 1
    return n


def changes_since(db, since=0, limit=500):
    """Versions this computer has with seq > since, oldest first: what a peer is missing."""
    rows = db.q("SELECT * FROM sync_rows WHERE seq>? AND ver IS NOT NULL ORDER BY seq LIMIT ?", (int(since or 0), int(limit)))
    return [{"t": r["tbl"], "k": json.loads(r["k"]), "row": json.loads(r["base"]) if r["base"] else None, "ver": r["ver"],
             "vv": json.loads(r["vv"]) if r["vv"] else vv_of_ver(r["ver"]), "pbase": json.loads(r["pbase"]) if r["pbase"] else None,
             "pvv": json.loads(r["pvv"]) if r["pvv"] else None, "origin": r["origin"] or "", "seq": r["seq"]} for r in rows]


def _merged_ver(vv, row) -> str:
    import hashlib
    h = hashlib.sha256((_canon(row) + json.dumps(vv, sort_keys=True)).encode("utf-8")).hexdigest()[:12]
    return f"{max(vv.values() or [0]):015d}.m.{h}"


def apply_versions(db, items, node, cloud=False):
    """Apply versions from a peer or the cloud: [{"t", "k", "row", "ver", "vv", "pbase", "origin"}]. Returns counts.
    `cloud`: they came from the cloud, which therefore has them (cver)."""
    stats = {"applied": 0, "merged": 0, "conflicts": 0, "skipped": 0, "same": 0}
    items = sorted(items, key=lambda x: (ORDER.get(x["t"], 999), x.get("seq", 0)))
    import logging
    with db.tx() as conn:
        set_applying(conn, True)
        try:
            for it in items:
                t = BY_NAME.get(it["t"])
                if not t:
                    stats["skipped"] += 1
                    continue
                try:
                    conn.execute(f"SELECT 1 FROM {t.name} LIMIT 0")
                except Exception:  # noqa: BLE001 — table of a newer version
                    stats["skipped"] += 1
                    continue
                key, k = it["k"], ks(it["k"])
                if conn.execute("SELECT 1 FROM sync_dirty WHERE tbl=? AND k=?", (t.name, k)).fetchone():
                    stamp_conn(conn, node, (t.name, k))  # our unsaved change becomes a version first
                meta = conn.execute("SELECT * FROM sync_rows WHERE tbl=? AND k=?", (t.name, k)).fetchone()
                _apply_one(conn, t, key, k, it, meta, stats, logging)
                if cloud:
                    conn.execute("UPDATE sync_rows SET cver=? WHERE tbl=? AND k=?", (it["ver"], t.name, k))
        finally:
            set_applying(conn, False)
    return stats


def _pvv(v):
    if not v:
        return None
    try:
        return {kk: int(x) for kk, x in (json.loads(v) if isinstance(v, str) else v).items()}
    except (ValueError, TypeError, AttributeError):
        return None


def _ancestor(it, meta, tv):
    """The ancestor for merging two concurrent versions: of the two candidates (the one the incoming version was made
    from, the one ours was made from) one that both versions cover, the later one. Unknown → the incoming one (old peers)."""
    mv = _vv(meta)
    cands = [(it.get("pbase"), _pvv(it.get("pvv"))),
             (json.loads(meta["pbase"]) if meta["pbase"] else None, _pvv(meta["pvv"]))]
    ok = [(row, vv) for row, vv in cands if vv is not None and vv_cmp(vv, tv) in ("lt", "eq") and vv_cmp(vv, mv) in ("lt", "eq")]
    if not ok:
        return it.get("pbase"), None
    best = ok[0]
    for row, vv in ok[1:]:
        if vv_cmp(vv, best[1]) == "gt" or (vv_cmp(vv, best[1]) == "cc" and sum(vv.values()) > sum(best[1].values())):
            best = (row, vv)
    return best


def _apply_one(conn, t, key, k, it, meta, stats, logging):
    tv = {kk: int(v) for kk, v in (it.get("vv") or vv_of_ver(it["ver"])).items()}
    theirs = it["row"]
    dev = ver_device(it["ver"]) or it.get("origin", "")
    if meta is not None and meta["ver"] == it["ver"]:
        stats["same"] += 1
        return
    c = "lt" if meta is None or meta["ver"] is None else vv_cmp(_vv(meta), tv)
    if c == "eq":  # same history, made into different rows on two computers: the same rule everywhere
        c = "lt" if it["ver"] > meta["ver"] else "gt"
    if c == "gt":
        stats["skipped"] += 1  # we already have something newer
        return
    conn.execute("SAVEPOINT rp")
    try:
        if c == "lt":
            write_row(conn, t, key, theirs)
            _save_meta(conn, t.name, k, it["ver"], tv, theirs, it.get("pbase"), it.get("origin") or dev, it.get("pvv"))
            stats["applied"] += 1
        else:  # changed here and there
            mine = json.loads(meta["base"]) if meta["base"] else None
            anc, avv = _ancestor(it, meta, tv)
            mine_newer = (ver_time(meta["ver"]), meta["ver"]) > (ver_time(it["ver"]), it["ver"])
            merged, lost = merge(anc, mine, theirs, mine_newer)
            vv = _vv(meta)
            for kk, v in tv.items():
                vv[kk] = max(vv.get(kk, 0), v)
            write_row(conn, t, key, merged)
            _save_meta(conn, t.name, k, _merged_ver(vv, merged), vv, merged, anc, it.get("origin") or dev, avv)
            if lost:
                log_conflict(conn, t, k, merged or theirs or mine, lost, dev)
                stats["conflicts"] += len(lost)
            stats["merged"] += 1
        conn.execute("RELEASE rp")
    except Exception as e:  # noqa: BLE001 — e.g. a unique number taken here: keep the row in the journal
        conn.execute("ROLLBACK TO rp")
        conn.execute("RELEASE rp")
        log_conflict(conn, t, k, theirs, [("*", "", _txt(theirs))], dev, kind="failed")
        conn.execute("INSERT INTO sync_rows(tbl, k, ver, vv, origin) VALUES(?,?,?,?,?) ON CONFLICT(tbl, k) DO UPDATE "
                     "SET ver=excluded.ver, vv=excluded.vv", (t.name, k, it["ver"], json.dumps(tv), it.get("origin") or dev))
        stats["conflicts"] += 1
        logging.getLogger("replica").warning("row %s %s not applied: %s", t.name, k, e, exc_info=True)


def cloud_outgoing(db, limit=400):
    """Versions the cloud does not have yet: [{"t", "k", "ks", "row", "ver", "vv", "pbase", "origin", "base"}]."""
    rows = db.q("SELECT * FROM sync_rows WHERE ver IS NOT NULL AND (cver IS NULL OR cver<>ver) ORDER BY seq LIMIT ?", (int(limit),))
    out = [{"t": r["tbl"], "k": json.loads(r["k"]), "ks": r["k"], "row": json.loads(r["base"]) if r["base"] else None,
            "ver": r["ver"], "vv": json.loads(r["vv"]) if r["vv"] else vv_of_ver(r["ver"]),
            "pbase": json.loads(r["pbase"]) if r["pbase"] else None, "pvv": json.loads(r["pvv"]) if r["pvv"] else None,
            "origin": r["origin"] or "", "base": r["cver"]}
           for r in rows]
    out.sort(key=lambda x: ORDER.get(x["t"], 999))
    return out


def cloud_pushed(db, item):
    with db.tx() as conn:
        conn.execute("UPDATE sync_rows SET cver=? WHERE tbl=? AND k=? AND ver=?", (item["ver"], item["t"], item["ks"], item["ver"]))


def foreign_ids(db, table, device) -> set:
    """Ids of rows that were created on another computer (that computer sends them to Dentist Plus)."""
    try:
        return {json.loads(r["k"])[0] for r in db.q("SELECT k FROM sync_rows WHERE tbl=? AND origin<>'' AND origin<>?",
                                                     (table, device))}
    except Exception:  # noqa: BLE001
        return set()


def conflicts(db, show_seen=False, limit=300):
    sql = "SELECT * FROM sync_conflicts" + ("" if show_seen else " WHERE seen=0") + " ORDER BY id DESC LIMIT ?"
    try:
        rows = db.q(sql, (limit,))
    except Exception:  # noqa: BLE001
        return []
    for r in rows:
        t = BY_NAME.get(r["tbl"])
        r["table_title"] = t.title if t else r["tbl"]
    return rows


def conflict_seen(db, cid=None):
    with db.tx() as c:
        if cid:
            c.execute("UPDATE sync_conflicts SET seen=1 WHERE id=?", (int(cid),))
        else:
            c.execute("UPDATE sync_conflicts SET seen=1")
    return True


def conflict_restore(db, cid):
    """Bring the other value of a field back (it becomes a normal local change and goes to the other computers)."""
    r = db.one("SELECT * FROM sync_conflicts WHERE id=?", (int(cid),))
    if not r:
        raise ValueError("Запись не найдена")
    t = BY_NAME.get(r["tbl"])
    if not t:
        raise ValueError("Неизвестная таблица")
    key = json.loads(r["k"])
    with db.tx() as conn:
        if r["kind"] == "failed":
            row = json.loads(r["other"]) if r["other"] else None
            if row is None:
                raise ValueError("Нечего восстанавливать")
            # a clashing unique value (number, code): free the row's own key and insert it as is
            write_row(conn, t, key, row)
        elif r["field"] == "*":
            raise ValueError("Строка сохранена — восстанавливать нечего")
        else:
            cur = read_row(conn, t, key)
            if cur is None:
                raise ValueError("Строка удалена")
            try:
                val = json.loads(r["other"])
            except ValueError:
                val = r["other"]
            if r["field"] in cur and isinstance(cur[r["field"]], str):
                val = r["other"]
            cur[r["field"]] = val
            write_row(conn, t, key, cur)
        conn.execute("UPDATE sync_conflicts SET seen=1 WHERE id=?", (r["id"],))
    return True
