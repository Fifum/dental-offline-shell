"""Upload a signed update (installer exe + latest.json made by update_sign.py) to where programs look for it.

    python tools\\publish_update.py <folder> --dest D:\\updates-test              # a local / network folder (tests)
    python tools\\publish_update.py <folder> --bucket <name> [--prefix updates/]  # Yandex Object Storage (S3)
    python tools\\publish_update.py --save-keys                                   # store the S3 keys (DPAPI)
    python tools\\publish_update.py <folder> --github Fifum/dental-desk-updates   # a GitHub release (3.1, gh CLI)
    python tools\\publish_update.py --prev-manifest --github <repo> --manifests release\\manifests --out <file.json>

The exe goes first and latest.json last, so a program never sees a latest.json pointing to a missing file.
S3 keys: environment YC_ACCESS_KEY_ID / YC_SECRET_ACCESS_KEY, or saved once with --save-keys into
%USERPROFILE%\\.dental-desk-keys\\yc-s3.key (DPAPI). The bucket needs public read for these two files only.
The address for the program (brand.json → "update_url") is https://storage.yandexcloud.net/<bucket>/<prefix>latest.json.

GitHub (3.1): a public repository with nothing but releases. The release v<version> is made as a draft, gets the
encrypted installer and then latest.json, and only then becomes «latest» — the address the programs read
(update_sign.py feed --github <repo> puts it into brand.json) is .../releases/latest/download/latest.json.
The repository is created on first use (gh repo create --public). Only an encrypted installer is uploaded there:
the clinic's build carries the clinic's name (update_sign.py feed makes the key).

3.12: the release also carries the delta «только изменения» (delta-<from>-<to>.bin) and the encrypted list of files
of this version (manifest-<version>.bin), both before latest.json. --prev-manifest finds the list of files of the
version the clinic has now (the feed's current latest.json, signature checked): release\\manifests\\manifest-<v>.json,
or manifest-<v>.bin from that release — the next delta is built from it (publish-update.ps1).
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
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import config  # noqa: E402

ENDPOINT = "storage.yandexcloud.net"
REGION = "ru-central1"
VERIFY_WAIT_S = 120  # after publishing: how long to wait for GitHub to serve the new latest.json
VERIFY_EVERY_S = 5
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


def _gh(*args, check=True):
    gh = shutil.which("gh")
    if not gh:
        sys.exit("Нет GitHub CLI (gh): установите его и выполните gh auth login")
    r = subprocess.run([gh, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        sys.exit(f"gh {' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:500]}")
    return r


def assets(src: Path, doc: dict) -> list:
    """The files of a release next to latest.json: the whole installer, the delta, the list of files (3.12)."""
    out = [src / doc["file"]]
    d = doc.get("delta")
    if isinstance(d, dict) and d.get("file"):
        out.append(src / d["file"])
    m = src / f"manifest-{doc['version']}.bin"
    if m.exists():
        out.append(m)
    return out


def check_files(src: Path, doc: dict):
    exe = src / doc["file"]
    if not exe.exists() or exe.stat().st_size != doc["size"]:
        sys.exit("Установщик не совпадает с latest.json — подпишите заново (update_sign.py release)")
    d = doc.get("delta")
    if isinstance(d, dict):
        f = src / str(d.get("file") or "")
        if not f.exists() or f.stat().st_size != d.get("size"):
            sys.exit("Файл «только изменения» не совпадает с latest.json — подпишите заново (update_sign.py release)")


def prev_manifest(repo: str, keep_dir: Path, out: Path) -> int:
    """The list of files of the version the clinic has now — the delta of the new release is built from it.
    0 and `out` written, or 1: there is none (a release before 3.12, a new feed) — the update goes whole only."""
    import manifest
    import updates
    r = _gh("release", "view", "--repo", repo, "--json", "tagName", check=False)
    if r.returncode != 0:
        print(f"В {repo} ещё нет выпусков: обновление пойдёт только целиком")
        return 1
    tag = json.loads(r.stdout or "{}").get("tagName") or ""
    tmp = Path(out).parent / "prev-release"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if _gh("release", "download", tag, "--repo", repo, "--pattern", "latest.json", "--dir", str(tmp), "--clobber",
           check=False).returncode != 0 or not (tmp / "latest.json").exists():
        print(f"Не удалось скачать latest.json выпуска {tag}: обновление пойдёт только целиком")
        return 1
    doc = json.loads((tmp / "latest.json").read_text(encoding="utf-8-sig"))
    if not updates.verify(doc):
        print(f"latest.json выпуска {tag} не подписан разработчиком: обновление пойдёт только целиком")
        return 1
    ver, want = doc.get("version"), doc.get("manifest")
    if not want:
        print(f"У версии {ver} в ленте нет списка файлов (выпуск до 3.12): обновление пойдёт только целиком")
        return 1
    m = None
    local = Path(keep_dir) / f"manifest-{ver}.json"
    if local.exists():
        try:
            m = json.loads(local.read_text(encoding="utf-8"))
        except ValueError:
            m = None
        if not manifest.valid(m) or manifest.digest(m) != want:
            print(f"{local} не совпадает с подписанным списком версии {ver} — берём его из ленты")
            m = None
    if m is None:
        name = f"manifest-{ver}.bin"
        if _gh("release", "download", tag, "--repo", repo, "--pattern", name, "--dir", str(tmp), "--clobber",
               check=False).returncode != 0 or not (tmp / name).exists():
            print(f"В выпуске {tag} нет {name}: обновление пойдёт только целиком")
            return 1
        key = updates.enc_key()
        try:
            m = json.loads(updates.open_text((tmp / name).read_text(encoding="ascii").strip(), key, updates.MANIFEST_AAD))
        except Exception:  # noqa: BLE001 — another build's key, a damaged file
            print(f"{name} не расшифровался ключом этой сборки: обновление пойдёт только целиком")
            return 1
        if not manifest.valid(m) or manifest.digest(m) != want:
            print(f"{name} не совпадает с подписанным списком файлов версии {ver}: обновление пойдёт только целиком")
            return 1
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    Path(out).write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    print(f"Список файлов версии {ver}: {len(m['files'])} файлов — обновление будет и «только изменения»")
    return 0


def github_publish(src: Path, doc: dict, repo: str, allow_plain=False):
    import updates
    if not doc.get("enc") and not allow_plain:
        sys.exit("Установщик не зашифрован, а репозиторий обновлений публичный. Сначала: python tools\\update_sign.py feed "
                 f"--github {repo}, пересборка и update_sign.py release (или --allow-plain для сборки без названия клиники)")
    ver, tag = doc["version"], f"v{doc['version']}"
    if _gh("repo", "view", repo, "--json", "name", check=False).returncode != 0:
        _gh("repo", "create", repo, "--public", "--add-readme", "--description", "Dental Desk updates (signed, read by the program)")
        print(f"Создан публичный репозиторий {repo}")
    if _gh("release", "view", tag, "--repo", repo, check=False).returncode == 0:
        sys.exit(f"Релиз {tag} уже есть в {repo}. Новая сборка — новая версия (app/config.py → VERSION)")
    _gh("release", "create", tag, *[str(f) for f in assets(src, doc)], "--repo", repo, "--draft", "--title", f"Dental Desk {ver}",
        "--notes", f"Обновление Dental Desk {ver}. Программа скачивает его сама и проверяет подпись разработчика.")
    _gh("release", "upload", tag, str(src / "latest.json"), "--repo", repo)
    _gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest")
    feed = updates.github_feed(repo)
    deadline = time.monotonic() + VERIFY_WAIT_S
    while True:  # what a program will now see; GitHub serves a new «latest» after a few seconds, sometimes a minute
        try:
            with updates._open(feed) as r:
                live = json.loads(r.read().decode("utf-8-sig"))
            ok = updates.verify(live) and live.get("version") == ver and live.get("sha256") == doc["sha256"]
            if not ok:
                live = f"версия {live.get('version')}, другой файл или подпись"
        except Exception as e:  # noqa: BLE001
            ok, live = False, str(e)
        if ok or time.monotonic() >= deadline:
            break
        print(f"GitHub ещё не отдаёт новую версию ({str(live)[:80]}), ждём…", flush=True)
        time.sleep(VERIFY_EVERY_S)
    print(f"Готово: {feed}" if ok else f"Релиз загружен, но за {VERIFY_WAIT_S} с по адресу {feed} так и не появилась "
          f"версия {ver}: {str(live)[:200]}. Проверьте позже: релиз мог ещё не разойтись по серверам GitHub")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?")
    ap.add_argument("--dest")
    ap.add_argument("--bucket")
    ap.add_argument("--prefix", default="updates/")
    ap.add_argument("--save-keys", action="store_true")
    ap.add_argument("--github", help="owner/repo: publish as a GitHub release")
    ap.add_argument("--allow-plain", action="store_true", help="with --github: allow an unencrypted installer")
    ap.add_argument("--prev-manifest", action="store_true", help="3.12: the list of files of the feed's current version")
    ap.add_argument("--manifests", default="release/manifests")
    ap.add_argument("--out", default="build/prev-manifest.json")
    a = ap.parse_args()
    if a.prev_manifest:
        if not a.github:
            ap.error("укажите --github <owner/repo>")
        return prev_manifest(a.github, Path(a.manifests), Path(a.out))
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
    check_files(src, doc)
    if a.github:
        return github_publish(src, doc, a.github, a.allow_plain)
    if a.dest:
        dest = Path(a.dest)
        dest.mkdir(parents=True, exist_ok=True)
        for f in assets(src, doc):
            shutil.copy2(f, dest / f.name)
        tmp = dest / "latest.json.tmp"
        shutil.copy2(src / "latest.json", tmp)
        os.replace(tmp, dest / "latest.json")
        print(f"Готово: {dest / 'latest.json'}")
        return 0
    if not a.bucket:
        ap.error("укажите --github, --dest или --bucket")
    kid, secret = _keys()
    prefix = a.prefix.strip("/") + "/" if a.prefix.strip("/") else ""
    for f in assets(src, doc):
        s3_put(a.bucket, prefix + f.name, f.read_bytes(), "application/octet-stream", kid, secret)
    s3_put(a.bucket, prefix + "latest.json", (src / "latest.json").read_bytes(), "application/json", kid, secret)
    print(f"Готово: https://{ENDPOINT}/{a.bucket}/{prefix}latest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
