"""Справка об оплате медицинских услуг для представления в налоговый орган (налоговый вычет).

The sums come from the payments made in this program during the year; the clinic can correct them
(payments taken in Dentist Plus are not here). Code 1 — ordinary medical services, code 2 — expensive
treatment from the government list. Every certificate is kept in a register with its own number per year
and is saved as a document in the patient's card.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import date, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS tax_certs(
    id TEXT PRIMARY KEY, number INTEGER, year INTEGER, patient_id TEXT, patient_fio TEXT, patient_inn TEXT, patient_birth TEXT,
    patient_doc TEXT, payer_same INTEGER, payer_fio TEXT, payer_inn TEXT, payer_birth TEXT, payer_doc TEXT,
    sum1 REAL, sum2 REAL, document_id TEXT, issued_at TEXT, issued_by TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS ix_taxcert_year ON tax_certs(year);
"""


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _inn(v, what):
    v = re.sub(r"\D", "", str(v or ""))
    if v and len(v) != 12:
        raise ValueError(f"ИНН {what} — 12 цифр")
    return v


def _birth(v, what):
    v = str(v or "").strip()[:10]
    if not v:
        return ""
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"Дата рождения {what} указана неверно") from None
    return v


def _money(v):
    try:
        x = round(float(str(v or 0).replace(",", ".").replace(" ", "")), 2)
    except ValueError:
        raise ValueError("Сумма указана неверно") from None
    if x < 0:
        raise ValueError("Сумма не может быть отрицательной")
    return x


def rub(x) -> str:
    rub_, kop = divmod(round(float(x or 0) * 100), 100)
    return f"{rub_:,}".replace(",", " ") + f" руб. {kop:02d} коп."


