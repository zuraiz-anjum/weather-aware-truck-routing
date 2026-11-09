"""
Hourly forecasts from Open-Meteo for a list of points.

One request carries up to a hundred points and a window of hours; a
corridor's worth goes out as a few requests at once. Values arrive in the
units the risk rules use: wind in miles an hour at the top of the hour, rain
and snow in inches fallen over the hour that ends at the time stamp. Rain
is Open-Meteo's large-scale rain plus its convective showers, since the
rules are about how hard it is raining, not why.

The free allowance is counted by address. When this address has spent its
hour's or day's, the browser can be asked to make the same requests from
its own (see offer) and send the hourly series back, and supplied() reads
them to the same standard as forecast() does Open-Meteo's own answer.
"""

import hashlib
import math
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings
from django.core.cache import cache

from .geometry import interpolate

VARIABLES = ("wind_speed_10m", "rain", "showers", "snowfall")
POINTS_PER_REQUEST = 100
PARALLEL_REQUESTS = 4

# The window asked for runs from midnight of the departure day to a midnight
# at least three days on, so that every departure on the same day, and the
# slider after it, is one fetch. Forecasts are revised hourly; a window
# fetched again within this long gets the same answer.
MIN_WINDOW = timedelta(days=3)
CACHE_SECONDS = 60 * 60

_session = requests.Session()


class WeatherError(Exception):
    """Open-Meteo could not be reached or answered with something unusable."""


class WeatherBusy(WeatherError):
    """Open-Meteo's free allowance is spent for the minute, the hour or the day; a later retry will do.

    `allowance` says which, in Open-Meteo's own word: "minutely", "hourly"
    or "daily"; `retry_after` is the seconds until it comes back.
    """

    def __init__(self, message, retry_after, allowance):
        super().__init__(message)
        self.retry_after = retry_after
        self.allowance = allowance


# Open-Meteo's refusals name the allowance that ran out. The minute's and
# the hour's come back after a minute and an hour, the day's at midnight UTC.
ALLOWANCES = (("daily", "the day", "tomorrow"), ("hourly", "the hour", "in an hour"), ("minutely", "the minute", "in a minute"))


def busy(reason):
    *_, shortest = ALLOWANCES
    word, span, when = next((a for a in ALLOWANCES if a[0] in reason.lower()), shortest)
    return WeatherBusy(f"the weather service's free allowance for {span} is spent; try again {when}", wait(word), word)


def wait(allowance):
    """Seconds until the named allowance comes back, never less than a minute."""
    if allowance == "daily":
        now = datetime.now(timezone.utc)
        return max(60, math.ceil((midnight_after(now) - now).total_seconds()))
    return 3600 if allowance == "hourly" else 60


class BadForecast(Exception):
    """The hourly series a browser sent back are not something a plan can be made from."""


@dataclass
class Hourly:
    times: list  # unix seconds, one an hour, ascending
    wind: list  # mph
    rain: list  # inches over the hour ending at the time
    snow: list

    def at(self, when):
        """(wind, rain, snow) at a moment: wind read between the hours, rain and snow for the hour ahead.

        Totals are stamped with the hour they end at, so for a truck setting
        off at 14:20, or at 14:00 exactly, the hour ahead is the 15:00 stamp.
        """
        t = when.timestamp()
        i = min(bisect_right(self.times, t), len(self.times) - 1)
        return interpolate(self.times, self.wind, t), self.rain[i], self.snow[i]


