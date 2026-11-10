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
        self._cloud = None          # cloud.Cloud, set by start_platform (or made on first use)
        self._cloud_worker = None
        self._stock = Stock(db)
        self._fiscal = Fiscal(db)
        from accounting import Accounting
        from marketing import Marketing
        from reports import Reports
        from shifts import Shifts
        self._reports = Reports(db)
        from director import Director
        self._dir = Director(db, self._reports)
        self._shifts = Shifts(db)
        self._acc = Accounting(db)
        self._mk = Marketing(db)
        from crm import CRM
        self._crm = CRM(db, self._local, self._mk)
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
        from plans import Plans
        self._plans = Plans(db, self._local, self._forms)
        from taxcert import TaxCerts
        self._tax = TaxCerts(db)
        from lab import Lab
        from loyalty import Loyalty
        self._lab = Lab(db)
        self._loyal = Loyalty(db)
        from finance import Finance
        self._fin = Finance(db, self._local, self._loyal)
        from consents import Consents
        self._consents = Consents(db)
        from daily import Daily
        self._daily = Daily(db, self._acc, self._fin)
        catalog.seed(db, demo=bool(config.load_settings().get("demo")))
        if config.load_settings().get("demo"):
            import demo
            demo.ensure_stock(self._stock)
            demo.ensure_stock_lots(self._stock)

    # ------------------------------------------------- stock and equipment --
    @staticmethod
    def _who():
        from auth import current_user_name
        return current_user_name()

    def stock_summary(self):
        from stock import EQ_STATUS, MOVE_KINDS, UNITS
        return {**self._stock.summary(), "units": UNITS, "move_kinds": MOVE_KINDS, "eq_status": EQ_STATUS}

    def _stock_view(self, rows):
        """2.14.1: the balance «по документам» is the accountant's view — only with the «Бухгалтерия» right."""
        if "accounting" in self._my_perms()[0]:
            return rows
        for r in rows if isinstance(rows, list) else [rows]:
            if r:
                r.pop("balance_doc", None)
                r.pop("value_doc", None)
        return rows

    def materials(self, q="", only_low=False, only_expiring=False):
        return self._stock_view(self._stock.materials(q, bool(only_low), only_expiring=bool(only_expiring)))

    def stock_lots(self, mid):
        return self._stock.lots(mid)

    def stock_expired(self):
        return self._stock.expired_lines()

    def purchase_list(self, cover_days=30):
        return self._stock.purchase_list(cover_days)

    def stock_scan(self, code):
        return self._stock.scan(code)

    def material(self, mid):
        return self._stock_view(self._stock.material(mid))

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
        """A receipt; with `pay` (a way from «Расходы за день») the purchase is also written down as today's expense,
        «без документа» when the receipt has no invoice (2.14.1)."""
        import daily
        f = f if isinstance(f, dict) else {}
        pay = f.get("pay") if f.get("pay") in daily.METHODS else None
        perms, u = self._my_perms()
        if pay and not perms & {"expenses_day", "accounting"}:
            raise ValueError("Записывать расходы за день может только сотрудник с правом «Расходы за день»")
        did = self._stock.receive(f, self._who())
        if pay:
            d = self._stock.doc(did)
            if d["total"] > 0:
                sup = d.get("supplier_name") or ""
                self._daily.save({"amount": d["total"], "category": "Материалы и закупки", "method": pay, "doc": not f.get("nodoc"),
                                  "comment": f"Приход на склад{' № ' + d['number'] if d['number'] else ''}{', ' + sup if sup else ''}"},
                                 self._who(), (u or {}).get("login") or "", "accounting" in perms)
        return did

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
        r = self._reports.debts()
        later = self._fin.not_due()  # 2.12: installments whose date has not come are not overdue debt
        for x in r["debts"]:
            x["not_due"] = min(x["debt"], later.get(x["patient_id"], 0))
        r["overdue"] = self._fin.overdue()
        r["insurance"] = self._fin.ins_summary()
        return r

    # ----------------------------------------------- director's analytics --
    def director_dashboard(self):
        return self._dir.dashboard()

    def report_patients(self, date_from=None, date_to=None):
        return self._dir.patients(date_from, date_to)

    def report_load(self, date_from=None, date_to=None):
        return self._dir.load(date_from, date_to)

    def report_conversion(self, date_from=None, date_to=None):
        return self._dir.conversion(date_from, date_to)

    def report_materials(self, date_from=None, date_to=None):
        return self._dir.materials(date_from, date_to)

    def kpi(self, month=None):
        return self._dir.kpi(month)

    def kpi_save(self, month, items=None, copy_prev=False):
        return self._dir.kpi_save(month, items or [], self._who(), bool(copy_prev))

    def director_settings(self):
        return self._dir.settings()

    def director_settings_save(self, f):
        return self._dir.save_settings(f, self._who())

    # ---------------------------------------------------------- accounting --
    def acc_summary(self, date_from=None, date_to=None):
        from accounting import AD, BASES, METHODS
        return {**self._acc.summary(date_from, date_to), "debts": {k: v for k, v in self._reports.debts().items()
                                                                     if k in ("total_debt", "total_advance")},
                "categories": self._acc.categories(), "methods": METHODS, "bases": BASES,
                "ad_category": AD, "sources": self._mk.sources()}

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

    # 2.15: the financial model — profit by steps, break-even, «what if»
    def _fm(self):
        from finmodel import FinModel
        return FinModel(self._db, self._acc, self._fin, self._dir, self._reports)

    def finmodel(self, month=None):
        return self._fm().model(month)

    def finmodel_scenario(self, month=None, f=None):
        return self._fm().scenario(month, f or {})

    def finmodel_brief(self):
        return self._fm().brief()

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

    # ---------------------------------------------------------------- CRM --
    @staticmethod
    def _login():
        from auth import _current
        u = getattr(_current, "user", None)
        return (u or {}).get("login") or ""

    def crm_summary(self):
        return self._crm.summary(self._login())

    def crm_tasks(self, f=None):
        return self._crm.tasks(f or {}, self._login())

    def crm_task_save(self, f):
        return self._crm.task_save(f or {}, self._who())

    def crm_task_done(self, tid, result="", comment="", later=None):
        return self._crm.task_done(tid, result, comment, self._who(), later)

    def crm_task_reopen(self, tid):
        return self._crm.task_reopen(tid)

    def crm_task_delete(self, tid):
        return self._crm.task_delete(tid)

    def crm_leads(self, f=None):
        return self._crm.leads(f or {})

    def crm_lead(self, lid):
        return self._crm.lead(lid)

    def crm_lead_save(self, f):
        return self._crm.lead_save(f or {}, self._who())

    def crm_lead_stage(self, lid, stage, reason=""):
        return self._crm.lead_stage(lid, stage, reason)

    def crm_lead_link(self, lid, pid):
        return self._crm.lead_link(lid, pid)

    def crm_lead_patient(self, lid):
        return self._crm.lead_patient(lid)

    def crm_match(self, phone):
        return self._crm.match(phone)

    def crm_funnel(self, date_from=None, date_to=None):
        return self._crm.funnel(date_from, date_to)

    def crm_segments(self):
        return self._crm.segments()

    def crm_segment_run(self, filters):
        return self._crm.segment_run(filters or {})

    def crm_segment_save(self, f):
        return self._crm.segment_save(f or {}, self._who())

    def crm_segment_delete(self, sid):
        return self._crm.segment_delete(sid)

    def crm_settings(self):
        return {**self._crm.settings(), "review_links": self._crm.review_links(), "staff": self._crm.staff()}

    def crm_settings_save(self, f):
        self._crm.settings_save(f or {})
        return self.crm_settings()

    def crm_review_save(self, f):
        return self._crm.review_save(f or {}, self._who())

    def crm_review_delete(self, rid):
        return self._crm.review_delete(rid)

    def crm_reviews(self, date_from=None, date_to=None):
        return self._crm.reviews(date_from, date_to)

    def crm_review_queue(self, day=None):
        return self._crm.review_queue(day)

    def crm_patient(self, pid):
        return self._crm.patient(pid)

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
                "clinic": s.get("clinic", {}), "phrases": self._local.templates("phrase"),
                "exams": self._local.structured("exam"), "drugs": self._local.structured("drug")}

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

    def tablet_send(self, tid, kind, patient_id, document_id=None, extra=None):
        """Send «sign this document», «fill in the questionnaire» or «choose and sign the plan» to a paired tablet."""
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
        elif kind == "plan":
            import plans
            extra = extra or {}
            plan = self._plans._plan(extra.get("plan_id"))
            if plan["patient_id"] != patient_id:
                raise ValueError("План не найден")
            html = str(extra.get("html") or "")
            if not html or len(html) > 4_000_000:
                raise ValueError("Пустая презентация плана")
            by = plans.totals(plan["items"], plan["variants"], plan.get("discount") or 0)["by_variant"]
            task = {"kind": "plan", "title": plan.get("title") or "План лечения", "patient": p["name"], "html": html,
                    "signer": p["name"], "plan_id": plan["id"], "patient_id": patient_id, "chosen": plan.get("variant") or "",
                    "variants": [{"key": v["key"], "name": v["name"], "total": by.get(v["key"], 0),
                                  "warranty": v.get("warranty", ""), "term": v.get("term", "")} for v in plan["variants"]]}
        elif kind == "nps":  # the after-visit survey: a score 0–10 and a few words
            s = self._crm.settings()
            task = {"kind": "nps", "title": "Оцените, пожалуйста, визит", "patient": p["name"], "patient_id": patient_id,
                    "question": s["nps_question"], "visit_id": (extra or {}).get("visit_id") or None}
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
            elif t["kind"] == "plan":
                result = self._plans.sign_on_tablet(t, data.get("variant"), data.get("image"), place, ip)
            elif t["kind"] == "nps":
                r = self._crm.review_save({"patient_id": t["patient_id"], "visit_id": t.get("visit_id"), "score": data.get("score"),
                                           "comment": data.get("comment"), "channel": "tablet"}, place)
                self._tablets.done(tb["id"], task_id, {"review_id": r["id"], "score": r["score"]})
                return {"ok": True, "links": [{"title": x["title"], "qr": x["qr"], "url": x["url"]} for x in r["links"]]}
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

    def restore_templates(self, kind):
        """«Вернуть встроенные»: hidden built-in exam templates, medicines or phrases come back."""
        if kind not in ("exam", "drug", "phrase", "document"):
            raise ValueError("Неизвестный вид шаблона")
        return self._local.restore_templates(kind)

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

    @staticmethod
    def _inv_total(inv):
        t = 0.0
        for it in inv.get("items") or []:
            line = float(it.get("price") or 0) * float(it.get("qty") or 1)
            t += line - line * float(it.get("discount") or 0) / 100
        return round(t - t * float(inv.get("discount") or 0) / 100, 2)

    def save_invoice(self, inv):
        is_inv = (inv.get("kind") or "invoice") != "plan"
        if is_inv:
            self._fin.check_uses(inv)  # lines «по абонементу» cost 0 and need visits left on the membership
            if inv.get("insurer_id"):
                self._fin.check_payer(inv, self._inv_total(inv))
        iid = self._local.save_invoice(inv)
        if is_inv:
            self._fin.write_uses(iid, inv.get("items"))
            if "insurer_id" in inv:
                self._fin.set_payer(iid, inv.get("insurer_id"), inv.get("ins_doc_id"))
        self._stock.on_invoice(iid, self._who())  # materials of billed services leave the stock
        return iid

    def invoice(self, iid):
        inv = self._local.invoice(iid)
        if inv:
            states = self._fiscal.payment_states([p["id"] for p in inv["payments"]])
            for p in inv["payments"]:
                p["receipt"] = states.get(p["id"])
            if inv.get("kind") != "plan":
                pk = self._fin.pockets(inv["patient_id"])
                inv["deposit"] = round(sum(x["amount"] for x in pk if x["invoice_id"] != iid), 2)
                inv["overpaid"] = round(sum(x["amount"] for x in pk if x["invoice_id"] == iid), 2)
                inv["schedule"] = self._fin.schedule(iid)
                if inv.get("insurer_id"):
                    ins = self._db.one("SELECT name FROM insurers WHERE id=?", (inv["insurer_id"],))
                    inv["insurer_name"] = ins["name"] if ins else ""
        return inv

    def plan_to_invoice(self, plan_id, item_indexes=None, visit_id=None):
        iid = self._local.plan_to_invoice(plan_id, item_indexes, visit_id)
        self._stock.on_invoice(iid, self._who())
        return iid

    def plan_choose(self, plan_id, variant):
        """The patient chose «эконом / стандарт / премиум» ('' cancels the choice)."""
        return self._plans.choose(plan_id, variant)

    def plan_pdf(self, html, name=""):
        """The plan presentation as a real PDF (headless Edge). The UI saves it with «Сохранить как…»."""
        import plans
        if not isinstance(html, str) or len(html) > 8_000_000:
            raise ValueError("Слишком большой документ")
        return plans.pdf_payload(html, name)

    def set_plan_status(self, plan_id, status):
        with self._db.tx() as c:
            c.execute("UPDATE invoices SET plan_status=?, transferred=0 WHERE id=? AND kind='plan'", (status, plan_id))
        return True

    def delete_invoice(self, iid):
        for p in self._db.q("SELECT id FROM payments WHERE invoice_id=?", (iid,)):
            if self._fiscal.payment_has_receipt(p["id"]):
                raise ValueError("По оплатам этого счёта пробиты чеки. Сначала оформите чеки возврата (раздел «Касса»).")
        self._fin.before_invoice_delete(iid)  # the advance spent on it goes back to the patient
        self._local.delete_invoice(iid)
        self._fin.after_invoice_delete(iid)
        self._stock.on_invoice(iid)  # invoice gone: its automatic write-off goes back to stock
        return True

    def add_payment(self, p):
        import loyalty
        method = p.get("method") or "Наличные"
        try:
            amount = round(float(p.get("amount") or 0), 2)
            inv = self._db.one("SELECT patient_id FROM invoices WHERE id=?", (p.get("invoice_id"),)) if p.get("invoice_id") else None
            patient = inv["patient_id"] if inv else p.get("patient_id")
            if not inv and method not in loyalty.MONEY_METHODS:
                raise ValueError("Аванс принимается деньгами: наличными, картой, по СБП или переводом")
            if not inv and not self._db.one("SELECT 1 AS x FROM patients WHERE id=?", (patient,)):
                raise ValueError("Пациент не найден")
            if method in ("Из аванса", "Страховая"):
                raise ValueError("Этот способ оплаты ставится сам: «Оплатить из аванса» в счёте или оплата реестра страховой")
            if method == loyalty.CERT:  # check before the payment exists: nothing to undo on a refusal
                self._loyal.check_redeem(p.get("cert_code"), amount)
            elif method == loyalty.BONUS:
                self._loyal.check_spend(patient, p.get("invoice_id"), amount)
            if method == loyalty.CERT:
                p = {**p, "comment": (f"сертификат {loyalty.norm_code(p.get('cert_code'))} " + str(p.get("comment") or "")).strip()}
            pid = self._local.add_payment(p)
        except ValueError as e:
            return {"ok": False, "message": str(e)}
        pay = self._db.one("SELECT * FROM payments WHERE id=?", (pid,))
        try:
            if method == loyalty.CERT:
                self._loyal.redeem(p.get("cert_code"), amount, pid)
            self._loyal.on_payment(pay, self._who())
        except ValueError as e:  # e.g. the certificate was used up a second ago on another computer
            self._local.delete_payment(pid)
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
        rows = self._fin.group_rows(pay_id)  # a move of the advance or a refund goes as a whole
        for r in rows:
            if self._fiscal.payment_has_receipt(r["id"]):
                raise ValueError("По этой оплате пробит чек. Сначала оформите чек возврата (раздел «Касса»), затем удалите оплату.")
            if self._fiscal.refund_printed(r["id"]):
                raise ValueError("По этому возврату пробит чек возврата — удалить возврат нельзя.")
        self._fin.can_delete(pay_id)
        for r in rows:
            self._loyal.on_payment_deleted(r["id"])
        if len(rows) > 1 or (rows and rows[0].get("kind") in ("deposit_use", "refund")):
            self._fin.delete_group(pay_id)
        else:
            self._local.delete_payment(pay_id)
        return True

    # ------------------------------------------------------- money 2.12 --
    def money_patient(self, patient_id):
        """Everything about the patient's money besides invoices: advance, memberships, schedules, insurance."""
        return {"deposit": self._fin.deposit(patient_id), "pockets": self._fin.pockets(patient_id),
                "memberships": self._fin.memberships(patient_id), "schedules": self._fin.schedules(patient_id),
                "ins_docs": self._fin.ins_docs(patient_id), "insurers": self._fin.insurers()}

    def deposit_use(self, invoice_id, amount=None, receipt=None, contact=""):
        r = self._fin.deposit_use(invoice_id, amount, self._who())
        import fiscal
        fs = fiscal.settings()
        if fs["enabled"] and (fs["auto"] if receipt is None else receipt):
            try:
                r["receipt"] = self._fiscal.for_payment(r["id"], contact, self._who())
            except ValueError as e:
                r["receipt"] = {"status": "error", "error": str(e)}
        return r

    def refund(self, f):
        f = f or {}
        r = self._fin.refund(f, self._who())
        import fiscal
        fs = fiscal.settings()
        if fs["enabled"] and f.get("receipt", fs["auto"]):
            out = []
            for pid in r["ids"]:
                try:
                    out.append(self._fiscal.for_refund(pid, f.get("contact", ""), self._who()))
                except ValueError as e:
                    out.append({"status": "error", "error": str(e)})
            r["receipt"] = out[0] if len(out) == 1 else {"status": out[-1].get("status"), "many": out}
        return r

    def schedule(self, invoice_id):
        return self._fin.schedule(invoice_id)

    def schedule_draft(self, invoice_id, count=3, first=None, step="month"):
        inv = self._db.one("SELECT total FROM invoices WHERE id=?", (invoice_id,))
        if not inv:
            raise ValueError("Счёт не найден")
        paid = self._db.one("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE invoice_id=?", (invoice_id,))["s"]
        return self._fin.schedule_draft(inv["total"], paid, count, first or None, step)

    def schedule_save(self, f):
        return self._fin.schedule_save(f, self._who())

    def schedule_delete(self, invoice_id):
        return self._fin.schedule_delete(invoice_id)

    def overdue_payments(self):
        return self._fin.overdue()

    def membership_types(self, all_=False):
        return self._fin.mtypes(bool(all_))

    def membership_type_save(self, f):
        return self._fin.mtype_save(f)

    def membership_type_delete(self, mid):
        return self._fin.mtype_delete(mid)

    def membership_sell(self, f):
        r = self._fin.membership_sell(f, self._who())
        self._stock.on_invoice(r["invoice_id"], self._who())
        return r

    def memberships(self, patient_id, active_only=False):
        return self._fin.memberships(patient_id, bool(active_only))

    def membership_cancel(self, mid):
        return self._fin.membership_cancel(mid)

    def cash_shift(self):
        return self._fin.shift_current()

    def cash_shift_open(self, f):
        return self._fin.shift_open(f, self._who())

    def cash_move(self, f):
        """Money put into or taken out of the drawer; «Расход из кассы» can go to the expenses at once."""
        f = f or {}
        eid = None
        if f.get("kind") == "out" and f.get("expense"):
            cur = self._fin.shift_current()["shift"]
            if cur and float(f.get("amount") or 0) <= cur["expected_cash"] + 0.009:
                eid = self._acc.save_expense({"amount": f.get("amount"), "category": f.get("category") or "Прочее",
                                              "method": "Наличные", "comment": (f.get("reason") or "") + (": " + f["comment"] if f.get("comment") else "")},
                                             self._who())
        try:
            return self._fin.shift_move(f, self._who(), eid)
        except ValueError:
            if eid:
                self._acc.delete_expense(eid)
            raise

    def cash_shift_close(self, f):
        out = self._fin.shift_close(f, self._who())
        import daily
        s = daily.settings()
        if s["enabled"] and s["on_close"]:  # 2.14: the day report goes to the owner when the shift is closed
            day = date.today().isoformat()
            threading.Thread(target=self._send_day_quiet, args=(day,), name="day-report", daemon=True).start()
            out["report_sending"] = True
        return out

    # --------------------------------------- 2.14: expenses of the day, the day report by e-mail --
    @staticmethod
    def _my_perms():
        from auth import PERM_KEYS, Auth, _current
        u = getattr(_current, "user", None)
        return (set(Auth.effective_perms(u)) if u else set(PERM_KEYS)), u

    def day_expenses(self):
        """Today's expenses: one's own (an administrator starts every day with a clean list), all of them with «Бухгалтерия»."""
        perms, u = self._my_perms()
        return self._daily.today((u or {}).get("login") or "", "accounting" in perms)

    def day_expense_save(self, f):
        perms, u = self._my_perms()
        eid = self._daily.save(f, self._who(), (u or {}).get("login") or "", "accounting" in perms)
        return {"id": eid, **self.day_expenses()}

    def day_expense_delete(self, eid):
        perms, u = self._my_perms()
        self._daily.delete(eid, (u or {}).get("login") or "", "accounting" in perms)
        return self.day_expenses()

    def _cash_for(self, day):
        try:
            return self.cash_day(day)
        except Exception:  # noqa: BLE001
            return {}

    def _send_day_quiet(self, day):
        try:
            self._daily.send(day, self._cash_for(day), self._who() or "Программа")
        except ValueError as e:
            log.info("day report: %s", e)

    def day_report(self, day=None):
        """The report of the day as it will go by mail. Without «Бухгалтерия» — today only."""
        perms, u = self._my_perms()
        day = str(day or date.today().isoformat())[:10]
        if day != date.today().isoformat() and "accounting" not in perms:
            raise ValueError("Отчёты прошлых дней видит только директор")
        full = bool(perms & {"cash_report", "accounting"})  # without them: one's own expenses, no cash figures
        rep = self._daily.report(day, self._cash_for(day) if full else {}, None if full else ((u or {}).get("login") or ""), shifts=full)
        return {**rep, "text": self._daily.text(rep), "state": self._daily.report_state(day)}

    def day_report_send(self, day=None, force=True):
        perms, _ = self._my_perms()
        day = str(day or date.today().isoformat())[:10]
        if day != date.today().isoformat() and "accounting" not in perms:
            raise ValueError("Отчёты прошлых дней отправляет только директор")
        return self._daily.send(day, self._cash_for(day), self._who(), force=bool(force))

    def day_report_settings(self):
        import daily
        return daily.public_settings()

    def day_report_settings_save(self, f):
        import daily
        return daily.save_settings(f if isinstance(f, dict) else {})

    # 2.14.1: the day report in Telegram through the clinic's own bot
    @staticmethod
    def _tg_token(token=""):
        import daily
        token = "".join(str(token or "").split()) or config.unprotect(daily.settings()["tg_token_enc"] or "")
        if not token:
            raise ValueError("Вставьте токен бота от @BotFather")
        return token

    def day_report_tg_check(self, token=""):
        """The bot behind the token (and its link for the owner to press «Старт»)."""
        import daily
        try:
            bot = daily.tg_check(self._tg_token(token))
        except daily.TgError as e:
            raise ValueError(str(e)[0].upper() + str(e)[1:]) from e
        return bot

    def day_report_tg_chats(self, token=""):
        """Who pressed «Старт» in the bot — the owner picks who gets the report."""
        import daily
        try:
            return daily.tg_chats(self._tg_token(token))
        except daily.TgError as e:
            raise ValueError(str(e)[0].upper() + str(e)[1:]) from e

    def cash_shifts(self, limit=40):
        return self._fin.shifts(limit)

    def cash_shift_info(self, sid):
        sh = self._fin.shift(sid)
        if not sh:
            raise ValueError("Смена не найдена")
        b = sh["closed_at"] or "9999"
        sh["payment_rows"] = self._db.q("""SELECT pay.*, p.name AS patient_name FROM payments pay LEFT JOIN patients p ON p.id=pay.patient_id
                                           WHERE pay.created_at>=? AND pay.created_at<=? AND pay.method IN ('Наличные','Карта','СБП','Перевод')
                                           ORDER BY pay.created_at""", (sh["opened_at"], b))
        return sh

    def insurers(self, all_=False):
        return self._fin.insurers(bool(all_))

    def insurer_save(self, f):
        return self._fin.insurer_save(f)

    def ins_docs(self, patient_id):
        return self._fin.ins_docs(patient_id)

    def ins_doc_save(self, f):
        return self._fin.ins_doc_save(f)

    def ins_doc_delete(self, did):
        return self._fin.ins_doc_delete(did)

    def ins_summary(self):
        return {**self._fin.ins_summary(), "registries": self._fin.registries()}

    def ins_candidates(self, insurer_id, date_from=None, date_to=None):
        return self._fin.ins_invoices(insurer_id, date_from or None, date_to or None)

    def registry_make(self, f):
        return self._fin.registry_make(f, self._who())

    def registry(self, rid):
        return self._fin.registry(rid)

    def registry_status(self, rid, status):
        return self._fin.registry_status(rid, status)

    def registry_pay(self, rid, f=None):
        return self._fin.registry_pay(rid, f or {}, self._who())

    def registry_delete(self, rid):
        return self._fin.registry_delete(rid)

    def registry_xlsx(self, rid):
        title, head, rows = self._fin.registry_table(rid)
        return self.export_xlsx(title, head, rows)

    # ---------------------------------------------------------------- lab --
    def lab_options(self):
        import lab
        return {"labs": self._lab.labs(), "works": lab.WORKS, "shades": lab.SHADES, "statuses": lab.STATUSES}

    def lab_orders(self, status="open", lab_id=None, patient_id=None, doctor_id=None):
        return self._lab.orders(status, lab_id or None, patient_id or None, doctor_id or None)

    def lab_order(self, oid):
        return self._lab.order(oid)

    def lab_save(self, f):
        return self._lab.save(f or {}, self._who())

    def lab_status(self, oid, status):
        return self._lab.set_status(oid, status)

    def lab_pay(self, oids, method="Безналичный перевод"):
        return self._lab.mark_paid(oids, self._acc, method, self._who())

    def labs_save(self, f):
        return self._lab.save_lab(f or {})

    def lab_summary(self):
        return self._lab.summary()

    # ------------------------------------------------------------ loyalty --
    def loyalty_settings(self):
        import loyalty
        return loyalty.settings()

    def loyalty_settings_save(self, f):
        import loyalty
        return loyalty.save_settings(f or {})

    def cert_sell(self, f):
        return self._loyal.sell(f or {}, self._who())

    def cert_info(self, code):
        return self._loyal.certificate(code)

    def cert_list(self, status="active"):
        return self._loyal.certificates(status)

    def cert_cancel(self, code):
        return self._loyal.cancel_certificate(code)

    def bonus_info(self, patient_id):
        import loyalty
        return {"balance": self._loyal.bonus_balance(patient_id), "history": self._loyal.bonus_history(patient_id)[:30],
                "family": self._loyal.family_of(patient_id), "settings": loyalty.settings()}

    def bonus_adjust(self, patient_id, amount, comment):
        return self._loyal.adjust(patient_id, amount, comment, self._who())

    def family_save(self, f):
        return self._loyal.save_family(f or {})

    def family_leave(self, patient_id):
        return self._loyal.leave_family(patient_id)

    # ---------------------------------------------------------------- SBP --
    def sbp_settings(self):
        s = config.load_settings().get("sbp") or {}
        return {"qr": s.get("qr") or "", "label": s.get("label") or "", "clinic": self._clinic().get("name") or ""}

    def sbp_settings_save(self, f):
        f = f or {}
        qr = str(f.get("qr") or "")
        if qr and (not qr.startswith("data:image/") or len(qr) > 3_000_000):
            raise ValueError("Загрузите картинку QR-кода (PNG или JPEG до 2 МБ)")
        config.save_settings({"sbp": {"qr": qr, "label": str(f.get("label") or "")[:200]}})
        return self.sbp_settings()

    def sbp_to_tablet(self, tid, amount, patient_id=None):
        """Show the clinic's SBP QR code and the sum on the patient tablet."""
        s = self.sbp_settings()
        if not s["qr"]:
            raise ValueError("Загрузите QR-код СБП в Настройках → «Бонусы, сертификаты и СБП»")
        p = self._db.patient(patient_id) if patient_id else None
        return self._tablets.send(tid, {"kind": "qr", "title": "Оплата по СБП", "patient": (p or {}).get("name") or "",
                                        "html": "", "qr": s["qr"], "amount": round(float(amount or 0), 2), "label": s["label"]}, self._who())

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
        """The day's payments; «money» is what actually came in: without certificate and bonus payments,
        plus certificates sold that day."""
        import loyalty
        out = self._local.cash_day(day)
        out["cert_sales"] = self._loyal.sales_day(day)
        sold = round(sum(x["amount"] for x in out["cert_sales"]), 2)
        non_money = sum(v for k, v in out["by_method"].items() if k in (loyalty.CERT, loyalty.BONUS))
        out["money_total"] = round(out["total"] - non_money + sold, 2)
        out["cert_sold"] = sold
        out["refunds"] = round(-sum(x["amount"] for x in out["payments"] if x.get("kind") == "refund"), 2)
        out["by_method"].pop("Из аванса", None)  # a move of the advance: +sum on the invoice, −sum on the advance
        out["shift"] = self._fin.shift_current()["shift"]
        return out

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
                mats = self._stock.materials()
                st["stock_low"] = sum(1 for m in mats if m["low"] or m["balance"] < 0)
                st["stock_exp"] = sum(1 for m in mats if m["exp_state"])
                st["stock_alerts"] = sum(1 for m in mats if m["low"] or m["balance"] < 0 or m["exp_state"])
        except Exception:  # noqa: BLE001
            pass
        try:
            from auth import _current, Auth
            u = getattr(_current, "user", None)
            if u is None or "lab" in Auth.effective_perms(u):
                ls = self._lab.summary()
                st["lab_due"] = ls["overdue"] + ls["fitting_today"]
        except Exception:  # noqa: BLE001
            pass
        try:
            from auth import _current, Auth
            u = getattr(_current, "user", None)
            if u is None or "marketing" in Auth.effective_perms(u):
                self._crm.auto()  # the rules run at most every 10 minutes
                st["crm_due"] = self._crm.due_count((u or {}).get("login") or "")
        except Exception:  # noqa: BLE001
            log.exception("crm tasks")
        try:
            from auth import _current, Auth
            u = getattr(_current, "user", None)
            if u is None or "settings" in Auth.effective_perms(u):
                import backup
                st["backup_warn"] = backup.warning()
                import cloud
                if cloud.configured():
                    c = self._cloud_obj().status()
                    sub = c.get("subscription") or {}
                    st["cloud"] = {"error": c["error"], "offline": c["offline"], "pending": c["pending"],
                                   "conflicts": c["conflicts"], "last_ok": c["last_ok"], "state": sub.get("state"),
                                   "days_left": sub.get("days_left"), "plan_title": sub.get("plan_title")}
        except Exception:  # noqa: BLE001
            pass
        try:
            import updates
            us = updates.UPDATER.state
            st["update"] = {"available": us["available"], "latest": us["latest"]}
        except Exception:  # noqa: BLE001
            pass
        try:  # 2.14: the employee's rights now (the director may change a position while the employee works)
            from auth import _current, Auth
            u = getattr(_current, "user", None)
            if u is not None:
                st["me_perms"] = Auth.effective_perms(u)
            self._daily.tick(self._cash_for)  # the day report at the set time, at most every 5 minutes
        except Exception:  # noqa: BLE001
            log.exception("status 2.14")
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
        if mode == "visit" and patient_id and not self._consents.has(patient_id):
            raise ValueError("Нет согласия пациента на запись приёма. Отметьте согласие и запишите приём снова.")
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
        from auth import role_base
        vp = voices.prints(self._db)
        try:
            users = self._db.q("SELECT id, name, position, role, doctor_id FROM users WHERE status='active' ORDER BY name")
        except Exception:  # noqa: BLE001
            users = []
        staff = [{"id": u["id"], "name": u["name"], "position": u["position"] or "", "label": voices.role_label(dict(u)),
                  "role": u["role"], "voice": {k: vp[u["id"]][k] for k in ("seconds", "quality", "updated_at")} if u["id"] in vp else None}
                 for u in users if role_base(u["role"]) not in ("storekeeper",)]
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

    # 2.13: the clinic's own local model and its quality check
    def local_ai_custom(self):
        import llm_local
        return llm_local.make_custom()

    def local_ai_eval(self, model=""):
        import ai
        import llm_local
        return llm_local.evaluate(str(model or ai.settings().get("model") or llm_local.CUSTOM))

    # ------------------------------------------------ 2.13: AI in the work --
    def assistant_ask(self, text, ctx=None):
        """The assistant in the corner: an answer from the program's data with this employee's rights."""
        from assistant import Assistant
        return Assistant(self).ask(text, ctx if isinstance(ctx, dict) else {})

    def assistant_voice(self, audio_b64, mime="audio/webm", ctx=None):
        import speech
        audio, suffix = self._audio(audio_b64, mime)
        rec = speech.transcribe(audio, suffix, "Кто у меня завтра? Запиши Петрову на четверг к Гусевой. Выручка за октябрь.")
        out = self.assistant_ask(rec["text"], ctx)
        out["heard"] = rec["text"]
        return out

    def ai_write(self, kind, record_id=None, patient_id=None, invoice_id=None, data=None):
        """A draft from the record: recommendations in plain words, an extract, a letter to the insurance company.
        `data` — the record form that is not saved yet."""
        import ai_docs
        rec = self._local.record(record_id) if record_id else None
        if not rec and isinstance(data, dict) and patient_id:
            rec = {"id": None, "patient_id": patient_id, "visit_id": data.get("visit_id"), "date": data.get("date"), "data": data}
        if not rec and patient_id:
            recs = self._local.records(patient_id)
            rec = recs[0] if recs else None
        if not rec:
            raise ValueError("В медкарте пациента нет записей — сначала проведите лечение")
        services = []
        inv = self._local.invoice(invoice_id) if invoice_id else None
        if not inv and rec.get("visit_id"):
            inv = next((i for i in self._local.invoices(rec["patient_id"]) if i.get("visit_id") == rec["visit_id"]
                        and (i.get("kind") or "invoice") == "invoice"), None)
        if inv:
            services = [str(x.get("title") or "") + (f" (зуб {x['tooth']})" if x.get("tooth") else "") for x in inv["items"]]
        p = self._db.patient(rec["patient_id"])
        out = ai_docs.write(kind, rec, services, names=[p["name"]] if p else [])
        out["record_id"] = rec["id"]
        return out

    def ai_plan_variant(self, v):
        import ai_docs
        return ai_docs.plan_variant(v if isinstance(v, dict) else {})

    def ai_translate(self, lines, lang, patient_id=None):
        import ai_docs
        p = self._db.patient(patient_id) if patient_id else None
        return ai_docs.translate(lines, lang, names=[p["name"]] if p else [])

    def ai_langs(self):
        import ai
        import ai_docs
        return {"langs": ai_docs.LANG_TITLE, "kinds": ai_docs.KINDS, "enabled": ai.enabled()}

    def medcheck_patient(self, pid):
        import medcheck
        return medcheck.check_patient(self._db, self._local, pid)

    def medcheck_record(self, f):
        import medcheck
        f = f if isinstance(f, dict) else {}
        xr = [r["taken_at"] or r["created_at"] for r in self._db.q(
            "SELECT taken_at, created_at FROM patient_files WHERE patient_id=? AND kind='xray'", (str(f.get("patient_id") or ""),))]
        return medcheck.check_record(f, xr)

    def director_weekly(self, week=None, use_ai=False):
        """The weekly summary for the director; with use_ai the model retells it as a short note (kept per week)."""
        import ai
        w = self._dir.weekly(week)
        key = f"ai_weekly:{w['week']}"
        cached = self._db.meta_get(key)
        if cached:
            w["ai_text"] = cached
        if use_ai and ai.enabled():
            try:
                w["ai_text"] = ai.generate("Перескажи директору клиники сводку за неделю короткой запиской: 3–5 предложений, "
                                           "до 700 знаков, сначала главное, затем 1–2 конкретных совета, что сделать на этой "
                                           "неделе. Цифры не меняй, без приветствия и заголовка.",
                                           w["title"] + "\n" + "\n".join(w["lines"]), max_chars=800)
                self._db.meta_set(key, w["ai_text"])
            except ValueError as e:
                w["ai_error"] = str(e)
        w["ai"] = ai.enabled()
        return w

    def teeth_voice(self, audio_b64, mime="audio/webm"):
        """13.2: the tooth chart by voice → {'text', 'teeth'}; the doctor checks it in the form."""
        import dictation
        import speech
        audio, suffix = self._audio(audio_b64, mime)
        rec = speech.transcribe(audio, suffix, dictation.FORMULA_PROMPT)
        return {**dictation.formula(rec["text"]), "seconds": rec["seconds"]}

    def teeth_parse(self, text):
        import dictation
        return dictation.formula(text)

    def voice_note(self, audio_b64, mime="audio/webm"):
        """13.4: a spoken note to the patient → text, and a task if it says «перезвонить через неделю»."""
        import assistant
        import speech
        audio, suffix = self._audio(audio_b64, mime)
        rec = speech.transcribe(audio, suffix, "Перезвонить через неделю. Пригласить на гигиену. Пациент просит утреннее время.")
        return assistant.voice_note(rec["text"])

    def note_parse(self, text):
        import assistant
        return assistant.voice_note(text)

    def consent_get(self, pid):
        return self._consents.get(pid)

    def consent_give(self, pid, method="verbal", note=""):
        return self._consents.give(pid, "recording", method, note, self._who())

    def consent_revoke(self, pid):
        return self._consents.revoke(pid, "recording", self._who())

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
        from server import local_addresses, network_categories
        s = config.load_settings()
        port = int(s.get("port") or 8765)
        ips = local_addresses()
        cats = network_categories()
        return {"mode": s.get("net_mode") or "server", "port": port, "addresses": ips,
                "urls": [f"http://{ip}:{port}/" for ip in ips],
                # Windows blocks incoming connections on a «Public» network: tablets and other PCs cannot connect
                "public": bool(ips) and cats.get(ips[0]) == "Public"}

    # ------------------------------------------------- cloud, updates, import --
    @staticmethod
    def _director(what):
        from auth import _current
        u = getattr(_current, "user", None)
        if u is not None and u.get("role") != "director":
            raise ValueError(f"{what} может только директор")

    def _cloud_obj(self):
        if self._cloud is None:
            from cloud import Cloud
            self._cloud = Cloud(self._db)
        return self._cloud

    @staticmethod
    def _cloud_call(fn, *a):
        from cloud import CloudError
        try:
            return fn(*a)
        except CloudError as e:
            raise ValueError(str(e)) from None

    def cloud_status(self):
        return self._cloud_obj().status()

    def cloud_join(self, url, code, name=""):
        self._director("Подключать клинику к облаку")
        r = self._cloud_call(self._cloud_obj().join, url, code, name)
        if self._cloud_worker:
            self._cloud_worker.trigger()
        return r

    def cloud_sync(self):
        return self._cloud_call(self._cloud_obj().sync)

    def cloud_code(self):
        self._director("Смотреть код подключения")
        return {"code": self._cloud_call(self._cloud_obj().code_for_others)}

    def cloud_leave(self):
        self._director("Отключать компьютер от облака")
        return self._cloud_call(self._cloud_obj().leave)

    def cloud_revoke(self, device_id):
        self._director("Отключать компьютеры клиники")
        return self._cloud_call(self._cloud_obj().revoke_device, str(device_id or ""))

    def cloud_conflicts(self, show_seen=False):
        import replica
        return replica.conflicts(self._db, bool(show_seen))

    def cloud_conflict_seen(self, cid=None):
        import replica
        return replica.conflict_seen(self._db, cid)

    def cloud_conflict_restore(self, cid):
        import replica
        return replica.conflict_restore(self._db, cid)

    def update_status(self):
        import updates
        st = dict(updates.UPDATER.state)
        st["configured"] = bool(updates.source())
        st["installed"] = bool(getattr(sys, "frozen", False))
        return st

    def update_check(self):
        import updates
        updates.UPDATER.check()
        return self.update_status()

    def update_download(self):
        self._director("Обновлять программу")
        import updates
        updates.UPDATER.start_download()
        return self.update_status()

    def update_install(self):
        self._director("Обновлять программу")
        import updates
        updates.UPDATER.install()
        return True

    def import_preview(self, name, data_b64, mapping=None):
        import files
        from importer import Importer
        return Importer(self._db, self._local).preview(name, files.b64_bytes(data_b64), mapping)

    def import_run(self, name, data_b64, mapping):
        import files
        from importer import Importer
        return Importer(self._db, self._local).run(name, files.b64_bytes(data_b64), mapping or {})

    def import_dp_all(self):
        s = config.load_settings()
        if s.get("demo"):
            raise ValueError("Сначала выключите демо-режим и впишите логин и пароль API Dentist Plus")
        if not (s.get("login") and s.get("pass_enc")):
            raise ValueError("Сначала впишите логин и пароль API Dentist Plus (Настройки → «Подключение к Dentist Plus»)")
        config.save_settings({"sync_all_patients": True})
        self._worker.trigger()
        return {"ok": True}

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
            p["surf_local"] = self._local.surf_state(pid)
            p["marketing"] = self._mk.patient_info(pid)
            p["files_count"] = self._files.count(pid)
            p["questionnaire"] = self._forms.latest(pid)
            p["lab_count"] = len(self._lab.orders("all", patient_id=pid))
            p["bonus"] = self._loyal.bonus_balance(pid)
            fam = self._loyal.family_of(pid)
            p["family"] = {"id": fam["id"], "name": fam["name"], "discount": fam["discount"], "members": len(fam["members"])} if fam else None
            signed = self._forms.signed_ids([d["id"] for d in p["documents"]])
            for d in p["documents"]:
                d["signed"] = d["id"] in signed
            p["perio_count"] = len(self._perio.list(pid))
            p["crm_open"] = self._db.one("SELECT COUNT(*) AS n FROM crm_tasks WHERE patient_id=? AND status='open'", (pid,))["n"]
            p["deposit"] = self._fin.deposit(pid)  # 2.12: advance, memberships, insurance documents
            p["free_payments"] = self._db.q("SELECT * FROM payments WHERE patient_id=? AND COALESCE(invoice_id,'')='' ORDER BY created_at DESC",
                                            (pid,))
            p["memberships"] = self._fin.memberships(pid, True)
            p["ins_docs"] = [d for d in self._fin.ins_docs(pid) if not d["expired"]]
            p["consent_recording"] = self._consents.get(pid)  # 2.13: consent to record the visit
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
        for k in ("cloud_token", "cloud_key", "cloud_invite"):  # stay on this computer, never shown
            s.pop(k, None)
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
            import cloud
            if cloud.configured():
                raise ValueError("Компьютер подключён к облаку клиники: демо-режим удалил бы данные на всех компьютерах. "
                                 "Сначала отключите облако (Настройки → «Облако и подписка»).")
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


