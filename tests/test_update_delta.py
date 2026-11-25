"""3.12: updates «только изменения» and downloads that continue after a break.

Two versions of a program folder in miniature (an exe, a big library that does not change, the interface, the update
helper, a file that goes away) are packed the way build.ps1 does (pack_app.py writes dd-manifest.json), released the
way publish-update.ps1 does (update_sign.py: the whole encrypted installer, the delta from the previous version, the
encrypted list of files) and served by a fake GitHub with HTTP Range. Checked: the delta has only what changed and
nothing readable; a program of exactly that version with intact files downloads only the delta, assembles and checks
the new folder (unchanged files are hard links, not copies) and the helper puts it in place; any doubt — a changed
file, another version, no manifest, a damaged delta, a manifest not matching the signed one, an earlier failure —
gives the whole file; a broken download continues with Range (also after a restart), a server that ignores Range or
a wrong piece start over; a damaged file is never installed; the program of 3.11 reads the new latest.json and
downloads the whole file as before."""
import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(BASE / "data")
os.environ["DD_UPDATE_RETRY_S"] = "0.02"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import config  # noqa: E402
import installer  # noqa: E402
import manifest  # noqa: E402
import pack_app  # noqa: E402
import swap  # noqa: E402
import update_helper  # noqa: E402
import update_sign  # noqa: E402
import updates  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402
from update_feed import Feed  # noqa: E402

FAIL, OK = [], [0]
REAL_PROGRAM_DIR = updates.program_dir


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:500]}")


sign_key = Ed25519PrivateKey.generate()
config.UPDATE_PUBKEY = sign_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
aes = os.urandom(32)
config.UPDATE_KEY = aes.hex()
update_sign._load_key = lambda: sign_key
EXE = config.BRAND["exe"] + ".exe"
big = os.urandom(3_000_000)
dll = os.urandom(1_500_000)


def folder(ver, files):
    d = BASE / f"dist-{ver}" / "App"
    for rel, data in files.items():
        p = d.joinpath(*rel.split("/"))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return d


v1 = folder("3.12.0", {EXE: b"MZ exe 3.12.0 " + os.urandom(400_000), "_internal/python311.dll": dll,
                       "_internal/lib/big.bin": big, "_internal/ui/app.js": "ui 3.12 клиника".encode(),
                       "_internal/dd-update-helper.exe": b"MZ helper 1", "_internal/old_only.pyd": b"old"})
v2 = folder("3.13.0", {EXE: b"MZ exe 3.13.0 " + os.urandom(400_000), "_internal/python311.dll": dll,
                       "_internal/lib/big.bin": big, "_internal/ui/app.js": "ui 3.13 клиника".encode(),
                       "_internal/ui/new.css": b"body{}", "_internal/dd-update-helper.exe": b"MZ helper 1"})
zip1, zip2 = BASE / "app-3.12.0.zip", BASE / "app-3.13.0.zip"
pack_app.main([str(v1), str(zip1), "--version", "3.12.0", "--exe", EXE])
pack_app.main([str(v2), str(zip2), "--version", "3.13.0", "--exe", EXE])
m1, m2 = manifest.load(v1), manifest.load(v2)
check("pack: the manifest is written into the folder and the zip", m1 and m1["version"] == "3.12.0"
      and manifest.NAME in zipfile.ZipFile(zip1).namelist() and manifest.NAME not in m1["files"], m1)
check("pack: every file with size and SHA-256", m1["files"]["_internal/lib/big.bin"] == [len(big), manifest.file_sha(v1 / "_internal/lib/big.bin")])
check("manifest: paths with /", all("\\" not in k for k in m1["files"]), list(m1["files"]))
check("manifest: a path out of the folder is refused", not manifest.valid({**m1, "files": {**m1["files"], "../evil.dll": [1, "0" * 64]}}))
setup1, setup2 = BASE / "DentalDesk-3.12.0.exe", BASE / "DentalDesk-3.13.0.exe"  # the whole installers
setup1.write_bytes(b"MZ setup 3.12.0 " + os.urandom(6_000_000))
setup2.write_bytes(b"MZ setup 3.13.0 " + os.urandom(6_000_000))

# ======================================================================= release (update_sign.py)
mans = BASE / "release-manifests"
feed12, feed13 = BASE / "feed-3.12.0", BASE / "feed-3.13.0"
update_sign.release(argparse.Namespace(exe=str(setup1), out=str(feed12), notes="", version="", app_zip=str(zip1),
                                       prev_manifest="", manifests=str(mans)))
