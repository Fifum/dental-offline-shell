"""Marketing: where patients come from, birthdays and call lists (visit reminders, lapsed patients,
treatment plans that were never started), with a log of every call so two administrators do not
ring the same person twice.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from db import DB
from reports import _period, status_kind

SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_marketing(
    patient_id TEXT PRIMARY KEY, source TEXT, no_calls INTEGER DEFAULT 0, updated_at TEXT);
CREATE TABLE IF NOT EXISTS marketing_calls(
    id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT, list TEXT, result TEXT, comment TEXT, at TEXT, user_name TEXT);
CREATE INDEX IF NOT EXISTS ix_calls_patient ON marketing_calls(patient_id);
"""
DEFAULT_SOURCES = ["Рекомендация знакомых", "Яндекс Карты", "2ГИС", "Сайт клиники", "Поиск в интернете", "Соцсети",
                   "Наружная реклама", "Проходили мимо", "Направил врач", "Другое"]
RESULTS = ["Дозвонились", "Записался", "Перезвонить", "Не дозвонились", "Отказ", "Написали"]
LISTS = {"remind": "Напомнить о визите", "lost": "Давно не были", "plans": "План лечения не начат",
         "unfinished": "План лечения не завершён", "birthdays": "Дни рождения", "debts": "Долги",
         "tasks": "Задача", "segment": "Рассылка", "reviews": "Оценка визита",  # these three: only marks in the call log
         "abandoned": "Брошенный план лечения"}  # 3.6: the call list of plan_status.py (calls with plan_id)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Marketing:
    def __init__(self, db):
        self.db = db
        db.script(SCHEMA)

    # ------------------------------------------------------------- sources --
    def sources(self):
        try:
            got = json.loads(self.db.meta_get("mk_sources") or "null")
        except ValueError:
            got = None
        return got if isinstance(got, list) and got else list(DEFAULT_SOURCES)

    def save_sources(self, items):
        clean = []
        for s in items or []:
            s = str(s or "").strip()[:60]
            if s and s not in clean:
                clean.append(s)
        if not clean:
            raise ValueError("Нужен хотя бы один источник")
        self.db.meta_set("mk_sources", json.dumps(clean, ensure_ascii=False))
        return clean

    def patient_info(self, pid):
        r = self.db.one("SELECT source, no_calls FROM patient_marketing WHERE patient_id=?", (str(pid),)) or {}
        calls = self.db.q("SELECT * FROM marketing_calls WHERE patient_id=? ORDER BY id DESC LIMIT 10", (str(pid),))
        return {"source": r.get("source") or "", "no_calls": bool(r.get("no_calls")), "calls": calls}

    def set_patient(self, pid, f):
        if not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (str(pid),)):
            raise ValueError("Пациент не найден")
        cur = self.patient_info(pid)
        source = str(f.get("source", cur["source"]) or "").strip()[:60]
        no_calls = bool(f.get("no_calls", cur["no_calls"]))
        with self.db.tx() as c:
            c.execute("""INSERT INTO patient_marketing(patient_id, source, no_calls, updated_at) VALUES(?,?,?,?)
                         ON CONFLICT(patient_id) DO UPDATE SET source=excluded.source, no_calls=excluded.no_calls,
                         updated_at=excluded.updated_at""", (str(pid), source, 1 if no_calls else 0, _now()))
        return True

    def sources_report(self, date_from=None, date_to=None):
        """Per source: all patients, new patients (first visit in the period) and what they paid in the period."""
        a, b = _period(date_from, date_to)
        first = {r["patient_id"]: r["f"] for r in self.db.q(
            f"SELECT patient_id, MIN(start) AS f FROM ({DB.ALL_VISITS}) WHERE patient_id IS NOT NULL GROUP BY patient_id")}
        src = {}  # the source Dentist Plus knows, overridden by the one chosen here
        for r in self.db.q("""SELECT id, json_extract(COALESCE(detail,data),'$.source') AS s FROM patients
                              WHERE json_type(COALESCE(detail,data),'$.source')='text'"""):
            if str(r["s"]).strip():
                src[r["id"]] = str(r["s"]).strip()[:60]
        src.update({r["patient_id"]: r["source"] for r in self.db.q("SELECT patient_id, source FROM patient_marketing WHERE source<>''")})
        paid = {r["patient_id"]: r["s"] for r in self.db.q(
            "SELECT patient_id, SUM(amount) AS s FROM payments WHERE created_at >= ? AND created_at < ? GROUP BY patient_id", (a, b))}
        local_new = {r["id"] for r in self.db.q("SELECT id FROM patients WHERE local=1 AND json_extract(detail,'$.created_offline') >= ? "
                                                "AND json_extract(detail,'$.created_offline') < ?", (a, b))}
        rows = {}
        for pid in {*src, *paid, *[p for p, f in first.items() if a <= f < b], *local_new}:
            k = src.get(pid) or ""
            r = rows.setdefault(k, {"source": k, "patients": 0, "new": 0, "paid": 0.0})
            r["new"] += 1 if (a <= (first.get(pid) or "") < b or pid in local_new) else 0
            r["paid"] += paid.get(pid) or 0
        for pid, k in src.items():
            rows[k]["patients"] += 1
        # payback of advertising: «Реклама» expenses with the source chosen, and requests from the CRM
        from crm import CRM
        crm = CRM(self.db)
        spent, leads = crm.ad_spend(a, b), crm.leads_by_source(a, b)
        for k in {*spent, *leads}:
            rows.setdefault(k, {"source": k, "patients": 0, "new": 0, "paid": 0.0})
        for k, r in rows.items():
            r["spent"] = spent.get(k, 0.0)
            r["leads"] = (leads.get(k) or {}).get("leads", 0)
            r["leads_came"] = (leads.get(k) or {}).get("came", 0)
            r["cost_new"] = round(r["spent"] / r["new"]) if r["spent"] and r["new"] else None
            r["roi"] = round(r["paid"] * 100 / r["spent"]) if r["spent"] else None
        out = sorted(({**r, "paid": round(r["paid"], 2)} for r in rows.values()), key=lambda x: (x["source"] == "", -x["new"], -x["paid"]))
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(), "rows": out,
                "with_source": len(src), "patients": self.db.one("SELECT COUNT(*) AS n FROM patients")["n"],
                "spent": round(sum(spent.values()), 2), "spent_no_source": spent.get("", 0.0)}

    # ---------------------------------------------------------- call lists --
    def _last_calls(self, pids, since):
        if not pids:
            return {}
        out = {}
        for r in self.db.q("SELECT * FROM marketing_calls WHERE at >= ? ORDER BY id", (since,)):
            if r["patient_id"] in pids:
                out[r["patient_id"]] = r
        return out

    def _no_calls(self):
        return {r["patient_id"] for r in self.db.q("SELECT patient_id FROM patient_marketing WHERE no_calls=1")}

    def call_list(self, kind, f=None):
        f = f or {}
        today = date.today()
        if kind == "remind":
            day = str(f.get("day") or "")[:10]
            if not day:  # the next day with bookings (tomorrow may be a Sunday)
                day = (today + timedelta(days=1)).isoformat()
                for n in range(1, 8):
                    d = (today + timedelta(days=n)).isoformat()
                    if self.db.one(f"SELECT 1 AS x FROM ({DB.ALL_VISITS}) WHERE start >= ? AND start < ? LIMIT 1",
                                   (d, (today + timedelta(days=n + 1)).isoformat())):
                        day = d
                        break
            try:
                date.fromisoformat(day)
            except ValueError:
                raise ValueError("Неверная дата") from None
            f = {**f, "day": day}
            nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
            rows = self.db.q(f"""SELECT a.id AS visit_id, a.patient_id, a.start, a.status, a.title, p.name, p.phone, d.name AS doctor_name
                                 FROM ({DB.ALL_VISITS}) a LEFT JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors d ON d.id=a.doctor_id
                                 WHERE a.start >= ? AND a.start < ? AND a.patient_id IS NOT NULL ORDER BY a.start""", (day, nxt))
            rows = [r for r in rows if status_kind(r["status"]) not in ("cancel", "noshow")]
            for r in rows:
                r["info"] = f"{r['start'][11:16]} · {r['doctor_name'] or 'врач не указан'}" + (f" · {r['title']}" if r["title"] else "")
            since = (today - timedelta(days=3)).isoformat()
        elif kind == "lost":
            months = min(36, max(1, int(f.get("months") or 6)))
            border = (today - timedelta(days=int(months * 30.4))).isoformat()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = self.db.q(f"""SELECT p.id AS patient_id, p.name, p.phone, v.last AS start
                FROM patients p JOIN (SELECT patient_id, MAX(start) AS last, SUM(CASE WHEN start >= ? THEN 1 ELSE 0 END) AS fut
                                      FROM ({DB.ALL_VISITS}) GROUP BY patient_id) v ON v.patient_id=p.id
                WHERE v.fut=0 AND v.last < ? ORDER BY v.last DESC LIMIT 500""", (now, border))
            for r in rows:
                r["info"] = f"последний визит {r['start'][8:10]}.{r['start'][5:7]}.{r['start'][:4]}"
            since = (today - timedelta(days=30)).isoformat()
        elif kind == "plans":
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = self.db.q(f"""SELECT i.id AS plan_id, i.patient_id, i.title, i.total, i.created_at AS start, i.plan_status,
                                        p.name, p.phone, d.name AS doctor_name
                FROM invoices i JOIN patients p ON p.id=i.patient_id LEFT JOIN doctors d ON d.id=i.doctor_id
                WHERE i.kind='plan' AND COALESCE(i.plan_status,'Предварительный') IN ('Предварительный','Активен')
                  AND i.created_at < ?
                  AND NOT EXISTS (SELECT 1 FROM ({DB.ALL_VISITS}) v WHERE v.patient_id=i.patient_id AND v.start >= ?)
                  AND NOT EXISTS (SELECT 1 FROM invoices j WHERE j.patient_id=i.patient_id AND COALESCE(j.kind,'invoice')='invoice'
                                  AND j.created_at > i.created_at)
                ORDER BY i.created_at DESC""", ((today - timedelta(days=int(f.get("days") or 7))).isoformat(), now))
            for r in rows:
                r["info"] = f"{r['title'] or 'План лечения'} на {r['total']:,.0f} ₽".replace(",", " ") + \
                            (f" · {r['doctor_name']}" if r["doctor_name"] else "")
            since = (today - timedelta(days=30)).isoformat()
        elif kind == "debts":
            from reports import Reports
            rows = [{"patient_id": x["patient_id"], "name": x["name"], "phone": x["phone"], "start": x["last"],
                     "info": f"долг {x['total']:,.0f} ₽".replace(",", " ")} for x in Reports(self.db).debts()["debts"]]
            since = (today - timedelta(days=14)).isoformat()
        elif kind == "birthdays":
            rows = self.birthdays(int(f.get("days") or 14))
            since = date(today.year, 1, 1).isoformat()
        elif kind == "unfinished":  # 6.5: the plan was started (billed or «Активен») but is not finished, nothing is booked
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = self.db.q(f"""SELECT i.id AS plan_id, i.patient_id, i.title, i.total, i.created_at, p.name, p.phone, d.name AS doctor_name,
                                        (SELECT COALESCE(SUM(j.total),0) FROM invoices j WHERE j.plan_id=i.id) AS billed,
                                        (SELECT MAX(v.start) FROM ({DB.ALL_VISITS}) v WHERE v.patient_id=i.patient_id AND v.start < ?) AS start
                FROM invoices i JOIN patients p ON p.id=i.patient_id LEFT JOIN doctors d ON d.id=i.doctor_id
                WHERE i.kind='plan' AND (COALESCE(i.plan_status,'')='Активен'
                       OR (COALESCE(i.plan_status,'') IN ('Предварительный','Подтверждён') AND EXISTS (SELECT 1 FROM invoices j WHERE j.plan_id=i.id)))
                  AND NOT EXISTS (SELECT 1 FROM ({DB.ALL_VISITS}) v WHERE v.patient_id=i.patient_id AND v.start >= ?)
                ORDER BY start""", (now, now))
            for r in rows:
                left = max(0.0, (r["total"] or 0) - (r["billed"] or 0))
                r["start"] = r["start"] or r["created_at"]
                r["info"] = f"{r['title'] or 'План лечения'}: осталось на {left:,.0f} ₽".replace(",", " ") + \
                            (f" · {r['doctor_name']}" if r["doctor_name"] else "") + \
                            (f" · последний визит {r['start'][8:10]}.{r['start'][5:7]}.{r['start'][:4]}" if r["start"] else "")
            since = (today - timedelta(days=30)).isoformat()
        else:
            raise ValueError("Неизвестный список")
        skip = self._no_calls()
        rows = [r for r in rows if r["patient_id"] not in skip]
        last = self._last_calls({r["patient_id"] for r in rows}, since)
        for r in rows:
            c = last.get(r["patient_id"])
            r["last_call"] = {"result": c["result"], "at": c["at"], "user_name": c["user_name"], "comment": c["comment"]} if c else None
        return {"kind": kind, "title": LISTS[kind], "rows": rows, "results": RESULTS, "day": f.get("day"),
                "done": sum(1 for r in rows if r["last_call"])}

    def birthdays(self, days=14):
        days = min(366, max(1, int(days)))
        today = date.today()
        out = []
        for p in self.db.q("SELECT id, name, phone, birth FROM patients WHERE birth LIKE '____-__-__%'"):
            try:
                bd = date.fromisoformat(p["birth"][:10])
            except ValueError:
                continue
            for y in (today.year, today.year + 1):
                try:
                    nxt = bd.replace(year=y)
                except ValueError:  # 29 February
                    nxt = date(y, 3, 1)
                if nxt >= today:
                    break
            delta = (nxt - today).days
            if delta < days:
                out.append({"patient_id": p["id"], "name": p["name"], "phone": p["phone"], "start": nxt.isoformat(),
                            "in_days": delta, "age": nxt.year - bd.year,
                            "info": ("сегодня" if delta == 0 else "завтра" if delta == 1 else f"через {delta} дн.") +
                                    f" · исполнится {nxt.year - bd.year}"})
        return sorted(out, key=lambda x: (x["in_days"], x["name"] or ""))

    def log_call(self, f, who="", login=""):
        """A call (or a message). 3.6: `plan_id` — a call about that treatment plan, `call_on` — when to call back,
        the caller's login is kept as well (staff are known by login on every computer of the clinic)."""
        pid = str(f.get("patient_id") or "")
        if not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Пациент не найден")
        result = str(f.get("result") or "")
        if result not in RESULTS:
            raise ValueError("Выберите результат звонка")
        lst = f.get("list") if f.get("list") in LISTS else ""
        cols = {r[1] for r in self.db.conn.execute("PRAGMA table_info(marketing_calls)")}
        with self.db.tx() as c:
            if "plan_id" in cols:
                c.execute("""INSERT INTO marketing_calls(patient_id, list, result, comment, at, user_name, plan_id, call_on, login)
                             VALUES(?,?,?,?,?,?,?,?,?)""",
                          (pid, lst, result, str(f.get("comment") or "").strip()[:300], _now(), who,
                           str(f.get("plan_id") or "") or None, str(f.get("call_on") or "")[:10] or None, str(login or "").lower() or None))
            else:
                c.execute("INSERT INTO marketing_calls(patient_id, list, result, comment, at, user_name) VALUES(?,?,?,?,?,?)",
                          (pid, lst, result, str(f.get("comment") or "").strip()[:300], _now(), who))
        if f.get("no_calls"):
            self.set_patient(pid, {"no_calls": True})
        return True

    def summary(self):
        today = date.today()
        lists = {k: len(self.call_list(k)["rows"]) for k in ("remind", "lost", "plans")}
        return {**lists, "birthdays_week": len(self.birthdays(7)), "birthdays_today": len([b for b in self.birthdays(1)]),
                "calls_today": self.db.one("SELECT COUNT(*) AS n FROM marketing_calls WHERE at >= ?", (today.isoformat(),))["n"]}
