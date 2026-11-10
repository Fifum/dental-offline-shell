"""Demo data so the app can be shown before API credentials are available."""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta

from normalize import utcnow, visit_fields

LN_M = ["Иванов", "Смирнов", "Кузнецов", "Попов", "Васильев", "Петров", "Соколов", "Михайлов", "Новиков", "Фёдоров",
        "Морозов", "Волков", "Алексеев", "Лебедев", "Семёнов", "Егоров", "Павлов", "Козлов", "Степанов", "Николаев"]
FN_M = ["Александр", "Дмитрий", "Максим", "Сергей", "Андрей", "Алексей", "Артём", "Илья", "Кирилл", "Михаил"]
FN_F = ["Анна", "Мария", "Елена", "Ольга", "Наталья", "Екатерина", "Татьяна", "Ирина", "Светлана", "Юлия"]
MN = ["Александров", "Сергеев", "Дмитриев", "Андреев", "Игорев", "Олегов", "Викторов", "Петров"]
SERVICES = ["Консультация", "Профгигиена", "Лечение кариеса", "Пломба", "Удаление зуба", "Чистка каналов",
            "Установка коронки", "Имплантация", "Контрольный осмотр", "Отбеливание", "Снятие слепков", "Брекеты: коррекция"]
STATUSES = ["Запланирован", "Подтверждён", "Пришёл", "Завершён", "Отменён"]
ALLERGY = ["нет", "нет", "нет", "Лидокаин", "Пенициллин", "Латекс", "нет"]
CHRONIC = ["нет", "нет", "Гипертония", "Сахарный диабет 2 типа", "Бронхиальная астма", "нет"]
DIAG = [("K02.1", "Кариес дентина"), ("K04.0", "Пульпит"), ("K05.1", "Хронический гингивит"),
        ("K08.1", "Потеря зубов вследствие удаления"), ("K03.6", "Отложения на зубах"), ("K07.3", "Аномалии положения зубов")]


def _person(rng, i):
    female = rng.random() < 0.55
    ln = rng.choice(LN_M) + ("а" if female else "")
    fn = rng.choice(FN_F if female else FN_M)
    mn = rng.choice(MN) + ("на" if female else "ич")
    return ln, fn, mn, female


