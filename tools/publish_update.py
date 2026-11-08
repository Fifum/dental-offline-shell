"""Upload a signed update (installer exe + latest.json made by update_sign.py) to where programs look for it.

    python tools\\publish_update.py <folder> --dest D:\\updates-test              # a local / network folder (tests)
    python tools\\publish_update.py <folder> --bucket <name> [--prefix updates/]  # Yandex Object Storage (S3)
    python tools\\publish_update.py --save-keys                                   # store the S3 keys (DPAPI)

The exe goes first and latest.json last, so a program never sees a latest.json pointing to a missing file.
S3 keys: environment YC_ACCESS_KEY_ID / YC_SECRET_ACCESS_KEY, or saved once with --save-keys into
%USERPROFILE%\\.dental-desk-keys\\yc-s3.key (DPAPI). The bucket needs public read for these two files only.
The address for the program (brand.json → "update_url") is https://storage.yandexcloud.net/<bucket>/<prefix>latest.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import hashlib
import hmac
import json
import os
import shutil
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402

ENDPOINT = "storage.yandexcloud.net"
REGION = "ru-central1"
KEYS = Path(os.environ.get("DD_KEY_DIR") or Path.home() / ".dental-desk-keys") / "yc-s3.key"


def _keys():
    kid, secret = os.environ.get("YC_ACCESS_KEY_ID"), os.environ.get("YC_SECRET_ACCESS_KEY")
    if kid and secret:
        return kid, secret
    if KEYS.exists():
        j = json.loads(config.unprotect(KEYS.read_text(encoding="ascii")) or "{}")
        return j.get("id"), j.get("secret")
    sys.exit("Нет ключей Object Storage: python tools\\publish_update.py --save-keys")


def _sign(key, msg):
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def s3_put(bucket, key, data: bytes, ctype, kid, secret):
    """PUT one object with AWS Signature V4 (Yandex Object Storage speaks the S3 protocol)."""
    import requests
    now = dt.datetime.now(dt.timezone.utc)
    amz, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    host = f"{bucket}.{ENDPOINT}"
    path = "/" + urllib.parse.quote(key)
    sha = hashlib.sha256(data).hexdigest()
    headers = {"host": host, "x-amz-content-sha256": sha, "x-amz-date": amz, "content-type": ctype}
    signed = ";".join(sorted(headers))
    canon = "\n".join(["PUT", path, "", "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)), signed, sha])
    scope = f"{day}/{REGION}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canon.encode()).hexdigest()])
    k = _sign(_sign(_sign(_sign(("AWS4" + secret).encode(), day), REGION), "s3"), "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = f"AWS4-HMAC-SHA256 Credential={kid}/{scope}, SignedHeaders={signed}, Signature={sig}"
    r = requests.put(f"https://{host}{path}", data=data, headers=headers, timeout=600)
    if r.status_code >= 300:
        sys.exit(f"Ошибка загрузки {key}: {r.status_code} {r.text[:300]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--dest")
    ap.add_argument("--bucket")
    ap.add_argument("--prefix", default="updates/")
    ap.add_argument("--save-keys", action="store_true")
    a = ap.parse_args()
    if a.save_keys:
        kid = input("Идентификатор ключа: ").strip()
        secret = getpass.getpass("Секретный ключ: ").strip()
        KEYS.parent.mkdir(parents=True, exist_ok=True)
        KEYS.write_text(config.protect(json.dumps({"id": kid, "secret": secret})), encoding="ascii")
        print(f"Сохранено (зашифровано): {KEYS}")
        return 0
    if not a.folder:
        ap.error("укажите папку с latest.json")
    src = Path(a.folder)
    doc = json.loads((src / "latest.json").read_text(encoding="utf-8-sig"))
    exe = src / doc["file"]
    if not exe.exists() or exe.stat().st_size != doc["size"]:
        sys.exit("Установщик не совпадает с latest.json — подпишите заново (update_sign.py release)")
    if a.dest:
        dest = Path(a.dest)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(exe, dest / exe.name)
        tmp = dest / "latest.json.tmp"
        shutil.copy2(src / "latest.json", tmp)
        os.replace(tmp, dest / "latest.json")
        print(f"Готово: {dest / 'latest.json'}")
        return 0
    if not a.bucket:
        ap.error("укажите --dest или --bucket")
    kid, secret = _keys()
    prefix = a.prefix.strip("/") + "/" if a.prefix.strip("/") else ""
    s3_put(a.bucket, prefix + exe.name, exe.read_bytes(), "application/octet-stream", kid, secret)
    s3_put(a.bucket, prefix + "latest.json", (src / "latest.json").read_bytes(), "application/json", kid, secret)
    print(f"Готово: https://{ENDPOINT}/{a.bucket}/{prefix}latest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
