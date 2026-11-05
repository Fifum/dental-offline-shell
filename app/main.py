"""Offline shell over Dentist Plus: schedule, patient cards and front-desk work without internet."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import date, timedelta

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
        self._local = Local(db)
        catalog.seed(db, demo=bool(config.load_settings().get("demo")))

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
        return self._local.save_invoice(inv)

    def invoice(self, iid):
        return self._local.invoice(iid)

    def plan_to_invoice(self, plan_id, item_indexes=None, visit_id=None):
        return self._local.plan_to_invoice(plan_id, item_indexes, visit_id)

    def set_plan_status(self, plan_id, status):
        with self._db.tx() as c:
            c.execute("UPDATE invoices SET plan_status=?, transferred=0 WHERE id=? AND kind='plan'", (status, plan_id))
        return True

    def delete_invoice(self, iid):
        self._local.delete_invoice(iid)
        return True

    def add_payment(self, p):
        try:
            return {"ok": True, "id": self._local.add_payment(p)}
        except ValueError as e:
            return {"ok": False, "message": str(e)}

    def delete_payment(self, pay_id):
        self._local.delete_payment(pay_id)
        return True

    def cash_day(self, day):
        return self._local.cash_day(day)

    def journal(self, show_done=False):
        return self._local.journal(show_done)

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
        return st

    def sync_now(self):
        self._worker.trigger()
        return True

    # ---------------------------------------------------------- schedule --
    def day(self, day: str, branch_id: str | None = None):
        return {"visits": self._db.day(day, branch_id or None),
                "doctors": self._db.doctors(), "branches": self._db.branches()}

    def month_counts(self, first_day: str):
        d = date.fromisoformat(first_day)
        return self._db.day_counts((d - timedelta(days=7)).isoformat(), (d + timedelta(days=45)).isoformat())

    def visit(self, vid):
        return self._db.visit(vid)

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
    try:
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(exe, target + ".new")
        os.replace(target + ".new", target)
    except PermissionError:
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


def main():
    import webview
    from sync import SyncWorker

    if self_install():
        return
    if not single_instance():
        ctypes_msg(f"{config.BRAND['name']} уже открыта — посмотрите в панели задач.")
        return
    db = DB()
    worker = SyncWorker(db)
    worker.start()
    api = Api(db, worker)
    ui = config.resource_dir() / "ui" / "index.html"
    window = webview.create_window(config.APP_TITLE, url=str(ui), js_api=api, width=1360, height=860,
                                   min_size=(1000, 640), background_color="#F6F6F6",
                                   minimized="--minimized" in sys.argv)
    _ = window
    webview.start(debug="--debug" in sys.argv, private_mode=False,
                  storage_path=str(config.data_dir() / "webview"))
    worker.stop_flag = True


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
