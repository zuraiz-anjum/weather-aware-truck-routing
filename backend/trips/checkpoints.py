"""
Where along a route the weather is looked at, and when the truck gets there.

Checkpoints sit every so many miles from the origin, with the destination as
the last one. Each checkpoint stands for the stretch of road from it to the
next, which is what turns a risk level into miles of road at that level.
"""

from dataclasses import dataclass

from .geometry import interpolate

INTERVALS = (10, 25, 50)

# More checkpoints than this on one route means thousands of forecast points
# for a coast-to-coast trip and no more information, since the forecast grid
# is coarser than the spacing anyway.
MAX_PER_ROUTE = 150

# A marker this close to the destination is the destination.
MERGE_MILES = 1.0


@dataclass(frozen=True)
class Checkpoint:
    mile: float
    lat: float
    lon: float
    seconds: float  # driving time from departure
    covers_miles: float  # road from here to the next checkpoint


def choose_interval(requested, longest_miles):
    """The requested spacing, or the next coarser one that keeps a route under MAX_PER_ROUTE."""
    for interval in INTERVALS:
        if interval >= requested and longest_miles / interval <= MAX_PER_ROUTE:
            return interval
    return INTERVALS[-1]


def default_interval(longest_miles):
    if longest_miles <= 300:
        return 10
    if longest_miles <= 1000:
        return 25
    return 50


def place(line, seconds, interval_miles):
    """Checkpoints along `line`; `seconds` is the cumulative driving time at each of its vertices."""
    marks = line.markers(interval_miles)
    if len(marks) > 2 and marks[-1] - marks[-2] < MERGE_MILES:
        del marks[-2]
    out = []
    for mile, following in zip(marks, marks[1:] + [marks[-1]]):
        lat, lon = line.position(mile)
        out.append(Checkpoint(mile, lat, lon, interpolate(line.miles, seconds, mile), following - mile))
    return out
