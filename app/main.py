"""Offline shell over Dentist Plus: schedule, patient cards and front-desk work without internet."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from db import DB  # noqa: E402

logging.basicConfig(filename=str(config.LOG_PATH), level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class Api:
    """Methods exposed to the web UI as window.pywebview.api.*"""

    def __init__(self, db: DB, worker):
        from local import Local
        import catalog
        self._db = db
        self._worker = worker
        from fiscal import Fiscal
        from stock import Stock
        self._local = Local(db)
        self._stock = Stock(db)
        self._fiscal = Fiscal(db)
        from accounting import Accounting
        from marketing import Marketing
        from reports import Reports
        from shifts import Shifts
        self._reports = Reports(db)
        self._shifts = Shifts(db)
        self._acc = Accounting(db)
        self._mk = Marketing(db)
        from waitlist import Waitlist
        self._wait = Waitlist(db)
        from sterilization import Sterilization
        self._steril = Sterilization(db)
        from perio import Perio
        self._perio = Perio(db)
        from files import Files
        self._files = Files(db)
        from forms import Forms
        from tablet import Tablets
        self._forms = Forms(db, self._local)
        self._tablets = Tablets(db)
        from taxcert import TaxCerts
        self._tax = TaxCerts(db)
        catalog.seed(db, demo=bool(config.load_settings().get("demo")))
        if config.load_settings().get("demo"):
            import demo
            demo.ensure_stock(self._stock)

    # ------------------------------------------------- stock and equipment --
    @staticmethod
    def _who():
        from auth import current_user_name
        return current_user_name()

    def stock_summary(self):
        from stock import EQ_STATUS, MOVE_KINDS, UNITS
        return {**self._stock.summary(), "units": UNITS, "move_kinds": MOVE_KINDS, "eq_status": EQ_STATUS}

    def materials(self, q="", only_low=False):
        return self._stock.materials(q, bool(only_low))

    def material(self, mid):
        return self._stock.material(mid)

    def save_material(self, f):
        return self._stock.save_material({**f, "_user": self._who()})

    def delete_material(self, mid):
        return self._stock.delete_material(mid)

    def suppliers(self):
        return self._stock.suppliers()

    def save_supplier(self, f):
        return self._stock.save_supplier(f)

    def delete_supplier(self, sid):
        return self._stock.delete_supplier(sid)

    def stock_receive(self, f):
        return self._stock.receive(f, self._who())

    def stock_write_off(self, f):
        return self._stock.write_off(f, self._who())

    def stock_inventory(self, f):
        return self._stock.inventory(f, self._who())

    def stock_docs(self, kind=None):
        return self._stock.docs(kind)

    def stock_doc(self, did):
        return self._stock.doc(did)

    def stock_moves(self, f=None):
        f = f or {}
        return self._stock.moves(f.get("material_id"), f.get("from"), f.get("to"), f.get("kind"))

    def norms(self, service_id=None):
        return self._stock.norms(service_id)

    def save_norms(self, service_id, items):
        return self._stock.save_norms(service_id, items)

    def equipment_list(self, q="", show_written_off=False):
        return self._stock.equipment_list(q, bool(show_written_off))

    def equipment(self, eid):
        return self._stock.equipment(eid)

    def save_equipment(self, f):
        return self._stock.save_equipment(f, self._who())

    def equipment_event(self, f):
        return self._stock.equipment_event(f, self._who())

    def write_off_equipment(self, f):
        return self._stock.write_off_equipment(f, self._who())

    # ------------------------------------------------------------- reports --
    def report_revenue(self, date_from=None, date_to=None):
        return self._reports.revenue(date_from, date_to)

    def report_visits(self, date_from=None, date_to=None):
        return self._reports.visits(date_from, date_to)

    def report_debts(self):
        return self._reports.debts()

    # ---------------------------------------------------------- accounting --
    def acc_summary(self, date_from=None, date_to=None):
        from accounting import BASES, METHODS
        return {**self._acc.summary(date_from, date_to), "debts": {k: v for k, v in self._reports.debts().items()
                                                                     if k in ("total_debt", "total_advance")},
                "categories": self._acc.categories(), "methods": METHODS, "bases": BASES}

    def expenses(self, date_from=None, date_to=None, category=None):
        return self._acc.expenses(date_from, date_to, category or None)

    def save_expense(self, f):
        return self._acc.save_expense(f, self._who())

    def delete_expense(self, eid):
        return self._acc.delete_expense(eid)

    def salary_schemes(self):
        return self._acc.schemes()

    def save_salary_scheme(self, f):
        return self._acc.save_scheme(f)

    def payroll(self, month=None):
        return self._acc.payroll(month)

    def pay_salary(self, f):
        return self._acc.pay_salary(f, self._who())

    # ----------------------------------------------------------- marketing --
    def mk_summary(self):
        return {**self._mk.summary(), "sources": self._mk.sources()}

    def mk_sources(self):
        return self._mk.sources()

    def save_mk_sources(self, items):
        return self._mk.save_sources(items)

    def mk_sources_report(self, date_from=None, date_to=None):
        return self._mk.sources_report(date_from, date_to)

    def call_list(self, kind, f=None):
        return self._mk.call_list(kind, f)

    def log_call(self, f):
        return self._mk.log_call(f, self._who())

    def set_patient_marketing(self, pid, f):
        return self._mk.set_patient(pid, f or {})

    # -------------------------------------------------------- work shifts --
    def shifts_month(self, month=None):
        return self._shifts.month(month)

    def save_shift(self, f):
        return self._shifts.save(f, self._who())

    def fill_shifts(self, f):
        return self._shifts.fill(f, self._who())

    def clear_shifts(self, person, month):
        return self._shifts.clear(person, month)

    # ------------------------------------------------- offline work (local) --
    def reference(self):
        import catalog
        s = config.load_settings()
        return {"mkb": catalog.MKB, "tooth_statuses": catalog.TOOTH_STATUSES,
                "doctors": self._db.doctors(), "branches": self._db.branches(),
                "clinic": s.get("clinic", {}), "phrases": self._local.templates("phrase")}

    def create_patient(self, f):
        return self._local.create_patient(f)

    def save_visit(self, f):
        return self._local.save_visit(f)

    def set_visit_status(self, vid, status):
        return self._local.set_visit_status(vid, status)

    # ------------------------------------------------ tax deduction certificate --
    def taxcert_data(self, patient_id, year):
        return self._tax.data(patient_id, year)

    def taxcert_issue(self, f):
        return self._tax.issue(f or {}, self._clinic(), self._local, self._who())

    def taxcert_list(self, year):
        return self._tax.list(year)

    # ------------------------------------------------------------ Excel export --
    def export_xlsx(self, title, headers, rows):
        """A table from the screen → .xlsx (returned as a data URL to save on the computer)."""
        import base64
        import xlsx
        data = xlsx.build(str(title or "Таблица")[:31], headers or [], rows or [])
        return {"name": xlsx.file_name(title), "url": "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,"
                + base64.b64encode(data).decode()}

    # ------------------------------------------ signatures, questionnaire, tablet --
    def _clinic(self):
        return config.load_settings().get("clinic") or {}

    def document_signatures(self, doc_id):
        return self._forms.signatures(doc_id)

    def document_sign(self, doc_id, signer, image, role="patient"):
        return self._forms.sign_document(doc_id, signer, image, role, "screen", "", self._who())

    def questionnaire_questions(self):
        return self._forms.questions()

    def questionnaire_save(self, patient_id, answers, signature):
        return self._forms.save_questionnaire(patient_id, answers, signature, self._clinic(), "screen", self._who())

    def questionnaire_latest(self, patient_id):
        return self._forms.latest(patient_id)

    def tablet_code(self, name=""):
        return self._tablets.new_code(name, self._who())

    def tablets_list(self):
        return self._tablets.list()

    def tablet_revoke(self, tid):
        return self._tablets.revoke(tid)

    def tablet_send(self, tid, kind, patient_id, document_id=None):
        """Send «sign this document» or «fill in the questionnaire» to a paired tablet."""
        p = self._db.patient(patient_id)
        if not p:
            raise ValueError("Пациент не найден")
        if kind == "sign":
            d = self._db.one("SELECT id, title, html, patient_id FROM documents WHERE id=?", (document_id,))
            if not d or d["patient_id"] != patient_id:
                raise ValueError("Документ не найден")
            task = {"kind": "sign", "title": d["title"], "patient": p["name"], "html": d["html"], "signer": p["name"],
                    "document_id": d["id"], "patient_id": patient_id}
        elif kind == "anketa":
            task = {"kind": "anketa", "title": "Анкета о состоянии здоровья", "patient": p["name"],
                    "questions": self._forms.questions(), "patient_id": patient_id}
        else:
            raise ValueError("Неизвестное задание для планшета")
        return self._tablets.send(tid, task, self._who())

    def tablet_status(self, tid, task_id):
        return self._tablets.status(tid, task_id)

    def tablet_cancel(self, tid, task_id):
        return self._tablets.cancel(tid, task_id)

    def _tablet_public(self, name, args, key, ip):
        """Requests from the tablet itself (no employee login): pair, task, submit."""
        if name == "pair":
            return self._tablets.pair(args[0] if args else "", ip)
        tb = self._tablets.tablet_by_key(key, ip)
        if name == "task":
            return {"tablet": tb["name"], "task": self._tablets.current(tb["id"])}
        if name == "submit":
            task_id, data = (args + [None, None])[:2]
            t = self._tablets.take(tb["id"], task_id)
            data = data or {}
            place = f"планшет «{tb['name']}»"
            if t["kind"] == "sign":
                r = self._forms.sign_document(t["document_id"], t["signer"], data.get("image"), "patient", place, ip, "")
                result = {"signature_id": r["id"]}
            else:
                r = self._forms.save_questionnaire(t["patient_id"], data.get("answers"), data.get("image"), self._clinic(), place, "")
                result = {"document_id": r["document_id"], "alerts": r["alerts"]}
            self._tablets.done(tb["id"], task_id, result)
            return {"ok": True}
        raise ValueError("Неизвестное действие")

    # ------------------------------------------------ patient files, X-rays --
    def files_list(self, patient_id):
        return self._files.list(patient_id)

    def file_thumbs(self, ids):
        return self._files.thumbs(ids)

    def file_get(self, fid, which="view"):
        return self._files.content(fid, which if which in ("view", "thumb", "orig") else "view")

    def file_add(self, patient_id, name, data_b64, meta=None):
        import files
        return self._files.add(patient_id, name, files.b64_bytes(data_b64), meta or {}, self._who())

    def file_update(self, fid, meta):
        return self._files.update(fid, meta or {})

    def file_delete(self, fid):
        return self._files.delete(fid)

    def files_inbox(self):
        return self._files.inbox()

    def files_inbox_import(self, patient_id, names, meta=None):
        return self._files.inbox_import(patient_id, names, meta or {}, self._who())

    def files_settings(self):
        import files
        return {"inbox": self._files.inbox_dir(), "folder": str(files.root()), "kinds": files.KINDS,
                "max_mb": files.MAX_BYTES // 1024 // 1024}

    def files_settings_save(self, f):
        self._files.save_inbox_dir((f or {}).get("inbox", ""))
        return self.files_settings()

    # ------------------------------------------------ periodontal chart --
    def perio_list(self, patient_id):
        return self._perio.list(patient_id)

    def perio_get(self, cid):
        return self._perio.get(cid)

    def perio_save(self, f):
        return self._perio.save(f or {}, self._who())

    def perio_delete(self, cid):
        return self._perio.delete(cid)

    def perio_parse(self, text):
        import perio
        return perio.parse_voice(text)

    def perio_voice(self, audio_b64, mime="audio/webm"):
        """The doctor dictates the chart: recognised on this computer, turned into chart commands."""
        import perio
        import speech
        audio, suffix = self._audio(audio_b64, mime)
        rec = speech.transcribe(audio, suffix, perio.PERIO_PROMPT)
        return {"text": rec["text"], "commands": perio.parse_voice(rec["text"]), "seconds": rec["seconds"]}

    # ------------------------------------------------ sterilization journal --
    def steril_options(self):
        return self._steril.options()

    def steril_list(self, date_from=None, date_to=None, sterilizer=None):
        return self._steril.list(date_from, date_to, sterilizer or None)

    def steril_save(self, f):
        return self._steril.save(f or {}, self._who())

    def steril_delete(self, cid):
        return self._steril.delete(cid)

    # --------------------------------------------------------- allergies --
    def _allergies(self, pid, anamnesis=""):
        import allergy
        p = self._db.patient(pid) if pid else None
        out = allergy.patient_allergies((p or {}).get("data") or {}, anamnesis or "")
        q = self._forms.allergy_text(pid) if pid else ""  # what the patient wrote in the questionnaire
        if q and q not in out:
            out.append(q)
        return out

    def allergy_check(self, patient_id, text, anamnesis=""):
        """Warnings for a treatment / prescription / service list against the patient's allergies."""
        import allergy
        al = self._allergies(patient_id, anamnesis)
        return {"allergies": al, "warnings": allergy.check(al, text)}

    # ---------------------------------------------- recurring visits, waiting list, reminders --
    def save_visit_series(self, f, every, count):
        """Book a visit several times; returns the dates and the ones that overlap another patient."""
        import conflicts
        r = self._local.save_series(f, every, count)
        clashes = []
        for vid in r["ids"]:
            v = self._db.visit(vid)
            if v and conflicts.find(v, self._db.day(v["start"][:10]), ignore=(v["id"],)):
                clashes.append(v["start"])
        return {**r, "clashes": clashes}

    def visit_series(self, sid):
        return self._local.series(sid)

    def cancel_series(self, sid, from_start):
        return self._local.cancel_series(sid, from_start)

    def waitlist(self, status="wait", doctor_id=None, day=None):
        return self._wait.list(status, doctor_id or None, day or None)

    def waitlist_count(self, doctor_id=None, day=None):
        return self._wait.count(doctor_id or None, day or None)

    def waitlist_save(self, f):
        return self._wait.save(f or {}, self._who())

    def waitlist_done(self, wid, visit_id=None):
        return self._wait.set_status(wid, "booked", visit_id)

    def waitlist_remove(self, wid):
        return self._wait.set_status(wid, "removed")

    REMINDER_DEFAULT = ("Здравствуйте, {имя}! Напоминаем о записи в клинику {клиника} {дата} в {время}, врач {врач}. "
                        "Если планы изменились, пожалуйста, сообщите нам{телефон клиники}.")

    def reminder_template(self):
        s = config.load_settings()
        c = s.get("clinic") or {}
        return {"text": s.get("reminder_template") or self.REMINDER_DEFAULT, "default": self.REMINDER_DEFAULT,
                "clinic": {"name": c.get("name") or "", "phone": c.get("phone") or "", "address": c.get("address") or ""}}

    def reminder_template_save(self, text):
        text = str(text or "").strip()
        if len(text) > 1000:
            raise ValueError("Текст слишком длинный (до 1000 знаков)")
        config.save_settings({"reminder_template": text})
        return self.reminder_template()

    def revert_visit(self, local_id):
        self._local.revert_visit(local_id)
        return True

    def save_record(self, f):
        return self._local.save_record(f)

    def record(self, rid):
        return self._local.record(rid)

    def delete_record(self, rid):
        self._local.delete_record(rid)
        return True

    def templates(self, kind=None):
        return self._local.templates(kind)

    def save_template(self, t):
        return self._local.save_template(t)

    def delete_template(self, tid):
        self._local.delete_template(tid)
        return True

    def reset_template(self, tid):
        import catalog
        b = catalog.builtin_document(tid)
        if b:
            with self._db.tx() as c:
                c.execute("UPDATE templates SET title=?, body=?, category=? WHERE id=?", (b["title"], b["body"], b["category"], tid))
        return True

    def doc_context(self, pid, doctor_id=None, record_id=None, invoice_id=None, visit_id=None):
        """Everything a document template may need."""
        p = self._db.patient(pid) or {}
        d = (p.get("data") or {})
        from normalize import get
        doctor = self._db.one("SELECT id, name, data FROM doctors WHERE id=?", (doctor_id,)) if doctor_id else None
        visit = self._db.visit(visit_id) if visit_id else None
        if not doctor and visit and visit.get("doctor_id"):
            doctor = self._db.one("SELECT id, name, data FROM doctors WHERE id=?", (visit["doctor_id"],))
        rec = self._local.record(record_id) if record_id else None
        if not rec:
            recs = self._local.records(pid)
            rec = recs[0] if recs else None
        if rec and not doctor and rec.get("doctor_id"):
            doctor = self._db.one("SELECT id, name, data FROM doctors WHERE id=?", (rec["doctor_id"],))
        inv = self._local.invoice(invoice_id) if invoice_id else None
        if not inv:
            invs = self._local.invoices(pid)
            inv = invs[0] if invs else None
        ddata = json.loads(doctor["data"]) if doctor and doctor.get("data") else {}
        return {
            "patient": {"fio": p.get("name", ""), "birth": p.get("birth", ""), "phone": p.get("phone", ""),
                        "address": str(get(d, "address", "addr", "registration_address", default="") or ""),
                        "card": str(get(d, "card_number", "card", "medcard_number",
                                        default="" if str(p.get("id", "")).startswith("L-") else p.get("id", "")) or "")},
            "doctor": {"fio": doctor["name"] if doctor else "", "position": str(get(ddata, "position", "speciality", "specialty", "post", default="") or "")},
            "clinic": config.load_settings().get("clinic", {}),
            "visit": {"date": (visit or {}).get("start", "") or (rec or {}).get("date", "")},
            "record": rec["data"] if rec else {}, "record_id": rec["id"] if rec else None,
            "invoice": inv, "records": [{"id": r["id"], "date": r["date"], "doctor_name": r["doctor_name"]} for r in self._local.records(pid)],
            "records_full": self._local.records(pid),
            "invoices": [{"id": i["id"], "created_at": i["created_at"], "total": i["total"]} for i in self._local.invoices(pid)],
        }

    def save_document(self, d):
        return self._local.save_document(d)

    def document(self, did):
        return self._local.document(did)

    def delete_document(self, did):
        self._local.delete_document(did)
        return True

    def services(self, q=""):
        return self._local.services(q)

    def save_service(self, s):
        return self._local.save_service(s)

    def delete_service(self, sid):
        self._local.delete_service(sid)
        return True

    def import_services(self, text):
        return self._local.import_services_csv(text)

    def save_invoice(self, inv):
        iid = self._local.save_invoice(inv)
        self._stock.on_invoice(iid, self._who())  # materials of billed services leave the stock
        return iid

    def invoice(self, iid):
        inv = self._local.invoice(iid)
        if inv:
            states = self._fiscal.payment_states([p["id"] for p in inv["payments"]])
            for p in inv["payments"]:
                p["receipt"] = states.get(p["id"])
        return inv

    def plan_to_invoice(self, plan_id, item_indexes=None, visit_id=None):
        iid = self._local.plan_to_invoice(plan_id, item_indexes, visit_id)
        self._stock.on_invoice(iid, self._who())
        return iid

    def set_plan_status(self, plan_id, status):
        with self._db.tx() as c:
            c.execute("UPDATE invoices SET plan_status=?, transferred=0 WHERE id=? AND kind='plan'", (status, plan_id))
        return True

    def delete_invoice(self, iid):
        for p in self._db.q("SELECT id FROM payments WHERE invoice_id=?", (iid,)):
            if self._fiscal.payment_has_receipt(p["id"]):
                raise ValueError("По оплатам этого счёта пробиты чеки. Сначала оформите чеки возврата (раздел «Касса»).")
        self._local.delete_invoice(iid)
        self._stock.on_invoice(iid)  # invoice gone: its automatic write-off goes back to stock
        return True

    def add_payment(self, p):
        try:
            pid = self._local.add_payment(p)
        except ValueError as e:
            return {"ok": False, "message": str(e)}
        out = {"ok": True, "id": pid}
        import fiscal
        fs = fiscal.settings()
        if fs["enabled"] and p.get("receipt", fs["auto"]):
            try:
                out["receipt"] = self._fiscal.for_payment(pid, p.get("contact", ""), self._who(), bool(p.get("electronically")))
            except ValueError as e:  # payment stays; the receipt can be printed later from the cash screen
                out["receipt"] = {"status": "error", "error": str(e)}
        return out

    def delete_payment(self, pay_id):
        if self._fiscal.payment_has_receipt(pay_id):
            raise ValueError("По этой оплате пробит чек. Сначала оформите чек возврата (раздел «Касса»), затем удалите оплату.")
        self._local.delete_payment(pay_id)
        return True

    # ------------------------------------------------------ fiscal receipts --
    def fiscal_status(self):
        import fiscal
        return {**self._fiscal.status(), "pay_types": fiscal.PAY_TYPE, "method_titles": fiscal.METHOD_TITLES}

    def fiscal_open_shift(self):
        return self._fiscal.open_shift(self._who())

    def fiscal_close_shift(self):
        return self._fiscal.close_shift(self._who())

    def fiscal_x_report(self):
        return self._fiscal.x_report(self._who())

    def fiscal_receipts(self, day=None, status=None):
        return self._fiscal.receipts(day, status)

    def fiscal_receipt(self, rid):
        return self._fiscal.receipt(rid)

    def fiscal_retry(self, rid):
        return self._fiscal.retry(rid, self._who())

    def fiscal_refund(self, rid):
        return self._fiscal.refund(rid, self._who())

    def fiscal_for_payment(self, payment_id, contact=""):
        return self._fiscal.for_payment(payment_id, contact, self._who())

    def fiscal_settings(self):
        import fiscal
        return {"settings": fiscal.settings(), "drivers": fiscal.DRIVERS, "taxation": fiscal.TAXATION, "taxes": fiscal.TAXES}

    def fiscal_save_settings(self, f):
        import fiscal
        cur = fiscal.settings()
        new = {k: f[k] for k in fiscal.DEFAULTS if k in f}
        if new.get("driver", cur["driver"]) not in fiscal.DRIVERS:
            raise ValueError("Неизвестный тип кассы")
        if new.get("taxation", cur["taxation"]) not in fiscal.TAXATION or new.get("tax", cur["tax"]) not in fiscal.TAXES:
            raise ValueError("Неизвестная система налогообложения или ставка НДС")
        for k in ("enabled", "auto"):
            if k in new:
                new[k] = bool(new[k])
        config.save_settings({"fiscal": {**cur, **new}})
        return self.fiscal_settings()

    def fiscal_check(self):
        return self._fiscal.check()

    def cash_day(self, day):
        return self._local.cash_day(day)

    def journal(self, show_done=False):
        items = self._local.journal(show_done)
        for it in items:  # double bookings matter for manual transfer too
            if it["kind"] == "visit" and not it["transferred"] and it.get("push_status") != "conflict":
                lv = self._db.one("SELECT * FROM local_visits WHERE id=?", (it["id"],))
                if lv and lv["action"] not in ("cancel", "status"):
                    it["conflict_text"] = self._visit_conflicts(lv)
        return items

    def write_map_default(self):
        from pusher import DEFAULT_WRITE_MAP
        return DEFAULT_WRITE_MAP

    def retry_push(self, table, rid):
        if table not in ("local_visits", "patients"):
            return False
        with self._db.tx() as c:
            c.execute(f"UPDATE {table} SET push_status=NULL, push_error=NULL WHERE id=? AND COALESCE(transferred,0)=0", (rid,))
        self._worker.trigger()
        return True

    def mark_transferred(self, table, ids, done=True):
        self._local.mark_transferred(table, ids, done)
        return True

    # ------------------------------------------------------------ status --
    def status(self):
        s = config.load_settings()
        st = self._worker.status()
        st["demo"] = bool(s.get("demo"))
        st["configured"] = bool(s.get("login") and s.get("pass_enc"))
        st["counts"] = self._db.counts()
        st["pending"] = self._db.pending_count()
        st["transfer_mode"] = s.get("transfer_mode", "manual")
        st["version"] = config.VERSION
        st["brand"] = config.BRAND
        try:
            from auth import _current, Auth
            u = getattr(_current, "user", None)
            if u is None or {"stock_view", "stock_edit"} & set(Auth.effective_perms(u)):
                st["stock_low"] = sum(1 for m in self._stock.materials() if m["low"] or m["balance"] < 0)
        except Exception:  # noqa: BLE001
            pass
        try:
            from auth import _current, Auth
            u = getattr(_current, "user", None)
            if u is None or "settings" in Auth.effective_perms(u):
                import backup
                st["backup_warn"] = backup.warning()
        except Exception:  # noqa: BLE001
            pass
        return st

    def sync_now(self):
        self._worker.trigger()
        return True

    # ---------------------------------------------------- dictation and AI --
    def speech_status(self):
        import ai
        import speech
        return {**speech.status(), "ai": ai.public_settings()}

    def speech_download(self, size):
        import speech
        return speech.download(size)

    def speech_use(self, size):
        import speech
        return speech.use_size(size)

    @staticmethod
    def _audio(audio_b64, mime):
        import base64
        if not audio_b64:
            raise ValueError("Пустая запись")
        audio = base64.b64decode(audio_b64.split(",", 1)[-1])
        if len(audio) > 30 * 1024 * 1024:
            raise ValueError("Слишком длинная запись. Диктуйте частями до 15 минут.")
        return audio, ".ogg" if "ogg" in mime else ".wav" if "wav" in mime else ".mp4" if "mp4" in mime else ".webm"

    def dictate(self, audio_b64, mime="audio/webm", patient_id=None, mode="dictation", doctor_id=None):
        """A recording from the doctor's microphone → text → record fields. Nothing is saved here:
        the doctor checks the result in the form and saves it.
        mode="visit": a recording of the whole visit; replies are signed «Врач», «Ассистент», «Пациент»
        by the employees' voice prints."""
        import speech
        audio, suffix = self._audio(audio_b64, mime)
        phrases = " ".join(t["title"] for t in self._local.templates("phrase")[:30])
        if mode != "visit":
            rec = speech.transcribe(audio, suffix, phrases)
            out = self.parse_dictation(rec["text"], patient_id)
            out.update(duration=rec["duration"], seconds=rec["seconds"], model=rec["model"])
            return out
        import voices
        rec = speech.transcribe(audio, suffix, phrases, words=True)
        note = ""
        try:
            from auth import _current
            me = getattr(_current, "user", None)
            cands = voices.candidates(self._db, doctor_id or None, me["id"] if me else None)
        except Exception:  # noqa: BLE001  (no staff table in a bare test database)
            cands = []
        if not cands:
            note = "Голоса сотрудников не записаны — реплики не подписаны. Настройки → «Голос и ИИ» → «Голоса сотрудников»."
        elif not voices.is_ready():
            cands, note = [], "Модель различения голосов не скачана — реплики не подписаны."
        lines = voices.label_words(rec["wav"], rec["words"], cands) if rec["words"] else []
        text = voices.as_text(lines) or rec["text"]
        out = self.parse_dictation(text, patient_id)
        out.update(duration=rec["duration"], seconds=rec["seconds"], model=rec["model"], mode="visit", voice_note=note,
                   speakers=sorted({lbl for lbl, _ in lines if lbl}))
        return out

    # employees' voice prints (who is speaking in a visit recording)
    def voice_status(self):
        import voices
        vp = voices.prints(self._db)
        try:
            users = self._db.q("SELECT id, name, position, role, doctor_id FROM users WHERE status='active' ORDER BY name")
        except Exception:  # noqa: BLE001
            users = []
        staff = [{"id": u["id"], "name": u["name"], "position": u["position"] or "", "label": voices.role_label(dict(u)),
                  "role": u["role"], "voice": {k: vp[u["id"]][k] for k in ("seconds", "quality", "updated_at")} if u["id"] in vp else None}
                 for u in users if u["role"] not in ("storekeeper",)]
        return {"model": voices.status(), "staff": staff}

    def voice_download(self):
        import voices
        return voices.download()

    def voice_enroll(self, user_id, audio_b64, mime="audio/webm"):
        import voices
        audio, suffix = self._audio(audio_b64, mime)
        p = voices.make_print(voices.decode(audio, suffix))
        voices.save_print(self._db, int(user_id), p)
        return {"seconds": p["seconds"], "quality": p["quality"]}

    def voice_delete(self, user_id):
        import voices
        voices.delete_print(self._db, int(user_id))
        return True

    def parse_dictation(self, text, patient_id=None):
        """Text (recognized or typed) → record fields: AI if it is on and reachable, otherwise offline rules.
        Text with replies signed «Врач: …», «Пациент: …» is treated as a visit conversation."""
        import ai
        import dictation
        import re
        # an employee signed by position (older recordings, or typed by hand) is the treating doctor
        text = re.sub(r"^(Директор|Администратор|Сотрудник)\s*:", "Врач:", text or "", flags=re.M)
        talk = bool(re.search(r"^(Врач|Ассистент|Пациент)\s*:", text, re.M))
        plain = re.sub(r"^(Врач|Ассистент|Пациент|Директор|Администратор|Сотрудник)\s*:\s*", "", text or "", flags=re.M)
        base = dictation.parse(plain)
        if talk:
            base["text"] = text
        out = {**base, "engine": "rules", "ai_error": None, "auto_insert": bool(ai.settings().get("auto_insert"))}
        if ai.settings()["enabled"] and (text or "").strip():
            p = self._db.patient(patient_id) if patient_id else None
            try:
                smart = ai.structure(base["text"], names=[p["name"]] if p else [], conversation=talk)
                out.update(fields={**base["fields"], **smart["fields"]}, diagnoses=smart["diagnoses"] or base["diagnoses"],
                           teeth={**base["teeth"], **smart["teeth"]}, engine="ai")
            except ValueError as e:
                out["ai_error"] = str(e)
        return out

    # AI on this computer: Ollama and a Qwen / Gemma model downloaded from the settings
    def local_ai_status(self):
        import llm_local
        return llm_local.status()

    def local_ai_install(self):
        import llm_local
        return llm_local.install()

    def local_ai_pull(self, model):
        import llm_local
        return llm_local.pull(model)

    def local_ai_use(self, model):
        import llm_local
        return llm_local.use(model)

    def local_ai_delete(self, model):
        import llm_local
        return llm_local.delete(model)

    def ai_settings_save(self, f):
        import ai
        return ai.save(f)

    def ai_test(self):
        import ai
        return ai.test()

    def offline_snapshot(self, days_back=1, days_forward=14):
        """Read-only copy for a client laptop: the schedule and the cards of patients in it, cut to what
        this employee may see. The laptop keeps it encrypted for the hours the server is unreachable."""
        from auth import Auth, PERM_KEYS, _current
        u = getattr(_current, "user", None)
        perms = set(Auth.effective_perms(u)) if u else set(PERM_KEYS)
        days_back, days_forward = max(0, min(int(days_back), 7)), max(1, min(int(days_forward), 31))
        today = date.today()
        out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": u["name"] if u else "",
               "brand": config.BRAND, "clinic": config.load_settings().get("clinic", {}),
               "from": (today - timedelta(days=days_back)).isoformat(), "to": (today + timedelta(days=days_forward)).isoformat(),
               "doctors": self._db.doctors(), "branches": self._db.branches(), "visits": [], "patients": {},
               "can": sorted(perms & {"schedule_view", "patients_view", "medcard_view"})}
        if "schedule_view" in perms:
            for i in range(-days_back, days_forward + 1):
                out["visits"].extend(self._db.day((today + timedelta(days=i)).isoformat()))
        if "patients_view" in perms:
            keep = ("id", "name", "phone", "birth", "data", "notes", "local")
            for pid in dict.fromkeys(v["patient_id"] for v in out["visits"] if v.get("patient_id")):
                p = self._db.patient(pid)
                if not p:
                    continue
                card = {k: p.get(k) for k in keep}
                card["visits"] = [{k: v.get(k) for k in ("start", "end", "status", "title", "doctor_name", "chair", "branch_name")}
                                  for v in p["visits"][:40]]
                if "medcard_view" in perms:
                    card["extras"] = p["extras"]
                    card["records"] = [{"date": r["date"], "doctor_name": r.get("doctor_name"), "data": r.get("data")}
                                       for r in self._local.records(pid)[:20]]
                    card["teeth"] = self._local.teeth_state(pid)
                out["patients"][pid] = card
        return out

    def save_clinic(self, clinic: dict):
        """Clinic requisites for documents (name, address, licence, director...)."""
        if not isinstance(clinic, dict):
            raise ValueError("Неверные реквизиты")
        config.save_settings({"clinic": {str(k): str(v)[:500] for k, v in clinic.items()}})
        return True

    def ui_settings(self):
        """Display settings every signed-in user needs (no credentials)."""
        s = config.load_settings()
        import fiscal
        fs = fiscal.settings()
        return {**{k: s.get(k) for k in ("day_start", "day_end", "slot_min", "show_empty_doctors", "demo", "transfer_mode")},
                "fiscal_enabled": fs["enabled"], "fiscal_auto": fs["auto"], "fiscal_test": fs["driver"] == "emulator"}

    # ------------------------------------------------------------ backups --
    def backup_status(self):
        import backup
        return backup.status()

    def backup_now(self):
        import backup
        return backup.make("manual")

    def backup_list(self):
        import backup
        return backup.listing()

    def backup_settings_save(self, f):
        import backup
        return backup.save_settings(f or {})

    def security_status(self, force=False):
        import security
        return security.disk_status(bool(force))

    def backup_restore(self, where, name):
        import backup
        from auth import _current
        u = getattr(_current, "user", None)
        if u is not None and u.get("role") != "director":
            raise ValueError("Восстанавливать базу из копии может только директор")
        return backup.restore(where, name, self._db.conn, self._db._lock, db_path=self._db.path)

    def network_info(self):
        from server import local_addresses
        s = config.load_settings()
        port = int(s.get("port") or 8765)
        return {"mode": s.get("net_mode") or "server", "port": port, "addresses": local_addresses(),
                "urls": [f"http://{ip}:{port}/" for ip in local_addresses()]}

    # ---------------------------------------------------------- schedule --
    def day(self, day: str, branch_id: str | None = None):
        import conflicts
        return {"visits": conflicts.mark_day(self._db.day(day, branch_id or None)),
                "doctors": self._db.doctors(), "branches": self._db.branches(), "shifts": self._shifts.day(day)}

    def month_counts(self, first_day: str):
        d = date.fromisoformat(first_day)
        return self._db.day_counts((d - timedelta(days=7)).isoformat(), (d + timedelta(days=45)).isoformat())

    def visit(self, vid):
        v = self._db.visit(vid)
        if v:
            v["conflict_text"] = self._visit_conflicts(v)
            try:
                v["allergies"] = self._allergies(v.get("patient_id"))
            except Exception:  # noqa: BLE001
                v["allergies"] = []
        return v

    def _visit_conflicts(self, v):
        """«у врача в это время уже …» for a booking that overlaps another patient of the same doctor."""
        import conflicts
        if not v.get("start"):
            return ""
        found = conflicts.find(v, self._db.day(v["start"][:10]), ignore=(v.get("id"), v.get("origin_id")))
        return conflicts.describe(found) if found else ""

    def force_push(self, rid):
        """«Send anyway»: the user checked the double booking and wants this appointment sent."""
        with self._db.tx() as c:
            c.execute("UPDATE local_visits SET push_force=1, push_status=NULL, push_error=NULL WHERE id=? AND transferred=0", (rid,))
        self._worker.trigger()
        return True

    # ---------------------------------------------------------- patients --
    def search(self, q: str):
        return self._db.search_patients(q)

    def patient(self, pid):
        p = self._db.patient(pid)
        if p:
            p["records"] = self._local.records(pid)
            p["documents"] = self._local.documents(pid)
            p["invoices"] = self._local.invoices(pid)
            p["balance_local"] = self._local.balance(pid)
            p["teeth_local"] = self._local.teeth_state(pid)
            p["marketing"] = self._mk.patient_info(pid)
            p["files_count"] = self._files.count(pid)
            p["questionnaire"] = self._forms.latest(pid)
            signed = self._forms.signed_ids([d["id"] for d in p["documents"]])
            for d in p["documents"]:
                d["signed"] = d["id"] in signed
            p["perio_count"] = len(self._perio.list(pid))
        return p

    def add_note(self, pid, text):
        if text and text.strip():
            self._db.add_note(pid, text.strip())
        return self._db.patient(pid)["notes"]

    def delete_note(self, pid, nid):
        self._db.delete_note(nid)
        return self._db.patient(pid)["notes"]

    # ---------------------------------------------------------- settings --
    def get_settings(self):
        s = config.load_settings()
        s["has_password"] = bool(s.pop("pass_enc", ""))
        s["data_dir"] = str(config.data_dir())
        s["autostart"] = self._autostart_get()
        s["history"] = self._db.sync_history()
        return s

    def save_settings(self, new: dict):
        allowed = {"base_url", "login", "demo", "interval_min", "days_back", "days_forward", "chunk_days",
                   "per_page", "visit_from_param", "visit_to_param", "sync_all_patients", "patient_extras",
                   "day_start", "day_end", "clinic", "show_empty_doctors", "slot_min", "transfer_mode", "write_map"}
        upd = {k: v for k, v in new.items() if k in allowed}
        if "write_map" in upd and isinstance(upd["write_map"], str):
            upd["write_map"] = json.loads(upd["write_map"] or "{}")
        if "patient_extras" in upd and isinstance(upd["patient_extras"], str):
            upd["patient_extras"] = json.loads(upd["patient_extras"] or "[]")
        for k in ("interval_min", "days_back", "days_forward", "chunk_days", "per_page", "day_start", "day_end", "slot_min"):
            if k in upd:
                upd[k] = int(upd[k])
        if new.get("password"):
            upd["pass_enc"] = config.protect(new["password"])
        old = config.load_settings()
        if old.get("demo") != upd.get("demo", old.get("demo")):
            if not old.get("demo") and self._db.pending_count():
                raise ValueError("Есть данные, не перенесённые в Dentist Plus. Сначала перенесите их (раздел «Перенос»).")
            self._db.wipe()  # never mix demo and real data
            import catalog
            catalog.seed(self._db, demo=bool(upd.get("demo")))
        config.save_settings(upd)
        if "autostart" in new:
            self._autostart_set(bool(new["autostart"]))
        self._worker.trigger()
        return self.get_settings()

    def test_connection(self, login: str = "", password: str = "", base_url: str = ""):
        from api_client import ApiError, DentistPlusClient
        s = config.load_settings()
        c = DentistPlusClient(base_url or s["base_url"], login or s["login"], password or config.unprotect(s.get("pass_enc", "")))
        if not c.login or not c.password:
            return {"ok": False, "message": "Укажите логин и пароль API"}
        try:
            c.auth()
            return {"ok": True, "message": "Подключение успешно, токен получен"}
        except ApiError as e:
            return {"ok": False, "message": str(e)}

    def diagnostics(self):
        from sync import diagnostics
        try:
            return json.dumps(diagnostics(config.load_settings()), ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            return f"Ошибка: {e}"

    def open_data_dir(self):
        os.startfile(str(config.data_dir()))  # noqa: S606

    # ------------------------------------------------ report for developer --
    @staticmethod
    def _desktop_dir():
        try:
            import ctypes  # noqa: PLC0415
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:  # CSIDL_DESKTOPDIRECTORY
                return buf.value
        except Exception:  # noqa: BLE001
            pass
        return None

    def dev_report(self):
        """Anonymized report (no patient data, passwords or keys) saved to the Desktop and to
        <data>/reports. Returns the path and the text, so it can also be copied into a messenger."""
        import devreport  # noqa: PLC0415
        try:
            rep = devreport.build(self._db, self._worker.status())
        except Exception as e:  # noqa: BLE001
            log.exception("dev report failed")
            return {"ok": False, "message": f"Не удалось собрать отчёт: {e.__class__.__name__}"}
        text = json.dumps(rep, ensure_ascii=False, indent=2)
        name = devreport.filename()
        rdir = config.data_dir() / "reports"
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / name).write_text(text, encoding="utf-8")
        path = rdir / name
        desk = self._desktop_dir()
        if desk:
            try:
                p = os.path.join(desk, name)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(text)
                path = p
            except OSError:
                pass
        self._last_report = str(path)
        return {"ok": True, "path": str(path), "name": name, "text": text, "on_desktop": bool(desk) and str(path).startswith(desk)}

    def show_dev_report(self):
        p = getattr(self, "_last_report", None)
        if not p or not os.path.exists(p):
            return False
        import subprocess  # noqa: PLC0415
        subprocess.Popen(["explorer", "/select,", p])  # noqa: S603, S607
        return True

    # --------------------------------------------------------- autostart --
    @staticmethod
    def _exe_cmd():
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --minimized'
        return f'"{sys.executable}" "{os.path.abspath(__file__)}" --minimized'

    def _autostart_get(self):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, config.APP_NAME)
                return True
        except OSError:
            return False

    def _autostart_set(self, on: bool):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, config.APP_NAME, 0, winreg.REG_SZ, self._exe_cmd())
            else:
                try:
                    winreg.DeleteValue(k, config.APP_NAME)
                except OSError:
                    pass


