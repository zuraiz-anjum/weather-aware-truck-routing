"""
Putting a trip together: the two places, the roads between them, the
checkpoints along each road, the forecast where and when the truck passes,
and which road to take.

Routes between two places are the same whatever the departure and the
load, so they are fetched once a day; the forecast is fetched for every
plan, in one go for the checkpoints of all the routes and the cells of the
heatmap, and the risk rules are applied to both.
"""

from datetime import timedelta

from django.core.cache import cache

from . import checkpoints, corridor, osrm, risk, weather
from .geometry import haversine_miles

SLIDER_HOURS = 48
ROUTES_CACHE_SECONDS = 24 * 3600
# When a side request failed the set of routes may be short through no
# fault of the geography, so it is kept only long enough to ride out a blip.
SHORT_CACHE_SECONDS = 10 * 60
SAME_PLACE_MILES = 1.0

# The recommendation, in the brief's order: fewest Severe miles, fewest High
# miles, lowest average risk, shortest driving time. No Travel miles come
# before all of these: a route with any is not a route the truck can take.
CRITERIA = (
    "fewer miles rated No Travel",
    "fewer miles rated Severe",
    "fewer miles rated High",
    "a lower average risk",
    "a shorter driving time",
)


class PlanningError(Exception):
    """The request is sound but no plan can be made of it."""


def plan(origin, destination, departure, load_lb, interval=None):
    """The plan for a trip from origin to destination (geocoding.Place), leaving at departure (aware)."""
    departure = departure.replace(microsecond=0)
    if haversine_miles(origin.lat, origin.lon, destination.lat, destination.lon) < SAME_PLACE_MILES:
        raise PlanningError("the origin and the destination are the same place")
    routes, missed = find_routes((origin.lat, origin.lon), (destination.lat, destination.lon))
    notes = []
    if len(routes) < osrm.WANTED:
        notes.append("Only %s distinct road route%s found between these places." % (
            ("one", " was") if len(routes) == 1 else ("two", "s were")))
        if missed:
            notes.append("The routing service did not answer every request; another try in a few minutes may find more.")

    longest_miles = max(r.distance_miles for r in routes)
    requested = interval or checkpoints.default_interval(longest_miles)
    interval = checkpoints.choose_interval(requested, longest_miles)
    if interval != requested:
        notes.append("Weather is sampled every %d miles rather than %d on a trip this long." % (interval, requested))
    stops = [checkpoints.place(r.line, r.seconds, interval) for r in routes]
    band = corridor.build([r.line for r in routes])

    end = departure + max(timedelta(seconds=max(r.duration_seconds for r in routes)), timedelta(hours=SLIDER_HOURS))
    # Rain at the last moment is read from the hour after it, so the trip
    # has to end before the horizon's last stamp, not on it.
    horizon = weather.horizon()
    if end >= horizon:
        raise PlanningError("the forecast runs to %s UTC and this trip would still need it after that; leave earlier"
                            % horizon.strftime("%d %b %H:%M"))

    # One forecast request for everything, each distinct point once: the
    # routes share their ends, and every point counts against the allowance.
    wanted = [(c.lat, c.lon) for route_stops in stops for c in route_stops] + [cell.point for cell in band.cells]
    index = {}
    slots = [index.setdefault((round(lat, 4), round(lon, 4)), len(index)) for lat, lon in wanted]
    fetched = weather.forecast(list(index), departure, end)
    hourlies = [fetched[slot] for slot in slots]
    taken = 0
    judged = []
    for route, route_stops in zip(routes, stops):
        judged.append(judge(route, route_stops, hourlies[taken : taken + len(route_stops)], departure, load_lb))
        taken += len(route_stops)
    cells = hourlies[taken:]

    order = sorted(range(len(routes)), key=lambda k: judged[k]["key"])
    ids = {k: "ABC"[rank] for rank, k in enumerate(order)}
    quickest = min(range(len(routes)), key=lambda k: routes[k].duration_seconds)
    names = describe(routes)

    # The best route is only recommended when nothing on it is rated No
    # Travel; otherwise it is the least bad, and the plan says so plainly.
    best = judged[order[0]]
    blocked = best["summary"]["miles_by_level"][risk.NO_TRAVEL]
    warning = None
    if blocked:
        warning = ("No route is clear to drive at this departure. Route A is the least bad and still has "
                   "%d miles rated No Travel; leave at another time." % round(blocked))

    out = []
    for rank, k in enumerate(order, start=1):
        route, verdict = routes[k], judged[k]
        out.append({
            "id": ids[k],
            "name": names[k],
            "detour": route.detour,
            "distance_miles": round(route.distance_miles, 1),
            "minor_miles": round(route.minor_miles, 1),
            "minor_roads": route.minor_roads(),
            "duration_seconds": round(route.duration_seconds),
            "arrival": (departure + timedelta(seconds=round(route.duration_seconds))).isoformat(),
            "geometry": {"type": "LineString", "coordinates": [[round(lon, 5), round(lat, 5)] for lat, lon in route.line.points]},
            "checkpoints": verdict["checkpoints"],
            "summary": {
                **verdict["summary"],
                "rank": rank,
                "recommended": rank == 1 and not blocked,
                "reason": reason(verdict["key"], judged[quickest]["key"], ids[quickest]) if rank == 1 and not blocked else None,
            },
        })

    return {
        "origin": {"label": origin.label, "lat": origin.lat, "lon": origin.lon},
        "destination": {"label": destination.label, "lat": destination.lat, "lon": destination.lon},
        "departure": departure.isoformat(),
        "load_lb": load_lb,
        "interval_miles": interval,
        "slider_hours": SLIDER_HOURS,
        "notes": notes,
        "warning": warning,
        "routes": out,
        "heatmap": heatmap(band, cells, departure, load_lb),
    }


