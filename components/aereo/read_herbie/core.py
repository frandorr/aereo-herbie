"""Aereo reader plugin for Herbie GRIB2 data.

Reads assets produced by :func:`aereo.search_herbie.core.search_herbie` into a
single ``xarray.Dataset``. Assets are grouped by model run
(``collection``/``model_run``/``product``/``fxx``/``href``); for each group a
``Herbie`` object is re-initialized and the variables are fetched via
``H.xarray(search)`` using exact ``search_this`` expressions carried by the
assets, so only the requested GRIB messages are downloaded (HTTP byte-range
subset when the index file is available).

When the task carries multiple model runs, the per-run datasets are
concatenated along the ``time`` dimension.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np
import pandas as pd
import xarray as xr
from herbie import Herbie
from pandera.typing.geopandas import GeoDataFrame
from structlog import get_logger

if TYPE_CHECKING:
    from aereo.interfaces import ExtractionTask
    from aereo.schemas import AssetSchema

logger = get_logger()

_GROUP_COLUMNS = ["collection", "model_run", "product", "fxx", "href"]


def _group_assets(
    assets: GeoDataFrame[AssetSchema],
) -> Iterable[tuple[dict[str, Any], GeoDataFrame[AssetSchema]]]:
    """Yield ``(group_key, group)`` pairs grouped by model run and file."""
    keys = [c for c in _GROUP_COLUMNS if c in assets.columns]
    if not keys:
        yield {}, assets
        return
    for key_values, group in assets.groupby(keys, dropna=False):
        if len(keys) == 1:
            key_values = (key_values,)
        yield dict(zip(keys, key_values)), group


def _exact_search_regex(search_terms: Iterable[str]) -> str | None:
    """Build an exact-match regex from literal ``search_this`` expressions."""
    terms = [t for t in search_terms if isinstance(t, str) and t]
    if not terms:
        return None
    return "|".join(re.escape(t) for t in dict.fromkeys(terms))


def _as_single_dataset(result: Any) -> xr.Dataset:
    """Normalize an ``H.xarray`` return value to a single ``xr.Dataset``.

    Herbie groups GRIB messages by compatible grids and returns a *list* of
    datasets (e.g. 2 m temperature and 10 m winds land in separate datasets
    because of their different level types). Merge them so downstream steps
    always see one dataset.
    """
    if isinstance(result, xr.Dataset):
        return result
    datasets = [ds for ds in result if isinstance(ds, xr.Dataset)]
    if not datasets:
        raise ValueError("H.xarray returned no datasets.")
    merged = datasets[0]
    for ds in datasets[1:]:
        merged = merged.merge(ds, compat="override", join="outer")
    return merged


def _read_group(
    key: dict[str, Any],
    group: GeoDataFrame[AssetSchema],
    remove_grib: bool,
    herbie_kwargs: dict[str, Any],
    xarray_kwargs: dict[str, Any],
) -> xr.Dataset:
    """Read one model-run group into an ``xr.Dataset`` via Herbie."""
    model = str(key.get("collection", group["collection"].iloc[0]))
    run = key.get("model_run", group["start_time"].iloc[0])
    product = key.get("product")
    fxx = key.get("fxx", 0)

    search = (
        _exact_search_regex(group["search_this"]) if "search_this" in group else None
    )

    H = Herbie(
        pd.Timestamp(run).to_pydatetime().replace(tzinfo=None),
        model=model,
        product=product if pd.notna(product) else None,
        fxx=int(fxx) if pd.notna(fxx) else 0,
        **herbie_kwargs,
    )
    logger.info(
        "Reading GRIB subset",
        model=model,
        run=str(run),
        n_messages=len(group),
    )
    return _as_single_dataset(H.xarray(search, remove_grib=remove_grib, **xarray_kwargs))


def _lonlat_names(ds: xr.Dataset) -> tuple[str, str] | None:
    """Return ``(lat_name, lon_name)`` coordinate names, if present."""
    for lat_name, lon_name in (("latitude", "longitude"), ("lat", "lon")):
        if lat_name in ds.coords and lon_name in ds.coords:
            return lat_name, lon_name
    return None


def _half_resolution(values: np.ndarray, axis: int = 0) -> float:
    """Half the median grid spacing of *values* along *axis* (pixel half-extent)."""
    if values.shape[axis] < 2:
        return 0.0
    diffs = np.abs(np.diff(values.astype(float), axis=axis))
    if diffs.size == 0 or not np.isfinite(diffs).any():
        return 0.0
    return float(np.nanmedian(diffs)) / 2.0


def _crop_to_bbox(ds: xr.Dataset, bbox: tuple[float, float, float, float]) -> xr.Dataset:
    """Crop a dataset to a WGS84 ``(xmin, ymin, xmax, ymax)`` bounding box.

    Works with both 1D (regular grids) and 2D (curvilinear grids such as
    HRRR's Lambert conformal) latitude/longitude coordinates. Longitudes are
    normalized to the -180..180 convention before masking. The antimeridian
    is not handled specially.

    Pixels are kept when their centers fall within the bbox expanded by half
    a grid cell (pixel-extent semantics: pixels *intersecting* the bbox are
    retained). This also avoids degenerate single-cell outputs when cropping
    a coarse grid to a small AOI.
    """
    names = _lonlat_names(ds)
    if names is None:
        logger.warning("No lat/lon coordinates found; skipping bbox crop")
        return ds
    lat_name, lon_name = names
    xmin, ymin, xmax, ymax = bbox

    lat_coord = ds[lat_name]
    lon_coord = ds[lon_name]
    if lat_coord.ndim == 1 and lon_coord.ndim == 1:
        pad_y = _half_resolution(lat_coord.values)
        pad_x = _half_resolution(lon_coord.values)
    else:
        pad_y = _half_resolution(lat_coord.values, axis=0)
        pad_x = _half_resolution(lon_coord.values, axis=1)

    lon = (lon_coord + 180) % 360 - 180
    mask = (
        (lat_coord >= ymin - pad_y)
        & (lat_coord <= ymax + pad_y)
        & (lon >= xmin - pad_x)
        & (lon <= xmax + pad_x)
    )
    return ds.where(mask.compute(), drop=True)


def _combine_datasets(datasets: list[xr.Dataset]) -> xr.Dataset:
    """Combine per-run datasets, concatenating along ``time`` when needed."""
    if len(datasets) == 1:
        return datasets[0]
    try:
        return xr.concat(
            [ds.expand_dims("time") if "time" not in ds.dims else ds for ds in datasets],
            dim="time",
        )
    except Exception as e:
        logger.warning(
            "Could not concatenate runs along time; falling back to merge",
            error=str(e),
        )
        return xr.merge(datasets, compat="override")


def read_herbie(
    task: ExtractionTask,
    crop_to_bbox: bool = True,
    remove_grib: bool = True,
    herbie_kwargs: dict[str, Any] | None = None,
    xarray_kwargs: dict[str, Any] | None = None,
) -> xr.Dataset:
    """Read Herbie search-result assets for *task* into an ``xr.Dataset``.

    Args:
        task: Extraction task whose assets come from ``search_herbie``
            (columns ``collection``, ``model_run``, ``product``, ``fxx``,
            ``search_this``, ``href``). Assets from other sources fall back
            to ``start_time`` as the model run and a full-file read.
        crop_to_bbox: Crop the dataset to ``task.bbox`` (WGS84) using the
            latitude/longitude coordinates.
        remove_grib: Delete the subsetted GRIB file after loading into
            memory (Herbie never removes pre-existing files).
        herbie_kwargs: Extra keyword arguments forwarded to ``Herbie()``.
        xarray_kwargs: Extra keyword arguments forwarded to ``H.xarray()``
            (e.g. ``backend_kwargs`` for cfgrib).

    Returns:
        An ``xr.Dataset`` with the requested variables, optionally cropped to
        the task bounding box.

    Raises:
        ValueError: If the task has no assets or no group could be read.
    """
    if task.assets is None or len(task.assets) == 0:
        raise ValueError("read_herbie requires a task with non-empty assets.")

    datasets: list[xr.Dataset] = []
    for key, group in _group_assets(task.assets):
        try:
            datasets.append(
                _read_group(
                    key,
                    group,
                    remove_grib=remove_grib,
                    herbie_kwargs=herbie_kwargs or {},
                    xarray_kwargs=xarray_kwargs or {},
                )
            )
        except Exception as e:
            logger.error("Failed to read GRIB group", key=key, error=str(e))

    if not datasets:
        raise ValueError("read_herbie could not read any asset group.")

    ds = _combine_datasets(datasets)

    bbox = task.bbox
    if crop_to_bbox and bbox is not None:
        ds = _crop_to_bbox(ds, bbox)
        if ds.sizes and all(size == 0 for size in ds.sizes.values()):
            logger.warning("BBox crop produced an empty dataset", bbox=bbox)

    return ds
