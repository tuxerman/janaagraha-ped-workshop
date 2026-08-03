"""Extract road-segment linestrings from Road History PDFs and attach them
to matching records in data_backend/json/works/works-*.json.

Most Road History PDFs (`data_backend/pdf/*.pdf`) are scans with no usable
text layer — 240 of 346 sampled return under 50 characters from `pdftotext`.
Trusting the embedded text stream for these would mean either silence or
garbage. Instead this script renders each PDF page to an image (`pdftoppm`)
and reads it back with OCR (`tesseract`) — extraction from the rendered
page, not from whatever text objects the source happened to embed. Both
tools run fully offline.

The "Segment Details" table format (seen on ~60% of the corpus) is:

    Seg No.  Length (m)   Start Coordinates      End Coordinates      From   To
       1       71.11      77.654299  13.041982   77.654946  13.041877  w1182  w1182

OCR of that table is noisy (misread digits, commas for decimal points,
column wrap on longer coordinate strings). Rather than a strict per-line
regex, every decimal-looking token in the "Segment Details" region is
pulled out and classified by magnitude (Bengaluru longitude ~77-78,
latitude ~12.3-13.6); a LON,LAT,LON,LAT run is one segment's coordinates,
and the nearest preceding non-coordinate number is its length. This
tolerates line-wrap and column reordering that break a fixed-column regex.

Matching a PDF to a work record does not rely on the `{work_bill_id}__`
filename prefix itself — that id is from whatever payments.parquet snapshot
was current at download time and does not resolve against the present
snapshot. Instead, the *original* filename after that prefix (what
download_road_history.py actually fetched by, since the request URL is
built from the name alone) is looked up directly in payments.parquet's
`files` column, which gives an exact job_number with no OCR involved —
verified empirically to be unambiguous across the whole corpus (54,966
distinct Road History filenames, 0 shared by more than one job_number).
OCR-based job-number reading (regex over the rendered page, with a
ward-corroborated fallback for single-digit misreads) is kept only as a
fallback for the case a filename isn't found in the parquet at all, or
turns out to be ambiguous — both currently zero-occurrence but not
guaranteed to stay that way as the corpus grows.

Every attached block carries `extraction_method` and `extraction_confidence`
per the project's linking rules — OCR is never presented as a surveyed
fact. PDFs that don't resolve are recorded in the run report, not silently
dropped, per "leave a trail."
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent
PDF_DIR = REPO_ROOT / "pdf"
WORKS_DIR = REPO_ROOT / "json" / "works"
MANIFEST_PATH = REPO_ROOT / "json" / "works.manifest.json"
REPORT_PATH = REPO_ROOT / "json" / "road_segments_extraction_report.json"
# Lives alongside the PDFs, next to download_road_history.py's own
# `_download_failures.json` — one result per PDF filename, written after
# every completion so a kill -9 / power loss / crash mid-run only costs the
# one PDF in flight, not the whole batch. A resumed run skips anything
# already keyed here unless --force-reprocess.
PROGRESS_PATH = PDF_DIR / "_extraction_progress.json"

RENDER_DPI = 300
MAX_PAGES_TRIED = 2
# "matched_altered" still means a job_number + segments were found and
# written to works-*.json — just with a coordinate reconstructed from a
# bare digit run rather than cleanly read. Treated the same as "matched"
# everywhere except the report/progress status label itself.
MATCHED_STATUSES = {"matched", "matched_altered"}

LON_RANGE = (77.0, 78.0)  # Bengaluru longitude
LAT_RANGE = (12.3, 13.6)  # Bengaluru latitude

JOB_NUMBER_RE = re.compile(r"\b(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{6})\b")
WARD_NO_RE = re.compile(r"Ward\s*No\.?\s*[:.]?\s*(\d{1,3})", re.IGNORECASE)
NUMBER_TOKEN_RE = re.compile(r"\d{1,3}[.,]\d{2,8}")
# A coordinate with its decimal point dropped entirely by OCR (e.g.
# "13022203" for "13.022203") — same digit-count range as NUMBER_TOKEN_RE's
# decimal part (2-8 digits) plus a 2-digit integer part, since every
# coordinate in this format is WW.dddddd. Matched separately (not merged
# into NUMBER_TOKEN_RE) so its origin is always known: reconstructing a
# decimal point is a real alteration of the OCR text, not a clean read, and
# callers need to tell the two apart.
BARE_COORDINATE_RE = re.compile(r"\b\d{6,10}\b")
TOKEN_RE = re.compile(f"(?P<sep>{NUMBER_TOKEN_RE.pattern})|(?P<bare>{BARE_COORDINATE_RE.pattern})")

SEGMENT_SECTION_START_RE = re.compile(r"Segment", re.IGNORECASE)
SEGMENT_SECTION_STOP_RE = re.compile(
    r"(Work\s*Details|Contractor\s*Details|Field\s*Inspection|History\s*of\s*Road)",
    re.IGNORECASE,
)

OSD_ROTATE_RE = re.compile(r"Rotate:\s*(\d+)")


def deskew(png: Path) -> None:
    """Detect page orientation via tesseract OSD and rotate the PNG in place
    if it's off by 90/180/270 — about 13% of scans in this corpus are, and
    OCR on a sideways table finds nothing. Best-effort: OSD needs enough
    recognizable text to work, so failures (near-blank pages, heavy
    watermarking) just leave the image as rendered.
    """
    osd = subprocess.run(
        ["tesseract", str(png), "-", "--psm", "0"],
        capture_output=True, text=True,
    )
    match = OSD_ROTATE_RE.search(osd.stdout)
    if not match:
        return
    degrees = int(match.group(1))
    if degrees == 0:
        return
    image = Image.open(png)
    image.rotate(-degrees, expand=True).save(png)


def render_and_ocr(pdf_path: Path, tmp_dir: Path) -> list[str]:
    """Render up to MAX_PAGES_TRIED pages to PNG and OCR each. Offline only."""
    texts = []
    for page in range(1, MAX_PAGES_TRIED + 1):
        stem = tmp_dir / f"page"
        result = subprocess.run(
            [
                "pdftoppm", "-r", str(RENDER_DPI), "-png",
                "-f", str(page), "-l", str(page),
                str(pdf_path), str(stem),
            ],
            capture_output=True,
        )
        pngs = sorted(tmp_dir.glob("page*.png"))
        if not pngs:
            break
        png = pngs[-1]
        deskew(png)
        ocr = subprocess.run(
            ["tesseract", str(png), "-", "--psm", "6"],
            capture_output=True, text=True,
        )
        text = ocr.stdout
        # --psm 6 (uniform block) is the right default for this form, but on
        # some scans it garbles the coordinate table where --psm 4 (single
        # column) reads it cleanly — and vice versa isn't true often enough
        # to make 4 the default (regressed 2 of 80 sampled PDFs where 6
        # already worked). So: only retry with 4, and only when the table
        # heading is present but nothing parsed from 6 — never swaps away
        # from a psm6 result that already worked.
        found, _ = extract_segments_from_text(text)
        if SEGMENT_SECTION_START_RE.search(text) and not found:
            retry = subprocess.run(
                ["tesseract", str(png), "-", "--psm", "4"],
                capture_output=True, text=True,
            )
            retry_found, _ = extract_segments_from_text(retry.stdout)
            if retry_found:
                text = retry.stdout
        texts.append(text)
        png.unlink()
        if JOB_NUMBER_RE.search(text) and SEGMENT_SECTION_START_RE.search(text):
            break
    return texts


def classify(x: float) -> str:
    if LON_RANGE[0] <= x < LON_RANGE[1]:
        return "LON"
    if LAT_RANGE[0] <= x < LAT_RANGE[1]:
        return "LAT"
    return "OTHER"


def extract_segment_block(text: str) -> str | None:
    start = SEGMENT_SECTION_START_RE.search(text)
    if not start:
        return None
    stop = SEGMENT_SECTION_STOP_RE.search(text, start.end())
    end = stop.start() if stop else min(len(text), start.end() + 4000)
    return text[start.end():end]


def extract_segments_from_text(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Returns (segments, altered) — altered is True if any segment's
    coordinates required reconstructing a decimal point from a bare digit
    run (no separator in the OCR text at all), as opposed to a clean
    ``\\d+[.,]\\d+`` read. Callers use this to mark the result
    ``matched_altered`` instead of ``matched``.
    """
    block = extract_segment_block(text)
    if not block:
        return [], False

    tokens: list[float] = []
    token_altered: list[bool] = []
    for match in TOKEN_RE.finditer(block):
        if match.group("sep"):
            try:
                tokens.append(float(match.group("sep").replace(",", ".")))
                token_altered.append(False)
            except ValueError:
                continue
        else:
            raw = match.group("bare")
            try:
                tokens.append(float(f"{raw[:2]}.{raw[2:]}"))
                token_altered.append(True)
            except ValueError:
                continue

    classes = [classify(t) for t in tokens]
    segments: list[dict[str, Any]] = []
    any_altered = False
    seg_counter = 0
    i = 0
    n = len(tokens)
    while i < n:
        if (
            i + 3 < n
            and classes[i] == "LON" and classes[i + 1] == "LAT"
            and classes[i + 2] == "LON" and classes[i + 3] == "LAT"
        ):
            lon1, lat1, lon2, lat2 = tokens[i:i + 4]
            if any(token_altered[i:i + 4]):
                any_altered = True
            lookback = []
            j = i - 1
            while j >= 0 and classes[j] == "OTHER" and len(lookback) < 3:
                lookback.append(tokens[j])
                j -= 1
            lookback.reverse()  # now oldest-first; last element is closest to the coords
            length_m = lookback[-1] if lookback else None
            seg_no = None
            if len(lookback) >= 2 and lookback[-2] == int(lookback[-2]):
                seg_no = int(lookback[-2])
            seg_counter += 1
            segments.append({
                "segment_number": seg_no if seg_no is not None else seg_counter,
                "length_m": length_m,
                "start": {"lat": lat1, "lng": lon1},
                "end": {"lat": lat2, "lng": lon2},
            })
            i += 4
        else:
            i += 1
    return segments, any_altered


