"""3.12: one download from the internet for the whole clinic — the computers give a checked update file to each other.

Three computers in miniature (tests/p2p_node.py, each with its own data folder, server and port): A and B of one
clinic, C of another clinic. A fake GitHub (tests/update_feed.py) counts what is downloaded from it. Checked: B takes
the file A has already downloaded, not the internet; a piece continues with Range; a computer of another clinic gets
nothing and is never a source; a damaged file on A is noticed and B downloads from the internet; B waits for A that
is downloading the same file right now instead of downloading it a second time (and does not wait for one that
stopped); the delta «только изменения» goes the same way; with nobody in the network — the internet."""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import p2p_harness as H  # noqa: E402

os.environ["LOCALAPPDATA"] = str(H.BASE / "maker")
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))
import config  # noqa: E402
import manifest  # noqa: E402
import update_sign  # noqa: E402
import updates  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402
from update_feed import Feed  # noqa: E402

check, wait, FAIL, OK = H.check, H.wait, H.FAIL, H.OK

# ======================================================================= a release: the whole file and a delta
sign_key = Ed25519PrivateKey.generate()
PUB = sign_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
config.UPDATE_PUBKEY = PUB
AES = os.urandom(32).hex()
config.UPDATE_KEY = AES
update_sign._load_key = lambda: sign_key
EXE = config.BRAND["exe"] + ".exe"
work = H.BASE / "release"
work.mkdir()
setup = work / "DentalDesk-3.13.0.exe"
setup.write_bytes(b"MZ setup 3.13.0 " + os.urandom(2_500_000))
import zipfile  # noqa: E402

app_zip = work / "app.zip"
files = {EXE: b"MZ 3.13 " + os.urandom(300_000), "_internal/dd-update-helper.exe": b"MZ helper", "_internal/ui/app.js": b"ui 3.13"}
new_m = {"app": "dentaldesk", "version": "3.13.0", "exe": EXE,
         "files": {k: [len(v), hashlib.sha256(v).hexdigest()] for k, v in files.items()}}
with zipfile.ZipFile(app_zip, "w") as z:
    for k, v in files.items():
        z.writestr(k, v)
    z.writestr(manifest.NAME, json.dumps(new_m))
prev = {**new_m, "version": "3.12.0", "files": {**new_m["files"], EXE: [5, "0" * 64]}}
(work / "prev.json").write_text(json.dumps(prev), encoding="utf-8")
feed_dir = work / "feed"
update_sign.release(argparse.Namespace(exe=str(setup), out=str(feed_dir), notes="", version="", app_zip=str(app_zip),
                                       prev_manifest=str(work / "prev.json"), manifests=""))
doc = json.loads((feed_dir / "latest.json").read_text(encoding="utf-8"))
SHA, DSHA = doc["sha256"], doc["delta"]["sha256"]
ENC_FULL = (feed_dir / doc["file"]).read_bytes()
PLAIN = doc["plain_sha256"]
gh = Feed(feed_dir)
check("release has the whole file and the delta", doc.get("delta") and gh.url)

# ======================================================================= three computers
H.ENV.update({"DD_UPDATE_RETRY_S": "0.05", "DD_UPDATE_LAN_POLL": "0.3", "DD_UPDATE_LAN_STALL": "3"})
K, K2 = os.urandom(32).hex(), os.urandom(32).hex()
A, B, C = H.Node("A"), H.Node("B"), H.Node("C")
NODES = (A, B, C)


def setup_code(key):
    return (f"import updates, cloud, shutil, hashlib, time, urllib.error\nconfig.UPDATE_PUBKEY = {PUB!r}\nconfig.UPDATE_KEY = {AES!r}\n"
            f"config.VERSION = '3.12.0'\nconfig.save_settings({{'update_url': {gh.url!r}, 'demo': False}})\n"
            f"cloud.set_clinic_key(bytes.fromhex({key!r}), 'Клиника')\nnode.wake(full=True)")


