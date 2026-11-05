"""Dev only: serve the UI in a normal browser with the same Python API (http://127.0.0.1:8765)."""
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
from db import DB  # noqa: E402
from main import Api  # noqa: E402
from sync import SyncWorker  # noqa: E402

db = DB()
worker = SyncWorker(db)
worker.start()
API = Api(db, worker)
UI = str(config.resource_dir() / "ui")


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=UI, **kw)

    def do_POST(self):
        name = self.path.split("/api/", 1)[-1]
        args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"[]")
        if name.startswith("_") or not hasattr(API, name):
            self.send_error(404)
            return
        code = 200
        try:
            result = getattr(API, name)(*args)
        except Exception as e:  # noqa: BLE001
            code, result = 500, {"error": str(e)}
        body = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