def find_routes(origin, destination):
    """The routes for a pair of places and how many side requests failed, from the cache when it has them."""
    # The number in the key goes up whenever what is stored changes shape,
    # so that entries written by an older copy of the code are passed over.
    key = "routes3:%.4f,%.4f:%.4f,%.4f" % (*origin, *destination)
    found = cache.get(key)
    if found is None:
        found = osrm.find(origin, destination)
        cache.set(key, found, SHORT_CACHE_SECONDS if found.missed else ROUTES_CACHE_SECONDS)
    return found


def judge(route, stops, hourlies, departure, load_lb):
    """Every checkpoint of one route assessed, with the figures the recommendation is made on."""
    readings = []
    for stop, hourly in zip(stops, hourlies):
        seconds = round(stop.seconds)
        eta = departure + timedelta(seconds=seconds)
        readings.append((stop, eta, seconds, risk.assess(*hourly.at(eta), load_lb)))
    miles_by_level = [0.0] * len(risk.NAMES)
    weighted = 0.0
    out = []
    for k, (stop, eta, seconds, found) in enumerate(readings):
        # A checkpoint stands for the road after it. The destination has no
        # road after it, but the truck arrives into its weather, so when that
        # reading is worse than the final stretch's own the stretch takes it:
        # a route arriving into No Travel conditions is not clear to drive.
        charged = found.level
        if k == len(readings) - 2:
            charged = max(charged, readings[-1][3].level)
        miles_by_level[charged] += stop.covers_miles
        weighted += charged * stop.covers_miles
        wind, rain, snow = found.readings
        out.append({
            "mile": round(stop.mile, 1),
            "lat": round(stop.lat, 5),
            "lon": round(stop.lon, 5),
            "eta": eta.isoformat(),
            "seconds": seconds,
            "covers_miles": round(stop.covers_miles, 1),
            "wind_mph": wind,
            "rain_in": rain,
            "snow_in": snow,
            "level": found.level,
            "wind_level": found.wind,
            "rain_level": found.rain,
            "snow_level": found.snow,
            "load_rule": found.load_rule,
        })
    average = weighted / route.distance_miles if route.distance_miles else 0.0
    # The mean is compared to a tenth. A longer route that meets the same
    # trouble has a lower mean only for carrying more calm miles after it,
    # which is no reason to drive them; means that close fall through to time.
    key = (
        round(miles_by_level[risk.NO_TRAVEL], 1),
        round(miles_by_level[risk.SEVERE], 1),
        round(miles_by_level[risk.HIGH], 1),
        round(average, 1),
        route.duration_seconds,
    )
    summary = {
        "miles_by_level": [round(m, 1) for m in miles_by_level],
        "average_risk": round(average, 2),
        "worst_level": max(c["level"] for c in out),
    }
    return {"checkpoints": out, "summary": summary, "key": key}


