"""3.1: updates from a GitHub release feed — encrypted installer, check once a minute without the API limit, any
employee updates from the «Вышла новая версия» toast.

A local HTTP server plays GitHub: /<owner>/<repo>/releases/latest/download/<file> answers 302 to an asset address
(like objects.githubusercontent.com), latest.json carries an ETag and comes back as 304 when unchanged, a feed
without releases answers 404."""
import argparse
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(BASE / "data")
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
import auth as authm  # noqa: E402
import config  # noqa: E402
import updates  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def raises(name, fn, text=""):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except (ValueError, OSError) as e:
        check(name, not text or text in str(e), e)


sign_key = Ed25519PrivateKey.generate()
config.UPDATE_PUBKEY = sign_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
aes = os.urandom(32)
config.UPDATE_KEY = aes.hex()
config.VERSION = "3.1.0"

# ======================================================================= encryption
plain = BASE / "AMKclinic-3.2.0.exe"
plain.write_bytes(b"MZ" + os.urandom(700_000) + "AMK Desk клиника".encode())
enc = BASE / "update-3.2.0.bin"
size, sha = updates.encrypt_file(plain, enc, aes)
data = enc.read_bytes()
check("encrypted size = nonce + file", size == len(data) == plain.stat().st_size + 16)
check("sha256 of the encrypted file", sha == hashlib.sha256(data).hexdigest())
check("clinic name not readable in the encrypted file", "AMK Desk".encode() not in data and b"MZ" != data[16:18])
back = BASE / "back.exe"
check("decrypts back to the same file", updates.decrypt_file(enc, back, aes) == updates._sha256(plain) and back.read_bytes() == plain.read_bytes())
updates.decrypt_file(enc, back, os.urandom(32))
check("another key gives another file", updates._sha256(back) != updates._sha256(plain))
sealed = updates.seal_text("Что нового: клиника AMK", aes)
check("notes sealed", "AMK" not in sealed and updates.open_text(sealed, aes) == "Что нового: клиника AMK")
try:
    updates.open_text(sealed, os.urandom(32))
    FAIL.append("notes opened with another key")
except Exception:  # noqa: BLE001
    OK[0] += 1
check("key from the build", updates.enc_key() == aes)
config.UPDATE_KEY = "abc"
check("a broken key is no key", updates.enc_key() is None)
config.UPDATE_KEY = aes.hex()
check("GitHub feed address", updates.github_feed("Fifum/dental-desk-updates/")
      == "https://github.com/Fifum/dental-desk-updates/releases/latest/download/latest.json")
check("installer next to latest.json in the same release",
      updates._join(updates.github_feed("o/r"), "update-3.2.0.bin") == "https://github.com/o/r/releases/latest/download/update-3.2.0.bin")
check("github.com is https", updates._allowed(updates.github_feed("o/r")))

# ======================================================================= signing a release (tools/update_sign.py)
import update_sign  # noqa: E402

update_sign._load_key = lambda: sign_key
notes_file = BASE / "notes.txt"
notes_file.write_text("Что нового в AMK Desk 3.2\n• обновления сами", encoding="utf-8")
feed_dir = BASE / "feed"
update_sign.release(argparse.Namespace(exe=str(plain), out=str(feed_dir), notes=str(notes_file), version=""))
doc = json.loads((feed_dir / "latest.json").read_text(encoding="utf-8"))
check("release: version from the file name", doc["version"] == "3.2.0", doc)
check("release: neutral encrypted file", doc["file"] == "update-3.2.0.bin" and doc["enc"] == updates.ENC
      and (feed_dir / "update-3.2.0.bin").exists() and not (feed_dir / plain.name).exists(), doc)
check("release: signed", updates.verify(doc))
check("release: no clinic name in latest.json", "AMK" not in json.dumps(doc, ensure_ascii=False) and "notes" not in doc, doc)
check("release: sizes and checksums", doc["plain_size"] == plain.stat().st_size and doc["plain_sha256"] == updates._sha256(plain)
      and doc["sha256"] == updates._sha256(feed_dir / doc["file"]))
config.UPDATE_KEY = ""
plain_dir = BASE / "feed-plain"
update_sign.release(argparse.Namespace(exe=str(plain), out=str(plain_dir), notes="", version="3.2.0"))
pdoc = json.loads((plain_dir / "latest.json").read_text(encoding="utf-8"))
check("release without a key: plain exe as before", pdoc["file"] == plain.name and "enc" not in pdoc and updates.verify(pdoc), pdoc)
config.UPDATE_KEY = aes.hex()

