"""AI (2.13.0): the assistant with the employee's rights (dates, names in any case, answers, proposed changes),
drafts of documents and translation (rules without the AI, the model with anonymous data), the record check,
the director's weekly summary, the tooth chart and notes by voice, the consent to record a visit, the clinic's
own local model and the quality check."""
import json
import os
import socket
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import ai  # noqa: E402
import ai_docs  # noqa: E402
import ai_eval  # noqa: E402
import assistant as A  # noqa: E402
import auth  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import dictation  # noqa: E402
import llm_local  # noqa: E402
import medcheck  # noqa: E402
import replica  # noqa: E402
from main import Api  # noqa: E402
from server import ClinicServer  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def refuses(name, fn, text=""):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except ValueError as e:
        check(name, not text or text in str(e), e)


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
T = date.today()
DOCS = {x["name"].split()[0]: x for x in d.doctors()}
GUS = DOCS["Гусева"]


def day(n):
    return (T + timedelta(days=n)).isoformat()


def patient(last, first="Тест", phone=""):
    return a.create_patient({"lname": last, "fname": first, "phone": phone})["id"]


def ask(q, ctx=None):
    return a.assistant_ask(q, ctx or {})


# ------------------------------------------------------------------ dates, times, names
mon = date(2026, 11, 9)  # a Monday
check("завтра", A.parse_day("кто у меня завтра", mon) == date(2026, 11, 10))
check("послезавтра", A.parse_day("послезавтра", mon) == date(2026, 11, 11))
check("в четверг", A.parse_day("запиши на четверг", mon) == date(2026, 11, 12))
check("в понедельник = сегодня", A.parse_day("в понедельник", mon) == mon)
check("в следующую среду", A.parse_day("в следующую среду", mon) == date(2026, 11, 18))
check("15 ноября", A.parse_day("на 15 ноября", mon) == date(2026, 11, 15))
check("15.12", A.parse_day("на 15.12", mon) == date(2026, 12, 15))
check("Субботина is not a Saturday", A.parse_day("найди Субботину", mon) is None)
check("за октябрь", A.parse_period("выручка за октябрь", mon) == (date(2026, 10, 1), date(2026, 10, 31)))
check("в марте = this year", A.parse_period("в марте", mon) == (date(2026, 3, 1), date(2026, 3, 31)))
check("Мартынова is not March", A.parse_period("сколько заплатила Мартынова", mon) is None)
check("в декабре = last year", A.parse_period("выручка в декабре", mon) == (date(2025, 12, 1), date(2025, 12, 31)))
check("этот месяц", A.parse_period("в этом месяце", mon) == (date(2026, 11, 1), mon))
check("прошлая неделя", A.parse_period("за прошлую неделю", mon) == (date(2026, 11, 2), date(2026, 11, 8)))
check("с 1 по 5 ноября", A.parse_period("с 1 по 5 ноября", mon) == (date(2026, 11, 1), date(2026, 11, 5)))
check("в 15:00", A.parse_time("запиши в 15:00") == "15:00")
check("в 9.30", A.parse_time("в 9.30") == "09:30" and A.parse_time("на 10.11") == "")
check("в 3 дня", A.parse_time("в 3 дня") == "15:00")
check("в 11", A.parse_time("к Петрову в 11") == "11:00")
check("на 15 ноября is no time", A.parse_time("на 15 ноября") == "")
check("через неделю", A.parse_due("перезвонить через неделю", mon) == date(2026, 11, 16))
check("через 3 дня", A.parse_due("через 3 дня", mon) == date(2026, 11, 12))
check("через месяц", A.parse_due("через месяц", mon) == mon + timedelta(days=30))
f = A.surname_forms("Петрова")
check("surname forms, female", f["acc"] == "петрову" and f["dat"] == "петровой", f)
f = A.surname_forms("Петров")
check("surname forms, male", f["acc"] == "петрова" and f["dat"] == "петрову", f)
check("surname forms, -ская", A.surname_forms("Вишневская")["acc"] == "вишневскую")

