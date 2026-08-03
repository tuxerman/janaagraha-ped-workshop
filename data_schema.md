# Data Schema — Tender ⋈ Work ⋈ Location

**The contract between `data_backend/` and `dashboard/`.** The dashboard builds against
this shape; the backend guarantees it. Change it here first, then in code.

**Status:** v0.1 draft
**Unit convention:** all amounts in **rupees** (integers, no decimals). Source CSVs are
in rupees; the older CityDocs DB is in lakhs — convert at ingest, never at read.

---

## The shape

One record per **work** (a `job_number` / `WO`), with the tender that produced it and
the location where it happened attached as nested objects.

```
work
 ├── tender      (nullable — the join is inferential)
 ├── location    (nullable — coordinates are sparse)
 ├── documents[]
 └── bills[]
```

Why work-centric and not tender-centric: a citizen asks "what happened on my road",
which is a work. Also, works are the denser side — 8,203 works have documents, while
most of the 130,710 tenders have no executed work we can see.

---

## `work` — the root object

| Field | Type | Notes |
|---|---|---|
| `job_number` | string | **Primary key.** e.g. `115-23-000014`. Ward-FY-serial. |
| `description` | string | Free text. The main searchable field. |
| `ward_number` | int? | |
| `ward_name` | string? | NULL for centralised works (see `ward_scheme`) |
| `ward_scheme` | enum | `198` \| `225` \| `243` \| `369` \| `special`. **A ward number is meaningless without this** — the same integer is a different place across schemes. |
| `zone` | string? | e.g. `Mahadevapura` |
| `award_fy` | string | e.g. `2020-21`. Parsed from the job_number middle segment. |
| `contractor_name` | string | Spellings vary across sources; see `contractor_key` |
| `contractor_key` | string | Normalised (lowercased, punctuation and `M/s` stripped) for grouping |
| `budget_head` | string? | |
| `amount_gross` | int | rupees, summed across bills |
| `amount_net` | int | rupees |
| `amount_deduction` | int | rupees. `gross - deduction == net` must hold. |
| `estimated_amount` | int? | **Usually NULL.** No numeric estimate exists in source data — only an Estimates PDF. Populated only if extracted. |
| `bill_count` | int | A work averages ~6.6 bills |
| `first_bill_date` | date? | ISO `YYYY-MM-DD` |
| `last_bill_date` | date? | ISO |
| `status` | enum | `in_progress` \| `completed` \| `unknown`. **`unknown` ≠ incomplete** — see below. |

### On `status`

Derive from completion-certificate presence **and** recency. A work awarded last
quarter with no completion certificate is `in_progress`, not a transparency failure.
If you cannot tell, emit `unknown` — never default to `completed`.

---

## `tender` — nullable nested object

**This link is inferential. It is never automatically trustworthy.**

| Field | Type | Notes |
|---|---|---|
| `tender_number` | string | e.g. `BBMP/2020-21/OW/WORK_INDENT46586`. Joins `ds1.tenderNumber`. |
| `nit_id` | int? | KPPP's internal id, where known |
| `source` | enum | `kppp` \| `eproc` |
| `title` | string | |
| `department` | string | e.g. `Bruhat Bengaluru Mahanagara Palike` |
| `tender_value` | int? | rupees. Often NULL on non-finalised tenders. |
| `estimated_value` | int? | rupees |
| `published_date` | date? | ISO |
| `awarded_date` | date? | ISO |
| `status` | string | `EVALUATION_COMPLETED`, `AWARDED`, `RETENDERED`, … |
| `num_bidders` | int? | |
| **`link_method`** | enum | `pdf_extract` \| `text_match` \| `manual` — **required** |
| **`link_confidence`** | enum | `high` \| `medium` \| `low` — **required** |
| `link_evidence` | string? | e.g. the document filename the number came from |

### Confidence rules

