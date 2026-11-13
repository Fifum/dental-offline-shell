"""Clinic network 3.0: the clinic's computers find each other in the Wi-Fi and sync directly, with no server.

Every laptop keeps its own database and works on its own when the power (and the router) goes off. When computers
of the same clinic see each other, they exchange row versions (replica.py) directly: every minute and right after
a change. Nothing to set up: a computer answers the UDP broadcast on port 8766 with its node id and the clinic id
(an HMAC of the clinic key), then the exchange goes over HTTP on port 8765, every request and answer sealed with
the clinic key (AES-256-GCM, the same key as the cloud). A computer without the key gets nothing.

Joining: a new computer sends a pairing request with a one-time X25519 public key to the computers it found.
The director (on any of his computers that is online) sees «Новый компьютер … просит подключиться» with a code
that is also shown on the new computer (six digits made from that public key, so a substituted key shows a
different code). On «Принять» that computer seals the clinic key for the new one (X25519 + HKDF + AES-GCM); the
new computer collects it and from then on is a trusted computer of the clinic.

    POST /p2p/pair_request   {node, name, pub}       open: a new computer asks to join
    POST /p2p/pair_poll      {node}                  open: … and waits for the answer
    POST /p2p/hello|pull|notify|blob|dp_mirror       sealed with the clinic key (dp_mirror: dp_main.py, 3.7.2)
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request

import config
import replica
from cloud import CloudError, Keys, clinic_key, file_whole, save_file, set_clinic_key

log = logging.getLogger("p2p")

INTERVAL = int(os.environ.get("DD_P2P_INTERVAL", "60"))   # full round: find computers, take what they have
TICK = float(os.environ.get("DD_P2P_TICK", "2"))          # local changes are announced this quickly
PAIR_TTL = 15 * 60
MAX_PAIRS = 10
SKEW = 24 * 3600
NODE = None  # the running Node of this process

SCHEMA = """
CREATE TABLE IF NOT EXISTS p2p_peers(node TEXT PRIMARY KEY, name TEXT, host TEXT, ip TEXT, port INTEGER, epoch TEXT,
    mark INTEGER DEFAULT 0, last_seen TEXT, last_sync TEXT, error TEXT);
