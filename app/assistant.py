"""2.13 (14.1): the AI assistant in the corner of the screen.

«Кто у меня завтра?», «Сколько выручки у Гусевой за октябрь?», «Найди пациентов без гигиены больше 6 месяцев»,
«Запиши Петрову на четверг к Гусевой» — the answer is made by the program from its own data, with the rights of the
employee who asks (the same permissions as the screens). Changes (a booking, a task, a note) are only proposed:
the employee presses «Да», and the normal method of the program does it, with its own check of rights and the
action journal.

How a question is understood: simple rules first (they work without the AI and without the internet); if the rules
do not know the question and the AI is on, the model picks one of the tools below and its parameters (it sees the
question only, never patient data). A general question («как объяснить пациенту, что такое пульпит») is answered
by the model in plain words, marked «ответ ИИ — проверьте»."""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, datetime, timedelta

import ai
from reports import status_kind

WD_RE = [r"понедельник\w{0,2}", r"вторник\w{0,2}", r"сред[ауе]", r"четверг\w{0,2}", r"пятниц[ауе]", r"суббот[ауе]", r"воскресень[еяю]"]
WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTH_RE = [r"январ[ьяе]", r"феврал[ьяе]", r"март[ае]?", r"апрел[ьяе]", r"ма[йяе]", r"июн[ьяе]", r"июл[ьяе]", r"август[ае]?",
            r"сентябр[ьяе]", r"октябр[ьяе]", r"ноябр[ьяе]", r"декабр[ьяе]"]
MONTHS_ANY = "(" + "|".join(f"(?:{m})" for m in MONTH_RE) + ")"
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
NUM_WORDS = {"один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
             "восемь": 8, "девять": 9, "десять": 10, "двенадцать": 12, "полгода": 6, "год": 12}

# tool: (who may use it — any of these rights, what it does — for the help and for the model)
TOOLS = {
    "schedule": (("schedule_view",), "расписание на день или несколько дней, можно по врачу («кто у меня завтра»)"),
    "patient": (("patients_view",), "карточка пациента: телефон, последний и следующий визит, долг, планы"),
    "revenue": (("reports", "accounting"), "выручка (поступления) клиники, врача или пациента за период"),
    "debts": (("reports", "accounting", "payments"), "кто должен клинике"),
    "segment": (("marketing",), "списки пациентов: без гигиены или без визита N месяцев, именинники, с незавершённым планом"),
    "tasks": (("marketing",), "мои задачи CRM на сегодня и просроченные"),
    "stock": (("stock_view", "stock_edit"), "что заканчивается на складе и у чего истекает срок"),
    "week": (("reports",), "сводка за прошлую неделю для директора"),
    "book": (("schedule_edit",), "записать пациента к врачу на день и время"),
    "task": (("marketing",), "поставить задачу: перезвонить, напомнить пациенту"),
    "note": (("patients_edit",), "записать примечание в карточку пациента"),
    "translate": (("docs", "marketing", "medcard_edit", "patients_edit", "schedule_edit"),
                  "перевести сообщение или текст для пациента на другой язык (нужен ИИ)"),
}
EXAMPLES = [("Кто у меня завтра?", "schedule"), ("Расписание Гусевой на четверг", "schedule"), ("Выручка за октябрь", "revenue"),
            ("Сколько заплатила Петрова в этом году?", "revenue"), ("Пациенты без гигиены больше 6 месяцев", "segment"),
            ("Кто должен клинике?", "debts"), ("Запиши Петрову на четверг к Гусевой в 15:00", "book"),
            ("Напомни перезвонить Иванову через неделю", "task"), ("Что заканчивается на складе?", "stock"), ("Сводка за неделю", "week")]

ROUTE_TASK = (
    "Определи, что просит сотрудник клиники, и верни ТОЛЬКО JSON без пояснений: "
    '{"tool": "", "name": "", "doctor": "", "date": "", "date_to": "", "time": "", "months": 0, "service": "", "text": ""}. '
    "tool — одно из: " + "; ".join(f"{k} — {v[1]}" for k, v in TOOLS.items()) + "; free — вопрос о стоматологии или общий "
    "вопрос, на который можно ответить без данных клиники (что такое пульпит, как объяснить пациенту, чем отличается…). "
    "name — фамилия пациента как в вопросе, doctor — фамилия врача, date и date_to — даты ГГГГ-ММ-ДД (сегодня {today}, {wd}), "
    "time — ЧЧ:ММ, months — число месяцев (год = 12), service — услуга (например «гигиена»), text — текст задачи или примечания. "
    "Пустые поля оставь пустыми. Примеры: «Кто у Орлова в среду?» → {\"tool\": \"schedule\", \"doctor\": \"Орлов\"}; "
    "«Сколько принесла Иванова за год?» → {\"tool\": \"revenue\", \"name\": \"Иванова\"}; "
    "«Почему болит зуб после пломбы?» → {\"tool\": \"free\"}.")
FREE_LIMIT = 900  # letters of a free answer of the assistant
FREE_TASK = (
    "Ответь на вопрос сотрудника стоматологической клиники коротко: 2–5 предложений, до 700 знаков, простыми словами, "
    "без вступлений вроде «Отличный вопрос». Если вопрос "
    "о данных клиники (пациенты, записи, деньги) — скажи, что такие вопросы нужно задавать конкретно, например "
    "«кто у меня завтра» или «выручка за октябрь».")


def _low(s):
    return str(s or "").lower().replace("ё", "е")


def _fmt(d):
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def _rub(v):
    return f"{round(v or 0):,}".replace(",", " ") + " ₽"


def _short(name):
    w = str(name or "").split()
    return f"{w[0]} {' '.join(x[0] + '.' for x in w[1:3])}".strip() if len(w) > 1 else (name or "")


