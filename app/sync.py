"""Background sync worker: pulls Dentist Plus data into the local SQLite DB."""
from __future__ import annotations

import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import config
from api_client import ApiError, DentistPlusClient, OfflineError
from normalize import utcnow, visit_fields

log = logging.getLogger("sync")


class SyncWorker(threading.Thread):
    def __init__(self, db):
        super().__init__(daemon=True, name="sync")
        self.db = db
        self.wake = threading.Event()
        self.stop_flag = False
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
        time.sleep(1.5)
        while not self.stop_flag:
            s = config.load_settings()
            ok = self.sync_once(s)
            # while offline: re-check every 30 s, sync immediately when the link is back
            wait = max(1, int(s.get("interval_min", 5))) * 60 if ok else 30
            self.wake.wait(wait)
            self.wake.clear()

    def sync_once(self, s=None) -> bool:
        s = s or config.load_settings()
        if s.get("demo"):
            from demo import ensure_demo
            ensure_demo(self.db)
            from demo import ensure_office
            ensure_office(self.db)
            if s.get("transfer_mode") == "auto":
                from pusher import simulate_demo
                simulate_demo(self.db)
            self._set(online=None, phase="Демо-режим", running=False, last_ok=self.db.meta_get("last_ok"))
            return True
        password = config.unprotect(s.get("pass_enc", ""))
        if not s.get("login") or not password:
            self._set(phase="Укажите логин и пароль API в настройках", online=None)
            return True

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

        # price list, if the partner API exposes it (endpoint name not documented)
        try:
            from normalize import get as g
            svc = list(c.paged("services", per_page=per_page, max_pages=50))
            with self.db.tx() as cx:
                for it in svc:
                    if not isinstance(it, dict) or it.get("id") is None:
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
            params = {s["visit_from_param"]: a.isoformat(), s["visit_to_param"]: b.isoformat()}
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

        # patient cards (detail + extras), 4 parallel requests
        ids = sorted(patient_ids)
        extras = [e for e in s.get("patient_extras", []) if e.get("path")]
        disabled_extras: set[str] = set()
        done = 0
        errors = 0

        def fetch(pid):
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

        with ThreadPoolExecutor(max_workers=4) as pool:
            for fut in [pool.submit(fetch, pid) for pid in ids]:
                try:
                    pid, out = fut.result()
                    if isinstance(out["detail"], dict):
                        out["detail"].setdefault("id", pid)
                        self.db.upsert_patients([out["detail"]], detail=True)
                    for k, items in out["extras"].items():
                        self.db.upsert_extra(pid, k, items)
                except OfflineError:
                    raise
                except Exception:  # noqa: BLE001
                    errors += 1
                done += 1
                if done % 5 == 0 or done == len(ids):
                    self._set(phase=f"Карты пациентов {done}/{len(ids)}…", progress=62 + int(37 * done / max(1, len(ids))))
        counts["patients"] = len(ids)
        if errors:
            counts["patient_errors"] = errors
        if disabled_extras:
            counts["extras_unavailable"] = sorted(disabled_extras)


def diagnostics(s: dict) -> dict:
    """Sample every endpoint once — used in Settings to see real field names."""
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
