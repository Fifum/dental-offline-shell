"""Helpers shared by the clinic-network tests (test_dp_main.py): a computer in miniature (tests/p2p_node.py in its
own process, data folder and port), check() and wait(). Copied from test_p2p.py."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.mkdtemp())

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:600]}")


def free_port():
    while True:
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            u.bind(("0.0.0.0", p + 1))
            return p
        except OSError:
            continue
        finally:
            u.close()


PORTS = {n: free_port() for n in "ABC"}
ENV = {**os.environ, "DD_DISCOVERY_PORTS": ",".join(str(p + 1) for p in PORTS.values()), "DD_P2P_DELAY": "0.3",
       "DD_P2P_INTERVAL": "4", "DD_P2P_TICK": "0.3", "DD_CLOUD_DELAY": "3600", "PYTHONIOENCODING": "utf-8"}


class Node:
    def __init__(self, name):
        self.name, self.port = name, PORTS[name]
        self.dir = BASE / name
        self.dir.mkdir()
        self.p = subprocess.Popen([sys.executable, str(ROOT / "tests" / "p2p_node.py"), str(self.dir), str(self.port)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=ENV, text=True, encoding="utf-8")
        hello = json.loads(self.p.stdout.readline())
        self.node = hello["node"]

    def run(self, code, quiet=False):
        self.p.stdin.write(json.dumps({"code": code}) + "\n")
        self.p.stdin.flush()
        ans = json.loads(self.p.stdout.readline())
        if not ans["ok"] and not quiet:
            FAIL.append(f"{self.name}: {ans['error']}\n{ans.get('tb', '')}")
        return ans.get("r") if ans["ok"] else ans

    def q(self, sql, args=()):
        return self.run(f"r = db.q({sql!r}, {tuple(args)!r})")

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def offline(self, on):
        """The router is off for this computer: it neither answers nor asks."""
        if on:
            self.run("import p2p as _p\n_p._h = _p.handle\ndef _off(*a, **k): raise _p.P2PError('нет сети', 503)\n"
                     "_p.handle = _off\nnode._r, node._n = node.round, node.notify_all\nnode.round = lambda full: None\n"
                     "node.notify_all = lambda: None")
        else:
            self.run("p2p.handle = p2p._h\nnode.round, node.notify_all = node._r, node._n\nnode.wake(full=True)")

    def stop(self):
        try:
            self.p.stdin.close()
            self.p.wait(5)
        except Exception:  # noqa: BLE001
            self.p.kill()


def wait(name, fn, timeout=25):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                OK[0] += 1
                return last
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.3)
    FAIL.append(f"{name} (timeout) {str(last)[:300]}")
    return None


