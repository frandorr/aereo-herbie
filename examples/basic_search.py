"""
Basic search example for aereo-herbie.

Builds an aereo Assets GeoDataFrame from the HRRR surface inventory
(GRIB2 index file) for one model run: 2 m temperature and 10 m winds.
No GRIB data is downloaded — only the small .idx inventory file is read,
and each row carries the byte range needed to fetch the variable later.
"""

from datetime import datetime, timezone

from aereo.search_herbie import search_herbie


def main():
    results = search_herbie(
        collections={
            "hrrr": [":TMP:2 m above ground", ":(U|V)GRD:10 m above ground"],
        },
        intersects=None,
        start_datetime=datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2024, 1, 1, 0, tzinfo=timezone.utc),
        product="sfc",
        fxx=0,
    )

    print(f"Found {len(results)} assets")
    if len(results) > 0:
        print(results[["id", "variable", "level", "range", "href"]].to_string())


if __name__ == "__main__":
    main()
