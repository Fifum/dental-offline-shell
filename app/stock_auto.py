"""3.5 «Склад: автосписание по приёмам Dentist Plus и себестоимость услуг».

Write-off by visits. A finished Dentist Plus visit (status «завершён» or «пришёл») with its services becomes a write-off of
the materials of the norms (`service_materials`, the same «техкарта» as for invoices made here). The services come from the
visit as Dentist Plus gave it (`visits.data`: services / items / works … — the partner API does not document them), else from
the visit's title when it is exactly the name of a service, else the user enters them («нет данных из Dentist Plus»).

* Safe by default: the visits are a list of drafts that someone with «Склад: приход, списание» confirms. The mode «сразу»
  writes them off by itself, but only visits from the day it was switched on, never older ones.
* Never twice: one row per visit (`stock_visit_use`, id = the visit id); the document is `V-<visit>` and its moves have stable
  ids, so two computers that wrote off the same visit offline end up with one write-off after syncing. A visit that has an
  invoice here (by the visit or by patient + day) is already written off by the invoice and is skipped.
* Reversible: «Отменить списание» puts the materials back and leaves the visit as «отменено» (the automatic mode does not
  touch it again); «Вернуть в черновики» makes it a draft again. Every step goes to the action journal.
* The place: the cabinet whose chair is the visit's chair, else the place of the visit's branch, else the place chosen in
  the settings, else the main stock.

Cost of a service: materials by the norm × the last purchase price + the laboratory and other costs entered for the service
+ the doctor's percent (the service's own, else the clinic's setting, else the average percent of the doctors' pay schemes).
The month view counts the services made (invoices here and visits written off here) against that cost. The P&L can take the
materials from the stock (what was written off) instead of the purchases — a setting of «Бухгалтерия».
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_settings(k TEXT PRIMARY KEY, v TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS stock_visit_use(
    id TEXT PRIMARY KEY, visit_id TEXT, patient_id TEXT, doctor_id TEXT, branch_id TEXT, chair TEXT, start TEXT,
    status TEXT, source TEXT, services TEXT, lines TEXT, location_id TEXT, doc_id TEXT, total REAL DEFAULT 0, note TEXT,
    done_by TEXT, done_name TEXT, at TEXT, auto INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_svu_start ON stock_visit_use(start);
CREATE TABLE IF NOT EXISTS service_costs(
    service_id TEXT PRIMARY KEY, lab REAL DEFAULT 0, other REAL DEFAULT 0, doctor_pct REAL, note TEXT, updated_at TEXT);
"""
DEFAULTS = {
    "mode": "draft",          # «draft» — a list to confirm; «auto» — written off by itself (visits from auto_since on)
    "auto_since": "",         # the day the automatic mode was switched on
    "days": "7",              # how many days back the list of visits shows by default
    "location": "",           # the place for visits whose cabinet or branch is unknown («» — the main stock)
    "by_title": "1",          # a visit without services: take the service whose name is the visit's title
    "doctor_pct": "",         # the doctor's percent in the cost («» — the average of the doctors' pay schemes)
    "pnl_materials": "expenses",  # «expenses» — the P&L takes the purchases; «stock» — what was written off
}
MODES = {"draft": "Черновик — списывать после подтверждения", "auto": "Сразу — списывать автоматически"}
PNL_MODES = {"expenses": "по закупкам (расходы «Материалы и закупки»)", "stock": "по списанию со склада"}
STATUS = {"draft": "К списанию", "no_services": "Нет услуг", "no_norms": "Нет норм", "invoice": "Списано по счёту",
          "done": "Списано", "skipped": "Не списывать", "reverted": "Списание отменено"}
AUTO_USER = "Автосписание"
NO_DP = "нет данных из Dentist Plus"
DONE_KINDS = ("done", "came")
SVC_KEYS = ("services", "visit_services", "service_list", "serviceList", "items", "works", "procedures", "positions",
            "treatments", "invoice_items", "order_items")
SVC_HOLDERS = ("invoice", "treatment", "plan", "order", "bill")
TICK_SECONDS = 300


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(v, name="Количество"):
    try:
        x = float(str(v).replace(",", ".").replace(" ", "")) if v not in (None, "") else 0.0
    except ValueError:
        raise ValueError(f"{name}: введите число") from None
    return round(x, 3)


def _norm(s):
    return re.sub(r"[\s.,;:«»\"'()\-–—]+", " ", str(s or "").lower().replace("ё", "е")).strip()


def _get(o, *keys):
    for k in keys:
        cur = o
        for part in k.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if cur not in (None, ""):
            return cur
    return None


