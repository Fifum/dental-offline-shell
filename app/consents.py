"""2.13 (13.7): the patient's consent to an audio recording of the visit.

Before «Запись приёма» the program asks whether the patient agreed: aloud (the employee notes it), or on paper
(the form «Согласие на аудиозапись приёма» from the documents). The consent is kept in the card with who noted it
and when, can be withdrawn, and goes to the other laptops of the clinic. Without it the visit is not recorded."""
from __future__ import annotations

from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_consents(
    id TEXT PRIMARY KEY, patient_id TEXT, kind TEXT, method TEXT, note TEXT,
    given_at TEXT, given_by TEXT, revoked_at TEXT, revoked_by TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS ix_consents_patient ON patient_consents(patient_id);
"""
KINDS = {"recording": "Аудиозапись приёма"}
METHODS = {"verbal": "устно, отмечено сотрудником", "paper": "подписано на бумаге", "document": "подписан документ в программе"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Consents:
    def __init__(self, db):
        self.db = db
        with db._lock:
            db.conn.executescript(SCHEMA)
            db.conn.commit()

    @staticmethod
    def _id(pid, kind):
        return f"{kind}:{pid}"   # the same row on every laptop: one consent per patient and kind

    def get(self, pid, kind="recording"):
        r = self.db.one("SELECT * FROM patient_consents WHERE id=?", (self._id(pid, kind),))
        if not r:
            return None
        r["active"] = not r["revoked_at"]
        r["method_text"] = METHODS.get(r["method"], r["method"] or "")
        return r

    def has(self, pid, kind="recording") -> bool:
        r = self.get(pid, kind)
        return bool(r and r["active"])

    def give(self, pid, kind="recording", method="verbal", note="", who=""):
        if kind not in KINDS:
            raise ValueError("Неизвестный вид согласия")
        if method not in METHODS:
            raise ValueError("Укажите, как получено согласие")
        if not self.db.one("SELECT 1 AS x FROM patients WHERE id=?", (str(pid),)):
            raise ValueError("Пациент не найден")
        with self.db.tx() as c:
            c.execute("""INSERT INTO patient_consents(id, patient_id, kind, method, note, given_at, given_by, revoked_at, revoked_by, updated_at)
                         VALUES(?,?,?,?,?,?,?,NULL,NULL,?)
                         ON CONFLICT(id) DO UPDATE SET method=excluded.method, note=excluded.note, given_at=excluded.given_at,
                         given_by=excluded.given_by, revoked_at=NULL, revoked_by=NULL, updated_at=excluded.updated_at""",
                      (self._id(pid, kind), str(pid), kind, method, str(note or "")[:300], _now(), who, _now()))
        return self.get(pid, kind)

    def revoke(self, pid, kind="recording", who=""):
        with self.db.tx() as c:
            c.execute("UPDATE patient_consents SET revoked_at=?, revoked_by=?, updated_at=? WHERE id=? AND revoked_at IS NULL",
                      (_now(), who, _now(), self._id(pid, kind)))
        return self.get(pid, kind)
