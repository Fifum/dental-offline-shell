"""3.7.2: one computer of the clinic talks to Dentist Plus, the others take the data from it.

Dentist Plus gives a clinic one API login, and a new token (POST /auth) makes the token of the other computer invalid:
several computers that sync on their own keep logging each other out («Авторизация не успешна»). So in the clinic
network only one computer — «the main one» — connects to Dentist Plus: it loads the data every 5 minutes and, in the
automatic mode, sends what was done on any computer of the clinic (the rows come to it over the clinic network).
The other computers take a copy of the Dentist Plus mirror from it every minute (p2p method `dp_mirror`, sealed with
the clinic key like every exchange) and never call the API themselves.

Which computer it is, is a clinic setting (`dp_settings` k='dp_main', replicated): {"node", "name", "at"}. The first
computer of the clinic network with an API login takes the role by itself; the director moves it in Settings
(«Обмен с Dentist Plus ведёт этот компьютер»). A computer outside the clinic network works on its own as before.
"""
from __future__ import annotations

import base64
import json
import socket
import time
import zlib
from datetime import date, timedelta

import config

KEY = "dp_main"
# the Dentist Plus mirror: tables a computer loads from the API and nobody edits (services and the clinic's own
# patients already travel with the clinic network, replica.py)
TABLES = ("branches", "doctors", "visits", "patient_extras", "dp_payments", "dp_schedule")
META = ("dp_chairs", "dp_record_statuses")


class DpMainError(Exception):
    pass


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def info(db) -> dict:
    try:
        r = db.one("SELECT v FROM dp_settings WHERE k=?", (KEY,))
        v = json.loads(r["v"]) if r and r["v"] else {}
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001 — no table yet or a broken value
        return {}


def _in_network() -> bool:
    try:
        import p2p
        return p2p.configured()
    except Exception:  # noqa: BLE001
        return False


def role(db) -> str:
    """"main" — this computer talks to Dentist Plus for the clinic; "follower" — another one does;
    "solo" — not in a clinic network or nobody took the role yet: talks to Dentist Plus itself."""
    if not _in_network():
        return "solo"
    node = info(db).get("node")
    if not node:
        return "solo"
    return "main" if node == config.node_id() else "follower"


def claim(db) -> dict:
    """This computer becomes the one that talks to Dentist Plus (the row goes to the others with the clinic network)."""
    v = {"node": config.node_id(), "name": socket.gethostname(), "at": _now()}
    with db.tx() as c:
        c.execute("INSERT INTO dp_settings(k, v, updated_at) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, "
                  "updated_at=excluded.updated_at", (KEY, json.dumps(v, ensure_ascii=False), _now()))
    return v


def status(db) -> dict:
    m = info(db)
    r = role(db)
    online = None
    if r == "follower":
        online = _peer(m.get("node")) is not None
    return {"role": r, "node": m.get("node") or "", "name": m.get("name") or "", "online": online,
            "in_network": _in_network(), "me": config.node_id(), "computer": socket.gethostname()}


def blocked_reason(db) -> str:
    """Why this computer must not call the Dentist Plus API now ("" when it may)."""
    if role(db) == "follower":
        name = info(db).get("name") or "другой компьютер"
        return (f"С Dentist Plus обменивается компьютер «{name}». С этого компьютера запросы к API не отправляются: "
                f"новый вход с тем же логином отключил бы тот компьютер. Проверьте подключение там или перенесите обмен "
                f"на этот компьютер в Настройках.")
    return ""


# ------------------------------------------------------------------ main side --
def _rows(db, sql, args=()):
    with db._lock:
        cur = db.conn.execute(sql, args)
        return {"cols": [d[0] for d in cur.description], "rows": [list(r) for r in cur.fetchall()]}


def snapshot(db, since="", full=False) -> dict:
    """Answer of the main computer to `dp_mirror`. Nothing but the stamp when the follower already has this copy."""
    if role(db) != "main":
        raise DpMainError("Этот компьютер не обменивается с Dentist Plus")
    stamp = db.meta_get("last_ok") or ""
    error = db.meta_get("last_error") or ""
    if not stamp:
        return {"stamp": "", "error": error, "same": True}
    if since == stamp and not full:
        return {"stamp": stamp, "error": error, "same": True}
    tables = {t: _rows(db, f"SELECT * FROM {t}") for t in TABLES}
    tables["patients"] = _rows(db, "SELECT * FROM patients WHERE COALESCE(local,0)=0")
    border = (date.today() - timedelta(days=int(config.load_settings().get("days_back") or 30))).isoformat()
    tables["visits_archive"] = (_rows(db, "SELECT * FROM visits_archive") if full
                                else _rows(db, "SELECT * FROM visits_archive WHERE start >= ?", (border,)))
    meta = {k: db.meta_get(k) for k in META}
    body = {"tables": tables, "meta": meta, "archive_from": "" if full else border}
    z = base64.b64encode(zlib.compress(json.dumps(body, ensure_ascii=False).encode("utf-8"), 6)).decode()
    return {"stamp": stamp, "error": error, "same": False, "z": z, "host": socket.gethostname()}


