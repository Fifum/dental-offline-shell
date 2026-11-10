"""2.15: the clinic's financial model for the director — profit by steps, break-even and a «what if» scenario.

Profit of a month, step by step (management accounting, not tax accounting):
    revenue (patients' payments) − variable costs (doctors' percent, materials, laboratory, acquiring)
    = margin − fixed costs (salaries, rent, utilities, advertising…) = operating profit − taxes = net profit.
Salaries are taken as accrued by the pay schemes for the month («Бухгалтерия» → «Зарплата»); a person without a scheme
counts by what was paid to them for that month. Salary payouts are therefore not counted a second time.
The ranges are rough guides for a dental clinic, a hint where to look, not a rule.
"""
from __future__ import annotations

from datetime import date, timedelta

from accounting import SALARY, _month_range

VARIABLE = {"Материалы и закупки": "materials", "Зуботехническая лаборатория": "lab", "Банк и эквайринг": "acquiring"}
TAXES = "Налоги и взносы"
DOCTORS = "Врачи (процент от услуг)"
STAFF = "Оклады и зарплата персонала"
# share of revenue, %: (from, to); a cost above «to» or a profit below «from» is worth a look
GUIDE = {
    "doctors": (20, 32), "materials": (5, 10), "lab": (4, 12), "acquiring": (0, 2.5),
    "margin": (50, 100), "staff": (8, 18), "Аренда": (0, 12), "Реклама": (2, 8), "operating": (15, 100), "net": (10, 100),
}
LIMITS = {"price": (-50, 100), "visits": (-80, 100), "doctors": (-30, 30), "fixed": (-80, 200)}


def _r(x):
    return round(x or 0, 2)


def _share(x, rev):
    return round(x * 100 / rev, 1) if rev else None


def _flag(key, share, profit=False):
    """«high» — a cost above its range, «low» — a profit below it, «ok» — inside, None — no guide or no revenue."""
    g = GUIDE.get(key)
    if not g or share is None:
        return None
    if profit:
        return "low" if share < g[0] else "ok"
    return "high" if share > g[1] else "ok"


def _line(key, name, amount, rev, profit=False, detail=None):
    s = _share(amount, rev)
    return {"key": key, "name": name, "amount": _r(amount), "share": s, "guide": GUIDE.get(key), "flag": _flag(key, s, profit),
            **({"detail": detail} if detail else {})}


