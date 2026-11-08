import math

from django.test import SimpleTestCase

from trips import corridor
from trips.corridor import BAND, MAX_CELLS, MIN_CELL_MILES, build, lattice
from trips.geometry import MILES_PER_DEGREE, Polyline

from .test_geometry import east_west_line


class LatticeTests(SimpleTestCase):
    def test_a_straight_road_gets_a_band_of_cells_along_it(self):
        line = Polyline(east_west_line(35.0, -100.0, 100))
        cells = lattice([line], 10.0)
        rows = {round(c.south / (10.0 / MILES_PER_DEGREE)) for c in cells}
        self.assertEqual(len(rows), 2 * BAND + 1)
        # 100 miles is ten or eleven cells long, plus the band at each end.
        self.assertTrue(10 + 2 * BAND <= len(cells) / len(rows) <= 11 + 2 * BAND, len(cells))
        for cell in cells:
            self.assertAlmostEqual((cell.north - cell.south) * MILES_PER_DEGREE, 10.0)
            self.assertAlmostEqual((cell.east - cell.west) * MILES_PER_DEGREE * math.cos(math.radians(35.0)), 10.0, places=1)

    def test_cells_are_shared_between_routes_that_run_together(self):
        a = Polyline(east_west_line(35.0, -100.0, 100))
        b = Polyline(east_west_line(35.0, -100.0, 100))
        self.assertEqual(len(lattice([a, b], 10.0)), len(lattice([a], 10.0)))

    def test_cells_on_the_road_are_forecast_on_the_road_and_the_rest_at_their_centre(self):
        cells = lattice([Polyline(east_west_line(35.0, -100.0, 100))], 10.0)
        row = [c for c in cells if c.south <= 35.0 < c.north]
        beside = [c for c in cells if not (c.south <= 35.0 < c.north)]
        on_road = [c for c in row if c.point[0] == 35.0]
        # The row the road runs along, less the band cell past each end.
        self.assertEqual(len(row) - len(on_road), 2)
        for cell in on_road:
            self.assertTrue(cell.west <= cell.point[1] < cell.east)
        for cell in beside + [c for c in row if c not in on_road]:
            self.assertAlmostEqual(cell.point[0], (cell.south + cell.north) / 2)
            self.assertAlmostEqual(cell.point[1], (cell.west + cell.east) / 2)


class BuildTests(SimpleTestCase):
    def test_cell_size_follows_the_longest_route_with_a_floor(self):
        short = build([Polyline(east_west_line(35.0, -100.0, 90))])
        self.assertEqual(short.cell_miles, MIN_CELL_MILES)
        long = build([Polyline(east_west_line(35.0, -100.0, 900))])
        self.assertAlmostEqual(long.cell_miles, 30.0, delta=0.01)

    def test_coarsens_until_the_cap_fits(self):
        far_apart = [Polyline(east_west_line(lat, -100.0, 900)) for lat in (30.0, 35.0, 40.0, 45.0)]
        corridor_ = build(far_apart)
        self.assertLessEqual(len(corridor_.cells), MAX_CELLS)
        self.assertGreater(corridor_.cell_miles, 30.0)

    def test_three_routes_a_little_apart_stay_well_inside_the_cap(self):
        routes = [Polyline(east_west_line(35.0 + k * 0.5, -100.0, 2800)) for k in range(3)]
        built = build(routes)
        self.assertLessEqual(len(built.cells), MAX_CELLS)
        self.assertAlmostEqual(built.cell_miles, 2800 / corridor.CELLS_ALONG, delta=0.01)
