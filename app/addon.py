"""3.2: the «Надстройка над Dentist Plus» mode (stage 0 of the add-on plan).

Dentist Plus is the clinic's official certified system: the medical record and every document for inspectors live
there. With the mode on (the default, also for existing installations) this program is the clinic's internal system:
- sections that come from Dentist Plus (patients, appointments, doctors, services) carry a discreet «из Dentist Plus»;
- our medical entries (record, visit templates, dictation, visit recording, AI review, prescriptions, referrals)
  are drafts for Dentist Plus — the official entry is the one saved in Dentist Plus;
- official document templates are signed «не для контролирующих органов» (or hidden, a second setting);
- SaaS sections (cloud for many clinics with its subscription, moving a base in from IDENT) are hidden in the UI.
Nothing is deleted and no method is blocked: the director switches the mode off in Settings and everything works as
before. The clinic network (p2p) and updates stay in both modes."""
from __future__ import annotations

import config

# Official documents: inspectors see the ones printed from Dentist Plus (the plan: contract, consents, 043/у, ИДС).
OFFICIAL_DOCS = {
    "doc_contract": "Договор на оказание платных медицинских услуг",
    "doc_consent_treatment": "Информированное добровольное согласие (ИДС)",
    "doc_consent_pd": "Согласие на обработку персональных данных",
    "doc_refusal": "Отказ от медицинского вмешательства",
    "doc_card043": "Медицинская карта 043/у",
    "doc_extract": "Выписка из медицинской карты",
    "doc_visit_note": "Справка о посещении",
}
# Medical papers made from our record: a draft, the official one is made in Dentist Plus.
DRAFT_DOCS = {
    "doc_recipe": "Рецепт 107-1/у",
    "doc_referral": "Направление",
}
# Everything else stays internal and unchanged: anketa (health questionnaire for the doctor's alerts), plan
# presentation, memo, consent to record the visit, receipt (not a fiscal check), act of works (payments: to decide).

OFFICIAL_NOTE = "Не для контролирующих органов — официальный документ печатайте из Dentist Plus"
DRAFT_NOTE = "Черновик для Dentist Plus — официальная запись в Dentist Plus"
SOURCE_NOTE = "из Dentist Plus"
DOCS_MODES = ("mark", "hide")   # official templates: signed (default) or hidden


def enabled(s: dict | None = None) -> bool:
    s = config.load_settings() if s is None else s
    return bool(s.get("addon_mode", True))


def docs_mode(s: dict | None = None) -> str:
    s = config.load_settings() if s is None else s
    m = s.get("addon_docs", "mark")
    return m if m in DOCS_MODES else "mark"


def doc_kind(template_id: str) -> str:
    """«official», «draft» or «internal» — for the program in the add-on mode."""
    tid = str(template_id or "")
    if tid in OFFICIAL_DOCS:
        return "official"
    if tid in DRAFT_DOCS:
        return "draft"
    return "internal"


def hidden_docs(s: dict | None = None) -> set:
    """Template ids the document lists leave out now (only with the mode on and «hide» chosen)."""
    s = config.load_settings() if s is None else s
    return set(OFFICIAL_DOCS) if enabled(s) and docs_mode(s) == "hide" else set()


def taxcert_hidden(s: dict | None = None) -> bool:
    """The tax deduction certificate is official too: hidden together with the official templates."""
    s = config.load_settings() if s is None else s
    return enabled(s) and docs_mode(s) == "hide"


def mark_templates(rows: list, s: dict | None = None) -> list:
    """templates(kind) for the UI: each document template gets its kind; hidden official ones are left out."""
    s = config.load_settings() if s is None else s
    on, hide = enabled(s), hidden_docs(s)
    out = []
    for t in rows:
        if t.get("kind") == "document":
            if t.get("id") in hide:
                continue
            t = {**t, "addon_kind": doc_kind(t.get("id")) if on else "internal"}
        out.append(t)
    return out


def info(s: dict | None = None) -> dict:
    """What every signed-in employee's UI needs (ui_settings, status)."""
    s = config.load_settings() if s is None else s
    on = enabled(s)
    return {"addon_mode": on, "addon_docs": docs_mode(s),
            "addon_official": sorted(OFFICIAL_DOCS) + ["taxcert"] if on else [], "addon_draft": sorted(DRAFT_DOCS) if on else [],
            "addon_taxcert_hidden": taxcert_hidden(s),
            "addon_notes": {"official": OFFICIAL_NOTE, "draft": DRAFT_NOTE, "source": SOURCE_NOTE}}


def clean(upd: dict) -> dict:
    """Settings → «Режим работы»: only the two keys, of the right type."""
    out = {}
    if "addon_mode" in upd:
        out["addon_mode"] = bool(upd["addon_mode"])
    if "addon_docs" in upd:
        if upd["addon_docs"] not in DOCS_MODES:
            raise ValueError("Неизвестный вариант для официальных документов")
        out["addon_docs"] = upd["addon_docs"]
    return out
