"""Updates over the internet: «Вышла новая версия» → anyone at the clinic presses «Обновить».

The update source is `latest.json` with the installer next to it. Since 3.1 it is a GitHub release of a public
repository that holds nothing but updates: the program reads
`https://github.com/<owner>/<repo>/releases/latest/download/latest.json` — a plain download link, not the REST API,
so the check once a minute does not touch the 60-requests-an-hour API limit (and sends If-None-Match, so an
unchanged file comes back as a short 304). The address comes from settings → brand.json → config.UPDATE_URL.

latest.json is signed with Ed25519: the secret key stays with the developer outside every repository, the public
key is built into the program (config.UPDATE_PUBKEY). A file that is not signed by that key, or a file whose size
or SHA-256 differ from the signed ones, is never started.

The clinic's build carries its name, so in a public repository the installer is stored encrypted (AES-256-CTR,
«enc» in latest.json) with a key built into that build only (brand.json → update_key, never in git); the notes
are encrypted too (AES-GCM). Encryption only hides the file from strangers — the signature is what protects it.

Installing = starting the downloaded installer (setup_main.py): it closes this program (which saves everything and
makes a backup on exit), puts the new version in place and opens it again.

3.12 — fast updates:
- «только изменения»: latest.json may describe a delta from the previous version (only the changed files of the
  program folder). A program of exactly that version whose files match its own manifest (manifest.py) downloads the
  delta, assembles the new folder next to itself, checks every file against the manifest of the new version and
  installs it the same way (update_helper.py: close, backup, the new version opens). Any doubt — the whole file.
  Programs up to 3.11 do not know the field and download the whole file as before.
- the clinic network first: a computer that has already downloaded and checked a file gives it to the others
  (p2p.py, sealed with the clinic key); a computer asks them before the internet, and waits for one that is
  downloading the same file right now instead of downloading it a second time. Every file is checked against the
  SHA-256 of the signed latest.json, wherever it came from.
- a download that broke off continues where it stopped (HTTP Range), from the internet and from the clinic network.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import config
import manifest

log = logging.getLogger("updates")
CHECK_EVERY_S = 60
INSTALL_GIVE_UP_S = 10 * 60  # М17: the installer waits for the program to close a few minutes at most
FIRST_CHECK_S = 30
MAX_SIZE = 600 * 1024 * 1024
ENC = "aes-256-ctr"
CHUNK = 1024 * 256
RETRIES = 5                                                   # attempts in a row that bring nothing new
RETRY_S = float(os.environ.get("DD_UPDATE_RETRY_S", "3"))     # pause before continuing a broken download
PEER_TIMEOUT = 4
LAN_POLL_S = float(os.environ.get("DD_UPDATE_LAN_POLL", "3"))
LAN_STALL_S = float(os.environ.get("DD_UPDATE_LAN_STALL", "45"))  # a computer that stopped downloading is not waited for
LAN_WAIT_MAX_S = 40 * 60
FILE_RE = r"[\w .()\-]+\.(exe|bin|zip)"
MANIFEST_AAD = b"dd-manifest"  # manifest-<version>.bin in the feed: the next release builds its delta from it


def vtuple(v) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))[:4]) or (0,)


def canonical(doc: dict) -> bytes:
    """The signed bytes: every field except «sig», keys sorted, no spaces."""
    return json.dumps({k: v for k, v in doc.items() if k != "sig"}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def verify(doc: dict, pubkey_hex: str | None = None) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    pub = pubkey_hex if pubkey_hex is not None else config.UPDATE_PUBKEY
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub)).verify(base64.b64decode(doc.get("sig") or ""), canonical(doc))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def sign(doc: dict, private_key) -> dict:
    out = {k: v for k, v in doc.items() if k != "sig"}
    out["sig"] = base64.b64encode(private_key.sign(canonical(out))).decode()
    return out


NOTES_MAX = 30000   # 3.11: «Что нового» of 3.10 was ~6000 letters and was cut at 4000 in the update dialog

# ------------------------------------------------------------------ encryption of the installer and the notes
def enc_key() -> bytes | None:
    """The build's update key (brand.json → update_key), or None for a build without one."""
    raw = str(getattr(config, "UPDATE_KEY", "") or "").strip()
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        return None
    return key if len(key) == 32 else None


def _ctr(key: bytes, nonce: bytes):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    return Cipher(algorithms.AES(key), modes.CTR(nonce))


def encrypt_file(src, dst, key: bytes) -> tuple[int, str]:
    """dst = 16-byte nonce + AES-CTR(src). Returns (size, sha256) of dst — what latest.json signs."""
    nonce = os.urandom(16)
    enc = _ctr(key, nonce).encryptor()
    h = hashlib.sha256(nonce)
    size = len(nonce)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(nonce)
        for chunk in iter(lambda: fi.read(CHUNK), b""):
            out = enc.update(chunk)
            h.update(out)
            size += len(out)
            fo.write(out)
        out = enc.finalize()
        h.update(out)
        size += len(out)
        fo.write(out)
    return size, h.hexdigest()


