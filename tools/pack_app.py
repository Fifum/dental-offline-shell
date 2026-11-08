"""Pack the program folder (dist\\<name>\\) into the zip that the installer exe carries.
Usage: pack_app.py <folder> <zip>"""
import os
import sys
import zipfile

src, out = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for root, _dirs, files in os.walk(src):
        for f in files:
            full = os.path.join(root, f)
            z.write(full, os.path.relpath(full, src))
            n += 1
print(f"packed {n} files, {os.path.getsize(out) / 1e6:.1f} MB")
