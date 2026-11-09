"""
The lattice of cells the weather heatmap is drawn on.

Cells are squares of latitude and longitude, a band of them along every
route, sized so that a trip is about two dozen cells long whatever its
length: a cell is then about forty pixels wide when the whole trip fits
on the screen, which is as fine as a heatmap needs to be. The count
matters because every cell is a point in the forecast request, and
Open-Meteo counts each point against a free allowance of six hundred a
minute.

A cell the road runs through is forecast where the road is: at a
checkpoint inside it when there is one, which costs nothing more, else at
the point of the road nearest its centre. A cell beside the road is
forecast at its centre.
"""

import math
from dataclasses import dataclass

from .geometry import MILES_PER_DEGREE

CELLS_ALONG = 24
MIN_CELL_MILES = 5.0
BAND = 1  # cells either side of the road
MAX_CELLS = 150


@dataclass(frozen=True)
class Cell:
    south: float
    west: float
    north: float
    east: float
    point: tuple  # (lat, lon) the forecast is asked for


@dataclass(frozen=True)
class Corridor:
    cell_miles: float
    cells: list


def build(lines, anchors=()):
    """A corridor covering every line, coarsened until it fits in MAX_CELLS; `anchors` are points already being forecast."""
    size = max(MIN_CELL_MILES, max(line.length for line in lines) / CELLS_ALONG)
    while True:
        cells = lattice(lines, size, anchors)
        if len(cells) <= MAX_CELLS:
            return Corridor(size, cells)
        size *= math.sqrt(len(cells) / MAX_CELLS) * 1.05


def lattice(lines, size_miles, anchors=()):
    dlat = size_miles / MILES_PER_DEGREE
    mid = sum(lat for line in lines for lat, _ in line.points) / sum(len(line.points) for line in lines)
    dlon = dlat / math.cos(math.radians(mid))
    on_road = {}
    taken = set()
    for line in lines:
        for lat, lon in line.sample(size_miles / 2):
            i, j = math.floor(lat / dlat), math.floor(lon / dlon)
            on_road.setdefault((i, j), []).append((lat, lon))
            for di in range(-BAND, BAND + 1):
                for dj in range(-BAND, BAND + 1):
                    taken.add((i + di, j + dj))
    anchored = {}
    for lat, lon in anchors:
        anchored.setdefault((math.floor(lat / dlat), math.floor(lon / dlon)), []).append((lat, lon))
    cells = []
    for i, j in sorted(taken):
        south, west, north, east = i * dlat, j * dlon, (i + 1) * dlat, (j + 1) * dlon
        centre = ((south + north) / 2, (west + east) / 2)
        inside = anchored.get((i, j)) or on_road.get((i, j))
        point = min(inside, key=lambda p: (p[0] - centre[0]) ** 2 + (p[1] - centre[1]) ** 2) if inside else centre
        cells.append(Cell(south, west, north, east, point))
    return cells