def decrypt_file(src, dst, key: bytes) -> str:
    """The reverse of encrypt_file; returns sha256 of the plain file."""
    h = hashlib.sha256()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        nonce = fi.read(16)
        if len(nonce) != 16:
            raise ValueError("Файл обновления повреждён")
        dec = _ctr(key, nonce).decryptor()
        for chunk in iter(lambda: fi.read(CHUNK), b""):
            out = dec.update(chunk)
            h.update(out)
            fo.write(out)
        out = dec.finalize()
        h.update(out)
        fo.write(out)
    return h.hexdigest()


def seal_text(text: str, key: bytes, aad: bytes = b"dd-notes") -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, text.encode("utf-8"), aad)).decode()


def open_text(sealed: str, key: bytes, aad: bytes = b"dd-notes") -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(sealed)
    return AESGCM(key).decrypt(raw[:12], raw[12:], aad).decode("utf-8")


# ------------------------------------------------------------------ where updates come from
def source() -> str:
    """Address of latest.json: settings → brand.json → built-in default ('' = not set up yet)."""
    return (config.load_settings().get("update_url") or config.BRAND.get("update_url") or config.UPDATE_URL or "").strip()


def github_feed(repo: str) -> str:
    """The address a build reads for a GitHub repository «owner/name» that publishes updates as releases."""
    return f"https://github.com/{repo.strip().strip('/')}/releases/latest/download/latest.json"


def _is_local(src: str) -> bool:
    return src.startswith("file:") or bool(re.match(r"^[A-Za-z]:[\\/]", src)) or src.startswith("\\\\")


def _local_path(src: str) -> str:
    if src.startswith("file:"):
        return urllib.request.url2pathname(urllib.parse.urlparse(src).path)
    return src


def _join(src: str, name: str) -> str:
    if re.match(r"^https?://", name):
        return name
    if _is_local(src):
        return os.path.join(os.path.dirname(_local_path(src)), name)
    return urllib.parse.urljoin(src, name)


def _allowed(url: str) -> bool:
    if _is_local(url) or url.startswith("https://"):
        return True
    host = urllib.parse.urlparse(url).hostname or ""
    return url.startswith("http://") and host in ("127.0.0.1", "localhost")


def _open(url, timeout=20, etag=""):
    if not _allowed(url):
        raise ValueError("Обновления скачиваются только по https://")
    if _is_local(url):
        return open(_local_path(url), "rb")
    headers = {"User-Agent": f"DentalDesk/{config.VERSION}", "Cache-Control": "no-cache"}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl_context() if url.startswith("https://") else None
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)  # noqa: S310 — scheme checked above


def ssl_context() -> ssl.SSLContext:
    """3.7.1: certificates of the Windows store AND of certifi together. Python reads only the certificates that are
    already in the Windows store, while Windows itself downloads a missing root on demand — so on some computers
    github.com failed with «unable to get issuer certificate». certifi (comes with requests) carries the current
    roots; the Windows store keeps what the clinic added itself (an antivirus that checks HTTPS, a corporate proxy)."""
    ctx = ssl.create_default_context()  # verifies host names; on Windows loads the system store (load_default_certs)
    try:
        ctx.load_default_certs()
    except Exception:  # noqa: BLE001
        pass
    try:
        import certifi  # noqa: PLC0415
        ctx.load_verify_locations(certifi.where())
    except Exception as e:  # noqa: BLE001 — still the Windows store alone
        log.info("certifi not available: %s", e)
    return ctx


CERT_ERROR = ("Не удалось проверить сертификат сервера обновлений. Проверьте дату и время на компьютере; "
              "если антивирус проверяет HTTPS-соединения — разрешите программе доступ к github.com")


def is_cert_error(e) -> bool:
    reason = getattr(e, "reason", e)
    return isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(e)


def updates_dir():
    p = config.data_dir() / "updates"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------ 3.12: checked files for the clinic's computers
def share_dir():
    """Update files as they were published (encrypted), downloaded and checked against a signed latest.json — kept
    for the other computers of the clinic (p2p.py serves them by their SHA-256)."""
    p = updates_dir() / "share"
    p.mkdir(parents=True, exist_ok=True)
    return p


_SLOCK = threading.Lock()


def _share_index() -> dict:
    try:
        idx = json.loads((share_dir() / "index.json").read_text(encoding="utf-8"))
        return idx if isinstance(idx, dict) else {}
    except (OSError, ValueError):
        return {}


def _share_save(idx):
    tmp = share_dir() / "index.json.tmp"
    tmp.write_text(json.dumps(idx), encoding="utf-8")
    os.replace(tmp, share_dir() / "index.json")


def _share_add(sha, name, size):
    with _SLOCK:
        idx = _share_index()
        idx[sha] = {"file": name, "size": int(size)}
        _share_save(idx)


