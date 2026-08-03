#!/usr/bin/env python3
"""Fill in ``location.lat``/``lng`` on data_backend/json/works/works-*.json records,
one ward at a time.

``build_work_json.py`` already assigns each record a ward/zone-level ``location``
object (see its ``build_location``) but leaves ``lat``/``lng`` as ``null`` — the
source CSVs carry no coordinates. This script closes that gap for a single ward
(``--ward-number``), in two passes:

1. **OSM feature match** (precision "point", source "geocoded_text", confidence
   "medium"): fetch every named road and bridge/flyover inside the ward's OSM
   boundary via Overpass, then look for one of those names appearing in the
   record's free-text ``description`` (e.g. "Hennur Bagalur Road", "Chelikere
   Main Road"). The matched way's centre point is used, and the OSM way id is
   recorded in ``notes`` so the match is traceable back to the source feature.
2. **Ward centroid** (source "ward_centroid", confidence stays "low"): used for
   every record in the ward where no feature name was found in the description.

Per the project's linking rules, every filled-in point is inferential — none of
this is a surveyed coordinate — so precision/source/confidence are always set to
reflect how the point was derived, never upgraded to "high".

Uses two free OSM services, each with its own usage policy: Nominatim (ward
boundary + centroid lookup, ~1 request/second) and Overpass (ward feature
query, one request per ward). Both are cached to disk under
``data_backend/json/`` so repeat runs are free.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

WORKS_DIR = Path(__file__).resolve().parent / "json" / "works"
WARD_CACHE_FILE = Path(__file__).resolve().parent / "json" / "ward_geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "janaagraha-ped-workshop-geocoder/0.1 (+https://github.com/janaagraha; contact: sledulabs@gmail.com)"
NOMINATIM_INTERVAL_SECONDS = 1.1  # Nominatim usage policy: max ~1 request/second

_last_nominatim_request_at = 0.0


def _throttle_nominatim() -> None:
    global _last_nominatim_request_at
    elapsed = time.monotonic() - _last_nominatim_request_at
    if elapsed < NOMINATIM_INTERVAL_SECONDS:
        time.sleep(NOMINATIM_INTERVAL_SECONDS - elapsed)
    _last_nominatim_request_at = time.monotonic()


def load_ward_cache() -> dict[str, Any]:
    if WARD_CACHE_FILE.exists():
        return json.loads(WARD_CACHE_FILE.read_text())
    return {}


def save_ward_cache(cache: dict[str, Any]) -> None:
    WARD_CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def nominatim_search(query: str) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "format": "json",
        "limit": "1",
        "countrycodes": "in",
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    _throttle_nominatim()
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def fetch_ward_boundary(ward_name: str) -> dict[str, Any] | None:
    """Resolve a ward name to a centroid + bounding box via Nominatim.

    Tries "<ward_name> Ward, Bengaluru" first, falling back to the bare
    locality name — some wards resolve better without the literal word "Ward".
    """
    already_has_ward = "ward" in ward_name.lower()
    queries = (
        [f"{ward_name}, Bengaluru, Karnataka, India"]
        if already_has_ward
        else [
            f"{ward_name} Ward, Bengaluru, Karnataka, India",
            f"{ward_name}, Bengaluru, Karnataka, India",
        ]
    )
    for query in queries:
        try:
            results = nominatim_search(query)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  ! Nominatim lookup failed for {query!r}: {exc}", file=sys.stderr)
            continue
        if not results:
            continue
        result = results[0]
        south, north, west, east = (float(v) for v in result["boundingbox"])
        return {
            "centroid": {"lat": float(result["lat"]), "lng": float(result["lon"])},
            "bbox": [south, west, north, east],  # south, west, north, east
            "display_name": result["display_name"],
        }
    return None


HIGHWAY_AND_BRIDGE_QUERY = """
[out:json][timeout:60];
(
  way["highway"]["name"]({bbox});
  way["bridge"]["name"]({bbox});
);
out center tags;
"""


def fetch_ward_features(bbox: list[float]) -> list[dict[str, Any]]:
    """Query Overpass for named roads/bridges/flyovers inside `bbox`.

    `bbox` is [south, west, north, east] (Nominatim order); Overpass wants the
    same order for a plain bbox filter.
    """
    bbox_str = ",".join(str(v) for v in bbox)
    query = HIGHWAY_AND_BRIDGE_QUERY.format(bbox=bbox_str)
    request = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.loads(response.read())

    features = []
    seen_names_and_centers: set[tuple[str, float, float]] = set()
    for element in data.get("elements", []):
        name = element.get("tags", {}).get("name")
        center = element.get("center")
        if not name or not center:
            continue
        key = (name, round(center["lat"], 5), round(center["lon"], 5))
        if key in seen_names_and_centers:
            continue
        seen_names_and_centers.add(key)
        features.append(
            {
                "name": name,
                "lat": center["lat"],
                "lng": center["lon"],
                "way_id": element["id"],
                "highway": element.get("tags", {}).get("highway"),
                "bridge": element.get("tags", {}).get("bridge"),
            }
        )
    return features


def get_ward_data(ward_name: str, cache: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch (or reuse from cache) boundary + features for one ward name."""
    if ward_name in cache:
        return cache[ward_name]

    boundary = fetch_ward_boundary(ward_name)
    if boundary is None:
        print(f"  ! could not resolve ward boundary for {ward_name!r}", file=sys.stderr)
        cache[ward_name] = None
        return None

    print(f"  resolved {ward_name!r} -> {boundary['display_name']}")
    try:
        features = fetch_ward_features(boundary["bbox"])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"  ! Overpass query failed for {ward_name!r}: {exc}", file=sys.stderr)
        features = []
    print(f"  found {len(features)} named roads/bridges in {ward_name!r}")

    ward_data = {"boundary": boundary, "features": features}
    cache[ward_name] = ward_data
    return ward_data


