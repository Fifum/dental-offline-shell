"""3.6: treatment plans as sales — «предложен → продан → в работе → завершён», «брошен» and «отказ»; the call list for
abandoned plans with the results of the calls; reports by status and doctor, conversion and the money left in abandoned plans.

The status stays in `invoices.plan_status` with the names of 2.9, so every report, segment and call list keeps working:
  Предварительный — предложен; Подтверждён — продан (the patient agreed or chose an option); Активен — в работе;
  Лечение завершено — завершён; Брошен (new) — sold or in work and nothing happens; Отказ — the patient refused.

Automatic changes (on by default, the director can switch them off and set the days):
  - a bill by the plan (as before) or a finished Dentist Plus visit with a service of the plan → «Активен»;
  - every item that may be billed is billed → «Лечение завершено»;
  - sold or in work, no visit, bill or booking for `days` (60) and nothing booked → «Брошен»
    (a proposed plan too, when `proposed_days` is set; 0 by default — «CRM → Обзвон → План не начат» covers them);
  - an abandoned plan gets a bill, a visit or a booking → back to «Активен» (it was started) or to what it was.
A manual change always wins: the rules look only at what happened after it. Every change is kept in `plan_status_log`
(who — by login; the automatic ones — «Программа»); an automatic row has an id made of the plan, the new status and the day,
so two laptops that change a plan offline keep one row after the sync. The automatic changes of a pass go to the action journal.

Calls on abandoned plans are rows of `marketing_calls` (list «abandoned», with `plan_id`, `call_on` and the caller's login),
so the patient's call history and «don't ring twice» keep working; «перезвонить» makes a CRM task due on that day (the menu
badge reminds), the other results close the plan's CRM tasks; «отказ» puts the plan to «Отказ» with the reason.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta

import plans as plansm
from reports import _period, status_kind

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_status_log(
    id TEXT PRIMARY KEY, plan_id TEXT, patient_id TEXT, old TEXT, new TEXT, reason TEXT, auto INTEGER DEFAULT 0,
    login TEXT, name TEXT, credit TEXT, at TEXT);
CREATE INDEX IF NOT EXISTS ix_psl_plan ON plan_status_log(plan_id);
CREATE INDEX IF NOT EXISTS ix_psl_at ON plan_status_log(at);
CREATE TABLE IF NOT EXISTS plan_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT);
"""
PROPOSED, SOLD, WORK, DONE, LOST, REFUSED = "Предварительный", "Подтверждён", "Активен", "Лечение завершено", "Брошен", "Отказ"
STATUSES = [(PROPOSED, "Предложен"), (SOLD, "Продан"), (WORK, "В работе"), (DONE, "Завершён"), (LOST, "Брошен"), (REFUSED, "Отказ")]
KEYS = [k for k, _ in STATUSES]
LABEL = dict(STATUSES)
SOLD_ST = (SOLD, WORK, DONE)
OPEN_ST = (PROPOSED, SOLD, WORK)
DEFAULTS = {"on": True, "days": 60, "proposed_days": 0, "done_auto": True, "visit_auto": True, "call_months": 12}
LIMITS = {"days": (14, 730), "proposed_days": (0, 730), "call_months": (0, 120)}
CALL_RESULTS = [("reached", "Дозвонились"), ("no_answer", "Не дозвонились"), ("callback", "Перезвонить"),
                ("refused", "Отказ"), ("booked", "Записался")]
CALL_LABEL = dict(CALL_RESULTS)
REFUSE_REASONS = ["Дорого", "Лечится в другой клинике", "Передумал", "Нет времени", "Переехал", "Другое"]
AUTO_NAME = "Программа"
TICK_SECONDS = 600
CREDIT_DAYS = 30   # a call this many days before a plan came back counts for the administrator (motivation)
DP_DAYS = 120      # how far back the Dentist Plus visits are matched with the plans' services


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _auto_id(*parts):
    return "PS-" + hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _fmt(d):
    d = str(d or "")
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}" if len(d) >= 10 else ""


def _rub(v):
    return f"{round(v or 0):,}".replace(",", " ") + " ₽"


def _r(x):
    return round(x or 0, 2)


def _pct(a, b):
    return round(a * 100 / b, 1) if b else None


def _item_key(it):
    return (str(it.get("service_id") or "").strip() or str(it.get("title") or "").strip().lower(), str(it.get("tooth") or "").strip())


