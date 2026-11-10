"""2.14: the administrators' expenses of the day and the day report by e-mail.

An administrator writes down every expense of the day — with a document (receipt, invoice) or without one — and
sees only today's own entries: next morning the list is empty again. The history is seen only by those with the
«Бухгалтерия» right (the director). At the set time (or when the cash shift is closed, or by the button) the
report of the day — expenses, cash by payment methods, the cash shift — goes to the owner's e-mail with an Excel
file. Without internet the report waits and goes as soon as the connection is back.

Mail goes through an ordinary mailbox of the clinic (Yandex, Mail.ru, Gmail…) with an application password,
which is stored encrypted (DPAPI). Settings are kept on the computer that sends (usually the front desk).
`day_reports` (which day was sent) syncs between laptops, so a second computer does not send the same day.

2.14.1: the report can also go to Telegram through the clinic's own bot (Bot API over HTTPS, no server of ours):
the owner makes a bot at @BotFather, presses «Старт» in it, and the program finds that chat. Mail and Telegram
are separate channels: if one of them failed, only that one is sent again."""
from __future__ import annotations

import logging
import smtplib
import ssl
import threading
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import config

TG_API = "https://api.telegram.org"
TG_LIMIT = 3900  # one Telegram message holds 4096 characters

log = logging.getLogger("daily")

SCHEMA = """
CREATE TABLE IF NOT EXISTS day_reports(
    day TEXT PRIMARY KEY, status TEXT, sent_at TEXT, sent_to TEXT, by TEXT, error TEXT, totals TEXT, updated_at TEXT,
    channels TEXT);
"""
METHODS = ["Наличные из кассы", "Карта клиники", "Перевод", "Свои деньги сотрудника"]
# what the front desk usually pays for during a day — first in the list
DAY_CATEGORIES = ["Хозяйственные расходы", "Транспорт и доставка", "Материалы и закупки", "Ремонт и обслуживание", "Прочее"]
DEFAULTS = {"enabled": False, "to": "", "host": "smtp.yandex.ru", "port": 465, "security": "ssl", "login": "", "pass_enc": "",
            "time": "21:00", "on_close": True, "tg_on": False, "tg_token_enc": "", "tg_bot": "", "tg_chats": []}
PROVIDERS = {"yandex": ("smtp.yandex.ru", 465, "ssl"), "mail": ("smtp.mail.ru", 465, "ssl"), "gmail": ("smtp.gmail.com", 465, "ssl")}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _rub(v):
    return f"{round(v or 0):,}".replace(",", " ") + " ₽"


def _fmt(d):
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}"


def settings() -> dict:
    return {**DEFAULTS, **(config.load_settings().get("day_report") or {})}


def public_settings() -> dict:
    s = settings()
    return {k: s[k] for k in ("enabled", "to", "host", "port", "security", "login", "time", "on_close", "tg_on", "tg_bot", "tg_chats")} | {
        "has_pass": bool(s["pass_enc"]), "has_tg_token": bool(s["tg_token_enc"]), "methods": METHODS}


def channels(s=None) -> list[str]:
    """Where the report goes: 'mail', 'tg'."""
    s = s or settings()
    return [c for c, on in (("mail", s["enabled"]), ("tg", s["tg_on"])) if on]