class FinModel:
    def __init__(self, db, acc, fin=None, director=None, reports=None):
        self.db, self.acc, self.fin, self.dir, self.rep = db, acc, fin, director, reports

    # ------------------------------------------------------------ one month --
    def _salaries(self, month):
        """Accrued pay of the month: (doctors' percent, everything else, rows for the detail)."""
        pr = self.acc.payroll(month)
        doctors = staff = 0.0
        rows = []
        for p in pr["rows"]:
            if p["percent"] or p["fixed"]:
                doc, fix = (p["by_percent"] if p["kind"] == "doctor" else 0.0), p["fixed"]
            elif p["kind"] == "doctor":
                doc, fix = p["paid_out"], 0.0
            else:
                doc, fix = 0.0, p["paid_out"]
            doctors += doc
            staff += fix
            rows.append({"name": p["name"], "doctors": _r(doc), "staff": _r(fix)})
        return doctors, staff, rows

    def pnl(self, month=None):
        """Profit of one month by steps."""
        mon, a, b = _month_range(month)
        rev = _r(self.db.one("""SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE created_at >= ? AND created_at < ?
                                AND method<>'Бонусы'""", (a, b))["s"])
        billed = _r(self.db.one("""SELECT COALESCE(SUM(total),0) AS s FROM invoices WHERE COALESCE(kind,'invoice')='invoice'
                                   AND created_at >= ? AND created_at < ?""", (a, b))["s"])
        cats, n_exp = {}, 0
        for r in self.db.q("""SELECT category, COALESCE(person,'') AS person, SUM(amount) AS s FROM expenses
                              WHERE date >= ? AND date < ? GROUP BY category, person""", (a, b)):
            n_exp += 1
            if r["category"] == SALARY and r["person"]:
                continue  # payouts to a person: the accrued pay below already holds them
            cats[r["category"]] = cats.get(r["category"], 0) + (r["s"] or 0)
        doctors, staff, pay_rows = self._salaries(mon)
        staff += cats.pop(SALARY, 0)  # a payout without a person: nobody accrues it
        taxes = cats.pop(TAXES, 0)

        var = [_line("doctors", DOCTORS, doctors, rev, detail=[x for x in pay_rows if x["doctors"]])]
        for cat, key in VARIABLE.items():
            var.append(_line(key, cat, cats.pop(cat, 0), rev))
        var_total = sum(x["amount"] for x in var)
        fixed = [_line("staff", STAFF, staff, rev, detail=[x for x in pay_rows if x["staff"]])]
        for cat, v in sorted(cats.items(), key=lambda x: -x[1]):
            fixed.append(_line(cat, cat, v, rev))
        fixed_total = sum(x["amount"] for x in fixed)
        margin = rev - var_total
        op = margin - fixed_total
        net = op - taxes
        cm = margin / rev if rev else 0.0
        be = fixed_total / cm if cm > 0 else None

        today = date.today()
        m0 = date.fromisoformat(a)
        m1 = date.fromisoformat(b) - timedelta(days=1)
        current = m0 <= today <= m1
        wd_all = self._workdays(m0, m1)
        wd_done = self._workdays(m0, min(today, m1)) if m0 <= today else []
        left = max(0, len(wd_all) - len(wd_done)) if current else 0
        return {
            "month": mon, "from": a, "to": m1.isoformat(), "current": current, "future": m0 > today,
            "workdays": len(wd_all), "workdays_done": len(wd_done) if current else (len(wd_all) if m1 < today else 0),
            "revenue": rev, "billed": billed, "has_data": bool(rev or billed or n_exp),
            "variable": var, "variable_total": _r(var_total), "variable_share": _share(var_total, rev),
            "margin": _line("margin", "Маржинальная прибыль", margin, rev, profit=True),
            "fixed": [x for x in fixed if x["amount"] or x["key"] == "staff"], "fixed_total": _r(fixed_total),
            "fixed_share": _share(fixed_total, rev),
            "operating": _line("operating", "Операционная прибыль", op, rev, profit=True),
            "taxes": _line(TAXES, TAXES, taxes, rev),
            "net": _line("net", "Чистая прибыль", net, rev, profit=True),
            "break_even": _r(be) if be is not None else None,
            "safety": _share(rev - be, rev) if be is not None and rev else None,
            "to_break_even": _r(max(0.0, be - rev)) if be is not None else None,
            "per_day_break_even": _r(be / len(wd_all)) if be is not None and wd_all else None,
            "per_day_left": _r(max(0.0, be - rev) / left) if be is not None and left else None,
            "no_schemes": not any(p["percent"] or p["fixed"] for p in self.acc.schemes()),
        }

    def _workdays(self, a, b):
        if self.dir is not None:
            return self.dir._workdays(a, b)
        return [a + timedelta(days=i) for i in range((b - a).days + 1) if (a + timedelta(days=i)).weekday() < 6]

    # ------------------------------------------------------- the whole screen --
    def model(self, month=None, history=True):
        cur = self.pnl(month)
        out = {**cur, "history": [], "reserve": self.reserve()}
        if history:
            y, m = map(int, cur["month"].split("-"))
            for i in range(5, -1, -1):
                k = (y * 12 + m - 1) - i
                p = cur if i == 0 else self.pnl(f"{k // 12:04d}-{k % 12 + 1:02d}")
                out["history"].append({"month": p["month"], "revenue": p["revenue"], "expense": _r(p["variable_total"] + p["fixed_total"] + p["taxes"]["amount"]),
                                       "operating": p["operating"]["amount"], "net": p["net"]["amount"], "share": p["net"]["share"],
                                       "has_data": p["has_data"]})
        return out

    def brief(self, month=None):
        """For the tile on the director's screen."""
        p = self.pnl(month)
        return {k: p[k] for k in ("month", "revenue", "break_even", "to_break_even", "safety", "current", "per_day_left")} | {
            "operating": p["operating"]["amount"], "operating_share": p["operating"]["share"], "net": p["net"]["amount"]}

    def reserve(self):
        """Money that is likely to come: confirmed plans not yet billed, installments not yet due, patients' debts."""
        out = {"plans_confirmed": 0.0, "plans_confirmed_n": 0, "plans_draft": 0.0, "plans_draft_n": 0, "installments": 0.0, "debts": 0.0}
        since = (date.today() - timedelta(days=365)).isoformat()
        for r in self.db.q("""SELECT COALESCE(plan_status,'Предварительный') AS st, COUNT(*) AS n, COALESCE(SUM(total),0) AS s FROM invoices
                              WHERE kind='plan' AND created_at >= ? GROUP BY st""", (since,)):
            if r["st"] == "Подтверждён":
                out["plans_confirmed"], out["plans_confirmed_n"] = _r(r["s"]), r["n"]
            elif r["st"] == "Предварительный":
                out["plans_draft"], out["plans_draft_n"] = _r(r["s"]), r["n"]
        if self.fin is not None:
            try:
                out["installments"] = _r(sum(self.fin.not_due().values()))
            except Exception:  # noqa: BLE001 — no installments tables in a bare database
                pass
        if self.rep is not None:
            out["debts"] = _r(self.rep.debts()["total_debt"])
        return out

    # ------------------------------------------------------------ what if --
    def scenario(self, month=None, f=None, base=None):
        return scenario(base or self.pnl(month), f or {})