def extract_job_number(text: str, known_job_numbers: set[str], jobs_by_ward_prefix: dict[str, list[str]]) -> tuple[str | None, str, list[str]]:
    """Returns (job_number, note). job_number is None if nothing resolvable.

    OCR digit errors on this field are substitutions, not insertions/deletions
    (a misread "0" as "9", not a dropped character) — so correction is scoped
    to the ward printed elsewhere on the same page (an independent OCR read)
    and scored by Hamming distance on the fixed-width WWW-YY-NNNNNN string,
    not by a generic fuzzy-string ratio. A tie between two candidates at the
    same distance is treated as unresolved rather than guessed.
    """
    candidates = [f"{m.group(1)}-{m.group(2)}-{m.group(3)}" for m in JOB_NUMBER_RE.finditer(text)]
    for candidate in candidates:
        if candidate in known_job_numbers:
            return candidate, "exact_match", candidates

    ward_match = WARD_NO_RE.search(text)
    if not ward_match or not candidates:
        return None, "no_job_number_resolved", candidates

    ward_prefix = ward_match.group(1).zfill(3)
    pool = jobs_by_ward_prefix.get(ward_prefix, [])

    for candidate in candidates:
        corrected = ward_prefix + candidate[3:]
        if corrected in known_job_numbers:
            return corrected, f"ward_prefix_corrected(ocr_candidate={candidate!r})", candidates

    best, best_distance, tie = None, None, False
    for candidate in candidates:
        base = ward_prefix + candidate[3:]
        for job_number in pool:
            if len(job_number) != len(base):
                continue
            distance = sum(1 for a, b in zip(job_number, base) if a != b)
            if best_distance is None or distance < best_distance:
                best, best_distance, tie = job_number, distance, False
            elif distance == best_distance and job_number != best:
                tie = True

    if best is not None and best_distance is not None and best_distance <= 2 and not tie:
        return best, f"hamming_corrected(distance={best_distance}, ward_prefix={ward_prefix!r})", candidates

    return None, "no_job_number_resolved", candidates


