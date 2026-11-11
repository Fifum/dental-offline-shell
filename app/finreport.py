"""3.4: the owner's management accounting — profit and loss by months, the cash flow by days or months and by «where
the money is» (the cash drawer, the bank account and cards, employees' own money), and the report for a week and for a
month that goes by e-mail and Telegram through the channels of the day report (daily.py).

Profit and loss is the financial model of one month (finmodel.FinModel.pnl) laid side by side for several months:
revenue, variable costs (doctors' percent, materials, laboratory, acquiring), margin, fixed costs by category (salaries
of the staff with the administrators' motivation, rent…), operating profit, taxes, net profit. Nothing is counted twice:
salary payouts to a person are inside the accrued pay.

The cash flow is money that really moved: patients' payments by real money (cash, card, SBP, transfer, the insurer),
gift certificates sold, refunds, and expenses by the way they were paid; expenses written down without a document are
shown apart («внутренние»). Paying from the advance, by bonuses or by a certificate moves no money and is left out;
cash put into or taken from the drawer (change, collection) is a move inside the clinic, shown with the drawer.

Payments accepted only in Dentist Plus are not here: its partner API does not give payments. The screens say so.
"""
from __future__ import annotations

import json
import logging
import smtplib
import threading
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import config
from accounting import _month_range
from reports import _period

log = logging.getLogger("finreport")

SCHEMA = """
CREATE TABLE IF NOT EXISTS period_reports(
    key TEXT PRIMARY KEY, kind TEXT, start TEXT, status TEXT, sent_at TEXT, sent_to TEXT, by TEXT, error TEXT,
    channels TEXT, updated_at TEXT);
"""
ACCOUNTS = {"cash": "Касса (наличные)", "bank": "Безналичные: счёт, карта, СБП", "staff": "Свои деньги сотрудников",
            "other": "Другие способы"}
PAY_ACC = {"Наличные": "cash", "Карта": "bank", "СБП": "bank", "Перевод": "bank", "Страховая": "bank"}
EXP_ACC = {"Наличные": "cash", "Наличные из кассы": "cash", "Безналичный перевод": "bank", "Карта": "bank", "Карта клиники": "bank",
           "Перевод": "bank", "Свои деньги сотрудника": "staff"}
NOT_MONEY = {"Из аванса", "Бонусы", "Сертификат"}
DP_NOTE = ("Оплаты, принятые только в Dentist Plus, сюда не попадают: в API Dentist Plus нет оплат. "
           "Здесь деньги, проведённые в этой программе.")