def build(seed=7):
    rng = random.Random(seed)
    branches = [{"id": 1, "title": "Клиника — Центр", "address": "ул. Ленина, 12"},
                {"id": 2, "title": "Клиника — Север", "address": "пр. Мира, 48"}]
    doctors = [
        {"id": 11, "lname": "Ахмедова", "fname": "Мадина", "mname": "Руслановна", "position": "Стоматолог-терапевт", "branch_id": 1},
        {"id": 12, "lname": "Ковалёв", "fname": "Игорь", "mname": "Петрович", "position": "Хирург-имплантолог", "branch_id": 1},
        {"id": 13, "lname": "Ли", "fname": "Виктория", "mname": "Сергеевна", "position": "Ортодонт", "branch_id": 1},
        {"id": 14, "lname": "Орлов", "fname": "Денис", "mname": "Андреевич", "position": "Стоматолог-ортопед", "branch_id": 2},
        {"id": 15, "lname": "Гусева", "fname": "Полина", "mname": "Игоревна", "position": "Гигиенист", "branch_id": 2},
    ]
    patients = []
    for i in range(140):
        ln, fn, mn, female = _person(rng, i)
        bd = date(rng.randint(1950, 2015), rng.randint(1, 12), rng.randint(1, 28))
        teeth = {str(t): rng.choice(["здоров", "здоров", "здоров", "пломба", "кариес", "коронка", "отсутствует", "имплант"])
                 for q in (1, 2, 3, 4) for t in range(q * 10 + 1, q * 10 + 9)}
        patients.append({
            "id": 1000 + i, "lname": ln, "fname": fn, "mname": mn,
            "gender": "Ж" if female else "М", "birth_date": bd.isoformat(),
            "phone": f"+7 9{rng.randint(10, 99)} {rng.randint(100, 999)}-{rng.randint(10, 99)}-{rng.randint(10, 99)}",
            "email": f"patient{1000 + i}@mail.ru" if rng.random() < 0.5 else "",
            "card_number": f"{2020 + rng.randint(0, 5)}-{1000 + i}",
            "address": f"г. Москва, ул. {rng.choice(['Садовая', 'Лесная', 'Школьная', 'Новая', 'Мира'])}, д. {rng.randint(1, 90)}",
            "allergies": rng.choice(ALLERGY),
            "chronic_diseases": rng.choice(CHRONIC),
            "blood_type": rng.choice(["I (0) Rh+", "II (A) Rh+", "III (B) Rh-", "IV (AB) Rh+", ""]),
            "comment": rng.choice(["", "", "Боится уколов, нужна аппликационная анестезия", "Предпочитает утро", "VIP"]),
            "dental_formula": teeth,
            "balance": rng.choice([0, 0, 0, -3500, 1200]),
        })
    visits = []
    vid = 50000
    today = date.today()
    for dd in range(-30, 31):
        day = today + timedelta(days=dd)
        if day.weekday() == 6:
            continue
        for doc in doctors:
            t = datetime.combine(day, datetime.min.time()).replace(hour=9)
            while t.hour < 19:
                if rng.random() < 0.72:
                    dur = rng.choice([30, 30, 45, 60, 60, 90])
                    p = rng.choice(patients)
                    if dd < 0:
                        st = rng.choice(["Завершён", "Завершён", "Завершён", "Отменён", "Не пришёл"])
                    elif dd == 0:
                        st = "Пришёл" if t.hour < datetime.now().hour else rng.choice(["Подтверждён", "Запланирован"])
                    else:
                        st = rng.choice(["Запланирован", "Подтверждён"])
                    visits.append({
                        "id": vid, "patient_id": p["id"], "doctor_id": doc["id"], "branch_id": doc["branch_id"],
                        "start": t.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": (t + timedelta(minutes=dur)).strftime("%Y-%m-%d %H:%M:%S"),
                        "status": st, "title": rng.choice(SERVICES),
                        "chair": f"Кресло {doctors.index(doc) + 1}",
                        "comment": rng.choice(["", "", "", "Перезвонить накануне", "Первичный"]),
                    })
                    vid += 1
                    t += timedelta(minutes=dur)
                else:
                    t += timedelta(minutes=30)
    diags = {}
    for p in patients:
        diags[str(p["id"])] = [{"id": p["id"] * 10 + k, "code": c, "title": n,
                                "tooth": rng.choice([11, 16, 26, 36, 46, 47, 21]),
                                "date": (today - timedelta(days=rng.randint(5, 400))).isoformat()}
                               for k, (c, n) in enumerate(rng.sample(DIAG, rng.randint(0, 3)))]
    return branches, doctors, patients, visits, diags


def ensure_demo(db, force=False):
    if not force and db.meta_get("demo_built") == date.today().isoformat():
        return
    branches, doctors, patients, visits, diags = build()
    db.wipe(with_local=False)  # keep what was entered in the app (demo records, invoices)
    import catalog
    catalog.seed(db, demo=True)
    db.upsert_branches(branches)
    db.upsert_doctors(doctors)
    db.upsert_patients(patients, detail=True)
    rows = []
    for v in visits:
        f = visit_fields(v)
        f["raw"] = v
        rows.append(f)
    today = date.today()
    db.replace_visits((today - timedelta(days=31)).isoformat(), (today + timedelta(days=31)).isoformat(), rows)
    for pid, items in diags.items():
        db.upsert_extra(pid, "diagnoses", items)
    db.meta_set("demo_built", today.isoformat())
    db.meta_set("last_ok", utcnow())
    db.log_sync(utcnow(), True, "Демо-данные сгенерированы", {"visits": len(rows), "patients": len(patients)})