pf = patient("Зарецкая", "Анна", "+7 900 111-22-33")
pm = patient("Зарецкий", "Иван")
pa1 = patient("Шульгина", "Ольга")
pa2 = patient("Шульгина", "Мария")
ast = A.Assistant(a)
check("«запиши Зарецкую» → the woman", [r["id"] for r in ast.find_patients("Запиши Зарецкую на завтра")] == [pf])
check("«перезвонить Зарецкому» → the man", [r["id"] for r in ast.find_patients("перезвонить Зарецкому")] == [pm])
check("first name narrows", [r["id"] for r in ast.find_patients("запиши Шульгину Марию")] == [pa2])
check("two namesakes → both", {r["id"] for r in ast.find_patients("найди Шульгину")} == {pa1, pa2})
check("doctor after «к» is not a patient", ast.find_doctors("запиши Зарецкую к Гусевой")[0]["id"] == GUS["id"])

# ------------------------------------------------------------------ routing
for q, tool in (("Кто у меня завтра?", "schedule"), ("Расписание Гусевой на четверг", "schedule"), ("Выручка за октябрь", "revenue"),
                ("Кто должен клинике?", "debts"), ("Пациенты без гигиены больше 6 месяцев", "segment"), ("Что заканчивается на складе?", "stock"),
                ("Сводка за неделю", "week"), ("Запиши Петрову на четверг", "book"), ("Напомни перезвонить Иванову через неделю", "task"),
                ("Заметка Петровой: просит утро", "note"), ("Найди Петрову", "patient"), ("мои задачи", "tasks"),
                ("Переведи на английский: Ждём вас", "translate"), ("что ты умеешь", "help")):
    r = ast.route(q)
    check(f"route «{q}»", r and r["tool"] == tool, r)
check("unknown question without AI", ast.route("как погода") is None)
h = ask("что ты умеешь")
check("help lists examples", h["tool"] == "help" and len(h["examples"]) == len(A.EXAMPLES) and h["ai"] is False)
r = ask("как погода")
check("unknown → help, no AI", r["tool"] == "help" and "Не понял" in r["text"])

# ------------------------------------------------------------------ answers from the data
vday = T + timedelta(days=1)
while vday.weekday() == 6:
    vday += timedelta(days=1)
v1 = a.save_visit({"patient_id": pf, "doctor_id": GUS["id"], "start": f"{vday} 11:00", "end": f"{vday} 11:30", "status": "Запланирован", "title": "Пломба"})
r = ask(f"расписание Гусевой на {vday.strftime('%d.%m')}")
check("doctor's day", r["tool"] == "schedule" and any(x["go"] == {"visit": v1} and "Зарецкая" in x["sub"] for x in r["rows"])
      and "Гусева П. И." in r["text"], r)
r = ask(f"свободное время у Гусевой {vday.strftime('%d.%m')}")
check("free time skips the booked 11:00", "11:00" not in r["text"] and "Свободное время" in r["text"], r["text"])  # demo visits fill other hours

inv = a.save_invoice({"patient_id": pf, "doctor_id": GUS["id"], "items": [{"title": "Пломба", "price": 5000}]})
a.add_payment({"invoice_id": inv, "patient_id": pf, "amount": 3000, "method": "Наличные"})
r = ask("сколько заплатила Зарецкая в этом месяце")
check("patient paid", "3 000 ₽" in r["text"] and "Зарецкая" in r["text"], r["text"])
r = ask("выручка Гусевой в этом месяце")
check("doctor's revenue", "Гусева" in r["text"] and "поступило" in r["text"], r["text"])
r = ask("выручка в этом месяце")
check("clinic revenue", r["text"].startswith("Клиника") and r["rows"], r)
r = ask("кто должен клинике")
check("debts list", r["text"].startswith("Должны клинике") and r["rows"] and all(x["go"].get("patient") for x in r["rows"]), r)
check("the patient's debt is in the report", any(x["patient_id"] == pf and x["total"] == 2000 for x in a.report_debts()["debts"]))
r = ask("найди Зарецкую", )
check("patient card answer", r["text"].startswith("Зарецкая") and any("Долг: 2 000 ₽" in x for x in r["lines"])
      and any("Следующий визит" in x for x in r["lines"]), r)
r = ask("что заканчивается на складе")
check("stock answer", r["tool"] == "stock" and "Заканчиваются" in r["text"], r["text"])
r = ask("сводка за неделю")
check("weekly via the assistant", r["tool"] == "week" and r["text"].startswith("Неделя") and r["lines"], r)
r = ask("пациенты без гигиены больше 6 месяцев")
check("no hygiene list", r["tool"] == "segment" and "Без профгигиены больше 6 мес." in r["text"] and r["more"], r["text"])

