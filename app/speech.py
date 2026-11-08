"""Speech to text on this computer (Whisper via faster-whisper). No internet needed once the model
is downloaded; the sound never leaves the computer.

Models live in %LOCALAPPDATA%/<app>/models/whisper-<size>. A model downloaded on one laptop can be
copied to another (same folder) with a flash drive.
"""
from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from pathlib import Path

import config

log = logging.getLogger("speech")

SIZES = {  # size: (title, approx MB)
    "base": ("Быстрая (точность ниже)", 145),
    "small": ("Рекомендуется", 480),
    "medium": ("Самая точная, медленнее, нужен мощный ноутбук", 1500),
}
DEFAULT_SIZE = "small"
PROMPT = ("Протокол стоматологического приёма. Жалобы. Анамнез. Объективно. Диагноз: кариес дентина, кариес эмали, "
          "пульпит, периодонтит, гингивит, пародонтит. Зуб 36, зуб 47. Лечение: инфильтрационная анестезия, "
          "проводниковая анестезия, ультракаин, препарирование, пломба из светоотверждаемого композита, эндодонтическое "
          "лечение, пломбирование каналов, коронка, имплант. Рекомендации.")
VISIT_PROMPT = ("Приём у стоматолога. — На что жалуетесь? — Болит зуб от холодного и сладкого. Кариес дентина, зуб 46: на жевательной "
                "поверхности кариозная полость, зондирование болезненно по эмалево-дентинной границе, перкуссия безболезненная. "
                "Инфильтрационная анестезия, ультракаин, артикаин, препарирование, хлоргексидин, коффердам, адгезив, пломба из "
                "светоотверждаемого композита, пульпит, периодонтит, эндодонтическое лечение, слюноотсос, сомкните зубы.")


def _prompt(core: str, extra: str) -> str:
    """Whisper keeps only the LAST ~223 tokens of a prompt: the clinic's own phrases go first, the dental
    terms last, so the terms are never the part that is cut off."""
    return (extra.strip()[-300:] + " " + core).strip()

_state = {"downloading": None, "progress": 0, "error": None}
_model = {"size": None, "obj": None}
_lock = threading.Lock()


def engine_available() -> bool:
    try:
        import faster_whisper  # noqa: F401, PLC0415
        return True
    except Exception:  # noqa: BLE001
        return False


def models_dir() -> Path:
    p = config.data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def model_path(size) -> Path:
    return models_dir() / f"whisper-{size}"


def is_ready(size) -> bool:
    p = model_path(size)
    return (p / "model.bin").exists() and (p / "config.json").exists()


def current_size() -> str:
    s = config.load_settings().get("speech_size") or DEFAULT_SIZE
    return s if s in SIZES else DEFAULT_SIZE


def status() -> dict:
    return {"engine": engine_available(), "size": current_size(), "folder": str(models_dir()),
            "models": {k: {"title": t, "mb": mb, "ready": is_ready(k)} for k, (t, mb) in SIZES.items()},
            "ready": is_ready(current_size()), **_state}


def _dir_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6 if p.exists() else 0


def download(size: str):
    if size not in SIZES:
        raise ValueError("Неизвестная модель")
    if not engine_available():
        raise ValueError("Модуль распознавания речи не установлен в этой сборке программы")
    if _state["downloading"]:
        return status()
    _state.update(downloading=size, progress=0, error=None)

    def run():
        from faster_whisper import download_model  # noqa: PLC0415
        target = model_path(size)
        done = threading.Event()

        def watch():
            while not done.is_set():
                _state["progress"] = min(99, int(_dir_mb(target) / SIZES[size][1] * 100))
                time.sleep(1)
        threading.Thread(target=watch, daemon=True).start()
        try:
            download_model(size, output_dir=str(target))
            if not is_ready(size):
                raise RuntimeError("модель скачалась не полностью")
            config.save_settings({"speech_size": size})
            _state["progress"] = 100
        except Exception as e:  # noqa: BLE001
            log.warning("model download failed: %s", e)
            _state["error"] = f"Не удалось скачать модель: {e}. Проверьте интернет или скопируйте папку модели с другого компьютера."
        finally:
            done.set()
            _state["downloading"] = None
    threading.Thread(target=run, name="speech-download", daemon=True).start()
    return status()


def use_size(size: str):
    if size not in SIZES:
        raise ValueError("Неизвестная модель")
    if not is_ready(size):
        raise ValueError("Сначала скачайте эту модель")
    config.save_settings({"speech_size": size})
    return status()


def _get_model():
    size = current_size()
    if not is_ready(size):
        ready = [k for k in SIZES if is_ready(k)]
        if not ready:
            raise ValueError("Модель распознавания речи не скачана. Настройки → «Голос и ИИ» → «Скачать модель».")
        size = ready[0]
    if _model["size"] != size:
        from faster_whisper import WhisperModel  # noqa: PLC0415
        threads = max(1, (os.cpu_count() or 2) - 1)
        _model.update(size=size, obj=WhisperModel(str(model_path(size)), device="cpu", compute_type="int8", cpu_threads=threads))
    return _model["obj"]


def transcribe(audio: bytes, suffix=".webm", extra_prompt="", words=False) -> dict:
    """Bytes of a recording (webm/ogg/wav/mp3) → {'text', 'duration', 'seconds'}; with words=True also
    'words' [(start, end, word)] and 'wav' (the decoded sound, kept in memory only)."""
    if not audio:
        raise ValueError("Пустая запись")
    if not engine_available():
        raise ValueError("Модуль распознавания речи не установлен в этой сборке программы")
    t0 = time.time()
    fd, path = tempfile.mkstemp(suffix=suffix if suffix.startswith(".") else "." + suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        with _lock:  # one recognition at a time: the CPU is the limit
            model = _get_model()
            if not words:
                segments, info = model.transcribe(path, language="ru", beam_size=5, vad_filter=True,
                                                  initial_prompt=_prompt(PROMPT, extra_prompt))
                text = " ".join(s.text.strip() for s in segments).strip()
                return {"text": text, "duration": round(info.duration, 1), "seconds": round(time.time() - t0, 1), "model": _model["size"]}
            # visit recording: word timings too, and the decoded sound for telling the voices apart
            from faster_whisper import decode_audio  # noqa: PLC0415
            wav = decode_audio(path, sampling_rate=16000)
            segments, info = model.transcribe(wav, language="ru", beam_size=5, vad_filter=True, word_timestamps=True,
                                              condition_on_previous_text=False,
                                              initial_prompt=_prompt(VISIT_PROMPT, extra_prompt))
            segs = list(segments)
            return {"text": " ".join(s.text.strip() for s in segs).strip(), "duration": round(info.duration, 1),
                    "words": [(w.start, w.end, w.word) for s in segs for w in (s.words or [])], "wav": wav,
                    "seconds": round(time.time() - t0, 1), "model": _model["size"]}
    finally:
        try:
            os.remove(path)  # the sound is not kept
        except OSError:
            pass
