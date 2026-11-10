"""Staff accounts: registration requests, director approval, password login, roles and permissions.

Passwords are stored as PBKDF2-SHA256 hashes with a per-user salt. Session tokens are random and
only their SHA-256 is kept in the database, so a copied database file does not let anyone log in.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
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
CREATE TABLE IF NOT EXISTS staff_roles(
    key TEXT PRIMARY KEY, title TEXT, base TEXT, perms TEXT, known TEXT, sort INTEGER DEFAULT 0, updated_at TEXT);
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
    ("reports", "Отчёты и экран директора: выручка, загрузка, план"),
    ("accounting", "Бухгалтерия: расходы, зарплата, прибыль"),
    ("marketing", "CRM: заявки, задачи, обзвон, рассылки, отзывы, источники"),
    ("shifts_edit", "Графики работы: составление"),
    ("transfer", "Перенос в Dentist Plus"),
    ("refs", "Шаблоны, прайс, реквизиты"),
    ("fiscal", "Касса: чеки, смены, X- и Z-отчёты, возвраты"),
    ("stock_view", "Склад: просмотр остатков"),
    ("stock_edit", "Склад: приход, списание, инвентаризация"),
    ("equipment", "Оборудование: учёт, обслуживание, списание"),
    ("sterilization", "Журнал стерилизации"),
    ("lab", "Лаборатория: заказ-наряды"),
    ("settings", "Настройки и подключение к Dentist Plus"),
    ("staff", "Сотрудники, права и журнал действий"),
    # 2.14
    ("expenses_day", "Расходы за день: вносить и видеть только сегодняшние"),
    ("export", "Выгрузка таблиц в Excel"),
]
PERM_KEYS = [k for k, _ in PERMS]
PERM_KEYS_2_13 = PERM_KEYS[:PERM_KEYS.index("expenses_day")]   # what a permission list saved before 2.14 knew about
# groups for the director's checkboxes («Должности» in «Сотрудники»)
PERM_GROUPS = [
    ("Расписание и пациенты", ["schedule_view", "schedule_edit", "patients_view", "patients_edit", "transfer"]),
    ("Медкарта и документы", ["medcard_view", "medcard_edit", "docs", "lab", "sterilization"]),
    ("Деньги", ["billing", "payments", "cash_report", "fiscal", "expenses_day"]),
    ("Управление", ["reports", "accounting", "marketing", "shifts_edit", "export"]),
    ("Склад", ["stock_view", "stock_edit", "equipment"]),
    ("Настройки", ["refs", "settings", "staff"]),
]

ROLES = {
    "director": {"title": "Директор", "perms": PERM_KEYS},
    "admin": {"title": "Администратор", "perms": [
        "schedule_view", "schedule_edit", "patients_view", "patients_edit", "medcard_view", "docs",
        "billing", "payments", "cash_report", "fiscal", "transfer", "refs", "stock_view", "stock_edit",
        "marketing", "shifts_edit", "sterilization", "lab", "expenses_day", "export"]},
    "doctor": {"title": "Врач", "perms": [
        "schedule_view", "patients_view", "patients_edit", "medcard_view", "medcard_edit", "docs", "billing", "stock_view",
        "sterilization", "lab", "export"]},
    "assistant": {"title": "Ассистент", "perms": ["schedule_view", "patients_view", "medcard_view", "stock_view", "sterilization", "export"]},
    "storekeeper": {"title": "Кладовщик", "perms": ["stock_view", "stock_edit", "equipment", "export"]},
}
BASE_ROLES = [k for k in ROLES if k != "director"]   # a position the director makes is built on one of these
_DB = {"db": None}   # the clinic database, for positions the director changed (set by Auth)


def _loads(v, default):
    try:
        x = json.loads(v) if v else default
        return x if isinstance(x, type(default)) else default
    except (TypeError, ValueError):
        return default


def _merge(saved: list, known: list, default: list) -> list:
    """Saved permissions + what appeared after they were saved (taken from the default of the role)."""
    return [p for p in PERM_KEYS if p in saved or (p not in known and p in default)]


def roles(db=None) -> dict:
    """Every position: {key: {'title', 'base', 'perms', 'builtin', 'edited', 'sort'}}. Built-in ones come from the code
    until the director changes them; the director's own positions come from `staff_roles` (synced between laptops)."""
    db = db or _DB["db"]
    out = {k: {"title": v["title"], "base": k, "perms": list(v["perms"]), "builtin": True, "edited": False, "sort": i}
           for i, (k, v) in enumerate(ROLES.items())}
    rows = []
    if db is not None:
        try:
            rows = db.q("SELECT * FROM staff_roles ORDER BY sort, title")
        except Exception:  # noqa: BLE001 — a database without the table (old tests)
            rows = []
    for r in rows:
        key = r["key"]
        if key == "director":
            continue
        base = key if key in ROLES else (r["base"] if r["base"] in BASE_ROLES else "assistant")
        default = ROLES[base]["perms"]
        perms = _merge(_loads(r["perms"], []), _loads(r["known"], PERM_KEYS_2_13), default)
        out[key] = {"title": (r["title"] or "").strip() or ROLES.get(key, {}).get("title", key), "base": base, "perms": perms,
                    "builtin": key in ROLES, "edited": True, "sort": (r["sort"] or 0) + (0 if key in ROLES else 100)}
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["sort"], kv[1]["title"])))