def reset(n):
    """A computer that has downloaded nothing yet."""
    n.run("shutil.rmtree(updates.updates_dir(), ignore_errors=True)\nupdates.UPDATER = updates.Updater()\n"
          "updates.UPDATER.check()")


def download(n):
    return n.run("r = updates.UPDATER._download()\nr = [r, updates._sha256(r), updates.UPDATER.state['via']]")


try:
    A.run(setup_code(K))
    B.run(setup_code(K))
    C.run(setup_code(K2))
    wait("A and B find each other", lambda: B.node in A.run("r = [p['node'] for p in node.live_list()]")
         and A.node in B.run("r = [p['node'] for p in node.live_list()]"), timeout=30)
    check("C of another clinic is not a computer of ours", C.node not in B.run("r = [p['node'] for p in node.live_list()]"))
    for n in NODES:
        reset(n)

    # --- A downloads from the internet, B takes it from A
    r = download(A)
    check("A: downloaded and checked", r and r[1] == PLAIN and r[2] == "интернет", r)
    check("A: one download from the internet", gh.count(doc["file"]) == 1, gh.hits)
    check("A: offers the checked file", A.run(f"r = updates.lan_have({SHA!r})")["have"])
    r = download(B)
    check("B: the same installer", r and r[1] == PLAIN, r)
    check("B: taken from A over the clinic network", gh.count(doc["file"]) == 1 and "сеть клиники" in r[2], (gh.hits, r))
    check("B: offers it further", B.run(f"r = updates.lan_have({SHA!r})")["have"])

    # --- a piece from a computer of the clinic continues with Range
    r = B.run(f"p = [x for x in node.live_list() if x['node'] == {A.node!r}][0]\n"
              f"with updates._peer_open(p, {SHA!r}, 1000) as resp:\n"
              "    r = [resp.status, resp.headers.get('Content-Range'), hashlib.sha256(resp.read()).hexdigest()]")
    check("Range from a computer of the clinic", r and r[0] == 206 and str(r[1]).startswith("bytes 1000-")
          and r[2] == hashlib.sha256(ENC_FULL[1000:]).hexdigest(), r)

    # --- another clinic gets nothing and is never a source
    r = C.run(f"try:\n    p2p.call('http://127.0.0.1:{A.port}', 'upd_have', {{'sha': {SHA!r}}})\n    r = 'answered'\n"
              "except p2p.P2PError as e:\n    r = [e.code, str(e)]")
    check("another clinic: «есть ли файл?» refused", r and r[0] == 403 and "другой клиники" in r[1], r)
    r = C.run(f"try:\n    updates._peer_open({{'ip': '127.0.0.1', 'port': {A.port}}}, {SHA!r}, 0)\n    r = 'got it'\n"
              "except urllib.error.HTTPError as e:\n    r = e.code")
    check("another clinic: the file refused", r == 403, r)
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{A.port}/p2p/upd/{SHA}", timeout=5)
        FAIL.append("a request without the clinic key got the file")
    except urllib.error.HTTPError as e:
        check("no clinic key: the file refused", e.code == 403, e.code)
    r = B.run(f"r = updates._ask_peers({SHA!r}, [{{'node': {C.node!r}, 'ip': '127.0.0.1', 'port': {C.port}, 'name': 'C'}}])")
    check("a computer of another clinic is never a source", r == [], r)

    # --- a damaged file on A: B notices it and goes to the internet
    reset(B)
    A.run(f"p = updates.shared({SHA!r})\nb = bytearray(p.read_bytes())\nb[len(b) // 2] ^= 1\np.write_bytes(bytes(b))")
    n0 = gh.count(doc["file"])
    r = download(B)
    check("damaged on A: B still installs the right file", r and r[1] == PLAIN, r)
    check("damaged on A: B took it from the internet", gh.count(doc["file"]) == n0 + 1, gh.hits)
    reset(A)

    # --- B waits for A that is downloading it right now: one download for the clinic
    reset(B)
    gh.slow = 0.08  # ~3 s for the whole file
    n0 = gh.count(doc["file"])
    A.run("updates.UPDATER.start_download()")
    wait("A is downloading", lambda: A.run(f"r = updates.lan_have({SHA!r})")["busy"], timeout=10)
    r = download(B)
    gh.slow = 0
    check("waited for A: the right file, from A", r and r[1] == PLAIN and "сеть клиники" in r[2], r)
    check("waited for A: one download from the internet for both", gh.count(doc["file"]) == n0 + 1, gh.hits[-4:])
    wait("A finished too", lambda: A.run("r = not updates.UPDATER.state['downloading'] and bool(updates.UPDATER.state['ready'])"))

    # --- a computer that stopped downloading is not waited for long
    reset(A)
    reset(B)
    A.run(f"updates.UPDATER.fetching = {{'sha': {SHA!r}, 'got': 1000, 'size': {doc['size']}, 'started': True}}")
    t0, n0 = time.time(), gh.count(doc["file"])
    r = download(B)
    took = time.time() - t0
    A.run("updates.UPDATER.fetching = None")
    check("a stalled computer: B downloads itself after a short wait", r and r[1] == PLAIN and gh.count(doc["file"]) == n0 + 1
          and 2 < took < 20, (took, gh.hits[-3:]))

    # --- the delta «только изменения» is shared the same way
    item = {"file": doc["delta"]["file"], "size": doc["delta"]["size"], "sha256": DSHA}
    reset(A)
    reset(B)
    A.run(f"r = str(updates.UPDATER._obtain({item!r}, 0, 100, what='только изменения'))")
    r = B.run(f"p = updates.UPDATER._obtain({item!r}, 0, 100, what='только изменения')\n"
              "r = [updates._sha256(p), updates.UPDATER.state['via']]")
    check("delta over the clinic network", r and r[0] == DSHA and "сеть клиники" in r[1] and gh.count(item["file"]) == 1,
          (r, gh.hits[-3:]))

    # --- nobody in the network: the internet, as before
    A.stop()
    reset(B)
    B.run("node.live.clear()")
    n0 = gh.count(doc["file"])
    r = download(B)
    check("nobody in the network: from the internet", r and r[1] == PLAIN and gh.count(doc["file"]) == n0 + 1, r)
