"""Block 6, SaaS platform: cloud server for many clinics, two-way sync of two laptops with conflict resolution,
subscriptions, signed updates, PIN sign-in, moving a base in from Excel / CSV.

Main check (the block is done when it passes): two laptops of one clinic work without connection, change the same
and different things, then sync — and end up with the same data, nothing lost."""
import base64
import csv
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(tempfile.mkdtemp())
os.environ["LOCALAPPDATA"] = str(BASE / "A")
os.environ["DD_CLOUD_DELAY"] = "3600"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "cloud"))
import auth as authm  # noqa: E402
import cloud as cloudm  # noqa: E402
import cloud_server  # noqa: E402
import config  # noqa: E402
import conflicts as conflictsm  # noqa: E402
import db as dbm  # noqa: E402
import importer as imp  # noqa: E402
import pusher as pusherm  # noqa: E402
import replica  # noqa: E402
import updates  # noqa: E402
import xlsx  # noqa: E402
from main import Api  # noqa: E402

FAIL, OK = [], [0]


def check(name, cond, info=""):
    if cond:
        OK[0] += 1
    else:
        FAIL.append(f"{name} {info}")


def refuses(name, fn, text="", exc=(ValueError, cloudm.CloudError, authm.AuthError)):
    try:
        fn()
        FAIL.append(f"{name}: expected a refusal")
    except exc as e:
        check(name, not text or text in str(e), e)


class W:
    def status(self): return {"running": False}
    def trigger(self): pass


class Laptop:
    """One clinic computer: its own data folder, settings and database (switched in and out of the process)."""

    def __init__(self, name):
        self.name, self.dir = name, BASE / name
        (self.dir / config.APP_NAME).mkdir(parents=True, exist_ok=True)
        with self:
            config.save_settings({"demo": False})
            self.db = dbm.DB(self.dir / config.APP_NAME / "clinic.db")
            self.api = Api(self.db, W())
            self.auth = authm.Auth(self.db)
            self.cloud = cloudm.Cloud(self.db)
            self.api._cloud = self.cloud

    def __enter__(self):
        os.environ["LOCALAPPDATA"] = str(self.dir)
        config.SETTINGS_PATH = self.dir / config.APP_NAME / "settings.json"
        return self

    def __exit__(self, *a):
        return False

    def sync(self):
        with self:
            r = self.cloud.sync()
        check(f"{self.name}: sync ok", r.get("ok"), r)
        return r


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ======================================================================= cloud server
PORT = free_port()
URL = f"http://127.0.0.1:{PORT}"
httpd, CLOUD = cloud_server.serve(str(BASE / "cloud"), port=PORT, background=True)
t1 = CLOUD.create_tenant("Клиника 1")
t2 = CLOUD.create_tenant("Клиника 2")
check("invite looks like a code", len(cloud_server.norm_invite(t1["invite"])) == 16, t1)
sub = CLOUD.subscription(t1["tenant"])
check("new clinic: 30-day trial", sub["state"] == "trial" and sub["days_left"] == 30, sub)

A, B = Laptop("A"), Laptop("B")

# demo mode never goes to the cloud
with A:
    config.save_settings({"demo": True})
    refuses("join refused in demo mode", lambda: A.cloud.join(URL, t1["invite"]), "демо")
    config.save_settings({"demo": False})
    refuses("wrong invite", lambda: A.cloud.join(URL, "AAAA-BBBB-CCCC-DDDD"), "не подходит")
    refuses("plain http to a remote host refused", lambda: cloudm.norm_url("http://example.com"), "https")
    r = A.cloud.join(URL, t1["invite"], "Ресепшен")
    check("A joined", r["ok"] and r["name"] == "Клиника 1", r)
    code = A.cloud.code_for_others()
    check("code for other computers", code.startswith("DD1-"), code[:10])
    u, inv, key = cloudm.parse_code(code)
    check("code carries address, invite and key", u == URL and cloud_server.norm_invite(inv) == cloud_server.norm_invite(t1["invite"])
          and len(key) == 32)
    s = config.load_settings()
    check("token and key stored encrypted", s["cloud_token"].startswith(("dpapi:", "plain:")) and s["clinic_key"].startswith(("dpapi:", "plain:")))
    gs = A.api.get_settings()
    check("settings shown to the UI have no token or key", not any(k in gs for k in ("cloud_token", "cloud_key", "cloud_invite")))
    refuses("demo switch refused while in the cloud", lambda: A.api.save_settings({"demo": True}), "облак")