def role_base(key) -> str:
    """The built-in role a position stands on (voices, «doctor» in the schedule): 'admin', 'doctor', …"""
    r = roles().get(str(key or ""))
    return r["base"] if r else str(key or "")

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
    "templates": ("docs", "medcard_edit", "refs"), "save_template": "refs", "delete_template": "refs", "reset_template": "refs", "restore_templates": "refs",
    "doc_context": "docs", "save_document": "docs", "document": "docs", "delete_document": "docs",
    "services": ("billing", "refs", "docs"), "save_service": "refs", "delete_service": "refs", "import_services": "refs",
    "invoice": ("billing", "payments"), "save_invoice": "billing", "delete_invoice": "billing",
    "plan_to_invoice": "billing", "set_plan_status": "billing", "plan_choose": "billing", "plan_pdf": ("billing", "docs"),
    "add_payment": "payments", "delete_payment": "payments", "cash_day": "cash_report",
    "allergy_check": ("medcard_view", "medcard_edit", "billing", "patients_view"),
    "steril_options": ("sterilization", "equipment"), "steril_list": ("sterilization", "equipment"),
    "steril_save": "sterilization", "steril_delete": "sterilization",
    "lab_options": ("lab", "billing", "accounting"), "lab_orders": ("lab", "billing", "accounting"), "lab_order": ("lab", "billing", "accounting"),
    "lab_summary": ("lab", "billing", "accounting"), "lab_save": "lab", "lab_status": "lab", "labs_save": "lab", "lab_pay": "accounting",
    "loyalty_settings": ("settings", "payments", "billing"), "loyalty_settings_save": "settings",
    "cert_sell": "payments", "cert_info": ("payments", "billing"), "cert_list": ("payments", "cash_report", "accounting"), "cert_cancel": "accounting",
    "bonus_info": ("payments", "billing", "patients_view"), "bonus_adjust": "settings",
    "family_save": ("patients_edit", "payments"), "family_leave": ("patients_edit", "payments"),
    "sbp_settings": ("payments", "settings"), "sbp_settings_save": "settings", "sbp_to_tablet": "payments",    "taxcert_data": ("payments", "cash_report", "docs"), "taxcert_issue": ("payments", "docs"), "taxcert_list": ("payments", "cash_report", "docs"),
    "export_xlsx": "export",  # 2.14: a right of its own (was open to everyone)
    "document_signatures": ("docs", "medcard_view", "patients_view"), "document_sign": "docs",
    "questionnaire_questions": ("patients_view", "docs", "patients_edit"), "questionnaire_save": ("patients_edit", "docs", "medcard_edit"),
    "questionnaire_latest": ("patients_view", "medcard_view"),
    "tablet_code": "settings", "tablets_list": ("settings", "docs", "patients_edit"), "tablet_revoke": "settings",
    "tablet_send": ("docs", "patients_edit"), "tablet_status": ("docs", "patients_edit"), "tablet_cancel": ("docs", "patients_edit"),
    "files_list": ("medcard_view", "patients_view"), "file_thumbs": ("medcard_view", "patients_view"),
    "file_get": ("medcard_view", "patients_view"), "file_add": ("medcard_edit", "patients_edit"),
    "file_update": ("medcard_edit", "patients_edit"), "file_delete": "medcard_edit",
    "files_inbox": ("medcard_edit", "patients_edit"), "files_inbox_import": ("medcard_edit", "patients_edit"),
    "files_settings": ("settings", "medcard_edit", "patients_edit"), "files_settings_save": "settings",
    "perio_list": "medcard_view", "perio_get": "medcard_view", "perio_save": "medcard_edit", "perio_delete": "medcard_edit",
    "perio_parse": "medcard_edit", "perio_voice": "medcard_edit",
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
    # 2.13 AI: the assistant checks the rights of every question itself (the same rights as the screens)
    "local_ai_custom": "settings", "local_ai_eval": "settings",
    "assistant_ask": ANY_USER, "assistant_voice": ANY_USER, "ai_langs": ANY_USER,
    "ai_write": ("docs", "medcard_edit"), "ai_plan_variant": "billing",
    "ai_translate": ("docs", "marketing", "medcard_edit", "patients_edit"),
    "medcheck_patient": ("medcard_view", "patients_view"), "medcheck_record": ("medcard_edit", "medcard_view"),
    "director_weekly": "reports", "teeth_voice": "medcard_edit", "teeth_parse": "medcard_edit",
    "voice_note": ("patients_edit", "marketing"), "note_parse": ("patients_edit", "marketing"),
    "consent_get": ("patients_view", "medcard_view", "medcard_edit"), "consent_give": ("medcard_edit", "patients_edit"),
    "consent_revoke": ("medcard_edit", "patients_edit"),
    # 2.14: expenses of the day and the day report by e-mail
    "day_expenses": ("expenses_day", "accounting"), "day_expense_save": ("expenses_day", "accounting"),
    "day_expense_delete": ("expenses_day", "accounting"), "day_report": ("expenses_day", "accounting", "cash_report"),
    "day_report_send": ("expenses_day", "accounting", "cash_report"), "day_report_settings": "settings",
    "day_report_settings_save": "settings",
    "day_report_tg_check": "settings", "day_report_tg_chats": "settings",  # 2.14.1: the report in Telegram
    # stock and equipment
    "stock_summary": ("stock_view", "equipment"), "materials": ("stock_view", "stock_edit"),
    "material": ("stock_view", "stock_edit"), "stock_moves": ("stock_view", "stock_edit"),
    "stock_docs": ("stock_view", "stock_edit"), "stock_doc": ("stock_view", "stock_edit"),
    "suppliers": ("stock_view", "stock_edit"), "norms": ("stock_view", "stock_edit", "refs"),
    "save_material": "stock_edit", "delete_material": "stock_edit", "save_supplier": "stock_edit",
    "delete_supplier": "stock_edit", "stock_receive": "stock_edit", "stock_write_off": "stock_edit",
    "stock_inventory": "stock_edit", "save_norms": "stock_edit",
    "stock_lots": ("stock_view", "stock_edit"), "stock_expired": ("stock_view", "stock_edit"),
    "purchase_list": ("stock_view", "stock_edit"), "stock_scan": ("stock_view", "stock_edit"),
    "equipment_list": ("equipment", "stock_view"), "equipment": ("equipment", "stock_view"),
    "save_equipment": "equipment", "equipment_event": "equipment", "write_off_equipment": "equipment",
    # money 2.12: advance, refunds, installments, memberships, cash shifts, insurance (ДМС)
    "money_patient": ("payments", "billing", "patients_view"), "deposit_use": "payments", "refund": "payments",
    "schedule": ("payments", "billing"), "schedule_draft": ("payments", "billing"), "schedule_save": ("payments", "billing"),
    "schedule_delete": ("payments", "billing"), "overdue_payments": ("reports", "accounting", "payments", "marketing"),
    "membership_types": ("payments", "billing", "refs"), "membership_type_save": ("refs", "accounting"),
    "membership_type_delete": ("refs", "accounting"), "membership_sell": "billing",
    "memberships": ("payments", "billing", "patients_view"), "membership_cancel": "accounting",
    "cash_shift": ("cash_report", "payments"), "cash_shift_open": "payments", "cash_move": "payments",
    "cash_shift_close": "payments", "cash_shifts": ("cash_report", "accounting"), "cash_shift_info": ("cash_report", "accounting"),
    "insurers": ("billing", "payments", "accounting", "patients_view"), "insurer_save": ("accounting", "refs"),
    "ins_docs": ("billing", "payments", "patients_view"), "ins_doc_save": ("patients_edit", "billing"),
    "ins_doc_delete": ("patients_edit", "billing"), "ins_summary": ("accounting", "reports"), "ins_candidates": "accounting",
    "registry_make": "accounting", "registry": "accounting", "registry_status": "accounting", "registry_pay": "accounting",
    "registry_delete": "accounting", "registry_xlsx": "accounting",
    # fiscal receipts
    "fiscal_status": ("fiscal", "cash_report", "payments"), "fiscal_receipts": ("fiscal", "cash_report"),
    "fiscal_receipt": ("fiscal", "cash_report", "payments"), "fiscal_open_shift": "fiscal", "fiscal_close_shift": "fiscal",
    "fiscal_x_report": "fiscal", "fiscal_retry": ("fiscal", "payments"), "fiscal_refund": "fiscal",
    "fiscal_for_payment": ("fiscal", "payments"), "fiscal_settings": ("settings", "fiscal"),
    "fiscal_save_settings": "settings", "fiscal_check": ("settings", "fiscal"),
    # reports and accounting
    "report_revenue": ("reports", "accounting"), "report_visits": "reports", "report_debts": ("reports", "accounting"),
    "director_dashboard": "reports", "report_patients": "reports", "report_load": "reports", "report_conversion": "reports",
    "report_materials": ("reports", "accounting"), "kpi": "reports", "kpi_save": "reports",
    "director_settings": "reports", "director_settings_save": "reports",
    "acc_summary": "accounting", "expenses": "accounting", "save_expense": "accounting", "delete_expense": "accounting",
    "salary_schemes": "accounting", "save_salary_scheme": "accounting", "payroll": "accounting", "pay_salary": "accounting",
    # marketing
    "mk_summary": "marketing", "mk_sources": ("marketing", "patients_view", "patients_edit"), "save_mk_sources": "marketing",
    "mk_sources_report": "marketing", "call_list": "marketing", "log_call": "marketing",
    "set_patient_marketing": ("marketing", "patients_edit"),
    # CRM: requests, tasks, segments, after-visit survey
    "crm_summary": "marketing", "crm_tasks": "marketing", "crm_task_save": "marketing", "crm_task_done": "marketing",
    "crm_task_reopen": "marketing", "crm_task_delete": "marketing", "crm_leads": "marketing", "crm_lead": "marketing",
    "crm_lead_save": "marketing", "crm_lead_stage": "marketing", "crm_lead_link": "marketing",
    "crm_lead_patient": ("marketing", "patients_edit"), "crm_match": ("marketing", "patients_view"),
    "crm_funnel": ("marketing", "reports"), "crm_segments": "marketing", "crm_segment_run": "marketing",
    "crm_segment_save": "marketing", "crm_segment_delete": "marketing", "crm_settings": "marketing", "crm_settings_save": "marketing",
    "crm_review_save": "marketing", "crm_review_delete": "marketing", "crm_reviews": ("marketing", "reports"),
    "crm_review_queue": "marketing", "crm_patient": "marketing",
    # work schedules
    "shifts_month": ("schedule_view", "shifts_edit", "staff"), "save_shift": "shifts_edit", "fill_shifts": "shifts_edit",
    "clear_shifts": "shifts_edit",
    # SaaS platform: cloud sync, updates, moving a base in (director-only actions are checked again in Api)
    "cloud_status": "settings", "cloud_join": "settings", "cloud_sync": "settings", "cloud_code": "settings",
    "cloud_leave": "settings", "cloud_revoke": "settings", "cloud_conflicts": "settings",
    "cloud_conflict_seen": "settings", "cloud_conflict_restore": "settings",
    "update_status": ANY_USER, "update_check": "settings", "update_download": "settings", "update_install": "settings",
    "import_preview": "settings", "import_run": "settings", "import_dp_all": "settings",
}

