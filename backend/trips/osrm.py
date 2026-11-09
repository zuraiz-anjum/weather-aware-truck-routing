"""
Routes from OSRM, and three of them when it offers fewer.

One request with alternatives and steps gives each route's full geometry,
the driving time of every step, which puts a clock on every vertex, and the
roads it follows. OSRM's own alternatives are usually one or two. The rest
are found by routing through a point off to one side of the straight line
between the ends. Such a point is an arbitrary spot the road has to leave
and come back to, so a promising candidate is routed once more through a
point on its new stretch itself, which gives the road without the
excursion. A candidate is kept when its new road actually gets somewhere,
is mostly new, and is not much slower; a trip down a single valley may
honestly have fewer than three.
"""

import logging
import math
import re
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests
from django.conf import settings

from . import polyline
from .geometry import (
    MILES_PER_DEGREE, Polyline, haversine_miles, near_mask, passes_once, shared_fraction, simplify_indices,
)

log = logging.getLogger(__name__)

METRES_PER_MILE = 1609.344
WANTED = 3

# OSRM draws a road with a vertex every hundred metres or so, tens of
# thousands for a long trip. Thinned to within thirty metres of itself the
# line keeps a tenth of them, and nothing downstream, from the mile markers
# to the map, can tell the difference.
SHAPE_TOLERANCE_MILES = 0.02

# Where the side points go, as (how far along the straight line, how far off
# it as a fraction of its length): the middle first, then a third of the way
# from either end, then the middle again but further out. The offset is kept
# within reason for very short and very long trips.
DETOUR_ROUNDS = (((0.5, 0.2),), ((0.33, 0.2), (0.67, 0.2)), ((0.5, 0.35),))
DETOUR_MIN_MILES = 8.0
DETOUR_MAX_MILES = 150.0

# A candidate is a route of its own when its longest stretch of new road is
# at least MIN_NEW_MILES long with its ends at least SPREAD of that apart
# (an excursion that leaves a road and comes back to the same place is not
# a route), when no more than UNNUMBERED_AT_MOST of that stretch is on roads
# without a route number (OSRM routes a car, and will happily send it down
# a forest road or a parkway that no truck may use), when less than
# MOSTLY_SHARED of it runs within a mile of a route already in hand, and
# when it is no slower than SLOWER_AT_MOST times the quickest: a safer road
# half as long again is still one a dispatcher would want to see.
SAMPLE_MILES = 2.0
MIN_NEW_MILES = 10.0
SPREAD = 0.4
UNNUMBERED_AT_MOST = 0.5
MOSTLY_SHARED = 0.85
SLOWER_AT_MOST = 1.6


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
    unnumbered: list  # (from mile, to mile, name) of each stretch on a road without a route number
    detour: bool  # found through a side point rather than offered by OSRM

    @property
    def unnumbered_miles(self):
        return sum(to - start for start, to, _ in self.unnumbered)

    def unnumbered_between(self, a, b):
        """Miles of unnumbered road between mile a and mile b."""
        return sum(max(0.0, min(b, to) - max(a, start)) for start, to, _ in self.unnumbered)

    def unnumbered_roads(self, limit=2):
        """The unnumbered roads driven furthest, by name, furthest first."""
        miles = {}
        for start, to, name in self.unnumbered:
            if name:
                miles[name] = miles.get(name, 0.0) + to - start
        return sorted(miles, key=miles.get, reverse=True)[:limit]


Found = namedtuple("Found", "routes missed")  # missed: side requests that failed, when the set is short for it
Run = namedtuple("Run", "length gap middle unnumbered")

_session = requests.Session()


