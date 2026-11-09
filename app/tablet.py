"""Tablet for patients on the clinic network: sign a document or fill in the health questionnaire.

Pairing: Settings → «Планшет для пациентов» shows a 6-digit code for 10 minutes. On the tablet the
administrator opens http://<this computer>:8765/t and types it once; the tablet gets its own key
(kept in the tablet's browser, valid until it is removed in the settings). The key opens nothing but
the task sent to this tablet: no schedule, no other patients.

Tasks live in memory: the employee sends one, the tablet shows it, the patient submits, the employee's
screen sees «готово». A task not taken in 30 minutes expires.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS tablets(
    id TEXT PRIMARY KEY, name TEXT, key_hash TEXT, created_at TEXT, created_by TEXT, last_seen TEXT, revoked INTEGER DEFAULT 0);
"""
PAIR_SECONDS = 600
TASK_SECONDS = 1800
MAX_FAILS, FAIL_WINDOW = 8, 300


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _h(key: str) -> str:
    return hashlib.sha256(str(key or "").encode()).hexdigest()


class TabletError(Exception):
    """Unknown or revoked tablet, wrong code, too many attempts."""


class Tablets:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()
        self._lock = threading.Lock()
        self._codes = {}   # code -> (expires, name, who)
        self._tasks = {}   # tablet_id -> task
        self._fails = {}   # ip -> [times]

    # ------------------------------------------------------------ pairing --
    def new_code(self, name="Планшет ресепшена", who="") -> dict:
        name = str(name or "").strip()[:60] or "Планшет"
        with self._lock:
            now = time.time()
            self._codes = {c: v for c, v in self._codes.items() if v[0] > now}
            code = f"{secrets.randbelow(1_000_000):06d}"
            while code in self._codes:
                code = f"{secrets.randbelow(1_000_000):06d}"
            self._codes[code] = (now + PAIR_SECONDS, name, who)
        return {"code": code, "expires_in": PAIR_SECONDS, "name": name}

    def _throttle(self, ip):
        now = time.time()
        hist = [t for t in self._fails.get(ip, []) if now - t < FAIL_WINDOW]
        self._fails[ip] = hist
        if len(hist) >= MAX_FAILS:
            raise TabletError("Слишком много неверных попыток. Подождите 5 минут.")

    def pair(self, code, ip="") -> dict:
        with self._lock:
            self._throttle(ip)
            v = self._codes.pop(str(code or "").strip(), None)
            if not v or v[0] < time.time():
                self._fails.setdefault(ip, []).append(time.time())
                raise TabletError("Код неверный или устарел. Возьмите новый код в настройках программы.")
        key = secrets.token_urlsafe(32)
        tid = "TB-" + uuid.uuid4().hex[:8]
        with self.db.tx() as c:
            c.execute("INSERT INTO tablets(id, name, key_hash, created_at, created_by, last_seen) VALUES(?,?,?,?,?,?)",
                      (tid, v[1], _h(key), _now(), v[2], _now()))
        return {"key": key, "id": tid, "name": v[1]}

    def tablet_by_key(self, key, ip="") -> dict:
        with self._lock:
            self._throttle(ip)
        r = self.db.one("SELECT id, name, revoked FROM tablets WHERE key_hash=?", (_h(key),)) if key else None
        if not r or r["revoked"]:
            with self._lock:
                self._fails.setdefault(ip, []).append(time.time())
            raise TabletError("Планшет не подключён к программе. Подключите его заново кодом из настроек.")
        with self.db.tx() as c:
            c.execute("UPDATE tablets SET last_seen=? WHERE id=?", (_now(), r["id"]))
        return r

    def list(self) -> list[dict]:
        rows = self.db.q("SELECT id, name, created_at, created_by, last_seen FROM tablets WHERE revoked=0 ORDER BY created_at")
        with self._lock:
            for r in rows:
                t = self._tasks.get(r["id"])
                r["busy"] = bool(t and t["state"] in ("waiting", "opened") and t["expires"] > time.time())
        return rows

    def revoke(self, tid) -> bool:
        with self.db.tx() as c:
            if not c.execute("UPDATE tablets SET revoked=1 WHERE id=? AND revoked=0", (tid,)).rowcount:
                raise ValueError("Планшет не найден")
        with self._lock:
            self._tasks.pop(tid, None)
        return True

    # -------------------------------------------------------------- tasks --
    def send(self, tid, task: dict, who="") -> dict:
        if not self.db.one("SELECT 1 AS x FROM tablets WHERE id=? AND revoked=0", (tid,)):
            raise ValueError("Планшет не найден — подключите его в настройках")
        t = {**task, "id": "TT-" + uuid.uuid4().hex[:10], "state": "waiting", "sent_by": who or "", "sent_at": _now(),
             "expires": time.time() + TASK_SECONDS, "result": None}
        with self._lock:
            self._tasks[tid] = t
        return {"task_id": t["id"], "state": t["state"]}

    def status(self, tid, task_id) -> dict:
        with self._lock:
            t = self._tasks.get(tid)
            if not t or t["id"] != task_id:
                return {"state": "gone"}
            if t["expires"] < time.time() and t["state"] != "done":
                t["state"] = "expired"
            return {"state": t["state"], "result": t["result"]}

    def cancel(self, tid, task_id) -> bool:
        with self._lock:
            t = self._tasks.get(tid)
            if t and t["id"] == task_id and t["state"] != "done":
                t["state"] = "cancelled"
        return True

    def current(self, tid) -> dict | None:
        """What the tablet shows now (public part only)."""
        with self._lock:
            t = self._tasks.get(tid)
            if not t or t["state"] not in ("waiting", "opened") or t["expires"] < time.time():
                return None
            t["state"] = "opened"
            return {k: t[k] for k in ("id", "kind", "title", "patient", "html", "questions", "signer", "qr", "amount", "label",
                                      "variants", "chosen", "question") if k in t}

    def take(self, tid, task_id) -> dict:
        with self._lock:
            t = self._tasks.get(tid)
            if not t or t["id"] != task_id or t["state"] not in ("waiting", "opened") or t["expires"] < time.time():
                raise ValueError("Это задание уже закрыто. Попросите сотрудника отправить его ещё раз.")
            return dict(t)

    def done(self, tid, task_id, result):
        with self._lock:
            t = self._tasks.get(tid)
            if t and t["id"] == task_id:
                t["state"], t["result"] = "done", result
