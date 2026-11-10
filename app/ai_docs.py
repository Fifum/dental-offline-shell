"""2.13: texts in seconds — recommendations in plain words, an extract from the record, a letter to the insurance
company, a description of a plan option for the patient, translation of documents and messages.

With the AI on, the model writes a draft from the anonymous record (no name, phone, birth date or address).
Without the AI (or when it fails) the program writes the same draft by simple rules, so the button always works.
The doctor reads, corrects and saves: nothing is saved here."""
from __future__ import annotations

import re

import ai

KINDS = {
    "recommendations": "Рекомендации пациенту простыми словами",
    "extract": "Выписка из медкарты",
    "insurance": "Письмо в страховую компанию",
    "explain": "Объяснение диагноза и лечения пациенту",
}
LANGS = {"en": "английский", "tr": "турецкий", "ka": "грузинский", "hy": "армянский", "kk": "казахский",
         "uz": "узбекский", "ky": "киргизский", "de": "немецкий", "zh": "китайский"}
LANG_TITLE = {"en": "English", "tr": "Türkçe", "ka": "ქართული", "hy": "Հայերեն", "kk": "Қазақша", "uz": "Oʻzbekcha",
              "ky": "Кыргызча", "de": "Deutsch", "zh": "中文"}

TASKS = {
    "recommendations": (
        "Напиши памятку пациенту после приёма по записи врача: что было сделано и что делать дома. Простыми словами, "
        "без латыни и кодов МКБ, 4–7 коротких пунктов, каждый с новой строки и с тире, без вступления, заголовка и "
        "обращения «Уважаемый». Первый пункт — что сделано сегодня. "
        "Бери советы ТОЛЬКО из рекомендаций и назначений врача и из «Стандартных рекомендаций клиники» ниже: один совет — "
        "один пункт, смысл и сроки точно как в совете (что можно — то можно, что нельзя — то нельзя), не соединяй советы. "
        "Своих советов не добавляй: никаких полосканий, растворов, соли, соды, трав, лекарств и сроков, которых нет ниже. "
        "Последний пункт: когда срочно звонить в клинику "
        "(сильная боль, отёк, температура, кровотечение)."),
    "extract": (
        "Составь выписку из медицинской карты стоматологического больного по записи врача: разделы «Жалобы», «Анамнез», "
        "«Объективно», «Диагноз» (с кодом МКБ-10 и номером зуба), «Проведено лечение», «Рекомендации». Официальный "
        "медицинский стиль, только факты из записи, кратко. Каждый раздел — с новой строки в виде «Жалобы: …», "
        "«Диагноз: …» (само слово «Раздел» не пиши). Раздела, о котором в записи ничего нет, не пиши вовсе — не "
        "придумывай «не отягощён», «без особенностей», консультации и советы: «Рекомендации» — только если врач их записал."),
    "insurance": (
        "Составь письмо в страховую компанию (ДМС) о лечении застрахованного по записи врача и списку услуг: обоснование "
        "медицинской необходимости — диагноз с кодом МКБ-10 и зубом, проведённое и планируемое лечение, перечень услуг. "
        "Деловой стиль, 2–3 коротких абзаца, без приветствий и подписи (их добавит программа), без выдуманных сумм и дат."),
    "explain": (
        "Объясни пациенту простыми словами его диагноз и проведённое лечение по записи врача: что это за проблема, "
        "почему её важно лечить, что сделано и чего ожидать. Ровно 3–4 коротких предложения (до 500 знаков), без "
        "латыни, без запугивания, без приветствия и обращения «Уважаемый»."),
    "plan_variant": (
        "Напиши для пациента подпись к варианту плана лечения: чем этот вариант хорош. СТРОГО 1–2 коротких предложения, "
        "всего не больше 200 знаков. Не перечисляй все услуги — назови главное, что получит пациент (например, "
        "«надёжный имплантат с циркониевой коронкой»), и гарантию, если она указана. Без обращения и приветствия "
        "(никаких «Уважаемый пациент»), без цен, без сроков лечения по этапам, без обещаний, которых нет в данных, без "
        "сравнения с другими клиниками.\n"
        "Пример ответа: «Имплантат с циркониевой коронкой — выглядит как свой зуб и служит много лет. Гарантия 5 лет.»"),
}
# the longest text of each kind, in letters: the model gets as many tokens and the reply is cut at whole sentences
# (the plan option's note is kept up to 400 letters, the patient reads it on one card of the presentation)
LIMITS = {"recommendations": 900, "extract": 2500, "insurance": 2000, "explain": 600, "plan_variant": 260}