doc12 = json.loads((feed12 / "latest.json").read_text(encoding="utf-8"))
check("release 3.12: no delta without the previous list of files", "delta" not in doc12 and updates.verify(doc12), doc12)
check("release 3.12: the digest of its list of files is signed", doc12["manifest"] == manifest.digest(m1))
check("release 3.12: the list kept for the next release", json.loads((mans / "manifest-3.12.0.json").read_text(encoding="utf-8")) == m1)
sealed = (feed12 / "manifest-3.12.0.bin").read_text(encoding="ascii")
check("release 3.12: the list in the feed is encrypted", EXE not in sealed and "big.bin" not in sealed
      and json.loads(updates.open_text(sealed, aes, updates.MANIFEST_AAD)) == m1)
try:
    update_sign.release(argparse.Namespace(exe=str(setup2), out=str(BASE / "feed-x"), notes="", version="", app_zip=str(zip1),
                                           prev_manifest="", manifests=""))
    FAIL.append("release: app.zip of another version accepted")
except SystemExit as e:
    check("release: app.zip of another version refused", "другой" in str(e) or "версии" in str(e), e)

update_sign.release(argparse.Namespace(exe=str(setup2), out=str(feed13), notes="", version="", app_zip=str(zip2),
                                       prev_manifest=str(mans / "manifest-3.12.0.json"), manifests=str(mans)))
doc = json.loads((feed13 / "latest.json").read_text(encoding="utf-8"))
d = doc.get("delta") or {}
check("release 3.13: delta from 3.12.0", d.get("from") == "3.12.0" and d.get("from_manifest") == manifest.digest(m1)
      and d.get("file") == "delta-3.12.0-3.13.0.bin" and (feed13 / d["file"]).stat().st_size == d["size"], doc)
check("release 3.13: signed together with the delta", updates.verify(doc) and not updates.verify({**doc, "delta": {**d, "from": "3.11.0"}}))
check("release 3.13: the delta is much smaller than the whole file", d["size"] < doc["size"] / 4, (d.get("size"), doc["size"]))
raw = (feed13 / d["file"]).read_bytes()
check("release 3.13: nothing readable in the delta", EXE.encode() not in raw and b"delta.json" not in raw and "клиника".encode() not in raw)
plain_delta = BASE / "delta-plain.zip"
check("release 3.13: the delta decrypts to what latest.json says", updates.decrypt_file(feed13 / d["file"], plain_delta, aes) == d["plain_sha256"])
with zipfile.ZipFile(plain_delta) as z:
    meta = json.loads(z.read("delta.json"))
    inside = sorted(n for n in z.namelist() if n.startswith("files/"))
check("delta: only the changed and new files", inside == sorted(f"files/{r}" for r in (EXE, "_internal/ui/app.js", "_internal/ui/new.css")), inside)
check("delta: the unchanged helper does not travel", "files/_internal/dd-update-helper.exe" not in inside)
check("delta: the removed file listed", meta["removed"] == ["_internal/old_only.pyd"] and meta["manifest"] == m2, meta.get("removed"))
check("delta: count in latest.json", d["files"] == 3, d)
check("verify: the delta file is checked too", update_sign.verify(argparse.Namespace(file=str(feed13 / "latest.json"))) == 0)

# ======================================================================= the program of 3.12.0 updates «только изменения»
PROG = BASE / "Programs" / "App"
installer.install_zip(zip1, str(PROG))  # what the 3.12.0 installer put on the computer
check("installed folder carries its manifest", manifest.load(PROG) == m1)
config.VERSION = "3.12.0"
updates.program_dir = lambda: PROG
gh = Feed(feed13)
config.save_settings({"update_url": gh.url})


def fresh():
    """A computer that has not downloaded anything yet."""
    shutil.rmtree(updates.updates_dir(), ignore_errors=True)
    return updates.Updater()


u = fresh()
st = u.check()
check("check: «только изменения» offered with its size", st["available"] and st["delta"] and st["dl_size"] == d["size"]
      and st["size"] == doc["plain_size"], st)
