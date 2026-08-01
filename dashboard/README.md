# Civic Tenders Dashboard

Local dashboard for viewing civic tenders. No dependencies — plain Node.js.

Includes a lightweight offline map (plain SVG, no external tiles or network calls)
plotting each tender's approximate location. Positions are illustrative, not exact
GPS. Click a pin to isolate that tender in the table below.

## Run

```bash
node server.js
```

Then open http://localhost:3000

Data is sample/pseudo data loaded from `data/tenders.json` — see [`../CLAUDE.md`](../CLAUDE.md)
for why the dashboard team builds against sample data only.
