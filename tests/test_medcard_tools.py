"""Version 2.3 medical record tools: allergy check, sterilization journal, periodontal chart, patient files and X-rays."""
import base64
import io
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ["LOCALAPPDATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import allergy  # noqa: E402
import auth  # noqa: E402
import backup  # noqa: E402
import config  # noqa: E402
import db as dbm  # noqa: E402
import demo  # noqa: E402
import files  # noqa: E402
import perio  # noqa: E402
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


def raises(fn, *a, **k):
    try:
        fn(*a, **k)
    except ValueError as e:
        return str(e)
    return None


d = dbm.DB(); demo.ensure_demo(d, force=True)
a = Api(d, W()); demo.ensure_stock(a._stock)
lev = lambda r: [(w["level"], w["substance"]) for w in r]  # noqa: E731

# ================================================================ allergy
check("same substance is a stop", lev(allergy.check(["Лидокаин"], "Анестезия: лидокаин 2% 1,7 мл")) == [("stop", "лидокаин")])
check("Latin name counts", lev(allergy.check(["лидокаин"], "Sol. Lidocaini 2%")) == [("stop", "лидокаин")])
check("same group is a warning", lev(allergy.check(["Лидокаин"], "Ультракаин Д-С форте")) == [("warn", "ультракаин")])
check("other group is fine", allergy.check(["Лидокаин"], "Новокаин 2%")[:1] == [] or lev(allergy.check(["Лидокаин"], "Новокаин"))[0][0] != "stop")
check("penicillins", lev(allergy.check(["Пенициллин"], "Амоксиклав 875")) == [("warn", "амоксиклав")])
check("free-word allergy", lev(allergy.check(["Хлоргексидин биглюконат"], "Обработка хлоргексидином 0,05%"))[0][0] == "stop")
check("latex and rubber dam", lev(allergy.check(["Латекс"], "Наложен коффердам")) == [("warn", "латекс")])
check("no allergies, no warnings", allergy.check([], "лидокаин") == [] and allergy.check(["Лидокаин"], "") == [])
check("stops first", [w["level"] for w in allergy.check(["Лидокаин", "Артикаин"], "артикаин, лидокаин")][0] == "stop")
al = allergy.patient_allergies({"allergies": "Пенициллин", "chronic": "нет", "allergy_note": "нет"},
                               "Аллергологический анамнез не отягощён. Аллергия на йод.")
check("allergies from card and anamnesis", al == ["Пенициллин", "йод"], al)
check("negations ignored", allergy.patient_allergies({"allergies": "Не выявлено"}, "Аллергии отрицает.") == [])
pid_al = next(p["id"] for p in d.q("SELECT id FROM patients") if "Лидокаин" in str((d.patient(p["id"]) or {}).get("data", {}).get("allergies", "")))
r = a.allergy_check(pid_al, "Инфильтрационная анестезия лидокаин 2%")
check("api: allergy from the card", r["allergies"] == ["Лидокаин"] and r["warnings"][0]["level"] == "stop", r)
check("api: anamnesis adds", "латекс" in [x.lower() for x in a.allergy_check(pid_al, "", "Аллергия на латекс")["allergies"]])
vid = next(v["id"] for v in d.q("SELECT id, patient_id FROM visits") if v["patient_id"] == pid_al) if d.q("SELECT 1 AS x FROM visits WHERE patient_id=?", (pid_al,)) else None
if vid:
    check("visit shows the allergy", a.visit(vid)["allergies"] == ["Лидокаин"])

# ================================================================ sterilization
opt = a.steril_options()
check("autoclave from equipment", any("Автоклав" in s for s in opt["sterilizers"]), opt["sterilizers"])
check("needs sterilizer", "стерилизатор" in (raises(a.steril_save, {"chem": "ok"}) or "").lower())
check("needs an indicator", "индикатор" in (raises(a.steril_save, {"sterilizer": "А1"}) or ""))
check("bad temperature", "Температура" in (raises(a.steril_save, {"sterilizer": "А1", "chem": "ok", "temp": 900}) or ""))
check("bad date", raises(a.steril_save, {"sterilizer": "А1", "chem": "ok", "at": "08.11.2026"}) is not None)
auth.set_current_user({"id": 3, "role": "assistant", "name": "Ассистент Анна"})
c1 = a.steril_save({"sterilizer": "Автоклав № 1", "chem": "ok", "packs": 10, "load": "наборы", "at": "2026-11-08 09:00", "temp": "134", "minutes": 5})
auth.set_current_user(None)
c2 = a.steril_save({"sterilizer": "Автоклав № 1", "chem": "ok", "bio": "fail", "at": "2026-11-08 12:00"})
c3 = a.steril_save({"sterilizer": "Сухожар", "chem": "ok", "at": "2026-11-08 13:00", "method": "Воздушный (сухожар)"})
c4 = a.steril_save({"sterilizer": "Автоклав № 1", "chem": "ok", "at": "2027-01-02 09:00"})
check("numbering per sterilizer", (c1["cycle_no"], c2["cycle_no"], c3["cycle_no"]) == (1, 2, 1))
check("numbering restarts in a new year", c4["cycle_no"] == 1)
check("operator is the signed-in employee", c1["operator"] == "Ассистент Анна" and c1["temp"] == 134.0)
check("failed indicator is брак", c2["result"] == "брак" and c1["result"] == "годно")
lst = a.steril_list("2026-11-01", "2026-11-30")
check("journal for the month", lst["count"] == 3 and lst["failed"] == 1 and lst["packs"] == 10)
check("filter by sterilizer", a.steril_list("2026-11-01", "2026-11-30", "Сухожар")["count"] == 1)
check("indicator text", lst["rows"][-1]["chem_text"] == "соответствует")
e = a.steril_save({**c2, "bio": "ok"})
check("edit keeps the number, fixes the result", e["cycle_no"] == 2 and e["result"] == "годно")
check("delete", a.steril_delete(c3["id"]) and a.steril_list("2026-11-01", "2026-11-30")["count"] == 2)
check("sterilizers remembered", "Автоклав № 1" in a.steril_options()["sterilizers"])
check("assistant has the journal", "sterilization" in auth.ROLES["assistant"]["perms"])

# ================================================================ periodontal chart
pid = d.q("SELECT id FROM patients LIMIT 1")[0]["id"]
check("empty chart refused", "пустая" in (raises(a.perio_save, {"patient_id": pid, "data": {"teeth": {}}}) or ""))
check("value range", raises(a.perio_save, {"patient_id": pid, "data": {"teeth": {"16": {"pd": [3, 2, 40]}}}}) is not None)
check("unknown patient", raises(a.perio_save, {"patient_id": "x", "data": {"teeth": {"16": {"pd": [3]}}}}) is not None)
ch = a.perio_save({"patient_id": pid, "date": "2026-11-01", "doctor_id": "", "note": "пародонтит средней степени",
                   "data": {"teeth": {"16": {"pd": [3, 2, 4, 5, 6, 3], "rec": [1, 0, 1], "bop": [1, 0, 0, 0, 1, 0], "mob": 1, "furc": 2},
                                      "17": {"missing": True}, "55": {"pd": [1]}, "26": {"pd": [2, 2, 2, 2, 2, 2]}}}})
check("chart saved, milk tooth dropped", sorted(ch["data"]["teeth"]) == ["16", "17", "26"], ch["data"]["teeth"].keys())
s = ch["stats"]
check("stats", s["teeth"] == 2 and s["sites"] == 12 and s["mean_pd"] == 2.9 and s["pd6"] == 1 and s["bop"] == 17, s)
check("CAL adds recession", s["mean_cal"] == 3.1, s)
ch2 = a.perio_save({"patient_id": pid, "date": "2026-11-08", "data": {"teeth": {"16": {"pd": [2, 2, 3, 3, 3, 2]}}}})
lst = a.perio_list(pid)
check("list newest first", [x["id"] for x in lst] == [ch2["id"], ch["id"]] and lst[0]["stats"]["mean_pd"] == 2.5)
check("patient count", a.patient(pid)["perio_count"] == 2)
up = a.perio_save({**ch2, "note": "контроль"})
check("update", up["id"] == ch2["id"] and up["note"] == "контроль")
check("delete chart", a.perio_delete(ch2["id"]) and len(a.perio_list(pid)) == 1)
cmds = a.perio_parse("Зуб шестнадцать три два четыре кровоточивость, нёбная два два три. Подвижность один. Следующий. Зуб 38 отсутствует")
check("voice: tooth and values", cmds[:4] == [{"t": "tooth", "v": "16"}, {"t": "val", "v": 3}, {"t": "val", "v": 2}, {"t": "val", "v": 4}], cmds[:4])
check("voice: bleeding, side, mobility, next, missing", [c["t"] for c in cmds[4:]] == ["bop", "side", "val", "val", "val", "mob", "next", "tooth", "missing"], cmds[4:])
check("voice: digits glued together", [c["v"] for c in perio.parse_voice("324") if c["t"] == "val"] == [3, 2, 4])
check("voice: recession mode and furcation", [c for c in perio.parse_voice("рецессия один ноль один фуркация два") if c["t"] in ("mode", "furc")]
      == [{"t": "mode", "v": "rec"}, {"t": "furc", "v": 2}])
check("voice: two-digit depth", perio.parse_voice("десять")[0] == {"t": "val", "v": 10} and perio.parse_voice("12")[0] == {"t": "val", "v": 12})

# ================================================================ files and X-rays
from PIL import Image  # noqa: E402


def img_bytes(fmt, size=(640, 480), color=128):
    b = io.BytesIO()
    Image.new("L" if fmt != "JPEG" else "RGB", size, color if fmt != "JPEG" else (color, 90, 60)).save(b, fmt)
    return b.getvalue()


def dicom_bytes(study="20261105", mono1=False):
    import numpy as np
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.3"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset("x", {}, file_meta=meta, preamble=b"\0" * 128)
    ds.Modality, ds.StudyDate, ds.Manufacturer = "IO", study, "TestVisio"
    ds.PhotometricInterpretation = "MONOCHROME1" if mono1 else "MONOCHROME2"
    arr = (np.arange(300 * 200).reshape(200, 300) % 4096).astype("uint16")
    ds.Rows, ds.Columns = arr.shape
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation, ds.SamplesPerPixel = 16, 12, 11, 0, 1
    ds.PixelData = arr.tobytes()
    out = io.BytesIO()
    ds.save_as(out, enforce_file_format=True)
    return out.getvalue()


b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
f1 = a.file_add(pid, "фото до.jpg", "data:image/jpeg;base64," + b64(img_bytes("JPEG")), {"kind": "photo", "tooth": "11"})
check("jpeg stored", f1["ext"] == ".jpg" and f1["kind"] == "photo" and f1["width"] == 640 and f1["tooth"] == "11")
f2 = a.file_add(pid, "OPG.tif", b64(img_bytes("TIFF", (900, 400))))
check("tiff gets a viewable copy", a.file_get(f2["id"])["mime"] == "image/png" and f2["height"] == 400)
f3 = a.file_add(pid, "IMG0001", b64(dicom_bytes()))
check("dicom recognised without extension", f3["ext"] == ".dcm" and f3["kind"] == "xray" and f3["taken_at"] == "2026-11-05", f3)
check("dicom maker kept", f3["meta"].get("Manufacturer") == "TestVisio")
check("dicom viewable", a.file_get(f3["id"])["url"].startswith("data:image/png;base64,"))
f4 = a.file_add(pid, "neg.dcm", b64(dicom_bytes("20261101", mono1=True)))
check("MONOCHROME1 dicom", f4["width"] == 300 and f4["height"] == 200)
f5 = a.file_add(pid, "согласие.pdf", b64(b"%PDF-1.4 test"))
check("pdf kept as document", f5["kind"] == "doc" and a.file_get(f5["id"], "orig")["mime"] == "application/pdf")
check("pdf has no thumbnail", f5["id"] not in a.file_thumbs([f5["id"]]))
check("duplicate detected", a.file_add(pid, "копия.jpg", b64(img_bytes("JPEG"))).get("duplicate") is True)
check("wrong type refused", "Можно добавить" in (raises(a.file_add, pid, "virus.exe", b64(b"MZ" * 100)) or ""))
check("empty refused", raises(a.file_add, pid, "a.png", "") is not None)
check("too large refused", "МБ" in (raises(a.file_add, pid, "big.png", b64(b"0" * (files.MAX_BYTES + 1))) or ""))
check("unknown patient refused", raises(a.file_add, "nope", "a.png", b64(img_bytes("PNG"))) is not None)
lst = a.files_list(pid)
check("list", len(lst) == 5 and all("kind_text" in x for x in lst))
check("thumbnails", set(a.file_thumbs([f1["id"], f2["id"], f3["id"]])) == {f1["id"], f2["id"], f3["id"]})
check("patient count", a.patient(pid)["files_count"] == 5)
u = a.file_update(f2["id"], {"title": "ОПТГ", "kind": "xray", "tooth": "", "taken_at": "2026-10-30", "note": "до лечения"})
check("update", u["title"] == "ОПТГ" and u["kind"] == "xray" and u["taken_at"] == "2026-10-30")
check("delete moves to _deleted", a.file_delete(f5["id"]) and any(p.name.startswith(f5["id"]) for p in (files.root() / "_deleted").iterdir()))
check("deleted hidden", f5["id"] not in [x["id"] for x in a.files_list(pid)] and raises(a.file_get, f5["id"]) is not None)

# visiograph folder
check("relative inbox refused", raises(a.files_settings_save, {"inbox": "images"}) is not None)
inbox = Path(tempfile.mkdtemp())
(inbox / "sub").mkdir()
(inbox / "a1.png").write_bytes(img_bytes("PNG", color=40))
(inbox / "sub" / "a2.dcm").write_bytes(dicom_bytes("20261108"))
(inbox / "notes.txt").write_text("x")
old = inbox / "old.png"
old.write_bytes(img_bytes("PNG", color=70))
t = (datetime.now() - timedelta(days=10)).timestamp()
os.utime(old, (t, t))
check("inbox setting", a.files_settings_save({"inbox": str(inbox)})["inbox"] == str(inbox))
ib = a.files_inbox()
names = sorted(Path(x["name"]).name for x in ib["rows"])
check("new images found (subfolders too), old and text skipped", names == ["a1.png", "a2.dcm"], names)
check("inbox thumbnails", all(x["thumb"] and x["thumb"].startswith("data:image/jpeg") for x in ib["rows"]))
imp = a.files_inbox_import(pid, [x["name"] for x in ib["rows"]], {"tooth": "36"})
check("imported as X-rays with the tooth", len(imp) == 2 and all(x["kind"] == "xray" and x["tooth"] == "36" for x in imp))
check("imported ones leave the list", a.files_inbox()["rows"] == [])
check("originals untouched", (inbox / "a1.png").exists())
check("unknown inbox file refused", raises(a.files_inbox_import, pid, [str(inbox / "nope.png")]) is not None)
a.files_settings_save({"inbox": str(inbox / "missing")})
check("missing inbox folder reported", "недоступна" in (a.files_inbox()["error"] or ""))

# backups mirror the files to the second folder
drive = Path(tempfile.mkdtemp())
backup.save_settings({"extra_dir": str(drive)})
backup.make("manual")
mirror = drive / backup.EXTRA_SUBDIR / "files"
check("files mirrored to the flash drive", mirror.is_dir() and any(p.name.startswith(f3["id"]) for p in mirror.rglob("*")))
check("deleted files not mirrored", not any("_deleted" in p.parts for p in mirror.rglob("*")))

# ================================================================ permissions
for m in ("allergy_check", "steril_options", "steril_list", "steril_save", "steril_delete", "perio_list", "perio_get", "perio_save",
          "perio_delete", "perio_parse", "perio_voice", "files_list", "file_thumbs", "file_get", "file_add", "file_update",
          "file_delete", "files_inbox", "files_inbox_import", "files_settings", "files_settings_save"):
    check(f"perm {m}", m in auth.METHOD_PERMS)
for m in ("steril_save", "steril_delete", "perio_save", "perio_delete", "file_add", "file_update", "file_delete", "files_inbox_import"):
    check(f"audited {m}", m in auth.AUDITED)
check("sterilization permission listed", "sterilization" in auth.PERM_KEYS)

print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for x in FAIL:
    print(" -", x)
sys.exit(1 if FAIL else 0)