"""


class P2PError(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.code = code


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


# ------------------------------------------------------------------ clinic --
def configured() -> bool:
    return clinic_key() is not None


def keys():
    k = clinic_key()
    return Keys(k) if k else None


def clinic_id() -> str:
    k = keys()
    return k.clinic_id() if k else ""


def clinic_name() -> str:
    return config.load_settings().get("clinic_name") or config.BRAND["name"]


def is_member() -> bool:
    """Joined an existing clinic (its director account came from another computer)."""
    return bool(config.load_settings().get("clinic_member"))


def paused() -> str:
    if replica.HOLD:  # В2: restored from a backup, until the restart
        return replica.HOLD
    if config.load_settings().get("demo"):
        return "Демо-режим: тестовые данные не уходят на другие компьютеры клиники"
    return ""


def create_clinic(name="", db=None, fresh=False):
    """The first computer of a clinic: a new clinic key. `fresh` — a just-installed program: its demo data goes."""
    if configured():
        return False
    if fresh and db is not None:
        _leave_demo(db)
    set_clinic_key(secrets.token_bytes(32), name or config.BRAND["name"])
    config.save_settings({"clinic_founder": True})
    log.info("clinic created, id %s", clinic_id())
    if NODE:
        NODE.wake(full=True)
    return True


def _leave_demo(db):
    if config.load_settings().get("demo"):
        config.save_settings({"demo": False})
        db.wipe(quiet=True)  # never mix demo and real data; К1: the deletions never go to the clinic's computers
        db.data_kind("real")
        import catalog
        catalog.seed(db, demo=False)


def identity() -> dict:
    """What this computer says about itself in the network (no patient data)."""
    lone = True
    if NODE:
        try:
            lone = not NODE.db.one("SELECT 1 AS x FROM p2p_peers WHERE last_sync IS NOT NULL LIMIT 1")
        except Exception:  # noqa: BLE001
            pass
    return {"node": config.node_id(), "clinic": clinic_id(), "clinic_name": clinic_name() if configured() else "",
            "lone": bool(lone and not is_member())}


# ------------------------------------------------------------------- wire --
def _req_aad(method, node, ts):
    return f"p2p|{method}|{node}|{ts}"


def seal_request(k: Keys, method, payload) -> dict:
    ts, node = int(time.time()), config.node_id()
    return {"n": node, "c": k.clinic_id(), "t": ts,
            "d": _b64(k.seal(json.dumps(payload, ensure_ascii=False).encode("utf-8"), _req_aad(method, node, ts)))}


def open_request(k: Keys, method, body: dict):
    if body.get("c") != k.clinic_id():
        raise P2PError("Компьютер другой клиники", 403)
    ts, node = int(body.get("t") or 0), str(body.get("n") or "")
    if abs(time.time() - ts) > SKEW:
        raise P2PError("Неверное время запроса", 403)
    try:
        data = k.open(base64.b64decode(body.get("d") or ""), _req_aad(method, node, ts))
    except (CloudError, ValueError):
        raise P2PError("Запрос не расшифрован", 403) from None
    return node, ts, json.loads(data.decode("utf-8"))


def call(base_url, method, payload, timeout=10, sealed=True):
    """POST to another computer of the clinic. Returns its (decrypted) answer; raises P2PError."""
    k = keys() if sealed else None
    if sealed and not k:
        raise P2PError("Компьютер не в сети клиники")
    body = seal_request(k, method, payload) if sealed else payload
    req = urllib.request.Request(base_url.rstrip("/") + "/p2p/" + method, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — the clinic network
            ans = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error")
        except Exception:  # noqa: BLE001
            msg = ""
        raise P2PError(msg or f"Компьютер ответил ошибкой {e.code}", e.code) from None
    except (OSError, ValueError) as e:
        raise P2PError("Нет связи с компьютером", -1) from e
    if not sealed:
        return ans
    try:
        data = k.open(base64.b64decode(ans.get("d") or ""), f"re|{method}|{body['t']}|{body['n']}")
    except (CloudError, ValueError):
        raise P2PError("Ответ не расшифрован: ключ клиники не подходит", 403) from None
    return json.loads(data.decode("utf-8"))


def handle(method, body: dict, ip: str) -> dict:
    """Server side of /p2p/<method> (called from server.py). Returns the JSON answer."""
    if method == "pair_request":
        return _pair_request(body, ip)
    if method == "pair_poll":
        return _pair_poll(body)
    k = keys()
    if not k or not NODE:
        raise P2PError("Компьютер ещё не в сети клиники", 409)
    node, ts, payload = open_request(k, method, body)
    fn = {"hello": NODE.on_hello, "pull": NODE.on_pull, "notify": NODE.on_notify, "blob": NODE.on_blob,
          "dp_mirror": NODE.on_dp_mirror}.get(method)
    if not fn:
        raise P2PError("Не найдено", 404)
    ans = fn(node, payload, ip)
    return {"d": _b64(k.seal(json.dumps(ans, ensure_ascii=False).encode("utf-8"), f"re|{method}|{ts}|{node}"))}


# ---------------------------------------------------------------- pairing --
def pair_code(pub: bytes) -> str:
    return f"{int.from_bytes(hashlib.sha256(b'dd-pair' + pub).digest()[:4], 'big') % 1000000:06d}"


def _box_key(shared: bytes, node: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"dd-pair-v1|" + node.encode()).derive(shared)


PAIRS: dict = {}          # node → request from a new computer (kept in memory: a request lives minutes)
_PLOCK = threading.Lock()


def _clean_pairs():
    now = time.time()
    for n in [n for n, p in PAIRS.items() if now - p["at"] > PAIR_TTL]:
        PAIRS.pop(n, None)


def _pair_request(body, ip):
    if not configured():
        raise P2PError("Этот компьютер ещё не в сети клиники", 409)
    if paused():
        raise P2PError("Компьютер клиники в демо-режиме — подключение к нему недоступно", 409)
    node, name = str(body.get("node") or "")[:40], str(body.get("name") or "Компьютер")[:80]
    try:
        pub = base64.b64decode(body.get("pub") or "")
    except ValueError:
        pub = b""
    if not node or len(pub) != 32 or node == config.node_id():
        raise P2PError("Неверный запрос")
    with _PLOCK:
        _clean_pairs()
        if node not in PAIRS and len(PAIRS) >= MAX_PAIRS:
            raise P2PError("Слишком много запросов на подключение. Подождите несколько минут.", 429)
        cur = PAIRS.get(node)
        if not cur or cur["pub"] != pub or cur["state"] == "rejected":
            PAIRS[node] = {"node": node, "name": name, "host": str(body.get("host") or "")[:80], "pub": pub,
                           "code": pair_code(pub), "ip": ip, "at": time.time(), "state": "wait", "grant": None,
                           "lone": bool(body.get("has_data"))}
    log.info("pairing request from %s (%s)", name, ip)
    return {"ok": True, "clinic_name": clinic_name(), "code": pair_code(pub), "computer": socket.gethostname()}


def _pair_poll(body):
    with _PLOCK:
        p = PAIRS.get(str(body.get("node") or ""))
        if not p:
            return {"state": "unknown"}
        if p["state"] == "granted":
            return {"state": "granted", **p["grant"]}
        return {"state": p["state"]}


def pending_pairs() -> list:
    with _PLOCK:
        _clean_pairs()
        return [{"node": p["node"], "name": p["name"], "host": p["host"], "code": p["code"], "ip": p["ip"],
                 "has_data": p["lone"], "at": time.strftime("%H:%M", time.localtime(p["at"]))}
                for p in PAIRS.values() if p["state"] == "wait"]


def accept_pair(node) -> dict:
    """The director said «Принять»: seal the clinic key for exactly that computer's public key."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    k = clinic_key()
    if not k:
        raise P2PError("Этот компьютер не в сети клиники")
    if NODE and NODE.joiner and NODE.joiner.state == "wait":  # two laptops must not swap keys with each other
        raise P2PError("Этот компьютер сам ждёт подключения к другой клинике — примите запрос на том компьютере")
    with _PLOCK:
        p = PAIRS.get(str(node or ""))
        if not p or p["state"] != "wait":
            raise P2PError("Запрос уже обработан или устарел")
        eph = X25519PrivateKey.generate()
        box_key = _box_key(eph.exchange(X25519PublicKey.from_public_bytes(p["pub"])), p["node"])
        peers = [{"ip": x["ip"], "port": x["port"]} for x in (NODE.live_list() if NODE else [])]
        port = NODE.port if NODE else 8765
        secret = json.dumps({"key": _b64(k), "clinic_name": clinic_name(), "peers": peers, "port": port}).encode()
        nonce = secrets.token_bytes(12)
        from cryptography.hazmat.primitives import serialization
        epk = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        p["grant"] = {"epk": _b64(epk), "box": _b64(nonce + AESGCM(box_key).encrypt(nonce, secret, p["node"].encode()))}
        p["state"] = "granted"
    log.info("pairing granted to %s", p["name"])
    return {"ok": True, "name": p["name"]}


