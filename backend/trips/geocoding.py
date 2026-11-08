"""
Place names to coordinates with Photon, komoot's geocoder over OpenStreetMap.

It answers partial words, which is what the suggestion box needs, and
returns the parts of a label separately so that a town comes out as
"Denver, Colorado" and an address with its street and city.
"""

import hashlib
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

# Photon has no country filter, so the search is boxed to the United States
# and its territories and the answers checked by country code.
BOUNDS = "-180,15,-64,72"
CACHE_SECONDS = 24 * 3600


class GeocodingError(Exception):
    """Photon could not be reached or answered with something unusable."""


class PlaceNotFound(Exception):
    """No place in the United States matches the text."""


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float


_session = requests.Session()


def suggest(text, limit=6):
    """Places in the United States matching text, best first."""
    text = " ".join(text.split())
    if len(text) < 2:
        return []
    key = "places:%d:%s" % (limit, hashlib.sha1(text.lower().encode()).hexdigest())
    found = cache.get(key)
    if found is not None:
        return found
    try:
        response = _session.get(
            f"{settings.PHOTON_URL}/api/",
            params={"q": text, "lang": "en", "limit": limit * 3, "bbox": BOUNDS},
            headers={"User-Agent": settings.USER_AGENT},
            timeout=settings.HTTP_TIMEOUT,
        )
        response.raise_for_status()
        features = response.json()["features"]
    except (requests.RequestException, ValueError, LookupError, TypeError) as exc:
        raise GeocodingError("the place search could not be reached") from exc
    places, seen = [], set()
    for feature in features:
        properties = feature.get("properties") or {}
        if properties.get("countrycode") != "US":
            continue
        try:
            lon, lat = feature["geometry"]["coordinates"]
            place = Place(label(properties), float(lat), float(lon))
        except (LookupError, TypeError, ValueError):
            continue
        if place.label and place.label not in seen:
            seen.add(place.label)
            places.append(place)
        if len(places) == limit:
            break
    cache.set(key, places, CACHE_SECONDS)
    return places


def locate(text):
    """The best match for text, for a form submitted without picking a suggestion."""
    places = suggest(text, limit=1)
    if not places:
        raise PlaceNotFound(f"no place in the United States called {text!r}")
    return places[0]


def label(properties):
    name = properties.get("name") or " ".join(filter(None, (properties.get("housenumber"), properties.get("street"))))
    parts = [name]
    for field in ("city", "state"):
        value = properties.get(field)
        if value and value not in parts:
            parts.append(value)
    return ", ".join(filter(None, parts))
