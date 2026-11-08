"""Moving the patient base in: Excel (.xlsx) or CSV exported from IDENT, Dentist Plus or any other table.

Columns are recognised by their titles (Фамилия / Имя / Отчество or ФИО, Телефон, Дата рождения, Пол, № карты,
Адрес, E-mail, Комментарий, Источник); the person can change any match before importing. Patients already in the
program (same phone, or same name and birth date) are skipped, so the same file can be imported twice safely.
Imported patients are ordinary patients created in this program (they go to Dentist Plus and to the cloud as usual).

IDENT keeps its base in Firebird; its «Пациенты» list is exported with the table's «Экспорт в Excel» button.
Old .xls files have to be saved as .xlsx (or CSV) in Excel first.
"""
from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

from normalize import person_name

MAX_BYTES = 30 * 1024 * 1024
MAX_ROWS = 100_000

FIELDS = [
    ("fio", "ФИО целиком"), ("lname", "Фамилия"), ("fname", "Имя"), ("mname", "Отчество"), ("phone", "Телефон"),
    ("phone2", "Второй телефон"), ("birth", "Дата рождения"), ("gender", "Пол"), ("card", "Номер карты"),
    ("email", "E-mail"), ("address", "Адрес"), ("comment", "Комментарий"), ("source", "Откуда узнал"),
]
FIELD_TITLES = dict(FIELDS)

SYNONYMS = {
    "fio": ["фио", "ф и о", "пациент", "фамилия имя отчество", "имя пациента", "клиент", "фио пациента", "полное имя"],
    "lname": ["фамилия"],
    "fname": ["имя"],
    "mname": ["отчество"],
    "phone": ["телефон", "мобильный", "мобильный телефон", "моб телефон", "сотовый", "сотовый телефон",
              "контактный телефон", "телефон мобильный", "phone", "тел"],
    "phone2": ["доп телефон", "дополнительный телефон", "домашний телефон", "телефон 2", "второй телефон", "рабочий телефон"],
    "birth": ["дата рождения", "д р", "др", "день рождения", "рожден", "birthday", "дата рожд"],
    "gender": ["пол"],
    "card": ["номер карты", "карта", "медкарта", "номер медкарты", "мк", "n карты", "номер мк", "амбулаторная карта"],
    "email": ["email", "e mail", "эл почта", "почта", "электронная почта"],
    "address": ["адрес", "адрес проживания", "адрес регистрации"],
    "comment": ["комментарий", "примечание", "примечания", "заметки", "заметка"],
    "source": ["источник", "откуда узнал", "рекламный источник", "откуда узнали", "канал привлечения"],
}


def _norm(s) -> str:
    s = str(s or "").lower().replace("ё", "е").replace("№", "n")
    return re.sub(r"\s+", " ", re.sub(r"[^a-zа-я0-9]+", " ", s)).strip()


def guess_field(title) -> str:
    t = _norm(title)
    if not t:
        return ""
    for field, names in SYNONYMS.items():
        if t in names:
            return field
    for field, names in SYNONYMS.items():  # «Телефон (мобильный)», «Дата рождения пациента»…
        if any(len(n) > 3 and n in t for n in names):
            return field
    return ""


# ------------------------------------------------------------------ reading --
def _xlsx_rows(data: bytes):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        if not sheets:
            raise ValueError("В книге Excel нет листов")
        root = ET.fromstring(z.read(sheets[0]))
    rows = []
    for r in root.iter(f"{{{ns['m']}}}row"):
        cells = {}
        for c in r.findall("m:c", ns):
            ref = c.get("r", "")
            col = 0
            for ch in re.match(r"[A-Z]+", ref).group(0) if re.match(r"[A-Z]+", ref) else "":
                col = col * 26 + ord(ch) - 64
            col = col - 1 if col else len(cells)
            t, v = c.get("t"), c.find("m:v", ns)
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            else:
                val = v.text if v is not None else ""
            cells[col] = val or ""
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        if len(rows) > MAX_ROWS:
            break
    return rows


