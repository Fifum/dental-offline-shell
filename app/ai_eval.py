"""2.13: the program's test questions for an AI model — how fast, how exact and how Russian its answers are on
the work it does in the clinic: dictation into the record, documents for the patient, a plan option, translation,
understanding the assistant's questions, a general question.

Every case is made of the program's own prompts (the same as in the work), so a better score here is a better
program. The data are invented: no patient's data is used. Run: Settings → «Голос и ИИ» → «Проверить качество»,
or `python tools/ai_eval.py <model> …` to compare models."""
from __future__ import annotations

import json
import re
import time
from datetime import date, timedelta

import ai

T = date.today()


def _ru_share(text):
    """Share of Cyrillic among letters (1.0 — all Russian). Chinese or Japanese characters are a heavy fault."""
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", text)
    cjk = len(re.findall(r"[぀-ヿ一-鿿]", text))
    if not letters:
        return 0.0
    ru = sum(1 for ch in letters if re.match(r"[А-Яа-яЁё]", ch))
    return max(0.0, ru / len(letters) - cjk * 0.1)


def _has(text, *alts):
    low = text.lower().replace("ё", "е")
    return any(a in low for a in alts)


def _json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


DICTATION = ("Жалобы на боль от холодного в тридцать шестом зубе. Объективно: на 36 глубокая кариозная полость, зондирование "
             "болезненно по дну. Диагноз: кариес дентина 36. Лечение: инфильтрационная анестезия Ультракаин 1,7 мл, препарирование, "
             "пломба из композита Филтек. Рекомендации: не есть два часа.")
REC_EXTRACTION = ("Дата приёма: 2026-11-05\nЖалобы: боль в зубе 48\nОбъективно: зуб 48 разрушен ниже уровня десны\n"
                  "Лечение: проводниковая анестезия Ультракаин 1,7 мл, удаление зуба 48, гемостаз\n"
                  "Диагноз: K08.3 Задержка корня зуба (зуб 48)")
REC_PULPITIS = ("Жалобы: ночные боли в зубе 26\nОбъективно: глубокая кариозная полость, вскрыта пульпа\n"
                "Диагноз: K04.0 Пульпит (зуб 26)\nЛечение: анестезия, экстирпация пульпы, временная пломба")


def _cases():
    import ai_docs
    import assistant
    wd = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][T.weekday()]
    route = assistant.ROUTE_TASK.replace("{today}", T.isoformat()).replace("{wd}", wd)
    fri = T + timedelta(days=(4 - T.weekday()) % 7)

    def c_dictation(out):
        j = _json(out) or {}
        dg = j.get("diagnoses") or []
        teeth = {str(k).replace(".", ""): v for k, v in (j.get("teeth") or {}).items()}
        checks = [bool(j), any(str(d.get("code", "")).upper().replace("К", "K") == "K02.1" and str(d.get("tooth", "")).replace(".", "") == "36"
                                for d in dg if isinstance(d, dict)),
                  teeth.get("36") == "Пломба", _has(str(j.get("complaints", "")), "холод"),
                  _has(str(j.get("treatment", "")), "ультракаин"), not _has(str(j.get("treatment", "")), "артикаин", "лидокаин")]
        return sum(checks) / len(checks), False

    def short(out, kind):  # as long as the program keeps, without a greeting at the start
        return len(out) <= ai_docs.LIMITS[kind] and not ai.GREETING.match(out)

    def sentences(out):
        return len(re.findall(r"[.!?](?:\s|$)", out))

    def c_extraction(out):
        low = out.lower()
        checks = [_has(out, "холод"), bool(re.search(r"не\s+(?:\w+\s+)?поло(?:ск|щ)|полоскать\s+нельзя", low)), _has(out, "2 час", "два час", "двух час"),
                  _has(out, "звон", "обратит"), not re.search(r"сол[её]н|содов|ромашк|трав[ая]|настой|антибиот", low),  # nothing invented
                  not re.search(r"K0\d", out), "**" not in out and "#" not in out, short(out, "recommendations"),
                  not re.search(r"^[^\n—–-]{0,80}:\s*$", out.split("\n")[0])]  # a list, no «Вот что делать дома:» heading
        return sum(checks) / len(checks), True

    def c_explain(out):
        n = len(re.findall(r"[.!?](?:\s|$)", out))
        checks = [_has(out, "нерв", "пульп"), _has(out, "канал", "временн", "пломб"), 2 <= n <= 5, not re.search(r"K0\d", out),
                  short(out, "explain")]
        return sum(checks) / len(checks), True

    def c_variant(out):
        checks = [_has(out, "имплант"), _has(out, "коронк"), _has(out, "5 лет", "пять лет"), not re.search(r"\d[\d\s]{3,}\s*(?:₽|руб)", out),
                  short(out, "plan_variant"), sentences(out) <= 2]
        return sum(checks) / len(checks), True

    def c_extract(out):  # sections as «Диагноз: …», only what the record has (there is no anamnesis in it)
        checks = [_has(out, "диагноз:"), _has(out, "k04.0"), "Раздел" not in out, not re.search(r"отягощ|без особенност", out.lower()),
                  not re.search(r"(?m)^\s*Анамнез", out), short(out, "extract"),
                  not re.search(r"ортодонт|консультац|^\s*Рекомендац", out, re.M)]  # the doctor wrote no recommendations
        return sum(checks) / len(checks), True

    def c_en(out):
        checks = [_has(out, "eat", "food"), _has(out, "2 hours", "two hours"), _has(out, "filling"), "36" in out,
                  not re.search(r"[А-Яа-яЁё]{3,}", out.split("|", 1)[-1])]
        return sum(checks) / len(checks), False

    def c_kk(out):
        checks = [bool(re.search(r"[әғқңөұүһі]", out.lower())), "36" in out, "2" in out]
        return sum(checks) / len(checks), False

    def r_check(tool, **want):
        def f(out):
            j = _json(out) or {}
            checks = [str(j.get("tool")) == tool]
            for k, v in want.items():
                got = str(j.get(k) or "").lower()
                checks.append(any(x in got for x in (v if isinstance(v, (list, tuple)) else [v])))
            return sum(checks) / len(checks), False
        return f

    def c_free(out):
        checks = [_has(out, "пульп", "нерв"), _has(out, "периодонт", "корн", "кост"), len(out) <= assistant.FREE_LIMIT]
        return sum(checks) / len(checks), True

    sys_dict = ai.prompt()
    return [
        ("dictation", "Диктовка → поля медкарты (JSON)", sys_dict, DICTATION, c_dictation, "system"),
        ("extraction", "Памятка после удаления", ai_docs.TASKS["recommendations"], REC_EXTRACTION + "\nСтандартные рекомендации клиники "
         "для этого лечения:\n" + "\n".join(x for x in ai_docs._rules("recommendations", {"data": {"treatment": "удаление зуба 48, анестезия",
                                                                                                    "diagnoses": [{"code": "K08.3"}]}}).split("\n")
                                          if x.startswith("— ") and ai_docs.URGENT not in x), c_extraction, "task"),
        ("explain", "Объяснить пульпит пациенту", ai_docs.TASKS["explain"], REC_PULPITIS, c_explain, "task"),
        ("extract", "Выписка из медкарты", ai_docs.TASKS["extract"], REC_PULPITIS, c_extract, "task"),
        ("variant", "Описание варианта плана", ai_docs.TASKS["plan_variant"],
         "Название варианта: Премиум\nУслуги: Имплантат Straumann (зуб 36); Коронка на имплантате, цирконий (зуб 36)\nГарантия: 5 лет\n"
         "Срок лечения: 4 месяца\nЗаметка врача: приживление 3 месяца", c_variant, "task"),
        ("en", "Перевод на английский", ai_docs.translate_task("en"),
         "Переведи на английский язык:\n1| Не принимать пищу 2 часа.\n2| Поставлена пломба на зуб 36.", c_en, "system"),
        ("kk", "Перевод на казахский", ai_docs.translate_task("kk"),
         "Переведи на казахский язык:\n1| Не принимать пищу 2 часа.\n2| Поставлена пломба на зуб 36.", c_kk, "system"),
        ("route_schedule", "Вопрос: расписание врача", route, "Кто записан к Гусевой послезавтра?",
         r_check("schedule", doctor="гусев", date=(T + timedelta(days=2)).isoformat()), "task"),
        ("route_book", "Вопрос: записать пациента", route, "Запишите Смирнову Ольгу на пятницу в 11 к Петрову",
         r_check("book", name="смирнов", doctor="петров", time="11:00", date=fri.isoformat()), "task"),
        ("route_segment", "Вопрос: список пациентов", route, "Покажи тех, кто не приходил на чистку больше года",
         r_check("segment", months=["12", "1"], service=["гигиен", "чистк"]), "task"),
        ("route_free", "Вопрос не о данных", route, "Чем отличается пульпит от периодонтита?", r_check("free"), "task"),
        ("free", "Общий вопрос по стоматологии", assistant.FREE_TASK, "Чем отличается пульпит от периодонтита?", c_free, "task"),
    ]