def build_job_index() -> tuple[dict[str, tuple[Path, int]], set[str], dict[str, list[str]]]:
    index: dict[str, tuple[Path, int]] = {}
    jobs_by_ward_prefix: dict[str, list[str]] = {}
    for path in sorted(WORKS_DIR.glob("works-*.json")):
        records = json.loads(path.read_text())
        for i, record in enumerate(records):
            job_number = record["job_number"]
            index[job_number] = (path, i)
            jobs_by_ward_prefix.setdefault(job_number[:3], []).append(job_number)
    return index, set(index), jobs_by_ward_prefix


def build_name_to_jobs(payments) -> dict[str, set[str]]:
    """Map each Road History attachment's original server-side filename to
    the job_number(s) that reference it, straight from payments.parquet's
    `files` column — no OCR involved. Verified empirically unambiguous
    across the whole corpus (0 of 54,966 names shared by >1 job_number), but
    kept as a set (not assumed singleton) so a future ambiguity is detected
    and falls back to OCR rather than silently picking one.
    """
    name_to_jobs: dict[str, set[str]] = {}
    for files_json, job_number in zip(payments["files"], payments["job_number"]):
        if not files_json:
            continue
        try:
            attachments = json.loads(files_json)
        except (TypeError, json.JSONDecodeError):
            continue
        for attachment in attachments:
            if attachment.get("type") != "Road History":
                continue
            name = attachment.get("name", "")
            if not name.lower().endswith(".pdf"):
                continue
            name_to_jobs.setdefault(name, set()).add(job_number)
    return name_to_jobs


