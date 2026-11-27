"""3.10 «Склад — медсестра»: requests for materials, consumption and write-offs waiting for approval, the stock's home screen.

* Requests (`stock_requests`): a nurse asks for materials for her cabinet (need date, priority, comment). The storekeeper
  issues them with «Выдать в кабинет» (a transfer, stock.py) and the request becomes «выдана» or «выдана частично»; or he
  rejects it with a reason. A request may be kept as a draft first.
* Approval (`stock_approvals`): consumption in treatment («Зафиксировать расход») or a write-off (a broken ampoule, an
  expired lot) by someone without «Склад: приход, списание» or «Склад: согласование» does not touch the stock: it waits for
  a manager or the director, who approves it (the write-off is made then, with the balances of that moment) or rejects it
  with a reason. The rule is enforced in Api, so a nurse cannot write off through the API either (`stock_write_off` needs
  «Склад: приход, списание»).
* Between computers: both tables are replicated. An approved request is written off as the document `A-<id>` whose moves
  have fixed ids, so two managers approving the same request on two laptops while the network is down end up with one
  write-off after syncing.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_requests(
    id TEXT PRIMARY KEY, number TEXT, location_id TEXT, need_date TEXT, priority TEXT, comment TEXT, lines TEXT, issued TEXT,
    status TEXT, created_by TEXT, created_name TEXT, created_at TEXT, sent_at TEXT, updated_at TEXT,
    decided_by TEXT, decided_name TEXT, decided_at TEXT, answer TEXT, doc_ids TEXT);
CREATE INDEX IF NOT EXISTS ix_sreq_status ON stock_requests(status);
CREATE TABLE IF NOT EXISTS stock_approvals(
    id TEXT PRIMARY KEY, kind TEXT, status TEXT, payload TEXT, total REAL DEFAULT 0, location_id TEXT, patient_id TEXT,
    summary TEXT, created_by TEXT, created_name TEXT, created_at TEXT, sent_at TEXT, updated_at TEXT,
    decided_by TEXT, decided_name TEXT, decided_at TEXT, answer TEXT, doc_id TEXT);
CREATE INDEX IF NOT EXISTS ix_sappr_status ON stock_approvals(status);
"""

PRIORITY = {"normal": "Обычный", "urgent": "Срочный", "critical": "Критический"}
REQ_STATUS = {"draft": "Черновик", "new": "Новая", "accepted": "Принята", "partial": "Выдана частично", "done": "Выдана", "rejected": "Отклонена",
              "cancelled": "Отменена"}
USE_KIND = {"consume": "Расход в лечении", "writeoff": "Списание"}
APPR_STATUS = {"draft": "Черновик", "pending": "На согласовании", "approved": "Согласовано", "rejected": "Отклонено",
               "cancelled": "Отменено", "done": "Списано"}
OPEN = ("new", "accepted", "partial")   # requests still to be issued (3.13: «Принята» — the manager took it into work)
CONSUME_REASON = "Расход в лечении"
STAT_DAYS = (7, 30, 90, 365)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clean(v, n=300):
    return str(v or "").strip()[:n]


def _loads(v, default):
    try:
        x = json.loads(v) if v else default
        return x if isinstance(x, type(default)) else default
    except (TypeError, ValueError):
        return default


