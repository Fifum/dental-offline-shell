"""Turn a dictated visit protocol into medical-record fields — offline, with plain rules.

«Жалобы на боль от холодного в 36. Объективно: глубокая полость… Диагноз: кариес дентина 36.
Лечение: анестезия, пломба. Зуб 47 отсутствует. Рекомендации: не есть 2 часа.»
→ complaints / anamnesis / objective / treatment / recommendations / next_visit,
  diagnoses [{code, title, tooth}], teeth {"36": "Пломба", "47": "Отсутствует"}.

The doctor always sees the result before saving.
"""
from __future__ import annotations

import re

from catalog import MKB

# --- what speech recognition usually gets wrong in dental Russian
FIXES = [
    (r"\bанамниз", "анамнез"), (r"\bнаживательн", "на жевательн"), (r"\bсвета\s+отверждаем", "светоотверждаем"),
    (r"\bзондирование\s+и\s+болезненно", "зондирование болезненно"), (r"\bпер[еи]куссия", "перкуссия"),
    (r"\bпульпид", "пульпит"), (r"\bпериодантит", "периодонтит"), (r"\bпародантит", "пародонтит"),
    (r"\bгингевит", "гингивит"), (r"\bкариез", "кариес"), (r"\bинфильтрацыон", "инфильтрацион"),
    (r"\bультра\s*каин", "ультракаин"), (r"\bанастези", "анестези"), (r"\bкомпози\b", "композита"), (r"\bсепта\s*нест", "септанест"), (r"\bэйр\s*флоу", "Air Flow"),
]

SECTIONS = [
    ("complaints", r"жалоб\w*|жалуется"),
    ("anamnesis", r"анамнез\w*|из\s+анамнеза"),
    ("objective", r"объективн\w*|осмотр\w*|при\s+осмотре|локальн\w*\s+статус"),
    ("diagnosis", r"диагноз\w*"),
    ("treatment", r"лечени\w*|проведено|проведен\w*\s+лечени\w*|выполнено|сделано"),
    ("recommendations", r"рекомендац\w*|рекомендовано|назначено|назначения"),
    ("next_visit", r"следующ\w+\s+визит\w*|повторн\w+\s+(?:визит|приём|прием)\w*|явка|контроль\s+через"),
]
_SEC_RE = re.compile(r"(?:(?<=^)|(?<=[.!?;\n]))\s*(" + "|".join(f"(?P<{k}>{p})" for k, p in SECTIONS) + r")\s*[:,—–-]?\s*",
                     re.I)

# --- teeth: «36», «зуб 36», «тридцать шестой», «тридцать шесть»
_UNITS = {"один": 1, "первый": 1, "первого": 1, "первом": 1, "два": 2, "второй": 2, "второго": 2, "втором": 2,
          "три": 3, "третий": 3, "третьего": 3, "третьем": 3, "четыре": 4, "четвёртый": 4, "четвертый": 4,
          "четвёртого": 4, "четвертого": 4, "четвёртом": 4, "четвертом": 4, "пять": 5, "пятый": 5, "пятого": 5,
          "пятом": 5, "шесть": 6, "шестой": 6, "шестого": 6, "шестом": 6, "семь": 7, "седьмой": 7, "седьмого": 7,
          "седьмом": 7, "восемь": 8, "восьмой": 8, "восьмого": 8, "восьмом": 8}
_TENS = {"двадцать": 2, "тридцать": 3, "сорок": 4, "пятьдесят": 5, "шестьдесят": 6, "семьдесят": 7, "восемьдесят": 8}
_TEENS = {"одиннадцать": 11, "одиннадцатый": 11, "одиннадцатого": 11, "двенадцать": 12, "двенадцатый": 12, "двенадцатого": 12,
          "тринадцать": 13, "тринадцатый": 13, "тринадцатого": 13, "четырнадцать": 14, "четырнадцатый": 14, "четырнадцатого": 14,
          "пятнадцать": 15, "пятнадцатый": 15, "пятнадцатого": 15, "шестнадцать": 16, "шестнадцатый": 16, "шестнадцатого": 16,
          "семнадцать": 17, "семнадцатый": 17, "семнадцатого": 17, "восемнадцать": 18, "восемнадцатый": 18, "восемнадцатого": 18}
