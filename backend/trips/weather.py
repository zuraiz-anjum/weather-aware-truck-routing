"""
Hourly forecasts from Open-Meteo for a list of points.

One request carries up to a hundred points and a window of hours; a
corridor's worth goes out as a few requests at once. Values arrive in the
units the risk rules use: wind in miles an hour at the top of the hour, rain
and snow in inches fallen over the hour that ends at the time stamp.
"""

import hashlib
import logging
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.cache import cache

from .geometry import interpolate

log = logging.getLogger(__name__)

VARIABLES = "wind_speed_10m,rain,snowfall"
POINTS_PER_REQUEST = 100
PARALLEL_REQUESTS = 4

# The window asked for starts at midnight of the departure day and runs at
# least three days, so that moving a departure around within the day asks
# nothing new of the service. Forecasts are revised hourly, and a window
# fetched again within this long gets the same answer.
MIN_WINDOW = timedelta(days=3)
CACHE_SECONDS = 30 * 60


class WeatherError(Exception):
    """Open-Meteo could not be reached or answered with something unusable."""


class WeatherBusy(WeatherError):
    """Open-Meteo's free allowance for the minute is spent; a retry will do."""


@dataclass
class Hourly:
    times: list  # unix seconds, one an hour, ascending
    wind: list  # mph
    rain: list  # inches over the hour ending at the time
    snow: list

    def at(self, when):
        """(wind, rain, snow) at a moment: wind read between the hours, rain and snow for the hour it falls in."""
        t = when.timestamp()
        i = min(bisect_left(self.times, t), len(self.times) - 1)
        return interpolate(self.times, self.wind, t), self.rain[i], self.snow[i]


def forecast(points, start, end):
    """One Hourly per point, covering at least the hours from start to end (aware datetimes)."""
    start = start.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = max(start + MIN_WINDOW, end.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    chunks = [points[i : i + POINTS_PER_REQUEST] for i in range(0, len(points), POINTS_PER_REQUEST)]
    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
        answers = list(pool.map(lambda chunk: _fetch(chunk, start, end), chunks))
    return [hourly for answer in answers for hourly in answer]


def _fetch(points, start, end):
    where = hashlib.sha1(",".join("%.4f,%.4f" % p for p in points).encode()).hexdigest()
    key = "forecast:%s:%s:%s" % (start.strftime("%Y%m%d%H"), end.strftime("%Y%m%d%H"), where)
    found = cache.get(key)
    if found is not None:
        return found
    params = {
        "latitude": ",".join("%.4f" % lat for lat, _ in points),
        "longitude": ",".join("%.4f" % lon for _, lon in points),
        "hourly": VARIABLES,
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "timeformat": "unixtime",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    }
    # The forecast starts at midnight UTC today unless earlier days are asked for.
    behind = (datetime.now(timezone.utc).date() - start.date()).days
    if behind > 0:
        params["past_days"] = behind
    try:
        response = _session.get(
            f"{settings.OPEN_METEO_URL}/v1/forecast",
            params=params,
            headers={"User-Agent": settings.USER_AGENT},
            timeout=settings.HTTP_TIMEOUT,
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError("the weather service could not be reached") from exc
    if isinstance(body, dict) and body.get("error"):
        reason = body.get("reason", "no reason given")
        if "limit" in reason.lower():
            raise WeatherBusy("the weather service has had its fill of requests for the moment; try again in a minute")
        raise WeatherError("the weather service refused the request: %s" % reason)
    if isinstance(body, dict):
        body = [body]  # a single point comes back bare
    try:
        hourlies = [_hourly(item["hourly"]) for item in body]
    except (LookupError, TypeError, ValueError) as exc:
        raise WeatherError("the weather service answered with an unexpected shape") from exc
    if len(hourlies) != len(points):
        raise WeatherError("the weather service answered for %d of %d points" % (len(hourlies), len(points)))
    cache.set(key, hourlies, CACHE_SECONDS)
    return hourlies


def _hourly(data):
    times = [int(t) for t in data["time"]]
    if not times:
        raise ValueError("no hours")
    # A null is an hour the model has nothing for; nothing is the safe reading
    # for a rate, and the hours in question are at the far end of the window.
    columns = [[float(v) if v is not None else 0.0 for v in data[name]] for name in VARIABLES.split(",")]
    if any(len(column) != len(times) for column in columns):
        raise ValueError("ragged columns")
    return Hourly(times, *columns)


_session = requests.Session()
