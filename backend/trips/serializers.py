import math
from datetime import datetime, timedelta, timezone

from rest_framework import serializers

from .checkpoints import INTERVALS
from .geocoding import EAST, NORTH, SOUTH, WEST
from .weather import VARIABLES

# A dispatcher plans the week ahead; further out the forecast is weather
# lore. Open-Meteo stops at 23:00 UTC on the sixteenth day counting today,
# and the two days of slider after the departure have to fit inside that
# whatever the time of day the request is made: thirteen days less an hour.
EARLIEST_BEHIND = timedelta(hours=1)
LATEST_AHEAD = timedelta(days=13) - timedelta(hours=1)

MAX_LOAD_LB = 200_000

# A forecast the browser fetched on the server's behalf (planner.NeedsForecast)
# is checked for shape here, cheaply, since a few hundred series of a few
# hundred hours is a million values, and for sense in weather.supplied. A
# plan asks for a few hundred points at most, and sixteen days are 385
# hours; anything past these was not fetched for the plan it came with.
MAX_FORECAST_POINTS = 400
MAX_FORECAST_HOURS = 500
HOURLY_SERIES = ("time", *VARIABLES)
NUMBER_OR_NULL = {int, float, type(None)}


class PlaceInput(serializers.Serializer):
    """A place as typed, or as picked from the suggestions with its coordinates."""

    text = serializers.CharField(max_length=200, required=False, allow_blank=True, trim_whitespace=True)
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False)

    def validate(self, data):
        if ("lat" in data) != ("lon" in data):
            raise serializers.ValidationError("give both lat and lon, or neither")
        if "lat" not in data and not data.get("text"):
            raise serializers.ValidationError("give a place name or coordinates")
        if "lat" in data and not (SOUTH <= data["lat"] <= NORTH and WEST <= data["lon"] <= EAST):
            raise serializers.ValidationError("coordinates are outside North America, which is as far as the app goes")
        return data


class PlanInput(serializers.Serializer):
    origin = PlaceInput()
    destination = PlaceInput()
    departure = serializers.DateTimeField()
    load_lb = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=INTERVALS, required=False)
    forecast = serializers.DictField(required=False)

    def validate_forecast(self, value):
        points, series = value.get("points"), value.get("hourly")
        if not isinstance(points, list) or not isinstance(series, list):
            raise serializers.ValidationError("give points and hourly, each a list")
        if len(points) > MAX_FORECAST_POINTS:
            raise serializers.ValidationError("more than %d points; no plan asks for that many" % MAX_FORECAST_POINTS)
        if len(series) != len(points):
            raise serializers.ValidationError("give one hourly series per point")
        for k, point in enumerate(points):
            if not (isinstance(point, list) and len(point) == 2 and all(type(c) in (int, float) and math.isfinite(c) for c in point)
                    and SOUTH <= point[0] <= NORTH and WEST <= point[1] <= EAST):
                raise serializers.ValidationError("point %d is not [lat, lon] in North America" % k)
        for k, hourly in enumerate(series):
            if not isinstance(hourly, dict) or set(hourly) != set(HOURLY_SERIES):
                raise serializers.ValidationError("hourly series %d is not Open-Meteo's hourly member (%s)" % (k, ", ".join(HOURLY_SERIES)))
            columns = [hourly[name] for name in HOURLY_SERIES]
            if not all(isinstance(column, list) for column in columns) or len({len(column) for column in columns}) != 1:
                raise serializers.ValidationError("the columns of hourly series %d are not lists of one length" % k)
            if len(columns[0]) > MAX_FORECAST_HOURS:
                raise serializers.ValidationError("hourly series %d runs longer than the forecast does" % k)
            if any(type(v) not in NUMBER_OR_NULL for column in columns for v in column):
                raise serializers.ValidationError("hourly series %d has a value that is not a number or null" % k)
        return value

    def validate_departure(self, value):
        now = datetime.now(timezone.utc)
        if value < now - EARLIEST_BEHIND:
            raise serializers.ValidationError("the departure is in the past")
        if value > now + LATEST_AHEAD:
            raise serializers.ValidationError(
                "the departure is too far ahead; the latest is %s UTC" % (now + LATEST_AHEAD).strftime("%d %b %H:%M"))
        return value.replace(microsecond=0)