# ------------------------------------------------------------------ demo stock --
DEMO_MATERIALS = [  # id, code, name, unit, category, min, price, start
    ("m1", "АН-01", "Артикаин 4% (Ультракаин), карпула 1,7 мл", "карп", "Анестезия", 50, 62, 140),
    ("m2", "АН-02", "Иглы карпульные 30G", "шт", "Анестезия", 50, 14, 180),
    ("m3", "ПЛ-01", "Композит светоотверждаемый, шприц 4 г", "г", "Пломбировочные", 20, 310, 36),
    ("m4", "ПЛ-02", "Адгезивная система, флакон 5 мл", "мл", "Пломбировочные", 5, 520, 12),
    ("m5", "ПЛ-03", "Протравочный гель 37%", "мл", "Пломбировочные", 5, 45, 8),
    ("m6", "ЭН-01", "Эндодонтические файлы, набор", "набор", "Эндодонтия", 5, 950, 9),
    ("m7", "ЭН-02", "Гуттаперчевые штифты, упаковка", "уп", "Эндодонтия", 3, 480, 2),
    ("m8", "РС-01", "Перчатки нитриловые, пара", "пара", "Расходники", 100, 9, 420),
    ("m9", "РС-02", "Маски медицинские", "шт", "Расходники", 100, 4, 260),
    ("m10", "РС-03", "Слюноотсосы", "шт", "Расходники", 100, 3, 85),
    ("m11", "ОР-01", "Слепочная масса А-силикон", "г", "Ортопедия", 300, 4.5, 900),
    ("m12", "ХР-01", "Шовный материал, нить 4-0", "шт", "Хирургия", 10, 160, 24),
    ("m13", "ГГ-01", "Паста полировочная", "г", "Гигиена", 50, 6, 40),
]
DEMO_NORMS = {  # demo service index -> [(material, qty)]
    1: [("m1", 1), ("m2", 1), ("m3", 0.4), ("m4", 0.1), ("m5", 0.2), ("m8", 2), ("m9", 1), ("m10", 2)],
    2: [("m1", 2), ("m2", 2), ("m6", 0.3), ("m7", 0.2), ("m3", 0.4), ("m8", 3), ("m9", 1), ("m10", 2)],
    5: [("m2", 1), ("m8", 1)],
    6: [("m13", 3), ("m8", 1), ("m9", 1), ("m10", 2)],
    7: [("m1", 1), ("m2", 1), ("m8", 2), ("m9", 1), ("m10", 1)],
    8: [("m1", 2), ("m2", 2), ("m12", 1), ("m8", 2), ("m9", 1), ("m10", 2)],
    12: [("m11", 30), ("m8", 1)],
}
DEMO_EQUIPMENT = [  # id, inv, name, category, model, location, price, purchase, next_service(days from today)
    ("e1", "00001", "Стоматологическая установка", "Установки", "Установка с нижней подачей", "Кабинет 1 · Кресло 1", 1450000, "2023-03-14", 40),
    ("e2", "00002", "Стоматологическая установка", "Установки", "Установка с верхней подачей", "Кабинет 2 · Кресло 2", 1380000, "2023-09-02", 75),
    ("e3", "00003", "Автоклав класса B, 23 л", "Стерилизация", "Автоклав 23 л", "Стерилизационная", 410000, "2022-11-20", -5),
    ("e4", "00004", "Компрессор безмасляный", "Инженерное", "Компрессор на 3 установки", "Техническое помещение", 265000, "2022-11-20", 12),
    ("e5", "00005", "Радиовизиограф", "Диагностика", "Датчик размера 1", "Кабинет 1 · Кресло 1", 390000, "2024-02-10", 180),
    ("e6", "00006", "Ультразвуковой скалер", "Гигиена", "Скалер с подсветкой", "Кабинет 2 · Кресло 2", 98000, "2024-06-01", 90),
    ("e7", "00007", "Апекслокатор", "Эндодонтия", "Апекслокатор с дисплеем", "Кабинет 1 · Кресло 1", 64000, "2021-05-18", 120),
    ("e8", "00008", "Наконечник турбинный", "Наконечники", "Турбинный наконечник", "Кабинет 2 · Кресло 2", 42000, "2020-01-15", 30),
]