# -------------------------------------------------------------- follower side --
def _peer(node):
    try:
        import p2p
    except Exception:  # noqa: BLE001
        return None
    if not node or not p2p.NODE:
        return None
    for p in p2p.NODE.live_list():
        if p.get("node") == node:
            return p
    return None


def _insert(c, table, block, cols_here):
    cols = [x for x in block["cols"] if x in cols_here]
    if not cols:
        return 0
    idx = [block["cols"].index(x) for x in cols]
    names = ", ".join(f'"{x}"' for x in cols)
    marks = ", ".join("?" for _ in cols)
    rows = [[r[i] for i in idx] for r in block["rows"]]
    c.executemany(f"INSERT OR REPLACE INTO {table}({names}) VALUES({marks})", rows)
    return len(rows)


def apply(db, snap: dict) -> dict:
    """Put the main computer's copy of Dentist Plus in place of ours (one transaction)."""
    body = json.loads(zlib.decompress(base64.b64decode(snap["z"])).decode("utf-8"))
    tables = body.get("tables") or {}
    counts = {}
    with db.tx() as c:
        here = {t: [r[1] for r in c.execute(f"PRAGMA table_info({t})")] for t in (*TABLES, "patients", "visits_archive")}
        for t in TABLES:
            if t in tables:
                c.execute(f"DELETE FROM {t}")
                counts[t] = _insert(c, t, tables[t], here[t])
        if "patients" in tables:
            ids = {str(r[tables["patients"]["cols"].index("id")]) for r in tables["patients"]["rows"]}
            old = [r[0] for r in c.execute("SELECT id FROM patients WHERE COALESCE(local,0)=0")]
            gone = [(i,) for i in old if i not in ids]
            c.executemany("DELETE FROM patients WHERE id=? AND COALESCE(local,0)=0", gone)
            counts["patients"] = _insert(c, "patients", tables["patients"], here["patients"])
        if "visits_archive" in tables:
            frm = body.get("archive_from") or ""
            if frm:
                c.execute("DELETE FROM visits_archive WHERE start >= ?", (frm,))
            else:
                c.execute("DELETE FROM visits_archive")
            counts["visits_archive"] = _insert(c, "visits_archive", tables["visits_archive"], here["visits_archive"])
        for k, v in (body.get("meta") or {}).items():
            if k in META and v is not None:
                c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?,?)", (k, v))
        c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('dp_mirror_stamp', ?)", (snap.get("stamp") or "",))
        if not body.get("archive_from"):
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('dp_mirror_archive', ?)", (_now(),))
    try:
        from pusher import apply_patient_edits
        apply_patient_edits(db)
    except Exception:  # noqa: BLE001 — the copy is in place; the edits show again next time
        pass
    return counts


def pull(db) -> dict:
    """Follower: take the copy from the main computer. Returns {"changed", "stamp", "error", "name", "counts"}."""
    import p2p
    m = info(db)
    name = m.get("name") or "другой компьютер"
    p = _peer(m.get("node"))
    if not p:
        raise DpMainError(f"Компьютер «{name}», который обменивается с Dentist Plus, сейчас не в сети клиники")
    full = not db.meta_get("dp_mirror_archive")
    try:
        r = p2p.call(f"http://{p['ip']}:{p['port']}", "dp_mirror",
                     {"since": db.meta_get("dp_mirror_stamp") or "", "full": full}, timeout=90)
    except p2p.P2PError as e:
        raise DpMainError(f"Компьютер «{name}» не передал данные Dentist Plus: {e}") from None
    out = {"changed": False, "stamp": r.get("stamp") or "", "error": r.get("error") or "", "name": name, "counts": {}}
    if not r.get("same") and r.get("z"):
        out["counts"] = apply(db, r)
        out["changed"] = True
    return out
