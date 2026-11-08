"""
Distances and positions along a road, and the two reductions a road goes
through: a simplified copy for the browser, and a sampling every few miles
for everything that treats it as a set of points.

Roads here are a few thousand miles long at most, so a flat projection
scaled by the cosine of the mean latitude is accurate to a fraction of a
per cent, which is all that choosing vertices or matching points needs. The
mileage a driver sees is great-circle.
"""

import math
from bisect import bisect_right

EARTH_RADIUS_MILES = 3958.7613
MILES_PER_DEGREE = EARTH_RADIUS_MILES * math.pi / 180


def haversine_miles(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(a, 1.0)))


def interpolate(xs, ys, x):
    """ys at x, linear between the two surrounding xs, held flat beyond the ends."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x)
    span = xs[i] - xs[i - 1]
    if span == 0:
        return ys[i]
    return ys[i - 1] + (ys[i] - ys[i - 1]) * (x - xs[i - 1]) / span


class Polyline:
    """Vertices as (lat, lon) with the cumulative mileage at each one.

    A road's vertices come from a routing engine that also reports the
    driven distance, which is a little longer than the sum of the straight
    segments between the vertices. Given `length`, the mileage is scaled so
    that the last vertex lands on it and mile markers match the engine's.
    """

    def __init__(self, points, length=None):
        self.points = [(float(lat), float(lon)) for lat, lon in points]
        if len(self.points) < 2:
            raise ValueError("a polyline needs at least two points")
        miles = [0.0]
        for (lat1, lon1), (lat2, lon2) in zip(self.points, self.points[1:]):
            miles.append(miles[-1] + haversine_miles(lat1, lon1, lat2, lon2))
        if length is not None and miles[-1] > 0:
            factor = length / miles[-1]
            miles = [m * factor for m in miles]
            miles[-1] = float(length)
        self.miles = miles

    @property
    def length(self):
        return self.miles[-1]

    def position(self, mile):
        """(lat, lon) at a mile marker, between vertices where it falls between them."""
        if mile <= 0:
            return self.points[0]
        if mile >= self.length:
            return self.points[-1]
        i = bisect_right(self.miles, mile)
        (lat1, lon1), (lat2, lon2) = self.points[i - 1], self.points[i]
        span = self.miles[i] - self.miles[i - 1]
        t = (mile - self.miles[i - 1]) / span if span else 0.0
        return (lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t)

    def markers(self, step_miles):
        """Mile markers every step_miles from the start, with the end itself last."""
        marks = [float(k * step_miles) for k in range(int(self.length // step_miles) + 1)]
        if self.length - marks[-1] > 1e-9:
            marks.append(self.length)
        return marks

    def sample(self, step_miles):
        """The positions at markers(step_miles)."""
        return [self.position(m) for m in self.markers(step_miles)]


def flat(points):
    """(x, y) in miles on a plane touching the sphere at the mean latitude of the points."""
    lat0 = math.radians(sum(lat for lat, _ in points) / len(points))
    kx = MILES_PER_DEGREE * math.cos(lat0)
    return [(lon * kx, lat * MILES_PER_DEGREE) for lat, lon in points]


def simplify(points, tolerance_miles):
    """The vertices that keep the line within tolerance_miles of the original."""
    return [points[i] for i in simplify_indices(points, tolerance_miles)]


def simplify_indices(points, tolerance_miles):
    """Douglas-Peucker: the indices of the vertices simplify() keeps, ascending."""
    n = len(points)
    if n < 3:
        return list(range(n))
    xy = flat(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    limit = tolerance_miles * tolerance_miles
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = xy[a]
        dx, dy = xy[b][0] - ax, xy[b][1] - ay
        seg = dx * dx + dy * dy
        worst, at = 0.0, a
        for i in range(a + 1, b):
            px, py = xy[i][0] - ax, xy[i][1] - ay
            if seg:
                t = (px * dx + py * dy) / seg
                t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                px, py = px - t * dx, py - t * dy
            d = px * px + py * py
            if d > worst:
                worst, at = d, i
        if worst > limit:
            keep[at] = True
            stack.append((a, at))
            stack.append((at, b))
    return [i for i in range(n) if keep[i]]


def shared_fraction(points, others, within_miles):
    """The fraction of `points` that lie within within_miles of some point of `others`."""
    if not points:
        return 0.0
    return sum(near_mask(points, others, within_miles)) / len(points)


def passes_once(points, within_miles, apart=3):
    """For each point of a sampled line, whether no part of the line `apart` samples or more away comes within within_miles.

    A road driven out to a spot and back along itself fails this on the
    way out and on the way back.
    """
    xy = flat(points) if points else []
    size = within_miles
    buckets = {}
    for k, (x, y) in enumerate(xy):
        buckets.setdefault((int(x // size), int(y // size)), []).append((k, x, y))
    limit = within_miles * within_miles
    out = []
    for k, (x, y) in enumerate(xy):
        i, j = int(x // size), int(y // size)
        out.append(not any(
            abs(other - k) >= apart and (x - bx) ** 2 + (y - by) ** 2 <= limit
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
            for other, bx, by in buckets.get((i + di, j + dj), ())
        ))
    return out


def near_mask(points, others, within_miles):
    """For each of `points`, whether some point of `others` lies within within_miles.

    Both are expected to be sampled at a spacing no coarser than within_miles,
    which makes a bucket grid of that size exact enough: a point can only be
    near something in its own or an adjacent bucket.
    """
    if not points:
        return []
    xy = flat(points + others)
    mine, theirs = xy[: len(points)], xy[len(points) :]
    size = within_miles
    buckets = {}
    for x, y in theirs:
        buckets.setdefault((int(x // size), int(y // size)), []).append((x, y))
    limit = within_miles * within_miles

    def close(x, y):
        i, j = int(x // size), int(y // size)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for bx, by in buckets.get((i + di, j + dj), ()):
                    if (x - bx) ** 2 + (y - by) ** 2 <= limit:
                        return True
        return False

    return [close(x, y) for x, y in mine]