def start_platform(api, db, holder=None):
    """Cloud sync and the update check, after every table exists (Api and Auth create theirs)."""
    from cloud import CloudWorker
    import updates
    w = CloudWorker(db)
    api._cloud, api._cloud_worker = w.cloud, w
    w.start()
    updates.UpdateWorker().start()
    if holder is not None:
        holder.cloud = w
    return w


def single_instance():
    """Return False if the app is already running (named mutex)."""
    if os.name != "nt":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{config.APP_NAME}OfflineMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def self_install():
    """Running a downloaded single-file exe (an older kind of build) installs it for this user and starts the
    installed copy. Since 2.6.1 releases are an installer (setup_main.py) that puts the program folder in place,
    and the installed folder build never installs itself. Returns True if this process should exit."""
    import installer
    if not getattr(sys, "frozen", False) or os.name != "nt" or "--no-install" in sys.argv or installer.is_onedir():
        return False
    import shutil
    exe = os.path.abspath(sys.executable)
    target_dir = installer.install_dir()
    target = installer.target_exe()
    if os.path.normcase(exe) == os.path.normcase(target):
        return False
    if not installer.close_running(target, seconds=10):
        installer.message(f"{config.BRAND['name']} уже открыта.\n\nЗакройте программу (значок в панели задач, правый щелчок → Закрыть окно) "
                          "и запустите этот файл ещё раз — программа обновится.")
        return True
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(exe, target + ".new")
        os.replace(target + ".new", target)
    except OSError as e:
        log.warning("self-install failed, running in place: %s", e)
        return False
    try:
        installer.make_shortcuts(target)
    except Exception as e:  # noqa: BLE001
        log.warning("shortcuts failed: %s", e)
    log.info("installed to %s", target)
    installer.launch(target, [a for a in sys.argv[1:] if a != "--no-install"])
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
        start_platform(api, db, self)
        from backup import BackupWorker
        self.backups = BackupWorker(db.path)
        self.backups.start()

    def stop(self):
        if self.worker:
            self.worker.stop_flag = True
        if getattr(self, "cloud", None):
            self.cloud.stop_flag = True
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
