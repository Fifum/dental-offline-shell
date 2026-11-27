"""3.15.1: «при закрытии документа закрывается всё приложение» (2026-11-27). Printing (the schedule, a document,
a receipt: window.print()) shows WebView2's print preview over the whole main window; the user took it for a document
in a window of its own and closed it with the window's × — the whole program closed.

Checked: while the page reports an open preview, the window's × keeps the window and closes only the preview (Esc to
the window; the page is loaded again when Esc could not reach it); without a preview × closes the program as before;
a late «opened» never undoes a newer «closed»; theme.js (the first script of every page of the window) reports
beforeprint / afterprint; the main window is wired to the guard.

The same was checked by hand in a real pywebview window: × over an open preview, then × again."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(ROOT / "app"))
import printguard  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {str(info)[:400]}")


def wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class Fake:
    """The window's side: Esc closes the preview (the page then says «closed»), reload counts."""

    def __init__(self, esc_works=True, esc_reaches=True):
        self.esc, self.reloads, self.esc_works, self.esc_reaches = [], 0, esc_works, esc_reaches
        self.g = printguard.PrintGuard(hwnd=lambda: 4242, esc=self.send_esc, reload=self.reload)
        self.g.WAIT = 0.4

    def send_esc(self, hwnd):
        self.esc.append(hwnd)
        if self.esc_reaches and self.esc_works:
            threading.Timer(0.05, lambda: self.g.state(False, 99)).start()  # afterprint
        return self.esc_reaches

    def reload(self):
        self.reloads += 1


# ---- no preview: × closes the program as before
f = Fake()
check("no preview: × closes the program", f.g.on_closing() is None)
check("no preview: nothing is sent", f.esc == [] and f.reloads == 0, (f.esc, f.reloads))

# ---- the preview is open: × keeps the window, Esc closes the preview
f = Fake()
f.g.state(True, 1)
check("preview open: the guard knows", f.g.open)
check("preview open: × keeps the window", f.g.on_closing() is False)
check("× again while it closes: still kept, no second Esc", f.g.on_closing() is False)
check("Esc went to the program's window", wait(lambda: f.esc == [4242]), f.esc)
check("the preview closed", wait(lambda: not f.g.open and not f.g.busy))
check("no reload when Esc did it", f.reloads == 0, f.reloads)
check("Esc sent once", f.esc == [4242], f.esc)
check("after the preview closed: × closes the program", f.g.on_closing() is None)

# ---- Esc could not reach the window (another window in front): the page is loaded again
f = Fake(esc_reaches=False)
f.g.state(True, 1)
check("Esc not delivered: × keeps the window", f.g.on_closing() is False)
check("Esc not delivered: the page is loaded again", wait(lambda: f.reloads == 1), f.reloads)
check("after the reload no preview is counted", wait(lambda: not f.g.open and not f.g.busy))
check("then × closes the program", f.g.on_closing() is None)

# ---- Esc delivered but the preview stayed: the page is loaded again after a short wait
f = Fake(esc_works=False)
f.g.state(True, 1)
t0 = time.time()
f.g.on_closing()
check("preview stayed after Esc: reload", wait(lambda: f.reloads == 1), f.reloads)
check("…after waiting for the preview to close", time.time() - t0 >= 0.4, time.time() - t0)
check("…and the guard forgets the preview", wait(lambda: not f.g.open and not f.g.busy))

# ---- Esc or reload failing does not break the window
g = printguard.PrintGuard(hwnd=lambda: 1 / 0, esc=lambda h: 1 / 0, reload=lambda: 1 / 0)
g.WAIT = 0.1
g.state(True, 1)
check("a failing handle: × still keeps the window", g.on_closing() is False)
check("a failing reload: the guard recovers", wait(lambda: not g.open and not g.busy))

# ---- order of the page's messages (each runs in a thread of its own)
g = printguard.PrintGuard()
g.state(True, 1)
g.state(False, 2)
g.state(True, 1)  # the late «opened»
check("a late «opened» does not undo a newer «closed»", not g.open)
g.state(True, 3)
check("the next print opens it again", g.open)
g.page_loaded()
check("a new page: no preview", not g.open)
g.state(True, 1)
check("a new page counts from the start again", g.open)
g.state("x", "nonsense")
check("nonsense from the page does not break it", isinstance(g.open, bool))

# ---- wiring: main window and the bridge
class Ev:
    def __init__(self):
        self.items = []

    def __iadd__(self, fn):
        self.items.append(fn)
        return self