class TaxCerts:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    def data(self, pid, year) -> dict:
        year = int(year)
        p = self.db.patient(pid)
        if not p:
            raise ValueError("Пациент не найден")
        pays = self.db.q("""SELECT substr(created_at,1,10) AS day, amount, method FROM payments
                            WHERE patient_id=? AND substr(created_at,1,4)=? AND COALESCE(method,'') NOT IN ('Из аванса', 'Страховая')
                            ORDER BY created_at""", (pid, str(year)))
        issued = self.db.q("SELECT number, issued_at, sum1, sum2, payer_fio FROM tax_certs WHERE patient_id=? AND year=? ORDER BY issued_at",
                           (pid, year))
        return {"year": year, "patient": {"id": pid, "name": p.get("name") or "", "birth": p.get("birth") or ""},
                "payments": pays, "total": round(sum(x["amount"] or 0 for x in pays), 2), "issued": issued}

    def issue(self, f: dict, clinic: dict, local, who="") -> dict:
        year = int(f.get("year") or date.today().year)
        if not 2000 <= year <= date.today().year:
            raise ValueError("Год указан неверно")
        p = self.db.patient(str(f.get("patient_id") or ""))
        if not p:
            raise ValueError("Пациент не найден")
        if not (clinic.get("name") and clinic.get("inn")):
            raise ValueError("Заполните название и ИНН клиники: «Шаблоны и прайс» → «Реквизиты»")
        same = bool(f.get("payer_same", True))
        patient = {"fio": str(f.get("patient_fio") or p.get("name") or "").strip()[:200],
                   "inn": _inn(f.get("patient_inn"), "пациента"), "birth": _birth(f.get("patient_birth") or p.get("birth"), "пациента"),
                   "doc": str(f.get("patient_doc") or "").strip()[:200]}
        payer = patient if same else {"fio": str(f.get("payer_fio") or "").strip()[:200], "inn": _inn(f.get("payer_inn"), "налогоплательщика"),
                                      "birth": _birth(f.get("payer_birth"), "налогоплательщика"), "doc": str(f.get("payer_doc") or "").strip()[:200]}
        if not payer["fio"]:
            raise ValueError("Укажите ФИО налогоплательщика (кто платил)")
        if not payer["inn"] and not (payer["birth"] and payer["doc"]):
            raise ValueError("Укажите ИНН налогоплательщика, а если его нет — дату рождения и паспорт")
        s1, s2 = _money(f.get("sum1")), _money(f.get("sum2"))
        if s1 + s2 <= 0:
            raise ValueError("Сумма в справке должна быть больше нуля")
        cid = "TC-" + uuid.uuid4().hex[:10]
        ts = _now()
        with self.db.tx() as c:
            n = (c.execute("SELECT MAX(number) FROM tax_certs WHERE year=?", (year,)).fetchone()[0] or 0) + 1
            c.execute("""INSERT INTO tax_certs(id, number, year, patient_id, patient_fio, patient_inn, patient_birth, patient_doc, payer_same,
                         payer_fio, payer_inn, payer_birth, payer_doc, sum1, sum2, issued_at, issued_by, note)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (cid, n, year, p["id"], patient["fio"], patient["inn"], patient["birth"], patient["doc"], int(same),
                       payer["fio"], payer["inn"], payer["birth"], payer["doc"], s1, s2, ts, who or "", str(f.get("note") or "")[:300]))
        cert = self.get(cid)
        body = render(cert, clinic, f.get("responsible") or who or "")
        doc_id = local.save_document({"patient_id": p["id"], "template_id": "tax_cert", "title": f"Справка для налогового вычета № {n} за {year} год",
                                      "html": body, "data": {"tax_cert": cid}})
        with self.db.tx() as c:
            c.execute("UPDATE tax_certs SET document_id=? WHERE id=?", (doc_id, cid))
        return {**self.get(cid), "html": body}

    def get(self, cid) -> dict:
        r = self.db.one("SELECT * FROM tax_certs WHERE id=?", (cid,))
        if not r:
            raise ValueError("Справка не найдена")
        return r

    def list(self, year) -> dict:
        rows = self.db.q("SELECT * FROM tax_certs WHERE year=? ORDER BY number", (int(year),))
        return {"year": int(year), "rows": rows, "total1": round(sum(r["sum1"] or 0 for r in rows), 2),
                "total2": round(sum(r["sum2"] or 0 for r in rows), 2)}


def render(c: dict, clinic: dict, responsible: str) -> str:
    e = html.escape
    dmy = lambda s: f"{s[8:10]}.{s[5:7]}.{s[:4]}" if s else ""  # noqa: E731

    def person(fio, inn, birth, doc):
        return (f"<b>{e(fio)}</b><br>ИНН: {e(inn) if inn else '—'}"
                + ("" if inn else f"<br>Дата рождения: {e(dmy(birth))}<br>Документ, удостоверяющий личность: {e(doc)}"))
    patient_line = ("Налогоплательщик и пациент являются одним лицом" if c["payer_same"]
                    else "Пациент:<br>" + person(c["patient_fio"], c["patient_inn"], c["patient_birth"], c["patient_doc"]))
    return f"""<h2 style="text-align:center">СПРАВКА<br>об оплате медицинских услуг для представления в налоговый орган</h2>
<p style="text-align:center">№ {c['number']} &nbsp; Отчётный год: {c['year']} &nbsp; Дата выдачи: {e(dmy(c['issued_at']))}</p>
<table border="1" cellspacing="0" cellpadding="6" style="width:100%;border-collapse:collapse">
<tr><td style="width:42%">Медицинская организация (ИП)</td><td><b>{e(clinic.get('name') or '')}</b><br>ИНН: {e(clinic.get('inn') or '')}{' &nbsp; КПП: ' + e(clinic['kpp']) if clinic.get('kpp') else ''}<br>{e(clinic.get('address') or '')}</td></tr>
<tr><td>Налогоплательщик (кто оплатил услуги)</td><td>{person(c['payer_fio'], c['payer_inn'], c['payer_birth'], c['payer_doc'])}</td></tr>
<tr><td>Пациент</td><td>{patient_line}</td></tr>
<tr><td>Стоимость оказанных медицинских услуг, код услуги 1</td><td><b>{rub(c['sum1'])}</b></td></tr>
<tr><td>Стоимость оказанных медицинских услуг, код услуги 2 (дорогостоящие виды лечения)</td><td><b>{rub(c['sum2'])}</b></td></tr>
</table>
<p>Лицо, ответственное за выдачу справки: {e(responsible or '')} &nbsp;&nbsp; ____________________ (подпись)</p>
<p>М. П. (при наличии)</p>"""
