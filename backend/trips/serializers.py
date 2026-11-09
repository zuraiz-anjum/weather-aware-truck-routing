from datetime import datetime, timedelta, timezone

from rest_framework import serializers

from .checkpoints import INTERVALS
from .geocoding import EAST, NORTH, SOUTH, WEST

# A dispatcher plans the week ahead; further out the forecast is weather
# lore. Open-Meteo stops at 23:00 UTC on the sixteenth day counting today,
# and the two days of slider after the departure have to fit inside that
# whatever the time of day the request is made: thirteen days less an hour.
EARLIEST_BEHIND = timedelta(hours=1)
LATEST_AHEAD = timedelta(days=13) - timedelta(hours=1)

MAX_LOAD_LB = 200_000


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

    def validate_departure(self, value):
        now = datetime.now(timezone.utc)
        if value < now - EARLIEST_BEHIND:
            raise serializers.ValidationError("the departure is in the past")
        if value > now + LATEST_AHEAD:
            raise serializers.ValidationError(
                "the departure is too far ahead; the latest is %s UTC" % (now + LATEST_AHEAD).strftime("%d %b %H:%M"))
        return value.replace(microsecond=0)
