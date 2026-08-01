# Civic Tenders Dashboard

Local dashboard for viewing civic tenders. No server-side dependencies — plain
Node.js backend.

## Map

The map uses [Leaflet](https://leafletjs.com/) with real OpenStreetMap tiles,
plotting each tender's approximate location. Positions are illustrative, not
exact GPS. Click a pin to isolate that tender in the table below.

**Note:** this requires internet access to load map tiles and the Leaflet
library (both from CDN). That's a deliberate exception to the "local sample
data only, no network calls" rule in [`../CLAUDE.md`](../CLAUDE.md) — everything
else (tender data, filtering, charts) still runs entirely offline.

## Charts

Below the table: a donut chart of tenders by status, and a donut chart of
estimated spend by ward. Both are drawn as plain inline SVG (no charting
library) and update live with the table's filters.

## Run

```bash
node server.js
```

Then open http://localhost:3000

Tender data is sample/pseudo data loaded from `data/tenders.json` — see
[`../CLAUDE.md`](../CLAUDE.md) for why the dashboard team builds against sample
data only.
