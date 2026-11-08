"""Staff accounts: registration requests, director approval, password login, roles and permissions.

Passwords are stored as PBKDF2-SHA256 hashes with a per-user salt. Session tokens are random and
only their SHA-256 is kept in the database, so a copied database file does not let anyone log in.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT, login TEXT UNIQUE COLLATE NOCASE, name TEXT, position TEXT,
    role TEXT, perms TEXT, pass_hash TEXT, status TEXT, doctor_id TEXT,
    created_at TEXT, approved_at TEXT, approved_by INTEGER, last_login TEXT);
CREATE TABLE IF NOT EXISTS sessions(
    token_hash TEXT PRIMARY KEY, user_id INTEGER, created_at TEXT, last_seen TEXT, ip TEXT, agent TEXT);
CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, user_id INTEGER, user_name TEXT, action TEXT,
    detail TEXT, ip TEXT);
CREATE INDEX IF NOT EXISTS ix_audit_at ON audit(at);
"""

# ------------------------------------------------------------------ permissions --
PERMS = [
    ("schedule_view", "Расписание: просмотр"),
    ("schedule_edit", "Расписание: запись, перенос, отмена"),
    ("patients_view", "Пациенты: просмотр карточки"),
    ("patients_edit", "Пациенты: новые пациенты и примечания"),
    ("medcard_view", "Медкарта: просмотр лечений и формулы"),
    ("medcard_edit", "Медкарта: проведение лечения"),
    ("docs", "Документы: создание и печать"),
    ("billing", "Счета и планы лечения"),
    ("payments", "Приём оплат"),
    ("cash_report", "Касса: отчёт за день"),
    ("reports", "Отчёты: выручка, визиты, долги"),
    ("accounting", "Бухгалтерия: расходы, зарплата, прибыль"),
    ("marketing", "Маркетинг: источники, обзвон, дни рождения"),
    ("shifts_edit", "Графики работы: составление"),
    ("transfer", "Перенос в Dentist Plus"),
    ("refs", "Шаблоны, прайс, реквизиты"),
    ("fiscal", "Касса: чеки, смены, X- и Z-отчёты, возвраты"),
    ("stock_view", "Склад: просмотр остатков"),
    ("stock_edit", "Склад: приход, списание, инвентаризация"),
    ("equipment", "Оборудование: учёт, обслуживание, списание"),
    ("settings", "Настройки и подключение к Dentist Plus"),
    ("staff", "Сотрудники, права и журнал действий"),
]
PERM_KEYS = [k for k, _ in PERMS]

ROLES = {
    "director": {"title": "Директор", "perms": PERM_KEYS},
    "admin": {"title": "Администратор", "perms": [
        "schedule_view", "schedule_edit", "patients_view", "patients_edit", "medcard_view", "docs",
        "billing", "payments", "cash_report", "fiscal", "transfer", "refs", "stock_view", "stock_edit",
        "marketing", "shifts_edit"]},
    "doctor": {"title": "Врач", "perms": [
        "schedule_view", "patients_view", "patients_edit", "medcard_view", "medcard_edit", "docs", "billing", "stock_view"]},
    "assistant": {"title": "Ассистент", "perms": ["schedule_view", "patients_view", "medcard_view", "stock_view"]},
    "storekeeper": {"title": "Кладовщик", "perms": ["stock_view", "stock_edit", "equipment"]},
}

# who is calling the data API right now (set by the server for each request)
_current = threading.local()


def set_current_user(user):
    _current.user = user


def current_user_name() -> str:
    u = getattr(_current, "user", None)
    return u["name"] if u else ""

