# Civic Works Dashboard

Local dashboard for exploring generated BBMP work, payment and document data. The
server reads the pipeline output at `../data_backend/json/works.json` and exposes a
compact `/api/works` response without the large document and bill arrays.

The interface shows actual gross payments. Tender matches and point coordinates are
shown only when supported by the generated data; missing values are not fabricated.

## Run

The generated dataset is stored with Git LFS, so hydrate it before starting the
dashboard after a fresh clone:

```bash
git lfs pull
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
