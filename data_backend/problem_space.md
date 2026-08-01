# Data backend

## Build the work JSON

The generated work-centric dataset follows [`../data_schema.md`](../data_schema.md).
The pipeline writes the complete dataset to `data_backend/json/works/` as valid JSON
arrays of no more than 10,000,000 bytes each. This keeps every generated file small
enough for ordinary Git and avoids requiring Git LFS.

```bash
python3 data_backend/build_work_json.py
python3 data_backend/build_work_json.py --check
python3 -m unittest discover -s data_backend -p 'test_*.py'
```

Build metadata is written to `data_backend/json/works.manifest.json`. The dashboard
uses the manifest to load chunks in order. It records source-row deduplication,
tender-link failure reasons, status derivation, record counts, byte limits, file
sizes, and SHA-256 checksums.
