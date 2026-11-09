"""Clinic server: one computer keeps the database and syncs with Dentist Plus; every computer in the
clinic network (including this one) opens the program as a page served from here.

HTTP  :8765  — UI files, /api/<method> (data), /auth/<method> (login, staff), /ping
UDP   :8766  — answers "where is the server?" broadcasts from client computers
"""
from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import config
from auth import AUDITED, Auth, AuthError, set_current_user

log = logging.getLogger("server")

DISCOVER_MSG = b"DENTALDESK_DISCOVER_V1"
MAX_BODY = 25 * 1024 * 1024
APP_ID = "dentaldesk"


def server_id() -> str:
    s = config.load_settings()
    if not s.get("server_id"):
        s = config.save_settings({"server_id": uuid.uuid4().hex})
    return s["server_id"]


def server_info(port) -> dict:
    return {"app": APP_ID, "server_id": server_id(), "name": config.BRAND["name"], "version": config.VERSION,
            "host": socket.gethostname(), "port": port}


def _brief(args) -> str:
    """Short description of what was changed, for the action journal (ids, titles — not whole records)."""
    parts = []
    for a in args[:3]:
        if isinstance(a, dict):
            for k in ("id", "patient_id", "title", "start", "amount", "method", "status"):
                if a.get(k) not in (None, ""):
                    parts.append(f"{k}={str(a[k])[:40]}")
        elif isinstance(a, (str, int, float)):
            parts.append(str(a)[:40])
        elif isinstance(a, list):
            parts.append(f"{len(a)} шт.")
    return ", ".join(parts)[:300]


def _strip_patient(p, perms):
    """A card without medcard / billing rights shows only what the role may see."""
    if not p:
        return p
    if "medcard_view" not in perms:
        p["records"], p["teeth_local"], p["surf_local"] = [], {}, {}
    if not perms.intersection({"billing", "payments"}):
        p["invoices"], p["balance_local"] = [], 0
    if "docs" not in perms:
        p["documents"] = []
    return p


class ClinicServer:
    def __init__(self, api, db, port=8765, host="0.0.0.0"):
        self.api, self.db, self.port, self.host = api, db, port, host
        self.auth = Auth(db)
        self.httpd = None
        self.ui_dir = str(config.resource_dir() / "ui")

    # ------------------------------------------------------------ dispatch --
    def call_auth(self, name, args, token, ip, agent, is_local):
        a = self.auth
        if name == "state":
            return a.state(token, is_local)
        if name == "bootstrap":
            return a.bootstrap(args[0] if args else {}, ip, agent, is_local)
        if name == "register":
            return a.register(args[0] if args else {}, ip)
        if name == "login":
            return a.login(*(list(args) + ["", ""])[:2], ip, agent)
        if name == "logout":
            return a.logout(token)
        if name == "pin_users":
            return a.pin_users()
        if name == "pin_login":
            return a.pin_login(*(list(args) + ["", ""])[:2], ip, agent)
        user = a.user_for(token)
        if not user:
            raise AuthError("Войдите в программу заново")
        if name == "change_password":
            return a.change_password(user, *(list(args) + ["", ""])[:2])
        if name == "set_pin":
            return a.set_pin(user, *(list(args) + ["", ""])[:2])
        if name == "clear_pin":
            return a.clear_pin(user)
        if "staff" not in a.effective_perms(user):
            raise AuthError("Раздел «Сотрудники» доступен только директору", 403)
        if name == "staff_list":
            return {"staff": a.staff_list(), "doctors": self.db.doctors()}
        if name == "staff_save":
            return a.staff_save(user, args[0])
        if name == "staff_reject":
            return a.staff_reject(user, args[0])
        if name == "staff_reset_password":
            return a.staff_reset_password(user, args[0], args[1] if len(args) > 1 else "")
        if name == "audit_list":
            return a.audit_list(*args[:3])
        if name == "roles_list":    # 2.14: positions and what each may see and do
            return a.roles_list()
        if name == "role_save":
            return a.role_save(user, args[0] if args else {})
        if name == "role_reset":
            return a.role_reset(user, args[0] if args else "")
        if name == "role_delete":
            return a.role_delete(user, args[0] if args else "")
        raise AuthError("Неизвестное действие", 404)

    def call_api(self, name, args, token, ip):
        if name.startswith("_") or not callable(getattr(self.api, name, None)):
            raise AuthError("Неизвестное действие", 404)
        user = self.auth.require(token, name)
        set_current_user(user)
        try:
            result = getattr(self.api, name)(*args)
        finally:
            set_current_user(None)
        if name == "patient":
            result = _strip_patient(result, set(self.auth.effective_perms(user)))
        elif name == "visit" and result:
            perms = set(self.auth.effective_perms(user))
            if "medcard_view" not in perms:
                result["records"] = []
            if not perms.intersection({"billing", "payments"}):
                result["invoices"] = []
        if name in AUDITED:
            self.auth.log(user, AUDITED[name], _brief(args), ip)
        return result

    # --------------------------------------------------------------- start --
    def start(self):
        srv = self

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=srv.ui_dir, **kw)

            def end_headers(self):
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                super().end_headers()

            def _json(self, code, obj):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.split("?")[0] == "/ping":
                    return self._json(200, server_info(srv.port))
                if self.path.split("?")[0] in ("/t", "/t/"):  # short address for the patient tablet
                    self.send_response(302)
                    self.send_header("Location", "/tablet.html")
                    self.end_headers()
                    return None
                return super().do_GET()

            def do_POST(self):
                ip = self.client_address[0]
                is_local = ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._json(413, {"error": "Слишком большой запрос"})
                try:
                    args = json.loads(self.rfile.read(length) or b"[]")
                    if not isinstance(args, list):
                        args = [args]
                except ValueError:
                    return self._json(400, {"error": "Неверный запрос"})
                token = self.headers.get("X-Session", "")
                agent = self.headers.get("User-Agent", "")
                kind, _, name = self.path.split("?")[0].lstrip("/").partition("/")
                try:
                    if kind == "auth":
                        result = srv.call_auth(name, args, token, ip, agent, is_local)
                    elif kind == "api":
                        result = srv.call_api(name, args, token, ip)
                    elif kind == "tablet":
                        from tablet import TabletError
                        try:
                            result = srv.api._tablet_public(name, args, self.headers.get("X-Tablet-Key", ""), ip)
                        except TabletError as e:
                            return self._json(403, {"error": str(e), "tablet": True})
                    else:
                        return self._json(404, {"error": "Не найдено"})
                    return self._json(200, result)
                except AuthError as e:
                    return self._json(e.code, {"error": str(e), "auth": e.code == 401})
                except (ValueError, KeyError, TypeError) as e:
                    log.info("bad request %s: %s", name, e)
                    return self._json(400, {"error": str(e) or "Неверные данные"})
                except Exception as e:  # noqa: BLE001
                    log.exception("api %s failed", name)
                    return self._json(500, {"error": f"Ошибка на сервере: {e}"})

            def log_message(self, *a):
                pass

        ThreadingHTTPServer.allow_reuse_address = False
        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, name="http", daemon=True).start()
        threading.Thread(target=self._discovery, name="discovery", daemon=True).start()
        log.info("server on %s:%s", self.host, self.port)
        return self

    def _discovery(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", self.port + 1))
        except OSError as e:
            log.warning("discovery disabled: %s", e)
            return
        info = json.dumps(server_info(self.port)).encode()
        while True:
            try:
                data, addr = s.recvfrom(256)
                if data.strip() == DISCOVER_MSG:
                    s.sendto(info, addr)
            except OSError:
                continue

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()


# ------------------------------------------------------------------- client side --
def discover(timeout=1.5, port=8765) -> list[dict]:
    """Ask the local network for clinic servers. Returns [{url, name, host, server_id, version}]."""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.3)
    try:
        for _ in range(2):
            for target in ("255.255.255.255", "127.0.0.1"):
                try:
                    s.sendto(DISCOVER_MSG, (target, port + 1))
                except OSError:
                    pass
            import time
            end = time.time() + timeout / 2
            while time.time() < end:
                try:
                    data, addr = s.recvfrom(2048)
                    info = json.loads(data)
                    if info.get("app") == APP_ID:
                        ip = addr[0]
                        info["url"] = f"http://{ip}:{info.get('port', port)}/"
                        info["ip"] = ip
                        found.setdefault(info["server_id"] + ("" if ip == "127.0.0.1" else ip), info)
                except (socket.timeout, ValueError):
                    continue
                except OSError:
                    break
    finally:
        s.close()
    # prefer real network addresses over loopback for the same server
    by_id = {}
    for info in found.values():
        cur = by_id.get(info["server_id"])
        if not cur or cur["ip"] == "127.0.0.1":
            by_id[info["server_id"]] = info
    return list(by_id.values())