def raw_services(raw) -> list:
    """The services of a visit as Dentist Plus gave them: [{dp_id, code, title, qty}] — any of the usual shapes."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, dict):
        return []
    out = []

    def take(lst):
        for it in lst or []:
            if isinstance(it, str) and it.strip():
                out.append({"dp_id": "", "code": "", "title": it.strip()[:200], "qty": 1.0})
                continue
            if not isinstance(it, dict):
                continue
            dp_id = _get(it, "service_id", "serviceId", "service.id")
            weak = it.get("id")  # the id of the line itself or of the service: trusted only when nothing else names it
            code = _get(it, "code", "article", "service.code", "service.article", "number") or ""
            title = _get(it, "title", "name", "service.title", "service.name", "service_title", "service_name") or ""
            q = _get(it, "count", "qty", "quantity", "amount_count", "cnt")
            try:
                q = float(str(q).replace(",", ".")) if q is not None else 1.0
            except ValueError:
                q = 1.0
            if dp_id is None and weak is None and not code and not title:
                continue
            out.append({"dp_id": "" if dp_id is None else str(dp_id), "line_id": "" if weak is None else str(weak),
                        "code": str(code)[:60], "title": str(title)[:200], "qty": q if q > 0 else 1.0})

    for k in SVC_KEYS:
        if isinstance(raw.get(k), list):
            take(raw[k])
    for h in SVC_HOLDERS:
        if isinstance(raw.get(h), dict):
            for k in SVC_KEYS:
                if isinstance(raw[h].get(k), list):
                    take(raw[h][k])
    for h in ("invoices", "orders", "bills"):
        if isinstance(raw.get(h), list):
            for x in raw[h]:
                if isinstance(x, dict):
                    for k in SVC_KEYS:
                        if isinstance(x.get(k), list):
                            take(x[k])
    return out


class StockAuto:
    def __init__(self, db, stock, acc=None):
        self.db, self.stock, self.acc = db, stock, acc
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()
        self._last_tick = 0.0
        self._count_cache = (0.0, None)
        stock.service_location = self.location_for_invoice

    # ------------------------------------------------------------ settings --
    def settings(self) -> dict:
        s = dict(DEFAULTS)
        for r in self.db.q("SELECT k, v FROM stock_settings"):
            if r["k"] in DEFAULTS:
                s[r["k"]] = r["v"] if r["v"] is not None else ""
        if s["mode"] not in MODES:
            s["mode"] = "draft"
        if s["pnl_materials"] not in PNL_MODES:
            s["pnl_materials"] = "expenses"
        return s

    def _put(self, vals: dict):
        with self.db.tx() as c:
            for k, v in vals.items():
                c.execute("INSERT INTO stock_settings(k, v, updated_at) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, "
                          "updated_at=excluded.updated_at", (k, str(v), _now()))
        self._count_cache = (0.0, None)

    def save_settings(self, f) -> dict:
        """The stock side: the mode, the place by default, the days of the list, the title rule."""
        f = f if isinstance(f, dict) else {}
        cur, out = self.settings(), {}
        if "mode" in f:
            mode = f["mode"] if f["mode"] in MODES else "draft"
            out["mode"] = mode
            if mode == "auto" and cur["mode"] != "auto":
                out["auto_since"] = date.today().isoformat()  # only visits from today on; older ones stay drafts
        if "location" in f:
            out["location"] = self.stock._loc(f.get("location")) or ""
        if "days" in f:
            out["days"] = str(max(1, min(62, int(_num(f.get("days"), "Дней")))))
        if "by_title" in f:
            out["by_title"] = "1" if f.get("by_title") else "0"
        if out:
            self._put(out)
        return self.settings()

    def save_cost_settings(self, f) -> dict:
        """The accounting side: the doctor's percent of the cost and where the P&L takes the materials from."""
        f = f if isinstance(f, dict) else {}
        out = {}
        if "doctor_pct" in f:
            v = str(f.get("doctor_pct") if f.get("doctor_pct") is not None else "").strip()
            if v:
                p = _num(v, "Процент врача")
                if not 0 <= p <= 100:
                    raise ValueError("Процент врача: от 0 до 100")
                v = f"{p:g}"
            out["doctor_pct"] = v
        if "pnl_materials" in f:
            out["pnl_materials"] = f["pnl_materials"] if f["pnl_materials"] in PNL_MODES else "expenses"
        if out:
            self._put(out)
        return self.settings()

    # -------------------------------------------------------------- places --
    def _location_for(self, chair, branch_id):
        """The cabinet of the chair, else the place of the branch, else the place of the settings, else the main stock."""
        locs = self.db.q("SELECT id, kind, branch_id, chair FROM stock_locations WHERE active=1 ORDER BY sort, name")
        ch = _norm(chair)
        if ch:
            for r in locs:
                if r["chair"] and _norm(r["chair"]) == ch:
                    return r["id"]
        if branch_id not in (None, ""):
            for r in locs:
                if r["branch_id"] and str(r["branch_id"]) == str(branch_id) and not r["chair"]:
                    return r["id"]
            for r in locs:
                if r["branch_id"] and str(r["branch_id"]) == str(branch_id):
                    return r["id"]
        loc = self.settings()["location"]
        return loc if loc and any(r["id"] == loc for r in locs) else ""

    def location_for_invoice(self, inv):
        """An invoice made here: the place of its visit (chair / branch) or the place of the settings."""
        chair = branch = None
        vid = (inv or {}).get("visit_id")
        if vid:
            v = self.db.one("SELECT chair, branch_id FROM local_visits WHERE id=?", (vid,)) or \
                self.db.one("SELECT chair, branch_id FROM visits_archive WHERE id=?", (vid,))
            if v:
                chair, branch = v["chair"], v["branch_id"]
        return self._location_for(chair, branch) or None

    # ------------------------------------------------------------ services --
    def _svc_index(self):
        rows = self.db.q("SELECT id, code, title, price FROM services")
        by_id = {r["id"]: r for r in rows}
        by_code, by_title = {}, {}
        for r in rows:
            if r["code"]:
                by_code.setdefault(str(r["code"]).strip().lower(), r)
            if r["title"]:
                by_title.setdefault(_norm(r["title"]), r)
        return by_id, by_code, by_title

    def _match(self, items, idx):
        by_id, by_code, by_title = idx
        out = []
        for it in items:
            s = None
            if it.get("dp_id"):
                s = by_id.get(f"api_{it['dp_id']}") or by_id.get(str(it["dp_id"]))
            if not s and it.get("code"):
                s = by_code.get(str(it["code"]).strip().lower())
            if not s and it.get("title"):
                s = by_title.get(_norm(it["title"]))
            if not s and it.get("line_id") and not it.get("title") and not it.get("code"):
                s = by_id.get(f"api_{it['line_id']}") or by_id.get(str(it["line_id"]))
            out.append({"service_id": s["id"] if s else None, "title": (s["title"] if s else it.get("title")) or it.get("code") or "Услуга",
                        "dp_title": it.get("title") or "", "qty": round(float(it.get("qty") or 1), 3), "found": bool(s)})
        return out

    def _norms(self):
        by = {}
        for r in self.db.q("""SELECT sm.service_id, sm.material_id, sm.qty, m.name, m.unit, m.price FROM service_materials sm
                              JOIN materials m ON m.id=sm.material_id WHERE m.active=1"""):
            by.setdefault(r["service_id"], []).append(r)
        return by

    def _lines(self, services, norms):
        need = {}
        for s in services:
            if not s.get("service_id"):
                continue
            for n in norms.get(s["service_id"], []):
                ln = need.setdefault(n["material_id"], {"material_id": n["material_id"], "name": n["name"], "unit": n["unit"],
                                                        "price": n["price"] or 0, "qty": 0.0, "services": []})
                ln["qty"] = round(ln["qty"] + n["qty"] * float(s.get("qty") or 1), 3)
                ln["services"].append(s["title"])
        out = sorted(need.values(), key=lambda x: x["name"])
        for ln in out:
            ln["sum"] = round(ln["qty"] * ln["price"], 2)
            ln["services"] = list(dict.fromkeys(ln["services"]))
        return out

    # -------------------------------------------------------------- visits --
    def _dp_visits(self, a, b):
        """Finished Dentist Plus visits of the days: the mirror (with what Dentist Plus gave) and the archive."""
        end = (date.fromisoformat(b) + timedelta(days=1)).isoformat()
        rows = self.db.q("""SELECT v.id, v.patient_id, v.doctor_id, v.branch_id, v.start, v.status, v.title, v.data, NULL AS chair
                            FROM visits v WHERE v.start >= ? AND v.start < ?
                            UNION ALL
                            SELECT h.id, h.patient_id, h.doctor_id, h.branch_id, h.start, h.status, h.title, NULL AS data, h.chair
                            FROM visits_archive h WHERE h.id NOT IN (SELECT id FROM visits) AND h.start >= ? AND h.start < ?""",
                         (a, end, a, end))
        from reports import status_kind
        today = date.today().isoformat()
        out = []
        for v in rows:
            kind = status_kind(v["status"])
            if kind not in DONE_KINDS or str(v["start"])[:10] > today:
                continue
            raw = {}
            if v["data"]:
                try:
                    raw = json.loads(v["data"])
                except ValueError:
                    raw = {}
            chair = v["chair"]
            if not chair and isinstance(raw, dict):
                c = raw.get("chair")
                chair = (c.get("title") or c.get("name")) if isinstance(c, dict) else (c or raw.get("chair_name") or raw.get("cabinet") or raw.get("room"))
            out.append({**{k: v[k] for k in ("id", "patient_id", "doctor_id", "branch_id", "start", "status", "title")},
                        "kind": kind, "raw": raw, "chair": str(chair or "")[:100], "mirror": v["data"] is not None})
        return out

    def _invoiced(self, a, b):
        """Visits written off already by an invoice made here: by the visit id (also a visit edited here) and by patient + day."""
        end = (date.fromisoformat(b) + timedelta(days=1)).isoformat()
        ids, pairs = set(), set()
        lv = {r["id"]: r for r in self.db.q("SELECT id, origin_id, remote_id FROM local_visits")}
        for r in self.db.q("""SELECT visit_id, patient_id, substr(created_at,1,10) AS day FROM invoices
                              WHERE COALESCE(kind,'invoice')='invoice' AND created_at >= ? AND created_at < ?""", (a, end)):
            if r["visit_id"]:
                ids.add(str(r["visit_id"]))
                x = lv.get(r["visit_id"])
                if x:
                    ids.update(str(v) for v in (x["origin_id"], x["remote_id"]) if v)
            pairs.add((str(r["patient_id"] or ""), r["day"]))
        return ids, pairs

    def _period(self, date_from=None, date_to=None):
        today = date.today()
        try:
            b = date.fromisoformat(str(date_to)[:10]) if date_to else today
        except ValueError:
            b = today
        try:
            a = date.fromisoformat(str(date_from)[:10]) if date_from else b - timedelta(days=int(self.settings()["days"]) - 1)
        except ValueError:
            a = b - timedelta(days=6)
        if a > b:
            a, b = b, a
        if (b - a).days > 92:
            a = b - timedelta(days=92)
        return a.isoformat(), b.isoformat()

    def _build(self, v, saved, idx, norms, invoiced, s):
        """One visit as the list shows it: services, the lines of the write-off and the state."""
        ids, pairs = invoiced
        row = {"id": str(v["id"]), "visit_id": str(v["id"]), "patient_id": v.get("patient_id"), "doctor_id": v.get("doctor_id"),
               "branch_id": v.get("branch_id"), "start": v.get("start"), "chair": v.get("chair") or "", "visit_status": v.get("status") or "",
               "title": v.get("title") or "", "note": "", "done_by": "", "done_name": "", "at": "", "auto": 0, "doc_id": ""}
        if saved and saved["services"] is not None:
            try:
                services = json.loads(saved["services"])
            except ValueError:
                services = []
            source = saved["source"] or "manual"
        else:
            services = self._match(raw_services(v.get("raw")), idx) if v.get("raw") else []
            source = "dp" if services else "none"
            if not services and s["by_title"] == "1" and v.get("title"):
                t = idx[2].get(_norm(v["title"]))
                if t:
                    services, source = [{"service_id": t["id"], "title": t["title"], "dp_title": v["title"], "qty": 1.0, "found": True}], "title"
        row["services"], row["source"] = services, source
        if saved:
            for k in ("note", "done_by", "done_name", "at", "auto", "doc_id"):
                row[k] = saved[k] or ("" if k != "auto" else 0)
        st = saved["status"] if saved else ""
        if st == "done":
            try:
                row["lines"] = json.loads(saved["lines"] or "[]")
            except ValueError:
                row["lines"] = []
            row["total"] = round(saved["total"] or 0, 2)
            row["location_id"] = saved["location_id"] or ""
            row["status"] = "done"
        else:
            row["lines"] = self._lines(services, norms)
            row["total"] = round(sum(x["sum"] for x in row["lines"]), 2)
            row["location_id"] = (saved["location_id"] if saved and saved["location_id"] is not None else None)
            if row["location_id"] is None:
                row["location_id"] = self._location_for(row["chair"], row["branch_id"])
            day = str(row["start"] or "")[:10]
            if row["visit_id"] in ids or (str(row["patient_id"] or ""), day) in pairs:
                base = "invoice"
            elif not any(x.get("service_id") for x in services):  # none, or none of them is in the price list
                base = "no_services"
            elif not row["lines"]:
                base = "no_norms"
            else:
                base = "draft"
            row["base_status"] = base  # what it would be without «не списывать» / «отменено»
            row["status"] = st if st in ("skipped", "reverted") else base
        row.setdefault("base_status", row["status"])
        row["status_title"] = STATUS[row["status"]]
        row["unknown"] = [x["dp_title"] or x["title"] for x in services if not x.get("service_id")]
        return row

    def _rows(self, a, b):
        s = self.settings()
        idx, norms = self._svc_index(), self._norms()
        invoiced = self._invoiced(a, b)
        end = (date.fromisoformat(b) + timedelta(days=1)).isoformat()
        saved = {r["id"]: r for r in self.db.q("SELECT * FROM stock_visit_use WHERE start >= ? AND start < ?", (a, end))}
        rows, seen = [], set()
        for v in self._dp_visits(a, b):
            if str(v["id"]) in seen:
                continue
            seen.add(str(v["id"]))
            rows.append(self._build(v, saved.get(str(v["id"])), idx, norms, invoiced, s))
        for sid, r in saved.items():  # written off earlier, the visit left the mirror (or Dentist Plus deleted it)
            if sid not in seen and r["status"] in ("done", "skipped", "reverted"):
                v = {k: r[k] for k in ("patient_id", "doctor_id", "branch_id", "start", "chair")}
                v.update(id=sid, status="", title="", raw=None)
                row = self._build(v, r, idx, norms, invoiced, s)
                row["gone"] = True
                rows.append(row)
        return rows

    def visits(self, date_from=None, date_to=None, status=None) -> dict:
        a, b = self._period(date_from, date_to)
        rows = self._rows(a, b)
        counts = {k: 0 for k in STATUS}
        for r in rows:
            counts[r["status"]] += 1
        names = {p["id"]: p["name"] for p in self.db.q("SELECT id, name FROM patients")}
        docs = {d["id"]: d["name"] for d in self.db.q("SELECT id, name FROM doctors")}
        locs = self.stock._loc_names()
        for r in rows:
            r["patient_name"] = names.get(r["patient_id"]) or ""
            r["doctor_name"] = docs.get(r["doctor_id"]) or ""
            r["location_name"] = locs.get(r["location_id"] or "", locs[""])
        if status:
            want = set(str(status).split(","))
            rows = [r for r in rows if r["status"] in want]
        rows.sort(key=lambda r: (str(r["start"] or "")), reverse=True)
        span = self.db.one("SELECT MIN(s) AS a, MAX(s) AS b FROM (SELECT start AS s FROM visits UNION ALL SELECT start AS s FROM visits_archive)")
        s = self.settings()
        return {"from": a, "to": b, "rows": rows, "counts": counts, "settings": s, "modes": MODES, "status_titles": STATUS,
                "has_dp": bool(span and span["a"]), "total_draft": round(sum(r["total"] for r in rows if r["status"] == "draft"), 2),
                "no_dp": NO_DP, "locations": [{"id": k, "name": v} for k, v in locs.items()]}

    def _one(self, vid):
        vid = str(vid or "")
        if not vid:
            raise ValueError("Приём не найден")
        saved = self.db.one("SELECT * FROM stock_visit_use WHERE id=?", (vid,))
        found = None
        for t in ("visits", "visits_archive"):
            r = self.db.one(f"SELECT start FROM {t} WHERE id=?", (vid,))
            if r:
                day = str(r["start"])[:10]
                found = next((v for v in self._dp_visits(day, day) if str(v["id"]) == vid), None)
                if found:
                    break
        if not found and saved:
            found = {k: saved[k] for k in ("patient_id", "doctor_id", "branch_id", "start", "chair")}
            found.update(id=vid, status="", title="", raw=None)
        if not found:
            raise ValueError("Приём не найден или ещё не завершён")
        day = str(found["start"])[:10]
        return self._build(found, saved, self._svc_index(), self._norms(), self._invoiced(day, day), self.settings()), saved

    def visit(self, vid) -> dict:
        row, _ = self._one(vid)
        return row

    def _save_row(self, c, row, status, **kw):
        now = _now()
        vals = {"visit_id": row["visit_id"], "patient_id": row["patient_id"], "doctor_id": row["doctor_id"], "branch_id": row["branch_id"],
                "chair": row["chair"], "start": row["start"], "status": status, "source": row["source"],
                "services": json.dumps(row["services"], ensure_ascii=False), "location_id": row.get("location_id") or "",
                "updated_at": now, **kw}
        cols = list(vals)
        c.execute(f"""INSERT INTO stock_visit_use(id, {', '.join(cols)}, created_at) VALUES(?, {', '.join('?' * len(cols))}, ?)
                      ON CONFLICT(id) DO UPDATE SET {', '.join(f'{k}=excluded.{k}' for k in cols)}""",
                  (row["id"], *[vals[k] for k in cols], now))

    def save_services(self, vid, services, location=None) -> dict:
        """The user's own services of a visit (Dentist Plus gave none, or gave others): the draft keeps them."""
        row, saved = self._one(vid)
        if row["status"] == "done":
            raise ValueError("Приём уже списан. Сначала отмените списание")
        idx = self._svc_index()
        out = []
        for it in services or []:
            sid = (it or {}).get("service_id")
            q = _num((it or {}).get("qty") or 1)
            if not sid or q <= 0:
                continue
            s = idx[0].get(sid)
            if not s:
                raise ValueError("Услуга не найдена в прайсе")
            out.append({"service_id": sid, "title": s["title"], "dp_title": "", "qty": q, "found": True})
        row["services"], row["source"] = out, "manual"
        if location is not None:
            row["location_id"] = self.stock._loc(location) or ""
        status = saved["status"] if saved and saved["status"] in ("skipped", "reverted") else "draft"
        with self.db.tx() as c:
            self._save_row(c, row, status)
        return self.visit(vid)

    def _uid_col(self):
        return "uid" in {r[1] for r in self.db.conn.execute("PRAGMA table_info(stock_moves)")}

    def confirm(self, ids, login="", name="", auto=False) -> dict:
        """Write off the visits' materials. A visit already written off, billed here, without services or norms is left as it is."""
        if isinstance(ids, (str, int)):
            ids = [ids]
        done, left = [], []
        has_uid = self._uid_col()
        for vid in list(dict.fromkeys(str(x) for x in ids or [] if x not in (None, ""))):
            try:
                row, saved = self._one(vid)
            except ValueError as e:
                left.append({"id": vid, "why": str(e)})
                continue
            # by hand a skipped or reverted visit may be written off again; the automatic mode takes drafts only
            ok = row["status"] == "draft" or (not auto and row["status"] in ("skipped", "reverted") and row["base_status"] == "draft")
            if not ok:
                why = STATUS[row["base_status"] if row["status"] in ("skipped", "reverted") else row["status"]]
                left.append({"id": vid, "why": why})
                continue
            doc_id, at = f"V-{vid}", str(row["start"] or _now())[:19].replace("T", " ")
            loc = row["location_id"] or None
            if loc and not self.db.one("SELECT 1 AS x FROM stock_locations WHERE id=? AND active=1", (loc,)):
                loc = None
            who = AUTO_USER if auto else (name or login)
            titles = "; ".join(dict.fromkeys(s["title"] for s in row["services"] if s.get("service_id")))
            with self.db.tx() as c:
                cur = c.execute("SELECT status FROM stock_visit_use WHERE id=?", (vid,)).fetchone()
                if cur and cur[0] == "done":  # written off a moment ago (another window, the automatic tick)
                    left.append({"id": vid, "why": STATUS["done"]})
                    continue
                c.execute("DELETE FROM stock_moves WHERE doc_id=?", (doc_id,))
                c.execute("""INSERT INTO stock_docs(id, kind, number, date, supplier_id, reason, comment, total, user_name, created_at, nodoc,
                             location_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET total=excluded.total,
                             reason=excluded.reason, user_name=excluded.user_name, location_id=excluded.location_id""",
                          (doc_id, "visit", "", at[:10], None, f"Приём Dentist Plus: {titles}"[:300], "", row["total"], who, at, 0, loc))
                for ln in row["lines"]:
                    cols = "material_id, qty, price, kind, doc_id, patient_id, reason, user_name, at, location_id"
                    vals = [ln["material_id"], -ln["qty"], ln["price"], "service", doc_id, row["patient_id"],
                            ("Приём: " + "; ".join(ln["services"]))[:200], who, at, loc]
                    if has_uid:  # the same id on every computer: one write-off of a visit, however many wrote it off
                        cols += ", uid"
                        vals.append(f"v-{vid}-{ln['material_id']}"[:120])
                    c.execute(f"INSERT INTO stock_moves({cols}) VALUES({', '.join('?' * len(vals))})", vals)
                row["location_id"] = loc or ""
                self._save_row(c, row, "done", lines=json.dumps(row["lines"], ensure_ascii=False), total=row["total"], doc_id=doc_id,
                               done_by="auto" if auto else login, done_name=who, at=_now() if not auto else at, auto=1 if auto else 0,
                               note="")
            done.append(vid)
        self._count_cache = (0.0, None)
        return {"done": done, "left": left, "count": len(done)}

    def revert(self, vid, login="", name="") -> dict:
        """Put the materials of a written-off visit back. The automatic mode leaves the visit alone afterwards."""
        row, saved = self._one(vid)
        if not saved or saved["status"] != "done":
            raise ValueError("Этот приём не списан")
        with self.db.tx() as c:
            c.execute("DELETE FROM stock_moves WHERE doc_id=?", (saved["doc_id"] or f"V-{vid}",))
            c.execute("DELETE FROM stock_docs WHERE id=?", (saved["doc_id"] or f"V-{vid}",))
            c.execute("""UPDATE stock_visit_use SET status='reverted', doc_id='', lines=NULL, total=0, note=?, updated_at=? WHERE id=?""",
                      (f"Списание отменил(а) {name or login} {_now()[:16]}", _now(), str(vid)))
        self._count_cache = (0.0, None)
        return self.visit(vid)

    def skip(self, vid, note="") -> dict:
        row, saved = self._one(vid)
        if row["status"] == "done":
            raise ValueError("Приём уже списан. Сначала отмените списание")
        with self.db.tx() as c:
            self._save_row(c, row, "skipped", note=str(note or "").strip()[:300])
        self._count_cache = (0.0, None)
        return self.visit(vid)

    def restore(self, vid) -> dict:
        """A skipped or reverted visit becomes a draft again (with the services it had)."""
        row, saved = self._one(vid)
        if not saved or saved["status"] not in ("skipped", "reverted"):
            raise ValueError("Приём и так в черновиках")
        with self.db.tx() as c:
            c.execute("UPDATE stock_visit_use SET status='draft', note='', updated_at=? WHERE id=?", (_now(), str(vid)))
        self._count_cache = (0.0, None)
        return self.visit(vid)

    # ------------------------------------------------------- automatic mode --
    def tick(self, force=False):
        """In the automatic mode: write off the finished visits from the day the mode was switched on. At most every 5 minutes."""
        if not force and time.time() - self._last_tick < TICK_SECONDS:
            return None
        self._last_tick = time.time()
        s = self.settings()
        if s["mode"] != "auto":
            return None
        since = s["auto_since"] or date.today().isoformat()
        a = max(since, (date.today() - timedelta(days=31)).isoformat())
        b = date.today().isoformat()
        if a > b:
            return None
        today = date.today().isoformat()
        ids = [r["id"] for r in self._rows(a, b) if r["status"] == "draft"
               and (r["visit_status"] == "" or self._kind(r["visit_status"]) == "done" or str(r["start"])[:10] < today)]
        if not ids:
            return {"count": 0, "done": [], "left": []}
        res = self.confirm(ids, auto=True)
        if res["count"]:
            self._journal(f"Списано приёмов: {res['count']}")
        return res

    @staticmethod
    def _kind(status):
        from reports import status_kind
        return status_kind(status)

    def _journal(self, detail):
        try:
            with self.db.tx() as c:
                c.execute("INSERT INTO audit(at, user_id, user_name, action, detail, ip) VALUES(?,?,?,?,?,?)",
                          (_now(), None, AUTO_USER, "Автосписание материалов по приёмам Dentist Plus", detail[:500], ""))
        except Exception:  # noqa: BLE001 — no journal in a bare database
            pass

    def draft_count(self) -> int:
        """Visits waiting for a write-off over the days of the list (for the tab), cached for a minute."""
        at, n = self._count_cache
        if n is not None and time.time() - at < 60:
            return n
        a, b = self._period()
        n = sum(1 for r in self._rows(a, b) if r["status"] == "draft")
        self._count_cache = (time.time(), n)
        return n

    # ------------------------------------------------------------------ cost --
    def doctor_pct(self):
        """The doctor's percent of the cost: the setting, else the average percent of the doctors' pay schemes, else 0."""
        v = self.settings()["doctor_pct"]
        if str(v).strip():
            return float(v), "setting"
        try:
            r = self.db.one("SELECT AVG(percent) AS p, COUNT(*) AS n FROM salary_schemes WHERE person LIKE 'd:%' AND percent > 0")
            if r and r["n"]:
                return round(r["p"], 1), "schemes"
        except Exception:  # noqa: BLE001 — no payroll tables
            pass
        return 0.0, "none"

    def costs(self, month=None) -> dict:
        """The cost of every service of the price list and, for the month, how many were made and what they earned."""
        norms = self._norms()
        own = {r["service_id"]: r for r in self.db.q("SELECT * FROM service_costs")}
        pct, pct_src = self.doctor_pct()
        made = self._made(month)
        rows = []
        for s in self.db.q("SELECT id, code, title, price, category FROM services WHERE active=1 ORDER BY category, title"):
            mats = [{"material_id": n["material_id"], "name": n["name"], "unit": n["unit"], "qty": n["qty"], "price": n["price"] or 0,
                     "sum": round(n["qty"] * (n["price"] or 0), 2)} for n in norms.get(s["id"], [])]
            o = own.get(s["id"]) or {}
            materials = round(sum(m["sum"] for m in mats), 2)
            lab, other = round(o.get("lab") or 0, 2), round(o.get("other") or 0, 2)
            p = o.get("doctor_pct")
            p_own = p is not None
            p = float(p) if p_own else pct
            price = round(s["price"] or 0, 2)
            doctor = round(price * p / 100, 2)
            cost = round(materials + lab + other + doctor, 2)
            n = made["by_service"].get(s["id"], 0)
            rows.append({"service_id": s["id"], "code": s["code"] or "", "title": s["title"], "category": s["category"] or "", "price": price,
                         "materials": materials, "lines": mats, "lab": lab, "other": other, "doctor_pct": p, "doctor_pct_own": p_own,
                         "doctor": doctor, "cost": cost, "margin": round(price - cost, 2),
                         "margin_pct": round((price - cost) * 100 / price, 1) if price else None, "note": o.get("note") or "",
                         "no_norms": not mats, "made": n, "made_revenue": round(n * price, 2), "made_cost": round(n * cost, 2)})
        tot_rev = round(sum(r["made_revenue"] for r in rows), 2)
        tot_cost = round(sum(r["made_cost"] for r in rows), 2)
        return {"rows": rows, "doctor_pct": pct, "doctor_pct_src": pct_src, "month": made["month"], "made_from": made["sources"],
                "revenue": tot_rev, "cost": tot_cost, "margin": round(tot_rev - tot_cost, 2),
                "margin_pct": round((tot_rev - tot_cost) * 100 / tot_rev, 1) if tot_rev else None,
                "materials": round(sum(r["made"] * r["materials"] for r in rows), 2),
                "no_norms": sum(1 for r in rows if r["no_norms"]), "settings": self.settings(), "pnl_modes": PNL_MODES}

    def _made(self, month=None):
        """Services made in the month: invoices made here plus Dentist Plus visits written off here (not billed here)."""
        try:
            y, m = map(int, str(month or date.today().strftime("%Y-%m"))[:7].split("-"))
            a = date(y, m, 1)
        except ValueError:
            a = date.today().replace(day=1)
        b = (a.replace(day=28) + timedelta(days=4)).replace(day=1)
        by, src = {}, {"invoices": 0, "visits": 0}
        for r in self.db.q("""SELECT items FROM invoices WHERE COALESCE(kind,'invoice')='invoice' AND created_at >= ? AND created_at < ?""",
                           (a.isoformat(), b.isoformat())):
            try:
                items = json.loads(r["items"] or "[]")
            except ValueError:
                items = []
            for it in items:
                if it.get("service_id"):
                    q = float(it.get("qty") or 1)
                    by[it["service_id"]] = by.get(it["service_id"], 0) + q
                    src["invoices"] += q
        for r in self.db.q("SELECT services FROM stock_visit_use WHERE status='done' AND start >= ? AND start < ?",
                           (a.isoformat(), b.isoformat())):
            try:
                items = json.loads(r["services"] or "[]")
            except ValueError:
                items = []
            for it in items:
                if it.get("service_id"):
                    q = float(it.get("qty") or 1)
                    by[it["service_id"]] = by.get(it["service_id"], 0) + q
                    src["visits"] += q
        return {"month": a.strftime("%Y-%m"), "by_service": by, "sources": src}

    def save_cost(self, f) -> dict:
        """The laboratory and other costs of a service and its own doctor's percent («» — the clinic's)."""
        f = f if isinstance(f, dict) else {}
        sid = f.get("service_id")
        if not sid or not self.db.one("SELECT 1 AS x FROM services WHERE id=?", (sid,)):
            raise ValueError("Услуга не найдена")
        lab, other = _num(f.get("lab"), "Лаборатория"), _num(f.get("other"), "Прочие затраты")
        if lab < 0 or other < 0:
            raise ValueError("Затраты не могут быть отрицательными")
        p = str(f.get("doctor_pct") if f.get("doctor_pct") is not None else "").strip()
        pct = None
        if p:
            pct = _num(p, "Процент врача")
            if not 0 <= pct <= 100:
                raise ValueError("Процент врача: от 0 до 100")
        with self.db.tx() as c:
            c.execute("""INSERT INTO service_costs(service_id, lab, other, doctor_pct, note, updated_at) VALUES(?,?,?,?,?,?)
                         ON CONFLICT(service_id) DO UPDATE SET lab=excluded.lab, other=excluded.other, doctor_pct=excluded.doctor_pct,
                         note=excluded.note, updated_at=excluded.updated_at""",
                      (sid, lab, other, pct, str(f.get("note") or "").strip()[:300], _now()))
        return next(r for r in self.costs()["rows"] if r["service_id"] == sid)


def stock_used(db, a, b):
    """The value of the materials that left the stock in [a, b): services, visits and write-offs (not transfers). None — no stock."""
    try:
        r = db.one("""SELECT COALESCE(SUM(-qty*price),0) AS v FROM stock_moves WHERE kind IN ('service','writeoff')
                      AND at >= ? AND at < ?""", (a, b))
        return round(r["v"] or 0, 2)
    except Exception:  # noqa: BLE001
        return None


def pnl_mode(db) -> str:
    try:
        r = db.one("SELECT v FROM stock_settings WHERE k='pnl_materials'")
        return r["v"] if r and r["v"] in PNL_MODES else "expenses"
    except Exception:  # noqa: BLE001
        return "expenses"