def shared(sha) -> Path | None:
    """The checked file with this SHA-256, if this computer has it."""
    if not re.fullmatch(r"[0-9a-f]{64}", str(sha or "")):
        return None
    e = _share_index().get(sha)
    if not isinstance(e, dict) or not re.fullmatch(FILE_RE, str(e.get("file") or "")):
        return None
    p = share_dir() / e["file"]
    try:
        return p if p.is_file() and p.stat().st_size == int(e.get("size") or -1) else None
    except (OSError, TypeError, ValueError):
        return None


def _keep_only(doc):
    """Only the files of the current latest.json stay (the whole file and its delta — the computers that have not
    updated yet may still ask for them); older ones, leftovers of broken downloads and old installers go."""
    full = os.path.basename(str(doc.get("file") or ""))
    keep = {full}
    d = doc.get("delta")
    if isinstance(d, dict):
        keep.add(os.path.basename(str(d.get("file") or "")))
    with _SLOCK:
        idx = _share_index()
        for sha in [s for s, e in idx.items() if not isinstance(e, dict) or e.get("file") not in keep]:
            idx.pop(sha, None)
        _share_save(idx)
        for f in share_dir().iterdir():
            if f.name == "index.json" or f.name in keep or f.name in {k + ".part" for k in keep}:
                continue
            try:
                f.unlink()
            except OSError:
                pass
    mine = {(full[:-4] + ".exe") if full else "", "dd-update-helper.exe"}
    for f in updates_dir().iterdir():
        if f.is_file() and (f.suffix in (".part", ".part2") or (f.suffix == ".exe" and f.name not in mine)):
            try:
                f.unlink()
            except OSError:
                pass


# ------------------------------------------------------------------ 3.12: the clinic network
def _peers() -> list:
    """Computers of this clinic that are online now (p2p.py found them and they carry the clinic key)."""
    try:
        import p2p
        node = p2p.NODE
        if not node or not p2p.configured() or p2p.paused():
            return []
        return [p for p in node.live_list() if p.get("node")]
    except Exception:  # noqa: BLE001
        return []


def _peer_name(p) -> str:
    return str(p.get("host") or p.get("name") or p.get("ip") or "")


