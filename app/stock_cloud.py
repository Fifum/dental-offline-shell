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

3.16: photos of equipment taken on a phone wait in the cloud (a private bucket) until a laptop syncs: it takes each one into
the gallery of its card (the first photo of a card becomes the main one), with who took it and when in the card's history,
sends the new gallery rows up and then tells the cloud to forget the photo.

3.18.2: no code to type. A laptop connects by a secret of its clinic made from the key of the clinic network (every computer
of one clinic has that key, cloud.clinic_key; the secret is an HMAC of it, the key itself never leaves): the cloud finds the
clinic another computer made, or — when the director opens «Телефон» — makes a new one. So the tab shows the QR for the phones
at once, and the other computers of the clinic join the same clinic by themselves (the worker asks every few hours). A computer
that is not in the clinic's network joins by a code a connected one makes («Код для другого компьютера», a day). A demo
program has a demo clinic of its own (a random secret of this computer): the test stock never meets the real one, and the
demo connection ends when the program leaves the demo. The provider's DDS-… codes keep working.

3.18.3: «Подключить мой телефон». The employee signed in at the computer gets a one-time QR of their own (15 minutes, `pair`):
the camera of the phone opens it, the person makes up a PIN of their own there, and the phone is bound to them — later it opens
by that PIN alone. So everyone active with a right of the stock goes to the cloud with their rights, with or without a PIN made
at the computer (the old way: the clinic's QR, «Кто вы?», that PIN). A PIN reset by the director (users.phone_pin_at = the time
of the reset), a dismissal or the rights taken away disconnect the bound phones in the cloud. The staff go up right after a
change (the server wakes the worker), not only with the minute's sync.

3.19: the phones on the clinic's Wi-Fi without the internet (phone_lan.py). With every sync this computer takes the list of the
phones of the clinic (/v1/phones: the hashes of their tokens and of their own PINs) for its own copy, and says where it answers
the phones on the Wi-Fi (the replicated setting of the stock `lan:<node>`: the cloud app shows «Склад через Wi-Fi клиники»).
Photos of materials from the phones come into the photos of the card (material_docs «MDP-<id>»), as those of equipment do.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import secrets
import socket
import threading
import time

import config
import replica

log = logging.getLogger("stock_cloud")

DEFAULT_URL = "https://jdqlcvmcfqtvzuymxhgg.supabase.co/functions/v1/stock"
PHONE_URL = "https://dental-desk-stock.vercel.app"
TABLES = ("materials", "suppliers", "stock_locations", "stock_docs", "stock_moves", "stock_lots", "stock_settings",
          "equipment", "equipment_events", "equipment_docs", "stock_requests", "stock_approvals", "material_docs")
PHONE_PERMS = ("stock_view", "stock_ops", "stock_edit", "stock_approve", "equipment", "accounting")
STOCK_RIGHTS = {"stock_view", "stock_ops", "stock_edit", "stock_approve", "equipment"}
INTERVAL = 60          # seconds between syncs
STATUS_EVERY = 600     # the clinic's status (phone code, devices) and the staff at least this often
PUSH_LIMIT = 400
TIMEOUT = 25
PHOTO_BATCH = 10       # photos of equipment taken from the cloud in one sync
AUTO_EVERY = 6 * 3600  # 3.18.2: a computer not connected yet asks this often whether its clinic has a cloud of the stock
SECRET_INFO = b"dd-stock-cloud-v1"


