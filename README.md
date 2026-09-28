# zwl-data

Water sources dataset for the ZWL app (Android + iOS, KMP).

Generated monthly (and on demand) by [`.github/workflows/build.yml`](.github/workflows/build.yml)
from OpenStreetMap data, published to GitHub Pages:

- `manifest.json` — dataset contract (version, file, sha256, bytes, count)
- `water-<version>.geojson` — normalized point features (plain GeoJSON)

## Source

Features are filtered and normalized from Geofabrik's Poland OSM extract
(`https://download.geofabrik.de/europe/poland-latest.osm.pbf`):

- `amenity=drinking_water`, `man_made=water_tap`, `amenity=water_point`,
  `natural=spring`, `man_made=water_well`, `amenity=fountain` (only with `drinking_water=yes`)
- `access` in `{private, no}` and `disused=yes` are dropped
- deduplicated by `osmId`

No PBF/extract intermediates are committed — only the final GeoJSON and manifest.

## Attribution / licence

Water source data © OpenStreetMap contributors, available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/).
See <https://www.openstreetmap.org/copyright>.

Because the modified database is redistributed (bundled app baseline and
downloaded dataset), the ODbL attribution applies to all consumers of this
data, including the ZWL app.
