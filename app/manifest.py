"""3.12: the list of files of the program folder — every path with its size and SHA-256 (dd-manifest.json next to the exe).

tools/pack_app.py writes it into the folder when the program is built, so it travels inside the installer and every
installed folder knows exactly what it should contain. An update «только изменения» (updates.py) checks this
computer's files against it before taking the changes, and the assembled new folder against the manifest of the new
version before installing it; tools/update_sign.py builds the delta from the manifests of two versions.
Paths use «/», relative to the program folder; the manifest itself is not listed in it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

NAME = "dd-manifest.json"
HELPER = "_internal/dd-update-helper.exe"  # installs a delta after the program closes (update_helper.py, build.ps1)
APP = "dentaldesk"


def file_sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel_ok(rel) -> bool:
    """A path inside the folder: relative, «/» only, no «..», no drive, never the manifest itself."""
    if not isinstance(rel, str) or not rel or rel == NAME or "\\" in rel or ":" in rel or rel.startswith("/"):
        return False
    parts = rel.split("/")
    return all(p and p not in (".", "..") for p in parts)


def build(folder, version, exe) -> dict:
    files = {}
    for root, _dirs, names in os.walk(folder):
        for n in names:
            full = os.path.join(root, n)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            if rel == NAME:
                continue
            files[rel] = [os.path.getsize(full), file_sha(full)]
    return {"app": APP, "version": str(version), "exe": str(exe), "files": dict(sorted(files.items()))}


def canonical(m: dict) -> bytes:
    return json.dumps(m, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(m: dict) -> str:
    """What latest.json signs about a manifest (and what a delta names as the version it starts from)."""
    return hashlib.sha256(canonical(m)).hexdigest()


def valid(m) -> bool:
    if not isinstance(m, dict) or m.get("app") != APP or not m.get("version") or not isinstance(m.get("files"), dict):
        return False
    if not rel_ok(m.get("exe")) or m["exe"] not in m["files"]:
        return False
    for rel, v in m["files"].items():
        if not rel_ok(rel) or not isinstance(v, list) or len(v) != 2 or not isinstance(v[0], int) or v[0] < 0 \
                or not isinstance(v[1], str) or not re.fullmatch(r"[0-9a-f]{64}", v[1]):
            return False
    return True


def write(folder, m: dict):
    tmp = os.path.join(folder, NAME + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=0)
    os.replace(tmp, os.path.join(folder, NAME))


def load(folder) -> dict | None:
    try:
        with open(os.path.join(folder, NAME), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    return m if valid(m) else None


def check(folder, m: dict, progress=None) -> list:
    """Paths of the manifest that are missing or differ in `folder` ([] = the folder is exactly this version).
    `progress(fraction)` is told how far the check got (hashing a few hundred megabytes takes seconds)."""
    total = sum(v[0] for v in m["files"].values()) or 1
    done, bad = 0, []
    for rel, (size, sha) in m["files"].items():
        p = os.path.join(folder, *rel.split("/"))
        try:
            ok = os.path.isfile(p) and os.path.getsize(p) == size and file_sha(p) == sha
        except OSError:
            ok = False
        if not ok:
            bad.append(rel)
        done += size
        if progress:
            progress(done / total)
    return bad
