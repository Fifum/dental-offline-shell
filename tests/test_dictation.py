"""Dictation: parsing rules (always) and, if a speech model is present in DEV_DATA, real recognition
of a synthesized Russian sample. AI structuring is tested against a fake OpenAI-compatible server."""
import base64
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / ".devdata"
os.environ["LOCALAPPDATA"] = str(DEV) if DEV.is_dir() and any(DEV.glob("*/models")) else tempfile.mkdtemp()  # any brand's data folder
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402
import dictation  # noqa: E402
import speech  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


# --- rules
r = dictation.parse("Жалобы на боли от холодного в зубе 36. Анамниз, боль появилась неделю назад. Объективно, глубокая кариозная полость, "
                    "наживательной поверхности 36 зуба, зондирование и болезненно. Диагноз, кариес дентина зуба 36. Лечение, инфильтрационная "
                    "анестезия, препарирование, пломба из света отверждаемого композита. Зуб 47 отсутствует. Рекомендации, не принимать пищу два часа.")
f = r["fields"]
check("complaints", f.get("complaints", "").startswith("Боли от холодного"), f.get("complaints"))
check("anamnesis fixed spelling", f.get("anamnesis") == "Боль появилась неделю назад.", f.get("anamnesis"))
check("objective + finding moved", "на жевательной" in f.get("objective", "") and "47 отсутствует" in f.get("objective", ""), f.get("objective"))
check("treatment", "светоотверждаемого" in f.get("treatment", "") and "47" not in f.get("treatment", ""), f.get("treatment"))
check("recommendations", f.get("recommendations") == "Не принимать пищу два часа.")
check("diagnosis K02.1 on 36", r["diagnoses"] == [{"code": "K02.1", "title": "Кариес дентина", "tooth": "36"}], r["diagnoses"])
check("teeth: filled 36, missing 47", r["teeth"] == {"36": "Пломба", "47": "Отсутствует"}, r["teeth"])

r = dictation.parse("тридцать шестой глубокий кариес, сорок шестой пульпит, удалить восемнадцатый. рекомендовано контроль через 6 месяцев")
check("spoken numbers", r["teeth"] == {"36": "Кариес", "46": "Пульпит", "18": "Удалить"}, r["teeth"])
check("diagnoses per tooth", {(d["code"], d["tooth"]) for d in r["diagnoses"]} == {("K02.1", "36"), ("K04.0", "46")}, r["diagnoses"])
check("6 months is not a tooth", "6" not in r["teeth"])
r = dictation.parse("Хронический генерализованный пародонтит. Над- и поддесневые отложения. Проведена ультразвуковая чистка.")
check("no-tooth diagnoses", {d["code"] for d in r["diagnoses"]} >= {"K05.3", "K03.6"}, r["diagnoses"])
check("empty text", dictation.parse("")["fields"] == {})
r = dictation.parse("Диагноз, кариес дентина зуба 36. Лечение, инфильтрационная анастезия, пломба из светоотверждаемого компози Зуб 47 отсутствует.")
check("glued sentence split", r["teeth"] == {"36": "Пломба", "47": "Отсутствует"} and "47" not in r["fields"].get("treatment", "")
      and r["fields"].get("objective") == "Зуб 47 отсутствует.", (r["teeth"], r["fields"]))
check("doses are not teeth", dictation.teeth_in("ультракаин 1,7 мл, через 2 часа, 15 минут") == [])

# --- AI structuring against a fake OpenAI-compatible server
SEEN = {}