def photo_note(p: dict) -> str:
    """The line of the card's history for a photo from a phone: who took it (and the position) and when."""
    who = (p.get("taken_name") or p.get("taken_by") or "сотрудник").strip()
    role = (p.get("taken_role") or "").strip()
    at = str(p.get("taken_at") or "")
    when = f"{at[8:10]}.{at[5:7]}.{at[:4]} {at[11:16]}".strip() if len(at) >= 10 and at[4] == "-" else ""
    return f"Фото с телефона: снял(а) {who}" + (f" ({role})" if role else "") + (f", {when}" if when else "")


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
    """Where the connection is kept: the settings of the program (the token and the secrets encrypted with DPAPI).
    3.18.2: `demo` — the connection was made in the demo (a demo clinic); `off` — the director disconnected this computer, it
    does not connect by itself again; `demo_key` / `own_key` — this computer's own secret for its demo clinic / when it has no
    key of a clinic network."""

    SECRET = ("token", "demo_key", "own_key")

    def load(self) -> dict:
        s = config.load_settings()
        return {"url": s.get("stock_cloud_url") or "", "token": config.unprotect(s.get("stock_cloud_token") or ""),
                "device": s.get("stock_cloud_device") or "", "tenant": s.get("stock_cloud_tenant") or "",
                "name": s.get("stock_cloud_name") or "", "last_tenant": s.get("stock_cloud_last_tenant") or "",
                "demo": bool(s.get("stock_cloud_demo")), "off": bool(s.get("stock_cloud_off")),
                "demo_key": config.unprotect(s.get("stock_cloud_demo_key") or ""),
                "own_key": config.unprotect(s.get("stock_cloud_own_key") or "")}

    def save(self, d: dict):
        out = {}
        for k, v in d.items():
            out["stock_cloud_" + k] = config.protect(v) if k in self.SECRET and v else v
        config.save_settings(out)


def clinic_secret(key: bytes) -> str:
    """What the cloud of the stock knows a clinic by: the same on every computer with the key of the clinic network, and
    telling nothing about the key (the key also opens the clinic's main cloud, which the cloud of the stock must never see)."""
    return base64.urlsafe_b64encode(hmac.new(key, SECRET_INFO, hashlib.sha256).digest()).decode().rstrip("=")