# feed: address and key into brand.json, a DPAPI copy of the key, the key kept on a second run
brand = BASE / "brand.json"
brand.write_text(json.dumps({"name": "Клиника", "exe": "Clinic"}, ensure_ascii=False), encoding="utf-8")
update_sign.BRAND_FILE, update_sign.AES_FILE, update_sign.KEY_DIR = brand, BASE / "keys" / "update-aes.key", BASE / "keys"
update_sign.feed(argparse.Namespace(github="Fifum/dental-desk-updates"))
b1 = json.loads(brand.read_text(encoding="utf-8"))
check("feed: brand kept", b1["name"] == "Клиника" and b1["exe"] == "Clinic", b1)
check("feed: address", b1["update_url"] == updates.github_feed("Fifum/dental-desk-updates"), b1)
check("feed: 256-bit key", len(bytes.fromhex(b1["update_key"])) == 32, b1)
check("feed: key copy protected", config.unprotect(update_sign.AES_FILE.read_text(encoding="ascii")) == b1["update_key"]
      and b1["update_key"] not in update_sign.AES_FILE.read_text(encoding="ascii"))
brand.write_text(json.dumps({"name": "Клиника"}, ensure_ascii=False), encoding="utf-8")  # e.g. brand.json made anew
update_sign.feed(argparse.Namespace(github=""))
check("feed: the same key restored from the copy", json.loads(brand.read_text(encoding="utf-8"))["update_key"] == b1["update_key"])

# ======================================================================= a fake GitHub
REPO = "Fifum/dental-desk-updates"
HITS = []
RELEASES = {"dir": feed_dir}


class GH(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        HITS.append((self.path, self.headers.get("If-None-Match")))
        pre = f"/{REPO}/releases/latest/download/"
        if self.path.startswith(pre):
            if RELEASES["dir"] is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(302)
            self.send_header("Location", f"/assets/{self.path[len(pre):]}?sig=x{time.time()}")
            self.end_headers()
            return
        if self.path.startswith("/assets/"):
            f = RELEASES["dir"] / self.path[8:].split("?")[0]
            body = f.read_bytes()
            etag = '"' + hashlib.md5(body).hexdigest() + '"'  # noqa: S324 — an ETag, not security
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GH)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
FEED = f"http://127.0.0.1:{httpd.server_port}/{REPO}/releases/latest/download/latest.json"
config.save_settings({"update_url": FEED})


def wait_download(u):
    for _ in range(200):
        if not u.state["downloading"]:
            return
        time.sleep(0.05)


u = updates.Updater()
st = u.check()
check("new version found through the redirect", st["available"] and st["latest"] == "3.2.0" and not st["error"], st)
check("notes decrypted for the toast", "обновления сами" in st["notes"], st["notes"])
check("size of the installer, not of the encrypted file", st["size"] == plain.stat().st_size, st)
n = len(HITS)
st = u.check()
check("unchanged latest.json: 304, nothing lost", HITS[-1][1] and st["available"] and st["latest"] == "3.2.0" and not st["error"], (HITS[n:], st))
u.start_download()
wait_download(u)
st = u.state
check("downloaded, decrypted, checked", st["ready"].endswith("update-3.2.0.exe") and Path(st["ready"]).read_bytes() == plain.read_bytes()
      and not st["error"] and st["progress"] == 100, st)
check("no encrypted leftovers", not list(updates.updates_dir().glob("*.bin")) and not list(updates.updates_dir().glob("*.part*")))
started = []
real_popen = updates.subprocess.Popen
updates.subprocess.Popen = lambda args, **kw: started.append(args)
os.environ["DD_UPDATE_RUN"] = "1"
try:
    u.install()
    check("installer started", started and started[0][0] == st["ready"], started)
    Path(st["ready"]).write_bytes(b"MZ evil")
    raises("changed installer not started", u.install, "изменился")
finally:
    updates.subprocess.Popen = real_popen
    del os.environ["DD_UPDATE_RUN"]
u.state["installing"] = False

# the same file twice is downloaded once; a corrupted download is refused
u.start_download()
wait_download(u)
check("download again after a bad file", Path(u.state["ready"]).read_bytes() == plain.read_bytes(), u.state)
n = len(HITS)
u.start_download()
wait_download(u)
check("already downloaded: no second download", not any("update-3.2.0.bin" in h[0] for h in HITS[n:]), HITS[n:])
data = (feed_dir / doc["file"]).read_bytes()  # the file the signed latest.json describes
bad = BASE / "feed-bad"
bad.mkdir()
(bad / "update-3.2.0.bin").write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
(bad / "latest.json").write_text(json.dumps(doc), encoding="utf-8")
RELEASES["dir"] = bad
Path(u.state["ready"]).unlink()
u.state["ready"] = ""
raises("damaged download refused", u._download, "контрольная")

