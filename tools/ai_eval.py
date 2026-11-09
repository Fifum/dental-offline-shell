"""Compare AI models on the program's test questions (developer's computer).

    python tools\\ai_eval.py gemma3:4b dental-desk qwen2.5:3b          # local models (the program's Ollama)
    python tools\\ai_eval.py --provider openai --url http://127.0.0.1:11434/v1 qwen3:4b
    python tools\\ai_eval.py --report report.md gemma3:4b

The same test questions as Settings → «Голос и ИИ» → «Проверить качество» (app/ai_eval.py): dictation into the
record, a memo, an explanation, a plan option, translation, the assistant's questions, a general question.
Invented data only. The program's settings are not changed."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+")
    ap.add_argument("--provider", default="local")
    ap.add_argument("--url", default="")
    ap.add_argument("--report", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    import ai_eval  # noqa: PLC0415
    runs = []
    for m in a.models:
        over = {"provider": a.provider, "model": m, **({"base_url": a.url} if a.url else {})}
        r = ai_eval.run(over, progress=lambda p: print(f"\r{m}: {p}%", end="", flush=True))
        print(f"\r{m}: итог {r['score']}, точность {r['accuracy']} %, русский {r['russian']} %, ответ {r['seconds']} с, "
              f"{r['tok_s'] or '—'} ток/с, ошибок {r['errors']}")
        runs.append(r)
    if a.json:
        Path(a.json).write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.report:
        Path(a.report).write_text(report(runs), encoding="utf-8")


def report(runs) -> str:
    out = ["| Модель | Итог | Точность | Русский | Ответ, с | Токенов/с |", "|---|---|---|---|---|---|"]
    out += [f"| {r['model']} | {r['score']} | {r['accuracy']} % | {r['russian']} % | {r['seconds']} | {r['tok_s'] or '—'} |" for r in runs]
    out += ["", "| Задача | " + " | ".join(r["model"] for r in runs) + " |", "|---|" + "---|" * len(runs)]
    for i, c in enumerate(runs[0]["cases"]):
        out.append(f"| {c['title']} | " + " | ".join(f"{round(r['cases'][i]['accuracy'] * 100)} % · {r['cases'][i]['seconds']} с" for r in runs) + " |")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