| | Meaning |
|---|---|
| `high` | Tender number extracted from the work's own PDF **and** it exists in the tender corpus. Deterministic. |
| `medium` | Text match corroborated by ward **and** amount agreement (0.5–1.5×). |
| `low` | Text match alone, or corroborated on only one signal. |

Text matching alone is ~49% precise — **`low` genuinely means "might be wrong"**, and
the dashboard must show it as such. Do not collapse these into a single "matched" flag.

### `tender: null` is not evidence of anything

A missing tender may mean: never executed as a work · the document was never attached ·
the attachment was blank · OCR failed · the tender predates the portal. Record which in
`link_failure_reason` on the work:

```
no_attachment | blank_document | mislabelled_document | unreadable |
number_not_in_corpus | no_candidate_found
```

**Never report "this tender never became a work" from a missing row.**

### On `WORK_INDENT`

`WORK_INDENT<n>` is a **per-department, per-FY counter, not a global id** — indent 134
exists simultaneously in BECC, BMRCL, BSCC and BNCC. Always key on the full
`tender_number` string, or on `(department, fy, indent)`. Never on a bare indent number.

---

## `tender.contract` — nested object

Extracted from the work's **Agreement** PDF (`doc_type: "Agreement"`), which is the
signed contract between BBMP and the contractor. Present on 99.5% of works as a file,
though extractability is unmeasured.

| Field | Type | Notes |
|---|---|---|
| `tender_notification_number` | string? | e.g. `BBMP/EE/BD/Tend-09/2022-23`. **BBMP's own tender reference — not the KPPP `tender_number`.** See below. |
| `publish_date` | date? | ISO. Date tenders were invited, e.g. `2022-09-21`. |
| `job_number` | string? | e.g. `237-23-000008`. Should equal the parent `work.job_number` — **use it as a cross-check on the extraction.** |
| `estimate` | int? | rupees. The **sanctioned estimate**, e.g. `9000000`. |
| `contract_price` | int? | rupees. The **accepted bid**, e.g. `8699618`. |
| `variance_pct` | float? | Signed % of contract vs estimate, e.g. `-3.32` for "3.32% Below". Derive; don't trust the printed figure alone. |
| `agreement_number` | string? | e.g. `EE/BD/AGR-200/2022-23` |
| `agreement_date` | date? | ISO |
| `as_number` | string? | Administrative sanction, e.g. `EE/BD/AS/73/2022-23` |
| `ts_number` | string? | Technical sanction, e.g. `EE/BD/TS/197/22-23` |
| `sr_year` | string? | Schedule of Rates the estimate is based on, e.g. `2021-22` |
| `completion_days` | int? | Days allowed from entrustment, including monsoon |
| `source_document` | string | Filename the values came from |

### Why this block matters

**It closes the Track 4 gap.** `work.estimated_amount` is NULL almost everywhere
because no source CSV carries a numeric estimate. The agreement prints **both** the
sanctioned estimate and the accepted contract price, in rupees, in plain language:

> *"Technical sanctioned … for Rs. 90,00,000/- … accepted the tender of the contractor
> … at a contract price of Rupees 86,99,618.00 … at 3.32% Below the Current SR 2021-22"*

So estimate-vs-payout becomes a three-way comparison — **estimate → contract price →
actual paid** (`work.amount_gross`) — which is strictly more informative than the
two-way comparison the track asked for. Populate `work.estimated_amount` from
`contract.estimate` when extracted.

It also carries **`completion_days`**, the only time-commitment field found so far.
Combined with `first_bill_date` / `last_bill_date` it supports a delay measure, and it
is the nearest thing to a Track 3 (DLP) signal currently identified — the agreement's
defect-remedying clause lives in the same document.

### ⚠ Two different tender numbers — do not conflate

| | Example | Namespace |
|---|---|---|
| `tender.tender_number` | `BBMP/2020-21/OW/WORK_INDENT46586` | **KPPP portal.** Joins `ds1.tenderNumber`. |
| `contract.tender_notification_number` | `BBMP/EE/BD/Tend-09/2022-23` | **BBMP division-internal.** Does *not* join `ds1`. |

