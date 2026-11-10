"""The clinic's computers ↔ cloud: connection, end-to-end encryption and the sync loop.

Connection: the provider creates the clinic on the cloud server and gives a connection code. The first computer
enters the server address and that code; it makes a random clinic key (AES-256) and shows a «code for other
computers» (address + code + key in one line). Every other laptop of the clinic is connected with that line.
The key never leaves the clinic's computers: rows and files go to the server encrypted (AES-GCM) under row
names that are HMACs, so the server cannot read patient data or even table names. Token, key and code are kept
encrypted with Windows DPAPI.

Sync (every few minutes while online, and on demand): pull what other computers changed → merge (replica.py) →
push our changes. The cloud refuses a row changed meanwhile by someone else; then we pull and merge again.
"""
from __future__ import annotations

import base64
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

log = logging.getLogger("cloud")
CODE_PREFIX = "DD1-"
TIMEOUT = 20


class CloudError(Exception):
    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ crypto --
class Keys:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("Неверный ключ клиники")
        self.key = key
        self.enc = hashlib.sha256(b"dd-enc\0" + key).digest()
        self.mac = hashlib.sha256(b"dd-mac\0" + key).digest()

    def check(self) -> str:
        return hmac.new(self.mac, b"dd-key-check", hashlib.sha256).hexdigest()

    def clinic_id(self) -> str:
        """Public name of the clinic in the network: computers with the same key see the same id."""
        return hmac.new(self.mac, b"dd-clinic-id", hashlib.sha256).hexdigest()[:16]

    def row_key(self, table, k) -> str:
        return hmac.new(self.mac, f"{table}\x1f{k}".encode(), hashlib.sha256).hexdigest()

    def blob_id(self, sha256_hex) -> str:
        return hmac.new(self.mac, b"blob\x1f" + sha256_hex.encode(), hashlib.sha256).hexdigest()

    def seal(self, data: bytes, aad: str) -> bytes:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(self.enc).encrypt(nonce, data, aad.encode())

    def open(self, blob: bytes, aad: str) -> bytes:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        try:
            return AESGCM(self.enc).decrypt(blob[:12], blob[12:], aad.encode())
        except InvalidTag:
            raise CloudError("Не удалось расшифровать данные: ключ клиники не подходит") from None

    def seal_row(self, obj, aad) -> str:
        return base64.b64encode(self.seal(json.dumps(obj, ensure_ascii=False).encode("utf-8"), aad)).decode()

    def open_row(self, s, aad):
        return json.loads(self.open(base64.b64decode(s), aad).decode("utf-8"))


