"""Updates over the internet: «Доступна новая версия» → the director presses «Обновить».

The update source is a folder on a web storage (Yandex Object Storage now, our own SaaS server later) with
`latest.json` and the installer exe next to it. latest.json is signed with Ed25519: the secret key stays with the
developer outside every repository, the public key is built into the program (config.UPDATE_PUBKEY). A file that
is not signed by that key, or an exe whose size or SHA-256 differ from the signed ones, is never started.

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
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import config

log = logging.getLogger("updates")
CHECK_EVERY_H = 6
FIRST_CHECK_S = 90
MAX_SIZE = 600 * 1024 * 1024


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


def source() -> str:
    """Address of latest.json: settings → brand.json → built-in default ('' = not set up yet)."""
    return (config.load_settings().get("update_url") or config.BRAND.get("update_url") or config.UPDATE_URL or "").strip()


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


def _open(url, timeout=20):
    if not _allowed(url):
        raise ValueError("Обновления скачиваются только по https://")
    if _is_local(url):
        return open(_local_path(url), "rb")
    req = urllib.request.Request(url, headers={"User-Agent": f"DentalDesk/{config.VERSION}", "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — scheme checked above


def updates_dir():
    p = config.data_dir() / "updates"
    p.mkdir(parents=True, exist_ok=True)
    return p


class Updater:
    def __init__(self):
        self.state = {"configured": bool(source()), "current": config.VERSION, "latest": None, "available": False,
                      "notes": "", "size": 0, "date": "", "checked_at": None, "error": "", "downloading": False,
                      "progress": 0, "ready": "", "installing": False}
        self._doc = None
        self._lock = threading.Lock()

    def check(self):
        src = source()
        self.state.update(configured=bool(src), current=config.VERSION)
        if not src:
            self.state.update(error="", available=False)
            return self.state
        try:
            with _open(src) as r:
                raw = r.read(256 * 1024)
            doc = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(doc, dict) or not verify(doc):
                raise ValueError("Файл обновления не подписан разработчиком — обновление отклонено")
            if doc.get("app") not in (None, "", "dentaldesk"):
                raise ValueError("Файл обновления от другой программы")
            for k in ("version", "file", "sha256", "size"):
                if not doc.get(k):
                    raise ValueError(f"В файле обновления нет поля «{k}»")
            self._doc = doc
            newer = vtuple(doc["version"]) > vtuple(config.VERSION)
            self.state.update(latest=doc["version"], available=newer, notes=str(doc.get("notes") or "")[:4000],
                              size=int(doc["size"]), date=str(doc.get("date") or ""), error="")
        except (OSError, ValueError) as e:
            msg = str(e) if isinstance(e, ValueError) else "Нет связи с сервером обновлений"
            log.info("update check: %s", e)
            self.state.update(error=msg)
        self.state["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return self.state

    def _download(self):
        doc = self._doc
        name = os.path.basename(str(doc["file"]).replace("\\", "/"))
        if not re.fullmatch(r"[\w .()\-]+\.exe", name):
            raise ValueError("Неверное имя файла обновления")
        size = int(doc["size"])
        if size <= 0 or size > MAX_SIZE:
            raise ValueError("Неверный размер файла обновления")
        dest = updates_dir() / name
        if dest.exists() and dest.stat().st_size == size and _sha256(dest) == doc["sha256"].lower():
            return str(dest)
        part = dest.with_suffix(".part")
        h, got = hashlib.sha256(), 0
        with _open(_join(source(), str(doc["file"])), timeout=60) as r, open(part, "wb") as f:
            while True:
                chunk = r.read(1024 * 256)
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
        os.replace(part, dest)
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
                self.state["error"] = str(e) if isinstance(e, ValueError) else f"Не удалось скачать обновление: {e}"
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
        if _sha256(path) != str(doc.get("sha256", "")).lower():  # checked again right before starting it
            raise ValueError("Файл обновления изменился после скачивания — скачайте заново")
        if not getattr(sys, "frozen", False) and not os.environ.get("DD_UPDATE_RUN"):
            raise ValueError("Установка обновления работает только в установленной программе")
        self.state["installing"] = True
        subprocess.Popen([path], close_fds=True, creationflags=0x00000008 | 0x00000200)  # noqa: S603 — signed file
        log.info("update %s started: %s", doc.get("version"), path)
        return True


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


UPDATER = Updater()


class UpdateWorker(threading.Thread):
    """Looks for a new version a minute and a half after start and then every few hours (quietly when offline)."""

    def __init__(self):
        super().__init__(name="updates", daemon=True)
        self.stop_flag = False

    def run(self):
        time.sleep(float(os.environ.get("DD_UPDATE_DELAY", FIRST_CHECK_S)))
        while not self.stop_flag:
            if source():
                UPDATER.check()
            time.sleep(CHECK_EVERY_H * 3600)