The notification number is the division's own file reference (the
`EE/.../YYYY-YY` format anticipated in `notes/20260620-kppp-tender-notes.md`). It is
useful for grouping works by division and tender round, and as corroboration — but the
KPPP join must use `tender_number`. **Treating the notification number as a KPPP key
will silently produce zero matches.**

### Extraction notes

- Agreement PDFs are **scanned** — expect no text layer; use vision.
- Page 1 is an e-Stamp certificate (agreement number, sanctioned estimate, parties).
  **Page 2 carries the substance** — notification number, job code, estimate, contract
  price, variance, completion days. Do not stop at page 1.
- Amounts appear in Indian digit grouping (`86,99,618.00`) and again as words. **Parse
  the words as a check on the digits** — this is free OCR validation.
- Assert `contract.job_number == work.job_number`. A mismatch means the wrong document
  was attached, which is a known failure mode.
- Confirmed reachable at both `account.bbmpgov.in` and `accounts.bbmp.gov.in`; the
  latter matches the TLS certificate, so **prefer `accounts.bbmp.gov.in` and skip the
  `-k` workaround.**

---

## `location` — nullable nested object

| Field | Type | Notes |
|---|---|---|
| `lat` | float? | WGS84 |
| `lng` | float? | |
| `precision` | enum | `point` \| `ward` \| `zone` \| `none` |
| `source` | enum | `photo_overlay` \| `geocoded_text` \| `ward_centroid` \| `manual` |
| `confidence` | enum | `high` \| `medium` \| `low` |
| `place_name` | string? | e.g. `Bommanahalli, Bengaluru` |
| `address` | string? | |
| `plus_code` | string? | |
| `n_photos_read` | int? | How many photos were inspected |
| `coord_reads` | float[]? | Individual readings before reconciliation — keeps the spread visible |
| `notes` | string? | Free text on reconciliation decisions |

### Reality check on coverage

**No source CSV contains a coordinate column.** Points come from GPS overlays burnt
into site photos, read by vision (EXIF is stripped server-side; OCR misreads digits).
Measured yield: **37 usable points from ~65 works (~57%)** in the only real test.

So expect `precision: "point"` on a minority of works. **`ward` precision is the
realistic default** — 87% of bills carry a usable ward name. A ward-level map is
honest and achievable; a point-level citywide map is not.

Centralised works (`CE Major Roads`, `CE Lakes`, `CE SWD`, …) have **no ward by
construction** — ~13% of bills. Emit `precision: "none"`, not a fabricated centroid.

This mirrors the existing format in `jana-demo-5jun/spatial/*.jsonl`.

---

## `documents[]`

| Field | Type | Notes |
|---|---|---|
| `doc_type` | string | `Tender Documents`, `M.B.`, `Road History`, `Photo - Before Work`, … |
| `filename` | string | |
| `url` | string | `https://account.bbmpgov.in/vssIFMS/Files1/<urlencoded filename>` |
| `is_placeholder` | bool | See below |

**Placeholder detection is not optional.** BBMP uploads stand-ins where no document
exists: `Not Applicable.gif`, `NOT APPLICALE FOR PMC.pdf` (their typo), and files
literally named `BLANK.pdf`. Naive counting overstates coverage — DPR is only 76% real.