def resolve_job_number_from_filename(
    pdf_path: Path, name_to_jobs: dict[str, set[str]]
) -> tuple[str | None, str]:
    """The primary, OCR-free match: download_road_history.py saves files as
    `{work_bill_id}__{original_name}`, and its fetch request is built from
    `original_name` alone (work_bill_id never enters the URL) — so the part
    after the first "__" is exactly the key payments.parquet's `files`
    column uses. work_bill_id itself is not used here since it drifts
    across payments.parquet snapshots and would not resolve reliably.
    """
    _, sep, original_name = pdf_path.name.partition("__")
    if not sep:
        return None, "no_work_bill_id_prefix"
    jobs = name_to_jobs.get(original_name)
    if not jobs:
        return None, "filename_not_in_parquet"
    if len(jobs) > 1:
        return None, f"filename_ambiguous(job_numbers={sorted(jobs)!r})"
    return next(iter(jobs)), "filename_lookup"


def process_pdf(
    pdf_path: Path, job_index, known_job_numbers, jobs_by_ward_prefix,
    parquet_job_numbers: set[str], name_to_jobs: dict[str, set[str]],
) -> dict[str, Any]:
    job_number, job_note = resolve_job_number_from_filename(pdf_path, name_to_jobs)

    if job_number is not None and job_number not in job_index:
        # Known before any rendering: this job_number simply isn't in
        # works-*.json (the upstream corpus gap vs payments.parquet — see
        # data_schema.md). No amount of OCR on this PDF changes that, so
        # skip the render+OCR cost entirely rather than pay it for nothing.
        return {
            "file": pdf_path.name, "status": "job_number_not_in_corpus",
            "job_number": job_number, "note": job_note,
        }

    with tempfile.TemporaryDirectory() as tmp:
        texts = render_and_ocr(pdf_path, Path(tmp))
    combined = "\n".join(texts)

    if job_number is None:
        if not combined.strip():
            return {"file": pdf_path.name, "status": "render_or_ocr_failed"}

        job_number, job_note, candidates = extract_job_number(combined, known_job_numbers, jobs_by_ward_prefix)
        if job_number is None:
            # Distinguish "OCR found a plausible number but it's not in the
            # works-*.json corpus at all" (upstream data gap) from "OCR found
            # nothing usable" (bad scan/render) — the fix differs for each.
            in_parquet = [c for c in candidates if c in parquet_job_numbers]
            return {
                "file": pdf_path.name, "status": "job_number_not_resolved", "note": job_note,
                "ocr_candidates": candidates, "candidates_in_parquet_not_in_corpus": in_parquet,
            }

    segments = []
    altered = False
    for text in texts:
        segments, altered = extract_segments_from_text(text)
        if segments:
            break

    if not segments:
        return {
            "file": pdf_path.name, "status": "no_segment_table",
            "job_number": job_number, "note": job_note,
        }

    if job_number not in job_index:
        return {
            "file": pdf_path.name, "status": "job_number_not_in_corpus",
            "job_number": job_number, "note": job_note,
        }

    confidence = "high" if job_note in ("filename_lookup",) or job_note.startswith(
        ("exact_match", "ward_prefix_corrected")
    ) else "medium"
    record_path, record_idx = job_index[job_number]
    return {
        "file": pdf_path.name, "status": "matched_altered" if altered else "matched",
        "job_number": job_number, "note": job_note,
        "record_path": str(record_path), "record_idx": record_idx,
        "segments": segments, "confidence": confidence, "altered": altered,
    }