VALID = {f"{q}{n}" for q in "1234" for n in "12345678"} | {f"{q}{n}" for q in "5678" for n in "12345"}

STATUS_WORDS = [  # order matters: the first match in a sentence wins for that tooth
    ("Отсутствует", r"отсутству\w*|нет\s+зуба|удал[её]н\b"),
    ("Удалить", r"удалить|под\s+удаление|показан\w*\s+к\s+удалению"),
    ("Имплант", r"имплант\w*"), ("Коронка", r"коронк\w*"), ("Мост", r"мост\w*"), ("Винир", r"винир\w*"),
    ("Вкладка", r"вкладк\w*"), ("Эндо-лечение", r"канал\w*|эндодонт\w*|пломбирование\s+каналов"),
    ("Периодонтит", r"периодонтит\w*"), ("Пульпит", r"пульпит\w*"), ("Корень", r"корен\w*|корня"),
    ("Подвижность", r"подвижност\w*"), ("Пломба", r"пломб\w*|реставрац\w*"), ("Кариес", r"кариес\w*|кариозн\w*"),
    ("Здоров", r"интактн\w*|здоров\w*"),
]

DIAG_SYNONYMS = [  # spoken phrase -> ICD-10 code (checked before plain title matching)
    (r"кариес\w*\s+эмал\w*|начальн\w+\s+кариес", "K02.0"), (r"кариес\w*\s+дентин\w*|средн\w+\s+кариес|глубок\w+\s+кариес", "K02.1"),
    (r"кариес\w*\s+цемент\w*", "K02.2"), (r"некроз\w*\s+пульп\w*|гангрен\w*\s+пульп\w*", "K04.1"),
    (r"остр\w+\s+(?:апикальн\w+\s+)?периодонтит\w*", "K04.4"), (r"периодонтит\w*", "K04.5"), (r"пульпит\w*", "K04.0"),
    (r"остр\w+\s+гингивит\w*", "K05.0"), (r"гингивит\w*", "K05.1"), (r"остр\w+\s+пародонтит\w*", "K05.2"),
    (r"пародонтит\w*", "K05.3"), (r"пародонтоз\w*", "K05.4"), (r"рецесси\w*", "K06.0"),
    (r"отложени\w*|зубн\w+\s+камн\w*|налёт|налет", "K03.6"), (r"стирани\w*", "K03.0"), (r"эрози\w*", "K03.2"),
    (r"альвеолит\w*", "K10.3"), (r"стоматит\w*", "K12.1"), (r"перелом\w*\s+зуба|скол\w*", "S02.5"),
    (r"ретенци\w*|ретинирован\w*", "K01.1"), (r"киста\w*", "K04.8"), (r"потер\w+\s+зуб\w*|отсутстви\w+\s+зуб\w*", "K08.1"),
    (r"кариес\w*", "K02.1"),
]
MKB_TITLE = dict(MKB)


def clean(text: str) -> str:
    t = " ".join(str(text or "").split())
    for pat, rep in FIXES:
        t = re.sub(pat, rep, t, flags=re.I)
    return t


def _words_to_teeth(text: str) -> str:
    """«тридцать шестой» → «36», «восемнадцатый» → «18» (only valid tooth numbers)."""
    def tens(m):
        t, u = _TENS[m.group(1).lower()], _UNITS[m.group(2).lower()]
        n = f"{t}{u}"
        return n if n in VALID else m.group(0)
    text = re.sub(r"\b(" + "|".join(_TENS) + r")\s+(" + "|".join(_UNITS) + r")\b", tens, text, flags=re.I)
    return re.sub(r"\b(" + "|".join(_TEENS) + r")\b", lambda m: str(_TEENS[m.group(1).lower()]), text, flags=re.I)


def teeth_in(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"(?<![\d.,])([1-8][1-8])(?![\d.,]|\s*(?:мин|час|дн|мм|мл|%|лет|год))", text):
        if m.group(1) in VALID and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+", text) if s.strip()]


