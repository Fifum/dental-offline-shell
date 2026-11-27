"""Local preview of the phone app: python dev_server.py → http://localhost:8765 (pages /e/… and /j fall back to index.html,
as the rewrites in vercel.json do). The cloud lets localhost in (CORS)."""
import http.server
import os
from pathlib import Path

ROOT = Path(__file__).parent


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def send_head(self):
        p = self.path.split("?")[0].split("#")[0]
        if p.startswith("/e/") or p in ("/j", "/j/"):
            self.path = "/index.html"
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


http.server.ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", 8765))), H).serve_forever()
