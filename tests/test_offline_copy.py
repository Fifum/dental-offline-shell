"""Read-only copy for client laptops: snapshot cut to rights, encrypted storage, offline sign-in."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import offline_store  # noqa: E402
from main import Api, Host, Setup  # noqa: E402
from server import ClinicServer  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
for login, role, perms in (("doc", "doctor", None), ("sched", "assistant", ["schedule_view"]), ("keeper", "storekeeper", None)):
    call("auth", "register", {"name": login, "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active", "perms": perms}, token=TD)
tok = {lg: call("auth", "login", lg, "secret1")[1]["token"] for lg in ("doc", "sched", "keeper")}

# --- snapshot respects rights
code, snap = call("api", "offline_snapshot", token=tok["doc"])
check("doctor snapshot", code == 200 and len(snap["visits"]) > 20 and len(snap["patients"]) > 10, (code, len(snap.get("visits", []))))
p = next(iter(snap["patients"].values()))
check("doctor card has medcard", "records" in p and "visits" in p and p["name"])
check("no money in snapshot", all("invoices" not in x and "balance_local" not in x for x in snap["patients"].values()))
code, s2 = call("api", "offline_snapshot", token=tok["sched"])
check("schedule-only: visits but no cards", s2["visits"] and s2["patients"] == {}, len(s2["patients"]))
code, s3 = call("api", "offline_snapshot", token=tok["keeper"])
check("storekeeper: nothing", s3["visits"] == [] and s3["patients"] == {})
check("snapshot needs login", call("api", "offline_snapshot")[0] == 401)
check("window limited", snap["from"] <= snap["to"] and all(snap["from"] <= v["start"][:10] <= snap["to"] for v in snap["visits"]))

# --- storage on the client computer
config.save_settings({"net_mode": "client", "server_url": f"http://127.0.0.1:{PORT}/"})
st = Setup(Host())
check("remember login", st.offline_remember("Doc", "secret1") is True)
r = st.offline_save("doc", json.dumps(snap))
check("copy saved", r["ok"] and r["visits"] == len(snap["visits"]))
raw = next(f for f in (config.data_dir() / "offline").glob("*.bin") if f.name != "users.bin").read_text(encoding="ascii")
check("copy encrypted on disk", raw.startswith("dpapi:") and snap["visits"][0]["patient_name"] not in raw)
check("users file has no password", "secret1" not in (config.data_dir() / "offline" / "users.bin").read_text(encoding="ascii"))
check("available lists login only", [x["login"] for x in st.offline_available()] == ["doc"])
check("wrong password refused", st.offline_open("doc", "nope")["ok"] is False)
o = st.offline_open("DOC", "secret1")
check("open copy (login case-insensitive)", o["ok"] and len(o["snapshot"]["visits"]) == len(snap["visits"]) and o["snapshot"]["saved_at"])
check("unknown login refused", st.offline_open("ghost", "secret1")["ok"] is False)
for _ in range(5):
    st.offline_open("doc", "bad")
check("throttle offline sign-in", "попыток" in st.offline_open("doc", "secret1").get("message", ""))
offline_store._fails.clear()
check("server alive seen", st.server_alive() is True)

# server computer never stores copies
config.save_settings({"net_mode": "server"})
check("server mode does not save", st.offline_save("doc", json.dumps(snap)) == {"ok": False} and st.offline_remember("x", "secret1") is False)

# old copies are removed
f = next(f for f in (config.data_dir() / "offline").glob("*.bin") if f.name != "users.bin")
os.utime(f, (0, 0))
check("old copy cleaned", st.offline_available() == [] and not f.exists())
check("forget", st.offline_forget("doc") is True)

srv.stop()
check("server down detected", st.server_alive() is False)
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