class StockFlow:
    def __init__(self, db, stock, files=None):
        self.db, self.stock, self.files = db, stock, files
        with db._lock:
            db.conn.executescript(SCHEMA)
            have = {r[1] for r in db.conn.execute("PRAGMA table_info(stock_requests)")}
            for col in ("accepted_by TEXT", "accepted_name TEXT", "accepted_at TEXT"):  # 3.13: who took the request into work
                if col.split()[0] not in have:
                    db.conn.execute(f"ALTER TABLE stock_requests ADD COLUMN {col}")
            db.conn.commit()

    # ------------------------------------------------------------ helpers --
    def _mats(self):
        return {r["id"]: r for r in self.db.q("SELECT id, name, unit, price, code, photo_id, active FROM materials")}

    def _lines(self, lines, need_positive=True):
        """[{material_id, qty}] → the same lines checked, one per material (quantities of repeats added up)."""
        mats, out = self._mats(), {}
        for ln in lines or []:
            mid = str((ln or {}).get("material_id") or "")
            if not mid:
                continue
            if mid not in mats:
                raise ValueError("В списке есть материал, которого нет в справочнике")
            q = self.stock_num(ln.get("qty"))
            if q <= 0:
                if need_positive:
                    raise ValueError(f"«{mats[mid]['name']}»: укажите количество больше нуля")
                continue
            out[mid] = round(out.get(mid, 0) + q, 3)
        if not out:
            raise ValueError("Добавьте хотя бы один материал")
        return [{"material_id": k, "qty": v} for k, v in out.items()]

    @staticmethod
    def stock_num(v):
        import stock
        return stock._num(v)

    def _place(self, lid):
        return self.stock._loc(lid) or ""

    def _decorate_lines(self, lines, mats=None, place=None):
        mats = mats or self._mats()
        bal = self.stock.location_balances() if place is not None else {}
        out = []
        for ln in lines or []:
            m = mats.get(ln.get("material_id")) or {}
            row = {**ln, "name": m.get("name") or "удалённый материал", "unit": m.get("unit") or "", "code": m.get("code") or "",
                   "photo_id": m.get("photo_id") or "", "price": m.get("price") or 0}
            if place is not None:
                row["balance"] = round(bal.get(ln.get("material_id"), {}).get(place or "", 0), 3)
            out.append(row)
        return out

    # ============================================================ requests --
    def _req_row(self, r, mats=None, names=None):
        names = names or self.stock._loc_names()
        lines = _loads(r.get("lines"), [])
        issued = _loads(r.get("issued"), {})
        r = dict(r)
        r["lines"] = self._decorate_lines(lines, mats)
        for ln in r["lines"]:
            ln["issued"] = round(float(issued.get(ln["material_id"], 0) or 0), 3)
        r["issued"] = issued
        r["doc_ids"] = _loads(r.get("doc_ids"), [])
        r["status_title"] = REQ_STATUS.get(r["status"], r["status"])
        r["priority_title"] = PRIORITY.get(r["priority"], PRIORITY["normal"])
        r["location_name"] = names.get(r.get("location_id") or "", names.get("", ""))
        r["positions"] = len(lines)
        return r

    def requests(self, status=None, mine_login=None, limit=200):
        """Requests, the open ones first. `status`: 'open' (new + partial), one status, or all; `mine_login` — only one's own."""
        sql, args = "SELECT * FROM stock_requests WHERE 1=1", []
        if status == "open":
            sql += " AND status IN ('new','accepted','partial')"
        elif status:
            sql += " AND status=?"
            args.append(status)
        if mine_login is not None:
            sql += " AND created_by=?"
            args.append(mine_login)
        else:
            sql += " AND status<>'draft'"  # someone else's draft is not a request yet
        sql += """ ORDER BY CASE status WHEN 'new' THEN 0 WHEN 'accepted' THEN 1 WHEN 'partial' THEN 2 WHEN 'draft' THEN 3 ELSE 4 END,
                   CASE priority WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 ELSE 2 END, COALESCE(sent_at, created_at) DESC LIMIT ?"""
        mats, names = self._mats(), self.stock._loc_names()
        return [self._req_row(r, mats, names) for r in self.db.q(sql, (*args, int(limit)))]

    def request(self, rid):
        r = self.db.one("SELECT * FROM stock_requests WHERE id=?", (str(rid or ""),))
        if not r:
            raise ValueError("Заявка не найдена")
        out = self._req_row(r)
        bal = self.stock.location_balances()
        for ln in out["lines"]:  # what the main stock and the cabinet have now — for whoever issues it
            by = bal.get(ln["material_id"], {})
            ln["at_main"] = round(by.get("", 0), 3)
            ln["at_place"] = round(by.get(out.get("location_id") or "", 0), 3)
        return out

    def save_request(self, f, login="", name="", may_edit_any=False):
        """A new request or a change of one's own draft. `send` — off it goes («Новая»), else it stays a draft."""
        f = f if isinstance(f, dict) else {}
        rid = str(f.get("id") or "")
        old = self.db.one("SELECT * FROM stock_requests WHERE id=?", (rid,)) if rid else None
        if rid and not old:
            raise ValueError("Заявка не найдена")
        if old and old["status"] != "draft":
            raise ValueError("Заявка уже отправлена — её нельзя изменить. Отмените её и создайте новую")
        if old and old["created_by"] != login and not may_edit_any:
            raise ValueError("Это черновик другого сотрудника")
        loc = self._place(f.get("location_id"))
        lines = self._lines(f.get("lines"))
        need = ""
        if f.get("need_date"):
            import stock
            need = stock._day(f.get("need_date"), "Дата потребности")
        pr = f.get("priority") if f.get("priority") in PRIORITY else "normal"
        send = bool(f.get("send"))
        now = _now()
        rid = rid or "RQ-" + uuid.uuid4().hex[:10]
        with self.db.tx() as c:
            number = old["number"] if old and old["number"] else ""
            if send and not number:
                n = c.execute("SELECT COUNT(*) FROM stock_requests WHERE COALESCE(number,'')<>''").fetchone()[0]
                number = str(n + 1)
            if old:
                c.execute("""UPDATE stock_requests SET number=?, location_id=?, need_date=?, priority=?, comment=?, lines=?, status=?,
                             sent_at=?, updated_at=? WHERE id=?""",
                          (number, loc, need, pr, _clean(f.get("comment"), 500), json.dumps(lines), "new" if send else "draft",
                           now if send else None, now, rid))
            else:
                c.execute("""INSERT INTO stock_requests(id, number, location_id, need_date, priority, comment, lines, issued, status,
                             created_by, created_name, created_at, sent_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (rid, number, loc, need, pr, _clean(f.get("comment"), 500), json.dumps(lines), "{}",
                           "new" if send else "draft", login, name, now, now if send else None, now))
        return self.request(rid)

    def cancel_request(self, rid, login="", may_any=False):
        r = self.db.one("SELECT * FROM stock_requests WHERE id=?", (str(rid or ""),))
        if not r:
            raise ValueError("Заявка не найдена")
        if r["created_by"] != login and not may_any:
            raise ValueError("Отменить можно только свою заявку")
        if r["status"] not in (("draft", "new", "accepted") if may_any else ("draft", "new")):
            raise ValueError(f"Заявка уже {REQ_STATUS.get(r['status'], r['status']).lower()} — отменить её нельзя"
                             + (". Попросите менеджера склада" if r["status"] == "accepted" else ""))
        with self.db.tx() as c:
            c.execute("UPDATE stock_requests SET status='cancelled', updated_at=? WHERE id=?", (_now(), r["id"]))
        return self.request(r["id"])

    def reject_request(self, rid, answer, login="", name=""):
        r = self.db.one("SELECT * FROM stock_requests WHERE id=?", (str(rid or ""),))
        if not r:
            raise ValueError("Заявка не найдена")
        if r["status"] not in OPEN:
            raise ValueError("Отклонить можно только заявку, которая ещё не выдана")
        answer = _clean(answer, 300)
        if not answer:
            raise ValueError("Напишите причину — медсестра увидит её в своих заявках")
        with self.db.tx() as c:
            c.execute("""UPDATE stock_requests SET status='rejected', decided_by=?, decided_name=?, decided_at=?, answer=?, updated_at=?
                         WHERE id=?""", (login, name, _now(), answer, _now(), r["id"]))
        return self.request(r["id"])

    def accept_request(self, rid, login="", name=""):
        """3.13 «Принята»: the stock manager took a new request into work — the nurse sees it, and it can no longer be cancelled
        by her alone. Issuing it later («Выдать в кабинет») makes it «выдана» as before."""
        r = self.db.one("SELECT * FROM stock_requests WHERE id=?", (str(rid or ""),))
        if not r:
            raise ValueError("Заявка не найдена")
        if r["status"] == "accepted":
            return self.request(r["id"])
        if r["status"] != "new":
            raise ValueError(f"Заявка уже {REQ_STATUS.get(r['status'], r['status']).lower()} — принять её нельзя")
        now = _now()
        with self.db.tx() as c:
            c.execute("""UPDATE stock_requests SET status='accepted', accepted_by=?, accepted_name=?, accepted_at=?, updated_at=?
                         WHERE id=? AND status='new'""", (login, name, now, now, r["id"]))
        return self.request(r["id"])

    def issued(self, request_ids, doc_id, lines):
        """After «Выдать в кабинет»: what was issued is counted against the requests (in their order) — «выдана» when all is."""
        left = {}
        for ln in lines or []:
            mid = str(ln.get("material_id") or "")
            if mid:
                left[mid] = left.get(mid, 0) + self.stock_num(ln.get("qty"))
        out = []
        for rid in list(dict.fromkeys(str(x) for x in request_ids or [] if x)):
            r = self.db.one("SELECT * FROM stock_requests WHERE id=?", (rid,))
            if not r or r["status"] not in OPEN:
                continue
            issued, docs = _loads(r["issued"], {}), _loads(r["doc_ids"], [])
            for ln in _loads(r["lines"], []):
                mid = ln["material_id"]
                want = max(0.0, float(ln["qty"]) - float(issued.get(mid, 0) or 0))
                give = min(want, left.get(mid, 0))
                if give > 0:
                    issued[mid] = round(float(issued.get(mid, 0) or 0) + give, 3)
                    left[mid] = round(left[mid] - give, 3)
            full = all(float(issued.get(ln["material_id"], 0) or 0) + 1e-9 >= float(ln["qty"]) for ln in _loads(r["lines"], []))
            some = any(float(v or 0) > 0 for v in issued.values())
            status = "done" if full else "partial" if some else r["status"]
            with self.db.tx() as c:
                c.execute("UPDATE stock_requests SET issued=?, doc_ids=?, status=?, updated_at=? WHERE id=?",
                          (json.dumps(issued), json.dumps(docs + [doc_id]), status, _now(), rid))
            out.append({"id": rid, "status": status})
        return out

    # ============================================= consumption and approval --
    def _use_form(self, f):
        """The checked form of «Зафиксировать расход» / «Списать»: what stock.write_off gets."""
        kind = f.get("kind") if f.get("kind") in USE_KIND else "consume"
        lines = self._lines(f.get("lines"))
        loc = self._place(f.get("location_id"))
        day = str(f.get("date") or "")[:10] or date.today().isoformat()
        import stock
        day = stock._day(day, "Дата")
        tm = _clean(f.get("time"), 5)
        pid = _clean(f.get("patient_id"), 60)
        pname = ""
        if pid:
            p = self.db.one("SELECT name FROM patients WHERE id=?", (pid,))
            if not p:
                raise ValueError("Пациент не найден")
            pname = p["name"] or ""
        sid = _clean(f.get("service_id"), 60)
        stitle = ""
        if sid:
            s = self.db.one("SELECT title, code FROM services WHERE id=?", (sid,))
            if not s:
                raise ValueError("Услуга не найдена")
            stitle = " ".join(x for x in (s["code"] or "", s["title"] or "") if x)
        if kind == "consume":
            reason = CONSUME_REASON + (f": {stitle}" if stitle else "")
        else:
            reason = _clean(f.get("reason"), 300)
            if not reason:
                raise ValueError("Укажите причину списания")
        return {"kind": kind, "date": day, "time": tm, "location_id": loc, "patient_id": pid, "patient_name": pname,
                "service_id": sid, "service_title": stitle, "reason": reason[:300], "comment": _clean(f.get("comment"), 500),
                "lines": lines}

    def _check_balances(self, form):
        names = self.stock._loc_names()
        for ln in form["lines"]:
            have = self.stock.location_balance(ln["material_id"], form["location_id"] or None)
            if ln["qty"] > have + 1e-9:
                m = self.db.one("SELECT name FROM materials WHERE id=?", (ln["material_id"],))
                raise ValueError(f"«{m['name']}»: в месте «{names.get(form['location_id'] or '', '')}» {have:g}, списать {ln['qty']:g} нельзя")

    def _summary(self, form):
        mats = self._mats()
        parts = [f"{(mats.get(ln['material_id']) or {}).get('name', '?')} — {ln['qty']:g}" for ln in form["lines"][:6]]
        more = len(form["lines"]) - 6
        return ("; ".join(parts) + (f" и ещё {more}" if more > 0 else ""))[:500]

    def _total(self, form):
        mats = self._mats()
        return round(sum(ln["qty"] * ((mats.get(ln["material_id"]) or {}).get("price") or 0) for ln in form["lines"]), 2)

    def _apply(self, form, who, did=None, uid=None):
        wf = {"reason": form["reason"], "comment": form["comment"], "date": form["date"], "time": form["time"],
              "location_id": form["location_id"], "patient_id": form["patient_id"],
              "lines": [{"material_id": ln["material_id"], "qty": ln["qty"]} for ln in form["lines"]]}
        return self.stock.write_off(wf, who, did=did, uid=uid)

    def use(self, f, direct, login="", name=""):
        """Consumption or a write-off. `direct` (the right to write off) — done at once; otherwise it waits for approval.
        A draft (`draft`) only remembers the form. Returns {status, id, doc_id}."""
        f = f if isinstance(f, dict) else {}
        aid = str(f.get("id") or "")
        old = self.db.one("SELECT * FROM stock_approvals WHERE id=?", (aid,)) if aid else None
        if aid and not old:
            raise ValueError("Черновик не найден")
        if old and (old["status"] != "draft" or old["created_by"] != login):
            raise ValueError("Этот расход уже отправлен — его нельзя изменить")
        form = self._use_form(f)
        draft = bool(f.get("draft"))
        if not draft:
            self._check_balances(form)
        aid = aid or "AP-" + uuid.uuid4().hex[:10]
        now = _now()
        status = "draft" if draft else ("done" if direct else "pending")
        doc_id = ""
        if status == "done":
            doc_id = self._apply(form, name or login, did=f"A-{aid}", uid=f"a-{aid}")
        with self.db.tx() as c:
            vals = (form["kind"], status, json.dumps(form, ensure_ascii=False), self._total(form), form["location_id"],
                    form["patient_id"], self._summary(form), now if status != "draft" else None, now, doc_id)
            if old:
                c.execute("""UPDATE stock_approvals SET kind=?, status=?, payload=?, total=?, location_id=?, patient_id=?, summary=?,
                             sent_at=?, updated_at=?, doc_id=? WHERE id=?""", (*vals, aid))
            else:
                c.execute("""INSERT INTO stock_approvals(kind, status, payload, total, location_id, patient_id, summary, sent_at, updated_at,
                             doc_id, id, created_by, created_name, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (*vals, aid, login, name, now))
            if status == "done":
                c.execute("UPDATE stock_approvals SET decided_by=?, decided_name=?, decided_at=? WHERE id=?", (login, name, now, aid))
        return {"status": status, "id": aid, "doc_id": doc_id, "item": self.approval(aid)}

    def _appr_row(self, r, names=None, mats=None):
        r = dict(r)
        form = _loads(r.get("payload"), {})
        names = names or self.stock._loc_names()
        r["form"] = {**form, "lines": self._decorate_lines(form.get("lines") or [], mats,
                                                        place=(form.get("location_id") or "") if r["status"] in ("draft", "pending") else None)}
        r.pop("payload", None)
        r["kind_title"] = USE_KIND.get(r["kind"], r["kind"])
        r["status_title"] = APPR_STATUS.get(r["status"], r["status"])
        r["location_name"] = names.get(r.get("location_id") or "", names.get("", ""))
        r["patient_name"] = form.get("patient_name") or ""
        r["service_title"] = form.get("service_title") or ""
        r["positions"] = len(form.get("lines") or [])
        return r

    def approvals(self, status=None, mine_login=None, limit=200):
        sql, args = "SELECT * FROM stock_approvals WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        if mine_login is not None:
            sql += " AND created_by=?"
            args.append(mine_login)
        else:
            sql += " AND status<>'draft'"
        sql += " ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, COALESCE(sent_at, created_at) DESC LIMIT ?"
        names, mats = self.stock._loc_names(), self._mats()
        return [self._appr_row(r, names, mats) for r in self.db.q(sql, (*args, int(limit)))]

    def approval(self, aid):
        r = self.db.one("SELECT * FROM stock_approvals WHERE id=?", (str(aid or ""),))
        if not r:
            raise ValueError("Запись не найдена")
        return self._appr_row(r)

    def decide(self, aid, action, answer="", login="", name=""):
        """A manager approves (the write-off is made now) or rejects (with a reason) what waits for approval."""
        r = self.db.one("SELECT * FROM stock_approvals WHERE id=?", (str(aid or ""),))
        if not r:
            raise ValueError("Запись не найдена")
        if r["status"] != "pending":
            raise ValueError(f"Уже {APPR_STATUS.get(r['status'], r['status']).lower()}")
        now = _now()
        if action == "reject":
            answer = _clean(answer, 300)
            if not answer:
                raise ValueError("Напишите причину отказа — сотрудник увидит её")
            with self.db.tx() as c:
                c.execute("""UPDATE stock_approvals SET status='rejected', decided_by=?, decided_name=?, decided_at=?, answer=?, updated_at=?
                             WHERE id=? AND status='pending'""", (login, name, now, answer, now, r["id"]))
            return self.approval(r["id"])
        if action != "approve":
            raise ValueError("Неизвестное действие")
        form = _loads(r["payload"], {})
        did = f"A-{r['id']}"
        if not self.db.one("SELECT 1 AS x FROM stock_docs WHERE id=?", (did,)):  # approved on another computer a moment ago
            self._check_balances(form)
            who = f"{r['created_name'] or r['created_by']} (согласовал(а) {name or login})"[:100]
            self._apply(form, who, did=did, uid=f"a-{r['id']}")
        with self.db.tx() as c:
            c.execute("""UPDATE stock_approvals SET status='approved', decided_by=?, decided_name=?, decided_at=?, answer=?, doc_id=?,
                         updated_at=? WHERE id=?""", (login, name, now, _clean(answer, 300), did, now, r["id"]))
        return self.approval(r["id"])

    def cancel_approval(self, aid, login="", may_any=False):
        r = self.db.one("SELECT * FROM stock_approvals WHERE id=?", (str(aid or ""),))
        if not r:
            raise ValueError("Запись не найдена")
        if r["created_by"] != login and not may_any:
            raise ValueError("Отменить можно только своё")
        if r["status"] not in ("draft", "pending"):
            raise ValueError(f"Уже {APPR_STATUS.get(r['status'], r['status']).lower()} — отменить нельзя")
        with self.db.tx() as c:
            c.execute("UPDATE stock_approvals SET status='cancelled', updated_at=? WHERE id=?", (_now(), r["id"]))
        return self.approval(r["id"])

    def counts(self, login=None, approver=False, issuer=False):
        """Numbers for the badges: what waits for this person — approvals for a manager, requests for whoever issues."""
        one = lambda sql, *a: self.db.one(sql, a)["n"]  # noqa: E731
        out = {"my_requests": one("SELECT COUNT(*) AS n FROM stock_requests WHERE created_by=? AND status IN ('new','accepted','partial')", login or ""),
               "my_pending": one("SELECT COUNT(*) AS n FROM stock_approvals WHERE created_by=? AND status='pending'", login or ""),
               "my_drafts": one("SELECT COUNT(*) AS n FROM stock_requests WHERE created_by=? AND status='draft'", login or "")
               + one("SELECT COUNT(*) AS n FROM stock_approvals WHERE created_by=? AND status='draft'", login or ""),
               "my_rejected": one("""SELECT COUNT(*) AS n FROM stock_approvals WHERE created_by=? AND status='rejected'
                                     AND decided_at >= ?""", login or "", (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))}
        if approver:
            out["to_approve"] = one("SELECT COUNT(*) AS n FROM stock_approvals WHERE status='pending'")
        if approver or issuer:
            out["to_issue"] = one("SELECT COUNT(*) AS n FROM stock_requests WHERE status IN ('new','accepted','partial')")
            out["to_accept"] = one("SELECT COUNT(*) AS n FROM stock_requests WHERE status='new'")
        return out

    # ========================================================== home screen --
    def stats(self, days=30):
        """Receipts, use and the stock's value for the last `days` days, in roubles (by the prices of the moves)."""
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 30
        days = days if days in STAT_DAYS else 30
        since = (date.today() - timedelta(days=days - 1)).isoformat()
        r = self.db.one("""SELECT COALESCE(SUM(CASE WHEN kind='receipt' THEN qty*price END),0) AS inc,
                                  COALESCE(SUM(CASE WHEN kind IN ('service','writeoff') THEN -qty*price END),0) AS used
                           FROM stock_moves WHERE substr(at,1,10) >= ?""", (since,))
        value = sum(m["value"] for m in self.stock.materials() if m["balance"] > 0)
        return {"days": days, "income": round(r["inc"] or 0, 2), "used": round(r["used"] or 0, 2), "value": round(value, 2)}

    def home(self, perms, login="", days=30):
        mats = self.stock.materials()
        approver = bool(perms & {"stock_approve"})
        ops = bool(perms & {"stock_edit", "stock_ops"})
        cnt = self.counts(login, approver, "stock_edit" in perms)
        critical = sorted((m for m in mats if m["low"] or m["balance"] < 0),
                          key=lambda m: (m["balance"] / m["min_qty"]) if m["min_qty"] else -1)
        lots = []
        lot_map = self.stock._lots_by_material({m["id"]: m["balance"] for m in mats})
        by_id = {m["id"]: m for m in mats}
        for mid, rec in lot_map.items():
            if mid not in by_id:
                continue
            for g in rec["lots"]:
                if g["left"] > 0 and (g["expires"] or g["lot"]):
                    m = by_id[mid]
                    lots.append({"material_id": mid, "name": m["name"], "unit": m["unit"], "code": m["code"], "photo_id": m.get("photo_id") or "",
                                 "lot": g["lot"], "expires": g["expires"], "state": g["state"], "days": g["days"], "left": g["left"]})
        lots.sort(key=lambda x: (x["expires"] or "9999", x["name"]))
        soon = [x for x in lots if x["state"] in ("expired", "soon")]
        names = self.stock._loc_names()
        where = {}
        for mid, by in self.stock.location_balances().items():  # where each material is: places with something on hand
            places = sorted(((k, v) for k, v in by.items() if v > 1e-9), key=lambda kv: (kv[0] != "", -kv[1]))
            if places:
                where[mid] = [{"id": k, "name": names.get(k, names.get("", "")), "qty": round(v, 3)} for k, v in places]
        tasks = []
        if cnt.get("to_approve"):
            tasks.append({"key": "approve", "title": "Согласовать списания", "sub": f"ждут решения: {cnt['to_approve']}", "count": cnt["to_approve"]})
        if cnt.get("to_issue"):
            tasks.append({"key": "issue", "title": "Выдать по заявкам", "count": cnt["to_issue"],
                          "sub": f"заявок из кабинетов: {cnt['to_issue']}" + (f", новых: {cnt['to_accept']}" if cnt.get("to_accept") else "")})
        if ops and any(x["state"] == "expired" for x in soon):
            n = len({x["material_id"] for x in soon if x["state"] == "expired"})
            tasks.append({"key": "expired", "title": "Убрать просроченное", "sub": f"материалов с истёкшим сроком: {n}", "count": n})
        if ops and critical:
            tasks.append({"key": "order", "title": "Пополнить запас", "sub": f"ниже минимума: {len(critical)}", "count": len(critical)})
        if cnt["my_pending"]:
            tasks.append({"key": "my", "title": "Мои списания на согласовании", "sub": f"ждут менеджера: {cnt['my_pending']}", "count": cnt["my_pending"]})
        if cnt["my_rejected"]:
            tasks.append({"key": "my", "title": "Отклонено менеджером", "sub": f"за неделю: {cnt['my_rejected']} — посмотрите причину", "count": cnt["my_rejected"]})
        if cnt["my_drafts"]:
            tasks.append({"key": "drafts", "title": "Незаконченные черновики", "sub": f"заявок и расходов: {cnt['my_drafts']}", "count": cnt["my_drafts"]})
        due = [e for e in self.stock.equipment_list() if e["service_due"]]
        if due and perms & {"equipment", "stock_edit", "stock_ops"}:
            tasks.append({"key": "service", "title": "Техобслуживание оборудования", "sub": f"пора на ТО: {len(due)}", "count": len(due)})
        cats = sorted({m["category"] for m in mats if m["category"]})
        return {"counts": cnt, "tasks": tasks, "approver": approver,
                "critical": [{"id": m["id"], "name": m["name"], "unit": m["unit"], "balance": m["balance"], "min_qty": m["min_qty"]}
                             for m in critical[:8]], "critical_count": len(critical),
                "expiring": soon[:8], "expiring_count": len(soon), "lots": lots[:400], "where": where, "stats": self.stats(days), "categories": cats,
                "stat_days": list(STAT_DAYS), "priorities": PRIORITY, "req_status": REQ_STATUS, "appr_status": APPR_STATUS}
