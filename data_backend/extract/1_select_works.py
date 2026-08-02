"""Step 1 — pick the first N distinct works from ds3 and resolve their documents.

ds3 is one row per BILL, not per work, so a work with 6 bills appears 6 times
with a different gross each time. We group to the work, sum the bills, and
union the attachments.

Usage:
    python3 1_select_works.py [--n 20] [--require-agreement]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import OrderedDict

from common import DS3_CSV, DOCTYPES_WANTED, OUT_DIR, award_fy, parse_documents_detail

csv.field_size_limit(sys.maxsize)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="number of distinct works")
    ap.add_argument(
        "--require-agreement",
        action="store_true",
        help="only keep works with a real (non-placeholder) Agreement PDF",
    )
    args = ap.parse_args()

    works: OrderedDict[str, dict] = OrderedDict()

    with DS3_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            wo = (row.get("WO") or "").strip()
            if not wo:
                continue

            if wo not in works:
                if len(works) >= args.n:
                    # Rows for an already-selected work may still appear later,
                    # so keep scanning rather than breaking outright.
                    continue
                works[wo] = {
                    "job_number": wo,
                    "description": (row.get("wcdescription") or "").strip(),
                    "contractor": (row.get("contractorname") or "").strip(),
                    "ddo": (row.get("ddoname") or "").strip(),
                    "budget_head": (row.get("budget") or "").strip(),
                    "billing_fy": row.get("financial_year"),
                    "award_fy": award_fy(wo),
                    "source_file": row.get("source_file"),
                    "bill_rows": 0,
                    "gross_total_rupees": 0.0,
                    "documents": [],
                    "_seen_files": set(),
                }

            w = works[wo]
            w["bill_rows"] += 1
            try:
                w["gross_total_rupees"] += float(row.get("gross") or 0)
            except ValueError:
                pass

            for doc in parse_documents_detail(row.get("documents_detail", "")):
                if doc["filename"] in w["_seen_files"]:
                    continue
                w["_seen_files"].add(doc["filename"])
                w["documents"].append(doc)

    selected = list(works.values())
    for w in selected:
        del w["_seen_files"]
        w["documents"].sort(key=lambda d: (d["doctype"], d["filename"]))
        w["targets"] = [
            d
            for d in w["documents"]
            if d["doctype"] in DOCTYPES_WANTED and not d["is_placeholder"]
        ]
        w["doc_count"] = len(w["documents"])
        w["placeholder_count"] = sum(1 for d in w["documents"] if d["is_placeholder"])

    if args.require_agreement:
        selected = [
            w
            for w in selected
            if any(d["doctype"] == "Agreement" for d in w["targets"])
        ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "works.json"
    out.write_text(json.dumps(selected, indent=2, ensure_ascii=False))

    n_targets = sum(len(w["targets"]) for w in selected)
    n_docs = sum(w["doc_count"] for w in selected)
    n_ph = sum(w["placeholder_count"] for w in selected)
    with_agr = sum(
        1 for w in selected if any(d["doctype"] == "Agreement" for d in w["targets"])
    )
    print(f"works selected      : {len(selected)}")
    print(f"attachments (unique): {n_docs}  ({n_ph} placeholders)")
    print(f"fetch targets       : {n_targets}")
    print(f"works w/ agreement  : {with_agr}")
    print(f"wrote               : {out}")


if __name__ == "__main__":
    main()