def _plural(n, one, few, many):
    n = abs(int(n))
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


# ------------------------------------------------------------------ dates --
def parse_day(text, today=None):
    """«сегодня», «завтра», «в четверг», «15 ноября», «15.11» → date or None."""
    t, today = _low(text), today or date.today()
    if "послезавтра" in t:
        return today + timedelta(days=2)
    if re.search(r"\bзавтра", t):
        return today + timedelta(days=1)
    if re.search(r"\bвчера", t):
        return today - timedelta(days=1)
    if re.search(r"\bсегодня", t):
        return today
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        y = int(y) + (2000 if y and len(y) == 2 else 0) if y else today.year
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\s+" + MONTHS_ANY + r"\b", t)
    if m:
        try:
            return date(today.year, _month(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    nxt = "следующ" in t
    for i, w in enumerate(WD_RE):
        if re.search(r"\b" + w + r"\b", t):
            delta = (i - today.weekday()) % 7
            return today + timedelta(days=delta + (7 if nxt else 0))
    return None


def _month(word):
    return next(i for i, m in enumerate(MONTH_RE) if re.fullmatch(m, word)) + 1


def parse_period(text, today=None):
    """«за октябрь», «в этом месяце», «за прошлую неделю», «за год», «с 1 по 15 ноября» → (from, to) inclusive, or None."""
    t, today = _low(text), today or date.today()
    m0 = today.replace(day=1)
    if re.search(r"прошл\w+\s+месяц", t):
        b = m0 - timedelta(days=1)
        return b.replace(day=1), b
    if re.search(r"(?:этот|этом|текущ\w+)\s+месяц|за месяц|с начала месяца", t):
        return m0, today
    if re.search(r"прошл\w+\s+недел", t):
        a = today - timedelta(days=today.weekday() + 7)
        return a, a + timedelta(days=6)
    if re.search(r"(?:эт\w+|текущ\w+)\s+недел", t):
        return today - timedelta(days=today.weekday()), today
    if re.search(r"за недел|7 дней", t):
        return today - timedelta(days=6), today
    if re.search(r"прошл\w+\s+год", t):
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if re.search(r"(?:этот|этом|текущ\w+)\s+год|за год|с начала года", t):
        return date(today.year, 1, 1), today
    m = re.search(r"\bс\s+(\d{1,2})\s+(?:" + MONTHS_ANY + r"\s+)?по\s+(\d{1,2})\s+" + MONTHS_ANY + r"\b", t)
    if m:
        mo2 = _month(m.group(4))
        mo1 = _month(m.group(2)) if m.group(2) else mo2
        try:
            return date(today.year, mo1, int(m.group(1))), date(today.year, mo2, int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(?<!\d\s)(?<!\d)\b" + MONTHS_ANY + r"\b", t)
    if m:
        i = _month(m.group(1))
        y = today.year if i <= today.month else today.year - 1
        return date(y, i, 1), date(y, i, calendar.monthrange(y, i)[1])
    if re.search(r"сегодня", t):
        return today, today
    if re.search(r"вчера", t):
        return today - timedelta(days=1), today - timedelta(days=1)
    return None


def parse_time(text):
    """«в 15:00», «в 9.30», «в 15 часов», «на 10 утра» → 'HH:MM' or ''."""
    t = _low(text)
    # «на 10.11» is a date, «в 9.30» is a time: a dot counts only after «в»
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", t) or re.search(r"\bв\s+(\d{1,2})\.(\d{2})\b(?!\.\d)", t)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\b(?:в|на|к)\s+(\d{1,2})\s*(?:час\w*|ч\b|утра|вечера|дня)?(?=\s|$|,|\.(?!\d))", t)
        if not m or re.search(r"\b(?:в|на|к)\s+" + m.group(1) + r"\s+" + MONTHS_ANY, t):
            return ""
        h, mi = int(m.group(1)), 0
        if re.search(r"\d\s*(?:вечера|дня)", t) and h < 12:
            h += 12
    return f"{h:02d}:{mi:02d}" if 0 <= h < 24 and 0 <= mi < 60 else ""


def _ai_day(a, key="date"):
    """A date the model gave (ГГГГ-ММ-ДД), or None."""
    try:
        return date.fromisoformat(str((a or {}).get(key) or "")) if re.match(r"\d{4}-\d{2}-\d{2}$", str((a or {}).get(key) or "")) else None
    except ValueError:
        return None


def parse_due(text, today=None):
    """When a task is due: «через неделю», «через 3 дня», «через месяц», «завтра», «в пятницу», a date."""
    t, today = _low(text), today or date.today()
    m = re.search(r"через\s+(\d+|" + "|".join(NUM_WORDS) + r")?\s*(дн|день|дня|недел|месяц|месяца|полгода|год)", t)
    if m:
        n = int(m.group(1)) if (m.group(1) or "").isdigit() else NUM_WORDS.get(m.group(1) or "", 1)
        u = m.group(2)
        if u.startswith("пол"):
            return today + timedelta(days=182)
        if u.startswith("д"):
            return today + timedelta(days=n)
        if u.startswith("недел"):
            return today + timedelta(days=7 * n)
        if u.startswith("год"):
            return today + timedelta(days=365 * n)
        return today + timedelta(days=int(30.4 * n))
    return parse_day(t, today)


# ----------------------------------------------------------------- names --
_STOP = {"запиши", "записать", "запишите", "найди", "найти", "покажи", "кто", "меня", "завтра", "сегодня", "послезавтра",
         "выручка", "выручки", "выручку", "сколько", "пациент", "пациента", "пациентку", "пациентов", "пациенты", "врача", "врачу",
         "доктора", "доктору", "напомни", "перезвонить", "позвонить", "через", "неделю", "месяц", "задача", "заметка", "примечание",
         "расписание", "записи", "запись", "приём", "прием", "приёмы", "часов", "утра", "вечера", "заплатил", "заплатила",
         "заплатили", "оплатил", "оплатила", "должен", "должна", "долг", "долги", "телефон", "когда", "следующий", "последний",
         "визит", "визита", "гигиены", "гигиена", "месяцев", "больше", "склад", "складе", "сводка", "неделя", "этом", "этот",
         "году", "прошлый", "прошлом", "году", "клиники", "клиника", "всего", "сумма", "задачи", "мои", "есть", "свободное",
         "время", "окно", "окна", "карточку", "карточка", "открой", "покажи", "напиши", "добавь", "про", "она", "него", "неё",
         "нее", "его", "них"} | set(MONTHS_GEN) | {w + "у" for w in ("недел",)}
_ENDS = ("ому", "ему", "ыми", "ими", "ой", "ей", "ую", "юю", "ым", "им", "ом", "ем", "ов", "ев", "у", "ю", "а", "я", "е", "ы", "и")


def _stem(w):
    w = _low(w)
    for e in _ENDS:
        if w.endswith(e) and len(w) - len(e) >= 4:
            return w[: -len(e)]
    return w


def _words(text):
    return [w for w in re.findall(r"[A-Za-zА-Яа-яЁё-]{3,}", str(text or "")) if _low(w) not in _STOP
            and not any(re.fullmatch(x, _low(w)) for x in WD_RE + MONTH_RE)]


def surname_forms(s):
    """Case forms of a Russian surname: {'nom', 'gen', 'dat', 'acc', 'ins', 'pre'} → word (lower case)."""
    s = _low(s)
    if re.search(r"(?:ов|ев|ёв|ин|ын)а$", s):
        b = s[:-1]
        return {"nom": s, "gen": b + "ой", "dat": b + "ой", "acc": b + "у", "ins": b + "ой", "pre": b + "ой"}
    if re.search(r"(?:ов|ев|ёв|ин|ын)$", s):
        return {"nom": s, "gen": s + "а", "dat": s + "у", "acc": s + "а", "ins": s + "ым", "pre": s + "е"}
    if s.endswith(("ская", "цкая")):
        b = s[:-2]
        return {"nom": s, "gen": b + "ой", "dat": b + "ой", "acc": b + "ую", "ins": b + "ой", "pre": b + "ой"}
    if s.endswith(("ский", "цкий")):
        b = s[:-2]
        return {"nom": s, "gen": b + "ого", "dat": b + "ому", "acc": b + "ого", "ins": b + "им", "pre": b + "ом"}
    if s.endswith("ая"):
        b = s[:-2]
        return {"nom": s, "gen": b + "ой", "dat": b + "ой", "acc": b + "ую", "ins": b + "ой", "pre": b + "ой"}
    return {"nom": s}   # Ли, Ким, Шевчук…: the program does not guess


def _case_wanted(text):
    """Which case the question puts the patient in: «запиши Петрову» — accusative, «перезвонить Петровой» — dative."""
    t = _low(text)
    if re.search(r"\bу\s+\w+$|\bу\s+[а-яё]+\b", t) and re.search(r"выручк|заплат|долг|телефон|когда", t):
        return "gen"
    if re.search(r"перезвон|позвон|напомни|напиши|отправ|сообщ", t):
        return "dat"
    if re.search(r"заметк|примечани|карточк", t):
        return "gen"
    if re.search(r"запиш|запис|найди|покажи|открой|пригласи|перенеси", t):
        return "acc"
    return "nom"


class Assistant:
    def __init__(self, api):
        self.api = api
        self.db = api._db

    # -------------------------------------------------------- who asks --
    @staticmethod
    def _user():
        try:
            from auth import _current
            return getattr(_current, "user", None)
        except Exception:  # noqa: BLE001
            return None

    def _perms(self):
        u = self._user()
        if not u:
            from auth import PERM_KEYS
            return set(PERM_KEYS)       # the desktop window itself and tests: everything
        from auth import Auth
        return set(Auth.effective_perms(u))

    def _can(self, tool):
        return bool(self._perms() & set(TOOLS[tool][0]))

    def _my_doctor(self):
        u = self._user()
        if u and u.get("doctor_id"):
            return str(u["doctor_id"])
        return None

    # ----------------------------------------------------------- lookups --
    def _doctor_hits(self, text):
        """[(doctor, word, after «к / у / врач»)] — a doctor named in the text by any case form of the surname."""
        toks = re.findall(r"[A-Za-zА-Яа-яЁё-]+", str(text or ""))
        out = []
        for i, w in enumerate(toks):
            lw = _low(w)
            if len(lw) < 3:
                continue
            for d in self.db.doctors():
                sur = str(d["name"] or "").split()[:1]
                if sur and (lw in surname_forms(sur[0]).values() or (len(_stem(lw)) >= 4 and _low(sur[0]).startswith(_stem(lw)))):
                    pre = i > 0 and _low(toks[i - 1]) in ("к", "у", "врач", "врача", "врачу", "доктор", "доктора", "доктору", "ко")
                    out.append((d, lw, pre))
        return out

    def find_doctors(self, text):
        hits = sorted(self._doctor_hits(text), key=lambda h: not h[2])
        out = []
        for d, _, _ in hits:
            if d not in out:
                out.append(d)
        return out

    def find_patients(self, text, skip_doctors=()):
        """Patients whose surname is in the text («Петрову» → Петрова). A word that names a doctor («к Гусевой») is
        skipped; a doctor's surname without «к / у» is still a patient when there is such a patient."""
        doc_words = {w: pre for _, w, pre in self._doctor_hits(text)} if skip_doctors else {}
        words = _words(text)
        want = _case_wanted(text)
        for i, w in enumerate(words):
            s, lw = _stem(w), _low(w)
            if len(s) < 3 or doc_words.get(lw):
                continue
            rows = self.db.q("SELECT id, name, phone, birth FROM patients WHERE search LIKE ? ORDER BY name LIMIT 60", (f"{s}%",))
            hit = [r for r in rows if _low(str(r["name"] or "").split()[0]).startswith(s)]
            if not hit:
                continue
            # the exact case form wins: «Петрову» after «запиши» is Петрова, after «перезвонить» — Петров
            exact = [r for r in hit if lw in surname_forms(str(r["name"]).split()[0]).values()]
            if exact:
                by_case = [r for r in exact if surname_forms(str(r["name"]).split()[0]).get(want) == lw]
                hit = by_case or exact
            rest = [_stem(x) for x in words[i + 1:i + 3] if len(_stem(x)) >= 3]
            if len(hit) > 1 and rest:  # «Смирнову Ольгу Петровну» — the first name and patronymic narrow it down
                score = {r["id"]: sum(1 for st in rest if any(_low(p).startswith(st) for p in str(r["name"]).split()[1:3])) for r in hit}
                best = max(score.values())
                hit = [r for r in hit if score[r["id"]] == best] if best else hit
            return hit
        return []

    # -------------------------------------------------------------- ask --
    def ask(self, text, ctx=None):
        text = " ".join(str(text or "").split())[:500]
        ctx = ctx or {}
        if not text:
            return self._help()
        intent = self.route(text)
        engine = "rules"
        if intent is None and ai.enabled():
            try:
                intent, engine = self._route_ai(text), "ai"
            except ValueError:
                intent = None
        if intent is None or intent["tool"] == "help":
            return self._help() if intent else self._free(text)
        if intent["tool"] == "free":
            return self._free(text)
        tool = intent["tool"]
        if not self._can(tool):
            return {"tool": tool, "text": "Для этого вопроса нужны права, которых у вашей учётной записи нет. Обратитесь к директору.",
                    "denied": True}
        try:
            out = getattr(self, "t_" + tool)(text, intent, ctx)
        except ValueError as e:
            out = {"text": str(e)}
        out.setdefault("tool", tool)
        out["engine"] = engine
        return out

    def route(self, text):
        """Simple rules → {'tool': ...} or None when the question is unknown."""
        t = _low(text)
        if re.search(r"что ты умеешь|что умеешь|^помо(щь|ги)\b|^help|^справка|какие вопросы", t):
            return {"tool": "help"}
        if re.match(r"^(?:переведи|перевести|перевод)\b", t):
            return {"tool": "translate"}
        if re.search(r"\b(запиш|запис\w+\s+(?:на|к)\b|назначь|поставь\s+на\s+при[её]м)", t) and not re.search(r"\bзаписи\b|кто записан|сколько записей", t):
            return {"tool": "book"}
        if re.search(r"напомн|перезвон|^задач|поставь задачу|позвонить\s|набрать", t):
            return {"tool": "task"}
        if re.search(r"^(заметк|примечани|запомни)", t):
            return {"tool": "note"}
        if re.search(r"выручк|поступлен|заработ|оборот|сколько\s+(?:денег|заплатил|оплатил|принес)|заплатил|оплатил\w*\s+за", t):
            return {"tool": "revenue"}
        if re.search(r"\bдолг|\bдолж|задолж", t):
            return {"tool": "debts"}
        if re.search(r"без\s+(?:гигиен|чистк|визит|при[её]м)|не\s+(?:был|приходил|появлял)|давно не|дн\w+ рожд|именинник|план\w*\s+не\s+(?:начат|заверш)|незаверш|не\s+начал", t):
            return {"tool": "segment"}
        if re.search(r"мои задачи|задачи на сегодня|что мне (?:сделать|сегодня)|просроченн\w+ задач", t):
            return {"tool": "tasks"}
        if re.search(r"склад|заканчива|материал|остатк|просроч|срок годн", t):
            return {"tool": "stock"}
        if re.search(r"сводк|итоги недели|как прошла неделя|отч[её]т за неделю", t):
            return {"tool": "week"}
        if re.search(r"кто\s+(?:у меня|записан|сегодня|завтра|придет|придёт)|расписани|записи на|при[её]м\w*\s+(?:на|сегодня|завтра)|сколько записей|кто на|свободн\w+ (?:время|окн)", t):
            return {"tool": "schedule"}
        if re.search(r"найди|телефон|когда\s+(?:следующ|последн|был|придет|придёт)|карточк|пациент", t) or self.find_patients(text):
            return {"tool": "patient"}
        return None

    def _route_ai(self, text):
        today = date.today()
        task = ROUTE_TASK.replace("{today}", today.isoformat()).replace("{wd}", ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][today.weekday()])
        raw = ai.generate(task, text)
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("ИИ не понял вопрос")
        try:
            j = json.loads(m.group(0))
        except ValueError as e:
            raise ValueError("ИИ не понял вопрос") from e
        tool = str(j.get("tool") or "")
        if tool not in TOOLS and tool != "free":
            raise ValueError("ИИ не понял вопрос")
        return {"tool": tool, "ai": {k: j.get(k) for k in ("name", "doctor", "date", "date_to", "time", "months", "service", "text")}}

    # the model gave names and dates in its own fields: put them into the text the tools read
    @staticmethod
    def _merged(text, intent):
        a = intent.get("ai") or {}
        extra = " ".join(str(a.get(k) or "") for k in ("name", "doctor"))
        return f"{text} {extra}".strip(), a

    def _help(self):
        can = [k for k in TOOLS if self._can(k)]
        ex = [e for e, tool in EXAMPLES if tool in can]
        return {"tool": "help", "text": "Спросите о данных программы простыми словами. Например:" if ex
                else "Для вашей учётной записи пока нет разделов, о которых можно спросить.",
                "examples": ex, "ai": ai.enabled()}

    def _free(self, text):
        if not ai.enabled():
            h = self._help()
            h["text"] = "Не понял вопрос. Без ИИ помощник отвечает на вопросы о данных программы. " + h["text"]
            return h
        try:
            return {"tool": "free", "text": ai.generate(FREE_TASK, text, max_chars=FREE_LIMIT), "engine": "ai", "ai_answer": True}
        except ValueError as e:
            return {"tool": "free", "text": f"ИИ сейчас недоступен: {e}"}

    # ------------------------------------------------------------- tools --
    def _patient_of(self, text, ctx, need=True):
        docs = [d["name"] for d in self.db.doctors()]
        found = self.find_patients(text, docs)
        if not found and ctx.get("patient_id"):
            p = self.db.one("SELECT id, name, phone, birth FROM patients WHERE id=?", (str(ctx["patient_id"]),))
            if p:
                return p, []
        if len(found) == 1:
            return found[0], []
        if not found:
            if need:
                raise ValueError("Не нашёл пациента. Напишите фамилию, например: «Запиши Петрову на четверг».")
            return None, []
        return None, found

    def _choose(self, found):
        return {"text": f"Нашлось несколько пациентов ({len(found)}) — уточните имя или откройте нужного:",
                "rows": [{"label": r["name"], "sub": (r["phone"] or "") + (f" · {r['birth'][:4]} г. р." if r.get("birth") else ""),
                          "go": {"patient": r["id"]}} for r in found[:12]]}

    def _visits(self, a, b, doctor_id=None):
        rows = self.db.q(f"""SELECT {self.db.VISIT_COLS} FROM ({self.db.ALL_VISITS}) a {self.db.VISIT_JOINS}
                             WHERE a.start >= ? AND a.start < ? ORDER BY a.start""", (a.isoformat(), (b + timedelta(days=1)).isoformat()))
        rows = [r for r in rows if status_kind(r["status"]) not in ("cancel", "noshow")]
        return [r for r in rows if not doctor_id or str(r["doctor_id"]) == str(doctor_id)]

    def t_schedule(self, text, intent, ctx):
        text, a = self._merged(text, intent)
        today = date.today()
        day = parse_day(text) or _ai_day(a) or today  # the rules count days of the week better than a small model
        per = parse_period(text) if re.search(r"недел", _low(text)) else None
        a0, b0 = per or (day, day)
        docs = self.find_doctors(text)
        doc = docs[0] if docs else None
        mine = bool(re.search(r"у меня|мои|ко мне", _low(text)))
        did = str(doc["id"]) if doc else (self._my_doctor() if mine else None)
        if mine and not did:
            mine_note = " (ваша учётная запись не связана с врачом — показываю всех)"
        else:
            mine_note = ""
        rows = self._visits(a0, b0, did)
        who = f", врач {_short(doc['name'])}" if doc else (", у вас" if did and mine else "")
        when = _fmt(a0) if a0 == b0 else f"{_fmt(a0)} — {_fmt(b0)}"
        if re.search(r"свободн", _low(text)):
            return self._free_slots(a0, did, who)
        if not rows:
            return {"text": f"{when.capitalize()}{who}: записей нет{mine_note}."}
        return {"text": f"{when.capitalize()}{who}: {len(rows)} {_plural(len(rows), 'запись', 'записи', 'записей')}{mine_note}.",
                "rows": [{"label": f"{r['start'][8:10]}.{r['start'][5:7]} {r['start'][11:16]}" if a0 != b0 else r["start"][11:16],
                          "sub": " · ".join(x for x in [r["patient_name"] or "без пациента", "" if did else _short(r["doctor_name"]), r["title"] or ""] if x),
                          "go": {"visit": r["id"]}} for r in rows[:40]]}

    def _hours(self):
        import config
        s = config.load_settings()
        return int(s.get("day_start") or 8), int(s.get("day_end") or 21)

    def _free_slots(self, day, did, who):
        h0, h1 = self._hours()
        busy = [(int(r["start"][11:13]) * 60 + int(r["start"][14:16]), int((r["end"] or r["start"])[11:13]) * 60 + int((r["end"] or r["start"])[14:16]))
                for r in self._visits(day, day, did)] if did else []
        if not did:
            return {"text": "Скажите, у какого врача искать свободное время, например: «свободное время у Гусевой завтра»."}
        now = datetime.now()
        free, t = [], h0 * 60
        while t + 30 <= h1 * 60 and len(free) < 12:
            if not any(s < t + 30 and e > t for s, e in busy) and (day > now.date() or t > now.hour * 60 + now.minute):
                free.append(f"{t // 60:02d}:{t % 60:02d}")
            t += 30
        return {"text": (f"Свободное время {_fmt(day)}{who}: " + ", ".join(free) + ".") if free else f"{_fmt(day).capitalize()}{who}: свободного времени нет."}

    def t_patient(self, text, intent, ctx):
        text, _ = self._merged(text, intent)
        p, many = self._patient_of(text, ctx)
        if many:
            return self._choose(many)
        perms = self._perms()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        vis = [v for v in self.db.q(f"SELECT a.start, a.status, a.title, d.name AS doctor_name FROM ({self.db.ALL_VISITS}) a "
                                     "LEFT JOIN doctors d ON d.id=a.doctor_id WHERE a.patient_id=? ORDER BY a.start", (p["id"],))
               if status_kind(v["status"]) not in ("cancel", "noshow")]
        past = [v for v in vis if v["start"] < now]
        fut = [v for v in vis if v["start"] >= now]
        lines = []
        if p["phone"]:
            lines.append(f"Телефон: {p['phone']}")
        if past:
            lines.append(f"Последний визит: {past[-1]['start'][8:10]}.{past[-1]['start'][5:7]}.{past[-1]['start'][:4]} · {_short(past[-1]['doctor_name'])}")
        lines.append(f"Следующий визит: {fut[0]['start'][8:10]}.{fut[0]['start'][5:7]} в {fut[0]['start'][11:16]} · {_short(fut[0]['doctor_name'])}"
                     if fut else "Следующего визита нет.")
        if perms & {"payments", "billing", "reports", "accounting"}:
            bal = self.api._local.balance(p["id"])
            if bal < -0.009:
                lines.append(f"Долг: {_rub(-bal)}")
        if perms & {"billing", "payments"}:
            pl = self.db.one("SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS s FROM invoices WHERE patient_id=? AND kind='plan' "
                             "AND COALESCE(plan_status,'Предварительный') IN ('Предварительный','Подтверждён','Активен','Брошен')", (p["id"],))
            if pl["n"]:
                lines.append(f"Открытых планов лечения: {pl['n']} на {_rub(pl['s'])}")
        return {"text": p["name"], "lines": lines, "rows": [{"label": "Открыть карточку", "sub": "", "go": {"patient": p["id"]}}]}

    def t_revenue(self, text, intent, ctx):
        text, a = self._merged(text, intent)
        per = parse_period(text)
        if a.get("date") and re.match(r"\d{4}-\d{2}-\d{2}$", str(a["date"])):
            d0 = date.fromisoformat(a["date"])
            d1 = date.fromisoformat(a["date_to"]) if re.match(r"\d{4}-\d{2}-\d{2}$", str(a.get("date_to") or "")) else d0
            per = per or (d0, d1)
        today = date.today()
        a0, b0 = per or (today.replace(day=1), today)
        when = _fmt(a0) if a0 == b0 else f"{_fmt(a0)} — {_fmt(b0)}"
        docs = self.find_doctors(text)
        mine = re.search(r"у меня|моя|мой|мне\b", _low(text)) and self._my_doctor()
        rep = self.api._reports.revenue(a0.isoformat(), b0.isoformat())  # `to` is inclusive
        if docs or mine:
            did = str(docs[0]["id"]) if docs else self._my_doctor()
            r = next((x for x in rep["by_doctor"] if str(x["doctor_id"]) == did), None)
            name = docs[0]["name"] if docs else "у вас"
            if not r:
                return {"text": f"{when.capitalize()}: у врача {name} счетов и оплат нет." if docs else f"{when.capitalize()}: у вас счетов и оплат нет."}
            return {"text": f"{name}, {when}: поступило {_rub(r['paid'])}, выставлено счетов на {_rub(r['billed'])} "
                            f"({r['invoices']} {_plural(r['invoices'], 'счёт', 'счёта', 'счетов')}, {r['patients']} {_plural(r['patients'], 'пациент', 'пациента', 'пациентов')})."}
        p, many = self._patient_of(text, {}, need=False)
        if many:
            return self._choose(many)
        if p:
            s = self.db.one("SELECT COALESCE(SUM(amount),0) AS s, COUNT(*) AS n FROM payments WHERE patient_id=? AND created_at >= ? AND created_at < ?",
                            (p["id"], a0.isoformat(), (b0 + timedelta(days=1)).isoformat()))
            return {"text": f"{p['name']}, {when}: оплачено {_rub(s['s'])} ({s['n']} {_plural(s['n'], 'оплата', 'оплаты', 'оплат')}).",
                    "rows": [{"label": "Открыть карточку", "sub": "", "go": {"patient": p["id"]}}]}
        top = [x for x in rep["by_doctor"] if x["paid"] or x["billed"]][:8]
        return {"text": f"Клиника, {when}: поступило {_rub(rep['paid'])}, выставлено счетов на {_rub(rep['billed'])}.",
                "rows": [{"label": _short(x["name"]), "sub": f"поступило {_rub(x['paid'])} · счета {_rub(x['billed'])}"} for x in top]}

    def t_debts(self, text, intent, ctx):
        d = self.api._reports.debts()
        rows = d["debts"]
        if not rows:
            return {"text": "Долгов у пациентов нет."}
        total = sum(x["total"] for x in rows)
        return {"text": f"Должны клинике {len(rows)} {_plural(len(rows), 'пациент', 'пациента', 'пациентов')} на {_rub(total)}.",
                "rows": [{"label": x["name"], "sub": f"{_rub(x['total'])}" + (f" · {x['phone']}" if x["phone"] else ""), "go": {"patient": x["patient_id"]}}
                         for x in rows[:15]]}

    def t_segment(self, text, intent, ctx):
        text, a = self._merged(text, intent)
        t = _low(text)
        m = re.search(r"(\d+)\s*(?:месяц|мес)", t) or re.search(r"(полгода|год)", t)
        months = int(a.get("months") or 0) or (int(m.group(1)) if m and m.group(1).isdigit() else 6 if m and m.group(1) == "полгода" else 12 if m else 6)
        f, what = {}, ""
        svc = str(a.get("service") or "")
        if re.search(r"гигиен|чистк", t) or re.search(r"гигиен|чистк", _low(svc)):
            return self._no_hygiene(months)
        elif re.search(r"рожден|именинник", t):
            days = 7 if re.search(r"недел", t) else 31 if re.search(r"месяц", t) else 1 if re.search(r"сегодня", t) else 7
            f, what = {"birthday_days": days}, f"День рождения в ближайшие {days} дн."
        elif re.search(r"план", t):
            kind = "not_started" if re.search(r"не\s+начат|не\s+начал", t) else "unfinished"
            f, what = {"plan": kind}, "План лечения не начат" if kind == "not_started" else "План лечения не завершён"
        else:
            f, what = {"months": months, "no_future": True}, f"Не были больше {months} мес. и не записаны"
        res = self.api._crm.segment_run(f)
        return {"text": f"{what}: {res['count']} {_plural(res['count'], 'пациент', 'пациента', 'пациентов')}"
                        + (f", с телефоном {res['with_phone']}" if res["count"] else "") + ".",
                "rows": [{"label": r["name"], "sub": " · ".join(x for x in [r["phone"] or "", r["info"]] if x), "go": {"patient": r["patient_id"]}}
                         for r in res["rows"][:20]],
                "more": {"view": "marketing", "segment": f} if res["count"] else None}

    def _no_hygiene(self, months):
        """Patients who come to the clinic (a visit in two years) but had no hygiene in `months` (or never)."""
        today = date.today()
        border = (today - timedelta(days=int(months * 30.4))).isoformat()
        active = (today - timedelta(days=730)).isoformat()
        last = {}
        for pid, d, title in self.api._crm._events("2000-01-01"):
            if "гигиен" in title:
                last[pid] = max(last.get(pid, ""), d)
        rows = [r for r in self.api._crm.segment_run({})["rows"] if r["start"] and r["start"] >= active
                and (last.get(r["patient_id"]) or "") < border]
        for r in rows:
            h = last.get(r["patient_id"])
            r["info"] = f"гигиена {h[8:10]}.{h[5:7]}.{h[:4]}" if h else "гигиены в программе не было"
        n = len(rows)
        return {"text": f"Без профгигиены больше {months} мес.: {n} {_plural(n, 'пациент', 'пациента', 'пациентов')}"
                        + " (из тех, кто был в клинике за два года).",
                "rows": [{"label": r["name"], "sub": " · ".join(x for x in [r["phone"] or "", r["info"]] if x), "go": {"patient": r["patient_id"]}}
                         for r in rows[:20]],
                "more": {"view": "marketing", "segment": {"service": "гигиен", "service_months": months}} if n else None}

    def t_tasks(self, text, intent, ctx):
        u = self._user()
        res = self.api._crm.tasks({"scope": "my"}, u["login"] if u else "")
        today = date.today().isoformat()
        rows = [r for r in res["rows"] if (r["due"] or today) <= today]
        if not rows:
            return {"text": "На сегодня задач нет."}
        late = sum(1 for r in rows if r["overdue"])
        return {"text": f"Задач на сегодня: {len(rows)}" + (f", из них просрочено {late}" if late else "") + ".",
                "rows": [{"label": r["title"], "sub": " · ".join(x for x in [r["patient_name"] or "", r["phone"] or "",
                          "просрочено" if r["overdue"] else ""] if x), "go": {"patient": r["patient_id"]} if r["patient_id"] else {"view": "marketing"}}
                         for r in rows[:20]]}

    def t_stock(self, text, intent, ctx):
        mats = self.api._stock.materials()
        low = [m for m in mats if m["low"] or m["balance"] < 0]
        exp = [m for m in mats if m.get("exp_state") in ("expired", "soon")]
        if not low and not exp:
            return {"text": "На складе всё в порядке: ничего не заканчивается и сроки годности не истекают."}
        rows = [{"label": m["name"], "sub": f"осталось {m['balance']:g} {m['unit'] or ''} (минимум {m['min_qty']:g})", "go": {"view": "stock"}} for m in low[:15]]
        rows += [{"label": m["name"], "sub": "срок годности истёк" if m["exp_state"] == "expired" else "срок годности скоро истекает",
                  "go": {"view": "stock"}} for m in exp[:10] if m not in low]
        return {"text": f"Заканчиваются: {len(low)}, истекает срок: {len(exp)}.", "rows": rows}

    def t_week(self, text, intent, ctx):
        w = self.api._dir.weekly()
        return {"text": w["title"], "lines": w["lines"], "rows": [{"label": "Открыть экран директора", "sub": "", "go": {"view": "director"}}]}

    def t_translate(self, text, intent, ctx):
        """«Переведи на английский: Ждём вас завтра в 10:00» → the translation (to copy into a message)."""
        import ai_docs
        m = re.match(r"^\s*(?:переведи|перевести|перевод)\s*(?:на\s+)?([а-яё]+?)(?:ий|ый|ой|ом|у)?\s*(?:язык\w*)?\s*[:,—-]\s*(.+)$", text, re.I | re.S)
        if not m:
            raise ValueError("Напишите так: «Переведи на английский: текст сообщения».")
        stem, body = _low(m.group(1)), m.group(2).strip()
        lang = next((k for k, v in ai_docs.LANGS.items() if v.startswith(stem[:5])), None)
        if not lang:
            raise ValueError("Перевожу на: " + ", ".join(ai_docs.LANGS.values()) + ".")
        names = [r["name"] for r in self.find_patients(body)[:1]]
        res = ai_docs.translate(body.split("\n"), lang, names)
        return {"text": f"Перевод ({ai_docs.LANG_TITLE[lang]}):", "copy": "\n".join(res["lines"]), "engine": "ai", "ai_answer": True}

    # ------------------------------------------------- proposed changes --
    def t_book(self, text, intent, ctx):
        text, a = self._merged(text, intent)
        docs = self.find_doctors(text)
        p, many = self._patient_of(text, ctx)
        if many:
            return self._choose(many)
        doc = docs[0] if docs else None
        did = str(doc["id"]) if doc else self._my_doctor()
        if not did:
            raise ValueError("К какому врачу записать? Например: «Запиши Петрову на четверг к Гусевой».")
        doc_name = doc["name"] if doc else next((d["name"] for d in self.db.doctors() if str(d["id"]) == did), "")
        day = parse_day(text) or _ai_day(a)
        if not day:
            raise ValueError("На какой день записать? Например: «на четверг», «на 15 ноября», «завтра».")
        if day < date.today():
            raise ValueError("Этот день уже прошёл — назовите другой.")
        tm = str(a.get("time") or "") if re.match(r"\d{2}:\d{2}$", str(a.get("time") or "")) else parse_time(text)
        dur = 60 if re.search(r"на\s+час|час\b", _low(text)) and not re.search(r"\d\s*час", _low(text)) else 30
        h0, h1 = self._hours()
        visits = self._visits(day, day, did)
        busy = [(int(r["start"][11:13]) * 60 + int(r["start"][14:16]), int((r["end"] or r["start"])[11:13]) * 60 + int((r["end"] or r["start"])[14:16]), r)
                for r in visits]
        note = ""
        if tm:
            t0 = int(tm[:2]) * 60 + int(tm[3:])
            clash = [r for s, e, r in busy if s < t0 + dur and e > t0]
            if clash:
                note = f"Внимание: в это время у врача уже {clash[0]['patient_name'] or 'запись'} ({clash[0]['start'][11:16]})."
        else:
            now = datetime.now()
            t0 = next((t for t in range(h0 * 60, h1 * 60 - dur + 1, 30)
                       if not any(s < t + dur and e > t for s, e, _ in busy) and (day > now.date() or t > now.hour * 60 + now.minute)), None)
            if t0 is None:
                raise ValueError(f"{_fmt(day).capitalize()} у врача {doc_name} свободного времени нет — назовите другой день.")
            note = "Время выбрано первое свободное — его можно поменять в записи."
        start = f"{day.isoformat()} {t0 // 60:02d}:{t0 % 60:02d}"
        end_m = t0 + dur
        end = f"{day.isoformat()} {end_m // 60:02d}:{end_m % 60:02d}"
        wd = WD_SHORT[day.weekday()]
        label = f"Записать на приём: {p['name']} — {wd}, {_fmt(day)}, {start[11:]}, врач {_short(doc_name)}?"
        return {"text": label, "lines": [note] if note else [],
                "action": {"method": "save_visit", "args": [{"patient_id": p["id"], "doctor_id": did, "start": start, "end": end,
                                                             "status": "Запланирован", "title": "", "comment": "Записано через помощника"}],
                           "ok": "Записать", "done": f"{p['name']} записан(а) на {_fmt(day)}, {start[11:]}", "go": {"day": day.isoformat()}}}

    def t_task(self, text, intent, ctx):
        text2, a = self._merged(text, intent)
        p, many = self._patient_of(text2, ctx, need=False)
        if many:
            return self._choose(many)
        due = parse_due(text) or date.today()
        what = str(a.get("text") or "").strip() or re.sub(r"^(?:напомни\w*|поставь задачу|задача)\s*[:,-]?\s*", "", text, flags=re.I)
        what = re.sub(r"\s+через\s+\S+(?:\s+(?:дн\w*|недел\w*|месяц\w*))?|\s+(?:завтра|послезавтра|сегодня)\b", "", what, flags=re.I).strip(" ,.")
        what = (what[0].upper() + what[1:]) if what else "Связаться с пациентом"
        u = self._user()
        f = {"title": what[:200], "patient_id": p["id"] if p else None, "due": due.isoformat(), "assignee": u["login"] if u else "",
             "comment": "Поставлено через помощника"}
        return {"text": f"Поставить задачу «{f['title']}»" + (f" по пациенту {p['name']}" if p else "") + f" на {_fmt(due)}?",
                "action": {"method": "crm_task_save", "args": [f], "ok": "Поставить задачу", "done": "Задача поставлена — она в CRM → «Задачи»"}}

    def t_note(self, text, intent, ctx):
        text2, a = self._merged(text, intent)
        p, many = self._patient_of(text2, ctx)
        if many:
            return self._choose(many)
        body = str(a.get("text") or "").strip() or re.sub(r"^(?:заметк\w*|примечани\w*|запомни)\s*[:,-]?\s*", "", text, flags=re.I)
        sur = str(p["name"] or "").split()[0] if p["name"] else ""
        if sur:  # «заметка Петровой: …» → the text after the name (and first name)
            forms = sorted(set(surname_forms(sur).values()) | {_low(sur)}, key=len, reverse=True)
            body = re.sub(r"^(?:для\s+|к\s+|про\s+)?(?:" + "|".join(map(re.escape, forms)) + r")(?:\s+[А-ЯЁ][а-яё]+){0,2}\s*[:,-]\s*", "", body, flags=re.I)
            body = re.sub(r"^(?:для\s+|к\s+|про\s+)?(?:" + "|".join(map(re.escape, forms)) + r")\s+", "", body, flags=re.I)
        body = body.strip(" :,-") or text
        return {"text": f"Записать примечание в карточку {p['name']}: «{body}»?",
                "action": {"method": "add_note", "args": [p["id"], body], "ok": "Записать", "done": "Примечание записано в карточку"}}


# ------------------------------------------------------------ voice notes --
def voice_note(text: str, today=None) -> dict:
    """13.4: a spoken note → {'text', 'task': {'title', 'due'} | None}. «Перезвонить через неделю» becomes a task."""
    t = " ".join(str(text or "").split())
    if not t:
        return {"text": "", "task": None}
    t = t[0].upper() + t[1:]
    low = _low(t)
    task = None
    if re.search(r"перезвон|позвонить|напомн|пригласить|записать на|связаться|написать пациент", low):
        due = parse_due(low, today) or (today or date.today()) + timedelta(days=1)
        title = re.sub(r"\s+через\s+\S+(?:\s+(?:дн\w*|недел\w*|месяц\w*))?", "", t, flags=re.I).strip(" ,.")
        task = {"title": title[:200] or "Связаться с пациентом", "due": due.isoformat()}
    return {"text": t if t.endswith((".", "!", "?")) else t + ".", "task": task}