# a build with another key, or none, refuses — never starts a file it could not read
RELEASES["dir"] = feed_dir
config.UPDATE_KEY = os.urandom(32).hex()
st = updates.Updater().check()
check("another build's key: explained", not st["available"] and "другой сборки" in st["error"], st)
config.UPDATE_KEY = ""
st = updates.Updater().check()
check("a build without a key: explained", "другой сборки" in st["error"], st)
config.UPDATE_KEY = aes.hex()
u2 = updates.Updater()
u2.check()
doc_x = updates.sign({**doc, "plain_sha256": "0" * 64}, sign_key)  # signed, but the file inside is another one
xdir = BASE / "feed-x"
xdir.mkdir()
(xdir / "update-3.2.0.bin").write_bytes(data)
(xdir / "latest.json").write_text(json.dumps(doc_x), encoding="utf-8")
RELEASES["dir"] = xdir
u2.check()
raises("decrypted file must match the signed checksum", u2._download, "не расшифровался")
RELEASES["dir"] = feed_dir

# unsigned / tampered feeds
tdir = BASE / "feed-t"
tdir.mkdir()
(tdir / "latest.json").write_text(json.dumps({**doc, "version": "9.9.9"}), encoding="utf-8")
RELEASES["dir"] = tdir
st = updates.Updater().check()
check("tampered latest.json refused", not st["available"] and "не подписан" in st["error"], st)
RELEASES["dir"] = None
st = updates.Updater().check()
check("repository without releases: quietly nothing", not st["available"] and not st["error"], st)
RELEASES["dir"] = feed_dir
config.VERSION = "3.2.0"
st = updates.Updater().check()
check("same version: nothing to install", not st["available"] and st["latest"] == "3.2.0", st)
config.VERSION = "3.1.0"
httpd.shutdown()
st = updates.Updater().check()
check("offline: a calm message", "Нет связи" in st["error"] and not st["available"], st)

# ======================================================================= the worker checks once a minute
check("once a minute", updates.CHECK_EVERY_S == 60)
calls = []
real_check = updates.UPDATER.check
updates.UPDATER.check = lambda: calls.append(1)
os.environ["DD_UPDATE_DELAY"], os.environ["DD_UPDATE_EVERY"] = "0", "0.05"
w = updates.UpdateWorker()
w.start()
time.sleep(0.4)
w.stop_flag = True
check("worker checks repeatedly", len(calls) >= 3, len(calls))
updates.UPDATER.state["downloading"] = True
calls.clear()
w = updates.UpdateWorker()
w.start()
time.sleep(0.25)
w.stop_flag = True
check("no checks while downloading", not calls, len(calls))
updates.UPDATER.state["downloading"] = False
updates.UPDATER.check = real_check

# ======================================================================= any employee may update
for m in ("update_status", "update_check", "update_download", "update_install"):
    check(f"{m} for any employee", authm.METHOD_PERMS.get(m) == authm.ANY_USER, authm.METHOD_PERMS.get(m))
check("installing stays in the journal", "update_install" in authm.AUDITED)
import main  # noqa: E402

src = Path(main.__file__).read_text(encoding="utf-8")
check("no director-only check on updating", "_director(\"Обновлять программу\")" not in src)
js = (ROOT / "app" / "ui" / "platform.js").read_text(encoding="utf-8")
check("toast text", "Вышла новая версия" in js and "updGo" in js)
check("toast for every employee", "if (u && u.available) updateBanner(u);" in js)

# ======================================================================= publishing to GitHub (gh mocked)
import publish_update  # noqa: E402

GH_CALLS = []


class R:
    def __init__(self, code=0):
        self.returncode, self.stdout, self.stderr = code, "", ""


def fake_gh(*args, check=True):
    GH_CALLS.append(args)
    if args[:2] in (("repo", "view"), ("release", "view")):
        return R(1)  # no repository, no release yet
    return R(0)


publish_update._gh = fake_gh


class Live:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, *a): return self.body


real_open = updates._open
updates._open = lambda url, **kw: Live(json.dumps(doc).encode())
try:
    rc = publish_update.github_publish(feed_dir, doc, REPO)
finally:
    updates._open = real_open
names = [" ".join(c[:2]) for c in GH_CALLS]
check("publish: repository created public", ("repo", "create", REPO, "--public") == GH_CALLS[1][:4], GH_CALLS)
check("publish: draft first, latest.json second, then latest", names[3:] == ["release create", "release upload", "release edit"]
      and "--draft" in GH_CALLS[3] and GH_CALLS[4][3].endswith("latest.json") and "--latest" in GH_CALLS[5], names)
check("publish: only the encrypted file goes up", GH_CALLS[3][3].endswith("update-3.2.0.bin"), GH_CALLS[3])
check("publish: no clinic name in the release text", not any("AMK" in " ".join(c) for c in GH_CALLS))
check("publish: checked what programs see", rc == 0)
try:
    publish_update.github_publish(plain_dir, pdoc, REPO)
    FAIL.append("plain installer published to a public repository")
except SystemExit as e:
    check("publish: plain installer refused", "не зашифрован" in str(e), e)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
