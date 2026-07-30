from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import geopandas as gpd
import pandas as pd

from shapely.geometry import box

from aereo.search_herbie.core import _combine_regexes, _run_datetimes, search_herbie
from aereo.search_herbie.domains import HRRR_CONUS_DOMAIN, MODEL_DOMAINS


def _inventory_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "grib_message": 1,
                "start_byte": 0,
                "end_byte": 202809,
                "range": "0-202809",
                "reference_time": pd.Timestamp("2024-01-01", tz="UTC"),
                "valid_time": pd.Timestamp("2024-01-01", tz="UTC"),
                "variable": "REFC",
                "level": "entire atmosphere",
                "forecast_time": "anl",
                "search_this": ":REFC:entire atmosphere:anl",
            },
            {
                "grib_message": 2,
                "start_byte": 202810,
                "end_byte": 246792,
                "range": "202810-246792",
                "reference_time": pd.Timestamp("2024-01-01", tz="UTC"),
                "valid_time": pd.Timestamp("2024-01-01", tz="UTC"),
                "variable": "TMP",
                "level": "2 m above ground",
                "forecast_time": "anl",
                "search_this": ":TMP:2 m above ground:anl",
            },
        ]
    )


def _mock_herbie(inventory: pd.DataFrame) -> MagicMock:
    H = MagicMock()
    H.grib = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com/hrrr.20240101/conus/hrrr.t00z.wrfsfcf00.grib2"
    H.idx = H.grib + ".idx"
    H.product = "sfc"
    H.inventory.return_value = inventory
    return H


def test_combine_regexes():
    assert _combine_regexes(None) is None
    assert _combine_regexes([]) is None
    assert _combine_regexes(["*"]) is None
    assert _combine_regexes([":TMP:2 m above ground"]) == ":TMP:2 m above ground"
    combined = _combine_regexes([":TMP:2 m", ":UGRD:10 m"])
    assert combined == "(?::TMP:2 m)|(?::UGRD:10 m)"


def test_run_datetimes():
    runs = _run_datetimes(
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 1, 3, tzinfo=timezone.utc),
        24,
    )
    assert len(runs) == 3
    assert runs[0] == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_search_herbie_empty_collections():
    gdf = search_herbie(
        collections=None,
        intersects=None,
        start_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert gdf.empty
    assert "id" in gdf.columns
    assert "collection" in gdf.columns
    assert "href" in gdf.columns


@patch("aereo.search_herbie.core.Herbie")
def test_search_herbie_results(mock_herbie_cls):
    mock_herbie_cls.return_value = _mock_herbie(_inventory_df())

    gdf = search_herbie(
        collections=["hrrr"],
        intersects=None,
        start_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert not gdf.empty
    assert len(gdf) == 2
    row = gdf.iloc[0]
    assert row["collection"] == "hrrr"
    assert row["href"].endswith(".grib2")
    assert row["idx_url"].endswith(".idx")
    assert row["variable"] == "REFC"
    assert row["start_byte"] == 0
    assert row["grib_message"] == 1
    assert row["start_time"] == pd.Timestamp("2024-01-01")
    assert row["end_time"] == pd.Timestamp("2024-01-01")
    # ids must be unique per GRIB message
    assert gdf["id"].is_unique


@patch("aereo.search_herbie.core.Herbie")
def test_search_herbie_passes_regex_to_inventory(mock_herbie_cls):
    mock_herbie_cls.return_value = _mock_herbie(_inventory_df())

    search_herbie(
        collections={"hrrr": [":TMP:2 m above ground"]},
        intersects=None,
        start_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    mock_herbie_cls.return_value.inventory.assert_called_with(":TMP:2 m above ground")


@patch("aereo.search_herbie.core.Herbie")
def test_search_herbie_herbie_failure_returns_empty(mock_herbie_cls):
    mock_herbie_cls.side_effect = RuntimeError("no data")

    gdf = search_herbie(
        collections=["hrrr"],
        intersects=None,
        start_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert isinstance(gdf, gpd.GeoDataFrame)
    assert gdf.empty


@patch("aereo.search_herbie.core.Herbie")
def test_search_herbie_populates_domain_geometry(mock_herbie_cls):
    mock_herbie_cls.return_value = _mock_herbie(_inventory_df())

    gdf = search_herbie(
        collections=["hrrr"],
        intersects=None,
        start_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert not gdf.empty
    assert gdf.geometry.notna().all()
    assert gdf.geometry.iloc[0].equals(HRRR_CONUS_DOMAIN)


@patch("aereo.search_herbie.core.Herbie")
def test_search_herbie_skips_model_outside_aoi(mock_herbie_cls):
    mock_herbie_cls.return_value = _mock_herbie(_inventory_df())
    europe = box(-10, 35, 40, 70)

    gdf = search_herbie(
        collections=["hrrr"],
        intersects=europe,
        start_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert gdf.empty
    mock_herbie_cls.assert_not_called()


@patch("aereo.search_herbie.core.Herbie")
def test_search_herbie_unknown_model_has_null_geometry(mock_herbie_cls):
    mock_herbie_cls.return_value = _mock_herbie(_inventory_df())
    assert "mymodel" not in MODEL_DOMAINS

    gdf = search_herbie(
        collections=["mymodel"],
        intersects=None,
        start_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )

    assert not gdf.empty
    assert gdf.geometry.isna().all()


def test_supported_collections_attribute():
    assert search_herbie.supported_collections == ["*"]
