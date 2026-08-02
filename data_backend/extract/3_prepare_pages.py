"""Step 3 — triage each PDF into a text-extraction job or a vision job.

No LLM API is called anywhere in this pipeline. Extraction is done by Claude
Code reading either extracted text or rendered PNGs directly, using session
tokens. This script does the deterministic prep; the reading itself is step
3.5 (see EXTRACTION_PROMPT.md).

Two branches, chosen per-PDF by whether it has a real text layer:

  TEXT-EXTRACTABLE (~13% of this corpus)
    -> full plain text is extracted with pdftotext and handed to the reader
       AS TEXT. No rendering, no regex parsing. The reader (an LLM) parses
       the fields directly out of the text -- the same judgment call it
       would make reading an image, just cheaper and with no image tokens.
       Regex was tried here first and dropped: pdftotext -layout fragments
       clauses across column boundaries, so a regex anchor can silently miss
       a clause that is sitting right there in the text with no signal
       anything was missed. See observations_running_doc.md. An LLM reading
       the same text does not have this failure mode.

  NOT TEXT-EXTRACTABLE (~87%, scanned with no/garbage text layer)
    -> ALL pages are rendered (not capped) and queued for vision reading.
       The reader must page through the full document before concluding a
       field is absent -- DLP clauses on this corpus have turned up on
       pages 3, 4, and 7 of the same document depending on office/template,
       and stopping early after finding *some* fields but not DLP produced
       5+ false "UNCLEAR" gradings in earlier passes of this project (see
       observations_running_doc.md). "Not found on the pages I looked at" is
       only a valid absence once every rendered page has actually been read.

Cost control: 110 DPI, not 200, for rendered pages -- image tokens scale with
area and 110 reads cleanly on these scans. No page cap: capping page count
is what caused the missed-DLP problem in the first place, and BBMP agreements
top out around 8 pages, so full rendering is cheap enough not to need one.

Usage:
    python3 3_prepare_pages.py [--dpi 110]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from common import OUT_DIR, PDF_DIR

PAGE_DIR = OUT_DIR / "pages"
TEXT_DIR = OUT_DIR / "text"

# Below this, a "text layer" is just stray scanner artefacts, not real text.
TEXT_LAYER_MIN_CHARS = 500


def pdf_pages(path: Path) -> int:
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"^Pages:\s*(\d+)", out, re.M)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def pdf_text(path: Path) -> str:
    try:
        return subprocess.run(
            ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=120
        ).stdout
    except Exception:
        return ""


def render_all(pdf: Path, out_prefix: Path, dpi: int, npages: int) -> list[Path]:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_prefix.parent.glob(out_prefix.name + "-*.png"))
    if len(existing) >= npages:
        return existing
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(out_prefix)],
        capture_output=True, timeout=300,
    )
    return sorted(out_prefix.parent.glob(out_prefix.name + "-*.png"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dpi", type=int, default=110)
    args = ap.parse_args()

    works = json.loads((OUT_DIR / "works.json").read_text())
    # Keyed by (job_number, sanitised local name) since the same sanitised name
    # can recur across different works' documents. Built from the FULL
    # document list, not just `targets` (the current fetch scope) -- PDFs
    # from an earlier, broader run are still sitting in pdfs/ and would
    # otherwise fall through to "Unknown" doctype and a wrongly-sanitised URL.
    doc_of: dict[tuple[str, str], dict] = {
        (w["job_number"], re.sub(r"[^A-Za-z0-9._-]", "_", d["filename"])[:150]): d
        for w in works
        for d in w["documents"]
    }

    text_queue: list[dict] = []
    vision_queue: list[dict] = []

    pdfs = sorted(PDF_DIR.glob("*/*.pdf"))
    print(f"triaging {len(pdfs)} PDFs ...")

    for pdf in pdfs:
        job_number = pdf.parent.name
        src = doc_of.get((job_number, pdf.name))
        doctype = src["doctype"] if src else "Unknown"
        source_filename = src["filename"] if src else pdf.name

        npages = pdf_pages(pdf) or 1
        text = pdf_text(pdf)
        has_text = len(text.strip()) >= TEXT_LAYER_MIN_CHARS

        base = {
            "job_number": job_number,
            "doctype": doctype,
            "pdf": str(pdf.relative_to(OUT_DIR)),
            "source_filename": source_filename,
            "pages_total": npages,
        }

        if has_text:
            text_path = TEXT_DIR / job_number / (pdf.stem + ".txt")
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(text)
            text_queue.append(base | {
                "method": "text",
                "text_file": str(text_path.relative_to(OUT_DIR)),
                "text_chars": len(text.strip()),
            })
        else:
            prefix = PAGE_DIR / job_number / pdf.stem
            pngs = render_all(pdf, prefix, args.dpi, npages)
            vision_queue.append(base | {
                "method": "vision",
                "pages_rendered": [str(p.relative_to(OUT_DIR)) for p in pngs],
            })

    (OUT_DIR / "text_queue.json").write_text(json.dumps(text_queue, indent=2))
    (OUT_DIR / "vision_queue.json").write_text(json.dumps(vision_queue, indent=2))

    n_png = sum(len(r["pages_rendered"]) for r in vision_queue)
    print(f"\ntext-extraction queue : {len(text_queue)} PDFs (no rendering, LLM reads extracted text)")
    print(f"vision queue          : {len(vision_queue)} PDFs -> {n_png} PNGs @ {args.dpi} DPI (ALL pages, no cap)")
    print(f"\nwrote: {OUT_DIR/'text_queue.json'}")
    print(f"wrote: {OUT_DIR/'vision_queue.json'}")


if __name__ == "__main__":
    main()
