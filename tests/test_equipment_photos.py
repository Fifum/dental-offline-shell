"""3.16 «Фото оборудования» с компьютера: several photos of a piece, one main (the picture of the register), set from the card,
from the form of a new piece and from a line of a receipt; deleting a photo (the next one becomes the main one), the old main
photo of before 3.13 is in the gallery too, a photo is made smaller and goes to the other computers, never a patient's file."""
import base64
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import auth  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import replica  # noqa: E402
from main import Api  # noqa: E402
from PIL import Image  # noqa: E402


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


def pic(color, size=(64, 48), fmt="PNG"):
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, fmt)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(b.getvalue()).decode()


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W())
replica.install(d)
S = a._stock
with d.tx() as c:
    c.execute("DELETE FROM equipment")
    c.execute("DELETE FROM equipment_events")
    c.execute("DELETE FROM sync_dirty")

# ------------------------------------------------------- the gallery of the card --
e1 = a.save_equipment({"name": "Стоматологическая установка", "inv_number": "СТ-001"})
r = a.equipment(e1)
check("no photos yet", r["gallery"] == [] and r["photos"] == [] and not r["photo_id"])
r = a.equipment_photo_add(e1, "установка-спереди.png", pic((20, 150, 140)))
f1 = r["photo_id"]
check("the first photo is the main one", f1 and [g["file_id"] for g in r["gallery"]] == [f1] and r["gallery"][0]["main"], r["gallery"])
check("its title is the file's name", r["gallery"][0]["title"] == "установка-спереди", r["gallery"][0])
r = a.equipment_photo_add(e1, "установка-сбоку.jpg", pic((200, 80, 40), fmt="JPEG"))
f2 = r["gallery"][1]["file_id"]
check("a second photo is not the main one", r["photo_id"] == f1 and len(r["gallery"]) == 2 and not r["gallery"][1]["main"], r["gallery"])
check("photos = the gallery, the main one first", r["photos"] == [f1, f2], r["photos"])
r = a.equipment_photo_add(e1, "снова.png", pic((20, 150, 140)))
check("the same picture twice stays one photo", len(r["gallery"]) == 2, r["gallery"])
r = a.equipment_photo_add(e1, "главное.png", pic((90, 90, 200)), True)
f3 = r["photo_id"]
check("a photo added as the main one", f3 not in (f1, f2) and r["gallery"][0]["file_id"] == f3 and len(r["gallery"]) == 3, r["gallery"])
refuses("a pdf is not a photo", lambda: a.equipment_photo_add(e1, "паспорт.pdf", "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 x").decode()), "фото")
refuses("not a picture", lambda: a.equipment_photo_add(e1, "a.png", "data:image/png;base64," + base64.b64encode(b"hello").decode()), "фото")

