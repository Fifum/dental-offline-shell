"""3.19: the stock app of a phone through the clinic's Wi-Fi — without the internet, straight to this computer.

The program's server gives the files of the phone app (the folder `phone/`, the same as on Vercel) under /s/ and their API
under /s/api/p/... — the routes of the cloud of the stock (/p/login, /p/pull, /p/op, ...), answered here:

- a phone is connected once through the cloud (the personal QR, the person's own PIN — 3.18.3); the cloud app then hands it
  over to this address with the device's token in the link's fragment. This computer knows the phones from the cloud's list
  (/v1/phones, taken with every sync of the stock: the token's and the PIN's hashes) and keeps the last copy for the time
  without the internet (`phone_local_devices`, not replicated);
- the PIN is checked against that copy (a bound phone) or against users.phone_pin_hash of this computer (the old way: the
  clinic's QR, «Кто вы?»); the rights always come from this computer's own staff, so a dismissal works at once;
- an operation runs through the program's own methods (Api) as the phone's employee — the same rules as at the computer, the
  same journal; a repeat after a lost answer is done once (`phone_local_ops`, by the phone's id of the operation). The rows it
  makes go to the cloud and to the other computers by the ordinary sync. The queues of the cloud app and of this one are
  separate (separate origins): what one queued goes only to its own address, so nothing is done twice.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time

import config
import replica

log = logging.getLogger("phone_lan")

SESSION_H = 12
PIN_FAILS = 5
LOCK_MIN = 15
PULL_LIMIT = 1000
OP_WAIT = 120  # an operation that has not finished this long (the program was closed meanwhile) is not waited for

SCHEMA = """
CREATE TABLE IF NOT EXISTS phone_local_devices(id TEXT PRIMARY KEY, name TEXT, login TEXT, pin_hash TEXT, token_hash TEXT,
    revoked INTEGER DEFAULT 0, bound_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_phone_local_devices_token ON phone_local_devices(token_hash);
CREATE TABLE IF NOT EXISTS phone_local_sessions(token_hash TEXT PRIMARY KEY, device_id TEXT, login TEXT, expires_at REAL,
    last_seen REAL);
CREATE TABLE IF NOT EXISTS phone_local_ops(op TEXT PRIMARY KEY, login TEXT, kind TEXT, result TEXT, at REAL);
CREATE TABLE IF NOT EXISTS phone_local_fails(k TEXT PRIMARY KEY, n INTEGER DEFAULT 0, until REAL DEFAULT 0);
"""

STOCK_T = {"materials", "suppliers", "stock_locations", "stock_docs", "stock_moves", "stock_lots", "stock_settings",
           "stock_requests", "stock_approvals", "material_docs"}
EQUIP_T = {"equipment", "equipment_events", "equipment_docs", "stock_locations", "stock_settings"}
EQ_MONEY = ("price", "salvage", "market_value", "replace_cost", "reserve_monthly", "disposal_amount", "residual")

NOT_HERE = "Подключите телефон, когда есть интернет: на компьютере клиники «Подключить мой телефон»."

# where this computer answers the phones (set by the server when it starts)
SERVER = {"port": 0, "https_port": 0}


class PhoneError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def _sha(s: str) -> str:
    return hashlib.sha256(str(s or "").encode("utf-8")).hexdigest()


def install(db):
    with db._lock:
        db.conn.executescript(SCHEMA)
        db.conn.commit()


def store_devices(db, phones: list) -> int:
    """The cloud's list of the phones of the clinic (/v1/phones) → this computer's copy. A phone the cloud no longer has is
    kept as disconnected (its sessions here end), never forgotten silently while it may still be signed in."""
    install(db)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    seen = set()
    with db.tx() as c:
        for p in phones or []:
            pid = str(p.get("id") or "")[:40]
            if not pid:
                continue
            seen.add(pid)
            revoked = 1 if p.get("revoked") or not p.get("token_hash") else 0
            c.execute("INSERT OR REPLACE INTO phone_local_devices(id, name, login, pin_hash, token_hash, revoked, bound_at, updated_at) "
                      "VALUES(?,?,?,?,?,?,?,?)", (pid, str(p.get("name") or "")[:80], str(p.get("login") or "").lower()[:60],
                                                  str(p.get("pin_hash") or "")[:200], str(p.get("token_hash") or "")[:80], revoked,
                                                  str(p.get("bound_at") or "")[:40], now))
        gone = [r[0] for r in c.execute("SELECT id FROM phone_local_devices WHERE revoked=0").fetchall() if r[0] not in seen]
        for pid in gone:
            c.execute("UPDATE phone_local_devices SET revoked=1, updated_at=? WHERE id=?", (now, pid))
        c.execute("DELETE FROM phone_local_sessions WHERE device_id IN (SELECT id FROM phone_local_devices WHERE revoked=1) "
                  "OR expires_at<?", (time.time(),))
        c.execute("DELETE FROM phone_local_ops WHERE at<?", (time.time() - 30 * 86400,))
    return len(seen)


def lan_info() -> dict:
    """The addresses of this computer for the phones on the clinic's Wi-Fi: {name, ip, http, https}."""
    import socket
    from server import local_addresses
    ips = local_addresses()
    ip = ips[0] if ips else ""
    port, sport = SERVER.get("port") or 0, SERVER.get("https_port") or 0
    return {"name": socket.gethostname(), "ip": ip, "ips": ips,
            "http": f"http://{ip}:{port}/s/" if ip and port else "",
            "https": f"https://{ip}:{sport}/s/" if ip and sport else ""}


def me(user: dict, perms: set, clinic: str) -> dict:
    """The same as me() of the cloud of the stock (cloud/stock/functions/stock/index.ts)."""
    p = perms
    return {"login": user["login"], "name": user["name"], "role_title": user["role_title"], "perms": sorted(p), "clinic": clinic,
            "local": True,
            "can": {"stock": bool(p & {"stock_view", "stock_ops", "stock_edit", "stock_approve"}),
                    "equipment": bool(p & {"equipment", "stock_view"}), "equipment_edit": "equipment" in p,
                    "money": "accounting" in p, "receive": bool(p & {"stock_edit", "stock_ops"}),
                    "use": bool(p & {"stock_edit", "stock_ops"}), "direct": bool(p & {"stock_edit", "stock_approve"}),
                    "approve": "stock_approve" in p, "request": bool(p & {"stock_edit", "stock_ops"}),
                    "handle_requests": bool(p & {"stock_edit", "stock_approve"}), "transfer": bool(p & {"stock_edit", "stock_ops"}),
                    "barcode": "stock_edit" in p, "photo": "equipment" in p, "photo_mat": bool(p & {"stock_edit", "stock_ops"})}}


class PhoneLan:
    def __init__(self, api, db, auth):
        self.api, self.db, self.auth = api, db, auth
        install(db)
        replica.install(db)  # /p/pull reads the replica's rows (made by p2p/stock_cloud as well; idempotent)
        self._lock = threading.Lock()

    # ------------------------------------------------------------ helpers --
    def _clinic(self) -> str:
        s = config.load_settings()
        return s.get("stock_cloud_name") or s.get("clinic_name") or config.BRAND.get("name") or ""

    def _kick(self):
        w = getattr(self.api, "_stock_cloud_worker", None)
        if w is not None:
            try:
                w.trigger()
            except Exception:  # noqa: BLE001
                pass

    def _device(self, headers):
        t = headers.get("X-DD-Device", "") or ""
        if not t:
            raise PhoneError("Телефон не подключён к клинике. " + NOT_HERE, 401)
        d = self.db.one("SELECT * FROM phone_local_devices WHERE token_hash=?", (_sha(t),))
        if not d:
            self._kick()  # a phone bound a moment ago: the next sync of the stock brings it
            raise PhoneError("Компьютер клиники ещё не получил этот телефон из облака склада. Подождите минуту и попробуйте снова "
                             "(компьютеру нужен интернет хотя бы раз после подключения телефона).", 409)
        if d["revoked"]:
            raise PhoneError("Телефон отключён от клиники. " + NOT_HERE, 401)
        return d

    def _user(self, login):
        import auth
        from stock_cloud import PHONE_PERMS, STOCK_RIGHTS
        u = self.db.one("SELECT * FROM users WHERE lower(login)=?", (str(login or "").lower(),))
        if not u or u.get("status") != "active":
            return None, set()
        perms = set(auth.Auth.effective_perms(u)) & set(PHONE_PERMS)
        if not perms & STOCK_RIGHTS:
            return u, set()
        titles = {k: v["title"] for k, v in auth.roles(self.db).items()}
        u = {**u, "login": (u["login"] or "").lower(), "name": u.get("name") or u["login"],
             "role_title": titles.get(u.get("role") or "", u.get("position") or "")}
        return u, perms

    def _wait(self, key) -> int:
        r = self.db.one("SELECT until FROM phone_local_fails WHERE k=?", (key,))
        left = (r["until"] if r else 0) - time.time()
        return int(left // 60) + 1 if left > 0 else 0

    def _fail(self, key):
        with self.db.tx() as c:
            r = c.execute("SELECT n FROM phone_local_fails WHERE k=?", (key,)).fetchone()
            n = (r[0] if r else 0) + 1
            if n >= PIN_FAILS:
                c.execute("INSERT OR REPLACE INTO phone_local_fails(k, n, until) VALUES(?, 0, ?)", (key, time.time() + LOCK_MIN * 60))
            else:
                c.execute("INSERT OR REPLACE INTO phone_local_fails(k, n, until) VALUES(?, ?, 0)", (key, n))

    def _ok(self, *keys):
        with self.db.tx() as c:
            for k in keys:
                c.execute("DELETE FROM phone_local_fails WHERE k=?", (k,))

    def _session(self, headers):
        """(user, perms, device) of a signed-in phone, the same checks as phone() of the cloud."""
        s = headers.get("X-DD-Session", "") or ""
        if not s:
            raise PhoneError("Войдите по ПИН-коду", 401)
        r = self.db.one("SELECT * FROM phone_local_sessions WHERE token_hash=? AND expires_at>?", (_sha(s), time.time()))
        d = self.db.one("SELECT * FROM phone_local_devices WHERE id=?", (r["device_id"],)) if r else None
        u, perms = self._user(r["login"]) if r else (None, set())
        bound = bool(d and d["login"] == (r or {}).get("login") and d["pin_hash"])
        if not r or not d or d["revoked"] or not u or not perms or not (bound or (u.get("phone_pin_hash") or "")):
            raise PhoneError("Войдите по ПИН-коду заново", 401)
        with self.db.tx() as c:
            c.execute("UPDATE phone_local_sessions SET last_seen=? WHERE token_hash=?", (time.time(), r["token_hash"]))
        return u, perms, d

    # ------------------------------------------------------------ routes --
    def handle(self, name, body, headers, ip=""):
        body = body if isinstance(body, dict) else {}
        if name in ("hello", "pair_info", "pair"):
            raise PhoneError(NOT_HERE, 400)
        if name == "staff":
            return self.staff(headers)
        if name == "login":
            return self.login(headers, body)
        if name == "logout":
            s = headers.get("X-DD-Session", "") or ""
            if s:
                with self.db.tx() as c:
                    c.execute("DELETE FROM phone_local_sessions WHERE token_hash=?", (_sha(s),))
            return {"ok": True}
        if name == "leave":  # only here: the phone stays connected in the cloud (that is done in the cloud app)
            t = headers.get("X-DD-Device", "") or ""
            d = self.db.one("SELECT id FROM phone_local_devices WHERE token_hash=?", (_sha(t),)) if t else None
            if d:
                with self.db.tx() as c:
                    c.execute("DELETE FROM phone_local_sessions WHERE device_id=?", (d["id"],))
            return {"ok": True}
        if name == "pin":
            self._session(headers)
            raise PhoneError("Сменить ПИН-код можно, когда есть интернет: откройте склад через интернет.", 400)
        u, perms, d = self._session(headers)
        if name == "me":
            return {"user": me(u, perms, self._clinic())}
        if name == "pull":
            return self.pull(u, perms, body)
        if name == "op":
            return self.op(u, perms, d, body, ip)
        raise PhoneError("Не найдено", 404)

    def staff(self, headers):
        d = self._device(headers)
        out = []
        if not (d["login"] and d["pin_hash"]):
            for r in self.db.q("SELECT login FROM users WHERE status='active' AND COALESCE(phone_pin_hash,'')<>'' ORDER BY name"):
                u, perms = self._user(r["login"])
                if u and perms:
                    out.append({"login": u["login"], "name": u["name"], "role_title": u["role_title"]})
        return {"clinic": self._clinic(), "staff": out, "bound": d["login"] if d["login"] and d["pin_hash"] else None,
                "local": True}

    def login(self, headers, body):
        import auth
        d = self._device(headers)
        w = self._wait("d:" + d["id"])
        if w:
            raise PhoneError(f"Слишком много неверных ПИН-кодов. Подождите {w} мин.", 429)
        own = bool(d["login"] and d["pin_hash"])
        login = d["login"] if own else str(body.get("login") or "").lower()[:60]
        u, perms = self._user(login)
        if u and (w := self._wait("u:" + u["login"])):
            raise PhoneError(f"Слишком много неверных ПИН-кодов. Подождите {w} мин.", 429)
        if u and not perms:
            raise PhoneError("У вашей должности больше нет доступа к складу", 403)
        pin = str(body.get("pin") or "")
        stored = d["pin_hash"] if own else (u or {}).get("phone_pin_hash") or ""
        ok = bool(u) and len(pin) == 6 and pin.isdigit() and bool(stored) and auth.check_password(pin, stored)
        if not ok:
            self._fail("d:" + d["id"])
            if u:
                self._fail("u:" + u["login"])
            raise PhoneError("Неверный ПИН-код", 403)
        self._ok("d:" + d["id"], "u:" + u["login"])
        tok = secrets.token_urlsafe(32)
        with self.db.tx() as c:
            c.execute("DELETE FROM phone_local_sessions WHERE expires_at<?", (time.time(),))
            c.execute("INSERT INTO phone_local_sessions(token_hash, device_id, login, expires_at, last_seen) VALUES(?,?,?,?,?)",
                      (_sha(tok), d["id"], u["login"], time.time() + SESSION_H * 3600, time.time()))
        return {"session": tok, "hours": SESSION_H, "user": me(u, perms, self._clinic())}

    def pull(self, u, perms, body):
        m = me(u, perms, self._clinic())
        if not m["can"]["stock"] and not m["can"]["equipment"]:
            raise PhoneError("У вашей должности нет доступа к складу", 403)
        from stock_cloud import TABLES
        replica.stamp(self.db, config.node_id())
        try:
            since = int(body.get("since") or 0)
        except (TypeError, ValueError):
            since = 0
        q = ",".join("?" * len(TABLES))
        rows = self.db.q(f"SELECT tbl, k, seq, base FROM sync_rows WHERE seq>? AND tbl IN ({q}) ORDER BY seq LIMIT ?",
                         (since, *TABLES, PULL_LIMIT))
        all_ = bool(perms & {"stock_edit", "stock_approve"})
        out = []
        for r in rows:
            t = r["tbl"]
            if not ((m["can"]["stock"] and t in STOCK_T) or (m["can"]["equipment"] and t in EQUIP_T)):
                continue
            row = replica.hide(t, json.loads(r["base"])) if r["base"] else None
            if t in ("stock_requests", "stock_approvals") and not all_ and row and row.get("created_by") != u["login"]:
                continue
            if t == "equipment" and row and not m["can"]["money"]:
                row = {k: v for k, v in row.items() if k not in EQ_MONEY}
            out.append({"t": t, "k": r["k"], "row": row, "seq": r["seq"]})
        nxt = rows[-1]["seq"] if rows else since
        return {"rows": out, "next": nxt, "more": len(rows) >= PULL_LIMIT, "user": m}

    # -------------------------------------------------------- operations --
    def op(self, u, perms, d, f, ip):
        oid = str(f.get("op") or "")
        if not (8 <= len(oid) <= 80) or not all(ch.isalnum() or ch in "_-" for ch in oid) or not oid.isascii():
            raise PhoneError("Неверная операция")
        kind = str(f.get("kind") or "")
        if kind not in OPS:
            raise PhoneError("Неизвестная операция")
        with self._lock:  # claimed first: two copies sent at once (a repeat while the first runs) run once
            with self.db.tx() as c:
                got = c.execute("INSERT OR IGNORE INTO phone_local_ops(op, login, kind, result, at) VALUES(?,?,?,NULL,?)",
                                (oid, u["login"], kind, time.time())).rowcount
        if not got:
            r = self.db.one("SELECT result, at FROM phone_local_ops WHERE op=?", (oid,))
            if r and r["result"]:
                return {**json.loads(r["result"]), "repeated": True}
            if not r or time.time() - (r["at"] or 0) < OP_WAIT:
                raise PhoneError("Операция ещё выполняется — повторю позже", 503)
            raise PhoneError("Операция не завершилась — проверьте данные и сделайте её заново", 409)
        try:
            res = self._run(u, perms, kind, f, oid, ip)
        except BaseException:
            with self.db.tx() as c:
                c.execute("DELETE FROM phone_local_ops WHERE op=? AND result IS NULL", (oid,))
            raise
        with self.db.tx() as c:
            c.execute("UPDATE phone_local_ops SET result=? WHERE op=?", (json.dumps(res, ensure_ascii=False, default=str), oid))
        return res

    def _run(self, u, perms, kind, f, oid, ip):
        from auth import AUDITED, METHOD_PERMS, Auth, AuthError, request_scope, set_current_user
        need, method, fn = OPS[kind]
        if not perms & set(need):
            raise PhoneError("У вашей должности нет на это права", 403)
        want = METHOD_PERMS.get(method)
        if want is not None and want != "*":
            wants = want if isinstance(want, tuple) else (want,)
            if not set(Auth.effective_perms(u)) & set(wants):
                raise PhoneError("Недостаточно прав для этого действия. Обратитесь к директору.", 403)
        set_current_user(u)
        try:
            with request_scope(ip):
                res = fn(self, f, oid, u)
        except AuthError as e:
            raise PhoneError(str(e), e.code) from None
        finally:
            set_current_user(None)
        if method in AUDITED:
            from server import _brief
            self.auth.log(u, AUDITED[method] + " (телефон)", _brief([{k: v for k, v in f.items() if k not in ("data", "op")}]), ip)
        return res

    # each: what the phone sends (the format of the cloud's opXxx) → the program's own method
    def _receive(self, f, oid, u):
        did = self.api.stock_receive({k: f.get(k) for k in ("lines", "date", "location_id", "supplier_id", "number", "comment",
                                                            "nodoc") if k in f})
        return {"doc_id": did, "message": "Поставка принята"}

    def _use(self, f, oid, u):
        form = {k: f.get(k) for k in ("lines", "location_id", "reason", "comment", "date", "time") if k in f}
        form["kind"] = "writeoff" if f.get("what") == "writeoff" else "consume"
        r = self.api.stock_use(form)
        done = (r or {}).get("status") == "done"
        return {"id": (r or {}).get("id"), "status": (r or {}).get("status"),
                "message": "Списано" if done else "Отправлено на согласование — со склада спишется после проверки менеджера"}

    def _decide(self, f, oid, u):
        r = self.api.stock_approval_decide(f.get("id"), f.get("action"), f.get("answer") or "")
        return {"id": (r or {}).get("id") or f.get("id"),
                "message": "Отклонено" if f.get("action") == "reject" else "Согласовано и списано"}

    def _approval_cancel(self, f, oid, u):
        self.api.stock_approval_cancel(f.get("id"))
        return {"id": f.get("id"), "message": "Отменено"}

    def _request(self, f, oid, u):
        r = self.api.stock_request_save({**{k: f.get(k) for k in ("lines", "location_id", "need_date", "priority", "comment")
                                            if k in f}, "send": 1})
        n = (r or {}).get("number") or ""
        return {"id": (r or {}).get("id"), "number": n, "message": f"Заявка № {n} отправлена" if n else "Заявка отправлена"}

    def _request_status(self, f, oid, u):
        k = f.get("kind")
        if k == "request_accept":
            self.api.stock_request_accept(f.get("id"))
            return {"id": f.get("id"), "message": "Заявка принята"}
        if k == "request_reject":
            self.api.stock_request_reject(f.get("id"), f.get("answer") or "")
            return {"id": f.get("id"), "message": "Заявка отклонена"}
        self.api.stock_request_cancel(f.get("id"))
        return {"id": f.get("id"), "message": "Заявка отменена"}

    def _transfer(self, f, oid, u):
        did = self.api.stock_transfer({k: f.get(k) for k in ("from_id", "to_id", "lines", "date", "comment", "request_ids") if k in f})
        return {"doc_id": did, "message": "Перемещено"}

    def _equipment_set(self, f, oid, u):
        if f.get("status") == "written_off":
            raise PhoneError("Выбытие оформляется в программе на компьютере")
        self.api.equipment_set({k: f.get(k) for k in ("id", "location_id", "location", "condition", "status", "text") if k in f})
        return {"id": f.get("id"), "message": "Сохранено"}

    def _equipment_inventory(self, f, oid, u):
        self.api.equipment_inventory({k: f.get(k) for k in ("id", "found", "location_id", "location", "condition", "comment",
                                                            "date") if k in f})
        return {"id": f.get("id"), "message": "Инвентаризация записана"}

    def _equipment_event(self, f, oid, u):
        ev = f.get("event") if f.get("event") in ("service", "repair", "note") else "note"
        b = {"equipment_id": f.get("id"), "kind": ev, "text": f.get("text") or "", "cost": f.get("cost") or 0,
             "date": f.get("date") or "", "back_in_use": bool(f.get("back_in_use"))}
        if f.get("next_service") is not None:
            b["next_service"] = f.get("next_service")
        self.api.equipment_event(b)
        return {"id": f.get("id"), "message": "Записано"}

    def _barcode(self, f, oid, u):
        mid, bar = str(f.get("id") or "")[:60], str(f.get("barcode") or "").strip()[:60]
        if not bar:
            raise PhoneError("Отсканируйте штрихкод")
        if not self.db.one("SELECT 1 AS x FROM materials WHERE id=?", (mid,)):
            raise PhoneError("Материал не найден", 404)
        dup = self.db.one("SELECT name FROM materials WHERE barcode=? AND id<>? AND COALESCE(active,1)=1", (bar, mid))
        if dup:
            raise PhoneError(f"Штрихкод {bar} уже указан у материала «{dup['name']}»")
        with self.db.tx() as c:
            c.execute("UPDATE materials SET barcode=? WHERE id=?", (bar, mid))
        return {"id": mid, "message": "Штрихкод привязан"}

    def _photo_bytes(self, f) -> bytes:
        raw = "".join(str(f.get("data") or "").split())
        if raw.startswith("data:"):
            raw = raw.split(",", 1)[-1]
        if not raw:
            raise PhoneError("Нет снимка — сфотографируйте ещё раз")
        if len(raw) > 4_100_000:
            raise PhoneError("Снимок больше 3 МБ — сфотографируйте ещё раз", 413)
        try:
            return base64.b64decode(raw, validate=False)
        except ValueError:
            raise PhoneError("Снимок повреждён — сфотографируйте ещё раз") from None

    def _photo_note(self, f, u):
        from stock_cloud import photo_note
        at = str(f.get("taken_at") or "").replace("T", " ")[:19]
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        return photo_note({"taken_name": u["name"], "taken_by": u["login"], "taken_role": u["role_title"],
                           "taken_at": at if len(at) >= 16 and at <= now else now})

    def _equipment_photo(self, f, oid, u):
        e = self.db.one("SELECT id, status, inv_number FROM equipment WHERE id=?", (str(f.get("id") or ""),))
        if not e:
            raise PhoneError("Оборудование не найдено", 404)
        if e["status"] == "written_off":
            raise PhoneError("Оборудование выбыло — изменить его нельзя")
        data = self._photo_bytes(f)
        ph = self.api._files.add_stock_photo(f"Фото с телефона {e['inv_number'] or ''}".strip() + ".jpg", data, u["name"])
        self.api._stock.equipment_photo_add(e["id"], ph["id"], "Фото с телефона", u["name"], doc_id="EDP-" + oid,
                                            note=self._photo_note(f, u))
        return {"id": e["id"], "photo": oid, "message": "Фото в карточке на компьютере клиники"}

    def _material_photo(self, f, oid, u):
        m = self.db.one("SELECT id, number, code FROM materials WHERE id=? AND COALESCE(active,1)=1", (str(f.get("id") or ""),))
        if not m:
            raise PhoneError("Материал не найден или убран из справочника", 404)
        data = self._photo_bytes(f)
        ph = self.api._files.add_stock_photo(f"Фото с телефона {m['number'] or m['code'] or ''}".strip() + ".jpg", data, u["name"])
        self.api._stock.material_doc_add(m["id"], "photo", self._photo_note(f, u), ph["id"], u["name"], doc_id="MDP-" + oid)
        return {"id": m["id"], "photo": oid, "message": "Фото в карточке материала на компьютере клиники"}


SE, SO, SA, EQ = "stock_edit", "stock_ops", "stock_approve", "equipment"
OPS = {  # kind: (the rights of the cloud's need(), the Api method whose METHOD_PERMS apply too, how)
    "receive": ((SE, SO), "stock_receive", PhoneLan._receive),
    "use": ((SE, SO), "stock_use", PhoneLan._use),
    "decide": ((SA,), "stock_approval_decide", PhoneLan._decide),
    "approval_cancel": ((SE, SO, SA), "stock_approval_cancel", PhoneLan._approval_cancel),
    "request": ((SE, SO), "stock_request_save", PhoneLan._request),
    "request_accept": ((SE, SA), "stock_request_accept", PhoneLan._request_status),
    "request_reject": ((SE, SA), "stock_request_reject", PhoneLan._request_status),
    "request_cancel": ((SE, SO, SA), "stock_request_cancel", PhoneLan._request_status),
    "transfer": ((SE, SO), "stock_transfer", PhoneLan._transfer),
    "equipment_set": ((EQ,), "equipment_set", PhoneLan._equipment_set),
    "equipment_inventory": ((EQ,), "equipment_inventory", PhoneLan._equipment_inventory),
    "equipment_event": ((EQ,), "equipment_event", PhoneLan._equipment_event),
    "barcode": ((SE,), "material_set", PhoneLan._barcode),
    "equipment_photo": ((EQ,), "equipment_photo_add", PhoneLan._equipment_photo),
    "material_photo": ((SE, SO), "material_doc_add", PhoneLan._material_photo),
}