def single_instance():
    """Return False if the app is already running (named mutex)."""
    if os.name != "nt":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{config.APP_NAME}OfflineMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def _install_dir():
    base = os.environ.get("APP_INSTALL_DIR") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", config.APP_NAME)
    return os.path.abspath(base)


def _make_shortcuts(target):
    """Desktop + Start menu shortcuts via PowerShell (no extra dependencies)."""
    import base64
    import subprocess
    desktop = os.environ.get("APP_DESKTOP")
    desk_expr = f"'{desktop}'" if desktop else "[Environment]::GetFolderPath('Desktop')"
    progs_expr = f"'{desktop}'" if desktop else "[Environment]::GetFolderPath('Programs')"
    ps = f"""
$t = '{target}'
$sh = New-Object -ComObject WScript.Shell
foreach ($d in @({desk_expr}, {progs_expr})) {{
  $l = $sh.CreateShortcut((Join-Path $d '{config.BRAND["name"]}.lnk'))
  $l.TargetPath = $t; $l.WorkingDirectory = (Split-Path $t); $l.IconLocation = "$t,0"
  $l.Description = '{config.BRAND["name"]} — расписание и медкарты'; $l.Save()
}}"""
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                   creationflags=0x08000000, timeout=60, check=False)  # CREATE_NO_WINDOW


