"""Dev only: a fake «new version» for checking the update button in the preview.

Signs a dummy installer with a throwaway key (never the real one) and prints the public key for devserver:
    python tools\\dev_update_feed.py <folder> <version>
    set DD_UPDATE_PUBKEY=<printed key>  (devserver.py uses it instead of the built-in one)
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import updates  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: E402

out, ver = Path(sys.argv[1]), sys.argv[2]
out.mkdir(parents=True, exist_ok=True)
key = Ed25519PrivateKey.generate()
exe = b"MZ" + os.urandom(2 * 1024 * 1024)
name = f"DentalDesk-{ver}.exe"
(out / name).write_bytes(exe)
doc = updates.sign({"app": "dentaldesk", "version": ver, "file": name, "size": len(exe), "sha256": hashlib.sha256(exe).hexdigest(),
                    "date": "2026-11-08", "notes": "Тестовая версия для проверки кнопки «Обновить».\n- пункт 1\n- пункт 2"}, key)
(out / "latest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
print(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex())
