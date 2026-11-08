"""Patient files: X-rays (DICOM too), intraoral photos, scans and documents, kept on this computer.

Storage: %LOCALAPPDATA%/<app>/files/<patient>/<id><ext> — the original is never changed. Next to it:
<id>.view.jpg|png (what the viewer shows: TIFF, BMP and DICOM converted) and <id>.thumb.jpg (list preview).

Visiograph / sensor software saves images into its own folder. The program watches that folder
(«Папка снимков визиографа» in the settings) and offers new images to put into the open patient's card.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger("files")

SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_files(
    id TEXT PRIMARY KEY, patient_id TEXT, kind TEXT, title TEXT, tooth TEXT, taken_at TEXT, note TEXT,
    orig_name TEXT, ext TEXT, mime TEXT, size INTEGER, sha256 TEXT, width INTEGER, height INTEGER, meta TEXT,
    created_at TEXT, created_by TEXT, updated_at TEXT, deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_pfiles_patient ON patient_files(patient_id);
CREATE TABLE IF NOT EXISTS file_inbox(path TEXT PRIMARY KEY, size INTEGER, mtime REAL, file_id TEXT, at TEXT);
"""
KINDS = {"xray": "Рентген", "photo": "Фото", "scan": "Скан / 3D", "doc": "Документ", "other": "Другое"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
BROWSER_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}  # shown as they are
ALLOWED = IMAGE_EXT | {".dcm", ".pdf", ".stl"}
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
        ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff", ".dcm": "application/dicom",
        ".pdf": "application/pdf", ".stl": "model/stl"}
MAX_BYTES = 15 * 1024 * 1024
THUMB = 320
INBOX_DAYS = 3


def root() -> Path:
    p = config.data_dir() / "files"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pdir(pid: str) -> Path:
    p = root() / re.sub(r"[^A-Za-z0-9_-]", "_", str(pid))[:80]
    p.mkdir(parents=True, exist_ok=True)
    return p


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_dicom(data: bytes) -> bool:
    return len(data) > 132 and data[128:132] == b"DICM"


def _ext(name: str, data: bytes) -> str:
    ext = Path(str(name or "")).suffix.lower()
    if _is_dicom(data):
        return ".dcm"
    return ".jpg" if ext == ".jpe" else ext


# -------------------------------------------------------------- previews --
def _dicom_image(data: bytes):
    """DICOM → (PIL image, meta). Windowing from the file when it has one, MONOCHROME1 inverted."""
    import numpy as np  # noqa: PLC0415
    import pydicom  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    ds = pydicom.dcmread(io.BytesIO(data), force=True)
    try:
        arr = ds.pixel_array
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"Снимок DICOM сжат способом, который программа пока не читает ({e}). "
                         "Сохраните его из программы визиографа в JPEG или PNG.") from None
    if arr.ndim == 3 and arr.shape[-1] not in (3, 4):  # several frames: the first one
        arr = arr[0]
    meta = {k: str(getattr(ds, k, "") or "") for k in ("Modality", "StudyDate", "BodyPartExamined", "Manufacturer",
                                                       "ManufacturerModelName", "PhotometricInterpretation")}
    if arr.ndim == 2:
        try:
            from pydicom.pixels import apply_voi_lut  # noqa: PLC0415
            arr = apply_voi_lut(arr, ds)
        except Exception:  # noqa: BLE001
            pass
        arr = arr.astype("float64")
        lo, hi = np.percentile(arr, 0.5), np.percentile(arr, 99.5)
        arr = np.clip((arr - lo) / max(hi - lo, 1e-6), 0, 1) * 255
        if meta["PhotometricInterpretation"].upper() == "MONOCHROME1":
            arr = 255 - arr
        img = Image.fromarray(arr.astype("uint8"), "L")
    else:
        img = Image.fromarray(arr.astype("uint8"))
    return img, meta


def make_previews(path: Path, ext: str) -> dict:
    """Writes <id>.view.* and <id>.thumb.jpg; returns width, height and what the file says about itself."""
    from PIL import Image, ImageOps  # noqa: PLC0415
    base = path.with_suffix("")
    info = {"width": None, "height": None, "meta": {}, "view": None}
    if ext not in IMAGE_EXT and ext != ".dcm":
        return info
    if ext == ".dcm":
        img, meta = _dicom_image(path.read_bytes())
        info["meta"] = {k: v for k, v in meta.items() if v}
        sd = meta.get("StudyDate", "")
        if re.fullmatch(r"\d{8}", sd):
            info["taken_at"] = f"{sd[:4]}-{sd[4:6]}-{sd[6:]}"
        view = base.parent / (base.name + ".view.png")
        img.save(view, "PNG", optimize=True)
        info["view"] = view.name
    else:
        img = Image.open(path)
        img = ImageOps.exif_transpose(img)
        if ext not in BROWSER_EXT:
            view = base.parent / (base.name + ".view.png")
            (img if img.mode in ("L", "RGB", "RGBA") else img.convert("RGB")).save(view, "PNG", optimize=True)
            info["view"] = view.name
    info["width"], info["height"] = img.size
    th = img.copy()
    if th.mode not in ("L", "RGB"):
        th = th.convert("RGB")
    th.thumbnail((THUMB, THUMB))
    th.save(base.parent / (base.name + ".thumb.jpg"), "JPEG", quality=82)
    return info