# Which permission each Api method needs. A tuple means "any of these". Methods that are not listed
# are refused: a new method stays closed until someone decides who may call it.
ANY_USER = "*"
METHOD_PERMS = {
    "status": ANY_USER, "ui_settings": ANY_USER, "reference": ANY_USER, "offline_snapshot": ANY_USER,
    "day": "schedule_view", "month_counts": "schedule_view", "visit": ("schedule_view", "patients_view"),
    "save_visit": "schedule_edit", "set_visit_status": ("schedule_edit", "medcard_edit"), "revert_visit": "schedule_edit",
    "search": ("patients_view", "schedule_edit"), "patient": "patients_view",
    "create_patient": "patients_edit", "add_note": "patients_edit", "delete_note": "patients_edit",
    "record": "medcard_view", "save_record": "medcard_edit", "delete_record": "medcard_edit",
    "templates": ("docs", "medcard_edit", "refs"), "save_template": "refs", "delete_template": "refs", "reset_template": "refs",
    "doc_context": "docs", "save_document": "docs", "document": "docs", "delete_document": "docs",
    "services": ("billing", "refs", "docs"), "save_service": "refs", "delete_service": "refs", "import_services": "refs",
    "invoice": ("billing", "payments"), "save_invoice": "billing", "delete_invoice": "billing",
    "plan_to_invoice": "billing", "set_plan_status": "billing",
    "add_payment": "payments", "delete_payment": "payments", "cash_day": "cash_report",
    "save_visit_series": "schedule_edit", "visit_series": ("schedule_view", "schedule_edit"), "cancel_series": "schedule_edit",
    "waitlist": ("schedule_view", "schedule_edit"), "waitlist_count": ("schedule_view", "schedule_edit"),
    "waitlist_save": "schedule_edit", "waitlist_done": "schedule_edit", "waitlist_remove": "schedule_edit",
    "reminder_template": ("marketing", "schedule_edit"), "reminder_template_save": "marketing",
    "journal": "transfer", "mark_transferred": "transfer", "retry_push": "transfer", "force_push": "transfer", "sync_now": ANY_USER,
    "write_map_default": "settings", "get_settings": "settings", "save_settings": "settings",
    "test_connection": "settings", "diagnostics": "settings", "open_data_dir": "settings",
    "dev_report": "settings", "show_dev_report": "settings",
    "network_info": "settings", "save_clinic": "refs",
    # backups (restore: directors only, checked again in Api.backup_restore)
    "backup_status": "settings", "backup_now": "settings", "backup_list": "settings",
    "backup_settings_save": "settings", "backup_restore": "settings", "security_status": "settings",
    # dictation and AI
    "speech_status": ("medcard_edit", "settings"), "dictate": "medcard_edit", "parse_dictation": "medcard_edit",
    "speech_download": "settings", "speech_use": "settings", "ai_settings_save": "settings", "ai_test": "settings",
    "voice_status": "settings", "voice_download": "settings", "voice_enroll": "settings", "voice_delete": "settings",
    "local_ai_status": "settings", "local_ai_install": "settings", "local_ai_pull": "settings",
    "local_ai_use": "settings", "local_ai_delete": "settings",
    # stock and equipment
    "stock_summary": ("stock_view", "equipment"), "materials": ("stock_view", "stock_edit"),
    "material": ("stock_view", "stock_edit"), "stock_moves": ("stock_view", "stock_edit"),
    "stock_docs": ("stock_view", "stock_edit"), "stock_doc": ("stock_view", "stock_edit"),
    "suppliers": ("stock_view", "stock_edit"), "norms": ("stock_view", "stock_edit", "refs"),
    "save_material": "stock_edit", "delete_material": "stock_edit", "save_supplier": "stock_edit",
    "delete_supplier": "stock_edit", "stock_receive": "stock_edit", "stock_write_off": "stock_edit",
    "stock_inventory": "stock_edit", "save_norms": "stock_edit",
    "equipment_list": ("equipment", "stock_view"), "equipment": ("equipment", "stock_view"),
    "save_equipment": "equipment", "equipment_event": "equipment", "write_off_equipment": "equipment",
    # fiscal receipts
    "fiscal_status": ("fiscal", "cash_report", "payments"), "fiscal_receipts": ("fiscal", "cash_report"),
    "fiscal_receipt": ("fiscal", "cash_report", "payments"), "fiscal_open_shift": "fiscal", "fiscal_close_shift": "fiscal",
    "fiscal_x_report": "fiscal", "fiscal_retry": ("fiscal", "payments"), "fiscal_refund": "fiscal",
    "fiscal_for_payment": ("fiscal", "payments"), "fiscal_settings": ("settings", "fiscal"),
    "fiscal_save_settings": "settings", "fiscal_check": ("settings", "fiscal"),
    # reports and accounting
    "report_revenue": ("reports", "accounting"), "report_visits": "reports", "report_debts": ("reports", "accounting"),
    "acc_summary": "accounting", "expenses": "accounting", "save_expense": "accounting", "delete_expense": "accounting",
    "salary_schemes": "accounting", "save_salary_scheme": "accounting", "payroll": "accounting", "pay_salary": "accounting",
    # marketing
    "mk_summary": "marketing", "mk_sources": ("marketing", "patients_view", "patients_edit"), "save_mk_sources": "marketing",
    "mk_sources_report": "marketing", "call_list": "marketing", "log_call": "marketing",
    "set_patient_marketing": ("marketing", "patients_edit"),
    # work schedules
    "shifts_month": ("schedule_view", "shifts_edit", "staff"), "save_shift": "shifts_edit", "fill_shifts": "shifts_edit",
    "clear_shifts": "shifts_edit",
}

