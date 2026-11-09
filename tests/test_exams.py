"""Medical record 2.10.0: visit templates by speciality (protocols), medicines and prescriptions in the record,
recipe / referral / patient memo documents, hiding and restoring built-in templates, rights and sync."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import auth  # noqa: E402
import catalog  # noqa: E402
import db as dbm  # noqa: E402
import local as localm  # noqa: E402
import replica  # noqa: E402
from main import Api  # noqa: E402


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def refuses(name, fn, text=""):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except ValueError as e:
        check(name, not text or text in str(e), e)


# ---------------------------------------------------------------- catalog
codes = {c for c, _ in catalog.MKB}
drugs = {d[0] for d in catalog.DRUGS}
specs = {e[1] for e in catalog.EXAMS}
check("six specialities", {"Терапия", "Хирургия", "Ортопедия", "Ортодонтия", "Пародонтология", "Детская"} <= specs, specs)
check("exam ids unique", len({e[0] for e in catalog.EXAMS}) == len(catalog.EXAMS))
check("exam diagnoses are in ICD-10 list", all(c in codes for e in catalog.EXAMS for c in e[4]))
check("exam prescriptions are in the medicines list", all(r in drugs for e in catalog.EXAMS for r in e[6]))
check("exam tooth states are known", all(not e[5] or all(x in catalog.TOOTH_STATUSES for x in e[5].split(", ")) for e in catalog.EXAMS))
check("exam fields are record fields", all(set(e[3]) <= {"complaints", "anamnesis", "objective", "treatment", "recommendations"} for e in catalog.EXAMS))
check("tooth placeholder used", sum("{зуб}" in json.dumps(e[3], ensure_ascii=False) for e in catalog.EXAMS) >= 12)
docs = {d[0]: d[3] for d in catalog.DOCS}
check("recipe document", "{{rp:rx}}" in docs.get("recipe", "") and "107-1/у" in docs["recipe"])
check("referral document", "{{record.diagnoses}}" in docs.get("referral", "") and "{{input:" in docs["referral"])
check("memo document", "{{table:rx}}" in docs.get("memo", ""))

# ---------------------------------------------------------------- seed and reference
d = dbm.DB()
d.upsert_doctors([{"id": 1, "lname": "Петров", "fname": "Пётр"}])
d.upsert_patients([{"id": 1, "lname": "Иванова", "fname": "Мария"}])
a = Api(d, W())
replica.install(d)
ref = a.reference()
check("exams in reference", len(ref["exams"]) == len(catalog.EXAMS), len(ref["exams"]))
check("medicines in reference", len(ref["drugs"]) == len(catalog.DRUGS))
ex = next(x for x in ref["exams"] if x["id"] == "ex_surg_extract")
check("exam body parsed", ex["data"]["diagnoses"] == ["K08.3"] and ex["data"]["tooth"] == "Отсутствует" and ex["category"] == "Хирургия")
check("medicine body parsed", ref["drugs"][0]["data"]["name"] == catalog.DRUGS[0][0] and ref["drugs"][0]["data"]["how"])
check("new documents seeded", {"doc_recipe", "doc_referral", "doc_memo"} <= {t["id"] for t in a.templates("document")})
catalog.seed(d)
check("second seed adds nothing", len(a.templates("exam")) == len(catalog.EXAMS))

# ---------------------------------------------------------------- own templates
refuses("unknown template kind", lambda: a.save_template({"kind": "virus", "title": "x", "body": "x"}), "Неизвестный")
refuses("exam body must be JSON", lambda: a.save_template({"kind": "exam", "category": "Терапия", "title": "Мой", "body": "{oops"}), "неверно")
refuses("exam needs a title", lambda: a.save_template({"kind": "exam", "category": "Терапия", "title": " ", "body": "{}"}), "название")
refuses("medicine needs a name", lambda: a.save_template({"kind": "drug", "title": "x", "body": json.dumps({"name": ""})}), "лекарства")
own = a.save_template({"kind": "exam", "category": "Мои шаблоны", "title": "Скол композита",
                       "body": json.dumps({"fields": {"treatment": "Починка пломбы зуба {зуб}."}, "diagnoses": ["K02.1"], "tooth": "Пломба",
                                           "rx": [{"name": "Своё средство", "dose": "1", "how": "утром", "days": "3"}]}, ensure_ascii=False)})
check("own exam saved", any(x["id"] == own and x["data"]["rx"][0]["name"] == "Своё средство" for x in a.reference()["exams"]))
drug = a.save_template({"kind": "drug", "title": "Тестовое средство", "body": json.dumps({"name": "Тестовое средство", "dose": "1 таб."}, ensure_ascii=False)})
check("own medicine saved", any(x["id"] == drug for x in a.reference()["drugs"]))
check("phrases still save", bool(a.save_template({"kind": "phrase", "category": "complaints", "title": "x", "body": "Жалоб нет."})))

# hide / restore built-ins, delete own ones
with d.tx() as c:
    c.execute("DELETE FROM sync_dirty")
a.delete_template("ex_ther_caries")
row = d.one("SELECT kind FROM templates WHERE id='ex_ther_caries'")
check("built-in exam hidden, not deleted", row and row["kind"] == "exam:off", row and dict(row))
check("hidden exam not offered", all(x["id"] != "ex_ther_caries" for x in a.reference()["exams"]))
check("hiding goes to other laptops", d.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='templates' AND k=?", (json.dumps(["ex_ther_caries"]),)))
catalog.seed(d)
check("hidden exam does not come back on start", d.one("SELECT kind FROM templates WHERE id='ex_ther_caries'")["kind"] == "exam:off")
a.delete_template("drug_0")
check("restore exams", a.restore_templates("exam") == 1 and d.one("SELECT kind FROM templates WHERE id='ex_ther_caries'")["kind"] == "exam")
check("restore touches only its kind", d.one("SELECT kind FROM templates WHERE id='drug_0'")["kind"] == "drug:off")
check("restore medicines", a.restore_templates("drug") == 1)
refuses("restore unknown kind", lambda: a.restore_templates("virus"), "Неизвестный")
a.delete_template(own)
check("own exam deleted", d.one("SELECT 1 AS x FROM templates WHERE id=?", (own,)) is None)
check("restore rights", auth.METHOD_PERMS.get("restore_templates") == "refs" and "restore_templates" in auth.AUDITED)

# ---------------------------------------------------------------- prescriptions in the record
check("rx cleaning", localm.clean_rx([{"name": " Ибупрофен ", "dose": "1", "how": "x" * 400, "days": 3}, {"name": ""}, "мусор", {"dose": "1"}])
      == [{"name": "Ибупрофен", "dose": "1", "how": "x" * 300, "days": "3"}])
check("rx not a list", localm.clean_rx("Ибупрофен") == [])
rid = a.save_record({"patient_id": "1", "doctor_id": "1", "date": "2026-11-09", "treatment": "Удаление зуба 46.",
                     "rx": [{"name": "Нимесулид 100 мг, таблетки", "dose": "по 1 таблетке", "how": "2 раза в день", "days": "3 дня"}, {"name": "  "}]})
rec = a.record(rid)
check("record keeps prescriptions", rec["data"]["rx"] == [{"name": "Нимесулид 100 мг, таблетки", "dose": "по 1 таблетке", "how": "2 раза в день", "days": "3 дня"}])
rid2 = a.save_record({"patient_id": "1", "date": "2026-11-09", "treatment": "Осмотр."})
check("record without prescriptions has no key", "rx" not in a.record(rid2)["data"])
ctx = a.doc_context("1", None, rid, None, None)
check("documents get prescriptions", ctx["record"]["rx"][0]["name"].startswith("Нимесулид"))

# allergy check covers prescriptions (the UI sends their names with the record text)
w = a.allergy_check("1", "Амоксициллин + клавулановая кислота 875 мг + 125 мг, таблетки", "аллергия на пенициллин")
check("penicillin allergy warns on amoxicillin", any("пеницил" in json.dumps(x, ensure_ascii=False).lower() for x in w["warnings"]), w["warnings"])
w = a.allergy_check("1", "Нимесулид 100 мг, таблетки", "аллергия на аспирин")
check("NSAID group warns", bool(w["warnings"]), w["warnings"])

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print(" -", f)
sys.exit(1 if FAIL else 0)
