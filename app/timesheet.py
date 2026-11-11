"""3.4: time tracking — the actual arrival and leaving of every employee (the timesheet) against the work schedule.

An employee presses «Я пришёл» / «Я ушёл» under his own account (the menu of the user in the top bar); the director or
whoever makes the schedules («Графики работы: составление») can correct a mark, and the correction is flagged.
One row per person per day in `time_marks`, synced between the clinic's computers like the schedules: two computers
that marked the arrival and the leaving of the same day merge field by field.

People are the same as in the schedules (shifts.people): a doctor from Dentist Plus («d:<id>») or a staff account.
A staff account is stored under its login («login:<login>»), not under the local integer id, because integer ids of
accounts differ between computers; the screens get the usual «u:<id>» keys.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from shifts import _hm, _month, people

SCHEMA = """
CREATE TABLE IF NOT EXISTS time_marks(
    id TEXT PRIMARY KEY, person TEXT, date TEXT, came TEXT, "left" TEXT, note TEXT, by TEXT, edited INTEGER DEFAULT 0,
    updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_time_marks_date ON time_marks(date);
CREATE TABLE IF NOT EXISTS staff_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT);
"""
DEFAULTS = {"late_grace": 5, "early_grace": 5}
STATUS = {"ok": "по графику", "late": "опоздание", "early": "ушёл раньше", "absent": "нет отметки", "extra": "вне графика",
          "noleave": "нет ухода", "wait": "ещё не отмечен", "future": "", "untracked": "не отмечается в табеле"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _min(hm):
    return int(hm[:2]) * 60 + int(hm[3:5]) if hm else None


# ------------------------------------------------------------------ people: stable keys --
def stable(db, key) -> str:
    """«u:<id>» → «login:<login>» (the same on every computer); a doctor «d:<id>» stays as it is."""
    key = str(key or "")
    if key.startswith("u:"):
        try:
            r = db.one("SELECT login FROM users WHERE id=?", (int(key[2:]),))
        except (ValueError, sqlite3.OperationalError):
            r = None
        if r and r["login"]:
            return "login:" + r["login"].lower()
    return key


def local(db, skey) -> str:
    """«login:<login>» → «u:<id>» of this computer; anything else stays."""
    skey = str(skey or "")
    if skey.startswith("login:"):
        try:
            r = db.one("SELECT id FROM users WHERE lower(login)=lower(?)", (skey[6:],))
        except sqlite3.OperationalError:
            r = None
        if r:
            return f"u:{r['id']}"
    return skey


def user_person(u) -> str | None:
    """The person of a signed-in account: its doctor, or the account itself."""
    if not u:
        return None
    if u.get("doctor_id"):
        return f"d:{u['doctor_id']}"
    return "login:" + str(u.get("login") or "").lower() if u.get("login") else None


def settings(db) -> dict:
    out = dict(DEFAULTS)
    try:
        for r in db.q("SELECT k, v FROM staff_settings"):
            if r["k"] in DEFAULTS:
                try:
                    out[r["k"]] = max(0, min(120, int(float(r["v"]))))
                except (TypeError, ValueError):
                    pass
    except sqlite3.OperationalError:
        pass
    return out


def save_settings(db, f) -> dict:
    f = f or {}
    with db.tx() as c:
        for k in DEFAULTS:
            if k in f:
                try:
                    v = int(float(str(f[k]).replace(",", ".")))
                except (TypeError, ValueError):
                    raise ValueError("Допуск — число минут") from None
                if not 0 <= v <= 120:
                    raise ValueError("Допуск: от 0 до 120 минут")
                c.execute("""INSERT INTO staff_settings(k, v, updated_at) VALUES(?,?,?)
                             ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at""", (k, str(v), _now()))
    return settings(db)


class Timesheet:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    # ------------------------------------------------------------ marks --
    def mark(self, skey, day) -> dict | None:
        return self.db.one("SELECT * FROM time_marks WHERE id=?", (f"{skey}|{day}",))

    def clock(self, u, kind, now=None) -> dict:
        """«Я пришёл» / «Я ушёл» of the signed-in employee. Coming back after leaving reopens the day."""
        skey = user_person(u)
        if not skey:
            raise ValueError("Отметить приход можно только под своей учётной записью")
        if kind not in ("in", "out"):
            raise ValueError("Неизвестная отметка")
        now = now or datetime.now()
        day, hm = now.date().isoformat(), now.strftime("%H:%M")
        cur = self.mark(skey, day)
        with self.db.tx() as c:
            if kind == "in":
                if not cur:
                    c.execute("""INSERT INTO time_marks(id, person, date, came, "left", note, by, edited, updated_at)
                                 VALUES(?,?,?,?,?,?,?,?,?)""", (f"{skey}|{day}", skey, day, hm, None, "", u.get("name") or "", 0, _now()))
                elif cur["left"]:
                    c.execute('UPDATE time_marks SET "left"=NULL, updated_at=? WHERE id=?', (_now(), cur["id"]))
                elif not cur["came"]:
                    c.execute("UPDATE time_marks SET came=?, updated_at=? WHERE id=?", (hm, _now(), cur["id"]))
            else:
                if not cur or not cur["came"]:
                    raise ValueError("Сначала отметьте приход")
                if hm < cur["came"]:
                    hm = cur["came"]
                c.execute('UPDATE time_marks SET "left"=?, updated_at=? WHERE id=?', (hm, _now(), cur["id"]))
        return self.me(u, now)

    def me(self, u, now=None) -> dict:
        skey = user_person(u)
        now = now or datetime.now()
        day = now.date().isoformat()
        if not skey:
            return {"person": None, "can": False, "day": day}
        m = self.mark(skey, day)
        key = local(self.db, skey)
        sh = self.db.one('SELECT start, "end" FROM work_shifts WHERE person=? AND date=?', (key, day)) if key else None
        state = "out" if not m or not m["came"] else ("in" if not m["left"] else "left")
        return {"person": key, "can": True, "day": day, "came": (m or {}).get("came"), "left": (m or {}).get("left"),
                "state": state, "shift": sh}

    def save(self, f, who="") -> dict | None:
        """A correction by the director / the schedule maker. Empty arrival and leaving remove the mark."""
        f = f or {}
        key = str(f.get("person") or "")
        if not any(p["key"] == key for p in people(self.db)):
            raise ValueError("Сотрудник не найден")
        day = str(f.get("date") or "")[:10]
        try:
            d = date.fromisoformat(day)
        except ValueError:
            raise ValueError("Неверная дата") from None
        if d > date.today():
            raise ValueError("Отметку за будущий день поставить нельзя")
        skey = stable(self.db, key)
        came = _hm(f["came"], "Приход") if str(f.get("came") or "").strip() else None
        left = _hm(f["left"], "Уход") if str(f.get("left") or "").strip() else None
        note = str(f.get("note") or "").strip()[:200]
        rid = f"{skey}|{day}"
        with self.db.tx() as c:
            if not came and not left:
                c.execute("DELETE FROM time_marks WHERE id=?", (rid,))
                return None
            if not came:
                raise ValueError("Укажите время прихода")
            if left and left < came:
                raise ValueError("Уход должен быть позже прихода")
            c.execute("""INSERT INTO time_marks(id, person, date, came, "left", note, by, edited, updated_at) VALUES(?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET came=excluded.came, "left"=excluded."left", note=excluded.note,
                         by=excluded.by, edited=1, updated_at=excluded.updated_at""", (rid, skey, day, came, left, note, who or "", 1, _now()))
        return self.mark(skey, day)

    # ------------------------------------------------------- timesheet --
    def period(self, a, b, only=None) -> dict:
        """Days [a, b] (dates, inclusive): plan (work schedule) against fact (marks) for every person who has either.
        `only` — a set of person keys («u:…», «d:…») to show."""
        a, b = (x if isinstance(x, date) else date.fromisoformat(str(x)[:10]) for x in (a, b))
        days = [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
        st = settings(self.db)
        today = date.today().isoformat()
        plan, fact = {}, {}
        for r in self.db.q('SELECT person, date, start, "end" FROM work_shifts WHERE date BETWEEN ? AND ?', (days[0], days[-1])):
            plan.setdefault(r["person"], {})[r["date"]] = (r["start"], r["end"])
        for r in self.db.q('SELECT * FROM time_marks WHERE date BETWEEN ? AND ?', (days[0], days[-1])):
            fact.setdefault(local(self.db, r["person"]), {})[r["date"]] = r
        ppl = [p for p in people(self.db) if (p["key"] in plan or p["key"] in fact) and (only is None or p["key"] in only)]
        rows = []
        for p in ppl:
            # who never marks in the period (e.g. a doctor who does not use the timesheet) is not «absent» every day
            tracked = bool(fact.get(p["key"]))
            cells, t = {}, {"plan_min": 0, "fact_min": 0, "late_n": 0, "late_min": 0, "early_n": 0, "early_min": 0, "absent_n": 0,
                            "extra_n": 0, "noleave_n": 0, "days": 0, "edited_n": 0}
            for d in days:
                pl, m = plan.get(p["key"], {}).get(d), fact.get(p["key"], {}).get(d)
                if not pl and not m:
                    continue
                c = self._cell(d, pl, m, st, today)
                if not tracked:
                    c["status"] = "untracked"
                cells[d] = c
                t["plan_min"] += c["plan_min"]
                t["fact_min"] += c["fact_min"]
                t["days"] += 1 if m and m["came"] else 0
                t["edited_n"] += 1 if m and m["edited"] else 0
                if c["late"]:
                    t["late_n"] += 1
                    t["late_min"] += c["late"]
                if c["early"]:
                    t["early_n"] += 1
                    t["early_min"] += c["early"]
                t["absent_n"] += c["status"] == "absent"
                t["extra_n"] += c["status"] == "extra"
                t["noleave_n"] += c["status"] == "noleave"
            t["plan_h"], t["fact_h"] = round(t["plan_min"] / 60, 2), round(t["fact_min"] / 60, 2)
            t["diff_h"] = round((t["fact_min"] - t["plan_min"]) / 60, 2)
            rows.append({**p, "cells": cells, "totals": t, "tracked": tracked})
        rows.sort(key=lambda r: not r["tracked"])  # those who mark first
        return {"from": days[0], "to": days[-1], "days": days, "rows": rows, "settings": st, "statuses": STATUS}

    @staticmethod
    def _cell(d, pl, m, st, today) -> dict:
        came, left = (m or {}).get("came"), (m or {}).get("left")
        c = {"plan": list(pl) if pl else None, "came": came, "left": left, "note": (m or {}).get("note") or "",
             "edited": bool((m or {}).get("edited")), "late": 0, "early": 0, "plan_min": 0, "fact_min": 0}
        if pl:
            c["plan_min"] = max(0, _min(pl[1]) - _min(pl[0]))
        if came and left:
            c["fact_min"] = max(0, _min(left) - _min(came))
        if pl and not came:
            c["status"] = "absent" if d < today else "wait" if d == today else "future"
            return c
        if not pl:
            c["status"] = "noleave" if not left and d < today else "extra"
            return c
        late = _min(came) - _min(pl[0])
        c["late"] = late if late > st["late_grace"] else 0
        if left:
            early = _min(pl[1]) - _min(left)
            c["early"] = early if early > st["early_grace"] else 0
        if not left and d < today:
            c["status"] = "noleave"
        elif c["late"]:
            c["status"] = "late"
        elif c["early"]:
            c["status"] = "early"
        else:
            c["status"] = "ok"
        return c

    def month(self, month=None, only=None) -> dict:
        y, m, n = _month(month)
        out = self.period(date(y, m, 1), date(y, m, n), only)
        out["month"] = f"{y:04d}-{m:02d}"
        return out

    def summary(self, a, b) -> list[dict]:
        """Short lines for the weekly and monthly report: who was late, who has no mark."""
        r = self.period(a, b)
        out = []
        for p in r["rows"]:
            t = p["totals"]
            if not p["tracked"] or not (t["plan_min"] or t["fact_min"]):
                continue
            out.append({"name": p["name"], "plan_h": t["plan_h"], "fact_h": t["fact_h"], "late_n": t["late_n"], "late_min": t["late_min"],
                        "early_n": t["early_n"], "absent_n": t["absent_n"], "noleave_n": t["noleave_n"], "extra_n": t["extra_n"]})
        return out
