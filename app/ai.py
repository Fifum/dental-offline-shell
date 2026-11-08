"""Optional AI layer: a language model puts a dictated protocol into the record fields and words it
the way a medical record is written (form 043/у style, ICD-10, FDI tooth numbers).

Providers:
  yandex    — YandexGPT in Yandex AI Studio (OpenAI-compatible API, API key + folder id)
  gigachat  — GigaChat (Sber): OAuth by authorization key, then chat API
  local     — Ollama with Qwen or Gemma downloaded and run by the program itself (llm_local.py)
  openai    — any other OpenAI-compatible service or a local model server (e.g. Ollama)

Off by default. Before anything is sent, the patient's name and phone numbers are removed.
If the AI is off, offline or fails, the offline rules in dictation.py are used.
"""
from __future__ import annotations

import json
import re
import ssl
import time
import uuid

import config
import dictation
from catalog import MKB, TOOTH_STATUSES

PROVIDERS = {
    "yandex": {"title": "YandexGPT (Яндекс)", "base_url": "https://llm.api.cloud.yandex.net/v1",
               "models": {"yandexgpt-lite": "YandexGPT Lite — дешевле", "yandexgpt": "YandexGPT Pro — точнее"},
               "price": {"yandexgpt-lite": 0.2, "yandexgpt": 0.8}},
    "gigachat": {"title": "GigaChat (Сбер)", "base_url": "https://gigachat.devices.sberbank.ru/api/v1",
                 "oauth_url": "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
                 "models": {"GigaChat-2": "GigaChat Lite — дешевле", "GigaChat-2-Pro": "GigaChat Pro", "GigaChat-2-Max": "GigaChat Max — точнее"},
                 "price": {"GigaChat-2": 0.065, "GigaChat-2-Pro": 0.5, "GigaChat-2-Max": 0.65}},
    "local": {"title": "ИИ на этом компьютере (бесплатно)", "base_url": "", "models": {}, "price": {}},
    "openai": {"title": "Другой сервис или своя модель (OpenAI-совместимый API)", "base_url": "", "models": {}, "price": {}},
}
TOKENS_PER_DICTATION = 3000  # instructions + ICD-10 list + dictation + answer, measured roughly

DEFAULTS = {"enabled": False, "provider": "yandex", "base_url": "", "model": "yandexgpt-lite", "key_enc": "", "folder": "",
            "scope": "GIGACHAT_API_CORP", "oauth_url": "", "style": True, "auto_insert": False, "timeout": 30}

SYSTEM = (
    "Ты медицинский регистратор стоматологической клиники. Тебе дают продиктованный врачом протокол приёма "
    "(распознанная речь, возможны ошибки распознавания). Разложи его по разделам медицинской карты и верни ТОЛЬКО JSON без пояснений:\n"
    '{"complaints": "", "anamnesis": "", "objective": "", "treatment": "", "recommendations": "", "next_visit": "", '
    '"diagnoses": [{"code": "", "tooth": ""}], "teeth": {"36": "Пломба"}}\n'
    "Разделы: complaints — жалобы; anamnesis — анамнез заболевания и жизни; objective — объективно: внешний осмотр, "
    "осмотр полости рта, локальный статус (Status localis), данные зондирования, перкуссии, ЭОД, рентгенографии; "
    "treatment — проведённое лечение по этапам с названиями препаратов и материалов; recommendations — рекомендации пациенту; "
    "next_visit — дата или срок следующего визита и план.\n"
    "{style}"
    "Нельзя: добавлять факты, которых нет в диктовке; ставить диагнозы, которые врач не называл; придумывать препараты, "
    "дозировки и зубы. Если раздела нет в диктовке — пустая строка. Исправляй очевидные ошибки распознавания медицинских терминов. "
    "Номера зубов — по системе FDI (ВОЗ): 11–48, молочные 51–85. Коды МКБ-10 бери только из списка: {mkb}. "
    "Состояния зубов для формулы — только из списка: {statuses}; ставь состояние после лечения (вылеченный кариес — «Пломба»)."
)
STYLE = (
    "Стиль записи — как в медицинской карте стоматологического больного (форма 043/у): официально-деловой медицинский язык, "
    "безличные и страдательные конструкции («Жалобы на…», «Проведено…», «Рекомендовано…»), полные медицинские термины "
    "без разговорных слов и без сокращений, кроме общепринятых (МКБ-10, ЭОД, ЭДТА, мм, мл, мг); каждый раздел — законченные "
    "предложения с заглавной буквы и точкой в конце; единицы измерения — по ГОСТ 8.417 (мм, мл, мг, мин); даты — ДД.ММ.ГГГГ; "
    "номер зуба пиши в тексте как «зуб 3.6» или «36» — так, как продиктовал врач.\n"
)

