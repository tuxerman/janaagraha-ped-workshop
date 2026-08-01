# Civic Works Dashboard

Local dashboard for exploring generated BBMP work, payment and document data. The
server reads the pipeline manifest at `../data_backend/json/works.manifest.json`,
loads its ordered JSON chunks, and exposes a compact `/api/works` response without
the large document and bill arrays.

The interface shows actual gross payments. Tender matches and point coordinates are
shown only when supported by the generated data; missing values are not fabricated.

## Run

```bash
node server.js
```

Then open <http://localhost:3000>.

## Test

```bash
npm test
```

The Leaflet map uses OpenStreetMap tiles when point coordinates are available. The
current source files contain ward labels but no point coordinates, so the dashboard
shows an explicit empty-map state instead.
