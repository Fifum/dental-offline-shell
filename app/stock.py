"""Stock of materials and the clinic's equipment.

Materials: every change of quantity is a row in stock_moves (receipt +, write-off −, inventory ±),
so the balance is always SUM(qty) and the history explains every number. Services can carry
consumption norms; billing a service writes the materials off automatically (and editing or
deleting the invoice puts them back).

Equipment: a register with inventory numbers, location, service history and a write-off act.

3.5 места хранения: the main stock plus cabinets and branches (`stock_locations`). Every move belongs to one place
(`stock_moves.location_id`, empty — the main stock), so the balance of a place is the sum of its moves and the clinic's balance
is still the sum of all moves. A transfer is a document with two moves (− there, + here); lots and expiry stay clinic-wide.

3.10 медсестра и амортизация: materials and equipment may carry a photo (`photo_id` — a row of `patient_files` owned by
«_stock», so the picture travels to the other computers like an X-ray); equipment has a straight-line depreciation (the cost
less the salvage value over the useful life, from the month after it was put into service, until it is written off).
Requests and write-offs waiting for approval are in stock_flow.py.

2.14.1 «без документа»: a receipt bought without an invoice, a write-off without an act or a stock count may be marked
`stock_docs.nodoc = 1`. The stock itself is always the real one (everything); «по документам» is the balance of the
documented moves only (plus services and starting balances) — seen with the «Бухгалтерия» right, for the accountant.
"""
from __future__ import annotations

import calendar
import json
import math
import re
import uuid
from datetime import date, datetime, timedelta
from urllib.parse import quote, unquote

import barcodes

SCHEMA = """
CREATE TABLE IF NOT EXISTS materials(
    id TEXT PRIMARY KEY, code TEXT, name TEXT, unit TEXT, category TEXT, min_qty REAL DEFAULT 0,
    price REAL DEFAULT 0, barcode TEXT, comment TEXT, active INTEGER DEFAULT 1, created_at TEXT);
CREATE TABLE IF NOT EXISTS suppliers(
    id TEXT PRIMARY KEY, name TEXT, phone TEXT, inn TEXT, comment TEXT, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS stock_docs(
    id TEXT PRIMARY KEY, kind TEXT, number TEXT, date TEXT, supplier_id TEXT, reason TEXT, comment TEXT,
    total REAL DEFAULT 0, user_name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS stock_moves(
    id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, qty REAL, price REAL DEFAULT 0, kind TEXT,
    doc_id TEXT, invoice_id TEXT, patient_id TEXT, reason TEXT, user_name TEXT, at TEXT);
CREATE INDEX IF NOT EXISTS ix_moves_mat ON stock_moves(material_id);
CREATE INDEX IF NOT EXISTS ix_moves_inv ON stock_moves(invoice_id);
CREATE TABLE IF NOT EXISTS service_materials(
    service_id TEXT, material_id TEXT, qty REAL, PRIMARY KEY(service_id, material_id));
CREATE TABLE IF NOT EXISTS equipment(
    id TEXT PRIMARY KEY, inv_number TEXT, name TEXT, category TEXT, model TEXT, serial TEXT,
    location TEXT, responsible TEXT, purchase_date TEXT, price REAL DEFAULT 0, warranty_until TEXT,
    next_service TEXT, status TEXT DEFAULT 'in_use', comment TEXT, created_at TEXT,
    writeoff_date TEXT, writeoff_reason TEXT, writeoff_act TEXT, writeoff_commission TEXT, residual REAL);
CREATE TABLE IF NOT EXISTS equipment_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, equipment_id TEXT, kind TEXT, date TEXT, text TEXT,
    cost REAL DEFAULT 0, user_name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS stock_lots(
    id INTEGER PRIMARY KEY AUTOINCREMENT, material_id TEXT, move_id INTEGER, lot TEXT, expires TEXT,
    qty REAL, created_at TEXT);
CREATE INDEX IF NOT EXISTS ix_lots_mat ON stock_lots(material_id);
CREATE TABLE IF NOT EXISTS stock_locations(
    id TEXT PRIMARY KEY, name TEXT, kind TEXT, branch_id TEXT, chair TEXT, active INTEGER DEFAULT 1, sort INTEGER DEFAULT 0,
    comment TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS stock_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS equipment_docs(
    id TEXT PRIMARY KEY, equipment_id TEXT, kind TEXT, title TEXT, file_id TEXT, created_by TEXT, created_at TEXT,
    deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_eqdocs_eq ON equipment_docs(equipment_id);
CREATE TABLE IF NOT EXISTS stock_orders(
    id TEXT PRIMARY KEY, number TEXT, supplier_id TEXT, date TEXT, expected TEXT, lines TEXT, received TEXT, status TEXT,
    total REAL DEFAULT 0, comment TEXT, doc_ids TEXT, user_name TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_sorders_status ON stock_orders(status);
CREATE TABLE IF NOT EXISTS material_docs(
    id TEXT PRIMARY KEY, material_id TEXT, kind TEXT, title TEXT, file_id TEXT, created_by TEXT, created_at TEXT,
    deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_matdocs_mat ON material_docs(material_id);
CREATE TABLE IF NOT EXISTS material_analogs(
    id TEXT PRIMARY KEY, a TEXT, b TEXT, created_by TEXT, created_at TEXT, deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS equipment_receipts(
    id TEXT PRIMARY KEY, number TEXT, supplier_id TEXT, doc_kind TEXT, doc_number TEXT, doc_date TEXT, amount REAL DEFAULT 0,
    comment TEXT, lines TEXT, step INTEGER DEFAULT 1, status TEXT, equipment_ids TEXT, pay TEXT, user_name TEXT,
    created_at TEXT, updated_at TEXT, accepted_at TEXT);
CREATE TABLE IF NOT EXISTS equipment_moves(
    id TEXT PRIMARY KEY, number TEXT, equipment_id TEXT, from_location_id TEXT, from_text TEXT, to_location_id TEXT, date TEXT,
    reason TEXT, responsible TEXT, comment TEXT, status TEXT, created_by TEXT, created_name TEXT, created_at TEXT,
    approved_by TEXT, approved_name TEXT, approved_at TEXT, answer TEXT, done_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_eqmoves_eq ON equipment_moves(equipment_id);
CREATE TABLE IF NOT EXISTS equipment_requests(
    id TEXT PRIMARY KEY, number TEXT, equipment_id TEXT, kind TEXT, description TEXT, priority TEXT, due TEXT,
    responsible TEXT, plan_id TEXT, status TEXT, cost REAL DEFAULT 0, result TEXT, created_by TEXT, created_name TEXT,
    created_at TEXT, started_at TEXT, done_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_eqreq_eq ON equipment_requests(equipment_id);
CREATE TABLE IF NOT EXISTS equipment_plans(
    id TEXT PRIMARY KEY, equipment_id TEXT, kind TEXT, every_months INTEGER DEFAULT 12, next_date TEXT, note TEXT,
    active INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS equipment_purchases(
    id TEXT PRIMARY KEY, number TEXT, name TEXT, reason TEXT, justification TEXT, category TEXT, budget REAL DEFAULT 0,
    year INTEGER, quarter INTEGER, priority TEXT, funding TEXT, replace_id TEXT, offers TEXT, status TEXT,
    created_by TEXT, created_name TEXT, created_at TEXT, sent_at TEXT, decided_by TEXT, decided_name TEXT, decided_at TEXT,
    answer TEXT, receipt_id TEXT, updated_at TEXT);
"""
SOON_DAYS = 30          # a lot expiring within this many days is highlighted
USAGE_DAYS = 60         # the average daily use for the purchase list is taken over this period
MIN_DAYS_LEFT = 14      # a material that lasts fewer days goes into the purchase list
EXPIRED_REASON = "Истёк срок годности"

MOVE_KINDS = {"receipt": "Приход", "writeoff": "Списание", "service": "По услуге", "inventory": "Инвентаризация",
              "return": "Возврат поставщику", "transfer": "Перемещение"}
MAIN = "Основной склад"   # the place of every move without a location (all of them before 3.5)
LOC_KINDS = {"store": "Склад", "cabinet": "Кабинет", "branch": "Филиал"}
EQ_STATUS = {"in_use": "В работе", "repair": "В ремонте", "storage": "На складе", "written_off": "Списано"}
EQ_EVENTS = {"service": "Обслуживание", "repair": "Ремонт", "move": "Перемещение", "note": "Заметка",
             "writeoff": "Списание", "status": "Статус", "inventory": "Инвентаризация", "replace_plan": "План замены",
             "disposal": "Выбытие", "doc": "Документ", "condition": "Состояние", "created": "Поставлено на учёт",
             "diag": "Диагностика",
             # 3.16 «Журнал действий»: a change of a card, of the references or settings, a request, the purchase plan
             "edit": "Редактирование", "settings": "Изменение параметров", "request": "Создание заявки", "purchase": "План закупок"}
# 3.13 «карточка оборудования»
EQ_OWNERSHIP = {"own": "Собственность клиники", "lease": "Аренда", "leasing": "Лизинг", "owner": "Имущество учредителя",
                "doctor": "Имущество врача", "other": "Иное пользование"}   # 3.15: the doctors' own and any other use
EQ_CONDITION = {"ok": "Исправно", "service": "Требует обслуживания", "faulty": "Неисправно"}
EQ_DISPOSAL = {"writeoff": "Списание", "utilize": "Утилизация", "sale": "Реализация (продажа)", "transfer": "Передача",
               "return": "Возврат владельцу"}   # 3.15: utilization and a transfer as ways of their own
EQ_DISPOSED = {"writeoff": "Списано", "utilize": "Утилизировано", "sale": "Продано", "transfer": "Передано",
               "return": "Возвращено владельцу"}
EQ_DOC_KINDS = {"contract": "Договор купли-продажи", "waybill": "Товарная накладная", "act": "Акт ввода в эксплуатацию",
                "passport": "Технический паспорт", "reg": "Регистрационное удостоверение", "warranty": "Гарантийный талон",
                "service_act": "Акты ТО", "photo": "Фотографии",
                # 3.16 «Документы» (mockup 13)
                "lease_contract": "Договор аренды или лизинга", "service_contract": "Договор на обслуживание",
                "manual": "Инструкция по эксплуатации", "cert": "Сертификат соответствия", "license": "Лицензия или разрешение",
                "report": "Отчёт или заключение", "other": "Другое"}
EQ_DOC_MAIN = ["contract", "waybill", "act", "passport", "reg", "warranty", "service_act", "photo"]   # «Документы (n/8)»
# 3.16: the categories of the section «Документы» (the photos live in the card's gallery, not here)
EQ_DOC_CATS = {"contracts": ("Договоры", ("contract", "lease_contract", "service_contract", "waybill")),
               "acts": ("Акты", ("act", "service_act")), "passports": ("Паспорта / инструкции", ("passport", "manual")),
               "certs": ("Сертификаты", ("cert", "reg")), "warranty": ("Гарантии", ("warranty",)),
               "licenses": ("Лицензии / разрешения", ("license",)), "reports": ("Отчёты и заключения", ("report",)),
               "other": ("Прочие", ("other",))}
EQ_DOC_COLS_316 = ("number TEXT", "doc_date TEXT", "valid_until TEXT", "counterparty TEXT", "archived INTEGER DEFAULT 0", "updated_at TEXT")
DOC_SOON_DAYS = 30
# the money of a piece of equipment: only someone with «Бухгалтерия» sees it, and only they may change it
EQ_MONEY = ("price", "salvage", "market_value", "replace_cost", "reserve_monthly", "disposal_amount", "residual")
EQ_NEW_COLS = ("manufacturer TEXT", "ownership TEXT", "condition TEXT", "location_id TEXT", "market_value REAL",
               "replace_cost REAL", "replace_date TEXT", "reserve_monthly REAL", "disposal_kind TEXT", "disposal_amount REAL")
CHAIR_HOURS = 154       # working hours of a chair in a month, for «амортизация на кресло-час»
INV_FIRST = "ОБ-001"
UNITS = ["шт", "уп", "мл", "г", "фл", "амп", "карп", "набор", "пара", "м"]
AMORT_METHODS = {"linear": "Линейный"}
# 3.14: rented equipment and the founder's own property are not the clinic's assets: no depreciation and no disposal in the P&L
OFF_BOOKS = ("lease", "owner", "doctor", "other")
CAPEX_DAYS = 45         # an expense this close to the purchase, of the same sum, looks like the purchase itself
MAX_USEFUL_MONTHS = 600  # 50 years
# 3.15 «Оборудование» by the clinic's mockups: the categories of property and the useful life usual for them (a hint in the
# card, never put in by itself: the term is only set by hand), the way a piece is accounted for, the journals
EQ_CATS = ["Стоматологическое оборудование", "Диагностическое оборудование", "Стерилизационное оборудование",
           "Инженерное оборудование", "Медицинские инструменты", "Компьютерная техника", "Оргтехника", "Мебель",
           "Бытовая техника", "Электрооборудование", "Системы безопасности", "Хозяйственный инвентарь", "Прочее имущество"]
EQ_LIFE = {"Стоматологическое оборудование": 120, "Диагностическое оборудование": 96, "Стерилизационное оборудование": 84,
           "Инженерное оборудование": 84, "Медицинские инструменты": 36, "Компьютерная техника": 36, "Оргтехника": 36,
           "Мебель": 84, "Бытовая техника": 60, "Электрооборудование": 60, "Системы безопасности": 60,
           "Хозяйственный инвентарь": 24, "Прочее имущество": 60}
# the category never decides the accounting: a cheap instrument may be counted by quantity without depreciation
EQ_ACCOUNTING = {"amort": "С амортизацией", "qty": "Количественный учёт без амортизации"}
EQ_NEW_COLS_315 = ("accounting TEXT", "contractor TEXT", "use_start TEXT", "use_end TEXT", "contract_no TEXT", "receipt_id TEXT",
                   "responsible_login TEXT", "qty INTEGER DEFAULT 1", "disposal_responsible TEXT", "disposal_basis TEXT")
RECEIPT_DOCS = {"contract": "Договор поставки", "waybill": "Товарная накладная", "invoice": "Счёт-фактура", "upd": "УПД"}
RECEIPT_STEPS = {1: "Документы", 2: "Оборудование", 3: "Учёт", 4: "Ввод в эксплуатацию"}
RECEIPT_STATUS = {"process": "В процессе", "accepted": "Принято", "cancelled": "Отменено"}
MOVE_STATUS = {"requested": "На утверждении", "approved": "Утверждено", "moving": "Перемещается", "done": "Завершено",
               "rejected": "Отклонено", "cancelled": "Отменено"}
MOVE_REASONS = ["Перераспределение нагрузки", "Оптимизация работы", "Ремонт кабинета", "Временное размещение",
                "Замена рабочего места", "Ввод в эксплуатацию", "На ремонт или обслуживание"]
REQ_KINDS = {"repair": "Ремонт", "service": "Обслуживание", "diag": "Диагностика"}
REQ_PREFIX = {"repair": "Р", "service": "ТО", "diag": "Д"}
REQ_STATUS = {"new": "Новая", "work": "В работе", "done": "Выполнено", "cancelled": "Отменено"}
PRIORITY = {"low": "Низкий", "mid": "Средний", "high": "Высокий"}
PLAN_KINDS = {"service": "Плановое ТО", "verify": "Поверка", "check": "Технический осмотр"}
PURCHASE_STATUS = {"draft": "Черновик", "pending": "На согласовании", "approved": "Согласовано", "rejected": "Отклонено",
                   "bought": "Куплено"}
FUNDING = {"own": "Собственные средства", "credit": "Кредит", "leasing": "Лизинг", "other": "Другое"}
# 3.14 «карточка материала»: its own number (МТ-0001, as the equipment's inventory number), the details of the mockup,
# the orders to suppliers («в пути»), the documents and photos, the analogs
MAT_FIRST = "МТ-0001"
MAT_NEW_COLS = ("number TEXT", "manufacturer TEXT", "description TEXT", "form TEXT", "shelf_life TEXT", "storage TEXT",
                "opt_qty REAL DEFAULT 0", "lead_days INTEGER DEFAULT 0", "supplier_id TEXT")
MAT_TEXT = {"manufacturer": 120, "description": 200, "form": 120, "shelf_life": 80, "storage": 200}
MAT_DOC_KINDS = {"reg": "Регистрационное удостоверение", "cert": "Сертификат или декларация", "manual": "Инструкция",
                 "msds": "Паспорт безопасности", "waybill": "Накладная", "photo": "Фото", "other": "Другое"}
ORDER_STATUS = {"ordered": "Заказан", "partial": "Получен частично", "received": "Получен", "cancelled": "Отменён"}
ORDER_OPEN = ("ordered", "partial")
REQ_OPEN = ("new", "accepted", "partial")   # stock_flow.OPEN: the cabinets' requests still to be issued — the reserve
# 3.16 «Справочники и настройки» (mockup 10): the module's settings, which really change what the program does, and the
# references of the clinic's own (the defaults below until the clinic changes them; kept in `stock_settings`)
EQ_MODULE = {"method": "linear", "round": "rub", "control_to": True, "to_days": 14, "to_report": True,
             "no_doc_disposal": False, "third_party": True}
EQ_ROUND = {"rub": "До рублей", "kop": "До копеек"}
EQ_WORKS = [{"name": "Технический осмотр", "kind": "service"}, {"name": "Чистка и смазка наконечников", "kind": "service"},
            {"name": "Замена фильтров", "kind": "service"}, {"name": "Дезинфекция водной системы установки", "kind": "service"},
            {"name": "Калибровка", "kind": "diag"}, {"name": "Проверка электробезопасности", "kind": "diag"},
            {"name": "Замена изношенных частей", "kind": "repair"}, {"name": "Ремонт электроники", "kind": "repair"}]
EQ_REGS = [{"name": "ТО стоматологической установки", "kind": "service", "every_months": 6, "category": "Стоматологическое оборудование",
            "checklist": ["Давление воздуха и воды", "Чистка фильтров и сеток", "Смазка наконечников и шлангов",
                          "Педаль, светильник, кресло", "Дезинфекция водной системы", "Нет утечек воды и воздуха"]},
           {"name": "ТО автоклава", "kind": "service", "every_months": 6, "category": "Стерилизационное оборудование",
            "checklist": ["Чистка камеры и уплотнителя двери", "Клапаны и датчики", "Вакуумный тест", "Замена фильтров",
                          "Контроль индикаторами"]},
           {"name": "ТО компрессора", "kind": "service", "every_months": 12, "category": "Инженерное оборудование",
            "checklist": ["Слив конденсата", "Замена воздушных фильтров", "Осушитель", "Рабочее давление", "Шум и вибрация"]},
           {"name": "Поверка средств измерений", "kind": "verify", "every_months": 12, "category": "Диагностическое оборудование",
            "checklist": ["Свидетельство о поверке", "Пломбы и маркировка", "Запись в паспорте"]}]
EQ_DISP_REASONS = ["Непригодно к эксплуатации", "Сильный износ", "Неисправно, ремонт экономически нецелесообразен", "Морально устарело",
                   "Утеряно или похищено", "Повреждено (авария, залив, пожар)", "Окончание договора аренды или лизинга"]
EQ_REFS_KEYS = ("eq_categories", "eq_life", "eq_models", "eq_groups", "eq_works", "eq_regs", "eq_disp_reasons", "eq_module")
# the fields of a card whose change the log shows «было → стало» (3.16 «Журнал действий»); kind: d — a date, m — money,
# n — months, a dict — the titles of codes
EQ_DIFF = [("inv_number", "Инвентарный номер", ""), ("name", "Наименование", ""), ("category", "Категория", ""),
           ("manufacturer", "Производитель", ""), ("model", "Модель", ""), ("serial", "Серийный номер", ""),
           ("responsible", "Ответственный", ""), ("purchase_date", "Дата покупки", "d"), ("warranty_until", "Гарантия до", "d"),
           ("next_service", "Следующее ТО", "d"), ("comment", "Примечание", ""), ("ownership", "Принадлежность", EQ_OWNERSHIP),
           ("accounting", "Способ учёта", EQ_ACCOUNTING), ("contractor", "Владелец или контрагент", ""), ("contract_no", "Договор", ""),
           ("use_start", "Начало использования", "d"), ("use_end", "Окончание использования", "d"), ("qty", "Количество", ""),
           ("replace_date", "Плановая замена", "d"), ("in_service", "Дата ввода в эксплуатацию", "d"), ("useful_months", "Срок службы", "n"),
           ("price", "Стоимость", "m"), ("salvage", "Ликвидационная стоимость", "m"), ("market_value", "Рыночная стоимость", "m"),
           ("replace_cost", "Стоимость замены", "m"), ("reserve_monthly", "Резерв на обновление", "m")]
EQ_PAST = ("price", "salvage", "useful_months", "in_service")  # changing them changes the depreciation of past months


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _num(v, name="Количество"):
    try:
        x = float(str(v).replace(",", ".").replace(" ", "")) if v not in (None, "") else 0.0
    except ValueError:
        raise ValueError(f"{name}: введите число") from None
    return round(x, 3)


def _clean(s, n=300):
    return str(s or "").strip()[:n]


def _fmt_val(v, kind):
    """3.16: a value of a card's field as the log shows it."""
    if v in (None, ""):
        return "—"
    if kind == "d":
        s = str(v)[:10]
        return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if len(s) == 10 else s
    if kind == "m":
        x = round(float(v or 0), 2)
        s = f"{x:,.2f}".replace(",", " ").replace(".00", "").replace(".", ",")
        return f"{s} ₽"
    if kind == "n":
        n = int(v or 0)
        if not n:
            return "—"
        if n % 12:
            return f"{n} мес."
        y = n // 12
        return f"{y} {'год' if y % 10 == 1 and y % 100 != 11 else 'года' if 2 <= y % 10 <= 4 and not 12 <= y % 100 <= 14 else 'лет'}"
    if isinstance(kind, dict):
        return kind.get(v, str(v))
    return str(v)


def eq_changes(old, new):
    """3.16: what changed in a card: [{f, t, old, new, m}] (m — money: hidden from someone without «Бухгалтерия»)."""
    out = []
    for f, t, kind in EQ_DIFF:
        a, b = old.get(f), new.get(f)
        if kind == "m" or f in ("qty", "useful_months"):
            same = round(float(a or 0), 2) == round(float(b or 0), 2)
        else:
            same = str(a or "") == str(b or "")
        if not same:
            out.append({"f": f, "t": t, "old": _fmt_val(a, kind), "new": _fmt_val(b, kind), "m": kind == "m"})
    return out


def _day(v, name="Годен до"):
    """A date from the form: 2027-03-31, 31.03.2027 or a month only (2027-03, 03.2027 → its last day)."""
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif (m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s)):
        y, mo, d = int(m[3]), int(m[2]), int(m[1])
    elif (m := re.fullmatch(r"(\d{4})-(\d{1,2})", s)) or (m := re.fullmatch(r"(\d{1,2})\.(\d{4})", s)):
        y, mo = (int(m[1]), int(m[2])) if "-" in s else (int(m[2]), int(m[1]))
        d = calendar.monthrange(y, mo)[1] if 1 <= mo <= 12 else 0
    else:
        raise ValueError(f"{name}: укажите дату, например 31.12.2027")
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        raise ValueError(f"{name}: такой даты нет") from None


GS = "\x1d"  # GS1 group separator (FNC1) that scanners send between variable-length fields
_GS1_FIXED = {"00": 18, "01": 14, "02": 14, "11": 6, "13": 6, "15": 6, "17": 6}
_GS1_VAR = ("10", "21", "240", "91", "92", "93")


def parse_scan(code):
    """What a scanner typed: a plain EAN/UPC/internal code, or a GS1 code (DataMatrix «Честный знак», GS1-128)
    with the GTIN, the lot (10) and the expiry date (17, YYMMDD). Returns {code, barcode, gtin, lot, expires}."""
    raw = str(code or "").strip().replace("\\x1d", GS).replace("<GS>", GS)
    for pre in ("]d2", "]C1", "]Q3", "]e0"):  # symbology identifiers some scanners prefix
        if raw.startswith(pre):
            raw = raw[len(pre):]
    out = {"code": raw.replace(GS, ""), "barcode": raw.replace(GS, ""), "gtin": "", "lot": "", "expires": ""}
    s = raw.replace("(", GS).replace(")", "") if raw.startswith("(") else raw
    s = s.lstrip(GS)
    if not (s.startswith("01") and len(s) >= 16 and s[2:16].isdigit()):
        return out
    i, fields = 0, {}
    while i < len(s):
        if s[i] == GS:
            i += 1
            continue
        ai = s[i:i + 2]
        if ai in _GS1_FIXED:
            n = _GS1_FIXED[ai]
            fields[ai] = s[i + 2:i + 2 + n]
            i += 2 + n
            continue
        ai = next((a for a in _GS1_VAR if s.startswith(a, i)), None)
        if not ai:
            break
        end = s.find(GS, i)
        end = len(s) if end < 0 else end
        fields[ai] = s[i + len(ai):end]
        i = end
    gtin = fields.get("01", "")
    out.update(gtin=gtin, barcode=gtin[1:] if gtin.startswith("0") else gtin, lot=fields.get("10", "")[:60])
    exp = fields.get("17", "")
    if len(exp) == 6 and exp.isdigit():
        y, mo, d = 2000 + int(exp[:2]), int(exp[2:4]), int(exp[4:])
        if d == 0 and 1 <= mo <= 12:  # «00» in GS1 means the end of the month
            d = calendar.monthrange(y, mo)[1]
        try:
            out["expires"] = date(y, mo, d).isoformat()
        except ValueError:
            pass
    return out


def _jl(v, default):
    try:
        x = json.loads(v) if v else default
        return x if isinstance(x, type(default)) else default
    except (TypeError, ValueError):
        return default


def _mon(day):
    """'2026-11-18' or '2026-11' → month index (year * 12 + month − 1); '' → None."""
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", str(day or "")[:10])
    return int(m[1]) * 12 + int(m[2]) - 1 if m else None


def _mon_str(k):
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def amortization(e, month=None):
    """Straight-line depreciation of one piece of equipment as of `month` ('YYYY-MM', default — this month, inclusive).

    The cost less the salvage value is spread evenly over the useful life, from the month after the date it was put into
    service (or bought); a written-off piece is not depreciated after the month of the write-off. The sum of k months is
    rounded once (not k rounded months), so the last month takes the kopecks and the total is exactly the base."""
    cost = round(float(e.get("price") or 0), 2)
    n = int(e.get("useful_months") or 0)
    start = _mon(e.get("in_service") or e.get("purchase_date"))
    out = {"on": False, "cost": cost, "method": e.get("amort_method") or "linear", "useful_months": n,
           "salvage": round(float(e.get("salvage") or 0), 2), "in_service": e.get("in_service") or e.get("purchase_date") or "",
           "monthly": 0.0, "accumulated": 0.0, "residual": cost, "months_done": 0, "months_left": 0, "first": "", "last": "",
           "percent": 0.0, "done": False, "stopped": ""}
    if e.get("accounting") == "qty":  # 3.15: counted by quantity, without depreciation
        out["qty"] = True
        return out
    if not (cost > 0 and n > 0 and start is not None):
        return out
    base = max(0.0, cost - min(out["salvage"], cost))
    first, last = start + 1, start + n
    stop = _mon(e.get("writeoff_date")) if e.get("status") == "written_off" else None
    now = _mon(month) if month else _mon(date.today().isoformat())
    upto = min(last, now, stop if stop is not None else last)
    k = max(0, upto - first + 1)
    acc = round(base * k / n, 2)
    out.update(on=True, monthly=round(base / n, 2), accumulated=acc, residual=round(cost - acc, 2), months_done=k,
               months_left=max(0, n - k) if stop is None else 0, first=_mon_str(first), last=_mon_str(last),
               percent=round(acc * 100 / base, 1) if base else 100.0, done=k >= n,
               stopped=_mon_str(stop) if stop is not None else "")
    return out