# proposals: nothing is changed until the employee confirms
n0 = d.one("SELECT COUNT(*) AS n FROM local_visits")["n"]
r = ask(f"Запиши Зарецкую на {vday.strftime('%d.%m')} к Гусевой в 11:00")
check("booking proposal", r["action"]["method"] == "save_visit" and r["action"]["args"][0]["start"] == f"{vday} 11:00"
      and r["action"]["args"][0]["doctor_id"] == GUS["id"], r)
check("clash noted", any("уже" in x for x in r["lines"]), r["lines"])
check("nothing booked yet", d.one("SELECT COUNT(*) AS n FROM local_visits")["n"] == n0)
r = ask(f"Запиши её на {vday.strftime('%d.%m')} к Гусевой", {"patient_id": pf})
check("first free slot, patient from the open card", r["action"]["args"][0]["patient_id"] == pf
      and r["action"]["args"][0]["start"] != f"{vday} 11:00", r)
r = ask(f"Запиши Зарецкую на {vday.strftime('%d.%m')} к Гусевой")
check("a date is not a time", r["action"]["args"][0]["start"][11:] not in (f"{vday.day:02d}:{vday.month:02d}", f"{vday.day:02d}:00"), r)
r = ask("Запиши Зарецкую на вчера к Гусевой")
check("no booking in the past", "прошёл" in r["text"], r["text"])
r = ask("Запиши Зарецкую на завтра")
check("asks for the doctor", "К какому врачу" in r["text"], r["text"])
r = ask("Напомни перезвонить Зарецкому через неделю")
check("task proposal", r["action"]["method"] == "crm_task_save" and r["action"]["args"][0]["patient_id"] == pm
      and r["action"]["args"][0]["due"] == day(7) and "через" not in r["action"]["args"][0]["title"], r)
r = ask("Заметка Зарецкой: просит утреннее время")
check("note proposal", r["action"]["method"] == "add_note" and r["action"]["args"] == [pf, "просит утреннее время"], r)
r = ask("Переведи на английский: Ждём вас завтра")
check("translate needs the AI", "ИИ" in r["text"], r["text"])

# ------------------------------------------------------------------ voice: tooth chart and notes
fm = dictation.formula("Восемнадцать отсутствует, семнадцать коронка, шестнадцать кариес. Сорок семь имплант коронка, "
                       "с двадцать шестого по двадцать восьмой отсутствуют, коронка на тридцать шесть")
check("voice chart", fm["teeth"] == {"18": "Отсутствует", "17": "Коронка", "16": "Кариес", "47": "Имплант, Коронка", "26": "Отсутствует",
                                     "27": "Отсутствует", "28": "Отсутствует", "36": "Коронка"}, fm)
check("teeth_parse api", a.teeth_parse("тридцать шесть пломба")["teeth"] == {"36": "Пломба"})
vn = A.voice_note("перезвонить через неделю, пригласить на гигиену", mon)
check("voice note → task", vn["task"] and vn["task"]["due"] == "2026-11-16" and vn["text"].startswith("Перезвонить"), vn)
check("voice note without a task", A.voice_note("пациент просит утреннее время")["task"] is None)

# ------------------------------------------------------------------ drafts without the AI (rules)
rid = a.save_record({"patient_id": pf, "doctor_id": GUS["id"], "date": T.isoformat(), "complaints": "Боль в зубе 48",
                     "objective": "Зуб 48 разрушен", "treatment": "Анестезия Ультракаин 1,7 мл, удаление зуба 48",
                     "diagnoses": [{"code": "K08.3", "title": "Задержка корня зуба", "tooth": "48"}], "source": ["dictation", "ai", "bad"]})