def _tz() -> int:
    off = datetime.datetime.now().astimezone().utcoffset()
    return int(off.total_seconds() // 60) if off is not None else 180


class StockCloud:
    def __init__(self, db, store=None, node=None, transport=None, files=None, stock=None, clinic_key=None):
        self.db = db
        self.store = store or Store()
        self.node = node or config.node_id()
        self.transport = transport or Http
        self._files, self._stock = files, stock  # 3.16: the photos of equipment from the phones (the program's own objects)
        self._clinic_key = clinic_key            # 3.18.2: the key of the clinic network (tests give their own)
        replica.install(db)
        self._lock = threading.Lock()
        self.next_auto = 0.0                     # when the worker asks again whether the clinic has a cloud
        self.state = {"last_ok": None, "last_try": None, "error": "", "offline": False, "running": False,
                      "pushed": 0, "pulled": 0, "photos": 0, "photos_waiting": 0}

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

    # ---------------------------------------------- 3.18.2: the clinic's secret and the demo --
    @staticmethod
    def demo_mode() -> bool:
        """The program shows the demo stock (DD_STOCK_CLOUD_DEMO: the tests' laptops count as real ones)."""
        return bool(config.load_settings().get("demo")) and not os.environ.get("DD_STOCK_CLOUD_DEMO")

    def _own(self, name) -> str:
        k = self.store.load().get(name) or ""
        if not k:
            k = secrets.token_urlsafe(32)
            self.store.save({name: k})
        return k

    def _network_key(self):
        if self._clinic_key is not None:
            return self._clinic_key() if callable(self._clinic_key) else self._clinic_key
        try:
            import cloud
            return cloud.clinic_key()
        except Exception:  # noqa: BLE001 — no clinic network on this computer
            return None

    def secrets_for(self, demo: bool) -> list:
        """The secrets this computer knows its clinic of the cloud by: the one of the clinic network (or, without a network,
        a random one of this computer); in the demo — a random one of this computer, so a demo clinic is never a real one."""
        if demo:
            return [self._own("demo_key")]
        key = self._network_key()
        return [clinic_secret(key)] if key else [self._own("own_key")]

    @staticmethod
    def _url() -> str:
        return (os.environ.get("DD_STOCK_CLOUD_URL") or DEFAULT_URL).rstrip("/")

    def _hello(self, demo: bool, **body) -> dict:
        s = config.load_settings()
        return {"name": socket.gethostname(), "version": config.VERSION, "tz": _tz(), "demo": demo,
                "keys": self.secrets_for(demo), "clinic": s.get("clinic_name") or "", **body}

    def _mode_ok(self) -> bool:
        """The demo stock and the real one never meet: a connection made in the demo ends when the program leaves it (the
        real stock connects then by itself), and a real connection is not used while the program shows the demo."""
        s = self.store.load()
        if not s["token"] or bool(s.get("demo")) == self.demo_mode():
            return True
        log.info("stock cloud: the %s connection ends — the program is %s the demo now",
                 "demo" if s.get("demo") else "real", "out of" if s.get("demo") else "in")
        self.leave(user=False)
        return False

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
        self._mode_ok()
        s = self.store.load()
        st = json.loads(self._meta("scloud_status") or "{}")
        devs = st.get("devices") or []
        on = self.configured()
        return {**self.state, "configured": on, "device": s["device"], "tenant": s["tenant"],
                "name": st.get("name") or s["name"], "phone_code": st.get("phone_code") or "", "phone_url": self.phone_url(),
                "laptops": sum(1 for d in devs if d.get("kind") == "laptop"),
                "phones": sum(1 for d in devs if d.get("kind") == "phone"),
                "staff": len(self._staff_list()), "pending": self.pending() if on else 0,
                "demo": bool(s.get("demo")) if on else self.demo_mode(), "off": bool(s.get("off")) and not on,
                "computer": socket.gethostname()}

    def refresh_status(self, h=None):
        h = h or self._http()
        r = h.post("/v1/status", {"version": config.VERSION, "tz": _tz(),
                                  "clinic": config.load_settings().get("clinic_name") or "",
                                  "keys": self.secrets_for(bool(self.store.load().get("demo")))})
        self._meta_set("scloud_status", json.dumps(r, ensure_ascii=False))
        self._meta_set("scloud_status_at", str(int(time.time())))
        return r

    def phone(self):
        """The clinic code for phones and a QR that opens the phone app with it: an https link, so the ordinary camera of a
        phone opens the stock of the clinic, where the employee enters the personal PIN."""
        if not self._mode_ok() or not self.configured():
            raise StockCloudError("Сначала подключите облако склада")
        st = json.loads(self._meta("scloud_status") or "{}")
        if not st.get("phone_code"):
            st = self.refresh_status()
        code = st.get("phone_code") or ""
        url = f"{self.phone_url()}/j#{code}"
        import crm
        return {"code": code, "url": url, "app": self.phone_url(), "qr": crm.qr_data_uri(url), "name": st.get("name") or ""}

    # ----------------------------------------------------------- connect --
    def _connected(self, r: dict, url: str, demo: bool):
        prev = self.store.load()["last_tenant"]
        if prev != r["tenant"]:  # another clinic's cloud (or the first one): it has nothing of ours yet
            with self.db.tx() as c:
                c.execute("UPDATE sync_rows SET sver=NULL")
                c.execute("DELETE FROM sync_state WHERE k LIKE 'scloud_%'")
        self.store.save({"url": url, "token": r["token"], "device": r["device"], "tenant": r["tenant"],
                         "name": r.get("name") or "", "last_tenant": r["tenant"], "demo": bool(demo), "off": False})
        if r.get("phone_code"):  # the QR at once, before the first sync
            st = json.loads(self._meta("scloud_status") or "{}")
            st.update(name=r.get("name") or "", phone_code=r["phone_code"], demo=bool(demo))
            self._meta_set("scloud_status", json.dumps(st, ensure_ascii=False))
        self._meta_set("scloud_status_at", "0")
        self.state.update(error="", offline=False)

    def connect(self, create=True):
        """3.18.2: connects without a code, by the secret of the clinic: to the clinic of the cloud another computer of the
        clinic made, or — `create` — to a new one. {"ok": False, "none": True}: the clinic has no cloud yet."""
        if self.configured() and self._mode_ok():
            return {"ok": True, "already": True}
        demo, url = self.demo_mode(), self._url()
        r = self.transport(url, "").post("/v1/register", self._hello(demo, create=bool(create)))
        if not r.get("tenant"):
            return {"ok": False, "none": True}
        self._connected(r, url, demo)
        log.info("stock cloud: %s %s clinic %s as %s", "made" if r.get("created") else "joined", "demo" if demo else "the",
                 r["tenant"], r["device"])
        return {"ok": True, "created": bool(r.get("created")), "name": r.get("name") or "", "demo": demo}

    def auto(self):
        """The worker: a computer whose clinic another computer has connected joins it by itself. Never makes a clinic,
        never in the demo, never after the director disconnected this computer."""
        if self.configured() or self.demo_mode() or self.store.load().get("off") or replica.HOLD:
            return None
        try:
            r = self.connect(create=False)
        except StockCloudError as e:
            log.info("stock cloud auto: %s", e)
            return None
        return r if r.get("ok") else None

    def invite(self):
        """A code for another computer of the clinic that is not in its network (typed there in «Телефон», works a day)."""
        if not self._mode_ok() or not self.configured():
            raise StockCloudError("Сначала подключите облако склада")
        if self.store.load().get("demo"):
            raise StockCloudError("В демо-режиме другие компьютеры не подключаются: у каждого свой демо-склад.")
        return self._http().post("/v1/invite")

    def join(self, code, name="", switch=False):
        """By a code: the provider's DDS-… or one a connected computer of the clinic made. `switch` — this computer is
        connected already (a cloud it made itself before it knew of the clinic's): it goes over to the clinic of the code."""
        if self.demo_mode():
            raise StockCloudError("Сначала выключите демо-режим: иначе тестовый склад попадёт в облако и на телефоны.")
        if self.configured() and not switch:
            raise StockCloudError("Этот компьютер уже подключён к облаку склада. Сначала отключите его.")
        code = "".join(str(code or "").split()).upper()
        if not code:
            raise StockCloudError("Введите код подключения склада (DDS-…)")
        url = self._url()
        r = self.transport(url, "").post("/v1/join", self._hello(False, code=code, name=name or socket.gethostname()))
        old = self.store.load()
        if old["token"]:  # the old connection of this computer ends only now, when the code has worked
            try:
                self.transport(old["url"] or url, old["token"]).post("/v1/leave")
            except StockCloudError as e:
                log.info("switch, leave: %s", e)
        self._connected(r, url, False)
        log.info("joined the stock cloud %s as %s", r["tenant"], r["device"])
        return {"ok": True, "name": r.get("name") or ""}

    def leave(self, user=True):
        """`user` — the director disconnected this computer: it does not connect by itself again (until «Подключить»)."""
        s = self.store.load()
        if s["token"]:
            try:
                self._http().post("/v1/leave")
            except StockCloudError as e:
                log.info("leave: %s", e)
        self.store.save({"url": "", "token": "", "device": "", "tenant": "", "name": "", "demo": False, "off": bool(user)})
        self.state.update(error="", last_ok=None)
        if not user:
            self.next_auto = 0.0
        return True

    # -------------------------------------------------------------- sync --
    def sync(self, force_status=False):
        if not self._mode_ok() or not self.configured():
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
            photos = self._photos(h)
            self._phones(h)
            self._publish_lan()
            due = force_status or time.time() - int(self._meta("scloud_status_at", "0") or 0) > STATUS_EVERY
            self._send_staff(h, force=due)
            if due:
                self.refresh_status(h)
            self.state.update(last_ok=time.strftime("%Y-%m-%d %H:%M:%S"), error="", offline=False, pushed=pushed, pulled=pulled)
            if photos:
                self.state["photos"] = int(self.state.get("photos") or 0) + photos
            return {"ok": True, "pushed": pushed, "pulled": pulled, "photos": photos}
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

    # ------------------------------------------------------------ photos --
    def _photo_tools(self):
        if self._files is None:
            from files import Files
            self._files = Files(self.db)
        if self._stock is None:
            from stock import Stock
            self._stock = Stock(self.db)
        return self._files, self._stock

    def _photos(self, h) -> int:
        """3.16: the photos of equipment the phones sent: into the galleries of the cards, then the cloud forgets them. The rows
        of the gallery go up before the cloud is told, so a laptop syncing next sees the photo is in the card already."""
        try:
            r = h.post("/v1/photos", {"limit": PHOTO_BATCH, "materials": True})  # 3.19: of materials too
        except StockCloudError as e:
            if e.code == -1:
                raise
            log.info("photos: %s", e)  # a cloud without photos yet: the stock itself is synced all the same
            return 0
        done, got = [], 0
        for p in r.get("photos") or []:
            try:
                n = self._take_photo(h, p)
            except StockCloudError as e:
                if e.code == -1:
                    raise
                log.info("photo %s: %s", p.get("id"), e)
                continue
            except Exception:  # noqa: BLE001 — one bad photo does not stop the others
                log.exception("photo %s", p.get("id"))
                continue
            if n is not None:
                done.append(p["id"])
                got += n
        if done:
            if got:
                self._push(h)
            h.post("/v1/photo_done", {"ids": done})
        self.state["photos_waiting"] = max(0, int(r.get("waiting") or 0) - len(done))
        return got

    def _take_photo(self, h, p):
        """1 — the photo is now in the card; 0 — nothing to add (in the card already, or the piece was disposed of, or the
        file is not a picture), the cloud may forget it; None — the piece is not on this computer yet: later."""
        files, stock = self._photo_tools()
        if p.get("material_id"):
            return self._take_material_photo(h, p, files, stock)
        did = "EDP-" + str(p.get("id") or "")[:80]  # the same photo is the same row of the gallery on every laptop
        if self.db.one("SELECT 1 AS x FROM equipment_docs WHERE id=?", (did,)):
            return 0
        e = self.db.one("SELECT id, status, inv_number FROM equipment WHERE id=?", (str(p.get("equipment_id") or ""),))
        if not e:
            return None
        if e["status"] == "written_off":
            log.info("photo %s of a disposed piece %s is dropped", p.get("id"), e["id"])
            return 0
        data = base64.b64decode(h.post("/v1/photo", {"id": p["id"]}).get("data") or "")
        who = (p.get("taken_name") or p.get("taken_by") or "").strip()
        try:
            ph = files.add_stock_photo(f"Фото с телефона {e['inv_number'] or ''}".strip() + ".jpg", data, who)
        except ValueError as er:
            log.warning("photo %s is not a picture: %s", p.get("id"), er)
            return 0
        stock.equipment_photo_add(e["id"], ph["id"], "Фото с телефона", who, doc_id=did, note=photo_note(p))
        return 1

    def _take_material_photo(self, h, p, files, stock):
        """3.19: a photo of a material → the photos of its card (the first one becomes the main photo)."""
        did = "MDP-" + str(p.get("id") or "")[:80]
        if self.db.one("SELECT 1 AS x FROM material_docs WHERE id=?", (did,)):
            return 0
        m = self.db.one("SELECT id, active, number, code FROM materials WHERE id=?", (str(p.get("material_id") or ""),))
        if not m:
            return None
        if not int(m["active"] if m["active"] is not None else 1):
            log.info("photo %s of a material removed from the list %s is dropped", p.get("id"), m["id"])
            return 0
        data = base64.b64decode(h.post("/v1/photo", {"id": p["id"]}).get("data") or "")
        who = (p.get("taken_name") or p.get("taken_by") or "").strip()
        try:
            ph = files.add_stock_photo(f"Фото с телефона {m['number'] or m['code'] or ''}".strip() + ".jpg", data, who)
        except ValueError as er:
            log.warning("photo %s is not a picture: %s", p.get("id"), er)
            return 0
        stock.material_doc_add(m["id"], "photo", photo_note(p), ph["id"], who, doc_id=did)
        return 1

    # ---------------------------------------- 3.19: the phones on the clinic's Wi-Fi --
    def _phones(self, h):
        """The phones of the clinic for this computer's own copy (a phone on the Wi-Fi signs in here without the internet)."""
        try:
            r = h.post("/v1/phones")
        except StockCloudError as e:
            if e.code == -1:
                raise
            log.info("phones: %s", e)  # a cloud before 3.19
            return 0
        import phone_lan
        return phone_lan.store_devices(self.db, r.get("phones") or [])

    def _publish_lan(self):
        """Where this computer answers the phones on the Wi-Fi: the replicated setting `lan:<node>` (changed only when the
        address or the mode changes, so it does not make a new version every minute)."""
        try:
            import phone_lan
            info = phone_lan.lan_info()
        except Exception as e:  # noqa: BLE001
            log.info("lan info: %s", e)
            return False
        if not info.get("http"):
            return False
        key = "lan:" + self.node
        v = {"name": info["name"], "http": info["http"], "https": info["https"]}
        try:
            old = self.db.one("SELECT v FROM stock_settings WHERE k=?", (key,))
            try:
                same = old and {k: (json.loads(old["v"]) or {}).get(k) for k in v} == v
            except (ValueError, TypeError, AttributeError):
                same = False
            if same:
                return False
            with self.db.tx() as c:
                c.execute("INSERT OR REPLACE INTO stock_settings(k, v, updated_at) VALUES(?, ?, ?)",
                          (key, json.dumps({**v, "at": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False),
                           time.strftime("%Y-%m-%d %H:%M:%S")))
            return True
        except Exception as e:  # noqa: BLE001 — no stock tables yet
            log.info("lan setting: %s", e)
            return False

    # ------------------------------------------------- 3.18.3: my phone --
    def pair(self, login):
        """«Подключить мой телефон»: a one-time QR of this employee (an https link the ordinary camera opens; 15 minutes, a new
        one replaces it). The staff go up first, so the cloud knows the person's rights right now."""
        if not self._mode_ok() or not self.configured():
            raise StockCloudError("Сначала подключите облако склада")
        login = str(login or "").lower()
        me = next((x for x in self._staff_list() if x["login"] == login), None)
        if not me:
            raise StockCloudError("У вашей должности нет прав склада — телефону нечего показать")
        h = self._http()
        self._send_staff(h, force=True)
        r = h.post("/v1/pair", {"login": login})
        url = f"{self.phone_url()}/j#{r['token']}"
        import crm
        return {"url": url, "qr": crm.qr_data_uri(url), "minutes": int(r.get("minutes") or 15), "name": me["name"],
                "app": self.phone_url(), "demo": bool(self.store.load().get("demo"))}

    def phones_of(self, login) -> int:
        """How many phones are bound to this employee (from the last status of the cloud)."""
        st = json.loads(self._meta("scloud_status") or "{}")
        return sum(1 for d in st.get("devices") or [] if d.get("kind") == "phone" and (d.get("login") or "") == str(login or "").lower())

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
            if u.get("status") != "active" or not perms & STOCK_RIGHTS:
                if closed and u.get("login"):
                    out.append({"login": u["login"].lower(), "name": "", "role": "", "role_title": "", "perms": [],
                                "pin_hash": None, "pin_at": ""})
                continue
            out.append({"login": (u["login"] or "").lower(), "name": u.get("name") or u["login"], "role": u.get("role") or "",
                        "role_title": titles.get(u.get("role") or "", u.get("position") or ""), "perms": sorted(perms),
                        "pin_hash": u.get("phone_pin_hash") or None, "pin_at": u.get("phone_pin_at") or ""})
        return out

    def _send_staff(self, h, force=False):
        staff = self._staff_list(closed=True)
        sig = hashlib.sha256(json.dumps(staff, sort_keys=True).encode()).hexdigest()
        if not force and sig == self._meta("scloud_staff"):
            return False
        h.post("/v1/staff", {"staff": staff, "v": 2})  # 3.18.3: the whole list (with or without a PIN made here)
        self._meta_set("scloud_staff", sig)
        return True


class StockCloudWorker(threading.Thread):
    """Syncs the cloud of the stock every minute while it is connected; `trigger()` asks for a sync right now."""

    def __init__(self, db, files=None, stock=None):
        super().__init__(name="stock-cloud", daemon=True)
        self.cloud = StockCloud(db, files=files, stock=stock)
        self._wake = threading.Event()
        self.stop_flag = False

    def trigger(self):
        self._wake.set()

    def step(self):
        """One turn: sync; a computer not connected yet asks now and then whether its clinic has a cloud (3.18.2)."""
        c = self.cloud
        if not c.configured() and time.time() >= c.next_auto:
            c.next_auto = time.time() + AUTO_EVERY
            c.auto()
        if c.configured():
            c.sync()

    def run(self):
        time.sleep(float(os.environ.get("DD_STOCK_CLOUD_DELAY", "25")))  # let the window open first
        while not self.stop_flag:
            try:
                self.step()
            except Exception:  # noqa: BLE001 — the worker never stops
                log.exception("stock cloud worker")
            self._wake.wait(INTERVAL)
            self._wake.clear()