stage = Path(u._download())
u.state["ready"] = str(stage)
check("delta: downloaded the delta only", gh.count(d["file"]) == 1 and gh.count(doc["file"]) == 0, gh.hits)
check("delta: mode", u.state["mode"] == "delta", u.state)
check("delta: the new folder sits next to the program", stage.parent == PROG and stage.name.startswith(".new-"), stage)
check("delta: the new folder is exactly 3.13.0", manifest.check(stage, m2) == [] and manifest.load(stage) == m2)
check("delta: the removed file is not in it", not (stage / "_internal" / "old_only.pyd").exists())
check("delta: unchanged files are hard links, not second copies", os.path.samefile(stage / "_internal/lib/big.bin", PROG / "_internal/lib/big.bin"))
check("delta: the program folder untouched while it runs", manifest.check(PROG, m1) == [] and manifest.load(PROG) == m1)
check("delta: no decrypted leftovers", not list(updates.updates_dir().glob("*.part")) and not (updates.updates_dir() / "delta.zip.part").exists())
check("delta: the checked delta is kept for the clinic's computers", updates.shared(d["sha256"]) is not None
      and updates.lan_have(d["sha256"])["have"])

started = []
real_popen = updates.subprocess.Popen
updates.subprocess.Popen = lambda args, **kw: started.append(args)
os.environ["DD_UPDATE_RUN"] = "1"
try:
    u.install()
finally:
    updates.subprocess.Popen = real_popen
check("install: the helper is started with a job", started and started[0][0].endswith("dd-update-helper.exe")
      and Path(started[0][0]).read_bytes() == b"MZ helper 1", started)
job = json.loads(Path(started[0][1]).read_text(encoding="utf-8"))
check("install: the job names the folder, the program and its window", job["stage"] == str(stage) and job["target"] == str(PROG)
      and job["exe"] == EXE and job["title"] == config.APP_TITLE, job)
launched, said = [], []
real_launch, real_message = swap.launch, swap.message
swap.launch = lambda exe, args: launched.append(exe)
swap.message = lambda text, title: said.append(text)
try:
    rc = update_helper.main([started[0][1]])
finally:
    swap.launch, swap.message = real_launch, real_message
check("helper: the new version is in place", rc == 0 and manifest.check(PROG, m2) == [] and manifest.load(PROG) == m2, (rc, said))
check("helper: the removed file is gone", not (PROG / "_internal" / "old_only.pyd").exists())
check("helper: no leftovers", not [n for n in os.listdir(PROG) if n.startswith((".new-", ".old-"))], os.listdir(PROG))
check("helper: the program opened again", launched == [str(PROG / EXE)] and not said, (launched, said))
u.state["installing"] = False

# a stage that changed after the check is not installed
u2 = fresh()
installer.install_zip(zip1, str(PROG))
u2.check()
stage = Path(u2._download())
u2.state["ready"] = str(stage)
(stage / "_internal" / "ui" / "app.js").write_bytes(b"evil")
try:
    u2.install()
    FAIL.append("install: a changed stage was installed")
except ValueError as e:
    check("install: a stage changed after the check is refused and removed", "изменились" in str(e) and not stage.exists(), e)

# the helper fails: the old version stays, opens again, and the next attempt is the whole file
u3 = fresh()
u3.check()
stage = Path(u3._download())
(stage / EXE).unlink()  # the swap cannot go on without the program in the new folder
jp = BASE / "job.json"
jp.write_text(json.dumps({"stage": str(stage), "target": str(PROG), "exe": EXE, "title": "t", "name": "Программа",
                          "failed": str(updates._failed_mark("3.13.0")), "retry_s": 0.01}), encoding="utf-8")
launched.clear(), said.clear()
swap.launch = lambda exe, args: launched.append(exe)
swap.message = lambda text, title: said.append(text)
try:
    rc = update_helper.main([str(jp)])
finally:
    swap.launch, swap.message = real_launch, real_message
check("helper failed: the old version as it was", rc == 1 and manifest.check(PROG, m1) == [], rc)
check("helper failed: opened again and said so", launched == [str(PROG / EXE)] and said and "целиком" in said[0], (launched, said))
check("helper failed: no stage left", not stage.exists())

# an antivirus holds the new exe for a moment: the swap is put back and tried again
updates._failed_mark("3.13.0").unlink()
u4 = fresh()
u4.check()
stage = Path(u4._download())
jp.write_text(json.dumps({"stage": str(stage), "target": str(PROG), "exe": EXE, "title": "t", "name": "Программа",
                          "failed": str(updates._failed_mark("3.13.0")), "retry_s": 0.01}), encoding="utf-8")
real_replace, busy_once = os.replace, [1]


