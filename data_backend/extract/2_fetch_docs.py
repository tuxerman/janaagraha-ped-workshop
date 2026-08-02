"""Step 2 — download the target PDFs listed in works.json.

Fetching is separated from extraction so that a network failure never costs the
(expensive) extraction work, and re-runs are cheap: anything already on disk is
skipped.

Usage:
    python3 2_fetch_docs.py [--limit 0] [--workers 6]
"""

from __future__ import annotations

import argparse
import json
import urllib3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from common import OUT_DIR, PDF_DIR, safe_name

# The cert is *.bbmp.gov.in and the host is account.bbmpgov.in -- a genuine SAN
# mismatch on BBMP's side, not a MITM. We verify=False deliberately; these are
# public read-only documents with no credentials in the request.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEOUT = 90


def fetch_one(job: tuple[str, str, str]) -> dict:
    job_number, url, filename = job
    dest = PDF_DIR / job_number / safe_name(filename)
    rec = {"job_number": job_number, "filename": filename, "url": url,
           "path": str(dest.relative_to(OUT_DIR))}

    if dest.exists() and dest.stat().st_size > 0:
        rec |= {"status": "cached", "bytes": dest.stat().st_size}
        return rec

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, timeout=TIMEOUT, verify=False)
    except Exception as exc:
        return rec | {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    if r.status_code != 200:
        return rec | {"status": "http_error", "http_status": r.status_code}

    body = r.content
    # A 200 with an HTML body is the portal's soft-404 for a missing file.
    if body[:5] not in (b"%PDF-", b"%PDF"):
        head = body[:200].lstrip().lower()
        if b"<html" in head or b"<!doc" in head:
            return rec | {"status": "not_a_pdf", "bytes": len(body)}

    dest.write_bytes(body)
    return rec | {"status": "ok", "bytes": len(body),
                  "content_type": r.headers.get("Content-Type", "")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    works = json.loads((OUT_DIR / "works.json").read_text())

    jobs: list[tuple[str, str, str]] = [
        (w["job_number"], d["url"], d["filename"])
        for w in works
        for d in w["targets"]
    ]
    if args.limit:
        jobs = jobs[: args.limit]

    print(f"fetching {len(jobs)} documents with {args.workers} workers ...")
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, rec in enumerate(pool.map(fetch_one, jobs), 1):
            results.append(rec)
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}")

    log = OUT_DIR / "fetch_log.json"
    log.write_text(json.dumps(results, indent=2))

    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total_mb = sum(r.get("bytes", 0) for r in results) / 1e6

    print("\nstatus:", counts)
    print(f"downloaded: {total_mb:.1f} MB")
    print(f"wrote     : {log}")


if __name__ == "__main__":
    main()