def _thumb_bytes(data: bytes, ext: str) -> bytes | None:
    """A small JPEG of an image that is not stored yet (for the visiograph folder list)."""
    from PIL import Image, ImageOps  # noqa: PLC0415
    try:
        img = _dicom_image(data)[0] if ext == ".dcm" else ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        img.thumbnail((200, 200))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=75)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


# ----------------------------------------------------------------- store --
class Files:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def count(self, pid) -> int:
        return self.db.one("SELECT COUNT(*) AS n FROM patient_files WHERE patient_id=? AND deleted=0", (pid,))["n"]

    def list(self, pid) -> list[dict]:
        rows = self.db.q("""SELECT id, patient_id, kind, title, tooth, taken_at, note, orig_name, ext, mime, size, width, height,
                                   meta, created_at, created_by FROM patient_files WHERE patient_id=? AND deleted=0
                            ORDER BY COALESCE(taken_at, substr(created_at,1,10)) DESC, created_at DESC""", (pid,))
        for r in rows:
            r["meta"] = json.loads(r["meta"] or "{}")
            r["kind_text"] = KINDS.get(r["kind"], r["kind"])
            r["image"] = r["ext"] in IMAGE_EXT or r["ext"] == ".dcm"
        return rows

    def add(self, pid, name, data: bytes, meta=None, who="") -> dict:
        meta = meta or {}
        if not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Пациент не найден")
        if not data:
            raise ValueError("Пустой файл")
        if len(data) > MAX_BYTES:
            raise ValueError(f"Файл больше {MAX_BYTES // 1024 // 1024} МБ. 3D-снимки (КТ) храните в программе томографа, "
                             "а сюда добавляйте нужные срезы картинками.")
        ext = _ext(name, data)
        if ext not in ALLOWED:
            raise ValueError("Можно добавить снимки (JPEG, PNG, TIFF, BMP, DICOM), PDF и STL")
        sha = hashlib.sha256(data).hexdigest()
        dup = self.db.one("SELECT id FROM patient_files WHERE patient_id=? AND sha256=? AND deleted=0", (pid, sha))
        if dup:
            return {**self.get_row(dup["id"]), "duplicate": True}
        fid = "F-" + uuid.uuid4().hex[:12]
        path = _pdir(pid) / (fid + ext)
        path.write_bytes(data)
        try:
            info = make_previews(path, ext)
        except ValueError:
            path.unlink(missing_ok=True)
            raise
        except Exception as e:  # noqa: BLE001  (a broken image: keep the file, no preview)
            log.warning("preview failed for %s: %s", name, e)
            info = {"width": None, "height": None, "meta": {}, "view": None}
        kind = meta.get("kind") if meta.get("kind") in KINDS else ("xray" if ext == ".dcm" else "photo" if ext in IMAGE_EXT else "doc")
        taken = str(meta.get("taken_at") or info.get("taken_at") or "")[:10] or None
        row = (fid, pid, kind, str(meta.get("title") or Path(str(name or "")).stem)[:200], str(meta.get("tooth") or "")[:40],
               taken, str(meta.get("note") or "")[:1000], str(name or "")[:200], ext, MIME.get(ext, "application/octet-stream"),
               len(data), sha, info["width"], info["height"], json.dumps(info["meta"], ensure_ascii=False), _now(), who or "", _now())
        with self.db.tx() as c:
            c.execute("""INSERT INTO patient_files(id, patient_id, kind, title, tooth, taken_at, note, orig_name, ext, mime, size,
                         sha256, width, height, meta, created_at, created_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
        return self.get_row(fid)

    def get_row(self, fid) -> dict:
        r = self.db.one("SELECT * FROM patient_files WHERE id=?", (fid,))
        if not r or r["deleted"]:
            raise ValueError("Файл не найден")
        r["meta"] = json.loads(r["meta"] or "{}")
        r["kind_text"] = KINDS.get(r["kind"], r["kind"])
        r["image"] = r["ext"] in IMAGE_EXT or r["ext"] == ".dcm"
        return r

    def content(self, fid, which="view") -> dict:
        """The file for the viewer: which = view | thumb | orig. Returned as a data: URL."""
        r = self.get_row(fid)
        d = _pdir(r["patient_id"])
        orig = d / (fid + r["ext"])
        cand = {"thumb": [d / f"{fid}.thumb.jpg"], "view": [d / f"{fid}.view.png", d / f"{fid}.view.jpg", orig], "orig": [orig]}[which]
        p = next((x for x in cand if x.exists()), None)
        if not p:
            raise ValueError("Файл не найден на диске. Возможно, его удалили из папки программы.")
        mime = "image/jpeg" if p.name.endswith(".jpg") else "image/png" if p.name.endswith(".png") else r["mime"]
        return {"id": fid, "name": r["orig_name"], "mime": mime, "url": f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()}

    def thumbs(self, ids) -> dict:
        out = {}
        for fid in list(ids or [])[:200]:
            try:
                out[fid] = self.content(fid, "thumb")["url"]
            except ValueError:
                pass
        return out

    def update(self, fid, meta) -> dict:
        self.get_row(fid)
        kind = meta.get("kind") if meta.get("kind") in KINDS else None
        taken = str(meta.get("taken_at") or "")[:10] or None
        with self.db.tx() as c:
            c.execute("""UPDATE patient_files SET kind=COALESCE(?, kind), title=?, tooth=?, taken_at=?, note=?, updated_at=? WHERE id=?""",
                      (kind, str(meta.get("title") or "")[:200], str(meta.get("tooth") or "")[:40], taken,
                       str(meta.get("note") or "")[:1000], _now(), fid))
        return self.get_row(fid)

    def delete(self, fid) -> bool:
        """The record is hidden and the files go to files/_deleted (kept until someone empties it by hand)."""
        r = self.get_row(fid)
        d, trash = _pdir(r["patient_id"]), root() / "_deleted"
        trash.mkdir(exist_ok=True)
        for p in d.glob(fid + "*"):
            try:
                shutil.move(str(p), str(trash / p.name))
            except OSError as e:
                log.warning("cannot move %s: %s", p, e)
        with self.db.tx() as c:
            c.execute("UPDATE patient_files SET deleted=1, updated_at=? WHERE id=?", (_now(), fid))
        return True

    # ------------------------------------------------ visiograph folder --
    @staticmethod
    def inbox_dir() -> str:
        return str(config.load_settings().get("files_inbox") or "")

    @staticmethod
    def save_inbox_dir(path: str) -> str:
        path = str(path or "").strip().strip('"')
        if path and not Path(path).is_absolute():
            raise ValueError("Укажите полный путь к папке, например C:\\Visiograph\\Images")
        config.save_settings({"files_inbox": path})
        return path

    def _inbox_files(self):
        d = self.inbox_dir()
        if not d:
            return None, []
        p = Path(d)
        if not p.is_dir():
            return f"Папка снимков визиографа недоступна: {d}", []
        border = (datetime.now() - timedelta(days=INBOX_DAYS)).timestamp()
        seen = {(r["path"], r["size"], r["mtime"]) for r in self.db.q("SELECT path, size, mtime FROM file_inbox")}
        out = []
        for f in sorted(p.rglob("*"), key=lambda x: x.stat().st_mtime if x.is_file() else 0, reverse=True)[:500]:
            try:
                if not f.is_file():
                    continue
                st = f.stat()
                if st.st_mtime < border or st.st_size > MAX_BYTES:
                    continue
                ext = f.suffix.lower()
                if ext not in IMAGE_EXT and ext != ".dcm" and not (ext == "" and st.st_size > 132):
                    continue
                if (str(f), st.st_size, round(st.st_mtime, 3)) in seen:
                    continue
                out.append((f, st))
            except OSError:
                continue
        return None, out[:40]

    def inbox(self) -> dict:
        err, items = self._inbox_files()
        rows = []
        for f, st in items:
            data = f.read_bytes()
            ext = _ext(f.name, data)
            if ext not in IMAGE_EXT and ext != ".dcm":
                continue
            th = _thumb_bytes(data, ext)
            rows.append({"name": str(f), "short": f.name, "size": st.st_size,
                         "at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                         "thumb": "data:image/jpeg;base64," + base64.b64encode(th).decode() if th else None})
        return {"dir": self.inbox_dir(), "error": err, "rows": rows}

    def inbox_import(self, pid, names, meta=None, who="") -> list[dict]:
        err, items = self._inbox_files()
        if err:
            raise ValueError(err)
        allowed = {str(f): (f, st) for f, st in items}
        out = []
        for n in names or []:
            if n not in allowed:
                raise ValueError("Снимок не найден в папке визиографа или уже добавлен")
            f, st = allowed[n]
            r = self.add(pid, f.name, f.read_bytes(), {"kind": "xray", **(meta or {})}, who)
            with self.db.tx() as c:
                c.execute("INSERT OR REPLACE INTO file_inbox(path, size, mtime, file_id, at) VALUES(?,?,?,?,?)",
                          (str(f), st.st_size, round(st.st_mtime, 3), r["id"], _now()))
            out.append(r)
        return out


def mirror(dest: Path) -> int:
    """Copy patient files that are new or changed to `dest` (used for the backup's second folder)."""
    src, n = root(), 0
    for p in src.rglob("*"):
        if not p.is_file() or "_deleted" in p.parts:
            continue
        t = dest / p.relative_to(src)
        try:
            if t.exists() and t.stat().st_size == p.stat().st_size:
                continue
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, t)
            n += 1
        except OSError as e:
            log.warning("mirror %s: %s", p, e)
    return n


def b64_bytes(b64: str) -> bytes:
    s = str(b64 or "")
    if s.startswith("data:"):
        s = s.split(",", 1)[1] if "," in s else ""
    try:
        return base64.b64decode(s, validate=False)
    except Exception:  # noqa: BLE001
        raise ValueError("Файл повреждён при передаче") from None