def split_sections(text: str) -> dict:
    """{'complaints': '…', 'objective': '…', …}; text before the first heading goes to «objective»."""
    out, pos, current = {}, 0, None
    for m in _SEC_RE.finditer(text):
        chunk = text[pos:m.start()].strip(" .,;:")
        if chunk:
            out.setdefault(current or "objective", []).append(chunk)
        current = next(k for k, _ in SECTIONS if m.group(k))
        pos = m.end()
    tail = text[pos:].strip(" .,;:")
    if tail:
        out.setdefault(current or "objective", []).append(tail)
    return {k: ". ".join(v).strip() for k, v in out.items()}


def _units(text: str):
    """Pieces of text that each talk about their own teeth. A sentence with one tooth is one piece;
    «36 кариес, 46 пульпит, удалить 18» becomes three pieces, each with its tooth."""
    out = []
    for sent in _sentences(text) or [text]:
        teeth = teeth_in(sent)
        if len(teeth) <= 1:
            out.append((sent, teeth))
            continue
        clauses = [c for c in re.split(r",|;|\s+и\s+", sent) if c.strip()]
        pending, last = [], []
        for c in clauses:
            ct = teeth_in(c)
            if ct:
                for p in pending:  # leading clauses without a tooth belong to the first tooth named
                    out.append((p, ct))
                pending = []
                out.append((c, ct))
                last = ct
            elif last:
                out.append((c, last))
            else:
                pending.append(c)
        out.extend((p, []) for p in pending)
    return out


def find_diagnoses(text: str) -> list[dict]:
    """Diagnoses with the tooth mentioned next to them."""
    found = []
    for sent, sent_teeth in _units(text):
        teeth = sent_teeth or [""]
        low = sent.lower()
        codes = []
        rest = low
        for pat, code in DIAG_SYNONYMS:
            if re.search(pat, rest):
                codes.append(code)
                rest = re.sub(pat, " ", rest)  # «кариес дентина» must not also match plain «кариес»
        for code in dict.fromkeys(codes):
            for tooth in teeth:
                item = {"code": code, "title": MKB_TITLE.get(code, ""), "tooth": tooth}
                if item not in found:
                    found.append(item)
    return found


def tooth_statuses(text: str) -> dict:
    """{'36': 'Пломба', '47': 'Отсутствует'} from sentences that name a tooth and a state."""
    out = {}
    for sent, teeth in _units(text):
        if not teeth:
            continue
        low = sent.lower()
        for status, pat in STATUS_WORDS:
            if re.search(pat, low):
                for t in teeth:
                    out.setdefault(t, status)
                break
    return out


def parse(text: str) -> dict:
    """Full result for the medical-record form. Treatment overrides diagnosis for the tooth state
    (a cavity that was filled is shown as «Пломба»)."""
    t = _words_to_teeth(clean(text))
    sec = split_sections(t)
    # «Зуб 47 отсутствует» said after «Лечение» is an examination finding, not treatment
    if sec.get("treatment"):
        finding = re.compile(r"\bзуб\w*\s+\d\d\s+(?:отсутству\w*|удал[её]н\w*)[^.!?]*[.!?]?", re.I)
        moved = [m.group(0).strip(" .") for m in finding.finditer(sec["treatment"])]
        if moved:
            sec["treatment"] = finding.sub(" ", sec["treatment"]).strip(" ,;")
            sec["treatment"] = re.sub(r"\s{2,}", " ", sec["treatment"]).strip()
            sec["objective"] = ". ".join(x.strip().rstrip(".") for x in [sec.get("objective", ""), *moved] if x.strip())
    diag_text = sec.pop("diagnosis", "")
    diagnoses = find_diagnoses(diag_text) if diag_text else []
    if not diagnoses:  # no «Диагноз:» heading — look through the whole text
        diagnoses = find_diagnoses(t)
    teeth = {}
    for part in ("objective", "complaints"):
        teeth.update({k: v for k, v in tooth_statuses(sec.get(part, "")).items() if k not in teeth})
    for k, v in tooth_statuses(diag_text).items():
        teeth[k] = v
    treated = [d["tooth"] for d in diagnoses if d.get("tooth")]
    for sent, sent_teeth in _units(sec.get("treatment", "")):
        low = sent.lower()
        for status, pat in STATUS_WORDS:
            if status in ("Отсутствует", "Здоров"):
                continue
            if re.search(pat, low):
                for k in (sent_teeth or treated):  # «пломба из композита» without a number = the tooth being treated
                    teeth[k] = status
                break
    for sentence in _sentences(t):  # «Зуб 47 отсутствует» anywhere
        if re.search(r"отсутству|удал[её]н\b", sentence.lower()):
            for tooth in teeth_in(sentence):
                teeth[tooth] = "Отсутствует"

    if sec.get("complaints"):
        sec["complaints"] = re.sub(r"^(?:на|что)\s+", "", sec["complaints"], flags=re.I)
    fields = {k: (v[0].upper() + v[1:] + ("" if v.endswith((".", "!", "?")) else ".")) for k, v in sec.items() if v}
    if diag_text:
        fields["diagnosis_text"] = diag_text
    return {"text": t, "fields": fields, "diagnoses": diagnoses, "teeth": teeth}


