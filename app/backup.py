"""Automatic backups of the clinic database, with restore in one click.

A backup is a .zip in %LOCALAPPDATA%/<app>/backups with:
  clinic.db      — a consistent copy made with SQLite's online backup (safe while the program works, WAL too)
  settings.json  — the settings file as it was (the API password inside is readable only on this computer)
  meta.json      — when, why, program version, how many patients and visits

Every copy is checked with PRAGMA integrity_check before it is kept. A copy can also go to a second
folder (a flash drive or another disk); if that folder is not available the main copy is still made
and the settings show a warning.

When: at start if the last copy is older than the interval, every `interval_h` hours while the program
runs, and when it closes. Rotation: every copy of the last `keep_all_days` days, then the newest copy of
each day up to `keep_days` days; the newest copy is never deleted.

Restore: the current database is first saved as a «before-restore» copy, then the chosen copy is written
into the open database with the same online-backup mechanism, and the program restarts.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger("backup")

DEFAULTS = {"enabled": True, "interval_h": 2, "keep_all_days": 2, "keep_days": 30, "extra_dir": ""}
REASONS = {"auto": "по расписанию", "start": "при запуске", "exit": "при выходе", "manual": "вручную",
           "before-restore": "перед восстановлением"}
NAME_RE = re.compile(r"^clinic-(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})(?:-([a-z-]+))?\.zip$")
WARN_HOURS = 24
EXTRA_SUBDIR = f"{config.APP_NAME} backups"

_STARTED = time.time()
_lock = threading.Lock()
_state ={"running": False, "error": None, "extra_error": None}


# ------------------------------------------------------------ settings --
def settings() -> dict:
    s = config.load_settings().get("backup") or {}
    return {**DEFAULTS, **{k: v for k, v in s.items() if k in DEFAULTS}}


def save_settings(f: dict) -> dict:
    cur = settings()
    if "enabled" in f:
        cur["enabled"] = bool(f["enabled"])
    for k, lo, hi in (("interval_h", 1, 24), ("keep_all_days", 1, 14), ("keep_days", 3, 365)):
        if k in f and f[k] not in (None, ""):
            try:
                v = int(f[k])
            except (TypeError, ValueError):
                raise ValueError("Укажите число") from None
            if not lo <= v <= hi:
                raise ValueError(f"Допустимо от {lo} до {hi}")
            cur[k] = v
    if cur["keep_days"] < cur["keep_all_days"]:
        raise ValueError("Хранить копии по дням нужно не меньше, чем все копии")
    if "extra_dir" in f:
        d = str(f["extra_dir"] or "").strip().strip('"')
        if d:
            p = Path(d)
            if not p.is_absolute():
                raise ValueError("Укажите полный путь к папке, например E:\\ или D:\\Копии")
            if _same_place(p, folder()):
                raise ValueError("Вторая папка должна быть на другом диске или флешке, а не там же, где основные копии")
        cur["extra_dir"] = d
    config.save_settings({"backup": cur})
    return status()


def _same_place(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except OSError:
        return False


# ------------------------------------------------------------- folders --
def folder() -> Path:
    p = config.data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def extra_folder(s: dict | None = None) -> Path | None:
    d = (s or settings()).get("extra_dir")
    return Path(d) / EXTRA_SUBDIR if d else None


def _parse(name: str):
    m = NAME_RE.match(name)
    if not m:
        return None
    day, hh, mm, ss, reason = m.groups()
    try:
        return datetime.strptime(f"{day} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S"), reason or "auto"
    except ValueError:
        return None


def _files(d: Path | None):
    """[(created, reason, path)] newest first."""
    out = []
    if d and d.is_dir():
        for p in d.iterdir():
            got = _parse(p.name)
            if got and p.is_file():
                out.append((got[0], got[1], p))
    return sorted(out, key=lambda x: x[0], reverse=True)


# ------------------------------------------------------------ checking --
def _check_db(path) -> dict:
    con = sqlite3.connect(str(path))
    try:
        res = con.execute("PRAGMA integrity_check").fetchone()[0]
        if res != "ok":
            raise ValueError(f"Копия повреждена: {res}")
        counts = {}
        for t in ("patients", "visits", "records", "invoices", "payments"):
            try:
                counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                pass
        return counts
    finally:
        con.close()


def _extract_db(zpath: Path) -> Path:
    """Unpack clinic.db of a backup into a temp file and check it. The caller deletes the file."""
    try:
        with zipfile.ZipFile(zpath) as z:
            if "clinic.db" not in z.namelist():
                raise ValueError("В архиве нет базы clinic.db")
            fd, tmp = tempfile.mkstemp(suffix=".db", dir=str(folder()))
            with os.fdopen(fd, "wb") as out, z.open("clinic.db") as src:
                shutil.copyfileobj(src, out)
    except zipfile.BadZipFile:
        raise ValueError("Файл копии повреждён (не открывается как архив)") from None
    try:
        _check_db(tmp)
    except Exception:
        os.remove(tmp)
        raise
    return Path(tmp)


# -------------------------------------------------------------- making --
def make(reason: str = "manual", db_path=None, now: datetime | None = None) -> dict:
    """Make one backup now. Returns its description. Raises ValueError if the copy failed."""
    db_path = Path(db_path or config.DB_PATH)
    if not db_path.exists():
        raise ValueError("Базы ещё нет — копировать нечего")
    reason = reason if reason in REASONS else "manual"
    s = settings()
    with _lock:
        _state["running"] = True
        try:
            now = now or datetime.now()
            d = folder()
            name = f"clinic-{now:%Y-%m-%d_%H-%M-%S}{'' if reason == 'auto' else '-' + reason}.zip"
            target = d / name
            fd, tmp_db = tempfile.mkstemp(suffix=".db", dir=str(d))
            os.close(fd)
            try:
                src = sqlite3.connect(str(db_path), timeout=30)
                dst = sqlite3.connect(tmp_db)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()
                counts = _check_db(tmp_db)
                meta = {"created": now.isoformat(timespec="seconds"), "reason": reason, "version": config.VERSION,
                        "app": config.APP_NAME, "counts": counts, "db_bytes": os.path.getsize(tmp_db)}
                part = target.with_suffix(".part")
                with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                    z.write(tmp_db, "clinic.db")
                    if config.SETTINGS_PATH.exists():
                        z.write(config.SETTINGS_PATH, "settings.json")
                    z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
                os.replace(part, target)
            finally:
                for p in (tmp_db, str(target.with_suffix(".part"))):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            rotate(d, s, now)
            _state["error"] = None
            _state["extra_error"] = _copy_extra(target, s, now)
            log.info("backup %s (%s, %.1f MB)", name, reason, target.stat().st_size / 1e6)
            return _describe(now, reason, target, "main", meta)
        except ValueError as e:
            _state["error"] = str(e)
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("backup failed")
            _state["error"] = f"Не удалось сделать копию: {e}"
            raise ValueError(_state["error"]) from e
        finally:
            _state["running"] = False


def _copy_extra(target: Path, s: dict, now: datetime):
    ex = extra_folder(s)
    if not ex:
        return None
    root = ex.parent
    if not root.exists():
        return f"Вторая папка недоступна ({root}). Вставьте флешку или проверьте диск — копия сохранена только на этом компьютере."
    try:
        ex.mkdir(parents=True, exist_ok=True)
        part = ex / (target.name + ".part")
        shutil.copy2(target, part)
        os.replace(part, ex / target.name)
        rotate(ex, s, now)
        return None
    except OSError as e:
        return f"Не удалось записать копию во вторую папку ({root}): {e.strerror or e}"


def rotate(d: Path, s: dict | None = None, now: datetime | None = None) -> list[str]:
    """Delete old copies by the rules. Returns the deleted names."""
    s = s or settings()
    now = now or datetime.now()
    files = _files(d)
    keep_all = now - timedelta(days=int(s["keep_all_days"]))
    keep_any = now - timedelta(days=int(s["keep_days"]))
    seen_days, removed = set(), []
    for i, (created, _reason, p) in enumerate(files):
        if i == 0 or created >= keep_all:
            seen_days.add(created.date())
            continue
        if created >= keep_any and created.date() not in seen_days:
            seen_days.add(created.date())  # newest copy of that day (files are newest first)
            continue
        try:
            p.unlink()
            removed.append(p.name)
        except OSError as e:
            log.warning("cannot delete old backup %s: %s", p, e)
    return removed


# ---------------------------------------------------------- describing --
def _describe(created, reason, p: Path, where, meta=None) -> dict:
    out = {"name": p.name, "where": where, "created": created.isoformat(timespec="seconds"), "reason": reason,
           "reason_text": REASONS.get(reason, reason), "size": p.stat().st_size}
    if meta:
        out.update(version=meta.get("version"), counts=meta.get("counts") or {})
    return out


def _meta(p: Path) -> dict:
    try:
        with zipfile.ZipFile(p) as z:
            return json.loads(z.read("meta.json").decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def listing() -> list[dict]:
    s = settings()
    out = [_describe(c, r, p, "main", _meta(p)) for c, r, p in _files(folder())]
    ex = extra_folder(s)
    if ex and ex.is_dir():
        names = {x["name"] for x in out}
        out += [_describe(c, r, p, "extra", _meta(p)) for c, r, p in _files(ex) if p.name not in names]
    return sorted(out, key=lambda x: x["created"], reverse=True)


def last_time() -> datetime | None:
    f = _files(folder())
    return f[0][0] if f else None


def status(now: datetime | None = None) -> dict:
    s = settings()
    now = now or datetime.now()
    files = _files(folder())
    last = files[0] if files else None
    age_h = (now - last[0]).total_seconds() / 3600 if last else None
    ex = extra_folder(s)
    ex_files = _files(ex) if ex else []
    warn = None
    if not s["enabled"]:
        warn = "Автоматические копии выключены."
    elif last is None:
        warn = "Резервных копий ещё нет."
    elif age_h >= WARN_HOURS:
        warn = f"Последняя резервная копия сделана {int(age_h // 24) or 1} дн. назад."
    if _state["error"]:
        warn = _state["error"]
    return {"settings": s, "folder": str(folder()), "count": len(files),
            "total_bytes": sum(p.stat().st_size for _c, _r, p in files),
            "last": _describe(last[0], last[1], last[2], "main") if last else None,
            "age_hours": round(age_h, 1) if age_h is not None else None,
            "extra": {"dir": s["extra_dir"], "folder": str(ex) if ex else "", "count": len(ex_files),
                      "last": ex_files[0][0].isoformat(timespec="seconds") if ex_files else None,
                      "available": bool(ex and ex.parent.exists()), "error": _state["extra_error"]} if ex else None,
            "running": _state["running"], "error": _state["error"], "warn": warn}


def warning() -> str | None:
    """Short text for the status bar, or None when the backups are fine."""
    try:
        st = status()
    except Exception:  # noqa: BLE001
        return None
    if st["last"] is None and st["settings"]["enabled"] and (st["running"] or time.time() - _STARTED < 180):
        return None  # the first copy is being made right after start
    return st["warn"] or (st["extra"] or {}).get("error")


# ------------------------------------------------------------- restore --
def find(where: str, name: str) -> Path:
    """A backup by its listed name; only from the two backup folders (no arbitrary paths)."""
    if not _parse(str(name or "")):
        raise ValueError("Копия не найдена")
    d = folder() if where != "extra" else extra_folder()
    p = d / name if d else None
    if not p or not p.is_file():
        raise ValueError("Копия не найдена — возможно, флешка не вставлена")
    return p


def restore(where: str, name: str, live_conn: sqlite3.Connection, lock=None, db_path=None) -> dict:
    """Replace the open database with a backup. The current data is saved first."""
    src_zip = find(where, name)
    tmp = _extract_db(src_zip)  # checked before anything changes
    try:
        safety = make("before-restore", db_path=db_path)
        src = sqlite3.connect(str(tmp))
        try:
            if lock is not None:
                with lock:
                    live_conn.commit()
                    src.backup(live_conn)
            else:
                live_conn.commit()
                src.backup(live_conn)
        finally:
            src.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    created = _parse(src_zip.name)[0]
    log.warning("database restored from %s (safety copy %s)", src_zip, safety["name"])
    return {"restored": src_zip.name, "created": created.isoformat(timespec="seconds"), "safety": safety["name"],
            "restart": True}


# -------------------------------------------------------------- worker --
class BackupWorker(threading.Thread):
    """Copies on start (if due), every interval while running, and once more on stop()."""

    CHECK_SECONDS = 60

    def __init__(self, db_path=None):
        super().__init__(name="backup", daemon=True)
        self.db_path = db_path
        self._stop = threading.Event()

    def _due(self, min_hours=None) -> bool:
        s = settings()
        if not s["enabled"]:
            return False
        last = last_time()
        hours = s["interval_h"] if min_hours is None else min_hours
        return last is None or datetime.now() - last >= timedelta(hours=hours)

    def _try(self, reason):
        try:
            make(reason, db_path=self.db_path)
        except Exception as e:  # noqa: BLE001
            log.warning("backup (%s) failed: %s", reason, e)

    def run(self):
        if self._due():
            self._try("start")
        while not self._stop.wait(self.CHECK_SECONDS):
            if self._due():
                self._try("auto")

    def stop(self, final=True):
        self._stop.set()
        if final and self._due(min_hours=0.25):  # not again if a copy was made in the last 15 minutes
            self._try("exit")


def wait_for_exit(pid: int, timeout=20.0):
    """Used by the restarted program: wait until the old process has closed."""
    if os.name != "nt":
        return
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if not h:
        return
    try:
        ctypes.windll.kernel32.WaitForSingleObject(h, int(timeout * 1000))
    finally:
        ctypes.windll.kernel32.CloseHandle(h)
    time.sleep(0.3)