check("record keeps how it was made", a.record(rid)["data"]["source"] == ["ai", "dictation"])
w = a.ai_write("recommendations", rid)
check("memo by rules", w["engine"] == "rules" and "Холод" in w["text"] and "позвоните в клинику" in w["text"], w["text"])
w = a.ai_write("extract", None, pf)
check("extract by rules", "Диагноз: K08.3" in w["text"] and "Проведено лечение" in w["text"], w["text"])
w = a.ai_write("insurance", rid)
check("insurance letter by rules", "K08.3" in w["text"] and "ДМС" in w["text"], w["text"])
w = a.ai_write("explain", None, pf, None, {"diagnoses": [{"code": "K04.0", "title": "Пульпит", "tooth": "26"}], "treatment": "Экстирпация пульпы"})
check("explain an unsaved form", "воспаление нерва" in w["text"], w["text"])
refuses("no records → no draft", lambda: a.ai_write("recommendations", None, pm), "нет записей")
pv = a.ai_plan_variant({"name": "Премиум", "warranty": "5 лет", "items": [{"title": "Имплантат", "tooth": "36"}]})
check("plan option by rules", "Имплантат (зуб 36)" in pv["text"] and "5 лет" in pv["text"] and pv["engine"] == "rules", pv)
refuses("translation needs the AI", lambda: a.ai_translate(["Здравствуйте"], "en"), "ИИ")
refuses("unknown language", lambda: ai_docs.translate(["x"], "xx"), "язык")

# ------------------------------------------------------------------ with the AI: anonymous data only
sent = []


def fake_chat(messages, s=None):
    sent.append(messages)
    user = messages[-1]["content"]
    sysm = messages[0]["content"]
    if "Определи, что просит" in sysm:
        if "пульпит" in user:
            return '{"tool": "free"}'
        return '{"tool": "schedule", "doctor": "Гусева", "date": "%s"}' % vday.isoformat()
    if "translator" in sysm or "переводчик" in sysm:
        check("translation goes without «write in Russian»", ai.BASE not in sysm)
        lines = [x for x in user.split("\n") if "|" in x]
        keep = lines[:-1] if len(lines) > 1 else lines  # loses the last line of a pack
        return "\n".join(f"{x.split('|')[0]}| EN {x.split('|', 1)[1].strip()}" for x in keep)
    if "Ответь на вопрос" in sysm:
        return "**Пульпит** — воспаление нерва."
    return "Конечно! Вот памятка:\n\n— Не есть 2 часа."


real_chat = ai._chat
ai._chat = fake_chat
config.save_settings({"ai": {**ai.DEFAULTS, "enabled": True, "provider": "openai", "base_url": "http://127.0.0.1:9", "model": "x"}})
w = a.ai_write("recommendations", rid)
check("memo by the AI, the «when to call» point kept", w["engine"] == "ai" and w["text"] == "— Не есть 2 часа.\n— " + ai_docs.URGENT, w)
check("the model gets the clinic's standard advice", "Стандартные рекомендации клиники" in sent[-1][-1]["content"]
      and "Холод на щёку" in sent[-1][-1]["content"])
check("no name or phone sent", "Зарецкая" not in json.dumps(sent[-1], ensure_ascii=False)
      and "900 111" not in json.dumps(sent[-1], ensure_ascii=False))
a.add_note(pf, "Зарецкая Анна просила перезвонить на +7 900 111-22-33")
check("anonymize", ai.anonymize("Зарецкая Анна, +7 900 111-22-33", ["Зарецкая Анна Тест"]) == "Пациент Пациент, [телефон]")
tr = a.ai_translate(["Здравствуйте, Зарецкая", "", "Пломба на 36", "До свидания"], "en", pf)
check("translation keeps lines and numbers", tr["lines"][0] == "EN Здравствуйте, Пациент" and tr["lines"][1] == ""
      and tr["lines"][2] == "EN Пломба на 36" and tr["lines"][3] == "До свидания", tr)
r = ask("как погода у Гусевой послезавтра")
check("AI picks the tool", r["tool"] == "schedule" and r["engine"] == "ai", r)
r = ask("Переведи на английский: Ждём вас завтра в 10:00")
check("translate a message", str(r.get("copy", "")).startswith("EN") and r.get("ai_answer"), r)
ai._chat = lambda m, s=None: "не json"
r = ask("чем отличается пульпит от периодонтита")
check("AI cannot route → free answer", r["tool"] == "free", r)
ai._chat = fake_chat
r = ask("чем отличается пульпит от периодонтита")
check("free answer cleaned", r["text"] == "Пульпит — воспаление нерва." and r["ai_answer"], r)
check("clean_answer", ai.clean_answer("## Итог\n**Да**\n* пункт") == "Итог\nДа\n— пункт")
pv = a.ai_plan_variant({"name": "Премиум", "items": [{"title": "Имплантат"}]})
check("plan option by the AI", pv["engine"] == "ai")
# 2.14.1: short texts — a limit of tokens for the model, the reply cut at whole sentences, no greeting
LONG = ("Здравствуйте, Пациент. Предлагаем вам вариант лечения под названием «Премиум». Он включает установку имплантата "
        "Straumann для зуба 36, а затем коронку из циркония на этом имплантате. Этот план обеспечит надёжную и долговечную "
        "замену зуба, гарантия 5 лет. Лечение займёт около 4 месяцев, включая 3 месяца на приживление имплантата.")