def _num(f, key, lo, hi):
    try:
        v = float(str((f or {}).get(key) or 0).replace(",", ".").replace(" ", ""))
    except ValueError:
        raise ValueError("Сценарий: введите число") from None
    return max(lo, min(hi, v))


def scenario(p, f):
    """Recount a month's profit when prices, the number of visits, the doctors' percent or fixed costs change.
    price, visits, fixed — % change; doctors — change of the doctors' percent in points; target — wanted operating profit, ₽."""
    price, visits = _num(f, "price", *LIMITS["price"]) / 100, _num(f, "visits", *LIMITS["visits"]) / 100
    dpts, fixed_k = _num(f, "doctors", *LIMITS["doctors"]) / 100, _num(f, "fixed", *LIMITS["fixed"]) / 100
    target = _num(f, "target", 0, 1e10)
    rev = p["revenue"]
    v = {x["key"]: x["amount"] for x in p["variable"]}
    rev2 = rev * (1 + price) * (1 + visits)
    doc_share = v.get("doctors", 0) / rev if rev else 0
    doctors2 = max(0.0, doc_share + dpts) * rev2 if rev else 0.0
    volume = 1 + visits  # materials and laboratory follow the number of visits, not the prices
    var2 = doctors2 + (v.get("materials", 0) + v.get("lab", 0)) * volume + v.get("acquiring", 0) * (rev2 / rev if rev else 0)
    fixed2 = p["fixed_total"] * (1 + fixed_k)
    tax2 = p["taxes"]["amount"] * (rev2 / rev) if rev else p["taxes"]["amount"]
    op2 = rev2 - var2 - fixed2
    cm2 = (rev2 - var2) / rev2 if rev2 else 0.0  # no revenue — no shares to count from
    be2 = fixed2 / cm2 if cm2 > 0 else None
    need = (fixed2 + target) / cm2 if cm2 > 0 else None
    wd = p.get("workdays") or 0
    return {
        "revenue": _r(rev2), "variable": _r(var2), "doctors": _r(doctors2), "fixed": _r(fixed2), "margin": _r(rev2 - var2),
        "margin_share": _share(rev2 - var2, rev2), "operating": _r(op2), "operating_share": _share(op2, rev2),
        "taxes": _r(tax2), "net": _r(op2 - tax2), "delta": _r(op2 - p["operating"]["amount"]),
        "break_even": _r(be2) if be2 is not None else None, "target": _r(target),
        "need": _r(need) if need is not None else None, "need_per_day": _r(need / wd) if need is not None and wd else None,
        "need_growth": _share(need - rev, rev) if need is not None and rev else None,
    }

