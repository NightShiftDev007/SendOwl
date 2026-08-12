"""Deterministic ISO country coordinates for the media overview globe."""

from functools import lru_cache

import pycountry
from countryinfo import CountryInfo


class CountryGeometryError(RuntimeError):
    """Raised when an imported ISO country cannot be positioned on the globe."""


@lru_cache(maxsize=1)
def _country_centroids() -> dict[str, tuple[float, float]]:
    """Build an ISO alpha-2 coordinate map from the packaged country registry."""
    centroids: dict[str, tuple[float, float]] = {}
    for country_data in CountryInfo().all().values():
        iso = country_data.get("ISO")
        coordinates = country_data.get("latlng")
        if not isinstance(iso, dict) or not isinstance(coordinates, list):
            continue
        alpha_2 = iso.get("alpha2")
        if not isinstance(alpha_2, str) or len(coordinates) != 2:
            continue
        latitude, longitude = coordinates
        if isinstance(latitude, int | float) and isinstance(longitude, int | float):
            centroids[alpha_2] = (float(latitude), float(longitude))
    centroids["PS"] = (31.9, 35.2)
    centroids["ME"] = (42.7, 19.3)
    centroids["MM"] = (21.9, 95.9)
    return centroids


def country_centroid(country_code: str) -> tuple[float, float]:
    """Return a deterministic centroid or fail instead of dropping real country data."""
    normalized_country_code = country_code.upper()
    if pycountry.countries.get(alpha_2=normalized_country_code) is None:
        raise CountryGeometryError(
            f"Imported country code {country_code!r} is not an ISO 3166-1 alpha-2 code"
        )
    centroid = _country_centroids().get(normalized_country_code)
    if centroid is None:
        raise CountryGeometryError(
            f"No country geometry is available for imported country code {country_code!r}"
        )
    return centroid
