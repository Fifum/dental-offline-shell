"""Work schedules of the staff: one shift per person per day, filled by hand or by weekday pattern.

A person is a doctor from Dentist Plus ("d:<id>") or a staff account of this program that is not
linked to a doctor ("u:<id>" on the screens), so administrators and assistants get schedules too.
3.6.1: a staff account is stored under its login ("login:<login>"), because account ids differ between the clinic's
computers; a stored reference nobody here has is shown as «неизвестный сотрудник» (staffref.py).
"""
from __future__ import annotations

import calendar
import re
import sqlite3
from datetime import date, datetime

import staffref

SCHEMA = """
CREATE TABLE IF NOT EXISTS work_shifts(
    id INTEGER PRIMARY KEY AUTOINCREMENT, person TEXT, date TEXT, start TEXT, "end" TEXT, note TEXT,
    user_name TEXT, updated_at TEXT, UNIQUE(person, date));
CREATE INDEX IF NOT EXISTS ix_shifts_date ON work_shifts(date);
"""
_HM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def people(db):
    """Doctors plus active staff accounts without a doctor link: [{key, name, position, kind}]."""
    out = [{"key": f"d:{d['id']}", "id": d["id"], "name": d["name"], "kind": "doctor",
            "position": ""} for d in db.doctors()]
    try:
        import json
        pos = {r["id"]: (json.loads(r["data"] or "{}").get("position") or "") for r in db.q("SELECT id, data FROM doctors")}
        for p in out:
            p["position"] = pos.get(p["id"], "")
    except (ValueError, sqlite3.OperationalError):
        pass
    try:
        for u in db.q("SELECT id, name, position FROM users WHERE status='active' AND COALESCE(doctor_id,'')='' ORDER BY name"):
            out.append({"key": f"u:{u['id']}", "id": u["id"], "name": u["name"], "kind": "staff", "position": u["position"] or ""})
    except sqlite3.OperationalError:  # no accounts table yet (tests without the server)
        pass
    return out


def person_name(db, key):
    return next((p["name"] for p in people(db) if p["key"] == key), None)


def _hm(v, what):
    s = str(v or "").strip().replace(".", ":")
    if re.fullmatch(r"\d{1,2}", s):
        s += ":00"
    m = _HM.match(s)
    if not m:
        raise ValueError(f"{what}: время в формате ЧЧ:ММ")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _month(month):
    try:
        y, m = map(int, str(month or date.today().strftime("%Y-%m"))[:7].split("-"))
        return y, m, calendar.monthrange(y, m)[1]
    except ValueError:
        raise ValueError("Неверный месяц") from None


def _hours(start, end):
    return (int(end[:2]) * 60 + int(end[3:]) - int(start[:2]) * 60 - int(start[3:])) / 60


