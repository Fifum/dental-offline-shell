"""Automatic backups: making and checking a copy, rotation, second folder, restore with a safety copy."""
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import backup  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
from main import Api  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        return str(e)
    return None


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
patients0 = d.one("SELECT COUNT(*) n FROM patients")["n"]
check("demo has patients", patients0 > 0)

# ---- status before any copy
st = backup.status()
check("no copies yet", st["count"] == 0 and st["last"] is None and st["warn"])
check("warning hidden right after start", backup.warning() is None)

# ---- one copy
r = a.backup_now()
p = backup.folder() / r["name"]
check("copy file exists", p.is_file(), r)
check("name pattern", backup._parse(r["name"]) is not None and r["name"].endswith("-manual.zip"), r["name"])
with zipfile.ZipFile(p) as z:
    names = set(z.namelist())
    meta = json.loads(z.read("meta.json"))
check("zip holds db, settings, meta", {"clinic.db", "meta.json"} <= names and ("settings.json" in names) == config.SETTINGS_PATH.exists(), names)
check("meta counts", meta["counts"].get("patients") == patients0 and meta["version"] == config.VERSION, meta)
tmp = backup._extract_db(p)
check("copy passes integrity check", backup._check_db(tmp)["patients"] == patients0)
os.remove(tmp)
check("no temp files left", not [f for f in backup.folder().iterdir() if f.suffix in (".db", ".part")],
      list(backup.folder().iterdir()))
st = backup.status()
check("status after copy", st["count"] == 1 and st["last"]["name"] == r["name"] and st["warn"] is None, st)
check("api status has no warning", not a.status().get("backup_warn"))

# ---- broken copy is refused
bad = backup.folder() / "clinic-2020-01-01_00-00-00-manual.zip"
bad.write_bytes(b"not a zip")
check("broken zip refused", "повреждён" in (raises(backup._extract_db, bad) or ""))
bad.unlink()
bad_db = backup.folder() / "x.db"
con = sqlite3.connect(bad_db); con.execute("CREATE TABLE t(a)"); con.commit(); con.close()
with zipfile.ZipFile(backup.folder() / "clinic-2020-01-02_00-00-00.zip", "w") as z:
    z.write(bad_db, "other.db")
check("zip without clinic.db refused", "нет базы" in (raises(backup._extract_db, backup.folder() / "clinic-2020-01-02_00-00-00.zip") or ""))
(backup.folder() / "clinic-2020-01-02_00-00-00.zip").unlink(); bad_db.unlink()

# ---- rotation: all of the last 2 days, one per day up to 30 days, nothing older
rot = Path(tempfile.mkdtemp())
now = datetime(2026, 11, 8, 12, 0, 0)
made = []
for hours in [0, 3, 20, 30, 50, 54, 60, 75, 24 * 10, 24 * 10 + 2, 24 * 31, 24 * 45]:
    t = now - timedelta(hours=hours)
    f = rot / f"clinic-{t:%Y-%m-%d_%H-%M-%S}.zip"
    f.write_bytes(b"x"); made.append((hours, f))
removed = backup.rotate(rot, {"keep_all_days": 2, "keep_days": 30}, now)
left = {h for h, f in made if f.exists()}
check("keeps everything of the last 2 days", {0, 3, 20, 30} <= left, left)
check("one per older day", 50 in left and 54 not in left and 60 not in left and 75 in left, left)
check("day 10: newest kept", 240 in left and 242 not in left, left)
check("older than 30 days deleted", 24 * 31 not in left and 24 * 45 not in left, left)
check("rotate returns removed names", len(removed) == len(made) - len(left))
only = Path(tempfile.mkdtemp()); f = only / "clinic-2020-01-01_00-00-00.zip"; f.write_bytes(b"x")
backup.rotate(only, {"keep_all_days": 2, "keep_days": 30}, now)
check("the newest copy is never deleted", f.exists())

# ---- settings validation
check("interval range", "от 1 до 24" in (raises(a.backup_settings_save, {"interval_h": 0}) or ""))
check("keep days >= keep all", raises(a.backup_settings_save, {"keep_all_days": 10, "keep_days": 5}) is not None)
check("relative extra dir refused", "полный путь" in (raises(a.backup_settings_save, {"extra_dir": "backups"}) or ""))
check("same folder refused", "другом диске" in (raises(a.backup_settings_save, {"extra_dir": str(backup.folder())}) or ""))
st = a.backup_settings_save({"interval_h": 3, "keep_all_days": 2, "keep_days": 20})
check("settings saved", st["settings"]["interval_h"] == 3 and backup.settings()["keep_days"] == 20)

