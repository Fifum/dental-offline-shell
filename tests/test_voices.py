"""Who is speaking in a visit recording: voice prints of employees, labelling replies, the API and the
AI prompt for a conversation. The neural model is replaced by a fake that tells tones apart, so the
test runs without downloading anything; the real model is checked by hand with synthesized voices."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import numpy as np  # noqa: E402

import db as dbm  # noqa: E402
import voices  # noqa: E402
from auth import METHOD_PERMS, Auth  # noqa: E402
from main import Api  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


SR = voices.SR
tone = lambda hz, sec: (0.3 * np.sin(2 * np.pi * hz * np.arange(int(sec * SR)) / SR)).astype(np.float32)  # noqa: E731
gap = lambda sec: np.zeros(int(sec * SR), np.float32)  # noqa: E731

# --- features: shape and sanity
f = voices.fbank(tone(440, 2.0))
check("fbank 80 bands, 10 ms frames", f.shape == (198, 80), f.shape)
check("fbank finite and mean-normalized", np.isfinite(f).all() and abs(float(f.mean())) < 1e-3)


# --- a fake voice model: the "voice" is the pitch of the tone
def fake_embed(chunks):
    out = []
    for c in chunks:
        hz = np.argmax(np.abs(np.fft.rfft(c))) * SR / len(c)
        v = np.zeros(256, np.float32)
        v[int(hz // 50) % 256] = 1.0
        out.append(v)
    return voices._norm(np.array(out)) if out else np.zeros((0, 256), np.float32)


voices.embed_many = fake_embed
voices.speech_only = lambda w: w  # tones have no pauses to cut

doc, asst = fake_embed([tone(200, 2)])[0], fake_embed([tone(400, 2)])[0]
wav = np.concatenate([tone(200, 3.0), gap(0.6), tone(800, 2.0), gap(0.6), tone(400, 1.5), gap(0.6), tone(200, 0.8)])
t = [0, 3.0, 3.6, 5.6, 6.2, 7.7, 8.3, 9.1]
words = [(t[0], 1.4, "Здравствуйте,"), (1.5, t[1], "на что жалуетесь?"), (t[2], t[3], "Болит зуб."),
         (t[4], t[5], "Подаю зеркало."), (t[6], t[7], "Хорошо.")]
lines = voices.label_words(wav, words, [("Врач", doc), ("Ассистент", asst)])
check("replies signed by voice", [lbl for lbl, _ in lines] == ["Врач", "Пациент", "Ассистент", "Врач"], lines)
check("one reply joined", lines[0][1] == "Здравствуйте, на что жалуетесь?", lines[0])
check("signed text", voices.as_text(lines).splitlines()[1] == "Пациент: Болит зуб.", voices.as_text(lines))
check("no voices — no signatures", voices.label_words(wav, words, []) == [("", " ".join(w[2] for w in words))])

# a long stretch without a pause: the interruption is still found window by window
long_wav = np.concatenate([tone(200, 4.0), tone(800, 4.0)])
lw = [(0.2, 1.8, "Откройте"), (2.0, 3.8, "рот."), (4.2, 5.8, "Ой,"), (6.0, 7.8, "больно.")]
ll = voices.label_words(long_wav, lw, [("Врач", doc)])
check("interruption inside a long stretch", [lbl for lbl, _ in ll] == ["Врач", "Пациент"], ll)

# a word too short to judge takes the voice of the nearest reply
sw = np.concatenate([tone(800, 2.0), gap(1.2), tone(200, 0.15), gap(0.4), tone(200, 2.0)])
sl = voices.label_words(sw, [(0.0, 2.0, "Больно."), (3.2, 3.35, "Нет,"), (3.75, 5.75, "это нормально.")], [("Врач", doc)])
check("too short word joins the nearest reply", sl == [("Пациент", "Больно."), ("Врач", "Нет, это нормально.")], sl)

# --- enrollment
try:
    voices.make_print(tone(200, 5))
    check("too little speech refused", False)
except ValueError as e:
    check("too little speech refused", "мало речи" in str(e), e)
p = voices.make_print(tone(200, 30))
check("print from 30 s", p["seconds"] == 30.0 and p["quality"] > 0.99 and abs(float(np.linalg.norm(p["emb"])) - 1) < 1e-3, p["quality"])

# --- storage, candidates and the API
d = dbm.DB()
auth = Auth(d)
with d.tx() as c:
    for uid, name, role, docid in [(1, "Директор Д.", "director", None), (2, "Врач В.", "doctor", "doc-1"),
                                   (3, "Врач Другой", "doctor", "doc-2"), (4, "Ассистент А.", "assistant", None),
                                   (5, "Кладовщик К.", "storekeeper", None)]:
        c.execute("INSERT INTO users(id, login, name, role, status, doctor_id) VALUES(?,?,?,?, 'active', ?)", (uid, f"u{uid}", name, role, docid))
voices.save_print(d, 2, p)
voices.save_print(d, 3, voices.make_print(tone(600, 30)))
voices.save_print(d, 4, voices.make_print(tone(400, 30)))
cands = voices.candidates(d, "doc-1")
check("candidates: visit's doctor and assistants only", sorted(lbl for lbl, _ in cands) == ["Ассистент", "Врач"], [c[0] for c in cands])
check("print stored as numbers, not sound", len(json.loads(d.one("SELECT emb FROM voice_prints WHERE user_id=2")["emb"])) == 256)


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


api = Api(d, W())
st = api.voice_status()
names = {u["name"]: u for u in st["staff"]}
check("voice status lists staff", "Ассистент А." in names and "Кладовщик К." not in names, list(names))
check("voice status shows who has a print", names["Врач В."]["voice"] and not names["Директор Д."]["voice"])
check("labels by role", names["Ассистент А."]["label"] == "Ассистент" and names["Врач В."]["label"] == "Врач")
check("a director who records is the doctor", names["Директор Д."]["label"] == "Врач", names["Директор Д."]["label"])
api.voice_delete(3)
check("print deleted", 3 not in voices.prints(d))
check("voice methods need settings permission",
      all(METHOD_PERMS.get(m) == "settings" for m in ("voice_status", "voice_download", "voice_enroll", "voice_delete")))

# enrollment through the API (decoding replaced: the recording is a tone)
voices.decode = lambda audio, suffix=".webm": tone(300, 25)
r = api.voice_enroll(1, "data:audio/webm;base64,AAAA", "audio/webm")
check("enroll via API", r["seconds"] == 25.0 and 1 in voices.prints(d), r)

# --- a signed conversation goes to the AI with the conversation rules; rules engine gets plain text
import ai  # noqa: E402
sent = {}


def fake_chat(messages, s=None):
    sent["system"], sent["user"] = messages[0]["content"], messages[1]["content"]
    return json.dumps({"complaints": "Боль от холодного в зубе 36.", "diagnoses": [{"code": "K02.1", "tooth": "36"}], "teeth": {"36": "Пломба"}})


ai._chat = fake_chat
ai.settings = lambda: {**ai.DEFAULTS, "enabled": True, "provider": "openai", "base_url": "http://x", "model": "m"}
talk = "Врач: Здравствуйте, на что жалуетесь?\nПациент: Болит зуб тридцать шесть от холодного.\nВрач: Кариес дентина, зуб 36."
out = api.parse_dictation(talk)
check("conversation rules sent to AI", "расшифровку разговора" in sent.get("system", ""), sent.get("system", "")[-200:])
check("signed text sent as is", sent.get("user", "").startswith("Врач:"), sent.get("user"))
check("AI result used", out["engine"] == "ai" and out["fields"].get("complaints") == "Боль от холодного в зубе 36.", out)
check("review keeps signatures", out["text"].startswith("Врач:"))
api.parse_dictation("Директор: Что беспокоит?\nПациент: Болит зуб.\nДиректор: Кариес 36.")
check("«Директор:» read as the doctor", "расшифровку разговора" in sent["system"] and sent["user"].startswith("Врач:")
      and "Директор" not in sent["user"], sent["user"])
api.parse_dictation("Жалобы на боль в 36. Объективно кариес.")
check("plain dictation without conversation rules", "расшифровку разговора" not in sent["system"])

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print("FAIL:", x)
sys.exit(1 if FAIL else 0)
