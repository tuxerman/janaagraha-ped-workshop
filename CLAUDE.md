# Janaagraha PED Workshop

Public Expenditure Dashboard — built at the Janaagraha Data Jam (1 Aug 2026) and
continuing after it.

**The vision:** turn Bengaluru's raw procurement and public-works data into something
a resident can actually read — a view that follows public money from budget line to
completed work, ward by ward. What no existing portal does is *link* the tender, the
contractor, the bills, the photos and the location into one thread.

---

## Two independent workstreams

This repo holds two efforts by **two teams working in parallel**. They are
deliberately decoupled so neither blocks the other.

```
dashboard/       What citizens see. Reads the generated work summaries.
data_backend/    Extraction scripts + the real data pipeline.
```

**The contract between them is the data schema — nothing else.** The dashboard team
never waits for a scraper to finish; the backend team never waits for a UI decision.
Agree the shape of the JSON early, then work independently against it.

---

## `dashboard/`

The citizen-facing dashboard.

The local server reads the chunk manifest at
`data_backend/json/works.manifest.json`, generated from the source workbooks
according to `data_schema.md`. It exposes compact work summaries to the browser
rather than transferring the full document and bill arrays. Derived values, missing
tender links and sparse locations must remain visibly qualified.

### The spec lives in a markdown file

`dashboard/SPEC.md` is the source of truth for what gets built, written and owned by
the dashboard team. It should cover:

- **What the dashboard looks like** — screens, layout, primary view, navigation
- **Who the users are** — resident, community leader, journalist, ward official. They
  want different things; say which ones this serves and which it does not.
- **What questions it answers** — write these as literal questions a user would ask
  ("How much was spent on my road in the last 5 years?"). This is the most important
  section: it defines done.
- **What data each answer needs** — the fields required, which drives the schema
  contract with `data_backend/`
- **What is explicitly out of scope** — for this iteration

Update `SPEC.md` when the plan changes. A stale spec is worse than none.

### Rules

- Generated data is loaded from disk; the browser makes no direct source-system calls
- **Label uncertainty visibly in the UI.** A dashboard about government transparency
  must not present missing or inferred fields as authoritative facts.
- Keep the data-loading layer thin and in one place, so swapping sample → real is a
  small change
- Design against the schema in `data_backend/`, not against whatever the sample
  happens to contain

---

## `data_backend/`

Extraction scripts and the pipeline that produces the real data.

Covers the workshop's four tracks:

| Track | Question |
|---|---|
| **1 — Match tenders to works** | Which tenders actually became executed works? |
| **2 — Map projects geospatially** | Can a citizen find these works on a map of their ward? |
| **3 — DLP & maintenance** | Is the contractor still on the hook — is the city paying twice? |
| **4 — Estimate vs payout** | Does a work cost what it was estimated to? |

Anchor use case: **Road History** — for any stretch, assemble its full history in one
place so a resident can see everything spent on it and whether repeated work is
justified.

### Responsibilities

- Ingest / scrape / parse source data (tenders, payments, work documents)
- Extraction scripts — including PDF and vision-based extraction
- **Define and publish the output schema** the dashboard consumes
- Produce the sample data the dashboard develops against
- Document what each source covers and, crucially, what it does not

### Rules

- **Every derived link carries a `method` and a `confidence`.** Matches between
  datasets are inferential. A fuzzy match must never be presented as certain.
- **Distinguish "in progress" from "missing."** A new work without a completion
  certificate is early in its life, not a transparency failure.
- **Absence is not evidence.** A tender with no linked work may mean it was never
  executed, *or* the document was never attached, *or* extraction failed. Record which.
- **Leave a trail.** Note method and assumptions so the next person can build on it.
- Prefer scoping small and finishing — one ward or one year, end to end, beats a
  half-built citywide pipeline.



---

## Conventions

- Python 3.11+, type hints, `pathlib.Path` not strings
- Plain functions over class hierarchies
- Comments only when the *why* is non-obvious
- Amounts: state the unit at every boundary. Source CSVs are in **rupees**; the older
  CityDocs DB is in **lakhs**. Most cross-dataset bugs start here.