def reason(best, quickest, quickest_id):
    """Why the best route is best, put against the quickest one, which is what a driver would take otherwise."""
    if best == quickest:
        return "the quickest route, and no other scores better on weather"
    behind = (best[-1] - quickest[-1]) / 60
    # Ranked above the quickest route, it beats it on some count before time.
    criterion = next(c for mine, theirs, c in zip(best, quickest, CRITERIA) if mine < theirs)
    if round(behind) == 0:
        return f"as quick as Route {quickest_id}, and {criterion}"
    gap = "%d min" % round(behind) if behind < 90 else "%.1f h" % (behind / 60)
    return f"{gap} slower than Route {quickest_id}, but {criterion}"


def describe(routes):
    """'via I-80 and I-76': the road a route drives most, and the one that sets it apart from the others.

    Among the roads that carry a real share of the drive and that the other
    routes do not, an interstate is named before a US highway before a
    state road, since that is how a dispatcher thinks of a route; failing
    any such road, the longest other road worth mentioning.
    """
    named = [(route, *roads_of(route, routes, max(10.0, 0.05 * route.distance_miles))) for route in routes]
    out = [phrase(top, second) for _, top, second in named]
    # Two routes named alike are told apart by whatever road differs, however short.
    alike = {n for n in out if out.count(n) > 1}
    for k, (route, top, second) in enumerate(named):
        if out[k] in alike:
            out[k] = phrase(top, second, own_road(route, routes, 1.0, besides=(top, second)))
    return out


def roads_of(route, routes, worth):
    """The road a route drives most and the one that sets it apart from the others; either may be None."""
    if not route.roads:
        return None, None
    top = max(route.roads, key=route.roads.get)
    second = own_road(route, routes, worth, besides=(top,))
    if second is None:
        rest = [road for road, miles in route.roads.items() if road != top and miles >= 2 * worth]
        second = max(rest, key=lambda road: (road_class(road), route.roads[road])) if rest else None
    return top, second


def own_road(route, routes, worth, besides):
    """The road on which this route drives at least `worth` miles more than any other does, or None."""
    others = [o for o in routes if o is not route]
    apart = {
        road: miles - max((o.roads.get(road, 0.0) for o in others), default=0.0)
        for road, miles in route.roads.items()
        if road not in besides
    }
    own = [road for road, miles in apart.items() if miles >= worth]
    return max(own, key=lambda road: (road_class(road), apart[road])) if own else None


def phrase(top, second=None, third=None):
    if top is None:
        return "via local roads"
    roads = [road for road in (top, second, third) if road]
    return "via " + (" and ".join(roads) if len(roads) < 3 else f"{roads[0]}, {roads[1]} and {roads[2]}")


def road_class(road):
    return 2 if road.startswith("I-") else 1 if road.startswith("US-") else 0


def heatmap(band, hourlies, departure, load_lb):
    """GeoJSON cells, each with its risk level at every hour of the slider."""
    hours = [departure + timedelta(hours=h) for h in range(SLIDER_HOURS + 1)]
    features = []
    for cell, hourly in zip(band.cells, hourlies):
        levels = [risk.assess(*hourly.at(when), load_lb).level for when in hours]
        ring = [[cell.west, cell.south], [cell.east, cell.south], [cell.east, cell.north], [cell.west, cell.north], [cell.west, cell.south]]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[round(lon, 4), round(lat, 4)] for lon, lat in ring]]},
            "properties": {"levels": levels},
        })
    return {"type": "FeatureCollection", "cell_miles": round(band.cell_miles, 1), "features": features}