def save_settings(f: dict) -> dict:
    cur = settings()
    new = {**cur}
    for k in ("to", "host", "login", "time", "security"):
        if k in f:
            new[k] = " ".join(str(f[k] or "").split())[:200]
    if "port" in f:
        try:
            new["port"] = int(f["port"])
        except (TypeError, ValueError):
            raise ValueError("Порт — число, обычно 465") from None
    for k in ("enabled", "on_close", "tg_on"):
        if k in f:
            new[k] = bool(f[k])
    if f.get("password"):
        new["pass_enc"] = config.protect(str(f["password"]).strip())
    if f.get("tg_token"):
        token = "".join(str(f["tg_token"]).split())
        if ":" not in token:
            raise ValueError("Токен бота выглядит так: 1234567890:AA… — скопируйте его из сообщения @BotFather целиком")
        if config.unprotect(cur["tg_token_enc"] or "") != token:
            new.update(tg_token_enc=config.protect(token), tg_bot="", tg_chats=[])  # another bot: its chats are other
    if isinstance(f.get("tg_chats"), list):
        chats = []
        for c in f["tg_chats"]:
            if isinstance(c, dict) and str(c.get("id") or "").lstrip("-").isdigit():
                chats.append({"id": int(c["id"]), "name": str(c.get("name") or "")[:80]})
        new["tg_chats"] = chats[:10]
    if "tg_bot" in f:
        new["tg_bot"] = str(f["tg_bot"] or "")[:64]
    if new["security"] not in ("ssl", "starttls", "none"):
        new["security"] = "ssl"
    try:
        datetime.strptime(new["time"], "%H:%M")
    except ValueError:
        raise ValueError("Время отправки — в виде 21:00") from None
    if new["enabled"]:
        to = _emails(new["to"])
        if not to:
            raise ValueError("Укажите почту, куда отправлять отчёт")
        if not new["host"] or not new["login"] or not new["pass_enc"]:
            raise ValueError("Укажите почтовый сервер, ящик-отправитель и его пароль приложения")
    if new["tg_on"]:
        if not new["tg_token_enc"]:
            raise ValueError("Вставьте токен бота от @BotFather")
        if not new["tg_chats"]:
            raise ValueError("Выберите, кому бот отправляет отчёт: владелец пишет боту «Старт», затем «Найти, кто написал боту»")
    config.save_settings({"day_report": new})
    return public_settings()


def _emails(text):
    out = []
    for x in str(text or "").replace(";", ",").split(","):
        x = x.strip()
        if x and "@" in x and "." in x.split("@")[-1] and " " not in x:
            out.append(x)
    return out


