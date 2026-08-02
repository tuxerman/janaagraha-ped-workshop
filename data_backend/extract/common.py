"""Shared helpers for the ds3 extraction pipeline.

The pipeline is split into stages that hand off via JSON on disk, so a
failure in fetching never costs you the selection work, and a failure in
extraction never costs you the downloads:

    1_select_works.py    ds3 CSV        -> works.json
    2_fetch_docs.py      works.json     -> pdfs/ + fetch_log.json
    3_prepare_pages.py   pdfs/          -> text_queue.json (text-layer PDFs)
                                           vision_queue.json (scanned PDFs,
                                           ALL pages rendered, no cap)
    3.5 (EXTRACTION_PROMPT.md, run by Claude Code, no API)
                         text_queue.json + vision_queue.json
                                        -> vision_extract.json
    4_assemble.py        vision_extract.json + works.json
                                        -> review_queue.json  (confidence-graded)
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

# Every attachment in ds3 is served from this one flat directory. Note the host:
# the TLS cert is *.bbmp.gov.in, so `account.bbmpgov.in` does NOT match it and
# needs verify=False. `accounts.bbmp.gov.in` matches but is a different vhost.
FILE_BASE = "https://account.bbmpgov.in/vssIFMS/Files1/"

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
PDF_DIR = OUT_DIR / "pdfs"

DS3_CSV = (
    HERE.parent.parent.parent / "Aug1_workshop" / "csvs" / "ds3_recent2fy_with_docs.csv"
)

# Doc types that carry the fields each track needs. Tracks 1/3/4 all live in
# the Agreement; Tender Documents adds a second, independent read of the
# tender reference (074-21-000006 showed the two disagreeing in useful ways --
# same tender, different ID). Work Order and Estimates were tried and dropped:
# Estimates are 22-page BOQ tables that were 73% of a 1GB download for zero
# track-relevant fields; Work Order occasionally corroborates the indent
# number but rarely adds anything Agreement doesn't already have.
DOCTYPES_WANTED = {
    "Agreement",
    "Tender Documents",
}

# Uploading *something* is mandatory, so officials upload a placeholder when a
# document does not apply. These are not missing data in the "we failed to get
# it" sense -- they are a positive signal that the field does not apply, and the
# distinction matters for Track 1's Section 4(g) case.
_PLACEHOLDER_RE = re.compile(
    r"not[\s._-]*app(lic|lical|licable)?|^blank|blank\.not|n[\s._-]*a\.", re.I
)


def is_placeholder(filename: str) -> bool:
    """True if the filename signals 'no such document' rather than real content."""
    stem = Path(filename or "").stem
    if _PLACEHOLDER_RE.search(stem):
        return True
    # A .gif in a corpus of scanned PDFs is always a placeholder image.
    return Path(filename or "").suffix.lower() == ".gif"


def parse_documents_detail(detail: str) -> list[dict]:
    """Parse the ' | '-joined 'Doctype: filename' pairs in documents_detail.

    Returns one dict per attachment, deduplicated on filename (the raw field
    repeats the same file when a work has several bill rows).
    """
    docs: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for chunk in (detail or "").split("|"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        doctype, _, filename = chunk.partition(":")
        doctype, filename = doctype.strip(), filename.strip()
        if not filename:
            continue
        key = (doctype, filename)
        if key in seen:
            continue
        seen.add(key)
        docs.append(
            {
                "doctype": doctype,
                "filename": filename,
                "url": FILE_BASE + quote(filename),
                "is_placeholder": is_placeholder(filename),
            }
        )
    return docs


def award_fy(job_number: str) -> str | None:
    """FY from the job number's middle segment: '040-21-000010' -> '2021-22'.

    This is the AWARD year, not the billing year -- ds3's own financial_year
    column is the billing year and routinely differs.
    """
    m = re.match(r"(?:R-)?o?\d+-(\d{2})-", job_number or "")
    if not m:
        return None
    y = 2000 + int(m.group(1))
    return f"{y}-{(y + 1) % 100:02d}"


def safe_name(filename: str) -> str:
    """Filesystem-safe local name for a fetched attachment."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:150]
