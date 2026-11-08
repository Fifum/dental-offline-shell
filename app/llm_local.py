"""AI on this computer: the program downloads Ollama and a small open model (Qwen or Gemma) itself,
runs Ollama in the background while the program is open, and stops it on exit.

Nothing leaves the computer and nothing is paid for. A computer with 8 GB of memory is enough for the
3–4B models; a graphics card is used if there is one, otherwise the processor (slower).

Files: %LOCALAPPDATA%/<app>/ollama (the program, ~1.6 GB download) and models/ollama (the models).
Both folders can be copied to another computer with a flash drive.
"""
from __future__ import annotations

import atexit
import io
import json
import logging
import os
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path

import config

log = logging.getLogger("llm_local")

OLLAMA_URL = "https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip"
OLLAMA_MB = 1650
PORT = 11435            # our own Ollama; 11434 is left to an Ollama the clinic may have installed itself
SYSTEM_PORT = 11434
CTX = 8192              # room for the instructions plus a half-hour visit conversation
MODELS = {  # name: (short title, description, download MB, memory GB)
    "qwen2.5:3b": ("Быстрая", "Qwen 2.5 · 3B — быстрее, точность ниже", 1900, 8),
    "gemma3:4b": ("Рекомендуется", "Gemma 3 · 4B — хорошо понимает русский", 3300, 8),
    "qwen2.5:7b": ("Самая точная", "Qwen 2.5 · 7B — точнее, нужен мощный компьютер", 4700, 16),
}
DEFAULT_MODEL = "gemma3:4b"

_state = {"task": None, "progress": 0, "error": None}
_proc = {"p": None}
_start_lock = threading.Lock()


# ------------------------------------------------------------------ paths --
def home() -> Path:
    p = config.data_dir() / "ollama"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = config.data_dir() / "models" / "ollama"
    p.mkdir(parents=True, exist_ok=True)
    return p


def exe() -> Path:
    return home() / "ollama.exe"


def installed() -> bool:
    return exe().exists()


def _get(url, timeout=1.5):
    import requests  # noqa: PLC0415
    try:
        r = requests.get(url, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def base() -> str | None:
    """Address of the Ollama to use: ours if installed, otherwise one already installed on the computer."""
    if installed():
        return f"http://127.0.0.1:{PORT}"
    if _get(f"http://127.0.0.1:{SYSTEM_PORT}/api/version"):
        return f"http://127.0.0.1:{SYSTEM_PORT}"
    return None


def memory_gb() -> float:
    try:
        import ctypes  # noqa: PLC0415

        class MS(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                        ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
        m = MS()
        m.len = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.total / 2**30, 1)
    except Exception:  # noqa: BLE001
        return 0.0


def _has_nvidia() -> bool:
    return bool(shutil.which("nvidia-smi")) or Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe").exists()


# ----------------------------------------------------------------- server --
def running(b=None) -> bool:
    b = b or base()
    return bool(b and _get(f"{b}/api/version"))


def ensure() -> str:
    """Start our Ollama if needed; returns its address."""
    b = base()
    if not b:
        raise ValueError("ИИ на этом компьютере не установлен. Настройки → «Голос и ИИ» → «ИИ на этом компьютере».")
    if running(b):
        return b
    if not installed():
        raise ValueError("Ollama на этом компьютере не отвечает. Запустите её или установите заново в Настройках.")
    with _start_lock:
        if running(b):
            return b
        env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{PORT}", "OLLAMA_MODELS": str(models_dir()),
               "OLLAMA_KEEP_ALIVE": "20m", "OLLAMA_CONTEXT_LENGTH": str(CTX), "OLLAMA_NOPRUNE": "1"}
        logf = open(home() / "server.log", "ab")  # noqa: SIM115  (kept open while the server runs)
        _proc["p"] = subprocess.Popen([str(exe()), "serve"], env=env, cwd=str(home()), stdout=logf, stderr=logf,
                                      stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(60):
            if running(b):
                return b
            if _proc["p"].poll() is not None:
                break
            time.sleep(0.5)
    raise ValueError(f"Не удалось запустить ИИ на этом компьютере. Подробности в файле {home() / 'server.log'}")


@atexit.register
def stop():
    p = _proc.get("p")
    if p and p.poll() is None:
        try:
            p.terminate()
            p.wait(5)
        except Exception:  # noqa: BLE001
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass


def models_ready() -> list[str]:
    b = base()
    if not b:
        return []
    if not running(b):
        if not installed():
            return []
        try:
            ensure()
        except ValueError:
            return []
    tags = _get(f"{b}/api/tags", 5) or {}
    return [m.get("name", "") for m in tags.get("models", [])]


def _is_ready(name, ready):
    return name in ready or (":" not in name and f"{name}:latest" in ready)


def status() -> dict:
    ready = models_ready() if (installed() or base()) else []
    return {"installed": installed(), "external": not installed() and bool(base()), "address": base(),
            "ollama_mb": download_mb(), "folder": str(config.data_dir()), "memory_gb": memory_gb(),
            "models": {k: {"title": t, "desc": d, "mb": mb, "ram": ram, "ready": _is_ready(k, ready)} for k, (t, d, mb, ram) in MODELS.items()},
            "other": [m for m in ready if m not in MODELS], **_state}


# ---------------------------------------------------------------- install --
class _NoRanges(Exception):
    pass


class _HttpFile(io.RawIOBase):
    """A remote file opened for reading by HTTP range requests, so zipfile can pick single files."""

    def __init__(self, url, http):
        self.url, self.http, self.pos, self.fetched = url, http, 0, 0
        r = http.get(url, headers={"Range": "bytes=0-0"}, timeout=30, stream=True)  # stream: never read a whole file here
        r.close()
        if r.status_code != 206 or "/" not in r.headers.get("Content-Range", ""):
            raise _NoRanges()
        self.url = r.url  # the resolved download address: no redirect on every piece
        self.size = int(r.headers["Content-Range"].rsplit("/", 1)[1])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def readinto(self, b):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(b), self.size) - 1
        for attempt in range(3):
            try:
                r = self.http.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}, timeout=60)
                if r.status_code == 206:
                    break
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    raise
        else:
            raise RuntimeError(f"сервер не отдал часть файла (HTTP {r.status_code})")
        n = len(r.content)
        b[:n] = r.content
        self.pos += n
        self.fetched += n
        return n