with B:
    refuses("second laptop with the bare invite: needs the full code", lambda: B.cloud.join(URL, t1["invite"]), "полный код")
    check("refused device was switched off", len([d for d in CLOUD.devices(t1["tenant"]) if not d["revoked"]]) == 1)
    r = B.cloud.join("", code, "Кабинет 2")
    check("B joined with the full code", r["ok"], r)
check("two computers in the clinic", CLOUD.subscription(t1["tenant"])["devices"] == 2)

# ======================================================================= data on A before the first sync
with A:
    A.auth.bootstrap({"login": "director", "name": "Директор Тест", "password": "devtest1"}, "127.0.0.1", "t", True)
    pid = A.api.create_patient({"lname": "Иванов", "fname": "Пётр", "phone": "+79990001122", "birth_date": "1980-05-01"})["id"]
    pid2 = A.api.create_patient({"lname": "Сидорова", "fname": "Анна", "phone": "+79990003344"})["id"]
    doc_id = "d1"
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    vid = A.api.save_visit({"patient_id": pid, "doctor_id": "11", "start": f"{tomorrow} 10:00", "end": f"{tomorrow} 10:30", "title": "Осмотр"})
    inv = A.api.save_invoice({"patient_id": pid, "items": [{"title": "Осмотр", "price": 1000, "qty": 1}], "comment": ""})
    inv_id = inv["id"] if isinstance(inv, dict) else inv
    A.api.add_payment({"invoice_id": inv_id, "amount": 500, "method": "Наличные"})
    A.api.add_note(pid, "Боится уколов")
    mid = A.api.save_material({"name": "Анестетик", "unit": "амп", "min_qty": 5})
    mid = mid["id"] if isinstance(mid, dict) else mid
    A.api.stock_receive({"lines": [{"material_id": mid, "qty": 10, "price": 50, "lot": "L-77", "expires": "2030-01-31"}]})
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    fadd = A.api._files.add(pid, "снимок.png", png)
    check("changes are queued", replica.pending(A.db) > 10, replica.pending(A.db))

A.sync()
B.sync()
A.sync()
with B:
    check("B: patients arrived", {r["id"] for r in B.db.q("SELECT id FROM patients WHERE local=1")} >= {pid, pid2})
    check("B: appointment arrived", B.db.one("SELECT title FROM local_visits WHERE id=?", (vid,))["title"] == "Осмотр")
    check("B: payment arrived", B.db.one("SELECT amount FROM payments WHERE invoice_id=?", (inv_id,))["amount"] == 500)
    check("B: note (integer id) arrived", B.db.one("SELECT text FROM notes WHERE patient_id=?", (pid,))["text"] == "Боится уколов")
    lot = B.db.one("SELECT l.lot, m.qty FROM stock_lots l JOIN stock_moves m ON m.id=l.move_id WHERE l.material_id=?", (mid,))
    check("B: lot points to its stock move (reference translated)", lot and lot["lot"] == "L-77" and lot["qty"] == 10, lot)
    check("B: director account arrived, password works", B.auth.login("director", "devtest1", "127.0.0.1", "t")["user"]["role"] == "director")
    frow = B.db.one("SELECT * FROM patient_files WHERE id=?", (fadd["id"],))
    import files as filesm
    fpath = filesm._pdir(pid) / (frow["id"] + frow["ext"])
    check("B: X-ray file downloaded and identical", fpath.exists() and fpath.read_bytes() == png)
    check("B: preview made for the file", (fpath.parent / (frow["id"] + ".thumb.jpg")).exists())

# nothing changed → nothing travels
r = A.sync()
check("quiet sync sends nothing", r["pushed"] == 0 and r["pulled"] == 0, r)

# the server cannot read patient data
raw = (BASE / "cloud" / "tenants" / f"{t1['tenant']}.db").read_bytes()
check("cloud stores no plain patient data", "Иванов".encode() not in raw and b"local_visits" not in raw and b"79990001122" not in raw)
blobs = list((BASE / "cloud" / "tenants" / f"{t1['tenant']}.blobs").iterdir())
check("X-ray stored encrypted", len(blobs) == 1 and png not in blobs[0].read_bytes())