def _ask_peers(sha, peers=None) -> list:
    """[(computer, answer)]: which computers of the clinic have the file `sha`, which are downloading it right now."""
    peers = _peers() if peers is None else peers
    if not peers:
        return []
    import p2p
    out, lock = [], threading.Lock()

    def one(p):
        try:
            a = p2p.call(f"http://{p['ip']}:{p['port']}", "upd_have", {"sha": sha}, timeout=PEER_TIMEOUT)
        except Exception:  # noqa: BLE001 — another clinic, an older version, no answer: simply not a source
            return
        if isinstance(a, dict):
            with lock:
                out.append((p, a))

    threads = [threading.Thread(target=one, args=(p,), daemon=True) for p in peers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(PEER_TIMEOUT + 2)
    with lock:
        return list(out)


def _peer_open(p, sha, start):
    """The file `sha` from a computer of the clinic, from byte `start` (the request is sealed with the clinic key)."""
    import p2p
    k = p2p.keys()
    if not k:
        raise OSError("Компьютер не в сети клиники")
    seal = base64.b64encode(json.dumps(p2p.seal_request(k, "upd_get", {"sha": sha})).encode()).decode()
    headers = {"X-DD-Seal": seal, "User-Agent": f"DentalDesk/{config.VERSION}"}
    if start:
        headers["Range"] = f"bytes={start}-"
    req = urllib.request.Request(f"http://{p['ip']}:{p['port']}/p2p/upd/{sha}", headers=headers)
    return urllib.request.urlopen(req, timeout=30)  # noqa: S310 — the clinic network; the file is checked after


def lan_have(sha) -> dict:
    """The answer to another computer of the clinic: «у меня есть этот файл» / «я его сейчас скачиваю»."""
    p = shared(sha)
    try:
        size = p.stat().st_size if p else 0
    except OSError:
        p, size = None, 0
    f = UPDATER.fetching
    busy = bool(f and f.get("sha") == sha and not p)
    return {"have": bool(p), "size": size, "busy": busy, "started": bool(busy and f.get("started")),
            "got": int(f.get("got") or 0) if busy else 0, "total": int(f.get("size") or 0) if busy else 0}


# ------------------------------------------------------------------ 3.12: downloads that continue after a break
class Unreachable(OSError):
    """No source answered (no internet, the connection kept breaking): the part stays, «Повторить» continues it."""


class _LocalPart:
    """A file in a local / network folder of updates, answering like an HTTP range response."""

    def __init__(self, path, start):
        self.f = open(path, "rb")  # noqa: SIM115 — closed in __exit__
        self.f.seek(start)
        self.status = 206 if start else 200
        self.headers = {"Content-Range": f"bytes {start}-"} if start else {}

    def read(self, n=-1):
        return self.f.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()
        return False


def _open_from(url, start):
    if not _allowed(url):
        raise ValueError("Обновления скачиваются только по https://")
    if _is_local(url):
        return _LocalPart(_local_path(url), start)
    headers = {"User-Agent": f"DentalDesk/{config.VERSION}"}
    if start:
        headers["Range"] = f"bytes={start}-"  # kept by urllib through GitHub's redirect to the file's server
    req = urllib.request.Request(url, headers=headers)
    ctx = ssl_context() if url.startswith("https://") else None
    return urllib.request.urlopen(req, timeout=60, context=ctx)  # noqa: S310 — scheme checked above


# ------------------------------------------------------------------ 3.12: «только изменения»
def program_dir() -> Path | None:
    """The installed program folder this process runs from — what an update «только изменения» changes — or None:
    a run from the sources, a copy started from another folder."""
    if not getattr(sys, "frozen", False):
        return None
    try:
        import installer
        here = os.path.dirname(os.path.abspath(sys.executable))
        if installer.is_onedir() and os.path.normcase(here) == os.path.normcase(installer.install_dir()):
            return Path(here)
    except Exception:  # noqa: BLE001
        pass
    return None


def _failed_mark(version) -> Path:
    """Written by update_helper.py when installing the changes failed: this version is then downloaded whole."""
    return updates_dir() / f"delta-failed-{re.sub(r'[^0-9.]', '', str(version))}"


def _assemble(zpath, pdir: Path, local: dict, stage: Path, doc: dict, progress=None) -> dict:
    """The new program folder in `stage`: the changed files from the delta, every other one from this computer's
    folder (a hard link — no second copy on the disk; a copy where a link is not possible), then every file checked
    against the manifest of the new version. Anything unexpected raises, and no stage is left behind."""
    shutil.rmtree(stage, ignore_errors=True)
    try:
        with zipfile.ZipFile(zpath) as z:
            try:
                meta = json.loads(z.read("delta.json").decode("utf-8"))
            except (KeyError, ValueError):
                raise ValueError("в обновлении нет описания изменений") from None
            new = meta.get("manifest") if isinstance(meta, dict) else None
            if not manifest.valid(new) or vtuple(new["version"]) != vtuple(doc.get("version")) \
                    or new["exe"] != local["exe"] or vtuple(meta.get("from")) != vtuple(local["version"]):
                raise ValueError("изменения не для этой версии программы")
            if doc.get("manifest") and manifest.digest(new) != doc["manifest"]:
                raise ValueError("список файлов новой версии не совпал с подписанным")
            if manifest.HELPER not in new["files"]:
                raise ValueError("в новой версии нет помощника установки")
            names = set(z.namelist())
            stage.mkdir(parents=True)
            for rel, (size, sha) in new["files"].items():
                dst = stage.joinpath(*rel.split("/"))
                dst.parent.mkdir(parents=True, exist_ok=True)
                if "files/" + rel in names:
                    with z.open("files/" + rel) as src, open(dst, "wb") as out:
                        shutil.copyfileobj(src, out, 1024 * 1024)
                        out.flush()
                        os.fsync(out.fileno())
                    continue
                if list(local["files"].get(rel) or []) != [size, sha]:
                    raise ValueError(f"в изменениях нет файла {rel}")
                src = pdir.joinpath(*rel.split("/"))
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)
        manifest.write(stage, new)
        bad = manifest.check(stage, new, progress)
        if bad:
            raise ValueError(f"файлы новой версии не совпали с её списком: {', '.join(bad[:3])}")
        return new
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


class NotModified(Exception):
    pass


