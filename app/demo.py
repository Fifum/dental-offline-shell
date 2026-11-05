"""Demo data so the app can be shown before API credentials are available."""
from __future__ import annotations

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
