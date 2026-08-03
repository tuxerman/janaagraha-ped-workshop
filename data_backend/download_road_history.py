"""Download Road History PDFs for a ward from BBMP's file server.

Reads work-bill "files" metadata (type == "Road History") out of
payments.parquet for a given ward, then fetches each attachment from
BBMP's vssIFMS file server into data_backend/pdf/.

Filenames on the server are not unique across work bills, so downloads
are saved as ``{work_bill_id}__{original_name}`` to preserve provenance.
"""

from __future__ import annotations

import argparse
import glob
import json
import time
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
import urllib3

# BBMP's server sends only its leaf certificate, omitting the GoDaddy
# intermediate, so certifi-based verification fails with "unable to get
# local issuer certificate". This is a known-scoped, read-only download
# from a public .gov.in portal, so we skip verification rather than
# fight the incomplete chain.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# The portal serves attachments from more than one directory
# (Files1, Files, Files2 have all been observed for the same work
# bill); a 404 on one does not mean the file is missing.
BASE_URLS = [
    "https://accounts.bbmp.gov.in/vssIFMS/Files1/",
    "https://accounts.bbmp.gov.in/vssIFMS/Files/",
    "https://accounts.bbmp.gov.in/vssIFMS/Files2/",
]
RETRIES_PER_URL = 3
REPO_ROOT = Path(__file__).resolve().parent
PAYMENTS_PARQUET = REPO_ROOT / "csv" / "payments.parquet"
OUT_DIR = REPO_ROOT / "pdf"
WORKS_DIR = REPO_ROOT / "json" / "works"


def known_job_numbers() -> set[str]:
    """job_numbers actually present in works-*.json.

    Road History PDFs whose job_number isn't in this set can never be
    matched to a work record by extract_road_segments.py (as of this
    writing, ~1 in 6 Road History attachments in payments.parquet fall
    outside it — see data_schema.md's `road_segments[]` section). Fetching
    those anyway is wasted requests against BBMP's server if the goal is
    the works dashboard, not a general-purpose PDF archive.
    """
    jobs: set[str] = set()
    for path in glob.glob(str(WORKS_DIR / "works-*.json")):
        for record in json.loads(Path(path).read_text()):
            jobs.add(record["job_number"])
    return jobs


def road_history_files(
    ward_number: float, ward_name: str, job_number_filter: set[str] | None = None
) -> list[dict]:
    df = pd.read_parquet(PAYMENTS_PARQUET)
    sub = df[(df["ward_number"] == ward_number) & (df["ward_name"] == ward_name)] if ward_number is not -1 else df

    seen: set[tuple[int, str]] = set()
    out: list[dict] = []
    for _, row in sub.iterrows():
        if job_number_filter is not None and row["job_number"] not in job_number_filter:
            continue
        files = row["files"]
        if not files:
            continue
        try:
            attachments = json.loads(files)
        except (TypeError, json.JSONDecodeError):
            continue
        for f in attachments:
            if f.get("type") != "Road History":
                continue
            name_lower = f["name"].lower()
            if not name_lower.endswith(".pdf"):
                continue
            if "not app" in name_lower or "na.pdf" in name_lower:
                continue
            key = (int(row["work_bill_id"]), f["name"])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "work_bill_id": int(row["work_bill_id"]),
                    "job_number": row["job_number"],
                    "name": f["name"],
                }
            )
    return out


def fetch(name: str) -> bytes:
    """Try each known file directory, retrying transient errors within each."""
    last_exc: Exception | None = None
    for base_url in BASE_URLS:
        url = base_url + quote(name)
        for attempt in range(1, RETRIES_PER_URL + 1):
            try:
                resp = requests.get(url, timeout=30, verify=False)
                if resp.status_code == 404:
                    last_exc = requests.HTTPError(f"404 at {url}")
                    break  # no point retrying a 404 on this path
                resp.raise_for_status()
                return resp.content
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < RETRIES_PER_URL:
                    time.sleep(1.5 * attempt)
    assert last_exc is not None
    raise last_exc


def already_fetched_names(out_dir: Path) -> set[str]:
    """Original (server-side) filenames already on disk, regardless of which
    work_bill_id they were saved under.

    ``work_bill_id`` is not stable across payments.parquet snapshots (the same
    bill can carry a different id after a refresh), so a dest-path exists()
    check keyed on the *current* snapshot's id silently stops recognizing
    files downloaded under an older one — a rerun would re-fetch most of the
    corpus. This is safe to dedupe on ``name`` alone because ``fetch()``'s
    request URL is built from ``name`` only; work_bill_id never enters it, so
    the same name always resolves to the same bytes regardless of which row
    referenced it.
    """
    names = set()
    for path in out_dir.glob("*__*"):
        prefix, sep, rest = path.name.partition("__")
        if sep and prefix.isdigit() and rest:
            names.add(rest)
    return names


def download_all(entries: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    fetched = already_fetched_names(out_dir)

    for i, entry in enumerate(entries, 1):
        if entry["name"] in fetched:
            continue
        dest = out_dir / f"{entry['work_bill_id']}__{entry['name']}"

        try:
            content = fetch(entry["name"])
            dest.write_bytes(content)
            fetched.add(entry["name"])
            print(f"[{i}/{len(entries)}] OK  {dest.name}")
        except requests.RequestException as exc:
            print(f"[{i}/{len(entries)}] FAIL {entry['name']}: {exc}")
            failures.append({**entry, "error": str(exc)})

        time.sleep(0.2)

    if failures:
        log_path = out_dir / "_download_failures.json"
        log_path.write_text(json.dumps(failures, indent=2))
        print(f"\n{len(failures)} failed; see {log_path}")
    else:
        log_path = out_dir / "_download_failures.json"
        log_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ward-number", type=float, default=-1, help="restrict to one ward (default: all wards)"
    )
    parser.add_argument(
        "--ward-name", default="", help="ward name, required alongside --ward-number"
    )
    parser.add_argument(
        "--only-known-jobs",
        action="store_true",
        help=(
            "only fetch attachments whose job_number appears in "
            "data_backend/json/works/works-*.json — skips PDFs that "
            "extract_road_segments.py could never match to a work record"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    job_filter = known_job_numbers() if args.only_known_jobs else None
    entries = road_history_files(args.ward_number, args.ward_name, job_filter)
    scope = "all wards" if args.ward_number == -1 else f"ward {args.ward_number} ({args.ward_name})"
    filter_note = " matching a known works-*.json job_number" if args.only_known_jobs else ""
    print(f"Found {len(entries)} Road History attachments for {scope}{filter_note}.")
    download_all(entries, OUT_DIR)