def _csv_rows(data: bytes):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Не удалось прочитать файл: неизвестная кодировка")
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=";,\t")
    except csv.Error:
        sep = ";" if text[:2000].count(";") > text[:2000].count(",") else ","

        class dialect(csv.excel):  # noqa: N801
            delimiter = sep
    return [r for r in csv.reader(io.StringIO(text), dialect)][: MAX_ROWS + 1]


def read_table(name: str, data: bytes):
    if len(data) > MAX_BYTES:
        raise ValueError("Файл слишком большой (больше 30 МБ)")
    low = str(name or "").lower()
    if low.endswith(".xls"):
        raise ValueError("Старый формат .xls не читается. Откройте файл в Excel и сохраните как «Книга Excel (.xlsx)» или CSV.")
    rows = _xlsx_rows(data) if data[:2] == b"PK" else _csv_rows(data)
    rows = [[str(c).strip() for c in r] for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        raise ValueError("В файле нет строк")
    # the header is the first row (of the first ten) where at least two columns are recognised
    for i, r in enumerate(rows[:10]):
        if sum(1 for c in r if guess_field(c)) >= 2:
            return rows[i], rows[i + 1:]
    return rows[0], rows[1:]


# ------------------------------------------------------------------ values --
def parse_birth(v) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    if re.fullmatch(r"\d{4,5}(\.0+)?", s) and 5000 < float(s) < 80000:  # Excel date number
        return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
    s = s.split(" ")[0]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y", "%Y.%m.%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            if d.year > date.today().year:
                d = d.replace(year=d.year - 100)
            return d.isoformat()
        except ValueError:
            continue
    return ""


def norm_phone(v) -> str:
    s = str(v or "").strip()
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    d = re.sub(r"\D", "", s)
    if len(d) == 11 and d[0] == "8":
        return "+7" + d[1:]
    if len(d) == 10 and d[0] == "9":
        return "+7" + d
    if len(d) >= 11:
        return "+" + d
    return s


def _gender(v) -> str:
    s = _norm(v)
    if s.startswith(("м", "m")):
        return "male"
    if s.startswith(("ж", "f", "w")):
        return "female"
    return ""


def map_row(row, mapping):
    """mapping: {column index: field}. Returns the patient fields or None for an empty row."""
    g = {}
    for i, field in mapping.items():
        if field and int(i) < len(row) and row[int(i)].strip():
            g[field] = row[int(i)].strip() if field not in g else g[field] + " " + row[int(i)].strip()
    if g.get("fio") and not g.get("lname"):
        parts = g["fio"].split()
        g["lname"] = parts[0] if parts else ""
        g["fname"] = parts[1] if len(parts) > 1 else ""
        g["mname"] = " ".join(parts[2:])
    if not (g.get("lname") or g.get("fname")):
        return None
    comment = g.get("comment", "")
    if g.get("phone2"):
        comment = (comment + "; " if comment else "") + "Доп. телефон: " + norm_phone(g["phone2"])
    if g.get("email"):
        comment = (comment + "; " if comment else "") + "E-mail: " + g["email"]
    return {"lname": g.get("lname", ""), "fname": g.get("fname", ""), "mname": g.get("mname", ""),
            "phone": norm_phone(g.get("phone", "")), "birth_date": parse_birth(g.get("birth", "")),
            "gender": _gender(g.get("gender", "")), "address": g.get("address", ""), "comment": comment,
            "card_number": g.get("card", ""), "email": g.get("email", ""), "source": g.get("source", "")}


def _digits(p) -> str:
    return re.sub(r"\D", "", str(p or ""))[-10:]


class Importer:
    def __init__(self, db, local):
        self.db, self.local = db, local

    def _known(self):
        phones, names = set(), set()
        for r in self.db.q("SELECT name, phone, birth FROM patients"):
            d = _digits(r["phone"])
            if len(d) >= 10:
                phones.add(d)
            names.add((str(r["name"] or "").lower().replace("ё", "е").strip(), r["birth"] or ""))
        return phones, names

    @staticmethod
    def _dup(p, phones, names):
        d = _digits(p["phone"])
        if len(d) >= 10 and d in phones:
            return True
        name = person_name({"lname": p["lname"], "fname": p["fname"], "mname": p["mname"]}).lower().replace("ё", "е").strip()
        return bool(p["birth_date"]) and (name, p["birth_date"]) in names

    def preview(self, name, data: bytes, mapping=None):
        header, rows = read_table(name, data)
        if mapping is None:
            mapping, used = {}, set()
            for i, h in enumerate(header):
                f = guess_field(h)
                if f and f not in used:
                    mapping[i] = f
                    used.add(f)
        mapping = {int(k): v for k, v in mapping.items() if v in FIELD_TITLES}
        heads = " ".join(_norm(h) for h in header)
        kind = ("IDENT" if "мобильный телефон" in heads and "фамилия" in heads else
                "Dentist Plus" if "фио" in heads and "телефон" in heads else "таблица")
        phones, names = self._known()
        ok = dup = empty = 0
        sample = []
        for r in rows:
            p = map_row(r, mapping)
            if not p:
                empty += 1
                continue
            is_dup = self._dup(p, phones, names)
            dup += is_dup
            ok += not is_dup
            if len(sample) < 12:
                sample.append({**p, "name": person_name(p), "dup": is_dup})
        problems = []
        if not any(f in mapping.values() for f in ("fio", "lname", "fname")):
            problems.append("Не найдена колонка с ФИО или фамилией — укажите её вручную")
        if "phone" not in mapping.values():
            problems.append("Не найдена колонка с телефоном — пациенты загрузятся без телефона")
        return {"kind": kind, "columns": [{"index": i, "title": h, "field": mapping.get(i, "")} for i, h in enumerate(header)],
                "fields": [{"key": k, "title": t} for k, t in FIELDS], "total": len(rows), "new": ok, "duplicates": dup,
                "empty": empty, "sample": sample, "problems": problems}

    def run(self, name, data: bytes, mapping):
        header, rows = read_table(name, data)
        mapping = {int(k): v for k, v in (mapping or {}).items() if v in FIELD_TITLES}
        if not any(f in mapping.values() for f in ("fio", "lname", "fname")):
            raise ValueError("Укажите колонку с ФИО или фамилией")
        phones, names = self._known()
        added = dup = empty = 0
        for r in rows:
            p = map_row(r, mapping)
            if not p:
                empty += 1
                continue
            if self._dup(p, phones, names):
                dup += 1
                continue
            res = self.local.create_patient(p)
            extra = {k: p[k] for k in ("card_number", "email") if p.get(k)}
            if extra:
                import json
                row = self.db.one("SELECT detail FROM patients WHERE id=?", (res["id"],))
                raw = json.loads(row["detail"] or "{}")
                raw.update(extra)
                raw["imported_from"] = name
                with self.db.tx() as c:
                    c.execute("UPDATE patients SET detail=?, data=?, search=search || ' ' || ? WHERE id=?",
                              (json.dumps(raw, ensure_ascii=False), json.dumps(raw, ensure_ascii=False),
                               str(p.get("card_number") or "").lower(), res["id"]))
            if p.get("source"):
                with self.db.tx() as c:
                    c.execute("INSERT OR REPLACE INTO patient_marketing(patient_id, source, no_calls, updated_at) VALUES(?,?,0,?)",
                              (res["id"], p["source"][:80], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            d = _digits(p["phone"])
            if len(d) >= 10:
                phones.add(d)
            names.add((res["name"].lower().replace("ё", "е").strip(), p["birth_date"]))
            added += 1
        return {"added": added, "duplicates": dup, "empty": empty, "total": len(rows)}
