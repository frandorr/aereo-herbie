"""Approximate static domain footprints (WGS84) for common Herbie models.

Model GRIB files carry their native projection but no cheap way to read the
extent without downloading data. These approximate bounding polygons let the
search provider populate asset ``geometry`` and clip the extraction AOI to
the model domain, similar to how ``aereo-search-aws-goes`` uses predefined
GOES domain polygons.

The polygons are intentionally approximate (bounding boxes of the native
grids); they are used for spatial pre-filtering only, not for exact masking.
"""

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

GLOBAL_DOMAIN = box(-180.0, -90.0, 180.0, 90.0)

#: Approximate HRRR CONUS domain (Lambert conformal, 3 km).
HRRR_CONUS_DOMAIN = box(-134.1, 21.1, -60.9, 52.6)

#: Approximate HRRR Alaska domain.
HRRR_ALASKA_DOMAIN = box(-180.0, 41.5, -122.0, 75.0)

#: Approximate North America domains used by NAM/RAP.
NORTH_AMERICA_DOMAIN = box(-170.0, 10.0, -40.0, 75.0)

#: Map of Herbie model name -> approximate WGS84 domain polygon.
MODEL_DOMAINS: dict[str, BaseGeometry] = {
    "hrrr": HRRR_CONUS_DOMAIN,
    "hrrrak": HRRR_ALASKA_DOMAIN,
    "urma": HRRR_CONUS_DOMAIN,
    "rtma": HRRR_CONUS_DOMAIN,
    "nam": NORTH_AMERICA_DOMAIN,
    "rap": NORTH_AMERICA_DOMAIN,
    "gfs": GLOBAL_DOMAIN,
    "gfs_wave": GLOBAL_DOMAIN,
    "gefs": GLOBAL_DOMAIN,
    "ecmwf": GLOBAL_DOMAIN,
    "aifs": GLOBAL_DOMAIN,
    "aigfs": GLOBAL_DOMAIN,
    "ifs": GLOBAL_DOMAIN,
}

__all__ = [
    "GLOBAL_DOMAIN",
    "HRRR_CONUS_DOMAIN",
    "HRRR_ALASKA_DOMAIN",
    "NORTH_AMERICA_DOMAIN",
    "MODEL_DOMAINS",
]
