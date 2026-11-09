"""Treatment plans with options: «эконом / стандарт / премиум» in one plan (block 2.9.0).

A plan stays one row of `invoices` (kind='plan'). Its items carry `opt`: '' — common to every option
(examination, hygiene), or the key of an option. `invoices.variants` keeps the options (name, warranty, term,
note) as JSON, `invoices.variant` — the option the patient chose. The plan total is what the patient pays:
common + chosen option; while nothing is chosen — common + the cheapest option, so the director's analytics
count the plan once and never three times.

The presentation for the patient is drawn in the UI (it needs the tooth formula); here: PDF through the
Edge that every Windows 10/11 has, and the choice the patient makes on the screen or on the tablet.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid

DEFAULT_VARIANTS = [{"key": "a", "name": "Эконом"}, {"key": "b", "name": "Стандарт"}, {"key": "c", "name": "Премиум"}]
MAX_VARIANTS = 4
_TEXT = {"name": 40, "warranty": 120, "term": 120, "note": 400}


def norm_variants(raw) -> list[dict]:
    """Clean the options from the UI: keys a-z0-9, unique, at most four, every one with a name."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            raw = []
    out, seen = [], set()
    for v in raw or []:
        if not isinstance(v, dict):
            continue
        key = re.sub(r"[^a-z0-9]", "", str(v.get("key") or "").lower())[:8]
        name = str(v.get("name") or "").strip()[:_TEXT["name"]]
        if not key or key in seen or not name:
            continue
        seen.add(key)
        out.append({"key": key, "name": name, **{k: str(v.get(k) or "").strip()[:n] for k, n in _TEXT.items() if k != "name"}})
        if len(out) >= MAX_VARIANTS:
            break
    return out


def line_sum(it: dict) -> float:
    s = float(it.get("price") or 0) * float(it.get("qty") or 1)
    return s - s * float(it.get("discount") or 0) / 100


def item_opt(it: dict, keys) -> str:
    """The option an item belongs to; items of an option that was removed become common."""
    o = str(it.get("opt") or "")
    return o if o in keys else ""


def totals(items, variants, discount=0.0, chosen="") -> dict:
    """{'common', 'by_variant': {key: sum}, 'total'} — every sum after the plan discount."""
    keys = [v["key"] for v in variants or []]
    k = 1 - float(discount or 0) / 100
    common = sum(line_sum(it) for it in items or [] if not item_opt(it, keys))
    by = {key: round((common + sum(line_sum(it) for it in items if item_opt(it, keys) == key)) * k, 2) for key in keys}
    if not keys:
        total = round(common * k, 2)
    elif chosen in by:
        total = by[chosen]
    else:
        total = min(by.values())
    return {"common": round(common * k, 2), "by_variant": by, "total": total}


def billable(items, variants, chosen="") -> list[int]:
    """Indexes of the items that may be billed: common ones and those of the chosen option."""
    keys = [v["key"] for v in variants or []]
    return [i for i, it in enumerate(items or []) if not item_opt(it, keys) or item_opt(it, keys) == chosen]