_token = {"value": "", "until": 0}


def settings() -> dict:
    return {**DEFAULTS, **(config.load_settings().get("ai") or {})}


def public_settings() -> dict:
    s = settings()
    return {k: s[k] for k in ("enabled", "provider", "base_url", "model", "folder", "scope", "style", "auto_insert")} | {
        "has_key": bool(s["key_enc"]), "providers": {k: {"title": v["title"], "models": v["models"]} for k, v in PROVIDERS.items()},
        "cost": cost_estimate(s)}


def cost_estimate(s=None) -> dict:
    """Roughly how much one dictation and a month of dictations cost with the chosen model."""
    s = s or settings()
    price = PROVIDERS.get(s["provider"], {}).get("price", {}).get(s["model"])
    if price is None:
        return {}
    one = price * TOKENS_PER_DICTATION / 1000
    return {"per_1000_tokens": price, "per_dictation": round(one, 2), "per_month_10_doctors": round(one * 10 * 15 * 22)}


def save(f: dict) -> dict:
    cur = settings()
    new = {k: f[k] for k in ("provider", "base_url", "model", "folder", "scope") if k in f}
    new = {k: str(v or "").strip() for k, v in new.items()}
    for k in ("enabled", "style", "auto_insert"):
        if k in f:
            new[k] = bool(f[k])
    if f.get("key"):
        new["key_enc"] = config.protect(str(f["key"]).strip())
    merged = {**cur, **new}
    if merged["provider"] not in PROVIDERS:
        raise ValueError("Неизвестный сервис ИИ")
    if merged["enabled"]:
        if not merged["model"]:
            raise ValueError("Скачайте модель ниже — после скачивания она включится сама" if merged["provider"] == "local"
                             else "Выберите модель")
        if merged["provider"] == "yandex" and not merged["folder"]:
            raise ValueError("Укажите идентификатор каталога Yandex Cloud (folder id)")
        if merged["provider"] == "openai" and not merged["base_url"]:
            raise ValueError("Укажите адрес сервиса")
        if merged["provider"] in ("yandex", "gigachat") and not merged["key_enc"]:
            raise ValueError("Укажите ключ")
    merged["base_url"] = merged["base_url"].rstrip("/")
    config.save_settings({"ai": merged})
    _token.update(value="", until=0)
    return public_settings()


def _anonymize(text: str, names=()) -> str:
    for n in names:
        for part in str(n or "").split():
            if len(part) >= 3:
                text = re.sub(re.escape(part), "Пациент", text, flags=re.I)
    return re.sub(r"\+?\d[\d\s()-]{8,}\d", "[телефон]", text)


def _session():
    """requests session that trusts the Windows certificate store too: GigaChat uses the Russian
    national root certificate (НУЦ Минцифры), which is installed into Windows, not into Python."""
    import requests  # noqa: PLC0415
    from requests.adapters import HTTPAdapter  # noqa: PLC0415

    class WinStore(HTTPAdapter):
        def init_poolmanager(self, *a, **kw):
            ctx = ssl.create_default_context()
            try:
                import certifi  # noqa: PLC0415
                ctx.load_verify_locations(certifi.where())
            except Exception:  # noqa: BLE001
                pass
            kw["ssl_context"] = ctx
            return super().init_poolmanager(*a, **kw)
    s = requests.Session()
    s.mount("https://", WinStore())
    return s