def ping(url, timeout=2.0) -> dict | None:
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/ping", timeout=timeout) as r:  # noqa: S310
            info = json.loads(r.read())
            return info if info.get("app") == APP_ID else None
    except Exception:  # noqa: BLE001
        return None


def _route_ip(target):
    """The local address Windows would send from to reach `target` (UDP connect sends nothing)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((target, 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return ""


def _is_lan(ip):
    """Ordinary home / office network ranges (Wi-Fi, cable): 192.168.x.x, 10.x.x.x, 172.16–31.x.x."""
    p = [int(x) for x in ip.split(".")]
    return p[0] == 10 or (p[0] == 192 and p[1] == 168) or (p[0] == 172 and 16 <= p[1] <= 31)


def local_addresses() -> list[str]:
    """IPv4 addresses of this computer that other clinic computers can use, the most likely one first.

    Skipped: loopback and 169.254.x.x (an adapter that got no address, e.g. a disconnected VPN). First comes the
    Wi-Fi / cable address the default route goes through, then other local networks, then VPN-like addresses
    (Radmin 26.x, Tailscale 100.64–127.x and the like), which a tablet on the clinic Wi-Fi cannot reach."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    main = _route_ip("8.8.8.8")  # the interface with the internet route (no packet is sent)
    for ip in (main, _route_ip("10.255.255.255"), _route_ip("192.168.255.255")):
        if ip:
            ips.add(ip)
    ips = {ip for ip in ips if ip and not ip.startswith(("127.", "169.254.", "0."))}
    return sorted(ips, key=lambda ip: (not _is_lan(ip), ip != main, [int(x) for x in ip.split(".")]))


def network_categories() -> dict:
    """Windows network type of each local address: {"192.168.1.14": "Public"} (Public / Private / DomainAuthenticated).
    A «Public» network blocks incoming connections, so a tablet or another PC cannot reach this one."""
    if sys.platform != "win32":
        return {}
    import subprocess
    ps = ("$p=@{}; Get-NetConnectionProfile | ForEach-Object { $p[$_.InterfaceIndex]=[string]$_.NetworkCategory };"
          "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $p.ContainsKey($_.InterfaceIndex) } |"
          " ForEach-Object { $_.IPAddress + '=' + $p[$_.InterfaceIndex] }")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], capture_output=True, text=True,
                           timeout=8, creationflags=0x08000000, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for line in (r.stdout or "").splitlines():
        ip, _, cat = line.strip().partition("=")
        if ip and cat:
            out[ip] = cat
    return out