# Generic trailing words stripped repeatedly from a feature name to get its
# distinctive "core" (e.g. "Hennur Bagalur Main Road" -> "Hennur Bagalur").
# Matching on the core avoids missing a hit just because the work description
# says "main road" where OSM says "Road", or vice versa.
GENERIC_SUFFIX_WORDS = {"road", "street", "st", "main", "cross", "drive"}
MIN_CORE_LENGTH = 6  # below this, a core is too generic/short to match on safely


def feature_core_name(name: str) -> str:
    words = name.strip().split()
    while words and words[-1].lower() in GENERIC_SUFFIX_WORDS:
        words.pop()
    return " ".join(words)


def normalize_for_matching(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def match_feature(description: str, features: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the most specific OSM feature whose core name appears in `description`.

    Longer core names are tried first, so a specific match (e.g. "Hennur
    Bagalur") wins over a shorter, more generic one that happens to also
    appear. Returns None if nothing distinctive enough matched.
    """
    normalized_description = normalize_for_matching(description)

    candidates = []
    for feature in features:
        core = feature_core_name(feature["name"])
        if len(core) < MIN_CORE_LENGTH or not re.search(r"[a-z]{4,}", core.lower()):
            continue
        candidates.append((core, feature))
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)

    for core, feature in candidates:
        pattern = r"\b" + r"\s+".join(re.escape(w) for w in normalize_for_matching(core).split()) + r"\b"
        if re.search(pattern, normalized_description):
            return feature
    return None


def geocode_record(record: dict[str, Any], ward_data: dict[str, Any] | None) -> bool:
    """Fill in `record["location"]` lat/lng in place. Returns True if changed."""
    location = record.get("location")
    if not location or location.get("lat") is not None or location["precision"] != "ward":
        return False
    if ward_data is None:
        return False

    ward_name = record["ward_name"]
    feature = match_feature(record["description"], ward_data["features"])
    if feature is not None:
        location["lat"] = feature["lat"]
        location["lng"] = feature["lng"]
        location["precision"] = "point"
        location["source"] = "geocoded_text"
        location["confidence"] = "medium"
        location["place_name"] = f"{feature['name']}, {ward_name}, Bengaluru"
        way_url = f"https://www.openstreetmap.org/way/{feature['way_id']}"
        location["notes"] = (
            f"Point taken from OSM way {feature['way_id']} ({way_url}), matched "
            f"because {feature['name']!r} appears in the work description; a "
            f"fuzzy text match against ward-scoped OSM road/bridge features, not "
            f"a surveyed coordinate."
        )
        return True

    centroid = ward_data["boundary"]["centroid"]
    location["lat"] = centroid["lat"]
    location["lng"] = centroid["lng"]
    location["notes"] = (
        "Ward centroid resolved via OpenStreetMap Nominatim from the ward name; "
        "no road/bridge name from the work description matched an OSM feature "
        "in this ward, and no point coordinates exist in the source CSVs."
    )
    return True


def process_file(
    path: Path,
    ward_number: int,
    ward_cache: dict[str, Any],
    dry_run: bool,
) -> int:
    records = json.loads(path.read_text())
    updated = 0
    for record in records:
        if record.get("ward_number") != ward_number:
            continue
        ward_data = get_ward_data(record["ward_name"], ward_cache)
        if geocode_record(record, ward_data):
            updated += 1

    if updated and not dry_run:
        path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ward-number",
        type=int,
        required=True,
        help="only geocode records for this ward_number (prototype is scoped to one ward at a time)",
    )
    parser.add_argument(
        "--files",
        default="works-*.json",
        help="glob pattern (relative to data_backend/json/works/) of files to scan",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="geocode and report counts but do not write the works-*.json files",
    )
    args = parser.parse_args()

    files = sorted(WORKS_DIR.glob(args.files))
    if not files:
        print(f"No files matching {args.files!r} in {WORKS_DIR}", file=sys.stderr)
        sys.exit(1)

    ward_cache = load_ward_cache()
    try:
        total_updated = 0
        for path in files:
            updated = process_file(path, args.ward_number, ward_cache, args.dry_run)
            if updated:
                print(f"{path.name}: {updated} records geocoded")
            total_updated += updated
        print(f"Done. {total_updated} records geocoded for ward {args.ward_number}.")
    finally:
        save_ward_cache(ward_cache)


if __name__ == "__main__":
    main()