finally:
    for n in NODES:
        n.stop()
    gh.stop()

# ======================================================================= pressed at once: the one that already downloads goes on
u = updates.Updater()
config.save_settings({"update_url": gh.url})
calls = []
rival = {"node": "0" * 8, "ip": "127.0.0.1", "port": 1, "name": "Ресепшн"}
answers = iter([[(rival, {"busy": True, "started": True, "got": 10, "total": 100})],
                [(rival, {"have": True, "size": len(ENC_FULL)})], [(rival, {"have": True, "size": len(ENC_FULL)})]])
real_ask, real_peer, real_from = updates._ask_peers, updates._peer_open, updates._open_from
updates._ask_peers = lambda sha, peers=None: calls.append(sha) or next(answers, [])


class _P:
    def __init__(self, start):
        self.data, self.status, self.headers = ENC_FULL[start:], 206 if start else 200, {"Content-Range": f"bytes {start}-"}

    def read(self, n=-1):
        out, self.data = self.data[:n], self.data[n:]
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


updates._peer_open = lambda p, sha, start: _P(start)
updates._open_from = lambda url, start: (_ for _ in ()).throw(AssertionError("the internet was used"))
try:
    part = updates.share_dir() / (doc["file"] + ".part")
    got = u._from_internet({"file": doc["file"], "size": len(ENC_FULL), "sha256": SHA}, part,
                           updates.share_dir() / doc["file"], set(), 0, 100, "обновление", "2 МБ")
    check("pressed at once: waits for the computer that already downloads, takes the file from it",
          updates._sha256(got) == SHA and u.fetching is None, calls)
except AssertionError as e:
    FAIL.append(f"pressed at once: {e}")
finally:
    updates._ask_peers, updates._peer_open, updates._open_from = real_ask, real_peer, real_from

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
