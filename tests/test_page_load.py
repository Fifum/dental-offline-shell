"""3.12.1: the window opened right after the program started lacked whole scripts («loadVoiceSettings is not defined»,
Settings without their menu): the server's queue of connections not accepted yet was 5, the window asks for ~50 files
at once while the program is busy starting, and Windows dropped the rest.

Checked: the server keeps a long queue and answers 100 connections at once while another thread keeps Python busy;
a page that lost a script reloads itself (twice at most in a row) and forgets that once everything has loaded."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT / "app"))
import server  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:400]}")


check("a long queue of connections", server._ExclusiveServer.request_queue_size >= 64, server._ExclusiveServer.request_queue_size)

UI = str(ROOT / "app" / "ui")


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=UI, **kw)

    def log_message(self, *a):
        pass


httpd = server._ExclusiveServer(("127.0.0.1", 0), H)
httpd.daemon_threads = True
threading.Thread(target=httpd.serve_forever, daemon=True).start()
port = httpd.server_address[1]
busy = [True]


def burn():  # the program starting: backups, the database, the models — Python is busy
    while busy[0]:
        sum(i * i for i in range(20000))


burners = [threading.Thread(target=burn, daemon=True) for _ in range(3)]
for t in burners:
    t.start()
results = []


def one():
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=20)
        s.sendall(b"GET /dictate.js HTTP/1.0\r\nHost: x\r\n\r\n")
        data = b""
        while True:
            c = s.recv(65536)
            if not c:
                break
            data += c
        results.append(data[:15] == b"HTTP/1.0 200 OK" and len(data) > 20000)
    except OSError as e:
        results.append(repr(e))


threads = [threading.Thread(target=one) for _ in range(100)]
for t in threads:
    t.start()
for t in threads:
    t.join()
busy[0] = False
httpd.shutdown()
bad = [r for r in results if r is not True]
check("100 files at once while the program is busy: none dropped", not bad, bad[:3])

# ---- the page reloads itself when a script did not arrive (theme.js, run in node with a tiny window)
JS = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");
function run(failed, stored) {
  const listeners = {}, store = Object.assign({}, stored), out = {reloads: 0, timers: []};
  const add = (k, fn) => (listeners[k] = listeners[k] || []).push(fn);
  const ss = {getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); },
              removeItem: k => { delete store[k]; }};
  const win = {addEventListener: add, sessionStorage: ss, matchMedia: () => ({matches: false, addEventListener() {}}),
               localStorage: {getItem: () => null, setItem() {}}, dispatchEvent() {}};
  const doc = {documentElement: {getAttribute: () => null, setAttribute() {}, classList: {add() {}, remove() {}},
               style: {}}, addEventListener: add};
  const ctx = {window: win, document: doc, location: {search: "", reload: () => out.reloads++},
               localStorage: win.localStorage, sessionStorage: ss, CustomEvent: function () {},
               setTimeout: (fn, ms) => { out.timers.push(ms); fn(); }, requestAnimationFrame: fn => fn(), console};
  win.window = win;
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  for (const f of failed) for (const fn of listeners.error || []) fn({target: {tagName: "SCRIPT", src: f}});
  for (const fn of listeners.error || []) fn({target: {tagName: "IMG", src: "x.png"}});
  for (const fn of listeners.DOMContentLoaded || []) fn({});
  return {reloads: out.reloads, timers: out.timers, store};
}
console.log(JSON.stringify({
  lost: run(["http://127.0.0.1:8765/dictate.js?v=3.12.1"], {}),
  again: run(["http://127.0.0.1:8765/dictate.js?v=3.12.1"], {"dd.reloaded": "1"}),
  third: run(["http://127.0.0.1:8765/dictate.js?v=3.12.1"], {"dd.reloaded": "2"}),
  fine: run([], {"dd.reloaded": "1"}),
  image: run([], {})
}));
"""
jsf = Path(tempfile.mkdtemp()) / "guard.js"
jsf.write_text(JS, encoding="utf-8")
r = subprocess.run(["node", str(jsf), str(ROOT / "app" / "ui" / "theme.js")], capture_output=True, text=True, encoding="utf-8")
try:
    res = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    res = None
    FAIL.append(f"node: {r.stdout[-400:]} {r.stderr[-800:]}")
if res:
    check("a lost script: the page reloads itself", res["lost"]["reloads"] == 1 and res["lost"]["store"].get("dd.reloaded") == "1", res["lost"])
    check("lost again: one more reload, a bit later", res["again"]["reloads"] == 1 and res["again"]["timers"][-1] > res["lost"]["timers"][-1], res["again"])
    check("never more than twice in a row", res["third"]["reloads"] == 0, res["third"])
    check("everything loaded: no reload, the count is forgotten", res["fine"]["reloads"] == 0 and "dd.reloaded" not in res["fine"]["store"], res["fine"])
    check("a missing picture is no reason to reload", res["image"]["reloads"] == 0, res["image"])
html = (ROOT / "app" / "ui" / "index.html").read_text(encoding="utf-8")
check("theme.js is the first script of the page (it must hear the others fail)",
      html.index("theme.js") < html.index("<script src=\"app.js"))

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