Name-based filtering is **necessary but not sufficient**: a file called
`notification.pdf` can still render as a blank page, and one inspected "Tender
Documents" was actually a mislabelled Job Number Certificate. Treat `is_placeholder:
false` as "looks real", not "verified to contain something".

**Fetching:** the TLS certificate is `*.bbmp.gov.in` but the host is
`account.bbmpgov.in`, so validation fails and it looks like a dead link. Requires
`curl -k` / `verify=False`.

---

## `road_segments[]` — nullable, one block per source PDF

Linestring geometry read off "Road History Data Sheet" PDFs
(`data_backend/pdf/`, `doc_type: "Road History"`). A job can have several
Road History PDFs (one per road in a multi-road package job) — each becomes
its own block, so segments are never merged across documents into one lossy
list.

| Field | Type | Notes |
|---|---|---|
| `source_document` | string | Filename the segments came from |
| `extraction_method` | string | `ocr_visual_extraction` — the *segment coordinates* are always read from a 300dpi render of the page via `tesseract`, not the PDF's text layer (~70% of this PDF corpus has no usable text layer at all — scanned images). The *job_number*, separately, is resolved primarily by filename lookup (see below), with OCR only as a fallback. |
| `extraction_confidence` | enum | `high` \| `medium` — `high` when the job_number came from an exact filename lookup, an exact OCR read, or an OCR read corrected only via an independently-OCR'd ward number; `medium` when corrected by Hamming-distance against the ward's known job numbers (i.e. a likely but unconfirmed single-digit OCR fix) |
| `notes` | string | How the job_number was resolved; a standing caveat that OCR digit misreads are possible in the segment coordinates regardless of how confidently the job_number itself was matched |
| `segments[]` | array | `{ segment_number, length_m, start: {lat, lng}, end: {lat, lng} }` — one row of the PDF's "Segment Details" table |

### How the job_number is resolved

`download_road_history.py` saves each PDF as `{work_bill_id}__{original_name}`,
but its own fetch request is built from `original_name` alone —
`work_bill_id` never enters the URL, and drifts across `payments.parquet`
snapshots besides. So the primary match is a direct, OCR-free lookup: strip
the `{work_bill_id}__` prefix and look up `original_name` in
`payments.parquet`'s `files` column (`type: "Road History"`) to read
`job_number` straight off that row. Verified empirically unambiguous across
the whole corpus (0 of 54,966 distinct Road History filenames shared by more
than one job_number) — but checked, not assumed, on every run; an ambiguous
or missing filename falls back to reading the job_number off the OCR'd page
instead (regex over the rendered text, with a ward-corroborated correction
for single-digit misreads).

Produced by `data_backend/extract_road_segments.py`. Coverage is still
limited by overlap between the PDF corpus and the `works-*.json` corpus, not
by matching accuracy — as of the last full check, 137 downloaded Road
History PDFs have a job_number that exists in `payments.parquet` but not in
`works-*.json` (built from a different, apparently older snapshot,
`2. payments-2026-07-30.xlsx`). See
`data_backend/json/road_segments_extraction_report.json` for the full
per-PDF breakdown.

---

## `bills[]`

| Field | Type | Notes |
|---|---|---|
| `bill_type` | string | `Running`, `First and Final`, `Second and Final`, … |
| `gross` | int | rupees |
| `net` | int | rupees |
| `deduction` | int | rupees |
| `bill_date` | date? | ISO |
| `rtgs_date` | date? | ISO — when money actually moved |

**Two dates, two meanings.** Award year (from `job_number`) and payment date are
routinely in different financial years. When a user asks about "spending in 2023"
without saying which, **default to award year and state the assumption.**

---

## Example record

```json
{
  "job_number": "087-21-000011",
  "description": "Providing Tractor and Gangmen in Ward No .87 HAL Airport",
  "ward_number": 87,
  "ward_name": "HAL Airport",
  "ward_scheme": "198",
  "zone": "Mahadevapura",
  "award_fy": "2021-22",
  "contractor_name": "M/s. Example Contractors",
  "contractor_key": "example contractors",
  "amount_gross": 1561836,
  "amount_net": 1405652,
  "amount_deduction": 156184,
  "estimated_amount": null,
  "bill_count": 3,
  "first_bill_date": "2024-06-11",
  "last_bill_date": "2025-01-22",
  "status": "completed",

  "tender": {
    "tender_number": "BBMP/2020-21/OW/WORK_INDENT46586",
    "source": "eproc",
    "title": "Providing Tractor and Gangmen in Ward No .87 HAL Airport",
    "department": "Bruhat Bengaluru Mahanagara Palike",
    "tender_value": 1338333,
    "status": "EVALUATION_COMPLETED",
    "num_bidders": 1,
    "link_method": "pdf_extract",
    "link_confidence": "high",
    "link_evidence": "WO-9--06784844-TND.pdf",

    "contract": {
      "tender_notification_number": "BBMP/EE/BD/Tend-09/2022-23",
      "publish_date": "2022-09-21",
      "job_number": "237-23-000008",
      "estimate": 9000000,
      "contract_price": 8699618,
      "variance_pct": -3.32,
      "agreement_number": "EE/BD/AGR-200/2022-23",
      "agreement_date": "2023-03-23",
      "as_number": "EE/BD/AS/73/2022-23",
      "ts_number": "EE/BD/TS/197/22-23",
      "sr_year": "2021-22",
      "completion_days": 120,
      "source_document": "WO-6-L4-ifms435-69634915-4-agreement 237-23-08.pdf"
    }
  },

  "location": {
    "lat": 12.905750,
    "lng": 77.627564,
    "precision": "point",
    "source": "photo_overlay",
    "confidence": "high",
    "place_name": "Bommanahalli, Bengaluru",
    "n_photos_read": 5,
    "coord_reads": [12.905682, 12.905750, 12.908179]
  },

  "documents": [
    {
      "doc_type": "Tender Documents",
      "filename": "WO-9--06784844-TND.pdf",
      "url": "https://account.bbmpgov.in/vssIFMS/Files1/WO-9--06784844-TND.pdf",
      "is_placeholder": false
    }
  ],

  "bills": [
    { "bill_type": "Running", "gross": 520612, "net": 468551,
      "deduction": 52061, "bill_date": "2024-06-11", "rtgs_date": "2024-06-18" }
  ]
}
```

A work with no tender found and no coordinates — **the common case** — looks like:

```json
{
  "job_number": "068-19-000116",
  "description": "Special development works in main roads and cross roads in ward no 68",
  "tender": null,
  "link_failure_reason": "blank_document",
  "location": { "lat": null, "lng": null, "precision": "ward",
                "source": "ward_centroid", "confidence": "low" }
}
```

---

## Invariants

Assert these in the pipeline; they catch most cross-dataset bugs.

1. `amount_gross - amount_deduction == amount_net` (exact, in rupees)
2. `job_number` is unique across the dataset
3. Every `tender` object has both `link_method` and `link_confidence`
4. `tender == null` implies `link_failure_reason` is set
5. `location.precision == "point"` implies `lat` and `lng` are both non-null
6. `ward_number` is never emitted without `ward_scheme`
7. All amounts are integers in rupees — no floats, no lakhs
8. `contract.job_number`, when present, equals `work.job_number` — a mismatch means the
   wrong document was attached
9. `contract.tender_notification_number` is **never** used to join `ds1` — that is
   `tender.tender_number`'s job

---

## Open questions

- **Estimate values** — now reachable via `contract.estimate` from the Agreement PDF
  (see above), which also gives `contract_price`. **Unmeasured:** what fraction of the
  ~8,160 works with an Agreement file yield clean values. Sample 30–50 before planning
  around it.
- **DLP fields** — nothing in the structured data mentions defect liability, but the
  Agreement's defect-remedying clause is in the same document `contract` is parsed
  from. Extract the clause text while the PDF is open, then spec fields once its shape
  is known.
- **Road identity** — the anchor use case needs works grouped by *road stretch*, but no
  road identifier exists. `Road History` PDFs (66% of works) may carry one.
- **Multi-tender works** — a work may span several tenders. Current schema allows one.
  Revisit if extraction finds this is common.