class PlanStatus:
    def __init__(self, db, local=None, crm=None, marketing=None, sauto=None):
        self.db, self.local, self.crm, self.mk, self.sauto = db, local, crm, marketing, sauto
        with db._lock:
            db.conn.executescript(SCHEMA)
            have = {r[1] for r in db.conn.execute("PRAGMA table_info(marketing_calls)")}
            for col in ("plan_id TEXT", "call_on TEXT", "login TEXT"):
                if have and col.split()[0] not in have:
                    db.conn.execute(f"ALTER TABLE marketing_calls ADD COLUMN {col}")
            db.conn.commit()
        self._tick_at = 0.0

    # ============================================================ settings --
    def settings(self) -> dict:
        out = dict(DEFAULTS)
        for r in self.db.q("SELECT k, v FROM plan_settings"):
            try:
                out[r["k"]] = json.loads(r["v"])
            except ValueError:
                pass
        for k in ("on", "done_auto", "visit_auto"):
            out[k] = bool(out.get(k))
        for k, (lo, hi) in LIMITS.items():
            try:
                out[k] = min(hi, max(lo, int(out.get(k))))
            except (TypeError, ValueError):
                out[k] = DEFAULTS[k]
        return out

    def save_settings(self, f) -> dict:
        f = f if isinstance(f, dict) else {}
        put = {}
        for k in ("on", "done_auto", "visit_auto"):
            if k in f:
                put[k] = bool(f[k])
        for k, (lo, hi) in LIMITS.items():
            if k in f:
                try:
                    v = int(f[k])
                except (TypeError, ValueError):
                    raise ValueError("Введите число дней") from None
                if not lo <= v <= hi:
                    raise ValueError({"days": f"Брошенным план становится через {lo}–{hi} дней без движения",
                                      "proposed_days": f"Предложенный план: от 0 (не трогать) до {hi} дней",
                                      "call_months": f"Обзвон: за последние 0–{hi} месяцев"}[k])
                put[k] = v
        with self.db.tx() as c:
            for k, v in put.items():
                c.execute("""INSERT INTO plan_settings(k, v, updated_at) VALUES(?,?,?)
                             ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at""", (k, json.dumps(v), _now()))
        self._tick_at = 0.0
        return self.settings()

    def meta(self) -> dict:
        return {"statuses": [{"key": k, "label": t} for k, t in STATUSES], "settings": self.settings(),
                "results": [{"key": k, "label": t} for k, t in CALL_RESULTS], "reasons": REFUSE_REASONS}

    # ============================================================ history --
    def _log(self, c, plan_id, patient_id, old, new, reason="", login="", name="", auto=False, credit=""):
        if auto:  # the same change from the same last row makes the same id on every computer (one row after a sync)
            prev = c.execute("SELECT id FROM plan_status_log WHERE plan_id=? ORDER BY at DESC, rowid DESC LIMIT 1", (plan_id,)).fetchone()
            lid = _auto_id(plan_id, old or "", new, prev[0] if prev else "")
        else:
            lid = "PS-" + uuid.uuid4().hex[:16]
        c.execute("""INSERT OR IGNORE INTO plan_status_log(id, plan_id, patient_id, old, new, reason, auto, login, name, credit, at)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                  (lid, plan_id, patient_id, old or "", new, str(reason or "")[:300], 1 if auto else 0, (login or "").lower(),
                   name or (AUTO_NAME if auto else ""), (credit or "").lower(), _now()))

    def record(self, plan_id, old, new, reason="", login="", name="", auto=False, credit=""):
        """A change made elsewhere (the plan editor, the choice of an option, a bill by the plan, the tablet)."""
        if not plan_id or (old or "") == (new or "") or new not in KEYS:
            return False
        p = self.db.one("SELECT patient_id FROM invoices WHERE id=?", (plan_id,))
        with self.db.tx() as c:
            self._log(c, plan_id, (p or {}).get("patient_id"), old, new, reason, login, name, auto, credit)
        return True

    def status_of(self, plan_id):
        r = self.db.one("SELECT kind, plan_status FROM invoices WHERE id=?", (str(plan_id or ""),))
        return (r["plan_status"] or PROPOSED) if r and r["kind"] == "plan" else None

    def set_status(self, plan_id, new, reason="", login="", name="", auto=False, credit="") -> dict:
        p = self.db.one("SELECT id, patient_id, kind, plan_status FROM invoices WHERE id=?", (str(plan_id or ""),))
        if not p or p["kind"] != "plan":
            raise ValueError("План не найден")
        new = str(new or "")
        if new not in KEYS:
            raise ValueError("Неизвестный статус плана")
        old = p["plan_status"] or PROPOSED
        if old == new:
            return {"changed": False, "status": new}
        with self.db.tx() as c:
            if auto:  # the program's own change: the mark «перенесено в Dentist Plus» stays
                c.execute("UPDATE invoices SET plan_status=? WHERE id=?", (new, p["id"]))
            else:
                c.execute("UPDATE invoices SET plan_status=?, transferred=0 WHERE id=?", (new, p["id"]))
            self._log(c, p["id"], p["patient_id"], old, new, reason, login, name, auto, credit)
        if new == LOST and self.crm is not None:
            try:
                self.crm.close_plan_tasks(p["id"], "Сделано", AUTO_NAME if auto else (name or login), rules=("plan",),
                                          note="План брошен — звонок в «CRM» → «Обзвон» → «Брошенные планы».")
            except Exception:  # noqa: BLE001 — a CRM without tables (bare tests)
                pass
        return {"changed": True, "status": new, "old": old}

    def history(self, plan_id) -> list:
        rows = self.db.q("SELECT * FROM plan_status_log WHERE plan_id=? ORDER BY at, rowid", (str(plan_id or ""),))
        names = self._names()
        for r in rows:
            r["old_label"], r["new_label"] = LABEL.get(r["old"], r["old"] or ""), LABEL.get(r["new"], r["new"])
            r["who"] = r["name"] or names.get(r["login"] or "", r["login"] or "")
            r["credit_name"] = names.get(r["credit"] or "", r["credit"] or "") if r["credit"] else ""
        return rows

    def _names(self):
        try:
            return {(r["login"] or "").lower(): r["name"] or r["login"] for r in self.db.q("SELECT login, name FROM users")}
        except Exception:  # noqa: BLE001
            return {}

    # ============================================================ the data --
    def _plans(self, statuses=None, only=None):
        sql = """SELECT i.id, i.patient_id, i.doctor_id, i.title, i.total, i.items, i.variants, i.variant, i.created_at,
                        COALESCE(i.plan_status,'Предварительный') AS st, p.name AS patient_name, p.phone, d.name AS doctor_name
                 FROM invoices i LEFT JOIN patients p ON p.id=i.patient_id LEFT JOIN doctors d ON d.id=i.doctor_id
                 WHERE i.kind='plan'"""
        args = []
        if statuses:
            sql += f" AND COALESCE(i.plan_status,'Предварительный') IN ({','.join('?' * len(statuses))})"
            args += list(statuses)
        if only:
            only = [str(x) for x in only]
            sql += f" AND i.id IN ({','.join('?' * len(only))})"
            args += only
        rows = self.db.q(sql, args)
        for r in rows:
            try:
                r["items"] = json.loads(r["items"] or "[]")
            except ValueError:
                r["items"] = []
            r["variants"] = plansm.norm_variants(r.get("variants"))
            r["variant"] = r.get("variant") or ""
        return rows

    def _changes(self):
        """{plan: {'last': row, 'manual': at of the last manual change, 'seen': statuses it had}}."""
        out = {}
        for r in self.db.q("SELECT plan_id, old, new, auto, at, login, credit, reason FROM plan_status_log ORDER BY at, rowid"):
            x = out.setdefault(r["plan_id"], {"last": None, "manual": "", "seen": set()})
            x["last"] = r
            x["seen"].update({r["old"], r["new"]})
            if not r["auto"]:
                x["manual"] = r["at"]
        return out

    def _billed(self):
        out = {}
        for r in self.db.q("""SELECT plan_id, items, total, created_at FROM invoices
                              WHERE plan_id IS NOT NULL AND COALESCE(kind,'invoice')='invoice'"""):
            x = out.setdefault(r["plan_id"], {"n": 0, "sum": 0.0, "last": "", "keys": Counter()})
            x["n"] += 1
            x["sum"] += r["total"] or 0
            x["last"] = max(x["last"], r["created_at"] or "")
            try:
                for it in json.loads(r["items"] or "[]"):
                    x["keys"][_item_key(it)] += 1
            except ValueError:
                pass
        return out

    def _visits(self, patients):
        """{patient: {'last': last visit that took place (or still planned in the past), 'future': booked}}."""
        from crm import HIST
        pids = sorted({str(p) for p in patients if p})
        out = {}
        if not pids:
            return out
        now = _now()
        for i in range(0, len(pids), 500):
            part = pids[i:i + 500]
            for v in self.db.q(f"SELECT patient_id, start, status FROM ({HIST}) WHERE patient_id IN ({','.join('?' * len(part))})", part):
                if status_kind(v["status"]) in ("cancel", "noshow") or not v["start"]:
                    continue
                x = out.setdefault(str(v["patient_id"]), {"last": "", "future": ""})
                if v["start"] >= now:
                    x["future"] = min(x["future"] or v["start"], v["start"])
                else:
                    x["last"] = max(x["last"], v["start"])
        return out

    def _dp_services(self, patients):
        """{patient: [(start, {service ids})]} — finished Dentist Plus visits of the last DP_DAYS days with known services."""
        if self.sauto is None or not patients:
            return {}
        out = {}
        try:
            a, b = (date.today() - timedelta(days=DP_DAYS)).isoformat(), date.today().isoformat()
            for r in self.sauto._rows(a, b):
                pid = str(r.get("patient_id") or "")
                if pid in patients:
                    ids = {s["service_id"] for s in r.get("services") or [] if s.get("service_id")}
                    if ids:
                        out.setdefault(pid, []).append((str(r.get("start") or ""), ids, r.get("services") or []))
        except Exception:  # noqa: BLE001 — the visits must never stop the statuses
            return {}
        return out

    @staticmethod
    def _need(p):
        """The items that may be billed (the chosen option and the common ones) as a Counter of keys."""
        idx = plansm.billable(p["items"], p["variants"], p["variant"])
        return Counter(_item_key(p["items"][i]) for i in idx)

    # ============================================================ the rules --
    def tick(self, force=False) -> dict:
        if not force and time.time() - self._tick_at < TICK_SECONDS:
            return {}
        self._tick_at = time.time()
        try:
            return self.evaluate()
        except Exception:  # noqa: BLE001 — called from status(): must never break it
            import logging
            logging.getLogger("app").exception("plan statuses")
            return {}

    def evaluate(self, only=None) -> dict:
        """Apply the automatic rules to the plans (all or `only`). Returns {new status: count}."""
        s = self.settings()
        if not s["on"]:
            return {}
        cand = self._plans((PROPOSED, SOLD, WORK, LOST), only)
        if not cand:
            return {}
        ch, billed = self._changes(), self._billed()
        pats = {str(p["patient_id"]) for p in cand if p["patient_id"]}
        vis = self._visits(pats)
        dp = self._dp_services(pats) if s["visit_auto"] else {}
        today = date.today()
        done = Counter()
        lines = []
        for p in cand:
            x = ch.get(p["id"]) or {"last": None, "manual": "", "seen": set()}
            last = x["last"]
            created = p["created_at"] or ""
            since = max(created, last["at"] if last else "")       # the last change of any kind
            guard = max(created, x["manual"])                      # the last change made by a person
            b = billed.get(p["id"]) or {"n": 0, "sum": 0.0, "last": "", "keys": Counter()}
            v = vis.get(str(p["patient_id"])) or {"last": "", "future": ""}
            need = self._need(p)
            keys = {k[0] for k in need}
            hits = [(st, svc) for st, ids, svc in dp.get(str(p["patient_id"]), []) if ids & keys]
            st = p["st"]
            new, reason, credit = None, "", ""
            if st in (PROPOSED, SOLD):
                hit = next(((h, svc) for h, svc in sorted(hits, key=lambda z: z[0]) if h > guard), None)
                if b["last"] and b["last"] >= guard:
                    new, reason = WORK, "счёт по плану"
                elif hit:
                    names = ", ".join(sv["title"] for sv in hit[1] if sv.get("service_id") in keys)[:120]
                    new, reason = WORK, f"приём в Dentist Plus {_fmt(hit[0])}: {names}"
            if new is None and st == WORK and s["done_auto"] and need and b["n"] and b["last"] >= guard \
                    and not (p["variants"] and not p["variant"]) and all(b["keys"][k] >= n for k, n in need.items()):
                new, reason = DONE, "все услуги плана выставлены в счета"
            if new is None and st == LOST:
                auto_lost = last is None or bool(last["auto"])
                hit = next((h for h, _ in sorted(hits, key=lambda z: z[0]) if h > since), None)
                why = ("счёт по плану" if b["last"] > since else f"приём в Dentist Plus {_fmt(hit)}" if hit else
                       f"визит {_fmt(v['last'])}" if v["last"] > since else
                       f"запись на {_fmt(v['future'])}" if v["future"] and auto_lost else "")
                if why:
                    started = b["n"] or hit or WORK in x["seen"]
                    back = WORK if started else (last["old"] if last and last["old"] in (PROPOSED, SOLD) else SOLD)
                    new, reason, credit = back, "снова в работе: " + why, self._credit(p["id"], since)
            if new is None and st in OPEN_ST:
                days = s["days"] if st in (SOLD, WORK) else s["proposed_days"]
                act = max(since, b["last"], v["last"])
                if days and not v["future"] and act and act[:10] <= (today - timedelta(days=days)).isoformat():
                    idle = (today - date.fromisoformat(act[:10])).days
                    new, reason = LOST, f"нет визитов, счетов и записи {idle} дн. (с {_fmt(act)})"
            if new and new != st:
                self.set_status(p["id"], new, reason, auto=True, credit=credit)
                done[new] += 1
                lines.append(f"{p['patient_name'] or 'пациент'}: «{p['title'] or 'План лечения'}» — {LABEL.get(st, st)} → {LABEL[new]}")
        if done:
            self._journal(", ".join(f"{LABEL[k].lower()}: {n}" for k, n in done.items()) + ". " + "; ".join(lines[:8])
                          + (f"; и ещё {len(lines) - 8}" if len(lines) > 8 else ""))
        return dict(done)

    def _credit(self, plan_id, since):
        """Login of who called about the plan before it came back (within CREDIT_DAYS), for the motivation."""
        border = max(str(since or ""), (datetime.now() - timedelta(days=CREDIT_DAYS)).strftime("%Y-%m-%d %H:%M:%S"))
        try:
            r = self.db.one("""SELECT login FROM marketing_calls WHERE plan_id=? AND at >= ? AND COALESCE(login,'')<>''
                               AND result IN ('Записался','Дозвонились','Перезвонить') ORDER BY at DESC, id DESC LIMIT 1""",
                            (str(plan_id), border))
        except Exception:  # noqa: BLE001
            r = None
        return (r or {}).get("login") or ""

    def _journal(self, detail):
        try:
            with self.db.tx() as c:
                c.execute("INSERT INTO audit(at, user_id, user_name, action, detail, ip) VALUES(?,?,?,?,?,?)",
                          (_now(), None, AUTO_NAME, "Статусы планов лечения (автоматически)", detail[:500], ""))
        except Exception:  # noqa: BLE001 — no journal in a bare database
            pass

    # ============================================================ call list --
    def _scope_sql(self, doctor_id):
        return (" AND i.doctor_id=?", [str(doctor_id)]) if doctor_id else ("", [])

    def calls(self, f=None) -> dict:
        """Abandoned plans to call about: who, why, the money, the last visit, the last call and when to call back."""
        f = f if isinstance(f, dict) else {}
        if f.get("refresh"):
            self.tick(force=True)
        s = self.settings()
        months = s["call_months"] if f.get("months") in (None, "") else min(120, max(0, int(f.get("months") or 0)))
        rows = self._plans((LOST,))
        if f.get("doctor_id"):
            rows = [r for r in rows if str(r["doctor_id"] or "") == str(f["doctor_id"])]
        skip = {r["patient_id"] for r in self.db.q("SELECT patient_id FROM patient_marketing WHERE no_calls=1")}
        ch, billed = self._changes(), self._billed()
        vis = self._visits({str(r["patient_id"]) for r in rows})
        today = date.today().isoformat()
        border = (date.today() - timedelta(days=int(months * 30.4))).isoformat() if months else ""
        calls = {}
        if rows:
            for c in self.db.q("SELECT * FROM marketing_calls WHERE plan_id IS NOT NULL ORDER BY at, id"):
                calls.setdefault(c["plan_id"], []).append(c)
        out = []
        for p in rows:
            if p["patient_id"] in skip:
                continue
            x = ch.get(p["id"]) or {"last": None}
            last = x["last"]
            lost_at = last["at"] if last and last["new"] == LOST else ""
            b = billed.get(p["id"]) or {"n": 0, "sum": 0.0, "last": ""}
            v = vis.get(str(p["patient_id"])) or {"last": "", "future": ""}
            act = max(p["created_at"] or "", b["last"], v["last"])
            if border and act[:10] < border:
                continue
            mine = [c for c in calls.get(p["id"], []) if c["at"] >= (lost_at or "")]
            lc = mine[-1] if mine else None
            due = True
            next_call = ""
            if lc:
                if lc["result"] == "Перезвонить":
                    next_call = lc["call_on"] or ""
                    due = not next_call or next_call <= today
                elif lc["result"] == "Не дозвонились":
                    due = lc["at"][:10] < today
                elif lc["result"] == "Дозвонились":
                    due = lc["at"][:10] <= (date.today() - timedelta(days=14)).isoformat()
                elif lc["result"] == "Записался":
                    due = False
            if v["future"]:
                due = False
            left = max(0.0, (p["total"] or 0) - b["sum"])
            reason = (last["reason"] if last and last["new"] == LOST else "") or ""
            out.append({"plan_id": p["id"], "patient_id": p["patient_id"], "name": p["patient_name"], "phone": p["phone"],
                        "title": p["title"] or "План лечения", "doctor_id": p["doctor_id"], "doctor_name": p["doctor_name"] or "",
                        "total": _r(p["total"]), "billed": _r(b["sum"]), "left": _r(left), "created_at": p["created_at"],
                        "last_visit": v["last"], "future": v["future"], "lost_at": lost_at, "reason": reason,
                        "idle": (date.today() - date.fromisoformat(act[:10])).days if act else None,
                        "manual": bool(last and last["new"] == LOST and not last["auto"]),
                        "calls": len(mine), "due": due, "next_call": next_call,
                        "last_call": {"result": lc["result"], "at": lc["at"], "user_name": lc["user_name"], "comment": lc["comment"],
                                      "call_on": lc["call_on"]} if lc else None,
                        "info": f"{p['title'] or 'План лечения'}: осталось на {_rub(left)}"
                                + (f" · {p['doctor_name']}" if p["doctor_name"] else "")
                                + (f" · последний визит {_fmt(v['last'])}" if v["last"] else "")})
        if f.get("due_only"):
            out = [r for r in out if r["due"]]
        out.sort(key=lambda r: (not r["due"], r["next_call"] or "", -r["left"]))
        return {"rows": out, "results": [{"key": k, "label": t} for k, t in CALL_RESULTS], "reasons": REFUSE_REASONS,
                "settings": s, "months": months, "due": sum(1 for r in out if r["due"]), "sum_left": _r(sum(r["left"] for r in out)),
                "doctors": self.db.doctors()}

    def due_count(self) -> int:
        """Abandoned plans to call about today (the badge of the list), cached for a minute: status() asks often."""
        at, n = getattr(self, "_due_cache", (0.0, 0))
        if time.time() - at < 60:
            return n
        try:
            n = self.calls({"due_only": True})["due"]
        except Exception:  # noqa: BLE001
            n = 0
        self._due_cache = (time.time(), n)
        return n

    def call(self, f, login="", name="") -> dict:
        """The result of a call about an abandoned plan."""
        f = f if isinstance(f, dict) else {}
        p = self.db.one("SELECT id, patient_id, kind, plan_status, title FROM invoices WHERE id=?", (str(f.get("plan_id") or ""),))
        if not p or p["kind"] != "plan":
            raise ValueError("План не найден")
        key = str(f.get("result") or "")
        if key not in CALL_LABEL:
            key = next((k for k, t in CALL_RESULTS if t == key), "")
        if not key:
            raise ValueError("Выберите результат звонка")
        comment = str(f.get("comment") or "").strip()[:300]
        call_on = None
        if key == "callback":
            try:
                call_on = date.fromisoformat(str(f.get("call_on") or "")[:10])
            except ValueError:
                raise ValueError("Укажите, когда перезвонить") from None
            if call_on < date.today():
                raise ValueError("Перезвонить можно сегодня или позже")
            call_on = call_on.isoformat()
        reason = str(f.get("reason") or "").strip()[:100]
        if key == "refused" and not reason:
            raise ValueError("Укажите причину отказа")
        text = "; ".join(x for x in (f"причина: {reason}" if key == "refused" else "",
                                     f"перезвонить {_fmt(call_on)}" if call_on else "", comment) if x)
        self.mk.log_call({"patient_id": p["patient_id"], "list": "abandoned", "result": CALL_LABEL[key], "comment": text,
                          "plan_id": p["id"], "call_on": call_on, "no_calls": bool(f.get("no_calls"))}, name, login)
        if self.crm is not None:
            if key == "callback":
                self.crm.plan_task(p["id"], p["patient_id"], call_on, login,
                                   f"«{p['title'] or 'План лечения'}»" + (f". {comment}" if comment else ""))
            elif key == "no_answer":
                self.crm.plan_task_later(p["id"])
            else:
                self.crm.close_plan_tasks(p["id"], {"reached": "Дозвонились", "refused": "Отказ", "booked": "Записался"}[key],
                                          name or login, rules=("plan", "plan_call"))
        self._due_cache = (0.0, 0)
        out = {"ok": True, "status": p["plan_status"] or PROPOSED}
        if key == "refused":
            out.update(self.set_status(p["id"], REFUSED, f"отказ по звонку: {reason}" + (f" ({comment})" if comment else ""),
                                       login, name))
        elif key == "booked":
            self.evaluate([p["id"]])  # back to work at once when the visit is already in the schedule
            st = self.status_of(p["id"])
            v = self._visits({str(p["patient_id"])}).get(str(p["patient_id"])) or {}
            if st == LOST and v.get("future"):  # abandoned by hand: the booking brings it back too
                ch = self._changes().get(p["id"]) or {"seen": set(), "last": None}
                back = WORK if (self._billed().get(p["id"]) or WORK in ch["seen"]) else SOLD
                self.set_status(p["id"], back, f"снова в работе: запись на {_fmt(v['future'])}", login, name, credit=login)
            out["status"] = self.status_of(p["id"])
        return out

    def after_task(self, task, result, login="", name=""):
        """A CRM task «перезвонить по брошенному плану» was closed on the tasks screen."""
        if not task or task.get("rule") != "plan_call" or not task.get("plan_id"):
            return
        if result == "Отказ" and self.status_of(task["plan_id"]) == LOST:
            self.set_status(task["plan_id"], REFUSED, "отказ по звонку (задача CRM)", login, name)
        elif result == "Записался":
            self.evaluate([task["plan_id"]])

    # ============================================================ reports --
    def report(self, date_from=None, date_to=None, doctor_id=None, status=None) -> dict:
        """Plans made in the period: by status and doctor, conversion «предложен → продан → в работе → завершён», brought back
        from «брошен»; the money left in abandoned plans now (any date)."""
        a, b = _period(date_from, date_to)
        allp = self._plans()
        if doctor_id:
            allp = [p for p in allp if str(p["doctor_id"] or "") == str(doctor_id)]
        ch, billed = self._changes(), self._billed()
        names = {d["id"]: d["name"] for d in self.db.doctors()}

        def reached(p):
            seen = set((ch.get(p["id"]) or {}).get("seen") or set()) | {p["st"]}
            bl = billed.get(p["id"])
            started = WORK in seen or DONE in seen or bool(bl)
            sold = started or SOLD in seen
            return sold, started, p["st"] == DONE or DONE in seen

        period = [p for p in allp if a <= (p["created_at"] or "")[:10] < b]
        by_status = {k: {"key": k, "label": t, "n": 0, "sum": 0.0} for k, t in STATUSES}
        docs = {}
        fun = {"proposed": 0, "sold": 0, "started": 0, "done": 0, "lost": 0, "refused": 0,
               "sum": 0.0, "sum_sold": 0.0, "billed": 0.0}
        for p in period:
            st = p["st"] if p["st"] in by_status else PROPOSED
            by_status[st]["n"] += 1
            by_status[st]["sum"] += p["total"] or 0
            sold, started, fin = reached(p)
            bl = (billed.get(p["id"]) or {}).get("sum", 0.0)
            did = p["doctor_id"] or ""
            x = docs.setdefault(did, {"doctor_id": did, "name": names.get(did) or p["doctor_name"] or "Без врача", "n": 0, "sum": 0.0,
                                      "sold": 0, "started": 0, "done": 0, "lost": 0, "refused": 0, "sum_sold": 0.0, "billed": 0.0,
                                      "lost_left": 0.0, **{k: 0 for k in KEYS}})
            for y in (x, fun):
                y["sum"] += p["total"] or 0
                y["sold"] += sold
                y["started"] += started
                y["done"] += fin
                y["lost"] += st == LOST
                y["refused"] += st == REFUSED
                y["sum_sold"] += (p["total"] or 0) if sold else 0
                y["billed"] += bl
            x["n"] += 1
            x[st] += 1
            if st == LOST:
                x["lost_left"] += max(0.0, (p["total"] or 0) - bl)
            fun["proposed"] += 1
        rows = []
        for x in docs.values():
            rows.append({**x, "sum": _r(x["sum"]), "sum_sold": _r(x["sum_sold"]), "billed": _r(x["billed"]), "lost_left": _r(x["lost_left"]),
                         "sold_rate": _pct(x["sold"], x["n"]), "start_rate": _pct(x["started"], x["n"]),
                         "done_rate": _pct(x["done"], x["n"]), "lost_rate": _pct(x["lost"], x["n"])})
        rows.sort(key=lambda r: -r["sum"])
        fun.update(sum=_r(fun["sum"]), sum_sold=_r(fun["sum_sold"]), billed=_r(fun["billed"]),
                   sold_rate=_pct(fun["sold"], fun["proposed"]), start_rate=_pct(fun["started"], fun["proposed"]),
                   done_rate=_pct(fun["done"], fun["proposed"]), lost_rate=_pct(fun["lost"], fun["proposed"]))
        # abandoned now, whenever the plan was made
        lost = []
        for p in allp:
            if p["st"] != LOST:
                continue
            bl = (billed.get(p["id"]) or {}).get("sum", 0.0)
            lost.append({"doctor_id": p["doctor_id"], "left": max(0.0, (p["total"] or 0) - bl)})
        lost_by = {}
        for x in lost:
            y = lost_by.setdefault(x["doctor_id"] or "", {"doctor_id": x["doctor_id"] or "", "name": names.get(x["doctor_id"]) or "Без врача",
                                                          "n": 0, "left": 0.0})
            y["n"] += 1
            y["left"] += x["left"]
        # brought back from «брошен» in the period
        back = self.db.q("""SELECT l.plan_id, l.credit, l.at, i.total, i.doctor_id FROM plan_status_log l JOIN invoices i ON i.id=l.plan_id
                            WHERE l.old=? AND l.new NOT IN (?, ?) AND l.at >= ? AND l.at < ?""", (LOST, LOST, REFUSED, a, b))
        if doctor_id:
            back = [r for r in back if str(r["doctor_id"] or "") == str(doctor_id)]
        staff = self._names()
        credit = Counter(r["credit"] for r in back if r["credit"])
        listed = [p for p in period if not status or p["st"] == status]
        listed.sort(key=lambda p: p["created_at"] or "", reverse=True)
        return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(), "settings": self.settings(),
                "by_status": [{**x, "sum": _r(x["sum"])} for x in by_status.values()], "by_doctor": rows, "funnel": fun,
                "lost_now": {"n": len(lost), "left": _r(sum(x["left"] for x in lost)),
                             "by_doctor": sorted(({**y, "left": _r(y["left"])} for y in lost_by.values()), key=lambda y: -y["left"])},
                "back": {"n": len(back), "sum": _r(sum(r["total"] or 0 for r in back)),
                         "by_staff": [{"login": k, "name": staff.get(k, k), "n": n} for k, n in credit.most_common()]},
                "plans": [{"id": p["id"], "patient_id": p["patient_id"], "patient_name": p["patient_name"], "title": p["title"] or "План лечения",
                           "doctor_name": p["doctor_name"] or "", "created_at": p["created_at"], "status": p["st"],
                           "label": LABEL.get(p["st"], p["st"]), "total": _r(p["total"]),
                           "billed": _r((billed.get(p["id"]) or {}).get("sum", 0.0))} for p in listed[:500]],
                "statuses": [{"key": k, "label": t} for k, t in STATUSES], "doctors": self.db.doctors()}


def abandoned_summary(db) -> dict:
    """{'n', 'left'} — abandoned plans now and the money left in them (the director's hint)."""
    r = db.one("""SELECT COUNT(*) AS n, COALESCE(SUM(MAX(0, i.total - COALESCE((SELECT SUM(j.total) FROM invoices j
                  WHERE j.plan_id=i.id AND COALESCE(j.kind,'invoice')='invoice'),0))),0) AS s
                  FROM invoices i WHERE i.kind='plan' AND i.plan_status=?""", (LOST,))
    return {"n": r["n"] if r else 0, "left": _r(r["s"]) if r else 0.0}
