"""Step 4 — merge extractions into one per-work record with a confidence grade.

Inputs:
  output/vision_extract.json  Claude's extraction results from step 3.5
                               (EXTRACTION_PROMPT.md) -- one record per PDF,
                               each carrying "method": "text" (parsed from a
                               real text layer) or "vision" (read from
                               rendered pages, all of them -- see
                               3_prepare_pages.py, no page cap)
  output/works.json           the ds3 selection

Output:
  output/review_queue.json    what the data review tool loads

Confidence is assigned by RULE, never by the extractor's own say-so -- a model
reporting its own certainty is not evidence. The grades follow the workshop
brief:

  STRONG        an explicit, well-formed identifier was read off the document
  NEEDS_REVIEW  a value was found but is ambiguous, malformed, or contradicted
  UNCLEAR       nothing usable; the reason is recorded so absence stays readable

Every field carries the source document it came from, so a reviewer can open the
exact PDF that produced it.

Usage:
    python3 4_assemble.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common import OUT_DIR

STRONG, REVIEW, UNCLEAR = "STRONG", "NEEDS_REVIEW", "UNCLEAR"

# A well-formed BBMP tender reference in either of the two observed shapes.
RE_TENDER_STRICT = re.compile(
    r"^BBMP/(?:\d{4}-\d{2}/[A-Z]{2,4}/WORK_INDENT\d+"
    r"|(?:[A-Z]{2,6}/){1,4}\d{1,4}/\d{4}-\d{2})$",
    re.I,
)


def load(name: str) -> list[dict]:
    p = OUT_DIR / name
    return json.loads(p.read_text()) if p.exists() else []


def grade_tender(value: str | None, source: str | None, note: str = "",
                 form: str | None = None, corroborated: bool = False) -> dict:
    """Track 1 confidence.

    The *form* of the reference matters more than whether one was found at all.
    A fully-qualified 'BBMP/2020-21/OW/WORK_INDENT46586' is a primary key. A
    bare 'Indent No. 52485' carries no year and no office, so it only joins if
    indent numbers turn out to be globally unique in ds1 -- which is exactly
    the WORK_INDENT trap noted in the June tender notes. Never grade it STRONG.
    """
    if not value:
        return {"value": None, "confidence": UNCLEAR, "source_document": source,
                "form": None, "reason": note or "no tender reference found in any document"}

    clean = re.sub(r"\s+", "", value)
    out = {"value": clean, "form": form, "source_document": source,
           "corroborated_across_documents": corroborated}

    if form == "bare_indent":
        return out | {
            "confidence": REVIEW,
            "reason": ("bare indent number with no year or office; joins to ds1 only "
                       "if indent numbers are globally unique -- verify before trusting")
            + (" (corroborated by a second document of this work)" if corroborated else ""),
        }

    if RE_TENDER_STRICT.match(clean) or form in ("kppp_work_indent", "bbmp_prose"):
        return out | {"confidence": STRONG,
                      "reason": "explicit well-formed tender number read from document"}

    if form == "eproc_notification":
        return out | {
            "confidence": REVIEW,
            "reason": ("e-proc notification number recovered from OCR text; separators "
                       "are frequently mangled (EE/MLP/TEND -> EEIMLPI) so normalise "
                       "before joining"),
        }

    return out | {"confidence": REVIEW,
                  "reason": "reference found but does not match a known BBMP tender format"}


def grade_dlp(raw: str | None, source: str | None) -> dict:
    """Track 3 confidence. Normalises 'three years' and '180 Days' to months."""
    if not raw:
        return {"value": None, "months": None, "confidence": UNCLEAR,
                "source_document": source, "reason": "no DLP clause found"}

    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    months = None
    if m := re.search(r"\b(one|two|three|four|five|\d+)\s*year", raw, re.I):
        tok = m.group(1).lower()
        months = (words.get(tok) or int(tok)) * 12
    elif m := re.search(r"\b(\d+)\s*month", raw, re.I):
        months = int(m.group(1))

    if months is not None:
        return {"value": raw, "months": months, "confidence": STRONG,
                "source_document": source, "reason": "explicit defect liability period"}

    # '180 Days' is the COMPLETION period, not the DLP. Recording it as DLP
    # would be wrong, so it is surfaced for a human rather than converted.
    if re.search(r"day", raw, re.I):
        return {"value": raw, "months": None, "confidence": REVIEW,
                "source_document": source,
                "reason": "only a completion period in days was found; "
                          "this is not necessarily the defect liability period"}

    return {"value": raw, "months": None, "confidence": REVIEW,
            "source_document": source, "reason": "DLP text found but not parseable"}


def grade_money(est, tendered, quoted, paid, source, is_pmc=False) -> dict:
    """Track 4 confidence: estimate vs agreement value vs eventual payout."""
    out = {
        "estimate_rupees": est,
        "amount_put_to_tender_rupees": tendered,
        "amount_quoted_rupees": quoted,
        "paid_gross_rupees": paid,
        "source_document": source,
        "is_pmc_contract": is_pmc,
    }

    if quoted and tendered:
        out["variance_pct"] = round((quoted - tendered) / tendered * 100, 2)
    if quoted and paid:
        out["payout_vs_contract_pct"] = round((paid - quoted) / quoted * 100, 2)

    if is_pmc:
        out["confidence"] = REVIEW
        out["reason"] = ("figures come from a PMC (consultant) agreement, a separate "
                         "contract from the civil work -- do not compare to work payout")
    elif quoted and tendered and est:
        out["confidence"] = STRONG
        out["reason"] = "estimate, tendered and quoted amounts all read from agreement"
    elif quoted or tendered or est:
        out["confidence"] = REVIEW
        out["reason"] = "only part of the estimate/tender/quote triple was found"
    else:
        out["confidence"] = UNCLEAR
        out["reason"] = "no contract amounts found"
    return out


def main() -> None:
    works = {w["job_number"]: w for w in load("works.json")}
    rows = load("vision_extract.json")

    by_work: dict[str, list[dict]] = {}
    for r in rows:
        by_work.setdefault(r["job_number"], []).append(r)

    review: list[dict] = []

    for job, w in works.items():
        docs = by_work.get(job, [])
        agreements = [d for d in docs if d["doctype"] == "Agreement"]
        # No fallback to a PMC agreement when it's all that was read: a PMC
        # contract's amounts/DLP belong to the consultant, not the work, so
        # using one here would silently reproduce the exact bug that motivated
        # detecting is_pmc from body text in the first place (040-23-000010,
        # 095-23-000001 -- both had their only-read Agreement turn out PMC).
        civil = [d for d in agreements if not d.get("is_pmc")]
        only_pmc_read = bool(agreements) and not civil
        tenders = [d for d in docs if d["doctype"] == "Tender Documents"]

        # --- Track 1: prefer the tender doc, fall back to the agreement ------
        t_val = t_src = t_form = None
        t_note = ""
        # Any document of this work may carry the reference; the work order and
        # the agreement often both print it, which is free corroboration.
        for d in tenders + civil + docs:
            f = d.get("fields") or {}
            if f.get("tender_number"):
                t_val = f["tender_number"]
                t_src = d.get("source_filename") or Path(d["pdf"]).name
                t_form = f.get("tender_number_form")
                break
        # Corroborated = the same reference appears in >1 document of this work.
        corrob = False
        if t_val:
            key = re.sub(r"\s+", "", t_val)
            corrob = sum(
                1 for d in docs
                if re.sub(r"\s+", "", (d.get("fields") or {}).get("tender_number") or "") == key
            ) > 1
        if not t_val:
            if not docs:
                t_note = "no fetchable Agreement/Tender document for this work"
            elif not tenders:
                t_note = "no Tender Document attached; agreement carried no reference"
            else:
                t_note = "documents present but no tender reference could be read"

        # --- Track 3 + 4: the civil agreement is the authority ---------------
        af = (civil[0].get("fields") or {}) if civil else {}
        a_src = (civil[0].get("source_filename") or Path(civil[0]["pdf"]).name) if civil else None
        is_pmc = False  # civil[] never contains a PMC doc by construction above

        amts = af.get("amounts_seen") or []
        est = af.get("estimate_rupees") or (max(amts) if amts else None)

        notes = [
            (d.get("fields") or {}).get("notes")
            for d in docs
            if (d.get("fields") or {}).get("notes")
        ]
        if only_pmc_read:
            notes.insert(0, "Only a PMC (consultant) Agreement was read for this work; "
                            "its civil-works Agreement was not extracted in this pass, "
                            "so Track 3/4 have no source and are UNCLEAR rather than "
                            "using the consultant's figures by mistake.")

        rec = {
            "job_number": job,
            "description": w["description"],
            "contractor": w["contractor"],
            "ward_hint": w["ddo"],
            "award_fy": w["award_fy"],
            "billing_fy": w["billing_fy"],
            "paid_gross_rupees": round(w["gross_total_rupees"], 2),
            "bill_rows": w["bill_rows"],
            "documents_total": w["doc_count"],
            "documents_extracted": len(docs),
            "_notes": notes,
            "track1_tender_link": grade_tender(t_val, t_src, t_note, t_form, corrob),
            "track3_dlp": grade_dlp(af.get("dlp_raw"), a_src),
            "track4_amounts": grade_money(
                est,
                af.get("amount_put_to_tender_rupees"),
                af.get("amount_quoted_rupees"),
                round(w["gross_total_rupees"], 2),
                a_src,
                is_pmc,
            ),
            # Everything the reviewer needs to open the originals themselves.
            "source_documents": [
                {"doctype": d["doctype"],
                 "file": d.get("source_filename") or Path(d["pdf"]).name,
                 "method": d.get("method"), "is_pmc": d.get("is_pmc", False)}
                for d in docs
            ],
        }
        review.append(rec)

    out = OUT_DIR / "review_queue.json"
    out.write_text(json.dumps(review, indent=2, ensure_ascii=False))

    def tally(key: str) -> dict:
        c: dict[str, int] = {}
        for r in review:
            g = r[key]["confidence"]
            c[g] = c.get(g, 0) + 1
        return c

    print(f"works assembled: {len(review)}\n")
    for k, label in [("track1_tender_link", "Track 1 (tender link)"),
                     ("track3_dlp", "Track 3 (DLP)"),
                     ("track4_amounts", "Track 4 (amounts)")]:
        t = tally(k)
        print(f"{label:24s} STRONG={t.get(STRONG,0):3d}  "
              f"NEEDS_REVIEW={t.get(REVIEW,0):3d}  UNCLEAR={t.get(UNCLEAR,0):3d}")
    print(f"\nwrote: {out}")


if __name__ == "__main__":
    main()