def reject_pair(node) -> bool:
    with _PLOCK:
        p = PAIRS.get(str(node or ""))
        if p and p["state"] == "wait":
            p["state"] = "rejected"
    return True


class Joiner:
    """This computer asks to join a clinic and waits for the director's answer (polls in the background)."""

    def __init__(self, db, targets: list, port=8765):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        self.db, self.targets, self.port = db, targets, port
        self.priv = X25519PrivateKey.generate()
        self.pub = self.priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.code = pair_code(self.pub)
        self.state, self.message, self.clinic = "idle", "", ""
        self.stop_flag = False

    def start(self):
        if self.db.one("SELECT 1 AS x FROM sync_state WHERE k='cloud_seq'") and config.load_settings().get("cloud_url"):
            raise P2PError("Этот компьютер подключён к облаку другой клиники. Сначала отключите облако.")
        has_data = bool(self.db.one("SELECT 1 AS x FROM users LIMIT 1"))
        body = {"node": config.node_id(), "name": socket.gethostname(), "host": socket.gethostname(), "pub": _b64(self.pub),
                "has_data": has_data}
        sent = []
        for t in self.targets:
            try:
                r = call(f"http://{t['ip']}:{t['port']}", "pair_request", body, timeout=5, sealed=False)
                self.clinic = r.get("clinic_name") or self.clinic
                sent.append(t)
            except P2PError as e:
                self.message = str(e)
        if not sent:
            self.state = "error"
            raise P2PError(self.message or "Компьютеры клиники не отвечают")
        self.targets, self.state, self.message = sent, "wait", ""
        threading.Thread(target=self._loop, name="p2p-join", daemon=True).start()
        return {"code": self.code, "clinic_name": self.clinic}

    def _loop(self):
        end = time.time() + PAIR_TTL
        while not self.stop_flag and self.state == "wait" and time.time() < end:
            for t in list(self.targets):
                try:
                    r = call(f"http://{t['ip']}:{t['port']}", "pair_poll", {"node": config.node_id()}, timeout=5, sealed=False)
                except P2PError:
                    continue
                if r.get("state") == "granted":
                    try:
                        self._granted(r, t)
                    except Exception as e:  # noqa: BLE001
                        log.exception("pairing")
                        self.state, self.message = "error", f"Не удалось подключиться: {e}"
                    return
                if r.get("state") == "rejected":
                    self.state, self.message = "rejected", "Директор отклонил подключение этого компьютера"
                    return
            time.sleep(1.5)
        if self.state == "wait":
            self.state, self.message = "expired", "Запрос устарел. Отправьте его ещё раз."

    def _granted(self, r, t):
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        box = base64.b64decode(r["box"])
        shared = self.priv.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(r["epk"])))
        secret = json.loads(AESGCM(_box_key(shared, config.node_id())).decrypt(box[:12], box[12:], config.node_id().encode()))
        key = base64.b64decode(secret["key"])
        _leave_demo(self.db)
        with self.db.tx() as c:  # another clinic's computers are not ours any more
            c.execute("DELETE FROM p2p_peers")
        set_clinic_key(key, secret.get("clinic_name") or "", member=True)
        config.save_settings({"clinic_founder": False})
        peers = [{"ip": t["ip"], "port": t["port"]}] + list(secret.get("peers") or [])
        if NODE:
            for p in peers:
                NODE.seen(None, p["ip"], p["port"])
            NODE.wake(full=True)
        self.state, self.message = "done", ""
        log.info("joined clinic %s", clinic_id())