def find(origin, destination):
    """Up to three distinct routes from origin to destination, quickest first, and how many requests failed."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        offered = pool.submit(alternatives, origin, destination)
        # The first pair of side points is asked for alongside the main
        # request rather than after it, since most trips turn out to need one.
        first, *later = DETOUR_ROUNDS
        sides = side_routes(pool, origin, destination, first)
        routes = offered.result()
        missed = admit(origin, destination, routes, sides)
        for spots in later:
            if len(routes) >= WANTED:
                break
            missed += admit(origin, destination, routes, side_routes(pool, origin, destination, spots))
    routes.sort(key=lambda r: r.duration_seconds)
    return Found(routes[:WANTED], missed if len(routes) < WANTED else 0)


def side_routes(pool, origin, destination, spots):
    return [
        pool.submit(via, origin, beside(origin, destination, fraction, side, offset), destination)
        for fraction, offset in spots
        for side in (1, -1)
    ]


def admit(origin, destination, routes, jobs):
    """Add the side routes that are roads of their own, quicker ones first; returns how many requests failed."""
    candidates, missed = [], 0
    for job in jobs:
        try:
            candidates.append(job.result())
        except NoRoute:
            pass  # a side point in the sea or the wilderness; nothing to retry
        except RoutingError as exc:
            missed += 1
            log.info("side route failed: %s", exc)
    for candidate in sorted(candidates, key=lambda r: r.duration_seconds):
        if len(routes) >= WANTED:
            break
        run = bridging(candidate, routes)
        if run is None:
            continue
        # Routed once more through its own new road, which gives the road
        # without the excursion to the side point, and only now, since a
        # candidate that is not reached is not worth a request.
        options = [(candidate, run)]
        try:
            again = via(origin, run.middle, destination)
            options.append((again, bridging(again, routes)))
        except RoutingError as exc:
            missed += 1
            log.info("side route through its own road failed: %s", exc)
        for option, run in sorted(options, key=lambda pair: pair[0].duration_seconds):
            if run and run.unnumbered <= UNNUMBERED_AT_MOST * run.length and distinct(option, routes):
                routes.append(option)
                break
    return missed


def bridging(route, others):
    """The longest stretch of `route` that is new road and gets somewhere, or None for a spur."""
    mine = route.line.sample(SAMPLE_MILES)
    theirs = [p for o in others for p in o.line.sample(SAMPLE_MILES)]
    near = near_mask(mine, theirs, 1.0)
    once = passes_once(mine, 1.0)
    best = start = None
    for i, is_near in enumerate(near + [True]):
        if not is_near and start is None:
            start = i
        elif is_near and start is not None:
            length = SAMPLE_MILES * (i - start)
            gap = haversine_miles(*mine[max(start - 1, 0)], *mine[min(i, len(mine) - 1)])
            if length >= MIN_NEW_MILES and gap >= SPREAD * length and (best is None or length > best.length):
                # The point to route through again: on the new road, as near
                # its middle as can be, and somewhere the route passes only
                # once with room on either side, so not on the way out to the
                # side point and back, nor at the turn.
                middle = (start + i) // 2
                single = [k for k in range(start, i) if all(once[max(start, k - 3) : min(i, k + 4)])] or [middle]
                unnumbered = route.unnumbered_between(start * SAMPLE_MILES, i * SAMPLE_MILES)
                best = Run(length, gap, mine[min(single, key=lambda k: abs(k - middle))], unnumbered)
            start = None
    return best


def distinct(candidate, routes):
    quickest = min(r.duration_seconds for r in routes)
    if candidate.duration_seconds > SLOWER_AT_MOST * quickest:
        return False
    mine = candidate.line.sample(SAMPLE_MILES)
    return all(shared_fraction(mine, r.line.sample(SAMPLE_MILES), 1.0) <= MOSTLY_SHARED for r in routes)


def beside(origin, destination, fraction, side, offset=0.2):
    """A point `fraction` of the way from origin to destination, `offset` of that distance off to one side."""
    lat0 = math.radians((origin[0] + destination[0]) / 2)
    kx, ky = MILES_PER_DEGREE * math.cos(lat0), MILES_PER_DEGREE
    ax, ay = (destination[1] - origin[1]) * kx, (destination[0] - origin[0]) * ky
    length = math.hypot(ax, ay)
    if length == 0:
        return origin
    offset = min(max(offset * length, DETOUR_MIN_MILES), DETOUR_MAX_MILES) * side
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
    points, seconds, roads, unnumbered = [], [], {}, []
    clock = mile = 0.0
    for leg in data["legs"]:
        for step in leg["steps"]:
            shape = polyline.decode(step["geometry"])
            duration = float(step["duration"])
            length = float(step["distance"]) / METRES_PER_MILE
            road = road_name(step)
            if road:
                roads[road] = roads.get(road, 0.0) + length
            if length and not numbered(step):
                name = step.get("name") or ""
                if unnumbered and unnumbered[-1][1] == mile and unnumbered[-1][2] == name:
                    unnumbered[-1] = (unnumbered[-1][0], mile + length, name)
                else:
                    unnumbered.append((mile, mile + length, name))
            mile += length
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
    duration = float(data["duration"])
    # The steps add up to a second or so off the route's own time; the clock
    # is nudged so the last vertex lands on it, as the mileage is on the distance.
    if clock and clock != duration:
        seconds = [s * duration / clock for s in seconds]
    kept = simplify_indices(points, SHAPE_TOLERANCE_MILES)
    line = Polyline([points[i] for i in kept], distance)
    return Route(line, [seconds[i] for i in kept], distance, duration, roads, unnumbered, detour)


def road_name(step):
    """'I-80' from a ref of 'I 80; US 30', else the street name, else nothing."""
    ref = (step.get("ref") or "").split(";")[0].strip()
    if ref:
        head, _, tail = ref.partition(" ")
        if head.isalpha() and head.isupper() and tail[:1].isdigit():
            return f"{head}-{tail}"
        return ref
    return step.get("name") or None


# A forest road's number is not a route number, and a road whose name says
# what it is ("US Highway 54 South", "North Sacramento Freeway") is a
# numbered road that the map data left the ref off.
FOREST_ROADS = ("NF", "FR", "FS", "NFD")
HIGHWAY_BY_NAME = re.compile(r"\b(highway|hwy|freeway|fwy|expressway|expy|turnpike|tpke|tollway|interstate)\b", re.I)


def numbered(step):
    """Whether a step runs on a road with a route number, which is what a truck can count on."""
    ref = (step.get("ref") or "").split(";")[0].strip()
    if ref:
        return ref.partition(" ")[0].upper() not in FOREST_ROADS
    return bool(HIGHWAY_BY_NAME.search(step.get("name") or ""))
