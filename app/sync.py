"""Background sync worker: pulls Dentist Plus data into the local SQLite DB."""
from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import json

import config
from api_client import ApiError, DentistPlusClient, OfflineError
from normalize import as_id, get, utcnow, visit_fields

log = logging.getLogger("sync")

HOURLY = 60 * 60   # dictionaries (chairs, visit statuses) and the doctors' schedule change rarely
SCHEDULE_LIMIT = 100   # GET /schedule returns at most 100 rows: a fuller answer is asked again in halves
CARD_PAUSE_S = 0.7     # pause between patient cards asked one by one after a 429 / 5xx
RETRY_MAX = 2000       # cards remembered for the next sync


def _card_reason(e) -> str:
    """Short reason of a patient card that did not load, for the sync log and the developer's report."""
    st = getattr(e, "status", None)
    if isinstance(st, int):
        return "HTTP 5xx" if st >= 500 else f"HTTP {st}"
    if isinstance(e, OfflineError) or "не ответил" in str(e):
        return "нет ответа"
    if isinstance(e, ApiError):
        return "ошибка API"
    return e.__class__.__name__


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


class SyncWorker(threading.Thread):
    def __init__(self, db):
        super().__init__(daemon=True, name="sync")
        self.db = db
        self.wake = threading.Event()
        self.stop_flag = False
        self.follower = False
        self.lock = threading.Lock()
        self.state = {
            "running": False, "online": None, "phase": "", "progress": 0,
            "last_ok": db.meta_get("last_ok"), "last_error": db.meta_get("last_error"),
            "last_attempt": None,
        }

    # -------------------------------------------------------------- API --
    def trigger(self):
        self.wake.set()

    def status(self):
        with self.lock:
            return dict(self.state)

    def _set(self, **kw):
        with self.lock:
            self.state.update(kw)

    # ------------------------------------------------------------- loop --
    def run(self):
        # Let the window open and show the saved data first: the first sync writes to the database and would
        # make the first screens wait. A fresh database (nothing synced yet) is filled almost at once.
        delay = 6 if self.db.meta_get("last_ok") else 1.5
        if self.wake.wait(delay):  # «Обновить» pressed meanwhile: go now
            self.wake.clear()
        while not self.stop_flag:
            s = config.load_settings()
            ok = self.sync_once(s)
            # while offline: re-check every 30 s, sync immediately when the link is back
            wait = max(1, int(s.get("interval_min", 5))) * 60 if ok else 30
            if self.follower:  # the copy from the main computer is cheap (the clinic network): every minute
                wait = 60
            self.wake.wait(wait)
            self.wake.clear()

    def sync_once(self, s=None) -> bool:
        s = s or config.load_settings()
        if s.get("demo"):
            from demo import ensure_demo
            ensure_demo(self.db)
            from demo import ensure_office, ensure_director, ensure_crm
            ensure_office(self.db)
            ensure_director(self.db)
            ensure_crm(self.db)
            if s.get("transfer_mode") == "auto":
                from pusher import simulate_demo
                simulate_demo(self.db)
            self._set(online=None, phase="Демо-режим", running=False, last_ok=self.db.meta_get("last_ok"))
            return True
        import dp_main
        role = dp_main.role(self.db)
        self.follower = role == "follower"
        if self.follower:  # 3.7.2: another computer of the clinic talks to Dentist Plus — take the copy from it
            return self._follow()
        password = config.unprotect(s.get("pass_enc", ""))
        if not s.get("login") or not password:
            self._set(phase="Укажите логин и пароль API в настройках", online=None)
            return True
        if role == "solo" and dp_main._in_network():
            dp_main.claim(self.db)  # the first computer of the clinic network with a login talks to Dentist Plus

        started = utcnow()
        self._set(running=True, phase="Проверка связи…", progress=0, last_attempt=started)
        client = DentistPlusClient(s["base_url"], s["login"], password)
        counts = {}
        try:
            if not client.is_online():
                raise OfflineError("Нет интернета")
            self._set(online=True, phase="Авторизация…")
            client.auth()
            if s.get("transfer_mode") == "auto" and self.db.pending_count():
                from pusher import Pusher
                self._set(phase="Отправка изменений в Dentist Plus…", progress=2)
                pushed = Pusher(self.db, client, s).run()
                counts["pushed"] = pushed
            self._pull(client, s, counts)
            self._pull_more(client, s, counts)
            from pusher import apply_patient_edits
            apply_patient_edits(self.db)
            self.db.purge(int(s["days_back"]))
            self.db.cleanup_transferred(started)
            from pusher import merge_pushed_patients
            merge_pushed_patients(self.db)
            self.db.meta_set("last_ok", utcnow())
            self.db.meta_set("last_error", "")
            p = counts.get("pushed") or {}
            note = ""
            if p:
                note = f" · отправлено в DP: {p['sent']}" + (f", ошибок: {p['errors']}" if p["errors"] else "") + \
                       (f", проверить вручную: {p['unknown'] + p['warnings']}" if p["unknown"] or p["warnings"] else "")
            self.db.log_sync(started, True, "Успешно" + note, counts)
            self._set(running=False, phase="Готово", progress=100, last_ok=utcnow(), last_error="")
            return True
        except OfflineError as e:
            self._set(running=False, online=False, phase="Офлайн — работаем с сохранёнными данными", last_error=str(e))
            return False
        except ApiError as e:
            msg = f"Ошибка API: {e}"
            self._fail(started, msg, counts)
            return e.status is not None and e.status in (401, 403, 422)  # bad creds: don't hammer every 30 s
        except Exception as e:  # noqa: BLE001
            log.error("sync failed\n%s", traceback.format_exc())
            self._fail(started, f"Сбой синхронизации: {e}", counts)
            return False

    def _follow(self) -> bool:
        """3.7.2: the copy of the Dentist Plus data from the computer that talks to Dentist Plus (dp_main.py)."""
        import dp_main
        started = utcnow()
        self._set(running=True, phase="Данные Dentist Plus с компьютера клиники…", online=None, last_attempt=started)
        try:
            r = dp_main.pull(self.db)
        except dp_main.DpMainError as e:
            msg = str(e)
            self.db.meta_set("last_error", msg)
            self._set(running=False, phase=msg, last_error=msg)
            return True
        except Exception as e:  # noqa: BLE001
            log.error("dp mirror failed\n%s", traceback.format_exc())
            msg = f"Сбой получения данных Dentist Plus: {e}"
            self.db.meta_set("last_error", msg)
            self._set(running=False, phase=msg, last_error=msg)
            return True
        err = f"{r['error']} (на компьютере «{r['name']}»)" if r["error"] else ""
        if r["stamp"]:
            self.db.meta_set("last_ok", r["stamp"])
        self.db.meta_set("last_error", err)
        if r["changed"]:
            self.db.log_sync(started, True, f"Данные Dentist Plus с компьютера «{r['name']}»", {**r["counts"], "via": r["name"]})
        self._set(running=False, phase=f"Данные Dentist Plus — через компьютер «{r['name']}»", progress=100,
                  last_ok=r["stamp"] or self.db.meta_get("last_ok"), last_error=err)
        return True

    def _fail(self, started, msg, counts):
        self.db.meta_set("last_error", msg)
        self.db.log_sync(started, False, msg, counts)
        self._set(running=False, phase=msg, last_error=msg)

    # ------------------------------------------------------------ steps --
    def _pull(self, c: DentistPlusClient, s: dict, counts: dict):
        per_page = int(s.get("per_page", 100))

        self._set(phase="Филиалы…", progress=3)
        try:
            branches = list(c.paged("branches", per_page=per_page))
            self.db.upsert_branches(branches)
            counts["branches"] = len(branches)
        except ApiError as e:
            counts["branches_error"] = str(e)

        self._set(phase="Врачи…", progress=6)
        try:
            doctors = list(c.paged("doctors", per_page=per_page))
            self.db.upsert_doctors(doctors)
            counts["doctors"] = len(doctors)
        except ApiError as e:
            counts["doctors_error"] = str(e)

        # price list (GET /services; deleted services are not returned without with_deleted=1)
        try:
            from normalize import get as g
            svc = list(c.paged("services", per_page=per_page, max_pages=50))
            with self.db.tx() as cx:
                for it in svc:
                    if not isinstance(it, dict) or it.get("id") is None or it.get("deleted") in (True, 1):
                        continue
                    price = g(it, "price", "cost", "amount", "sum", default=0)
                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        price = 0.0
                    cx.execute("INSERT OR REPLACE INTO services VALUES(?,?,?,?,?,?,1)",
                               (f"api_{it['id']}", str(g(it, "code", "article", "number", default="") or ""),
                                str(g(it, "title", "name", default="Услуга") or ""), price,
                                str(g(it, "category.title", "category.name", "group", "category", default="") or ""), "api"))
            counts["services"] = len(svc)
        except ApiError:
            pass

        # visits in chunks: oldest -> newest, each chunk replaced atomically
        today = date.today()
        start = today - timedelta(days=int(s["days_back"]))
        end = today + timedelta(days=int(s["days_forward"]))
        step = max(1, int(s.get("chunk_days", 7)))
        chunks = []
        d = start
        while d <= end:
            chunks.append((d, min(end, d + timedelta(days=step - 1))))
            d += timedelta(days=step)
        patient_ids: set[str] = set()
        embedded_patients = []
        total_visits = 0
        for i, (a, b) in enumerate(chunks):
            self._set(phase=f"Записи {a:%d.%m}–{b:%d.%m}…", progress=8 + int(52 * i / len(chunks)))
            # with_deleted=1: cancelled visits come too (is_cancelled) and are shown as «Отменён» instead of vanishing
            params = {s["visit_from_param"]: a.isoformat(), s["visit_to_param"]: b.isoformat(), "with_deleted": 1}
            rows = []
            for raw in c.paged("visits", params, per_page=per_page):
                if not isinstance(raw, dict):
                    continue
                f = visit_fields(raw)
                f["raw"] = raw
                if f["start"] and not (a.isoformat() <= f["start"][:10] <= b.isoformat()):
                    continue  # API ignored the date filter for this one
                rows.append(f)
                if f["patient_id"]:
                    patient_ids.add(f["patient_id"])
                if f["patient"]:
                    embedded_patients.append(f["patient"])
                if f["doctor"] and f["doctor"].get("id") is not None:
                    self.db.upsert_doctors([f["doctor"]])
            self.db.replace_visits(a.isoformat(), b.isoformat(), rows)
            total_visits += len(rows)
        counts["visits"] = total_visits
        if embedded_patients:
            self.db.upsert_patients(embedded_patients)

        if s.get("sync_all_patients"):
            self._set(phase="Список пациентов…", progress=62)
            batch = []
            for p in c.paged("patients", per_page=per_page):
                batch.append(p)
                if len(batch) >= 500:
                    self.db.upsert_patients(batch)
                    batch = []
            self.db.upsert_patients(batch)

        # patient cards (detail + extras): 4 parallel requests. 3.7.1: a card that did not load is not lost —
        # on «too many requests» (429), a server error (5xx) or a timeout the parallel pass stops sending, the rest
        # are asked one by one with a pause, and what still failed is asked again by the next sync
        # (meta «patients_retry»). A 404 is a patient deleted or merged in Dentist Plus: counted, not retried.
        retry_before = self._retry_list()
        ids = sorted(patient_ids | set(retry_before))
        extras = [e for e in s.get("patient_extras", []) if e.get("path")]
        disabled_extras: set[str] = set()
        slow = threading.Event()   # set at the first transient error: the parallel pass stops sending
        done = 0
        reasons: dict[str, int] = {}
        examples: dict[str, str] = {}
        deferred: list[str] = []
        failed_transient: list[str] = []
        loaded = 0

        def fetch(pid, parallel=True):
            if parallel and slow.is_set():
                return pid, None
            detail = c.request(f"patients/{pid}")
            if isinstance(detail, dict) and isinstance(detail.get("data"), dict):
                detail = detail["data"]
            out = {"detail": detail, "extras": {}}
            for ex in extras:
                if ex["key"] in disabled_extras:
                    continue
                params = {k: str(v).replace("{id}", pid) for k, v in (ex.get("params") or {}).items()}
                path = ex["path"].replace("{id}", pid)
                try:
                    items = list(c.paged(path, params, per_page=per_page, max_pages=20))
                    out["extras"][ex["key"]] = items
                except ApiError as e:
                    if e.status in (400, 403, 404, 405, 422):
                        disabled_extras.add(ex["key"])
            return pid, out

        def save(pid, out):
            nonlocal loaded
            if isinstance(out["detail"], dict):
                out["detail"].setdefault("id", pid)
                self.db.upsert_patients([out["detail"]], detail=True)
            for k, items in out["extras"].items():
                self.db.upsert_extra(pid, k, items)
            loaded += 1

        def failed(pid, e, final):
            """Count the reason; a transient one is retried (now one by one, or by the next sync)."""
            reason = _card_reason(e)
            transient = reason in ("HTTP 429", "HTTP 5xx", "нет ответа")
            if transient and not final:
                slow.set()
                deferred.append(pid)
                return
            if transient:
                failed_transient.append(pid)
            reasons[reason] = reasons.get(reason, 0) + 1
            examples.setdefault(reason, str(e)[:160])

        def progress():
            if done % 5 == 0 or done == len(ids):
                self._set(phase=f"Карты пациентов {done}/{len(ids)}…", progress=62 + int(37 * done / max(1, len(ids))))

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [(pid, pool.submit(fetch, pid)) for pid in ids]
            for pid, fut in futs:
                n_deferred = len(deferred)
                try:
                    _, out = fut.result()
                    if out is None:
                        deferred.append(pid)
                    else:
                        save(pid, out)
                except OfflineError as e:
                    if loaded == 0 and done == 0:
                        raise  # the link is gone, not one card
                    failed(pid, e, final=False)
                except Exception as e:  # noqa: BLE001
                    failed(pid, e, final=False)
                if len(deferred) == n_deferred:  # a deferred card is counted when it is asked again
                    done += 1
                    progress()
        for i, pid in enumerate(deferred):
            if self.stop_flag:
                failed_transient.extend(deferred[i:])
                reasons["не успели"] = reasons.get("не успели", 0) + len(deferred) - i
                break
            time.sleep(CARD_PAUSE_S)
            try:
                _, out = fetch(pid, parallel=False)
                save(pid, out)
            except OfflineError as e:  # the link is gone: the rest waits for the next sync
                failed(pid, e, final=True)
                rest = deferred[i + 1:]
                failed_transient.extend(rest)
                if rest:
                    reasons["нет ответа"] = reasons.get("нет ответа", 0) + len(rest)
                break
            except Exception as e:  # noqa: BLE001
                failed(pid, e, final=True)
            done += 1
            progress()

        self._save_retry_list(failed_transient)
        counts["patients"] = len(ids)
        errors = sum(reasons.values())
        if errors:
            counts["patient_errors"] = errors
            counts["patient_error_reasons"] = dict(sorted(reasons.items()))
            log.warning("patient cards: %d of %d not loaded: %s; e.g. %s", errors, len(ids),
                        ", ".join(f"{k} — {v}" for k, v in sorted(reasons.items())),
                        "; ".join(f"{k}: {v}" for k, v in sorted(examples.items())))
        if deferred:
            counts["patient_retried_slowly"] = len(deferred)
        if failed_transient:
            counts["patient_retry_next_sync"] = len(failed_transient)
        if retry_before:
            counts["patient_retry_from_last_sync"] = len(retry_before)
        if disabled_extras:
            counts["extras_unavailable"] = sorted(disabled_extras)

    def _retry_list(self) -> list[str]:
        try:
            v = json.loads(self.db.meta_get("patients_retry") or "[]")
            return [str(x) for x in v if x][:RETRY_MAX] if isinstance(v, list) else []
        except ValueError:
            return []

    def _save_retry_list(self, ids):
        self.db.meta_set("patients_retry", json.dumps(sorted(set(ids))[:RETRY_MAX]))

    # ------------------------------------------------- documented extras --
    def _pull_more(self, c: DentistPlusClient, s: dict, counts: dict):
        """Dictionaries for the automatic transfer, Dentist Plus payments for «Сверка», the doctors' schedule.
        Each part is optional: an error is noted in the sync log and the rest goes on."""
        today = date.today()
        start = today - timedelta(days=int(s["days_back"]))
        end = today + timedelta(days=int(s["days_forward"]))
        hourly = self._due("dp_dicts_at")
        if hourly:
            for key, path in (("dp_chairs", "chairs"), ("dp_record_statuses", "record_statuses")):
                try:
                    items = [x for x in c.paged(path, per_page=200, max_pages=10) if isinstance(x, dict)]
                    self.db.meta_set(key, json.dumps(items, ensure_ascii=False))
                except ApiError as e:
                    counts[f"{path}_error"] = str(e)
            self.db.meta_set("dp_dicts_at", str(int(time.time())))

        self._set(phase="Оплаты Dentist Plus…")
        try:
            pays = list(c.paged("payments", {"date_from": start.isoformat(), "date_to": end.isoformat()}, per_page=200))
            self._save_payments(start.isoformat(), end.isoformat(), pays)
            counts["dp_payments"] = len(pays)
        except ApiError as e:
            counts["payments_error"] = str(e)

        if hourly or not self.db.one("SELECT 1 AS x FROM dp_schedule LIMIT 1"):
            self._set(phase="Расписание врачей…")
            try:
                n = self._pull_schedule(c, today - timedelta(days=7), end)
                counts["dp_schedule"] = n["received"]
                counts["dp_schedule_saved"] = n["saved"]
                if n["skipped"]:
                    counts["dp_schedule_skipped"] = n["skipped"]
            except ApiError as e:
                counts["schedule_error"] = str(e)

    def _due(self, key):
        try:
            return time.time() - int(self.db.meta_get(key) or 0) >= HOURLY
        except ValueError:
            return True

    def _save_payments(self, a, b, pays):
        now = utcnow()
        end = (date.fromisoformat(b) + timedelta(days=1)).isoformat()
        with self.db.tx() as cx:
            cx.execute("DELETE FROM dp_payments WHERE date >= ? AND date < ?", (a, end))
            for p in pays:
                if not isinstance(p, dict) or p.get("id") is None:
                    continue
                cx.execute("INSERT OR REPLACE INTO dp_payments VALUES(?,?,?,?,?,?,?,?)",
                           (str(p["id"]), str(p.get("date") or "")[:19], _num(get(p, "sum", "amount", default=0)),
                            as_id(get(p, "client_id", "patient_id")), as_id(p.get("visit_id")),
                            str(p.get("payment_type") or ""), json.dumps(p, ensure_ascii=False), now))

    def _pull_schedule(self, c: DentistPlusClient, a: date, b: date) -> int:
        """GET /schedule per doctor in windows of up to 31 days (the answer is capped at 100 rows)."""
        doctors = [d["id"] for d in self.db.q("SELECT id FROM doctors")]
        rows = []

        def fetch(doc, x, y):
            items = c.request("schedule", {"doctor_id": doc, "date_from": x.isoformat(), "date_to": y.isoformat()})
            items = items if isinstance(items, list) else (c._items(items)[0] if isinstance(items, dict) else [])
            if len(items) >= SCHEDULE_LIMIT and x < y:
                mid = x + (y - x) // 2
                return fetch(doc, x, mid) + fetch(doc, mid + timedelta(days=1), y)
            return [i for i in items if isinstance(i, dict)]

        for doc in doctors:
            x = a
            while x <= b:
                y = min(b, x + timedelta(days=30))
                rows += fetch(doc, x, y)
                x = y + timedelta(days=1)
        now = utcnow()
        skipped = 0
        with self.db.tx() as cx:
            cx.execute("DELETE FROM dp_schedule WHERE day >= ? AND day <= ?", (a.isoformat(), b.isoformat()))
            for r in rows:
                day, doc = str(r.get("day") or "")[:10], as_id(r.get("doctor_id"))
                if not day or not doc or not r.get("time_from") or not r.get("time_to"):
                    skipped += 1  # 3.7.1: counted, so «пришло» = «сохранено» + «пропущено» in the sync log
                    continue
                cx.execute("INSERT OR REPLACE INTO dp_schedule VALUES(?,?,?,?,?,?,?)",
                           (doc, day, as_id(r.get("chair_id")) or "", as_id(r.get("branch_id")),
                            str(r["time_from"])[:5], str(r["time_to"])[:5], now))
            saved = cx.execute("SELECT COUNT(*) FROM dp_schedule WHERE day >= ? AND day <= ?",
                               (a.isoformat(), b.isoformat())).fetchone()[0]
        return {"received": len(rows), "saved": saved, "skipped": skipped}


