from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import box

from aereo.interfaces import ExtractionTask
from aereo.read_herbie.core import (
    _combine_datasets,
    _crop_to_bbox,
    _exact_search_regex,
    read_herbie,
)


def _assets_df(runs: list[pd.Timestamp] | None = None) -> gpd.GeoDataFrame:
    runs = runs or [pd.Timestamp("2024-01-01", tz="UTC")]
    rows = []
    for run in runs:
        for i, (var, search_this) in enumerate(
            [
                ("TMP", ":TMP:2 m above ground:anl"),
                ("UGRD", ":UGRD:10 m above ground:anl"),
            ]
        ):
            rows.append(
                {
                    "id": f"hrrr-{run:%Y%m%dT%H}-f00-{i:04d}-{var.lower()}",
                    "collection": "hrrr",
                    "geometry": box(-134.1, 21.1, -60.9, 52.6),
                    "start_time": run,
                    "end_time": run,
                    "href": "https://example.com/hrrr.t00z.wrfsfcf00.grib2",
                    "search_this": search_this,
                    "model_run": run,
                    "product": "sfc",
                    "fxx": 0,
                }
            )
    return gpd.GeoDataFrame(rows, geometry="geometry")


def _fake_hrrr_dataset() -> xr.Dataset:
    """Small HRRR-like dataset: 2D lat/lon, longitudes in 0..360."""
    y = np.arange(10)
    x = np.arange(10)
    lat2d, lon2d = np.meshgrid(
        np.linspace(39.0, 41.0, 10), np.linspace(254.0, 256.0, 10), indexing="ij"
    )
    return xr.Dataset(
        {"t2m": (("y", "x"), np.ones((10, 10)))},
        coords={
            "y": y,
            "x": x,
            "latitude": (("y", "x"), lat2d),
            "longitude": (("y", "x"), lon2d),
            "time": pd.Timestamp("2024-01-01"),
        },
    )


def _task(assets: gpd.GeoDataFrame, aoi=None) -> ExtractionTask:
    return ExtractionTask(id="t1", assets=assets, job=MagicMock(), aoi=aoi)


def test_exact_search_regex():
    assert _exact_search_regex([]) is None
    assert _exact_search_regex([":TMP:2 m above ground:anl"]) == ":TMP:2\\ m\\ above\\ ground:anl"
    regex = _exact_search_regex([":TMP:sfc", ":TMP:sfc", ":UGRD:sfc"])
    assert regex == ":TMP:sfc|:UGRD:sfc"


def test_crop_to_bbox_2d_lonlat():
    ds = _fake_hrrr_dataset()
    cropped = _crop_to_bbox(ds, (-105.5, 39.5, -104.5, 40.5))
    assert cropped.sizes["y"] < ds.sizes["y"]
    assert cropped.sizes["x"] < ds.sizes["x"]
    lon = (cropped["longitude"] + 180) % 360 - 180
    # Pixels intersecting the bbox are kept: centers may lie up to half a
    # grid cell outside the bbox.
    assert float(lon.min()) >= -105.5 - 0.12
    assert float(lon.max()) <= -104.5 + 0.12


def test_crop_to_bbox_1d_coarse_grid_pads_half_cell():
    """A small AOI on a coarse 1D grid must not collapse to a single row."""
    lats = np.arange(-40.0, -30.0, 0.25)
    lons = np.arange(295.0, 305.0, 0.25)
    ds = xr.Dataset(
        {"t2m": (("latitude", "longitude"), np.ones((len(lats), len(lons))))},
        coords={"latitude": lats, "longitude": lons},
    )
    # Strictly inside the bbox there is exactly one lat center (-36.25).
    cropped = _crop_to_bbox(ds, (-61.47, -36.47, -60.72, -36.11))
    assert cropped.sizes["latitude"] >= 3
    assert cropped.sizes["longitude"] >= 3


def test_combine_datasets_concatenates_runs():
    ds1 = _fake_hrrr_dataset()
    ds2 = _fake_hrrr_dataset().assign_coords(time=pd.Timestamp("2024-01-02"))
    combined = _combine_datasets([ds1, ds2])
    assert combined.sizes["time"] == 2


@patch("aereo.read_herbie.core.Herbie")
def test_read_herbie_single_run(mock_herbie_cls):
    mock_herbie_cls.return_value.xarray.return_value = _fake_hrrr_dataset()
    aoi = box(-105.5, 39.5, -104.5, 40.5)
    task = _task(_assets_df(), aoi=aoi)

    ds = read_herbie(task)

    # Herbie initialized with tz-naive run datetime, model and product
    (run_arg,), kwargs = mock_herbie_cls.call_args
    assert run_arg == datetime(2024, 1, 1)
    assert kwargs["model"] == "hrrr"
    assert kwargs["product"] == "sfc"
    assert kwargs["fxx"] == 0

    # xarray called with exact escaped search_this regex
    search_arg = mock_herbie_cls.return_value.xarray.call_args[0][0]
    assert "TMP" in search_arg and "UGRD" in search_arg

    # Cropped to the AOI bounds
    assert ds.sizes["y"] < 10


@patch("aereo.read_herbie.core.Herbie")
def test_read_herbie_multiple_runs_concat(mock_herbie_cls):
    runs = [pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2024-01-02", tz="UTC")]

    def _xarray_side_effect(*args, **kwargs):
        return _fake_hrrr_dataset()

    mock_herbie_cls.return_value.xarray.side_effect = _xarray_side_effect
    task = _task(_assets_df(runs))

    ds = read_herbie(task, crop_to_bbox=False)

    assert mock_herbie_cls.call_count == 2
    assert ds.sizes["time"] == 2


@patch("aereo.read_herbie.core.Herbie")
def test_read_herbie_merges_xarray_list(mock_herbie_cls):
    """Herbie returns a list of datasets (one per compatible grid); the
    reader must merge them instead of passing the list downstream."""
    t2m = _fake_hrrr_dataset()
    winds = xr.Dataset(
        {"u10": (("y", "x"), np.ones((10, 10))), "v10": (("y", "x"), np.ones((10, 10)))},
        coords={
            "y": np.arange(10),
            "x": np.arange(10),
            "latitude": t2m["latitude"],
            "longitude": t2m["longitude"],
            "time": pd.Timestamp("2024-01-01"),
        },
    )
    mock_herbie_cls.return_value.xarray.return_value = [t2m, winds]
    task = _task(_assets_df())

    ds = read_herbie(task, crop_to_bbox=False)

    assert isinstance(ds, xr.Dataset)
    assert set(ds.data_vars) == {"t2m", "u10", "v10"}


def test_read_herbie_empty_assets_raises():
    # ExtractionTask itself enforces non-empty assets at construction time.
    assets = _assets_df().iloc[0:0]
    with pytest.raises(ValueError, match="assets cannot be empty"):
        _task(assets)


@patch("aereo.read_herbie.core.Herbie")
def test_read_herbie_all_groups_fail_raises(mock_herbie_cls):
    mock_herbie_cls.side_effect = RuntimeError("boom")
    with pytest.raises(ValueError, match="could not read any asset group"):
        read_herbie(_task(_assets_df()))