# --- 2.13 (13.2): the tooth chart by voice — «восемнадцать отсутствует, семнадцать коронка, шестнадцать кариес»
FORMULA_WORDS = [("Каналы запломбированы", r"каналы\s+запломбирован\w*|запломбирован\w*\s+канал\w*"), ("Штифт", r"штифт\w*"),
                 ("Промежуточная часть моста", r"промежуточн\w*\s+част\w*")] + STATUS_WORDS
FORMULA_PROMPT = ("Зубная формула. Восемнадцать отсутствует, семнадцать коронка, шестнадцать кариес, тридцать шесть пломба, "
                  "сорок семь имплант, с двадцать шестого по двадцать восьмой отсутствуют.")


def _range(a: str, b: str) -> list[str]:
    """«с 26 по 28» → 26, 27, 28 (inside one quadrant)."""
    if a[0] != b[0]:
        return [a, b]
    lo, hi = sorted((int(a[1]), int(b[1])))
    return [f"{a[0]}{n}" for n in range(lo, hi + 1) if f"{a[0]}{n}" in VALID]


def formula(text: str) -> dict:
    """Spoken tooth chart → {'text', 'teeth': {'18': 'Отсутствует', ...}, 'unknown': [...]}: every state goes to the
    teeth named before it («восемнадцать, семнадцать отсутствуют»), or after it when it comes first («коронка на 17»)."""
    t = _words_to_teeth(clean(text))
    t = re.sub(r"\bс\s+(\d\d)\s*(?:-?го|-?й)?\s+по\s+(\d\d)\s*(?:-?й|-?го)?\s*",
               lambda m: " ".join(_range(m.group(1), m.group(2))) + " ", t, flags=re.I)
    pat = re.compile(r"(?P<tooth>(?<![\d.,])[1-8][1-8](?![\d.,]))|" + "|".join(f"(?P<s{i}>{p})" for i, (_, p) in enumerate(FORMULA_WORDS)) +
                     r"|(?P<sep>[.;!?]|\bдалее\b|\bпотом\b)|(?P<comma>,)", re.I)
    teeth, pending, lead, last, unknown = {}, [], None, [], []

    def put(n, status):
        have = [x for x in str(teeth.get(n) or "").split(", ") if x]
        if status not in have:
            have.append(status)
        teeth[n] = ", ".join(have)
    for m in pat.finditer(t):
        if m.group("tooth"):
            n = m.group("tooth")
            if n not in VALID:
                unknown.append(n)
            elif lead:
                put(n, lead)
            else:
                pending.append(n)
                last = []
        elif m.group("sep"):
            pending, lead, last = [], None, []
        elif m.group("comma"):
            last, lead = [], None
        else:
            status = next(FORMULA_WORDS[i][0] for i in range(len(FORMULA_WORDS)) if m.group(f"s{i}"))
            if pending:
                for n in pending:
                    put(n, status)
                last, pending, lead = pending, [], None
            elif last:  # «47 имплант коронка»: both states for the same tooth
                for n in last:
                    put(n, status)
            else:
                lead = status
    return {"text": t, "teeth": teeth, "unknown": unknown}
