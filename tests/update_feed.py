"""A fake GitHub release feed for the update tests (3.12).

Serves the files of a folder at /<repo>/releases/latest/download/<name> the way GitHub does (302 to /assets/<name>),
with HTTP Range, a log of every file request (name, Range header) and switches: cut a download short after N bytes,
ignore Range, send slowly."""
import http.server
import re
import threading
import time
from pathlib import Path


class Feed:
    def __init__(self, folder, repo="Fifum/dental-desk-updates"):
        self.dir, self.repo = Path(folder), repo
        self.hits = []        # (file name, Range header or None)
        self.cut = {}         # file name → bytes to send before the connection breaks (once)
        self.no_range = False
        self.slow = 0.0       # seconds per 64 KB
        feed = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                pre = f"/{feed.repo}/releases/latest/download/"
                if self.path.startswith(pre):
                    self.send_response(302)
                    self.send_header("Location", "/assets/" + self.path[len(pre):] + f"?sig=x{time.time()}")
                    self.end_headers()
                    return
                if not self.path.startswith("/assets/"):
                    self.send_response(404)
                    self.end_headers()
                    return
                name = self.path[8:].split("?")[0]
                f = feed.dir / name
                if not f.is_file():
                    self.send_response(404)
                    self.end_headers()
                    return
                body = f.read_bytes()
                rng = self.headers.get("Range")
                feed.hits.append((name, rng))
                m = re.fullmatch(r"bytes=(\d+)-", rng or "")
                start = int(m[1]) if m and not feed.no_range else 0
                if start and start >= len(body):
                    self.send_response(416)
                    self.end_headers()
                    return
                part = body[start:]
                self.send_response(206 if start else 200)
                if start:
                    self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
                self.send_header("Content-Length", str(len(part)))
                self.end_headers()
                limit = feed.cut.pop(name, None)
                out = part if limit is None else part[:limit]
                try:
                    for i in range(0, len(out), 65536):
                        self.wfile.write(out[i:i + 65536])
                        if feed.slow:
                            time.sleep(feed.slow)
                except OSError:
                    pass
                if limit is not None:
                    self.close_connection = True

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/{repo}/releases/latest/download/latest.json"

    def count(self, name):
        return sum(1 for n, _r in self.hits if n == name)

    def ranges(self, name):
        return [r for n, r in self.hits if n == name]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
