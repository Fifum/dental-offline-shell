"""Dentist Plus partner API client (https://api2.dentist-plus.com/partner).

Per the partner documentation (https://api-balancer.dentist-plus.com/partner/docs/, OpenAPI partner-doc.json):
POST /auth {login, pass} -> {token, expires_at}; every other call carries «Authorization: Bearer <token>»,
the token expires and is then requested again. Lists take ?page&per_page (at most 200) and answer
{meta: {current_page, last_page, per_page, total}, data: [...]}; small dictionaries answer a plain array.
Errors come as {"error": "..."} (401 bad login, 404 «Запись не найдена»). No rate limit is documented;
429 / Retry-After is still honoured.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from normalize import get

MAX_PER_PAGE = 200      # documented maximum of ?per_page
TOKEN_MARGIN = 120      # seconds: a token this close to expires_at is renewed before the call


class ApiError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


class OfflineError(ApiError):
    pass


class AuthError(ApiError):
    """POST /auth answered an error (or no token): a write that needed the login was never sent."""


def connect_failed(e) -> bool:
    """True when the request never reached the server (no connection, DNS, refused, connect timeout, TLS handshake):
    then nothing was written. Any other connection error (dropped while sending or reading the answer) may come
    after the server did the write."""
    if isinstance(e, (requests.ConnectTimeout, requests.exceptions.ProxyError, requests.exceptions.SSLError)):
        return True
    try:
        from urllib3.exceptions import ConnectTimeoutError, NewConnectionError
        early = (NewConnectionError, ConnectTimeoutError)
    except ImportError:  # pragma: no cover
        early = ()
    seen, todo = set(), [e]
    while todo:
        x = todo.pop()
        if x is None or id(x) in seen:
            continue
        seen.add(id(x))
        if early and isinstance(x, early):
            return True
        todo += [getattr(x, "reason", None), x.__cause__, x.__context__]
        todo += [a for a in getattr(x, "args", ()) if isinstance(a, BaseException)]
    text = str(e)
    return any(m in text for m in ("Failed to establish a new connection", "NameResolutionError", "getaddrinfo failed"))


class DentistPlusClient:
    def __init__(self, base_url: str, login: str, password: str, timeout=25):
        self.base = base_url.rstrip("/")
        self.login, self.password = login, password
        self.timeout = timeout
        self.token: str | None = None
        self.token_exp: datetime | None = None   # expires_at of the token (UTC), None when the server gave none
        # the card threads share the client: one re-login at a time, and none when another thread already renewed
        # the token (Dentist Plus keeps only the newest token, so parallel logins log each other out)
        self._auth_lock = threading.Lock()
        self.token_gen = 0
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
            raise AuthError(self._err_text(data) or f"Ошибка авторизации (HTTP {r.status_code})", r.status_code)
        token = get(data, "token", "access_token", "data.token", "data.access_token", "api_token") if isinstance(data, dict) else None
        if not token:
            raise AuthError("Сервер не вернул токен авторизации", r.status_code)
        self.token = token
        self.token_exp = self._exp(data.get("expires_at") if isinstance(data, dict) else None)
        self.s.headers["Authorization"] = f"Bearer {token}"
        self.token_gen += 1
        return data

    @staticmethod
    def _exp(v):
        """expires_at «2023-05-21T13:38:48.290765Z» -> aware UTC datetime (None when absent or unreadable)."""
        if not v:
            return None
        try:
            d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    def _stale(self) -> bool:
        return not self.token or (self.token_exp is not None and
                                  (self.token_exp - datetime.now(timezone.utc)).total_seconds() < TOKEN_MARGIN)

    def _ensure_token(self):
        if self._stale():
            with self._auth_lock:
                if self._stale():  # another thread may have renewed it while this one waited
                    self.token = None
                    self.auth()

    def _reauth(self, gen):
        """401 for a request sent with token generation `gen`: log in again, unless another thread already did."""
        with self._auth_lock:
            if self.token_gen == gen:
                self.token = None
                self.auth()

    def request(self, path: str, params=None, _retry=2):
        self._ensure_token()
        if params and "per_page" in params:
            params = {**params, "per_page": min(MAX_PER_PAGE, max(1, int(params["per_page"])))}
        url = f"{self.base}/{path.lstrip('/')}"
        for attempt in range(4):
            gen = self.token_gen
            try:
                r = self.s.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt >= 2:
                    raise OfflineError(f"Нет связи с сервером: {e.__class__.__name__}")
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 401 and _retry:
                # the token was dropped (another login with the same account, or the server's own limit):
                # a fresh token, twice at most, the second time after a pause
                if _retry < 2:
                    time.sleep(3)
                self._reauth(gen)
                return self.request(path, params, _retry=_retry - 1)
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
        server (avoids duplicates); only a failure to connect (nothing was sent) is reported as offline. A connection
        dropped later may come after the server did the write: the result is unknown (ApiError, status None).
        401 (token expired) and 429 (too many requests) mean the server did not do the write, so those are repeated.
        A failed login on the way (AuthError) also means nothing was written: the caller may send again later."""
        self._ensure_token()
        url = f"{self.base}/{path.lstrip('/')}"
        reauth = True
        for attempt in range(4):
            gen = self.token_gen
            try:
                r = self.s.request(method.upper(), url, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                if connect_failed(e):
                    raise OfflineError(f"Нет связи с сервером: {e.__class__.__name__}")
                if isinstance(e, requests.Timeout):
                    raise ApiError("Сервер не ответил вовремя — результат неизвестен, проверьте в Dentist Plus", None)
                raise ApiError("Связь прервалась во время отправки — результат неизвестен, проверьте в Dentist Plus", None)
            if r.status_code == 401 and reauth:
                reauth = False
                self._reauth(gen)
                continue
            if r.status_code == 429 and attempt < 3:
                ra = r.headers.get("Retry-After", "")
                time.sleep(min(30, int(ra)) if ra.isdigit() else (3, 8, 15)[attempt])
                continue
            break
        return r.status_code, self._json(r)

    def paged(self, path: str, params=None, per_page=100, max_pages=500):
        """Iterate over all items of a list endpoint, whatever pagination it uses."""
        params = dict(params or {})
        per_page = min(MAX_PER_PAGE, max(1, int(per_page or 20)))
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
