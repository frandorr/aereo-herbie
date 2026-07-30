"""Aereo search provider built on Herbie GRIB2 index (inventory) files.

Herbie parses the plain-text ``.idx`` companion files of NWP GRIB2 products
into a Pandas DataFrame it calls the *inventory*. This plugin turns each
inventory row (a GRIB message with variable, level, forecast time and byte
range) into an aereo asset row validated against
:class:`aereo.schemas.AssetSchema`.

Collection names map directly to Herbie model names (e.g. ``"hrrr"``,
``"gfs"``, ``"ecmwf"``, ``"gefs"``). Per-collection asset keys are regular
expressions matched against Herbie's ``search_this`` column, exactly like
``H.inventory(search_this)``::

    {"hrrr": [":TMP:2 m above ground", ":(U|V)GRD:10 m above ground"]}

No GRIB data is downloaded by this plugin: it only fetches the small index
files and reports URLs plus byte ranges, so a downstream reader can perform
HTTP range requests to extract individual variables.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

import geopandas as gpd
import pandas as pd
from aereo.interfaces import build_collection_asset_filters, empty_asset_result
from aereo.interfaces.utils import normalize_geometry_input
from herbie import FastHerbie
from aereo.schemas import AssetSchema
from pandera.typing.geopandas import GeoDataFrame
from pydantic import ConfigDict, validate_call
from shapely.geometry.base import BaseGeometry
from structlog import get_logger

from .domains import MODEL_DOMAINS

logger = get_logger()


def _combine_regexes(regexes: Sequence[str] | None) -> str | None:
    """Combine multiple inventory regexes into a single alternation."""
    if not regexes:
        return None
    cleaned = [r for r in regexes if r and r != "*"]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]
    return "|".join(f"(?:{r})" for r in cleaned)


def _run_datetimes(
    start: datetime, end: datetime, interval_hours: int
) -> list[datetime]:
    """Generate model run datetimes from *start* to *end* (inclusive)."""
    runs = []
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        runs.append(current)
        current += timedelta(hours=interval_hours)
    return runs


def _fetch_inventories(
    herbies: list[Any], search: str | None, max_threads: int
) -> list[tuple[Any, pd.DataFrame]]:
    """Fetch inventories (``.idx`` download + parse) concurrently.

    Returns ``(Herbie, inventory)`` pairs in input order; runs whose
    inventory fails or is empty are dropped with a warning. Note that
    ``FastHerbie.inventory()`` itself is sequential, hence this helper.
    """

    def _inventory(H: Any) -> tuple[Any, pd.DataFrame] | None:
        try:
            df = H.inventory(search)
        except Exception as e:
            logger.warning(
                "Inventory fetch failed",
                model=str(getattr(H, "model", "?")),
                run=str(getattr(H, "date", "?")),
                error=str(e),
            )
            return None
        if df is None or len(df) == 0:
            return None
        return H, df

    if len(herbies) < 2:
        results = [_inventory(H) for H in herbies]
    else:
        with ThreadPoolExecutor(max_workers=min(len(herbies), max_threads)) as exe:
            results = list(exe.map(_inventory, herbies))
    return [r for r in results if r is not None]


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def search_herbie(
    collections: Mapping[str, Sequence[str]] | Sequence[str] | None,
    intersects: BaseGeometry | dict[str, Any] | str | Path | None,
    start_datetime: datetime | None,
    end_datetime: datetime | None,
    product: str | None = None,
    fxx: int | Sequence[int] = 0,
    run_interval_hours: int = 24,
    search_regex: str | None = None,
    priority: Sequence[str] | None = None,
    herbie_kwargs: dict[str, Any] | None = None,
    max_threads: int = 50,
) -> GeoDataFrame[AssetSchema]:
    """Search NWP model GRIB2 inventories via Herbie and return assets.

    Args:
        collections: Mapping of Herbie model name -> inventory regexes
            (matched against the ``search_this`` column), or a sequence of
            model names for full inventories.
        intersects: AOI geometry. When provided, models whose approximate
            domain does not intersect the AOI are skipped. Asset footprints
            are set to the model's approximate domain (see
            :mod:`aereo.search_herbie.domains`) or left null for unknown
            models.
        start_datetime: Start of the model-run temporal window.
        end_datetime: End of the model-run temporal window. A midnight value
            (e.g. a date-only string like ``"2025-11-01"``) is inclusive of
            the whole day, mirroring STAC date semantics.
        product: Herbie product (e.g. ``"sfc"`` for HRRR). ``None`` uses the
            model's default product.
        fxx: Forecast lead time(s) in hours. A single int (e.g. ``6``) or a
            list of lead times (e.g. ``[6, 12, 24]``) to search several
            forecast horizons per run in one call. Each returned asset
            carries its own lead time in the ``fxx`` column.
        run_interval_hours: Spacing between model runs to query.
        search_regex: Extra regex applied to ``search_this`` on top of the
            per-collection asset filters.
        priority: Optional source priority list forwarded to Herbie
            (e.g. ``["aws", "nomads"]``).
        herbie_kwargs: Extra keyword arguments forwarded to ``Herbie()``.
        max_threads: Maximum threads for creating the per-run Herbie objects
            and fetching their inventories.

    Returns:
        A GeoDataFrame where each row is a GRIB message (variable/level) of a
        matched model run, with columns defined by
        :class:`aereo.schemas.AssetSchema` plus inventory details
        (``grib_message``, ``start_byte``, ``end_byte``, ``range``,
        ``variable``, ``level``, ``forecast_time``, ``search_this``,
        ``idx_url``).
    """
    model_names, asset_filters = build_collection_asset_filters(collections)
    if not model_names:
        return empty_asset_result()

    if not start_datetime or not end_datetime:
        return empty_asset_result()

    if start_datetime.tzinfo is None:
        start_datetime = start_datetime.replace(tzinfo=timezone.utc)
    if end_datetime.tzinfo is None:
        end_datetime = end_datetime.replace(tzinfo=timezone.utc)

    # A midnight end (e.g. a date-only string like "2025-11-01") means the
    # whole day, mirroring STAC date semantics.
    if end_datetime.time() == time.min:
        end_datetime += timedelta(days=1) - timedelta(microseconds=1)

    runs = _run_datetimes(start_datetime, end_datetime, run_interval_hours)
    fxx_list = sorted({int(f) for f in ([fxx] if isinstance(fxx, int) else fxx)})
    if not fxx_list:
        return empty_asset_result()

    extra_kwargs = dict(herbie_kwargs or {})
    aoi = normalize_geometry_input(intersects) if intersects is not None else None

    rows: list[dict[str, Any]] = []

    for model in model_names:
        domain = MODEL_DOMAINS.get(model)
        if aoi is not None and domain is not None and not aoi.intersects(domain):
            logger.info("Model domain does not intersect AOI; skipping", model=model)
            continue

        model_regex = _combine_regexes(
            sorted(asset_filters[model]) if asset_filters.get(model) else None
        )
        combined_regex = _combine_regexes(
            [r for r in (model_regex, search_regex) if r]
        )

        try:
            # Herbie expects tz-naive datetimes. FastHerbie resolves all
            # per-run files (existence checks) concurrently.
            FH = FastHerbie(
                [r.replace(tzinfo=None) for r in runs],
                model=model,
                product=product,
                fxx=fxx_list,
                priority=priority,
                max_threads=max_threads,
                **extra_kwargs,
            )
        except Exception as e:
            logger.warning(
                "FastHerbie initialization failed",
                model=model,
                error=str(e),
            )
            continue

        valid = [H for H in FH.file_exists if H.idx is not None]
        if len(valid) < len(FH.objects):
            logger.warning(
                "No GRIB/IDX found for some runs",
                model=model,
                n_missing=len(FH.objects) - len(valid),
            )

        for H, inventory in _fetch_inventories(valid, combined_regex, max_threads):
            run = pd.Timestamp(H.date).tz_localize("UTC")
            lead = int(H.fxx)

            inventory = inventory.copy()
            inventory["reference_time"] = pd.to_datetime(
                inventory["reference_time"], errors="coerce", utc=True
            )
            inventory["valid_time"] = pd.to_datetime(
                inventory["valid_time"], errors="coerce", utc=True
            )
            inventory = inventory.dropna(subset=["reference_time", "valid_time"])

            for rec in inventory.to_dict(orient="records"):
                variable = str(rec.get("variable", "unknown"))
                level = str(rec.get("level", ""))
                slug = re.sub(r"[^A-Za-z0-9]+", "-", f"{variable}-{level}").strip("-")
                rows.append(
                    {
                        "id": (
                            f"{model}-{run:%Y%m%dT%H}-f{lead:02d}-"
                            f"{int(rec['grib_message']):04d}-{slug.lower()}"
                        ),
                        "collection": model,
                        "geometry": domain,
                        "start_time": rec["reference_time"],
                        "end_time": rec["valid_time"],
                        "href": H.grib,
                        "idx_url": H.idx,
                        "grib_message": int(rec["grib_message"]),
                        "start_byte": rec.get("start_byte"),
                        "end_byte": rec.get("end_byte"),
                        "range": rec.get("range"),
                        "variable": variable,
                        "level": level,
                        "forecast_time": str(rec.get("forecast_time", "")),
                        "search_this": str(rec.get("search_this", "")),
                        "model_run": run,
                        "fxx": lead,
                        "product": H.product,
                    }
                )

            logger.info(
                "Inventory collected",
                model=model,
                run=run.isoformat(),
                n_messages=len(inventory),
            )

    if not rows:
        return empty_asset_result()

    gdf = gpd.GeoDataFrame(rows, geometry="geometry")
    return cast(GeoDataFrame, AssetSchema.validate(gdf))


search_herbie.supported_collections = ["*"]  # type: ignore[attr-defined]