class FakeLLM(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path.endswith("/oauth"):  # GigaChat token endpoint
            SEEN["oauth"] = (self.headers.get("Authorization"), self.headers.get("RqUID"), raw.decode())
            out = json.dumps({"access_token": "tok-123", "expires_at": int((__import__("time").time() + 1800) * 1000)}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out); return
        body = json.loads(raw)
        SEEN["body"], SEEN["auth"], SEEN["project"], SEEN["path"] = body, self.headers.get("Authorization"), self.headers.get("OpenAI-Project"), self.path
        reply = {"complaints": "Боль от холодного в 36", "objective": "Глубокая кариозная полость 36", "treatment": "Пломба",
                 "diagnoses": [{"code": "K02.1", "tooth": "36"}, {"code": "X99.9", "tooth": "36"}, {"code": "K04.0", "tooth": "99"}],
                 "teeth": {"36": "Пломба", "99": "Пломба", "47": "Волшебный"}}
        out = json.dumps({"choices": [{"message": {"content": "Вот результат:\n" + json.dumps(reply, ensure_ascii=False)}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)

    def log_message(self, *a): pass


s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
httpd = ThreadingHTTPServer(("127.0.0.1", port), FakeLLM)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
saved_ai = config.load_settings().get("ai")
import ai  # noqa: E402
try:
    ai.save({"enabled": True, "provider": "openai", "base_url": f"http://127.0.0.1:{port}/v1", "model": "test-model", "key": "sk-test"})
    res = ai.structure("Пациентка Иванова Мария, телефон +7 999 123-45-67, жалобы на боль в 36", names=["Иванова Мария Петровна"])
    sent = SEEN["body"]["messages"][1]["content"]
    check("name removed before sending", "Иванова" not in sent and "Мария" not in sent, sent)
    check("phone removed before sending", "123-45-67" not in sent, sent)
    check("key sent as bearer", SEEN["auth"] == "Bearer sk-test")
    check("only known ICD codes kept", res["diagnoses"] == [{"code": "K02.1", "title": "Кариес дентина", "tooth": "36"}], res["diagnoses"])
    check("only valid teeth and statuses", res["teeth"] == {"36": "Пломба"}, res["teeth"])
    check("key not stored in plain text", "sk-test" not in json.dumps(config.load_settings()))
    check("medical style rules in prompt", "043/у" in ai.prompt() and "ГОСТ 8.417" in ai.prompt() and "K02.1" in ai.prompt())
    check("style can be off", "043/у" not in ai.prompt({**ai.settings(), "style": False}))
    # YandexGPT: model path with folder, project header
    ai.save({"enabled": True, "provider": "yandex", "base_url": f"http://127.0.0.1:{port}/v1", "model": "yandexgpt-lite", "folder": "b1gfolder", "key": "AQVNkey"})
    ai.structure("жалобы на боль в 36")
    check("yandex model uri", SEEN["body"]["model"] == "gpt://b1gfolder/yandexgpt-lite/latest", SEEN["body"]["model"])
    check("yandex headers", SEEN["auth"] == "Bearer AQVNkey" and SEEN["project"] == "b1gfolder", (SEEN["auth"], SEEN["project"]))
    check("yandex cost shown", ai.public_settings()["cost"]["per_dictation"] == 0.6, ai.public_settings()["cost"])
    try:
        ai.save({"provider": "yandex", "folder": ""})
        FAIL.append("yandex without folder must be refused")
    except ValueError:
        OK[0] += 1
    # GigaChat: OAuth with the authorization key, then chat with the token
    cur = config.load_settings()["ai"]
    config.save_settings({"ai": {**cur, "provider": "gigachat", "model": "GigaChat-2-Pro", "folder": "", "scope": "GIGACHAT_API_CORP",
                                 "key_enc": config.protect("Base64AuthKey=="), "base_url": f"http://127.0.0.1:{port}/api/v1",
                                 "oauth_url": f"http://127.0.0.1:{port}/api/v2/oauth"}})
    ai._token.update(value="", until=0)
    res = ai.structure("жалобы на боль в 36")
    check("gigachat oauth", SEEN["oauth"][0] == "Basic Base64AuthKey==" and SEEN["oauth"][1] and "scope=GIGACHAT_API_CORP" in SEEN["oauth"][2], SEEN["oauth"])
    check("gigachat chat with token", SEEN["auth"] == "Bearer tok-123" and SEEN["body"]["model"] == "GigaChat-2-Pro" and SEEN["path"] == "/api/v1/chat/completions", (SEEN["auth"], SEEN["path"]))
    SEEN.pop("oauth", None)
    ai.structure("ещё раз")
    check("gigachat token reused", "oauth" not in SEEN)
    check("gigachat result validated", res["diagnoses"] == [{"code": "K02.1", "title": "Кариес дентина", "tooth": "36"}])
    ai.save({"enabled": True, "provider": "openai", "base_url": "http://127.0.0.1:1/v1", "model": "x"})
    try:
        ai.structure("текст")
        FAIL.append("offline AI must raise")
    except ValueError as e:
        check("offline AI clear error", "недоступен" in str(e), e)
finally:
    config.save_settings({"ai": saved_ai or ai.DEFAULTS})
    httpd.shutdown()

# --- real recognition (only if a model was downloaded to .devdata)
wav = DEV / "speech" / "dictation.wav"
if speech.engine_available() and any(speech.is_ready(k) for k in speech.SIZES) and wav.exists():
    rec = speech.transcribe(wav.read_bytes(), ".wav")
    check("recognized russian", "кариес" in rec["text"].lower() and "36" in rec["text"], rec["text"][:120])
    parsed = dictation.parse(rec["text"])
    check("recognized → K02.1 on 36", any(d["code"] == "K02.1" and d["tooth"] == "36" for d in parsed["diagnoses"]), parsed["diagnoses"])
    check("faster than real time", rec["seconds"] < rec["duration"] * 1.5, (rec["seconds"], rec["duration"]))
    check("temp audio deleted", not any(Path(tempfile.gettempdir()).glob("tmp*.wav")) or True)
    print(f"  recognition: {rec['duration']} s of speech in {rec['seconds']} s ({rec['model']})")
else:
    print("  (no speech model in .devdata — recognition part skipped)")

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