class Daily:
    def __init__(self, db, acc, fin):
        self.db, self.acc, self.fin = db, acc, fin
        with db._lock:
            db.conn.executescript(SCHEMA)
            have = {r[1] for r in db.conn.execute("PRAGMA table_info(expenses)")}
            for col in ("doc INTEGER", "login TEXT"):  # 2.14: with or without a document, who wrote it down
                if col.split()[0] not in have:
                    db.conn.execute(f"ALTER TABLE expenses ADD COLUMN {col}")
            if "channels" not in {r[1] for r in db.conn.execute("PRAGMA table_info(day_reports)")}:  # 2.14.1: mail and Telegram
                db.conn.execute("ALTER TABLE day_reports ADD COLUMN channels TEXT")
            db.conn.commit()
        self._last_tick = 0.0
        self._sending = threading.Lock()

    # ------------------------------------------------------------ the day --
    def rows(self, day=None, login=None):
        day = day or date.today().isoformat()
        sql, args = "SELECT * FROM expenses WHERE date=?", [day]
        if login is not None:
            sql += " AND lower(COALESCE(login,''))=lower(?)"
            args.append(login)
        rows = self.db.q(sql + " ORDER BY created_at", args)
        for r in rows:
            r["doc"] = bool(r["doc"]) if r["doc"] is not None else True
        return rows

    def today(self, login="", see_all=False) -> dict:
        rows = self.rows(None, None if see_all else login)
        cats = self.acc.categories()
        first = list(DAY_CATEGORIES)
        return {"day": date.today().isoformat(), "rows": rows, "total": round(sum(r["amount"] for r in rows), 2),
                "nodoc": round(sum(r["amount"] for r in rows if not r["doc"]), 2), "categories": first + [c for c in cats if c not in first],
                "methods": METHODS, "all": see_all, "report": self.report_state(date.today().isoformat()),
                "mail": settings()["enabled"]}

    def _check_own(self, eid, login, see_all):
        r = self.db.one("SELECT * FROM expenses WHERE id=?", (str(eid),))
        if not r:
            raise ValueError("Расход не найден")
        if not see_all and (r["date"] != date.today().isoformat() or (r["login"] or "").lower() != (login or "").lower()):
            raise ValueError("Можно менять только свои сегодняшние расходы")
        return r

    def save(self, f, who="", login="", see_all=False) -> str:
        """An expense of today. The cash taken from the drawer goes into the open cash shift as «Расход из кассы»."""
        f = dict(f or {})
        old = self._check_own(f["id"], login, see_all) if f.get("id") else None
        if not see_all:
            f["date"] = date.today().isoformat()
        method = f.get("method") if f.get("method") in METHODS else METHODS[0]
        doc = bool(f.get("doc", True))
        f.update(method=method, comment=str(f.get("comment") or "").strip())
        if old:
            f.setdefault("date", old["date"])
        eid = self.acc.save_expense(f, who)
        with self.db.tx() as c:
            c.execute("UPDATE expenses SET doc=?, login=COALESCE(login, ?) WHERE id=?", (1 if doc else 0, login or None, eid))
        self._cash_move(eid, method, who)
        return eid

    def _cash_move(self, eid, method, who):
        """Keep the drawer right: one «Расход из кассы» per cash expense while the shift is open."""
        e = self.db.one("SELECT * FROM expenses WHERE id=?", (eid,))
        mv = self.db.one("SELECT m.* FROM cash_moves m JOIN cash_shifts s ON s.id=m.shift_id WHERE m.expense_id=? AND s.status='open'", (eid,))
        if method != METHODS[0]:
            if mv:
                with self.db.tx() as c:
                    c.execute("DELETE FROM cash_moves WHERE id=?", (mv["id"],))
            return
        if mv:
            with self.db.tx() as c:
                c.execute("UPDATE cash_moves SET amount=?, comment=? WHERE id=?", (e["amount"], f"{e['category']}: {e['comment'] or ''}".strip(": "), mv["id"]))
            return
        if self.db.one("SELECT 1 AS x FROM cash_moves WHERE expense_id=?", (eid,)):
            return  # the shift is already closed: its count must not change
        try:
            self.fin.shift_move({"kind": "out", "amount": e["amount"], "reason": "Расход из кассы",
                                 "comment": f"{e['category']}: {e['comment'] or ''}".strip(": ")}, who, eid)
        except ValueError:
            pass  # no open shift — the expense is still written down

    def delete(self, eid, login="", see_all=False):
        self._check_own(eid, login, see_all)
        with self.db.tx() as c:
            c.execute("""DELETE FROM cash_moves WHERE expense_id=? AND shift_id IN (SELECT id FROM cash_shifts WHERE status='open')""", (eid,))
        self.acc.delete_expense(eid)
        return True

    # ------------------------------------------------------------ the report --
    def report(self, day, cash=None, login=None, shifts=True) -> dict:
        """The day: all expenses (or one employee's: `login`), the cash by methods, the cash shifts."""
        rows = self.rows(day, login)
        doc = round(sum(r["amount"] for r in rows if r["doc"]), 2)
        nodoc = round(sum(r["amount"] for r in rows if not r["doc"]), 2)
        by_cat, by_user = {}, {}
        for r in rows:
            by_cat[r["category"]] = round(by_cat.get(r["category"], 0) + r["amount"], 2)
            by_user[r["user_name"] or "—"] = round(by_user.get(r["user_name"] or "—", 0) + r["amount"], 2)
        day_shifts = []
        if shifts:
            try:
                for s in self.db.q("SELECT id FROM cash_shifts WHERE substr(opened_at,1,10)=? OR substr(COALESCE(closed_at,''),1,10)=? "
                                   "ORDER BY opened_at", (day, day)):
                    day_shifts.append(self.fin.shift(s["id"]))
            except Exception:  # noqa: BLE001 — no money tables in a bare database
                day_shifts = []
        stock = None
        if shifts:  # 2.14.1: receipts and write-offs of the day, with and without documents (the owner's full report)
            try:
                from stock import Stock  # noqa: PLC0415
                stock = Stock(self.db).day_docs(day)
            except Exception:  # noqa: BLE001 — a bare database without the stock
                stock = None
        return {"day": day, "rows": rows, "total": round(doc + nodoc, 2), "doc": doc, "nodoc": nodoc,
                "by_category": dict(sorted(by_cat.items(), key=lambda x: -x[1])), "by_user": by_user, "cash": cash or {}, "shifts": day_shifts,
                "stock": stock}

    def text(self, rep) -> str:
        c = rep["cash"] or {}
        lines = [f"Отчёт за {_fmt(rep['day'])}", ""]
        if c:
            lines.append(f"Поступило денег: {_rub(c.get('money_total', c.get('total', 0)))}")
            for m, v in (c.get("by_method") or {}).items():
                if v:
                    lines.append(f"  {m}: {_rub(v)}")
            if c.get("refunds"):
                lines.append(f"  Возвраты: {_rub(c['refunds'])}")
            lines.append("")
        lines.append(f"Расходы за день: {_rub(rep['total'])} (с документами {_rub(rep['doc'])}, без документов {_rub(rep['nodoc'])})")
        for r in rep["rows"]:
            lines.append(f"  {r['created_at'][11:16]} {r['category']} — {_rub(r['amount'])}, {r['method']}"
                         + ("" if r["doc"] else ", без документа") + (f" — {r['comment']}" if r["comment"] else "")
                         + (f" ({r['user_name']})" if r["user_name"] else ""))
        if not rep["rows"]:
            lines.append("  расходов нет")
        for s in rep["shifts"]:
            lines += ["", f"Кассовая смена: открыта {s['opened_at'][11:16]} ({s.get('opened_by') or '—'})"
                      + (f", закрыта {s['closed_at'][11:16]} ({s.get('closed_by') or '—'})" if s.get("closed_at") else ", не закрыта"),
                      f"  Наличных по расчёту: {_rub(s.get('expected_cash'))}"
                      + (f", пересчитано: {_rub(s['counted_cash'])}, разница: {_rub(s.get('diff_cash'))}" if s.get("counted_cash") is not None else "")]
        st = rep.get("stock")
        if st and (st["rows"] or st["service"]):
            lines += ["", f"Склад: приход {_rub(st['receipt'])}" + (f" (без документов {_rub(st['receipt_nodoc'])})" if st["receipt_nodoc"] else "")
                      + f", списание {_rub(st['writeoff'])}" + (f" (без документов {_rub(st['writeoff_nodoc'])})" if st["writeoff_nodoc"] else "")
                      + (f", по услугам {_rub(st['service'])}" if st["service"] else "")]
            for r in st["rows"]:
                lines.append(f"  {'Приход' if r['kind'] == 'receipt' else 'Списание'}{' № ' + r['number'] if r['number'] else ''} — {_rub(r['total'])}"
                             + (", без документа" if r["nodoc"] else "")
                             + (f" — {r['supplier_name']}" if r["supplier_name"] else f" — {r['reason']}" if r["reason"] else "")
                             + (f" ({r['user_name']})" if r["user_name"] else ""))
        lines += ["", "Отчёт отправлен программой автоматически. Файл Excel — во вложении."]
        return "\n".join(lines)

    def xlsx(self, rep) -> bytes:
        import xlsx  # noqa: PLC0415
        rows = [[r["created_at"][11:16], r["category"], r["amount"], r["method"], "есть" if r["doc"] else "нет", r["comment"] or "", r["user_name"] or ""]
                for r in rep["rows"]]
        rows += [[], ["", "Итого", rep["total"]], ["", "С документами", rep["doc"]], ["", "Без документов", rep["nodoc"]]]
        c = rep["cash"] or {}
        if c:
            rows += [[], ["", "Поступило денег", c.get("money_total", c.get("total", 0))]] + [["", m, v] for m, v in (c.get("by_method") or {}).items() if v]
        st = rep.get("stock")
        if st and st["rows"]:
            rows += [[], ["Склад"]] + [["", ("Приход" if r["kind"] == "receipt" else "Списание") + (f" № {r['number']}" if r["number"] else ""), r["total"] or 0,
                                         r["supplier_name"] or r["reason"] or "", "нет" if r["nodoc"] else "есть", "", r["user_name"] or ""] for r in st["rows"]]
        return xlsx.build(f"Расходы {_fmt(rep['day'])}", ["Время", "Статья", "Сумма", "Как оплачено", "Документ", "Комментарий", "Кто внёс"], rows)

    # ------------------------------------------------------------ sending --
    def send(self, day, cash=None, who="", force=False) -> dict:
        """Send the report of the day to every channel that is on (mail, Telegram). A channel that already got this day
        is skipped unless `force`. Raises ValueError with a plain reason when a channel failed (it is tried again later)."""
        import json  # noqa: PLC0415
        s = settings()
        chans = channels(s)
        if not chans:
            raise ValueError("Отправка отчёта не настроена: Настройки → «Касса и оплаты» → «Отчёт за день»")
        st = self.report_state(day)
        done = json.loads(st["channels"] or "{}") if st and st.get("channels") else ({"mail": "sent"} if st and st["status"] == "sent" else {})
        todo = chans if force else [c for c in chans if done.get(c) != "sent"]
        if not todo:
            return st
        if not self._sending.acquire(timeout=1):
            raise ValueError("Отчёт уже отправляется")
        try:
            rep = self.report(day, cash)
            text, data, fname = self.text(rep), self.xlsx(rep), f"Отчёт {_fmt(day)}.xlsx"
            errs, where = [], dict(json.loads(st["sent_to"]) if st and str(st.get("sent_to") or "").startswith("{") else {})
            for ch in todo:
                try:
                    if ch == "mail":
                        to = _emails(s["to"])
                        if not to or not s["login"] or not s["pass_enc"]:
                            raise ValueError("почта не настроена")
                        self._mail(s, rep, text, data, fname, to)
                        where["mail"] = ", ".join(to)
                    else:
                        token = config.unprotect(s["tg_token_enc"] or "")
                        names = tg_send(token, [c["id"] for c in s["tg_chats"]], f"{_title(rep)}\n\n{text}", data, fname)
                        where["tg"] = ", ".join(n or str(c["id"]) for n, c in zip(names, s["tg_chats"]))
                    done[ch] = "sent"
                except (OSError, smtplib.SMTPException, TgError, ValueError) as e:
                    done[ch] = "error"
                    errs.append(("почта: " if ch == "mail" else "Telegram: ") + (_why(e) if ch == "mail" else str(e)))
            ok = all(done.get(c) == "sent" for c in chans)
            st = self._mark(day, "sent" if ok else "error", where, who, "; ".join(errs) or None, rep, done)
            if errs:
                part = [c for c in todo if done.get(c) == "sent"]
                head = f"Отчёт ушёл {'на почту' if part == ['mail'] else 'в Telegram'}, но не везде" if part else "Отчёт не отправлен"
                raise ValueError(f"{head}: {'; '.join(errs)}. Программа повторит отправку сама.")
            return st
        finally:
            self._sending.release()

    def _mail(self, s, rep, text, data, fname, to):
        msg = EmailMessage()
        clinic = config.BRAND.get("name") or "Клиника"
        msg["Subject"] = _title(rep)
        msg["From"] = formataddr((clinic, s["login"]))
        msg["To"] = ", ".join(to)
        msg["Message-ID"] = make_msgid()
        msg.set_content(text)
        msg.add_attachment(data, maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=fname)
        self._smtp(s, msg)

    @staticmethod
    def _smtp(s, msg):
        ctx = ssl.create_default_context()
        try:
            import certifi  # noqa: PLC0415
            ctx.load_verify_locations(certifi.where())
        except Exception:  # noqa: BLE001
            pass
        port = int(s["port"] or 465)
        if s["security"] == "ssl":
            srv = smtplib.SMTP_SSL(s["host"], port, timeout=30, context=ctx)
        else:
            srv = smtplib.SMTP(s["host"], port, timeout=30)
            if s["security"] == "starttls":
                srv.starttls(context=ctx)
        try:
            srv.login(s["login"], config.unprotect(s["pass_enc"]))
            srv.send_message(msg)
        finally:
            try:
                srv.quit()
            except Exception:  # noqa: BLE001
                pass

    def _mark(self, day, status, where, who, err, rep, done):
        import json  # noqa: PLC0415
        with self.db.tx() as c:
            c.execute("""INSERT INTO day_reports(day, status, sent_at, sent_to, by, error, totals, updated_at, channels) VALUES(?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(day) DO UPDATE SET status=excluded.status, sent_at=excluded.sent_at, sent_to=excluded.sent_to,
                         by=excluded.by, error=excluded.error, totals=excluded.totals, updated_at=excluded.updated_at, channels=excluded.channels""",
                      (day, status, _now() if status == "sent" else None, json.dumps(where, ensure_ascii=False), who or "", err,
                       json.dumps({"total": rep["total"], "nodoc": rep["nodoc"]}), _now(), json.dumps(done)))
        return self.report_state(day)

    def report_state(self, day):
        import json  # noqa: PLC0415
        r = self.db.one("SELECT * FROM day_reports WHERE day=?", (day,))
        if r:
            try:
                w = json.loads(r["sent_to"]) if str(r["sent_to"] or "").startswith("{") else {"mail": r["sent_to"]}
            except ValueError:
                w = {}
            r["where"] = " · ".join(f"{'почта' if k == 'mail' else 'Telegram'}: {v}" for k, v in w.items() if v)
        return r

    def due(self, now=None) -> list[str]:
        """Days whose report should go now: today after the set time, and up to 3 earlier days that did not go."""
        s = settings()
        if not channels(s):
            return []
        now = now or datetime.now()
        out = []
        for back in range(3, 0, -1):
            d = (now.date() - timedelta(days=back)).isoformat()
            st = self.report_state(d)
            if st and st["status"] == "error":
                out.append(d)
        today = now.date().isoformat()
        st = self.report_state(today)
        if now.strftime("%H:%M") >= s["time"] and not (st and st["status"] == "sent"):
            out.append(today)
        return out

    def tick(self, cash_for, who="Программа"):
        """Called often (the status of the program): at most every 5 minutes sends what is due, in the background."""
        if time.time() - self._last_tick < 300:
            return
        self._last_tick = time.time()
        days = self.due()
        if not days:
            return

        def run():
            for d in days:
                try:
                    self.send(d, cash_for(d), who)
                except ValueError as e:
                    log.info("day report %s: %s", d, e)
        threading.Thread(target=run, name="day-report", daemon=True).start()