def make_code(url, invite, key: bytes) -> str:
    raw = json.dumps({"u": url, "i": invite, "k": base64.b64encode(key).decode()}, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_code(code: str):
    """Full code «DD1-…» → (url, invite, key); a bare invite → (None, invite, None)."""
    code = "".join(str(code or "").split())
    if code.upper().startswith(CODE_PREFIX):
        body = code[len(CODE_PREFIX):]
        try:
            j = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            return j["u"], j["i"], base64.b64decode(j["k"])
        except (ValueError, KeyError, TypeError):
            raise CloudError("Код подключения повреждён — скопируйте его целиком") from None
    return None, code, None


def norm_url(url: str) -> str:
    url = str(url or "").strip().rstrip("/")
    if not url:
        raise CloudError("Укажите адрес облачного сервера")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = url.split("/")[2].split(":")[0]
    if url.startswith("http://") and host not in ("127.0.0.1", "localhost") and not os.environ.get("DD_CLOUD_INSECURE"):
        raise CloudError("Облачный сервер должен работать по https://")
    return url


# ------------------------------------------------------------------ client --
def clinic_key() -> bytes | None:
    """3.0: one clinic key for the clinic network and the cloud (before 3.0 only the cloud had one)."""
    s = config.load_settings()
    raw = config.unprotect(s.get("clinic_key") or "") or config.unprotect(s.get("cloud_key") or "")
    try:
        key = base64.b64decode(raw) if raw else None
    except ValueError:
        return None
    return key if key and len(key) == 32 else None


def set_clinic_key(key: bytes, name="", member=False):
    config.save_settings({"clinic_key": config.protect(base64.b64encode(key).decode()), "clinic_id": Keys(key).clinic_id(),
                          "clinic_name": name or config.load_settings().get("clinic_name") or "",
                          **({"clinic_member": True} if member else {})})


def _settings():
    s = config.load_settings()
    ck = clinic_key()
    return {"url": s.get("cloud_url") or "", "token": config.unprotect(s.get("cloud_token") or ""),
            "key": base64.b64encode(ck).decode() if ck else "", "invite": config.unprotect(s.get("cloud_invite") or ""),
            "device": s.get("cloud_device") or "", "name": s.get("cloud_name") or "", "tenant": s.get("cloud_tenant") or "",
            "interval": max(1, int(s.get("cloud_interval_min") or 3))}


def configured() -> bool:
    s = _settings()
    return bool(s["url"] and s["token"] and s["key"])


class Http:
    def __init__(self, url, token=""):
        import requests
        self.url, self.token, self.s = url.rstrip("/"), token, requests.Session()

    def _check(self, r):
        if r.status_code >= 400:
            try:
                msg = r.json().get("error")
            except ValueError:
                msg = ""
            raise CloudError(msg or f"Облачный сервер ответил ошибкой {r.status_code}", r.status_code)
        return r

    def _h(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def post(self, path, body=None):
        import requests
        try:
            r = self.s.post(self.url + path, json=body or {}, headers=self._h(), timeout=TIMEOUT)
        except requests.RequestException as e:
            raise CloudError("Нет связи с облачным сервером", -1) from e
        return self._check(r).json()

    def put_blob(self, bid, data):
        import requests
        try:
            return self._check(self.s.put(f"{self.url}/v1/blob/{bid}", data=data, headers=self._h(), timeout=120))
        except requests.RequestException as e:
            raise CloudError("Нет связи с облачным сервером", -1) from e

    def get_blob(self, bid):
        import requests
        try:
            return self._check(self.s.get(f"{self.url}/v1/blob/{bid}", headers=self._h(), timeout=120)).content
        except requests.RequestException as e:
            raise CloudError("Нет связи с облачным сервером", -1) from e


class Cloud:
    def __init__(self, db):
        self.db = db
        replica.install(db)
        self._lock = threading.Lock()
        self.state = {"last_ok": None, "last_try": None, "error": "", "offline": False, "running": False,
                      "pushed": 0, "pulled": 0, "conflicts_new": 0}

    # ------------------------------------------------------------ helpers --
    def _meta(self, k, default=None):
        r = self.db.one("SELECT v FROM sync_state WHERE k=?", (k,))
        return r["v"] if r else default

    def _meta_set(self, k, v):
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO sync_state(k, v) VALUES(?, ?)", (k, v))

    @staticmethod
    def _ver(device, at):
        """Version of a row = when it was changed here (the later change wins a clash) + who + a random tail."""
        return f"{int(at):015d}.{device}.{secrets.token_hex(3)}"

    def status(self):
        s = _settings()
        sub = self._meta("cloud_sub")
        out = {**self.state, "configured": configured(), "url": s["url"], "name": s["name"], "device": s["device"],
               "pending": replica.pending(self.db), "subscription": json.loads(sub) if sub else None,
               "conflicts": self.db.one("SELECT COUNT(*) AS n FROM sync_conflicts WHERE seen=0")["n"],
               "interval": s["interval"], "computer": socket.gethostname()}
        devs = self._meta("cloud_devices")
        out["devices"] = [d for d in (json.loads(devs) if devs else []) if not d.get("revoked")]
        return out

    # ------------------------------------------------------------ connect --
    def join(self, url, code, name=""):
        if config.load_settings().get("demo") and not os.environ.get("DD_CLOUD_DEMO"):
            raise CloudError("Сначала выключите демо-режим: иначе тестовые пациенты попадут на все компьютеры клиники.")
        if configured():
            raise CloudError("Этот компьютер уже подключён к облаку. Сначала отключите его.")
        c_url, invite, key = parse_code(code)
        own = clinic_key()
        if key is not None and own and key != own:
            raise CloudError("Этот код — от облака другой клиники: его ключ не совпадает с ключом этой клиники.")
        key = key or own
        url = norm_url(c_url or url)
        h = Http(url)
        r = h.post("/v1/join", {"invite": invite, "name": name or socket.gethostname(), "version": config.VERSION})
        h.token = r["token"]
        try:
            if key is None:
                if r.get("key_check"):
                    raise CloudError("К облаку клиники уже подключён другой компьютер. Введите полный код подключения с него: "
                                     "Настройки → «Облако и подписка» → «Код для других компьютеров».")
                key = secrets.token_bytes(32)
                h.post("/v1/key_check", {"check": Keys(key).check()})
            elif r.get("key_check") and r["key_check"] != Keys(key).check():
                raise CloudError("Ключ в коде не подходит к облаку этой клиники")
            elif not r.get("key_check"):
                h.post("/v1/key_check", {"check": Keys(key).check()})
        except Exception:
            try:
                h.post("/v1/leave")
            except CloudError:
                pass
            raise
        prev = config.load_settings().get("cloud_last_tenant")
        if prev and prev != r["tenant"]:
            self.reset()
        set_clinic_key(key)
        config.save_settings({"cloud_url": url, "cloud_token": config.protect(r["token"]), "cloud_key": "",
            "cloud_invite": config.protect(invite), "cloud_device": r["device"],
            "cloud_name": r["name"], "cloud_tenant": r["tenant"], "cloud_last_tenant": r["tenant"]})
        self._meta_set("cloud_sub", json.dumps(r.get("subscription") or {}, ensure_ascii=False))
        log.info("joined cloud tenant %s as device %s", r["tenant"], r["device"])
        return {"ok": True, "name": r["name"], "subscription": r.get("subscription")}

    def code_for_others(self):
        s = _settings()
        if not configured():
            raise CloudError("Компьютер не подключён к облаку")
        return make_code(s["url"], s["invite"], base64.b64decode(s["key"]))

    def leave(self):
        s = _settings()
        if s["token"]:
            try:
                Http(s["url"], s["token"]).post("/v1/leave")
            except CloudError as e:
                log.info("leave: %s", e)
        config.save_settings({"cloud_url": "", "cloud_token": "", "cloud_invite": "", "cloud_device": "",  # the clinic key stays
                              "cloud_name": "", "cloud_tenant": ""})
        self.state.update(error="", last_ok=None)
        return True

    def revoke_device(self, device_id):
        s = _settings()
        if device_id == s["device"]:
            raise CloudError("Чтобы отключить этот компьютер, нажмите «Отключить от облака»")
        Http(s["url"], s["token"]).post("/v1/revoke", {"device": device_id})
        self.refresh_status()
        return True

    def reset(self):
        """Another cloud: it has nothing of ours yet — send every version again (versions themselves stay)."""
        with self.db.tx() as c:
            c.execute("UPDATE sync_rows SET cver=NULL")
            c.execute("DELETE FROM sync_state WHERE k LIKE 'cloud_%'")
        replica.install(self.db)

    def refresh_status(self):
        s = _settings()
        r = Http(s["url"], s["token"]).post("/v1/status", {"version": config.VERSION})
        self._meta_set("cloud_sub", json.dumps(r["subscription"], ensure_ascii=False))
        self._meta_set("cloud_devices", json.dumps(r.get("devices") or [], ensure_ascii=False))
        return r

    # --------------------------------------------------------------- sync --
    def sync(self):
        if not configured():
            return {"ok": False, "message": "Облако не подключено"}
        if not self._lock.acquire(blocking=False):
            return {"ok": True, "message": "Синхронизация уже идёт"}
        self.state.update(running=True, last_try=time.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            s = _settings()
            keys = Keys(base64.b64decode(s["key"]))
            h = Http(s["url"], s["token"])
            pulled = pushed = 0
            conflicts0 = self.db.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"]
            for _ in range(6):
                pulled += self._pull(h, keys)
                n, rejected, full = self._push(h, keys, s["device"])
                pushed += n
                if not rejected and not full:
                    break
            self._fetch_files(h, keys)
            try:
                self.refresh_status()
            except CloudError:
                pass
            new_conf = self.db.one("SELECT COUNT(*) AS n FROM sync_conflicts")["n"] - conflicts0
            self.state.update(last_ok=time.strftime("%Y-%m-%d %H:%M:%S"), error="", offline=False, pushed=pushed,
                              pulled=pulled, conflicts_new=new_conf)
            return {"ok": True, "pushed": pushed, "pulled": pulled, "conflicts": new_conf}
        except CloudError as e:
            self.state.update(error=str(e), offline=e.code == -1)
            if e.code == 402:
                try:
                    self.refresh_status()
                except CloudError:
                    pass
            return {"ok": False, "message": str(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("cloud sync failed")
            self.state.update(error=f"Ошибка синхронизации: {e}", offline=False)
            return {"ok": False, "message": str(e)}
        finally:
            self.state["running"] = False
            self._lock.release()

    def _pull(self, h, keys):
        total = 0
        while True:
            since = int(self._meta("cloud_seq", "0"))
            r = h.post("/v1/pull", {"since": since, "limit": 500})
            self._meta_set("cloud_sub", json.dumps(r.get("subscription") or {}, ensure_ascii=False))
            items = []
            for row in r["rows"]:
                try:
                    obj = keys.open_row(row["data"], row["key"])
                except CloudError:
                    log.warning("row %s: cannot decrypt", row["key"][:12])
                    continue
                # 3.0: the same versions as between computers in the clinic network (vv, ancestor, who made the row)
                items.append({"t": obj["t"], "k": obj["k"], "row": obj["row"], "ver": row["ver"], "seq": row["seq"],
                              "vv": obj.get("vv") or replica.vv_of_ver(row["ver"]), "pbase": obj.get("pbase"),
                              "origin": obj.get("origin") or ""})
            if items:
                replica.apply_versions(self.db, items, config.node_id(), cloud=True)
                total += len(items)
            if r["rows"]:
                self._meta_set("cloud_seq", str(r["rows"][-1]["seq"]))
            if not r.get("more"):
                return total

    def _push(self, h, keys, device):
        replica.stamp(self.db, config.node_id())
        items = replica.cloud_outgoing(self.db, limit=400)
        if not items:
            return 0, False, False
        self._upload_files(h, keys, [i for i in items if i["t"] == "patient_files" and i["row"]])
        changes, byk = [], {}
        for it in items:
            rk = keys.row_key(it["t"], it["ks"])
            byk[rk] = it
            changes.append({"key": rk, "ver": it["ver"], "base": it["base"],
                            "data": keys.seal_row({"t": it["t"], "k": it["k"], "row": it["row"], "vv": it["vv"],
                                                   "pbase": it["pbase"], "origin": it["origin"]}, rk)})
        r = h.post("/v1/push", {"changes": changes})
        for rk in r["accepted"]:
            replica.cloud_pushed(self.db, byk[rk])
        return len(r["accepted"]), bool(r["rejected"]), len(items) >= 400

    # ------------------------------------------------- X-rays and files --
    @staticmethod
    def _file_path(row):
        import files
        return files._pdir(row["patient_id"]) / (row["id"] + (row.get("ext") or ""))

    def _upload_files(self, h, keys, items):
        want = {}
        for it in items:
            p = self._file_path(it["row"])
            if it["row"].get("sha256") and p.exists():
                want[keys.blob_id(it["row"]["sha256"])] = p
        if not want:
            return
        have = set(h.post("/v1/blob_has", {"ids": list(want)})["have"])
        for bid, p in want.items():
            if bid not in have:
                h.put_blob(bid, keys.seal(p.read_bytes(), bid))

    def _fetch_files(self, h, keys):
        """Download files of patient cards that other computers added (rows arrived, files not yet here)."""
        try:
            rows = self.db.q("SELECT * FROM patient_files WHERE COALESCE(deleted,0)=0 AND sha256 IS NOT NULL")
        except Exception:  # noqa: BLE001
            return
        import files
        for r in rows:
            p = self._file_path(r)
            if p.exists():
                continue
            bid = keys.blob_id(r["sha256"])
            try:
                data = keys.open(h.get_blob(bid), bid)
            except CloudError as e:
                if e.code == 404:
                    continue  # the other computer has not sent it yet
                raise
            if hashlib.sha256(data).hexdigest() != r["sha256"]:
                log.warning("file %s: checksum mismatch", r["id"])
                continue
            p.write_bytes(data)
            try:
                files.make_previews(p, r.get("ext") or "")
            except Exception as e:  # noqa: BLE001
                log.info("previews for %s: %s", r["id"], e)


class CloudWorker(threading.Thread):
    """Syncs every few minutes while the cloud is configured; `trigger()` asks for a sync right now."""

    def __init__(self, db):
        super().__init__(name="cloud", daemon=True)
        self.cloud = Cloud(db)
        self._wake = threading.Event()
        self.stop_flag = False

    def trigger(self):
        self._wake.set()

    def run(self):
        time.sleep(float(os.environ.get("DD_CLOUD_DELAY", "20")))  # let the window open first
        while not self.stop_flag:
            if configured():
                self.cloud.sync()
            self._wake.wait(_settings()["interval"] * 60)
            self._wake.clear()
