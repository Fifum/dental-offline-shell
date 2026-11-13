"""Dental Desk cloud: sync server for many clinics. Standard library only (Python 3.10+).

Each clinic (tenant) has its own SQLite file; a device token belongs to exactly one tenant and every query
uses the tenant taken from the token, never from the request. Rows arrive already encrypted on the clinic's
computers (AES-256-GCM with the clinic key, which the server never sees); the server keeps opaque blobs,
their versions and a growing sequence number, and refuses a row whose base version is not the current one.

    python cloud_server.py serve --port 8780 --data ./data            # behind nginx with TLS in production
    python cloud_server.py create-tenant "Клиника на Ленина"          # prints the connection code (30-day trial)
    python cloud_server.py pay <tenant> --plan clinic --months 1 --amount 5900
    python cloud_server.py list | devices <tenant> | revoke <device> | new-invite <tenant> | plans
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_VERSION = 1
MAX_BODY = 40 * 1024 * 1024
MAX_PUSH = 1000
PULL_LIMIT = 500
GRACE_DAYS = 7
TRIAL_DAYS = 30

PLANS = {
    "trial": {"title": "Пробный период", "price": 0, "devices": 5},
    "start": {"title": "Старт", "price": 2900, "devices": 3},
    "clinic": {"title": "Клиника", "price": 5900, "devices": 10},
    "network": {"title": "Сеть клиник", "price": 11900, "devices": 50},
}

CONTROL = """
CREATE TABLE IF NOT EXISTS tenants(
    id TEXT PRIMARY KEY, name TEXT, plan TEXT, trial_until TEXT, paid_until TEXT, created_at TEXT,
    status TEXT DEFAULT 'active', invite_hash TEXT UNIQUE, key_check TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS devices(
    id TEXT PRIMARY KEY, tenant_id TEXT, name TEXT, token_hash TEXT UNIQUE, created_at TEXT, last_seen TEXT,
    version TEXT, revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS payments(
    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT, plan TEXT, amount REAL, months INTEGER, at TEXT, note TEXT);
"""
TENANT = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS rows(key TEXT PRIMARY KEY, ver TEXT, data TEXT, device TEXT, seq INTEGER);
CREATE INDEX IF NOT EXISTS ix_rows_seq ON rows(seq);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""
HEX = re.compile(r"^[0-9a-f]{16,128}$")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _invite() -> str:
    raw = base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=")
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


def norm_invite(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())


class CloudError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


class Cloud:
    def __init__(self, data_dir):
        self.dir = os.path.abspath(data_dir)
        os.makedirs(os.path.join(self.dir, "tenants"), exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._glock = threading.Lock()
        with self._control() as c:
            c.executescript(CONTROL)

    # ------------------------------------------------------------- storage --
    def _control(self):
        c = sqlite3.connect(os.path.join(self.dir, "control.db"), timeout=30)
        c.row_factory = sqlite3.Row
        return _Conn(c)

    def _tenant_db(self, tid):
        if not HEX.match(tid):
            raise CloudError("Неверная клиника", 400)
        c = sqlite3.connect(os.path.join(self.dir, "tenants", f"{tid}.db"), timeout=30)
        c.row_factory = sqlite3.Row
        c.executescript(TENANT)
        return _Conn(c)

    def _blob_dir(self, tid):
        p = os.path.join(self.dir, "tenants", tid + ".blobs")
        os.makedirs(p, exist_ok=True)
        return p

    def _lock(self, tid):
        with self._glock:
            return self._locks.setdefault(tid, threading.Lock())

    # -------------------------------------------------------------- admin --
    def create_tenant(self, name, plan="trial", days=TRIAL_DAYS):
        tid, code = secrets.token_hex(12), _invite()
        with self._control() as c:
            c.execute("INSERT INTO tenants(id, name, plan, trial_until, created_at, invite_hash) VALUES(?,?,?,?,?,?)",
                      (tid, name, plan, (date.today() + timedelta(days=days)).isoformat(), _now(), _h(norm_invite(code))))
        return {"tenant": tid, "invite": code}

    def new_invite(self, tid):
        code = _invite()
        with self._control() as c:
            if not c.execute("UPDATE tenants SET invite_hash=? WHERE id=?", (_h(norm_invite(code)), tid)).rowcount:
                raise CloudError("Клиника не найдена", 404)
        return code

    def pay(self, tid, plan, months=1, amount=0.0, note=""):
        if plan not in PLANS or plan == "trial":
            raise CloudError("Неизвестный тариф")
        with self._control() as c:
            t = c.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
            if not t:
                raise CloudError("Клиника не найдена", 404)
            prev = t["paid_until"] or t["trial_until"]  # paying during the trial keeps its remaining days
            start = max(date.today(), date.fromisoformat(prev) if prev else date.today())
            until = start + timedelta(days=30 * int(months))
            c.execute("UPDATE tenants SET plan=?, paid_until=?, status='active' WHERE id=?", (plan, until.isoformat(), tid))
            c.execute("INSERT INTO payments(tenant_id, plan, amount, months, at, note) VALUES(?,?,?,?,?,?)",
                      (tid, plan, float(amount or 0), int(months), _now(), note))
        return self.subscription(tid)

    def tenants(self):
        with self._control() as c:
            rows = [dict(r) for r in c.execute("SELECT * FROM tenants ORDER BY created_at")]
            for r in rows:
                r["devices"] = c.execute("SELECT COUNT(*) FROM devices WHERE tenant_id=? AND revoked=0", (r["id"],)).fetchone()[0]
        for r in rows:
            r.pop("invite_hash", None)
            r.pop("key_check", None)
            r["subscription"] = self.subscription(r["id"])
        return rows

    def subscription(self, tid):
        with self._control() as c:
            t = c.execute("SELECT * FROM tenants WHERE id=?", (tid,)).fetchone()
            if not t:
                raise CloudError("Клиника не найдена", 404)
            used = c.execute("SELECT COUNT(*) FROM devices WHERE tenant_id=? AND revoked=0", (tid,)).fetchone()[0]
        today = date.today()
        paid = date.fromisoformat(t["paid_until"]) if t["paid_until"] else None
        trial = date.fromisoformat(t["trial_until"]) if t["trial_until"] else None
        plan = t["plan"] if t["plan"] in PLANS else "trial"
        if paid and paid >= today:
            state, until = "active", paid
        elif not paid and trial and trial >= today:
            state, until, plan = "trial", trial, "trial"
        else:
            until = paid or trial or today
            state = "grace" if (today - until).days <= GRACE_DAYS else "expired"
        if t["status"] == "blocked":
            state = "blocked"
        return {"tenant": t["id"], "name": t["name"], "plan": plan, "plan_title": PLANS[plan]["title"],
                "price": PLANS[plan]["price"], "state": state, "until": until.isoformat(), "days_left": (until - today).days,
                "devices": used, "max_devices": PLANS[plan]["devices"], "grace_days": GRACE_DAYS,
                "plans": [{"key": k, **v} for k, v in PLANS.items() if k != "trial"]}

    def devices(self, tid):
        with self._control() as c:
            return [{k: r[k] for k in ("id", "name", "created_at", "last_seen", "version", "revoked")}
                    for r in c.execute("SELECT * FROM devices WHERE tenant_id=? ORDER BY created_at", (tid,))]

    def revoke(self, device_id, tid=None):
        with self._control() as c:
            sql, args = "UPDATE devices SET revoked=1, token_hash=NULL WHERE id=?", [device_id]
            if tid:
                sql += " AND tenant_id=?"
                args.append(tid)
            if not c.execute(sql, args).rowcount:
                raise CloudError("Компьютер не найден", 404)
        return True

    # ----------------------------------------------------------- devices --
    def join(self, invite, name, version=""):
        code = norm_invite(invite)
        if len(code) < 12:
            raise CloudError("Неверный код подключения", 400)
        with self._control() as c:
            t = c.execute("SELECT * FROM tenants WHERE invite_hash=?", (_h(code),)).fetchone()
            if not t:
                raise CloudError("Код подключения не подходит. Проверьте его или попросите новый.", 403)
            if t["status"] == "blocked":
                raise CloudError("Клиника отключена. Свяжитесь с поддержкой.", 403)
        sub = self.subscription(t["id"])
        if sub["devices"] >= sub["max_devices"]:
            raise CloudError(f"По тарифу «{sub['plan_title']}» можно подключить {sub['max_devices']} компьютеров. "
                             "Отключите ненужный компьютер или смените тариф.", 402)
        did, token = secrets.token_hex(8), secrets.token_urlsafe(32)
        with self._control() as c:
            c.execute("INSERT INTO devices(id, tenant_id, name, token_hash, created_at, last_seen, version) VALUES(?,?,?,?,?,?,?)",
                      (did, t["id"], str(name or "Компьютер")[:80], _h(token), _now(), _now(), str(version)[:20]))
        return {"device": did, "token": token, "tenant": t["id"], "name": t["name"], "key_check": t["key_check"],
                "subscription": self.subscription(t["id"])}

    def device_for(self, token):
        if not token:
            raise CloudError("Компьютер не подключён к облаку", 401)
        with self._control() as c:
            d = c.execute("SELECT * FROM devices WHERE token_hash=? AND revoked=0", (_h(token),)).fetchone()
            if not d:
                raise CloudError("Этот компьютер отключён от облака клиники. Подключите его заново.", 401)
            c.execute("UPDATE devices SET last_seen=? WHERE id=?", (_now(), d["id"]))
        return dict(d)

    def set_key_check(self, dev, check):
        if not HEX.match(str(check or "")):
            raise CloudError("Неверный ключ")
        with self._control() as c:
            t = c.execute("SELECT key_check FROM tenants WHERE id=?", (dev["tenant_id"],)).fetchone()
            if t["key_check"] and t["key_check"] != check:
                raise CloudError("Ключ клиники уже задан на другом компьютере", 409)
            c.execute("UPDATE tenants SET key_check=? WHERE id=? AND key_check IS NULL", (check, dev["tenant_id"]))
        return True

    def _writable(self, tid, write=True):
        sub = self.subscription(tid)
        if sub["state"] in ("expired", "blocked"):
            raise CloudError("Подписка закончилась — синхронизация приостановлена. Данные на компьютерах клиники "
                             "сохраняются; после оплаты синхронизация продолжится сама.", 402)
        return sub

    # -------------------------------------------------------------- sync --
    def push(self, dev, changes):
        tid = dev["tenant_id"]
        self._writable(tid)
        if not isinstance(changes, list) or len(changes) > MAX_PUSH:
            raise CloudError("Слишком много изменений за раз")
        accepted, rejected = [], []
        with self._lock(tid), self._tenant_db(tid) as c:
            seq = int((c.execute("SELECT v FROM meta WHERE k='seq'").fetchone() or [0])[0])
            for ch in changes:
                key, ver, base, data = str(ch.get("key") or ""), str(ch.get("ver") or ""), ch.get("base"), ch.get("data")
                if not HEX.match(key) or not ver or not isinstance(data, str) or len(ver) > 80:
                    rejected.append({"key": key, "reason": "bad"})
                    continue
                cur = c.execute("SELECT ver FROM rows WHERE key=?", (key,)).fetchone()
                if (cur["ver"] if cur else None) != base:
                    rejected.append({"key": key, "reason": "conflict"})
                    continue
                seq += 1
                c.execute("INSERT INTO rows(key, ver, data, device, seq) VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                          "ver=excluded.ver, data=excluded.data, device=excluded.device, seq=excluded.seq",
                          (key, ver, data, dev["id"], seq))
                accepted.append(key)
            c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('seq', ?)", (str(seq),))
        return {"accepted": accepted, "rejected": rejected, "seq": seq}

    def pull(self, dev, since=0, limit=PULL_LIMIT):
        tid = dev["tenant_id"]
        sub = self._writable(tid)
        limit = max(1, min(int(limit or PULL_LIMIT), PULL_LIMIT))
        with self._tenant_db(tid) as c:
            rows = [dict(r) for r in c.execute("SELECT key, ver, data, device, seq FROM rows WHERE seq>? ORDER BY seq LIMIT ?",
                                               (int(since or 0), limit))]
            top = int((c.execute("SELECT v FROM meta WHERE k='seq'").fetchone() or [0])[0])
        return {"rows": rows, "more": bool(rows) and rows[-1]["seq"] < top, "seq": top, "subscription": sub}

    @staticmethod
    def _sha_path(path) -> str:
        """The blob's checksum lives beside the blob folder (<tenant>.blobs.sha), the folder keeps only blobs."""
        d = os.path.dirname(path) + ".sha"
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, os.path.basename(path))

    @classmethod
    def _blob_whole(cls, path) -> bool:
        """The stored blob is whole: its checksum (kept next to it since the upload) matches. Older blobs: by existence."""
        if not os.path.exists(path):
            return False
        try:
            with open(cls._sha_path(path), encoding="ascii") as f:
                want = f.read().strip()
        except OSError:
            return True
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest() == want

    def blob_put(self, dev, bid, data: bytes, sha=""):
        if not HEX.match(bid):
            raise CloudError("Неверный файл")
        self._writable(dev["tenant_id"])
        got = hashlib.sha256(data).hexdigest()
        if sha and sha.lower() != got:  # cut on the way
            raise CloudError("Файл передан не полностью")
        path = os.path.join(self._blob_dir(dev["tenant_id"]), bid)
        if not self._blob_whole(path):  # a damaged copy is replaced by a whole one
            sp = self._sha_path(path)
            for p, b in ((path + ".tmp", data), (sp + ".tmp", got.encode("ascii"))):
                with open(p, "wb") as f:
                    f.write(b)
                    f.flush()
                    os.fsync(f.fileno())
            os.replace(path + ".tmp", path)
            os.replace(sp + ".tmp", sp)
        return {"ok": True}

    def blob_get(self, dev, bid):
        if not HEX.match(bid):
            raise CloudError("Неверный файл")
        path = os.path.join(self._blob_dir(dev["tenant_id"]), bid)
        if not self._blob_whole(path):
            raise CloudError("Файл не найден", 404)
        with open(path, "rb") as f:
            return f.read()

    def blob_has(self, dev, ids):
        d = self._blob_dir(dev["tenant_id"])
        return [b for b in ids if HEX.match(str(b)) and self._blob_whole(os.path.join(d, b))]


class _Conn:
    """sqlite3 connection as a context manager that commits and always closes."""

    def __init__(self, c):
        self.c = c

    def __enter__(self):
        return self.c

    def __exit__(self, exc, *_):
        if exc is None:
            self.c.commit()
        self.c.close()


# ------------------------------------------------------------------ http --
def make_handler(cloud: Cloud):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DentalDeskCloud/1"
        timeout = 30  # a slow or silent client does not hold a thread forever

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0:  # -1 would read until the client closes, past MAX_BODY
                raise CloudError("Неверный запрос", 400)
            if n > MAX_BODY:
                raise CloudError("Слишком большой запрос", 413)
            return self.rfile.read(n) if n else b""

        def _dev(self):
            auth = self.headers.get("Authorization", "")
            return cloud.device_for(auth[7:] if auth.startswith("Bearer ") else "")

        def _route(self, method):
            path = self.path.split("?")[0].rstrip("/")
            if method == "GET" and path in ("/v1/ping", ""):
                return self._json(200, {"app": "dentaldesk-cloud", "api": API_VERSION})
            if path.startswith("/v1/blob/"):
                dev, bid = self._dev(), path.rsplit("/", 1)[-1]
                if method == "PUT":
                    return self._json(200, cloud.blob_put(dev, bid, self._body(), self.headers.get("X-Blob-Sha256") or ""))
                return self._send(200, cloud.blob_get(dev, bid), "application/octet-stream")
            if method != "POST":
                raise CloudError("Не найдено", 404)
            raw = self._body()
            try:
                f = json.loads(raw or b"{}")
            except ValueError:
                raise CloudError("Неверный запрос") from None
            if not isinstance(f, dict):
                raise CloudError("Неверный запрос")
            if path == "/v1/join":
                return self._json(200, cloud.join(f.get("invite"), f.get("name"), f.get("version", "")))
            dev = self._dev()
            if path == "/v1/key_check":
                return self._json(200, {"ok": cloud.set_key_check(dev, f.get("check"))})
            if path == "/v1/status":
                with cloud._control() as c:
                    t = c.execute("SELECT key_check FROM tenants WHERE id=?", (dev["tenant_id"],)).fetchone()
                    if f.get("version"):
                        c.execute("UPDATE devices SET version=? WHERE id=?", (str(f["version"])[:20], dev["id"]))
                return self._json(200, {"subscription": cloud.subscription(dev["tenant_id"]), "device": dev["id"],
                                        "devices": cloud.devices(dev["tenant_id"]), "key_check": t["key_check"]})
            if path == "/v1/push":
                return self._json(200, cloud.push(dev, f.get("changes") or []))
            if path == "/v1/pull":
                return self._json(200, cloud.pull(dev, f.get("since", 0), f.get("limit", PULL_LIMIT)))
            if path == "/v1/blob_has":
                return self._json(200, {"have": cloud.blob_has(dev, f.get("ids") or [])})
            if path == "/v1/leave":
                return self._json(200, {"ok": cloud.revoke(dev["id"], dev["tenant_id"])})
            if path == "/v1/revoke":  # a director switches off another computer of the same clinic
                return self._json(200, {"ok": cloud.revoke(str(f.get("device") or ""), dev["tenant_id"])})
            raise CloudError("Не найдено", 404)

        def _handle(self, method):
            try:
                self._route(method)
            except CloudError as e:
                self._json(e.code, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"error {self.path}: {e!r}\n")
                self._json(500, {"error": "Ошибка сервера"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def log_message(self, fmt, *args):
            if os.environ.get("CLOUD_LOG"):
                sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    return Handler


def serve(data_dir, host="127.0.0.1", port=8780, background=False):
    cloud = Cloud(data_dir)
    httpd = ThreadingHTTPServer((host, port), make_handler(cloud))
    httpd.daemon_threads = True
    if background:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, cloud
    print(f"Dental Desk cloud on http://{host}:{port}/  data: {cloud.dir}")
    httpd.serve_forever()
    return httpd, cloud


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dental Desk cloud server")
    ap.add_argument("--data", default=os.environ.get("CLOUD_DATA", "./cloud-data"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8780)
    s = sub.add_parser("create-tenant")
    s.add_argument("name")
    s.add_argument("--days", type=int, default=TRIAL_DAYS)
    s = sub.add_parser("pay")
    s.add_argument("tenant")
    s.add_argument("--plan", required=True, choices=[k for k in PLANS if k != "trial"])
    s.add_argument("--months", type=int, default=1)
    s.add_argument("--amount", type=float, default=0)
    s.add_argument("--note", default="")
    sub.add_parser("list")
    sub.add_parser("plans")
    s = sub.add_parser("devices")
    s.add_argument("tenant")
    s = sub.add_parser("revoke")
    s.add_argument("device")
    s = sub.add_parser("new-invite")
    s.add_argument("tenant")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        serve(a.data, a.host, a.port)
        return 0
    cloud = Cloud(a.data)
    out = {"create-tenant": lambda: cloud.create_tenant(a.name, days=a.days),
           "pay": lambda: cloud.pay(a.tenant, a.plan, a.months, a.amount, a.note),
           "list": cloud.tenants, "plans": lambda: PLANS,
           "devices": lambda: cloud.devices(a.tenant), "revoke": lambda: cloud.revoke(a.device),
           "new-invite": lambda: {"invite": cloud.new_invite(a.tenant)}}[a.cmd]()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
