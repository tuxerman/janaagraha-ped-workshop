# Data backend

## Build the work JSON

The generated work-centric dataset follows [`../data_schema.md`](../data_schema.md).
The pipeline writes the complete dataset to `data_backend/json/works.json`. Because
the generated file is larger than GitHub's normal 100 MB blob limit, the repository
tracks it with Git LFS.

```bash
python3 data_backend/build_work_json.py
python3 data_backend/build_work_json.py --check
python3 -m unittest discover -s data_backend -p 'test_*.py'
```

Build metadata is written to `data_backend/json/works.manifest.json`. The manifest
records source-row deduplication, tender-link failure reasons, status derivation,
record counts, file sizes, and SHA-256 checksums.
