"""Dentist Plus partner API client (https://api2.dentist-plus.com/partner).

Confirmed: POST /auth {login, pass} -> token; GET /branches, /doctors, /patients,
/patients/{id}, /visits, /schedule, /diagnoses require the token.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import requests

from normalize import get


class ApiError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


class OfflineError(ApiError):
    pass


class DentistPlusClient:
    def __init__(self, base_url: str, login: str, password: str, timeout=25):
        self.base = base_url.rstrip("/")
        self.login, self.password = login, password
        self.timeout = timeout
        self.token: str | None = None
        self.s = requests.Session()
        self.s.headers.update({"Accept": "application/json", "User-Agent": "DentistPlus-offline-shell/1.3"})

    # ------------------------------------------------------------ basics --
    def is_online(self) -> bool:
        host = urlparse(self.base)
        try:
            requests.head(f"{host.scheme}://{host.netloc}/", timeout=6, allow_redirects=False)
            return True
        except requests.RequestException:
            return False

    def auth(self):
        try:
            r = self.s.post(f"{self.base}/auth", json={"login": self.login, "pass": self.password}, timeout=self.timeout)
        except requests.RequestException as e:
            raise OfflineError(f"Нет связи с сервером: {e.__class__.__name__}")
        data = self._json(r)
        if r.status_code >= 400:
            raise ApiError(self._err_text(data) or f"Ошибка авторизации (HTTP {r.status_code})", r.status_code)
        token = get(data, "token", "access_token", "data.token", "data.access_token", "api_token") if isinstance(data, dict) else None
        if not token:
            raise ApiError("Сервер не вернул токен авторизации")
        self.token = token
        self.s.headers["Authorization"] = f"Bearer {token}"
        return data

    def request(self, path: str, params=None, _retry=True):
        if not self.token:
            self.auth()
        url = f"{self.base}/{path.lstrip('/')}"
        for attempt in range(4):
            try:
                r = self.s.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt >= 2:
                    raise OfflineError(f"Нет связи с сервером: {e.__class__.__name__}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 401 and _retry:
                self.token = None
                self.auth()
                return self.request(path, params, _retry=False)
            if r.status_code == 429 and attempt < 3:   # rate limit: honour Retry-After, else 3/8/15 s
                ra = r.headers.get("Retry-After", "")
                time.sleep(min(30, int(ra)) if ra.isdigit() else (3, 8, 15)[attempt])
                continue
            if r.status_code >= 500 and attempt < 2:   # server error: two quick retries, then give up
                time.sleep((2, 5)[attempt])
                continue
            data = self._json(r)
            if r.status_code >= 400:
                raise ApiError(self._err_text(data) or f"HTTP {r.status_code} для {path}", r.status_code)
            return data
        raise ApiError(f"Сервер не ответил на {path} после нескольких попыток")

    def write(self, method: str, path: str, body: dict):
        """POST/PUT/PATCH. Returns (status_code, json). Never retries a write after it reached the
        server (avoids duplicates); only connection errors before sending are reported as offline."""
        if not self.token:
            self.auth()
        url = f"{self.base}/{path.lstrip('/')}"
        try:
            r = self.s.request(method.upper(), url, json=body, timeout=self.timeout)
        except requests.ConnectionError as e:
            raise OfflineError(f"Нет связи с сервером: {e.__class__.__name__}")
        except requests.Timeout:
            raise ApiError("Сервер не ответил вовремя — результат неизвестен, проверьте в Dentist Plus", None)
        if r.status_code == 401:
            self.token = None
            self.auth()
            r = self.s.request(method.upper(), url, json=body, timeout=self.timeout)
        return r.status_code, self._json(r)

    def paged(self, path: str, params=None, per_page=100, max_pages=500):
        """Iterate over all items of a list endpoint, whatever pagination it uses."""
        params = dict(params or {})
        page = 1
        seen_first = None
        while page <= max_pages:
            data = self.request(path, {**params, "page": page, "per_page": per_page})
            items, last_page, has_next = self._items(data)
            if not items:
                return
            first_id = items[0].get("id") if isinstance(items[0], dict) else None
            if first_id is not None and first_id == seen_first:
                return  # endpoint ignores ?page — avoid infinite loop
            seen_first = first_id if page == 1 else seen_first
            yield from items
            if last_page is not None:
                if page >= int(last_page):
                    return
            elif has_next is False or (has_next is None and len(items) < per_page):
                return
            page += 1
            time.sleep(0.15)

    # ----------------------------------------------------------- helpers --
    @staticmethod
    def _items(data):
        if isinstance(data, list):
            return data, None, False
        if not isinstance(data, dict):
            return [], None, False
        items = None
        for key in ("data", "items", "results", "list", "rows", "visits", "patients", "doctors", "branches"):
            val = data.get(key)
            if isinstance(val, list):
                items = val
                break
            if isinstance(val, dict) and isinstance(val.get("data"), list):  # Laravel paginator inside "data"
                items = val["data"]
                data = {**data, **val}
                break
        if items is None:
            return ([data] if data.get("id") is not None else []), None, False
        last = get(data, "meta.last_page", "last_page", "pagination.last_page", "pagination.total_pages", "pages", "total_pages")
        nxt = get(data, "links.next", "next_page_url", "meta.next", "pagination.next")
        has_next = None
        if "links" in data or "next_page_url" in data:
            has_next = bool(nxt)
        try:
            last = int(last) if last is not None else None
        except (TypeError, ValueError):
            last = None
        return items, last, has_next

    @staticmethod
    def _json(r):
        try:
            return r.json()
        except ValueError:
            return {"error": r.text[:300]}

    @staticmethod
    def _err_text(data):
        if isinstance(data, dict):
            msg = data.get("error") or data.get("message")
            if isinstance(msg, (dict, list)):
                msg = str(msg)
            if isinstance(msg, str):
                msg = re.sub(r"\s*\(and \d+ more errors?\)", "", msg).strip()
            return msg
        return None