class Shifts:
    def __init__(self, db):
        self.db = db
        db.conn.executescript(SCHEMA)
        db.conn.commit()

    def month(self, month=None):
        y, m, n = _month(month)
        first, last = f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{n:02d}"
        rows = self.db.q('SELECT person, date, start, "end", note FROM work_shifts WHERE date BETWEEN ? AND ?', (first, last))
        ppl = people(self.db)
        idx = staffref.Index(self.db)
        shifts, totals = {}, {}
        for r in rows:
            k = staffref.to_screen(self.db, r["person"], idx)
            shifts.setdefault(k, {})[r["date"]] = {"start": r["start"], "end": r["end"], "note": r["note"] or ""}
            t = totals.setdefault(k, {"days": 0, "hours": 0.0})
            t["days"] += 1
            t["hours"] = round(t["hours"] + _hours(r["start"], r["end"]), 2)
        # 3.6.1: shifts of a reference nobody here has stay visible (they can be removed), never under somebody else
        ppl += [{"key": k, "id": None, "name": staffref.unknown_name(k), "kind": "unknown",
                 "position": "нет такой учётной записи на этом компьютере"} for k in sorted(shifts) if staffref.is_unknown(k)]
        return {"month": f"{y:04d}-{m:02d}", "days": [f"{y:04d}-{m:02d}-{d:02d}" for d in range(1, n + 1)],
                "people": ppl, "shifts": shifts, "totals": totals}

    def _check_person(self, key):
        """The screen key of a listed person → what is stored (3.6.1: the login of a staff account)."""
        if not any(p["key"] == key for p in people(self.db)):
            raise ValueError("Сотрудник не найден")
        return staffref.to_store(self.db, key)

    def save(self, f, who=""):
        """Set (or with an empty start, remove) one person's shift on one day."""
        key, day = str(f.get("person") or ""), str(f.get("date") or "")[:10]
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError("Неверная дата") from None
        if staffref.is_unknown(key):  # a shift of «неизвестный сотрудник» can only be removed
            if str(f.get("start") or "").strip():
                raise ValueError("Сотрудник не найден на этом компьютере — такую смену можно только удалить")
            with self.db.tx() as c:
                c.execute("DELETE FROM work_shifts WHERE person=? AND date=?", (staffref.to_store(self.db, key), day))
            return None
        screen, key = key, self._check_person(key)
        if not str(f.get("start") or "").strip():
            with self.db.tx() as c:
                c.execute("DELETE FROM work_shifts WHERE person=? AND date=?", (key, day))
            return None
        start, end = _hm(f.get("start"), "Начало"), _hm(f.get("end"), "Конец")
        if end <= start:
            raise ValueError("Конец смены должен быть позже начала")
        with self.db.tx() as c:
            c.execute("""INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)
                         ON CONFLICT(person, date) DO UPDATE SET start=excluded.start, "end"=excluded."end",
                         note=excluded.note, user_name=excluded.user_name, updated_at=excluded.updated_at""",
                      (key, day, start, end, str(f.get("note") or "").strip()[:200], who, _now()))
        return {"person": screen, "date": day, "start": start, "end": end}

    def fill(self, f, who=""):
        """Fill a month by weekdays (0 = Monday): «Пн–Пт 09:00–18:00». Returns how many days were set."""
        keys = f.get("people") or ([f["person"]] if f.get("person") else [])
        if not keys:
            raise ValueError("Выберите сотрудников")
        keys = [self._check_person(k) for k in keys]
        wd = {int(x) for x in (f.get("weekdays") or []) if str(x).isdigit() and 0 <= int(x) <= 6}
        if not wd:
            raise ValueError("Отметьте дни недели")
        start, end = _hm(f.get("start"), "Начало"), _hm(f.get("end"), "Конец")
        if end <= start:
            raise ValueError("Конец смены должен быть позже начала")
        y, m, n = _month(f.get("month"))
        every = max(1, int(f.get("every") or 1))  # 2 = every other week
        overwrite = bool(f.get("overwrite"))
        count = 0
        with self.db.tx() as c:
            for d in range(1, n + 1):
                day = date(y, m, d)
                if day.weekday() not in wd or ((d - 1) // 7) % every:
                    continue
                for k in keys:
                    if not overwrite and c.execute("SELECT 1 FROM work_shifts WHERE person=? AND date=?", (k, day.isoformat())).fetchone():
                        continue
                    c.execute("""INSERT INTO work_shifts(person, date, start, "end", note, user_name, updated_at) VALUES(?,?,?,?,?,?,?)
                                 ON CONFLICT(person, date) DO UPDATE SET start=excluded.start, "end"=excluded."end",
                                 user_name=excluded.user_name, updated_at=excluded.updated_at""",
                              (k, day.isoformat(), start, end, "", who, _now()))
                    count += 1
        return count

    def clear(self, person, month):
        person = staffref.to_store(self.db, person) if staffref.is_unknown(person) else self._check_person(person)
        y, m, n = _month(month)
        with self.db.tx() as c:
            cur = c.execute("DELETE FROM work_shifts WHERE person=? AND date BETWEEN ? AND ?",
                            (person, f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{n:02d}"))
            return cur.rowcount

    def day(self, day):
        """{doctor_id: {start, end}} for the calendar; None when nobody has a shift that day (schedules not used)."""
        rows = self.db.q('SELECT person, start, "end" FROM work_shifts WHERE date=? AND person LIKE \'d:%\'', (str(day)[:10],))
        return {r["person"][2:]: {"start": r["start"], "end": r["end"]} for r in rows} or None