def held(a, b):
    if busy_once[0] and os.path.basename(str(a)) == EXE and ".new-" in str(a):
        busy_once[0] = 0
        raise PermissionError("файл проверяет антивирус")
    return real_replace(a, b)


launched.clear(), said.clear()
swap.launch = lambda exe, args: launched.append(exe)
swap.message = lambda text, title: said.append(text)
os.replace = held
try:
    rc = update_helper.main([str(jp)])
finally:
    os.replace = real_replace
    swap.launch, swap.message = real_launch, real_message
check("helper: a file held for a moment — tried again, installed", rc == 0 and manifest.check(PROG, m2) == [] and not said
      and not updates._failed_mark("3.13.0").exists(), (rc, said))
check("helper: no leftovers after the retry", not [n for n in os.listdir(PROG) if n.startswith((".new-", ".old-"))], os.listdir(PROG))
installer.install_zip(zip1, str(PROG))
updates._failed_mark("3.13.0").write_text("x", encoding="utf-8")
st = updates.Updater().check()
check("after a failed install: the whole file next time", not st["delta"] and st["dl_size"] == doc["size"], st)
updates._failed_mark("3.13.0").unlink()

# ======================================================================= any doubt — the whole file
setup2_bytes = setup2.read_bytes()


def whole(name, before=None):
    uu = fresh()
    if before:
        before()
    uu.check()
    n0, d0 = gh.count(doc["file"]), gh.count(d["file"])
    try:
        path = uu._download()
    except Exception as e:  # noqa: BLE001
        FAIL.append(f"{name}: {e}")
        return None
    check(f"{name}: the whole file downloaded and checked", uu.state["mode"] == "full" and Path(path).read_bytes() == setup2_bytes
          and gh.count(doc["file"]) == n0 + 1, (uu.state, gh.hits[-3:]))
    check(f"{name}: no stage left in the program folder", not [x for x in os.listdir(PROG) if x.startswith(".new-")], os.listdir(PROG))
    return uu, d0


installer.install_zip(zip1, str(PROG))
lib = PROG / "_internal" / "lib" / "big.bin"
lib.write_bytes(big[:-1] + bytes([big[-1] ^ 1]))  # a library changed by hand (an antivirus, a copy over it)
r = whole("a changed file of the program")
if r:
    check("a changed file: found before downloading the delta", gh.count(d["file"]) == r[1])
lib.write_bytes(big)

config.VERSION = "3.11.9"
st = fresh().check()
check("another version than «from»: the whole file", st["available"] and not st["delta"] and st["dl_size"] == doc["size"], st)
config.VERSION = "3.12.0"

(PROG / manifest.NAME).rename(PROG / "keep.json")
st = fresh().check()
check("an installed folder without a manifest (≤3.11): the whole file", not st["delta"], st)
(PROG / "keep.json").rename(PROG / manifest.NAME)

updates.program_dir = lambda: None
st = fresh().check()
check("not the installed folder (a run from the sources): the whole file", not st["delta"], st)
check("a run from the sources is not an installed folder", REAL_PROGRAM_DIR() is None)
updates.program_dir = lambda: PROG

other = dict(m1, files={**m1["files"], "_internal/extra.txt": [1, "0" * 64]})
manifest.write(PROG, other)
st = fresh().check()
check("a folder of another build of 3.12.0 (its list differs): the whole file", not st["delta"], st)
manifest.write(PROG, m1)

