"""Two-way replication of the clinic's own data between computers (through the cloud server).

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
    T("stock_docs", title="Складской документ"),
    T("stock_moves", intpk=True, title="Движение по складу"),
    T("stock_lots", intpk=True, refs={"move_id": "stock_moves"}, title="Партия"),
    T("service_materials", key=("service_id", "material_id"), title="Норма списания"),
    T("equipment", title="Оборудование"),
    T("equipment_events", intpk=True, title="Обслуживание оборудования"),
    T("work_shifts", intpk=True, title="Смена"),
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


def _cols(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _key_expr(t, alias):
    return "json_array(" + ", ".join(f"{alias}.{c}" for c in t.key) + ")"


def install(db):
    """Create the bookkeeping tables and triggers (idempotent). Tables that do not exist yet are skipped."""
    conn = db.conn
    with db._lock:
        conn.executescript(SCHEMA)
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
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
            ins = f"INSERT OR REPLACE INTO sync_dirty(tbl, k, at) VALUES('{t.name}', {{k}}, {NOW_MS})"
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


def apply_remote(db, items, device):
    """Apply rows pulled from the cloud: [{"t", "k", "row", "ver", "device"}]. Returns counts."""
    stats = {"applied": 0, "merged": 0, "conflicts": 0, "skipped": 0}
    items = sorted(items, key=lambda x: (ORDER.get(x["t"], 999), x.get("seq", 0)))
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
                k = json.dumps(it["k"], ensure_ascii=False)
                key = it["k"]
                meta = conn.execute("SELECT ver, base FROM sync_rows WHERE tbl=? AND k=?", (t.name, k)).fetchone()
                if meta and meta["ver"] == it["ver"]:
                    continue  # our own change coming back
                dirty = conn.execute("SELECT at FROM sync_dirty WHERE tbl=? AND k=?", (t.name, k)).fetchone()
                theirs = it["row"]
                conn.execute("SAVEPOINT rp")
                try:
                    if not dirty:
                        write_row(conn, t, key, theirs)
                        stats["applied"] += 1
                    else:
                        mine = read_row(conn, t, key)
                        base = json.loads(meta["base"]) if meta and meta["base"] else None
                        merged, lost = merge(base, mine, theirs, mine_newer=dirty["at"] >= ver_time(it["ver"]))
                        write_row(conn, t, key, merged)
                        if lost:
                            log_conflict(conn, t, k, merged or theirs or mine, lost, it.get("device", ""))
                            stats["conflicts"] += len(lost)
                        stats["merged"] += 1
                        if merged == theirs:
                            conn.execute("DELETE FROM sync_dirty WHERE tbl=? AND k=?", (t.name, k))
                    conn.execute("INSERT INTO sync_rows(tbl, k, ver, base, origin) VALUES(?,?,?,?,?) "
                                 "ON CONFLICT(tbl, k) DO UPDATE SET ver=excluded.ver, base=excluded.base",
                                 (t.name, k, it["ver"], json.dumps(theirs, ensure_ascii=False) if theirs is not None else None,
                                  it.get("device", "")))
                    conn.execute("RELEASE rp")
                except Exception as e:  # noqa: BLE001 — e.g. a unique number taken here: keep the row in the journal
                    conn.execute("ROLLBACK TO rp")
                    conn.execute("RELEASE rp")
                    log_conflict(conn, t, k, theirs, [("*", "", _txt(theirs))], it.get("device", ""), kind="failed")
                    conn.execute("INSERT INTO sync_rows(tbl, k, ver, base, origin) VALUES(?,?,?,?,?) "
                                 "ON CONFLICT(tbl, k) DO UPDATE SET ver=excluded.ver",
                                 (t.name, k, it["ver"], None, it.get("device", "")))
                    stats["conflicts"] += 1
                    import logging
                    logging.getLogger("replica").warning("row %s %s not applied: %s", t.name, k, e)
        finally:
            set_applying(conn, False)
    return stats


def outgoing(db, limit=400):
    """Changed rows to push: [{"t", "k", "key", "row", "base", "at"}], oldest change first."""
    out = []
    with db._lock:
        conn = db.conn
        for d in conn.execute("SELECT tbl, k, at FROM sync_dirty ORDER BY at LIMIT ?", (limit,)).fetchall():
            t = BY_NAME.get(d["tbl"])
            if not t:
                continue
            key = json.loads(d["k"])
            meta = conn.execute("SELECT ver FROM sync_rows WHERE tbl=? AND k=?", (t.name, d["k"])).fetchone()
            out.append({"t": t.name, "k": key, "ks": d["k"], "row": read_row(conn, t, key),
                        "base": meta["ver"] if meta else None, "at": d["at"]})
    out.sort(key=lambda x: (ORDER.get(x["t"], 999), x["at"]))
    return out


def pushed(db, item, ver, device):
    """The cloud took this row: remember it as the new base and forget the change unless it changed again."""
    with db.tx() as conn:
        conn.execute("INSERT INTO sync_rows(tbl, k, ver, base, origin) VALUES(?,?,?,?,?) "
                     "ON CONFLICT(tbl, k) DO UPDATE SET ver=excluded.ver, base=excluded.base",
                     (item["t"], item["ks"], ver, json.dumps(item["row"], ensure_ascii=False) if item["row"] is not None else None, device))
        conn.execute("DELETE FROM sync_dirty WHERE tbl=? AND k=? AND at=?", (item["t"], item["ks"], item["at"]))


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
