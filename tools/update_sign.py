"""Signing updates for the «Обновить» button (developer's computer only).

    python tools\\update_sign.py keygen                      # once: makes the signing key, prints the public key
    python tools\\update_sign.py release <installer.exe> --notes "release\\Что нового….txt" --out <folder>
    python tools\\update_sign.py verify <folder>\\latest.json
    python tools\\update_sign.py backup <file>               # a copy of the secret key (keep it offline!)
    python tools\\update_sign.py feed --github <owner/repo>  # once per clinic build: GitHub address + encryption key

The secret key lives outside every repository: %USERPROFILE%\\.dental-desk-keys\\update-ed25519.key, encrypted
with Windows DPAPI (readable only under this Windows account). Without the key nobody can publish an update the
program would accept. Lose it — and the programs already installed can be updated only by hand once
(a new build with a new public key). So make a backup and keep it on a flash drive in a safe place.
`release` copies the installer into --out and writes latest.json next to it; upload both (publish_update.py).

3.12 — updates «только изменения»: `release --app-zip build\\app.zip` takes the manifest of the new version from the
zip (pack_app.py put it there), signs its digest into latest.json and stores it: plain as
release\\manifests\\manifest-<version>.json (--manifests) and encrypted as manifest-<version>.bin next to latest.json, so
the next release finds it even on another computer (publish_update.py --prev-manifest). With --prev-manifest (the
manifest of the version the clinic has now) it also builds delta-<from>-<to>.bin: only the files that changed, plus
the new manifest; latest.json gets «delta» — from which version, the file, its size and SHA-256. Programs up to 3.11
do not know the field and keep downloading the whole file.

`feed` writes into app/brand.json (not in git) the address of a GitHub release feed and the AES key the clinic's
build decrypts its updates with (a copy of the key: %USERPROFILE%\\.dental-desk-keys\\update-aes.key, DPAPI - a
build without the same key cannot read the updates, so run `feed` again on a new computer to restore it).
With the key set, `release` stores the installer encrypted under a neutral name (update-<version>.bin) and
encrypts the notes, so a public repository shows neither the clinic's name nor its notes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import config  # noqa: E402
import manifest  # noqa: E402
import updates  # noqa: E402

DELTA_WORTH = 0.7  # a delta bigger than this share of the whole installer is not worth it: the whole file only

KEY_DIR = Path(os.environ.get("DD_KEY_DIR") or Path.home() / ".dental-desk-keys")
KEY_FILE = KEY_DIR / "update-ed25519.key"
AES_FILE = KEY_DIR / "update-aes.key"
BRAND_FILE = ROOT / "app" / "brand.json"


def _load_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    env = os.environ.get("DD_UPDATE_KEY_PEM")
    if env:
        return load_pem_private_key(Path(env).read_bytes(), None)
    if not KEY_FILE.exists():
        sys.exit(f"Нет ключа подписи {KEY_FILE}. Создайте: python tools\\update_sign.py keygen")
    raw = config.unprotect(KEY_FILE.read_text(encoding="ascii").strip())
    if not raw:
        sys.exit("Ключ подписи не расшифровался: он создан под другой учётной записью Windows")
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(raw))


def _pub_hex(key) -> str:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def keygen(_a):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    if KEY_FILE.exists():
        sys.exit(f"Ключ уже есть: {KEY_FILE}. Новый ключ сделает обновления старых программ невозможными.")
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    KEY_FILE.write_text(config.protect(raw), encoding="ascii")
    print(f"Ключ сохранён: {KEY_FILE}")
    print(f"Открытый ключ (вписать в app/config.py → UPDATE_PUBKEY): {_pub_hex(key)}")


def backup(a):
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
    dest = Path(a.file)
    if dest.exists():
        sys.exit("Файл уже существует")
    dest.write_bytes(_load_key().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    print(f"Копия секретного ключа: {dest}. Храните её отдельно от компьютера (флешка в сейфе) и никому не отправляйте.")


def zip_manifest(app_zip) -> dict:
    """The manifest inside build\\app.zip (pack_app.py), checked against the files of the zip."""
    with zipfile.ZipFile(app_zip) as z:
        try:
            m = json.loads(z.read(manifest.NAME).decode("utf-8"))
        except KeyError:
            sys.exit(f"В {app_zip} нет {manifest.NAME}: соберите программу заново (build.ps1)")
        if not manifest.valid(m):
            sys.exit(f"{manifest.NAME} в {app_zip} повреждён")
        sizes = {i.filename: i.file_size for i in z.infolist()}
    for rel, (size, _sha) in m["files"].items():
        if sizes.get(rel) != size:
            sys.exit(f"{app_zip}: файл {rel} не совпадает со списком файлов — соберите программу заново")
    return m


def make_delta(prev: dict, app_zip, out_zip) -> dict:
    """delta.json (the new manifest, what changed and what is gone) + files/<path> of every file that is new or
    differs from `prev`. Returns {changed, removed}."""
    new = zip_manifest(app_zip)
    changed = [rel for rel, v in new["files"].items() if list(prev["files"].get(rel) or []) != list(v)]
    removed = sorted(set(prev["files"]) - set(new["files"]))
    with zipfile.ZipFile(app_zip) as z, zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as d:
        d.writestr("delta.json", json.dumps({"app": manifest.APP, "from": prev["version"], "to": new["version"],
                                             "manifest": new, "changed": changed, "removed": removed}, ensure_ascii=False))
        for rel in changed:
            h = hashlib.sha256()
            with z.open(rel) as src, d.open("files/" + rel, "w") as dst:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    h.update(chunk)
                    dst.write(chunk)
            if h.hexdigest() != new["files"][rel][1]:
                sys.exit(f"{app_zip}: файл {rel} не совпадает со списком файлов — соберите программу заново")
    return {"changed": len(changed), "removed": len(removed)}


def release(a):
    exe = Path(a.exe)
    if not exe.exists():
        sys.exit(f"Нет файла {exe}")
    ver = a.version or (re.search(r"(\d+\.\d+\.\d+)", exe.name) or [None, config.VERSION])[1]
    notes = ""
    if a.notes:
        notes = Path(a.notes).read_text(encoding="utf-8-sig").strip()
    key = _load_key()
    if _pub_hex(key) != config.UPDATE_PUBKEY:
        sys.exit("Ключ подписи не совпадает с открытым ключом в app/config.py — программа отклонит такое обновление")
    app_zip, prev_file, keep_dir = (getattr(a, k, "") or "" for k in ("app_zip", "prev_manifest", "manifests"))
    new_m = zip_manifest(app_zip) if app_zip else None
    if new_m and new_m["version"] != ver:
        sys.exit(f"{app_zip} — сборка версии {new_m['version']}, а выпускается {ver}: соберите программу заново (build.ps1)")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("update-*.bin"), *out.glob("delta-*.bin"), *out.glob("delta-*.zip"), *out.glob("manifest-*.bin")]:
        old.unlink()
    aes = updates.enc_key()
    if aes:  # the clinic's build: encrypted installer under a neutral name, encrypted notes
        name = f"update-{ver}.bin"
        size, sha = updates.encrypt_file(exe, out / name, aes)
        doc = {"app": "dentaldesk", "version": ver, "file": name, "size": size, "sha256": sha, "enc": updates.ENC,
               "plain_size": exe.stat().st_size, "plain_sha256": updates._sha256(exe), "date": date.today().isoformat()}
        if notes:
            doc["notes_enc"] = updates.seal_text(notes[:updates.NOTES_MAX], aes)  # 3.11: whole, not 4000
    else:
        name = exe.name
        target = out / name
        if target.resolve() != exe.resolve():
            shutil.copy2(exe, target)
        data = target.read_bytes()
        doc = {"app": "dentaldesk", "version": ver, "file": name, "size": len(data),
               "sha256": hashlib.sha256(data).hexdigest(), "date": date.today().isoformat(), "notes": notes[:updates.NOTES_MAX]}
    extra = ""
    if new_m:  # 3.12: the list of files of this version — the next release builds its delta from it
        doc["manifest"] = manifest.digest(new_m)
        if aes:
            (out / f"manifest-{ver}.bin").write_text(updates.seal_text(json.dumps(new_m, ensure_ascii=False), aes,
                                                                       updates.MANIFEST_AAD), encoding="ascii")
        if keep_dir:
            Path(keep_dir).mkdir(parents=True, exist_ok=True)
            (Path(keep_dir) / f"manifest-{ver}.json").write_text(json.dumps(new_m, ensure_ascii=False), encoding="utf-8")
    if new_m and prev_file:
        prev = json.loads(Path(prev_file).read_text(encoding="utf-8"))
        if not manifest.valid(prev):
            sys.exit(f"{prev_file}: это не список файлов программы")
        if updates.vtuple(prev["version"]) >= updates.vtuple(ver) or prev["exe"] != new_m["exe"]:
            print(f"Дельта не нужна: прошлая версия {prev['version']} ({prev['exe']}), новая {ver} ({new_m['exe']})")
        else:
            dz = out / f"delta-{prev['version']}-{ver}.zip"
            info = make_delta(prev, app_zip, dz)
            if dz.stat().st_size > DELTA_WORTH * exe.stat().st_size:
                dz.unlink()
                print(f"Дельта от {prev['version']} почти как весь установщик — только полный файл")
            else:
                delta = {"from": prev["version"], "from_manifest": manifest.digest(prev), "files": info["changed"]}
                if aes:
                    dname = dz.with_suffix(".bin").name
                    dsize, dsha = updates.encrypt_file(dz, out / dname, aes)
                    delta.update(file=dname, size=dsize, sha256=dsha, plain_size=dz.stat().st_size,
                                 plain_sha256=updates._sha256(dz))
                    dz.unlink()
                else:
                    delta.update(file=dz.name, size=dz.stat().st_size, sha256=updates._sha256(dz))
                doc["delta"] = delta
                extra = (f"; только изменения от {prev['version']}: изменено файлов — {info['changed']}, "
                         f"{max(1, round(delta['size'] / 1048576))} МБ")
    doc = updates.sign(doc, key)
    (out / "latest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Готово: {out / 'latest.json'} (версия {ver}, {doc['size'] // 1024 // 1024} МБ{', зашифровано' if aes else ''}{extra})")


def feed(a):
    """GitHub address and the encryption key into app/brand.json (kept: the key already there or in the key folder)."""
    if not BRAND_FILE.exists():
        sys.exit(f"Нет {BRAND_FILE}: ключ шифрования нужен только сборке клиники")
    brand = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
    key = str(brand.get("update_key") or "")
    if not key and AES_FILE.exists():
        key = config.unprotect(AES_FILE.read_text(encoding="ascii").strip()) or ""
        if not key:
            sys.exit("Ключ шифрования не расшифровался: он создан под другой учётной записью Windows")
    made = not key
    if made:
        key = os.urandom(32).hex()
    if not AES_FILE.exists():
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        AES_FILE.write_text(config.protect(key), encoding="ascii")
    brand["update_key"] = key
    if a.github:
        brand["update_url"] = updates.github_feed(a.github)
    BRAND_FILE.write_text(json.dumps(brand, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(("Новый ключ шифрования создан" if made else "Ключ шифрования сохранён") + f": {BRAND_FILE} (копия: {AES_FILE})")
    if a.github:
        print(f"Адрес обновлений: {brand['update_url']}")
    print("Пересоберите программу: этот ключ и адрес войдут в новую сборку.")


def verify(a):
    doc = json.loads(Path(a.file).read_text(encoding="utf-8-sig"))
    ok = updates.verify(doc)
    print("Подпись верна" if ok else "ПОДПИСЬ НЕВЕРНА")
    exe = Path(a.file).parent / doc.get("file", "")
    if ok and exe.exists():
        same = updates._sha256(exe) == doc["sha256"]
        print("Файл установщика совпадает" if same else "ФАЙЛ УСТАНОВЩИКА НЕ СОВПАДАЕТ")
        ok = ok and same
    d = doc.get("delta")
    if ok and isinstance(d, dict):
        df = Path(a.file).parent / str(d.get("file") or "")
        same = df.exists() and updates._sha256(df) == d.get("sha256")
        print(f"Только изменения от {d.get('from')}: " + ("файл совпадает" if same else "ФАЙЛ НЕ СОВПАДАЕТ ИЛИ ЕГО НЕТ"))
        ok = ok and same
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    s = sub.add_parser("backup")
    s.add_argument("file")
    s = sub.add_parser("release")
    s.add_argument("exe")
    s.add_argument("--out", required=True)
    s.add_argument("--notes", default="")
    s.add_argument("--version", default="")
    s.add_argument("--app-zip", default="", help="build\\app.zip: the manifest of this version (3.12)")
    s.add_argument("--prev-manifest", default="", help="manifest of the version the clinic has now: build the delta")
    s.add_argument("--manifests", default="", help="folder to keep manifest-<version>.json for the next release")
    s = sub.add_parser("verify")
    s.add_argument("file")
    s = sub.add_parser("feed")
    s.add_argument("--github", default="")
    a = ap.parse_args()
    return {"keygen": keygen, "backup": backup, "release": release, "verify": verify, "feed": feed}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
