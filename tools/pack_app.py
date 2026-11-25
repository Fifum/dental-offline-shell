"""Pack the program folder (dist\\<name>\\) into the zip that the installer exe carries.

    pack_app.py <folder> <zip> [--version 3.12.0 --exe AMKclinic.exe]

3.12: with --version the folder first gets dd-manifest.json (every file with its size and SHA-256, app/manifest.py):
it goes into the zip and so into every installed folder, and tools/update_sign.py builds the next update
«только изменения» from it."""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import manifest  # noqa: E402


def pack(src, out, version="", exe="") -> int:
    if version:
        if not exe or not os.path.isfile(os.path.join(src, exe)):
            raise SystemExit(f"В папке {src} нет {exe or 'программы'}")
        m = manifest.build(src, version, exe)
        manifest.write(src, m)
        print(f"manifest: {len(m['files'])} files, version {version}")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(src):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, src))
                n += 1
    print(f"packed {n} files, {os.path.getsize(out) / 1e6:.1f} MB")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("zip")
    ap.add_argument("--version", default="")
    ap.add_argument("--exe", default="")
    a = ap.parse_args(argv)
    pack(a.folder, a.zip, a.version, a.exe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