# Changes worth keeping in the action journal, with a human label.
AUDITED = {
    "save_visit": "Запись на приём", "set_visit_status": "Статус приёма", "revert_visit": "Отмена изменения записи",
    "save_visit_series": "Повторяющиеся записи", "cancel_series": "Отмена серии записей",
    "waitlist_save": "Лист ожидания", "waitlist_done": "Запись из листа ожидания", "waitlist_remove": "Удаление из листа ожидания",
    "reminder_template_save": "Текст напоминания о визите",
    "create_patient": "Новый пациент", "add_note": "Примечание", "delete_note": "Удаление примечания",
    "save_record": "Лечение в медкарте", "delete_record": "Удаление лечения",
    "save_template": "Шаблон", "delete_template": "Удаление шаблона", "reset_template": "Сброс шаблона",
    "save_document": "Документ", "delete_document": "Удаление документа",
    "save_service": "Услуга в прайсе", "delete_service": "Удаление услуги", "import_services": "Импорт прайса",
    "save_invoice": "Счёт / план", "delete_invoice": "Удаление счёта", "plan_to_invoice": "Счёт по плану",
    "set_plan_status": "Статус плана", "add_payment": "Оплата", "delete_payment": "Удаление оплаты",
    "mark_transferred": "Отметка переноса в DP", "retry_push": "Повтор отправки в DP", "force_push": "Отправка в DP несмотря на двойную запись",
    "save_settings": "Настройки", "test_connection": "Проверка подключения", "save_clinic": "Реквизиты клиники",
    "backup_now": "Резервная копия вручную", "backup_settings_save": "Настройки резервных копий",
    "backup_restore": "Восстановление базы из резервной копии",
    "save_material": "Материал в справочнике", "delete_material": "Удаление материала", "save_supplier": "Поставщик",
    "delete_supplier": "Удаление поставщика", "stock_receive": "Приход на склад", "stock_write_off": "Списание материалов",
    "stock_inventory": "Инвентаризация", "save_norms": "Нормы списания по услуге",
    "save_equipment": "Оборудование", "equipment_event": "Обслуживание оборудования",
    "write_off_equipment": "Списание оборудования",
    "fiscal_open_shift": "Открытие смены на кассе", "fiscal_close_shift": "Закрытие смены (Z-отчёт)",
    "fiscal_x_report": "X-отчёт", "fiscal_retry": "Повтор чека", "fiscal_refund": "Чек возврата",
    "fiscal_for_payment": "Чек по оплате", "fiscal_save_settings": "Настройки кассы",
    "save_expense": "Расход", "delete_expense": "Удаление расхода", "save_salary_scheme": "Схема оплаты сотрудника",
    "pay_salary": "Выплата зарплаты", "save_mk_sources": "Источники пациентов", "log_call": "Звонок пациенту",
    "set_patient_marketing": "Источник пациента", "save_shift": "Смена в графике", "fill_shifts": "Заполнение графика",
    "clear_shifts": "Очистка графика",
    "dictate": "Диктовка в медкарту", "speech_download": "Скачивание модели речи", "ai_settings_save": "Настройки ИИ",
}