def load_progress() -> dict[str, dict[str, Any]]:
    if not PROGRESS_PATH.exists():
        return {}
    return json.loads(PROGRESS_PATH.read_text())


def save_progress(progress: dict[str, dict[str, Any]]) -> None:
    # Atomic write (temp file + rename) so a crash mid-write never leaves a
    # truncated/corrupt progress file behind for the next run to choke on.
    tmp = PROGRESS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(PROGRESS_PATH)


def apply_matched_update(update: dict[str, Any]) -> None:
    """Write one matched PDF's segments into its works-*.json chunk immediately
    (not batched to end-of-run), so progress survives an interruption. Safe to
    call repeatedly for the same PDF (e.g. a rerun after a crash) since the
    block is keyed and replaced by source_document, never appended twice.
    """
    path = Path(update["record_path"])
    records = json.loads(path.read_text())
    record = records[update["record_idx"]]
    altered_note = (
        " At least one coordinate in this block had its decimal point "
        "reconstructed after the first two digits (the OCR text had no "
        "separator at all, e.g. '13022203') — more speculative than a "
        "normal OCR digit misread; verify before treating as precise."
        if update.get("altered")
        else ""
    )
    block = {
        "source_document": update["file"],
        "extraction_method": "ocr_visual_extraction",
        "extraction_confidence": update["confidence"],
        "notes": (
            f"job_number matched via {update['note']}; coordinates and "
            f"lengths read by OCR off a {RENDER_DPI}dpi render of the "
            f"source PDF page (offline, tesseract), not from the PDF's "
            f"text layer. Digit misreads are possible; treat as "
            f"indicative, not surveyed.{altered_note}"
        ),
        "segments": update["segments"],
    }
    record.setdefault("road_segments", [])
    record["road_segments"] = [
        b for b in record["road_segments"] if b["source_document"] != update["file"]
    ]
    record["road_segments"].append(block)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    refresh_manifest_chunk(path)


