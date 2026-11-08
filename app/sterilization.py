"""Sterilization journal: every autoclave / dry-heat cycle with its mode, indicators and what was loaded.

Inspections ask for this journal on paper; the program keeps it and prints it for any period. A cycle
with a failed indicator is marked «брак»: its load must be sterilized again.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS steril_cycles(
    id TEXT PRIMARY KEY, at TEXT, sterilizer TEXT, cycle_no INTEGER, method TEXT, program TEXT,
    temp REAL, pressure REAL, minutes INTEGER, chem TEXT, bio TEXT, load TEXT, packs INTEGER,
    result TEXT, operator TEXT, note TEXT, created_at TEXT, created_by TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_steril_at ON steril_cycles(at);
"""
METHODS = ["Паровой (автоклав)", "Воздушный (сухожар)", "Химический", "Газовый"]
PROGRAMS = ["134 °C, 0,21 МПа, 5 мин", "132 °C, 0,20 МПа, 20 мин", "121 °C, 0,11 МПа, 20 мин", "120 °C, 0,11 МПа, 45 мин",
            "180 °C, 60 мин", "160 °C, 150 мин"]
INDICATOR = {"ok": "соответствует", "fail": "не соответствует", "": "не ставился"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(v, what, lo, hi, integer=False):
    if v in (None, ""):
        return None
    try:
        x = float(str(v).replace(",", "."))
    except ValueError:
        raise ValueError(f"{what}: укажите число") from None
    if not lo <= x <= hi:
        raise ValueError(f"{what}: допустимо от {lo:g} до {hi:g}")
    return int(x) if integer else x


class Sterilization:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def options(self) -> dict:
        eq = []
        try:
            # SQLite lower() does not fold Cyrillic, so the name filter is done here
            eq = [r["name"] for r in self.db.q("SELECT name FROM equipment WHERE status!='written_off' ORDER BY name")
                  if any(w in (r["name"] or "").lower() for w in ("автоклав", "стерилиз", "сухожар"))]
        except Exception:  # noqa: BLE001  (no equipment table yet)
            pass
        used = [r["sterilizer"] for r in self.db.q(
            "SELECT DISTINCT sterilizer FROM steril_cycles WHERE sterilizer!='' ORDER BY sterilizer")]
        return {"methods": METHODS, "programs": PROGRAMS, "indicator": INDICATOR,
                "sterilizers": list(dict.fromkeys(eq + used))}

    def next_no(self, sterilizer: str, year: int | None = None) -> int:
        year = year or date.today().year
        r = self.db.one("SELECT MAX(cycle_no) AS n FROM steril_cycles WHERE sterilizer=? AND substr(at,1,4)=?",
                        (sterilizer, str(year)))
        return int(r["n"] or 0) + 1

    def list(self, date_from=None, date_to=None, sterilizer=None) -> dict:
        a = str(date_from or date.today().replace(day=1).isoformat())[:10]
        b = str(date_to or date.today().isoformat())[:10]
        sql, args = "SELECT * FROM steril_cycles WHERE substr(at,1,10) BETWEEN ? AND ?", [a, b]
        if sterilizer:
            sql += " AND sterilizer=?"
            args.append(sterilizer)
        rows = self.db.q(sql + " ORDER BY at DESC, cycle_no DESC", args)
        for r in rows:
            r["chem_text"], r["bio_text"] = INDICATOR.get(r["chem"] or "", r["chem"]), INDICATOR.get(r["bio"] or "", r["bio"])
        return {"from": a, "to": b, "rows": rows, "count": len(rows), "failed": sum(1 for r in rows if r["result"] == "брак"),
                "packs": sum(int(r["packs"] or 0) for r in rows)}

    def save(self, f: dict, who="") -> dict:
        sterilizer = str(f.get("sterilizer") or "").strip()[:120]
        if not sterilizer:
            raise ValueError("Укажите стерилизатор (например, «Автоклав № 1»)")
        at = str(f.get("at") or "").strip().replace("T", " ")[:16] or _now()[:16]
        try:
            datetime.strptime(at, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError("Дата и время указаны неверно") from None
        chem, bio = str(f.get("chem") or ""), str(f.get("bio") or "")
        if chem not in INDICATOR or bio not in INDICATOR:
            raise ValueError("Неизвестный результат индикатора")
        if not chem and not bio:
            raise ValueError("Отметьте результат химического индикатора")
        vals = {
            "at": at, "sterilizer": sterilizer,
            "method": str(f.get("method") or METHODS[0])[:60], "program": str(f.get("program") or "")[:120],
            "temp": _num(f.get("temp"), "Температура", 20, 300), "pressure": _num(f.get("pressure"), "Давление", 0, 1),
            "minutes": _num(f.get("minutes"), "Время", 1, 600, True), "chem": chem, "bio": bio,
            "load": str(f.get("load") or "").strip()[:500], "packs": _num(f.get("packs"), "Упаковок", 0, 1000, True),
            "result": "брак" if "fail" in (chem, bio) else "годно",
            "operator": str(f.get("operator") or who or "").strip()[:120], "note": str(f.get("note") or "").strip()[:500],
        }
        cid = f.get("id")
        with self.db.tx() as c:
            if cid:
                if not c.execute("SELECT 1 FROM steril_cycles WHERE id=?", (cid,)).fetchone():
                    raise ValueError("Цикл не найден")
                c.execute(f"UPDATE steril_cycles SET {', '.join(k + '=?' for k in vals)}, updated_at=? WHERE id=?",
                          (*vals.values(), _now(), cid))
            else:
                cid = "SC-" + uuid.uuid4().hex[:10]
                no = _num(f.get("cycle_no"), "Номер цикла", 1, 100000, True) or None
                vals["cycle_no"] = no
                c.execute(f"""INSERT INTO steril_cycles(id, {', '.join(vals)}, created_at, created_by, updated_at)
                              VALUES(?, {', '.join('?' * len(vals))}, ?, ?, ?)""", (cid, *vals.values(), _now(), who or "", _now()))
        if not f.get("id") and not vals.get("cycle_no"):
            with self.db.tx() as c:  # numbering per sterilizer and year
                n = self.next_no(sterilizer, int(at[:4]))
                c.execute("UPDATE steril_cycles SET cycle_no=? WHERE id=?", (n, cid))
        return self.db.one("SELECT * FROM steril_cycles WHERE id=?", (cid,))

    def delete(self, cid: str) -> bool:
        with self.db.tx() as c:
            if not c.execute("DELETE FROM steril_cycles WHERE id=?", (cid,)).rowcount:
                raise ValueError("Цикл не найден")
        return True
