"""One-off: measure how many of the 'no OCR candidate' PDFs are actually
rotated, using tesseract's orientation-and-script-detection (OSD) mode, so
rotation-correction effort is spent only if it will move the needle.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PDF_DIR = Path(__file__).resolve().parent / "pdf"
FILES = Path(sys.argv[1]).read_text().splitlines()

results = []
for i, name in enumerate(FILES, 1):
    name = name.strip()
    if not name:
        continue
    pdf_path = PDF_DIR / name
    with tempfile.TemporaryDirectory() as tmp:
        stem = Path(tmp) / "p"
        subprocess.run(
            ["pdftoppm", "-r", "150", "-png", "-f", "1", "-l", "1", str(pdf_path), str(stem)],
            capture_output=True,
        )
        pngs = sorted(Path(tmp).glob("p*.png"))
        if not pngs:
            results.append((name, "render_failed", None))
            continue
        osd = subprocess.run(
            ["tesseract", str(pngs[-1]), "-", "--psm", "0"],
            capture_output=True, text=True,
        )
        m = re.search(r"Orientation in degrees:\s*(\d+)", osd.stdout)
        conf = re.search(r"Orientation confidence:\s*([\d.]+)", osd.stdout)
        if m:
            results.append((name, m.group(1), conf.group(1) if conf else None))
        else:
            results.append((name, "osd_failed", osd.stderr.strip().splitlines()[-1] if osd.stderr else ""))
    print(f"[{i}/{len(FILES)}] {name}: {results[-1][1]}", file=sys.stderr)

from collections import Counter
c = Counter(r[1] for r in results)
print("\nRotation breakdown:", dict(c))
for r in results:
    if r[1] not in ("0",):
        print(r)
