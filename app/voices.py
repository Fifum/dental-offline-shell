"""Who is speaking: tells the doctor and the assistant apart from the patient in a visit recording.

Each employee reads a short text once (Settings → «Голос и ИИ» → «Голоса сотрудников»). The program
keeps a voice print: 256 numbers that describe the voice, not the sound itself. During a visit
recording every 2 seconds of speech are compared with the prints of the visit's doctor and the
assistants: a close match is that employee, anything else is the patient.

Works on this computer without internet once the model (~27 MB) is downloaded. The sound is not kept.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger("voices")

MODEL_FILE = "voice-resnet34.onnx"
MODEL_MB = 27
MODEL_URLS = [  # the same WeSpeaker ResNet34 (VoxCeleb) model: GitHub release first, Hugging Face as a mirror
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/wespeaker_en_voxceleb_resnet34.onnx",
    "https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/wespeaker_en_voxceleb_resnet34.onnx",
]
SR = 16000
WIN, HOP = 2.0, 1.0          # seconds: a recording is judged in 2-second windows every second
MIN_ENROLL_SPEECH = 15.0     # seconds of clear speech needed for a voice print
THRESHOLD = 0.40             # cosine similarity: at or above — an employee, below — the patient
PAUSE = 0.35                 # seconds of silence between words that may mean another speaker
LONG_SPAN = 3.0              # a stretch of speech longer than this is checked for interruptions inside

SCHEMA = """CREATE TABLE IF NOT EXISTS voice_prints(
    user_id INTEGER PRIMARY KEY, emb TEXT, seconds REAL, quality REAL, updated_at TEXT);"""

_state = {"downloading": False, "progress": 0, "error": None}
_sess = {"obj": None}
_lock = threading.Lock()


# ------------------------------------------------------------------ model --
def model_path() -> Path:
    p = config.data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p / MODEL_FILE


def is_ready() -> bool:
    p = model_path()
    return p.exists() and p.stat().st_size > 20_000_000


def status() -> dict:
    return {"ready": is_ready(), "mb": MODEL_MB, "file": str(model_path()), **_state}


def download():
    if _state["downloading"]:
        return status()
    _state.update(downloading=True, progress=0, error=None)

    def run():
        import requests  # noqa: PLC0415
        target, part = model_path(), model_path().with_suffix(".part")
        err = None
        for url in MODEL_URLS:
            try:
                with requests.get(url, stream=True, timeout=30) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("Content-Length") or MODEL_MB * 1_000_000)
                    got = 0
                    with open(part, "wb") as f:
                        for chunk in r.iter_content(1 << 16):
                            f.write(chunk)
                            got += len(chunk)
                            _state["progress"] = min(99, int(got / total * 100))
                part.replace(target)
                if not is_ready():
                    raise RuntimeError("файл скачался не полностью")
                _state["progress"] = 100
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = e
                log.warning("voice model download from %s failed: %s", url, e)
        if err:
            _state["error"] = (f"Не удалось скачать модель голосов: {err}. Проверьте интернет или скопируйте файл "
                               f"{MODEL_FILE} с другого компьютера в папку {target.parent}.")
        _state["downloading"] = False
    threading.Thread(target=run, name="voice-download", daemon=True).start()
    return status()


def _session():
    if not is_ready():
        raise ValueError("Модель различения голосов не скачана. Настройки → «Голос и ИИ» → «Голоса сотрудников».")
    if _sess["obj"] is None:
        import onnxruntime as ort  # noqa: PLC0415
        _sess["obj"] = ort.InferenceSession(str(model_path()), providers=["CPUExecutionProvider"])
    return _sess["obj"]


# --------------------------------------------------------------- features --
_mel = {}


def _mel_banks(n_mels=80, n_fft=512, low=20.0, high=SR / 2):
    import numpy as np  # noqa: PLC0415
    key = (n_mels, n_fft)
    if key not in _mel:
        mel = lambda f: 1127.0 * np.log(1.0 + np.asarray(f) / 700.0)  # noqa: E731
        lo, hi = mel(low), mel(high)
        delta = (hi - lo) / (n_mels + 1)
        freqs = mel(np.arange(n_fft // 2) * SR / n_fft)
        banks = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
        for b in range(n_mels):
            left, center, right = lo + b * delta, lo + (b + 1) * delta, lo + (b + 2) * delta
            up = (freqs - left) / (center - left)
            down = (right - freqs) / (right - center)
            banks[b, :n_fft // 2] = np.clip(np.minimum(up, down), 0, None)
        _mel[key] = banks
    return _mel[key]


def fbank(wav):
    """Kaldi-style 80-dim log mel filterbank (25 ms frames, 10 ms step), mean-normalized — the input the
    WeSpeaker models were trained on."""
    import numpy as np  # noqa: PLC0415
    x = np.asarray(wav, dtype=np.float32) * 32768.0
    flen, fhop = 400, 160
    if len(x) < flen:
        x = np.pad(x, (0, flen - len(x)))
    n = 1 + (len(x) - flen) // fhop
    idx = np.arange(flen)[None, :] + fhop * np.arange(n)[:, None]
    fr = x[idx].astype(np.float64)
    fr -= fr.mean(axis=1, keepdims=True)
    fr[:, 1:] -= 0.97 * fr[:, :-1].copy()
    fr[:, 0] *= 1 - 0.97
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(flen) / (flen - 1))) ** 0.85
    spec = np.abs(np.fft.rfft(fr * win, n=512)) ** 2
    feats = np.log(np.maximum(spec @ _mel_banks().T.astype(np.float64), np.finfo(np.float32).eps))
    feats -= feats.mean(axis=0, keepdims=True)
    return feats.astype(np.float32)


def _norm(v):
    import numpy as np  # noqa: PLC0415
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def embed_many(chunks):
    """Equal-length pieces of sound → voice prints (one row each)."""
    import numpy as np  # noqa: PLC0415
    if not chunks:
        return np.zeros((0, 256), dtype=np.float32)
    s = _session()
    out = []
    for i in range(0, len(chunks), 16):
        batch = np.stack([fbank(c) for c in chunks[i:i + 16]])
        out.append(s.run(None, {"feats": batch})[0])
    return _norm(np.concatenate(out))


def decode(audio: bytes, suffix=".webm"):
    import os  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from faster_whisper import decode_audio  # noqa: PLC0415
    fd, path = tempfile.mkstemp(suffix=suffix if suffix.startswith(".") else "." + suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        return decode_audio(path, sampling_rate=SR)
    finally:
        try:
            os.remove(path)  # the sound is not kept
        except OSError:
            pass


def speech_only(wav):
    """Cut pauses out (the same voice detector Whisper uses)."""
    import numpy as np  # noqa: PLC0415
    from faster_whisper.vad import VadOptions, get_speech_timestamps  # noqa: PLC0415
    ts = get_speech_timestamps(wav, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))
    return np.concatenate([wav[t["start"]:t["end"]] for t in ts]) if ts else wav[:0]


def _voiced(piece):
    """Keep the 20 ms frames that are no more than 26 dB below the loudest one."""
    import numpy as np  # noqa: PLC0415
    n = len(piece) // 320
    if n == 0:
        return piece[:0]
    fr = piece[:n * 320].reshape(n, 320)
    rms = np.sqrt((fr ** 2).mean(axis=1))
    return fr[rms >= 0.05 * rms.max()].reshape(-1) if rms.max() > 0 else piece[:0]


def _windows(wav, start=0.0, end=None):
    import numpy as np  # noqa: PLC0415
    end = len(wav) / SR if end is None else end
    w, h = int(WIN * SR), int(HOP * SR)
    a, b = int(start * SR), int(end * SR)
    out = []
    if b - a < w:  # a short reply: repeat it up to 2 seconds rather than borrow the neighbours' voices
        piece = _voiced(wav[a:b])  # silence would drown a short reply's voice
        return [(start, np.resize(piece, w))] if len(piece) >= int(0.25 * SR) else []
    for s in range(a, max(a + 1, b - w + 1), h):
        piece = wav[s:s + w]
        if len(piece) == w:
            out.append((s / SR, piece))
    if out and int(out[-1][0] * SR) + w < b and b <= len(wav):  # the last words get a window of their own
        out.append(((b - w) / SR, wav[b - w:b]))
    return out


# ------------------------------------------------------------ enrollment --
def make_print(wav) -> dict:
    import numpy as np  # noqa: PLC0415
    sp = speech_only(wav)
    secs = len(sp) / SR
    if secs < MIN_ENROLL_SPEECH:
        raise ValueError(f"Слишком мало речи: {secs:.0f} с из {MIN_ENROLL_SPEECH:.0f}. Прочитайте текст целиком, "
                         "обычным голосом, ближе к микрофону.")
    embs = embed_many([p for _, p in _windows(sp)])
    center = _norm(embs.mean(axis=0))
    quality = float(np.mean(embs @ center))
    return {"emb": center, "seconds": round(secs, 1), "quality": round(quality, 3)}


def ensure_schema(db):
    db.script(SCHEMA)  # В1: under the lock — a bare executescript commits another thread's open transaction


def save_print(db, user_id: int, p: dict):
    ensure_schema(db)
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO voice_prints(user_id, emb, seconds, quality, updated_at) VALUES(?,?,?,?,?)",
                  (int(user_id), json.dumps([round(float(x), 5) for x in p["emb"]]), p["seconds"], p["quality"],
                   datetime.now().isoformat(timespec="seconds")))


def delete_print(db, user_id: int):
    ensure_schema(db)
    with db.tx() as c:
        c.execute("DELETE FROM voice_prints WHERE user_id=?", (int(user_id),))


def prints(db) -> dict:
    ensure_schema(db)
    return {r["user_id"]: dict(r) for r in db.q("SELECT * FROM voice_prints")}


# ------------------------------------------------------------- diarization --
def label_words(wav, words, voices, threshold=THRESHOLD):
    """words: [(start, end, text)] from Whisper; voices: [(label, emb)].
    Returns [(label, text)] — consecutive words of one speaker joined into one reply."""
    import numpy as np  # noqa: PLC0415
    if not words:
        return []
    if not voices:
        return [("", " ".join(w[2] for w in words).strip())]
    refs = _norm(np.stack([v for _, v in voices]))
    names = [lbl for lbl, _ in voices]

    def name_of(scores_row):
        k = int(scores_row.argmax())
        return names[k] if scores_row[k] >= threshold else "Пациент"

    # people change turns at pauses. The pauses are taken from the sound itself (the speech detector):
    # Whisper's word timings drift by a few tenths of a second, enough to glue a short «Нет» to the
    # doctor's next phrase. Each word goes to the stretch of speech its middle falls into.
    groups = _groups_by_sound(wav, words) or _groups_by_pause(words)
    judged = []
    for s, e, sp in groups:
        wins = _windows(wav, s, e)
        if not wins:
            labels = [None] * len(sp)  # too little sound to judge: decided by the nearest reply below
        else:
            embs = embed_many([p for _, p in wins])
            if e - s <= LONG_SPAN:   # a short stretch is one reply: judge it as a whole
                labels = [name_of(_norm(embs.mean(axis=0)) @ refs.T)] * len(sp)
            else:                    # a long one may hide an interruption: judge by the windows around each word
                sc = embs @ refs.T
                starts = np.array([t for t, _ in wins])
                labels = []
                for a, b, _ in sp:
                    mid = (a + b) / 2
                    near = (starts <= mid) & (starts + WIN >= mid)
                    row = sc[near].mean(axis=0) if near.any() else sc[int(np.abs(starts + WIN / 2 - mid).argmin())]
                    labels.append(name_of(row))
        judged.append((sp, labels))
    for i, (sp, labels) in enumerate(judged):
        if labels[0] is None:
            prev = (sp[0][0] - judged[i - 1][0][-1][1], judged[i - 1][1][-1]) if i and judged[i - 1][1][-1] else None
            nxt = (judged[i + 1][0][0][0] - sp[-1][1], judged[i + 1][1][0]) if i + 1 < len(judged) and judged[i + 1][1][0] else None
            near = min([x for x in (prev, nxt) if x], default=(0, "Пациент"))
            judged[i] = (sp, [near[1]] * len(sp))
    out = []
    for sp, labels in judged:
        for (_, _, text), lbl in zip(sp, labels):
            if out and out[-1][0] == lbl:
                out[-1][1].append(text)
            else:
                out.append((lbl, [text]))
    return [(lbl, " ".join(t.strip() for t in ts).strip()) for lbl, ts in out]


def speech_regions(wav):
    """Stretches of speech [(start, end)] in seconds, split at pauses of 0.15 s and longer."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps  # noqa: PLC0415
    ts = get_speech_timestamps(wav, VadOptions(min_silence_duration_ms=150, speech_pad_ms=30, min_speech_duration_ms=120))
    return [(t["start"] / SR, t["end"] / SR) for t in ts]