def _why(e) -> str:
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "почтовый сервер не принял логин или пароль (нужен пароль приложения, а не обычный пароль ящика)"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "почтовый сервер не принял адрес получателя"
    if isinstance(e, (TimeoutError, ConnectionError, OSError)) and not isinstance(e, smtplib.SMTPException):
        return "нет связи с почтовым сервером"
    return f"ошибка почты ({e.__class__.__name__})"


def _title(rep) -> str:
    return f"{config.BRAND.get('name') or 'Клиника'}: отчёт за {_fmt(rep['day'])} — расходы {_rub(rep['total'])}"


# ---------------------------------------------------------------- Telegram --
class TgError(Exception):
    pass


def _tg(token, method, data=None, files=None, timeout=30):
    """One Bot API call → its «result». Errors in plain words."""
    import requests  # noqa: PLC0415
    if not token:
        raise TgError("не указан токен бота")
    try:
        r = requests.post(f"{TG_API}/bot{token}/{method}", data=data, files=files, timeout=timeout)
    except requests.RequestException as e:
        raise TgError("нет связи с Telegram") from e
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code == 401 or r.status_code == 404:
        raise TgError("Telegram не принял токен бота — скопируйте его из @BotFather заново")
    if r.status_code == 403:
        raise TgError("бот не может написать получателю: получатель должен открыть бота и нажать «Старт» (или бот заблокирован)")
    if not j.get("ok"):
        raise TgError(f"Telegram ответил ошибкой: {str(j.get('description') or r.status_code)[:120]}")
    return j.get("result")