# ICD-10 → what to tell the patient (offline drafts; the doctor corrects)
PLAIN = {
    "K02": ("кариес — разрушение твёрдых тканей зуба микробами", ["Не принимать пищу 2 часа после пломбирования.",
            "Чистить зубы 2 раза в день мягкой щёткой и пастой с фтором, пользоваться зубной нитью.",
            "Ограничить сладкое и сладкие напитки между едой."]),
    "K03": ("повышенное стирание или налёт на зубах", ["Чистить зубы 2 раза в день, раз в полгода — профессиональная гигиена.",
            "Если сжимаете зубы ночью, обсудите с врачом защитную капу."]),
    "K04.0": ("пульпит — воспаление нерва зуба", ["После анестезии 2–3 часа не есть, чтобы не прикусить щёку и губу.",
              "Несколько дней зуб может ныть при накусывании — это проходит само.",
              "Не нагружать зуб твёрдой пищей до постоянной пломбы или коронки.", "Прийти на следующий этап лечения в назначенный день."]),
    "K04": ("воспаление тканей у корня зуба (периодонтит)", ["Несколько дней зуб может ныть при накусывании — это проходит само.",
            "Не нагружать зуб твёрдой пищей до постоянной пломбы или коронки.", "Прийти на следующий этап лечения в назначенный день."]),
    "K05": ("воспаление дёсен (гингивит или пародонтит)", ["Чистить зубы 2 раза в день мягкой щёткой, промежутки — нитью или ёршиком.",
            "Полоскать рот, если назначено, после чистки зубов.", "Приходить на профессиональную гигиену раз в 3–6 месяцев."]),
    "K06": ("изменения десны", ["Чистить зубы мягкой щёткой без сильного нажима.", "Показываться врачу раз в полгода."]),
    "K07": ("неправильное положение зубов или прикуса", ["Носить аппарат или капы так, как сказал врач.",
            "Тщательно чистить зубы и аппарат после каждой еды."]),
    "K08": ("отсутствие зубов или остаток корня", ["Обсудить с врачом, чем восполнить отсутствующие зубы, чтобы соседние не смещались."]),
    "K10.3": ("альвеолит — воспаление лунки после удаления", ["Не полоскать рот активно, делать ротовые ванночки, если назначено.",
              "Не курить и не пить через трубочку несколько дней."]),
    "K12": ("воспаление слизистой рта", ["Избегать острой, горячей и кислой пищи до заживления.", "Обрабатывать слизистую так, как назначил врач."]),
    "S02.5": ("скол или перелом зуба", ["Не откусывать твёрдое этим зубом до восстановления.", "При боли или подвижности зуба сразу прийти в клинику."]),
    "Z01.2": ("профилактический осмотр", ["Чистить зубы 2 раза в день, пользоваться зубной нитью.", "Приходить на осмотр и гигиену раз в полгода."]),
}
TREAT = [  # words in the treatment → advice after it
    (r"удален|экстракц", ["Не есть 2 часа, в первый день не полоскать рот, не греть щёку, не заниматься спортом.",
                          "Холод на щёку по 15 минут в первые часы.", "Не трогать лунку языком, не курить 2–3 дня."]),
    (r"имплант", ["Первые дни — мягкая пища, жевать другой стороной.", "Не курить и не пить алкоголь, пока заживает десна."]),
    (r"гигиен|ультразвук|air.?flow|скейлинг", ["Сутки не есть красящие продукты: кофе, чай, вино, свёклу.", "Повторить гигиену через 6 месяцев."]),
    (r"коронк|винир|вкладк|мост", ["Временную конструкцию беречь: не жевать на ней липкое и твёрдое.", "Чистить зубы как обычно, у десны — особенно тщательно."]),
    (r"канал|эндодонт", ["Зуб может ныть при накусывании несколько дней — это нормально.", "До постоянной пломбы или коронки не грызть твёрдое этим зубом."]),
    (r"анестез", ["Пока не прошло онемение (2–3 часа), не есть и не пить горячее."]),
]
URGENT = "Если появились сильная боль, отёк, температура выше 38 °C или кровотечение не останавливается — сразу позвоните в клинику."


def _plain(code: str):
    for k in (code, code[:3]):
        if k in PLAIN:
            return PLAIN[k]
    return None


