"""Automatic transfer of changes made in this app to Dentist Plus (transfer_mode = "auto").

Endpoints and fields follow the partner documentation (https://api-balancer.dentist-plus.com/partner/docs/):
  * POST /patients — branch_id* and fname* required; date_of_birth YYYY-MM-DD; gender male / female; description;
  * PUT /patients/{id} — the same fields (a card changed here, table patient_edits);
  * POST /visits — branch_id*, patient_id*, doctor_id*, start*, end* («YYYY-MM-DD HH:MM:SS»), description,
    chair_id, status_id (an id of the dictionary /record_statuses);
  * PUT /visits/{id} — the same required set: the visit is read first (GET /visits/{id}) and its writable fields
    are sent back with our change on top, so nothing the API needs is lost (move, edit, status, a medical record);
  * POST /visits/{id}/cancel {reason} — cancelling.
Endpoint paths and field names can still be overridden by settings["write_map"] without rebuilding.

Safety rules:
  * an item counts as transferred only if the server answered 2xx;
  * a write is never retried after it may have reached the server (timeout -> status "unknown",
    staff must check Dentist Plus by hand) — no duplicates;
  * before creating a visit we look for the same visit in Dentist Plus (dedupe);
  * after creating we re-read the day and compare time/doctor, mismatches are flagged;
  * after a PUT of a visit the services on its teeth are compared with what was there before — fewer means
    «проверьте визит» (the documentation does not say whether PUT keeps fields it was not sent).
Documents, invoices and payments stay manual (payments need a fiscal receipt).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

import conflicts
from api_client import ApiError, OfflineError
from normalize import as_id, get, visit_fields

log = logging.getLogger("push")

PATIENT_FIELDS = {"lname": "lname", "fname": "fname", "mname": "mname", "phone": "phone", "birth_date": "date_of_birth",
                  "gender": "gender", "address": "address", "email": "email", "comment": "description"}
DEFAULT_WRITE_MAP = {
    "datetime_format": "%Y-%m-%d %H:%M:%S",
    "patient_create": {"method": "POST", "path": "patients", "fields": dict(PATIENT_FIELDS)},
    "patient_update": {"method": "PUT", "path": "patients/{id}", "fields": dict(PATIENT_FIELDS)},
    "visit_create": {"method": "POST", "path": "visits",
                     "fields": {"patient_id": "patient_id", "doctor_id": "doctor_id", "branch_id": "branch_id",
                                "start": "start", "end": "end", "title": "description"}},
    "visit_update": {"method": "PUT", "path": "visits/{id}",
                     "fields": {"doctor_id": "doctor_id", "branch_id": "branch_id", "start": "start", "end": "end",
                                "title": "description"}},
    "visit_cancel": {"method": "POST", "path": "visits/{id}/cancel"},
    # sections of a medical record (records.data) -> fields of the Dentist Plus visit; "*" collects the rest
    "record_fields": {"complaints": "complaints", "anamnesis": "disease_history", "objective": "objectively",
                      "*": "description_doctor"},
    "status_values": {},   # our status word -> Dentist Plus status id or title, when the automatic match is wrong
}

# writable fields of a visit (PUT /visits/{id}) and where they are in its GET answer
_VISIT_KEEP = {"branch_id": ("branch_id", "branch.id"), "patient_id": ("patient_id", "patient.id"),
               "doctor_id": ("doctor_id", "doctor.id"), "assistant_id": ("assistant_id", "assistant.id"),
               "chair_id": ("chair_id", "chair.id"), "start": ("start",), "end": ("end",), "description": ("description",),
               "type": ("type",), "record_type_id": ("record_type_id", "custom_type.id"), "field_id": ("field_id", "field.id"),
               "complex_id": ("complex_id",)}
_VISIT_TEXT = ("complaints", "inspection", "objectively", "subjectively", "bite", "description_doctor", "disease_history",
               "life_history", "examinations_data")
_PATIENT_KEEP = ("fname", "mname", "lname", "phone", "gender", "date_of_birth", "address", "card", "email", "snils", "iin",
                 "passport", "passport_series", "passport_given_by", "passport_issue_date", "passport_dep_code", "url",
                 "description", "representative_passport", "representative_fio", "representative_phone",
                 "representative_address", "send_marketing", "send_notifications")
GENDER = {"м": "male", "муж": "male", "мужской": "male", "male": "male", "m": "male",
          "ж": "female", "жен": "female", "женский": "female", "female": "female", "f": "female"}
AUTO_WHO = "Автоперенос"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _err(code, data):
    if isinstance(data, dict):
        msg = data.get("message") or data.get("error") or ""
        if not isinstance(msg, str):
            msg = str(msg)
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


def _int(v):
    """Dentist Plus ids are integers; ours are strings."""
    s = str(v).strip() if v is not None else ""
    return int(s) if s.isdigit() else (v if s else None)


def _unwrap(data):
    return data["data"] if isinstance(data, dict) and isinstance(data.get("data"), dict) else data


def _stem(word):
    w = re.sub(r"\s+", " ", str(word or "").lower().replace("ё", "е")).strip()
    return re.sub(r"[аяоеыийь]+$", "", w)


def _services_count(visit):
    teeth = visit.get("teeth") if isinstance(visit, dict) else None
    return sum(len(t.get("services") or []) for t in teeth if isinstance(t, dict)) if isinstance(teeth, list) else 0


class Pusher:
    def __init__(self, db, client, settings):
        self.db, self.c = db, client
        wm = dict(DEFAULT_WRITE_MAP)
        wm.update(settings.get("write_map") or {})
        self.wm = wm
        self.s = settings
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

    def _dict(self, key):
        try:
            v = json.loads(self.db.meta_get(key) or "[]")
            return v if isinstance(v, list) else []
        except ValueError:
            return []

    def _status_id(self, word):
        """Our status word («Подтверждён») -> id of /record_statuses («Подтверждена»); None when there is no match
        (Dentist Plus then keeps / sets its default)."""
        if not word:
            return None
        statuses = self._dict("dp_record_statuses")
        manual = (self.wm.get("status_values") or {}).get(word)
        if manual is not None:
            if str(manual).isdigit():
                return int(manual)
            word = manual
        w = str(word).lower().replace("ё", "е").strip()
        for x in statuses:
            if str(x.get("title", "")).lower().replace("ё", "е").strip() == w:
                return _int(x.get("id"))
        stem = _stem(word)
        for x in statuses:
            if stem and _stem(x.get("title")) == stem:
                return _int(x.get("id"))
        return None

    def _chair_id(self, chair):
        if not chair:
            return None
        if str(chair).isdigit():
            return int(chair)
        for x in self._dict("dp_chairs"):
            if str(x.get("title", "")).strip().lower() == str(chair).strip().lower():
                return _int(x.get("id"))
        return None

    def _branch(self, branch_id=None, doctor_id=None):
        """branch_id is required by POST /patients and /visits: the visit's, else the doctor's, else the settings', else
        the only (first) branch synced from Dentist Plus."""
        if branch_id:
            return _int(branch_id)
        if doctor_id:
            r = self.db.one("SELECT branch_id FROM doctors WHERE id=?", (str(doctor_id),))
            if r and r["branch_id"]:
                return _int(r["branch_id"])
        if self.s.get("dp_branch_id"):
            return _int(self.s["dp_branch_id"])
        r = self.db.one("SELECT id FROM branches ORDER BY CAST(id AS INTEGER) LIMIT 1")
        return _int(r["id"]) if r else None

    def _body(self, spec, src: dict):
        out = {}
        for ours, theirs in (spec.get("fields") or {}).items():
            v = src.get(ours)
            if v in (None, ""):
                continue
            if ours in ("start", "end"):
                v = self._dt(v)
            elif ours in ("patient_id", "doctor_id", "branch_id"):
                v = _int(v)
            elif ours == "gender":
                v = GENDER.get(str(v).strip().lower())
                if not v:
                    continue
            elif ours == "birth_date":
                v = str(v)[:10]
            out[theirs] = v
        return out

    def _visit_body(self, spec, src: dict):
        body = self._body(spec, src)
        desc = "\n".join(x for x in (str(src.get("title") or "").strip(), str(src.get("comment") or "").strip()) if x)
        if desc and "description" in (spec.get("fields") or {}).values():
            body["description"] = desc
        chair = self._chair_id(src.get("chair"))
        if chair:
            body["chair_id"] = chair
        if src.get("action") not in ("cancel",):
            st = self._status_id(src.get("status"))
            if st is not None:
                body["status_id"] = st
        if not body.get("branch_id"):
            b = self._branch(src.get("branch_id"), src.get("doctor_id"))
            if b is not None:
                body["branch_id"] = b
        return body

    def _mark(self, table, rid, status, error="", remote_id=None, done=False):
        extra = ", transferred_by=COALESCE(transferred_by, ?)" if done and table == "records" else ""
        with self.db.tx() as cx:
            cx.execute(f"""UPDATE {table} SET push_status=?, push_error=?, push_at=?,
                           remote_id=COALESCE(?, remote_id)
                           {', transferred=1, transferred_at=?' if done else ''}{extra} WHERE id=?""",
                       (status, error, _now(), remote_id, *((_now(),) if done else ()), *((AUTO_WHO,) if extra else ()), rid))
        if done:
            self.counts["sent"] += 1
            if status == "warn":
                self.counts["warnings"] += 1
        elif status == "unknown":
            self.counts["unknown"] += 1
        elif status == "conflict":
            self.counts["conflicts"] += 1
        elif status != "wait":
            self.counts["errors"] += 1

    def _day_visits(self, day):
        rows = []
        for raw in self.c.paged("visits", {self.p_from: day, self.p_to: day}, per_page=200, max_pages=10):
            if isinstance(raw, dict):
                f = visit_fields(raw)
                rows.append(f)
        return rows

    def _get_visit(self, vid):
        """GET /visits/{id} -> the visit, or raises ApiError (404 = deleted in Dentist Plus)."""
        return _unwrap(self.c.request(f"visits/{vid}"))

    @staticmethod
    def _keep_visit(cur: dict) -> dict:
        """The writable fields of a visit as Dentist Plus gave it (GET), in the shape PUT takes."""
        out = {}
        for k, paths in _VISIT_KEEP.items():
            v = get(cur, *paths)
            if v not in (None, ""):
                out[k] = v
        for k in _VISIT_TEXT:
            if cur.get(k) not in (None, ""):
                out[k] = cur[k]
        if isinstance(cur.get("include_in_form_043"), bool):
            out["include_in_form_043"] = cur["include_in_form_043"]
        st = get(cur, "status_id", "status.id")
        if st not in (None, "") and not isinstance(st, dict):
            out["status_id"] = _int(st)
        return out

    def _put_visit(self, target, changes: dict, table, rid, warn_text=""):
        """Read the visit, put our changes over its writable fields, PUT it, check the services did not go away.
        Returns the HTTP code (or None when nothing was sent)."""
        try:
            cur = self._get_visit(target)
        except ApiError as e:
            if e.status == 404:
                self._mark(table, rid, "error", "Визит не найден в Dentist Plus — возможно, его удалили")
                return None
            raise
        before = _services_count(cur)
        body = {**self._keep_visit(cur if isinstance(cur, dict) else {}), **changes}
        for k in ("branch_id", "patient_id", "doctor_id"):
            if body.get(k) is not None:
                body[k] = _int(body[k])
        missing = [k for k in ("branch_id", "patient_id", "doctor_id", "start", "end") if not body.get(k)]
        if missing:
            self._mark(table, rid, "error", "Не хватает полей для Dentist Plus: " + ", ".join(missing))
            return None
        spec = self.wm["visit_update"]
        code, data = self.c.write(spec["method"], spec["path"].replace("{id}", str(target)), body)
        if 200 <= code < 300:
            after = _services_count(_unwrap(data)) if isinstance(_unwrap(data), dict) and "teeth" in _unwrap(data) else before
            if after < before:
                self._mark(table, rid, "warn", f"Отправлено, но у визита в Dentist Plus стало меньше услуг ({before} → {after}) — "
                                               "проверьте визит", target, done=True)
            else:
                self._mark(table, rid, "warn" if warn_text else "sent", warn_text, target, done=True)
        else:
            self._mark(table, rid, "error", _err(code, data))
        return code

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
            if not body.get("fname"):
                self._mark("patients", p["id"], "error", "Укажите имя пациента — Dentist Plus не создаёт пациента без имени")
                continue
            if not body.get("branch_id"):
                lv = self.db.one("SELECT branch_id, doctor_id FROM local_visits WHERE patient_id=? ORDER BY created_at LIMIT 1", (p["id"],))
                br = self._branch(lv["branch_id"] if lv else None, lv["doctor_id"] if lv else None)
                if br is None:
                    self._mark("patients", p["id"], "error", "Не известен филиал Dentist Plus — дождитесь синхронизации филиалов")
                    continue
                body["branch_id"] = br
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

    def push_patient_edits(self):
        """Cards of Dentist Plus patients changed here -> PUT /patients/{id} (read first, our fields on top)."""
        spec = self.wm["patient_update"]
        rows = self.db.q("""SELECT e.*, p.local AS p_local, p.remote_id AS p_remote FROM patient_edits e
                            LEFT JOIN patients p ON p.id = e.patient_id
                            WHERE e.transferred=0 AND COALESCE(e.push_status,'') != 'unknown' ORDER BY e.updated_at""")
        rows = self._own(rows, "patient_edits")
        for e in rows:
            target = e["p_remote"] if e["p_local"] else e["patient_id"]
            if not target or not str(target).isdigit():
                self._mark("patient_edits", e["id"], "wait", "Сначала должен уйти новый пациент")
                continue
            try:
                cur = _unwrap(self.c.request(f"patients/{target}"))
            except ApiError as ex:
                if ex.status == 404:
                    self._mark("patient_edits", e["id"], "error", "Пациент не найден в Dentist Plus")
                    continue
                raise
            body = {k: cur[k] for k in _PATIENT_KEEP if isinstance(cur, dict) and cur.get(k) not in (None, "")}
            if isinstance(cur, dict):
                if cur.get("phone_2"):
                    body["phone2"] = cur["phone_2"]
                for k, path in (("doctor_id", "doctor.id"), ("curator_id", "curator_id")):
                    v = get(cur, path)
                    if v not in (None, ""):
                        body[k] = _int(v)
                if isinstance(cur.get("tags"), list):
                    body["tags"] = [_int(t.get("id")) for t in cur["tags"] if isinstance(t, dict) and t.get("id") is not None]
            body.update(self._body(spec, json.loads(e["data"] or "{}")))
            body["branch_id"] = self._branch()
            if not body.get("fname") or body["branch_id"] is None:
                self._mark("patient_edits", e["id"], "error", "Для Dentist Plus нужны имя пациента и филиал")
                continue
            try:
                code, data = self.c.write(spec["method"], spec["path"].replace("{id}", str(target)), body)
            except OfflineError:
                raise
            except ApiError as ex:
                self._mark("patient_edits", e["id"], "unknown", str(ex))
                continue
            if 200 <= code < 300:
                self._mark("patient_edits", e["id"], "sent", "", str(target), done=True)
            else:
                self._mark("patient_edits", e["id"], "error", _err(code, data))
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
            target = v["remote_id"] or v["origin_id"]
            if not target and (v["action"] == "cancel" or conflicts.is_cancelled(v)):
                self._mark("local_visits", v["id"], "sent", "Отменена до отправки — в Dentist Plus не создавалась", done=True)
                continue
            if not pid:
                self._mark("local_visits", v["id"], "error", "Сначала должен уйти новый пациент")
                continue
            src = dict(v)
            src["patient_id"] = pid
            try:
                if target:  # move / edit / status / cancel of an existing Dentist Plus visit
                    if v["action"] == "cancel" or conflicts.is_cancelled(v):
                        spec = self.wm["visit_cancel"]
                        reason = str(v["comment"] or "").strip() or "Отмена записи"
                        code, data = self.c.write(spec["method"], spec["path"].replace("{id}", str(target)), {"reason": reason})
                        if 200 <= code < 300:
                            self._mark("local_visits", v["id"], "sent", "", target, done=True)
                        else:
                            self._mark("local_visits", v["id"], "error", _err(code, data))
                            if code in (401, 403):
                                return False
                        continue
                    if v["action"] in ("move", "edit"):
                        why = self._clash(v, src, self._day_visits(v["start"][:10]), ignore=(target,))
                        if why:
                            self._mark("local_visits", v["id"], "conflict", why)
                            continue
                    changes = self._visit_body(self.wm["visit_update"], src)
                    changes["patient_id"] = _int(pid)
                    if v["action"] == "status":  # only the status: time, doctor and description stay as in Dentist Plus
                        changes = {k: changes[k] for k in ("status_id",) if k in changes}
                        if not changes:
                            self._mark("local_visits", v["id"], "error",
                                       f"Статуса «{v['status']}» нет в Dentist Plus — поменяйте статус там вручную")
                            continue
                    code = self._put_visit(target, changes, "local_visits", v["id"])
                    if code in (401, 403):
                        return False
                    continue
                if not v["doctor_id"]:
                    self._mark("local_visits", v["id"], "error", "Укажите врача — Dentist Plus не создаёт запись без врача")
                    continue
                # new visit: dedupe first
                day = v["start"][:10]
                day_visits = self._day_visits(day)
                same = [x for x in day_visits
                        if x["patient_id"] == str(pid) and (x["start"] or "")[:16] == v["start"][:16] and not conflicts.is_cancelled(x)]
                if same:
                    self._mark("local_visits", v["id"], "sent", "Уже была в Dentist Plus — дубль не создан", same[0]["id"], done=True)
                    continue
                why = self._clash(v, src, day_visits)
                if why:
                    self._mark("local_visits", v["id"], "conflict", why)
                    continue
                spec = self.wm["visit_create"]
                body = self._visit_body(spec, src)
                if not body.get("branch_id"):
                    self._mark("local_visits", v["id"], "error", "Не известен филиал Dentist Plus — дождитесь синхронизации филиалов")
                    continue
                code, data = self.c.write(spec["method"], spec["path"], body)
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

    # ------------------------------------------------------ medical records
    def _record_target(self, r):
        """The Dentist Plus visit a record belongs to: its visit id when that is a Dentist Plus visit, or the id a
        visit made here got in Dentist Plus. None — the record is not linked to a visit there (stays manual)."""
        vid = str(r["visit_id"] or "")
        if not vid:
            return None
        if vid.startswith("L-"):
            lv = self.db.one("SELECT remote_id, origin_id FROM local_visits WHERE id=?", (vid,))
            vid = str((lv or {}).get("remote_id") or (lv or {}).get("origin_id") or "")
        return vid if vid.isdigit() else None

    def record_fields(self, data: dict) -> dict:
        """Sections of a record -> fields of the Dentist Plus visit (see write_map["record_fields"])."""
        import dp_transfer
        fmap = dict(self.wm.get("record_fields") or {})
        rest_field = fmap.pop("*", None)
        out, rest = {}, []
        for key, title in dp_transfer.SECTION_TITLES.items():
            text = dp_transfer.section_text(key, data)
            if not text:
                continue
            if key in fmap:
                out[fmap[key]] = (out[fmap[key]] + "\n" + text) if fmap[key] in out else text
            else:
                rest.append(f"{title}:\n{text}")
        if rest and rest_field:
            out[rest_field] = (out.get(rest_field, "") + "\n\n" if out.get(rest_field) else "") + "\n\n".join(rest)
        return out

    def push_records(self):
        rows = self.db.q("""SELECT * FROM records WHERE COALESCE(transferred,0)=0 AND COALESCE(push_status,'') != 'unknown'
                            ORDER BY created_at""")
        rows = self._own(rows, "records")
        for r in rows:
            target = self._record_target(r)
            if not target:
                if r["push_status"] != "manual":
                    with self.db.tx() as cx:
                        cx.execute("UPDATE records SET push_status='manual', push_error=?, push_at=? WHERE id=?",
                                   ("Запись не привязана к визиту Dentist Plus — перенесите вручную", _now(), r["id"]))
                continue
            try:
                ours = self.record_fields(json.loads(r["data"] or "{}"))
            except ValueError:
                ours = {}
            if not ours:
                continue
            try:
                cur = self._get_visit(target)
            except ApiError as e:
                if e.status == 404:
                    self._mark("records", r["id"], "error", "Визит не найден в Dentist Plus — возможно, его удалили")
                    continue
                if e.status is None:
                    raise
                self._mark("records", r["id"], "error", str(e))
                continue
            try:
                sent_before = json.loads(self.db.meta_get(f"dp_record_sent:{r['id']}") or "{}")
            except ValueError:
                sent_before = {}
            changes = {}
            for field, text in ours.items():
                was = str((cur or {}).get(field) or "").strip()
                old = str(sent_before.get(field) or "").strip()
                text = text.strip()
                if was == text:
                    continue
                if not was or was == old:
                    changes[field] = text
                elif old and old in was:  # the record was changed here after it was sent: our old text is replaced
                    changes[field] = was.replace(old, text)
                elif text not in was:  # the doctor already wrote something there: ours goes after it
                    changes[field] = was + "\n\n" + text
            if not changes:
                self._mark("records", r["id"], "sent", "Уже было в визите Dentist Plus", target, done=True)
                continue
            try:
                code = self._put_visit(target, changes, "records", r["id"])
            except OfflineError:
                raise
            except ApiError as e:
                self._mark("records", r["id"], "unknown" if e.status is None else "error", str(e))
                continue
            if code is not None and 200 <= code < 300:
                self.db.meta_set(f"dp_record_sent:{r['id']}", json.dumps(ours, ensure_ascii=False))
            if code in (401, 403):
                return False
        return True

    def run(self):
        if self.push_patients() and self.push_patient_edits():
            if self.push_visits():
                self.push_records()
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
            for t in ("local_visits", "records", "documents", "invoices", "payments", "notes", "patient_extras", "patient_edits"):
                cx.execute(f"UPDATE {t} SET patient_id=? WHERE patient_id=?", (r["rid"], r["lid"]))
            cx.execute("DELETE FROM patients WHERE id=?", (r["lid"],))
    return len(rows)


def apply_patient_edits(db):
    """A card changed here and not yet in Dentist Plus: after a sync brought the old card back, our change is put
    over it again, so the screens show what the staff wrote."""
    rows = db.q("SELECT patient_id, data FROM patient_edits WHERE COALESCE(transferred,0)=0 ORDER BY updated_at")
    if not rows:
        return 0
    n = 0
    for e in rows:
        p = db.one("SELECT detail, data FROM patients WHERE id=?", (e["patient_id"],))
        if not p:
            continue
        try:
            raw = json.loads(p["detail"] or p["data"] or "{}")
            raw.update(json.loads(e["data"] or "{}"))
        except ValueError:
            continue
        db.upsert_patients([raw], detail=True)
        n += 1
    return n


def simulate_demo(db):
    """Demo mode: pretend the send worked so the workflow can be shown without a real account."""
    with db.tx() as cx:
        for t, extra in (("patients", " AND local=1"), ("local_visits", ""), ("patient_edits", "")):
            cx.execute(f"""UPDATE {t} SET transferred=1, transferred_at=?, push_status='sent',
                           push_error='демо: отправка имитируется', push_at=? WHERE COALESCE(transferred,0)=0{extra}""",
                       (_now(), _now()))