def amort_charge(e, month):
    """Depreciation of one piece for one month ('YYYY-MM'): the difference of the totals at its end and the month before."""
    k = _mon(month)
    if k is None:
        return 0.0
    a, b = amortization(e, _mon_str(k)), amortization(e, _mon_str(k - 1))
    return round(a["accumulated"] - b["accumulated"], 2) if a["on"] else 0.0


def amort_schedule(e):
    """Every month of the useful life (up to the write-off): charge, total so far and book value."""
    a = amortization(e)
    if not a["on"]:
        return []
    out, prev = [], 0.0
    base = max(0.0, a["cost"] - min(a["salvage"], a["cost"]))
    first, last = _mon(a["first"]), _mon(a["last"])
    stop = _mon(a["stopped"]) if a["stopped"] else None
    for k in range(first, last + 1):
        if stop is not None and k > stop:
            break
        acc = round(base * (k - first + 1) / a["useful_months"], 2)
        out.append({"month": _mon_str(k), "charge": round(acc - prev, 2), "accumulated": acc, "residual": round(a["cost"] - acc, 2)})
        prev = acc
    return out


def on_books(e) -> bool:
    """3.14: the piece is the clinic's own (or in leasing) — its depreciation and disposal go into the P&L."""
    return (e.get("ownership") or "own") not in OFF_BOOKS and e.get("accounting") != "qty"


def amort_month(db, month):
    """3.10: depreciation of all the equipment for one month ('YYYY-MM') — a line of the P&L (3.14: the clinic's own only)."""
    return round(sum(amort_charge(e, month) for e in db.q("SELECT * FROM equipment") if on_books(e)), 2)


def amort_month_detail(db, month):
    """3.14: the depreciation of one month by piece, the largest first — the detail of the P&L line."""
    out = [{"name": f"{e['name']}{' (' + e['inv_number'] + ')' if e['inv_number'] else ''}", "amount": amort_charge(e, month)}
           for e in db.q("SELECT * FROM equipment") if on_books(e)]
    return sorted([x for x in out if x["amount"]], key=lambda x: -x["amount"])


def disposal_month(db, month):
    """3.14: the equipment that left the clinic in the month ('YYYY-MM'): its book value at the disposal less what it was sold
    for — the P&L line «Выбытие оборудования» (a sale above the book value makes it negative: a gain)."""
    out = []
    for e in db.q("""SELECT * FROM equipment WHERE status='written_off' AND substr(COALESCE(writeoff_date,''),1,7)=?
                     ORDER BY writeoff_date, name""", (str(month or "")[:7],)):
        if not on_books(e):
            continue
        residual = e["residual"] if e["residual"] is not None else amortization(e)["residual"]
        sale = (e["disposal_amount"] or 0) if e.get("disposal_kind") == "sale" else 0
        out.append({"id": e["id"], "inv_number": e["inv_number"], "name": e["name"], "kind": e.get("disposal_kind") or "writeoff",
                    "date": e["writeoff_date"], "residual": round(residual or 0, 2), "sale": round(sale, 2),
                    "amount": round((residual or 0) - sale, 2)})
    return out