def _extract_remote(url, need):
    import requests  # noqa: PLC0415
    raw = _HttpFile(url, requests.Session())
    z = zipfile.ZipFile(io.BufferedReader(raw, buffer_size=4 << 20))
    items = [i for i in z.infolist() if need(i.filename)]
    total = sum(i.compress_size for i in items) or 1
    start = raw.fetched
    for i in items:
        z.extract(i, home())
        _state["progress"] = min(94, int((raw.fetched - start) / total * 94))


def _download(url, part):
    import requests  # noqa: PLC0415
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or OLLAMA_MB * 1_000_000)
        got = 0
        with open(part, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                got += len(chunk)
                _state["progress"] = min(90, int(got / total * 90))


def download_mb() -> int:
    return OLLAMA_MB if _has_nvidia() else 45


def install():
    if _state["task"]:
        return status()
    _state.update(task="install", progress=0, error=None)

    def run():
        part = home() / "ollama.zip.part"
        nvidia = _has_nvidia()
        # graphics-card libraries are 1.5 of the 1.6 GB: without an NVIDIA card only the rest is needed
        need = (lambda n: True) if nvidia else (lambda n: "/cuda" not in n.lower() and "rocm" not in n.lower())
        try:
            try:
                _extract_remote(OLLAMA_URL, need)          # only the needed files, by HTTP ranges
            except _NoRanges:
                _download(OLLAMA_URL, part)                # the server would not give parts: whole archive
                with zipfile.ZipFile(part) as z:
                    for i in z.infolist():
                        if need(i.filename):
                            z.extract(i, home())
            _state["progress"] = 99
            if not installed():
                raise RuntimeError("в архиве нет ollama.exe")
            ensure()
            _state["progress"] = 100
        except Exception as e:  # noqa: BLE001
            log.warning("ollama install failed: %s", e)
            _state["error"] = f"Не удалось установить ИИ: {e}. Проверьте интернет и свободное место на диске (нужно около 5 ГБ)."
        finally:
            try:
                part.unlink()
            except OSError:
                pass
            _state["task"] = None
    threading.Thread(target=run, name="ollama-install", daemon=True).start()
    return status()


def pull(model: str):
    if model not in MODELS:
        raise ValueError("Неизвестная модель")
    if _state["task"]:
        return status()
    _state.update(task=f"pull:{model}", progress=0, error=None)

    def run():
        import requests  # noqa: PLC0415
        try:
            b = ensure()
            layers = {}
            with requests.post(f"{b}/api/pull", json={"model": model, "stream": True}, stream=True, timeout=(10, 600)) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    j = json.loads(line)
                    if j.get("error"):
                        raise RuntimeError(j["error"])
                    if j.get("digest") and j.get("total"):
                        layers[j["digest"]] = (j.get("completed") or 0, j["total"])
                        done, tot = sum(c for c, _ in layers.values()), sum(t for _, t in layers.values())
                        # new parts appear as the pull goes on: never let the bar step back
                        _state["progress"] = max(_state["progress"], min(99, int(done / max(tot, 1) * 100)))
                    if j.get("status") == "success":
                        break
            if not _is_ready(model, models_ready()):
                raise RuntimeError("модель скачалась не полностью")
            use(model)
            _state["progress"] = 100
        except Exception as e:  # noqa: BLE001
            log.warning("model pull failed: %s", e)
            _state["error"] = f"Не удалось скачать модель: {e}. Проверьте интернет; скачивание можно продолжить — уже скачанное сохраняется."
        finally:
            _state["task"] = None
    threading.Thread(target=run, name="ollama-pull", daemon=True).start()
    return status()


def use(model: str):
    """Make the program fill records with this local model."""
    import ai  # noqa: PLC0415
    ai.save({"enabled": True, "provider": "local", "model": model})
    return status()


def delete(model: str):
    import requests  # noqa: PLC0415
    b = ensure()
    requests.delete(f"{b}/api/delete", json={"model": model}, timeout=30)
    return status()


# ------------------------------------------------------------------- chat --
def chat(messages, model: str, timeout=300) -> str:
    import requests  # noqa: PLC0415
    b = ensure()
    try:
        r = requests.post(f"{b}/api/chat", timeout=max(timeout, 300), json={
            "model": model, "messages": messages, "stream": False, "keep_alive": "20m",
            "options": {"temperature": 0.1, "num_ctx": CTX}})
    except requests.Timeout as e:
        raise ValueError("ИИ на этом компьютере думал слишком долго. Выберите модель «Быстрая» или сократите запись.") from e
    except requests.RequestException as e:
        raise ValueError(f"ИИ на этом компьютере не отвечает: {e.__class__.__name__}") from e
    if r.status_code == 404:
        raise ValueError(f"Модель {model} не скачана. Настройки → «Голос и ИИ» → «ИИ на этом компьютере».")
    if r.status_code != 200:
        raise ValueError(f"ИИ на этом компьютере ответил ошибкой {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["message"]["content"]
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError("ИИ на этом компьютере вернул непонятный ответ") from e
