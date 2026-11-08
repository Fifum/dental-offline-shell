"""Waiting list: patients who want an earlier or a specific time («позвоните, если освободится окно»).

An entry is a patient, an optional doctor, what they want and the dates that suit them. When a visit is
booked from the list the entry is marked «записан» and linked to the visit; when a visit of that doctor
is cancelled the schedule reminds the administrator that people are waiting.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS waitlist(
    id TEXT PRIMARY KEY, patient_id TEXT, doctor_id TEXT, wish TEXT, date_from TEXT, date_to TEXT, note TEXT,
    status TEXT DEFAULT 'wait', visit_id TEXT, created_at TEXT, created_by TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_waitlist_status ON waitlist(status);
"""
STATUSES = {"wait": "ждёт", "booked": "записан", "removed": "убран"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _day(v):
    v = str(v or "").strip()[:10]
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError("Дата указана неверно") from None


class Waitlist:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def list(self, status="wait", doctor_id=None, day=None) -> list[dict]:
        """Entries, oldest first. With `day`, only those whose dates include that day."""
        sql = """SELECT w.*, p.name AS patient_name, p.phone AS patient_phone, d.name AS doctor_name
                 FROM waitlist w LEFT JOIN patients p ON p.id=w.patient_id LEFT JOIN doctors d ON d.id=w.doctor_id
                 WHERE 1=1"""
        args = []
        if status and status != "all":
            sql += " AND w.status=?"
            args.append(status)
        if doctor_id:
            sql += " AND (w.doctor_id=? OR w.doctor_id IS NULL OR w.doctor_id='')"
            args.append(doctor_id)
        if day:
            sql += " AND (w.date_from IS NULL OR w.date_from<=?) AND (w.date_to IS NULL OR w.date_to>=?)"
            args += [day, day]
        sql += " ORDER BY w.created_at"
        rows = self.db.q(sql, args)
        for r in rows:
            r["status_text"] = STATUSES.get(r["status"], r["status"])
        return rows

    def count(self, doctor_id=None, day=None) -> int:
        return len(self.list("wait", doctor_id, day))

    def save(self, f: dict, who="") -> str:
        pid = str(f.get("patient_id") or "").strip()
        if not pid:
            raise ValueError("Выберите пациента")
        if not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Пациент не найден")
        d0, d1 = _day(f.get("date_from")), _day(f.get("date_to"))
        if d0 and d1 and d1 < d0:
            raise ValueError("Дата «по» раньше даты «с»")
        vals = (pid, f.get("doctor_id") or None, str(f.get("wish") or "").strip()[:300], d0, d1,
                str(f.get("note") or "").strip()[:500])
        ts = _now()
        with self.db.tx() as c:
            if f.get("id"):
                if not c.execute("SELECT 1 FROM waitlist WHERE id=?", (f["id"],)).fetchone():
                    raise ValueError("Запись листа ожидания не найдена")
                c.execute("""UPDATE waitlist SET patient_id=?, doctor_id=?, wish=?, date_from=?, date_to=?, note=?, updated_at=?
                             WHERE id=?""", (*vals, ts, f["id"]))
                return f["id"]
            wid = "W-" + uuid.uuid4().hex[:10]
            c.execute("""INSERT INTO waitlist(id, patient_id, doctor_id, wish, date_from, date_to, note, status, created_at,
                         created_by, updated_at) VALUES(?,?,?,?,?,?,?,'wait',?,?,?)""", (wid, *vals, ts, who or "", ts))
            return wid

    def set_status(self, wid: str, status: str, visit_id=None) -> bool:
        if status not in STATUSES:
            raise ValueError("Неизвестный статус")
        with self.db.tx() as c:
            n = c.execute("UPDATE waitlist SET status=?, visit_id=COALESCE(?, visit_id), updated_at=? WHERE id=?",
                          (status, visit_id, _now(), wid)).rowcount
        if not n:
            raise ValueError("Запись листа ожидания не найдена")
        return True