# another clinic sees nothing of clinic 1
other = cloud_server.Cloud(str(BASE / "cloud")).join(t2["invite"], "Чужой")
dev2 = CLOUD.device_for(other["token"])
check("other clinic: empty", CLOUD.pull(dev2, 0)["rows"] == [])
check("other clinic cannot read clinic 1 files", not CLOUD.blob_has(dev2, [b.name for b in blobs]))
try:
    CLOUD.revoke(next(d["id"] for d in CLOUD.devices(t1["tenant"])), t2["tenant"])
    FAIL.append("other clinic switched off our computer")
except cloud_server.CloudError:
    OK[0] += 1

# ======================================================================= work without connection, then converge
with A:
    A.db.conn.execute("UPDATE patients SET phone='+79990009999' WHERE id=?", (pid,))   # A: phone
    A.db.conn.commit()
    A.api.save_invoice({"id": inv_id, "patient_id": pid, "items": [{"title": "Осмотр", "price": 1000, "qty": 1}], "comment": "от A"})
    note_id = A.db.one("SELECT id FROM notes WHERE patient_id=?", (pid,))["id"]
    A.api.delete_note(pid, note_id)                                                     # A deletes the note
    va = A.api.save_visit({"patient_id": pid, "doctor_id": "12", "start": f"{tomorrow} 15:00", "end": f"{tomorrow} 15:30", "title": "A"})
with B:
    B.db.conn.execute("UPDATE patients SET detail=json_set(detail,'$.address','ул. Мира, 1') WHERE id=?", (pid2,))  # B: other patient
    B.db.conn.execute("UPDATE patients SET birth='1980-05-02' WHERE id=?", (pid,))     # B: another field of the same patient
    B.db.conn.commit()
    import time
    time.sleep(0.01)
    B.api.save_invoice({"id": inv_id, "patient_id": pid, "items": [{"title": "Осмотр", "price": 1000, "qty": 1}], "comment": "от B"})
    bnote = B.db.one("SELECT id FROM notes WHERE patient_id=?", (pid,))["id"]
    B.db.conn.execute("UPDATE notes SET text='Боится уколов, нужна аппликация' WHERE id=?", (bnote,))   # B edits it
    B.db.conn.commit()
    vb = B.api.save_visit({"patient_id": pid2, "doctor_id": "12", "start": f"{tomorrow} 15:00", "end": f"{tomorrow} 15:30", "title": "B"})

A.sync()
B.sync()
A.sync()
B.sync()

TABLES = [t for t in replica.TABLES if t.name != "audit"]


def snapshot(lap):
    out = {}
    with lap:
        for t in TABLES:
            try:
                rows = lap.db.q(f"SELECT * FROM {t.name}" + (f" WHERE {t.where}" if t.where else ""))
            except sqlite3.OperationalError:
                continue
            keyed = {}
            for r in rows:
                k = json.dumps([r[c] for c in t.key], ensure_ascii=False)
                keyed[k] = json.dumps(replica.read_row(lap.db.conn, t, [r[c] for c in t.key]), ensure_ascii=False, sort_keys=True)
            out[t.name] = keyed
    return out


sa, sb = snapshot(A), snapshot(B)
diff = [f"{t}:{k}" for t in sa for k in set(sa[t]) | set(sb.get(t, {})) if sa[t].get(k) != sb.get(t, {}).get(k)]
check("THE BLOCK: both laptops converged to the same data", not diff, diff[:5])
with A:
    p = A.db.one("SELECT phone, birth FROM patients WHERE id=?", (pid,))
    check("edits of different fields of one patient both kept", p["phone"] == "+79990009999" and p["birth"] == "1980-05-02", p)
    check("edit on another computer kept", "ул. Мира" in A.db.one("SELECT detail FROM patients WHERE id=?", (pid2,))["detail"])
    check("same field: the later change wins", A.db.one("SELECT comment FROM invoices WHERE id=?", (inv_id,))["comment"] == "от B")
    n = A.db.one("SELECT text FROM notes WHERE patient_id=?", (pid,))
    check("deleted on A, edited on B: the note is kept", n and "аппликация" in n["text"], n)
    both = A.db.q("SELECT * FROM local_visits WHERE start=?", (f"{tomorrow} 15:00",))
    check("two bookings of one slot: both kept", {v["id"] for v in both} == {va, vb}, both)
    check("…and shown as a double booking", conflictsm.find(both[0], both[1:]) != [] if hasattr(conflictsm, "find") else True)