def _groups_by_sound(wav, words):
    regions = speech_regions(wav)
    if not regions:
        return []
    buckets = [[] for _ in regions]
    for w in words:
        mid = (w[0] + w[1]) / 2
        k = min(range(len(regions)), key=lambda i: 0 if regions[i][0] <= mid <= regions[i][1]
                else min(abs(mid - regions[i][0]), abs(mid - regions[i][1])))
        buckets[k].append(w)
    return [(r[0], r[1], b) for r, b in zip(regions, buckets) if b]


def _groups_by_pause(words):
    """Fallback when the speech detector finds nothing: pauses between Whisper's words."""
    spans = []
    for w in words:
        if spans and w[0] - spans[-1][-1][1] < PAUSE:
            spans[-1].append(w)
        else:
            spans.append([w])
    return [(sp[0][0], sp[-1][1], sp) for sp in spans]


def as_text(lines) -> str:
    return "\n".join(f"{lbl}: {t}" if lbl else t for lbl, t in lines if t)


def role_label(user: dict) -> str:
    """How a reply is signed. Whoever records a visit with their own voice and is not an assistant is
    treating the patient — a director who is also a dentist included — so it is «Врач»: the AI reads
    the conversation by these three words."""
    from auth import role_base  # noqa: PLC0415  (2.14: the director's own positions stand on a built-in role)
    return "Ассистент" if role_base(user.get("role")) == "assistant" else "Врач"


def candidates(db, doctor_id=None, current_user_id=None):
    """Voices to look for in a visit: the visit's doctor, every assistant, and whoever is recording."""
    import numpy as np  # noqa: PLC0415
    vp = prints(db)
    if not vp:
        return []
    out = []
    for u in db.q("SELECT id, name, role, doctor_id, status FROM users WHERE status='active'"):
        if u["id"] not in vp:
            continue
        from auth import role_base  # noqa: PLC0415
        base = role_base(u["role"])
        if (doctor_id and u["doctor_id"] == doctor_id) or base == "assistant" or u["id"] == current_user_id \
                or (not doctor_id and base == "doctor"):
            out.append((role_label(dict(u)), np.array(json.loads(vp[u["id"]]["emb"]), dtype=np.float32)))
    return out