class Updater:
    def __init__(self):
        self.state = {"configured": bool(source()), "current": config.VERSION, "latest": None, "available": False,
                      "notes": "", "size": 0, "date": "", "checked_at": None, "error": "", "downloading": False,
                      "progress": 0, "ready": "", "installing": False, "unpublished": False,
                      "dl_size": 0, "delta": False, "note": "", "mode": "", "via": ""}  # 3.12: what, how, from where
        self._doc = None
        self._etag = ("", "")  # (address, ETag) of the last latest.json read
        self._lock = threading.Lock()
        self._last_logged = ""
        self.fetching = None  # 3.12: {sha, got, size} while this computer downloads that file from the internet

    def _fetch(self, src) -> bytes:
        etag = self._etag[1] if self._etag[0] == src and self._doc else ""
        try:
            with _open(src, etag=etag) as r:
                raw = r.read(256 * 1024)
                tag = (getattr(r, "headers", None) or {}).get("ETag") or ""
        except urllib.error.HTTPError as e:
            if e.code == 304:
                raise NotModified() from None
            if e.code == 404:  # a new repository without releases yet
                raise FileNotFoundError("no release") from None
            raise
        self._etag = (src, tag)
        return raw

    def check(self):
        src = source()
        self.state.update(configured=bool(src), current=config.VERSION)
        if not src:
            self.state.update(error="", available=False)
            return self.state
        try:
            doc = json.loads(self._fetch(src).decode("utf-8-sig"))
            if not isinstance(doc, dict) or not verify(doc):
                raise ValueError("Файл обновления не подписан разработчиком — обновление отклонено")
            if doc.get("app") not in (None, "", "dentaldesk"):
                raise ValueError("Файл обновления от другой программы")
            for k in ("version", "file", "sha256", "size"):
                if not doc.get(k):
                    raise ValueError(f"В файле обновления нет поля «{k}»")
            notes = str(doc.get("notes") or "")
            if doc.get("enc"):
                key = enc_key()
                if doc["enc"] != ENC or not key or not doc.get("plain_sha256") or not doc.get("plain_size"):
                    raise ValueError("Это обновление для другой сборки программы — установите новую версию файлом-установщиком")
                if doc.get("notes_enc"):
                    try:
                        notes = open_text(doc["notes_enc"], key)
                    except Exception:  # noqa: BLE001 — another build's key
                        raise ValueError("Это обновление для другой сборки программы — установите новую версию файлом-установщиком") from None
            newer = vtuple(doc["version"]) > vtuple(config.VERSION)
            if not self._doc or self._doc.get("sha256") != doc["sha256"]:
                self.state.update(ready="", mode="")  # another file than the one downloaded before
            self._doc = doc
            self._last_logged = ""
            plan = self._delta_plan(doc) if newer else None
            self.state.update(latest=doc["version"], available=newer, notes=notes[:NOTES_MAX],
                              size=int(doc.get("plain_size") or doc["size"]), date=str(doc.get("date") or ""), error="",
                              unpublished=False, delta=bool(plan),
                              dl_size=int(plan["delta"]["size"]) if plan else int(doc["size"]))
            if not self.state["downloading"] and not self.state["installing"]:
                try:
                    _keep_only(doc)
                except OSError as e:
                    log.info("update files cleanup: %s", e)
        except NotModified:
            self.state.update(error="", unpublished=False)
        except FileNotFoundError:  # 3.6.1: say so instead of «последняя версия» — nothing has been published yet
            self.state.update(error="", available=False, latest=None, unpublished=True)
        except (OSError, ValueError) as e:
            msg = str(e) if isinstance(e, ValueError) else CERT_ERROR if is_cert_error(e) else "Нет связи с сервером обновлений"
            if str(e) != self._last_logged:  # the check runs every minute: log a failure once, not 60 times an hour
                log.info("update check: %s", e)
                self._last_logged = str(e)
            self.state.update(error=msg)
        self.state["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return self.state

    # -------------------------------------------------------------- what to download
    def _delta_plan(self, doc):
        """The delta of latest.json, when this computer can use it: the program is exactly the version the delta
        starts from, installed as a folder with its manifest, that manifest is the one the delta was made against,
        and installing changes of this version has not failed here before. None = the whole file."""
        d = doc.get("delta")
        if not isinstance(d, dict) or vtuple(d.get("from")) != vtuple(config.VERSION):
            return None
        enc = bool(doc.get("enc"))
        name = str(d.get("file") or "")
        try:
            size = int(d.get("size") or 0)
            if enc:
                int(d.get("plain_size") or "x")
        except (TypeError, ValueError):
            return None
        if not re.fullmatch(FILE_RE, name) or os.path.basename(name) != name or not 0 < size <= MAX_SIZE \
                or not re.fullmatch(r"[0-9a-f]{64}", str(d.get("sha256") or "")) or name.endswith(".bin") != enc \
                or (enc and not re.fullmatch(r"[0-9a-f]{64}", str(d.get("plain_sha256") or ""))):
            return None
        if _failed_mark(doc.get("version")).exists():
            return None
        pdir = program_dir()
        m = manifest.load(pdir) if pdir else None
        if not m or vtuple(m.get("version")) != vtuple(config.VERSION) or manifest.digest(m) != d.get("from_manifest"):
            return None
        return {"delta": d, "dir": pdir, "manifest": m}

    def _prog(self, lo, hi, frac):
        self.state["progress"] = max(0, min(100, int(lo + (hi - lo) * max(0.0, min(1.0, frac)))))

    def _note(self, text):
        self.state["note"] = text

    def _download(self):
        doc = self._doc
        name = os.path.basename(str(doc["file"]).replace("\\", "/"))
        enc = bool(doc.get("enc"))
        if not re.fullmatch(r"[\w .()\-]+\.(exe|bin)", name) or (name.endswith(".bin") and not enc):
            raise ValueError("Неверное имя файла обновления")
        size = int(doc["size"])
        if size <= 0 or size > MAX_SIZE:
            raise ValueError("Неверный размер файла обновления")
        dest = updates_dir() / (name[:-4] + ".exe")
        want = str(doc.get("plain_sha256") if enc else doc["sha256"]).lower()
        if dest.exists() and _sha256(dest) == want:
            self.state["mode"] = "full"
            return str(dest)
        plan = self._delta_plan(doc)
        if plan:
            try:
                stage = self._via_delta(doc, plan)
                self.state["mode"] = "delta"
                return stage
            except Unreachable:
                raise  # no connection: the whole file would not come either; «Повторить» continues the delta
            except Exception as e:  # noqa: BLE001 — any doubt: the whole file, as before
                log.warning("update %s: «только изменения» not used (%s), downloading the whole file", doc.get("version"), e)
                self.state.update(delta=False, dl_size=size)
        got = self._obtain({"file": name, "size": size, "sha256": str(doc["sha256"]).lower()}, 0, 96)
        self._note("Проверяем обновление…")
        part2 = dest.with_suffix(".part2")
        if not enc:
            shutil.copyfile(got, part2)
            sha = _sha256(part2)
        else:
            key = enc_key()
            if not key:
                raise ValueError("Это обновление для другой сборки программы")
            try:
                sha = decrypt_file(got, part2, key)
            except Exception:
                part2.unlink(missing_ok=True)
                raise
        if sha != want or (enc and part2.stat().st_size != int(doc["plain_size"])):
            part2.unlink(missing_ok=True)
            raise ValueError("Файл обновления не расшифровался — это обновление для другой сборки программы" if enc
                             else "Файл обновления повреждён (контрольная сумма не совпала) — попробуйте ещё раз")
        os.replace(part2, dest)
        self.state["mode"] = "full"
        self._prog(0, 100, 1)
        return str(dest)

    def _via_delta(self, doc, plan) -> str:
        d, pdir, local = plan["delta"], plan["dir"], plan["manifest"]
        self._note("Проверяем файлы программы…")
        bad = manifest.check(pdir, local, progress=lambda f: self._prog(0, 8, f))
        if bad:
            raise ValueError(f"файлы программы отличаются от её версии: {', '.join(bad[:3])}")
        got = self._obtain({"file": d["file"], "size": int(d["size"]), "sha256": str(d["sha256"]).lower()}, 8, 70,
                           what="только изменения")
        self._note("Собираем новую версию и проверяем её файлы…")
        zpath = updates_dir() / "delta.zip.part"
        try:
            if doc.get("enc"):
                key = enc_key()
                if not key:
                    raise ValueError("нет ключа этой сборки")
                sha = decrypt_file(got, zpath, key)
                if sha != str(d["plain_sha256"]).lower() or zpath.stat().st_size != int(d["plain_size"]):
                    raise ValueError("изменения не расшифровались")
            else:
                shutil.copyfile(got, zpath)
            stage = pdir / f".new-{re.sub(r'[^0-9.]', '', str(doc['version']))}"
            _assemble(zpath, pdir, local, stage, doc, lambda f: self._prog(70, 100, f))
        finally:
            zpath.unlink(missing_ok=True)
        return str(stage)

    # -------------------------------------------------------------- where it comes from
    def _obtain(self, item, lo, hi, what="обновление") -> Path:
        """The published file `item` ({file, size, sha256}) in share_dir(), checked against its SHA-256: from a computer
        of the clinic that has it, after one that is downloading it right now, else from the internet."""
        sha, size = item["sha256"], int(item["size"])
        final = share_dir() / item["file"]
        if final.is_file() and final.stat().st_size == size and _sha256(final) == sha:
            _share_add(sha, final.name, size)
            self._prog(lo, hi, 1)
            self.state["via"] = "уже скачано"
            return final
        part = final.with_name(final.name + ".part")
        mb = f"{max(1, round(size / 1048576))} МБ"
        bad = set()
        for _ in range(3):
            offers = _ask_peers(sha)
            got = self._from_peers(item, part, final, offers, bad, lo, hi, what, mb)
            if got:
                return got
            busy = [(p, a) for p, a in offers if a.get("busy") and p.get("node") not in bad]
            if not busy:
                break
            if not self._wait_peers(item, busy, lo, hi):
                bad.update(p.get("node") for p, _a in busy)  # stopped or gone: not waited for again
                break
        return self._from_internet(item, part, final, bad, lo, hi, what, mb)

    def _from_peers(self, item, part, final, offers, bad, lo, hi, what, mb):
        sha, size = item["sha256"], int(item["size"])
        for p, a in offers:
            if not a.get("have") or int(a.get("size") or 0) != size or p.get("node") in bad:
                continue
            self._note(f"Скачиваем {what} ({mb}) по сети клиники с компьютера «{_peer_name(p)}»")
            try:
                self._pull(lambda start, p=p: _peer_open(p, sha, start), part, size, lo, hi, retries=2)
            except (OSError, http.client.HTTPException, ValueError) as e:
                log.info("update file from %s: %s", _peer_name(p), e)
                bad.add(p.get("node"))
                continue
            if _sha256(part) == sha:
                return self._keep(part, final, item, f"сеть клиники, компьютер «{_peer_name(p)}»")
            log.warning("update file from %s: checksum mismatch, not used", _peer_name(p))
            part.unlink(missing_ok=True)
            bad.add(p.get("node"))
        return None

    def _wait_peers(self, item, busy, lo, hi) -> bool:
        """Another computer of the clinic is downloading this very file from the internet: wait for it instead of
        downloading it a second time. True when one of them has it now; False when they stopped or went away."""
        sha, peers = item["sha256"], [p for p, _a in busy]
        names = ", ".join(f"«{_peer_name(p)}»" for p in peers[:2])
        began, best, moved = time.time(), -1, time.time()
        while time.time() - began < LAN_WAIT_MAX_S:
            offers = _ask_peers(sha, peers)
            if any(a.get("have") for _p, a in offers):
                return True
            live = [a for _p, a in offers if a.get("busy")]
            if not live:
                return False
            got = max(int(a.get("got") or 0) for a in live)
            total = max(int(a.get("total") or 0) for a in live) or int(item["size"])
            if got > best:
                best, moved = got, time.time()
            elif time.time() - moved > LAN_STALL_S:
                return False
            self._note(f"Это обновление уже скачивает компьютер {names} — возьмём у него по сети клиники")
            self._prog(lo, hi, got / total)
            time.sleep(LAN_POLL_S)
        return False

    def _from_internet(self, item, part, final, bad, lo, hi, what, mb):
        sha, size = item["sha256"], int(item["size"])
        url = _join(source(), item["file"])

        def busy():
            self.fetching = {"sha": sha, "got": part.stat().st_size if part.exists() else 0, "size": size}

        busy()
        try:
            # two computers pressed «Обновить» at the same moment: one that already downloads, or else the one with the
            # smaller id, goes on; the other waits for it and takes the file from it
            me = config.node_id()
            rivals = [(p, a) for p, a in _ask_peers(sha) if a.get("busy") and p.get("node") not in bad
                      and (a.get("started") or str(p.get("node") or "") < me)]
            if rivals:
                self.fetching = None
                if self._wait_peers(item, rivals, lo, hi):
                    got = self._from_peers(item, part, final, _ask_peers(sha, [p for p, _a in rivals]), bad, lo, hi, what, mb)
                    if got:
                        return got
                else:
                    bad.update(p.get("node") for p, _a in rivals)
                busy()
            self.fetching["started"] = True
            for _ in range(2):
                self._note(f"Скачиваем {what} ({mb}) из интернета")
                try:
                    self._pull(lambda start: _open_from(url, start), part, size, lo, hi, retries=RETRIES, advertise=True)
                except urllib.error.HTTPError:
                    raise
                except (OSError, http.client.HTTPException) as e:
                    raise Unreachable(str(e)) from e
                if _sha256(part) == sha:
                    return self._keep(part, final, item, "интернет")
                part.unlink(missing_ok=True)  # damaged on the way: once more from the start
                log.warning("update download: checksum mismatch, once more from the start")
            raise ValueError("Файл обновления повреждён (контрольная сумма не совпала) — попробуйте ещё раз")
        finally:
            self.fetching = None

    def _keep(self, part, final, item, via):
        os.replace(part, final)
        _share_add(item["sha256"], final.name, int(item["size"]))
        self.state["via"] = via
        return final

    def _pull(self, open_fn, part: Path, size, lo, hi, retries, advertise=False):
        """Download into `part` until it has `size` bytes, continuing what is already there (HTTP Range). A broken
        connection is retried after a pause; `retries` attempts in a row that bring nothing new give up (the part stays)."""
        misses = 0
        while True:
            have = part.stat().st_size if part.exists() else 0
            if have > size:
                part.unlink()
                have = 0
            if have == size:
                return
            try:
                self._pull_once(open_fn, part, have, size, lo, hi, advertise)
            except urllib.error.HTTPError as e:
                if e.code == 416 and have:
                    part.unlink(missing_ok=True)  # «range not satisfiable»: what we have is not the start of this file
                elif e.code < 500:
                    raise  # no such file, no access: another attempt would not change it
                misses += 1  # 416, or the server is busy for a moment (5xx)
                if misses > retries:
                    raise
                time.sleep(RETRY_S)
            except (OSError, http.client.HTTPException) as e:
                if is_cert_error(e):
                    raise
                now = part.stat().st_size if part.exists() else 0
                misses = 0 if now > have else misses + 1
                if misses >= retries:
                    raise
                log.info("update download broke off at %s of %s bytes (%s): continuing", now, size, e)
                time.sleep(RETRY_S)

    def _pull_once(self, open_fn, part: Path, have, size, lo, hi, advertise):
        too_big = False
        with open_fn(have) as r:
            if have:
                cr = str((getattr(r, "headers", None) or {}).get("Content-Range") or "")
                m = re.match(r"bytes (\d+)-", cr)
                if int(getattr(r, "status", 0) or 200) != 206 or not m or int(m[1]) != have:
                    have = 0  # this source sends the file from its start: write it anew
            got = have
            with open(part, "ab" if have else "wb") as f:
                while True:
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    if got + len(chunk) > size:
                        too_big = True
                        break
                    got += len(chunk)
                    f.write(chunk)
                    self._prog(lo, hi, got / size)
                    if advertise and self.fetching:
                        self.fetching["got"] = got
        if too_big:
            part.unlink(missing_ok=True)
            raise ValueError("Файл обновления больше ожидаемого")
        if got < size:
            raise ConnectionError(f"связь оборвалась на {got} из {size} байт")

    def start_download(self):
        if not self._doc or not self.state["available"]:
            self.check()
        if not self.state["available"]:
            raise ValueError(self.state["error"] or "Новой версии нет")
        if self.state["downloading"]:
            return self.state

        def run():
            try:
                self.state["ready"] = self._download()
                self.state.update(error="", note="")
            except Unreachable as e:
                self.state["error"] = (CERT_ERROR if is_cert_error(e) else
                                       "Связь прервалась — нажмите «Повторить»: скачивание продолжится с того же места")
                log.warning("update download: %s", e)
            except (OSError, ValueError) as e:
                self.state["error"] = (str(e) if isinstance(e, ValueError) else CERT_ERROR if is_cert_error(e)
                                       else f"Не удалось скачать обновление: {e}")
                log.warning("update download: %s", e)
            finally:
                self.state["downloading"] = False

        self.state.update(downloading=True, progress=0, ready="", error="", note="", mode="", via="")
        threading.Thread(target=run, name="update-download", daemon=True).start()
        return self.state

    def install(self):
        path = self.state.get("ready")
        if not path or not os.path.exists(path):
            raise ValueError("Сначала скачайте обновление")
        doc = self._doc or {}
        if self.state.get("mode") == "delta":
            return self._install_delta(Path(path), doc)
        want = str(doc.get("plain_sha256") if doc.get("enc") else doc.get("sha256", "")).lower()
        if _sha256(path) != want:  # checked again right before starting it
            raise ValueError("Файл обновления изменился после скачивания — скачайте заново")
        if not getattr(sys, "frozen", False) and not os.environ.get("DD_UPDATE_RUN"):
            raise ValueError("Установка обновления работает только в установленной программе")
        self.state.update(installing=True, error="")
        self._installing_at = time.time()
        try:
            subprocess.Popen([path], close_fds=True, creationflags=0x00000008 | 0x00000200)  # noqa: S603 — signed file
        except OSError as e:
            self.state["installing"] = False
            raise ValueError(f"Не удалось запустить установку обновления: {e}") from None
        log.info("update %s started: %s", doc.get("version"), path)
        return True

    def _install_delta(self, stage: Path, doc):
        """3.12: the assembled folder is checked once more, then the helper (update_helper.py) closes the program
        (it saves and backs up on exit), puts the folder in place and opens the new version."""
        m = manifest.load(stage)
        if not m or vtuple(m.get("version")) != vtuple(doc.get("version")) or manifest.check(stage, m):
            shutil.rmtree(stage, ignore_errors=True)
            self.state.update(ready="", mode="")
            raise ValueError("Файлы обновления изменились после проверки — нажмите «Обновить» ещё раз")
        if not getattr(sys, "frozen", False) and not os.environ.get("DD_UPDATE_RUN"):
            raise ValueError("Установка обновления работает только в установленной программе")
        helper = updates_dir() / "dd-update-helper.exe"
        try:
            shutil.copyfile(stage.joinpath(*manifest.HELPER.split("/")), helper)
        except OSError as e:
            raise ValueError(f"Не удалось подготовить установку обновления: {e}") from None
        if _sha256(helper) != m["files"][manifest.HELPER][1]:
            raise ValueError("Помощник установки обновления повреждён — нажмите «Обновить» ещё раз")
        job = {"stage": str(stage), "target": str(stage.parent), "exe": m["exe"], "title": config.APP_TITLE,
               "name": config.BRAND["name"], "failed": str(_failed_mark(doc.get("version"))), "args": []}
        jp = updates_dir() / "apply.json"
        jp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        self.state.update(installing=True, error="")
        self._installing_at = time.time()
        try:
            subprocess.Popen([str(helper), str(jp)], close_fds=True, creationflags=0x00000008 | 0x00000200)  # noqa: S603
        except OSError as e:
            self.state["installing"] = False
            raise ValueError(f"Не удалось запустить установку обновления: {e}") from None
        log.info("update %s («только изменения») started: %s", doc.get("version"), stage)
        return True

    def installing(self) -> bool:
        """М17: the installer closes this program; if it is still running long after, the installer gave up
        (the program did not close, or the person pressed «Отмена») — back to normal, «Обновить» works again."""
        if self.state["installing"] and time.time() - getattr(self, "_installing_at", 0) > INSTALL_GIVE_UP_S:
            self.state.update(installing=False, error="Обновление не установилось: программа не закрылась. Нажмите «Обновить» ещё раз.")
            log.warning("update: the installer did not close the program, giving up")
        return self.state["installing"]


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


UPDATER = Updater()


class UpdateWorker(threading.Thread):
    """Looks for a new version half a minute after start and then once a minute (quietly when offline)."""

    def __init__(self):
        super().__init__(name="updates", daemon=True)
        self.stop_flag = False

    def run(self):
        time.sleep(float(os.environ.get("DD_UPDATE_DELAY", FIRST_CHECK_S)))
        while not self.stop_flag:
            if source() and not UPDATER.state["downloading"] and not UPDATER.installing():
                try:
                    UPDATER.check()
                except Exception:  # noqa: BLE001 — never let the worker die
                    log.exception("update check")
            time.sleep(float(os.environ.get("DD_UPDATE_EVERY", CHECK_EVERY_S)))
