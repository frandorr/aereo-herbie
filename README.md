# 🚀 aereo-herbie

The `aereo-herbie` plugin provides **search** and **read** capabilities for the `aereo` ecosystem, built on [Herbie](https://herbie.readthedocs.io/) GRIB2 index (inventory) files for NWP model data (HRRR, GFS, ECMWF, GEFS, ...).

Powered by the [Polylith architecture](https://davidvujic.github.io/python-polylith-docs/setup/) and `uv`.

---

## Components

| Entry point | Type | Description |
|-------------|------|-------------|
| `search_herbie` | SearchProvider | Discover model-run inventories → `GeoDataFrame[AssetSchema]` |
| `read_herbie` | Reader | Read search-result assets into an `xr.Dataset` (byte-range subsets) |

## `search_herbie`

For each requested model run, the search provider:

1. Initializes `Herbie(date, model=..., product=..., fxx=...)`.
2. Downloads only the small `.idx` inventory file (no GRIB data).
3. Parses it with `H.inventory(search_regex)` — exactly like the
   [Herbie inventory tutorial](https://herbie.readthedocs.io/en/latest/user_guide/tutorial/inventory.html).
4. Maps every GRIB message (variable + level + byte range) to a row of an
   aereo `GeoDataFrame[AssetSchema]`.

Each returned asset row includes the GRIB `href`, the `idx_url`, the
`start_byte`/`end_byte`/`range` columns, `variable`, `level`,
`forecast_time`, and `search_this`, so the reader can fetch individual
variables with HTTP range requests. The `geometry` column carries the model's
approximate domain polygon (`MODEL_DOMAINS`, exported from
`aereo.search_herbie`), so search results can be gridded by
`build_grouped_tasks` even without a job `target_aoi`.

### Collection naming

Collection names map directly to Herbie model names (`hrrr`, `gfs`, `ecmwf`,
`gefs`, ...). Per-collection asset keys are regexes matched against Herbie's
`search_this` column:

```python
collections = {
    "hrrr": [":TMP:2 m above ground", ":(U|V)GRD:10 m above ground"],
}
```

A sequence of model names (e.g. `["hrrr", "gfs"]`) returns the full
inventory of each run.

### Usage

```python
from datetime import datetime, timezone
from aereo.search_herbie import search_herbie

gdf = search_herbie(
    collections={"hrrr": [":TMP:2 m above ground"]},
    intersects=None,
    start_datetime=datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
    end_datetime=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
    product="sfc",            # Herbie product (None = model default)
    fxx=0,                    # forecast lead time in hours
    run_interval_hours=6,     # spacing between model runs to query
)
```

> **Note:** Model inventories have no per-granule footprints, so every asset
> gets the model's approximate static domain polygon as `geometry` (see
> `components/aereo/search_herbie/domains.py`). When `intersects` is given,
> models whose domain does not intersect the AOI are skipped entirely. This
> lets `build_grouped_tasks` clip the job's `target_aoi` to the model domain
> when gridding.

### Search parameters

| Param | Required | Default | Description |
|-------|----------|---------|-------------|
| `collections` | yes | — | Herbie models, optionally with inventory regexes per model |
| `start_datetime` / `end_datetime` | yes | — | Model-run temporal window |
| `intersects` | no | `None` | AOI; skips models whose domain does not intersect it |
| `product` | no | `None` | Herbie product (e.g. `"sfc"` for HRRR) |
| `fxx` | no | `0` | Forecast lead time in hours; int or list of ints (e.g. `[6, 12, 24]`) to cover several forecast horizons per run in one search |
| `run_interval_hours` | no | `24` | Spacing between queried model runs |
| `search_regex` | no | `None` | Extra regex applied to `search_this` |
| `priority` | no | `None` | Source priority forwarded to Herbie (e.g. `["aws", "nomads"]`) |
| `herbie_kwargs` | no | `None` | Extra kwargs forwarded to `Herbie()` |

## `read_herbie`

A `Reader` callable for `ExtractionJob(read=read_herbie, ...)`. It consumes
assets produced by `search_herbie`:

1. Groups task assets by model run (`collection`/`model_run`/`product`/`fxx`/`href`).
2. Re-initializes `Herbie` per group and calls `H.xarray(search)` with an
   exact-match regex built from the assets' `search_this` values — Herbie
   downloads only those GRIB messages using HTTP byte ranges.
3. Concatenates multiple runs along `time` and optionally crops to
   `task.bbox` (WGS84) using the dataset's latitude/longitude coordinates
   (works with 1D regular grids and 2D curvilinear grids like HRRR).

### Reader parameters

| Param | Default | Description |
|-------|---------|-------------|
| `crop_to_bbox` | `True` | Crop the dataset to `task.bbox` |
| `remove_grib` | `True` | Delete subsetted GRIB files after loading |
| `herbie_kwargs` | `None` | Extra kwargs forwarded to `Herbie()` |
| `xarray_kwargs` | `None` | Extra kwargs forwarded to `H.xarray()` |

## Development

```bash
uv sync
uv pip install -e projects/aereo-herbie --no-deps --python .venv/bin/python
uv run pytest
```

See `examples/basic_search.py` for a runnable example.
