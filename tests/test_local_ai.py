"""AI on this computer: installing Ollama from a zip (only the needed files, by HTTP ranges, or the
whole archive when the server cannot give parts), pulling a model with progress, switching the
program to it and asking it. A fake HTTP server stands in for GitHub and for Ollama."""
import io
import json
import os
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import ai  # noqa: E402
import llm_local  # noqa: E402
from auth import METHOD_PERMS  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("ollama.exe", b"MZ" + os.urandom(300_000))
    z.writestr("lib/ollama/ggml-base.dll", os.urandom(200_000))
    z.writestr("lib/ollama/cuda_v12/ggml-cuda.dll", os.urandom(3_000_000))
    z.writestr("lib/ollama/cuda_v13/cublas.dll", os.urandom(3_000_000))
ZIP = buf.getvalue()
SEEN = {"ranges": 0, "full": 0, "chat": None, "pulled": False}
RANGES = {"on": True}


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/ollama.zip":
            rng = self.headers.get("Range")
            if rng and RANGES["on"]:
                a, b = rng.split("=")[1].split("-")
                a, b = int(a), min(int(b), len(ZIP) - 1)
                SEEN["ranges"] += 1
                self.send_response(206); self.send_header("Content-Range", f"bytes {a}-{b}/{len(ZIP)}")
                self.send_header("Content-Length", str(b - a + 1)); self.end_headers(); self.wfile.write(ZIP[a:b + 1])
            else:
                SEEN["full"] += 1
                self.send_response(200); self.send_header("Content-Length", str(len(ZIP))); self.end_headers(); self.wfile.write(ZIP)
        elif self.path == "/api/version":
            self._json({"version": "0.0-test"})
        elif self.path == "/api/tags":
            self._json({"models": [{"name": "gemma3:4b"}] if SEEN["pulled"] else []})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/pull":
            self.send_response(200); self.send_header("Content-Type", "application/x-ndjson"); self.end_headers()
            for done in (0, 500, 1000):
                self.wfile.write(json.dumps({"status": "pulling", "digest": "sha256:a", "total": 1000, "completed": done}).encode() + b"\n")
            SEEN["pulled"] = True
            self.wfile.write(b'{"status":"success"}\n')
        elif self.path == "/api/chat":
            SEEN["chat"] = body
            self._json({"message": {"role": "assistant", "content": '{"complaints": "Боль от холодного.", "teeth": {"36": "Пломба"}}'}})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}"
llm_local.OLLAMA_URL = URL + "/ollama.zip"
llm_local._has_nvidia = lambda: False
llm_local.ensure = lambda: URL           # the fake server plays a running Ollama
llm_local.base = lambda: URL if llm_local.installed() else None


def wait():
    for _ in range(200):
        if not llm_local._state["task"]:
            return
        time.sleep(0.05)


check("permissions", all(METHOD_PERMS.get(m) == "settings" for m in
                         ("local_ai_status", "local_ai_install", "local_ai_pull", "local_ai_use", "local_ai_delete")))
st = llm_local.status()
check("not installed at first", not st["installed"] and not st["models"]["gemma3:4b"]["ready"], st)
check("small download without NVIDIA", st["ollama_mb"] < 100, st["ollama_mb"])

# install: only the needed files, fetched in parts
llm_local.install(); wait()
home = llm_local.home()
check("install ok", llm_local.installed() and llm_local._state["error"] is None, llm_local._state["error"])
check("CPU library extracted", (home / "lib/ollama/ggml-base.dll").exists())
check("graphics-card libraries skipped", not (home / "lib/ollama/cuda_v12").exists() and not (home / "lib/ollama/cuda_v13").exists())
check("fetched by ranges, not whole", SEEN["ranges"] > 0 and SEEN["full"] == 0, SEEN)
check("no archive left behind", not (home / "ollama.zip.part").exists())

# the same when the server cannot give parts: the whole archive, then extract
# (two plain answers: the probe for parts, closed unread, and the real download)
for p in sorted(home.rglob("*"), reverse=True):
    p.unlink() if p.is_file() else p.rmdir()
RANGES["on"] = False
llm_local.install(); wait()
check("fallback: whole archive", SEEN["full"] == 2 and llm_local.installed() and not (home / "lib/ollama/cuda_v12").exists(), SEEN)
check("fallback: archive removed", not (home / "ollama.zip.part").exists())

# pull a model: progress to the end, then the program switches to it
try:
    llm_local.pull("nonexistent:1b")
    check("unknown model refused", False)
except ValueError:
    check("unknown model refused", True)
llm_local.pull("gemma3:4b"); wait()
st = llm_local.status()
check("model ready", st["models"]["gemma3:4b"]["ready"] and st["error"] is None, st)
s = ai.settings()
check("switched on after download", s["enabled"] and s["provider"] == "local" and s["model"] == "gemma3:4b", {k: s[k] for k in ("enabled", "provider", "model")})

# asking the local model: native Ollama call with a big context, nothing about keys
res = ai.structure("Жалобы на боль от холодного в 36. Поставлена пломба.")
check("answer parsed", res["fields"].get("complaints") == "Боль от холодного." and res["teeth"] == {"36": "Пломба"}, res)
c = SEEN["chat"] or {}
check("context large enough for a visit", c.get("options", {}).get("num_ctx", 0) >= 8192, c.get("options"))
check("not streamed", c.get("stream") is False)
check("local needs no key", "local" in ai.PROVIDERS and ai.save({"enabled": True, "provider": "local", "model": "gemma3:4b"})["provider"] == "local")
try:
    ai.save({"enabled": True, "provider": "local", "model": ""})
    check("model required", False)
except ValueError as e:
    check("model required", "Скачайте модель" in str(e), e)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print("FAIL:", x)
sys.exit(1 if FAIL else 0)