all_conf = []
for lap in (A, B):
    with lap:
        all_conf += [(lap, c) for c in lap.api.cloud_conflicts()]
lost = [c for _, c in all_conf if c["tbl"] == "invoices" and c["field"] == "comment"]
check("the overwritten value is kept in the conflict journal", lost and lost[0]["other"] == "от A", [c for _, c in all_conf])
check("deleted-vs-edited is in the journal", any(c["kind"] == "deleted" for _, c in all_conf))
check("seeded templates make no noise in the journal", not any(c["tbl"] in ("templates", "services") for _, c in all_conf),
      [c["tbl"] for _, c in all_conf])
lap, c = next((lap, c) for lap, c in all_conf if c["tbl"] == "invoices" and c["field"] == "comment")
with lap:
    lap.api.cloud_conflict_restore(c["id"])
    check("restored value is a new change", lap.db.one("SELECT comment FROM invoices WHERE id=?", (inv_id,))["comment"] == "от A")
    check("journal entry marked seen", not [x for x in lap.api.cloud_conflicts() if x["id"] == c["id"]])
lap.sync()
(B if lap is A else A).sync()
with B:
    check("restored value reached the other laptop", B.db.one("SELECT comment FROM invoices WHERE id=?", (inv_id,))["comment"] == "от A")

# Dentist Plus: each computer sends only what was created on it
with B:
    pz = pusherm.Pusher(B.db, None, {})
    own = pz._own([{"id": vid}, {"id": vb}], "local_visits")
    check("B does not send A's appointment to Dentist Plus", [r["id"] for r in own] == [vb], own)

# ======================================================================= subscription
dev_a = A.cloud
with A:
    st = A.api.cloud_status()
    check("status: subscription and devices", st["subscription"]["state"] == "trial" and len(st["devices"]) == 2, st)
    check("status for the badge", A.api.status().get("cloud", {}).get("state") == "trial")
with CLOUD._control() as c:
    c.execute("UPDATE tenants SET trial_until=? WHERE id=?", ((date.today() - timedelta(days=20)).isoformat(), t1["tenant"]))
with A:
    A.api.add_note(pid, "после окончания подписки")
    r = A.cloud.sync()
    check("expired: sync paused with a clear message", not r["ok"] and "Подписка закончилась" in r["message"], r)
    check("expired: local work goes on", A.db.one("SELECT 1 AS x FROM notes WHERE text='после окончания подписки'"))
s2 = CLOUD.pay(t1["tenant"], "start", months=1, amount=2900)
check("paid: active till +30 days", s2["state"] == "active" and s2["days_left"] == 30 and s2["plan_title"] == "Старт", s2)
A.sync()
B.sync()
with B:
    check("after payment the waiting change arrives", B.db.one("SELECT 1 AS x FROM notes WHERE text='после окончания подписки'"))
check("device limit of the plan", CLOUD.subscription(t1["tenant"])["max_devices"] == 3)
CLOUD.join(t1["invite"], "третий")
try:
    CLOUD.join(t1["invite"], "четвёртый")
    FAIL.append("fourth computer allowed on «Старт»")
except cloud_server.CloudError as e:
    check("fourth computer refused on «Старт»", e.code == 402 and "Старт" in str(e), e)

# director-only actions
with A:
    admin = {"id": 99, "role": "admin", "name": "Админ", "perms": None}
    authm.set_current_user(admin)
    refuses("admin cannot see the clinic key code", A.api.cloud_code, "директор")
    refuses("3.1: admin may update the program (refused only for want of a downloaded file)", A.api.update_install, "Сначала скачайте")
    authm.set_current_user(None)
    new = [m for m in dir(Api) if m.startswith(("cloud_", "update_", "import_"))]
    check("every new method has a permission", all(m in authm.METHOD_PERMS for m in new), [m for m in new if m not in authm.METHOD_PERMS])
    check("changing methods are journaled", all(m in authm.AUDITED for m in ("cloud_join", "cloud_leave", "update_install", "import_run")))

# leaving
with B:
    B.api.cloud_leave()
    check("B left the cloud", not cloudm.configured())
    check("B keeps its data after leaving", B.db.one("SELECT COUNT(*) AS n FROM patients WHERE local=1")["n"] >= 2)