class Plans:
    def __init__(self, db, local, forms=None):
        self.db, self.local, self.forms = db, local, forms

    def _plan(self, plan_id) -> dict:
        p = self.local.invoice(plan_id)
        if not p or p.get("kind") != "plan":
            raise ValueError("План не найден")
        return p

    def choose(self, plan_id, key) -> dict:
        """The patient chose an option ('' — choice cancelled). The plan becomes «Подтверждён»."""
        p = self._plan(plan_id)
        variants = p.get("variants") or []
        key = str(key or "")
        if key and key not in [v["key"] for v in variants]:
            raise ValueError("Такого варианта в плане нет")
        t = totals(p["items"], variants, p.get("discount") or 0, key)
        st = p.get("plan_status") or "Предварительный"
        if key and st == "Предварительный":
            st = "Подтверждён"
        elif not key and st == "Подтверждён":
            st = "Предварительный"
        with self.db.tx() as c:
            c.execute("UPDATE invoices SET variant=?, total=?, plan_status=?, transferred=0, transferred_at=NULL WHERE id=?",
                      (key or None, t["total"], st, plan_id))
        return self._plan(plan_id)

    def variant_name(self, plan, key) -> str:
        return next((v["name"] for v in plan.get("variants") or [] if v["key"] == key), "")

    def sign_on_tablet(self, task: dict, variant, image, place, ip="") -> dict:
        """Tablet result: the presentation is saved to the card as a signed document and the option is set."""
        plan = self._plan(task["plan_id"])
        variants = plan.get("variants") or []
        variant = str(variant or "")
        if variants and variant not in [v["key"] for v in variants]:
            raise ValueError("Выберите вариант лечения")
        import forms as formsm
        formsm._png(image)  # an empty pad is refused before anything is saved to the card
        html = task["html"]
        if variants:
            t = totals(plan["items"], variants, plan.get("discount") or 0, variant)
            money = f'{t["total"]:,.0f}'.replace(",", " ")
            html += (f'<p class="pp-choice">Пациент выбрал вариант: <b>{_esc(self.variant_name(plan, variant))}</b> — '
                     f'{money} ₽</p>')
        title = "План лечения" + (f" — {self.variant_name(plan, variant)}" if variants else "")
        did = self.local.save_document({"patient_id": plan["patient_id"], "template_id": "plan_presentation", "title": title,
                                        "html": html, "data": {"plan_id": plan["id"], "variant": variant}})
        self.forms.sign_document(did, task.get("signer") or task.get("patient") or "Пациент", image, "patient", place, ip, "")
        if variants:
            self.choose(plan["id"], variant)
        elif (plan.get("plan_status") or "Предварительный") == "Предварительный":
            with self.db.tx() as c:
                c.execute("UPDATE invoices SET plan_status='Подтверждён', transferred=0 WHERE id=?", (plan["id"],))
        return {"document_id": did, "variant": variant}


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ------------------------------------------------------------------ PDF --
def find_edge() -> str:
    """Microsoft Edge (or the WebView2 runtime the program already needs) — both print HTML to PDF."""
    cands = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            cands.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        root = os.path.join(base or "", "Microsoft", "EdgeWebView", "Application")
        if base and os.path.isdir(root):
            for ver in sorted(os.listdir(root), reverse=True):
                cands.append(os.path.join(root, ver, "msedge.exe"))
    cands.append(shutil.which("msedge") or "")
    return next((c for c in cands if c and os.path.isfile(c)), "")


def html_to_pdf(html: str, timeout=90) -> bytes:
    """A whole HTML document → PDF bytes (headless Edge, own temporary profile, no header/footer)."""
    edge = find_edge()
    if not edge:
        raise ValueError("На компьютере не найден Microsoft Edge. Сохраните PDF через «Печать» → «Сохранить как PDF».")
    tmp = tempfile.mkdtemp(prefix="dd-pdf-")
    try:
        src, out = os.path.join(tmp, "plan.html"), os.path.join(tmp, "plan.pdf")
        with open(src, "w", encoding="utf-8") as f:
            f.write(html)
        args = [edge, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", f"--user-data-dir={os.path.join(tmp, 'profile')}", "--no-pdf-header-footer",
                "--print-to-pdf-no-header", f"--print-to-pdf={out}", "file:///" + src.replace("\\", "/")]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(args, timeout=timeout, capture_output=True, creationflags=flags)
        if not os.path.isfile(out) or os.path.getsize(out) < 500:
            raise ValueError("Не удалось сохранить PDF. Сохраните через «Печать» → «Сохранить как PDF».")
        with open(out, "rb") as f:
            return f.read()
    except subprocess.TimeoutExpired:
        raise ValueError("PDF собирается слишком долго. Сохраните через «Печать» → «Сохранить как PDF».")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pdf_payload(html: str, name: str) -> dict:
    data = html_to_pdf(html)
    safe = re.sub(r'[\\/:*?"<>|]+', " ", str(name or "План лечения")).strip()[:80] or "План лечения"
    return {"name": safe + ".pdf", "url": "data:application/pdf;base64," + base64.b64encode(data).decode(),
            "size": len(data), "id": uuid.uuid4().hex[:8]}
