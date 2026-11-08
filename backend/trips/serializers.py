from datetime import datetime, timedelta, timezone

from rest_framework import serializers

from .checkpoints import INTERVALS

# A dispatcher plans the week ahead; further out the forecast is weather
# lore, and Open-Meteo stops at sixteen days anyway.
EARLIEST_BEHIND = timedelta(hours=1)
LATEST_AHEAD = timedelta(days=14)

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
            raise serializers.ValidationError("the departure is more than %d days away" % LATEST_AHEAD.days)
        return value.replace(microsecond=0)
