# Step 3.5 — extraction (run by Claude Code, not by an API)

`3_prepare_pages.py` writes two queues, scoped to whatever `--jobs` you gave
it (or all of `works.json` if omitted) and safe to re-run — it skips any PDF
already triaged and merges into the existing queue files rather than
clobbering entries for jobs outside this run's scope:

- `output/text_queue.json` — PDFs with a real text layer. Each entry points to
  a `text_file` containing the full extracted text. **Read the text, parse the
  fields directly from it.** No regex, no rendering.
- `output/vision_queue.json` — PDFs without a usable text layer (scanned).
  Each entry gives the PDF path and `pages_total`. **Open the PDF directly
  with the Read tool** (it renders each page as an image natively — no
  separate PNG step) **and read every page before concluding a field is
  absent.**

Both queues feed the same output file: `output/vision_extract.json`, which
`4_assemble.py` consumes. The field is named `vision_extract.json` for
historical reasons — it holds the extraction result regardless of which
branch produced it; each record's `"method"` says which (`"text"` or
`"vision"`).

**There is no API client anywhere in this pipeline.** A human (or an agent
loop) drives this step — it is not a cron-able unattended job.

## Selective, not corpus-wide

Every step in this pipeline takes an explicit job-number scope and is safe to
re-run: `1_select_works.py --n` grows `works.json` without disturbing earlier
entries, `2_fetch_docs.py` skips anything already on disk, `3_prepare_pages.py
--jobs` triages only the jobs you name, and this extraction step should only
be pointed at the entries in `text_queue.json` / `vision_queue.json` for
**new** job numbers — check `output/vision_extract.json` for job numbers
already present and skip them. Never re-derive or overwrite an existing
record; append only.

## How to run it

Ask Claude Code, in this repo:

> Process `output/text_queue.json`: Read each `text_file` and extract the
> fields below directly from the text. Then process `output/vision_queue.json`:
> open each PDF directly with the Read tool and read every page — all of
> them, not just the first one or two — and extract the same fields. Skip any
> job_number already present in `output/vision_extract.json`. Append one JSON
> object per PDF to `output/vision_extract.json`. Do batches of ~10 PDFs per
> turn.

## Text-queue extraction

The text is plain, extracted `pdftotext -layout` output — not a rendered
image. Read it like a document, not like a regex target: pdftotext's layout
mode fragments clauses across column boundaries (a DLP clause can appear as
`"...paid.\n  liability period is three\nyear from..."` with unrelated column
text physically interleaved), so parse the way a person would — by
understanding the sentence — not by pattern-matching a fixed phrase order.
This is exactly why regex was dropped for this branch: it is blind to
fragmentation an LLM reads through without effort.

## Vision-queue extraction — read every page

**This is the rule that most needs enforcing.** On this corpus, DLP clauses
have turned up on page 3 of one office's template, page 4 of another
(4+ page document, clause list continuing past where a shorter agreement
would have ended), and page 7 of a third (the agreement re-stamps mid-document
with a second e-stamp, restarting numbered clauses). Contract amounts have
similarly been split across pages 2 and 4.

Concretely: for a PDF with `pages_total` = N, read all N pages via the Read
tool before writing `null`/omitting a field. Stopping after page 2 "because
that's usually enough" is exactly the mistake that produced 5+ wrong DLP
gradings earlier in this project (see `observations_running_doc.md`) — every
one of those was later found sitting in plain text on a page that had already
been available but never opened.

If a document is unusually long (8+ pages) and a field is still not found
after reading all of it, that is a legitimate absence — record it as such in
`notes`, don't guess.

## What to extract

Return one object per PDF, matching the shape `4_assemble.py` expects:

```json
{
  "job_number": "040-21-000010",
  "doctype": "Agreement",
  "pdf": "pdfs/040-21-000010/WO-6--30069398-AGR-040-21-10.pdf",
  "source_filename": "WO-6--30069398-AGR-040-21-10.pdf",
  "method": "vision",
  "is_pmc": false,
  "fields": {
    "tender_number": "BBMP/EE/KNG/TEN/13/2020-21",
    "tender_published_date": "28.07.2020",
    "agreement_number": "EE/KEN/AGMT/124/2020-21",
    "agreement_date": "28.08.2020",
    "estimate_rupees": 9000000,
    "amount_put_to_tender_rupees": 7574220.01,
    "amount_quoted_rupees": 7951003.88,
    "variance_raw": "+4.97% Above",
    "dlp_raw": "24 months",
    "work_code": "040-21-000010"
  }
}
```

`method` is `"text"` or `"vision"` depending on which queue the PDF came
from. `source_filename` is copied straight from the queue entry (needed for a
working download URL later — do not alter it).

## Rules

1. **Transcribe, do not infer.** If a field is not visibly present, omit the
   key. Never carry a value over from another document.
2. **Amounts in rupees, as numbers.** `Rs.90.00 Lakhs` → `9000000`.
   `79,51,003.88` → `7951003.88`. Indian digit grouping is 2-2-3, not 3-3-3;
   read the digits, not the comma pattern.
3. **Keep the three amounts distinct.** "Sanctioned/Estimate", "Amount put to
   tender", and "Amount quoted by bidder" are three different numbers. Track 4
   is exactly the comparison between them, so collapsing them destroys the
   deliverable.
4. **DLP verbatim into `dlp_raw`.** Do not convert. `three years` and
   `180 Days` mean different things — a completion period is not a defect
   liability period, and `4_assemble.py` grades that distinction. If a
   maintenance-style contract uses "guarantee period" instead, use that value
   and say so in `notes`.
5. **Flag PMC.** If the agreement is with a project management consultant
   (language like "the Consultant shall perform...", "PMC Services",
   "Project Management Consultant") rather than the civil contractor, set
   `is_pmc: true`. Its amounts must not be compared against the work's
   payout. The filename is not a reliable signal for this — read the body.
6. **A work can have multiple Agreement PDFs.** Civil contract and PMC
   contract are often both filed as doctype "Agreement". Read and record
   each one you can find; don't assume the first Agreement PDF is the civil
   one.
7. **Record contradictions rather than resolving them.** These are scans of
   handwritten-annotated documents; dates and agreement numbers are often
   overwritten. If a value appears twice with different content, put both in
   `notes` and omit the field. Assembly will grade it `NEEDS_REVIEW`.
8. **Say when a page is unreadable.** Set `"unreadable": true` with a short
   `notes`. A blank or illegible scan is a finding — `UNCLEAR` with a reason
   beats a guess.
9. **If a shared reference appears across multiple works** (e.g. the same
   tender number on two different job codes), note it rather than treating it
   as an error — one tender can legitimately cover multiple work packages.

## Cost control

- Text-queue PDFs cost no image tokens at all — this is why splitting the two
  branches matters, not just correctness.
- Vision-queue PDFs are opened directly with the Read tool — no PNG
  pre-rendering step, no DPI choice to make, no `output/pages/` directory to
  manage or clean up. The Read tool renders each page as it's needed.
- No page cap. Capping was tried and is what caused the page-3/4/7 DLP misses
  in the first place; BBMP agreements top out around 8 pages, so reading
  everything is cheap enough not to need one.