# Changes worth keeping in the action journal, with a human label.
AUDITED = {
    "save_visit": "Запись на приём", "set_visit_status": "Статус приёма", "revert_visit": "Отмена изменения записи",
    "lab_save": "Заказ-наряд в лабораторию", "lab_status": "Статус заказ-наряда", "labs_save": "Лаборатория в справочнике",
    "lab_pay": "Оплата лаборатории", "loyalty_settings_save": "Настройки бонусов и сертификатов", "cert_sell": "Продажа сертификата",
    "cert_cancel": "Аннулирование сертификата", "bonus_adjust": "Ручное изменение бонусов", "family_save": "Семья пациента",
    "family_leave": "Выход из семьи", "sbp_settings_save": "QR-код СБП",    "taxcert_issue": "Справка для налогового вычета", "export_xlsx": "Выгрузка таблицы в Excel",
    "document_sign": "Подпись документа", "questionnaire_save": "Анкета о здоровье",
    "tablet_code": "Код подключения планшета", "tablet_revoke": "Отключение планшета", "tablet_send": "Задание на планшет",
    "file_add": "Файл в карте пациента", "file_update": "Описание файла пациента", "file_delete": "Удаление файла пациента",
    "files_inbox_import": "Снимки из визиографа в карту", "files_settings_save": "Папка снимков визиографа",
    "perio_save": "Пародонтограмма", "perio_delete": "Удаление пародонтограммы",
    "steril_save": "Цикл стерилизации", "steril_delete": "Удаление цикла стерилизации",
    "save_visit_series": "Повторяющиеся записи", "cancel_series": "Отмена серии записей",
    "waitlist_save": "Лист ожидания", "waitlist_done": "Запись из листа ожидания", "waitlist_remove": "Удаление из листа ожидания",
    "reminder_template_save": "Текст напоминания о визите",
    "create_patient": "Новый пациент", "add_note": "Примечание", "delete_note": "Удаление примечания",
    "save_record": "Лечение в медкарте", "delete_record": "Удаление лечения",
    "save_template": "Шаблон", "delete_template": "Удаление шаблона", "reset_template": "Сброс шаблона",
    "restore_templates": "Возврат встроенных шаблонов",
    "save_document": "Документ", "delete_document": "Удаление документа",
    "save_service": "Услуга в прайсе", "delete_service": "Удаление услуги", "import_services": "Импорт прайса",
    "save_invoice": "Счёт / план", "delete_invoice": "Удаление счёта", "plan_to_invoice": "Счёт по плану",
    "set_plan_status": "Статус плана", "plan_choose": "Выбор варианта плана", "add_payment": "Оплата", "delete_payment": "Удаление оплаты",
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
    "cloud_join": "Подключение к облаку клиники", "cloud_code": "Показан код подключения к облаку",
    "cloud_leave": "Отключение от облака", "cloud_revoke": "Отключение компьютера клиники от облака",
    "cloud_conflict_restore": "Возврат значения после синхронизации", "update_download": "Скачивание обновления",
    "update_install": "Установка обновления программы", "import_run": "Перенос пациентов из файла",
    "import_dp_all": "Загрузка всех пациентов из Dentist Plus",
    "kpi_save": "План на месяц", "director_settings_save": "Число кресел для загрузки",
    "crm_task_save": "Задача CRM", "crm_task_done": "Задача CRM выполнена", "crm_task_reopen": "Задача CRM снова открыта",
    "crm_task_delete": "Удаление задачи CRM", "crm_lead_save": "Заявка", "crm_lead_stage": "Этап заявки",
    "crm_lead_link": "Заявка связана с пациентом", "crm_lead_patient": "Пациент из заявки",
    "crm_segment_save": "Сегмент пациентов", "crm_segment_delete": "Удаление сегмента", "crm_settings_save": "Настройки CRM",
    "crm_review_save": "Оценка визита", "crm_review_delete": "Удаление оценки визита",
    "deposit_use": "Оплата счёта из аванса", "refund": "Возврат денег пациенту", "schedule_save": "График платежей (рассрочка)",
    "schedule_delete": "Удаление графика платежей", "membership_type_save": "Вид абонемента",
    "membership_type_delete": "Вид абонемента убран из продажи", "membership_sell": "Продажа абонемента",
    "membership_cancel": "Аннулирование абонемента", "cash_shift_open": "Открытие кассовой смены",
    "cash_move": "Внесение или изъятие денег из кассы", "cash_shift_close": "Закрытие кассовой смены",
    "insurer_save": "Страховая компания", "ins_doc_save": "Полис или гарантийное письмо ДМС",
    "ins_doc_delete": "Удаление полиса или гарантийного письма", "registry_make": "Реестр для страховой",
    "registry_status": "Реестр отправлен в страховую", "registry_pay": "Оплата реестра страховой",
    "registry_delete": "Удаление реестра", "registry_xlsx": "Реестр для страховой в Excel",
    "local_ai_custom": "Модель клиники для ИИ на компьютере", "consent_give": "Согласие пациента на запись приёма",
    "consent_revoke": "Отзыв согласия на запись приёма", "teeth_voice": "Зубная формула голосом",
    "day_expense_save": "Расход за день", "day_expense_delete": "Удаление расхода за день",
    "day_report_send": "Отчёт за день отправлен на почту", "day_report_settings_save": "Настройки отчёта за день на почту",
}