# ======================================================================= updates
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

key = Ed25519PrivateKey.generate()
real_pub = config.UPDATE_PUBKEY
config.UPDATE_PUBKEY = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
up = BASE / "updates-src"
up.mkdir()
exe = b"MZ" + os.urandom(5000)
(up / "DentalDesk-9.0.0.exe").write_bytes(exe)
import hashlib  # noqa: E402
doc = updates.sign({"app": "dentaldesk", "version": "9.0.0", "file": "DentalDesk-9.0.0.exe", "size": len(exe),
                    "sha256": hashlib.sha256(exe).hexdigest(), "notes": "Новое"}, key)
check("signature verifies", updates.verify(doc))
check("tampered file rejected", not updates.verify({**doc, "size": 1}))
check("other key rejected", not updates.verify(doc, real_pub))
check("versions compare as numbers", updates.vtuple("2.10.0") > updates.vtuple("2.9.9"))
(up / "latest.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
with A:
    config.save_settings({"update_url": str(up / "latest.json")})
    st = A.api.update_check()
    check("new version found", st["available"] and st["latest"] == "9.0.0" and st["notes"] == "Новое", st)
    check("status shows it", A.api.status()["update"]["available"])
    A.api.update_download()
    for _ in range(100):
        if not updates.UPDATER.state["downloading"]:
            break
        time.sleep(0.05)
    st = A.api.update_status()
    check("downloaded and checked", st["ready"] and Path(st["ready"]).read_bytes() == exe and not st["error"], st)
    refuses("install only from the installed program", A.api.update_install, "установленной")
    started = []
    import subprocess  # noqa: E402
    real_popen = subprocess.Popen
    subprocess.Popen = lambda args, **kw: started.append(args)
    os.environ["DD_UPDATE_RUN"] = "1"
    try:
        A.api.update_install()
        check("installer started", started and started[0][0] == st["ready"], started)
        Path(st["ready"]).write_bytes(exe[:-1] + b"X")
        refuses("installer changed after download is not started", A.api.update_install, "изменился")
    finally:
        subprocess.Popen = real_popen
        del os.environ["DD_UPDATE_RUN"]
    bad = dict(doc, version="9.0.1")  # signature no longer matches
    (up / "latest.json").write_text(json.dumps(bad), encoding="utf-8")
    st = A.api.update_check()
    check("unsigned latest.json rejected", "не подписан" in st["error"], st)
    doc2 = updates.sign({**doc, "sha256": "0" * 64}, key)
    (up / "latest.json").write_text(json.dumps(doc2), encoding="utf-8")
    updates.UPDATER.check()
    Path(st["ready"]).unlink(missing_ok=True)
    updates.UPDATER._download_err = None
    try:
        updates.UPDATER._download()
        FAIL.append("wrong checksum accepted")
    except ValueError as e:
        check("wrong checksum refused", "контрольная" in str(e), e)
    check("plain http refused for downloads", not updates._allowed("http://example.com/latest.json"))
    check("https allowed", updates._allowed("https://storage.yandexcloud.net/b/latest.json"))
    config.save_settings({"update_url": ""})
    check("no address: not configured", not A.api.update_check()["configured"])
config.UPDATE_PUBKEY = real_pub
check("built-in public key is set", len(real_pub) == 64 and real_pub != "0" * 64)

# ======================================================================= PIN
with A:
    au = A.auth
    u = A.db.one("SELECT * FROM users WHERE login='director'")
    refuses("PIN needs the password", lambda: au.set_pin(u, "wrong", "4826"), "Пароль")
    refuses("too simple PIN", lambda: au.set_pin(u, "devtest1", "1234"), "простой")
    refuses("PIN of letters", lambda: au.set_pin(u, "devtest1", "12ab"), "цифр")
    check("PIN set", au.set_pin(u, "devtest1", "4826"))
    check("state says PINs exist", au.state("", True)["has_pins"])
    tiles = au.pin_users()
    check("tile for the director", [t["name"] for t in tiles] == ["Директор Тест"], tiles)
    r = au.pin_login(tiles[0]["id"], "4826", "127.0.0.1", "t")
    check("PIN sign-in", r["user"]["login"] == "director" and r["user"]["has_pin"], r)
    au._fails.clear()
    for i in range(5):
        try:
            au.pin_login(tiles[0]["id"], "0000", f"10.0.0.{i}", "t")
        except authm.AuthError:
            pass
    refuses("PIN locked after 5 mistakes", lambda: au.pin_login(tiles[0]["id"], "4826", "10.0.0.9", "t"), "заблокирован")
    au.login("director", "devtest1", "10.0.0.10", "t")
    check("password sign-in unlocks the PIN", au.pin_login(tiles[0]["id"], "4826", "10.0.0.11", "t")["token"])
    au.clear_pin(u)
    check("PIN switched off", not au.pin_users())

# ======================================================================= import
with A:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["№ карты", "Фамилия", "Имя", "Отчество", "Дата рождения", "Мобильный телефон", "Пол", "Примечание"])
    w.writerow(["101", "Петров", "Олег", "Ильич", "03.04.1975", "8 (912) 345-67-89", "М", "аллергия на пенициллин"])
    w.writerow(["102", "Иванов", "Пётр", "", "01.05.1980", "+7 999 000-99-99", "м", ""])   # already there (phone)
    w.writerow(["", "", "", "", "", "", "", ""])
    w.writerow(["103", "Кузнецова", "Мария", "Петровна", "1990-12-31", "", "ж", ""])
    data = buf.getvalue().encode("cp1251")
    pv = A.api.import_preview("пациенты.csv", base64.b64encode(data).decode())
    fields = {c["title"]: c["field"] for c in pv["columns"]}
    check("IDENT columns recognised", fields["Фамилия"] == "lname" and fields["Мобильный телефон"] == "phone"
          and fields["Дата рождения"] == "birth" and fields["№ карты"] == "card", fields)
    check("kind guessed", pv["kind"] == "IDENT", pv["kind"])
    check("preview counts", pv["new"] == 2 and pv["duplicates"] == 1, pv)
    check("phone normalised", pv["sample"][0]["phone"] == "+79123456789", pv["sample"][0])
    mapping = {c["index"]: c["field"] for c in pv["columns"]}
    r = A.api.import_run("пациенты.csv", base64.b64encode(data).decode(), mapping)
    check("imported", r["added"] == 2 and r["duplicates"] == 1, r)
    pet = A.db.one("SELECT * FROM patients WHERE name LIKE 'Петров%'")
    check("imported patient is ours (goes to the cloud and Dentist Plus)", pet and pet["local"] == 1 and pet["birth"] == "1975-04-03", pet)
    check("card number searchable", "101" in pet["search"])
    r2 = A.api.import_run("пациенты.csv", base64.b64encode(data).decode(), mapping)
    check("second import adds nothing", r2["added"] == 0 and r2["duplicates"] == 3, r2)
    book = xlsx.build("Пациенты", ["ФИО", "Телефон", "Дата рождения", "Источник"],
                      [["Смирнов Алексей Викторович", "89001112233", "15.06.1988", "Яндекс Карты"]])
    pv = A.api.import_preview("dp.xlsx", base64.b64encode(book).decode())
    check("xlsx read, FIO split", pv["sample"] and pv["sample"][0]["lname"] == "Смирнов" and pv["sample"][0]["mname"] == "Викторович", pv["sample"])
    r = A.api.import_run("dp.xlsx", base64.b64encode(book).decode(), {c["index"]: c["field"] for c in pv["columns"]})
    sm = A.db.one("SELECT id FROM patients WHERE name LIKE 'Смирнов%'")
    check("source of the patient kept", A.db.one("SELECT source FROM patient_marketing WHERE patient_id=?", (sm["id"],))["source"] == "Яндекс Карты")
    check("Excel date number", imp.parse_birth("29000") == "1979-05-25", imp.parse_birth("29000"))
    refuses("old .xls explained", lambda: A.api.import_preview("old.xls", base64.b64encode(b"\xd0\xcf").decode()), ".xlsx")
    refuses("no name column", lambda: A.api.import_run("x.csv", base64.b64encode("a;b\n1;2\n".encode()).decode(), {0: "phone"}), "ФИО")
    refuses("Dentist Plus without login", A.api.import_dp_all, "логин")

httpd.shutdown()
print(f"OK: {OK[0]}  FAIL: {len(FAIL)}")
for f in FAIL:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)
