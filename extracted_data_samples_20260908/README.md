# What's in this folder

Sample output from two extraction runs against BBMP work order documents, done
during and after the Aug 1 workshop. These are real results on real documents, not
mocked data. The point of sharing them is to show what an LLM-based extraction
script actually produces: the field structure, the confidence labelling, and where
it currently falls short.

Two separate things are covered here, and they come from different runs on
different document sets.

## 1. Extracting tender links, DLP clauses and amounts from work order documents

Files: `vision_extract.json`, `review_queue.json`

The idea: read the PDFs attached to a work order (agreements, tender documents)
and pull out three things per work: which tender it was awarded under, its
defects liability period, and the estimate/tendered/quoted/paid amounts. Claude
reads the document images directly (vision) rather than going through OCR first.

**`vision_extract.json`** is the raw, per-document output, 45 entries. One entry
per PDF read. Fields:

- `job_number`, `doctype` (e.g. "Agreement"), `pdf`, `source_filename` — which
  document this came from
- `method` — always "vision" in this file, meaning the page images were read
  directly, not OCR'd text
- `is_pmc` — true if this document is a PMC (project management consultancy)
  contract rather than the civil works contract, since these get mixed together
  in the document set and need to be told apart
- `fields` — the extracted data itself: `tender_number` and `tender_number_form`,
  three dates (tender published, administrative approval, technical sanction),
  `dlp_raw` (the defects liability period as stated in the document, e.g. "3
  years"), four amount fields (`estimate_rupees`, `amount_put_to_tender_rupees`,
  `amount_quoted_rupees`, plus `variance_raw`), `work_code`, and a free-text
  `notes` field

The `notes` field is worth reading closely in a few entries. It's where the
model records things a fixed schema can't: for example, in one entry it flags
that four separate job codes across the sample share the same tender number and
date, and reasons that this means one citywide tender notification covering many
job codes, not a data error. That kind of reasoning is genuinely useful and is
also exactly the kind of thing that needs a human to sanity-check before it's
trusted at scale.

**`review_queue.json`** is the rolled-up version, 30 entries, one per work order
rather than per document. This is the shape the review tool (`review.html` in
the extraction repo) actually displays. Fields:

- Work order metadata: `description`, `contractor`, `ward_hint`, `award_fy`,
  `billing_fy`, `paid_gross_rupees`, `bill_rows`, `documents_total` (how many
  documents are attached to this work order in total) and `documents_extracted`
  (how many of those were actually read for this run — usually far fewer than
  `documents_total`, since most attachments are photos or certificates that
  don't carry tender/DLP/amount data)
- `_notes` — free text on anything unusual caught during extraction or review.
  One entry here documents a real correction: the model initially read a "180
  Days" figure as the DLP, when that was actually the completion period: the
  real DLP clause was on a different page and was only caught after a manual
  spot-check. Left in deliberately, as an example of the kind of error this
  process needs to catch before the output is trusted.
- Three tracked fields, each structured the same way: a `value`, a
  `confidence` rating (STRONG, NEEDS_REVIEW or UNCLEAR), the `source_document`
  it came from, and a `reason` explaining why it got that confidence rating:
  - `track1_tender_link` — the tender this work was awarded under
  - `track3_dlp` — the defects liability period, also given as a `months` integer
  - `track4_amounts` — estimate, tendered, quoted and paid amounts, plus
    `variance_pct` (quoted vs tendered) and `payout_vs_contract_pct` (paid vs
    quoted)
- `source_documents` — list of every document behind this work order's fields

Confidence is not evenly distributed. Across this sample of 30: tender links
came back STRONG for 13, NEEDS_REVIEW for 9, UNCLEAR for 8. DLP came back
STRONG for 23, UNCLEAR for 7 (no NEEDS_REVIEW for that field in this sample).
So roughly a third of tender links and a quarter of DLP clauses in this batch
would need a human to look at them before being used as-is. That ratio is the
main thing to take away from this sample: the extraction works, but it knows
when it isn't sure, and a real deployment needs to route the NEEDS_REVIEW and
UNCLEAR cases to a person rather than publish them as fact.

## 2. Reading GPS coordinates off site photos

Files: `bommanahalli-o235-spatial.jsonl`, `bommanahalli-oo175-spatial.jsonl`,
`madivala-o190-spatial.jsonl`, plus `bommanahalli-o235.json` and
`madivala-o190.json` for source context.

Separate question from the one above: can a work order be placed on a map? BBMP
work orders don't have a latitude/longitude field anywhere in the source data.
What some of them have is site photos (before, in-progress, after) taken with a
GPS camera app, which burns the coordinates into the image itself as a visible
overlay, not as metadata. So this extraction is: fetch the photos attached to a
work order, read the burnt-in overlay, and pull out the coordinates.

**The `-spatial.jsonl` files** are the output, one JSON object per line, one
line per work order. Fields:

- `wcname`, `wbid`, `nameofwork` — identifies the work order
- `lat`, `long` — the coordinate the model settled on
- `coord_reads` — every individual reading it took across the photos for this
  work order, before reconciling to the single `lat`/`long` above. Multiple
  photos of the same site should read close to the same coordinate; when they
  don't agree, that disagreement is preserved here rather than silently
  averaged away
- `plus_code`, `place_name`, `address` — reverse-geocoded from the coordinate,
  where available
- `ocr_jobno` — the job number as read off the photo overlay itself, as a
  cross-check against `wcname`
- `overlay_family` — which GPS camera app style produced the photo. Only one
  overlay style ("GPS Map Camera") actually burns in a coordinate; a second,
  common style just prints a city name and date with no usable coordinate
- `source_photo_urls`, `n_photos_read` — which photos were read and how many
- `status` — `ok`, `no_photo_pdf` (no photo document attached to fetch), or
  `no_coords_sampled` (a photo exists but didn't carry a readable coordinate)
- `notes`, where present — flags an inferred or uncertain digit. One entry
  here notes that a longitude reading of 77.627 was inferred because the photo
  grid caused a 6 to slip to an 8, and cross-checks it against a nearby work
  order at the same building that read cleanly. This is the same kind of
  honest uncertainty-flagging as the `_notes` field in the extraction sample
  above, and matters for the same reason.

Across the three files: 37 of 65 work orders came back `ok` (a usable
coordinate), 19 had no photo document to even attempt, and 9 had a photo but no
readable coordinate in it. So roughly half of work orders with a photo actually
yield a point on a map, and that ratio should be treated as a rough scale, not
a precise forecast: it comes from 65 work orders across two wards.

**`bommanahalli-o235.json` and `madivala-o190.json`** are the full source work
order data behind two of the three spatial files above, included so the
spatial output can be traced back to what it started from. Each is a list of
work order records as scraped from the VSS portal: `slno`, `wcname`, `wbid`,
`nameofwork`, `amount`, `jobcode` (a raw HTML block with start/end dates, ward,
division, budget line and contractor, exactly as BBMP publishes it), `remarks`,
`brdetails` (order/sub-bill/bill/payment history), and a `documents` array
listing every attached file with its `type`, `filename` and source `url`. This
is what the spatial script reads from: it looks for documents of type "Photo -
Before Work", "Photo - Work In Progress" and "Photo - After Work" in this list,
fetches them, and attempts the coordinate read described above.