MONTHS = ("январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
MAX_MONTHS = 24


def _r(x):
    return round(x or 0, 2)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _rub(v):
    v = round(v or 0)
    return ("−" if v < 0 else "") + f"{abs(v):,}".replace(",", " ") + " ₽"


def _fmt(d):
    return f"{d[8:10]}.{d[5:7]}.{d[:4]}"


def month_title(mon):
    y, m = map(int, mon.split("-"))
    return f"{MONTHS[m - 1].capitalize()} {y}"


def _months(m_from, m_to):
    a, _, _ = _month_range(m_from)
    b, _, _ = _month_range(m_to or m_from)
    if b < a:
        a, b = b, a
    y, m = map(int, a.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= b and len(out) < MAX_MONTHS:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ------------------------------------------------------------------ profit and loss by months --
def pnl_months(fm, m_from=None, m_to=None) -> dict:
    """Profit and loss for every month of [m_from, m_to] (at most 24), as rows × months. Default: the last 6 months."""
    if not m_from:
        t = date.today()
        k = t.year * 12 + t.month - 1 - 5
        m_from, m_to = f"{k // 12:04d}-{k % 12 + 1:02d}", t.strftime("%Y-%m")
    months = _months(m_from, m_to)
    ps = [fm.pnl(m) for m in months]
    n = len(months)
    rows = []

    def add(key, name, vals, kind="line", profit=False):
        total = _r(sum(vals))
        rows.append({"key": key, "name": name, "kind": kind, "profit": profit, "values": [_r(v) for v in vals], "total": total})

    rev = [p["revenue"] for p in ps]
    add("revenue", "Поступления от пациентов", rev, "total")
    add("variable", "Переменные расходы", [p["variable_total"] for p in ps], "group")
    for i, x in enumerate(ps[0]["variable"] if ps else []):
        add(x["key"], x["name"], [p["variable"][i]["amount"] for p in ps])
    add("margin", "Маржинальная прибыль", [p["margin"]["amount"] for p in ps], "total", True)
    add("fixed", "Постоянные расходы", [p["fixed_total"] for p in ps], "group")
    fixed = {}
    for j, p in enumerate(ps):
        for x in p["fixed"]:
            fixed.setdefault(x["key"], {"name": x["name"], "values": [0.0] * n})["values"][j] = x["amount"]
    order = sorted(fixed.items(), key=lambda kv: (kv[0] != "staff", -sum(kv[1]["values"])))
    for k, v in order:
        add(k, v["name"], v["values"])
    add("operating", "Операционная прибыль", [p["operating"]["amount"] for p in ps], "total", True)
    add("taxes", "Налоги и взносы", [p["taxes"]["amount"] for p in ps], "group")
    add("net", "Чистая прибыль", [p["net"]["amount"] for p in ps], "total", True)
    sal = [next((x["amount"] for x in p["variable"] if x["key"] == "doctors"), 0) + next((x["amount"] for x in p["fixed"] if x["key"] == "staff"), 0)
           for p in ps]
    total_rev = _r(sum(rev))
    for r in rows:
        r["share"] = round(r["total"] * 100 / total_rev, 1) if total_rev else None
    return {"months": months, "titles": [month_title(m) for m in months], "rows": rows,
            "has_data": [p["has_data"] for p in ps], "current": [p["current"] for p in ps], "billed": [p["billed"] for p in ps],
            "salaries": [_r(x) for x in sal], "salaries_total": _r(sum(sal)), "revenue_total": total_rev,
            "net_total": next(r["total"] for r in rows if r["key"] == "net"),
            "no_schemes": bool(ps and ps[-1].get("no_schemes")), "note": DP_NOTE}


# ------------------------------------------------------------------ cash flow --
def cashflow(db, date_from=None, date_to=None, group="day", fin=None) -> dict:
    """Money in and out of the clinic by days (or months) and by accounts."""
    a, b = _period(date_from, date_to)
    days = (date.fromisoformat(b) - date.fromisoformat(a)).days
    group = "month" if group == "month" or days > 62 else "day"
    cut = 7 if group == "month" else 10
    acc = {k: {"key": k, "name": v, "in": 0.0, "out": 0.0, "moves_in": 0.0, "moves_out": 0.0} for k, v in ACCOUNTS.items()}
    per, in_by, out_by, ins_methods = {}, {}, {}, {}
    tot = {"in": 0.0, "out": 0.0, "refunds": 0.0, "out_doc": 0.0, "out_nodoc": 0.0, "certs": 0.0}

    def bucket(at):
        k = str(at)[:cut]
        return per.setdefault(k, {"period": k, "in": 0.0, "out": 0.0, "by_acc": {}})

    def flow(at, account, amount, direction):
        x = bucket(at)
        x[direction] += amount
        ba = x["by_acc"].setdefault(account, {"in": 0.0, "out": 0.0})
        ba[direction] += amount
        acc[account][direction] += amount
        tot[direction] += amount

    for p in db.q("SELECT amount, method, kind, created_at FROM payments WHERE created_at >= ? AND created_at < ?", (a, b)):
        m = p["method"] or ""
        if m in NOT_MONEY or not p["amount"]:
            continue
        account = PAY_ACC.get(m, "other")
        if p["amount"] < 0:
            flow(p["created_at"], account, -p["amount"], "out")
            tot["refunds"] += -p["amount"]
            out_by["Возвраты пациентам"] = out_by.get("Возвраты пациентам", 0) - p["amount"]
        else:
            flow(p["created_at"], account, p["amount"], "in")
            in_by[m] = in_by.get(m, 0) + p["amount"]
    try:
        certs = db.q("SELECT amount, method, sold_at FROM certificates WHERE sold_at >= ? AND sold_at < ?", (a, b))
    except Exception:  # noqa: BLE001 — no loyalty tables in a bare database
        certs = []
    for c in certs:
        if not c["amount"] or (c["method"] or "") in NOT_MONEY:
            continue
        flow(c["sold_at"], PAY_ACC.get(c["method"] or "", "other"), c["amount"], "in")
        in_by["Продажа сертификатов"] = in_by.get("Продажа сертификатов", 0) + c["amount"]
        tot["certs"] += c["amount"]
    for e in db.q("SELECT * FROM expenses WHERE date >= ? AND date < ?", (a, b)):
        if not e["amount"]:
            continue
        flow(e["date"], EXP_ACC.get(e["method"] or "", "other"), e["amount"], "out")
        out_by[e["category"] or "Прочее"] = out_by.get(e["category"] or "Прочее", 0) + e["amount"]
        nodoc = e.get("doc") is not None and not e.get("doc")
        tot["out_nodoc" if nodoc else "out_doc"] += e["amount"]
    moves = []
    try:
        moves = db.q("""SELECT at, kind, amount, reason FROM cash_moves WHERE at >= ? AND at < ? AND COALESCE(expense_id,'')=''""", (a, b))
    except Exception:  # noqa: BLE001
        moves = []
    by_move = {}
    for mv in moves:
        if not mv["amount"]:
            continue
        acc["cash"]["moves_in" if mv["kind"] == "in" else "moves_out"] += mv["amount"]
        k = f"{'Внесено' if mv['kind'] == 'in' else 'Изъято'}: {mv['reason'] or '—'}"
        by_move[k] = by_move.get(k, 0) + mv["amount"]
    rows, cum = [], 0.0
    for k in sorted(per):
        x = per[k]
        net = x["in"] - x["out"]
        cum += net
        rows.append({"period": k, "in": _r(x["in"]), "out": _r(x["out"]), "net": _r(net), "cum": _r(cum),
                     "by_acc": {ak: {"in": _r(v["in"]), "out": _r(v["out"])} for ak, v in x["by_acc"].items()}})
    accounts = []
    for v in acc.values():
        v = {**v, **{k: _r(v[k]) for k in ("in", "out", "moves_in", "moves_out")}}
        v["net"] = _r(v["in"] - v["out"] + v["moves_in"] - v["moves_out"])
        if v["in"] or v["out"] or v["moves_in"] or v["moves_out"] or v["key"] in ("cash", "bank"):
            accounts.append(v)
    shifts = []
    if fin is not None:
        try:
            for s in db.q("SELECT id FROM cash_shifts WHERE opened_at >= ? AND opened_at < ? ORDER BY opened_at", (a, b)):
                sh = fin.shift(s["id"])
                if sh:
                    shifts.append({k: sh.get(k) for k in ("id", "opened_at", "closed_at", "opened_by", "closed_by", "status", "expected_cash",
                                                          "counted_cash", "diff_cash", "card_expected", "card_terminal", "diff_card",
                                                          "sbp_expected", "sbp_bank", "diff_sbp")})
        except Exception:  # noqa: BLE001
            shifts = []
    diffs = [s for s in shifts if any(abs(s.get(k) or 0) >= 0.01 for k in ("diff_cash", "diff_card", "diff_sbp"))]
    return {"from": a, "to": (date.fromisoformat(b) - timedelta(days=1)).isoformat(), "group": group, "rows": rows, "accounts": accounts,
            "in": _r(tot["in"]), "out": _r(tot["out"]), "net": _r(tot["in"] - tot["out"]), "refunds": _r(tot["refunds"]),
            "certs": _r(tot["certs"]), "out_doc": _r(tot["out_doc"]), "out_nodoc": _r(tot["out_nodoc"]),
            "in_by_method": {k: _r(v) for k, v in sorted(in_by.items(), key=lambda x: -x[1])},
            "out_by_category": {k: _r(v) for k, v in sorted(out_by.items(), key=lambda x: -x[1])},
            "moves": {k: _r(v) for k, v in by_move.items()}, "shifts": shifts, "shift_diffs": len(diffs),
            "dp": {"payments": None, "note": DP_NOTE}}


# ------------------------------------------------------------------ the week and the month --
def period_of(kind, start=None, today=None):
    """(key, first day, last day) of the last full week (Mon–Sun) or month, or of the one that holds `start`."""
    today = today or date.today()
    if kind == "week":
        d = date.fromisoformat(str(start)[:10]) if start else today - timedelta(days=7)
        a = d - timedelta(days=d.weekday())
        return f"week:{a.isoformat()}", a, a + timedelta(days=6)
    if kind == "month":
        if start:
            mon, _, _ = _month_range(str(start)[:7])
        else:
            k = today.year * 12 + today.month - 2
            mon = f"{k // 12:04d}-{k % 12 + 1:02d}"
        _, a, b = _month_range(mon)
        return f"month:{mon}", date.fromisoformat(a), date.fromisoformat(b) - timedelta(days=1)
    raise ValueError("Отчёт бывает за неделю или за месяц")


class PeriodReports:
    """Builds the report for a week or a month and sends it by the day report's channels."""

    def __init__(self, db, api):
        self.db, self.api = db, api
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()
        self._last_tick = 0.0
        self._sending = threading.Lock()

    # ------------------------------------------------------------ content --
    def build(self, kind, start=None) -> dict:
        key, a, b = period_of(kind, start)
        api = self.api
        span = (b - a).days + 1
        pa, pb = a - timedelta(days=span if kind == "week" else 0), a - timedelta(days=1)
        if kind == "month":
            pa = date.fromisoformat(_month_range(pb.strftime("%Y-%m"))[1])
        cf = cashflow(self.db, a, b, "day" if kind == "week" else "month", api._fin)
        prev = cashflow(self.db, pa, pb, "month", api._fin)
        rep = {"key": key, "kind": kind, "from": a.isoformat(), "to": b.isoformat(), "prev_from": pa.isoformat(), "prev_to": pb.isoformat(),
               "money": cf, "prev_in": prev["in"], "prev_out": prev["out"]}
        if kind == "week":
            rep["title"] = f"Неделя {_fmt(a.isoformat())[:5]} — {_fmt(b.isoformat())}"
            try:
                rep["lines"] = api._dir.weekly(a.isoformat())["lines"]
            except Exception:  # noqa: BLE001
                rep["lines"] = []
        else:
            mon = a.strftime("%Y-%m")
            rep["title"] = month_title(mon)
            fm = api._fm()
            p = fm.pnl(mon)
            rep["pnl"] = {"revenue": p["revenue"], "billed": p["billed"], "variable": p["variable_total"], "margin": p["margin"]["amount"],
                          "fixed": p["fixed_total"], "operating": p["operating"]["amount"], "taxes": p["taxes"]["amount"],
                          "net": p["net"]["amount"], "net_share": p["net"]["share"], "break_even": p["break_even"],
                          "lines": [{"name": x["name"], "amount": x["amount"]} for x in p["variable"] + p["fixed"] if x["amount"]]}
            pp = fm.pnl(pa.strftime("%Y-%m"))
            rep["pnl_prev"] = {"revenue": pp["revenue"], "net": pp["net"]["amount"], "has_data": pp["has_data"]}
            pr = api._acc.payroll(mon)
            rep["payroll"] = {"earned": pr["earned"], "paid_out": pr["paid_out"], "due": pr["due"],
                              "rows": [{"name": r["name"], "earned": r["earned"], "bonus": r.get("bonus", 0), "due": r["due"]} for r in pr["rows"]]}
            mo = api._mot.month(mon)
            rep["motivation"] = {"total": mo["total"], "rows": [{"name": r["name"], "total": r["total"]} for r in mo["rows"]]}
            try:
                k = api._dir.kpi(mon)["clinic"]["metrics"]
                rep["kpi"] = {m: {"plan": v["plan"], "fact": v["fact"], "pct": v["pct"]} for m, v in k.items()}
            except Exception:  # noqa: BLE001
                rep["kpi"] = {}
        rep["timesheet"] = api._ts.summary(a, b)
        return rep

    def text(self, rep) -> str:
        c = rep["money"]
        lines = [f"Отчёт: {rep['title'].lower() if rep['kind'] == 'month' else rep['title']}", ""]

        def vs(cur, prev):
            if not prev:
                return ""
            d = round((cur - prev) * 100 / prev)
            return f" ({'+' if d > 0 else '−' if d < 0 else ''}{abs(d)} % к прошлому {'месяцу' if rep['kind'] == 'month' else 'периоду'})"
        lines.append(f"Поступило денег: {_rub(c['in'])}{vs(c['in'], rep['prev_in'])}")
        for m, v in c["in_by_method"].items():
            lines.append(f"  {m}: {_rub(v)}")
        lines.append(f"Ушло денег: {_rub(c['out'])} (с документами {_rub(c['out_doc'])}, без документов {_rub(c['out_nodoc'])}"
                     + (f", возвраты {_rub(c['refunds'])}" if c["refunds"] else "") + ")")
        for k, v in list(c["out_by_category"].items())[:12]:
            lines.append(f"  {k}: {_rub(v)}")
        lines.append(f"Итог движения денег: {_rub(c['net'])}")
        for a in c["accounts"]:
            if a["in"] or a["out"]:
                lines.append(f"  {a['name']}: пришло {_rub(a['in'])}, ушло {_rub(a['out'])}")
        if c["shift_diffs"]:
            lines.append(f"  Кассовых смен с расхождением: {c['shift_diffs']}")
        p = rep.get("pnl")
        if p:
            lines += ["", "Прибыль и убытки (управленческий учёт):",
                      f"  Поступления {_rub(p['revenue'])}, переменные расходы {_rub(p['variable'])}, маржинальная прибыль {_rub(p['margin'])}",
                      f"  Постоянные расходы {_rub(p['fixed'])}, операционная прибыль {_rub(p['operating'])}",
                      f"  Налоги и взносы {_rub(p['taxes'])}, чистая прибыль {_rub(p['net'])}"
                      + (f" ({str(p['net_share']).replace('.', ',')} % поступлений)" if p["net_share"] is not None else "")]
            pp = rep.get("pnl_prev") or {}
            if pp.get("has_data"):
                lines.append(f"  Месяцем раньше: поступления {_rub(pp['revenue'])}, чистая прибыль {_rub(pp['net'])}")
            if p["break_even"] is not None:
                lines.append(f"  Точка безубыточности: {_rub(p['break_even'])}")
        k = rep.get("kpi") or {}
        if k.get("revenue", {}).get("plan"):
            r = k["revenue"]
            lines.append(f"  План по поступлениям: {_rub(r['plan'])}, выполнено {r['pct'] or 0:g} %".replace(".", ","))
        if k:
            lines.append(f"  Приёмов: {k.get('visits', {}).get('fact') or 0}, новых пациентов: {k.get('new_patients', {}).get('fact') or 0}")
        pr = rep.get("payroll")
        if pr and (pr["earned"] or pr["paid_out"]):
            lines += ["", f"Зарплата: начислено {_rub(pr['earned'])}, выплачено {_rub(pr['paid_out'])}, к выплате {_rub(pr['due'])}"]
        mo = rep.get("motivation")
        if mo and mo["rows"]:
            lines.append(f"Мотивация администраторов: {_rub(mo['total'])} — " + ", ".join(f"{r['name']} {_rub(r['total'])}" for r in mo["rows"]))
        if rep.get("lines"):
            lines += ["", "Неделя:", *[f"  {x}" for x in rep["lines"]]]
        ts = rep.get("timesheet") or []
        bad = [t for t in ts if t["late_n"] or t["absent_n"] or t["noleave_n"]]
        if ts:
            lines += ["", "Табель:"]
            for t in ts:
                extra = []
                if t["late_n"]:
                    extra.append(f"опозданий {t['late_n']} ({t['late_min']} мин)")
                if t["absent_n"]:
                    extra.append(f"без отметки {t['absent_n']} дн.")
                if t["noleave_n"]:
                    extra.append(f"без ухода {t['noleave_n']}")
                lines.append(f"  {t['name']}: {str(t['fact_h']).replace('.', ',')} ч из {str(t['plan_h']).replace('.', ',')} ч по графику"
                             + (f"; {', '.join(extra)}" if extra else ""))
            if not bad:
                lines.append("  опозданий и пропусков нет")
        lines += ["", DP_NOTE, "Отчёт отправлен программой автоматически. Файл Excel — во вложении."]
        return "\n".join(lines)

    def xlsx(self, rep) -> bytes:
        import xlsx  # noqa: PLC0415
        c = rep["money"]
        rows = [["Деньги", "Поступило", c["in"]]] + [["", m, v] for m, v in c["in_by_method"].items()]
        rows += [["", "Ушло", c["out"]], ["", "с документами", c["out_doc"]], ["", "без документов", c["out_nodoc"]]]
        rows += [["", k, v] for k, v in c["out_by_category"].items()]
        rows += [["", "Итог", c["net"]]] + [["Счёт", a["name"], a["in"] - a["out"]] for a in c["accounts"]]
        if c["rows"]:
            rows += [[]] + [["По дням" if c["group"] == "day" else "По месяцам", r["period"], r["in"], r["out"], r["net"]] for r in c["rows"]]
        p = rep.get("pnl")
        if p:
            rows += [[], ["Прибыль и убытки", "Поступления", p["revenue"]], ["", "Переменные расходы", p["variable"]],
                     ["", "Маржинальная прибыль", p["margin"]], ["", "Постоянные расходы", p["fixed"]],
                     ["", "Операционная прибыль", p["operating"]], ["", "Налоги и взносы", p["taxes"]], ["", "Чистая прибыль", p["net"]]]
            rows += [["Статьи", x["name"], x["amount"]] for x in p["lines"]]
        pr = rep.get("payroll")
        if pr and pr["rows"]:
            rows += [[]] + [["Зарплата", r["name"], r["earned"], r["bonus"], r["due"]] for r in pr["rows"]]
        for t in rep.get("timesheet") or []:
            rows.append(["Табель", t["name"], t["fact_h"], t["plan_h"], t["late_n"], t["late_min"], t["absent_n"]])
        return xlsx.build(rep["title"], ["Раздел", "Строка", "Сумма / часы", "", "", "", ""], rows)

    def subject(self, rep) -> str:
        what = f"отчёт за {rep['title'].lower()}" if rep["kind"] == "month" else f"отчёт за неделю {_fmt(rep['from'])[:5]} — {_fmt(rep['to'])}"
        return f"{config.BRAND.get('name') or 'Клиника'}: {what} — поступило {_rub(rep['money']['in'])}"

    # ------------------------------------------------------------ sending --
    def state(self, key):
        r = self.db.one("SELECT * FROM period_reports WHERE key=?", (key,))
        if r:
            try:
                w = json.loads(r["sent_to"] or "{}")
            except ValueError:
                w = {}
            r["where"] = " · ".join(f"{'почта' if k == 'mail' else 'Telegram'}: {v}" for k, v in w.items() if v)
        return r

    def send(self, kind, start=None, who="", force=False) -> dict:
        import daily  # noqa: PLC0415
        s = daily.settings()
        chans = daily.channels(s)
        if not chans:
            raise ValueError("Отправка отчётов не настроена: Настройки → «Касса и оплаты» → «Отчёт за день»")
        key, a, _ = period_of(kind, start)
        st = self.state(key)
        done = json.loads(st["channels"] or "{}") if st and st.get("channels") else {}
        todo = chans if force else [c for c in chans if done.get(c) != "sent"]
        if not todo:
            return st
        if not self._sending.acquire(timeout=1):
            raise ValueError("Отчёт уже отправляется")
        try:
            rep = self.build(kind, a.isoformat())
            text, data = self.text(rep), self.xlsx(rep)
            fname = f"Отчёт {rep['title']}.xlsx".replace("—", "-")
            subject = self.subject(rep)
            errs, where = [], dict(json.loads(st["sent_to"]) if st and str(st.get("sent_to") or "").startswith("{") else {})
            for ch in todo:
                try:
                    if ch == "mail":
                        to = daily._emails(s["to"])
                        if not to or not s["login"] or not s["pass_enc"]:
                            raise ValueError("почта не настроена")
                        msg = EmailMessage()
                        msg["Subject"] = subject
                        msg["From"] = formataddr((config.BRAND.get("name") or "Клиника", s["login"]))
                        msg["To"] = ", ".join(to)
                        msg["Message-ID"] = make_msgid()
                        msg.set_content(text)
                        msg.add_attachment(data, maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=fname)
                        daily.Daily._smtp(s, msg)
                        where["mail"] = ", ".join(to)
                    else:
                        token = config.unprotect(s["tg_token_enc"] or "")
                        names = daily.tg_send(token, [c["id"] for c in s["tg_chats"]], f"{subject}\n\n{text}", data, fname)
                        where["tg"] = ", ".join(n or str(c["id"]) for n, c in zip(names, s["tg_chats"]))
                    done[ch] = "sent"
                except (OSError, smtplib.SMTPException, daily.TgError, ValueError) as e:
                    done[ch] = "error"
                    errs.append(("почта: " + daily._why(e)) if ch == "mail" else f"Telegram: {e}")
            ok = all(done.get(c) == "sent" for c in chans)
            with self.db.tx() as c:
                c.execute("""INSERT INTO period_reports(key, kind, start, status, sent_at, sent_to, by, error, channels, updated_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET status=excluded.status, sent_at=excluded.sent_at,
                             sent_to=excluded.sent_to, by=excluded.by, error=excluded.error, channels=excluded.channels, updated_at=excluded.updated_at""",
                          (key, kind, a.isoformat(), "sent" if ok else "error", _now() if ok else None, json.dumps(where, ensure_ascii=False),
                           who or "", "; ".join(errs) or None, json.dumps(done), _now()))
            if errs:
                raise ValueError(f"Отчёт отправлен не везде: {'; '.join(errs)}. Программа повторит отправку сама.")
            return self.state(key)
        finally:
            self._sending.release()

    def due(self, now=None) -> list[tuple]:
        """[(kind, start)] to send now: last week from Monday (after the day report's time) until Wednesday; last month
        from the 1st until the 3rd. Only when a channel is on and the report of that kind is switched on."""
        import daily  # noqa: PLC0415
        s = daily.settings()
        if not daily.channels(s):
            return []
        now = now or datetime.now()
        t, hm = now.date(), now.strftime("%H:%M")
        out = []
        if s.get("week_on", True):
            mon = t - timedelta(days=t.weekday())
            day_n = (t - mon).days  # 0 = Monday
            if day_n <= 2 and (day_n > 0 or hm >= s["time"]):
                key, a, _ = period_of("week", (mon - timedelta(days=7)).isoformat())
                st = self.state(key)
                if not (st and st["status"] == "sent"):
                    out.append(("week", a.isoformat()))
        if s.get("month_on", True):
            if t.day <= 3 and (t.day > 1 or hm >= s["time"]):
                key, a, _ = period_of("month", today=t)
                st = self.state(key)
                if not (st and st["status"] == "sent"):
                    out.append(("month", a.isoformat()))
        return out

    def tick(self, who="Программа"):
        """Called often (the status): at most every 5 minutes sends what is due, in the background; quiet otherwise."""
        if time.time() - self._last_tick < 300:
            return
        self._last_tick = time.time()
        todo = self.due()
        if not todo:
            return

        def run():
            for kind, start in todo:
                try:
                    self.send(kind, start, who)
                except ValueError as e:
                    log.info("period report %s %s: %s", kind, start, e)
                except Exception:  # noqa: BLE001
                    log.exception("period report")
        threading.Thread(target=run, name="period-report", daemon=True).start()
