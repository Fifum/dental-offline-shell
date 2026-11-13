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
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config

log = logging.getLogger("updates")
CHECK_EVERY_S = 60
INSTALL_GIVE_UP_S = 10 * 60  # М17: the installer waits for the program to close a few minutes at most
FIRST_CHECK_S = 30
MAX_SIZE = 600 * 1024 * 1024
ENC = "aes-256-ctr"
CHUNK = 1024 * 256


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


def seal_text(text: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, text.encode("utf-8"), b"dd-notes")).decode()


def open_text(sealed: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(sealed)
    return AESGCM(key).decrypt(raw[:12], raw[12:], b"dd-notes").decode("utf-8")


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


class NotModified(Exception):
    pass


class Updater:
    def __init__(self):
        self.state = {"configured": bool(source()), "current": config.VERSION, "latest": None, "available": False,
                      "notes": "", "size": 0, "date": "", "checked_at": None, "error": "", "downloading": False,
                      "progress": 0, "ready": "", "installing": False, "unpublished": False}
        self._doc = None
        self._etag = ("", "")  # (address, ETag) of the last latest.json read
        self._lock = threading.Lock()
        self._last_logged = ""

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
                self.state["ready"] = ""  # another file than the one downloaded before
            self._doc = doc
            self._last_logged = ""
            self.state.update(latest=doc["version"], available=newer, notes=notes[:4000],
                              size=int(doc.get("plain_size") or doc["size"]), date=str(doc.get("date") or ""), error="",
                              unpublished=False)
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
            return str(dest)
        got_file = updates_dir() / name if enc else dest
        part = got_file.with_suffix(".part")
        h, got = hashlib.sha256(), 0
        with _open(_join(source(), str(doc["file"])), timeout=60) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                got += len(chunk)
                if got > size:
                    raise ValueError("Файл обновления больше ожидаемого")
                h.update(chunk)
                f.write(chunk)
                self.state["progress"] = int(got * 100 / size)
        if got != size or h.hexdigest() != doc["sha256"].lower():
            part.unlink(missing_ok=True)
            raise ValueError("Файл обновления повреждён (контрольная сумма не совпала) — попробуйте ещё раз")
        if not enc:
            os.replace(part, dest)
            return str(dest)
        key = enc_key()
        if not key:
            part.unlink(missing_ok=True)
            raise ValueError("Это обновление для другой сборки программы")
        plain = dest.with_suffix(".part2")
        try:
            sha = decrypt_file(part, plain, key)
        finally:
            part.unlink(missing_ok=True)
        if sha != want or plain.stat().st_size != int(doc["plain_size"]):
            plain.unlink(missing_ok=True)
            raise ValueError("Файл обновления не расшифровался — это обновление для другой сборки программы")
        os.replace(plain, dest)
        return str(dest)

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
                self.state["error"] = ""
            except (OSError, ValueError) as e:
                self.state["error"] = (str(e) if isinstance(e, ValueError) else CERT_ERROR if is_cert_error(e)
                                      else f"Не удалось скачать обновление: {e}")
                log.warning("update download: %s", e)
            finally:
                self.state["downloading"] = False

        self.state.update(downloading=True, progress=0, ready="", error="")
        threading.Thread(target=run, name="update-download", daemon=True).start()
        return self.state

    def install(self):
        path = self.state.get("ready")
        if not path or not os.path.exists(path):
            raise ValueError("Сначала скачайте обновление")
        doc = self._doc or {}
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