def record_text(rec: dict, services=()) -> str:
    """The record (and services) as short labelled lines for a model. No name, phone, birth date or address."""
    d = (rec or {}).get("data") or rec or {}
    lines = []
    if rec and rec.get("date"):
        lines.append(f"Дата приёма: {rec['date']}")
    for k, t in (("complaints", "Жалобы"), ("anamnesis", "Анамнез"), ("objective", "Объективно"), ("treatment", "Лечение"),
                 ("recommendations", "Рекомендации врача"), ("next_visit", "Следующий визит")):
        if str(d.get(k) or "").strip():
            lines.append(f"{t}: {str(d[k]).strip()}")
    dg = [f"{x.get('code', '')} {x.get('title', '')}" + (f" (зуб {x['tooth']})" if x.get("tooth") else "") for x in d.get("diagnoses") or []]
    if dg:
        lines.append("Диагноз: " + "; ".join(dg))
    rx = [", ".join(str(r.get(k) or "") for k in ("name", "dose", "how", "days") if r.get(k)) for r in d.get("rx") or []]
    if rx:
        lines.append("Назначения: " + "; ".join(rx))
    if services:
        lines.append("Услуги: " + "; ".join(services))
    return "\n".join(lines)


def _rules(kind: str, rec: dict, services=()) -> str:
    d = (rec or {}).get("data") or rec or {}
    dg = d.get("diagnoses") or []
    treat = str(d.get("treatment") or "")
    if kind in ("recommendations", "explain"):
        what, tips = [], []
        for x in dg:
            p = _plain(str(x.get("code") or ""))
            if p:
                what.append(p[0] + (f" (зуб {x['tooth']})" if x.get("tooth") else ""))
                tips += p[1]
        for pat, adv in TREAT:
            if re.search(pat, treat, re.I):
                tips += adv
        if kind == "explain":
            if not what and not treat:
                return "В записи нет диагноза и лечения — объяснение составить не из чего."
            out = (f"У вас {'; '.join(what)}. " if what else "") + (f"Что сделано: {treat.rstrip('.')}." if treat else "")
            return out + " Такие проблемы без лечения обычно усиливаются, поэтому важно пройти лечение до конца и приходить на осмотры."
        own = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", str(d.get("recommendations") or "")) if s.strip()]
        rx = [f"{r['name']}: {', '.join(str(r.get(k)) for k in ('dose', 'how', 'days') if r.get(k))}" for r in d.get("rx") or [] if r.get("name")]
        seen, items = set(), []
        for t in own + rx + tips:
            k = t.lower()[:40]
            if k not in seen:
                seen.add(k)
                items.append(t if t.endswith((".", "!", "?")) else t + ".")
        head = f"Сегодня: {treat.rstrip('.')}." if treat else ""
        return "\n".join(([head] if head else []) + [f"— {t}" for t in items[:8]] + [f"— {URGENT}"])
    if kind == "extract":
        parts = []
        for k, t in (("complaints", "Жалобы"), ("anamnesis", "Анамнез"), ("objective", "Объективно")):
            if str(d.get(k) or "").strip():
                parts.append(f"{t}: {str(d[k]).strip()}")
        if dg:
            parts.append("Диагноз: " + "; ".join(f"{x.get('code', '')} {x.get('title', '')}" + (f", зуб {x['tooth']}" if x.get("tooth") else "") for x in dg) + ".")
        for k, t in (("treatment", "Проведено лечение"), ("recommendations", "Рекомендации")):
            if str(d.get(k) or "").strip():
                parts.append(f"{t}: {str(d[k]).strip()}")
        return "\n".join(parts) or "В записи медкарты нет данных для выписки."
    if kind == "insurance":
        diag = "; ".join(f"{x.get('code', '')} {x.get('title', '')}" + (f" (зуб {x['tooth']})" if x.get("tooth") else "") for x in dg) or "—"
        out = [f"Застрахованному проведено обследование, установлен диагноз: {diag}."]
        if treat:
            out.append(f"Проведено лечение: {treat.rstrip('.')}.")
        if services:
            out.append("Оказаны услуги: " + "; ".join(services) + ".")
        if d.get("next_visit"):
            out.append(f"План: {str(d['next_visit']).rstrip('.')}.")
        out.append("Лечение проведено по медицинским показаниям. Просим согласовать оплату оказанных услуг по договору ДМС.")
        return "\n\n".join(out)
    raise ValueError("Неизвестный вид документа")


