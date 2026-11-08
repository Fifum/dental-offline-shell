"""Patient-filled forms: the health questionnaire and handwritten signatures under documents.

A signature is a PNG drawn with a finger (tablet) or a mouse/pen (this screen). It is stored with the time,
the signer, where it was signed and a SHA-256 of the document text at that moment, so a later edit of the
document is visible («документ изменён после подписи»).
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import uuid
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS document_signatures(
    id TEXT PRIMARY KEY, document_id TEXT, signer TEXT, role TEXT, image TEXT, doc_sha256 TEXT,
    signed_at TEXT, place TEXT, ip TEXT, created_by TEXT);
CREATE INDEX IF NOT EXISTS ix_docsig_doc ON document_signatures(document_id);
CREATE TABLE IF NOT EXISTS questionnaires(
    id TEXT PRIMARY KEY, patient_id TEXT, answers TEXT, signature TEXT, document_id TEXT, place TEXT,
    created_at TEXT, created_by TEXT);
CREATE INDEX IF NOT EXISTS ix_quest_patient ON questionnaires(patient_id);
"""

# key, question, extra field label (None — yes/no only), alert title when «да»
QUESTIONS = [
    ("allergy", "Есть ли у вас аллергия на лекарства, обезболивающие, латекс, продукты?", "На что", "Аллергия"),
    ("drugs", "Принимаете ли вы постоянно какие-либо лекарства?", "Какие", "Постоянно принимает"),
    ("heart", "Болезни сердца и сосудов: гипертония, инфаркт, стенокардия, кардиостимулятор?", "Что именно", "Сердце и сосуды"),
    ("bleeding", "Повышенная кровоточивость или приём препаратов, разжижающих кровь (варфарин, аспирин и др.)?", "Что именно", "Кровоточивость / антикоагулянты"),
    ("diabetes", "Сахарный диабет?", None, "Сахарный диабет"),
    ("infect", "Гепатит B или C, ВИЧ, туберкулёз?", None, "Инфекционные заболевания"),
    ("asthma", "Бронхиальная астма, эпилепсия, обмороки?", "Что именно", "Астма / эпилепсия"),
    ("anesth", "Были ли плохие реакции на обезболивание у стоматолога?", "Какие", "Реакция на анестезию"),
    ("pregnancy", "Беременность или кормление грудью (для женщин)?", "Срок", "Беременность / кормление"),
    ("other", "Другие хронические заболевания или операции?", "Какие", "Другие заболевания"),
    ("smoking", "Курите ли вы?", None, None),
]
SIGN_MAX = 400_000  # bytes of the PNG


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _png(image) -> str:
    """A signature data URL → checked base64 PNG (empty or not a PNG → error)."""
    s = str(image or "")
    if s.startswith("data:"):
        s = s.split(",", 1)[1] if "," in s else ""
    try:
        raw = base64.b64decode(s, validate=False)
    except Exception:  # noqa: BLE001
        raw = b""
    if not raw.startswith(b"\x89PNG") or len(raw) > SIGN_MAX:
        raise ValueError("Подпись не получена — распишитесь в поле ещё раз")
    if _ink(raw) < 40:  # an empty or almost empty pad
        raise ValueError("Поле подписи пустое — распишитесь пальцем или мышью")
    return base64.b64encode(raw).decode()


def _ink(raw: bytes) -> int:
    """How many pixels of the pad are drawn on (the pad is transparent or white where nothing is drawn)."""
    import io  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return 0
    im.thumbnail((400, 400))
    return sum(1 for r, g, b, a in im.getdata() if a > 60 and (r + g + b) < 600)


def doc_hash(html_text: str) -> str:
    return hashlib.sha256(str(html_text or "").encode("utf-8")).hexdigest()


def clean_answers(answers) -> dict:
    out = {}
    for key, _q, extra, _a in QUESTIONS:
        a = (answers or {}).get(key) or {}
        yes = a.get("yes")
        if yes not in (True, False):
            raise ValueError("Ответьте на все вопросы анкеты «да» или «нет»")
        text = str(a.get("text") or "").strip()[:300] if extra else ""
        out[key] = {"yes": bool(yes), "text": text if yes else ""}
    return out


def alerts(answers: dict) -> list[str]:
    """«Аллергия: лидокаин», «Сахарный диабет» … — what the doctor must see in the card."""
    out = []
    for key, _q, _e, title in QUESTIONS:
        a = (answers or {}).get(key) or {}
        if title and a.get("yes"):
            out.append(f"{title}: {a['text']}" if a.get("text") else title)
    return out