def run(over=None, progress=None, only=None) -> dict:
    """{'model', 'at', 'score', 'accuracy', 'russian', 'seconds', 'tok_s', 'cases': [...]} for the AI in the settings
    (or `over` = {'provider', 'model'})."""
    import llm_local
    s = {**ai.settings(), **(over or {}), "enabled": True}
    cases = [c for c in _cases() if not only or c[0] in only]
    out = []
    for n, (cid, title, system, user, check, how) in enumerate(cases):
        msgs = ([{"role": "system", "content": system}] if how == "system" else
                [{"role": "system", "content": ai.BASE + "\n" + system}]) + [{"role": "user", "content": user}]
        t0 = time.time()
        llm_local.last_stats.clear()
        try:
            ans, err = ai._chat(msgs, {**s, "timeout": 300}), None
        except ValueError as e:
            ans, err = "", str(e)
        sec = round(time.time() - t0, 1)
        acc, russian_case = check(ans) if ans else (0.0, False)
        st = dict(llm_local.last_stats)
        tok_s = round(st["eval_count"] / (st["eval_duration"] / 1e9), 1) if st.get("eval_duration") else None
        out.append({"id": cid, "title": title, "seconds": sec, "tok_s": tok_s, "accuracy": round(acc, 2),
                    "russian": round(_ru_share(ans), 2) if russian_case else None, "answer": ans[:600], "chars": len(ans), "error": err,
                    "prompt_tokens": st.get("prompt_eval_count"), "tokens": st.get("eval_count")})
        if progress:
            progress(int((n + 1) * 100 / len(cases)) - 1)
    acc = sum(c["accuracy"] for c in out) / max(1, len(out))
    ru = [c["russian"] for c in out if c["russian"] is not None]
    rus = sum(ru) / len(ru) if ru else 0
    secs = [c["seconds"] for c in out if not c["error"]]
    toks = [c["tok_s"] for c in out if c["tok_s"]]
    return {"model": s["model"], "provider": s["provider"], "at": time.strftime("%Y-%m-%d %H:%M"),
            "accuracy": round(acc * 100), "russian": round(rus * 100), "seconds": round(sum(secs) / len(secs), 1) if secs else None,
            "tok_s": round(sum(toks) / len(toks), 1) if toks else None, "score": round((acc * 0.7 + rus * 0.3) * 100),
            "errors": sum(1 for c in out if c["error"]), "cases": out}
