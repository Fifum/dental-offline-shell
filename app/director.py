"""The director's analytics: the main screen, patients (new, repeat, retention), chair and doctor load,
conversion «consultation → plan → treatment», the share of materials in revenue and plan vs fact.

Visits come from the schedule (Dentist Plus + changes made here) plus `visits_archive`, the history of
Dentist Plus visits that is never purged. Money is what was billed and paid in this program (reports.py).
Only `kpi_targets` (the director's plans and the number of chairs) is written here.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

import config
from db import DB
from reports import _period, status_kind

SCHEMA = """
CREATE TABLE IF NOT EXISTS kpi_targets(
    id TEXT PRIMARY KEY, month TEXT, scope TEXT, metric TEXT, value REAL, user_name TEXT, updated_at TEXT);
"""
METRICS = {"revenue": "Поступления, ₽", "visits": "Приёмы", "new_patients": "Новые пациенты"}
PLAN_STARTED = ("Активен", "Лечение завершено")
PLAN_ACCEPTED = ("Подтверждён",) + PLAN_STARTED
PLAN_OPEN = ("Предварительный", "Подтверждён")
WD = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
LOST = ("cancel", "noshow")
RETURN_DAYS = (90, 180)       # a new patient «returned» when there is another visit within this many days
LOST_FROM, LOST_TO = 180, 540  # «gone»: the last visit was this many days ago and nothing is booked

# Every visit the program knows about: the schedule, then archived Dentist Plus visits that left the mirror
# (minus those a local edit stands for).
HIST = f"""SELECT a.id, a.patient_id, a.doctor_id, a.start, a."end", a.status, {DB.CHAIR} AS chair FROM ({DB.ALL_VISITS}) a
    UNION ALL
    SELECT h.id, h.patient_id, h.doctor_id, h.start, h."end", h.status, h.chair FROM visits_archive h
    WHERE h.id NOT IN (SELECT id FROM visits)
      AND h.id NOT IN (SELECT origin_id FROM local_visits WHERE origin_id IS NOT NULL)
      AND h.id NOT IN (SELECT remote_id FROM local_visits WHERE remote_id IS NOT NULL)"""


def _plural(n, one, few, many):
    m, h = n % 10, n % 100
    return one if m == 1 and h != 11 else few if 2 <= m <= 4 and not 12 <= h <= 14 else many


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _hm(s):
    try:
        return int(s[11:13]) * 60 + int(s[14:16])
    except (TypeError, ValueError, IndexError):
        return None


def _mins(start, end):
    a, b = _hm(start), _hm(end)
    return max(0, b - a) if a is not None and b is not None and str(start)[:10] == str(end)[:10] else 0


def _pct(a, b):
    return round(a * 100 / b, 1) if b else None


def _month(m):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(m or "")):
        raise ValueError("Месяц в формате ГГГГ-ММ")
    y, mm = int(m[:4]), int(m[5:7])
    return date(y, mm, 1), date(y, mm, calendar.monthrange(y, mm)[1])


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Director:
    def __init__(self, db, reports):
        self.db, self.rep = db, reports
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    # ============================================================ helpers --
    def _visits(self, a, b):
        """Visits starting in [a, b) with their kind, length and whether they are over."""
        now = _now()
        rows = self.db.q(f"SELECT * FROM ({HIST}) WHERE start >= ? AND start < ? ORDER BY start", (str(a), str(b)))
        for r in rows:
            r["kind"] = status_kind(r["status"])
            r["min"] = _mins(r["start"], r["end"])
            r["past"] = r["start"] < now
            r["chair"] = str(r["chair"]).strip() if r["chair"] not in (None, "") else ""
        return rows

    def _first_visits(self):
        """{patient_id: (first day, doctor_id)} by the first visit that took place (not cancelled or missed)."""
        out = {}
        for r in self.db.q(f"SELECT patient_id, doctor_id, start, status FROM ({HIST}) WHERE patient_id IS NOT NULL ORDER BY start"):
            if r["patient_id"] not in out and status_kind(r["status"]) not in LOST:
                out[r["patient_id"]] = (r["start"][:10], r["doctor_id"])
        return out

    def history_from(self):
        r = self.db.one(f"SELECT MIN(start) AS f FROM ({HIST})")
        return (r["f"] or "")[:10] if r else ""

    def _hours(self):
        s = config.load_settings()
        try:
            h0, h1 = int(s.get("day_start") or 8), int(s.get("day_end") or 21)
        except (TypeError, ValueError):
            h0, h1 = 8, 21
        h0, h1 = max(0, min(23, h0)), max(1, min(24, h1))
        return (h0, h1) if h1 > h0 else (8, 21)

    def _workweek(self):
        """Weekdays the clinic works on, seen from the last ten weeks of visits (Mon–Sat when there is nothing yet)."""
        t = date.today()
        n = [0] * 7
        for r in self.db.q(f"SELECT start FROM ({HIST}) WHERE start >= ? AND start < ?",
                           ((t - timedelta(days=70)).isoformat(), (t + timedelta(days=1)).isoformat())):
            try:
                n[_d(r["start"]).weekday()] += 1
            except ValueError:
                pass
        top = max(n)
        return {i for i in range(7) if n[i] >= top * 0.2} if top else {0, 1, 2, 3, 4, 5}

    def _workdays(self, a, b, week=None):
        """Working days in [a, b]."""
        week = self._workweek() if week is None else week
        a, b = _d(a), _d(b)
        return [a + timedelta(days=i) for i in range((b - a).days + 1) if (a + timedelta(days=i)).weekday() in week]

    def settings(self):
        r = self.db.one("SELECT value FROM kpi_targets WHERE id='*:clinic:chairs'")
        t = date.today()
        seen = {v["chair"] for v in self._visits(t - timedelta(days=60), t + timedelta(days=30)) if v["chair"]}
        return {"chairs": int(r["value"]) if r and r["value"] else None, "chairs_seen": len(seen),
                "hours": list(self._hours())}

    def save_settings(self, f, user=""):
        v = str((f or {}).get("chairs") or "").strip()
        with self.db.tx() as c:
            if not v:
                c.execute("DELETE FROM kpi_targets WHERE id='*:clinic:chairs'")
                return True
            if not v.isdigit() or not 1 <= int(v) <= 60:
                raise ValueError("Кресел: число от 1 до 60")
            c.execute("""INSERT OR REPLACE INTO kpi_targets(id, month, scope, metric, value, user_name, updated_at)
                         VALUES('*:clinic:chairs','*','clinic','chairs',?,?,?)""", (int(v), user, _now()))
        return True

    def _chairs(self):
        s = self.settings()
        return s["chairs"] or s["chairs_seen"] or max(1, len(self.db.doctors()))

    def _doctor_names(self):
        return {d["id"]: d["name"] for d in self.db.doctors()}

    def _shift_minutes(self, a, b):
        """{doctor_id: minutes of work by the work schedule in [a, b]} (only doctors that have a schedule)."""
        out = {}
        try:
            rows = self.db.q('SELECT person, start, "end" FROM work_shifts WHERE date >= ? AND date <= ? AND person LIKE \'d:%\'',
                             (str(a), str(b)))
        except Exception:  # noqa: BLE001 — no schedules table yet
            return out
        for r in rows:
            m = _mins("0000-00-00 " + (r["start"] or ""), "0000-00-00 " + (r["end"] or ""))
            out[r["person"][2:]] = out.get(r["person"][2:], 0) + m
        return out

    # ===================================================== main screen --
    def dashboard(self):
        t = date.today()
        m0 = t.replace(day=1)
        m1 = date(t.year, t.month, calendar.monthrange(t.year, t.month)[1])
        p0 = (m0 - timedelta(days=1)).replace(day=1)
        p_to = min(p0 + (t - m0), m0 - timedelta(days=1))
        week = self._workweek()
        h0, h1 = self._hours()
        chairs = self._chairs()
        day_cap = chairs * (h1 - h0) * 60

        today = self.rep.revenue(t, t)
        mtd = self.rep.revenue(m0, t)
        prev = self.rep.revenue(p0, p_to)
        wd_all, wd_done = self._workdays(m0, m1, week), self._workdays(m0, t, week)
        pace = len(wd_done) / len(wd_all) if wd_all else 1
        forecast = round(mtd["paid"] / pace, 2) if pace and wd_done else 0.0

        vis = self._visits(m0, t + timedelta(days=8))
        vt = [v for v in vis if v["start"][:10] == t.isoformat()]
        past_m = [v for v in vis if v["past"] and v["start"][:10] >= m0.isoformat()]
        prev_v = [v for v in self._visits(p0, p_to + timedelta(days=1)) if v["past"]]
        lost_m = sum(v["kind"] in LOST for v in past_m)
        lost_p = sum(v["kind"] in LOST for v in prev_v)
        booked_today = sum(v["min"] for v in vt if v["kind"] not in LOST)

        ahead = []
        for i in range(1, 8):
            d = t + timedelta(days=i)
            if d.weekday() not in week:
                continue
            ds = d.isoformat()
            mins = sum(v["min"] for v in vis if v["start"][:10] == ds and v["kind"] not in LOST)
            ahead.append({"day": ds, "wd": WD[d.weekday()], "booked": mins, "load": _pct(mins, day_cap) or 0,
                          "visits": sum(1 for v in vis if v["start"][:10] == ds and v["kind"] not in LOST)})

        first = self._first_visits()
        new_m = sum(1 for f in first.values() if m0.isoformat() <= f[0] <= t.isoformat())
        new_p = sum(1 for f in first.values() if p0.isoformat() <= f[0] <= p_to.isoformat())
        plans = self.db.q("""SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS s FROM invoices WHERE kind='plan'
                             AND COALESCE(plan_status,'Предварительный') IN ('Предварительный','Подтверждён') AND created_at >= ?""",
                          ((t - timedelta(days=365)).isoformat(),))[0]
        debts = self.rep.debts()
        kpi = self.kpi(m0.strftime("%Y-%m"))
        clinic_plan = kpi["clinic"]["metrics"]["revenue"]["plan"]

        # doctors this month
        names = self._doctor_names()
        shifts = self._shift_minutes(m0, t)
        by_doc = {}
        for v in past_m:
            if not v["doctor_id"]:
                continue
            x = by_doc.setdefault(v["doctor_id"], {"visits": 0, "booked": 0, "days": set()})
            if v["kind"] not in LOST:
                x["visits"] += 1
                x["booked"] += v["min"]
                x["days"].add(v["start"][:10])
        docs = []
        rev_by = {d["doctor_id"]: d for d in mtd["by_doctor"] if d["doctor_id"]}
        targets = {r["scope"][2:]: r for r in kpi["doctors"]}
        for did in sorted(set(by_doc) | set(rev_by) | set(targets), key=lambda k: names.get(k, "")):
            if did not in names:
                continue
            x, r = by_doc.get(did, {"visits": 0, "booked": 0, "days": set()}), rev_by.get(did, {})
            avail = shifts.get(did) or len(x["days"]) * (h1 - h0) * 60
            plan = (targets.get(did) or {}).get("metrics", {}).get("revenue", {}).get("plan")
            paid = r.get("paid", 0)
            docs.append({"doctor_id": did, "name": names[did], "paid": paid, "billed": r.get("billed", 0),
                         "plan": plan, "plan_pct": _pct(paid, plan), "forecast": round(paid / pace, 2) if pace and wd_done else 0,
                         "visits": x["visits"], "load": _pct(x["booked"], avail), "by_shifts": did in shifts,
                         "avg_check": round(r["billed"] / r["invoices"], 2) if r.get("invoices") else 0})
        docs.sort(key=lambda d: -d["paid"])

        out = {
            "today": {"day": t.isoformat(), "paid": today["paid"], "billed": today["billed"],
                      "visits": sum(1 for v in vt if v["kind"] not in LOST), "lost": sum(v["kind"] in LOST for v in vt),
                      "came": sum(v["kind"] in ("came", "done") for v in vt), "load": _pct(booked_today, day_cap) or 0,
                      "workday": t.weekday() in week},
            "month": {"from": m0.isoformat(), "to": t.isoformat(), "paid": mtd["paid"], "billed": mtd["billed"],
                      "prev_paid": prev["paid"], "delta": _pct(mtd["paid"] - prev["paid"], prev["paid"]),
                      "forecast": forecast, "plan": clinic_plan, "plan_pct": _pct(mtd["paid"], clinic_plan),
                      "forecast_pct": _pct(forecast, clinic_plan), "workdays": len(wd_all), "workdays_done": len(wd_done),
                      "avg_check": mtd["avg_check"], "prev_avg_check": prev["avg_check"],
                      "new_patients": new_m, "prev_new_patients": new_p,
                      "lost_share": _pct(lost_m, len(past_m)) or 0, "prev_lost_share": _pct(lost_p, len(prev_v)) or 0,
                      "prev_visits": len(prev_v),
                      "by_day": mtd["by_day"]},
            "ahead": ahead, "doctors": docs, "chairs": chairs, "hours": [h0, h1],
            "plans_open": {"count": plans["n"], "sum": round(plans["s"], 2)},
            "debts": debts["total_debt"],
        }
        out["advice"] = self._advice(out, past_m)
        return out

    def _advice(self, d, past_m):
        """What deserves the director's attention, in plain words (simple rules, no AI)."""
        m, out = d["month"], []

        def rub(v):
            return f"{round(v):,}".replace(",", " ") + " ₽"
        if m["plan"]:
            gap = m["plan"] - m["forecast"]
            if gap > m["plan"] * 0.03:
                out.append({"level": "warn", "go": "plan",
                            "text": f"Прогноз месяца {rub(m['forecast'])} — ниже плана на {rub(gap)}. Нужно примерно "
                                    f"{rub(gap / max(1, m['workdays'] - m['workdays_done']))} сверх обычного в каждый оставшийся рабочий день."})
            else:
                out.append({"level": "ok", "go": "plan", "text": f"Клиника идёт к плану: прогноз {rub(m['forecast'])} при плане {rub(m['plan'])}."})
        else:
            out.append({"level": "info", "go": "plan", "text": "План на месяц не задан — задайте его, и здесь появится прогноз выполнения."})
        pace = m["workdays_done"] / m["workdays"] if m["workdays"] else 0
        for doc in d["doctors"]:
            if doc["plan"] and pace >= 0.25 and (doc["plan_pct"] or 0) < pace * 100 * 0.8:
                out.append({"level": "warn", "go": "plan",
                            "text": f"{doc['name']}: выполнено {doc['plan_pct'] or 0:g} % плана, а прошло {round(pace * 100)} % рабочих дней."})
        low = [a for a in d["ahead"][:3] if a["load"] < 50]
        if low:
            days = ", ".join(f"{a['wd']} {int(a['day'][8:10])} — {a['load']:g} %" for a in low)
            out.append({"level": "warn", "go": "schedule",
                        "text": f"Свободные окна в ближайшие дни ({days}). Предложите их пациентам из листа ожидания и обзвона."})
        grew = m["prev_visits"] >= 20 and m["lost_share"] >= m["prev_lost_share"] + 3
        if len(past_m) >= 20 and m["lost_share"] >= 10 and (grew or (m["prev_visits"] < 20 and m["lost_share"] >= 15)):
            slots = {}
            for v in past_m:
                if v["kind"] in LOST:
                    h = _hm(v["start"]) or 0
                    k = (_d(v["start"]).weekday(), "утром" if h < 12 * 60 else "днём" if h < 16 * 60 else "вечером")
                    slots[k] = slots.get(k, 0) + 1
            worst = max(slots.items(), key=lambda x: x[1])[0] if slots else None
            when = f" Чаще всего — {('в понедельник', 'во вторник', 'в среду', 'в четверг', 'в пятницу', 'в субботу', 'в воскресенье')[worst[0]]} {worst[1]}." if worst else ""
            out.append({"level": "warn", "go": "visits",
                        "text": (f"Отмены и неявки выросли: {m['lost_share']:g} % записей против {m['prev_lost_share']:g} % в прошлом месяце."
                                 if grew else f"Отмены и неявки — {m['lost_share']:g} % записей.") + when + " Помогут напоминания накануне."})
        if d["plans_open"]["count"]:
            out.append({"level": "info", "go": "conversion",
                        "text": f"Не начаты {d['plans_open']['count']} планов лечения на {rub(d['plans_open']['sum'])}. "
                                "Список для звонков — «CRM» → «Обзвон» → «План не начат»."})
        try:  # CRM tasks nobody did on time
            late = self.db.one("SELECT COUNT(*) AS n FROM crm_tasks WHERE status='open' AND due < ?", (date.today().isoformat(),))["n"]
        except Exception:  # noqa: BLE001 — no CRM tables (tests of the director alone)
            late = 0
        if late:
            out.append({"level": "warn", "go": "crm", "text": f"Просрочено {late} {_plural(late, 'задача', 'задачи', 'задач')} CRM: "
                                                         "звонки и приглашения пациентам. Список — «CRM» → «Задачи» → «Просрочено»."})
        if d["debts"] > 0:
            out.append({"level": "info", "go": "debts", "text": f"Пациенты должны клинике {rub(d['debts'])}."})
        if m["avg_check"] and m["prev_avg_check"] and m["avg_check"] < m["prev_avg_check"] * 0.9:
            out.append({"level": "info", "go": "revenue",
                        "text": f"Средний чек снизился: {rub(m['avg_check'])} против {rub(m['prev_avg_check'])} в прошлом месяце."})
        return out

    # ============================================================ patients --
    def patients(self, date_from=None, date_to=None):
        a, b = _period(date_from, date_to)
        first = self._first_visits()
        vis = [v for v in self._visits(a, b) if v["patient_id"] and v["kind"] not in LOST and v["past"]]
        names = self._doctor_names()
        seen, new, docs = set(), set(), {}
        for v in vis:
            pid = v["patient_id"]
            seen.add(pid)
            is_new = a <= first.get(pid, ("",))[0] < b
            if is_new:
                new.add(pid)
            if v["doctor_id"]:
                x = docs.setdefault(v["doctor_id"], {"doctor_id": v["doctor_id"], "name": names.get(v["doctor_id"]) or "Без врача",
                                                     "new": set(), "repeat": set(), "visits": 0})
                x["visits"] += 1
                (x["new"] if is_new and first[pid][1] == v["doctor_id"] else x["repeat"]).add(pid)
        inv = self.db.q("""SELECT patient_id, total FROM invoices WHERE COALESCE(kind,'invoice')='invoice'
                           AND created_at >= ? AND created_at < ?""", (a, b))
        rev_new = sum(i["total"] or 0 for i in inv if i["patient_id"] in new)
        rev_all = sum(i["total"] or 0 for i in inv)

        # months of the period
        months = {}
        for v in vis:
            months.setdefault(v["start"][:7], {"month": v["start"][:7], "new": set(), "repeat": set()})
        for v in vis:
            pid = v["patient_id"]
            m = months[v["start"][:7]]
            (m["new"] if first.get(pid, ("",))[0][:7] == v["start"][:7] else m["repeat"]).add(pid)

        # retention: cohorts by the month of the first visit, the last 12 months
        t = date.today()
        allv = self.db.q(f"SELECT patient_id, start, status FROM ({HIST}) WHERE patient_id IS NOT NULL AND start < ?", (_now(),))
        days = {}
        for r in allv:
            if status_kind(r["status"]) not in LOST:
                days.setdefault(r["patient_id"], set()).add(r["start"][:10])
        cohorts = {}
        c0 = (t.replace(day=1) - timedelta(days=330)).replace(day=1).isoformat()
        for pid, (f, _doc) in first.items():
            if f < c0:
                continue
            c = cohorts.setdefault(f[:7], {"month": f[:7], "new": 0, **{f"r{n}": 0 for n in RETURN_DAYS}})
            c["new"] += 1
            fd = _d(f)
            later = [_d(x) for x in days.get(pid, ()) if x > f]
            for n in RETURN_DAYS:
                if any((x - fd).days <= n for x in later):
                    c[f"r{n}"] += 1
        coh = []
        for k in sorted(cohorts):
            c = cohorts[k]
            y, mm = int(k[:4]), int(k[5:7])
            end = date(y, mm, calendar.monthrange(y, mm)[1])
            for n in RETURN_DAYS:  # a cohort that has not had the time yet shows «рано»
                c[f"p{n}"] = _pct(c[f"r{n}"], c["new"]) if (t - end).days >= n else None
            coh.append(c)

        # gone: the last visit LOST_FROM–LOST_TO days ago and nothing booked
        future = {r["patient_id"] for r in self.db.q(f"SELECT patient_id, status FROM ({HIST}) WHERE start >= ? AND patient_id IS NOT NULL",
                                                       (_now(),)) if status_kind(r["status"]) not in LOST}
        lo, hi = (t - timedelta(days=LOST_TO)).isoformat(), (t - timedelta(days=LOST_FROM)).isoformat()
        gone = sum(1 for pid, ds in days.items() if pid not in future and lo <= max(ds) <= hi)
        hf = self.history_from()
        return {"from": a, "to": (_d(b) - timedelta(days=1)).isoformat(), "patients": len(seen), "new": len(new),
                "repeat": len(seen - new), "new_share": _pct(len(new), len(seen)) or 0, "visits": len(vis),
                "revenue_new": round(rev_new, 2), "revenue_repeat": round(rev_all - rev_new, 2),
                "by_doctor": sorted(({**x, "new": len(x["new"]), "repeat": len(x["repeat"])} for x in docs.values()),
                                    key=lambda x: -x["visits"]),
                "by_month": [{"month": m["month"], "new": len(m["new"]), "repeat": len(m["repeat"])} for _, m in sorted(months.items())],
                "cohorts": coh, "return_days": list(RETURN_DAYS), "gone": gone, "gone_days": [LOST_FROM, LOST_TO],
                "history_from": hf, "history_short": bool(hf) and (_d(a) - _d(hf)).days < 60}

    # ================================================================ load --
    def load(self, date_from=None, date_to=None):
        a, b = _period(date_from, date_to)
        last = _d(b) - timedelta(days=1)
        week = self._workweek()
        h0, h1 = self._hours()
        chairs = self._chairs()
        wdays = self._workdays(a, last, week)
        day_min = (h1 - h0) * 60
        cap = chairs * day_min * len(wdays)
        vis = self._visits(a, b)
        names = self._doctor_names()
        booked = sum(v["min"] for v in vis if v["kind"] not in LOST)
        lost = sum(v["min"] for v in vis if v["kind"] in LOST and v["past"])

        by_chair = {}
        for v in vis:
            if v["kind"] in LOST:
                continue
            k = v["chair"] or "_"
            x = by_chair.setdefault(k, {"chair": "" if k == "_" else k, "booked": 0, "visits": 0})
            x["booked"] += v["min"]
            x["visits"] += 1
        for x in by_chair.values():
            x["load"] = _pct(x["booked"], day_min * len(wdays)) if x["chair"] else None

        shifts = self._shift_minutes(a, last)
        docs = {}
        for v in vis:
            if not v["doctor_id"]:
                continue
            x = docs.setdefault(v["doctor_id"], {"doctor_id": v["doctor_id"], "name": names.get(v["doctor_id"]) or "Без врача",
                                                 "visits": 0, "booked": 0, "lost": 0, "days": set()})
            if v["kind"] in LOST:
                x["lost"] += v["min"] if v["past"] else 0
            else:
                x["visits"] += 1
                x["booked"] += v["min"]
                x["days"].add(v["start"][:10])
        by_doc = []
        for x in docs.values():
            avail = shifts.get(x["doctor_id"]) or len(x["days"]) * day_min
            by_doc.append({**x, "days": len(x["days"]), "available": avail, "load": _pct(x["booked"], avail),
                           "by_shifts": x["doctor_id"] in shifts})
        by_doc.sort(key=lambda x: -(x["load"] or 0))

        # weekday × hour: how full the chairs are, and where cancellations and no-shows happen
        n_wd = [sum(1 for d in wdays if d.weekday() == i) for i in range(7)]
        grid = [[0] * (h1 - h0) for _ in range(7)]
        tot_wd, lost_wd = [0] * 7, [0] * 7
        for v in vis:
            s, e = _hm(v["start"]), _hm(v["end"])
            if s is None or e is None:
                continue
            wd = _d(v["start"]).weekday()
            if v["past"]:
                tot_wd[wd] += 1
                lost_wd[wd] += v["kind"] in LOST
            if v["kind"] in LOST:
                continue
            for h in range(h0, h1):
                ov = max(0, min(e, (h + 1) * 60) - max(s, h * 60))
                grid[wd][h - h0] += ov
        heat = [{"wd": WD[i], "days": n_wd[i], "cells": [_pct(m, chairs * 60 * n_wd[i]) or 0 for m in grid[i]],
                 "lost_share": _pct(lost_wd[i], tot_wd[i])} for i in range(7) if i in week or n_wd[i] or tot_wd[i]]
        by_day = []
        for d in wdays:
            ds = d.isoformat()
            m = sum(v["min"] for v in vis if v["start"][:10] == ds and v["kind"] not in LOST)
            by_day.append({"day": ds, "booked": m, "load": _pct(m, chairs * day_min) or 0})
        return {"from": a, "to": last.isoformat(), "chairs": chairs, "hours": [h0, h1], "workdays": len(wdays),
                "capacity": cap, "booked": booked, "lost": lost, "load": _pct(booked, cap) or 0,
                "by_chair": sorted(by_chair.values(), key=lambda x: (not x["chair"], x["chair"])),
                "by_doctor": by_doc, "heat": heat, "by_day": by_day}

    # ========================================================== conversion --
    def conversion(self, date_from=None, date_to=None):
        """Consultation → plan → treatment by doctor. A consultation is a patient's first visit that took place."""
        a, b = _period(date_from, date_to)
        names = self._doctor_names()
        first = self._first_visits()
        plans = self.db.q("""SELECT id, patient_id, doctor_id, total, COALESCE(plan_status,'Предварительный') AS st,
                                    substr(created_at,1,10) AS day FROM invoices WHERE kind='plan'""")
        billed = {r["plan_id"]: r["s"] for r in self.db.q("""SELECT plan_id, SUM(total) AS s FROM invoices
                                                              WHERE plan_id IS NOT NULL AND COALESCE(kind,'invoice')='invoice' GROUP BY plan_id""")}
        by_pat = {}
        for p in plans:
            by_pat.setdefault(p["patient_id"], []).append(p)

        def doc(did):
            return rows.setdefault(did or "_", {"doctor_id": did, "name": names.get(did) or "Без врача", "consult": 0,
                                                "with_plan": 0, "started": 0, "plans": 0, "plans_sum": 0.0, "accepted": 0,
                                                "plans_started": 0, "done": 0, "refused": 0, "sum_started": 0.0, "billed": 0.0})
        rows = {}
        for pid, (f, did) in first.items():
            if not a <= f < b:
                continue
            x = doc(did)
            x["consult"] += 1
            mine = [p for p in by_pat.get(pid, []) if p["day"] >= f]
            if mine:
                x["with_plan"] += 1
                if any(p["st"] in PLAN_STARTED or billed.get(p["id"]) for p in mine):
                    x["started"] += 1
        for p in plans:
            if not a <= p["day"] < b:
                continue
            x = doc(p["doctor_id"])
            started = p["st"] in PLAN_STARTED or bool(billed.get(p["id"]))
            x["plans"] += 1
            x["plans_sum"] += p["total"] or 0
            x["accepted"] += p["st"] in PLAN_ACCEPTED or started
            x["plans_started"] += started
            x["done"] += p["st"] == "Лечение завершено"
            x["refused"] += p["st"] == "Отказ"
            x["sum_started"] += (p["total"] or 0) if started else 0
            x["billed"] += billed.get(p["id"]) or 0
        out = []
        for x in rows.values():
            out.append({**x, "plans_sum": round(x["plans_sum"], 2), "sum_started": round(x["sum_started"], 2),
                        "billed": round(x["billed"], 2), "plan_rate": _pct(x["with_plan"], x["consult"]),
                        "start_rate": _pct(x["started"], x["consult"]), "plans_rate": _pct(x["plans_started"], x["plans"]),
                        "sum_rate": _pct(x["sum_started"], x["plans_sum"])})
        out.sort(key=lambda x: -(x["consult"] + x["plans"]))
        tot = {k: sum(x[k] for x in out) for k in ("consult", "with_plan", "started", "plans", "plans_sum", "accepted",
                                                   "plans_started", "done", "refused", "sum_started", "billed")}
        tot.update(plan_rate=_pct(tot["with_plan"], tot["consult"]), start_rate=_pct(tot["started"], tot["consult"]),
                   plans_rate=_pct(tot["plans_started"], tot["plans"]), sum_rate=_pct(tot["sum_started"], tot["plans_sum"]))
        return {"from": a, "to": (_d(b) - timedelta(days=1)).isoformat(), "by_doctor": out, "total": tot}

    # =========================================================== materials --
    def materials(self, date_from=None, date_to=None):
        """Cost of materials written off by services, spread over the lines of each invoice by the norms."""
        import json
        a, b = _period(date_from, date_to)
        inv = self.db.q("""SELECT id, items, total FROM invoices WHERE COALESCE(kind,'invoice')='invoice'
                           AND created_at >= ? AND created_at < ?""", (a, b))
        moves = {}
        for r in self.db.q("""SELECT invoice_id, SUM(-qty * price) AS s FROM stock_moves WHERE kind='service'
                              AND invoice_id IN (SELECT id FROM invoices WHERE created_at >= ? AND created_at < ?)
                              GROUP BY invoice_id""", (a, b)):
            moves[r["invoice_id"]] = r["s"] or 0
        norm = {}
        for r in self.db.q("""SELECT sm.service_id, SUM(sm.qty * COALESCE(m.price,0)) AS c FROM service_materials sm
                              LEFT JOIN materials m ON m.id=sm.material_id GROUP BY sm.service_id"""):
            norm[r["service_id"]] = r["c"] or 0
        by, cost, estimated = {}, 0.0, 0
        for i in inv:
            items = json.loads(i["items"] or "[]")
            weights = [norm.get(it.get("service_id"), 0) * float(it.get("qty") or 1) for it in items]
            wsum = sum(weights)
            # an invoice made before the norms were set has no write-off: its cost is estimated by the norms
            spent = moves[i["id"]] if i["id"] in moves else wsum
            if i["id"] not in moves and wsum:
                estimated += 1
            cost += spent
            for it, w in zip(items, weights):
                title = str(it.get("title") or "Без названия").strip()
                by[title] = by.get(title, 0.0) + (spent * w / wsum if wsum else 0)
        cost = round(cost, 2)
        manual = self.db.one("""SELECT COALESCE(SUM(-qty * price),0) AS s FROM stock_moves WHERE kind='writeoff'
                                AND at >= ? AND at < ?""", (a, b))["s"]
        billed = round(sum(i["total"] or 0 for i in inv), 2)
        return {"from": a, "to": (_d(b) - timedelta(days=1)).isoformat(),
                "by_service": {k: round(v, 2) for k, v in by.items() if v}, "cost": cost, "billed": billed,
                "share": _pct(cost, billed) or 0, "manual_writeoff": round(manual or 0, 2),
                "has_norms": bool(norm), "estimated": estimated}

    # ======================================================== plan vs fact --
    def kpi(self, month=None):
        month = month or date.today().strftime("%Y-%m")
        m0, m1 = _month(month)
        t = date.today()
        names = self._doctor_names()
        targets = {}
        for r in self.db.q("SELECT scope, metric, value FROM kpi_targets WHERE month=?", (month,)):
            targets[(r["scope"], r["metric"])] = r["value"]
        prev_month = (m0 - timedelta(days=1)).strftime("%Y-%m")
        has_prev = bool(self.db.one("SELECT 1 AS x FROM kpi_targets WHERE month=? LIMIT 1", (prev_month,)))
        rev = self.rep.revenue(m0, min(m1, t)) if m0 <= t else {"paid": 0, "by_doctor": []}
        vis = self._visits(m0, m1 + timedelta(days=1))
        first = self._first_visits()
        week = self._workweek()
        wd_all = self._workdays(m0, m1, week)
        wd_done = [d for d in wd_all if d <= t]
        current = m0 <= t <= m1
        pace = len(wd_done) / len(wd_all) if wd_all else 1

        def facts(did=None):
            mine = [v for v in vis if did is None or v["doctor_id"] == did]
            done = sum(1 for v in mine if v["past"] and v["kind"] not in LOST)
            ahead = sum(1 for v in mine if not v["past"] and v["kind"] not in LOST)
            new = sum(1 for f in first.values() if m0.isoformat() <= f[0] <= m1.isoformat() and (did is None or f[1] == did))
            paid = rev["paid"] if did is None else next((d["paid"] for d in rev["by_doctor"] if d["doctor_id"] == did), 0)
            return {"revenue": (paid, round(paid / pace, 2) if current and wd_done else paid),
                    "visits": (done, done + ahead if current else done),
                    "new_patients": (new, round(new / pace) if current and wd_done else new)}

        def row(scope, name, did=None):
            f = facts(did)
            ms = {}
            for k in METRICS:
                plan = targets.get((scope, k))
                fact, fc = f[k]
                ms[k] = {"plan": plan, "fact": fact, "forecast": fc, "pct": _pct(fact, plan), "forecast_pct": _pct(fc, plan)}
            return {"scope": scope, "name": name, "metrics": ms}
        docs_seen = {v["doctor_id"] for v in vis if v["doctor_id"]} | {k[0][2:] for k in targets if k[0].startswith("d:")}
        return {"month": month, "from": m0.isoformat(), "to": m1.isoformat(), "current": current,
                "workdays": len(wd_all), "workdays_done": len(wd_done), "metrics": METRICS, "prev_has_plan": has_prev,
                "clinic": row("clinic", "Вся клиника"),
                "doctors": [row("d:" + did, names[did], did) for did in sorted(docs_seen, key=lambda k: names.get(k, "")) if did in names]}

    def kpi_save(self, month, items, user="", copy_prev=False):
        _month(month)
        names = self._doctor_names()
        if copy_prev:
            prev = (_month(month)[0] - timedelta(days=1)).strftime("%Y-%m")
            items = [{"scope": r["scope"], "metric": r["metric"], "value": r["value"]}
                     for r in self.db.q("SELECT scope, metric, value FROM kpi_targets WHERE month=?", (prev,))]
            if not items:
                raise ValueError("В прошлом месяце план не задан")
        clean = []
        for it in items or []:
            scope, metric = str(it.get("scope") or ""), str(it.get("metric") or "")
            if metric not in METRICS:
                raise ValueError("Неизвестный показатель плана")
            if scope != "clinic" and not (scope.startswith("d:") and scope[2:] in names):
                raise ValueError("План можно задать клинике или врачу")
            raw = str(it.get("value") if it.get("value") is not None else "").replace(" ", "").replace(",", ".")
            if raw == "":
                clean.append((scope, metric, None))
                continue
            try:
                v = float(raw)
            except ValueError:
                raise ValueError(f"{METRICS[metric]}: нужно число") from None
            if v < 0 or v > 1e10:
                raise ValueError(f"{METRICS[metric]}: число от 0")
            clean.append((scope, metric, round(v, 2)))
        with self.db.tx() as c:
            for scope, metric, v in clean:
                key = f"{month}:{scope}:{metric}"
                if v is None:
                    c.execute("DELETE FROM kpi_targets WHERE id=?", (key,))
                else:
                    c.execute("""INSERT INTO kpi_targets(id, month, scope, metric, value, user_name, updated_at) VALUES(?,?,?,?,?,?,?)
                                 ON CONFLICT(id) DO UPDATE SET value=excluded.value, user_name=excluded.user_name,
                                 updated_at=excluded.updated_at""", (key, month, scope, metric, v, user, _now()))
        return len(clean)