def horizon():
    """The last hour Open-Meteo will forecast: 23:00 UTC on the sixteenth day, counting today."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=settings.FORECAST_DAYS) - timedelta(hours=1)


def forecast(points, start, end):
    """One Hourly per point, with every hour a truck between start and end (aware datetimes) could need."""
    first, last = window(start, end)
    chunks = [points[i : i + POINTS_PER_REQUEST] for i in range(0, len(points), POINTS_PER_REQUEST)]
    with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
        answers = list(pool.map(lambda chunk: _fetch(chunk, first, last), chunks))
    hourlies = [hourly for answer in answers for hourly in answer]
    # The hours that came back may stop short of the window (see _hourly).
    if not _covers(hourlies, start, end):
        raise WeatherError("the weather service has no forecast for part of this trip")
    return hourlies


def supplied(series, start, end):
    """One Hourly per point from the hourly series a browser fetched when asked to (see offer), judged as forecast() judges Open-Meteo's.

    The series are Open-Meteo's own `hourly` members, passed on as they
    came, so the same reading applies: trailing nulls are hours past the
    model's reach, a null anywhere else refuses the plan. What a browser
    sends is never cached; the next plan fetches for itself.
    """
    try:
        hourlies = [_hourly(data) for data in series]
    except WeatherError as exc:
        raise BadForecast("the supplied forecast has no value for part of this trip") from exc
    except (LookupError, TypeError, ValueError) as exc:
        raise BadForecast("the supplied forecast is not in the shape Open-Meteo sends") from exc
    if not _covers(hourlies, start, end):
        raise BadForecast("the supplied forecast does not cover the whole trip")
    return hourlies


def offer(points, start, end):
    """What a browser needs to fetch the forecast for these points itself: the public address, the query, and the points.

    The address is the public one whatever this server uses, since a
    self-hosted copy or the customer endpoint is the server's own affair;
    for the same reason the query carries no key. The browser adds the
    points a hundred to a request, as _fetch does.
    """
    return {
        "url": f"{settings.OPEN_METEO_PUBLIC_URL}/v1/forecast",
        "params": query(*window(start, end)),
        "points": [[round(lat, 4), round(lon, 4)] for lat, lon in points],
    }


def window(start, end):
    """The hours fetched for a trip between start and end: midnight of the start's day to a midnight at least three days on, inside the horizon."""
    start = start.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = min(max(start + MIN_WINDOW, midnight_after(end.astimezone(timezone.utc) + timedelta(hours=1))), horizon())
    return start, end


def query(start, end):
    """The query of a forecast request for a window, apart from the points and any key; _fetch and offer() both build on it."""
    return {
        "hourly": ",".join(VARIABLES),
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "timeformat": "unixtime",
        "start_hour": start.strftime("%Y-%m-%dT%H:%M"),
        "end_hour": end.strftime("%Y-%m-%dT%H:%M"),
    }


def _covers(hourlies, start, end):
    """Whether every series is there by `start` and runs past `end`.

    Rain and snow at a moment are read from the stamp after it, so the
    series has to run past the last moment, not merely up to it.
    """
    first, last = start.timestamp(), end.timestamp()
    return all(hourly.times[0] <= first and hourly.times[-1] > last for hourly in hourlies)


def midnight_after(when):
    """The first midnight at or after `when`."""
    midnight = when.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight if midnight == when else midnight + timedelta(days=1)


def _fetch(points, start, end):
    where = hashlib.sha1(",".join("%.4f,%.4f" % p for p in points).encode()).hexdigest()
    key = "forecast2:%s:%s:%s" % (start.strftime("%Y%m%d%H"), end.strftime("%Y%m%d%H"), where)  # 2: see planner.find_routes
    found = cache.get(key)
    if found is not None:
        return found
    try:
        response = _session.get(
            f"{settings.OPEN_METEO_URL}/v1/forecast",
            params={
                "latitude": ",".join("%.4f" % lat for lat, _ in points),
                "longitude": ",".join("%.4f" % lon for _, lon in points),
                **query(start, end),
                **({"apikey": settings.OPEN_METEO_API_KEY} if settings.OPEN_METEO_API_KEY else {}),
            },
            headers={"User-Agent": settings.USER_AGENT},
            timeout=settings.HTTP_TIMEOUT,
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherError("the weather service could not be reached") from exc
    if isinstance(body, dict) and body.get("error"):
        reason = body.get("reason", "no reason given")
        if "limit" in reason.lower():
            raise busy(reason)
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
    columns = [data[name] for name in VARIABLES]
    if any(len(column) != len(times) for column in columns):
        raise ValueError("ragged columns")
    rows = list(zip(times, *columns))
    # The model runs sixteen days out from its own start, so between
    # midnight UTC and the arrival of the day's first run, around half past
    # four, the last few hours of the sixteenth day come back null. Those
    # are cut off the end, and forecast() checks whether the trip needed
    # them. A null anywhere else is an hour the model has nothing for;
    # reading it as calm would be the wrong way round for a safety rating,
    # so the plan is refused instead.
    while rows and None in rows[-1]:
        rows.pop()
    if not rows or any(None in row for row in rows):
        raise WeatherError("the weather service has no forecast for part of this trip")
    times, wind, rain, showers, snow = zip(*rows)
    return Hourly(
        list(times),
        [float(w) for w in wind],
        [float(r) + float(s) for r, s in zip(rain, showers)],
        [float(s) for s in snow],
    )