damaged = BASE / "feed-damaged-delta"
shutil.copytree(feed13, damaged)
b = bytearray((damaged / d["file"]).read_bytes())
b[len(b) // 2] ^= 1
(damaged / d["file"]).write_bytes(bytes(b))
gh.dir = damaged
r = whole("a damaged delta")
check("a damaged delta: tried, then the whole file", r and gh.count(d["file"]) >= r[1] + 1, gh.hits[-4:])
check("a damaged delta: not kept, not given to others", not updates.shared(d["sha256"]))
gh.dir = feed13

forged = BASE / "feed-forged"
shutil.copytree(feed13, forged)
(forged / "latest.json").write_text(json.dumps(updates.sign({**doc, "manifest": "0" * 64}, sign_key)), encoding="utf-8")
gh.dir = forged
whole("a delta whose list of files is not the signed one")
gh.dir = feed13

# ======================================================================= downloads that continue after a break
config.VERSION = "3.11.0"  # the whole file: 6 MB
uu = fresh()
uu.check()
gh.hits.clear()
gh.cut[doc["file"]] = 1_000_000
path = uu._download()
check("broken off: continued with Range from where it stopped", Path(path).read_bytes() == setup2_bytes
      and gh.ranges(doc["file"]) == [None, "bytes=1000000-"], gh.hits)

uu = fresh()
uu.check()
enc_full = (feed13 / doc["file"]).read_bytes()
(updates.share_dir() / (doc["file"] + ".part")).write_bytes(enc_full[:2_097_152])  # the program was closed mid-way
gh.hits.clear()
path = uu._download()
check("after a restart: only the rest is downloaded", Path(path).read_bytes() == setup2_bytes
      and gh.ranges(doc["file"]) == ["bytes=2097152-"], gh.hits)

uu = fresh()
uu.check()
(updates.share_dir() / (doc["file"] + ".part")).write_bytes(enc_full[:500_000])
gh.no_range, gh.hits[:] = True, []
path = uu._download()
gh.no_range = False
check("a server that ignores Range: from the start, still right", Path(path).read_bytes() == setup2_bytes
      and len(gh.ranges(doc["file"])) == 1, gh.hits)

uu = fresh()
uu.check()
(updates.share_dir() / (doc["file"] + ".part")).write_bytes(os.urandom(300_000))  # a wrong piece
gh.hits.clear()
path = uu._download()
check("a wrong piece: noticed by the checksum, downloaded again from the start", Path(path).read_bytes() == setup2_bytes
      and gh.ranges(doc["file"]) == ["bytes=300000-", None], gh.hits)

config.VERSION = "3.12.0"
uu = fresh()
uu.check()
gh.hits.clear()
gh.cut[d["file"]] = 40_000
stage = Path(uu._download())
check("the delta continues after a break too", uu.state["mode"] == "delta" and manifest.check(stage, m2) == []
      and gh.ranges(d["file"]) == [None, "bytes=40000-"], gh.hits)
shutil.rmtree(stage, ignore_errors=True)

# checksum: a damaged file is never installed
bad = BASE / "feed-bad"
shutil.copytree(feed13, bad)
for name in (doc["file"], d["file"]):
    b = bytearray((bad / name).read_bytes())
    b[100] ^= 1
    (bad / name).write_bytes(bytes(b))
gh.dir = bad
uu = fresh()
uu.check()
try:
    uu._download()
    FAIL.append("damaged files accepted")
except ValueError as e:
    check("damaged files: refused with a clear message", "контрольная" in str(e), e)
check("damaged files: nothing ready, nothing kept", not updates.shared(doc["sha256"]) and not updates.shared(d["sha256"])
      and not list(updates.share_dir().glob("*.part")) and not list(updates.updates_dir().glob("*.exe")))
gh.dir = feed13

# no connection in the middle: a calm message, the piece stays for «Повторить»
config.VERSION = "3.11.0"
uu = fresh()
uu.check()
gh.cut[doc["file"]] = 700_000
real_open_from = updates._open_from
calls = [0]


def flaky(url, start):
    calls[0] += 1
    if calls[0] > 1:
        raise OSError("сеть пропала")
    return real_open_from(url, start)


updates._open_from = flaky
uu.start_download()
for _ in range(400):
    if not uu.state["downloading"]:
        break
    __import__("time").sleep(0.02)
updates._open_from = real_open_from
part = updates.share_dir() / (doc["file"] + ".part")
check("offline mid-way: «Повторить» continues", "продолжится" in uu.state["error"] and part.exists()
      and part.stat().st_size == 700_000, (uu.state["error"], part.exists() and part.stat().st_size))
gh.hits.clear()
uu.start_download()
for _ in range(400):
    if not uu.state["downloading"]:
        break
    __import__("time").sleep(0.02)
check("«Повторить»: the rest only", uu.state["ready"] and Path(uu.state["ready"]).read_bytes() == setup2_bytes
      and gh.ranges(doc["file"]) == ["bytes=700000-"], (uu.state, gh.hits))

# ======================================================================= the program of 3.11 and the new latest.json
spec = importlib.util.spec_from_file_location("updates_311", ROOT / "tests" / "fixtures" / "updates_311.py")
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
config.VERSION = "3.11.0"
shutil.rmtree(updates.updates_dir(), ignore_errors=True)
check("3.11: the new latest.json is signed for it too", old.verify(doc))
ou = old.Updater()
st = ou.check()
check("3.11: the new fields do not disturb the check", st["available"] and st["latest"] == "3.13.0" and not st["error"], st)
gh.hits.clear()
path = ou._download()
check("3.11: downloads the whole file as before", Path(path).read_bytes() == setup2_bytes and gh.count(doc["file"]) == 1
      and gh.count(d["file"]) == 0, gh.hits)
check("3.11: the 3.12 feed without a delta too", old.verify(doc12))

# ======================================================================= publishing (publish_update.py, gh mocked)
import publish_update  # noqa: E402

GH = []
FEEDS = {"v3.12.0": feed12, "v3.13.0": feed13, "v3.11.0": None}
LIVE = ["v3.12.0"]


class R:
    def __init__(self, code=0, out=""):
        self.returncode, self.stdout, self.stderr = code, out, ""


def fake_gh(*args, check=True):
    GH.append(args)
    if args[:2] == ("release", "view") and args[2] == "--repo":
        return R(0, json.dumps({"tagName": LIVE[0]}))
    if args[:2] in (("repo", "view"), ("release", "view")):
        return R(1)
    if args[:2] == ("release", "download"):
        tag, pattern, where = args[2], args[args.index("--pattern") + 1], Path(args[args.index("--dir") + 1])
        src = FEEDS.get(tag)
        if tag == "v3.11.0" and pattern == "latest.json":
            (where / "latest.json").write_text(json.dumps(updates.sign({**doc12, "version": "3.11.0", "manifest": ""}, sign_key)),
                                               encoding="utf-8")
            return R(0)
        if not src or not (src / pattern).exists():
            return R(1)
        shutil.copy2(src / pattern, where / pattern)
        return R(0)
    return R(0)


publish_update._gh = fake_gh
out_m = BASE / "prev-manifest.json"
keep = BASE / "keep-manifests"
rc = publish_update.prev_manifest("o/r", keep, out_m)
check("prev manifest: taken from the feed when not kept here", rc == 0 and json.loads(out_m.read_text(encoding="utf-8")) == m1
      and (keep / "manifest-3.12.0.json").exists(), rc)
GH.clear()
rc = publish_update.prev_manifest("o/r", keep, out_m)
check("prev manifest: the kept copy is used (checked against the signed digest)", rc == 0
      and not any("manifest-3.12.0.bin" in a for c in GH for a in c), GH)
(keep / "manifest-3.12.0.json").write_text(json.dumps({**m1, "version": "3.12.0", "exe": "Other.exe"}), encoding="utf-8")
rc = publish_update.prev_manifest("o/r", keep, out_m)
check("prev manifest: a kept copy that differs from the signed one is replaced", rc == 0
      and json.loads((keep / "manifest-3.12.0.json").read_text(encoding="utf-8")) == m1, rc)
LIVE[0] = "v3.11.0"
out_m.unlink()
rc = publish_update.prev_manifest("o/r", keep, out_m)
check("prev manifest: a release before 3.12 has none — the whole file only", rc == 1 and not out_m.exists(), rc)
GH.clear()
real_open = updates._open


class Live:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, *a): return self.body


updates._open = lambda url, **kw: Live(json.dumps(doc).encode())
try:
    rc = publish_update.github_publish(feed13, doc, "o/r")
finally:
    updates._open = real_open
create = next(c for c in GH if c[:2] == ("release", "create"))
check("publish: the whole file, the delta and the list of files go up before latest.json",
      rc == 0 and [Path(a).name for a in create[3:6]] == [doc["file"], d["file"], "manifest-3.13.0.bin"]
      and GH[GH.index(create) + 1][3].endswith("latest.json"), create)
dest = BASE / "published"
sys.argv = ["publish_update.py", str(feed13), "--dest", str(dest)]
publish_update.main()
check("publish to a folder: the delta goes too", (dest / d["file"]).exists() and (dest / "latest.json").exists())

# ======================================================================= the window shows it
js = (ROOT / "app" / "ui" / "platform.js").read_text(encoding="utf-8")
check("window: «только изменения» and its size", "только изменения" in js and "updSize(st)" in js)
check("window: where the download comes from", "updNote" in js and "u.note" in js)
import main  # noqa: E402

msrc = Path(main.__file__).read_text(encoding="utf-8")
check("status carries the note and the size", '"note": us.get("note")' in msrc and '"dl_size"' in msrc)

gh.stop()
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
