"""
Routes from OSRM, and three of them when it offers fewer.

One request with alternatives and steps gives each route's full geometry,
the driving time of every step, which puts a clock on every vertex, and the
roads it follows. OSRM's own alternatives are usually one or two. The rest
are found by routing through a point off to one side of the straight line
between the ends, and kept when they are mostly new road and not much
slower; a trip down a single valley may honestly have fewer than three.
"""

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests
from django.conf import settings

from . import polyline
from .geometry import MILES_PER_DEGREE, Polyline, haversine_miles, interpolate, shared_fraction, simplify_indices

log = logging.getLogger(__name__)

METRES_PER_MILE = 1609.344
WANTED = 3

# OSRM draws a road with a vertex every hundred metres or so, tens of
# thousands for a long trip. Thinned to within thirty metres of itself the
# line keeps a tenth of them, and nothing downstream, from the mile markers
# to the map, can tell the difference.
SHAPE_TOLERANCE_MILES = 0.02

# Where the side points go: a fifth of the way across, within reason, at the
# middle first and then a third of the way from either end.
DETOUR_FRACTION = 0.2
DETOUR_MIN_MILES = 8.0
DETOUR_MAX_MILES = 150.0
DETOUR_ROUNDS = ((0.5,), (0.33, 0.67))

# A candidate is a route of its own when less than this much of it runs
# within a mile of a route already in hand, and it is no slower than this
# many times the quickest.
MOSTLY_SHARED = 0.85
SLOWER_AT_MOST = 1.4
SAMPLE_MILES = 2.0


class RoutingError(Exception):
    """OSRM could not be reached or answered with something unusable."""


class NoRoute(RoutingError):
    """There is no road between the two places."""


@dataclass
class Route:
    line: Polyline
    seconds: list  # driving time at each vertex of line
    distance_miles: float
    duration_seconds: float
    roads: dict  # road name -> miles driven on it
    detour: bool  # found through a side point rather than offered by OSRM

    def seconds_at(self, mile):
        return interpolate(self.line.miles, self.seconds, mile)


_session = requests.Session()


def find(origin, destination):
    """Up to three distinct routes from origin to destination, quickest first."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        offered = pool.submit(alternatives, origin, destination)
        # The first pair of side points is asked for alongside the main
        # request rather than after it, since most trips turn out to need one.
        first, second = DETOUR_ROUNDS
        sides = side_routes(pool, origin, destination, first)
        routes = offered.result()
        admit(routes, sides)
        if len(routes) < WANTED:
            admit(routes, side_routes(pool, origin, destination, second))
    routes.sort(key=lambda r: r.duration_seconds)
    return routes[:WANTED]


def side_routes(pool, origin, destination, fractions):
    return [
        pool.submit(via, origin, beside(origin, destination, fraction, side), destination)
        for fraction in fractions
        for side in (1, -1)
    ]


def admit(routes, jobs):
    """Add the side routes that are routes of their own, quicker ones first."""
    candidates = []
    for job in jobs:
        try:
            candidates.append(job.result())
        except RoutingError as exc:
            log.info("side route failed: %s", exc)
    for candidate in sorted(candidates, key=lambda r: r.duration_seconds):
        if len(routes) < WANTED and distinct(candidate, routes):
            routes.append(candidate)


def distinct(candidate, routes):
    quickest = min(r.duration_seconds for r in routes)
    if candidate.duration_seconds > SLOWER_AT_MOST * quickest:
        return False
    mine = candidate.line.sample(SAMPLE_MILES)
    return all(shared_fraction(mine, r.line.sample(SAMPLE_MILES), 1.0) <= MOSTLY_SHARED for r in routes)


def beside(origin, destination, fraction, side):
    """A point `fraction` of the way from origin to destination, off to one side."""
    lat0 = math.radians((origin[0] + destination[0]) / 2)
    kx, ky = MILES_PER_DEGREE * math.cos(lat0), MILES_PER_DEGREE
    ax, ay = (destination[1] - origin[1]) * kx, (destination[0] - origin[0]) * ky
    length = math.hypot(ax, ay)
    if length == 0:
        return origin
    offset = min(max(DETOUR_FRACTION * length, DETOUR_MIN_MILES), DETOUR_MAX_MILES) * side
    px, py = -ay / length * offset, ax / length * offset
    return (origin[0] + (ay * fraction + py) / ky, origin[1] + (ax * fraction + px) / kx)


def alternatives(origin, destination):
    body = _request([origin, destination], alternatives=3)
    return [_route(r, detour=False) for r in body["routes"]]


def via(origin, through, destination):
    body = _request([origin, through, destination], alternatives="false")
    return _route(body["routes"][0], detour=True)


def _request(places, **params):
    path = ";".join("%.6f,%.6f" % (lon, lat) for lat, lon in places)
    try:
        response = _session.get(
            f"{settings.OSRM_URL}/route/v1/driving/{path}",
            params={"steps": "true", "overview": "false", "geometries": "polyline", **params},
            headers={"User-Agent": settings.USER_AGENT},
            timeout=settings.HTTP_TIMEOUT,
        )
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RoutingError("the routing service could not be reached") from exc
    code = body.get("code") if isinstance(body, dict) else None
    if code in ("NoRoute", "NoSegment"):
        raise NoRoute("no road route between those places")
    if code != "Ok" or not body.get("routes"):
        raise RoutingError(f"the routing service answered {code or response.status_code}")
    return body


def _route(data, detour):
    try:
        return _stitch(data, detour)
    except (LookupError, TypeError, ValueError) as exc:
        raise RoutingError("the routing service answered with an unexpected shape") from exc


def _stitch(data, detour):
    """One Route from OSRM's legs and steps, with a clock on every vertex."""
    points, seconds, roads = [], [], {}
    clock = 0.0
    for leg in data["legs"]:
        for step in leg["steps"]:
            shape = polyline.decode(step["geometry"])
            duration = float(step["duration"])
            road = road_name(step)
            if road:
                roads[road] = roads.get(road, 0.0) + float(step["distance"]) / METRES_PER_MILE
            along = [0.0]
            for a, b in zip(shape, shape[1:]):
                along.append(along[-1] + haversine_miles(*a, *b))
            for k, point in enumerate(shape):
                if points and point == points[-1]:
                    continue  # consecutive steps share their boundary vertex
                points.append(point)
                seconds.append(clock + duration * (along[k] / along[-1] if along[-1] else 1.0))
            clock += duration
    distance = float(data["distance"]) / METRES_PER_MILE
    kept = simplify_indices(points, SHAPE_TOLERANCE_MILES)
    line = Polyline([points[i] for i in kept], distance)
    return Route(line, [seconds[i] for i in kept], distance, float(data["duration"]), roads, detour)


def road_name(step):
    """'I-80' from a ref of 'I 80; US 30', else the street name, else nothing."""
    ref = (step.get("ref") or "").split(";")[0].strip()
    if ref:
        head, _, tail = ref.partition(" ")
        if head.isalpha() and head.isupper() and tail[:1].isdigit():
            return f"{head}-{tail}"
        return ref
    return step.get("name") or None