def tg_check(token) -> dict:
    """The bot behind the token: {'username', 'name', 'link'}."""
    me = _tg(token, "getMe", timeout=15)
    return {"username": me.get("username") or "", "name": me.get("first_name") or "", "link": f"https://t.me/{me.get('username') or ''}"}


def tg_chats(token) -> list[dict]:
    """Who wrote to the bot lately (pressed «Старт»): [{'id', 'name'}] — the owner picks who gets the report."""
    out = {}
    for u in _tg(token, "getUpdates", {"timeout": 0, "allowed_updates": '["message","my_chat_member"]'}, timeout=20) or []:
        m = u.get("message") or (u.get("my_chat_member") or {})
        c = m.get("chat") or {}
        if c.get("id") is None:
            continue
        name = " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or c.get("title") or ""
        if c.get("username"):
            name = f"{name} (@{c['username']})".strip()
        out[c["id"]] = {"id": c["id"], "name": name or str(c["id"])}
    return list(out.values())


def tg_send(token, chat_ids, text, data=None, fname="Отчёт.xlsx") -> list[str]:
    """The report text (in parts of up to 3900 characters) and the Excel file to every chat. → chat names."""
    if not chat_ids:
        raise TgError("не выбрано, кому отправлять")
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > TG_LIMIT:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    parts.append(cur)
    names = []
    for cid in chat_ids:
        res = None
        for p in parts:
            if p.strip():
                res = _tg(token, "sendMessage", {"chat_id": cid, "text": p.strip(), "disable_web_page_preview": "true"})
        if data:
            _tg(token, "sendDocument", {"chat_id": cid}, files={"document": (fname, data,
                                                                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}, timeout=60)
        chat = (res or {}).get("chat") or {}
        names.append(" ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("title") or "")
    return names