SESSION_IDLE = timedelta(hours=12)
PBKDF2_ROUNDS = 240_000
MAX_FAILS, LOCK_SECONDS = 5, 60


class AuthError(Exception):
    """Wrong credentials, expired session or missing permission. `code` is the HTTP status."""

    def __init__(self, message, code=401):
        super().__init__(message)
        self.code = code


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, want = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(dk.hex(), want)
    except (ValueError, AttributeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _clean_login(login) -> str:
    return str(login or "").strip().lower()


def _check_new_password(pw):
    pw = str(pw or "")
    if len(pw) < 6:
        raise AuthError("Пароль должен быть не короче 6 символов", 400)
    return pw


class Auth:
    def __init__(self, db):
        self.db = db
        db.conn.executescript(SCHEMA)
        db.conn.commit()
        self._fails: dict[str, list] = {}
        self._flock = threading.Lock()

    # ------------------------------------------------------------- helpers --
    def has_users(self) -> bool:
        return bool(self.db.one("SELECT 1 AS x FROM users LIMIT 1"))

    @staticmethod
    def effective_perms(user: dict) -> list[str]:
        if user.get("role") == "director":
            return list(PERM_KEYS)
        if user.get("perms"):
            try:
                custom = json.loads(user["perms"])
                return [p for p in custom if p in PERM_KEYS]
            except ValueError:
                pass
        return list(ROLES.get(user.get("role"), {}).get("perms", []))

    def public_user(self, u: dict) -> dict:
        return {"id": u["id"], "login": u["login"], "name": u["name"], "position": u.get("position") or "",
                "role": u.get("role") or "", "role_title": ROLES.get(u.get("role") or "", {}).get("title", ""),
                "status": u["status"], "doctor_id": u.get("doctor_id"), "custom_perms": bool(u.get("perms")),
                "perms": self.effective_perms(u), "created_at": u.get("created_at"), "last_login": u.get("last_login")}

    def log(self, user, action, detail="", ip=""):
        uid = user["id"] if user else None
        name = user["name"] if user else ""
        with self.db.tx() as c:
            c.execute("INSERT INTO audit(at, user_id, user_name, action, detail, ip) VALUES(?,?,?,?,?,?)",
                      (_now(), uid, name, action, str(detail)[:500], ip))

    def _throttle(self, key):
        with self._flock:
            t = [x for x in self._fails.get(key, []) if time.time() - x < LOCK_SECONDS]
            self._fails[key] = t
            if len(t) >= MAX_FAILS:
                raise AuthError(f"Слишком много неудачных попыток. Подождите {LOCK_SECONDS} секунд.", 429)

    def _fail(self, key):
        with self._flock:
            self._fails.setdefault(key, []).append(time.time())

    def _new_session(self, user, ip, agent):
        token = secrets.token_urlsafe(32)
        now = _now()
        with self.db.tx() as c:
            c.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?)", (_token_hash(token), user["id"], now, now, ip, agent[:200]))
            c.execute("UPDATE users SET last_login=? WHERE id=?", (now, user["id"]))
            # forget sessions idle for longer than allowed
            c.execute("DELETE FROM sessions WHERE last_seen < ?", ((datetime.now() - SESSION_IDLE).strftime("%Y-%m-%d %H:%M:%S"),))
        return token

    # -------------------------------------------------------------- public --
    def state(self, token, is_local):
        user = self.user_for(token, touch=False) if token else None
        import config
        return {"brand": config.BRAND, "version": config.VERSION,
                "has_users": self.has_users(), "can_bootstrap": not self.has_users() and is_local,
                "user": self.public_user(user) if user else None,
                "roles": [{"key": k, "title": v["title"], "perms": v["perms"]} for k, v in ROLES.items()],
                "perm_list": [{"key": k, "title": t} for k, t in PERMS]}

    def bootstrap(self, f, ip, agent, is_local):
        """First start: the person at the server computer creates the director account."""
        if self.has_users():
            raise AuthError("Учётная запись директора уже создана. Войдите или подайте заявку.", 403)
        if not is_local:
            raise AuthError("Первую учётную запись (директора) можно создать только на компьютере-сервере.", 403)
        login, name = _clean_login(f.get("login")), str(f.get("name") or "").strip()
        if not login or not name:
            raise AuthError("Укажите имя и логин", 400)
        pw = _check_new_password(f.get("password"))
        with self.db.tx() as c:
            c.execute("INSERT INTO users(login, name, position, role, pass_hash, status, created_at, approved_at) "
                      "VALUES(?,?,?,?,?,?,?,?)", (login, name, str(f.get("position") or "Директор"), "director",
                                                  hash_password(pw), "active", _now(), _now()))
        user = self.db.one("SELECT * FROM users WHERE login=?", (login,))
        self.log(user, "Создана учётная запись директора", ip=ip)
        return {"token": self._new_session(user, ip, agent), "user": self.public_user(user)}

    def register(self, f, ip):
        if not self.has_users():
            raise AuthError("Сначала на компьютере-сервере нужно создать учётную запись директора.", 403)
        login, name = _clean_login(f.get("login")), str(f.get("name") or "").strip()
        if not login or not name:
            raise AuthError("Укажите ФИО и логин", 400)
        if len(login) < 3 or any(ch.isspace() for ch in login):
            raise AuthError("Логин: от 3 символов, без пробелов", 400)
        pw = _check_new_password(f.get("password"))
        self._throttle("reg:" + ip)
        if self.db.one("SELECT 1 AS x FROM users WHERE login=?", (login,)):
            self._fail("reg:" + ip)
            raise AuthError("Такой логин уже занят", 409)
        wanted = f.get("role") if f.get("role") in ROLES and f.get("role") != "director" else ""
        with self.db.tx() as c:
            c.execute("INSERT INTO users(login, name, position, role, pass_hash, status, created_at) VALUES(?,?,?,?,?,?,?)",
                      (login, name, str(f.get("position") or "").strip(), wanted, hash_password(pw), "pending", _now()))
        user = self.db.one("SELECT * FROM users WHERE login=?", (login,))
        self.log(user, "Заявка на регистрацию", f"{name}, {f.get('position') or ''}", ip)
        return {"ok": True, "message": "Заявка отправлена. Войти можно будет после одобрения директором."}

    def login(self, login, password, ip, agent):
        login = _clean_login(login)
        key = f"{login}|{ip}"
        self._throttle(key)
        u = self.db.one("SELECT * FROM users WHERE login=?", (login,))
        if not u or not check_password(str(password or ""), u["pass_hash"]):
            self._fail(key)
            self.log(None, "Неудачный вход", login, ip)
            raise AuthError("Неверный логин или пароль")
        if u["status"] == "pending":
            raise AuthError("Заявка ещё не одобрена директором", 403)
        if u["status"] != "active":
            raise AuthError("Учётная запись заблокирована. Обратитесь к директору.", 403)
        self.log(u, "Вход", ip=ip)
        return {"token": self._new_session(u, ip, agent), "user": self.public_user(u)}

    def logout(self, token):
        user = self.user_for(token, touch=False)
        with self.db.tx() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token or ""),))
        if user:
            self.log(user, "Выход")
        return True

    def user_for(self, token, touch=True):
        if not token:
            return None
        th = _token_hash(token)
        s = self.db.one("SELECT * FROM sessions WHERE token_hash=?", (th,))
        if not s:
            return None
        if datetime.strptime(s["last_seen"], "%Y-%m-%d %H:%M:%S") < datetime.now() - SESSION_IDLE:
            with self.db.tx() as c:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
            return None
        u = self.db.one("SELECT * FROM users WHERE id=?", (s["user_id"],))
        if not u or u["status"] != "active":
            return None
        if touch:
            with self.db.tx() as c:
                c.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (_now(), th))
        return u

    def require(self, token, method):
        """Return the user allowed to call `method`, or raise AuthError."""
        user = self.user_for(token)
        if not user:
            raise AuthError("Войдите в программу заново")
        need = METHOD_PERMS.get(method)
        if need is None:
            raise AuthError("Действие недоступно", 403)
        if need == ANY_USER:
            return user
        perms = set(self.effective_perms(user))
        needs = need if isinstance(need, tuple) else (need,)
        if not perms.intersection(needs):
            raise AuthError("Недостаточно прав для этого действия. Обратитесь к директору.", 403)
        return user

    def change_password(self, user, old, new):
        if not check_password(str(old or ""), user["pass_hash"]):
            raise AuthError("Текущий пароль указан неверно", 400)
        pw = _check_new_password(new)
        with self.db.tx() as c:
            c.execute("UPDATE users SET pass_hash=? WHERE id=?", (hash_password(pw), user["id"]))
        self.log(user, "Смена пароля")
        return True

    # ---------------------------------------------------- staff management --
    def staff_list(self):
        return [self.public_user(u) for u in self.db.q(
            "SELECT * FROM users ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 ELSE 2 END, name")]

    def _directors_left(self, except_id):
        return self.db.one("SELECT COUNT(*) AS n FROM users WHERE role='director' AND status='active' AND id<>?",
                           (except_id,))["n"]

    def staff_save(self, actor, f):
        uid = int(f.get("id") or 0)
        u = self.db.one("SELECT * FROM users WHERE id=?", (uid,))
        if not u:
            raise AuthError("Сотрудник не найден", 404)
        role = f.get("role", u["role"])
        if role not in ROLES:
            raise AuthError("Выберите роль", 400)
        status = f.get("status", u["status"])
        if status not in ("active", "blocked", "pending"):
            raise AuthError("Неизвестный статус", 400)
        if u["role"] == "director" and (role != "director" or status != "active") and not self._directors_left(uid):
            raise AuthError("В программе должен остаться хотя бы один директор", 400)
        perms = f.get("perms")
        perms_json = json.dumps([p for p in perms if p in PERM_KEYS]) if isinstance(perms, list) and role != "director" else None
        approved = u["status"] == "pending" and status == "active"
        with self.db.tx() as c:
            c.execute("UPDATE users SET name=?, position=?, role=?, perms=?, status=?, doctor_id=?, "
                      "approved_at=COALESCE(?, approved_at), approved_by=COALESCE(?, approved_by) WHERE id=?",
                      (str(f.get("name") or u["name"]).strip(), str(f.get("position", u["position"]) or "").strip(), role,
                       perms_json, status, f.get("doctor_id") or None,
                       _now() if approved else None, actor["id"] if approved else None, uid))
            if status != "active":
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        what = "Заявка одобрена" if approved else "Блокировка" if status == "blocked" else "Изменены права сотрудника"
        self.log(actor, what, f"{u['name']} → {ROLES[role]['title']}", "")
        return self.public_user(self.db.one("SELECT * FROM users WHERE id=?", (uid,)))

    def staff_reject(self, actor, uid):
        u = self.db.one("SELECT * FROM users WHERE id=?", (int(uid),))
        if not u or u["status"] != "pending":
            raise AuthError("Заявка не найдена", 404)
        with self.db.tx() as c:
            c.execute("DELETE FROM users WHERE id=?", (u["id"],))
        self.log(actor, "Заявка отклонена", u["name"])
        return True

    def staff_reset_password(self, actor, uid, new):
        u = self.db.one("SELECT * FROM users WHERE id=?", (int(uid),))
        if not u:
            raise AuthError("Сотрудник не найден", 404)
        pw = _check_new_password(new)
        with self.db.tx() as c:
            c.execute("UPDATE users SET pass_hash=? WHERE id=?", (hash_password(pw), u["id"]))
            c.execute("DELETE FROM sessions WHERE user_id=?", (u["id"],))
        self.log(actor, "Сброс пароля", u["name"])
        return True

    def audit_list(self, day=None, user_id=None, limit=500):
        sql, args = "SELECT * FROM audit WHERE 1=1", []
        if day:
            sql += " AND substr(at,1,10)=?"
            args.append(day)
        if user_id:
            sql += " AND user_id=?"
            args.append(int(user_id))
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        return self.db.q(sql, args)
