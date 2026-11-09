"""CRM: requests (leads) and their funnel, tasks for the front desk (made by hand or by rules after a service,
an unfinished treatment plan or a bad review), patient segments for a WhatsApp mailing, the after-visit
survey (NPS, 0–10) with links to leave a review on the maps, and the payback of advertising.

Everything lives in the clinic base and is synced between laptops (replica.TABLES). A task made by a rule
gets an id built from the rule, the patient and the date, so two laptops that make it on their own make the
same row, and after a sync there is still one task.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta

from db import DB
from reports import _period, status_kind

SCHEMA = """
CREATE TABLE IF NOT EXISTS crm_leads(
    id TEXT PRIMARY KEY, name TEXT, phone TEXT, source TEXT, channel TEXT, interest TEXT, stage TEXT,
    lost_reason TEXT, comment TEXT, patient_id TEXT, assignee TEXT, next_at TEXT,
    created_at TEXT, created_by TEXT, updated_at TEXT, closed_at TEXT);
CREATE INDEX IF NOT EXISTS ix_leads_created ON crm_leads(created_at);
CREATE TABLE IF NOT EXISTS crm_tasks(
    id TEXT PRIMARY KEY, title TEXT, kind TEXT, rule TEXT, patient_id TEXT, lead_id TEXT, plan_id TEXT,
    assignee TEXT, due TEXT, status TEXT, result TEXT, comment TEXT,
    created_at TEXT, created_by TEXT, done_at TEXT, done_by TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_tasks_due ON crm_tasks(status, due);
CREATE INDEX IF NOT EXISTS ix_tasks_patient ON crm_tasks(patient_id);
CREATE TABLE IF NOT EXISTS crm_reviews(
    id TEXT PRIMARY KEY, patient_id TEXT, visit_id TEXT, doctor_id TEXT, score INTEGER, comment TEXT,
    channel TEXT, created_at TEXT, user_name TEXT);
CREATE INDEX IF NOT EXISTS ix_reviews_at ON crm_reviews(created_at);
CREATE TABLE IF NOT EXISTS crm_segments(
    id TEXT PRIMARY KEY, title TEXT, filters TEXT, created_by TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS crm_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT);
"""

STAGES = [("new", "Новая"), ("contact", "Связались"), ("booked", "Записан"), ("came", "Пришёл"), ("lost", "Отказ")]
STAGE_KEYS = [k for k, _ in STAGES]
STAGE_ORDER = {k: i for i, k in enumerate(STAGE_KEYS)}
CHANNELS = ["Звонок", "WhatsApp", "Telegram", "Сайт", "Соцсети", "Пришёл в клинику", "Другое"]
LOST_REASONS = ["Дорого", "Выбрал другую клинику", "Не дозвонились", "Передумал", "Неудобное время", "Другое"]
TASK_RESULTS = ["Сделано", "Записался", "Дозвонились", "Не дозвонились", "Перезвонить позже", "Отказ"]
AD_CATEGORY = "Реклама"

# Rules «after a service — a task in N days». match: words of the service name (any of them, case-insensitive).
# skip_booked: no task (and an open one is closed) when the patient already has a future visit.
DEFAULT_RULES = [
    {"id": "r_extract", "on": True, "match": "удален, экстракц", "days": 1, "skip_booked": False,
     "title": "Узнать самочувствие после удаления зуба"},
    {"id": "r_implant", "on": True, "match": "имплант", "days": 7, "skip_booked": True,
     "title": "Контроль после имплантации: пригласить на осмотр"},
    {"id": "r_hygiene", "on": True, "match": "гигиен, чистк", "days": 180, "skip_booked": True,
     "title": "Пора на профгигиену — пригласить"},
    {"id": "r_canal", "on": False, "match": "канал", "days": 14, "skip_booked": True,
     "title": "После лечения каналов: пригласить на постоянную пломбу"},
]
DEFAULT_SETTINGS = {
    "rules": DEFAULT_RULES,
    "plan_days": 30,            # an agreed or started plan with no visits for this long → «пригласить продолжить»
    "plan_on": True,
    "bad_score": 6,             # this score or lower → a task for the director
    "good_score": 9,            # this score or higher → offer the review links
    "links": {"yandex": "", "gis": "", "other": ""},
    "nps_question": "Насколько вероятно, что вы порекомендуете нашу клинику друзьям и знакомым?",
    "nps_text": "Здравствуйте, {имя}! Спасибо, что выбрали клинику {клиника}. Оцените, пожалуйста, визит "
                "от 0 до 10 — насколько вероятно, что вы порекомендуете нас знакомым? Просто ответьте цифрой.",
    "review_text": "{имя}, спасибо за высокую оценку! Нам очень поможет ваш отзыв: {ссылка}",
    "mail_text": "Здравствуйте, {имя}! Клиника {клиника} приглашает вас на профилактический осмотр — "
                 "запишитесь в удобное время{телефон клиники}.",
    # 2.12: reminders about money
    "debt_on": True,            # the patient owes for this many days → «напомнить о долге»
    "debt_days": 7,
    "pay_on": True,             # an installment date has passed → «напомнить о платеже по рассрочке»
    "debt_text": "Здравствуйте, {имя}! Напоминаем, что в клинике {клиника} за лечение осталось оплатить {сумма}. "
                 "Оплатить можно в клинике, картой или по СБП. Если уже оплатили — просто не обращайте внимания на это сообщение.",
    "pay_text": "Здравствуйте, {имя}! Напоминаем о платеже по графику: {сумма} (срок — {срок}). "
                "Клиника {клиника}. Если уже оплатили — спасибо!",
}
LINK_TITLES = {"yandex": "Яндекс Карты", "gis": "2ГИС", "other": "Другая площадка"}
LOOKBACK = 30          # a rule makes tasks only for the last 30 days (2 for rules under a month: a call after an
                       # extraction is no use three weeks later), so the first start does not flood the list;
                       # a task made today is due today at the earliest — «overdue» means nobody did it in time
GEN_EVERY = 600        # seconds between automatic passes


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _auto_id(*parts):
    return "A-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:14]


def digits(phone):
    d = re.sub(r"\D", "", str(phone or ""))
    if len(d) == 11 and d[0] in "78":
        d = d[1:]
    return d[-10:] if len(d) >= 10 else d


def _words(match):
    return [w.strip().lower().replace("ё", "е") for w in re.split(r"[,;\n]", str(match or "")) if w.strip()]


def _low(s):
    return str(s or "").lower().replace("ё", "е")


def _day(v):
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _clean_day(v, what="Дата"):
    if not v:
        return None
    d = _day(v)
    if not d:
        raise ValueError(f"{what}: неверная дата")
    return d.isoformat()


# visits with their titles: the schedule (Dentist Plus + changes made here) plus the history that is never purged
HIST = f"""SELECT a.id, a.patient_id, a.doctor_id, a.start, a.status, a.title FROM ({DB.ALL_VISITS}) a
    UNION ALL
    SELECT h.id, h.patient_id, h.doctor_id, h.start, h.status, h.title FROM visits_archive h
    WHERE h.id NOT IN (SELECT id FROM visits)
      AND h.id NOT IN (SELECT origin_id FROM local_visits WHERE origin_id IS NOT NULL)
      AND h.id NOT IN (SELECT remote_id FROM local_visits WHERE remote_id IS NOT NULL)"""


class CRM:
    def __init__(self, db, local=None, marketing=None):
        self.db = db
        self.local = local
        self.mk = marketing
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()
        self._gen_at = 0.0

    # ============================================================ settings --
    def settings(self):
        out = json.loads(json.dumps(DEFAULT_SETTINGS))
        for r in self.db.q("SELECT k, v FROM crm_settings"):
            try:
                out[r["k"]] = json.loads(r["v"])
            except ValueError:
                pass
        links = {**DEFAULT_SETTINGS["links"], **(out.get("links") if isinstance(out.get("links"), dict) else {})}
        out["links"] = {k: str(links.get(k) or "") for k in LINK_TITLES}
        if not isinstance(out.get("rules"), list):
            out["rules"] = DEFAULT_RULES
        return out

    def settings_save(self, f):
        f = f or {}
        cur = self.settings()
        put = {}
        if "rules" in f:
            rules, seen = [], set()
            for r in f.get("rules") or []:
                title = str(r.get("title") or "").strip()[:150]
                words = _words(r.get("match"))
                if not title and not words:
                    continue
                if not title or not words:
                    raise ValueError("В правиле нужны и услуга, и текст задачи")
                try:
                    days = int(r.get("days"))
                except (TypeError, ValueError):
                    raise ValueError("Через сколько дней: введите число") from None
                if not 0 <= days <= 1100:
                    raise ValueError("Через сколько дней: от 0 до 1100")
                rid = str(r.get("id") or "") or _id("r")
                if rid in seen:
                    rid = _id("r")
                seen.add(rid)
                rules.append({"id": rid, "on": bool(r.get("on", True)), "match": ", ".join(words), "days": days,
                              "skip_booked": bool(r.get("skip_booked")), "title": title})
            put["rules"] = rules
        for k, lo, hi in (("plan_days", 7, 365), ("bad_score", 0, 9), ("good_score", 1, 10)):
            if k in f:
                try:
                    v = int(f[k])
                except (TypeError, ValueError):
                    raise ValueError("Введите число") from None
                put[k] = min(hi, max(lo, v))
        if put.get("bad_score", cur["bad_score"]) >= put.get("good_score", cur["good_score"]):
            raise ValueError("Плохая оценка должна быть ниже хорошей")
        if "plan_on" in f:
            put["plan_on"] = bool(f["plan_on"])
        for k in ("debt_on", "pay_on"):
            if k in f:
                put[k] = bool(f[k])
        if "debt_days" in f:
            try:
                put["debt_days"] = min(180, max(1, int(f["debt_days"])))
            except (TypeError, ValueError):
                raise ValueError("Через сколько дней напомнить о долге: введите число") from None
        if "links" in f:
            links = {}
            for k in LINK_TITLES:
                v = str((f.get("links") or {}).get(k) or "").strip()[:500]
                if v and not re.match(r"^https?://\S+$", v):
                    raise ValueError(f"{LINK_TITLES[k]}: ссылка должна начинаться с https://")
                links[k] = v
            put["links"] = links
        for k in ("nps_question", "nps_text", "review_text", "mail_text", "debt_text", "pay_text"):
            if k in f:
                v = str(f[k] or "").strip()
                if len(v) > 1000:
                    raise ValueError("Текст слишком длинный (до 1000 знаков)")
                put[k] = v or DEFAULT_SETTINGS[k]
        with self.db.tx() as c:
            for k, v in put.items():
                c.execute("""INSERT INTO crm_settings(k, v, updated_at) VALUES(?,?,?)
                             ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at""",
                          (k, json.dumps(v, ensure_ascii=False), _now()))
        self._gen_at = 0.0
        return self.settings()

    def review_links(self):
        """Configured review links with a QR code for each (shown on the tablet after a good score)."""
        out = []
        for k, title in LINK_TITLES.items():
            url = self.settings()["links"].get(k)
            if url:
                out.append({"key": k, "title": title, "url": url, "qr": qr_data_uri(url)})
        return out

    # ============================================================== people --
    def staff(self):
        """Employees who can be given a task: active accounts with CRM rights."""
        try:
            from auth import Auth
            rows = self.db.q("SELECT login, name, role, perms, status FROM users WHERE status='active' ORDER BY name")
            return [{"login": r["login"], "name": r["name"]} for r in rows if "marketing" in Auth.effective_perms(r)]
        except Exception:  # noqa: BLE001 — no accounts table (tests without the server)
            return []

    def _names(self):
        try:
            return {r["login"].lower(): r["name"] for r in self.db.q("SELECT login, name FROM users")}
        except Exception:  # noqa: BLE001
            return {}

    def _director_login(self):
        try:
            r = self.db.one("SELECT login FROM users WHERE status='active' AND role='director' ORDER BY id LIMIT 1")
            return r["login"] if r else ""
        except Exception:  # noqa: BLE001
            return ""

    def _check_login(self, login):
        login = str(login or "").strip()
        if not login:
            return ""
        try:
            found = self.db.one("SELECT login FROM users WHERE login=? AND status='active'", (login,))
        except sqlite3.OperationalError:  # no accounts yet
            found = None
        if not found:
            raise ValueError("Сотрудник не найден")
        return found["login"]

    def _no_calls(self):
        return {r["patient_id"] for r in self.db.q("SELECT patient_id FROM patient_marketing WHERE no_calls=1")}

    def _future(self):
        now = _now()
        return {r["patient_id"] for r in self.db.q(f"SELECT DISTINCT patient_id, status FROM ({DB.ALL_VISITS}) WHERE start >= ?", (now,))
                if r["patient_id"] and status_kind(r["status"]) not in ("cancel", "noshow")}

    # ============================================================== tasks --
    def tasks(self, f=None, login=""):
        """scope: my (mine and shared, open), all (open), overdue, done (last 30 days)."""
        f = f or {}
        self.auto(force=bool(f.get("refresh")))
        scope = f.get("scope") or "my"
        today = date.today().isoformat()
        sql = """SELECT t.*, p.name AS patient_name, p.phone AS phone FROM crm_tasks t LEFT JOIN patients p ON p.id=t.patient_id"""
        if scope == "done":
            rows = self.db.q(sql + " WHERE t.status='done' AND t.done_at >= ? ORDER BY t.done_at DESC LIMIT 500",
                             ((date.today() - timedelta(days=30)).isoformat(),))
        else:
            rows = self.db.q(sql + " WHERE t.status='open' ORDER BY t.due, t.created_at")
            if scope == "my":
                me = str(login or "").lower()
                rows = [r for r in rows if not r["assignee"] or r["assignee"].lower() == me]
            elif scope == "overdue":
                rows = [r for r in rows if (r["due"] or today) < today]
        names = self._names()
        fut = self._future()
        for r in rows:
            r["assignee_name"] = names.get((r["assignee"] or "").lower(), "") if r["assignee"] else ""
            r["overdue"] = r["status"] == "open" and (r["due"] or today) < today
            r["today"] = r["status"] == "open" and (r["due"] or today) == today
            r["booked"] = r["patient_id"] in fut
        open_rows = self.db.q("SELECT assignee, due FROM crm_tasks WHERE status='open'")
        me = str(login or "").lower()
        mine = [r for r in open_rows if not r["assignee"] or r["assignee"].lower() == me]
        return {"scope": scope, "rows": rows, "results": TASK_RESULTS, "staff": self.staff(),
                "counts": {"my": sum(1 for r in mine if (r["due"] or today) <= today), "my_all": len(mine), "all": len(open_rows),
                           "overdue": sum(1 for r in open_rows if (r["due"] or today) < today)}}

    def due_count(self, login=""):
        """Open tasks for today and earlier: mine and shared (the menu badge)."""
        today = date.today().isoformat()
        r = self.db.one("""SELECT COUNT(*) AS n FROM crm_tasks WHERE status='open' AND COALESCE(due,'') <= ?
                           AND (COALESCE(assignee,'')='' OR lower(assignee)=lower(?))""", (today, str(login or "")))
        return r["n"]

    def task_save(self, f, who=""):
        f = f or {}
        title = str(f.get("title") or "").strip()[:200]
        if not title:
            raise ValueError("Напишите, что нужно сделать")
        pid = str(f.get("patient_id") or "") or None
        if pid and not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Пациент не найден")
        lead = str(f.get("lead_id") or "") or None
        if lead and not self.db.one("SELECT 1 AS x FROM crm_leads WHERE id=?", (lead,)):
            raise ValueError("Заявка не найдена")
        due = _clean_day(f.get("due"), "Срок") or date.today().isoformat()
        assignee = self._check_login(f.get("assignee"))
        comment = str(f.get("comment") or "").strip()[:500]
        tid = str(f.get("id") or "")
        with self.db.tx() as c:
            if tid and c.execute("SELECT 1 FROM crm_tasks WHERE id=?", (tid,)).fetchone():
                c.execute("UPDATE crm_tasks SET title=?, patient_id=?, lead_id=?, assignee=?, due=?, comment=?, updated_at=? WHERE id=?",
                          (title, pid, lead, assignee, due, comment, _now(), tid))
            else:
                tid = _id("T")
                c.execute("""INSERT INTO crm_tasks(id, title, kind, rule, patient_id, lead_id, plan_id, assignee, due, status,
                             result, comment, created_at, created_by, done_at, done_by, updated_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (tid, title, "task", None, pid, lead, None, assignee, due, "open", None, comment, _now(), who, None, None, _now()))
        return tid

    def task_done(self, tid, result="", comment="", who="", later=None):
        """Close a task with a result; «Перезвонить позже» moves the due date instead."""
        t = self.db.one("SELECT * FROM crm_tasks WHERE id=?", (str(tid or ""),))
        if not t:
            raise ValueError("Задача не найдена")
        result = str(result or "Сделано")
        if result not in TASK_RESULTS:
            raise ValueError("Выберите результат")
        note = str(comment or "").strip()[:500]
        comment = (t["comment"] + "\n" if t["comment"] and note else t["comment"] or "") + note
        with self.db.tx() as c:
            if result == "Перезвонить позже":
                due = _clean_day(later, "Когда перезвонить") or (date.today() + timedelta(days=1)).isoformat()
                c.execute("UPDATE crm_tasks SET due=?, result=?, comment=?, updated_at=? WHERE id=?", (due, result, comment, _now(), t["id"]))
            else:
                c.execute("UPDATE crm_tasks SET status='done', result=?, comment=?, done_at=?, done_by=?, updated_at=? WHERE id=?",
                          (result, comment, _now(), who, _now(), t["id"]))
        # a call result also goes to the call journal, so the call lists show it too
        if t["patient_id"] and self.mk and result in ("Записался", "Дозвонились", "Не дозвонились", "Отказ", "Перезвонить позже"):
            self.mk.log_call({"patient_id": t["patient_id"], "list": "tasks", "result": {"Перезвонить позже": "Перезвонить"}.get(result, result),
                              "comment": (t["title"] + (". " + note if note else ""))[:300]}, who)
        return True

    def task_reopen(self, tid):
        with self.db.tx() as c:
            if not c.execute("UPDATE crm_tasks SET status='open', done_at=NULL, done_by=NULL, updated_at=? WHERE id=?",
                             (_now(), str(tid or ""))).rowcount:
                raise ValueError("Задача не найдена")
        return True

    def task_delete(self, tid):
        """A task made by hand is deleted; one made by a rule is hidden (otherwise the rule makes it again)."""
        t = self.db.one("SELECT kind FROM crm_tasks WHERE id=?", (str(tid or ""),))
        if not t:
            raise ValueError("Задача не найдена")
        with self.db.tx() as c:
            if t["kind"] == "task":
                c.execute("DELETE FROM crm_tasks WHERE id=?", (tid,))
            else:
                c.execute("UPDATE crm_tasks SET status='dismissed', updated_at=? WHERE id=?", (_now(), tid))
        return True

    # ----------------------------------------------------- automatic tasks --
    def _events(self, since):
        """(patient, day, service name) since the date: lines of invoices and finished visits."""
        out = []
        for r in self.db.q("""SELECT patient_id, created_at, items FROM invoices
                              WHERE COALESCE(kind,'invoice')='invoice' AND created_at >= ? AND patient_id IS NOT NULL""", (since,)):
            try:
                items = json.loads(r["items"] or "[]")
            except ValueError:
                items = []
            for it in items:
                out.append((r["patient_id"], r["created_at"][:10], _low(it.get("title"))))
        for r in self.db.q(f"SELECT patient_id, start, status, title FROM ({HIST}) WHERE start >= ? AND start < ? AND patient_id IS NOT NULL",
                           (since, _now())):
            if r["title"] and status_kind(r["status"]) in ("done", "came"):
                out.append((r["patient_id"], r["start"][:10], _low(r["title"])))
        return out

    def auto(self, force=False):
        """Make the tasks the rules ask for (at most every GEN_EVERY seconds). Returns how many were added."""
        import time
        if not force and time.time() - self._gen_at < GEN_EVERY:
            return 0
        self._gen_at = time.time()
        s = self.settings()
        today = date.today()
        skip = self._no_calls()
        fut = self._future()
        have = {r["id"]: r for r in self.db.q("SELECT id, status, rule, patient_id FROM crm_tasks WHERE kind<>'task'")}
        new, close = [], []
        rules = [r for r in s["rules"] if r.get("on") and _words(r.get("match"))]
        if rules:
            longest = max(int(r["days"]) for r in rules)
            events = self._events((today - timedelta(days=longest + LOOKBACK)).isoformat())
            for rule in rules:
                words, days = _words(rule["match"]), int(rule["days"])
                lo, hi = today - timedelta(days=days + (LOOKBACK if days >= 30 else 2)), today - timedelta(days=days)
                last = {}
                for pid, d, title in events:
                    if any(w in title for w in words):
                        last[pid] = max(last.get(pid, ""), d)
                for pid, d in last.items():
                    dd = _day(d)
                    if not dd or not lo <= dd <= hi or pid in skip:
                        continue
                    if rule.get("skip_booked") and pid in fut:
                        continue
                    tid = _auto_id(rule["id"], pid, d)
                    if tid in have:
                        continue
                    new.append((tid, rule["title"], "auto", rule["id"], pid, None, None, "", max(dd + timedelta(days=days), today).isoformat(),
                                "open", None, f"Услуга {_fmt(d)}", _now(), "Программа", None, None, _now()))
            skip_rules = {r["id"] for r in rules if r.get("skip_booked")}
            close = [tid for tid, t in have.items() if t["status"] == "open" and t["rule"] in skip_rules and t["patient_id"] in fut]
        if s.get("plan_on"):
            border = (today - timedelta(days=int(s["plan_days"]))).isoformat()
            plans = self.db.q("""SELECT i.id, i.patient_id, i.title, i.created_at,
                    (SELECT MAX(j.created_at) FROM invoices j WHERE j.plan_id=i.id) AS billed
                FROM invoices i WHERE i.kind='plan' AND COALESCE(i.plan_status,'') IN ('Подтверждён','Активен')""")
            last_visit = {r["patient_id"]: r["m"] for r in self.db.q(
                f"SELECT patient_id, MAX(start) AS m FROM ({HIST}) WHERE start < ? GROUP BY patient_id", (_now(),))}
            for p in plans:
                pid = p["patient_id"]
                if not pid or pid in skip or pid in fut:
                    continue
                act = max(p["created_at"] or "", p["billed"] or "", last_visit.get(pid) or "")[:10]
                if not act or act >= border:
                    continue
                tid = _auto_id("plan", p["id"], act)
                if tid in have:
                    continue
                title = "План лечения не завершён — пригласить продолжить"
                new.append((tid, title, "auto", "plan", pid, None, p["id"], "", today.isoformat(), "open", None,
                            f"{p['title'] or 'План лечения'}; последний раз — {_fmt(act)}", _now(), "Программа", None, None, _now()))
            close += [tid for tid, t in have.items() if t["status"] == "open" and t["rule"] == "plan" and t["patient_id"] in fut]
        self._money_tasks(s, today, skip, have, new, close)
        if new or close:
            with self.db.tx() as c:
                c.executemany("""INSERT OR IGNORE INTO crm_tasks(id, title, kind, rule, patient_id, lead_id, plan_id, assignee, due,
                                 status, result, comment, created_at, created_by, done_at, done_by, updated_at)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", new)
                for tid in close:
                    c.execute("UPDATE crm_tasks SET status='done', result=CASE WHEN rule IN ('debt','pay') THEN 'Сделано' ELSE 'Записался' END, "
                              "done_at=?, done_by='Программа', comment=CASE WHEN rule IN ('debt','pay') THEN TRIM(COALESCE(comment,'') || ' Оплачено.') "
                              "ELSE comment END, updated_at=? WHERE id=? AND status='open'", (_now(), _now(), tid))
        return len(new)

    def _money_tasks(self, s, today, skip, have, new, close):
        """2.12: a passed installment date and a debt that hangs for `debt_days` → a reminder for the front desk.
        The task closes itself when the money comes."""
        from finance import Finance
        from reports import Reports
        fin = Finance(self.db)
        if s.get("pay_on", True):
            late = fin.overdue()
            keys = set()
            for x in late:
                if x["patient_id"] in skip:
                    continue
                tid = _auto_id("pay", x["invoice_id"], x["due"])
                keys.add(tid)
                if tid not in have:
                    new.append((tid, "Напомнить о платеже по рассрочке", "auto", "pay", x["patient_id"], None, None, "", today.isoformat(),
                                "open", None, f"{_rub(x['amount'])}, срок был {_fmt(x['due'])}", _now(), "Программа", None, None, _now()))
            close += [tid for tid, t in have.items() if t["status"] == "open" and t["rule"] == "pay" and tid not in keys]
        if s.get("debt_on", True):
            border = (today - timedelta(days=int(s.get("debt_days") or 7))).isoformat()
            later = fin.not_due()
            owing = set()
            for x in Reports(self.db).debts()["debts"]:
                rest = round(x["debt"] - later.get(x["patient_id"], 0), 2)  # what is in a schedule is not late yet
                if rest < 0.009:
                    continue
                owing.add(x["patient_id"])
                if x["patient_id"] in skip or not x["last"] or x["last"][:10] > border:
                    continue
                tid = _auto_id("debt", x["patient_id"], x["last"][:10])
                if tid not in have:
                    new.append((tid, "Напомнить о долге", "auto", "debt", x["patient_id"], None, None, "", today.isoformat(), "open", None,
                                f"Долг {_rub(rest)}", _now(), "Программа", None, None, _now()))
            close += [tid for tid, t in have.items() if t["status"] == "open" and t["rule"] == "debt" and t["patient_id"] not in owing]

    # ============================================================== leads --
    def match(self, phone, name=""):
        """Patients with the same phone (last 10 digits) — so a request does not make a second card."""
        d = digits(phone)
        if len(d) < 10:
            return []
        out = []
        for p in self.db.q("SELECT id, name, phone, birth FROM patients WHERE phone IS NOT NULL AND phone<>''"):
            if digits(p["phone"]) == d:
                out.append(p)
        return out[:10]

    def leads(self, f=None):
        f = f or {}
        self._advance()
        a, b = _period(f.get("from") or (date.today() - timedelta(days=90)).isoformat(), f.get("to"))
        rows = self.db.q("""SELECT l.*, p.name AS patient_name FROM crm_leads l LEFT JOIN patients p ON p.id=l.patient_id
                            WHERE l.created_at >= ? AND l.created_at < ? ORDER BY l.created_at DESC""", (a, b))
        if f.get("open"):  # still being worked on, whatever the date
            rows += [r for r in self.db.q("""SELECT l.*, p.name AS patient_name FROM crm_leads l LEFT JOIN patients p ON p.id=l.patient_id
                                             WHERE l.created_at < ? AND l.stage IN ('new','contact') ORDER BY l.created_at DESC""", (a,))]
        q = _low(f.get("q")).strip()
        if q:
            qd = re.sub(r"\D", "", q)
            rows = [r for r in rows if q in _low(r["name"]) or (qd and qd in re.sub(r"\D", "", r["phone"] or ""))]
        names = self._names()
        today = date.today().isoformat()
        for r in rows:
            r["assignee_name"] = names.get((r["assignee"] or "").lower(), "")
            r["late"] = r["stage"] in ("new", "contact") and bool(r["next_at"]) and r["next_at"][:10] < today
        by = {k: [r for r in rows if r["stage"] == k] for k in STAGE_KEYS}
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(), "rows": rows,
                "stages": [{"key": k, "title": t, "count": len(by[k])} for k, t in STAGES],
                "channels": CHANNELS, "reasons": LOST_REASONS, "staff": self.staff()}

    def lead(self, lid):
        r = self.db.one("SELECT l.*, p.name AS patient_name, p.phone AS patient_phone FROM crm_leads l "
                        "LEFT JOIN patients p ON p.id=l.patient_id WHERE l.id=?", (str(lid or ""),))
        if not r:
            raise ValueError("Заявка не найдена")
        r["tasks"] = self.db.q("SELECT * FROM crm_tasks WHERE lead_id=? ORDER BY created_at DESC", (r["id"],))
        r["matches"] = [] if r["patient_id"] else self.match(r["phone"])
        return r

    def lead_save(self, f, who=""):
        f = f or {}
        name = " ".join(str(f.get("name") or "").split())[:120]
        phone = str(f.get("phone") or "").strip()[:40]
        if not name and not phone:
            raise ValueError("Укажите имя или телефон")
        if phone and len(digits(phone)) < 10:
            raise ValueError("Телефон: нужно 10–11 цифр")
        channel = str(f.get("channel") or "")[:40]
        source = str(f.get("source") or "").strip()[:60]
        stage = f.get("stage") if f.get("stage") in STAGE_KEYS else None
        vals = {"name": name, "phone": phone, "source": source, "channel": channel,
                "interest": str(f.get("interest") or "").strip()[:200], "comment": str(f.get("comment") or "").strip()[:1000],
                "assignee": self._check_login(f.get("assignee")), "next_at": _clean_day(f.get("next_at"), "Когда связаться")}
        lid = str(f.get("id") or "")
        with self.db.tx() as c:
            if lid and c.execute("SELECT 1 FROM crm_leads WHERE id=?", (lid,)).fetchone():
                c.execute("""UPDATE crm_leads SET name=?, phone=?, source=?, channel=?, interest=?, comment=?, assignee=?, next_at=?,
                             updated_at=? WHERE id=?""", (*vals.values(), _now(), lid))
            else:
                lid = _id("LD")
                c.execute("""INSERT INTO crm_leads(id, name, phone, source, channel, interest, comment, assignee, next_at, stage,
                             lost_reason, patient_id, created_at, created_by, updated_at, closed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (lid, *vals.values(), stage or "new", None, None, _now(), who, _now(), None))
        if f.get("patient_id"):
            self.lead_link(lid, f["patient_id"])
        return lid

    def lead_stage(self, lid, stage, reason=""):
        if stage not in STAGE_KEYS:
            raise ValueError("Неизвестный этап")
        reason = str(reason or "").strip()[:100]
        if stage == "lost" and not reason:
            raise ValueError("Укажите причину отказа")
        closed = _now() if stage in ("came", "lost") else None
        with self.db.tx() as c:
            if not c.execute("UPDATE crm_leads SET stage=?, lost_reason=?, closed_at=?, updated_at=? WHERE id=?",
                             (stage, reason if stage == "lost" else None, closed, _now(), str(lid or ""))).rowcount:
                raise ValueError("Заявка не найдена")
        return True

    def lead_link(self, lid, pid):
        """Tie the request to a patient card (found by phone or just created)."""
        if not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (str(pid or ""),)):
            raise ValueError("Пациент не найден")
        lead = self.db.one("SELECT * FROM crm_leads WHERE id=?", (str(lid or ""),))
        if not lead:
            raise ValueError("Заявка не найдена")
        with self.db.tx() as c:
            c.execute("UPDATE crm_leads SET patient_id=?, updated_at=? WHERE id=?", (pid, _now(), lid))
        if lead["source"] and self.mk and not (self.mk.patient_info(pid).get("source")):
            self.mk.set_patient(pid, {"source": lead["source"]})
        self._advance()
        return True

    def lead_patient(self, lid):
        """Make a patient card from the request (name split into surname / name / patronymic)."""
        lead = self.db.one("SELECT * FROM crm_leads WHERE id=?", (str(lid or ""),))
        if not lead:
            raise ValueError("Заявка не найдена")
        if lead["patient_id"]:
            return {"id": lead["patient_id"]}
        if not self.local:
            raise ValueError("Нет доступа к карточкам")
        parts = (lead["name"] or "").split()
        if not parts:
            raise ValueError("Укажите в заявке имя пациента")
        p = self.local.create_patient({"lname": parts[0], "fname": " ".join(parts[1:2]), "mname": " ".join(parts[2:]),
                                       "phone": lead["phone"] or "", "comment": f"Из заявки: {lead['interest'] or lead['channel'] or ''}".strip(": ")})
        self.lead_link(lid, p["id"])
        return p

    def _advance(self):
        """A request with a patient moves on by itself: a visit after the request → «Записан», a visit that took place → «Пришёл»."""
        rows = self.db.q("SELECT id, patient_id, stage, created_at FROM crm_leads WHERE patient_id IS NOT NULL AND stage IN ('new','contact','booked')")
        if not rows:
            return
        now = _now()
        vis = {}
        pids = {r["patient_id"] for r in rows}
        for v in self.db.q(f"SELECT patient_id, start, status FROM ({DB.ALL_VISITS}) WHERE patient_id IS NOT NULL"):
            if v["patient_id"] in pids:
                vis.setdefault(v["patient_id"], []).append(v)
        upd = []
        for r in rows:
            best = r["stage"]
            for v in vis.get(r["patient_id"], []):
                k = status_kind(v["status"])
                if k in ("cancel", "noshow") or v["start"][:10] < r["created_at"][:10]:
                    continue
                st = "came" if (v["start"] < now and k in ("done", "came")) else "booked"
                if STAGE_ORDER[st] > STAGE_ORDER[best]:
                    best = st
            if best != r["stage"]:
                upd.append((best, now if best == "came" else None, now, r["id"]))
        if upd:
            with self.db.tx() as c:
                c.executemany("UPDATE crm_leads SET stage=?, closed_at=?, updated_at=? WHERE id=?", upd)

    def funnel(self, date_from=None, date_to=None):
        """Requests of the period: how many reached each stage, by source and by channel, and why they refused."""
        self._advance()
        a, b = _period(date_from, date_to)
        rows = self.db.q("SELECT * FROM crm_leads WHERE created_at >= ? AND created_at < ?", (a, b))
        reach = {k: sum(1 for r in rows if r["stage"] != "lost" and STAGE_ORDER[r["stage"]] >= STAGE_ORDER[k]) for k in STAGE_KEYS[:4]}
        reach["new"] = len(rows)

        def group(key):
            g = {}
            for r in rows:
                x = g.setdefault(r[key] or "", {"name": r[key] or "", "leads": 0, "booked": 0, "came": 0, "lost": 0})
                x["leads"] += 1
                x["booked"] += r["stage"] in ("booked", "came")
                x["came"] += r["stage"] == "came"
                x["lost"] += r["stage"] == "lost"
            for x in g.values():
                x["conv"] = round(x["came"] * 100 / x["leads"]) if x["leads"] else 0
            return sorted(g.values(), key=lambda x: (x["name"] == "", -x["leads"]))
        reasons = {}
        for r in rows:
            if r["stage"] == "lost":
                reasons[r["lost_reason"] or "Без причины"] = reasons.get(r["lost_reason"] or "Без причины", 0) + 1
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(), "total": len(rows),
                "steps": [{"key": k, "title": t, "count": reach[k]} for k, t in STAGES[:4]],
                "lost": sum(1 for r in rows if r["stage"] == "lost"),
                "by_source": group("source"), "by_channel": group("channel"),
                "reasons": sorted(({"reason": k, "count": v} for k, v in reasons.items()), key=lambda x: -x["count"])}

    # ============================================================ reviews --
    def review_save(self, f, who=""):
        f = f or {}
        pid = str(f.get("patient_id") or "")
        if not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Пациент не найден")
        try:
            score = int(f.get("score"))
        except (TypeError, ValueError):
            raise ValueError("Выберите оценку от 0 до 10") from None
        if not 0 <= score <= 10:
            raise ValueError("Выберите оценку от 0 до 10")
        channel = f.get("channel") if f.get("channel") in ("tablet", "phone", "message") else "phone"
        vid, doc = str(f.get("visit_id") or "") or None, str(f.get("doctor_id") or "") or None
        if vid and not doc:
            v = self.db.one(f"SELECT doctor_id FROM ({DB.ALL_VISITS}) WHERE id=?", (vid,))
            doc = v["doctor_id"] if v else None
        if not vid:  # the latest visit that took place
            v = self.db.one(f"SELECT id, doctor_id FROM ({HIST}) WHERE patient_id=? AND start < ? ORDER BY start DESC LIMIT 1", (pid, _now()))
            if v:
                vid, doc = v["id"], doc or v["doctor_id"]
        rid = _id("RV")
        comment = str(f.get("comment") or "").strip()[:1000]
        with self.db.tx() as c:
            c.execute("""INSERT INTO crm_reviews(id, patient_id, visit_id, doctor_id, score, comment, channel, created_at, user_name)
                         VALUES(?,?,?,?,?,?,?,?,?)""", (rid, pid, vid, doc, score, comment, channel, _now(), who))
        s = self.settings()
        if score <= s["bad_score"]:
            tid = _auto_id("review", rid)
            with self.db.tx() as c:
                c.execute("""INSERT OR IGNORE INTO crm_tasks(id, title, kind, rule, patient_id, lead_id, plan_id, assignee, due, status,
                             result, comment, created_at, created_by, done_at, done_by, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (tid, f"Пациент недоволен (оценка {score}) — позвонить и разобраться", "auto", "review", pid, None, None,
                           self._director_login(), date.today().isoformat(), "open", None, comment[:500], _now(), "Программа", None, None, _now()))
        return {"id": rid, "score": score, "ask_review": score >= s["good_score"], "links": self.review_links() if score >= s["good_score"] else []}

    def review_delete(self, rid):
        with self.db.tx() as c:
            if not c.execute("DELETE FROM crm_reviews WHERE id=?", (str(rid or ""),)).rowcount:
                raise ValueError("Оценка не найдена")
        return True

    def review_queue(self, day=None):
        """Who to ask about the visit: patients whose visit on the day took place and who have not rated it yet."""
        d = _clean_day(day) or date.today().isoformat()
        nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        rows = self.db.q(f"""SELECT a.id AS visit_id, a.patient_id, a.start, a.status, a.title, a.doctor_id, p.name, p.phone, dr.name AS doctor_name
                             FROM ({DB.ALL_VISITS}) a LEFT JOIN patients p ON p.id=a.patient_id LEFT JOIN doctors dr ON dr.id=a.doctor_id
                             WHERE a.start >= ? AND a.start < ? AND a.patient_id IS NOT NULL ORDER BY a.start""", (d, nxt))
        rated = {r["patient_id"] for r in self.db.q("SELECT patient_id FROM crm_reviews WHERE created_at >= ?", (d,))}
        skip = self._no_calls()
        out, seen = [], set()
        for r in rows:
            if status_kind(r["status"]) in ("cancel", "noshow") or r["start"] > _now() or r["patient_id"] in seen:
                continue
            seen.add(r["patient_id"])
            r["rated"] = r["patient_id"] in rated
            r["no_calls"] = r["patient_id"] in skip
            r["info"] = f"{r['start'][11:16]} · {r['doctor_name'] or 'врач не указан'}" + (f" · {r['title']}" if r["title"] else "")
            out.append(r)
        return {"day": d, "rows": out, "left": sum(1 for r in out if not r["rated"] and not r["no_calls"])}

    def reviews(self, date_from=None, date_to=None):
        """NPS of the period: % of 9–10 minus % of 0–6, for the clinic and each doctor, and the latest comments."""
        a, b = _period(date_from, date_to)
        rows = self.db.q("""SELECT r.*, p.name AS patient_name, p.phone AS phone, d.name AS doctor_name FROM crm_reviews r
                            LEFT JOIN patients p ON p.id=r.patient_id LEFT JOIN doctors d ON d.id=r.doctor_id
                            WHERE r.created_at >= ? AND r.created_at < ? ORDER BY r.created_at DESC""", (a, b))

        def nps(rs):
            n = len(rs)
            if not n:
                return {"count": 0, "nps": None, "avg": None, "promoters": 0, "passives": 0, "detractors": 0}
            pro = sum(1 for r in rs if r["score"] >= 9)
            det = sum(1 for r in rs if r["score"] <= 6)
            return {"count": n, "nps": round((pro - det) * 100 / n), "avg": round(sum(r["score"] for r in rs) / n, 1),
                    "promoters": pro, "passives": n - pro - det, "detractors": det}
        docs = {}
        for r in rows:
            docs.setdefault(r["doctor_id"] or "", []).append(r)
        by_doc = sorted(({"doctor_id": k, "name": (v[0]["doctor_name"] or "Без врача"), **nps(v)} for k, v in docs.items()),
                        key=lambda x: (-x["count"], x["name"]))
        dist = [sum(1 for r in rows if r["score"] == i) for i in range(11)]
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(), **nps(rows), "by_doctor": by_doc,
                "dist": dist, "rows": rows[:300], "links": [{"key": x["key"], "title": x["title"], "url": x["url"]} for x in self.review_links()]}

    # ============================================================ segments --
    def segments(self):
        out = []
        for r in self.db.q("SELECT * FROM crm_segments ORDER BY title"):
            try:
                r["filters"] = json.loads(r["filters"] or "{}")
            except ValueError:
                r["filters"] = {}
            out.append(r)
        return {"saved": out, "presets": PRESETS, "sources": self.mk.sources() if self.mk else []}

    def segment_save(self, f, who=""):
        title = str((f or {}).get("title") or "").strip()[:80]
        if not title:
            raise ValueError("Назовите сегмент")
        filters = clean_filters((f or {}).get("filters"))
        sid = str((f or {}).get("id") or "") or _id("SG")
        with self.db.tx() as c:
            c.execute("""INSERT INTO crm_segments(id, title, filters, created_by, updated_at) VALUES(?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET title=excluded.title, filters=excluded.filters, updated_at=excluded.updated_at""",
                      (sid, title, json.dumps(filters, ensure_ascii=False), who, _now()))
        return sid

    def segment_delete(self, sid):
        with self.db.tx() as c:
            if not c.execute("DELETE FROM crm_segments WHERE id=?", (str(sid or ""),)).rowcount:
                raise ValueError("Сегмент не найден")
        return True

    def segment_run(self, filters):
        """Patients that match all the filters (no «do not call» patients unless asked)."""
        f = clean_filters(filters)
        today = date.today()
        now = _now()
        pats = self.db.q("SELECT id, name, phone, birth FROM patients")
        vis = {}
        for v in self.db.q(f"SELECT patient_id, doctor_id, start, status FROM ({HIST}) WHERE patient_id IS NOT NULL"):
            if status_kind(v["status"]) in ("cancel", "noshow"):
                continue
            x = vis.setdefault(v["patient_id"], {"last": "", "future": False, "count": 0, "doctors": set()})
            if v["start"] >= now:
                x["future"] = True
            else:
                x["last"] = max(x["last"], v["start"])
                x["count"] += 1
                if v["doctor_id"]:
                    x["doctors"].add(v["doctor_id"])
        sources = {}
        if f.get("source"):
            for r in self.db.q("""SELECT id, json_extract(COALESCE(detail,data),'$.source') AS s FROM patients
                                  WHERE json_type(COALESCE(detail,data),'$.source')='text'"""):
                sources[r["id"]] = str(r["s"]).strip()
            sources.update({r["patient_id"]: r["source"] for r in self.db.q("SELECT patient_id, source FROM patient_marketing WHERE source<>''")})
        plans = {}
        if f.get("plan"):
            for p in self.db.q("SELECT patient_id, plan_status, id, (SELECT COUNT(*) FROM invoices j WHERE j.plan_id=i.id) AS billed "
                               "FROM invoices i WHERE kind='plan'"):
                st = p["plan_status"] or "Предварительный"
                if st in ("Лечение завершено", "Отказ"):
                    continue
                kind = "unfinished" if (st == "Активен" or p["billed"]) else "not_started"
                plans.setdefault(p["patient_id"], set()).add(kind)
        debts = {}
        if f.get("debt"):
            from reports import Reports
            debts = {x["patient_id"]: x["total"] for x in Reports(self.db).debts()["debts"]}
        paid = {}
        if f.get("paid_min"):
            paid = {r["patient_id"]: r["s"] for r in self.db.q("SELECT patient_id, SUM(amount) AS s FROM payments GROUP BY patient_id")}
        service_last = {}
        if f.get("service"):
            words = _words(f["service"])
            for pid, d, title in self._events("2000-01-01"):
                if any(w in title for w in words):
                    service_last[pid] = max(service_last.get(pid, ""), d)
        skip = set() if f.get("with_no_calls") else self._no_calls()
        out = []
        for p in pats:
            pid = p["id"]
            if pid in skip:
                continue
            v = vis.get(pid) or {"last": "", "future": False, "count": 0, "doctors": set()}
            info = []
            if f.get("no_future") and v["future"]:
                continue
            if f.get("months"):
                if not v["last"] or v["last"] >= (today - timedelta(days=int(f["months"] * 30.4))).isoformat():
                    continue
            if f.get("visits_min") and v["count"] < f["visits_min"]:
                continue
            if f.get("doctor_id") and f["doctor_id"] not in v["doctors"]:
                continue
            bd = _day(p["birth"])
            age = None
            if bd:
                age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
            if f.get("age_min") is not None and (age is None or age < f["age_min"]):
                continue
            if f.get("age_max") is not None and (age is None or age > f["age_max"]):
                continue
            if f.get("birthday_days"):
                if not bd:
                    continue
                n = _days_to_birthday(bd, today)
                if n >= f["birthday_days"]:
                    continue
                info.append("день рождения " + ("сегодня" if n == 0 else "завтра" if n == 1 else f"через {n} дн."))
            if f.get("source") and sources.get(pid, "") != f["source"]:
                continue
            if f.get("plan"):
                have = plans.get(pid, set())
                if not (have if f["plan"] == "any" else {f["plan"]} & have):
                    continue
                info.append("план не начат" if have == {"not_started"} else "план не завершён")
            if f.get("debt"):
                if not debts.get(pid):
                    continue
                info.append(f"долг {_rub(debts[pid])}")
            if f.get("paid_min") and (paid.get(pid) or 0) < f["paid_min"]:
                continue
            if f.get("service"):
                sd = service_last.get(pid)
                if not sd:
                    continue
                if f.get("service_months") and sd >= (today - timedelta(days=int(f["service_months"] * 30.4))).isoformat():
                    continue
                info.append(f"услуга {_fmt(sd)}")
            if v["last"]:
                info.append(f"последний визит {_fmt(v['last'])}")
            if v["future"]:
                info.append("есть запись")
            out.append({"patient_id": pid, "name": p["name"], "phone": p["phone"], "start": v["last"], "info": ", ".join(info), "age": age})
        out.sort(key=lambda x: (x["name"] or ""))
        return {"filters": f, "rows": out[:3000], "count": len(out), "with_phone": sum(1 for r in out if len(digits(r["phone"])) >= 10),
                "cut": len(out) > 3000}

    # ======================================================== ad payback --
    def ad_spend(self, a, b):
        """Advertising expenses of the period by source ('' — the source was not chosen)."""
        out = {}
        try:
            rows = self.db.q("SELECT COALESCE(source,'') AS s, SUM(amount) AS t FROM expenses WHERE category=? AND date >= ? AND date < ? "
                             "GROUP BY s", (AD_CATEGORY, a, b))
        except sqlite3.OperationalError:  # no accounting tables yet (the column comes with Accounting)
            return out
        for r in rows:
            out[r["s"]] = round(r["t"] or 0, 2)
        return out

    def leads_by_source(self, a, b):
        out = {}
        for r in self.db.q("SELECT COALESCE(source,'') AS s, stage FROM crm_leads WHERE created_at >= ? AND created_at < ?", (a, b)):
            x = out.setdefault(r["s"], {"leads": 0, "came": 0})
            x["leads"] += 1
            x["came"] += r["stage"] == "came"
        return out

    # ===================================================== patient card --
    def patient(self, pid):
        pid = str(pid or "")
        tasks = self.db.q("SELECT * FROM crm_tasks WHERE patient_id=? AND status IN ('open','done') ORDER BY COALESCE(done_at, due) DESC LIMIT 50", (pid,))
        leads = self.db.q("SELECT * FROM crm_leads WHERE patient_id=? ORDER BY created_at DESC", (pid,))
        reviews = self.db.q("SELECT r.*, d.name AS doctor_name FROM crm_reviews r LEFT JOIN doctors d ON d.id=r.doctor_id "
                            "WHERE r.patient_id=? ORDER BY r.created_at DESC", (pid,))
        calls = self.db.q("SELECT * FROM marketing_calls WHERE patient_id=? ORDER BY id DESC LIMIT 50", (pid,))
        names = self._names()
        for t in tasks:
            t["assignee_name"] = names.get((t["assignee"] or "").lower(), "")
        return {"tasks": tasks, "leads": leads, "reviews": reviews, "calls": calls,
                "open": sum(1 for t in tasks if t["status"] == "open"), "stages": dict(STAGES)}

    def summary(self, login=""):
        self.auto()
        today = date.today().isoformat()
        st = self.db.one("""SELECT SUM(CASE WHEN due < ? THEN 1 ELSE 0 END) AS overdue, COUNT(*) AS open FROM crm_tasks WHERE status='open'""", (today,))
        return {"tasks_due": self.due_count(login), "tasks_open": st["open"] or 0, "tasks_overdue": st["overdue"] or 0,
                "leads_new": self.db.one("SELECT COUNT(*) AS n FROM crm_leads WHERE stage='new'")["n"]}


# ---------------------------------------------------------------- filters --
PRESETS = [
    {"id": "p_lost6", "title": "Не были больше 6 месяцев", "filters": {"months": 6, "no_future": True}},
    {"id": "p_plan", "title": "План лечения не завершён", "filters": {"plan": "any", "no_future": True}},
    {"id": "p_hyg", "title": "Профгигиена больше полугода назад", "filters": {"service": "гигиен, чистк", "service_months": 6, "no_future": True}},
    {"id": "p_bd", "title": "Дни рождения в ближайший месяц", "filters": {"birthday_days": 31}},
    {"id": "p_debt", "title": "Должники", "filters": {"debt": True}},
    {"id": "p_vip", "title": "Постоянные пациенты (5 и больше визитов)", "filters": {"visits_min": 5}},
]


def clean_filters(f):
    f = f if isinstance(f, dict) else {}
    out = {}

    def num(k, lo, hi):
        v = f.get(k)
        if v in (None, "", False):
            return
        try:
            x = int(float(str(v).replace(",", ".")))
        except ValueError:
            raise ValueError("В фильтре нужно число") from None
        out[k] = min(hi, max(lo, x))
    num("months", 1, 120)
    num("visits_min", 1, 1000)
    num("age_min", 0, 120)
    num("age_max", 0, 120)
    num("birthday_days", 1, 366)
    num("paid_min", 1, 100_000_000)
    num("service_months", 1, 120)
    if "age_min" in out and "age_max" in out and out["age_min"] > out["age_max"]:
        raise ValueError("Возраст «от» больше, чем «до»")
    for k in ("no_future", "debt", "with_no_calls"):
        if f.get(k):
            out[k] = True
    if f.get("plan") in ("any", "not_started", "unfinished"):
        out["plan"] = f["plan"]
    for k, n in (("source", 60), ("doctor_id", 60), ("service", 120)):
        v = str(f.get(k) or "").strip()[:n]
        if v:
            out[k] = v
    if "service_months" in out and "service" not in out:
        out.pop("service_months")
    return out


def _days_to_birthday(bd, today):
    for y in (today.year, today.year + 1):
        try:
            nxt = bd.replace(year=y)
        except ValueError:  # 29 February
            nxt = date(y, 3, 1)
        if nxt >= today:
            return (nxt - today).days
    return 999


def _fmt(d):
    d = str(d or "")
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}" if len(d) >= 10 else d


def _rub(v):
    return f"{round(v or 0):,}".replace(",", " ") + " ₽"


def qr_data_uri(text):
    try:
        import segno
        return segno.make(str(text), error="m").png_data_uri(scale=8, border=2)
    except Exception:  # noqa: BLE001 — no QR without the library: the link is shown as text
        return ""