def anketa_html(patient: dict, answers: dict, clinic: dict, signed_at: str) -> str:
    e = html.escape
    rows = "".join(
        f"<tr><td>{e(q)}</td><td style='text-align:center'><b>{'да' if answers[k]['yes'] else 'нет'}</b></td>"
        f"<td>{e(answers[k]['text'])}</td></tr>" for k, q, _x, _t in QUESTIONS)
    return (f"<h2 style='text-align:center'>Анкета о состоянии здоровья</h2>"
            f"<p>{e(clinic.get('name') or '')}{', ' + e(clinic['address']) if clinic.get('address') else ''}</p>"
            f"<p>Пациент: <b>{e(patient.get('name') or '')}</b>"
            f"{', дата рождения ' + e(patient['birth']) if patient.get('birth') else ''}</p>"
            f"<table border='1' cellspacing='0' cellpadding='4' style='width:100%;border-collapse:collapse'>"
            f"<tr><th>Вопрос</th><th>Ответ</th><th>Уточнение</th></tr>{rows}</table>"
            f"<p>Сведения сообщены мной лично и достоверны. Обязуюсь сообщить врачу об их изменении.</p>"
            f"<p>Заполнено {e(signed_at[:16])}</p>")


class Forms:
    def __init__(self, db, local):
        self.db, self.local = db, local
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    # -------------------------------------------------------- signatures --
    def sign_document(self, doc_id, signer, image, role="patient", place="screen", ip="", who="") -> dict:
        d = self.db.one("SELECT id, html, title FROM documents WHERE id=?", (doc_id,))
        if not d:
            raise ValueError("Документ не найден")
        if role not in ("patient", "representative", "doctor"):
            raise ValueError("Неизвестная роль подписанта")
        signer = str(signer or "").strip()[:200]
        if not signer:
            raise ValueError("Укажите, кто подписывает")
        sid = "SG-" + uuid.uuid4().hex[:10]
        with self.db.tx() as c:
            c.execute("""INSERT INTO document_signatures(id, document_id, signer, role, image, doc_sha256, signed_at, place, ip, created_by)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""", (sid, doc_id, signer, role, _png(image), doc_hash(d["html"]), _now(),
                                                         place, ip or "", who or ""))
        return self.signatures(doc_id)[-1]

    def signatures(self, doc_id) -> list[dict]:
        d = self.db.one("SELECT html FROM documents WHERE id=?", (doc_id,))
        cur = doc_hash(d["html"]) if d else ""
        rows = self.db.q("SELECT * FROM document_signatures WHERE document_id=? ORDER BY signed_at", (doc_id,))
        for r in rows:
            r["image"] = "data:image/png;base64," + r["image"]
            r["changed"] = r["doc_sha256"] != cur
        return rows

    def signed_ids(self, doc_ids) -> set:
        ids = list(doc_ids or [])
        if not ids:
            return set()
        q = ",".join("?" * len(ids))
        return {r["document_id"] for r in self.db.q(f"SELECT DISTINCT document_id FROM document_signatures WHERE document_id IN ({q})", ids)}

    # ----------------------------------------------------- questionnaire --
    def questions(self) -> list[dict]:
        return [{"key": k, "q": q, "extra": x} for k, q, x, _t in QUESTIONS]

    def save_questionnaire(self, pid, answers, signature, clinic, place="screen", who="") -> dict:
        p = self.db.patient(pid)
        if not p:
            raise ValueError("Пациент не найден")
        ans = clean_answers(answers)
        sig = _png(signature)
        ts = _now()
        doc_id = self.local.save_document({"patient_id": pid, "template_id": "anketa_filled", "title": f"Анкета о здоровье от {ts[8:10]}.{ts[5:7]}.{ts[:4]}",
                                           "html": anketa_html(p, ans, clinic or {}, ts), "data": {"answers": ans}})
        with self.db.tx() as c:
            c.execute("""INSERT INTO document_signatures(id, document_id, signer, role, image, doc_sha256, signed_at, place, ip, created_by)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      ("SG-" + uuid.uuid4().hex[:10], doc_id, p.get("name") or "", "patient", sig,
                       doc_hash(self.db.one("SELECT html FROM documents WHERE id=?", (doc_id,))["html"]), ts, place, "", who or ""))
            qid = "Q-" + uuid.uuid4().hex[:10]
            c.execute("""INSERT INTO questionnaires(id, patient_id, answers, signature, document_id, place, created_at, created_by)
                         VALUES(?,?,?,?,?,?,?,?)""", (qid, pid, json.dumps(ans, ensure_ascii=False), sig, doc_id, place, ts, who or ""))
        return {"id": qid, "document_id": doc_id, "alerts": alerts(ans), "created_at": ts}

    def latest(self, pid) -> dict | None:
        r = self.db.one("SELECT id, answers, document_id, created_at, place FROM questionnaires WHERE patient_id=? ORDER BY created_at DESC LIMIT 1", (pid,))
        if not r:
            return None
        r["answers"] = json.loads(r["answers"] or "{}")
        r["alerts"] = alerts(r["answers"])
        return r

    def allergy_text(self, pid) -> str:
        q = self.latest(pid)
        a = (q or {}).get("answers", {}).get("allergy") or {}
        return a.get("text") or ("есть (не уточнено)" if a.get("yes") else "")


def safe_name(s: str) -> str:
    return re.sub(r"[^\w\s.-]", "", str(s or ""))[:80].strip() or "file"
