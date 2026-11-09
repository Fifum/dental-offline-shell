"""A training set for fine-tuning (LoRA) the clinic's model later — anonymous, from the clinic's own records.

    python tools\\ai_dataset.py <clinic.db> <out.jsonl> [--limit 2000]

Every line is a chat in the usual format {"messages": [system, user, assistant]} for two tasks of the program:
  1) record → memo for the patient (the answer is the program's rule draft: a doctor should read and correct the
     file before training — the model learns what the doctors approve);
  2) record text → record fields JSON (the answer is the record as the doctor saved it).
No names, phones, birth dates or addresses: the record text goes through the same anonymization as before a
request to an AI service, and the patient's name is replaced in every field. Keep the file inside the clinic."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=2000)
    a = ap.parse_args()
    import ai  # noqa: PLC0415
    import ai_docs  # noqa: PLC0415
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute("""SELECT r.id, r.date, r.data, p.name FROM records r LEFT JOIN patients p ON p.id=r.patient_id
                          ORDER BY r.date DESC LIMIT ?""", (a.limit,)).fetchall()
    n = 0
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            data = json.loads(r["data"] or "{}")
            names = [r["name"]] if r["name"] else []
            clean = {k: ai.anonymize(v, names) if isinstance(v, str) else v for k, v in data.items()}
            rec = {"date": r["date"], "data": clean}
            src = ai_docs.record_text(rec)
            if not src.strip():
                continue
            memo = ai_docs._rules("recommendations", rec)
            f.write(json.dumps({"messages": [{"role": "system", "content": ai.BASE + "\n" + ai_docs.TASKS["recommendations"]},
                                             {"role": "user", "content": src}, {"role": "assistant", "content": memo}],
                                "task": "recommendations", "check": "врач проверяет ответ перед обучением"}, ensure_ascii=False) + "\n")
            fields = {k: clean.get(k) or "" for k in ("complaints", "anamnesis", "objective", "treatment", "recommendations", "next_visit")}
            fields["diagnoses"] = [{"code": x.get("code", ""), "tooth": x.get("tooth", "")} for x in clean.get("diagnoses") or []]
            fields["teeth"] = clean.get("teeth") or {}
            text = " ".join(f"{t}: {fields[k]}" for k, t in (("complaints", "Жалобы"), ("objective", "Объективно"),
                                                              ("treatment", "Лечение"), ("recommendations", "Рекомендации")) if fields[k])
            if text:
                f.write(json.dumps({"messages": [{"role": "system", "content": ai.prompt()}, {"role": "user", "content": text},
                                                 {"role": "assistant", "content": json.dumps(fields, ensure_ascii=False)}],
                                    "task": "dictation"}, ensure_ascii=False) + "\n")
            n += 1
    print(f"Записей медкарты: {n}, примеров: в файле {a.out}")


if __name__ == "__main__":
    main()