def _gigachat_token(s, http) -> str:
    import requests  # noqa: PLC0415
    if _token["value"] and time.time() < _token["until"] - 60:
        return _token["value"]
    url = s.get("oauth_url") or PROVIDERS["gigachat"]["oauth_url"]
    try:
        r = http.post(url, timeout=15, data={"scope": s.get("scope") or "GIGACHAT_API_CORP"},
                      headers={"Authorization": f"Basic {config.unprotect(s['key_enc'])}", "RqUID": str(uuid.uuid4()),
                               "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    except requests.exceptions.SSLError as e:
        raise ValueError("Не удалось проверить сертификат GigaChat. Установите в Windows корневой сертификат "
                         "«Russian Trusted Root CA» (Минцифры) с сайта Госуслуг и повторите.") from e
    except requests.RequestException as e:
        raise ValueError(f"GigaChat недоступен: {e.__class__.__name__}") from e
    if r.status_code != 200:
        raise ValueError(f"GigaChat не принял ключ (HTTP {r.status_code}). Проверьте ключ авторизации и тип доступа.")
    j = r.json()
    _token["value"] = j.get("access_token", "")
    exp = j.get("expires_at") or 0
    _token["until"] = exp / 1000 if exp > 1e11 else (exp or time.time() + 1500)
    return _token["value"]


def _chat(messages, s=None) -> str:
    import requests  # noqa: PLC0415
    s = s or settings()
    prov = s["provider"]
    if prov == "local":  # Ollama started by the program itself: nothing leaves the computer
        import llm_local  # noqa: PLC0415
        return llm_local.chat(messages, s["model"], s.get("timeout", 30))
    http = _session()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    base = (s.get("base_url") or PROVIDERS[prov]["base_url"]).rstrip("/")
    model = s["model"]
    if prov == "yandex":
        headers["Authorization"] = f"Bearer {config.unprotect(s['key_enc'])}"  # API key of a service account
        headers["OpenAI-Project"] = s["folder"]
        if not model.startswith("gpt://"):
            model = f"gpt://{s['folder']}/{model}/latest"
    elif prov == "gigachat":
        headers["Authorization"] = f"Bearer {_gigachat_token(s, http)}"
    elif s["key_enc"]:
        headers["Authorization"] = f"Bearer {config.unprotect(s['key_enc'])}"
    key = (prov, base, model)
    params = dict(_params.get(key) or {"temperature": 0.1, "max_tokens": 2000})
    for _ in range(4):
        reasoning = "max_completion_tokens" in params
        timeout = max(s.get("timeout", 30), 90) if reasoning else s.get("timeout", 30)
        try:
            r = http.post(f"{base}/chat/completions", headers=headers, timeout=timeout,
                          json={"model": model, "messages": messages, **params})
        except requests.exceptions.SSLError as e:
            raise ValueError("Ошибка сертификата при подключении к ИИ-сервису") from e
        except requests.RequestException as e:
            raise ValueError(f"ИИ-сервис недоступен: {e.__class__.__name__}") from e
        fixed = _adapt(params, r) if r.status_code == 400 else None
        if fixed is None:
            break
        params = fixed
    if r.status_code == 401 and prov == "gigachat":
        _token.update(value="", until=0)
    if r.status_code != 200:
        raise ValueError(f"ИИ-сервис ответил ошибкой HTTP {r.status_code}: {r.text[:200]}")
    _params[key] = params
    try:
        choice = r.json()["choices"][0]
        content = choice["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        raise ValueError("ИИ-сервис вернул непонятный ответ") from e
    if not content.strip() and choice.get("finish_reason") == "length":
        raise ValueError("Модель потратила весь лимит на размышления и не дала ответ. Выберите модель попроще (например, mini).")
    return content


_params: dict = {}  # request parameters that worked for (provider, address, model)


def _adapt(params: dict, r) -> dict | None:
    """Newer OpenAI models (gpt-5, o-series) reject max_tokens and a custom temperature. Read which
    parameter the service complained about and return corrected parameters, or None if nothing to fix."""
    try:
        err = r.json().get("error") or {}
        msg, param = str(err.get("message") or ""), str(err.get("param") or "")
    except (ValueError, AttributeError):
        msg, param = r.text or "", ""
    p = dict(params)
    if "max_completion_tokens" in msg and "max_tokens" in p:
        # reasoning models count their hidden reasoning against this limit, so give more room
        del p["max_tokens"]
        p["max_completion_tokens"] = 8000
        p.setdefault("reasoning_effort", "low")
        return p
    for name in ("temperature", "reasoning_effort", "max_completion_tokens", "max_tokens"):
        if name in p and (param == name or re.search(rf"\b{name}\b", msg)):
            del p[name]
            return p
    return None


def _validate(obj: dict) -> dict:
    codes = dict(MKB)
    fields = {k: str(obj.get(k) or "").strip() for k in ("complaints", "anamnesis", "objective", "treatment", "recommendations", "next_visit")}
    diagnoses = []
    for d in obj.get("diagnoses") or []:
        if not isinstance(d, dict):
            continue
        code = str(d.get("code") or "").upper().replace("К", "K").strip()
        tooth = str(d.get("tooth") or "").replace(".", "").strip()
        if code in codes and (not tooth or tooth in dictation.VALID):
            diagnoses.append({"code": code, "title": codes[code], "tooth": tooth})
    teeth = {}
    for k, v in (obj.get("teeth") or {}).items():
        k = str(k).replace(".", "")
        if k in dictation.VALID and v in TOOTH_STATUSES:
            teeth[k] = v
    return {"fields": {k: v for k, v in fields.items() if v}, "diagnoses": diagnoses, "teeth": teeth}


def prompt(s=None) -> str:
    s = s or settings()
    return (SYSTEM.replace("{style}", STYLE if s.get("style", True) else "Пиши грамотным медицинским языком.\n")
            .replace("{mkb}", "; ".join(f"{c} {t}" for c, t in MKB)).replace("{statuses}", ", ".join(TOOTH_STATUSES)))


CONVERSATION = (
    "Сейчас тебе дают не диктовку, а расшифровку разговора на приёме. Реплики подписаны программой по голосу: "
    "«Врач:», «Ассистент:», «Пациент:» (у коротких реплик подпись может быть ошибочной — проверяй по смыслу). "
    "Жалобы и анамнез бери из слов пациента и из вопросов врача, на которые пациент ответил; объективно, диагноз, "
    "лечение, рекомендации и следующий визит — из слов врача (и ассистента, если он называет материалы и препараты). "
    "Приветствия, бытовые разговоры, команды вроде «откройте рот», «сплюньте» в медкарту не переносить. "
    "Пиши разделы своими словами в стиле медкарты, а не репликами.\n"
)


def structure(text: str, names=(), conversation=False) -> dict:
    """Dictation (or a signed visit conversation) → record fields via the model.
    Raises ValueError if the AI is off or fails."""
    s = settings()
    if not s["enabled"]:
        raise ValueError("ИИ выключен")
    system = prompt(s) + ("\n" + CONVERSATION if conversation else "")
    content = _chat([{"role": "system", "content": system}, {"role": "user", "content": _anonymize(text, names)}], s)
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise ValueError("ИИ не вернул данные в нужном виде")
    try:
        return _validate(json.loads(m.group(0)))
    except ValueError as e:
        raise ValueError("ИИ вернул данные с ошибкой") from e


def test() -> str:
    s = settings()
    reply = _chat([{"role": "user", "content": "Ответь одним словом: работает"}], {**s, "timeout": 20})
    return f"ИИ отвечает: «{reply.strip()[:60]}»"