class Stock:
    def __init__(self, db):
        self.db = db
        with db._lock:  # В1: raw schema statements never interleave with another thread's transaction
            db.conn.executescript(SCHEMA)
            if "nodoc" not in {r[1] for r in db.conn.execute("PRAGMA table_info(stock_docs)")}:  # 2.14.1: without a document
                db.conn.execute("ALTER TABLE stock_docs ADD COLUMN nodoc INTEGER DEFAULT 0")
            dcols = {r[1] for r in db.conn.execute("PRAGMA table_info(stock_docs)")}
            for col in ("location_id TEXT", "to_location_id TEXT"):  # 3.5: where a document took or put the materials
                if col.split()[0] not in dcols:
                    db.conn.execute(f"ALTER TABLE stock_docs ADD COLUMN {col}")
            if "location_id" not in {r[1] for r in db.conn.execute("PRAGMA table_info(stock_moves)")}:  # 3.5: the place of a move
                db.conn.execute("ALTER TABLE stock_moves ADD COLUMN location_id TEXT")
            # 3.10: photos of materials and equipment, depreciation of equipment
            if "photo_id" not in {r[1] for r in db.conn.execute("PRAGMA table_info(materials)")}:
                db.conn.execute("ALTER TABLE materials ADD COLUMN photo_id TEXT")
            ecols = {r[1] for r in db.conn.execute("PRAGMA table_info(equipment)")}
            for col in ("photo_id TEXT", "in_service TEXT", "useful_months INTEGER", "salvage REAL DEFAULT 0", "amort_method TEXT",
                        *EQ_NEW_COLS):  # 3.13: the equipment card
                if col.split()[0] not in ecols:
                    db.conn.execute(f"ALTER TABLE equipment ADD COLUMN {col}")
            ecols = {r[1] for r in db.conn.execute("PRAGMA table_info(equipment)")}
            for col in EQ_NEW_COLS_315:  # 3.15: the accounting, someone else's property, the journals
                if col.split()[0] not in ecols:
                    db.conn.execute(f"ALTER TABLE equipment ADD COLUMN {col}")
            if "data" not in {r[1] for r in db.conn.execute("PRAGMA table_info(equipment_events)")}:  # 3.13: inventory details
                db.conn.execute("ALTER TABLE equipment_events ADD COLUMN data TEXT")
            if "reg_id" not in {r[1] for r in db.conn.execute("PRAGMA table_info(equipment_plans)")}:  # 3.16: the regulation of a plan
                db.conn.execute("ALTER TABLE equipment_plans ADD COLUMN reg_id TEXT")
            dcols = {r[1] for r in db.conn.execute("PRAGMA table_info(equipment_docs)")}
            for col in EQ_DOC_COLS_316:  # 3.16 «Документы»: the number, the date, the term, the counterparty, the archive
                if col.split()[0] not in dcols:
                    db.conn.execute(f"ALTER TABLE equipment_docs ADD COLUMN {col}")
            mcols = {r[1] for r in db.conn.execute("PRAGMA table_info(materials)")}
            for col in MAT_NEW_COLS:  # 3.14: the material card
                if col.split()[0] not in mcols:
                    db.conn.execute(f"ALTER TABLE materials ADD COLUMN {col}")
            self._fill_numbers(db.conn)
            db.conn.commit()

    service_location = None  # 3.5: callable(invoice row) -> place of the automatic write-off by an invoice (set by Api)

    @staticmethod
    def _fill_numbers(conn):
        """3.14: a material without a number (made before 3.14, by the demo, or on a computer not updated yet) gets the next one,
        in the order the materials were made: every computer numbers the same materials the same way."""
        todo = conn.execute("SELECT id FROM materials WHERE COALESCE(number,'')='' ORDER BY COALESCE(created_at,''), id").fetchall()
        if not todo:
            return 0
        used = {str(r[0]) for r in conn.execute("SELECT number FROM materials WHERE COALESCE(number,'')<>''")}
        n = max([int(m[1]) for x in used if (m := re.match(r"^МТ-(\d+)$", x))] or [0])
        for (mid,) in todo:
            n += 1
            while f"МТ-{n:04d}" in used:
                n += 1
            conn.execute("UPDATE materials SET number=? WHERE id=?", (f"МТ-{n:04d}", mid))
        return len(todo)

    def fill_numbers(self):
        with self.db.tx() as c:
            return self._fill_numbers(c)

    # ============================================================ materials --
    def materials(self, q="", only_low=False, with_inactive=False, only_expiring=False, location=None):
        """`location` (3.5): the balance and its value in that place («» — the main stock); the minimum stays clinic-wide."""
        rows = self.db.q("""
            SELECT m.*, COALESCE(SUM(s.qty), 0) AS balance,
                   COALESCE(SUM(CASE WHEN COALESCE(d.nodoc, 0) = 0 THEN s.qty END), 0) AS balance_doc,
                   MAX(CASE WHEN s.kind IN ('service','writeoff') THEN s.at END) AS last_used
            FROM materials m LEFT JOIN stock_moves s ON s.material_id = m.id LEFT JOIN stock_docs d ON d.id = s.doc_id
            WHERE (? OR m.active = 1)
            GROUP BY m.id ORDER BY m.category, m.name""", (1 if with_inactive else 0,))
        q = (q or "").strip().lower()
        lots = self._lots_by_material({r["id"]: r["balance"] for r in rows})
        for r in rows:
            r["balance"] = round(r["balance"], 3)
            r["balance_doc"] = round(r["balance_doc"], 3)   # by documents only (2.14.1)
            r["value_doc"] = round(r["balance_doc"] * (r["price"] or 0), 2)
            r["low"] = r["min_qty"] > 0 and r["balance"] <= r["min_qty"]
            r["value"] = round(r["balance"] * (r["price"] or 0), 2)
            ls = [x for x in lots.get(r["id"], {}).get("lots", []) if x["left"] > 0]
            r["lots"] = len(ls)
            r["expired_qty"] = round(sum(x["left"] for x in ls if x["state"] == "expired"), 3)
            r["soon_qty"] = round(sum(x["left"] for x in ls if x["state"] == "soon"), 3)
            r["expires"] = min((x["expires"] for x in ls if x["expires"]), default="")
            r["exp_state"] = "expired" if r["expired_qty"] > 0 else "soon" if r["soon_qty"] > 0 else ""
        if location is not None:
            at = self.location_balances()
            for r in rows:
                r["total_balance"] = r["balance"]
                r["balance"] = round(at.get(r["id"], {}).get(location or "", 0), 3)
                r["value"] = round(r["balance"] * (r["price"] or 0), 2)
        if q:
            rows = [r for r in rows if q in f"{r['code']} {r['name']} {r['category']} {r['barcode']} {r.get('number') or ''} "
                                             f"{r.get('manufacturer') or ''}".lower()]
        if only_low:
            rows = [r for r in rows if r["low"]]
        if only_expiring:
            rows = [r for r in rows if r["exp_state"]]
        return rows

    # ------------------------------------------------- lots and expiry dates --
    def _lots_by_material(self, balances, mid=None):
        """Lots left on hand, worked out from the move ledger instead of being stored (FEFO).

        Whatever leaves the stock is taken from the lot that expires first. So, going from the latest expiry to
        the earliest, each lot keeps min(its quantity, what is still unassigned of the balance); what no lot covers
        is stock «без срока». A write-off of a specific expired lot is stored as a negative row of that lot.
        Nothing here depends on move ids staying put, so on_invoice can delete and re-create its moves freely."""
        sql = """SELECT l.id, l.material_id, l.lot, l.expires, l.qty, l.created_at, s.at, s.doc_id, d.number AS doc_number,
                        sp.name AS supplier_name
                 FROM stock_lots l JOIN stock_moves s ON s.id = l.move_id
                 LEFT JOIN stock_docs d ON d.id = s.doc_id LEFT JOIN suppliers sp ON sp.id = d.supplier_id"""
        rows = self.db.q(sql + (" WHERE l.material_id=?" if mid else "") + " ORDER BY l.id", (mid,) if mid else ())
        groups = {}
        for r in rows:  # one lot = one material + lot number + expiry date, however many receipts brought it
            key = (r["material_id"], r["lot"] or "", r["expires"] or "")
            g = groups.get(key)
            if g is None:
                if r["qty"] <= 0:
                    continue
                g = groups[key] = {"id": r["id"], "material_id": r["material_id"], "lot": r["lot"] or "", "expires": r["expires"] or "",
                                   "qty": 0.0, "received": r["at"][:10] if r["at"] else "", "doc_number": r["doc_number"] or "",
                                   "supplier_name": r["supplier_name"] or ""}
            g["qty"] += r["qty"]
        today = date.today()
        soon = (today.toordinal() + SOON_DAYS)
        out = {}
        for g in groups.values():
            out.setdefault(g["material_id"], {"lots": []})["lots"].append(g)
        for m_id, rec in out.items():
            left = max(0.0, balances.get(m_id, 0) or 0)
            # latest expiry first; a lot without a date is consumed last of all; among equal dates the newest is kept
            rec["lots"].sort(key=lambda g: (g["expires"] or "9999-12-31", g["id"]), reverse=True)
            for g in rec["lots"]:
                g["qty"] = round(max(0.0, g["qty"]), 3)
                g["left"] = round(min(g["qty"], left), 3)
                left = round(left - g["left"], 3)
                if g["expires"]:
                    e = date.fromisoformat(g["expires"])
                    g["days"] = (e - today).days
                    g["state"] = "expired" if e < today else "soon" if e.toordinal() <= soon else "ok"
                else:
                    g["days"], g["state"] = None, "ok"
            rec["lots"].reverse()  # show the earliest expiry first
            rec["no_lot"] = round(left, 3)
        return out

    def lots(self, mid):
        """The lots of one material on hand: earliest expiry first, plus the part not covered by any lot."""
        bal = self.balance(mid)
        rec = self._lots_by_material({mid: bal}, mid).get(mid, {"lots": [], "no_lot": max(0.0, bal)})
        return {"lots": [g for g in rec["lots"] if g["left"] > 0], "no_lot": rec["no_lot"], "balance": bal}

    def expired_lines(self):
        """Ready lines for «Списать просроченное»: every expired lot that is still on hand."""
        out = []
        mats = {m["id"]: m for m in self.materials()}
        bal = {k: v["balance"] for k, v in mats.items()}
        for mid, rec in self._lots_by_material(bal).items():
            if mid not in mats:
                continue
            for g in rec["lots"]:
                if g["state"] == "expired" and g["left"] > 0:
                    m = mats[mid]
                    out.append({"material_id": mid, "name": m["name"], "unit": m["unit"], "qty": g["left"], "lot_id": g["id"],
                                "lot": g["lot"], "expires": g["expires"], "price": m["price"]})
        out.sort(key=lambda x: (x["expires"], x["name"]))
        return out

    def material(self, mid):
        rows = [r for r in self.materials(with_inactive=True) if r["id"] == mid]
        if not rows:
            return None
        m = rows[0]
        m["lot_list"] = self.lots(mid)
        m["moves"] = self.moves(material_id=mid, limit=1000)  # 3.14: «История» — every move
        names = self._loc_names()  # 3.5: where it is
        m["by_location"] = [{"id": k, "name": names.get(k, MAIN), "qty": v}
                            for k, v in sorted(self.location_balances().get(mid, {}).items(), key=lambda x: (x[0] != "", names.get(x[0], "")))
                            if abs(v) > 1e-9]
        m["norms"] = self.db.q("""SELECT sm.service_id, sm.qty, s.title, s.code FROM service_materials sm
                                  JOIN services s ON s.id = sm.service_id WHERE sm.material_id=? ORDER BY s.title""", (mid,))
        m.update(self.material_supplies(mid))   # 3.13 «карточка материала»
        m.update(self.material_usage(mid, m["balance"] - (m.get("expired_qty") or 0)))
        m.update(self.material_card(m))         # 3.14: by the mockup
        return m

    # ------------------------------------------------------ 3.14: the material card --
    def reserve(self, mid=None):
        """«Резервный остаток»: what the cabinets asked for and did not get yet (new, accepted and partly issued requests)."""
        if not self.db.one("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name='stock_requests'"):
            return {}
        out = {}
        for r in self.db.q(f"SELECT lines, issued FROM stock_requests WHERE status IN ({','.join('?' * len(REQ_OPEN))})", REQ_OPEN):
            issued = _jl(r["issued"], {})
            for ln in _jl(r["lines"], []):
                k = str((ln or {}).get("material_id") or "")
                if not k or (mid and k != mid):
                    continue
                try:
                    left = float(ln.get("qty") or 0) - float(issued.get(k, 0) or 0)
                except (TypeError, ValueError):
                    continue
                if left > 1e-9:
                    out[k] = round(out.get(k, 0) + left, 3)
        return out

    def in_transit(self, mid=None):
        """«В пути (заказано)»: ordered from suppliers and not received yet, by the open orders."""
        out = {}
        for o in self.db.q(f"SELECT lines, received FROM stock_orders WHERE status IN ({','.join('?' * len(ORDER_OPEN))})", ORDER_OPEN):
            got = _jl(o["received"], {})
            for ln in _jl(o["lines"], []):
                k = str((ln or {}).get("material_id") or "")
                if not k or (mid and k != mid):
                    continue
                left = float(ln.get("qty") or 0) - float(got.get(k, 0) or 0)
                if left > 1e-9:
                    out[k] = round(out.get(k, 0) + left, 3)
        return out

    def material_card(self, m):
        """What the 3.14 card adds: reserve, in transit, the coverage by days, the analytics, the use by month, the orders,
        the documents and photos, the analogs, the barcode and the services it is used in."""
        mid, today = m["id"], date.today()
        usable = max(0.0, (m["balance"] or 0) - (m.get("expired_qty") or 0))
        reserve = self.reserve(mid).get(mid, 0.0)
        free = round(max(0.0, usable - reserve), 3)
        transit = self.in_transit(mid).get(mid, 0.0)
        daily = (m.get("usage") or {}).get("daily") or 0
        days = round(free / daily, 1) if daily > 0 else None
        opt = m.get("opt_qty") or 0
        full = opt or (m["min_qty"] or 0) * 2
        # by month for a year: services, the use in treatment (the nurse's «Расход в лечении») and the other write-offs
        ym = []
        y, mo = today.year, today.month
        for _ in range(12):
            ym.append(f"{y}-{mo:02d}")
            y, mo = (y, mo - 1) if mo > 1 else (y - 1, 12)
        ym.reverse()
        months = {}
        for r in self.db.q("""SELECT substr(at,1,7) AS mon, kind, reason, -SUM(qty) AS q, -SUM(qty*price) AS v FROM stock_moves
                              WHERE material_id=? AND kind IN ('service','writeoff') AND substr(at,1,10) >= ?
                              GROUP BY mon, kind, reason""", (mid, ym[0] + "-01")):
            k = "service" if r["kind"] == "service" else "treatment" if str(r["reason"] or "").startswith("Расход в лечении") else "writeoff"
            g = months.setdefault(r["mon"], {"month": r["mon"], "service": 0.0, "treatment": 0.0, "writeoff": 0.0, "sum": 0.0})
            g[k] = round(g[k] + (r["q"] or 0), 3)
            g["sum"] = round(g["sum"] + (r["v"] or 0), 2)
        use_months = [months.get(k) or {"month": k, "service": 0.0, "treatment": 0.0, "writeoff": 0.0, "sum": 0.0} for k in ym]
        tot = {k: round(sum(x[k] for x in use_months), 3) for k in ("service", "treatment", "writeoff")}
        m30 = (today - timedelta(days=30)).isoformat()
        used30 = -(self.db.one("""SELECT COALESCE(SUM(qty),0) AS q FROM stock_moves WHERE material_id=? AND kind IN ('service','writeoff')
                                 AND substr(at,1,10) > ?""", (mid, m30))["q"] or 0)
        y365 = (today - timedelta(days=365)).isoformat()
        buy = self.db.one("""SELECT COALESCE(SUM(qty*price),0) AS v, COALESCE(SUM(qty),0) AS q FROM stock_moves
                             WHERE material_id=? AND kind='receipt' AND qty > 0 AND price > 0 AND substr(at,1,10) > ?""", (mid, y365))
        orders = [o for o in self.orders(open_only=True) if any(ln["material_id"] == mid for ln in o["lines"])]
        docs = self.db.q("""SELECT d.*, f.ext, f.size FROM material_docs d LEFT JOIN patient_files f ON f.id = d.file_id
                            WHERE d.material_id=? AND d.deleted=0 ORDER BY d.created_at, d.id""", (mid,))
        for d in docs:
            d["kind_title"] = MAT_DOC_KINDS.get(d["kind"], d["kind"])
            d["image"] = (d.get("ext") or "") in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
        photos = list(dict.fromkeys(x for x in [m.get("photo_id")] + [d["file_id"] for d in docs if d["kind"] == "photo"] if x))
        sup = self.db.one("SELECT id, name, phone FROM suppliers WHERE id=?", (m.get("supplier_id"),)) if m.get("supplier_id") else None
        bar = m.get("barcode") or ""
        ean = bar if barcodes.valid_ean(bar) else ("" if bar else barcodes.internal_ean(mid))
        if m["balance"] <= 0:
            status = ("bad", "Нет в наличии")
        elif usable <= 0:
            status = ("bad", "Просрочено")
        elif m["low"] or (m["min_qty"] and free <= m["min_qty"]):
            status = ("warn", "Заканчивается")
        else:
            status = ("ok", "В наличии")
        return {"reserve": round(reserve, 3), "free": free, "in_transit": round(transit, 3), "status": status,
                "monthly": round(daily * 30, 1), "used30": round(max(0.0, used30), 3), "cover_days": days,
                "cover_pct": round(max(0.0, min(100.0, free / full * 100)), 1) if full else (100.0 if free > 0 else 0.0),
                "cover_full": full, "unit_cost": m["price"] or 0,
                "avg_price": round(buy["v"] / buy["q"], 2) if buy["q"] else (m["price"] or 0), "avg_price_qty": round(buy["q"] or 0, 3),
                "use_months": use_months, "use_total": tot, "orders": orders, "docs": docs, "photos": photos,
                "doc_kinds": [{"kind": k, "title": t, "count": sum(1 for d in docs if d["kind"] == k)} for k, t in MAT_DOC_KINDS.items()],
                "analogs": self.analogs(mid), "supplier": sup,
                "ean": ean, "ean_svg": barcodes.ean_svg(ean) if ean else "", "ean_internal": bool(ean and ean != bar)}

    # ---------------------------------------------------- 3.14: orders to suppliers --
    def orders(self, status=None, open_only=False, limit=300):
        sql, args = "SELECT o.*, s.name AS supplier_name, s.phone AS supplier_phone FROM stock_orders o LEFT JOIN suppliers s ON s.id = o.supplier_id", []
        if open_only:
            sql += f" WHERE o.status IN ({','.join('?' * len(ORDER_OPEN))})"
            args += list(ORDER_OPEN)
        elif status:
            sql += " WHERE o.status=?"
            args.append(status)
        rows = self.db.q(sql + " ORDER BY CASE WHEN o.status IN ('ordered','partial') THEN 0 ELSE 1 END, o.date DESC, o.created_at DESC LIMIT ?",
                         (*args, int(limit)))
        mats = {r["id"]: r for r in self.db.q("SELECT id, name, unit, number, code FROM materials")}
        today = date.today().isoformat()
        for o in rows:
            got = _jl(o["received"], {})
            lines = []
            for ln in _jl(o["lines"], []):
                mm = mats.get(ln.get("material_id")) or {}
                rec = round(float(got.get(ln.get("material_id"), 0) or 0), 3)
                lines.append({**ln, "name": mm.get("name") or "удалённый материал", "unit": mm.get("unit") or "", "number": mm.get("number") or "",
                              "code": mm.get("code") or "", "received": rec, "left": round(max(0.0, float(ln.get("qty") or 0) - rec), 3)})
            o["lines"] = lines
            o["received"] = got
            o["doc_ids"] = _jl(o["doc_ids"], [])
            o["status_title"] = ORDER_STATUS.get(o["status"], o["status"])
            o["late"] = o["status"] in ORDER_OPEN and bool(o["expected"]) and o["expected"] < today
            o["supplier_name"] = o["supplier_name"] or ""
        return rows

    def order(self, oid):
        o = next((x for x in self.orders(limit=100000) if x["id"] == oid), None)
        if not o:
            raise ValueError("Заказ не найден")
        return o

    def save_order(self, f, user=""):
        """«Сформировать закупку»: an order to one supplier. The expected day is the order's day plus the longest delivery term
        of its materials (or the day typed in the form). What is ordered and not received yet is «в пути»."""
        lines = self._lines(f.get("lines"))
        if any(q <= 0 for _, q, _ in lines):
            raise ValueError("Количество в заказе должно быть больше нуля")
        merged = {}
        for mid, q, pr in lines:
            g = merged.setdefault(mid, {"material_id": mid, "qty": 0.0, "price": pr})
            g["qty"] = round(g["qty"] + q, 3)
        sid = str(f.get("supplier_id") or "").strip() or None
        if sid and not self.db.one("SELECT 1 AS x FROM suppliers WHERE id=?", (sid,)):
            raise ValueError("Поставщик не найден")
        day = _day(f.get("date"), "Дата заказа") or date.today().isoformat()
        exp = _day(f.get("expected"), "Ожидается")
        if not exp:
            lead = max([int(r["lead_days"] or 0) for r in self.db.q(
                f"SELECT lead_days FROM materials WHERE id IN ({','.join('?' * len(merged))})", tuple(merged))] or [0])
            exp = (date.fromisoformat(day) + timedelta(days=lead)).isoformat() if lead else ""
        oid, at = _id("PO"), _now()
        n = self.db.one("SELECT COUNT(*) AS n FROM stock_orders")["n"]
        total = round(sum(g["qty"] * g["price"] for g in merged.values()), 2)
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_orders(id, number, supplier_id, date, expected, lines, received, status, total, comment, doc_ids,
                         user_name, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (oid, _clean(f.get("number"), 30) or f"З-{n + 1:04d}", sid, day, exp, json.dumps(list(merged.values()), ensure_ascii=False),
                       "{}", "ordered", total, _clean(f.get("comment"), 500), "[]", user, at, at))
        return oid

    def cancel_order(self, oid):
        o = self.db.one("SELECT * FROM stock_orders WHERE id=?", (str(oid or ""),))
        if not o:
            raise ValueError("Заказ не найден")
        if o["status"] not in ORDER_OPEN:
            raise ValueError("Заказ уже закрыт")
        with self.db.tx() as c:
            c.execute("UPDATE stock_orders SET status='cancelled', updated_at=? WHERE id=?", (_now(), o["id"]))
        return True

    def _order_received(self, c, oid, did, lines):
        """A receipt by an order counts against it: «получен частично» or «получен»."""
        o = c.execute("SELECT lines, received, doc_ids, status FROM stock_orders WHERE id=?", (oid,)).fetchone()
        if not o or o[3] not in ORDER_OPEN:
            raise ValueError("Заказ не найден или уже закрыт")
        want, got, docs = _jl(o[0], []), _jl(o[1], {}), _jl(o[2], [])
        for mid, q, _ in lines:
            got[mid] = round(float(got.get(mid, 0) or 0) + q, 3)
        full = all(float(got.get(ln["material_id"], 0) or 0) + 1e-9 >= float(ln["qty"]) for ln in want)
        c.execute("UPDATE stock_orders SET received=?, doc_ids=?, status=?, updated_at=? WHERE id=?",
                  (json.dumps(got), json.dumps(docs + [did]), "received" if full else "partial", _now(), oid))

    # ------------------------------------------------- 3.14: documents and analogs --
    def material_doc_add(self, mid, kind, title, file_id, user=""):
        m = self.db.one("SELECT id, photo_id FROM materials WHERE id=? AND active=1", (str(mid or ""),))
        if not m:
            raise ValueError("Материал не найден или убран из справочника")
        kind = kind if kind in MAT_DOC_KINDS else "other"
        did = _id("MD")
        with self.db.tx() as c:
            c.execute("INSERT INTO material_docs(id, material_id, kind, title, file_id, created_by, created_at, deleted) VALUES(?,?,?,?,?,?,?,0)",
                      (did, m["id"], kind, _clean(title, 200) or MAT_DOC_KINDS[kind], file_id, user, _now()))
            if kind == "photo" and not m["photo_id"]:
                c.execute("UPDATE materials SET photo_id=? WHERE id=?", (file_id, m["id"]))
        return did

    def material_doc_delete(self, did):
        d = self.db.one("SELECT * FROM material_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        with self.db.tx() as c:
            c.execute("UPDATE material_docs SET deleted=1 WHERE id=?", (d["id"],))
            if c.execute("SELECT 1 FROM materials WHERE id=? AND photo_id=?", (d["material_id"], d["file_id"])).fetchone():
                nxt = c.execute("SELECT file_id FROM material_docs WHERE material_id=? AND kind='photo' AND deleted=0 AND file_id<>? "
                                "ORDER BY created_at LIMIT 1", (d["material_id"], d["file_id"])).fetchone()
                c.execute("UPDATE materials SET photo_id=? WHERE id=?", (nxt[0] if nxt else None, d["material_id"]))
        return d["material_id"]

    def material_doc_file(self, did):
        d = self.db.one("SELECT * FROM material_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        return d

    @staticmethod
    def _pair(a, b):
        a, b = sorted((str(a or ""), str(b or "")))
        return f"{a}|{b}"[:120], a, b

    def analogs(self, mid):
        rows = self.db.q("""SELECT CASE WHEN x.a=? THEN x.b ELSE x.a END AS id FROM material_analogs x
                            WHERE x.deleted=0 AND (x.a=? OR x.b=?)""", (mid, mid, mid))
        ids = [r["id"] for r in rows]
        if not ids:
            return []
        mats = {r["id"]: r for r in self.materials(with_inactive=True) if r["id"] in ids}
        return sorted([{"id": k, "name": mats[k]["name"], "number": mats[k].get("number") or "", "code": mats[k]["code"] or "",
                        "unit": mats[k]["unit"], "balance": mats[k]["balance"], "price": mats[k]["price"] or 0, "active": mats[k]["active"],
                        "photo_id": mats[k].get("photo_id") or ""} for k in ids if k in mats], key=lambda x: x["name"])

    def analog_add(self, mid, other, user=""):
        if not mid or not other or mid == other:
            raise ValueError("Выберите другой материал")
        for x in (mid, other):
            if not self.db.one("SELECT 1 AS x FROM materials WHERE id=? AND active=1", (x,)):
                raise ValueError("Материал не найден")
        key, a, b = self._pair(mid, other)
        with self.db.tx() as c:
            c.execute("""INSERT INTO material_analogs(id, a, b, created_by, created_at, deleted) VALUES(?,?,?,?,?,0)
                         ON CONFLICT(id) DO UPDATE SET deleted=0, created_by=excluded.created_by, created_at=excluded.created_at""",
                      (key, a, b, user, _now()))
        return key

    def analog_delete(self, mid, other):
        key, _, _ = self._pair(mid, other)
        with self.db.tx() as c:
            c.execute("UPDATE material_analogs SET deleted=1 WHERE id=?", (key,))
        return True

    # ------------------------------------------------ 3.14: the label of a material --
    def material_qr_text(self, m, clinic=""):
        """Like the equipment's: a link `<app>/m/<номер>` or the text with the number first."""
        url = self.phone_url()
        if url:
            return f"{url.rstrip('/')}/m/{quote(str(m.get('number') or ''), safe='')}"
        lines = [str(m.get("number") or ""), m["name"], m.get("code") and f"Арт.: {m['code']}",
                 m.get("manufacturer") and f"Производитель: {m['manufacturer']}", clinic]
        return "\n".join(str(x) for x in lines if x)

    def material_by_code(self, code):
        """The material a scanned label points to: the link, the text of the QR or just the number «МТ-0147»."""
        s = str(code or "").strip()
        if not s:
            return None
        m = re.search(r"/m/([^/?#\s]+)", s)
        num = unquote(m[1]) if m else s.splitlines()[0].strip()
        if not num:
            return None
        r = self.db.one("SELECT id FROM materials WHERE number=? AND active=1", (num,))
        if not r:  # «мт-0147» typed by hand: SQLite lower() knows no Cyrillic
            r = next((x for x in self.db.q("SELECT id, number FROM materials WHERE active=1 AND COALESCE(number,'')<>''")
                      if x["number"].casefold() == num.casefold()), None)
        return r["id"] if r else None

    def material_label(self, mid):
        """Printing the label of a material without a barcode writes its internal EAN-13 down, so a desk scanner finds it."""
        m = self.db.one("SELECT * FROM materials WHERE id=?", (str(mid or ""),))
        if not m:
            raise ValueError("Материал не найден")
        if not m["barcode"]:
            ean = barcodes.internal_ean(m["id"])
            if not self.db.one("SELECT 1 AS x FROM materials WHERE barcode=? AND id<>?", (ean, m["id"])):
                with self.db.tx() as c:
                    c.execute("UPDATE materials SET barcode=? WHERE id=? AND COALESCE(barcode,'')=''", (ean, m["id"]))
        return m["id"]

    def material_supplies(self, mid):
        """3.13 «Карточка материала»: every receipt of the material — when, from whom, how much, at what price, by which invoice;
        per supplier: how many deliveries, the last one and the best price; the last supplier and the best current offer.

        A material is bought from different suppliers over time (Marchenko, then Ivanova, then Petrov), so the supplier lives on
        each receipt (`stock_docs.supplier_id`), not on the material."""
        rows = self.db.q("""SELECT m.id, m.qty, m.price, m.at, m.doc_id, m.location_id, m.user_name, d.number AS doc_number,
                                   COALESCE(NULLIF(d.date,''), substr(m.at,1,10)) AS day, d.supplier_id, COALESCE(d.nodoc,0) AS nodoc,
                                   s.name AS supplier_name, l.lot, l.expires
                            FROM stock_moves m LEFT JOIN stock_docs d ON d.id = m.doc_id LEFT JOIN suppliers s ON s.id = d.supplier_id
                            LEFT JOIN stock_lots l ON l.id = (SELECT MIN(x.id) FROM stock_lots x WHERE x.move_id = m.id AND x.qty > 0)
                            WHERE m.material_id=? AND m.kind='receipt' AND m.qty > 0
                            ORDER BY day DESC, m.at DESC, m.id DESC""", (mid,))
        names = self._loc_names()
        by = {}
        for r in rows:
            r["qty"] = round(r["qty"], 3)
            r["sum"] = round(r["qty"] * (r["price"] or 0), 2)
            r["supplier_name"] = r["supplier_name"] or ""
            r["location_name"] = names.get(r.get("location_id") or "", MAIN)
            if not r["supplier_id"]:
                continue
            g = by.get(r["supplier_id"])
            if g is None:  # rows go from the newest, so the first row of a supplier is its last delivery
                g = by[r["supplier_id"]] = {"supplier_id": r["supplier_id"], "supplier_name": r["supplier_name"], "count": 0, "qty": 0.0,
                                            "sum": 0.0, "last_date": r["day"], "last_price": r["price"] or 0, "min_price": None}
            g["count"] += 1
            g["qty"] = round(g["qty"] + r["qty"], 3)
            g["sum"] = round(g["sum"] + r["sum"], 2)
            if (r["price"] or 0) > 0 and (g["min_price"] is None or r["price"] < g["min_price"]):
                g["min_price"] = r["price"]
        sups = sorted(by.values(), key=lambda g: g["last_date"] or "", reverse=True)
        for g in sups:
            g["avg_price"] = round(g["sum"] / g["qty"], 2) if g["qty"] else 0
        priced = [g for g in sups if g["last_price"] > 0]
        best = min(priced, key=lambda g: (g["last_price"], -(date.fromisoformat(g["last_date"]).toordinal() if g["last_date"] else 0))) \
            if priced else None
        for g in sups:
            g["best"] = best is not None and g["supplier_id"] == best["supplier_id"]
        last = next((r for r in rows if r["supplier_id"]), None)
        return {"supplies": rows[:300], "supply_count": len(rows), "supplier_stats": sups,
                "last_supply": last and {"supplier_id": last["supplier_id"], "supplier_name": last["supplier_name"], "date": last["day"],
                                         "price": last["price"] or 0, "qty": last["qty"], "doc_id": last["doc_id"],
                                         "doc_number": last["doc_number"] or ""},
                "best_offer": best and {"supplier_id": best["supplier_id"], "supplier_name": best["supplier_name"],
                                        "price": best["last_price"], "date": best["last_date"]}}

    def material_usage(self, mid, usable):
        """How fast the material goes: services and write-offs over the last 60 days, and how many days the usable stock lasts."""
        since = date.fromordinal(date.today().toordinal() - USAGE_DAYS).isoformat()
        used = -(self.db.one("""SELECT COALESCE(SUM(qty),0) AS q FROM stock_moves WHERE material_id=? AND kind IN ('service','writeoff')
                                AND substr(at,1,10) > ?""", (mid, since))["q"] or 0)
        used = round(max(0.0, used), 3)
        daily = used / USAGE_DAYS
        return {"usage": {"days": USAGE_DAYS, "used": used, "daily": round(daily, 3),
                          "days_left": round(max(0.0, usable) / daily, 1) if daily > 0 else None}}

    def save_material(self, f):
        """3.14: the fields not sent keep their values (the nurse's quick form, the scanner and the importer send only some);
        a new material gets the next number «МТ-…»."""
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите название материала")
        mid = f.get("id") or _id("M")
        old = self.db.one("SELECT * FROM materials WHERE id=?", (mid,)) or {}
        val = lambda k, fn: fn(f[k]) if k in f and f[k] is not None else old.get(k)  # noqa: E731
        bar = _clean(f.get("barcode"), 60) if "barcode" in f and f["barcode"] is not None else (old.get("barcode") or "")
        if bar:
            dup = self.db.one("SELECT name FROM materials WHERE barcode=? AND id<>? AND active=1", (bar, mid))
            if dup:
                raise ValueError(f"Штрихкод {bar} уже указан у материала «{dup['name']}»")
        number = _clean(f.get("number"), 30) if f.get("number") else (old.get("number") or self._next_mat_number())
        if number != old.get("number"):  # only a number being given is checked: two offline computers may have made a pair
            dup = self.db.one("SELECT name FROM materials WHERE number=? AND id<>? AND active=1", (number, mid))
            if dup:
                raise ValueError(f"Номер {number} уже у материала «{dup['name']}»")
        sup_id = val("supplier_id", lambda v: str(v or "").strip() or None)
        if sup_id and not self.db.one("SELECT 1 AS x FROM suppliers WHERE id=?", (sup_id,)):
            sup_id = None
        extra = {k: val(k, lambda v, n=n: _clean(v, n)) or "" for k, n in MAT_TEXT.items()}
        opt = val("opt_qty", lambda v: max(0, _num(v, "Оптимальный остаток"))) or 0
        lead = val("lead_days", lambda v: max(0, min(365, int(_num(v, "Срок поставки"))))) or 0
        with self.db.tx() as c:
            c.execute("""INSERT INTO materials(id, code, name, unit, category, min_qty, price, barcode, comment, active, created_at,
                         number, manufacturer, description, form, shelf_life, storage, opt_qty, lead_days, supplier_id)
                         VALUES(?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET code=excluded.code, name=excluded.name, unit=excluded.unit,
                         category=excluded.category, min_qty=excluded.min_qty, price=excluded.price,
                         barcode=excluded.barcode, comment=excluded.comment, active=1, number=excluded.number,
                         manufacturer=excluded.manufacturer, description=excluded.description, form=excluded.form,
                         shelf_life=excluded.shelf_life, storage=excluded.storage, opt_qty=excluded.opt_qty,
                         lead_days=excluded.lead_days, supplier_id=excluded.supplier_id""",
                      (mid, val("code", lambda v: _clean(v, 50)) or "", name, val("unit", lambda v: _clean(v, 20)) or "шт",
                       val("category", lambda v: _clean(v, 100)) or "", val("min_qty", lambda v: max(0, _num(v, "Минимальный остаток"))) or 0,
                       val("price", lambda v: max(0, _num(v, "Цена"))) or 0, bar, val("comment", lambda v: _clean(v, 500)) or "",
                       old.get("created_at") or _now(), number, *extra.values(), opt, lead, sup_id))
            sup = f.get("supplier_id") if f.get("supplier_id") and self.db.one("SELECT 1 AS x FROM suppliers WHERE id=?", (f.get("supplier_id"),)) else None
            if f.get("start_qty") and not f.get("id") and not sup:
                q = _num(f["start_qty"])
                if q:
                    c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, reason, user_name, at) VALUES(?,?,?,?,?,?,?)",
                              (mid, q, _num(f.get("price")), "inventory", "Начальный остаток", f.get("_user", ""), _now()))
        if f.get("start_qty") and not f.get("id") and sup and _num(f["start_qty"]) > 0:
            # 3.13: a new material «от поставщика» — the starting stock is that supplier's receipt, so the card shows who it was
            self.receive({"supplier_id": sup, "number": f.get("doc_number"), "lines": [{"material_id": mid, "qty": f["start_qty"], "price": f.get("price")}],
                          "comment": "Начальный остаток"}, f.get("_user", ""))
        return mid

    _MAT_SET = {"min_qty": "Минимальный остаток", "opt_qty": "Оптимальный остаток", "lead_days": "Срок поставки",
                "supplier_id": "Основной поставщик"}

    def material_set(self, mid, field, value):
        """3.14: the four fields under «Общие сведения» are saved at once, one by one (no form, no «Сохранить»)."""
        m = self.db.one("SELECT * FROM materials WHERE id=? AND active=1", (str(mid or ""),))
        if not m:
            raise ValueError("Материал не найден или убран из справочника")
        if field not in self._MAT_SET:
            raise ValueError("Это поле так не меняется")
        if field == "supplier_id":
            v = str(value or "").strip() or None
            if v and not self.db.one("SELECT 1 AS x FROM suppliers WHERE id=? AND active=1", (v,)):
                raise ValueError("Поставщик не найден")
        elif field == "lead_days":
            v = int(max(0, min(365, _num(value, self._MAT_SET[field]))))
        else:
            v = max(0, _num(value, self._MAT_SET[field]))
        with self.db.tx() as c:
            c.execute(f"UPDATE materials SET {field}=? WHERE id=?", (v, m["id"]))
        return v

    _MNUM = re.compile(r"^(.*?)(\d+)$")

    def _next_mat_number(self):
        """The next number of a material: the prefix of the last numbered one goes on (МТ-0147 → МТ-0148), first МТ-0001."""
        rows = self.db.q("SELECT number FROM materials WHERE COALESCE(number,'')<>'' ORDER BY COALESCE(created_at,''), rowid")
        parsed = [(m[1], m[2]) for r in rows if (m := self._MNUM.match(str(r["number"]).strip()))]
        if not parsed:
            return MAT_FIRST
        prefix = parsed[-1][0]
        same = [n for p, n in parsed if p == prefix]
        nxt, width = max(int(n) for n in same) + 1, max(len(n) for n in same)
        used = {str(r["number"]).strip() for r in rows}
        while f"{prefix}{str(nxt).zfill(width)}" in used:
            nxt += 1
        return f"{prefix}{str(nxt).zfill(width)}"

    def delete_material(self, mid):
        with self.db.tx() as c:
            c.execute("UPDATE materials SET active=0 WHERE id=?", (mid,))
            c.execute("DELETE FROM service_materials WHERE material_id=?", (mid,))
        return True

    def balance(self, mid):
        return round(self.db.one("SELECT COALESCE(SUM(qty),0) AS b FROM stock_moves WHERE material_id=?", (mid,))["b"], 3)

    # ============================================================ suppliers --
    def suppliers(self):
        return self.db.q("SELECT * FROM suppliers WHERE active=1 ORDER BY name")

    def save_supplier(self, f):
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите поставщика")
        sid = f.get("id") or _id("S")
        with self.db.tx() as c:
            c.execute("""INSERT INTO suppliers(id, name, phone, inn, comment, active) VALUES(?,?,?,?,?,1)
                         ON CONFLICT(id) DO UPDATE SET name=excluded.name, phone=excluded.phone, inn=excluded.inn,
                         comment=excluded.comment, active=1""",
                      (sid, name, _clean(f.get("phone"), 50), _clean(f.get("inn"), 20), _clean(f.get("comment"), 500)))
        return sid

    def delete_supplier(self, sid):
        with self.db.tx() as c:
            c.execute("UPDATE suppliers SET active=0 WHERE id=?", (sid,))
        return True

    # ============================================== documents: in / out / count --
    def _lines(self, lines):
        out = []
        for ln in lines or []:
            mid = ln.get("material_id")
            if not mid or not self.db.one("SELECT 1 AS x FROM materials WHERE id=?", (mid,)):
                raise ValueError("В документе есть материал, которого нет в справочнике")
            out.append((mid, _num(ln.get("qty")), max(0, _num(ln.get("price"), "Цена"))))
        if not out:
            raise ValueError("Добавьте хотя бы один материал")
        return out

    def receive(self, f, user=""):
        """Supplier invoice (накладная): stock goes up, last purchase price is remembered."""
        lines = self._lines(f.get("lines"))
        if any(q <= 0 for _, q, _ in lines):
            raise ValueError("Количество в приходе должно быть больше нуля")
        # lot number and expiry date of each line (optional; any of the two makes a lot)
        lots = [(_clean(ln.get("lot"), 60), _day(ln.get("expires"))) for ln in f.get("lines") or []]
        did, at = _id("R"), _now()
        day = f.get("date") or date.today().isoformat()
        total = round(sum(q * p for _, q, p in lines), 2)
        loc = self._loc(f.get("location_id"))
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "receipt", _clean(f.get("number"), 50), day, f.get("supplier_id") or None, "",
                       _clean(f.get("comment"), 500), total, user, at, 1 if f.get("nodoc") else 0, loc))
            for (mid, q, p), (lot, exp) in zip(lines, lots):
                cur = c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, user_name, at, location_id)
                                   VALUES(?,?,?,?,?,?,?,?)""", (mid, q, p, "receipt", did, user, f"{day} {at[11:]}", loc))
                if lot or exp:
                    c.execute("INSERT INTO stock_lots(material_id, move_id, lot, expires, qty, created_at) VALUES(?,?,?,?,?,?)",
                              (mid, cur.lastrowid, lot, exp, q, at))
                if p > 0:
                    c.execute("UPDATE materials SET price=? WHERE id=?", (p, mid))
            if f.get("order_id"):  # 3.14: the receipt by an order to a supplier closes it (or a part of it)
                self._order_received(c, str(f["order_id"]), did, lines)
        return did

    def write_off(self, f, user="", did=None, uid=None):
        """Manual write-off (spoiled, expired, used outside a service). Cannot go below zero.

        3.10: `patient_id` of the form goes to the moves (consumption in treatment); `did` and `uid` give the document and its
        moves fixed ids, so a write-off approved on two computers at once stays one write-off after syncing."""
        lines = self._lines(f.get("lines"))
        reason = _clean(f.get("reason"), 300)
        if not reason:
            raise ValueError("Укажите причину списания")
        need = {}
        for mid, q, _ in lines:
            if q <= 0:
                raise ValueError("Количество для списания должно быть больше нуля")
            need[mid] = need.get(mid, 0) + q
        # 3.5: a write-off from a named place cannot take more than that place has; without a place — the clinic's balance
        by_place = "location_id" in f
        loc = self._loc(f.get("location_id"))
        for mid, q in need.items():
            bal = self.location_balance(mid, loc) if by_place else self.balance(mid)
            if q > bal + 1e-9:
                name = self.db.one("SELECT name FROM materials WHERE id=?", (mid,))["name"]
                where = f"в месте «{self.location_name(loc)}»" if by_place else "на складе"
                raise ValueError(f"«{name}»: {where} {bal:g}, списать {q:g} нельзя")
        # a line may name the lot it takes from (write-off of an expired lot): that lot shrinks, not the undated stock
        lot_of, taken = [], {}
        for (mid, q, _), ln in zip(lines, f.get("lines") or []):
            lid = ln.get("lot_id")
            if not lid:
                lot_of.append(None)
                continue
            g = next((x for x in self.lots(mid)["lots"] if str(x["id"]) == str(lid)), None)
            if not g:
                raise ValueError("Партия не найдена или уже списана")
            taken[g["id"]] = taken.get(g["id"], 0) + q
            if taken[g["id"]] > g["left"] + 1e-9:
                q = taken[g["id"]]
                name = self.db.one("SELECT name FROM materials WHERE id=?", (mid,))["name"]
                raise ValueError(f"«{name}», партия {g['lot'] or '—'}: осталось {g['left']:g}, списать {q:g} нельзя")
            lot_of.append(g)
        did, at = did or _id("W"), _now()
        day = f.get("date") or date.today().isoformat()
        tm = str(f.get("time") or "").strip()
        tm = f"{tm}:00"[:8] if re.fullmatch(r"\d{2}:\d{2}", tm) else at[11:]
        pid = _clean(f.get("patient_id"), 60) or None
        has_uid = bool(uid) and "uid" in {r[1] for r in self.db.conn.execute("PRAGMA table_info(stock_moves)")}
        prices = {r["id"]: r["price"] for r in self.db.q("SELECT id, price FROM materials")}
        total = round(sum(q * (prices.get(mid) or 0) for mid, q, _ in lines), 2)
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "writeoff", "" if f.get("nodoc") else self._next_number("writeoff"), day, None, reason,
                       _clean(f.get("comment"), 500), total, user, at, 1 if f.get("nodoc") else 0, loc))
            for i, ((mid, q, _), g) in enumerate(zip(lines, lot_of)):
                why = reason + (f" (партия {g['lot']})" if g and g["lot"] else "")
                cols, vals = ("material_id, qty, price, kind, doc_id, reason, user_name, at, location_id, patient_id",
                              [mid, -q, prices.get(mid) or 0, "writeoff", did, why[:300], user, f"{day} {tm}", loc, pid])
                if has_uid:
                    cols += ", uid"
                    vals.append(f"{uid}-{i}"[:120])
                cur = c.execute(f"INSERT INTO stock_moves({cols}) VALUES({', '.join('?' * len(vals))})", vals)
                if g:
                    c.execute("INSERT INTO stock_lots(material_id, move_id, lot, expires, qty, created_at) VALUES(?,?,?,?,?,?)",
                              (mid, cur.lastrowid, g["lot"], g["expires"], -q, at))
        return did

    def inventory(self, f, user=""):
        """Stock count: actual quantities replace the book ones; differences become moves."""
        counted = []
        for ln in f.get("lines") or []:
            if ln.get("actual") in (None, ""):
                continue
            mid = ln.get("material_id")
            if not self.db.one("SELECT 1 AS x FROM materials WHERE id=?", (mid,)):
                continue
            actual = _num(ln["actual"], "Фактический остаток")
            if actual < 0:
                raise ValueError("Фактический остаток не может быть отрицательным")
            counted.append((mid, actual))
        if not counted:
            raise ValueError("Введите фактический остаток хотя бы по одному материалу")
        did, at = _id("I"), _now()
        diffs = []
        by_place = "location_id" in f  # 3.5: a count of one place compares with that place's balance
        loc = self._loc(f.get("location_id"))
        with self.db.tx() as c:
            for mid, actual in counted:
                if by_place:
                    book = c.execute("SELECT COALESCE(SUM(qty),0) FROM stock_moves WHERE material_id=? AND COALESCE(location_id,'')=?",
                                     (mid, loc or "")).fetchone()[0]
                else:
                    book = c.execute("SELECT COALESCE(SUM(qty),0) FROM stock_moves WHERE material_id=?", (mid,)).fetchone()[0]
                book = round(book, 3)
                d = round(actual - book, 3)
                if abs(d) > 1e-9:
                    price = c.execute("SELECT price FROM materials WHERE id=?", (mid,)).fetchone()[0] or 0
                    c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, reason, user_name, at, location_id)
                                 VALUES(?,?,?,?,?,?,?,?,?)""", (mid, d, price, "inventory", did, "Инвентаризация", user, at, loc))
                    diffs.append({"material_id": mid, "book": book, "actual": actual, "diff": d})
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "inventory", "" if f.get("nodoc") else self._next_number("inventory"), at[:10], None, "Инвентаризация",
                       _clean(f.get("comment"), 500), 0, user, at, 1 if f.get("nodoc") else 0, loc))
        return {"id": did, "counted": len(counted), "diffs": diffs}

    def _next_number(self, kind):
        """Acts are numbered among documented ones only: an internal write-off does not leave a gap in them."""
        n = self.db.one("SELECT COUNT(*) AS n FROM stock_docs WHERE kind=? AND COALESCE(nodoc,0)=0", (kind,))["n"]
        return str(n + 1)

    def day_docs(self, day) -> dict:
        """Receipts and write-offs of a day for the day report: sums with and without documents."""
        rows = self.db.q("""SELECT d.kind, d.number, d.total, COALESCE(d.nodoc,0) AS nodoc, d.reason, d.user_name, s.name AS supplier_name
                            FROM stock_docs d LEFT JOIN suppliers s ON s.id=d.supplier_id
                            WHERE d.date=? AND d.kind IN ('receipt','writeoff') ORDER BY d.created_at""", (day,))
        svc = self.db.one("""SELECT COALESCE(SUM(-qty*price),0) AS v FROM stock_moves WHERE kind='service' AND substr(at,1,10)=?""", (day,))["v"]
        out = {"rows": rows, "service": round(svc or 0, 2)}
        for k in ("receipt", "writeoff"):
            out[k] = round(sum(r["total"] or 0 for r in rows if r["kind"] == k), 2)
            out[k + "_nodoc"] = round(sum(r["total"] or 0 for r in rows if r["kind"] == k and r["nodoc"]), 2)
        return out

    def docs(self, kind=None, limit=200):
        sql = """SELECT d.*, s.name AS supplier_name, (SELECT COUNT(*) FROM stock_moves m WHERE m.doc_id=d.id) AS lines
                 FROM stock_docs d LEFT JOIN suppliers s ON s.id=d.supplier_id"""
        args = []
        if kind:
            sql += " WHERE d.kind=?"
            args.append(kind)
        rows = self.db.q(sql + " ORDER BY d.created_at DESC LIMIT ?", (*args, int(limit)))
        names = self._loc_names()
        for r in rows:
            r["location_name"] = names.get(r.get("location_id") or "", MAIN)
            r["to_location_name"] = names.get(r.get("to_location_id") or "", MAIN) if r["kind"] == "transfer" else ""
            if r["kind"] == "transfer":
                r["lines"] = (r["lines"] or 0) // 2  # two moves per line: − there, + here
        return rows

    def doc(self, did):
        d = self.db.one("""SELECT d.*, s.name AS supplier_name, s.inn AS supplier_inn FROM stock_docs d
                           LEFT JOIN suppliers s ON s.id=d.supplier_id WHERE d.id=?""", (did,))
        if d:
            d["moves"] = self.db.q("""SELECT m.*, t.name, t.unit, t.code FROM stock_moves m JOIN materials t ON t.id=m.material_id
                                      WHERE m.doc_id=? ORDER BY m.id""", (did,))
            names = self._loc_names()
            d["location_name"] = names.get(d.get("location_id") or "", MAIN)
            d["to_location_name"] = names.get(d.get("to_location_id") or "", MAIN)
            for m in d["moves"]:
                m["location_name"] = names.get(m.get("location_id") or "", MAIN)
            if d["kind"] == "transfer":  # one line per material: what went from there to here
                d["moves"] = [m for m in d["moves"] if m["qty"] > 0]
        return d

    def moves(self, material_id=None, day_from=None, day_to=None, kind=None, limit=500, location=None):
        sql = """SELECT m.*, t.name, t.unit, p.name AS patient_name, d.number AS doc_number, COALESCE(d.nodoc,0) AS nodoc
                 FROM stock_moves m JOIN materials t ON t.id = m.material_id
                 LEFT JOIN patients p ON p.id = m.patient_id LEFT JOIN stock_docs d ON d.id = m.doc_id WHERE 1=1"""
        args = []
        if material_id:
            sql += " AND m.material_id=?"
            args.append(material_id)
        if day_from:
            sql += " AND substr(m.at,1,10) >= ?"
            args.append(day_from)
        if day_to:
            sql += " AND substr(m.at,1,10) <= ?"
            args.append(day_to)
        if kind:
            sql += " AND m.kind=?"
            args.append(kind)
        if location is not None:
            sql += " AND COALESCE(m.location_id,'')=?"
            args.append(location or "")
        rows = self.db.q(sql + " ORDER BY m.at DESC, m.id DESC LIMIT ?", (*args, int(limit)))
        names = self._loc_names()
        for r in rows:
            r["kind_title"] = MOVE_KINDS.get(r["kind"], r["kind"])
            r["location_name"] = names.get(r.get("location_id") or "", MAIN)
            if r["kind"] == "service" and str(r.get("doc_id") or "").startswith("V-"):
                r["kind_title"] = "По приёму"  # 3.5: the write-off by a Dentist Plus visit
        return rows

    # ======================================================= places (3.5) --
    def _loc(self, lid):
        """A place id from the form: «» (or nothing) is the main stock; an unknown or closed place is an error."""
        lid = str(lid or "").strip()
        if not lid:
            return None
        if not self.db.one("SELECT 1 AS x FROM stock_locations WHERE id=? AND active=1", (lid,)):
            raise ValueError("Место хранения не найдено")
        return lid

    def _loc_names(self):
        return {"": MAIN, **{r["id"]: r["name"] for r in self.db.q("SELECT id, name FROM stock_locations")}}

    def location_name(self, lid):
        return self._loc_names().get(lid or "", MAIN)

    def location_balance(self, mid, lid):
        return round(self.db.one("SELECT COALESCE(SUM(qty),0) AS b FROM stock_moves WHERE material_id=? AND COALESCE(location_id,'')=?",
                                 (mid, lid or ""))["b"], 3)

    def location_balances(self):
        """{material id: {place id («» — main): balance}} — only places where something is or was."""
        out = {}
        for r in self.db.q("""SELECT material_id, COALESCE(location_id,'') AS loc, SUM(qty) AS q FROM stock_moves
                              GROUP BY material_id, COALESCE(location_id,'')"""):
            out.setdefault(r["material_id"], {})[r["loc"]] = round(r["q"] or 0, 3)
        return out

    def locations(self, with_inactive=False):
        """The main stock first, then the cabinets and branches: how many materials are there and for how much."""
        rows = self.db.q("SELECT * FROM stock_locations WHERE (? OR active=1) ORDER BY sort, name", (1 if with_inactive else 0,))
        prices = {m["id"]: m["price"] or 0 for m in self.db.q("SELECT id, price FROM materials WHERE active=1")}
        bal = self.location_balances()
        stat = {}
        for mid, by in bal.items():
            if mid not in prices:
                continue
            for loc, q in by.items():
                s = stat.setdefault(loc, {"items": 0, "value": 0.0, "negative": 0})
                if abs(q) > 1e-9:
                    s["items"] += 1
                if q > 0:
                    s["value"] += q * prices[mid]
                elif q < -1e-9:
                    s["negative"] += 1
        main = {"id": "", "name": MAIN, "kind": "main", "kind_title": "Основной", "branch_id": "", "chair": "", "active": 1, "comment": ""}
        out = []
        for r in [main] + rows:
            s = stat.get(r["id"], {"items": 0, "value": 0.0, "negative": 0})
            out.append({**r, "kind_title": r.get("kind_title") or LOC_KINDS.get(r["kind"], r["kind"]),
                        "items": s["items"], "value": round(s["value"], 2), "negative": s["negative"]})
        return out

    def save_location(self, f):
        name = _clean(f.get("name"), 100)
        if not name:
            raise ValueError("Укажите название места хранения")
        if name.lower() == MAIN.lower():
            raise ValueError(f"«{MAIN}» уже есть")
        lid = str(f.get("id") or "") or _id("L")
        # SQLite lower() knows only Latin letters: compare in Python so that «кабинет 1» is «Кабинет 1»
        dup = any(r["name"].casefold() == name.casefold() for r in self.db.q("SELECT name FROM stock_locations WHERE id<>? AND active=1", (lid,)))
        if dup:
            raise ValueError(f"Место «{name}» уже есть")
        kind = f.get("kind") if f.get("kind") in LOC_KINDS else "cabinet"
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_locations(id, name, kind, branch_id, chair, active, sort, comment, created_at, updated_at)
                         VALUES(?,?,?,?,?,1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind,
                         branch_id=excluded.branch_id, chair=excluded.chair, sort=excluded.sort, comment=excluded.comment, active=1,
                         updated_at=excluded.updated_at""",
                      (lid, name, kind, _clean(f.get("branch_id"), 40), _clean(f.get("chair"), 100), int(_num(f.get("sort"), "Порядок")),
                       _clean(f.get("comment"), 300), _now(), _now()))
        return lid

    def delete_location(self, lid):
        """A place is closed only when it is empty: move what is left first (the history stays)."""
        if not self.db.one("SELECT 1 AS x FROM stock_locations WHERE id=?", (lid,)):
            raise ValueError("Место хранения не найдено")
        left = [m for m, by in self.location_balances().items() if abs(by.get(lid, 0)) > 1e-9
                and self.db.one("SELECT 1 AS x FROM materials WHERE id=? AND active=1", (m,))]
        if left:
            raise ValueError(f"В этом месте ещё есть материалы ({len(left)}). Сначала переместите их на другое место")
        with self.db.tx() as c:
            c.execute("UPDATE stock_locations SET active=0, updated_at=? WHERE id=?", (_now(), lid))
        return True

    def transfer(self, f, user=""):
        """Move materials from one place to another: one document, − there and + here; the clinic's balance does not change."""
        src, dst = self._loc(f.get("from_id")), self._loc(f.get("to_id"))
        if (src or "") == (dst or ""):
            raise ValueError("Выберите разные места: откуда и куда")
        lines = self._lines(f.get("lines"))
        need = {}
        for mid, q, _ in lines:
            if q <= 0:
                raise ValueError("Количество для перемещения должно быть больше нуля")
            need[mid] = need.get(mid, 0) + q
        for mid, q in need.items():
            have = self.location_balance(mid, src)
            if q > have + 1e-9:
                name = self.db.one("SELECT name FROM materials WHERE id=?", (mid,))["name"]
                raise ValueError(f"«{name}»: в месте «{self.location_name(src)}» {have:g}, переместить {q:g} нельзя")
        did, at = _id("T"), _now()
        day = f.get("date") or date.today().isoformat()
        prices = {r["id"]: r["price"] or 0 for r in self.db.q("SELECT id, price FROM materials")}
        total = round(sum(q * prices.get(mid, 0) for mid, q in need.items()), 2)
        why = f"{self.location_name(src)} → {self.location_name(dst)}"
        with self.db.tx() as c:
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                         location_id, to_location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (did, "transfer", self._next_number("transfer"), day, None, why, _clean(f.get("comment"), 500), total, user, at,
                       0, src, dst))
            for mid, q in need.items():
                for qty, loc in ((-q, src), (q, dst)):
                    c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, reason, user_name, at, location_id)
                                 VALUES(?,?,?,?,?,?,?,?,?)""", (mid, qty, prices.get(mid, 0), "transfer", did, why, user, f"{day} {at[11:]}", loc))
        return did

    # ================================================ norms + auto write-off --
    def norms(self, service_id=None):
        sql = """SELECT sm.*, m.name, m.unit, m.price, s.title AS service_title FROM service_materials sm
                 JOIN materials m ON m.id=sm.material_id JOIN services s ON s.id=sm.service_id WHERE m.active=1"""
        args = ()
        if service_id:
            sql += " AND sm.service_id=?"
            args = (service_id,)
        return self.db.q(sql + " ORDER BY s.title, m.name", args)

    def save_norms(self, service_id, items):
        if not self.db.one("SELECT 1 AS x FROM services WHERE id=?", (service_id,)):
            raise ValueError("Услуга не найдена")
        with self.db.tx() as c:
            c.execute("DELETE FROM service_materials WHERE service_id=?", (service_id,))
            for it in items or []:
                q = _num(it.get("qty"))
                if it.get("material_id") and q > 0:
                    c.execute("INSERT OR REPLACE INTO service_materials VALUES(?,?,?)", (service_id, it["material_id"], q))
        return self.norms(service_id)

    def on_invoice(self, invoice_id, user=""):
        """Bring the automatic write-off of an invoice in line with its current services."""
        inv = self.db.one("SELECT id, patient_id, visit_id, items, kind, created_at FROM invoices WHERE id=?", (invoice_id,))
        with self.db.tx() as c:
            c.execute("DELETE FROM stock_moves WHERE invoice_id=? AND kind='service'", (invoice_id,))
            if not inv or (inv["kind"] or "invoice") != "invoice":
                return 0
            need = {}
            titles = {}
            for it in json.loads(inv["items"] or "[]"):
                sid = it.get("service_id")
                if not sid:
                    continue
                qty = float(it.get("qty") or 1)
                for n in c.execute("SELECT material_id, qty FROM service_materials WHERE service_id=?", (sid,)).fetchall():
                    need[n[0]] = need.get(n[0], 0) + n[1] * qty
                    titles.setdefault(n[0], []).append(it.get("title") or "")
            loc = None
            if need and self.service_location is not None:
                try:
                    loc = self.service_location(inv) or None
                except Exception:  # noqa: BLE001 — the place never stops the write-off
                    loc = None
            for mid, q in need.items():
                price = (c.execute("SELECT price FROM materials WHERE id=? AND active=1", (mid,)).fetchone() or [None])[0]
                if price is None:
                    continue
                c.execute("""INSERT INTO stock_moves(material_id, qty, price, kind, invoice_id, patient_id, reason, user_name, at, location_id)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (mid, -round(q, 3), price or 0, "service", invoice_id, inv["patient_id"],
                           "; ".join(dict.fromkeys(titles[mid]))[:200], user, _now(), loc))
        return len(need)

    # ======================================================= purchase list --
    def offers(self):
        """The last purchase price of every material from every supplier: {material_id: [offer, …] cheapest first}."""
        rows = self.db.q("""SELECT m.material_id, d.supplier_id, s.name AS supplier_name, m.price, substr(m.at,1,10) AS day, m.id
                            FROM stock_moves m JOIN stock_docs d ON d.id = m.doc_id JOIN suppliers s ON s.id = d.supplier_id
                            WHERE m.kind='receipt' AND m.price > 0 AND s.active = 1 ORDER BY m.at, m.id""")
        last = {}
        for r in rows:  # later receipts overwrite earlier ones: one, latest price per supplier
            last[(r["material_id"], r["supplier_id"])] = r
        out = {}
        for r in last.values():
            out.setdefault(r["material_id"], []).append({"supplier_id": r["supplier_id"], "supplier_name": r["supplier_name"],
                                                         "price": r["price"], "date": r["day"]})
        for v in out.values():
            v.sort(key=lambda o: (o["price"], -date.fromisoformat(o["date"]).toordinal() if o["date"] else 0))
        return out

    def purchase_list(self, cover_days=30):
        """What to order now, grouped by the supplier: the material's main one (3.14) or the cheapest.

        Daily use = what services and write-offs took over the last 60 days / 60. Target stock = the optimal stock of the card
        (3.14) or max(2 × minimum, minimum + daily use × cover_days). A material is ordered when its usable stock (expired lots
        do not count) is at or below the minimum, or lasts fewer days than max(14, its delivery term). What is already ordered
        and on its way (3.14) counts as stock: neither ordered twice nor a reason to order."""
        try:
            cover = max(1, min(365, int(float(cover_days or 30))))
        except (TypeError, ValueError):
            cover = 30
        since = date.fromordinal(date.today().toordinal() - USAGE_DAYS).isoformat()
        used = {r["material_id"]: -r["q"] for r in self.db.q(
            """SELECT material_id, SUM(qty) AS q FROM stock_moves WHERE kind IN ('service','writeoff') AND substr(at,1,10) > ?
               GROUP BY material_id""", (since,))}
        offers = self.offers()
        sups = {s["id"]: s for s in self.suppliers()}
        transit = self.in_transit()
        groups = {}
        for m in self.materials():
            daily = max(0.0, used.get(m["id"], 0) or 0) / USAGE_DAYS
            on_way = transit.get(m["id"], 0.0)
            have = round(m["balance"] - m["expired_qty"], 3)
            soon = round(have + on_way, 3)
            days_left = round(soon / daily, 1) if daily > 0 else None
            mn = m["min_qty"] or 0
            lead = int(m.get("lead_days") or 0)
            if not (soon <= mn or (days_left is not None and days_left < max(MIN_DAYS_LEFT, lead))):
                continue
            target = (m.get("opt_qty") or 0) or max(mn * 2, mn + daily * cover)
            qty = math.ceil(round(target - max(0.0, soon), 6))
            if qty <= 0:
                continue
            offs = offers.get(m["id"], [])
            main = m.get("supplier_id") if m.get("supplier_id") in sups else None
            best = next((o for o in offs if o["supplier_id"] == main), None) if main else (offs[0] if offs else None)
            price = best["price"] if best else (m["price"] or 0)
            sid = main or (best["supplier_id"] if best else "")
            g = groups.setdefault(sid, {"supplier_id": sid, "supplier_name": (sups.get(sid) or {}).get("name") or "Поставщик не выбран",
                                        "phone": (sups.get(sid) or {}).get("phone", ""), "inn": (sups.get(sid) or {}).get("inn", ""),
                                        "lines": [], "total": 0})
            g["lines"].append({"material_id": m["id"], "code": m["code"], "number": m.get("number") or "", "name": m["name"], "unit": m["unit"],
                               "category": m["category"], "in_transit": on_way, "lead_days": lead, "main": bool(main),
                               "balance": m["balance"], "usable": have, "expired_qty": m["expired_qty"], "min_qty": mn,
                               "daily": round(daily, 3), "days_left": days_left, "target": round(target, 3), "qty": qty,
                               "price": price, "sum": round(qty * price, 2), "offers": offs,
                               "why": "ниже минимума" if soon <= mn else f"хватит на {days_left:g} дн."})
            g["total"] = round(g["total"] + qty * price, 2)
        out = sorted(groups.values(), key=lambda g: (not g["supplier_id"], g["supplier_name"]))
        return {"cover_days": cover, "groups": out, "count": sum(len(g["lines"]) for g in out),
                "total": round(sum(g["total"] for g in out), 2)}

    # ============================================================ scanner --
    def scan(self, code):
        """A barcode from the scanner → the material with this code (plain EAN or GTIN of a GS1 code) + lot and expiry."""
        p = parse_scan(code)
        if not p["code"]:
            raise ValueError("Пустой штрихкод")
        keys = [k for k in dict.fromkeys((p["code"], p["barcode"], p["gtin"], p["gtin"].lstrip("0"),
                                                  "0" + p["code"] if len(p["code"]) == 13 and p["code"].isdigit() else "")) if k]
        m = None
        for k in keys:
            m = self.db.one("SELECT id FROM materials WHERE barcode=? AND active=1", (k,))
            if m:
                break
        if not m and barcodes.valid_ean(p["code"]) and p["code"].startswith("29"):  # 3.14: the internal EAN of a label
            m = next(({"id": r["id"]} for r in self.db.q("SELECT id FROM materials WHERE active=1 AND COALESCE(barcode,'')=''")
                      if barcodes.internal_ean(r["id"]) == p["code"]), None)
        if not m:  # 3.14: the QR or the number «МТ-0147» of a material label
            k = self.material_by_code(code)
            m = {"id": k} if k else None
        mat = next((x for x in self.materials() if x["id"] == m["id"]), None) if m else None
        # 3.13: the QR of an equipment label opens its card
        return {**p, "material": mat, "equipment_id": None if mat else self.equipment_by_code(code)}

    def summary(self):
        mats = self.materials()
        today = date.today().isoformat()
        eq = self.equipment_list()
        return {"materials": len(mats), "low": sum(1 for m in mats if m["low"]),
                "expired": sum(1 for m in mats if m["exp_state"] == "expired"),
                "expiring": sum(1 for m in mats if m["exp_state"] == "soon"),
                "alerts": sum(1 for m in mats if m["low"] or m["balance"] < 0 or m["exp_state"]),
                "value": round(sum(m["value"] for m in mats if m["balance"] > 0), 2),
                "equipment": sum(1 for e in eq if e["status"] != "written_off"),
                "eq_repair": sum(1 for e in eq if e["status"] == "repair"),  # 3.14
                "eq_residual": round(sum(e["amort"]["residual"] for e in eq if e["status"] != "written_off"), 2),  # 3.10
                "eq_cost": round(sum(e["price"] or 0 for e in eq if e["status"] != "written_off"), 2),
                "service_due": sum(1 for e in eq if e["status"] != "written_off" and e["next_service"] and e["next_service"] <= today)}

    # ============================================================ equipment --
    def _eq_titles(self, r, today=None):
        today = today or date.today().isoformat()
        off = r["status"] == "written_off"
        r["status_title"] = EQ_DISPOSED.get(r.get("disposal_kind") or "writeoff", "Выбыло") if off else EQ_STATUS.get(r["status"], r["status"])
        r["service_due"] = bool(r["next_service"] and r["next_service"] <= today and not off)
        r["condition"] = r.get("condition") or "ok"
        r["ownership"] = r.get("ownership") or "own"
        r["condition_title"] = EQ_CONDITION.get(r["condition"], r["condition"])
        r["ownership_title"] = EQ_OWNERSHIP.get(r["ownership"], r["ownership"])
        r["amort"] = amortization(r)  # 3.10
        r["accounting"] = r.get("accounting") or "amort"  # 3.15
        r["accounting_title"] = EQ_ACCOUNTING.get(r["accounting"], r["accounting"])
        r["third_party"] = r["ownership"] in OFF_BOOKS
        r["qty"] = r.get("qty") or 1
        r["money"] = True
        return r

    @staticmethod
    def hide_money(e):
        """3.13: the equipment without its money — for someone without «Бухгалтерия»."""
        for r in e if isinstance(e, list) else [e]:
            if not r:
                continue
            for k in (*EQ_MONEY, "amort", "amort_schedule", "chair_hour_cost"):
                r.pop(k, None)
            r["money"] = False
        return e

    def equipment_list(self, q="", show_written_off=False, money=True):
        rows = self.db.q("SELECT * FROM equipment ORDER BY CASE status WHEN 'written_off' THEN 1 ELSE 0 END, location, name")
        today = date.today().isoformat()
        last = {r["equipment_id"]: r["d"] for r in self.db.q(  # 3.14: «Инвентаризация → Оборудование»
            "SELECT equipment_id, MAX(date) AS d FROM equipment_events WHERE kind='inventory' GROUP BY equipment_id")}
        names = self._loc_names()
        for r in rows:
            self._eq_titles(r, today)
            r["last_inventory_date"] = last.get(r["id"], "")
            r["location_name"] = names.get(r.get("location_id")) if r.get("location_id") else (r["location"] or "")  # 3.15
        if not show_written_off:
            rows = [r for r in rows if r["status"] != "written_off"]
        q = (q or "").strip().lower()
        if q:
            rows = [r for r in rows if q in f"{r['inv_number']} {r['name']} {r['model']} {r['serial']} {r['location']} {r['manufacturer']}".lower()]
        return rows if money else self.hide_money(rows)

    def equipment(self, eid, money=True):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (eid,))
        if not e:
            return e
        self._eq_titles(e)
        e["amort_schedule"] = amort_schedule(e)  # 3.10: depreciation and its months
        e["events"] = self.db.q("SELECT * FROM equipment_events WHERE equipment_id=? ORDER BY date DESC, id DESC", (eid,))
        for ev in e["events"]:
            ev["kind_title"] = EQ_EVENTS.get(ev["kind"], ev["kind"])
            try:
                ev["data"] = json.loads(ev.get("data") or "null")
            except ValueError:
                ev["data"] = None
        # 3.13: documents, the photo gallery, the year's service costs, the chair hour
        docs = self.db.q("""SELECT d.*, f.ext, f.size, f.orig_name FROM equipment_docs d LEFT JOIN patient_files f ON f.id = d.file_id
                            WHERE d.equipment_id=? AND d.deleted=0 ORDER BY d.created_at, d.id""", (eid,))
        for d in docs:
            d["kind_title"] = EQ_DOC_KINDS.get(d["kind"], d["kind"])
            d["image"] = (d.get("ext") or "") in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
        e["docs"] = docs
        have = {d["kind"] for d in docs} | ({"photo"} if e.get("photo_id") else set())
        e["doc_kinds"] = [{"kind": k, "title": EQ_DOC_KINDS[k], "count": sum(1 for d in docs if d["kind"] == k)} for k in EQ_DOC_KINDS]
        e["doc_count"], e["doc_total"] = sum(1 for k in EQ_DOC_MAIN if k in have), len(EQ_DOC_MAIN)
        e["photos"] = list(dict.fromkeys(x for x in [e.get("photo_id")] + [d["file_id"] for d in docs if d["kind"] == "photo"] if x))
        year_ago = (date.today() - timedelta(days=365)).isoformat()
        work = [ev for ev in e["events"] if ev["kind"] in ("service", "repair")]
        e["service_cost_year"] = round(sum(ev["cost"] or 0 for ev in work if (ev["date"] or "") >= year_ago), 2)
        e["service_count_year"] = sum(1 for ev in work if (ev["date"] or "") >= year_ago)
        inv = next((ev for ev in e["events"] if ev["kind"] == "inventory"), None)
        e["last_inventory"] = {"date": inv["date"], "found": bool((inv["data"] or {}).get("found", True)),
                               "diffs": (inv["data"] or {}).get("diffs", []), "user_name": inv["user_name"]} if inv else None
        e["chair_hours"] = self.chair_hours()
        a = e["amort"]
        e["chair_hour_cost"] = round(a["monthly"] / e["chair_hours"], 2) if a["on"] and e["chair_hours"] else 0.0
        if e.get("location_id"):
            p = self.db.one("SELECT name FROM stock_locations WHERE id=?", (e["location_id"],))
            e["location_name"] = p["name"] if p else e["location"]
        else:
            e["location_name"] = e["location"] or ""
        return e if money else self.hide_money(e)

    def _eq_live(self, eid):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (str(eid or ""),))
        if not e:
            raise ValueError("Оборудование не найдено")
        if e["status"] == "written_off":
            raise ValueError("Оборудование выбыло — изменить его нельзя")
        return e

    def _eq_place(self, f, old=None):
        """(location_id, location text): a place of «Места хранения» or a free text («Кабинет 1 · Кресло 1»)."""
        old = old or {}
        if "location_id" in f and f.get("location_id") not in (None, ""):
            p = self.db.one("SELECT id, name FROM stock_locations WHERE id=?", (str(f.get("location_id")),))
            if not p:
                raise ValueError("Такого места нет в «Местах хранения»")
            return p["id"], p["name"]
        if "location" in f:
            loc = _clean(f.get("location"), 100)
            keep = "location_id" not in f and loc == (old.get("location") or "")
            return (old.get("location_id") or "") if keep else "", loc
        if "location_id" in f:  # «— не указано —»
            return "", ""
        return old.get("location_id") or "", old.get("location") or ""

    def save_equipment(self, f, user="", money=True):
        """The card of a piece of equipment. `money` (3.13) — the author has «Бухгалтерия»: without it the cost, the
        depreciation and the replacement money are neither taken from the form nor changed."""
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите название оборудования")
        eid = f.get("id")
        old = self.db.one("SELECT * FROM equipment WHERE id=?", (eid,)) if eid else None
        if old and old["status"] == "written_off":
            raise ValueError("Списанное оборудование изменить нельзя")
        inv = _clean(f.get("inv_number"), 50) or (old["inv_number"] if old and old["inv_number"] else self._next_inv(_clean(f.get("category"), 100)))
        dup = self.db.one("SELECT id FROM equipment WHERE inv_number=? AND id<>?", (inv, eid or ""))
        if dup:
            raise ValueError(f"Инвентарный номер {inv} уже занят")
        status = f.get("status") or (old["status"] if old else "in_use")
        if status not in EQ_STATUS or status == "written_off":
            status = old["status"] if old else "in_use"
        o = old or {}
        lid, loc = self._eq_place(f, o)
        price = max(0, _num(f.get("price"), "Стоимость")) if money else float(o.get("price") or 0)

        def keep(k, fn):
            return fn(f.get(k)) if k in f else (o.get(k) if o.get(k) is not None else "")
        cut = lambda n: (lambda v: _clean(v, n))  # noqa: E731
        vals = (inv, name, keep("category", cut(100)), keep("model", cut(100)), keep("serial", cut(100)), loc,
                keep("responsible", cut(100)), keep("purchase_date", cut(10)), price, keep("warranty_until", cut(10)),
                keep("next_service", cut(10)), status, keep("comment", cut(1000)))
        cond = f.get("condition") if f.get("condition") in EQ_CONDITION else (o.get("condition") or "ok")
        own = f.get("ownership") if f.get("ownership") in EQ_OWNERSHIP else (o.get("ownership") or "own")
        extra = {"manufacturer": keep("manufacturer", cut(100)), "ownership": own, "condition": cond, "location_id": lid,
                 "replace_date": keep("replace_date", lambda v: _day(v, "Плановая дата замены") if v else ""),
                 # 3.15: the accounting, someone else's property and its contract, the person responsible, the quantity
                 "contractor": keep("contractor", cut(200)), "contract_no": keep("contract_no", cut(60)),
                 "use_start": keep("use_start", lambda v: _day(v, "Начало использования") if v else ""),
                 "use_end": keep("use_end", lambda v: _day(v, "Окончание использования") if v else ""),
                 "responsible_login": keep("responsible_login", cut(60)),
                 "qty": max(1, int(_num(f.get("qty"), "Количество") or 1)) if "qty" in f else (o.get("qty") or 1)}
        if money:  # the way it is accounted for changes its depreciation: only with «Бухгалтерия»
            acc = f.get("accounting") if f.get("accounting") in EQ_ACCOUNTING else (o.get("accounting") or "amort")
            extra["accounting"] = acc
        elif not old:
            extra["accounting"] = "amort"
        if money:
            for k, title in (("market_value", "Рыночная стоимость"), ("replace_cost", "Стоимость замены"),
                             ("reserve_monthly", "Резерв на обновление")):
                if k in f:
                    extra[k] = max(0, _num(f.get(k), title))
        amort = self._amort_fields(f, price) if money else None
        in_service = _day(f.get("in_service"), "Дата ввода в эксплуатацию") if not money and f.get("in_service") else None
        today = date.today().isoformat()
        ev = "INSERT INTO equipment_events(equipment_id, kind, date, text, user_name, created_at) VALUES(?,?,?,?,?,?)"
        with self.db.tx() as c:
            if old:
                c.execute("""UPDATE equipment SET inv_number=?, name=?, category=?, model=?, serial=?, location=?, responsible=?,
                             purchase_date=?, price=?, warranty_until=?, next_service=?, status=?, comment=? WHERE id=?""", (*vals, eid))
            else:
                eid = _id("E")
                c.execute("""INSERT INTO equipment(inv_number, name, category, model, serial, location, responsible, purchase_date,
                             price, warranty_until, next_service, status, comment, id, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (*vals, eid, _now()))
                c.execute(ev, (eid, "created", today, f"Инв. № {inv}" + (f" · {loc}" if loc else ""), user, _now()))
            c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in extra)} WHERE id=?", (*extra.values(), eid))
            if amort is not None:
                c.execute("UPDATE equipment SET in_service=?, useful_months=?, salvage=?, amort_method=? WHERE id=?", (*amort, eid))
            elif in_service:
                c.execute("UPDATE equipment SET in_service=? WHERE id=?", (in_service, eid))
            # 3.16: every change is a line of the log with «было → стало» (equipment_events.data)
            ch = lambda t, a, b: {"changes": [{"t": t, "old": a, "new": b}]}  # noqa: E731
            if old and (old["location"] or "") != loc:
                self._ev(c, eid, "move", f"{old['location'] or '—'} → {loc or '—'}", user, today,
                         data=ch("Место", old["location"] or "—", loc or "—"))
            if old and old["status"] != status:
                self._ev(c, eid, "status", f"{EQ_STATUS[old['status']]} → {EQ_STATUS[status]}", user, today,
                         data=ch("Статус", EQ_STATUS[old["status"]], EQ_STATUS[status]))
            if old and (old.get("condition") or "ok") != cond:
                self._ev(c, eid, "condition", f"{EQ_CONDITION[old.get('condition') or 'ok']} → {EQ_CONDITION[cond]}", user, today,
                         data=ch("Состояние", EQ_CONDITION[old.get("condition") or "ok"], EQ_CONDITION[cond]))
            if old:
                new = dict(c.execute("SELECT * FROM equipment WHERE id=?", (eid,)).fetchone())
                diff = eq_changes(old, new)
                if diff:
                    data = {"changes": diff}
                    past = [x["t"].lower() for x in diff if x["f"] in EQ_PAST]
                    if past and amortization(old)["months_done"] > 0:  # «подозрительное»: the past months change
                        data["flag"] = f"Изменено задним числом ({', '.join(past)}): меняется амортизация прошлых месяцев"
                    self._ev(c, eid, "edit", "Изменено: " + ", ".join(x["t"].lower() for x in diff), user, today, data=data)
        return eid

    @staticmethod
    def _amort_fields(f, price):
        """3.10: (in service, useful life in months, salvage value, method) from the form; None — the form has none of them."""
        keys = ("in_service", "useful_months", "useful_years", "salvage", "amort_method")
        if not any(k in f for k in keys):
            return None
        months = f.get("useful_months")
        if months in (None, "") and f.get("useful_years") not in (None, ""):
            months = _num(f.get("useful_years"), "Срок полезного использования") * 12
        months = int(round(_num(months, "Срок полезного использования"))) if months not in (None, "") else 0
        if months < 0 or months > MAX_USEFUL_MONTHS:
            raise ValueError(f"Срок полезного использования — от 1 месяца до {MAX_USEFUL_MONTHS // 12} лет")
        salvage = max(0, _num(f.get("salvage"), "Ликвидационная стоимость"))
        if months and salvage > price:
            raise ValueError("Ликвидационная стоимость больше стоимости оборудования")
        day = _day(f.get("in_service"), "Дата ввода в эксплуатацию") if f.get("in_service") else ""
        method = f.get("amort_method") if f.get("amort_method") in AMORT_METHODS else "linear"
        return day or None, months or None, salvage, method

    def amort_month(self, month):
        return amort_month(self.db, month)

    def capex_candidates(self):
        """3.14: expenses that look like the purchase of a piece of equipment — the same sum (±1 ₽) within 45 days of its
        purchase or putting into service — but are written down under another category. Next to the depreciation they would
        count the equipment twice; «Перенести» moves them into «Покупка оборудования»."""
        from accounting import CAPEX, SALARY
        eq = [e for e in self.db.q("SELECT * FROM equipment WHERE COALESCE(price,0) > 0") if on_books(e)]
        if not eq:
            return []
        try:
            exps = self.db.q("SELECT * FROM expenses WHERE category NOT IN (?, ?) ORDER BY date", (CAPEX, SALARY))
        except Exception:  # noqa: BLE001 — no accounting tables
            return []
        out, used = [], set()
        for x in exps:
            try:
                xd = date.fromisoformat(str(x["date"])[:10])
            except ValueError:
                continue
            for e in eq:
                day = e.get("purchase_date") or e.get("in_service")
                if e["id"] in used or not day or abs((x["amount"] or 0) - (e["price"] or 0)) > 1:
                    continue
                try:
                    if abs((xd - date.fromisoformat(str(day)[:10])).days) > CAPEX_DAYS:
                        continue
                except ValueError:
                    continue
                used.add(e["id"])
                out.append({"expense_id": x["id"], "date": x["date"], "category": x["category"], "amount": x["amount"],
                            "comment": x["comment"] or "", "equipment_id": e["id"], "name": e["name"], "inv_number": e["inv_number"],
                            "purchase_date": day})
                break
        return out

    def amort_report(self, m_from=None, m_to=None):
        """Depreciation by months for every piece: the charge of each month, the total so far and the book value today."""
        t = date.today()
        a = _mon(m_to) if m_to else _mon(t.isoformat())
        b = _mon(m_from) if m_from else (a - 11 if a is not None else None)
        if a is None or b is None:
            raise ValueError("Укажите месяцы, например 2026-01")
        b, a = min(a, b), max(a, b)
        b = max(b, a - 35)  # at most three years at a time
        months = [_mon_str(k) for k in range(b, a + 1)]
        rows = []
        off = 0
        for e in self.db.q("SELECT * FROM equipment ORDER BY name"):
            am = amortization(e)
            if not am["on"]:
                continue
            if not on_books(e):  # 3.14: rented or the founder's — not in the clinic's depreciation
                off += 1
                continue
            vals = [amort_charge(e, m) for m in months]
            rows.append({"id": e["id"], "inv_number": e["inv_number"], "name": e["name"], "status": e["status"],
                         "status_title": EQ_STATUS.get(e["status"], e["status"]), "cost": am["cost"], "monthly": am["monthly"],
                         "accumulated": am["accumulated"], "residual": am["residual"], "last": am["last"], "done": am["done"],
                         "values": vals, "total": round(sum(vals), 2)})
        no = self.db.one("""SELECT COUNT(*) AS n FROM equipment WHERE status<>'written_off' AND COALESCE(price,0)>0
                            AND COALESCE(useful_months,0)=0""")["n"]
        return {"months": months, "rows": rows, "totals": [round(sum(r["values"][i] for r in rows), 2) for i in range(len(months))],
                "total": round(sum(r["total"] for r in rows), 2), "cost": round(sum(r["cost"] for r in rows), 2),
                "accumulated": round(sum(r["accumulated"] for r in rows), 2), "residual": round(sum(r["residual"] for r in rows), 2),
                "this_month": self.amort_month(t.strftime("%Y-%m")), "without_life": no, "off_books": off}

    # ---------------------------------------- 3.13: inventory numbers, settings --
    _INV = re.compile(r"^(.*?)(\d+)$")

    def _next_inv(self, category=""):
        """The next inventory number: the prefix of the last numbered piece goes on (СТ-001 → СТ-002, the width of the
        digits kept); numbers of digits only go on as before (00001 → 00002); the very first one is ОБ-001.
        3.16: a category in an inventory group («Справочники») takes the group's code: СТ-001, СТ-002…"""
        rows = self.db.q("SELECT inv_number, created_at FROM equipment WHERE COALESCE(inv_number,'')<>'' ORDER BY created_at, rowid")
        grp = next((g for g in self.eq_groups() if category and category in g["categories"]), None)
        if grp:
            prefix = f"{grp['code']}-"
            used = {str(r["inv_number"]).strip() for r in rows}
            same = [m[2] for r in rows if (m := self._INV.match(str(r["inv_number"]).strip())) and m[1] == prefix]
            nxt, width = max((int(n) for n in same), default=0) + 1, max((len(n) for n in same), default=3)
            while f"{prefix}{str(nxt).zfill(width)}" in used:
                nxt += 1
            return f"{prefix}{str(nxt).zfill(width)}"
        if not rows:
            return INV_FIRST
        parsed = [(m[1], m[2]) for r in rows if (m := self._INV.match(str(r["inv_number"]).strip()))]
        pref = [p for p in parsed if p[0]]
        if pref:
            prefix = pref[-1][0]
            same = [n for p, n in pref if p == prefix]
            nxt, width = max(int(n) for n in same) + 1, max(len(n) for n in same)
            used = {str(r["inv_number"]).strip() for r in rows}
            while f"{prefix}{str(nxt).zfill(width)}" in used:
                nxt += 1
            return f"{prefix}{str(nxt).zfill(width)}"
        nums = [int(n) for p, n in parsed if not p]
        return str(max(nums, default=0) + 1).zfill(5) if nums else INV_FIRST

    def next_inv(self, category=""):
        return self._next_inv(_clean(category, 100))

    # ---------------------------------------------------------- 3.15: «Обзор» --
    def equipment_overview(self, money=True):
        """The director's page of the section: the whole property without opening a card — how many, in what condition, what
        it cost and is worth now (money only with «Бухгалтерия»), by category, what is due soon and what needs attention."""
        today = date.today()
        t, soon30, soon60 = today.isoformat(), (today + timedelta(days=30)).isoformat(), (today + timedelta(days=60)).isoformat()
        rows = self.equipment_list("", False, True)
        names = self._loc_names()
        live = [e for e in rows if e["status"] != "written_off"]
        cond = {"ok": 0, "service": 0, "faulty": 0}
        for e in live:
            k = "faulty" if e["status"] == "repair" or e["condition"] == "faulty" else e["condition"]
            cond[k if k in cond else "ok"] += 1
        own = [e for e in live if on_books(e)]
        cats = {}
        for e in live:
            g = cats.setdefault(e["category"] or "Без категории", {"name": e["category"] or "Без категории", "count": 0, "cost": 0.0, "residual": 0.0})
            g["count"] += e["qty"]
            if on_books(e):
                g["cost"] = round(g["cost"] + (e["price"] or 0), 2)
                g["residual"] = round(g["residual"] + (e["amort"]["residual"] if e["amort"]["on"] else (e["price"] or 0)), 2)
        total_cost = round(sum(g["cost"] for g in cats.values()), 2)
        for g in cats.values():
            g["share"] = round(g["cost"] * 100 / total_cost, 1) if total_cost else 0.0
        by_cat = sorted(cats.values(), key=lambda g: (-g["cost"], -g["count"], g["name"]))
        month = today.strftime("%Y-%m")
        full = [e for e in own if e["amort"]["on"] and e["amort"]["done"]]
        # what is due: service by the card and by the schedule, verification, replacement, the end of a lease or of a warranty
        ev = []
        lbl = lambda e: f"{e['name']}{' ' + e['inv_number'] if e['inv_number'] else ''}"  # noqa: E731
        for e in live:
            if e["next_service"] and e["next_service"] <= soon60:
                ev.append({"date": e["next_service"], "kind": "service", "title": "Техническое обслуживание", "equipment_id": e["id"], "name": lbl(e)})
            if e.get("replace_date") and e["replace_date"] <= (today + timedelta(days=120)).isoformat():
                ev.append({"date": e["replace_date"], "kind": "replace", "title": "Плановая замена", "equipment_id": e["id"], "name": lbl(e)})
            if e.get("use_end") and e["use_end"] <= soon60:
                ev.append({"date": e["use_end"], "kind": "use_end", "title": {"lease": "Окончание аренды", "leasing": "Завершение лизинга"}.get(
                    e["ownership"], "Окончание пользования"), "equipment_id": e["id"], "name": lbl(e)})
            if e.get("warranty_until") and t <= e["warranty_until"] <= soon30:
                ev.append({"date": e["warranty_until"], "kind": "warranty", "title": "Окончание гарантии", "equipment_id": e["id"], "name": lbl(e)})
        by_id = {e["id"]: e for e in live}
        for p in self.db.q("SELECT * FROM equipment_plans WHERE active=1 AND COALESCE(next_date,'')<>'' AND next_date<=?", (soon60,)):
            e = by_id.get(p["equipment_id"])
            if e:
                ev.append({"date": p["next_date"], "kind": "plan_" + (p["kind"] or "service"), "title": PLAN_KINDS.get(p["kind"], "Плановое ТО"),
                           "equipment_id": e["id"], "name": lbl(e)})
        ev.sort(key=lambda x: (x["date"], x["name"]))
        for x in ev:
            x["overdue"] = x["date"] < t
        # to replace: depreciated in full, the useful life runs out within half a year, a replacement planned within a year
        repl = []
        for e in own:
            a = e["amort"]
            why = ""
            if a["on"] and a["done"]:
                why = "Амортизировано 100 %"
            elif a["on"] and a["months_left"] <= 6:
                why = f"Срок службы истекает: осталось {a['months_left']} мес."
            elif e.get("replace_date") and e["replace_date"] <= (today + timedelta(days=365)).isoformat():
                why = f"Плановая замена {e['replace_date']}"
            if why:
                repl.append({"id": e["id"], "name": e["name"], "inv_number": e["inv_number"], "photo_id": e.get("photo_id") or "", "why": why,
                             "urgent": bool(a["on"] and a["done"]), "replace_date": e.get("replace_date") or ""})
        repl.sort(key=lambda x: (not x["urgent"], x["replace_date"] or "9999", x["name"]))
        reqs = self.db.q("""SELECT r.*, e.name AS equipment_name, e.inv_number FROM equipment_requests r LEFT JOIN equipment e ON e.id = r.equipment_id
                            ORDER BY r.created_at DESC LIMIT 6""")
        for r in reqs:
            r["kind_title"] = REQ_KINDS.get(r["kind"], r["kind"])
            r["status_title"] = REQ_STATUS.get(r["status"], r["status"])
            r["overdue"] = r["status"] in ("new", "work") and bool(r["due"]) and r["due"] < t
        open_rep = self.db.one("SELECT COUNT(*) AS n FROM equipment_requests WHERE status IN ('new','work') AND kind='repair'")["n"]
        out = {"total": sum(e["qty"] for e in live), "cards": len(live), "condition": cond, "full_amort": len(full),
               "by_category": by_cat, "events": ev[:12], "to_replace": repl, "requests": reqs,
               "attention": {"service_soon": sum(1 for x in ev if x["kind"] in ("service", "plan_service", "plan_verify", "plan_check") and t <= x["date"] <= soon30),
                             "service_overdue": sum(1 for x in ev if x["kind"] in ("service", "plan_service", "plan_verify", "plan_check") and x["overdue"]),
                             "repairs_open": open_rep, "to_replace": len(repl)},
               "third_party": sum(1 for e in live if e["third_party"]), "places": len({e.get("location_id") or e["location"] for e in live})}
        if money:
            out["money"] = {"cost": total_cost, "residual": round(sum(g["residual"] for g in cats.values()), 2),
                            "monthly": round(sum(amort_charge(e, month) for e in own), 2)}
        return out

    # ------------------------------------------------------ 3.15: «Поступление» --
    _RCPT_TEXT = {"name": 200, "category": 100, "manufacturer": 100, "model": 100, "serial": 100, "inv_number": 50, "responsible": 100}

    def _receipt_lines(self, lines, old_lines=None, money=True):
        """The lines of a receipt: what came (name, category, model, serial, quantity, price) and how it is accounted for (inv. №,
        useful life, the way, the place, the day it was put into service). Without «Бухгалтерия» the money of a line is kept."""
        old = {str(x.get("key")): x for x in (old_lines or [])}
        out = []
        for i, ln in enumerate(lines or []):
            ln = ln if isinstance(ln, dict) else {}
            name = _clean(ln.get("name"), 200)
            if not name:
                continue
            key = str(ln.get("key") or f"L{i + 1}-{uuid.uuid4().hex[:6]}")
            o = old.get(key, {})
            row = {"key": key, **{k: _clean(ln.get(k), n) for k, n in self._RCPT_TEXT.items()},
                   "qty": max(1, int(_num(ln.get("qty"), "Количество") or 1)),
                   "accounting": ln.get("accounting") if ln.get("accounting") in EQ_ACCOUNTING else (o.get("accounting") or "amort"),
                   "location_id": str(ln.get("location_id") or "")[:60], "in_service": _day(ln.get("in_service"), "Ввод в эксплуатацию")}
            if money:
                row["price"] = max(0, _num(ln.get("price"), "Цена"))
                n = int(_num(ln.get("useful_months"), "Срок полезного использования") or 0)
                if not 0 <= n <= MAX_USEFUL_MONTHS:
                    raise ValueError("Срок полезного использования — от 0 до 600 месяцев")
                row["useful_months"] = n
            else:
                row["price"], row["useful_months"] = o.get("price") or 0, o.get("useful_months") or 0
            out.append(row)
        return out

    def _receipt_row(self, r, sups=None, money=True):
        r = dict(r)
        r["lines"] = _jl(r.get("lines"), [])
        r["equipment_ids"] = _jl(r.get("equipment_ids"), [])
        r["status_title"] = RECEIPT_STATUS.get(r["status"], r["status"])
        r["doc_kind_title"] = RECEIPT_DOCS.get(r.get("doc_kind"), r.get("doc_kind") or "")
        sups = sups if sups is not None else {s["id"]: s["name"] for s in self.db.q("SELECT id, name FROM suppliers")}
        r["supplier_name"] = sups.get(r.get("supplier_id")) or ""
        r["positions"] = sum(int(x.get("qty") or 1) for x in r["lines"])
        r["lines_total"] = round(sum((x.get("price") or 0) * int(x.get("qty") or 1) for x in r["lines"]), 2)
        if not money:
            r.pop("amount", None)
            r.pop("lines_total", None)
            for x in r["lines"]:
                x.pop("price", None)
        return r

    def eq_receipts(self, year=None, money=True):
        y = str(year or date.today().year)
        sups = {s["id"]: s["name"] for s in self.db.q("SELECT id, name FROM suppliers")}
        rows = [self._receipt_row(r, sups, money) for r in self.db.q(
            "SELECT * FROM equipment_receipts WHERE status<>'cancelled' ORDER BY COALESCE(doc_date,''), created_at DESC")]
        rows = [r for r in rows if r["status"] == "process"] + sorted([r for r in rows if r["status"] != "process"],
                                                                     key=lambda r: r.get("doc_date") or "", reverse=True)
        period = [r for r in rows if (r.get("doc_date") or r["created_at"] or "")[:4] == y]
        out = {"year": int(y), "receipts": rows, "count": len(period), "accepted": sum(1 for r in period if r["status"] == "accepted"),
               "process": sum(1 for r in rows if r["status"] == "process"), "docs": RECEIPT_DOCS, "steps": RECEIPT_STEPS}
        if money:
            out["total"] = round(sum(r.get("amount") or r.get("lines_total") or 0 for r in period), 2)
        return out

    def eq_receipt(self, rid, money=True):
        r = self.db.one("SELECT * FROM equipment_receipts WHERE id=?", (str(rid or ""),))
        if not r:
            raise ValueError("Поступление не найдено")
        return self._receipt_row(r, money=money)

    def eq_receipt_save(self, f, user="", money=True):
        """A receipt step by step: the documents (supplier, the kind, number and date, the sum), the equipment, its accounting.
        It stays «В процессе» until «Ввести в эксплуатацию»."""
        f = f if isinstance(f, dict) else {}
        rid = str(f.get("id") or "")
        old = self.db.one("SELECT * FROM equipment_receipts WHERE id=?", (rid,)) if rid else None
        if old and old["status"] != "process":
            raise ValueError("Поступление уже проведено — изменить его нельзя")
        o = dict(old or {})
        sid = str(f.get("supplier_id") if "supplier_id" in f else o.get("supplier_id") or "").strip() or None
        if sid and not self.db.one("SELECT 1 AS x FROM suppliers WHERE id=?", (sid,)):
            raise ValueError("Поставщик не найден")
        kind = f.get("doc_kind") if f.get("doc_kind") in RECEIPT_DOCS else (o.get("doc_kind") or "contract")
        num = _clean(f.get("doc_number"), 60) if "doc_number" in f else (o.get("doc_number") or "")
        if not num:
            raise ValueError("Укажите номер документа")
        if not sid:
            raise ValueError("Выберите поставщика")
        dday = _day(f.get("doc_date"), "Дата документа") if f.get("doc_date") else (o.get("doc_date") or date.today().isoformat())
        amount = max(0, _num(f.get("amount"), "Сумма по документу")) if money and "amount" in f else (o.get("amount") or 0)
        lines = self._receipt_lines(f.get("lines"), _jl(o.get("lines"), []), money) if "lines" in f else _jl(o.get("lines"), [])
        step = max(int(o.get("step") or 1), min(4, max(1, int(_num(f.get("step")) or 1))))
        at = _now()
        with self.db.tx() as c:
            if old:
                c.execute("""UPDATE equipment_receipts SET supplier_id=?, doc_kind=?, doc_number=?, doc_date=?, amount=?, comment=?, lines=?,
                             step=?, updated_at=? WHERE id=?""",
                          (sid, kind, num, dday, amount, _clean(f.get("comment"), 500) if "comment" in f else o.get("comment") or "",
                           json.dumps(lines, ensure_ascii=False), step, at, rid))
            else:
                rid = _id("ER")
                yy = dday[2:4]
                n = c.execute("SELECT COUNT(*) FROM equipment_receipts WHERE substr(COALESCE(doc_date,''),1,4)=?", (dday[:4],)).fetchone()[0] + 1
                c.execute("""INSERT INTO equipment_receipts(id, number, supplier_id, doc_kind, doc_number, doc_date, amount, comment, lines, step,
                             status, equipment_ids, user_name, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (rid, f"П-{n:05d}/{yy}", sid, kind, num, dday, amount, _clean(f.get("comment"), 500),
                           json.dumps(lines, ensure_ascii=False), step, "process", "[]", user, at, at))
        return rid

    def eq_receipt_accept(self, rid, user="", money=True):
        """«Ввести в эксплуатацию»: every line becomes a card (one per unit; counted by quantity — one card with its quantity),
        put into service on its day and place, with its inventory number; the receipt is «Принято»."""
        r = self.db.one("SELECT * FROM equipment_receipts WHERE id=?", (str(rid or ""),))
        if not r:
            raise ValueError("Поступление не найдено")
        if r["status"] != "process":
            raise ValueError("Поступление уже проведено")
        lines = _jl(r["lines"], [])
        if not lines:
            raise ValueError("Добавьте оборудование — шаг «Оборудование»")
        ids = []
        for ln in lines:
            units = 1 if ln.get("accounting") == "qty" else int(ln.get("qty") or 1)
            for k in range(units):
                f = {"name": ln["name"], "category": ln.get("category"), "manufacturer": ln.get("manufacturer"), "model": ln.get("model"),
                     "serial": ln.get("serial") if units == 1 else "", "responsible": ln.get("responsible"),
                     "purchase_date": r["doc_date"], "in_service": ln.get("in_service") or r["doc_date"], "status": "in_use",
                     "qty": ln.get("qty") if ln.get("accounting") == "qty" else 1, "accounting": ln.get("accounting") or "amort",
                     "inv_number": ln.get("inv_number") if k == 0 else "", "price": ln.get("price") or 0,
                     "useful_months": ln.get("useful_months") or 0}
                if ln.get("location_id"):
                    f["location_id"] = ln["location_id"]
                eid = self.save_equipment(f, user, money=True)  # the receipt's prices were set by «Бухгалтерия» (or kept)
                ids.append(eid)
        with self.db.tx() as c:
            for eid in ids:
                c.execute("UPDATE equipment SET receipt_id=? WHERE id=?", (r["id"], eid))
                self._ev(c, eid, "created", f"Поступление {r['number']}: {RECEIPT_DOCS.get(r['doc_kind'], '')} № {r['doc_number']}", user,
                         r["doc_date"])
            c.execute("UPDATE equipment_receipts SET status='accepted', step=4, equipment_ids=?, accepted_at=?, updated_at=? WHERE id=?",
                      (json.dumps(ids), _now(), _now(), r["id"]))
        return ids

    def eq_receipt_cancel(self, rid):
        r = self.db.one("SELECT * FROM equipment_receipts WHERE id=?", (str(rid or ""),))
        if not r or r["status"] != "process":
            raise ValueError("Отменить можно только поступление в процессе")
        with self.db.tx() as c:
            c.execute("UPDATE equipment_receipts SET status='cancelled', updated_at=? WHERE id=?", (_now(), r["id"]))
        return True

    # ------------------------------------------------------ 3.15: «Перемещения» --
    def _move_row(self, r, names, eqs):
        r = dict(r)
        e = eqs.get(r["equipment_id"]) or {}
        r["equipment_name"] = e.get("name") or "удалённое оборудование"
        r["inv_number"] = e.get("inv_number") or ""
        r["photo_id"] = e.get("photo_id") or ""
        r["from_name"] = names.get(r.get("from_location_id")) if r.get("from_location_id") else (r.get("from_text") or "—")
        r["to_name"] = names.get(r.get("to_location_id")) or "—"
        today = date.today().isoformat()
        r["planned"] = r["status"] == "approved" and (r.get("date") or "") > today
        r["status_title"] = "Запланировано" if r["planned"] else MOVE_STATUS.get(r["status"], r["status"])
        r["stage"] = {"requested": 1, "approved": 2, "moving": 3, "done": 4}.get(r["status"], 0)
        return r

    def eq_moves(self, year=None, equipment_id=None):
        y = str(year or date.today().year)
        names = self._loc_names()
        eqs = {e["id"]: e for e in self.db.q("SELECT id, name, inv_number, photo_id FROM equipment")}
        sql, args = "SELECT * FROM equipment_moves WHERE status<>'cancelled'", []
        if equipment_id:
            sql += " AND equipment_id=?"
            args.append(equipment_id)
        rows = [self._move_row(r, names, eqs) for r in self.db.q(sql + " ORDER BY date DESC, created_at DESC", args)]
        period = [r for r in rows if (r.get("date") or "")[:4] == y]
        return {"year": int(y), "moves": rows, "count": len(period), "done": sum(1 for r in period if r["status"] == "done"),
                "process": sum(1 for r in rows if r["status"] in ("requested", "moving") or (r["status"] == "approved" and not r["planned"])),
                "planned": sum(1 for r in rows if r["planned"]), "statuses": MOVE_STATUS, "reasons": MOVE_REASONS}

    def eq_move_save(self, f, user="", login="", approve=False):
        """«Создать перемещение»: from where the piece is now to another place, on a day, for a reason. Approved by someone with
        «Оборудование: согласование» (the author with that right — at once); only then it may be moved."""
        f = f if isinstance(f, dict) else {}
        e = self._eq_live(f.get("equipment_id"))
        to = self.db.one("SELECT id, name FROM stock_locations WHERE id=?", (str(f.get("to_location_id") or ""),))
        if not to:
            raise ValueError("Выберите, куда переместить (место из «Мест хранения»)")
        if to["id"] == (e["location_id"] or ""):
            raise ValueError("Оборудование уже там")
        if self.db.one("SELECT 1 AS x FROM equipment_moves WHERE equipment_id=? AND status IN ('requested','approved','moving')", (e["id"],)):
            raise ValueError("По этому оборудованию уже есть незавершённое перемещение")
        reason = _clean(f.get("reason"), 200)
        if not reason:
            raise ValueError("Укажите основание перемещения")
        day = _day(f.get("date"), "Дата перемещения") or date.today().isoformat()
        n = self.db.one("SELECT COUNT(*) AS n FROM equipment_moves")["n"] + 1
        mid, at = _id("EM"), _now()
        with self.db.tx() as c:
            c.execute("""INSERT INTO equipment_moves(id, number, equipment_id, from_location_id, from_text, to_location_id, date, reason,
                         responsible, comment, status, created_by, created_name, created_at, approved_by, approved_name, approved_at, updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (mid, f"ПМ-{n:04d}", e["id"], e["location_id"] or "", e["location"] or "", to["id"], day, reason,
                       _clean(f.get("responsible"), 150), _clean(f.get("comment"), 250), "approved" if approve else "requested",
                       login, user, at, login if approve else None, user if approve else None, at if approve else None, at))
        if approve and f.get("now"):
            self.eq_move_step(mid, "done", user)
        return mid

    def eq_move_decide(self, mid, action, answer="", login="", user=""):
        m = self.db.one("SELECT * FROM equipment_moves WHERE id=?", (str(mid or ""),))
        if not m or m["status"] != "requested":
            raise ValueError("Перемещение не ждёт утверждения")
        if action not in ("approve", "reject"):
            raise ValueError("Утвердить или отклонить")
        if action == "reject" and not _clean(answer):
            raise ValueError("Напишите, почему отклонено")
        with self.db.tx() as c:
            c.execute("""UPDATE equipment_moves SET status=?, approved_by=?, approved_name=?, approved_at=?, answer=?, updated_at=? WHERE id=?""",
                      ("approved" if action == "approve" else "rejected", login, user, _now(), _clean(answer, 300), _now(), m["id"]))
        return m["id"]

    def eq_move_step(self, mid, step, user=""):
        """«Начать перемещение» (approved → moving) and «Подтвердить» (→ done: the card gets its new place, a line of history)."""
        m = self.db.one("SELECT * FROM equipment_moves WHERE id=?", (str(mid or ""),))
        if not m:
            raise ValueError("Перемещение не найдено")
        if step == "moving" and m["status"] != "approved":
            raise ValueError("Начать можно утверждённое перемещение")
        if step == "done" and m["status"] not in ("approved", "moving"):
            raise ValueError("Подтвердить можно утверждённое перемещение")
        if step not in ("moving", "done"):
            raise ValueError("Неизвестный этап")
        if step == "done":
            e = self._eq_live(m["equipment_id"])
            to = self.db.one("SELECT id, name FROM stock_locations WHERE id=?", (m["to_location_id"],))
            with self.db.tx() as c:
                c.execute("UPDATE equipment SET location_id=?, location=? WHERE id=?", (to["id"], to["name"], e["id"]))
                self._ev(c, e["id"], "move", f"{m['number']}: {e['location'] or '—'} → {to['name']} ({m['reason']})", user)
                c.execute("UPDATE equipment_moves SET status='done', done_at=?, updated_at=? WHERE id=?", (_now(), _now(), m["id"]))
        else:
            with self.db.tx() as c:
                c.execute("UPDATE equipment_moves SET status='moving', updated_at=? WHERE id=?", (_now(), m["id"]))
        return m["id"]

    def eq_move_cancel(self, mid):
        m = self.db.one("SELECT * FROM equipment_moves WHERE id=?", (str(mid or ""),))
        if not m or m["status"] not in ("requested", "approved"):
            raise ValueError("Отменить можно перемещение до его начала")
        with self.db.tx() as c:
            c.execute("UPDATE equipment_moves SET status='cancelled', updated_at=? WHERE id=?", (_now(), m["id"]))
        return True

    # ---------------------------------------------- 3.15: «Обслуживание и ремонт» --
    def _req_row(self, r, eqs, today):
        r = dict(r)
        e = eqs.get(r["equipment_id"]) or {}
        r["equipment_name"], r["inv_number"], r["photo_id"] = e.get("name") or "удалённое оборудование", e.get("inv_number") or "", e.get("photo_id") or ""
        r["kind_title"] = REQ_KINDS.get(r["kind"], r["kind"])
        r["priority_title"] = PRIORITY.get(r["priority"], PRIORITY["mid"])
        r["overdue"] = r["status"] in ("new", "work") and bool(r["due"]) and r["due"] < today
        r["status_title"] = "Просрочено" if r["overdue"] else REQ_STATUS.get(r["status"], r["status"])
        return r

    def eq_requests(self, year=None, equipment_id=None):
        """Requests for repair, service and diagnostics with the year's figures, the service schedule (the plans and the dates of the
        cards) and what service and repair cost this year and the year before."""
        y = int(year or date.today().year)
        today = date.today().isoformat()
        eqs = {e["id"]: e for e in self.db.q("SELECT id, name, inv_number, photo_id, next_service, status FROM equipment")}
        sql, args = "SELECT * FROM equipment_requests WHERE status<>'cancelled'", []
        if equipment_id:
            sql += " AND equipment_id=?"
            args.append(equipment_id)
        rows = [self._req_row(r, eqs, today) for r in self.db.q(sql + " ORDER BY created_at DESC", args)]
        regs = {p["id"]: p.get("reg_id") for p in self.db.q("SELECT id, reg_id FROM equipment_plans")}
        by_reg = {g["id"]: g for g in self.eq_regs()}
        for r in rows:  # 3.16: the checklist of the regulation of the schedule — ticked when the request is done
            g = by_reg.get(regs.get(r.get("plan_id")) or "")
            r["checklist"] = list(g["checklist"]) if g and r["status"] in ("new", "work") else []
            r["reg_name"] = g["name"] if g else ""
        period = [r for r in rows if (r["created_at"] or "")[:4] == str(y)]
        sched = self.eq_schedule()
        cost = lambda yy: round(self.db.one("""SELECT COALESCE(SUM(cost),0) AS v FROM equipment_events WHERE kind IN ('service','repair','diag')
                                                AND substr(date,1,4)=?""", (str(yy),))["v"] or 0, 2)  # noqa: E731
        now_c, prev_c = cost(y), cost(y - 1)
        return {"year": y, "requests": rows, "total": len(period), "done": sum(1 for r in period if r["status"] == "done"),
                "work": sum(1 for r in rows if r["status"] in ("new", "work") and not r["overdue"]),
                "overdue": sum(1 for r in rows if r["overdue"]), "schedule": sched,
                "next_service": next((x["date"] for x in sched if x["date"] >= today), ""),
                "cost": now_c, "cost_prev": prev_c, "cost_change": round((now_c - prev_c) * 100 / prev_c, 1) if prev_c else None,
                "kinds": REQ_KINDS, "priorities": PRIORITY, "statuses": REQ_STATUS}

    def eq_request_save(self, f, user="", login="", report_only=False):
        """A request: repair («Сообщить о неисправности» of a nurse is one too), service or diagnostics. A repair request marks the
        piece «Неисправно» until it is done."""
        f = f if isinstance(f, dict) else {}
        e = self._eq_live(f.get("equipment_id"))
        kind = "repair" if report_only else (f.get("kind") if f.get("kind") in REQ_KINDS else "repair")
        text = _clean(f.get("description"), 500)
        if not text:
            raise ValueError("Опишите проблему или работу")
        pr = f.get("priority") if f.get("priority") in PRIORITY else "mid"
        due = _day(f.get("due"), "Желаемая дата выполнения")
        plan = str(f.get("plan_id") or "") or None
        if plan and not self.db.one("SELECT 1 AS x FROM equipment_plans WHERE id=? AND equipment_id=?", (plan, e["id"])):
            plan = None
        n = self.db.one("SELECT COUNT(*) AS n FROM equipment_requests WHERE kind=?", (kind,))["n"] + 1
        rid, at = _id("RQ"), _now()
        with self.db.tx() as c:
            c.execute("""INSERT INTO equipment_requests(id, number, equipment_id, kind, description, priority, due, responsible, plan_id, status,
                         cost, created_by, created_name, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (rid, f"{REQ_PREFIX[kind]}-{n:03d}", e["id"], kind, text, pr, due, _clean(f.get("responsible"), 150), plan, "new", 0,
                       login, user, at, at))
            # 3.16: the log shows who asked for the work («Создание заявки»)
            self._ev(c, e["id"], "request", f"{REQ_PREFIX[kind]}-{n:03d} ({REQ_KINDS[kind].lower()}): {text}", user,
                     data={"module": "Обслуживание", "request": f"{REQ_PREFIX[kind]}-{n:03d}"})
            if kind == "repair" and (e["condition"] or "ok") != "faulty":
                c.execute("UPDATE equipment SET condition='faulty' WHERE id=?", (e["id"],))
                self._ev(c, e["id"], "condition", f"{EQ_CONDITION.get(e['condition'] or 'ok')} → {EQ_CONDITION['faulty']}: {text}", user)
        return rid

    def eq_request_status(self, rid, status, f=None, user=""):
        """«В работу» (a repair sends the piece to «В ремонте»), «Выполнено» (the cost and the result go to the history like a service
        or a repair; the piece is back in use and «Исправно»; a request of the schedule moves its next date on), «Отменить»."""
        f = f if isinstance(f, dict) else {}
        r = self.db.one("SELECT * FROM equipment_requests WHERE id=?", (str(rid or ""),))
        if not r:
            raise ValueError("Заявка не найдена")
        if r["status"] in ("done", "cancelled"):
            raise ValueError("Заявка уже закрыта")
        if status not in ("work", "done", "cancelled"):
            raise ValueError("Неизвестный статус")
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (r["equipment_id"],))
        at, day = _now(), date.today().isoformat()
        with self.db.tx() as c:
            if status == "work":
                c.execute("UPDATE equipment_requests SET status='work', started_at=?, updated_at=? WHERE id=?", (at, at, r["id"]))
                if r["kind"] == "repair" and e and e["status"] == "in_use":
                    c.execute("UPDATE equipment SET status='repair' WHERE id=?", (e["id"],))
                    self._ev(c, e["id"], "status", f"{EQ_STATUS['in_use']} → {EQ_STATUS['repair']} ({r['number']})", user)
            elif status == "cancelled":
                c.execute("UPDATE equipment_requests SET status='cancelled', updated_at=? WHERE id=?", (at, r["id"]))
            else:
                cost = max(0, _num(f.get("cost"), "Сумма"))
                result = _clean(f.get("result"), 500) or r["description"]
                day = _day(f.get("date"), "Дата") or day
                # 3.16: the checklist of the regulation the plan follows — what was done, a line of the history
                checks = [{"t": _clean(x.get("t"), 120), "ok": bool(x.get("ok"))} for x in (f.get("checklist") or [])
                          if isinstance(x, dict) and _clean(x.get("t"), 120)][:40]
                if checks:
                    result = _clean(f"{result}. Чек-лист: {sum(1 for x in checks if x['ok'])} из {len(checks)}", 500)
                c.execute("UPDATE equipment_requests SET status='done', cost=?, result=?, done_at=?, updated_at=? WHERE id=?",
                          (cost, result, f"{day} {at[11:]}", at, r["id"]))
                if e:
                    self._ev(c, e["id"], "service" if r["kind"] == "service" else "repair" if r["kind"] == "repair" else "diag",
                             f"{r['number']}: {result}", user, day, cost,
                             data={"module": "Обслуживание", "request": r["number"], **({"checklist": checks} if checks else {})})
                    if e["status"] == "repair" or r["kind"] == "repair":
                        c.execute("UPDATE equipment SET status=CASE WHEN status='repair' THEN 'in_use' ELSE status END, condition='ok' WHERE id=?", (e["id"],))
                    if r["plan_id"]:
                        p = c.execute("SELECT every_months, next_date FROM equipment_plans WHERE id=?", (r["plan_id"],)).fetchone()
                        if p and p[0]:
                            k = _mon(day) + int(p[0])
                            y_, m_ = divmod(k, 12)
                            d_ = min(int(day[8:10]), calendar.monthrange(y_, m_ + 1)[1])
                            c.execute("UPDATE equipment_plans SET next_date=?, updated_at=? WHERE id=?", (date(y_, m_ + 1, d_).isoformat(), at, r["plan_id"]))
                    self._sync_next_service(c, e["id"])
        return r["id"]

    def _sync_next_service(self, c, eid):
        """The card's «Следующее ТО» is the nearest date of its schedule of service (when it has one)."""
        nxt = c.execute("SELECT MIN(next_date) FROM equipment_plans WHERE equipment_id=? AND active=1 AND kind='service' AND COALESCE(next_date,'')<>''",
                        (eid,)).fetchone()[0]
        if nxt:
            c.execute("UPDATE equipment SET next_service=? WHERE id=?", (nxt, eid))

    def eq_plans(self):
        eqs = {e["id"]: e for e in self.db.q("SELECT id, name, inv_number, status FROM equipment")}
        regs = {g["id"]: g["name"] for g in self.eq_regs()}
        out = []
        for p in self.db.q("SELECT * FROM equipment_plans WHERE active=1 ORDER BY next_date"):
            e = eqs.get(p["equipment_id"])
            if not e or e["status"] == "written_off":
                continue
            out.append({**p, "equipment_name": e["name"], "inv_number": e["inv_number"] or "", "kind_title": PLAN_KINDS.get(p["kind"], p["kind"]),
                        "reg_name": regs.get(p.get("reg_id") or "", "")})
        return out

    def eq_schedule(self):
        """«График технического обслуживания»: the plans (ТО, поверка, осмотр) and the cards' own next service where there is no plan."""
        today = date.today().isoformat()
        rows = [{"date": p["next_date"], "equipment_id": p["equipment_id"], "name": p["equipment_name"], "inv_number": p["inv_number"],
                 "kind": p["kind"], "kind_title": p["kind_title"], "plan_id": p["id"], "every": p["every_months"]} for p in self.eq_plans() if p["next_date"]]
        planned = {r["equipment_id"] for r in rows if r["kind"] == "service"}
        for e in self.db.q("SELECT id, name, inv_number, next_service FROM equipment WHERE status<>'written_off' AND COALESCE(next_service,'')<>''"):
            if e["id"] not in planned:
                rows.append({"date": e["next_service"], "equipment_id": e["id"], "name": e["name"], "inv_number": e["inv_number"] or "",
                             "kind": "service", "kind_title": "Плановое ТО", "plan_id": None, "every": 0})
        for r in rows:
            r["overdue"] = r["date"] < today
        return sorted(rows, key=lambda r: (r["date"], r["name"]))

    def eq_due(self):
        """3.16 «Контроль сроков ТО и уведомления»: the service, verification and inspection overdue or due within the set days
        (the plans of the schedule and the cards' own next service) and the open requests past their date — the bell of the
        section, the badge of the menu and a line of the day report. Off — nothing."""
        m = self.eq_module()
        if not m["control_to"]:
            return {"on": False, "days": m["to_days"], "items": [], "overdue": 0, "soon": 0}
        today = date.today()
        t, lim = today.isoformat(), (today + timedelta(days=m["to_days"])).isoformat()
        items = [{"date": x["date"], "equipment_id": x["equipment_id"], "name": x["name"], "inv_number": x["inv_number"],
                  "title": x["kind_title"], "kind": x["kind"], "overdue": x["overdue"]} for x in self.eq_schedule() if x["date"] <= lim]
        eqs = {e["id"]: e for e in self.db.q("SELECT id, name, inv_number FROM equipment WHERE status<>'written_off'")}
        for r in self.db.q("""SELECT * FROM equipment_requests WHERE status IN ('new','work') AND COALESCE(due,'')<>'' AND due < ?
                              ORDER BY due""", (t,)):
            e = eqs.get(r["equipment_id"])
            if e:
                items.append({"date": r["due"], "equipment_id": e["id"], "name": e["name"], "inv_number": e["inv_number"] or "",
                              "title": f"Заявка {r['number']} не выполнена", "kind": "request", "overdue": True})
        items.sort(key=lambda x: (not x["overdue"], x["date"], x["name"]))
        return {"on": True, "days": m["to_days"], "items": items, "overdue": sum(1 for x in items if x["overdue"]),
                "soon": sum(1 for x in items if not x["overdue"]), "to_report": m["to_report"]}

    def eq_plan_save(self, f):
        f = f if isinstance(f, dict) else {}
        e = self._eq_live(f.get("equipment_id"))
        kind = f.get("kind") if f.get("kind") in PLAN_KINDS else "service"
        every = int(_num(f.get("every_months"), "Периодичность") or 0)
        if not 1 <= every <= 120:
            raise ValueError("Периодичность — от 1 до 120 месяцев")
        nxt = _day(f.get("next_date"), "Следующая дата")
        if not nxt:
            raise ValueError("Укажите дату следующего ТО")
        pid, at = str(f.get("id") or "") or _id("PL"), _now()
        reg = str(f.get("reg_id") or "")  # 3.16: the regulation (its checklist is ticked when the work is done)
        if reg and reg not in {g["id"] for g in self.eq_regs()}:
            reg = ""
        with self.db.tx() as c:
            c.execute("""INSERT INTO equipment_plans(id, equipment_id, kind, every_months, next_date, note, active, created_at, updated_at, reg_id)
                         VALUES(?,?,?,?,?,?,1,?,?,?) ON CONFLICT(id) DO UPDATE SET equipment_id=excluded.equipment_id, kind=excluded.kind,
                         every_months=excluded.every_months, next_date=excluded.next_date, note=excluded.note, active=1, updated_at=excluded.updated_at,
                         reg_id=excluded.reg_id""",
                      (pid, e["id"], kind, every, nxt, _clean(f.get("note"), 200), at, at, reg or None))
            self._sync_next_service(c, e["id"])
        return pid

    def eq_plan_delete(self, pid):
        with self.db.tx() as c:
            c.execute("UPDATE equipment_plans SET active=0, updated_at=? WHERE id=?", (_now(), str(pid or "")))
        return True

    def eq_confirm(self, eid, user=""):
        """The nurse confirms the piece is in its place (a line of «Инвентаризация» without changes)."""
        e = self._eq_live(eid)
        with self.db.tx() as c:
            self._ev(c, e["id"], "inventory", "Наличие подтверждено", user, data={"found": True, "diffs": [], "confirm": True})
        return e["id"]

    # ------------------------------------------------------ 3.15: «Амортизация» --
    def eq_amort_year(self, year=None):
        """The screen «Амортизация» of a year: the cost, the book value, the accumulated depreciation and the wear of the clinic's
        own equipment at the end of the year (today for this one), the depreciation by month with the running total, the cost by
        category, the key figures and the register split into «с амортизацией», «полностью амортизировано», «без амортизации»."""
        t = date.today()
        y = int(year or t.year)
        last = _mon(t.isoformat()) if y == t.year else _mon(f"{y}-12")
        months = [f"{y}-{m:02d}" for m in range(1, 13)]
        rows, cats = [], {}
        for e in self.db.q("SELECT * FROM equipment ORDER BY category, name"):
            if e["status"] == "written_off" and (e["writeoff_date"] or "")[:4] < str(y):
                continue
            self._eq_titles(e)
            am = amortization(e, _mon_str(last))
            own = on_books(e)
            why = ("Стороннее имущество" if e["ownership"] in OFF_BOOKS else "Количественный учёт" if e["accounting"] == "qty"
                   else "" if am["on"] else "Не указан срок" if (e["price"] or 0) > 0 else "Не указана стоимость")
            grp = "off" if why else "on" if not am["done"] else "done"  # someone else's property is never the clinic's depreciation
            r = {"id": e["id"], "inv_number": e["inv_number"] or "", "name": e["name"], "category": e["category"] or "", "photo_id": e.get("photo_id") or "",
                 "cost": am["cost"], "useful_months": am["useful_months"], "first": am["first"], "accumulated": am["accumulated"],
                 "residual": am["residual"] if am["on"] else (e["price"] or 0), "percent": am["percent"] if am["on"] else 0.0,
                 "monthly": am["monthly"] if am["on"] and not am["done"] else 0.0, "group": grp, "why": why, "own": own,
                 "status": e["status"], "status_title": e["status_title"], "values": [amort_charge(e, m) if own else 0.0 for m in months]}
            rows.append(r)
            if own and e["status"] != "written_off":
                g = cats.setdefault(e["category"] or "Без категории", {"name": e["category"] or "Без категории", "cost": 0.0, "count": 0})
                g["cost"] = round(g["cost"] + am["cost"], 2)
                g["count"] += 1
        live = [r for r in rows if r["own"] and r["status"] != "written_off"]
        on = [r for r in live if r["group"] != "off"]
        cost = round(sum(r["cost"] for r in live), 2)
        acc = round(sum(r["accumulated"] for r in on), 2)
        charge = [round(sum(r["values"][i] for r in rows), 2) for i in range(12)]
        running, cum = [], 0.0
        start = round(sum(r["accumulated"] for r in rows if r["own"]) - sum(charge), 2)  # what was accumulated before the year
        for v in charge:
            cum = round(cum + v, 2)
            running.append(round(start + cum, 2))
        tot = sum(g["cost"] for g in cats.values())
        by_cat = sorted(({**g, "share": round(g["cost"] * 100 / tot, 1) if tot else 0.0} for g in cats.values()), key=lambda g: -g["cost"])
        return {"year": y, "months": months, "charge": charge, "running": running, "upto": _mon_str(last) if y >= t.year else f"{y}-12",
                "cost": cost, "residual": round(cost - acc, 2), "accumulated": acc,
                "monthly": round(sum(amort_charge(r_e, t.strftime("%Y-%m")) for r_e in self.db.q("SELECT * FROM equipment") if on_books(r_e)), 2),
                "wear": round(acc * 100 / cost, 1) if cost else 0.0, "by_category": by_cat,
                "count_on": len(on), "count_done": sum(1 for r in live if r["group"] == "done"), "count_running": sum(1 for r in live if r["group"] == "on"),
                "count_off": sum(1 for r in rows if r["group"] == "off" and r["status"] != "written_off"),
                "avg_life": round(sum(r["useful_months"] for r in on) / len(on) / 12, 1) if on else 0.0,
                "avg_wear": round(sum(r["percent"] for r in on) / len(on), 1) if on else 0.0,
                "rows": [r for r in rows if r["status"] != "written_off"], "this_month": self.amort_month(t.strftime("%Y-%m"))}

    # ------------------------------------------------- 3.15: «Выбытие и списание» --
    def eq_disposals(self, year=None, money=True):
        y = str(year or date.today().year)
        names = self._loc_names()
        rows = []
        for e in self.db.q("SELECT * FROM equipment WHERE status='written_off' ORDER BY writeoff_date DESC, name"):
            self._eq_titles(e)
            kind = e.get("disposal_kind") or "writeoff"
            book = e["residual"] if e["residual"] is not None else amortization(e)["residual"]
            r = {"id": e["id"], "inv_number": e["inv_number"] or "", "name": e["name"], "photo_id": e.get("photo_id") or "", "date": e["writeoff_date"] or "",
                 "kind": kind, "kind_title": EQ_DISPOSAL.get(kind, kind), "status_title": e["status_title"], "act": e["writeoff_act"] or "",
                 "doc": ({"writeoff": "Акт списания", "utilize": "Акт утилизации", "transfer": "Акт передачи"}.get(kind, "") + (f" № {e['writeoff_act']}" if e["writeoff_act"] else "")) if kind in ("writeoff", "utilize", "transfer") else EQ_DISPOSAL.get(kind, kind),
                 "reason": e["writeoff_reason"] or "", "responsible": e.get("disposal_responsible") or "", "basis": e.get("disposal_basis") or "",
                 "location": names.get(e.get("location_id")) if e.get("location_id") else (e["location"] or "")}
            if money:
                r.update(cost=round(e["price"] or 0, 2), residual=round(book or 0, 2), amount=round(e["disposal_amount"] or 0, 2))
            rows.append(r)
        period = [r for r in rows if r["date"][:4] == y]
        out = {"year": int(y), "rows": rows, "count": len(period), "kinds": EQ_DISPOSAL,
               **{k: sum(1 for r in period if r["kind"] == k) for k in EQ_DISPOSAL}}
        if money:
            out["sum"] = round(sum(r["residual"] for r in period), 2)
        return out

    # ------------------------------------------------ 3.15: «Планирование закупок» --
    def _purchase_row(self, r, eqs):
        r = dict(r)
        r["offers"] = _jl(r.get("offers"), [])
        r["status_title"] = PURCHASE_STATUS.get(r["status"], r["status"])
        r["priority_title"] = PRIORITY.get(r["priority"], PRIORITY["mid"])
        r["funding_title"] = FUNDING.get(r["funding"], r["funding"] or "")
        e = eqs.get(r.get("replace_id")) or {}
        r["replace_name"] = f"{e.get('name')}{' ' + e['inv_number'] if e.get('inv_number') else ''}" if e else ""
        r["best_offer"] = min((o for o in r["offers"] if (o.get("price") or 0) > 0), key=lambda o: o["price"], default=None)
        return r

    def eq_purchases(self, year=None):
        """The plan of purchases of a year: what to buy, why, for how much, in which quarter, how urgent, from which money; the
        status (draft → on approval → approved / rejected → bought), the calendar by quarter, the budget by status and category,
        the nearest actions."""
        t = date.today()
        y = int(year or t.year)
        eqs = {e["id"]: e for e in self.db.q("SELECT id, name, inv_number FROM equipment")}
        rows = [self._purchase_row(r, eqs) for r in self.db.q(
            "SELECT * FROM equipment_purchases WHERE year=? AND status<>'cancelled' ORDER BY quarter, CASE priority WHEN 'high' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END, name", (y,))]
        live = [r for r in rows if r["status"] != "rejected"]
        total = round(sum(r["budget"] or 0 for r in live), 2)
        by_st = {k: round(sum(r["budget"] or 0 for r in live if (r["status"] == k or (k == "approved" and r["status"] == "bought"))), 2)
                 for k in ("approved", "pending", "draft")}
        cats = {}
        for r in live:
            g = cats.setdefault(r["category"] or "Без категории", {"name": r["category"] or "Без категории", "budget": 0.0})
            g["budget"] = round(g["budget"] + (r["budget"] or 0), 2)
        by_cat = sorted(({**g, "share": round(g["budget"] * 100 / total, 1) if total else 0.0} for g in cats.values()), key=lambda g: -g["budget"])
        acts = []
        for r in live:
            if r["status"] == "pending":
                acts.append({"kind": "approve", "title": f"Согласовать: {r['name']}", "id": r["id"], "date": r.get("sent_at", "")[:10]})
            elif r["status"] == "draft" and not r["offers"]:
                acts.append({"kind": "offers", "title": f"Подготовить КП: {r['name']}", "id": r["id"], "date": ""})
            elif r["status"] == "draft":
                acts.append({"kind": "send", "title": f"Отправить на согласование: {r['name']}", "id": r["id"], "date": ""})
            elif r["status"] == "approved":
                acts.append({"kind": "buy", "title": f"Закупить ({['I', 'II', 'III', 'IV'][(r['quarter'] or 1) - 1]} квартал): {r['name']}", "id": r["id"], "date": ""})
        return {"year": y, "rows": rows, "total": total, "count": len(live), "approved": sum(1 for r in live if r["status"] in ("approved", "bought")),
                "pending": sum(1 for r in live if r["status"] == "pending"), "draft": sum(1 for r in live if r["status"] == "draft"),
                "by_status": by_st, "by_category": by_cat,
                "by_quarter": [round(sum(r["budget"] or 0 for r in live if r["quarter"] == q), 2) for q in (1, 2, 3, 4)],
                "actions": acts[:6], "statuses": PURCHASE_STATUS, "priorities": PRIORITY, "funding": FUNDING}

    def eq_purchase_save(self, f, user="", login=""):
        f = f if isinstance(f, dict) else {}
        pid = str(f.get("id") or "")
        old = self.db.one("SELECT * FROM equipment_purchases WHERE id=?", (pid,)) if pid else None
        if old and old["status"] not in ("draft", "rejected"):
            raise ValueError("Закупку на согласовании или согласованную изменить нельзя — сначала верните её в черновик")
        name = _clean(f.get("name"), 200)
        if not name:
            raise ValueError("Укажите, что закупить")
        y = int(_num(f.get("year")) or date.today().year)
        q = int(_num(f.get("quarter")) or 1)
        if not 1 <= q <= 4:
            raise ValueError("Квартал — от I до IV")
        rep = str(f.get("replace_id") or "") or None
        if rep and not self.db.one("SELECT 1 AS x FROM equipment WHERE id=?", (rep,)):
            rep = None
        offers = []
        for o in (f.get("offers") if "offers" in f else _jl((old or {}).get("offers"), [])) or []:
            o = o if isinstance(o, dict) else {}
            sup = _clean(o.get("supplier"), 150)
            if not sup and not o.get("file_id"):
                continue
            offers.append({"supplier": sup, "price": max(0, _num(o.get("price"), "Цена КП")), "days": int(_num(o.get("days")) or 0),
                           "note": _clean(o.get("note"), 200), "file_id": str(o.get("file_id") or "")[:40], "file_name": _clean(o.get("file_name"), 120)})
        at = _now()
        vals = (name, _clean(f.get("reason"), 200), _clean(f.get("justification"), 1000), _clean(f.get("category"), 100),
                max(0, _num(f.get("budget"), "Бюджет")), y, q, f.get("priority") if f.get("priority") in PRIORITY else "mid",
                f.get("funding") if f.get("funding") in FUNDING else "own", rep, json.dumps(offers, ensure_ascii=False))
        with self.db.tx() as c:
            if old:
                c.execute("""UPDATE equipment_purchases SET name=?, reason=?, justification=?, category=?, budget=?, year=?, quarter=?, priority=?,
                             funding=?, replace_id=?, offers=?, status='draft', updated_at=? WHERE id=?""", (*vals, at, pid))
            else:
                pid = _id("PP")
                n = c.execute("SELECT COUNT(*) FROM equipment_purchases").fetchone()[0] + 1
                c.execute("""INSERT INTO equipment_purchases(name, reason, justification, category, budget, year, quarter, priority, funding, replace_id,
                             offers, id, number, status, created_by, created_name, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (*vals, pid, f"ЗК-{n:03d}", "draft", login, user, at, at))
        return pid

    def eq_purchase_status(self, pid, action, answer="", login="", user=""):
        """«На согласование» (with the reason and the budget), «Согласовать» / «Отклонить» (the right «Оборудование: согласование»),
        «Куплено», «В черновик», «Удалить» (a draft)."""
        r = self.db.one("SELECT * FROM equipment_purchases WHERE id=?", (str(pid or ""),))
        if not r:
            raise ValueError("Закупка не найдена")
        st, at = r["status"], _now()
        nxt = {("send", "draft"): "pending", ("send", "rejected"): "pending", ("approve", "pending"): "approved", ("reject", "pending"): "rejected",
               ("bought", "approved"): "bought", ("draft", "pending"): "draft", ("draft", "rejected"): "draft", ("draft", "approved"): "draft",
               ("delete", "draft"): "cancelled", ("delete", "rejected"): "cancelled"}.get((action, st))
        if not nxt:
            raise ValueError(f"Из статуса «{PURCHASE_STATUS.get(st, st)}» так нельзя")
        if action == "send" and not ((r["budget"] or 0) > 0 and (r["justification"] or r["reason"])):
            raise ValueError("Перед согласованием укажите бюджет и обоснование")
        if action == "reject" and not _clean(answer):
            raise ValueError("Напишите, почему отклонено")
        sets = {"status": nxt, "updated_at": at}
        if action == "send":
            sets["sent_at"] = at
        if action in ("approve", "reject"):
            sets.update(decided_by=login, decided_name=user, decided_at=at, answer=_clean(answer, 300))
        with self.db.tx() as c:
            c.execute(f"UPDATE equipment_purchases SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), r["id"]))
        return r["id"]

    def eq_purchase_offer_file(self, pid, file_id, name):
        r = self.db.one("SELECT * FROM equipment_purchases WHERE id=?", (str(pid or ""),))
        if not r:
            raise ValueError("Закупка не найдена")
        offers = _jl(r["offers"], [])
        offers.append({"supplier": "", "price": 0, "days": 0, "note": "", "file_id": file_id, "file_name": _clean(name, 120)})
        with self.db.tx() as c:
            c.execute("UPDATE equipment_purchases SET offers=?, updated_at=? WHERE id=?", (json.dumps(offers, ensure_ascii=False), _now(), r["id"]))
        return r["id"]

    # ------------------------------------------------ 3.15: «Стороннее оборудование» --
    THIRD = ("doctor", "lease", "leasing", "other", "owner")

    def eq_third_party(self):
        """What the clinic uses and does not own: the doctors' own, rented, in leasing, the founder's, any other use — who owns it,
        where it is, from when and till when, what it is worth (as the card says)."""
        t = date.today()
        today, soon = t.isoformat(), (t + timedelta(days=30)).isoformat()
        rows = []
        for e in self.equipment_list("", False, True):
            if e["ownership"] not in self.THIRD:
                continue
            end = e.get("use_end") or ""
            st = ("ended", "Окончено") if end and end < today else ("soon", "Истекает") if end and end <= soon else                 ("active", "Действует") if e["ownership"] in ("lease", "leasing") or end else ("use", "В пользовании")
            rows.append({"id": e["id"], "name": e["name"], "inv_number": e["inv_number"] or "", "photo_id": e.get("photo_id") or "",
                         "ownership": e["ownership"], "ownership_title": e["ownership_title"], "contractor": e.get("contractor") or "",
                         "contract_no": e.get("contract_no") or "", "place": e.get("location_name") or "", "start": e.get("use_start") or "",
                         "end": end, "status": st[0], "status_title": st[1], "price": e["price"] or 0})
        kinds = {k: sum(1 for r in rows if r["ownership"] == k) for k in self.THIRD}
        ev = sorted(({"date": r["end"], "title": {"lease": "Окончание аренды", "leasing": "Завершение лизинга"}.get(r["ownership"], "Окончание пользования"),
                      "name": f"{r['name']}{' ' + r['inv_number'] if r['inv_number'] else ''}", "id": r["id"], "overdue": r["end"] < today}
                     for r in rows if r["end"] and r["end"] <= (t + timedelta(days=180)).isoformat()), key=lambda x: x["date"])
        return {"rows": rows, "total": len(rows), "kinds": kinds, "titles": {k: EQ_OWNERSHIP[k] for k in self.THIRD},
                "cost": round(sum(r["price"] for r in rows), 2), "events": ev[:6]}

    # ---------------------------------------------------------- 3.15: «Документы» --
    def eq_all_docs(self):
        """Every document of the equipment in one list (passports, contracts, acts, warranties), the warranties that end within a
        month or have ended, and the pieces without a technical passport or a contract."""
        t = date.today()
        today, soon = t.isoformat(), (t + timedelta(days=30)).isoformat()
        eqs = {e["id"]: e for e in self.db.q("SELECT id, name, inv_number, status, warranty_until, photo_id FROM equipment")}
        docs = []
        for d in self.db.q("""SELECT d.*, f.ext, f.size FROM equipment_docs d LEFT JOIN patient_files f ON f.id = d.file_id
                              WHERE d.deleted=0 ORDER BY d.created_at DESC"""):
            e = eqs.get(d["equipment_id"]) or {}
            docs.append({**d, "kind_title": EQ_DOC_KINDS.get(d["kind"], d["kind"]), "equipment_name": e.get("name") or "удалённое оборудование",
                         "inv_number": e.get("inv_number") or "", "image": (d.get("ext") or "") in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")})
        have = {}
        for d in docs:
            have.setdefault(d["equipment_id"], set()).add(d["kind"])
        live = [e for e in eqs.values() if e["status"] != "written_off"]
        warr = sorted(({"id": e["id"], "name": e["name"], "inv_number": e["inv_number"] or "", "date": e["warranty_until"],
                        "ended": e["warranty_until"] < today} for e in live if e["warranty_until"] and e["warranty_until"] <= soon),
                      key=lambda x: x["date"])
        missing = [{"id": e["id"], "name": e["name"], "inv_number": e["inv_number"] or "",
                    "lack": [EQ_DOC_KINDS[k] for k in ("passport", "contract") if k not in have.get(e["id"], set())]} for e in live]
        return {"docs": docs, "kinds": EQ_DOC_KINDS, "counts": {k: sum(1 for d in docs if d["kind"] == k) for k in EQ_DOC_KINDS},
                "warranty": warr, "missing": [m for m in missing if m["lack"]]}

    # ------------------------------------------------------ 3.15: «Аналитика» --
    def eq_analytics(self, year=None, money=True):
        """What the equipment costs to keep: service, repair and diagnostics by month and by category, the most expensive pieces to
        maintain, the age of the fleet, the depreciation of the year and per chair hour (money only with «Бухгалтерия»)."""
        t = date.today()
        y = int(year or t.year)
        eqs = {e["id"]: e for e in self.db.q("SELECT * FROM equipment")}
        ev = self.db.q("""SELECT equipment_id, kind, date, cost FROM equipment_events WHERE kind IN ('service','repair','diag')
                          AND substr(date,1,4)=?""", (str(y),))
        by_m = [{"month": f"{y}-{m:02d}", "service": 0.0, "repair": 0.0, "diag": 0.0} for m in range(1, 13)]
        cats, top = {}, {}
        for x in ev:
            mi = int(x["date"][5:7]) - 1
            by_m[mi][x["kind"]] = round(by_m[mi][x["kind"]] + (x["cost"] or 0), 2)
            e = eqs.get(x["equipment_id"]) or {}
            c = cats.setdefault(e.get("category") or "Без категории", {"name": e.get("category") or "Без категории", "count": 0, "keep": 0.0,
                                                                        "repairs": 0, "amort": 0.0})
            c["keep"] = round(c["keep"] + (x["cost"] or 0), 2)
            c["repairs"] += 1 if x["kind"] == "repair" else 0
            g = top.setdefault(x["equipment_id"], {"id": x["equipment_id"], "name": e.get("name") or "—", "inv_number": e.get("inv_number") or "",
                                                   "cost": 0.0, "repairs": 0, "works": 0})
            g["cost"] = round(g["cost"] + (x["cost"] or 0), 2)
            g["works"] += 1
            g["repairs"] += 1 if x["kind"] == "repair" else 0
        ages = {"до 2 лет": 0, "3–5 лет": 0, "6–10 лет": 0, "больше 10 лет": 0, "дата не указана": 0}
        months = [f"{y}-{m:02d}" for m in range(1, 13)]
        amort_y = 0.0
        for e in eqs.values():
            if e["status"] == "written_off":
                continue
            c = cats.setdefault(e["category"] or "Без категории", {"name": e["category"] or "Без категории", "count": 0, "keep": 0.0, "repairs": 0, "amort": 0.0})
            c["count"] += 1
            if on_books(e):
                a_ = round(sum(amort_charge(e, m) for m in months), 2)
                c["amort"] = round(c["amort"] + a_, 2)
                amort_y += a_
            d0 = e.get("in_service") or e.get("purchase_date")
            if not d0:
                ages["дата не указана"] += 1
            else:
                yrs = (t - date.fromisoformat(d0[:10])).days / 365.25
                ages["до 2 лет" if yrs < 3 else "3–5 лет" if yrs < 6 else "6–10 лет" if yrs < 11 else "больше 10 лет"] += 1
        keep = round(sum(m["service"] + m["repair"] + m["diag"] for m in by_m), 2)
        out = {"year": y, "by_month": by_m, "keep": keep, "service": round(sum(m["service"] for m in by_m), 2),
               "repair": round(sum(m["repair"] for m in by_m), 2), "diag": round(sum(m["diag"] for m in by_m), 2),
               "repairs": sum(1 for x in ev if x["kind"] == "repair"), "works": len(ev),
               "by_category": sorted(cats.values(), key=lambda c: (-c["keep"], -c["count"])), "top": sorted(top.values(), key=lambda g: -g["cost"])[:8],
               "ages": [{"name": k, "count": v} for k, v in ages.items() if v or k != "дата не указана"]}
        if money:
            hours = self.chair_hours()
            out.update(amort=round(amort_y, 2), total=round(amort_y + keep, 2), chair_hours=hours,
                       chair_hour=round((self.amort_month(t.strftime("%Y-%m")) + keep / 12) / hours, 2) if hours else 0.0)
        else:
            for c in out["by_category"]:
                c.pop("amort", None)
        return out

    # ------------------------------------------------------ 3.15: «Журнал действий» --
    def eq_log(self, f=None):
        """Every event of every piece (put on the books, moved, serviced, repaired, counted, disposed, documents): who and when."""
        f = f if isinstance(f, dict) else {}
        sql = """SELECT ev.*, e.name, e.inv_number FROM equipment_events ev LEFT JOIN equipment e ON e.id = ev.equipment_id WHERE 1=1"""
        args = []
        if f.get("kind") in EQ_EVENTS:
            sql += " AND ev.kind=?"
            args.append(f["kind"])
        if f.get("from"):
            sql += " AND ev.date >= ?"
            args.append(_day(f["from"], "С"))
        if f.get("to"):
            sql += " AND ev.date <= ?"
            args.append(_day(f["to"], "По"))
        if f.get("user"):
            sql += " AND ev.user_name=?"
            args.append(_clean(f["user"], 100))
        rows = self.db.q(sql + " ORDER BY ev.date DESC, ev.id DESC LIMIT 500", args)
        for r in rows:
            r["kind_title"] = EQ_EVENTS.get(r["kind"], r["kind"])
            r["data"] = _jl(r.get("data"), {}) or None
        users = [r["u"] for r in self.db.q("SELECT DISTINCT user_name AS u FROM equipment_events WHERE COALESCE(user_name,'')<>'' ORDER BY u")]
        return {"rows": rows, "kinds": EQ_EVENTS, "users": users}

    # ------------------------------------------- 3.15: «Справочники и настройки» --
    def _setting(self, k, default):
        r = self.db.one("SELECT v FROM stock_settings WHERE k=?", (k,))
        try:
            v = json.loads(r["v"]) if r and r["v"] else default
        except ValueError:
            v = default
        return v if isinstance(v, type(default)) else default

    def _set_setting(self, c, k, v):
        c.execute("""INSERT INTO stock_settings(k, v, updated_at) VALUES(?,?,?)
                     ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at""", (k, json.dumps(v, ensure_ascii=False), _now()))

    def eq_categories(self):
        """The clinic's list of categories (by default the 13 of the mockups) and those already used in the cards."""
        own = [str(x) for x in self._setting("eq_categories", []) if str(x).strip()] or list(EQ_CATS)
        used = [r["category"] for r in self.db.q("SELECT DISTINCT category FROM equipment WHERE COALESCE(category,'')<>''")]
        return list(dict.fromkeys(own + sorted(x for x in used if x not in own)))

    def eq_life(self):
        """The usual useful life by category, in months: a hint in the card (the term itself is always set by hand)."""
        life = dict(EQ_LIFE)
        for k, v in self._setting("eq_life", {}).items():
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if 0 <= n <= MAX_USEFUL_MONTHS:
                life[str(k)] = n
        return {k: v for k, v in life.items() if v}

    def _own_list(self, k, default):
        """A reference of the clinic's own: the saved list (even an empty one), or the defaults until it is first saved."""
        r = self.db.one("SELECT v FROM stock_settings WHERE k=?", (k,))
        if not r:
            return [dict(x) if isinstance(x, dict) else x for x in default]
        v = _jl(r["v"], [])
        return v

    def eq_models(self):
        return [x for x in self._own_list("eq_models", []) if isinstance(x, dict) and (x.get("manufacturer") or x.get("model"))]

    def eq_groups(self):
        return [{**x, "categories": [str(c) for c in (x.get("categories") or []) if str(c).strip()]}
                for x in self._own_list("eq_groups", []) if isinstance(x, dict) and x.get("code")]

    def eq_works(self):
        dflt = [{"id": f"W{i + 1}", **w} for i, w in enumerate(EQ_WORKS)]
        return [x for x in self._own_list("eq_works", dflt) if isinstance(x, dict) and x.get("name")]

    def eq_regs(self):
        dflt = [{"id": f"R{i + 1}", **g} for i, g in enumerate(EQ_REGS)]
        return [{**x, "checklist": [str(t) for t in (x.get("checklist") or []) if str(t).strip()]}
                for x in self._own_list("eq_regs", dflt) if isinstance(x, dict) and x.get("name")]

    def eq_disp_reasons(self):
        return [str(x) for x in self._own_list("eq_disp_reasons", EQ_DISP_REASONS) if str(x).strip()]

    def eq_module(self):
        """3.16 «Основные настройки модуля»: what really changes the program's work (the depreciation in the P&L is the old
        switch `pnl_amort`)."""
        m = dict(EQ_MODULE)
        for k, v in self._setting("eq_module", {}).items():
            if k in EQ_MODULE and type(v) is type(EQ_MODULE[k]):
                m[k] = v
        m["round"] = m["round"] if m["round"] in EQ_ROUND else "rub"
        m["method"] = m["method"] if m["method"] in AMORT_METHODS else "linear"
        m["to_days"] = min(90, max(1, int(m["to_days"])))
        r = self.db.one("SELECT v FROM stock_settings WHERE k='pnl_amort'")
        m["auto_amort"] = not r or r["v"] != "0"
        return m

    def _log_settings(self, c, user, obj, module, changes, flag=""):
        """3.16: a change of the references or the settings is a line of «Журнал действий» (no piece of equipment)."""
        text = f"{obj}: " + "; ".join(f"{x['t']} {x['old']} → {x['new']}" for x in changes[:4]) + ("…" if len(changes) > 4 else "")
        data = {"object": obj, "module": module, "changes": changes}
        if flag:
            data["flag"] = flag
        self._ev(c, "", "settings", _clean(text, 500), user, data=data)

    def eq_module_save(self, f, user="", money=False):
        f = f if isinstance(f, dict) else {}
        old = self.eq_module()
        new = {k: old[k] for k in EQ_MODULE}
        for k in ("control_to", "to_report", "no_doc_disposal", "third_party"):
            if k in f:
                new[k] = bool(f[k])
        if "round" in f:
            if f["round"] not in EQ_ROUND:
                raise ValueError("Выберите округление сумм")
            new["round"] = f["round"]
        if "to_days" in f:
            n = int(_num(f["to_days"], "За сколько дней предупреждать") or 0)
            if not 1 <= n <= 90:
                raise ValueError("Предупреждать о ТО — за 1–90 дней")
            new["to_days"] = n
        if "method" in f:
            if f["method"] not in AMORT_METHODS:
                raise ValueError("Такого метода амортизации нет")
            if f["method"] != old["method"] and not money:
                raise ValueError("Метод амортизации меняет сотрудник с правом «Бухгалтерия»")
            new["method"] = f["method"]
        auto = old["auto_amort"]
        if "auto_amort" in f and bool(f["auto_amort"]) != auto:
            if not money:
                raise ValueError("Амортизацию в ОПиУ включает и выключает сотрудник с правом «Бухгалтерия»")
            auto = bool(f["auto_amort"])
        yn = lambda v: "вкл." if v else "выкл."  # noqa: E731
        titles = {"method": ("Метод амортизации", lambda v: AMORT_METHODS.get(v, v)), "round": ("Округление сумм", lambda v: EQ_ROUND.get(v, v)),
                  "control_to": ("Контроль сроков ТО", yn), "to_days": ("Предупреждать о ТО за, дней", str),
                  "to_report": ("ТО в отчёте за день", yn), "no_doc_disposal": ("Запрет списания без документа", yn),
                  "third_party": ("Учёт стороннего оборудования", yn)}
        changes = [{"t": t, "old": fm(old[k]), "new": fm(new[k])} for k, (t, fm) in titles.items() if new[k] != old[k]]
        if auto != old["auto_amort"]:
            changes.append({"t": "Автоматический расчёт амортизации", "old": yn(old["auto_amort"]), "new": yn(auto)})
        if not changes:
            return self.eq_module()
        with self.db.tx() as c:
            self._set_setting(c, "eq_module", new)
            if auto != old["auto_amort"]:
                c.execute("""INSERT INTO stock_settings(k, v, updated_at) VALUES('pnl_amort', ?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v,
                             updated_at=excluded.updated_at""", ("1" if auto else "0", _now()))
            self._log_settings(c, user, "Основные настройки модуля", "Настройки", changes,
                               flag="Выключен запрет списания без документа" if old["no_doc_disposal"] and not new["no_doc_disposal"] else "")
        return self.eq_module()

    # the references: what each list holds and how it is checked
    EQ_REF_TITLES = {"eq_models": "Модели и производители", "eq_groups": "Инвентарные группы", "eq_works": "Виды работ (ТО)",
                     "eq_regs": "Регламенты обслуживания", "eq_disp_reasons": "Причины выбытия"}

    def _check_ref(self, key, rows):
        rows = rows if isinstance(rows, list) else []
        out, seen = [], set()
        if key == "eq_disp_reasons":
            for x in rows:
                t = _clean(x, 150)
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    out.append(t)
            if not out:
                raise ValueError("Оставьте хотя бы одну причину выбытия")
            return out[:60]
        for x in rows:
            if not isinstance(x, dict):
                continue
            rid = _clean(x.get("id"), 40) or _id(key[3].upper())
            if key == "eq_models":
                mf, md = _clean(x.get("manufacturer"), 100), _clean(x.get("model"), 100)
                if not (mf or md):
                    continue
                k = f"{mf.lower()}|{md.lower()}"
                if k in seen:
                    raise ValueError(f"Модель «{mf} {md}» записана дважды")
                out.append({"id": rid, "manufacturer": mf, "model": md, "article": _clean(x.get("article"), 60),
                            "category": _clean(x.get("category"), 100)})
            elif key == "eq_groups":
                code = re.sub(r"\s+", "", _clean(x.get("code"), 8)).upper().rstrip("-")
                if not code:
                    continue
                if not re.fullmatch(r"[A-ZА-ЯЁ0-9]{1,6}", code):
                    raise ValueError(f"Код группы «{code}» — до 6 букв или цифр, например СТ")
                k = code
                if k in seen:
                    raise ValueError(f"Код группы {code} занят")
                cats = list(dict.fromkeys(_clean(cc, 100) for cc in (x.get("categories") or []) if _clean(cc, 100)))
                out.append({"id": rid, "code": code, "name": _clean(x.get("name"), 120) or code, "okof": _clean(x.get("okof"), 40),
                            "categories": cats})
            elif key == "eq_works":
                name = _clean(x.get("name"), 120)
                if not name:
                    continue
                k = name.lower()
                if k in seen:
                    raise ValueError(f"Вид работ «{name}» записан дважды")
                out.append({"id": rid, "name": name, "kind": x.get("kind") if x.get("kind") in REQ_KINDS else "service"})
            elif key == "eq_regs":
                name = _clean(x.get("name"), 120)
                if not name:
                    continue
                k = name.lower()
                if k in seen:
                    raise ValueError(f"Регламент «{name}» записан дважды")
                every = int(_num(x.get("every_months"), "Периодичность") or 0)
                if not 1 <= every <= 120:
                    raise ValueError(f"«{name}»: периодичность — от 1 до 120 месяцев")
                checks = list(dict.fromkeys(_clean(t, 120) for t in (x.get("checklist") or []) if _clean(t, 120)))[:40]
                out.append({"id": rid, "name": name, "kind": x.get("kind") if x.get("kind") in PLAN_KINDS else "service",
                            "every_months": every, "category": _clean(x.get("category"), 100), "checklist": checks})
            else:
                raise ValueError("Неизвестный справочник")
            seen.add(k)
        if key == "eq_groups":
            cats = [cc for g in out for cc in g["categories"]]
            dup = next((cc for cc in cats if cats.count(cc) > 1), None)
            if dup:
                raise ValueError(f"Категория «{dup}» уже в другой инвентарной группе")
        return out[:500]

    @staticmethod
    def _ref_names(key, rows):
        if key == "eq_disp_reasons":
            return [str(x) for x in rows]
        if key == "eq_models":
            return [" ".join(x for x in (r.get("manufacturer"), r.get("model")) if x) for r in rows]
        if key == "eq_groups":
            return [f"{r['code']} {r['name']}" for r in rows]
        return [r.get("name") or "" for r in rows]

    def _ref_changes(self, key, old, new):
        a, b = self._ref_names(key, old), self._ref_names(key, new)
        added, gone = [x for x in b if x not in a], [x for x in a if x not in b]
        ch = []
        if added:
            ch.append({"t": "Добавлено", "old": "—", "new": ", ".join(added[:6]) + ("…" if len(added) > 6 else "")})
        if gone:
            ch.append({"t": "Убрано", "old": ", ".join(gone[:6]) + ("…" if len(gone) > 6 else ""), "new": "—"})
        if not ch and old != new:
            ch.append({"t": "Записи изменены", "old": str(len(old)), "new": str(len(new))})
        return ch

    def eq_ref_save(self, key, rows, user=""):
        """3.16: one reference of the clinic (models, inventory groups, kinds of work, regulations, reasons of disposal)."""
        if key not in self.EQ_REF_TITLES:
            raise ValueError("Неизвестный справочник")
        new = self._check_ref(key, rows)
        old = {"eq_models": self.eq_models, "eq_groups": self.eq_groups, "eq_works": self.eq_works, "eq_regs": self.eq_regs,
               "eq_disp_reasons": self.eq_disp_reasons}[key]()
        ch = self._ref_changes(key, old, new)
        with self.db.tx() as c:
            self._set_setting(c, key, new)
            if ch:
                self._log_settings(c, user, self.EQ_REF_TITLES[key], "Справочники", ch)
        return self.eq_refs()

    def eq_refs(self):
        cats = self.eq_categories()
        counts = {r["category"] or "": r["n"] for r in self.db.q(
            "SELECT category, COUNT(*) AS n FROM equipment WHERE status<>'written_off' GROUP BY category")}
        life = self.eq_life()
        live = self.db.q("SELECT id, category, manufacturer, model, location_id, ownership, accounting FROM equipment WHERE status<>'written_off'")
        # models: the clinic's list and what the cards already have
        own = self.eq_models()
        used = {}
        for e in live:
            if e["manufacturer"] or e["model"]:
                k = f"{(e['manufacturer'] or '').strip().lower()}|{(e['model'] or '').strip().lower()}"
                u = used.setdefault(k, {"manufacturer": (e["manufacturer"] or "").strip(), "model": (e["model"] or "").strip(),
                                        "category": e["category"] or "", "count": 0})
                u["count"] += 1
        models = []
        for m in own:
            k = f"{m['manufacturer'].lower()}|{m['model'].lower()}"
            models.append({**m, "count": used.pop(k, {}).get("count", 0), "from_cards": False})
        models += [{"id": "", **u, "article": "", "from_cards": True} for u in sorted(used.values(), key=lambda u: (u["manufacturer"], u["model"]))]
        groups = self.eq_groups()
        for g in groups:
            g["count"] = sum(counts.get(cc, 0) for cc in g["categories"])
        regs = self.eq_regs()
        plans = {r["reg_id"]: r["n"] for r in self.db.q(
            "SELECT reg_id, COUNT(*) AS n FROM equipment_plans WHERE active=1 AND COALESCE(reg_id,'')<>'' GROUP BY reg_id")}
        for g in regs:
            g["plans"] = plans.get(g["id"], 0)
        places = [{"id": p["id"], "name": p["name"], "kind": p["kind"], "kind_title": LOC_KINDS.get(p["kind"], p["kind"] or ""),
                   "chair": p["chair"] or "", "count": sum(1 for e in live if e["location_id"] == p["id"])}
                  for p in self.db.q("SELECT id, name, kind, chair FROM stock_locations WHERE active=1 ORDER BY sort, name")]
        chairs = [r["chair"] for r in self.db.q("""SELECT chair, COUNT(*) AS n FROM visits_archive WHERE COALESCE(chair,'')<>''
                                                   GROUP BY chair ORDER BY chair""")] if self._has("visits_archive") else []
        own_counts = {}
        for e in live:
            own_counts[e["ownership"] or "own"] = own_counts.get(e["ownership"] or "own", 0) + 1
        reasons = self.eq_disp_reasons()
        rc = {}
        for r in self.db.q("SELECT writeoff_reason FROM equipment WHERE status='written_off' AND COALESCE(writeoff_reason,'')<>''"):
            for x in reasons:
                if r["writeoff_reason"].startswith(x):
                    rc[x] = rc.get(x, 0) + 1
        return {"categories": [{"name": c, "count": counts.get(c, 0), "life": life.get(c, 0)} for c in cats],
                "ownership": EQ_OWNERSHIP, "accounting": EQ_ACCOUNTING, "conditions": EQ_CONDITION, "statuses": EQ_STATUS,
                "disposals": EQ_DISPOSAL, "receipt_docs": RECEIPT_DOCS, "move_reasons": MOVE_REASONS, "req_kinds": REQ_KINDS,
                "priorities": PRIORITY, "plan_kinds": PLAN_KINDS, "funding": FUNDING, "chair_hours": self.chair_hours(),
                # 3.16 «Справочники и настройки»
                "models": models, "manufacturers": sorted({m["manufacturer"] for m in models if m["manufacturer"]}, key=str.lower),
                "groups": groups, "works": self.eq_works(), "regs": regs, "disp_reasons": [{"name": x, "count": rc.get(x, 0)} for x in reasons],
                "places": places, "chairs": chairs, "ownership_counts": own_counts, "off_books": list(OFF_BOOKS),
                "module": self.eq_module(), "methods": AMORT_METHODS, "rounds": EQ_ROUND, "doc_kinds": EQ_DOC_KINDS,
                "doc_cats": {k: {"title": t, "kinds": list(ks)} for k, (t, ks) in EQ_DOC_CATS.items()}}

    def _has(self, table):
        return bool(self.db.one("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name=?", (table,)))

    def eq_refs_save(self, f, user=""):
        """Categories in their order and the usual useful life of each (months; 0 — none)."""
        f = f if isinstance(f, dict) else {}
        out_c, out_l = None, None
        if "categories" in f:
            cats = list(dict.fromkeys(_clean(x, 100) for x in (f.get("categories") or []) if _clean(x, 100)))
            if not cats:
                raise ValueError("Оставьте хотя бы одну категорию")
            out_c = cats[:60]
        if "life" in f:
            out_l = {}
            for k, v in (f.get("life") or {}).items():
                n = int(_num(v, "Срок службы") or 0)
                if not 0 <= n <= MAX_USEFUL_MONTHS:
                    raise ValueError("Срок службы — от 0 до 600 месяцев")
                out_l[_clean(k, 100)] = n
        old_c, old_l = self.eq_categories(), self.eq_life()
        ch = []
        if out_c is not None:
            ch = self._ref_changes("eq_disp_reasons", old_c, out_c)
        if out_l is not None:
            for k, n in out_l.items():
                if old_l.get(k, 0) != n:
                    ch.append({"t": f"Норматив «{k}»", "old": _fmt_val(old_l.get(k, 0), "n"), "new": _fmt_val(n, "n")})
        with self.db.tx() as c:
            if out_c is not None:
                self._set_setting(c, "eq_categories", out_c)
            if out_l is not None:
                self._set_setting(c, "eq_life", out_l)
            if ch:
                self._log_settings(c, user, "Виды оборудования и нормы амортизации", "Справочники", ch)
        return self.eq_refs()

    def eq_place_chair(self, lid, chair, user=""):
        """3.16 «Места эксплуатации»: the chair of Dentist Plus in a cabinet — its appointments are the runtime of the equipment
        there («Аналитика → Эффективность использования»)."""
        p = self.db.one("SELECT * FROM stock_locations WHERE id=? AND active=1", (str(lid or ""),))
        if not p:
            raise ValueError("Место не найдено")
        chair = _clean(chair, 100)
        if chair == (p["chair"] or ""):
            return self.eq_refs()
        with self.db.tx() as c:
            c.execute("UPDATE stock_locations SET chair=?, updated_at=? WHERE id=?", (chair, _now(), p["id"]))
            self._log_settings(c, user, f"Место «{p['name']}»", "Справочники", [{"t": "Кресло", "old": p["chair"] or "—", "new": chair or "—"}])
        return self.eq_refs()

    def eq_refs_export(self):
        """«Импорт / экспорт справочников»: every reference and setting of the module in one file (to another clinic or a backup)."""
        m = self.eq_module()
        return {"format": "dental-desk-equipment-refs", "version": 1, "exported_at": _now(), "categories": self.eq_categories(),
                "life": self.eq_life(), "eq_models": self.eq_models(), "eq_groups": self.eq_groups(), "eq_works": self.eq_works(),
                "eq_regs": self.eq_regs(), "eq_disp_reasons": self.eq_disp_reasons(),
                "module": {k: m[k] for k in EQ_MODULE if k != "method"}}

    def eq_refs_import(self, data, user=""):
        data = data if isinstance(data, dict) else {}
        if data.get("format") != "dental-desk-equipment-refs":
            raise ValueError("Это не файл справочников оборудования Dental Desk")
        refs = {k: self._check_ref(k, data[k]) for k in self.EQ_REF_TITLES if k in data}
        if "categories" in data or "life" in data:
            self.eq_refs_save({k: data[k] for k in ("categories", "life") if k in data}, user)
        if isinstance(data.get("module"), dict):
            self.eq_module_save({k: v for k, v in data["module"].items() if k in EQ_MODULE and k != "method"}, user, money=False)
        for k, rows in refs.items():
            self.eq_ref_save(k, rows, user)
        return {"imported": sorted([self.EQ_REF_TITLES[k] for k in refs] + (["Виды оборудования"] if "categories" in data else [])),
                "refs": self.eq_refs()}

    def chair_hours(self):
        try:
            r = self.db.one("SELECT v FROM stock_settings WHERE k='chair_hours'")
            n = float(r["v"]) if r and r["v"] not in (None, "") else CHAIR_HOURS
        except (ValueError, TypeError):
            n = CHAIR_HOURS
        return n if 0 < n <= 744 else CHAIR_HOURS

    def set_chair_hours(self, n):
        n = _num(n, "Часы кресла в месяц")
        if not 1 <= n <= 744:
            raise ValueError("Часы работы кресла в месяц — от 1 до 744")
        with self.db.tx() as c:
            c.execute("INSERT INTO stock_settings(k, v, updated_at) VALUES('chair_hours', ?, ?) ON CONFLICT(k) DO UPDATE SET "
                      "v=excluded.v, updated_at=excluded.updated_at", (f"{n:g}", _now()))
        return self.chair_hours()

    # -------------------------------------------------- 3.13: events and quick actions --
    def _ev(self, c, eid, kind, text, user, day=None, cost=0, data=None):
        c.execute("INSERT INTO equipment_events(equipment_id, kind, date, text, cost, user_name, created_at, data) VALUES(?,?,?,?,?,?,?,?)",
                  (eid, kind, day or date.today().isoformat(), text, cost, user, _now(),
                   json.dumps(data, ensure_ascii=False) if data is not None else None))

    def equipment_event(self, f, user=""):
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (f.get("equipment_id"),))
        if not e:
            raise ValueError("Оборудование не найдено")
        kind = f.get("kind") if f.get("kind") in ("service", "repair", "note") else "note"
        text = _clean(f.get("text"), 1000)
        if not text:
            raise ValueError("Опишите, что сделано")
        day = _day(f.get("date"), "Дата") if f.get("date") else date.today().isoformat()
        with self.db.tx() as c:
            self._ev(c, e["id"], kind, text, user, day, max(0, _num(f.get("cost"), "Стоимость")))
            if f.get("next_service") is not None:
                c.execute("UPDATE equipment SET next_service=? WHERE id=?", (_clean(f.get("next_service"), 10), e["id"]))
            if f.get("back_in_use") and e["status"] == "repair":  # «из ремонта — в работу»
                c.execute("UPDATE equipment SET status='in_use', condition='ok' WHERE id=?", (e["id"],))
                self._ev(c, e["id"], "status", f"{EQ_STATUS['repair']} → {EQ_STATUS['in_use']}", user, day)
        return e["id"]

    def equipment_set(self, f, user=""):
        """The quick changes of the card, saved at once: the place («Переместить»), the condition, who owns it, the status
        («Отправить на ремонт»). Every change is a line of the history."""
        e = self._eq_live(f.get("id"))
        note = _clean(f.get("text"), 500)
        sets, evs = {}, []
        if "location_id" in f or "location" in f:
            lid, loc = self._eq_place(f, e)
            if loc != (e["location"] or "") or lid != (e["location_id"] or ""):
                sets.update(location_id=lid, location=loc)
                evs.append(("move", f"{e['location'] or '—'} → {loc or '—'}"))
        if "condition" in f:
            cond = f.get("condition")
            if cond not in EQ_CONDITION:
                raise ValueError("Выберите техническое состояние")
            if cond != (e["condition"] or "ok"):
                sets["condition"] = cond
                evs.append(("condition", f"{EQ_CONDITION[e['condition'] or 'ok']} → {EQ_CONDITION[cond]}"))
        if "ownership" in f:
            own = f.get("ownership")
            if own not in EQ_OWNERSHIP:
                raise ValueError("Выберите принадлежность")
            if own != (e["ownership"] or "own"):
                sets["ownership"] = own
                evs.append(("note", f"Принадлежность: {EQ_OWNERSHIP[e['ownership'] or 'own']} → {EQ_OWNERSHIP[own]}"))
        if "status" in f:
            st = f.get("status")
            if st not in EQ_STATUS or st == "written_off":
                raise ValueError("Выбытие оформляется отдельно: «Оформить выбытие»")
            if st != e["status"]:
                sets["status"] = st
                if st == "repair":
                    if "condition" not in sets and (e["condition"] or "ok") == "ok":
                        sets["condition"] = "faulty"
                    evs.append(("repair", "Отправлено на ремонт"))
                else:
                    evs.append(("status", f"{EQ_STATUS[e['status']]} → {EQ_STATUS[st]}"))
        if note and evs:
            k, t = evs[-1]
            evs[-1] = (k, f"{t}. {note}")
        if not sets:
            return e["id"]
        # 3.16: «было → стало» of each quick change for the log
        titles = {"move": "Место", "condition": "Состояние", "note": "Принадлежность", "status": "Статус", "repair": "Статус"}
        with self.db.tx() as c:
            c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), e["id"]))
            for k, t in evs:
                pair = (t.split(". ")[0].split(": ", 1)[-1]).split(" → ") if " → " in t else None
                data = {"changes": [{"t": titles.get(k, ""), "old": pair[0], "new": pair[1]}]} if pair and len(pair) == 2 else None
                if k == "repair":
                    data = {"changes": [{"t": "Статус", "old": EQ_STATUS[e["status"]], "new": EQ_STATUS["repair"]}]}
                self._ev(c, e["id"], k, t, user, data=data)
        return e["id"]

    def equipment_inventory(self, f, user=""):
        """«Провести инвентаризацию»: found or not, where and in what condition; the differences are written down and the card
        takes the place and the condition that were seen."""
        e = self._eq_live(f.get("id"))
        found = f.get("found", True) not in (False, 0, "0", "false", "no")
        comment = _clean(f.get("comment"), 500)
        day = _day(f.get("date"), "Дата") if f.get("date") else date.today().isoformat()
        data, diffs, sets = {"found": found}, [], {}
        if found:
            lid, loc = self._eq_place(f, e) if ("location_id" in f or "location" in f) else (e["location_id"] or "", e["location"] or "")
            if loc != (e["location"] or ""):
                diffs.append(f"место: {e['location'] or '—'} → {loc or '—'}")
                sets.update(location_id=lid, location=loc)
            cond = f.get("condition") or e["condition"] or "ok"
            if cond not in EQ_CONDITION:
                raise ValueError("Выберите техническое состояние")
            if cond != (e["condition"] or "ok"):
                diffs.append(f"состояние: {EQ_CONDITION[e['condition'] or 'ok']} → {EQ_CONDITION[cond]}")
                sets["condition"] = cond
            data.update(location=loc, condition=cond)
        else:
            diffs.append("не найдено на месте")
        data["diffs"] = diffs
        text = ("Найдено" if found else "Не найдено") + ("; расхождения: " + "; ".join(diffs) if found and diffs else
                                                         "; расхождений нет" if found else "") + (f". {comment}" if comment else "")
        with self.db.tx() as c:
            if sets:
                c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), e["id"]))
            self._ev(c, e["id"], "inventory", text, user, day, data=data)
        return e["id"]

    def equipment_inventory_batch(self, lines, user=""):
        """3.14 «Инвентаризация → Оборудование»: several pieces checked in one go (only the rows that were looked at)."""
        out = {"done": 0, "diffs": 0, "not_found": 0}
        for ln in lines or []:
            if not isinstance(ln, dict) or not ln.get("id"):
                continue
            self.equipment_inventory(ln, user)
            ev = self.db.one("SELECT data FROM equipment_events WHERE equipment_id=? AND kind='inventory' ORDER BY id DESC LIMIT 1", (ln["id"],))
            data = json.loads((ev or {}).get("data") or "{}")
            out["done"] += 1
            if not data.get("found", True):
                out["not_found"] += 1
            elif data.get("diffs"):
                out["diffs"] += 1
        if not out["done"]:
            raise ValueError("Отметьте, что найдено и что не найдено")
        return out

    def equipment_inventory_log(self, limit=300):
        """3.14 «Инвентаризация → История»: every check of the equipment, the newest first."""
        rows = self.db.q("""SELECT ev.id, ev.equipment_id, ev.date, ev.text, ev.user_name, ev.data, e.name, e.inv_number
                            FROM equipment_events ev JOIN equipment e ON e.id = ev.equipment_id
                            WHERE ev.kind='inventory' ORDER BY ev.date DESC, ev.id DESC LIMIT ?""", (int(limit),))
        for r in rows:
            try:
                d = json.loads(r.pop("data") or "{}") or {}
            except ValueError:
                d = {}
            r["found"], r["diffs"] = bool(d.get("found", True)), d.get("diffs") or []
        return rows

    def equipment_service_log(self, day_from=None, day_to=None):
        """3.14 «Оборудование → ТО и ремонт»: what is due for service (overdue and within 60 days), and every service and repair
        of the period with its cost."""
        today = date.today()
        a = _day(day_from, "С") if day_from else (today - timedelta(days=365)).isoformat()
        b = _day(day_to, "По") if day_to else today.isoformat()
        a, b = min(a, b), max(a, b)
        soon = (today + timedelta(days=60)).isoformat()
        eq = [e for e in self.equipment_list(money=False) if e["status"] != "written_off"]
        names = self._loc_names()
        due = []
        for e in eq:
            if e["next_service"] and e["next_service"] <= soon:
                due.append({"id": e["id"], "inv_number": e["inv_number"], "name": e["name"], "next_service": e["next_service"],
                            "days": (date.fromisoformat(e["next_service"]) - today).days, "due": e["service_due"],
                            "status": e["status"], "status_title": e["status_title"],
                            "location": names.get(e.get("location_id") or "", "") if e.get("location_id") else e["location"] or ""})
        due.sort(key=lambda x: x["next_service"])
        events = self.db.q("""SELECT ev.id, ev.equipment_id, ev.kind, ev.date, ev.text, ev.cost, ev.user_name, e.name, e.inv_number
                              FROM equipment_events ev JOIN equipment e ON e.id = ev.equipment_id
                              WHERE ev.kind IN ('service','repair') AND ev.date >= ? AND ev.date <= ?
                              ORDER BY ev.date DESC, ev.id DESC""", (a, b))
        for ev in events:
            ev["kind_title"] = EQ_EVENTS.get(ev["kind"], ev["kind"])
        return {"from": a, "to": b, "due": due, "events": events,
                "in_repair": [{"id": e["id"], "inv_number": e["inv_number"], "name": e["name"]} for e in eq if e["status"] == "repair"],
                "cost": round(sum(ev["cost"] or 0 for ev in events), 2),
                "cost_service": round(sum(ev["cost"] or 0 for ev in events if ev["kind"] == "service"), 2),
                "cost_repair": round(sum(ev["cost"] or 0 for ev in events if ev["kind"] == "repair"), 2)}

    def equipment_replace_plan(self, f, user="", money=True):
        """«Запланировать замену»: the date; with «Бухгалтерия» also the market value, the cost of a new one and the monthly
        reserve (empty — worked out: what is missing for a new one over the months left)."""
        e = self._eq_live(f.get("id"))
        day = _day(f.get("replace_date"), "Плановая дата замены") if f.get("replace_date") else ""
        if not day:
            raise ValueError("Укажите плановую дату замены")
        if day <= date.today().isoformat():
            raise ValueError("Плановая дата замены должна быть в будущем")
        sets = {"replace_date": day}
        if money:
            mv = max(0, _num(f.get("market_value"), "Рыночная стоимость")) if "market_value" in f else float(e["market_value"] or 0)
            rc = max(0, _num(f.get("replace_cost"), "Стоимость замены")) if "replace_cost" in f else float(e["replace_cost"] or 0)
            rm = f.get("reserve_monthly")
            if rm in (None, ""):
                months = max(1, (_mon(day) or 0) - (_mon(date.today().isoformat()) or 0))
                rm = round(max(0.0, rc - mv) / months, 2)
            sets.update(market_value=mv, replace_cost=rc, reserve_monthly=max(0, _num(rm, "Резерв на обновление")))
        comment = _clean(f.get("comment"), 300)
        with self.db.tx() as c:
            c.execute(f"UPDATE equipment SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), e["id"]))
            self._ev(c, e["id"], "replace_plan", f"Замена запланирована на {day[8:10]}.{day[5:7]}.{day[:4]}" + (f". {comment}" if comment else ""), user)
        return e["id"]

    def equipment_dispose(self, f, user="", money=True):
        """«Оформить выбытие»: списание и утилизация (the act of the commission, as before), продажа or возврат владельцу
        (leased or the founder's). The piece stays in the register as «выбыло» and is not depreciated after that month."""
        e = self.db.one("SELECT * FROM equipment WHERE id=?", (f.get("id"),))
        if not e:
            raise ValueError("Оборудование не найдено")
        if e["status"] == "written_off":
            raise ValueError("Оборудование уже списано" if (e["disposal_kind"] or "writeoff") == "writeoff" else "Оборудование уже выбыло")
        kind = f.get("kind") if f.get("kind") in EQ_DISPOSAL else "writeoff"
        reason = _clean(f.get("reason"), 500)
        if not reason:
            raise ValueError({"writeoff": "Укажите причину списания", "utilize": "Укажите причину утилизации",
                              "sale": "Укажите покупателя и основание продажи", "transfer": "Укажите, кому и по какому договору передано",
                              "return": "Укажите, кому и по какому документу возвращено"}[kind])
        commission = [_clean(x, 150) for x in (f.get("commission") or []) if _clean(x)]
        if kind in ("writeoff", "utilize") and len(commission) < 2:
            raise ValueError("Укажите председателя и хотя бы одного члена комиссии")
        basis = _clean(f.get("basis"), 200)
        if not basis and self.eq_module()["no_doc_disposal"]:  # 3.16 «Запрет списания без документа»
            raise ValueError("Укажите документ-основание: в настройках оборудования включён запрет списания без документа")
        day = _day(f.get("date"), "Дата") if f.get("date") else date.today().isoformat()
        # 3.15: every disposal has its act, numbered on among all the acts of disposal (writeoff, utilization, sale, transfer)
        n = self.db.one("SELECT COUNT(*) AS n FROM equipment WHERE status='written_off' AND COALESCE(writeoff_act,'')<>''")["n"] + 1
        act = _clean(f.get("act_number"), 30) or str(n) if kind in ("writeoff", "utilize", "transfer") else ""
        # 3.14: the book value is the depreciation's as of the day of the disposal (not of today — a disposal entered later)
        book = amortization({**e, "status": "written_off", "writeoff_date": day})["residual"]
        if money:
            residual = max(0, _num(f.get("residual"), "Остаточная стоимость")) if f.get("residual") not in (None, "") else book
            amount = max(0, _num(f.get("amount"), "Сумма продажи")) if kind == "sale" else 0
        else:  # without «Бухгалтерия» the book value is the depreciation's, the price of a sale is not taken
            residual, amount = book, 0
        text = {"writeoff": f"Акт списания № {act}: {reason}", "utilize": f"Акт утилизации № {act}: {reason}",
                "sale": f"Продано: {reason}", "transfer": f"Акт передачи № {act}: {reason}",
                "return": f"Возвращено владельцу: {reason}"}[kind]
        with self.db.tx() as c:
            c.execute("""UPDATE equipment SET status='written_off', writeoff_date=?, writeoff_reason=?, writeoff_act=?,
                         writeoff_commission=?, residual=?, disposal_kind=?, disposal_amount=?, disposal_responsible=?,
                         disposal_basis=? WHERE id=?""",
                      (day, reason, act, json.dumps(commission, ensure_ascii=False), residual, kind, amount,
                       _clean(f.get("responsible"), 150), basis, e["id"]))
            data = {"module": "Выбытие", "changes": [{"t": "Статус", "old": EQ_STATUS[e["status"]], "new": EQ_DISPOSED[kind]}]}
            if not basis:  # 3.16: «подозрительное» — no document behind the disposal
                data["flag"] = "Выбытие без документа-основания"
            self._ev(c, e["id"], "writeoff" if kind in ("writeoff", "utilize") else "disposal", text, user, day, data=data)
        return e["id"]

    def write_off_equipment(self, f, user="", money=True):
        return self.equipment_dispose({**f, "kind": "writeoff"}, user, money)

    # ----------------------------------------------------------- 3.13: documents --
    def equipment_doc_add(self, eid, kind, title, file_id, user=""):
        """A document (or a photo) of the card: the file is a row of patient_files owned by «_stock», so it travels to the
        other computers like the stock photos; the first photo becomes the main one."""
        e = self._eq_live(eid)
        kind = kind if kind in EQ_DOC_KINDS else "other"
        did = _id("ED")
        title = _clean(title, 200) or EQ_DOC_KINDS[kind]
        with self.db.tx() as c:
            c.execute("INSERT INTO equipment_docs(id, equipment_id, kind, title, file_id, created_by, created_at, deleted) VALUES(?,?,?,?,?,?,?,0)",
                      (did, e["id"], kind, title, file_id, user, _now()))
            if kind == "photo" and not e["photo_id"]:
                c.execute("UPDATE equipment SET photo_id=? WHERE id=?", (file_id, e["id"]))
            self._ev(c, e["id"], "doc", f"{EQ_DOC_KINDS[kind]}: {title}", user)
        return did

    def equipment_doc_delete(self, did, user=""):
        d = self.db.one("SELECT * FROM equipment_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        e = self._eq_live(d["equipment_id"])
        with self.db.tx() as c:
            c.execute("UPDATE equipment_docs SET deleted=1 WHERE id=?", (d["id"],))
            if e["photo_id"] == d["file_id"]:
                nxt = c.execute("SELECT file_id FROM equipment_docs WHERE equipment_id=? AND kind='photo' AND deleted=0 AND file_id<>? "
                                "ORDER BY created_at LIMIT 1", (e["id"], d["file_id"])).fetchone()
                c.execute("UPDATE equipment SET photo_id=? WHERE id=?", (nxt[0] if nxt else None, e["id"]))
            self._ev(c, e["id"], "doc", f"Убран документ: {EQ_DOC_KINDS.get(d['kind'], d['kind'])} — {d['title']}", user,
                     data={"module": "Документы", "doc": d["id"], "flag": "Убран документ оборудования"})
        return e["id"]

    def equipment_doc_file(self, did):
        d = self.db.one("SELECT * FROM equipment_docs WHERE id=? AND deleted=0", (str(did or ""),))
        if not d:
            raise ValueError("Документ не найден")
        return d

    # ------------------------------------------------- 3.13: QR of the inventory label --
    def phone_url(self):
        """The address of the stock's phone app (empty — not set up): a QR then holds a link to the card there."""
        r = self.db.one("SELECT v FROM stock_settings WHERE k='phone_url'")
        u = str((r or {}).get("v") or "").strip()
        return u if re.match(r"^https://[^\s/]+", u) else ""

    def qr_text(self, e, clinic=""):
        """What the QR of a label holds: a link `<app>/e/<инв. №>`, or (no app yet) the text a phone camera shows as it is —
        the number first, so a desk scanner that stops at the line break still types the number."""
        url = self.phone_url()
        if url:
            return f"{url.rstrip('/')}/e/{quote(str(e['inv_number'] or ''), safe='')}"
        lines = [f"Инв. № {e['inv_number']}", e["name"], e.get("model") and f"Модель: {e['model']}",
                 e.get("serial") and f"S/N: {e['serial']}", e.get("location") and f"Место: {e['location']}", clinic]
        return "\n".join(str(x) for x in lines if x)

    def equipment_by_code(self, code):
        """The equipment a scanned label points to: the link of the phone app or the text of the label (or just the number)."""
        s = str(code or "").strip()
        if not s:
            return None
        m = re.search(r"/e/([^/?#\s]+)", s)
        if m:
            inv = unquote(m[1])
        else:
            first = s.splitlines()[0].strip()
            m = re.match(r"^(?:инв\.?\s*№?|inv\.?\s*n?o?\.?)\s*(.+)$", first, re.I)
            inv = (m[1] if m else first).strip()
        r = self.db.one("SELECT id FROM equipment WHERE inv_number=?", (inv,)) or \
            self.db.one("SELECT id FROM equipment WHERE lower(inv_number)=lower(?)", (inv,))
        return r["id"] if r else None
