"""Installer (2.6.1): the program folder is unpacked once and updated in place; data folders are never touched."""
import os
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import config  # noqa: E402
import installer  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


exe = config.BRAND["exe"] + ".exe"
tmp = Path(tempfile.mkdtemp())


def make_zip(path, version, extra=()):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(exe, f"exe {version}")
        z.writestr("_internal/base_library.zip", f"lib {version}")
        z.writestr("_internal/ui/index.html", f"ui {version}")
        for name in extra:
            z.writestr(name, version)
    return path


os.environ["APP_INSTALL_DIR"] = str(tmp / "Programs" / "App")
target = Path(installer.install_dir())
check("install dir from env", target == (tmp / "Programs" / "App").resolve())
check("target exe", installer.target_exe() == str(target / exe))

# fresh install
got = installer.install_zip(make_zip(tmp / "v1.zip", "1", ["_internal/old_only.pyd"]), str(target))
check("exe installed", Path(got).read_text() == "exe 1")
check("folder installed", (target / "_internal" / "ui" / "index.html").read_text() == "ui 1")

# an older single-file install leaves just the exe; a user file next to it must survive
(target / "notes.txt").write_text("keep")
got = installer.install_zip(make_zip(tmp / "v2.zip", "2"), str(target))
check("exe updated", Path(got).read_text() == "exe 2")
check("folder updated", (target / "_internal" / "base_library.zip").read_text() == "lib 2")
check("files of the old version removed", not (target / "_internal" / "old_only.pyd").exists())
check("other files kept", (target / "notes.txt").read_text() == "keep")
check("no staging leftovers", not [p for p in os.listdir(target) if p.startswith((".new-", ".old-"))], os.listdir(target))

# a broken installer leaves the installed version as it was
bad = tmp / "bad.zip"
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("readme.txt", "no exe")
try:
    installer.install_zip(bad, str(target))
    FAIL.append("broken zip: expected a refusal")
except RuntimeError:
    OK[0] += 1
check("broken zip keeps the old version", (target / exe).read_text() == "exe 2")

# leftovers of an interrupted update are cleaned up
(target / ".old-123").mkdir()
(target / ".new-456").mkdir()
installer.install_zip(make_zip(tmp / "v3.zip", "3"), str(target))
check("leftovers cleaned", not [p for p in os.listdir(target) if p.startswith((".new-", ".old-"))], os.listdir(target))

# nothing runs from the exe: no need to close anything; the data folder is a different one
check("not locked", installer.close_running(str(target / exe), seconds=1) is True)
check("data folder is separate", os.path.normcase(str(config.data_dir())) != os.path.normcase(str(target))
      and not str(config.data_dir()).startswith(str(target)))
check("dev run is not a folder build", installer.is_onedir() is False)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
