"""3.13: the cloud of the stock — the stock and the equipment of the clinic for the phones of the staff.

A laptop connected with the clinic's code (Склад → «Телефон и облако склада») sends the rows of its stock and equipment
tables to the cloud of the stock (Supabase, edge function «stock», see cloud/stock) with the same versions as between the
computers of the clinic (replica.py) and takes what the phones and the other laptops changed there. Patients never go
there: `patient_id` of stock moves and write-offs is left out (replica.HIDDEN) and put back from this computer's copy when
a row comes back. Unlike the main cloud (cloud.py) the rows are not encrypted end to end: the cloud checks the rights of a
phone and does stock operations itself, so it has to read them. What it keeps: materials, suppliers, places, documents,
moves, lots, equipment and its documents, requests and write-offs waiting for approval — no patients, no money of
patients. `sync_rows.sver` = the version the cloud of the stock has, so it gets only what it does not have yet.

The staff who may sign in on a phone: active employees with a personal PIN of the stock app (users.phone_pin_hash, only its
hash goes) and a right of the stock; the cloud checks every operation against their rights.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import socket
import threading
import time

import config
import replica

log = logging.getLogger("stock_cloud")

DEFAULT_URL = "https://jdqlcvmcfqtvzuymxhgg.supabase.co/functions/v1/stock"
PHONE_URL = "https://dental-desk-stock.vercel.app"
TABLES = ("materials", "suppliers", "stock_locations", "stock_docs", "stock_moves", "stock_lots", "stock_settings",
          "equipment", "equipment_events", "equipment_docs", "stock_requests", "stock_approvals")
PHONE_PERMS = ("stock_view", "stock_ops", "stock_edit", "stock_approve", "equipment", "accounting")
STOCK_RIGHTS = {"stock_view", "stock_ops", "stock_edit", "stock_approve", "equipment"}
INTERVAL = 60          # seconds between syncs
STATUS_EVERY = 600     # the clinic's status (phone code, devices) and the staff at least this often
PUSH_LIMIT = 400
TIMEOUT = 25


class StockCloudError(Exception):
    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


class Http:
    def __init__(self, url, token=""):
        import requests
        self.url, self.token, self.s = url.rstrip("/"), token, requests.Session()

    def post(self, path, body=None):
        import requests
        h = {"X-DD-Token": self.token} if self.token else {}
        try:
            r = self.s.post(self.url + path, json=body or {}, headers=h, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise StockCloudError("Нет связи с облаком склада", -1) from e
        if r.status_code >= 400:
            try:
                msg = r.json().get("error")
            except ValueError:
                msg = ""
            raise StockCloudError(msg or f"Облако склада ответило ошибкой {r.status_code}", r.status_code)
        return r.json()


class Store:
    """Where the connection is kept: the settings of the program (the token encrypted with DPAPI)."""

    def load(self) -> dict:
        s = config.load_settings()
        return {"url": s.get("stock_cloud_url") or "", "token": config.unprotect(s.get("stock_cloud_token") or ""),
                "device": s.get("stock_cloud_device") or "", "tenant": s.get("stock_cloud_tenant") or "",
                "name": s.get("stock_cloud_name") or "", "last_tenant": s.get("stock_cloud_last_tenant") or ""}

    def save(self, d: dict):
        out = {}
        for k, v in d.items():
            out["stock_cloud_" + k] = config.protect(v) if k == "token" and v else v
        config.save_settings(out)


def _tz() -> int:
    off = datetime.datetime.now().astimezone().utcoffset()
    return int(off.total_seconds() // 60) if off is not None else 180


class StockCloud:
    def __init__(self, db, store=None, node=None, transport=None):
        self.db = db
        self.store = store or Store()
        self.node = node or config.node_id()
        self.transport = transport or Http
        replica.install(db)
        self._lock = threading.Lock()
        self.state = {"last_ok": None, "last_try": None, "error": "", "offline": False, "running": False,
                      "pushed": 0, "pulled": 0}

    # ------------------------------------------------------------ helpers --
    def _meta(self, k, default=None):
        r = self.db.one("SELECT v FROM sync_state WHERE k=?", (k,))
        return r["v"] if r else default

    def _meta_set(self, k, v):
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES(?, ?)", (k, v))

    def configured(self) -> bool:
        s = self.store.load()
        return bool(s["url"] and s["token"])

    def _http(self):
        s = self.store.load()
        return self.transport(s["url"], s["token"])

    def pending(self) -> int:
        try:
            q = ",".join("?" * len(TABLES))
            return self.db.one(f"SELECT COUNT(*) AS n FROM sync_rows WHERE ver IS NOT NULL AND (sver IS NULL OR sver<>ver) "
                               f"AND tbl IN ({q})", TABLES)["n"] + self.db.one(
                f"SELECT COUNT(*) AS n FROM sync_dirty WHERE tbl IN ({q})", TABLES)["n"]
        except Exception:  # noqa: BLE001
            return 0

    def phone_url(self) -> str:
        try:
            r = self.db.one("SELECT v FROM stock_settings WHERE k='phone_url'")
        except Exception:  # noqa: BLE001 — no stock tables yet
            r = None
        return ((r or {}).get("v") or PHONE_URL).rstrip("/")

    def _ensure_phone_url(self):
        """The address of the phone app, once for the clinic (a replicated setting of the stock)."""
        try:
            if not self.db.one("SELECT 1 AS x FROM stock_settings WHERE k='phone_url'"):
                with self.db.tx() as c:
                    c.execute("INSERT OR IGNORE INTO stock_settings(k, v, updated_at) VALUES('phone_url', ?, ?)",
                              (PHONE_URL, time.strftime("%Y-%m-%d %H:%M:%S")))
        except Exception as e:  # noqa: BLE001
            log.info("phone_url: %s", e)

    # ------------------------------------------------------------ status --
    def status(self):
        s = self.store.load()
        st = json.loads(self._meta("scloud_status") or "{}")
        devs = st.get("devices") or []
        return {**self.state, "configured": self.configured(), "device": s["device"], "tenant": s["tenant"],
                "name": st.get("name") or s["name"], "phone_code": st.get("phone_code") or "", "phone_url": self.phone_url(),
                "laptops": sum(1 for d in devs if d.get("kind") == "laptop"),
                "phones": sum(1 for d in devs if d.get("kind") == "phone"),
                "staff": len(self._staff_list()), "pending": self.pending() if self.configured() else 0}

    def refresh_status(self, h=None):
        h = h or self._http()
        r = h.post("/v1/status", {"version": config.VERSION, "tz": _tz(),
                                  "clinic": config.load_settings().get("clinic_name") or ""})
        self._meta_set("scloud_status", json.dumps(r, ensure_ascii=False))
        self._meta_set("scloud_status_at", str(int(time.time())))
        return r

    def phone(self):
        """The clinic code for phones and a QR that opens the phone app with it."""
        if not self.configured():
            raise StockCloudError("Сначала подключите облако склада")
        st = json.loads(self._meta("scloud_status") or "{}")
        if not st.get("phone_code"):
            st = self.refresh_status()
        code = st.get("phone_code") or ""
        url = f"{self.phone_url()}/j#{code}"
        import crm
        return {"code": code, "url": url, "app": self.phone_url(), "qr": crm.qr_data_uri(url), "name": st.get("name") or ""}

    # ----------------------------------------------------------- connect --
    def join(self, code, name=""):
        if config.load_settings().get("demo") and not os.environ.get("DD_STOCK_CLOUD_DEMO"):
            raise StockCloudError("Сначала выключите демо-режим: иначе тестовый склад попадёт в облако и на телефоны.")
        if self.configured():
            raise StockCloudError("Этот компьютер уже подключён к облаку склада. Сначала отключите его.")
        code = "".join(str(code or "").split()).upper()
        if not code:
            raise StockCloudError("Введите код подключения склада (DDS-…)")
        url = (os.environ.get("DD_STOCK_CLOUD_URL") or DEFAULT_URL).rstrip("/")
        r = self.transport(url, "").post("/v1/join", {"code": code, "name": name or socket.gethostname(),
                                                      "version": config.VERSION, "tz": _tz()})
        prev = self.store.load()["last_tenant"]
        if prev != r["tenant"]:  # another clinic's cloud (or the first one): it has nothing of ours yet
            with self.db.tx() as c:
                c.execute("UPDATE sync_rows SET sver=NULL")
                c.execute("DELETE FROM sync_state WHERE k LIKE 'scloud_%'")
        self.store.save({"url": url, "token": r["token"], "device": r["device"], "tenant": r["tenant"],
                         "name": r.get("name") or "", "last_tenant": r["tenant"]})
        self._meta_set("scloud_status_at", "0")
        log.info("joined the stock cloud %s as %s", r["tenant"], r["device"])
        return {"ok": True, "name": r.get("name") or ""}

    def leave(self):
        s = self.store.load()
        if s["token"]:
            try:
                self._http().post("/v1/leave")
            except StockCloudError as e:
                log.info("leave: %s", e)
        self.store.save({"url": "", "token": "", "device": "", "tenant": "", "name": ""})
        self.state.update(error="", last_ok=None)
        return True

    # -------------------------------------------------------------- sync --
    def sync(self, force_status=False):
        if not self.configured():
            return {"ok": False, "message": "Облако склада не подключено"}
        if replica.HOLD:
            return {"ok": False, "message": replica.HOLD}
        if not self._lock.acquire(blocking=False):
            return {"ok": True, "message": "Синхронизация уже идёт"}
        self.state.update(running=True, last_try=time.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            h = self._http()
            self._ensure_phone_url()
            pulled = pushed = 0
            for _ in range(6):
                pulled += self._pull(h)
                n, rejected, full = self._push(h)
                pushed += n
                if not rejected and not full:
                    break
            due = force_status or time.time() - int(self._meta("scloud_status_at", "0") or 0) > STATUS_EVERY
            self._send_staff(h, force=due)
            if due:
                self.refresh_status(h)
            self.state.update(last_ok=time.strftime("%Y-%m-%d %H:%M:%S"), error="", offline=False, pushed=pushed, pulled=pulled)
            return {"ok": True, "pushed": pushed, "pulled": pulled}
        except StockCloudError as e:
            self.state.update(error=str(e), offline=e.code == -1)
            return {"ok": False, "message": str(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("stock cloud sync failed")
            self.state.update(error=f"Ошибка синхронизации склада: {e}", offline=False)
            return {"ok": False, "message": str(e)}
        finally:
            self.state["running"] = False
            self._lock.release()

    def _local_row(self, t, key):
        with self.db._lock:
            try:
                return replica.read_row(self.db.conn, t, key)
            except Exception:  # noqa: BLE001 — a table of a newer version
                return None

    def _pull(self, h):
        total = 0
        while True:
            since = int(self._meta("scloud_seq", "0") or 0)
            r = h.post("/v1/pull", {"since": since, "limit": 500})
            rows = r.get("rows") or []
            items = []
            for x in rows:
                t = replica.BY_NAME.get(x.get("t"))
                if t is None or t.name not in TABLES:
                    continue
                try:
                    key = json.loads(x["k"])
                except (ValueError, TypeError, KeyError):
                    continue
                row, pbase = x.get("row"), x.get("pbase")
                if t.name in replica.HIDDEN:  # the patient of this computer's copy stays
                    local = self._local_row(t, key)
                    row, pbase = replica.unhide(t.name, row, local), replica.unhide(t.name, pbase, local)
                items.append({"t": t.name, "k": key, "row": row, "ver": x["ver"], "seq": x.get("seq") or 0,
                              "vv": x.get("vv") or replica.vv_of_ver(x["ver"]), "pbase": pbase, "pvv": x.get("pvv"),
                              "origin": x.get("origin") or ""})
            if items:
                replica.apply_versions(self.db, items, self.node, mark="sver")
                total += len(items)
            if rows:
                self._meta_set("scloud_seq", str(rows[-1]["seq"]))
            if not r.get("more") or not rows:
                return total

    def _push(self, h):
        replica.stamp(self.db, self.node)
        q = ",".join("?" * len(TABLES))
        rows = self.db.q(f"SELECT * FROM sync_rows WHERE ver IS NOT NULL AND (sver IS NULL OR sver<>ver) AND tbl IN ({q}) "
                         f"ORDER BY seq LIMIT ?", (*TABLES, PUSH_LIMIT))
        if not rows:
            return 0, False, False
        changes, quiet = [], []
        for r in rows:
            base = json.loads(r["base"]) if r["base"] else None
            if base is None and not r["sver"]:  # deleted here before the cloud ever had it
                quiet.append(r)
                continue
            changes.append({"t": r["tbl"], "k": r["k"], "ver": r["ver"], "base": r["sver"],
                            "vv": json.loads(r["vv"]) if r["vv"] else replica.vv_of_ver(r["ver"]),
                            "row": replica.hide(r["tbl"], base),
                            "pbase": replica.hide(r["tbl"], json.loads(r["pbase"]) if r["pbase"] else None),
                            "pvv": json.loads(r["pvv"]) if r["pvv"] else None, "origin": r["origin"] or ""})
        changes.sort(key=lambda c: replica.ORDER.get(c["t"], 999))
        acc, rejected = set(), False
        if changes:
            res = h.post("/v1/push", {"changes": changes})
            acc = {(t, k) for t, k in res.get("accepted") or []}
            rejected = bool(res.get("rejected"))
        with self.db.tx() as c:
            for ch in changes:
                if (ch["t"], ch["k"]) in acc:
                    c.execute("UPDATE sync_rows SET sver=? WHERE tbl=? AND k=? AND ver=?", (ch["ver"], ch["t"], ch["k"], ch["ver"]))
            for r in quiet:
                c.execute("UPDATE sync_rows SET sver=ver WHERE tbl=? AND k=? AND ver=?", (r["tbl"], r["k"], r["ver"]))
        return len(acc), rejected, len(rows) >= PUSH_LIMIT

    # ------------------------------------------------------------- staff --
    def _staff_list(self, closed=False):
        """Who may sign in on a phone. `closed`: also everyone else of the clinic, with an empty PIN — the cloud never
        deletes anybody for missing from a list (a new laptop may not know everyone yet), so a PIN reset, a dismissal or a
        right taken away is said explicitly."""
        import auth
        try:
            users = self.db.q("SELECT * FROM users ORDER BY login")
            titles = {k: v["title"] for k, v in auth.roles(self.db).items()}
        except Exception:  # noqa: BLE001 — no users table yet
            return []
        out = []
        for u in users:
            perms = set(auth.Auth.effective_perms(u)) & set(PHONE_PERMS)
            if u.get("status") != "active" or not u.get("phone_pin_hash") or not perms & STOCK_RIGHTS:
                if closed and u.get("login"):
                    out.append({"login": u["login"].lower(), "name": "", "role": "", "role_title": "", "perms": [],
                                "pin_hash": None, "pin_at": ""})
                continue
            out.append({"login": (u["login"] or "").lower(), "name": u.get("name") or u["login"], "role": u.get("role") or "",
                        "role_title": titles.get(u.get("role") or "", u.get("position") or ""), "perms": sorted(perms),
                        "pin_hash": u["phone_pin_hash"], "pin_at": u.get("phone_pin_at") or ""})
        return out

    def _send_staff(self, h, force=False):
        staff = self._staff_list(closed=True)
        sig = hashlib.sha256(json.dumps(staff, sort_keys=True).encode()).hexdigest()
        if not force and sig == self._meta("scloud_staff"):
            return False
        h.post("/v1/staff", {"staff": staff})
        self._meta_set("scloud_staff", sig)
        return True


class StockCloudWorker(threading.Thread):
    """Syncs the cloud of the stock every minute while it is connected; `trigger()` asks for a sync right now."""

    def __init__(self, db):
        super().__init__(name="stock-cloud", daemon=True)
        self.cloud = StockCloud(db)
        self._wake = threading.Event()
        self.stop_flag = False

    def trigger(self):
        self._wake.set()

    def run(self):
        time.sleep(float(os.environ.get("DD_STOCK_CLOUD_DELAY", "25")))  # let the window open first
        while not self.stop_flag:
            if self.cloud.configured():
                self.cloud.sync()
            self._wake.wait(INTERVAL)
            self._wake.clear()