# ---- second folder: missing flash drive -> warning, main copy still made
missing = Path(tempfile.gettempdir()) / "no-such-drive-7f3a" / "x"
a.backup_settings_save({"extra_dir": str(missing)})
r2 = a.backup_now()
check("main copy made without the drive", (backup.folder() / r2["name"]).is_file())
st = backup.status()
check("extra error shown", st["extra"]["error"] and "недоступна" in st["extra"]["error"] and not st["extra"]["available"], st["extra"])
check("status bar warns about the drive", "недоступна" in (a.status().get("backup_warn") or ""))
drive = Path(tempfile.mkdtemp())
a.backup_settings_save({"extra_dir": str(drive)})
r3 = a.backup_now()
ex = drive / backup.EXTRA_SUBDIR / r3["name"]
check("copy written to second folder", ex.is_file() and ex.stat().st_size == (backup.folder() / r3["name"]).stat().st_size)
st = backup.status()
check("extra ok", st["extra"]["available"] and st["extra"]["error"] is None and st["extra"]["count"] == 1, st["extra"])

# ---- listing from both folders
only_extra = drive / backup.EXTRA_SUBDIR / "clinic-2026-01-05_10-00-00.zip"
import shutil  # noqa: E402
shutil.copy2(ex, only_extra)
lst = a.backup_list()
check("listing newest first", lst[0]["created"] >= lst[-1]["created"])
check("listing includes second-folder-only copy", any(x["where"] == "extra" and x["name"] == only_extra.name for x in lst))
check("listing has counts", all("counts" in x for x in lst if x["where"] == "main"))
check("restore refuses foreign paths", "не найдена" in (raises(backup.find, "main", "..\\settings.json") or ""))
check("restore refuses unknown name", "не найдена" in (raises(backup.find, "main", "clinic-2001-01-01_00-00-00.zip") or ""))

# ---- restore round-trip
good = r3["name"]
pid = d.one("SELECT id FROM patients LIMIT 1")["id"]
d.add_note(pid, "после копии")
with d.tx() as c:
    c.execute("DELETE FROM visits")
check("data changed after the copy", d.one("SELECT COUNT(*) n FROM visits")["n"] == 0)
auth.set_current_user({"id": 2, "role": "admin", "name": "Админ"})
check("only director restores", "только директор" in (raises(a.backup_restore, "main", good) or ""))
auth.set_current_user({"id": 1, "role": "director", "name": "Директор"})
before = {x["name"] for x in backup.listing()}
res = a.backup_restore("main", good)
auth.set_current_user(None)
check("restore result", res["restored"] == good and res["restart"] is True, res)
check("visits are back", d.one("SELECT COUNT(*) n FROM visits")["n"] > 0)
check("later note gone", not d.q("SELECT 1 FROM notes WHERE text='после копии'"))
check("same connection still works", d.one("SELECT COUNT(*) n FROM patients")["n"] == patients0)
safety = res["safety"]
check("safety copy made", safety not in before and safety.endswith("-before-restore.zip") and (backup.folder() / safety).is_file())
# the safety copy holds the state just before restoring: no visits, with the note
tmp = backup._extract_db(backup.folder() / safety)
con = sqlite3.connect(tmp)
check("safety copy has the newer data", con.execute("SELECT COUNT(*) FROM visits").fetchone()[0] == 0
      and con.execute("SELECT COUNT(*) FROM notes WHERE text='после копии'").fetchone()[0] == 1)
con.close(); os.remove(tmp)
res2 = a.backup_restore("main", safety)
check("safety copy can be restored back", d.one("SELECT COUNT(*) n FROM visits")["n"] == 0 and res2["restored"] == safety)
a.backup_restore("main", good)
check("restore from second folder", a.backup_restore("extra", r3["name"])["restored"] == r3["name"])

# ---- the worker: copy at start when due, none on exit right after
for f in backup.folder().iterdir():
    f.unlink()
w = backup.BackupWorker(d.path)
w.CHECK_SECONDS = 3600
w.start()
w.join(timeout=0.01)
import time  # noqa: E402
for _ in range(50):
    if backup.status()["count"]:
        break
    time.sleep(0.1)
check("copy at start", backup.status()["count"] == 1 and backup.status()["last"]["reason"] == "start", backup.status()["last"])
w.stop()
check("no extra copy on exit right after one", backup.status()["count"] == 1)
old = backup.folder() / backup.status()["last"]["name"]
os.replace(old, backup.folder() / "clinic-2026-01-01_00-00-00-start.zip")
w2 = backup.BackupWorker(d.path); w2.stop()
check("copy on exit when the last is old", any(x["reason"] == "exit" for x in backup.listing()))
a.backup_settings_save({"enabled": False})
w3 = backup.BackupWorker(d.path)
check("disabled: nothing due", w3._due() is False)
check("disabled: warning", "выключены" in (backup.status()["warn"] or ""))
a.backup_settings_save({"enabled": True})

# ---- old copy warning
for f in backup.folder().iterdir():
    f.unlink()
(backup.folder() / "clinic-2026-01-01_00-00-00.zip").write_bytes(b"x")
check("old copy warning", "дн. назад" in (backup.status()["warn"] or ""))

# ---- permissions map
for m in ("backup_status", "backup_now", "backup_list", "backup_settings_save", "backup_restore"):
    check(f"perm {m}", auth.METHOD_PERMS.get(m) == "settings")
check("restore audited", "backup_restore" in auth.AUDITED)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
