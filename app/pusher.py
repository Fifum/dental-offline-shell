"""Automatic transfer of changes made in this app to Dentist Plus.

The partner API's write endpoints are not publicly documented, so endpoint paths and field
names come from settings["write_map"] and can be adjusted without rebuilding. Safety rules:
  * an item counts as transferred only if the server answered 2xx;
  * a write is never retried after it may have reached the server (timeout -> status "unknown",
    staff must check Dentist Plus by hand) — no duplicates;
  * before creating a visit we look for the same visit in Dentist Plus (dedupe);
  * after creating we re-read the day and compare time/doctor, mismatches are flagged.
Medical records, documents, invoices and payments stay manual (no known API, payments need a fiscal receipt).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

import conflicts
from api_client import ApiError, OfflineError
from normalize import as_id, get, visit_fields

log = logging.getLogger("push")

DEFAULT_WRITE_MAP = {
    "datetime_format": "%Y-%m-%d %H:%M:%S",
    "patient_create": {"method": "POST", "path": "patients",
                       "fields": {"lname": "lname", "fname": "fname", "mname": "mname", "phone": "phone",
                                  "birth_date": "birth_date", "gender": "gender", "address": "address", "comment": "comment"}},
    "visit_create": {"method": "POST", "path": "visits",
                     "fields": {"patient_id": "patient_id", "doctor_id": "doctor_id", "branch_id": "branch_id",
                                "start": "start", "end": "end", "title": "description", "comment": "comment"}},
    "visit_update": {"method": "PUT", "path": "visits/{id}",
                     "fields": {"doctor_id": "doctor_id", "branch_id": "branch_id", "start": "start", "end": "end",
                                "title": "description", "comment": "comment", "status": "status"}},
    "status_values": {},   # e.g. {"Отменён": "cancelled"} once the real values are known
}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _err(code, data):
    if isinstance(data, dict):
        msg = data.get("message") or data.get("error") or ""
        errs = data.get("errors")
        if isinstance(errs, dict) and errs:
            parts = [f"{k}: {v[0] if isinstance(v, list) and v else v}" for k, v in list(errs.items())[:4]]
            msg = (msg + " — " if msg else "") + "; ".join(parts)
        if msg:
            return f"HTTP {code}: {msg}"
    return f"HTTP {code}"


def _remote_id(data):
    if isinstance(data, dict):
        return as_id(get(data, "id", "data.id", "visit.id", "patient.id", "result.id", "data.visit.id", "data.patient.id"))
    return None


class Pusher:
    def __init__(self, db, client, settings):
        self.db, self.c = db, client
        wm = dict(DEFAULT_WRITE_MAP)
        wm.update(settings.get("write_map") or {})
        self.wm = wm
        self.p_from, self.p_to = settings.get("visit_from_param", "date_from"), settings.get("visit_to_param", "date_to")
        self.counts = {"sent": 0, "errors": 0, "unknown": 0, "warnings": 0, "conflicts": 0}

    # ------------------------------------------------------------ helpers
    def _own(self, rows, table):
        """With the clinic network or the cloud, every computer sends to Dentist Plus only what was created on it —
        never twice (3.0: «created on it» = the node id in the row's first version)."""
        import config
        import replica
        dev = config.node_id()
        foreign = replica.foreign_ids(self.db, table, dev) if dev else set()
        return [r for r in rows if r["id"] not in foreign]

    def _dt(self, s):
        if not s:
            return None
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").strftime(self.wm.get("datetime_format") or "%Y-%m-%d %H:%M:%S")

    def _body(self, spec, src: dict):
        out = {}
        for ours, theirs in (spec.get("fields") or {}).items():
            v = src.get(ours)
            if v in (None, ""):
                continue
            if ours in ("start", "end"):
                v = self._dt(v)
            if ours == "status":
                v = (self.wm.get("status_values") or {}).get(v, v)
            out[theirs] = v
        return out

    def _mark(self, table, rid, status, error="", remote_id=None, done=False):
        with self.db.tx() as cx:
            cx.execute(f"""UPDATE {table} SET push_status=?, push_error=?, push_at=?,
                           remote_id=COALESCE(?, remote_id)
                           {', transferred=1, transferred_at=?' if done else ''} WHERE id=?""",
                       (status, error, _now(), remote_id, *((_now(),) if done else ()), rid))
        if done:
            self.counts["sent"] += 1
            if status == "warn":
                self.counts["warnings"] += 1
        elif status == "unknown":
            self.counts["unknown"] += 1
        elif status == "conflict":
            self.counts["conflicts"] += 1
        else:
            self.counts["errors"] += 1

    def _day_visits(self, day):
        rows = []
        for raw in self.c.paged("visits", {self.p_from: day, self.p_to: day}, per_page=200, max_pages=10):
            if isinstance(raw, dict):
                rows.append(visit_fields(raw))
        return rows

    def _clash(self, v, src, day_visits, ignore=()):
        """Before sending: is this doctor already busy with another patient at that time in Dentist Plus?
        Returns the text for the transfer list, or "" when the slot is free (or the user said «send anyway»)."""
        if v.get("push_force") or v.get("action") in ("cancel", "status") or conflicts.is_cancelled(v):
            return ""
        found = conflicts.find(src, day_visits, ignore)
        if not found:
            return ""
        ids = [str(f.get("patient_id")) for f in found]
        marks = ",".join("?" * len(ids))
        names = {}
        for r in self.db.q(f"SELECT id, remote_id, name FROM patients WHERE id IN ({marks}) OR remote_id IN ({marks})", ids * 2):
            names[str(r["id"])] = r["name"]
            if r.get("remote_id"):
                names[str(r["remote_id"])] = r["name"]
        for f in found:
            f["patient_name"] = names.get(str(f.get("patient_id")))
        return ("Не отправлено — двойная запись: " + conflicts.describe(found, "в Dentist Plus") +
                ". Перенесите запись или нажмите «Отправить всё равно».")

    # ----------------------------------------------------------- patients
    def push_patients(self):
        spec = self.wm["patient_create"]
        rows = self.db.q("""SELECT * FROM patients WHERE local=1 AND COALESCE(transferred,0)=0
                            AND remote_id IS NULL AND COALESCE(push_status,'') != 'unknown'""")
        rows = self._own(rows, "patients")
        for p in rows:
            raw = json.loads(p["detail"] or p["data"] or "{}")
            body = self._body(spec, raw)
            try:
                code, data = self.c.write(spec["method"], spec["path"], body)
            except OfflineError:
                raise
            except ApiError as e:
                self._mark("patients", p["id"], "unknown", str(e))
                continue
            rid = _remote_id(data)
            if 200 <= code < 300 and rid:
                self._mark("patients", p["id"], "sent", "", rid, done=True)
            elif 200 <= code < 300:
                self._mark("patients", p["id"], "unknown", "Сервер принял, но не вернул id — проверьте пациента в Dentist Plus")
            else:
                self._mark("patients", p["id"], "error", _err(code, data))
                if code in (401, 403):
                    return False
        return True

    # ------------------------------------------------------------- visits
    def push_visits(self):
        rows = self.db.q("""SELECT lv.*, p.remote_id AS patient_remote, p.local AS patient_local
                            FROM local_visits lv LEFT JOIN patients p ON p.id = lv.patient_id
                            WHERE lv.transferred=0 AND COALESCE(lv.push_status,'') != 'unknown'  -- conflicts are re-checked every time
                            ORDER BY lv.created_at""")
        rows = self._own(rows, "local_visits")
        for v in rows:
            pid = v["patient_remote"] if v["patient_local"] else v["patient_id"]
            if not pid:
                self._mark("local_visits", v["id"], "error", "Сначала должен уйти новый пациент")
                continue
            src = dict(v)
            src["patient_id"] = pid
            target = v["remote_id"] or v["origin_id"]
            try:
                if target:  # move / edit / status / cancel of an existing Dentist Plus visit
                    if v["action"] in ("move", "edit"):
                        why = self._clash(v, src, self._day_visits(v["start"][:10]), ignore=(target,))
                        if why:
                            self._mark("local_visits", v["id"], "conflict", why)
                            continue
                    spec = self.wm["visit_update"]
                    code, data = self.c.write(spec["method"], spec["path"].replace("{id}", str(target)), self._body(spec, src))
                    if 200 <= code < 300:
                        self._mark("local_visits", v["id"], "sent", "", target, done=True)
                    else:
                        self._mark("local_visits", v["id"], "error", _err(code, data))
                        if code in (401, 403):
                            return False
                    continue
                # new visit: dedupe first
                day = v["start"][:10]
                day_visits = self._day_visits(day)
                same = [x for x in day_visits
                        if x["patient_id"] == str(pid) and (x["start"] or "")[:16] == v["start"][:16]]
                if same:
                    self._mark("local_visits", v["id"], "sent", "Уже была в Dentist Plus — дубль не создан", same[0]["id"], done=True)
                    continue
                why = self._clash(v, src, day_visits)
                if why:
                    self._mark("local_visits", v["id"], "conflict", why)
                    continue
                spec = self.wm["visit_create"]
                code, data = self.c.write(spec["method"], spec["path"], self._body(spec, src))
                if not (200 <= code < 300):
                    self._mark("local_visits", v["id"], "error", _err(code, data))
                    if code in (401, 403):
                        return False
                    continue
                rid = _remote_id(data)
                # verify what was actually created
                check = [x for x in self._day_visits(day) if (rid and x["id"] == rid) or
                         (x["patient_id"] == str(pid) and (x["start"] or "")[:16] == v["start"][:16])]
                if check and (check[0]["start"] or "")[:16] == v["start"][:16] and (not v["doctor_id"] or check[0]["doctor_id"] in (None, str(v["doctor_id"]))):
                    self._mark("local_visits", v["id"], "sent", "", check[0]["id"], done=True)
                elif check:
                    self._mark("local_visits", v["id"], "warn",
                               f"Создана, но в Dentist Plus время {check[0]['start']} — проверьте запись", check[0]["id"], done=True)
                elif rid:
                    self._mark("local_visits", v["id"], "warn", "Создана, но не найдена при проверке — проверьте в Dentist Plus", rid, done=True)
                else:
                    self._mark("local_visits", v["id"], "unknown", "Сервер ответил успехом, но запись не найдена — проверьте в Dentist Plus")
            except OfflineError:
                raise
            except ApiError as e:
                self._mark("local_visits", v["id"], "unknown" if e.status is None else "error", str(e))
        return True

    def run(self):
        if self.push_patients():
            self.push_visits()
        return self.counts


def merge_pushed_patients(db):
    """After a sync brought the patient back from Dentist Plus under its real id, move everything
    from the temporary local card to the real one and drop the temporary card."""
    rows = db.q("""SELECT l.id AS lid, l.remote_id AS rid FROM patients l
                   JOIN patients r ON r.id = l.remote_id WHERE l.local=1 AND l.remote_id IS NOT NULL""")
    if not rows:
        return 0
    with db.tx() as cx:
        for r in rows:
            for t in ("local_visits", "records", "documents", "invoices", "payments", "notes", "patient_extras"):
                cx.execute(f"UPDATE {t} SET patient_id=? WHERE patient_id=?", (r["rid"], r["lid"]))
            cx.execute("DELETE FROM patients WHERE id=?", (r["lid"],))
    return len(rows)


def simulate_demo(db):
    """Demo mode: pretend the send worked so the workflow can be shown without a real account."""
    with db.tx() as cx:
        for t, extra in (("patients", " AND local=1"), ("local_visits", "")):
            cx.execute(f"""UPDATE {t} SET transferred=1, transferred_at=?, push_status='sent',
                           push_error='демо: отправка имитируется', push_at=? WHERE COALESCE(transferred,0)=0{extra}""",
                       (_now(), _now()))