def ensure_stock(stock):
    """Invented stock and equipment for the demo clinic (only once, only if nothing is there yet)."""
    db = stock.db
    if db.one("SELECT 1 AS x FROM materials WHERE id LIKE 'demo_%' LIMIT 1") or db.one("SELECT 1 AS x FROM materials LIMIT 1"):
        return
    rnd = random.Random(7)
    today = date.today()
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO suppliers VALUES('demo_s1','ООО «Дентал Снаб»','+7 900 000-11-22','7700000000','',1)")
        c.execute("INSERT OR IGNORE INTO suppliers VALUES('demo_s2','ООО «Стоматорг»','+7 900 000-33-44','7800000000','',1)")
        for mid, code, name, unit, cat, mn, price, start in DEMO_MATERIALS:
            c.execute("INSERT INTO materials(id, code, name, unit, category, min_qty, price, barcode, comment, active, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,1,?)", ("demo_" + mid, code, name, unit, cat, mn, price, "", "", utcnow()))
        for n, (sup, days) in enumerate((("demo_s1", 25), ("demo_s2", 9))):
            day = (today - timedelta(days=days)).isoformat()
            lines = [m for i, m in enumerate(DEMO_MATERIALS) if i % 2 == n]
            total = sum(m[6] * m[7] for m in lines)
            c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (f"demo_r{n}", "receipt", f"{1040 + n * 37}", day, sup, "", "", total, "Демо", f"{day} 10:00:00"))
            for m in lines:
                c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, user_name, at) VALUES(?,?,?,?,?,?,?)",
                          ("demo_" + m[0], m[7], m[6], "receipt", f"demo_r{n}", "Демо", f"{day} 10:00:00"))
        for m in DEMO_MATERIALS:  # some use over the last weeks
            used = round(m[7] * rnd.uniform(0.25, 0.8 if m[0] not in ("m4", "m7", "m12") else 1.0), 1 if m[3] in ("г", "мл") else 0)
            day = (today - timedelta(days=rnd.randint(1, 8))).isoformat()
            c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, reason, user_name, at) VALUES(?,?,?,?,?,?,?)",
                      ("demo_" + m[0], -used, m[6], "service", "Приёмы за период", "Демо", f"{day} 18:00:00"))
        for si, items in DEMO_NORMS.items():
            for mid, q in items:
                c.execute("INSERT OR IGNORE INTO service_materials VALUES(?,?,?)", (f"demo_{si}", "demo_" + mid, q))
        for eid, inv, name, cat, model, loc, price, bought, nxt in DEMO_EQUIPMENT:
            c.execute("""INSERT INTO equipment(id, inv_number, name, category, model, serial, location, responsible, purchase_date,
                         price, warranty_until, next_service, status, comment, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      ("demo_" + eid, inv, name, cat, model, f"SN{rnd.randint(100000, 999999)}", loc, "", bought, price,
                       (date.fromisoformat(bought) + timedelta(days=730)).isoformat(), (today + timedelta(days=nxt)).isoformat(),
                       "repair" if eid == "e8" else "in_use", "", utcnow()))
            c.execute("INSERT INTO equipment_events(equipment_id, kind, date, text, cost, user_name, created_at) VALUES(?,?,?,?,?,?,?)",
                      ("demo_" + eid, "service", (today - timedelta(days=rnd.randint(60, 200))).isoformat(),
                       "Плановое техобслуживание, замена фильтров", rnd.choice([0, 3500, 6000]), "Демо", utcnow()))


def _ean13(body12):
    s = sum(int(ch) * (3 if i % 2 else 1) for i, ch in enumerate(body12))
    return body12 + str((10 - s % 10) % 10)


DEMO_LOTS = [  # material, lot, expires in days from today (negative = already expired), qty, price
    ("m1", "A2611", -10, 20, 60), ("m1", "A2803", 420, 60, 60),
    ("m5", "G-118", 12, 6, 42), ("m4", "BD-0925", 25, 4, 540), ("m12", "SR-4471", 300, 10, 150),
]


def ensure_stock_lots(stock):
    """A demo receipt with lots and expiry dates (one lot already expired, two run out soon) and demo barcodes.
    Separate from ensure_stock so that demo databases made by older versions get it too (once)."""
    db = stock.db
    if not db.one("SELECT 1 AS x FROM materials WHERE id='demo_m1'") or db.one("SELECT 1 AS x FROM stock_docs WHERE id='demo_r2'"):
        return
    today = date.today()
    day = (today - timedelta(days=20)).isoformat()
    total = sum(q * p for _, _, _, q, p in DEMO_LOTS)
    with db.tx() as c:
        for n, (mid, *_rest) in enumerate(DEMO_MATERIALS):
            c.execute("UPDATE materials SET barcode=? WHERE id=? AND COALESCE(barcode,'')=''", (_ean13(f"46070000{n + 1:04d}"), "demo_" + mid))
        c.execute("INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?)", ("demo_r2", "receipt", "1131", day, "demo_s2", "", "", total, "Демо", f"{day} 11:00:00"))
        for mid, lot, days, q, price in DEMO_LOTS:
            cur = c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, user_name, at) VALUES(?,?,?,?,?,?,?)",
                            ("demo_" + mid, q, price, "receipt", "demo_r2", "Демо", f"{day} 11:00:00"))
            c.execute("INSERT INTO stock_lots(material_id, move_id, lot, expires, qty, created_at) VALUES(?,?,?,?,?,?)",
                      ("demo_" + mid, cur.lastrowid, lot, (today + timedelta(days=days)).isoformat(), q, f"{day} 11:00:00"))
        # the second supplier is cheaper for the polishing paste: the purchase list shows both offers
        c.execute("INSERT INTO stock_moves(material_id, qty, price, kind, doc_id, user_name, at) VALUES(?,?,?,?,?,?,?)",
                  ("demo_m13", 10, 5.5, "receipt", "demo_r2", "Демо", f"{day} 11:00:00"))
        c.execute("UPDATE stock_docs SET total=total+55 WHERE id='demo_r2'")


# ------------------------------------------- demo money, expenses, sources and shifts --
DEMO_SOURCES = ["Рекомендация знакомых", "Рекомендация знакомых", "Яндекс Карты", "Яндекс Карты", "2ГИС", "Сайт клиники",
                "Соцсети", "Проходили мимо", "Поиск в интернете", ""]
DEMO_EXPENSES = [  # day of month, category, amount, comment
    (2, "Аренда", 180000, "Аренда помещения"), (5, "Коммунальные услуги", 14200, "Электричество, вода"),
    (6, "Связь и интернет", 3900, "Интернет и телефония"), (9, "Зуботехническая лаборатория", 46500, "Коронки и каппы"),
    (12, "Материалы и закупки", 38700, "Расходные материалы"), (15, "Реклама", 25000, "Реклама на картах"),
    (20, "Банк и эквайринг", 6100, "Комиссия эквайринга"), (25, "Налоги и взносы", 41000, "Взносы за сотрудников")]
DEMO_PAY = {"11": (30, 0), "12": (35, 0), "13": (30, 0), "14": (30, 0), "15": (25, 30000)}  # doctor -> (%, salary)


def ensure_office(db):
    """Invoices with payments for past visits, expenses, pay schemes, patient sources and shifts (demo only, once)."""
    from accounting import Accounting
    from marketing import Marketing
    from shifts import Shifts
    for m in (Accounting, Marketing, Shifts):
        m(db)  # tables
    if db.one("SELECT 1 AS x FROM expenses WHERE id LIKE 'demo_%' LIMIT 1"):
        return
    srv = db.q("SELECT id, code, title, price FROM services WHERE id LIKE 'demo_%' ORDER BY id")
    if not srv:
        return
    rnd = random.Random(11)
    today = date.today()
    past = db.q("""SELECT id, patient_id, doctor_id, start FROM visits WHERE start >= ? AND start < ? AND status='Завершён'
                   ORDER BY start""", ((today - timedelta(days=30)).isoformat(), today.isoformat()))
    with db.tx() as c:
        for n, v in enumerate(past):
            if rnd.random() > 0.55:
                continue
            items = []
            for s in rnd.sample(srv, rnd.choice([1, 1, 2])):
                qty = rnd.choice([1, 1, 1, 2])
                items.append({"service_id": s["id"], "code": s["code"], "title": s["title"], "price": s["price"], "qty": qty,
                              "discount": 0, "sum": round(s["price"] * qty, 2)})
            total = round(sum(i["sum"] for i in items), 2)
            at = v["start"][:16].replace("T", " ")
            r = rnd.random()
            paid = total if r < 0.86 else round(total * 0.5, 2) if r < 0.95 else 0
            st = "Оплачен" if paid >= total else "Частично оплачен" if paid else "Не оплачен"
            iid = f"demo_i{n}"
            c.execute("""INSERT OR IGNORE INTO invoices(id, patient_id, visit_id, doctor_id, items, total, discount, status, comment,
                         created_at, transferred, transferred_at, kind) VALUES(?,?,?,?,?,?,0,?,?,?,1,?,'invoice')""",
                      (iid, v["patient_id"], v["id"], v["doctor_id"], json.dumps(items, ensure_ascii=False), total, st, "", at, at))
            if paid:
                c.execute("""INSERT OR IGNORE INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at, transferred,
                             transferred_at) VALUES(?,?,?,?,?,?,?,1,?)""",
                          (f"demo_p{n}", iid, v["patient_id"], paid, rnd.choice(["Карта", "Карта", "Наличные", "Перевод"]), "", at, at))
        for n, v in enumerate(past[:6]):  # advances: paid ahead for the next stage
            c.execute("""INSERT OR IGNORE INTO payments(id, invoice_id, patient_id, amount, method, comment, created_at, transferred,
                         transferred_at) VALUES(?,NULL,?,?,?,?,?,1,?)""",
                      (f"demo_a{n}", v["patient_id"], rnd.choice([5000, 10000, 15000]), "Карта", "Аванс за лечение",
                       v["start"][:16], v["start"][:16]))
        for n, v in enumerate(past[:6]):  # treatment plans that were never started
            items = [{"title": s["title"], "price": s["price"], "qty": 1, "sum": s["price"]} for s in srv[n % 5:n % 5 + 3]]
            c.execute("""INSERT OR IGNORE INTO invoices(id, patient_id, doctor_id, items, total, discount, status, comment, created_at,
                         transferred, kind, plan_status, title) VALUES(?,?,?,?,?,0,'План','',?,1,'plan','Предварительный',?)""",
                      (f"demo_pl{n}", v["patient_id"], v["doctor_id"], json.dumps(items, ensure_ascii=False),
                       sum(i["sum"] for i in items), v["start"][:16], "План лечения"))
        for back in (1, 0):
            y, m = (today.year, today.month - back) if today.month - back > 0 else (today.year - 1, 12)
            for day, cat, amount, comment in DEMO_EXPENSES:
                d = date(y, m, min(day, 28))
                if d <= today:
                    c.execute("INSERT INTO expenses(id, date, category, amount, method, person, period, comment, user_name, created_at) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (f"demo_e{back}_{day}", d.isoformat(), cat, amount, "Безналичный перевод", None, None, comment,
                               "Демо", utcnow()))
        for did, (pct, fixed) in DEMO_PAY.items():
            c.execute("INSERT OR IGNORE INTO salary_schemes(person, percent, fixed, base, minus_materials, updated_at) VALUES(?,?,?,?,?,?)",
                      (f"d:{did}", pct, fixed, "paid", 0, utcnow()))
        for p in db.q("SELECT id FROM patients"):
            s = rnd.choice(DEMO_SOURCES)
            if s:
                c.execute("INSERT OR IGNORE INTO patient_marketing VALUES(?,?,0,?)", (p["id"], s, utcnow()))
        first = today.replace(day=1)
        for k, did in enumerate(DEMO_PAY):
            d = first
            while d.month == first.month:
                if d.weekday() < 6 and (d.weekday() + k) % 6 != 5:  # each doctor has one weekday off
                    start, end = ("09:00", "15:00") if k % 2 else ("12:00", "19:00") if d.weekday() % 2 else ("09:00", "19:00")
                    c.execute('INSERT OR IGNORE INTO work_shifts(person, date, start, "end", note, user_name, updated_at) '
                              "VALUES(?,?,?,?,?,?,?)", (f"d:{did}", d.isoformat(), start, end, "", "Демо", utcnow()))
                d += timedelta(days=1)


def ensure_director(db):
    """Plans for the month and treatment plans in every status, so the director's screen has something to show (once)."""
    from director import Director
    from reports import Reports
    Director(db, Reports(db))  # table
    if db.one("SELECT 1 AS x FROM kpi_targets WHERE user_name='Демо' LIMIT 1"):
        return
    inv = db.q("""SELECT id, patient_id, doctor_id, items, total, created_at FROM invoices WHERE id LIKE 'demo_i%'
                  AND plan_id IS NULL ORDER BY created_at""")
    if not inv:
        return
    rnd = random.Random(23)
    today = date.today()
    month = today.strftime("%Y-%m")
    paid = db.q("""SELECT i.doctor_id, SUM(p.amount) AS s FROM payments p JOIN invoices i ON i.id=p.invoice_id
                   WHERE p.created_at >= ? GROUP BY i.doctor_id""", ((today - timedelta(days=30)).isoformat(),))
    now = utcnow()
    days = db.one("SELECT COUNT(DISTINCT substr(created_at,1,10)) AS n FROM payments WHERE created_at >= ?",
                  ((today - timedelta(days=30)).isoformat(),))["n"] or 1
    first = today.replace(day=1)
    workdays = sum(1 for k in range(31) if (first + timedelta(days=k)).month == first.month and (first + timedelta(days=k)).weekday() < 6)
    k = workdays / days  # a month of work at the demo's usual pace
    with db.tx() as c:
        total = sum(r["s"] or 0 for r in paid)
        rows = [("clinic", "revenue", round(total * k * 1.05, -4) or 300000), ("clinic", "new_patients", 40)]
        rows += [(f"d:{r['doctor_id']}", "revenue", round((r["s"] or 0) * k * rnd.choice([0.9, 1.0, 1.15]), -3))
                 for r in paid if r["doctor_id"]]
        for scope, metric, v in rows:
            c.execute("INSERT OR REPLACE INTO kpi_targets(id, month, scope, metric, value, user_name, updated_at) VALUES(?,?,?,?,?,?,?)",
                      (f"{month}:{scope}:{metric}", month, scope, metric, v, "Демо", now))
        # treatment plans: started (with invoices billed from them), finished, accepted and refused
        for n, i in enumerate(inv[::3][:18]):
            st = ["Активен", "Активен", "Лечение завершено", "Подтверждён", "Отказ", "Активен"][n % 6]
            items = json.loads(i["items"] or "[]")
            extra = round(i["total"] * rnd.choice([1.5, 2, 3]), -2)
            items.append({"title": "Следующий этап лечения", "price": extra, "qty": 1, "sum": extra})
            pid = f"demo_dpl{n}"
            c.execute("""INSERT OR IGNORE INTO invoices(id, patient_id, doctor_id, items, total, discount, status, comment, created_at,
                         transferred, kind, plan_status, title) VALUES(?,?,?,?,?,0,'План','',?,1,'plan',?,?)""",
                      (pid, i["patient_id"], i["doctor_id"], json.dumps(items, ensure_ascii=False), i["total"] + extra,
                       i["created_at"], st, "План лечения"))
            if st in ("Активен", "Лечение завершено"):
                c.execute("UPDATE invoices SET plan_id=? WHERE id=?", (pid, i["id"]))