def self_install():
    """Running a downloaded exe (e.g. from Telegram) installs it for this user and starts the installed
    copy. Running a newer exe later updates the installed one. Returns True if this process should exit."""
    if not getattr(sys, "frozen", False) or os.name != "nt" or "--no-install" in sys.argv:
        return False
    import shutil
    import subprocess
    exe = os.path.abspath(sys.executable)
    target_dir = _install_dir()
    target = os.path.join(target_dir, config.BRAND["exe"] + ".exe")
    if os.path.normcase(exe) == os.path.normcase(target):
        return False
    def _copy():
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(exe, target + ".new")
        os.replace(target + ".new", target)

    try:
        _copy()
    except PermissionError:
        # the old version is open: ask it to close (it saves everything on close), then update
        updated = False
        try:
            import ctypes
            import time
            hwnd = ctypes.windll.user32.FindWindowW(None, config.APP_TITLE)
            if hwnd:
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                for _ in range(40):
                    time.sleep(0.25)
                    try:
                        _copy()
                        updated = True
                        break
                    except PermissionError:
                        continue
        except Exception as e:  # noqa: BLE001
            log.warning("auto-close for update failed: %s", e)
        if not updated:
            try:
                os.remove(target + ".new")
            except OSError:
                pass
            ctypes_msg(f"{config.BRAND['name']} уже открыта.\n\nЗакройте программу (значок в панели задач, правый щелчок → Закрыть окно) "
                       "и запустите этот файл ещё раз — программа обновится.")
            return True
    except OSError as e:
        log.warning("self-install failed, running in place: %s", e)
        return False
    try:
        _make_shortcuts(target)
    except Exception as e:  # noqa: BLE001
        log.warning("shortcuts failed: %s", e)
    log.info("installed to %s", target)
    subprocess.Popen([target, *[a for a in sys.argv[1:] if a != "--no-install"]], close_fds=True,
                     creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return True


class Host:
    """Runs the clinic server on this computer when it is the server (database + sync + network)."""

    def __init__(self):
        self.server = None
        self.worker = None
        self.backups = None

    def port(self):
        return int(config.load_settings().get("port") or 8765)

    def start_server(self):
        if self.server:
            return
        from server import ClinicServer
        from sync import SyncWorker
        db = DB()
        self.worker = SyncWorker(db)
        self.worker.start()
        api = Api(db, self.worker)
        self.server = ClinicServer(api, db, port=self.port()).start()
        from backup import BackupWorker
        self.backups = BackupWorker(db.path)
        self.backups.start()

    def stop(self):
        if self.worker:
            self.worker.stop_flag = True
        if self.server:
            self.server.stop()
        if self.backups:
            self.backups.stop()  # one more copy on exit


class Setup:
    """Bridge for the first-start screen (ui/setup.html): server or client, find the server."""

    def __init__(self, host: Host):
        self._host = host
        self._window = None
        self._error = ""

    def info(self):
        s = config.load_settings()
        return {"mode": s.get("net_mode") or "", "server_url": s.get("server_url") or "", "error": self._error,
                "brand": config.BRAND, "version": config.VERSION, "port": self._host.port()}

    def discover(self):
        from server import discover
        return discover(port=self._host.port())

    def check(self, url):
        from server import ping
        url = _norm_url(url, self._host.port())
        info = ping(url)
        return {"ok": bool(info), "url": url, "info": info}

    def use_server(self):
        try:
            self._host.start_server()
        except OSError as e:
            self._error = f"Не удалось открыть порт {self._host.port()}: {e}. Возможно, программа уже запущена."
            return {"ok": False, "message": self._error}
        config.save_settings({"net_mode": "server"})
        url = f"http://127.0.0.1:{self._host.port()}/"
        self._go(url)
        return {"ok": True, "url": url}

    def use_client(self, url):
        r = self.check(url)
        if not r["ok"]:
            return {"ok": False, "message": "По этому адресу сервер клиники не отвечает"}
        config.save_settings({"net_mode": "client", "server_url": r["url"], "server_id": r["info"]["server_id"]})
        self._go(r["url"])
        return {"ok": True, "url": r["url"]}

    def open_setup(self):
        if self._window:
            self._window.load_url(_ui_page("setup.html"))
        return True

    def reconnect(self):
        """Client lost the server: try the saved address, then look for the same server in the network."""
        url = _client_url(self._host.port())
        if url:
            self._go(url)
            return {"ok": True, "url": url}
        return {"ok": False}

    # ---- read-only copy on this computer for when the server is unreachable ----
    def is_client(self):
        return config.load_settings().get("net_mode") == "client"

    def offline_remember(self, login, password):
        import offline_store
        return offline_store.remember_login(login, password) if self.is_client() else False

    def offline_save(self, login, snapshot_json):
        import offline_store
        if not self.is_client():
            return {"ok": False}
        return offline_store.save(login, snapshot_json)

    def offline_available(self):
        import offline_store
        return offline_store.available()

    def offline_open(self, login, password):
        import offline_store
        try:
            return {"ok": True, "snapshot": offline_store.open_copy(login, password)}
        except ValueError as e:
            return {"ok": False, "message": str(e)}

    def offline_forget(self, login):
        import offline_store
        return offline_store.forget(login)

    def set_theme(self, pref):
        """Remember the theme chosen in the app for the pages opened from files and the window background."""
        if pref in THEMES:
            config.save_settings({"ui_theme": pref})
        return True

    def open_offline(self):
        if self._window:
            page = _ui_page("offline.html")
            threading.Timer(0.05, lambda: self._window.load_url(page)).start()
        return True

    def choose_folder(self):
        """Folder picker for the second backup folder (a flash drive or another disk)."""
        import webview
        if not self._window:
            return ""
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or getattr(webview, "FOLDER_DIALOG", 20)
        res = self._window.create_file_dialog(kind)
        return str(res[0]) if res else ""

    def save_file(self, name, data_url):
        """«Сохранить как…» for an export (Excel). Returns the chosen path or '' when cancelled."""
        import base64
        import webview
        name = str(name or "export.xlsx")
        ext = os.path.splitext(name)[1].lower()
        if ext not in (".xlsx", ".csv", ".xml", ".pdf") or not self._window:
            return ""
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or getattr(webview, "SAVE_DIALOG", 30)
        types = {".xlsx": ("Книга Excel (*.xlsx)",), ".csv": ("CSV (*.csv)",), ".xml": ("XML (*.xml)",), ".pdf": ("PDF (*.pdf)",)}[ext]
        res = self._window.create_file_dialog(kind, save_filename=os.path.basename(name), file_types=types)
        path = res[0] if isinstance(res, (list, tuple)) and res else res
        if not path:
            return ""
        path = str(path)
        if not path.lower().endswith(ext):
            path += ext
        payload = str(data_url).split(",", 1)[1] if "," in str(data_url) else str(data_url)
        with open(path, "wb") as f:
            f.write(base64.b64decode(payload))
        return path

    def open_url(self, url):
        """Open a WhatsApp / Telegram chat or a phone link in the system (only these kinds of links)."""
        import webbrowser
        url = str(url or "")
        if not url.startswith(("https://wa.me/", "https://t.me/", "tel:")):
            return False
        webbrowser.open(url)
        return True

    def restart_app(self):
        """Start a fresh copy of the program (it waits for this one to close) and close this one."""
        import subprocess
        args, skip = [], False
        for a in sys.argv[1:]:
            if skip:
                skip = False
            elif a == "--wait-pid":
                skip = True
            elif a != "--minimized":
                args.append(a)
        cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__)]
        subprocess.Popen([*cmd, *args, "--wait-pid", str(os.getpid())], close_fds=True,
                         creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        if self._window:
            threading.Timer(0.3, self._window.destroy).start()
        return True

    def server_alive(self):
        from server import ping
        url = config.load_settings().get("server_url")
        return bool(url and ping(url, timeout=1.5))

    def allow_firewall(self):
        """Ask Windows (UAC prompt) to let other clinic computers reach this one."""
        import subprocess
        exe = sys.executable
        name = config.BRAND["name"]
        port = self._host.port()
        cmds = [f'netsh advfirewall firewall delete rule name="{name}"',
                f'netsh advfirewall firewall add rule name="{name}" dir=in action=allow protocol=TCP localport={port} '
                f'program="{exe}" profile=private,domain enable=yes',
                f'netsh advfirewall firewall add rule name="{name}" dir=in action=allow protocol=UDP localport={port + 1} '
                f'program="{exe}" profile=private,domain enable=yes']
        script = " & ".join(cmds)
        ps = f"Start-Process cmd -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList '/c {script.replace(chr(39), chr(39) * 2)}'"
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           creationflags=0x08000000, timeout=120, check=False, capture_output=True)
        return {"ok": r.returncode == 0}

    def _go(self, url):
        self._error = ""
        if self._window:
            threading.Timer(0.05, lambda: self._window.load_url(url)).start()


