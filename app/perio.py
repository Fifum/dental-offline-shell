"""Periodontal chart: pocket depth, recession, bleeding on probing, mobility and furcation for each tooth.

Data of one chart: {"teeth": {"16": {"pd": [6], "rec": [6], "bop": [6], "mob": 0..3, "furc": 0..3, "missing": bool}}}.
Sites 0–2 are the buccal side, 3–5 the oral side, each left to right as the chart shows them.
Clinical attachment level (CAL) = pocket depth + recession.

Voice entry: «зуб шестнадцать три два четыре кровоточивость, нёбная два два три, подвижность один, следующий»
is turned into commands that the chart editor applies one by one.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime

from dictation import VALID, _words_to_teeth

SCHEMA = """
CREATE TABLE IF NOT EXISTS perio_charts(
    id TEXT PRIMARY KEY, patient_id TEXT, date TEXT, doctor_id TEXT, data TEXT, note TEXT,
    created_at TEXT, created_by TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_perio_patient ON perio_charts(patient_id);
"""
TEETH = [f"{q}{n}" for q in "1234" for n in "12345678"]  # permanent teeth only


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _int(v, lo, hi):
    if v in (None, ""):
        return None
    try:
        x = int(float(v))
    except (TypeError, ValueError):
        raise ValueError("В пародонтограмме должны быть числа") from None
    if not lo <= x <= hi:
        raise ValueError(f"Значение {x} вне допустимого: от {lo} до {hi}")
    return x


def clean_data(data) -> dict:
    """Validate and normalise a chart; unknown teeth and fields are dropped."""
    teeth = (data or {}).get("teeth") or {}
    out = {}
    for n, t in teeth.items():
        n = str(n)
        if n not in TEETH or not isinstance(t, dict):
            continue
        six = lambda k, lo, hi: [_int(x, lo, hi) for x in (list(t.get(k) or []) + [None] * 6)[:6]]  # noqa: E731
        row = {"pd": six("pd", 0, 15), "rec": six("rec", -5, 15),
               "bop": [bool(x) for x in (list(t.get("bop") or []) + [False] * 6)[:6]],
               "mob": _int(t.get("mob"), 0, 3), "furc": _int(t.get("furc"), 0, 3), "missing": bool(t.get("missing"))}
        if row["missing"] or any(x is not None for x in row["pd"] + row["rec"]) or any(row["bop"]) or row["mob"] or row["furc"]:
            out[n] = row
    return {"teeth": out}


def stats(data) -> dict:
    """Summary used in the list and on the chart: mean depth, deep pockets, bleeding."""
    pd, cal, bop, sites = [], [], 0, 0
    teeth = 0
    for n, t in (data or {}).get("teeth", {}).items():
        if t.get("missing"):
            continue
        has = False
        for i in range(6):
            p = (t.get("pd") or [None] * 6)[i]
            if p is None:
                continue
            has = True
            sites += 1
            pd.append(p)
            r = (t.get("rec") or [None] * 6)[i]
            cal.append(p + (r or 0))
            bop += 1 if (t.get("bop") or [False] * 6)[i] else 0
        teeth += has
    n = len(pd)
    return {"teeth": teeth, "sites": sites, "mean_pd": round(sum(pd) / n, 1) if n else None,
            "mean_cal": round(sum(cal) / n, 1) if n else None,
            "pd4": round(100 * sum(1 for p in pd if p >= 4) / n) if n else None,
            "pd6": sum(1 for p in pd if p >= 6), "bop": round(100 * bop / n) if n else None}


class Perio:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def list(self, patient_id) -> list[dict]:
        rows = self.db.q("""SELECT c.id, c.date, c.doctor_id, d.name AS doctor_name, c.data, c.note, c.created_by
                            FROM perio_charts c LEFT JOIN doctors d ON d.id=c.doctor_id
                            WHERE c.patient_id=? ORDER BY c.date DESC, c.created_at DESC""", (patient_id,))
        for r in rows:
            r["stats"] = stats(json.loads(r.pop("data") or "{}"))
        return rows

    def get(self, cid) -> dict:
        r = self.db.one("SELECT * FROM perio_charts WHERE id=?", (cid,))
        if not r:
            raise ValueError("Пародонтограмма не найдена")
        r["data"] = json.loads(r["data"] or "{}")
        r["stats"] = stats(r["data"])
        return r

    def save(self, f: dict, who="") -> dict:
        pid = str(f.get("patient_id") or "")
        if not pid or not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (pid,)):
            raise ValueError("Пациент не найден")
        d = str(f.get("date") or date.today().isoformat())[:10]
        try:
            date.fromisoformat(d)
        except ValueError:
            raise ValueError("Дата указана неверно") from None
        data = clean_data(f.get("data"))
        if not data["teeth"]:
            raise ValueError("Пародонтограмма пустая — заполните хотя бы один зуб")
        vals = (pid, d, f.get("doctor_id") or None, json.dumps(data, ensure_ascii=False), str(f.get("note") or "")[:1000])
        with self.db.tx() as c:
            cid = f.get("id")
            if cid:
                if not c.execute("SELECT 1 FROM perio_charts WHERE id=?", (cid,)).fetchone():
                    raise ValueError("Пародонтограмма не найдена")
                c.execute("UPDATE perio_charts SET patient_id=?, date=?, doctor_id=?, data=?, note=?, updated_at=? WHERE id=?",
                          (*vals, _now(), cid))
            else:
                cid = "PC-" + uuid.uuid4().hex[:10]
                c.execute("""INSERT INTO perio_charts(id, patient_id, date, doctor_id, data, note, created_at, created_by, updated_at)
                             VALUES(?,?,?,?,?,?,?,?,?)""", (cid, *vals, _now(), who or "", _now()))
        return self.get(cid)

    def delete(self, cid) -> bool:
        with self.db.tx() as c:
            if not c.execute("DELETE FROM perio_charts WHERE id=?", (cid,)).rowcount:
                raise ValueError("Пародонтограмма не найдена")
        return True


# ------------------------------------------------------------- voice entry --
_NUM = {"ноль": 0, "нуль": 0, "один": 1, "одна": 1, "раз": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
        "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10}
PERIO_PROMPT = ("Пародонтограмма. Зуб шестнадцать: три два четыре, кровоточивость. Нёбная сторона: два два три. "
                "Рецессия один ноль один. Подвижность один. Фуркация два. Зуб отсутствует. Следующий. Язычная, щёчная.")


def parse_voice(text: str) -> list[dict]:
    """Spoken chart → commands: tooth, val, mode (pd/rec), side (b/l), bop, mob, furc, missing, next."""
    t = _words_to_teeth(str(text or "").lower().replace("ё", "е"))
    tokens = re.findall(r"[а-яa-z]+|\d+", t)
    out, i = [], 0

    def number_at(j):
        if j >= len(tokens):
            return None
        w = tokens[j]
        if w.isdigit():
            return int(w)
        return _NUM.get(w)

    while i < len(tokens):
        w = tokens[i]
        nxt = number_at(i + 1)
        if w.startswith("зуб") and i + 1 < len(tokens) and tokens[i + 1].isdigit() and tokens[i + 1] in VALID:
            out.append({"t": "tooth", "v": tokens[i + 1]})
            i += 2
            continue
        if w.startswith("подвижн") and nxt is not None:
            out.append({"t": "mob", "v": min(3, nxt)})
            i += 2
            continue
        if w.startswith("фуркац") and nxt is not None:
            out.append({"t": "furc", "v": min(3, nxt)})
            i += 2
            continue
        if w.startswith("рецесс"):
            out.append({"t": "mode", "v": "rec"})
        elif w.startswith(("карман", "глубин", "зондир")):
            out.append({"t": "mode", "v": "pd"})
        elif w.startswith(("кров", "bop")):
            out.append({"t": "bop"})
        elif w.startswith(("отсутств", "удален")):
            out.append({"t": "missing"})
        elif w.startswith(("следующ", "дальше")):
            out.append({"t": "next"})
        elif w.startswith(("щечн", "вестибул", "губн", "наружн")):
            out.append({"t": "side", "v": "b"})
        elif w.startswith(("небн", "язычн", "оральн", "внутрен")):
            out.append({"t": "side", "v": "l"})
        elif w.isdigit():
            n = int(w)
            if n <= 15:
                out.append({"t": "val", "v": n})
            else:  # «324» or «32» said without pauses: separate digits
                out += [{"t": "val", "v": int(ch)} for ch in w]
        elif w in _NUM:
            out.append({"t": "val", "v": _NUM[w]})
        i += 1
    return out