def ensure_crm(db):
    """Requests in every stage, after-visit scores, a couple of tasks and advertising expenses (once)."""
    from crm import CRM, _auto_id
    CRM(db)  # tables
    if db.one("SELECT 1 AS x FROM crm_leads WHERE created_by='Демо' LIMIT 1"):
        return
    pats = db.q("SELECT id, name, phone FROM patients WHERE COALESCE(local,0)=0 ORDER BY id LIMIT 40")
    docs = [d["id"] for d in db.q("SELECT id FROM doctors ORDER BY id")]
    if len(pats) < 16:
        return
    rnd = random.Random(11)
    today = date.today()
    now = utcnow()
    first = ["Мария", "Ольга", "Ирина", "Сергей", "Андрей", "Наталья", "Дмитрий", "Елена", "Алексей", "Татьяна", "Павел", "Юлия"]
    last = ["Смирнова", "Кузнецова", "Попова", "Соколов", "Лебедев", "Козлова", "Новиков", "Морозова", "Волков", "Зайцева", "Орлов", "Белова"]
    wants = ["Болит зуб", "Профгигиена", "Имплантация, консультация", "Брекеты для ребёнка", "Отбеливание", "Коронка", "Удаление зуба мудрости"]
    sources = ["Яндекс Карты", "2ГИС", "Сайт клиники", "Соцсети", "Рекомендация знакомых"]
    with db.tx() as c:
        for n in range(16):
            stage = ["new", "new", "contact", "contact", "booked", "came", "came", "lost"][n % 8]
            when = (datetime.now() - timedelta(days=rnd.randint(0, 25), hours=rnd.randint(0, 8))).strftime("%Y-%m-%d %H:%M:%S")
            pid = pats[n]["id"] if stage in ("booked", "came") else None
            c.execute("""INSERT INTO crm_leads(id, name, phone, source, channel, interest, comment, assignee, next_at, stage, lost_reason,
                         patient_id, created_at, created_by, updated_at, closed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (f"demo_ld{n}", pats[n]["name"] if pid else f"{last[n % 12]} {first[n % 12]}",
                       pats[n]["phone"] if pid else f"+7 9{rnd.randint(10, 99)} {rnd.randint(100, 999)}-{rnd.randint(10, 99)}-{rnd.randint(10, 99)}",
                       sources[n % 5], ["Звонок", "WhatsApp", "Сайт", "Звонок", "Пришёл в клинику"][n % 5], wants[n % 7], "", "",
                       (today + timedelta(days=rnd.randint(-2, 3))).isoformat() if stage in ("new", "contact") else None,
                       stage, "Дорого" if stage == "lost" else None, pid, when, "Демо", now, when if stage in ("came", "lost") else None))
        for n, p in enumerate(pats[16:36]):
            score = [10, 9, 10, 8, 9, 10, 7, 10, 9, 4, 10, 9, 8, 10, 9, 10, 6, 10, 9, 10][n]
            at = (datetime.now() - timedelta(days=rnd.randint(0, 20))).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""INSERT INTO crm_reviews(id, patient_id, visit_id, doctor_id, score, comment, channel, created_at, user_name)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      (f"demo_rv{n}", p["id"], None, docs[n % len(docs)] if docs else None, score,
                       {4: "Долго ждал в коридоре", 6: "Дороговато", 0: "Всё понравилось, спасибо!"}.get(score, "") if n % 3 == 0 or score < 7 else "",
                       ["tablet", "phone"][n % 2], at, "Демо"))
            if score <= 6:
                c.execute("""INSERT OR IGNORE INTO crm_tasks(id, title, kind, rule, patient_id, lead_id, plan_id, assignee, due, status, result,
                             comment, created_at, created_by, done_at, done_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (_auto_id("review", f"demo_rv{n}"), f"Пациент недоволен (оценка {score}) — позвонить и разобраться", "auto", "review",
                           p["id"], None, None, "", today.isoformat(), "open", None, "", now, "Программа", None, None, now))
        for n, (title, d) in enumerate([("Перезвонить по поводу рассрочки на имплантацию", 0), ("Отправить памятку после отбеливания", 1),
                                        ("Уточнить время повторного приёма", -1)]):
            c.execute("""INSERT INTO crm_tasks(id, title, kind, rule, patient_id, lead_id, plan_id, assignee, due, status, result, comment,
                         created_at, created_by, done_at, done_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (f"demo_tk{n}", title, "task", None, pats[36 + n % 4]["id"] if len(pats) > 36 + n % 4 else None, None, None, "",
                       (today + timedelta(days=d)).isoformat(), "open", None, "", now, "Демо", None, None, now))
        has_src = {r[1] for r in c.execute("PRAGMA table_info(expenses)")}
        if "source" in has_src and pats:
            for n, (src, amount) in enumerate([("Яндекс Карты", 15000), ("2ГИС", 8000), ("Соцсети", 12000), ("Сайт клиники", 5000)]):
                c.execute("""INSERT OR IGNORE INTO expenses(id, date, category, amount, method, person, period, comment, source, user_name, created_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (f"demo_ad{n}", today.replace(day=1).isoformat(), "Реклама", amount,
                                                                "Безналичный перевод", None, None, f"Реклама: {src}", src, "Демо", now))
