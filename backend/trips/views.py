import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView, exception_handler as drf_exception_handler

from . import geocoding, osrm, planner, weather
from .serializers import PlanInput

log = logging.getLogger(__name__)


class PlanThrottle(AnonRateThrottle):
    scope = "plan"


class PlanView(APIView):
    """POST /api/plan/: three routes, their checkpoints assessed, the heatmap, and which to take."""

    throttle_classes = [PlanThrottle]

    def post(self, request):
        form = PlanInput(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        result = planner.plan(
            resolve(data["origin"]),
            resolve(data["destination"]),
            data["departure"],
            data["load_lb"],
            data.get("interval_miles"),
        )
        return Response(result)


def resolve(place):
    """A Place from the form: typed coordinates as they are, text through the geocoder."""
    if "lat" in place:
        return geocoding.Place(place.get("text") or "%.4f, %.4f" % (place["lat"], place["lon"]), place["lat"], place["lon"])
    return geocoding.locate(place["text"])


class PlacesView(APIView):
    """GET /api/places/?q=: suggestions for the origin and destination boxes."""

    def get(self, request):
        places = geocoding.suggest(request.query_params.get("q", ""))
        return Response({"places": [{"label": p.label, "lat": p.lat, "lon": p.lon} for p in places]})


class HealthView(APIView):
    throttle_classes = []

    def get(self, request):
        return Response({"status": "ok"})


UNPLANNABLE = (osrm.NoRoute, geocoding.PlaceNotFound, planner.PlanningError)
UPSTREAM = (osrm.RoutingError, weather.WeatherError, geocoding.GeocodingError)


def exception_handler(exc, context):
    """Every error as {"detail": "..."}: ours with the right status, the framework's flattened."""
    if isinstance(exc, UNPLANNABLE):
        return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    if isinstance(exc, weather.WeatherBusy):
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE, headers={"Retry-After": str(exc.retry_after)})
    if isinstance(exc, UPSTREAM):
        log.warning("upstream failure: %s", exc, exc_info=exc.__cause__)
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict) and "detail" not in response.data:
        response.data = {"detail": "; ".join(flatten(response.data)), "errors": response.data}
    return response


def flatten(errors, where=""):
    """'origin.lat: message' lines from the framework's nested error dict."""
    if isinstance(errors, dict):
        for field, inner in errors.items():
            if field == "non_field_errors":
                yield from flatten(inner, where)
            else:
                yield from flatten(inner, f"{where}.{field}" if where else str(field))
    elif isinstance(errors, list):
        for item in errors:
            yield from flatten(item, where)
    else:
        message = str(errors).rstrip(".")  # the lines are joined with semicolons
        # A message that names its own field, as the departure's do, needs no prefix.
        if not where or message.startswith("the %s " % where.rsplit(".", 1)[-1]):
            yield message
        else:
            yield f"{where}: {message}"