SESSION_IDLE = timedelta(hours=12)
PBKDF2_ROUNDS = 240_000
MAX_FAILS, LOCK_SECONDS = 5, 60
PIN_MAX_FAILS = 5


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
        _DB["db"] = db
        db.conn.executescript(SCHEMA)
        have = {r[1] for r in db.conn.execute("PRAGMA table_info(users)")}
        for col in ("pin_hash TEXT", "pin_fails INTEGER DEFAULT 0"):  # quick sign-in on a shared computer
            if col.split()[0] not in have:
                db.conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
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
        role = roles().get(user.get("role") or "") or {"perms": []}
        if user.get("perms"):
            try:
                v = json.loads(user["perms"]) if isinstance(user["perms"], str) else None
            except ValueError:
                v = None
            if isinstance(v, list):           # saved before 2.14: a plain list
                return _merge(v, PERM_KEYS_2_13, role["perms"])
            if isinstance(v, dict):
                return _merge(v.get("perms") or [], v.get("known") or PERM_KEYS_2_13, role["perms"])
        return list(role["perms"])

    def public_user(self, u: dict) -> dict:
        return {"id": u["id"], "login": u["login"], "name": u["name"], "position": u.get("position") or "",
                "role": u.get("role") or "", "role_title": (roles().get(u.get("role") or "") or {}).get("title", ""),
                "status": u["status"], "doctor_id": u.get("doctor_id"), "custom_perms": bool(u.get("perms")),
                "has_pin": bool(u.get("pin_hash")),
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
                "has_pins": bool(self.db.one("SELECT 1 AS x FROM users WHERE status='active' AND pin_hash IS NOT NULL LIMIT 1")),
                "user": self.public_user(user) if user else None,
                "roles": [{"key": k, "title": v["title"], "perms": v["perms"], "base": v["base"], "builtin": v["builtin"]}
                          for k, v in roles().items()],
                "perm_list": [{"key": k, "title": t} for k, t in PERMS],
                "perm_groups": [{"title": t, "keys": keys} for t, keys in PERM_GROUPS]}

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
        wanted = f.get("role") if f.get("role") in roles() and f.get("role") != "director" else ""
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
        if u.get("pin_fails"):
            with self.db.tx() as c:
                c.execute("UPDATE users SET pin_fails=0 WHERE id=?", (u["id"],))
        return {"token": self._new_session(u, ip, agent), "user": self.public_user(u)}

    # ------------------------------------------------------------ PIN code --
    def pin_users(self):
        """Who can sign in with a PIN on this computer: names only, for the tiles of the sign-in screen."""
        return [{"id": u["id"], "name": u["name"], "position": u.get("position") or (roles().get(u.get("role") or "") or {}).get("title", ""),
                 "locked": (u.get("pin_fails") or 0) >= PIN_MAX_FAILS}
                for u in self.db.q("SELECT * FROM users WHERE status='active' AND pin_hash IS NOT NULL ORDER BY name")]

    def pin_login(self, uid, pin, ip, agent):
        key = f"pin|{ip}"
        self._throttle(key)
        try:
            u = self.db.one("SELECT * FROM users WHERE id=?", (int(uid),))
        except (TypeError, ValueError):
            u = None
        if not u or u["status"] != "active" or not u.get("pin_hash"):
            raise AuthError("Для этого сотрудника вход по ПИН-коду не включён — войдите по паролю")
        if (u.get("pin_fails") or 0) >= PIN_MAX_FAILS:
            raise AuthError(f"ПИН-код заблокирован после {PIN_MAX_FAILS} ошибок. Войдите по логину и паролю — ПИН снова заработает.", 403)
        if not check_password(str(pin or ""), u["pin_hash"]):
            self._fail(key)
            with self.db.tx() as c:
                c.execute("UPDATE users SET pin_fails=COALESCE(pin_fails,0)+1 WHERE id=?", (u["id"],))
            left = PIN_MAX_FAILS - (u.get("pin_fails") or 0) - 1
            self.log(None, "Неверный ПИН-код", u["name"], ip)
            raise AuthError("Неверный ПИН-код" + (f". Осталось попыток: {left}" if left > 0 else
                                                  ". ПИН заблокирован — войдите по логину и паролю"))
        with self.db.tx() as c:
            c.execute("UPDATE users SET pin_fails=0 WHERE id=?", (u["id"],))
        self.log(u, "Вход по ПИН-коду", ip=ip)
        return {"token": self._new_session(u, ip, agent), "user": self.public_user(u)}

    def set_pin(self, user, password, pin):
        if not check_password(str(password or ""), user["pass_hash"]):
            raise AuthError("Пароль указан неверно", 400)
        pin = str(pin or "").strip()
        if not re.fullmatch(r"\d{4,6}", pin):
            raise AuthError("ПИН-код — от 4 до 6 цифр", 400)
        if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
            raise AuthError("Слишком простой ПИН-код (одинаковые цифры или подряд) — выберите другой", 400)
        with self.db.tx() as c:
            c.execute("UPDATE users SET pin_hash=?, pin_fails=0 WHERE id=?", (hash_password(pin), user["id"]))
        self.log(user, "Установлен ПИН-код")
        return True

    def clear_pin(self, user):
        with self.db.tx() as c:
            c.execute("UPDATE users SET pin_hash=NULL, pin_fails=0 WHERE id=?", (user["id"],))
        self.log(user, "ПИН-код отключён")
        return True

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
        all_roles = roles()
        if role not in all_roles:
            raise AuthError("Выберите должность", 400)
        status = f.get("status", u["status"])
        if status not in ("active", "blocked", "pending"):
            raise AuthError("Неизвестный статус", 400)
        if u["role"] == "director" and (role != "director" or status != "active") and not self._directors_left(uid):
            raise AuthError("В программе должен остаться хотя бы один директор", 400)
        perms = f.get("perms")
        perms_json = (json.dumps({"perms": [p for p in perms if p in PERM_KEYS], "known": PERM_KEYS})
                      if isinstance(perms, list) and role != "director" else None)
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
        self.log(actor, what, f"{u['name']} → {all_roles[role]['title']}", "")
        return self.public_user(self.db.one("SELECT * FROM users WHERE id=?", (uid,)))

    # ----------------------------------------------- 2.14: positions and their rights --
    def roles_list(self):
        rs = roles(self.db)
        n = {r["role"]: r["n"] for r in self.db.q("SELECT role, COUNT(*) AS n FROM users WHERE status<>'blocked' GROUP BY role")}
        return {"roles": [{"key": k, **v, "people": n.get(k, 0), "default": ROLES.get(v["base"], {}).get("perms", []),
                           "locked": k == "director"} for k, v in rs.items()],
                "perm_list": [{"key": k, "title": t} for k, t in PERMS],
                "perm_groups": [{"title": t, "keys": keys} for t, keys in PERM_GROUPS], "bases": BASE_ROLES}

    def role_save(self, actor, f):
        """The director changes what a position may see and do, or makes a new one («Старший администратор»)."""
        f = f or {}
        key = str(f.get("key") or "").strip()
        if key == "director":
            raise AuthError("У директора все права — их нельзя изменить", 400)
        rs = roles(self.db)
        title = str(f.get("title") or "").strip()[:60]
        if key and key not in rs:
            raise AuthError("Должность не найдена", 404)
        if not title:
            raise AuthError("Напишите название должности", 400)
        if any(v["title"].lower() == title.lower() and k != key for k, v in rs.items()):
            raise AuthError("Такая должность уже есть", 400)
        base = key if key in ROLES else (f.get("base") if f.get("base") in BASE_ROLES else (rs.get(key) or {}).get("base") or "")
        if base not in BASE_ROLES:
            raise AuthError("Выберите, на какую роль похожа должность", 400)
        perms = [p for p in (f.get("perms") or []) if p in PERM_KEYS]
        if key and key == (actor or {}).get("role") and "staff" not in perms:
            raise AuthError("Нельзя убрать у своей должности право «Сотрудники» — иначе вы не сможете вернуть его", 400)
        new = not key
        key = key or "p_" + secrets.token_hex(4)
        sort = int(f.get("sort") or 0) if str(f.get("sort") or "0").lstrip("-").isdigit() else 0
        with self.db.tx() as c:
            c.execute("""INSERT INTO staff_roles(key, title, base, perms, known, sort, updated_at) VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(key) DO UPDATE SET title=excluded.title, base=excluded.base, perms=excluded.perms,
                         known=excluded.known, sort=excluded.sort, updated_at=excluded.updated_at""",
                      (key, title, base, json.dumps(perms), json.dumps(PERM_KEYS), sort, _now()))
        self.log(actor, "Новая должность" if new else "Изменены права должности", f"{title}: {len(perms)} прав")
        return {"key": key, **roles(self.db)[key]}

    def role_reset(self, actor, key):
        """A built-in position back to what the program gives it by default."""
        key = str(key or "")
        if key not in ROLES or key == "director":
            raise AuthError("Вернуть можно только встроенную должность", 400)
        with self.db.tx() as c:
            c.execute("DELETE FROM staff_roles WHERE key=?", (key,))
        self.log(actor, "Права должности как в программе", ROLES[key]["title"])
        return {"key": key, **roles(self.db)[key]}

    def role_delete(self, actor, key):
        key = str(key or "")
        rs = roles(self.db)
        if key not in rs or key in ROLES:
            raise AuthError("Удалить можно только свою должность", 400)
        n = self.db.one("SELECT COUNT(*) AS n FROM users WHERE role=?", (key,))["n"]
        if n:
            raise AuthError(f"На этой должности {n} сотр. — сначала переведите их на другую", 400)
        with self.db.tx() as c:
            c.execute("DELETE FROM staff_roles WHERE key=?", (key,))
        self.log(actor, "Удалена должность", rs[key]["title"])
        return True

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
