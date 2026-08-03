"""Step 3 — triage each PDF into a text-extraction job or a vision job.

No LLM API is called anywhere in this pipeline. Extraction is done by Claude
Code reading either extracted text or the PDF itself directly, using session
tokens. This script does the deterministic prep; the reading itself is step
3.5 (see EXTRACTION_PROMPT.md).

No PNG rendering. The Read tool opens PDFs natively (each page renders as an
image to the model, same as a rendered PNG would), so there is no reason to
pre-render pages to disk -- that was pure wasted work (899MB of PNGs for a
30-work sample) solving a problem the tool already solves.

Two branches, chosen per-PDF by whether it has a real text layer:

  TEXT-EXTRACTABLE
    -> full plain text is extracted with pdftotext and handed to the reader
       AS TEXT. No regex parsing -- the reader (an LLM) parses the fields
       directly out of the text, the same judgment call it would make
       reading an image, just cheaper and with no image tokens.
       Regex was tried here first and dropped: pdftotext -layout fragments
       clauses across column boundaries, so a regex anchor can silently miss
       a clause that is sitting right there in the text with no signal
       anything was missed. See observations_running_doc.md.

  NOT TEXT-EXTRACTABLE (scanned, no/garbage text layer)
    -> the reader opens the PDF directly with the Read tool and reads every
       page before concluding a field is absent. DLP clauses on this corpus
       have turned up on pages 3, 4, and 7 of the same document depending on
       office/template -- stopping early after finding *some* fields but not
       DLP produced 5+ false "UNCLEAR" gradings in earlier passes of this
       project (see observations_running_doc.md).

Selective and idempotent: only triages the job numbers passed via --jobs (or
every job in works.json if omitted), and skips any PDF whose text file (text
branch) already exists on disk. Re-running costs nothing for work already
done.

Usage:
    python3 3_prepare_pages.py [--jobs 003-23-000003,006-23-000001,...]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from common import OUT_DIR, PDF_DIR

TEXT_DIR = OUT_DIR / "text"

# Below this, a "text layer" is just stray scanner artefacts, not real text.
TEXT_LAYER_MIN_CHARS = 500

# Some scanner apps (TapScanner and similar) stamp a repeated watermark line
# on every page, which alone can clear TEXT_LAYER_MIN_CHARS on a purely
# scanned PDF with no real text layer (33 lines of "Scanned by TapScanner" =
# 757 chars, past the threshold, zero extractable content). A real text layer
# has many distinct words; a watermark-only "layer" has very few relative to
# its line count. Guard against this by also requiring a minimum count of
# distinct alphabetic words.
TEXT_LAYER_MIN_DISTINCT_WORDS = 40


def pdf_text(path: Path) -> str:
    try:
        return subprocess.run(
            ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=120
        ).stdout
    except Exception:
        return ""


def looks_like_real_text(text: str) -> bool:
    if len(text.strip()) < TEXT_LAYER_MIN_CHARS:
        return False
    words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)}
    return len(words) >= TEXT_LAYER_MIN_DISTINCT_WORDS


def pdf_pages(path: Path) -> int:
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"^Pages:\s*(\d+)", out, re.M)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=str, default=None,
                    help="comma-separated job numbers to triage; default: all in works.json")
    args = ap.parse_args()

    works = json.loads((OUT_DIR / "works.json").read_text())
    if args.jobs:
        wanted = set(args.jobs.split(","))
        works = [w for w in works if w["job_number"] in wanted]

    doc_of: dict[tuple[str, str], dict] = {
        (w["job_number"], re.sub(r"[^A-Za-z0-9._-]", "_", d["filename"])[:150]): d
        for w in works
        for d in w["documents"]
    }

    text_queue: list[dict] = []
    vision_queue: list[dict] = []

    job_numbers = {w["job_number"] for w in works}
    pdfs = sorted(p for p in PDF_DIR.glob("*/*.pdf") if p.parent.name in job_numbers)
    print(f"triaging {len(pdfs)} PDFs across {len(job_numbers)} works ...")

    n_skipped = 0
    for pdf in pdfs:
        job_number = pdf.parent.name
        src = doc_of.get((job_number, pdf.name))
        doctype = src["doctype"] if src else "Unknown"
        source_filename = src["filename"] if src else pdf.name

        base = {
            "job_number": job_number,
            "doctype": doctype,
            "pdf": str(pdf.relative_to(OUT_DIR)),
            "source_filename": source_filename,
        }

        text_path = TEXT_DIR / job_number / (pdf.stem + ".txt")
        if text_path.exists():
            # Already triaged as text-extractable in a prior run.
            text_queue.append(base | {
                "method": "text",
                "text_file": str(text_path.relative_to(OUT_DIR)),
                "text_chars": len(text_path.read_text().strip()),
            })
            n_skipped += 1
            continue

        text = pdf_text(pdf)
        has_text = looks_like_real_text(text)

        if has_text:
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(text)
            text_queue.append(base | {
                "method": "text",
                "text_file": str(text_path.relative_to(OUT_DIR)),
                "text_chars": len(text.strip()),
            })
        else:
            vision_queue.append(base | {
                "method": "vision",
                "pages_total": pdf_pages(pdf) or 1,
            })

    # Merge into any existing queue files rather than clobbering entries for
    # jobs outside this run's --jobs scope.
    def merge(name: str, new_rows: list[dict]) -> list[dict]:
        path = OUT_DIR / name
        existing = json.loads(path.read_text()) if path.exists() else []
        keep = [r for r in existing if r["job_number"] not in job_numbers]
        merged = keep + new_rows
        path.write_text(json.dumps(merged, indent=2))
        return merged

    text_queue = merge("text_queue.json", text_queue)
    vision_queue = merge("vision_queue.json", vision_queue)

    print(f"\ntext-extraction queue : {len(text_queue)} PDFs total ({n_skipped} already-triaged, reused)")
    print(f"vision queue          : {len(vision_queue)} PDFs total (read directly with the Read tool, all pages)")
    print(f"\nwrote: {OUT_DIR/'text_queue.json'}")
    print(f"wrote: {OUT_DIR/'vision_queue.json'}")


if __name__ == "__main__":
    main()
