#!/usr/bin/env python3
"""Normalize osmium-exported OSM water features into the ZWL water-sources dataset.

Input: GeoJSON from `osmium export --geometry-types=point` on a tag-filtered
Poland extract. Output: `dist/water-<version>.geojson` (plain GeoJSON) plus
`dist/manifest.json` (frozen contract, see docs/water-sources-PLAN.md 3.4).

Python 3 standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

TAG_RULES = (
    ("amenity", "drinking_water", "DRINKING_WATER"),
    ("man_made", "water_tap", "WATER_TAP"),
    ("amenity", "water_point", "WATER_POINT"),
    ("natural", "spring", "SPRING"),
    ("man_made", "water_well", "WELL"),
    ("amenity", "fountain", "FOUNTAIN"),
)

CONFIRMED_TYPES = frozenset(("DRINKING_WATER", "WATER_TAP", "WATER_POINT"))

YES_VALUES = frozenset(("yes", "true", "1"))
NO_VALUES = frozenset(("no", "false", "0"))

REJECTED_ACCESS = frozenset(("private", "no"))

TYPE_PREFIX = {
    "node": "n",
    "way": "w",
    "relation": "r",
    "n": "n",
    "w": "w",
    "r": "r",
}


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Normalize OSM water sources into GeoJSON + manifest.")
    parser.add_argument("--input", required=True, help="raw GeoJSON exported by osmium")
    parser.add_argument("--previous-manifest", required=True, help="previous manifest.json or {} placeholder")
    parser.add_argument("--outdir", required=True, help="output directory for water-<version>.geojson + manifest.json")
    return parser.parse_args(argv)


def feature_type(tags):
    for key, value, type_name in TAG_RULES:
        if tags.get(key) == value:
            return type_name
    return None


def identify(feature, tags):
    props = feature.get("properties") or {}
    raw_id = props.get("@id")
    if raw_id is None:
        raw_id = props.get("osm_id")
    if raw_id is None:
        raw_id = feature.get("id")
    if raw_id is None:
        return None, None

    raw_type = props.get("@type")
    if raw_type is None:
        raw_type = props.get("osm_type")
    if raw_type is None:
        raw_type = tags.get("type")
    if raw_type is None:
        raw_type = feature.get("type")
    if raw_type is None:
        return None, None

    prefix = TYPE_PREFIX.get(str(raw_type).lower())
    if prefix is None:
        return None, None

    return "%s%s" % (prefix, raw_id), prefix


def drinking_water_status(tags, type_name):
    raw = tags.get("drinking_water")
    if raw is not None:
        value = str(raw).strip().lower()
        if value in YES_VALUES:
            return "YES"
        if value in NO_VALUES:
            return "NO"
        return "UNKNOWN"
    if type_name in CONFIRMED_TYPES:
        return "YES"
    return "UNKNOWN"


def parse_depth(tags, type_name):
    if type_name != "WELL":
        return None
    raw = tags.get("depth")
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value.endswith("m"):
        value = value[:-1].strip()
    try:
        depth = float(value)
    except (TypeError, ValueError):
        return None
    if depth != depth:
        return None
    return depth


def point_coordinates(feature):
    geometry = feature.get("geometry") or {}
    if geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
        return None
    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None
    if longitude != longitude or latitude != latitude:
        return None
    if not (-180.0 <= longitude <= 180.0) or not (-90.0 <= latitude <= 90.0):
        return None
    return round(longitude, 6), round(latitude, 6)


def normalize_feature(feature):
    tags = feature.get("properties") or {}
    if not isinstance(tags, dict):
        return None

    type_name = feature_type(tags)
    if type_name is None:
        return None

    if type_name == "FOUNTAIN" and str(tags.get("drinking_water", "")).strip().lower() not in YES_VALUES:
        return None

    access = tags.get("access")
    if access is not None and str(access).strip().lower() in REJECTED_ACCESS:
        return None

    if str(tags.get("disused", "")).strip().lower() in YES_VALUES:
        return None

    coordinates = point_coordinates(feature)
    if coordinates is None:
        return None

    osm_id, _ = identify(feature, tags)
    if osm_id is None:
        return None

    longitude, latitude = coordinates
    name = tags.get("name") or ""
    drinking = drinking_water_status(tags, type_name)
    depth = parse_depth(tags, type_name)

    return {
        "osmId": osm_id,
        "type": type_name,
        "name": name,
        "drinkingWater": drinking,
        "verified": False,
        "depthMeters": depth,
        "notes": None,
        "_coordinates": (longitude, latitude),
    }


def build_geojson(features):
    output_features = []
    for feature in features:
        longitude, latitude = feature["_coordinates"]
        output_features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {
                    "osmId": feature["osmId"],
                    "type": feature["type"],
                    "name": feature["name"],
                    "drinkingWater": feature["drinkingWater"],
                    "verified": feature["verified"],
                    "depthMeters": feature["depthMeters"],
                    "notes": feature["notes"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": output_features}


def read_previous_version(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return 0
    if not isinstance(data, dict):
        return 0
    version = data.get("version")
    try:
        return int(version)
    except (TypeError, ValueError):
        return 0


def main(argv):
    args = parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    raw_features = raw.get("features") or []

    deduped = {}
    for feature in raw_features:
        normalized = normalize_feature(feature)
        if normalized is None:
            continue
        osm_id = normalized["osmId"]
        if osm_id in deduped:
            continue
        deduped[osm_id] = normalized

    features = list(deduped.values())

    now = datetime.datetime.now(datetime.timezone.utc)
    today = int(now.strftime("%Y%m%d"))
    previous_version = read_previous_version(args.previous_manifest)
    version = max(today, previous_version + 1)

    collection = build_geojson(features)
    payload = json.dumps(collection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    os.makedirs(args.outdir, exist_ok=True)
    file_name = "water-%d.geojson" % version
    file_path = os.path.join(args.outdir, file_name)
    with open(file_path, "wb") as handle:
        handle.write(payload)

    manifest = {
        "version": version,
        "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file": file_name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "count": len(features),
        "sources": ["OSM"],
    }
    with open(os.path.join(args.outdir, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print("version=%d count=%d bytes=%d file=%s" % (version, len(features), len(payload), file_name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
