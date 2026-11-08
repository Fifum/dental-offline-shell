"""Allergy check: a patient's allergies against what is about to be given (anaesthetic, antibiotic, material).

Simple word rules, no AI: the same substance is a stop («аллергия на лидокаин» + «лидокаин» in the treatment),
a substance of the same group is a warning (lidocaine allergy + articaine — both amide anaesthetics).
The doctor decides; the program only makes sure the allergy is not missed.
"""
from __future__ import annotations

import re

# group: (title, [stems of substances and trade names])
GROUPS = {
    "amide": ("амидные анестетики", ["лидокаин", "ксилокаин", "артикаин", "ультракаин", "убистезин", "септанест", "артифрин",
                                     "альфакаин", "мепивакаин", "скандонест", "мепивастезин", "прилокаин", "бупивакаин", "ропивакаин",
                                     "lidocain", "articain", "ultracain", "septanest", "mepivacain", "scandonest"]),
    "ester": ("эфирные анестетики", ["новокаин", "прокаин", "анестезин", "бензокаин", "тетракаин", "дикаин", "novocain", "procain", "benzocain"]),
    "penicillin": ("пенициллины", ["пенициллин", "амоксициллин", "амоксиклав", "аугментин", "флемоксин", "ампициллин", "оксациллин"]),
    "cephalosporin": ("цефалоспорины", ["цефазолин", "цефтриаксон", "цефуроксим", "цефалексин", "цефиксим"]),
    "lincosamide": ("линкозамиды", ["линкомицин", "клиндамицин", "далацин"]),
    "macrolide": ("макролиды", ["азитромицин", "сумамед", "кларитромицин", "эритромицин"]),
    "nsaid": ("нестероидные противовоспалительные", ["аспирин", "ацетилсалицил", "ибупрофен", "нурофен", "кеторолак", "кетанов",
                                                    "кеторол", "диклофенак", "нимесулид", "найз", "нимесил", "метамизол", "анальгин"]),
    "latex": ("латекс", ["латекс"]),
    "chlorhexidine": ("хлоргексидин", ["хлоргексидин", "корсодил"]),
    "iodine": ("йод", ["йод", "повидон", "бетадин"]),
    "metronidazole": ("метронидазол", ["метронидазол", "трихопол", "метрогил"]),
    "eugenol": ("эвгенол", ["эвгенол", "эвгенат"]),
}
NO_ALLERGY = re.compile(r"^(нет|не выявлен\w*|отрицает|не отягощ\w*|без особенностей|-|—|0|no|none)\.?$", re.I)
ANAMNESIS = re.compile(r"аллерг\w*(?:\s+реакц\w*)?\s*(?:на|к)?\s*:?\s*([^.;\n]+)", re.I)
NEGATED = re.compile(r"не отягощ|отрицает|не выявлен|^\s*нет\b|не было", re.I)


def _norm(s: str) -> str:
    return str(s or "").lower().replace("ё", "е")


LATIN = {"lidocain": "лидокаин", "articain": "артикаин", "ultracain": "ультракаин", "septanest": "септанест",
         "mepivacain": "мепивакаин", "scandonest": "скандонест", "novocain": "новокаин", "procain": "прокаин",
         "benzocain": "бензокаин"}


def _stems(text: str) -> set[str]:
    """Known substance stems that occur in a text (Latin names counted as the Russian ones)."""
    t = _norm(text)
    return {LATIN.get(st, st) for _g, (_t, stems) in GROUPS.items() for st in stems if st in t}


def _group(stem: str) -> str | None:
    return next((g for g, (_t, stems) in GROUPS.items() if stem in stems), None)


def patient_allergies(data: dict | None, anamnesis: str = "") -> list[str]:
    """Allergy texts from the patient's card (any field named like «allerg») and «аллергия на …» in the anamnesis."""
    out = []
    for k, v in (data or {}).items():
        if isinstance(v, (str, int, float)) and re.search(r"allerg|аллерг", str(k), re.I):
            s = str(v).strip()
            if s and not NO_ALLERGY.match(s):
                out.append(s)
    for m in ANAMNESIS.finditer(anamnesis or ""):
        s = m.group(1).strip()
        if s and not NEGATED.search(m.group(0)) and not NO_ALLERGY.match(s):
            out.append(s)
    return list(dict.fromkeys(out))


def check(allergies: list[str], text: str) -> list[dict]:
    """Warnings for `text` (treatment, prescription, service names) against the allergy list.
    level 'stop' — the same substance, 'warn' — the same group."""
    if not allergies or not str(text or "").strip():
        return []
    used = _stems(text)
    out, seen = [], set()
    for a in allergies:
        a_stems = _stems(a)
        # an allergy written in free words: any long word of it present in the text counts as the same substance
        free = [w for w in re.findall(r"[а-яa-z]{5,}", _norm(a)) if w not in {"аллергия", "реакция", "непереносимость"}]
        for st in sorted(used):
            g = _group(st)
            if st in a_stems or any(w[:6] in st or st[:6] in w for w in free):
                key = ("stop", st)
                if key not in seen:
                    seen.add(key)
                    out.append({"level": "stop", "substance": st, "allergy": a,
                                "text": f"Аллергия «{a}», а в назначении — {st}."})
            elif g and any(_group(x) == g for x in a_stems):
                key = ("warn", st)
                if key not in seen:
                    seen.add(key)
                    out.append({"level": "warn", "substance": st, "allergy": a,
                                "text": f"Аллергия «{a}»; {st} из той же группы ({GROUPS[g][0]}) — возможна перекрёстная реакция."})
        if any(w.startswith("латекс") for w in free) and re.search(r"латекс|перчат|коффердам|раббердам", _norm(text)):
            key = ("warn", "латекс")
            if key not in seen and ("stop", "латекс") not in seen:
                seen.add(key)
                out.append({"level": "warn", "substance": "латекс", "allergy": a,
                            "text": f"Аллергия «{a}»: используйте безлатексные перчатки и коффердам."})
    return sorted(out, key=lambda x: x["level"] != "stop")
