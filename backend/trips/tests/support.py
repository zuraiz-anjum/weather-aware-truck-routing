"""Shared pieces for the test modules."""

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from .test_polyline import encode

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@override_settings(CACHES=LOCAL_CACHE)
class CacheTestCase(SimpleTestCase):
    def setUp(self):
        cache.clear()


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}")


def osrm_step(points, distance_m, duration_s, name="", ref=""):
    return {"geometry": encode(points), "distance": distance_m, "duration": duration_s, "name": name, "ref": ref}


def osrm_route(legs, distance_m, duration_s):
    return {"distance": distance_m, "duration": duration_s, "legs": [{"steps": steps} for steps in legs]}


def fake_route(points, duration, detour=False, roads=None, minor=()):
    """A Route driven at a steady speed along the given points."""
    from trips.geometry import Polyline
    from trips.osrm import Route

    line = Polyline(points)
    return Route(line, [m * duration / line.length for m in line.miles], line.length, duration, roads or {}, list(minor), detour)


def fake_forecast(wind_by_lat=lambda lat: 10.0, rain=0.0, snow=0.0):
    """A stand-in for weather.forecast: steady conditions set by latitude, every hour of the window."""
    from trips.weather import Hourly

    def forecast(points, start, end):
        first = int(start.timestamp() // 3600 * 3600)
        last = int(end.timestamp() // 3600 * 3600) + 3600
        times = list(range(first, last + 1, 3600))
        return [Hourly(times, [wind_by_lat(lat)] * len(times), [rain] * len(times), [snow] * len(times)) for lat, _ in points]

    return forecast