got = {}
ai._chat = lambda m, s=None: got.update(s or {}) or LONG
pv = a.ai_plan_variant({"name": "Премиум", "warranty": "5 лет", "items": [{"title": "Имплантат", "tooth": "36"}]})
check("a long option is cut to whole sentences", pv["engine"] == "ai" and len(pv["text"]) <= ai_docs.LIMITS["plan_variant"]
      and pv["text"].endswith(".") and pv["text"].startswith("Предлагаем"), pv["text"])
check("the model gets a short token limit", got.get("max_tokens") == ai.tokens_for(ai_docs.LIMITS["plan_variant"]), got.get("max_tokens"))
check("the note always fits the plan (400)", len(ai_docs.plan_variant({"name": "Х", "items": [{"title": "Очень длинная услуга " * 6}] * 9})["text"]) <= 400)
check("fit: whole lines of a list", ai.fit("— раз\n— два\n— три", 12) == "— раз\n— два")
check("fit: one long sentence → cut at a word", ai.fit("слово " * 30, 40).endswith("…") and len(ai.fit("слово " * 30, 40)) <= 40)
check("fit: short text untouched", ai.fit("Коротко.", 260) == "Коротко.")
ai._chat = lambda m, s=None: "— Не есть 2 часа.\n" + "\n".join(f"— Совет номер {i}, довольно длинный, чтобы не влезть." for i in range(40))
w = a.ai_write("recommendations", rid)
check("a cut memo still ends with when to call", len(w["text"]) <= ai_docs.LIMITS["recommendations"] and w["text"].endswith(ai_docs.URGENT), w["text"][-120:])
ai._chat = lambda m, s=None: got.update(s or {}) or "Пульпит — воспаление нерва. " * 60
r = ask("чем отличается пульпит от периодонтита")
check("a free answer has a limit", len(r["text"]) <= A.FREE_LIMIT and got.get("max_tokens") == ai.tokens_for(A.FREE_LIMIT), len(r["text"]))
ai._chat = lambda m, s=None: "Жалобы: ночные боли.\nДиагноз: K04.0 Пульпит (зуб 26).\nРекомендации: наблюдение у врача."
ex = ai_docs.write("extract", {"data": {"complaints": "ночные боли", "diagnoses": [{"code": "K04.0", "tooth": "26"}]}})
check("an extract without the doctor's recommendations has none", ex["engine"] == "ai" and "Рекомендац" not in ex["text"] and "Диагноз" in ex["text"], ex["text"])
ex = ai_docs.write("extract", {"data": {"complaints": "ночные боли", "recommendations": "не жевать на этой стороне"}})
check("the doctor's recommendations stay", "Рекомендации" in ex["text"])
ai._chat = fake_chat
wk = a.director_weekly(None, True)
check("weekly retold by the AI and kept", wk["ai_text"] and d.meta_get(f"ai_weekly:{wk['week']}") == wk["ai_text"])
ai._chat = lambda m, s=None: (_ for _ in ()).throw(ValueError("нет связи"))
w = a.ai_write("recommendations", rid)
check("AI fails → rules", w["engine"] == "rules" and w["ai_error"] == "нет связи" and "Холод" in w["text"])
ai._chat = real_chat
config.save_settings({"ai": {**ai.DEFAULTS}})

# ------------------------------------------------------------------ record check (14.4)
it = medcheck.check_record({"treatment": "Лечение каналов зуба 36, анестезия", "rx": [{"name": "Ибупрофен"}],
                            "diagnoses": [{"code": "K04.0", "title": "Пульпит"}]})
txt = " ".join(x["text"] for x in it)
check("record check finds gaps", all(w in txt for w in ("K04.0 без номера зуба", "Не заполнен осмотр", "рентгеновский снимок",
                                                         "Анестезия без препарата", "Ибупрофен")), txt)
check("short labels", all(x.get("short") for x in it))
it = medcheck.check_record({"complaints": "Нет", "objective": "Полость", "treatment": "Каналы 36", "date": T.isoformat(),
                            "diagnoses": [{"code": "K04.0", "tooth": "36"}]}, [day(-3)])
