# Dashboard Spec

**Status:** DRAFT — template, not yet filled in
**Owner:** dashboard team
**Last updated:** _(date)_

This is the source of truth for what gets built. Fill in each section; delete the
prompts in _italics_ as you go. **A stale spec is worse than none** — update it when
the plan changes.

The **Questions it answers** section is the most important one. It defines done.

---

## 1. What this is

_One paragraph. What does a person see when they land on this, and what do they walk
away with? Write it as if explaining to a resident, not a developer._

---

## 2. Who it is for

Different users want very different things. Say which ones this serves — **and which
it does not.** Serving everyone means serving no-one.

| User | What they want | In scope? |
|---|---|---|
| **Resident** | Is my road being fixed? Was money spent near me? | _yes / no_ |
| **Community leader** | Ward-level patterns; something to take to an official | _yes / no_ |
| **Journalist** | Outliers, repeated work, contractor patterns | _yes / no_ |
| **Ward official / engineer** | Status of works they are accountable for | _yes / no_ |

**Primary user for this iteration:** _(pick exactly one)_

_Why this one: (one line)_

---

## 3. Questions it answers

Write these as **literal questions a user would ask, in their words.** Not features,
not screens — questions. If the dashboard can't answer it, it isn't done.

| # | Question | User | Priority |
|---|---|---|---|
| Q1 | _e.g. "How much has been spent on my road in the last 5 years?"_ | Resident | Must |
| Q2 | _e.g. "Which works in my ward are still unfinished?"_ | | Must |
| Q3 | | | Should |
| Q4 | | | Could |

_Rule of thumb: 3–5 "Must" questions is a good scope for a first iteration._

---

## 4. What it looks like

### Screens

_List each screen and its job in one line._

| Screen | Purpose |
|---|---|
| _Landing / ward view_ | |
| _Work detail_ | |
| _Road history_ | |

### Primary view

_What's on screen first? Sketch it in ASCII, or describe the layout. What is the one
thing a user should notice within 3 seconds?_

```
(sketch here)
```

### Navigation

_How does a user get from the landing view to a specific work? Search, map click,
ward picker, list?_

---

## 5. Data each answer needs

This drives the schema contract with `data_backend/`. For each Must question, list the
fields required. **If a field isn't in `data_backend/SCHEMA.md`, flag it there — don't
invent it locally.**

| Question | Fields needed | Available? |
|---|---|---|
| Q1 | _ward, work_description, amount, year_ | |
| Q2 | | |

**Gaps** — things the UI wants that the data cannot currently provide:

- _e.g. precise road geometry — only ward-level location exists today_

---

## 6. Handling uncertainty

The backend emits `confidence` and `method` on derived links (see
`data_backend/SCHEMA.md`). **The UI must not flatten these away.**

Decide and record here:

- **How is a low-confidence link shown?** _(badge / muted styling / hidden entirely)_
- **How is missing data distinguished from zero?** "No completion certificate" and
  "₹0 spent" are completely different claims.
- **How is "in progress" distinguished from "missing"?** A new work without a
  completion certificate is early in its life, not a scandal.
- **Where does the pseudo-data banner appear?** _(required while on sample data)_

---

## 7. Out of scope

_Be explicit. This is what stops scope creep at 3pm._

- _e.g. citywide map — ward-level only for this iteration_
- _e.g. contractor profiles_
- _e.g. login / user accounts_

---

## 8. Open questions

_Things blocking a decision. Assign each one an owner._

| Question | Owner | Status |
|---|---|---|
| | | |