class Events:
    closing, loaded = Ev(), Ev()


class Win:
    events = Events()


class SetupStub:
    _print = None


w, s = Win(), SetupStub()
g = printguard.attach(w, s)
check("attach: the bridge gets the guard", s._print is g)
check("attach: × of the main window goes through the guard", g.on_closing in w.events.closing.items)
check("attach: a new page resets it", g.page_loaded in w.events.loaded.items)

main_src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
check("main(): the guard is attached before the window starts",
      0 < main_src.index("printguard.attach(window, setup)") < main_src.index("webview.start("))
import main  # noqa: E402
st = main.Setup(main.Host())
check("Setup without a window: print_state is harmless", st.print_state(True, 1) is False)
st._print = printguard.PrintGuard()
check("Setup.print_state reaches the guard", st.print_state(True, 1) is True and st._print.open)
st.print_state(False, 2)
check("Setup.print_state: closed", not st._print.open)

# ---- theme.js reports beforeprint / afterprint (run in node with a tiny window)
JS = r"""
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");
function run(bridge) {
  const listeners = {}, calls = [];
  const add = (k, fn) => (listeners[k] = listeners[k] || []).push(fn);
  const win = {addEventListener: add, matchMedia: () => ({matches: false, addEventListener() {}}),
               localStorage: {getItem: () => null, setItem() {}}, sessionStorage: {getItem: () => null, setItem() {}, removeItem() {}}};
  if (bridge === "ok") win.pywebview = {api: {print_state: (on, n) => { calls.push([on, n]); return Promise.resolve(on); }}};
  if (bridge === "rejects") win.pywebview = {api: {print_state: (on, n) => { calls.push([on, n]); return Promise.reject(new Error("x")); }}};
  if (bridge === "throws") win.pywebview = {api: {print_state: () => { throw new Error("x"); }}};
  if (bridge === "old") win.pywebview = {api: {}};
  const doc = {documentElement: {getAttribute: () => null, setAttribute() {}, classList: {add() {}, remove() {}}, style: {}},
               addEventListener: add, dispatchEvent() {}};
  const ctx = {window: win, document: doc, location: {search: "", reload() {}}, localStorage: win.localStorage,
               sessionStorage: win.sessionStorage, CustomEvent: function () {}, setTimeout() {}, console};
  win.window = win;
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  let error = "";
  try {
    for (const k of ["beforeprint", "afterprint", "beforeprint", "afterprint"]) for (const fn of listeners[k] || []) fn({});
  } catch (e) { error = String(e); }
  return {calls, error, before: (listeners.beforeprint || []).length, after: (listeners.afterprint || []).length};
}
const out = {ok: run("ok"), rejects: run("rejects"), throws: run("throws"), old: run("old"), none: run("none")};
setTimeout(() => console.log(JSON.stringify(out)), 50);
process.on("unhandledRejection", () => { out.unhandled = true; });
"""
jsf = Path(tempfile.mkdtemp()) / "print.js"
jsf.write_text(JS, encoding="utf-8")
r = subprocess.run(["node", str(jsf), str(ROOT / "app" / "ui" / "theme.js")], capture_output=True, text=True, encoding="utf-8")
try:
    res = json.loads(r.stdout.strip().splitlines()[-1])
except (ValueError, IndexError):
    res = None
    FAIL.append(f"node: {r.stdout[-400:]} {r.stderr[-800:]}")
if res:
    check("theme.js listens to the print preview opening and closing", res["ok"]["before"] == 1 and res["ok"]["after"] == 1, res["ok"])
    check("theme.js tells the program: opened, closed, opened, closed — numbered",
          res["ok"]["calls"] == [[True, 1], [False, 2], [True, 3], [False, 4]], res["ok"]["calls"])
    check("a refused message is not an unhandled error", not res.get("unhandled") and not res["rejects"]["error"], res)
    check("a broken bridge does not break printing", not res["throws"]["error"], res["throws"])
    check("an older program without print_state: printing works", not res["old"]["error"] and not res["old"]["calls"], res["old"])
    check("outside the program (a browser): printing works", not res["none"]["error"], res["none"])
pages = {p: (ROOT / "app" / "ui" / p).read_text(encoding="utf-8") for p in ("index.html", "offline.html", "setup.html")}
for p, html in pages.items():
    check(f"{p} loads theme.js (it carries the print report)", "theme.js" in html)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