check("X-ray within 60 days is enough", not any("снимок" in x["text"] for x in it), it)
check("record check api", any("диагноз" in x["text"] for x in a.medcheck_record({"patient_id": pf})))
mc = a.medcheck_patient(pf)
txt = " ".join(x["text"] for x in mc["items"])
check("card check: consents missing", "согласия на лечение" in txt and "персональных данных" in txt and mc["warn"] >= 2, txt)
check("card check: no X-ray for the extraction", "рентгеновский" in txt, txt)
a.save_document({"patient_id": pf, "template_id": "doc_consent_treatment", "title": "Согласие", "html": "<p>x</p>"})
a._files.add(pf, "48.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, {"kind": "xray", "taken_at": T.isoformat()})
txt2 = " ".join(x["text"] for x in a.medcheck_patient(pf)["items"])
check("card check updates", "согласия на лечение" not in txt2 and "рентгеновский" not in txt2, txt2)

# ------------------------------------------------------------------ the director's week (14.8)
wk = a.director_weekly()
check("weekly summary", wk["title"].startswith("Неделя") and any(x.startswith("Поступило") for x in wk["lines"])
      and any(x.startswith("Новых пациентов") for x in wk["lines"]) and wk["ai"] is False, wk)
check("no patient names in the week", not any("Зарецк" in x for x in wk["lines"]))

# ------------------------------------------------------------------ consent to record the visit (13.7)
refuses("visit recording without consent", lambda: a.dictate("", "audio/webm", pf, "visit"), "согласия")
refuses("unknown consent way", lambda: a.consent_give(pf, "smoke"), "как получено")
c = a.consent_give(pf, "verbal")
check("consent given", c["active"] and c["method"] == "verbal" and a.patient(pf)["consent_recording"]["active"])
refuses("with consent the recording goes on (empty audio here)", lambda: a.dictate("", "audio/webm", pf, "visit"), "Пустая запись")
c = a.consent_revoke(pf)
check("consent withdrawn", not c["active"] and c["revoked_at"])
check("given again", a.consent_give(pf, "paper")["active"])
check("one row per patient", d.one("SELECT COUNT(*) AS n FROM patient_consents WHERE patient_id=?", (pf,))["n"] == 1)
check("consent form template", any(t["id"] == "doc_consent_recording" for t in a.templates("document")))

# ------------------------------------------------------------------ the local model and the quality check
llm_local.models_ready = lambda: []
refuses("clinic model needs a base model", llm_local.make_custom, "скачайте модель")
check("clinic model base: Gemma first", llm_local._base_for_custom(["qwen2.5:3b", "gemma3:4b"]) == "gemma3:4b"
      and llm_local._base_for_custom(["qwen2.5:3b"]) == "qwen2.5:3b" and llm_local._base_for_custom(["other:1b"]) is None)
check("clinic model settings", llm_local.CUSTOM_PARAMS["num_ctx"] == llm_local.CTX and len(llm_local.CUSTOM_EXAMPLES) % 2 == 0)
check("russian share", ai_eval._ru_share("Привет мир") == 1.0 and ai_eval._ru_share("Привет 你好") < 0.9)
ideal = {"dictation": json.dumps({"complaints": "Боль от холодного", "treatment": "Анестезия Ультракаин, пломба",
                                  "diagnoses": [{"code": "K02.1", "tooth": "36"}], "teeth": {"36": "Пломба"}}, ensure_ascii=False),
         "extraction": "— Холод на щёку. — Не полоскать рот. — Не есть 2 часа. — При боли позвоните в клинику.",
         "en": "1| Do not eat for 2 hours.\n2| A filling was placed on tooth 36."}


def eval_chat(messages, s=None):
    u = messages[-1]["content"]
    if "тридцать шестом" in u:
        return ideal["dictation"]
    if "удаление зуба 48" in u:
        return ideal["extraction"]
    if "Не принимать пищу" in u and "English" in messages[0]["content"]:
        return ideal["en"]
    return "Ответ"


ai._chat = eval_chat
res = ai_eval.run({"provider": "openai", "model": "x"}, only=["dictation", "extraction", "en", "route_free"])
ai._chat = real_chat
byid = {c["id"]: c for c in res["cases"]}
check("eval: ideal answers score 100", byid["dictation"]["accuracy"] == 1 and byid["extraction"]["accuracy"] == 1 and byid["en"]["accuracy"] == 1, byid)
check("eval: a wrong answer scores 0", byid["route_free"]["accuracy"] == 0)
check("eval summary", res["accuracy"] == 75 and res["russian"] == 100 and res["model"] == "x", res)
check("eval has 12 cases", len(ai_eval._cases()) == 12)

# ------------------------------------------------------------------ rights, journal, sync
new = ["assistant_ask", "assistant_voice", "ai_langs", "ai_write", "ai_plan_variant", "ai_translate", "medcheck_patient", "medcheck_record",
       "director_weekly", "teeth_voice", "teeth_parse", "voice_note", "note_parse", "consent_get", "consent_give", "consent_revoke",
       "local_ai_custom", "local_ai_eval"]
check("every new method has a right", all(m in auth.METHOD_PERMS for m in new) and all(hasattr(a, m) for m in new))
check("changes are in the journal", all(m in auth.AUDITED for m in ("consent_give", "consent_revoke", "local_ai_custom")))
check("consents go to the other laptops", "patient_consents" in {t.name for t in replica.TABLES})

sk = socket.socket(); sk.bind(("127.0.0.1", 0)); PORT = sk.getsockname()[1]; sk.close()
srv = ClinicServer(a, d, port=PORT, host="127.0.0.1").start()


def call(kind, name, *args, token=""):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/{kind}/{name}", data=json.dumps(list(args)).encode(),
                                 headers={"Content-Type": "application/json", "X-Session": token}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


TD = call("auth", "bootstrap", {"name": "Директор", "login": "dir", "password": "secret1"})[1]["token"]
for login, role in (("adm", "admin"), ("doc", "doctor"), ("asi", "assistant")):
    call("auth", "register", {"name": login.upper(), "login": login, "password": "secret1"})
    u = next(x for x in call("auth", "staff_list", token=TD)[1]["staff"] if x["login"] == login)
    call("auth", "staff_save", {"id": u["id"], "role": role, "status": "active", "doctor_id": GUS["id"] if login == "doc" else None}, token=TD)
TA, TDoc, TAs = (call("auth", "login", x, "secret1")[1]["token"] for x in ("adm", "doc", "asi"))
st, r = call("api", "assistant_ask", "выручка в этом месяце", {}, token=TDoc)
check("doctor: no revenue", st == 200 and r.get("denied"), r)
st, r = call("api", "assistant_ask", "кто должен клинике", {}, token=TA)
check("admin: debts allowed (payments)", st == 200 and not r.get("denied") and r["tool"] == "debts", r)
st, r = call("api", "assistant_ask", "пациенты без гигиены больше 6 месяцев", {}, token=TDoc)
check("doctor: no CRM lists", r.get("denied"), r)
st, r = call("api", "assistant_ask", f"кто у меня {vday.strftime('%d.%m')}", {}, token=TDoc)
check("doctor: «у меня» = own schedule", st == 200 and r["rows"] and all("·" not in x["sub"] or "Гусева" not in x["sub"] for x in r["rows"])
      and ", у вас" in r["text"], r)
st, r = call("api", "assistant_ask", "что ты умеешь", {}, token=TAs)
check("assistant role: help shows only allowed examples", st == 200 and all(e[1] in ("schedule", "stock") for e in A.EXAMPLES if e[0] in r["examples"]) and r["examples"], r)
check("assistant role: no drafts", call("api", "ai_write", "recommendations", rid, token=TAs)[0] == 403)
check("assistant role: no consent marks", call("api", "consent_give", pf, "verbal", token=TAs)[0] == 403)
check("doctor marks consent", call("api", "consent_give", pf, "verbal", "", token=TDoc)[0] == 200)
check("director's week: reports only", call("api", "director_weekly", token=TDoc)[0] == 403 and call("api", "director_weekly", token=TD)[0] == 200)
st, r = call("api", "assistant_ask", "Запиши Зарецкую на завтра к Гусевой", {}, token=TAs)
check("assistant role cannot book", r.get("denied"), r)
au = d.q("SELECT action, user_name FROM audit WHERE action='Согласие пациента на запись приёма' ORDER BY id")
check("consent in the journal", au and au[-1]["user_name"] == "DOC", au)
srv.stop()

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
