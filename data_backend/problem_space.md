# Data backend

## Build the work JSON

The generated work-centric dataset follows [`../data_schema.md`](../data_schema.md).
It is sharded into valid JSON arrays so no generated file approaches GitHub's
single-file size limit.

```bash
python3 data_backend/build_work_json.py
python3 data_backend/build_work_json.py --check
python3 -m unittest discover -s data_backend -p 'test_*.py'
```

Output and build metadata are written to `data_backend/json/works/`. The manifest
records source-row deduplication, tender-link failure reasons, status derivation,
record counts, file sizes, and SHA-256 checksums.