def diagnostics(s: dict, db=None) -> dict:
    """Sample every endpoint once — used in Settings to see real field names."""
    if db is not None:
        import dp_main
        why = dp_main.blocked_reason(db)
        if why:
            return {"auth": why}
    password = config.unprotect(s.get("pass_enc", ""))
    if not s.get("login") or not password:
        return {"auth": "Сначала укажите логин и пароль API и нажмите «Сохранить»"}
    c = DentistPlusClient(s["base_url"], s["login"], password)
    out = {}
    try:
        c.auth()
        out["auth"] = "OK"
    except ApiError as e:
        return {"auth": f"Ошибка: {e}"}
    today = date.today().isoformat()
    probes = [("branches", {}), ("doctors", {}),
              ("visits", {s["visit_from_param"]: today, s["visit_to_param"]: today}),
              ("patients", {"per_page": 2})]
    first_patient = None
    for path, params in probes:
        try:
            data = c.request(path, {**params, "page": 1, "per_page": 3})
            items, _, _ = c._items(data)
            out[path] = {"count_on_page": len(items), "sample": items[:2],
                         "envelope_keys": list(data.keys()) if isinstance(data, dict) else "list"}
            if path == "visits" and items:
                first_patient = visit_fields(items[0])["patient_id"]
            if path == "patients" and items and not first_patient:
                first_patient = str(items[0].get("id"))
        except ApiError as e:
            out[path] = f"Ошибка: {e}"
    if first_patient:
        try:
            out[f"patients/{first_patient}"] = c.request(f"patients/{first_patient}")
        except ApiError as e:
            out[f"patients/{first_patient}"] = f"Ошибка: {e}"
        for ex in s.get("patient_extras", []):
            params = {k: str(v).replace("{id}", first_patient) for k, v in (ex.get("params") or {}).items()}
            try:
                out[ex["path"]] = c.request(ex["path"].replace("{id}", first_patient), {**params, "per_page": 3})
            except ApiError as e:
                out[ex["path"]] = f"Ошибка: {e}"
    return out