def refresh_manifest_chunk(chunk_path: Path) -> None:
    """Recompute one chunk's bytes/sha256/records in works.manifest.json after
    patching it in place. server.js verifies every chunk's checksum and size
    against the manifest on load and refuses to start on a mismatch — writing
    to works-*.json without this would silently break the live dashboard
    until someone noticed and rebuilt the manifest by hand (as happened
    twice before this was automated).
    """
    manifest = json.loads(MANIFEST_PATH.read_text())
    data = chunk_path.read_bytes()
    records = json.loads(data)
    rel_path = f"{WORKS_DIR.name}/{chunk_path.name}"
    for chunk in manifest["chunks"]:
        if chunk["file"] == rel_path:
            chunk["records"] = len(records)
            chunk["bytes"] = len(data)
            chunk["sha256"] = hashlib.sha256(data).hexdigest()
            break
    else:
        raise ValueError(f"{rel_path} not listed in {MANIFEST_PATH}")
    manifest["chunking"]["total_bytes"] = sum(c["bytes"] for c in manifest["chunks"])
    manifest["record_count"] = sum(c["records"] for c in manifest["chunks"])
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(MANIFEST_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="process only the first N PDFs (pilot runs)")
    parser.add_argument("--dry-run", action="store_true", help="extract and report but do not write works-*.json")
    parser.add_argument(
        "--max-parallel", type=int, default=4,
        help=(
            "number of PDFs to render/OCR concurrently (default: 4). Each PDF's "
            "work — pdftoppm, tesseract OSD, tesseract OCR — is independent "
            "external-process I/O against its own temp dir, so threads (not "
            "processes) are enough to parallelize it."
        ),
    )
    parser.add_argument(
        "--force-reprocess", action="store_true",
        help=(
            "ignore _extraction_progress.json and reprocess every PDF, including "
            "ones already recorded from a prior run. Default is to resume: skip "
            "any PDF already present in the progress file, matched or not."
        ),
    )
    parser.add_argument(
        "--retry-errors", action="store_true",
        help=(
            "reprocess PDFs recorded with any non-'matched' status (e.g. "
            "no_segment_table, job_number_not_resolved, render_or_ocr_failed) "
            "— useful after a pipeline improvement (e.g. the --psm 4 fallback) "
            "that might recover previously-failed PDFs, without redoing "
            "PDFs that already matched. Ignored if --force-reprocess is set."
        ),
    )
    args = parser.parse_args()
    if args.max_parallel < 1:
        sys.exit("--max-parallel must be at least 1")

    for tool in ("pdftoppm", "tesseract"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            sys.exit(f"required tool {tool!r} not found on PATH")

    job_index, known_job_numbers, jobs_by_ward_prefix = build_job_index()

    import pandas as pd
    payments = pd.read_parquet(REPO_ROOT / "csv" / "payments.parquet")
    parquet_job_numbers = set(payments["job_number"].dropna())
    name_to_jobs = build_name_to_jobs(payments)

    pdfs = sorted(p for p in PDF_DIR.glob("*.pdf"))
    if args.limit:
        pdfs = pdfs[:args.limit]

    progress = {} if args.force_reprocess else load_progress()

    def is_settled(pdf_path: Path) -> bool:
        recorded = progress.get(pdf_path.name)
        if recorded is None:
            return False
        if args.retry_errors and recorded["status"] not in MATCHED_STATUSES:
            return False
        return True

    already_done = [p for p in pdfs if is_settled(p)]
    to_process = [p for p in pdfs if not is_settled(p)]
    if already_done:
        mode_note = (
            "retrying only non-matched ones"
            if args.retry_errors
            else "use --force-reprocess to redo everything, or --retry-errors to only retry failures"
        )
        print(
            f"Resuming: {len(already_done)}/{len(pdfs)} PDFs already settled in "
            f"{PROGRESS_PATH.name}, skipping those ({len(to_process)} left, {mode_note}).",
            file=sys.stderr,
        )

    # Seed with prior-run results so the final report/summary covers the whole
    # corpus, not just what this invocation touched.
    results_by_name = {p.name: progress[p.name] for p in already_done}

    with ThreadPoolExecutor(max_workers=args.max_parallel) as executor:
        future_to_pdf = {
            executor.submit(
                process_pdf, pdf_path, job_index, known_job_numbers, jobs_by_ward_prefix, parquet_job_numbers,
                name_to_jobs,
            ): pdf_path
            for pdf_path in to_process
        }
        for n, future in enumerate(as_completed(future_to_pdf), 1):
            pdf_path = future_to_pdf[future]
            result = future.result()
            print(f"[{n}/{len(to_process)}] {pdf_path.name} -> {result['status']}", file=sys.stderr)
            results_by_name[pdf_path.name] = result

            if not args.dry_run:
                if result["status"] in MATCHED_STATUSES:
                    apply_matched_update(result)
                progress[pdf_path.name] = result
                save_progress(progress)

    results = sorted(results_by_name.values(), key=lambda r: r["file"])

    matched = sum(1 for r in results if r["status"] in MATCHED_STATUSES)
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    REPORT_PATH.write_text(json.dumps({"summary": by_status, "results": results}, indent=2) + "\n")
    print(f"\n{matched}/{len(results)} PDFs matched and segments extracted (of {len(pdfs)} total).")
    print(f"Status breakdown: {by_status}")
    print(f"Full report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