def _norm_url(url, port):
    url = str(url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    rest = url.split("://", 1)[1]
    if ":" not in rest.split("/", 1)[0]:
        host = rest.split("/", 1)[0]
        url = url.replace(host, f"{host}:{port}", 1)
    return url.rstrip("/") + "/"


THEMES = ("light", "dark", "system")


def _theme_pref():
    p = config.load_settings().get("ui_theme")
    return p if p in THEMES else "system"


def _theme_is_dark():
    p = _theme_pref()
    if p != "system":
        return p == "dark"
    try:  # Windows «app mode»: AppsUseLightTheme = 0 means dark
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def _ui_page(name):
    """A page opened from the program folder (other origin than the app): pass the theme along."""
    return str(config.resource_dir() / "ui" / name) + "?theme=" + _theme_pref()


def _client_url(port):
    """Saved server address if it answers; otherwise the same server found again in the network
    (its address may change after a router restart)."""
    from server import discover, ping
    s = config.load_settings()
    url = s.get("server_url")
    if url and ping(url):
        return url
    for info in discover(port=port):
        if info.get("server_id") == s.get("server_id"):
            config.save_settings({"server_url": info["url"]})
            return info["url"]
    return None


def _trusted_page(uri: str) -> bool:
    """Pages of the program itself: local server, the clinic server, bundled files."""
    uri = (uri or "").lower()
    srv = (config.load_settings().get("server_url") or "").lower()
    origin = "/".join(srv.split("/")[:3]) if srv else ""
    return uri.startswith(("http://127.0.0.1", "http://localhost", "file:///")) or bool(origin and uri.startswith(origin))


def _allow_microphone():
    """WebView2 asks «Site http://127.0.0.1:8765 wants to use the microphone» in its own grey popup.
    The program's own pages get the microphone silently; anything else keeps the default prompt."""
    try:
        from webview.platforms import edgechromium as ec  # noqa: PLC0415
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        log.info("microphone auto-permission unavailable: %s", e)
        return
    original = ec.EdgeChrome.on_webview_ready
    keep = []

    def on_ready(self, sender, args):
        original(self, sender, args)
        if not args.IsSuccess:
            return

        def on_permission(_s, e):
            try:
                if e.PermissionKind == CoreWebView2PermissionKind.Microphone and _trusted_page(str(e.Uri)):
                    e.State = CoreWebView2PermissionState.Allow
            except Exception as ex:  # noqa: BLE001
                log.warning("permission handler: %s", ex)
        keep.append(on_permission)
        sender.CoreWebView2.PermissionRequested += on_permission
    ec.EdgeChrome.on_webview_ready = on_ready


def _focus_running() -> bool:
    """Second start: bring the open window to the front instead of a «already open» message box."""
    try:
        import ctypes  # noqa: PLC0415
        u = ctypes.windll.user32
        hwnd = u.FindWindowW(None, config.APP_TITLE)
        if not hwnd:
            return False
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
        u.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False


def main():
    import webview

    if self_install():
        return
    if "--wait-pid" in sys.argv:  # restarted after a restore from a backup: let the old window close first
        try:
            import backup
            backup.wait_for_exit(int(sys.argv[sys.argv.index("--wait-pid") + 1]))
        except (IndexError, ValueError):
            pass
    if not single_instance():
        if not _focus_running():
            ctypes_msg(f"{config.BRAND['name']} уже открыта — посмотрите в панели задач.")
        return
    _allow_microphone()
    host = Host()
    setup = Setup(host)
    s = config.load_settings()
    setup_page = _ui_page("setup.html")
    url = setup_page
    if s.get("net_mode") == "server":
        try:
            host.start_server()
            url = f"http://127.0.0.1:{host.port()}/"
        except OSError as e:
            setup._error = f"Не удалось запустить сервер на порту {host.port()}: {e}"
    elif s.get("net_mode") == "client":
        url = _client_url(host.port()) or setup_page
        if url == setup_page:
            setup._error = f"Сервер клиники не отвечает ({s.get('server_url')}). Проверьте, что компьютер-сервер включён и программа на нём запущена."
            import offline_store
            if offline_store.available():  # server down at start: open the saved copy right away
                url = _ui_page("offline.html")
    # the microphone (dictation) is only allowed on «secure» pages; the clinic server is plain http on
    # the local network, so tell WebView2 to trust exactly that address
    srv = config.load_settings().get("server_url") or ""
    if srv.startswith("http://") and "127.0.0.1" not in srv:
        origin = "/".join(srv.split("/")[:3])
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--unsafely-treat-insecure-origin-as-secure={origin}"
    window = webview.create_window(config.APP_TITLE, url=url, js_api=setup, width=1360, height=860,
                                   min_size=(1000, 640), background_color="#141312" if _theme_is_dark() else "#F6F6F6",
                                   minimized="--minimized" in sys.argv)
    setup._window = window
    webview.start(debug="--debug" in sys.argv, private_mode=False,
                  storage_path=str(config.data_dir() / "webview"))
    host.stop()


def ctypes_msg(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, config.APP_TITLE, 0x40)
    except Exception:  # noqa: BLE001
        print(text)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log.exception("fatal")
        raise
