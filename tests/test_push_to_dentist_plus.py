"""Mock Dentist Plus with write endpoints; test automatic push end to end."""
from pathlib import Path
APP = str(Path(__file__).resolve().parents[1] / 'app')
import json, os, sys, threading, tempfile
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, APP)
today = date.today().isoformat()
VISITS = [{"id": 100, "patient_id": 5, "doctor_id": 7, "branch_id": 1, "start": f"{today} 10:00:00", "end": f"{today} 10:30:00", "status": "Подтверждён"}]
PATIENTS = {5: {"id": 5, "fio": "Старый Пациент", "phone": "+79990000000"}}
NEXT = {"v": 200, "p": 800}
MODE = {"reject_visits": False}
WRITES = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def body(self): return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def auth_ok(self): return self.headers.get("Authorization") == "Bearer TKN"
    def do_POST(self):
        p = urlparse(self.path).path.replace("/partner/", "")
        b = self.body()
        if p == "auth": return self.send(200, {"token": "TKN"})
        if not self.auth_ok(): return self.send(401, {"error": "auth"})
        WRITES.append(("POST", p, b))
        if p == "patients":
            NEXT["p"] += 1; pid = NEXT["p"]; PATIENTS[pid] = {"id": pid, "fio": f"{b.get('lname')} {b.get('fname')}", "phone": b.get("phone")}
            return self.send(201, {"data": {"id": pid}})
        if p == "visits":
            if MODE["reject_visits"] or "start" not in b:
                return self.send(422, {"message": "Ошибка валидации", "errors": {"date_start": ["Поле date_start обязательно."]}})
            NEXT["v"] += 1; vid = NEXT["v"]
            VISITS.append({"id": vid, "patient_id": int(b["patient_id"]), "doctor_id": int(b.get("doctor_id") or 0) or None,
                           "branch_id": 1, "start": b["start"], "end": b.get("end"), "status": "Запланирован"})
            return self.send(201, {"id": vid})
        self.send(404, {"error": "nf"})
    def do_PUT(self):
        p = urlparse(self.path).path.replace("/partner/", "")
        if not self.auth_ok(): return self.send(401, {"error": "auth"})
        b = self.body(); WRITES.append(("PUT", p, b))
        vid = int(p.split("/")[1])
        for v in VISITS:
            if v["id"] == vid:
                v.update({k: b[k] for k in ("start", "end", "status", "doctor_id") if k in b}); return self.send(200, {"data": v})
        self.send(404, {"error": "nf"})
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if not self.auth_ok(): return self.send(401, {"error": "auth"})
        p = u.path.replace("/partner/", "")
        page = int(q.get("page", 1))
        def paged(items): return {"data": items if page == 1 else [], "meta": {"current_page": page, "last_page": 1}}
        if p == "branches": return self.send(200, paged([{"id": 1, "title": "Филиал"}]))
        if p == "doctors": return self.send(200, paged([{"id": 7, "name": "Доктор"}, {"id": 8, "name": "Доктор 2"}]))
        if p == "visits":
            f, t = q["date_from"], q["date_to"]
            return self.send(200, paged([v for v in VISITS if f <= v["start"][:10] <= t]))
        if p.startswith("patients/"):
            pid = int(p.split("/")[1]); return self.send(200, {"data": PATIENTS.get(pid, {"id": pid})})
        self.send(404, {"error": "nf"})

srv = ThreadingHTTPServer(("127.0.0.1", 8798), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

import config, db as dbm
from sync import SyncWorker
from local import Local
config.save_settings({"demo": False, "base_url": "http://127.0.0.1:8798/partner", "login": "u", "pass_enc": config.protect("p"),
                      "transfer_mode": "manual", "patient_extras": []})
d = dbm.DB(); w = SyncWorker(d); L = Local(d)
print("1 initial sync:", w.sync_once(), d.counts()["visits"])

# offline work: new patient + visit for him, and a move of the existing DP visit
np = L.create_patient({"lname": "Новикова", "fname": "Анна", "phone": "+7 900 111-22-33"})
L.save_visit({"patient_id": np["id"], "doctor_id": "7", "branch_id": "1", "start": f"{today} 15:00", "end": f"{today} 15:30", "title": "Консультация"})
L.save_visit({"id": "100", "patient_id": "5", "doctor_id": "8", "branch_id": "1", "start": f"{today} 12:00", "end": f"{today} 12:30", "action": "move"})
print("2 pending (manual mode):", d.pending_count())
w.sync_once(); print("3 manual mode, writes to DP:", len(WRITES), "pending:", d.pending_count())

config.save_settings({"transfer_mode": "auto"})
w.sync_once()
print("4 auto mode writes:", [(m, p) for m, p, _ in WRITES])
print("  visit body:", [b for m, p, b in WRITES if p == "visits"][0])
print("  DP visits now:", [(v["id"], v["patient_id"], v["start"][:16], v["doctor_id"]) for v in VISITS])
j = L.journal(show_done=True)
print("  journal:", [(x["what"], x["transferred"], x["push_status"], x["push_error"]) for x in j if x.get("auto")])
print("  pending:", d.pending_count())
w.sync_once()   # second sync: merge temp patient, drop transferred overrides
print("5 after next sync: local patients:", d.q("SELECT COUNT(*) n FROM patients WHERE local=1")[0]["n"],
      "local_visits:", d.q("SELECT COUNT(*) n FROM local_visits")[0]["n"],
      "day:", [(x["patient_name"], x["start"][11:16], x["doctor_name"], x["local"]) for x in d.day(today)])

# dedupe: a local visit identical to one already in DP must not be posted again
n0 = len(WRITES)
L.save_visit({"patient_id": "5", "doctor_id": "7", "branch_id": "1", "start": f"{today} 12:00", "end": f"{today} 12:30"})
w.sync_once()
print("6 dedupe: new POSTs:", [x for x in WRITES[n0:] if x[0] == "POST"], [(x["push_status"], x["push_error"]) for x in L.journal(True) if x["kind"] == "visit"][-1])

# validation error must keep the item pending with the server message
MODE["reject_visits"] = True
L.save_visit({"patient_id": "5", "doctor_id": "7", "branch_id": "1", "start": f"{today} 17:00", "end": f"{today} 17:30"})
w.sync_once()
last = [x for x in L.journal() if x["kind"] == "visit"][-1]
print("7 rejected:", last["transferred"], last["push_status"], last["push_error"])
srv.shutdown()
