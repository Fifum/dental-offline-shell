"""Signing updates for the «Обновить» button (developer's computer only).

    python tools\\update_sign.py keygen                      # once: makes the signing key, prints the public key
    python tools\\update_sign.py release <installer.exe> --notes "release\\Что нового….txt" --out <folder>
    python tools\\update_sign.py verify <folder>\\latest.json
    python tools\\update_sign.py backup <file>               # a copy of the secret key (keep it offline!)

The secret key lives outside every repository: %USERPROFILE%\\.dental-desk-keys\\update-ed25519.key, encrypted
with Windows DPAPI (readable only under this Windows account). Without the key nobody can publish an update the
program would accept. Lose it — and the programs already installed can be updated only by hand once
(a new build with a new public key). So make a backup and keep it on a flash drive in a safe place.
`release` copies the installer into --out and writes latest.json next to it; upload both (publish_update.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import config  # noqa: E402
import updates  # noqa: E402

KEY_DIR = Path(os.environ.get("DD_KEY_DIR") or Path.home() / ".dental-desk-keys")
KEY_FILE = KEY_DIR / "update-ed25519.key"


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
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    target = out / exe.name
    if target.resolve() != exe.resolve():
        shutil.copy2(exe, target)
    data = target.read_bytes()
    doc = {"app": "dentaldesk", "version": ver, "file": exe.name, "size": len(data),
           "sha256": hashlib.sha256(data).hexdigest(), "date": date.today().isoformat(), "notes": notes[:4000]}
    doc = updates.sign(doc, key)
    (out / "latest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Готово: {out / 'latest.json'} (версия {ver}, {len(data) // 1024 // 1024} МБ)")


def verify(a):
    doc = json.loads(Path(a.file).read_text(encoding="utf-8-sig"))
    ok = updates.verify(doc)
    print("Подпись верна" if ok else "ПОДПИСЬ НЕВЕРНА")
    exe = Path(a.file).parent / doc.get("file", "")
    if ok and exe.exists():
        same = hashlib.sha256(exe.read_bytes()).hexdigest() == doc["sha256"]
        print("Файл установщика совпадает" if same else "ФАЙЛ УСТАНОВЩИКА НЕ СОВПАДАЕТ")
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
    s = sub.add_parser("verify")
    s.add_argument("file")
    a = ap.parse_args()
    return {"keygen": keygen, "backup": backup, "release": release, "verify": verify}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