# ------------------------------------------------------------------- node --
class Node(threading.Thread):
    """Finds the clinic's computers, takes their changes and tells them about ours."""

    def __init__(self, db, port=8765):
        super().__init__(name="p2p", daemon=True)
        global NODE
        self.db, self.port = db, int(port)
        replica.install(db)
        db.script(SCHEMA)
        self.live: dict = {}       # node → {ip, port, name, host, seen}
        self.others: dict = {}     # computers of other clinics (or not joined yet) seen in the network
        self._wake = threading.Event()
        self._full = True
        self._wanted: set = set()
        self._lock = threading.Lock()
        self.stop_flag = False
        self.joiner = None
        self.state = {"last_ok": None, "last_round": None, "error": "", "pulled": 0, "sent": 0, "conflicts_new": 0}
        NODE = self

    # ------------------------------------------------------------ helpers --
    def wake(self, full=False, node=None):
        if full:
            self._full = True
        if node:
            self._wanted.add(node)
        self._wake.set()

    def seen(self, node, ip, port, name="", host="", epoch=None):
        """A computer of our clinic is alive at ip:port (from a discovery answer or its own request)."""
        if not ip:
            return
        if node:
            self.live[node] = {"node": node, "ip": ip, "port": int(port or 8765), "name": name, "host": host, "seen": time.time()}
            with self.db.tx() as c:
                c.execute("INSERT INTO p2p_peers(node, name, host, ip, port, last_seen) VALUES(?,?,?,?,?,?) ON CONFLICT(node) DO "
                          "UPDATE SET ip=excluded.ip, port=excluded.port, last_seen=excluded.last_seen, "
                          "name=COALESCE(NULLIF(excluded.name, ''), name), host=COALESCE(NULLIF(excluded.host, ''), host)",
                          (node, name, host, ip, int(port or 8765), _now()))
        else:  # only an address (from the pairing answer): ask it who it is
            self.live.setdefault(f"addr:{ip}:{port}", {"node": "", "ip": ip, "port": int(port or 8765), "name": "", "host": "",
                                                        "seen": time.time()})

    def live_list(self):
        now = time.time()
        return [p for p in self.live.values() if now - p["seen"] < 3 * INTERVAL]

    def _info(self):
        return {"node": config.node_id(), "name": socket.gethostname(), "host": socket.gethostname(), "port": self.port,
                "epoch": replica.epoch(self.db),
                "top": replica.top_seq(self.db)}

    # ------------------------------------------------------------ server --
    def on_hello(self, node, f, ip):
        self.seen(node, ip, f.get("port"), f.get("name", ""), f.get("host", ""))
        with _PLOCK:
            PAIRS.pop(node, None)  # it has the key: the request is done
        return self._info()

    def on_pull(self, node, f, ip):
        if paused():
            raise P2PError(paused(), 409)
        self.seen(node, ip, f.get("port"), f.get("name", ""), f.get("host", ""))
        replica.stamp(self.db, config.node_id())
        ep, top = replica.epoch(self.db), replica.top_seq(self.db)
        since = int(f.get("since") or 0)
        if f.get("epoch") != ep or since > top:
            since = 0  # restored from a backup (or a new database): send everything, versions sort it out
        limit = max(1, min(int(f.get("limit") or 500), 1000))
        items = replica.changes_since(self.db, since, limit)
        return {"epoch": ep, "top": top, "items": items, "more": len(items) >= limit}

    def on_notify(self, node, f, ip):
        self.seen(node, ip, f.get("port"), f.get("name", ""), f.get("host", ""))
        self.wake(node=node)
        return {"ok": True}

    def on_blob(self, node, f, ip):
        sha = str(f.get("sha") or "")
        r = self.db.one("SELECT * FROM patient_files WHERE sha256=? LIMIT 1", (sha,)) if sha else None
        if not r:
            raise P2PError("Файл не найден", 404)
        p = _file_path(r)
        if not file_whole(p, r):  # В15: a damaged file is never given to another computer
            raise P2PError("Файл не найден", 404)
        return {"data": _b64(p.read_bytes())}

    def on_dp_mirror(self, node, f, ip):
        """3.7.2: the copy of Dentist Plus for a computer that does not talk to Dentist Plus itself (dp_main.py)."""
        import dp_main
        self.seen(node, ip, f.get("port"), f.get("name", ""), f.get("host", ""))
        try:
            return dp_main.snapshot(self.db, str(f.get("since") or ""), bool(f.get("full")))
        except dp_main.DpMainError as e:
            raise P2PError(str(e), 409) from None

    # ------------------------------------------------------------ client --
    def discover(self):
        """UDP broadcast: computers of our clinic → live; others (other clinic, not joined) → `others`."""
        import server
        me, cid = config.node_id(), clinic_id()
        others = {}
        for info in server.discover(port=self.port):
            node = info.get("node")
            if not node or node == me:
                continue
            if cid and info.get("clinic") == cid:
                self.seen(node, info["ip"], info.get("port"), info.get("host", ""), info.get("host", ""))
            else:
                others[node] = info
        self.others = others
        return others

    def _peer_row(self, node):
        return self.db.one("SELECT * FROM p2p_peers WHERE node=?", (node,))

    def sync_peer(self, p) -> int:
        url = f"http://{p['ip']}:{p['port']}"
        me = {"port": self.port, "name": socket.gethostname(), "host": socket.gethostname()}
        if not p.get("node"):  # known only by address: say hello to learn who it is
            info = call(url, "hello", me, timeout=5)
            self.live.pop(f"addr:{p['ip']}:{p['port']}", None)
            if not info.get("node"):
                return 0
            self.seen(info["node"], p["ip"], p["port"], info.get("name", ""), info.get("host", ""))
            p = self.live[info["node"]]
        row = self._peer_row(p["node"]) or {}
        mark, ep = int(row.get("mark") or 0), row.get("epoch") or ""
        got = 0
        for _ in range(200):
            r = call(url, "pull", {**me, "since": mark, "epoch": ep, "limit": 500}, timeout=30)
            if r["epoch"] != ep:
                mark, ep = 0, r["epoch"]
            items = r.get("items") or []
            if items:
                st = replica.apply_versions(self.db, items, config.node_id())
                self.state["conflicts_new"] += st["conflicts"]
                got += st["applied"] + st["merged"]
                mark = max(mark, max(int(i["seq"]) for i in items))
            elif not r.get("more"):
                mark = int(r.get("top") or 0)
            with self.db.tx() as c:
                c.execute("UPDATE p2p_peers SET mark=?, epoch=?, last_sync=?, error='' WHERE node=?", (mark, ep, _now(), p["node"]))
            if not r.get("more"):
                break
        self._fetch_files(url)
        return got

    def _fetch_files(self, url):
        try:
            rows = self.db.q("SELECT * FROM patient_files WHERE COALESCE(deleted,0)=0 AND sha256 IS NOT NULL")
        except Exception:  # noqa: BLE001
            return
        import files
        for r in rows:
            p = _file_path(r)
            if file_whole(p, r):  # В15: a file cut by a power cut is taken again
                continue
            try:
                data = base64.b64decode(call(url, "blob", {"sha": r["sha256"]}, timeout=120)["data"])
            except P2PError as e:
                if e.code == 404:
                    continue
                raise
            if hashlib.sha256(data).hexdigest() != r["sha256"]:
                log.warning("file %s: checksum mismatch", r["id"])
                continue
            save_file(p, data)
            try:
                files.make_previews(p, r.get("ext") or "")
            except Exception as e:  # noqa: BLE001
                log.info("previews for %s: %s", r["id"], e)

    def notify_all(self):
        me = {"port": self.port, "name": socket.gethostname(), "host": socket.gethostname()}
        for p in self.live_list():
            if p.get("node"):
                threading.Thread(target=self._notify_one, args=(p, me), daemon=True).start()

    def _notify_one(self, p, me):
        try:
            call(f"http://{p['ip']}:{p['port']}", "notify", me, timeout=4)
            self.state["sent"] += 1
        except P2PError:
            pass

    def round(self, full):
        """One pass: (full) find computers and greet them, then take changes from the ones that asked or all."""
        if full:
            try:
                self.discover()
            except OSError as e:
                log.info("discovery: %s", e)
            known = self.db.q("SELECT * FROM p2p_peers")  # broadcast may be blocked: try the last known addresses too
            for k in known:
                if k["node"] not in self.live and k["ip"]:
                    try:
                        call(f"http://{k['ip']}:{k['port']}", "hello", {"port": self.port, "name": socket.gethostname(),
                                                                         "host": socket.gethostname()}, timeout=3)
                        self.seen(k["node"], k["ip"], k["port"], k["name"], k["host"])
                    except P2PError:
                        pass
        wanted, self._wanted = self._wanted, set()
        targets = [p for p in self.live_list() if full or p.get("node") in wanted or not p.get("node")]
        err = ""
        for p in targets:
            try:
                if full and p.get("node"):
                    call(f"http://{p['ip']}:{p['port']}", "hello", {"port": self.port, "name": socket.gethostname(),
                                                                     "host": socket.gethostname()}, timeout=5)
                self.state["pulled"] += self.sync_peer(p)
            except P2PError as e:
                err = str(e)
                if p.get("node"):
                    with self.db.tx() as c:
                        c.execute("UPDATE p2p_peers SET error=? WHERE node=?", (err[:200], p["node"]))
                    if e.code == -1:
                        self.live.pop(p["node"], None)
            except Exception as e:  # noqa: BLE001
                log.exception("sync with %s", p.get("ip"))
                err = str(e)
        self.state.update(last_round=_now(), error=err)
        if targets and not err:
            self.state["last_ok"] = _now()

    def run(self):
        time.sleep(float(os.environ.get("DD_P2P_DELAY", "3")))
        last_full = 0.0
        while not self.stop_flag:
            try:
                if configured() and not paused():
                    if replica.pending(self.db) and replica.stamp(self.db, config.node_id()):
                        self.notify_all()  # tell the others right away: they come and take it
                    full = self._full or time.time() - last_full >= INTERVAL
                    if full or self._wanted:
                        self._full = False
                        self.round(full)
                        if full:
                            last_full = time.time()
            except Exception:  # noqa: BLE001
                log.exception("p2p round")
            self._wake.wait(TICK)
            self._wake.clear()

    # ------------------------------------------------------------ status --
    def status(self):
        peers = self.db.q("SELECT node, name, host, ip, port, last_seen, last_sync, error FROM p2p_peers ORDER BY name")
        live = {p["node"] for p in self.live_list()}
        for p in peers:
            p["online"] = p["node"] in live
        return {**self.state, "configured": configured(), "clinic_name": clinic_name() if configured() else "",
                "clinic_id": clinic_id(), "node": config.node_id(), "computer": socket.gethostname(), "peers": peers,
                "paused": paused(), "pending": replica.pending(self.db), "member": is_member(),
                "founder": bool(config.load_settings().get("clinic_founder")), "lone": identity()["lone"],
                "others": [{"node": n, "host": o.get("host"), "ip": o.get("ip"), "port": o.get("port"),
                            "clinic_name": o.get("clinic_name") or "", "clinic": o.get("clinic") or ""}
                           for n, o in self.others.items() if o.get("clinic")],
                "join": {"state": self.joiner.state, "code": self.joiner.code, "message": self.joiner.message,
                         "clinic_name": self.joiner.clinic} if self.joiner else None}

    def join(self, targets):
        if self.joiner and self.joiner.state == "wait":
            self.joiner.stop_flag = True
        self.joiner = Joiner(self.db, targets, self.port)
        return self.joiner.start()


def _file_path(row):
    import files
    return files._pdir(row["patient_id"]) / (row["id"] + (row.get("ext") or ""))


def scan(timeout=2.5):
    """For the first-start screen: clinics found in the network → [{clinic, clinic_name, computers: [...]}]."""
    import server
    me = config.node_id()
    by = {}
    for info in server.discover(timeout=timeout, port=NODE.port if NODE else 8765):
        if info.get("node") == me or not info.get("clinic"):
            continue
        c = by.setdefault(info["clinic"], {"clinic": info["clinic"], "clinic_name": info.get("clinic_name") or "", "computers": []})
        c["computers"].append({"node": info.get("node"), "host": info.get("host"), "ip": info["ip"], "port": info.get("port"),
                               "lone": info.get("lone")})
    return list(by.values())
