"""3.6.1: staff in the work schedules, the pay schemes and the salary payouts — by login, not by the local account id.

Accounts are synced between the clinic's computers by login; their integer ids are local and differ from computer to
computer (an account created or approved on each one separately). Up to 3.6.0 `work_shifts.person`,
`salary_schemes.person` and `expenses.person` held «u:<id>», so after a sync a schedule, a pay scheme or a salary
payout could land on another person. Now they hold «login:<login>» (as the timesheet and the motivation of 3.4 do);
a doctor stays «d:<id>» — doctors come from Dentist Plus with the same ids on every computer.

The screens keep the usual keys: «u:<id>» of this computer for an account, «d:<id>» for a doctor. A stored reference
that no account of this computer has (a leftover «u:<id>», or a login whose account has not arrived yet) is shown as
«неизвестный сотрудник» under the key «x:<stored>» — never as somebody else.

The migration on start converts only the rows this computer wrote last: their «u:<id>» was written with this
computer's ids. A row last written by another computer (an older version there) keeps «u:<id>» and shows as unknown:
the ids of that computer are not known here, and that computer converts the row itself once it is updated.
"""
from __future__ import annotations

import json
import sqlite3

UNKNOWN = "неизвестный сотрудник"
X = "x:"  # screen key of a reference nobody here has
TABLES = (("work_shifts", "uid"), ("salary_schemes", "person"), ("expenses", "id"))  # table, its sync key


class Index:
    """Accounts of this computer: id ↔ login (any status), loaded once per screen."""

    def __init__(self, db):
        self.by_id, self.by_login = {}, {}
        try:
            for r in db.q("SELECT id, login FROM users"):
                if r["login"]:
                    lg = r["login"].lower()
                    self.by_id[r["id"]], self.by_login[lg] = lg, r["id"]
        except sqlite3.OperationalError:  # no accounts table yet (tests without the server)
            pass


def to_store(db, key, idx=None) -> str:
    """A key from the screen → what is stored: «u:<id>» → «login:<login>», «x:<stored>» → <stored>, the rest as is."""
    key = str(key or "")
    if key.startswith(X):
        return key[len(X):]
    if key.startswith("login:"):
        return "login:" + key[6:].lower()
    if key.startswith("u:"):
        idx = idx or Index(db)
        try:
            lg = idx.by_id.get(int(key[2:]))
        except ValueError:
            lg = None
        if lg:
            return "login:" + lg
    return key


def to_screen(db, stored, idx=None) -> str:
    """What is stored → the key of the screens of this computer (see the module note)."""
    stored = str(stored or "")
    if stored.startswith("login:"):
        idx = idx or Index(db)
        uid = idx.by_login.get(stored[6:].lower())
        return f"u:{uid}" if uid is not None else X + stored
    if stored.startswith("u:"):  # left from before 3.6.1: whose id it is cannot be told any more
        return X + stored
    return stored


def unknown_name(key) -> str:
    """«неизвестный сотрудник», with the login when it is known."""
    s = str(key or "")
    s = s[len(X):] if s.startswith(X) else s
    return f"{UNKNOWN} ({s[6:]})" if s.startswith("login:") else UNKNOWN


def is_unknown(key) -> bool:
    return str(key or "").startswith(X)


# ------------------------------------------------------------------ migration --
def _node():
    try:
        import config  # noqa: PLC0415
        s = config.load_settings()
        return s.get("node_id") or s.get("cloud_device") or ""
    except Exception:  # noqa: BLE001
        return ""


def _have(conn, name) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def written_here(conn, table, k, node) -> bool:
    """Was the row last written on this computer? No sync data (never left it), a change not synced yet, or the
    last version made here. A version merged from two computers counts as made by the one with the later change."""
    if not _have(conn, "sync_rows"):
        return True
    if _have(conn, "sync_dirty") and conn.execute("SELECT 1 FROM sync_dirty WHERE tbl=? AND k=?", (table, k)).fetchone():
        return True
    m = conn.execute("SELECT ver, vv FROM sync_rows WHERE tbl=? AND k=?", (table, k)).fetchone()
    if m is None or not m[0]:
        return True
    p = str(m[0]).split(".")
    dev = p[1] if len(p) > 2 and p[1] != "m" else ""
    if not dev and m[1]:
        try:
            vv = json.loads(m[1])
            dev = max(vv, key=lambda n: int(vv[n])) if vv else ""
        except (ValueError, TypeError):
            dev = ""
    return bool(node) and dev == node


def _ks(v) -> str:
    return json.dumps([v], ensure_ascii=False, separators=(",", ":"))


def migrate(db, node=None) -> dict:
    """Convert «u:<id>» of the rows written here into «login:<login>» (idempotent, runs on every start).
    Returns {table: converted}; rows of accounts that are gone, and rows of other computers, stay as they are."""
    node = _node() if node is None else node
    out = {}
    if not _have(db.conn, "users"):
        return out
    idx = Index(db)
    with db.tx() as conn:
        for table, keycol in TABLES:
            if not _have(conn, table):
                continue
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if keycol not in cols:  # work_shifts before replication: no uid yet, nothing has left this computer
                keycol = "rowid"
            rows = conn.execute(f"SELECT rowid AS rid, {keycol} AS k, person, "
                                f"{'updated_at' if 'updated_at' in cols else 'created_at'} AS at "
                                f"FROM {table} WHERE person LIKE 'u:%'").fetchall()
            n = 0
            for r in rows:
                lg = None
                try:
                    lg = idx.by_id.get(int(str(r["person"])[2:]))
                except ValueError:
                    pass
                if not lg or (keycol != "rowid" and r["k"] is not None and not written_here(conn, table, _ks(r["k"]), node)):
                    continue
                new = "login:" + lg
                if table == "work_shifts":
                    ex = conn.execute('SELECT rowid AS rid, updated_at AS at FROM work_shifts WHERE person=? AND date='
                                      '(SELECT date FROM work_shifts WHERE rowid=?)', (new, r["rid"])).fetchone()
                    if ex:  # the same person and day already came under the login: the later one stays
                        if (ex["at"] or "") >= (r["at"] or ""):
                            conn.execute("DELETE FROM work_shifts WHERE rowid=?", (r["rid"],))
                            n += 1
                            continue
                        conn.execute("DELETE FROM work_shifts WHERE rowid=?", (ex["rid"],))
                    conn.execute("UPDATE work_shifts SET person=? WHERE rowid=?", (new, r["rid"]))
                elif table == "salary_schemes":
                    # the key changes: delete and insert, so that the other computers drop the old key too
                    ex = conn.execute("SELECT updated_at AS at FROM salary_schemes WHERE person=?", (new,)).fetchone()
                    if ex and (ex["at"] or "") >= (r["at"] or ""):
                        conn.execute("DELETE FROM salary_schemes WHERE rowid=?", (r["rid"],))
                        n += 1
                        continue
                    row = dict(conn.execute("SELECT * FROM salary_schemes WHERE rowid=?", (r["rid"],)).fetchone())
                    conn.execute("DELETE FROM salary_schemes WHERE rowid=?", (r["rid"],))
                    conn.execute("DELETE FROM salary_schemes WHERE person=?", (new,))
                    row["person"] = new
                    conn.execute(f"INSERT INTO salary_schemes({', '.join(row)}) VALUES({', '.join('?' * len(row))})", list(row.values()))
                else:
                    conn.execute(f"UPDATE {table} SET person=? WHERE rowid=?", (new, r["rid"]))
                n += 1
            if n:
                out[table] = n
    return out
