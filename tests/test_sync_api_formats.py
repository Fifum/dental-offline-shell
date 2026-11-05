"""Sync robustness: 4 differently shaped fake Dentist Plus servers + failures in the middle."""
from pathlib import Path
APP = str(Path(__file__).resolve().parents[1] / 'app')
import json, os, sys, threading, tempfile, time, importlib
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, APP)
T = date.today()
DAYS = [T + timedelta(days=k) for k in (-20, -3, 0, 0, 1, 5, 25, 40)]   # 40 = outside window, must be ignored
STATE = {"flavor": "A", "calls": 0, "fail429": 1, "fail500_patient": "502", "hits": {}}

def visit_obj(i, d, flavor):
    h = 9 + i
    if flavor == "A":   # Laravel-ish: date + time fields, nested patient + status object
        return {"id": 1000 + i, "date": d.isoformat(), "time": f"{h:02d}:00", "time_to": f"{h:02d}:45",
                "patient": {"id": 500 + i, "fio": f"Пациент А{i}"}, "doctor_id": 7, "branch_id": 1,
                "status": {"id": 2, "title": "Подтверждён"}, "comment": "к"}
    if flavor == "B":   # ISO with Z and offset, doctor object
        s = datetime(d.year, d.month, d.day, h, 0, tzinfo=timezone.utc)
        return {"id": f"b{i}", "start_at": s.isoformat().replace("+00:00", "Z"), "end_at": (s + timedelta(minutes=30)).isoformat(),
                "patient_id": 600 + i, "doctor": {"id": 8, "name": "Доктор Б"}, "status": "confirmed"}
    if flavor == "C":   # unix timestamps, client_id / user_id names
        s = datetime(d.year, d.month, d.day, h, 30)
        return {"id": 3000 + i, "date_start": int(s.timestamp()), "date_end": int((s + timedelta(hours=1)).timestamp()),
                "client_id": 700 + i, "user_id": 9, "filial_id": 2, "state": "Новый"}
    # D: "dd.mm.yyyy HH:MM" strings, duration only
    return {"id": 4000 + i, "datetime": d.strftime("%d.%m.%Y") + f" {h:02d}:15", "duration": 40,
            "patient": {"id": 800 + i, "lname": "Дэ", "fname": f"Пациент{i}"}, "doctors": [{"id": 10, "lname": "Врачев", "fname": "Д"}], "status_name": "Пришёл"}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        f = STATE["flavor"]
        tok = {"A": {"token": "T"}, "B": {"access_token": "T"}, "C": {"data": {"token": "T"}}, "D": {"api_token": "T"}}[f]
        self.send(200, tok)
    def do_GET(self):
        STATE["calls"] += 1
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path.replace("/partner/", "")
        STATE["hits"][p.split("/")[0]] = STATE["hits"].get(p.split("/")[0], 0) + 1
        if self.headers.get("Authorization") != "Bearer T": return self.send(401, {"error": "Авторизация не успешна"})
        f = STATE["flavor"]; page = int(q.get("page", 1)); per = int(q.get("per_page", 100))
        def wrap(items, key="data"):
            chunk = items[(page - 1) * per: page * per]
            last = max(1, -(-len(items) // per))
            if f == "A": return {"data": chunk, "meta": {"current_page": page, "last_page": last}}
            if f == "B": return items                      # plain list, ignores page entirely
            if f == "C": return {"data": {"data": chunk, "current_page": page, "last_page": last,
                                          "next_page_url": f"x?page={page + 1}" if page < last else None}}
            return {"visits" if key == "visits" else "data": chunk, "links": {"next": f"?page={page + 1}" if page < last else None}}
        if p == "branches": return self.send(200, wrap([{"id": 1, "title": "Центр"}, {"id": 2, "name": "Север"}]))
        if p == "doctors":
            if f == "D": return self.send(404, {"error": "not found"})          # missing endpoint must not break sync
            return self.send(200, wrap([{"id": 7, "fio": "Иванов И.И."}, {"id": 8, "name": "Доктор Б"}, {"id": 9, "last_name": "Сидоров", "first_name": "С"}]))
        if p == "services": return self.send(404, {"error": "nf"})
        if p == "visits":
            if STATE["fail429"] > 0: STATE["fail429"] -= 1; return self.send(429, {"error": "too many"})
            items = [visit_obj(i, d, f) for i, d in enumerate(DAYS)]
            if f != "B":   # B ignores the date filter on purpose
                fr, to = q.get("date_from"), q.get("date_to")
                def vd(x):
                    from normalize import visit_fields
                    return (visit_fields(x)["start"] or "")[:10]
                items = [x for x in items if fr <= vd(x) <= to]
            return self.send(200, wrap(items, "visits"))
        if p.startswith("patients/"):
            pid = p.split("/")[1]
            if pid == STATE["fail500_patient"]: return self.send(500, {"error": "boom"})
            body = {"id": int(pid), "fio": f"Карта {pid}", "phone": "+79990000000", "birthday": "1990-05-06", "allergy": "Лидокаин"}
            return self.send(200, {"data": body} if f in ("A", "C") else body)
        if p == "diagnoses": return self.send(422, {"message": "patient_id invalid"})
        self.send(404, {"error": "nf"})

srv = ThreadingHTTPServer(("127.0.0.1", 8797), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()

for flavor in "ABCD":
    os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
    for m in ("config", "db", "sync", "demo", "catalog", "local", "main", "pusher"):
        if m in sys.modules: importlib.reload(sys.modules[m])
    import config, db as dbm
    from sync import SyncWorker
    STATE.update(flavor=flavor, calls=0, fail429=1, hits={})
    config.save_settings({"demo": False, "base_url": "http://127.0.0.1:8797/partner", "login": "u", "pass_enc": config.protect("p")})
    d = dbm.DB(); w = SyncWorker(d)
    t0 = time.time(); ok = w.sync_once(); dt = time.time() - t0
    vis = d.q("SELECT v.start, v.\"end\", v.status, p.name pn, dd.name dn FROM visits v LEFT JOIN patients p ON p.id=v.patient_id LEFT JOIN doctors dd ON dd.id=v.doctor_id ORDER BY start")
    hist = d.sync_history(1)[0]
    print(f"\n=== flavor {flavor}: ok={ok} {dt:.1f}s calls={STATE['calls']} hits={STATE['hits']}")
    print("  msg:", hist["message"], "| counts:", hist["counts"])
    print("  visits:", len(vis), "(expected 7, the +40 day one dropped)")
    for v in vis[:3]:
        print("   ", v["start"], "-", v["end"], "|", v["status"], "|", v["pn"], "|", v["dn"])
    print("  doctors:", [r["name"] for r in d.doctors()], " branches:", [r["name"] for r in d.branches()])
    sample = d.q("SELECT id FROM patients LIMIT 1")
    if sample:
        p = d.patient(sample[0]["id"]); print("  patient card:", p["name"], p["phone"], p["birth"], p["data"].get("allergy"))
srv.shutdown()