def write(kind: str, rec: dict, services=(), names=()) -> dict:
    """{'text', 'engine': 'ai' | 'rules', 'ai_error'} — a draft for the doctor to check."""
    if kind not in KINDS:
        raise ValueError("Неизвестный вид документа")
    base = _rules(kind, rec, services)
    out = {"text": base, "engine": "rules", "ai_error": None, "title": KINDS[kind]}
    if ai.enabled():
        src = record_text(rec, services)
        if kind in ("recommendations", "explain") and src.strip():  # the clinic's own advice: the model retells, not invents
            src += "\nСтандартные рекомендации клиники для этого лечения:\n" + "\n".join(
                x for x in base.split("\n") if x.startswith("— ") and URGENT not in x)
        if src.strip():
            try:
                text = ai.generate(TASKS[kind], src, names, max_chars=LIMITS[kind])
                d = (rec or {}).get("data") or rec or {}
                if kind == "extract" and not str(d.get("recommendations") or "").strip() and not d.get("rx"):
                    # the doctor wrote no recommendations: a small model's «наблюдение у врача» is not a fact of the record
                    text = re.sub(r"(?m)^\s*Рекомендац[^\n]*\n?", "", text).strip()
                if kind == "recommendations" and not re.search(r"звон|обратит|приходит|срочно", text.split("\n")[-1], re.I):
                    # the last point (when to call the clinic) must stay, even when the list was cut
                    keep = ai.fit(text, LIMITS[kind] - len(URGENT) - 3)
                    text = keep + "\n— " + URGENT
                out.update(text=text, engine="ai")
            except ValueError as e:
                out["ai_error"] = str(e)
    return out


def plan_variant(v: dict) -> dict:
    """A plan option → one or two short sentences for the patient (up to LIMITS["plan_variant"] letters)."""
    items = [it for it in v.get("items") or [] if str(it.get("title") or "").strip()]
    names = [str(it["title"]).strip() + (f" (зуб {it['tooth']})" if it.get("tooth") else "") for it in items]
    base = (f"Вариант «{v.get('name') or 'план'}»: " + ("; ".join(names[:6]) + ("…" if len(names) > 6 else "") if names else "услуги по плану") + "."
            + (f" Гарантия — {v['warranty']}." if v.get("warranty") else "") + (f" Срок лечения — {v['term']}." if v.get("term") else ""))
    out = {"text": ai.fit(base, 400), "engine": "rules", "ai_error": None}
    if ai.enabled() and names:
        src = "\n".join([f"Название варианта: {v.get('name') or ''}", "Услуги: " + "; ".join(names),
                         f"Гарантия: {v.get('warranty') or 'не указана'}", f"Срок лечения: {v.get('term') or 'не указан'}",
                         f"Заметка врача: {v.get('note') or ''}"])
        try:
            out.update(text=ai.generate(TASKS["plan_variant"], src, max_chars=LIMITS["plan_variant"]), engine="ai")
        except ValueError as e:
            out["ai_error"] = str(e)
    return out


def translate_task(lang: str) -> str:
    """Instructions for a translator model. English ones for English: a small model follows them better."""
    if lang == "en":
        return ("You are a medical translator of a dental clinic. Translate every numbered line from Russian into English. "
                "Use exact dental terms (пломба — filling, коронка — crown, удаление — extraction, зуб — tooth, пульпит — pulpitis). "
                "Keep numbers, dates, tooth numbers and sums. Keep the line numbers and the «|» sign, one line per number. "
                "The answer must be in English only, without comments.")
    return (f"Ты медицинский переводчик стоматологической клиники. Переведи каждую пронумерованную строку с русского на {LANGS[lang]} "
            f"язык. Термины переводи точно, числа, даты, номера зубов и суммы не меняй. Сохрани номера строк и знак «|», по одной "
            f"строке на номер. Ответ — только на {LANGS[lang]} языке, без пояснений.")


def translate(lines, lang: str, names=()) -> dict:
    """Lines of a document or a message → the same lines in `lang`. Needs the AI (rules cannot translate).
    Lines go in numbered packs; a line the model lost stays as it was."""
    if lang not in LANGS:
        raise ValueError("Неизвестный язык")
    if not ai.enabled():
        raise ValueError("Перевод делает ИИ — включите его: Настройки → «Голос и ИИ»")
    src = [str(x or "") for x in (lines if isinstance(lines, list) else str(lines or "").split("\n"))][:400]
    out = list(src)
    task = translate_task(lang)
    todo = [i for i, s in enumerate(src) if re.search(r"[A-Za-zА-Яа-яЁё]", s)]
    for k in range(0, len(todo), 25):
        pack = todo[k:k + 25]
        text = f"Переведи на {LANGS[lang]} язык:\n" + "\n".join(f"{n + 1}| {src[i]}" for n, i in enumerate(pack))
        reply = ai.generate(task, text, names, timeout=180, base=False)  # the common rules say «write in Russian»
        got = {}
        for m in re.finditer(r"(?m)^\s*(\d+)\s*[|)]\s?(.*)$", reply):
            got[int(m.group(1))] = m.group(2).strip()
        for n, i in enumerate(pack):
            if got.get(n + 1):
                out[i] = got[n + 1]
    return {"lines": out, "lang": lang, "title": LANG_TITLE[lang], "engine": "ai"}