# a stored photo: made smaller, a stock file, goes to the other computers
big = a.equipment_photo_add(e1, "огромное.png", pic((10, 200, 10), size=(3000, 2000)))
fb = next(g["file_id"] for g in big["gallery"] if g["file_id"] not in (f1, f2, f3))
check("several photos keep the order they were added in", [g["file_id"] for g in big["gallery"]] == [f3, f1, f2, fb], big["gallery"])
row = d.one("SELECT * FROM patient_files WHERE id=?", (fb,))
check("made smaller and kept as a JPEG of the stock", row["patient_id"] == "_stock" and row["ext"] == ".jpg" and max(row["width"], row["height"]) <= 1200, row)
check("the file goes to the other computers", d.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='patient_files' AND k=?", (json.dumps([fb]),)))
check("the gallery row goes too", d.one("SELECT COUNT(*) AS n FROM sync_dirty WHERE tbl='equipment_docs'")["n"] >= 4)
r = a.equipment_photo_delete(e1, fb)
check("delete a photo that is not the main one", r["photo_id"] == f3 and fb not in r["photos"] and len(r["gallery"]) == 3)
check("the file itself stays (a receipt may hold it)", d.one("SELECT deleted FROM patient_files WHERE id=?", (fb,))["deleted"] == 0)

# the main photo
r = a.equipment_photo_main(e1, f2)
check("«Сделать главным»", r["photo_id"] == f2 and r["gallery"][0]["file_id"] == f2 and r["gallery"][0]["main"]
      and sum(g["main"] for g in r["gallery"]) == 1, r["gallery"])
check("the history knows", any("Главное фото" in (x["text"] or "") for x in r["events"]), [x["text"] for x in r["events"][:3]])
with d.tx() as c:
    c.execute("DELETE FROM sync_dirty WHERE tbl='equipment'")
a.equipment_photo_main(e1, f1)
check("the main photo goes to the other computers", d.one("SELECT 1 AS x FROM sync_dirty WHERE tbl='equipment' AND k=?", (json.dumps([e1]),)))
check("main again: nothing changes", a.equipment_photo_main(e1, f1)["photo_id"] == f1)
refuses("main: a photo of another card", lambda: a.equipment_photo_main(e1, "F-nope"), "не найдено")
pid = d.one("SELECT id FROM patients LIMIT 1")["id"]
pf = a._files.add(pid, "snimok.png", base64.b64decode(pic((1, 2, 3)).split(",", 1)[1]), {"kind": "photo"})
refuses("main: never a patient's file", lambda: a.equipment_photo_main(e1, pf["id"]), "не найдено")

# the register shows the main photo
lst = {x["id"]: x for x in a.equipment_list()}
check("the register knows the main photo", lst[e1]["photo_id"] == f1)
th = a.stock_photos([f1, pf["id"]])
check("its preview for the register, never a patient's file", th.get(f1, "").startswith("data:image/jpeg") and pf["id"] not in th, list(th))

# deleting the main photo, then all
r = a.equipment_photo_delete(e1, f1)
check("the main photo deleted → the next one is the main one", r["photo_id"] in (f2, f3) and f1 not in r["photos"] and len(r["gallery"]) == 2, r["gallery"])
check("the history knows the deletion", any((x["text"] or "").startswith("Убрано фото") for x in r["events"]))
refuses("deleting a photo twice", lambda: a.equipment_photo_delete(e1, f1), "не найдено")
for g in list(r["gallery"]):
    r = a.equipment_photo_delete(e1, g["file_id"])
check("no photos left — no main photo", not r["photo_id"] and r["gallery"] == [] and r["doc_count"] == 0, (r["photo_id"], r["gallery"]))

# the main photo of before 3.13 (only photo_id): in the gallery, deletable
e2 = a.save_equipment({"name": "Автоклав"})
old = a.equipment_photo_upload("старое.png", pic((120, 120, 0)))
check("an upload gives the id and the preview", old["file_id"] and old["thumb"].startswith("data:image/jpeg"), old)
with d.tx() as c:
    c.execute("UPDATE equipment SET photo_id=? WHERE id=?", (old["file_id"], e2))
r = a.equipment(e2)
check("the old main photo is in the gallery", [g["file_id"] for g in r["gallery"]] == [old["file_id"]] and r["gallery"][0]["main"], r["gallery"])
r = a.equipment_photo_add(e2, "новое.png", pic((0, 120, 120)))
check("a new photo next to the old main one", r["photo_id"] == old["file_id"] and len(r["gallery"]) == 2)
r = a.equipment_photo_delete(e2, old["file_id"])
check("the old main photo deleted", r["photo_id"] == r["gallery"][0]["file_id"] and len(r["gallery"]) == 1, r["gallery"])

# «Фото материала или оборудования» of 3.10 goes into the gallery as the main photo
x = a.stock_photo_set("equipment", e2, "кресло.png", pic((5, 60, 200)))
r = a.equipment(e2)
check("stock_photo_set: the main photo of the gallery", r["photo_id"] == x["photo_id"] and r["gallery"][0]["file_id"] == x["photo_id"] and len(r["gallery"]) == 2, r["gallery"])
a.stock_photo_clear("equipment", e2)
r = a.equipment(e2)
check("stock_photo_clear: the main photo leaves, the next one is the main one", r["photo_id"] and x["photo_id"] not in r["photos"] and len(r["gallery"]) == 1)

# ------------------------------------------------------- a new piece with its photos --
u1, u2 = a.equipment_photo_upload("компрессор-1.png", pic((30, 30, 30))), a.equipment_photo_upload("компрессор-2.png", pic((60, 60, 60)))
e3 = a.save_equipment({"name": "Компрессор", "photos": [u2["file_id"], u1["file_id"], pf["id"], "F-nope"]})
r = a.equipment(e3)
check("a new piece gets the photos of its form, the first is the main one", r["photo_id"] == u2["file_id"] and r["photos"] == [u2["file_id"], u1["file_id"]], r["photos"])
check("never a patient's file into a card", pf["id"] not in r["photos"])
a.save_equipment({"id": e3, "name": "Компрессор", "photos": [old["file_id"]]})
check("an edit does not touch the gallery", a.equipment(e3)["photos"] == [u2["file_id"], u1["file_id"]])

# ------------------------------------------------------- the photos of a receipt --
sup = S.save_supplier({"name": "СтомТех ООО"})
p1, p2 = a.equipment_photo_upload("рентген.png", pic((200, 200, 0))), a.equipment_photo_upload("рентген-2.png", pic((200, 0, 200)))
rc = a.equipment_receipt_save({"supplier_id": sup, "doc_number": "ДП-1", "doc_date": "2026-11-20", "step": 2})
rc = a.equipment_receipt_save({"id": rc["id"], "step": 3, "lines": [
    {"name": "Радиовизиограф", "qty": 2, "photos": [p1["file_id"], p2["file_id"], pf["id"]]},
    {"name": "Лампа", "qty": 1}]})
check("a line keeps its photos (no patient's file)", rc["lines"][0]["photos"] == [p1["file_id"], p2["file_id"]] and rc["lines"][1]["photos"] == [], rc["lines"])
rc = a.equipment_receipt_save({"id": rc["id"], "step": 4, "lines": [{k: v for k, v in ln.items() if k != "photos"} for ln in rc["lines"]]})
check("a step without the photos keeps them", rc["lines"][0]["photos"] == [p1["file_id"], p2["file_id"]], rc["lines"][0].get("photos"))
x = a.equipment_receipt_accept(rc["id"])
cards = [a.equipment(i) for i in x["equipment_ids"]]
rv = [c_ for c_ in cards if c_["name"] == "Радиовизиограф"]
check("every unit of the line has the photos, the first is the main one", len(rv) == 2 and all(c_["photos"] == [p1["file_id"], p2["file_id"]] and c_["photo_id"] == p1["file_id"] for c_ in rv),
      [c_["photos"] for c_ in rv])
check("a line without photos — a card without photos", next(c_ for c_ in cards if c_["name"] == "Лампа")["photos"] == [])
r = a.equipment_photo_delete(rv[0]["id"], p1["file_id"])
check("a photo deleted from one card stays in the other", p1["file_id"] in a.equipment(rv[1]["id"])["photos"] and r["photo_id"] == p2["file_id"])

# ------------------------------------------------------- a piece that is gone --
a.equipment_dispose({"id": e3, "kind": "writeoff", "reason": "Износ", "commission": ["А", "Б"]})
refuses("no photos after disposal", lambda: a.equipment_photo_add(e3, "a.png", pic((9, 9, 9))), "выбыло")
refuses("no main photo after disposal", lambda: a.equipment_photo_main(e3, u1["file_id"]), "выбыло")
refuses("no deletion after disposal", lambda: a.equipment_photo_delete(e3, u1["file_id"]), "выбыло")
check("the card of a piece that is gone keeps its photos", a.equipment(e3)["photos"] == [u2["file_id"], u1["file_id"]])

# ------------------------------------------------------- rights and the journal --
NEW = ("equipment_photo_upload", "equipment_photo_add", "equipment_photo_main", "equipment_photo_delete")
check("every new method needs «Оборудование»", all(auth.METHOD_PERMS.get(k) == "equipment" for k in NEW), {k: auth.METHOD_PERMS.get(k) for k in NEW})
check("changes of the gallery in the journal", all(k in auth.AUDITED for k in NEW[1:]))
check("an upload alone is not a change", "equipment_photo_upload" not in auth.AUDITED)

# ------------------------------------------------------- the screens --
ui = ROOT / "app" / "ui"
idx = (ui / "index.html").read_text(encoding="utf-8")
check("the script and its styles are on the page", "stock-eqphotos.js" in idx and "styles-eqphotos.css" in idx)
check("the gallery after the card's script", idx.find("stock-eqphotos.js") > idx.find("stock-eqcard.js"))
js = (ui / "stock-eqphotos.js").read_text(encoding="utf-8")
for fn in ("equipment_photo_add", "equipment_photo_main", "equipment_photo_delete", "equipment_photo_upload"):
    check(f"the screen calls {fn}", fn in js)
check("drag and drop", "ondrop" in js and "dataTransfer" in js)
check("a deletion is asked first", re.search(r"await ask\([^)]*фото", js, re.I) is not None)
card = (ui / "stock-eqcard.js").read_text(encoding="utf-8")
check("the card draws the gallery", "eqGalleryHtml(" in card and "eqGalleryWire(" in card)
check("the form of a new piece has its photos", "eqPhStrip" in card)
sec = (ui / "stock-eqsection.js").read_text(encoding="utf-8")
check("a line of a receipt has its photos", "eqPhStrip" in sec)
css = (ui / "styles-eqphotos.css").read_text(encoding="utf-8")
check("the dark theme of the gallery", 'data-theme="dark"' in css)
seen = {}
for f in sorted(ui.glob("*.js")):
    for m in re.finditer(r"^(?:const|let|class|(?:async\s+)?function)\s+([A-Za-z_$][\w$]*)", f.read_text(encoding="utf-8"), re.M):
        seen.setdefault(m[1], []).append(f.name)
dups = {k: v for k, v in seen.items() if len(v) > 1}
check("no global name declared twice in the screen scripts", not dups, dups)

print("\n".join("FAIL " + f for f in FAIL))
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
sys.exit(1 if FAIL else 0)
