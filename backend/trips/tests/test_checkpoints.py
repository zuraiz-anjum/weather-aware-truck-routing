from django.test import SimpleTestCase

from trips.checkpoints import MAX_PER_ROUTE, choose_interval, default_interval, place
from trips.geometry import Polyline

from .test_geometry import east_west_line


def steady_route(miles, mph=60.0, length=None):
    """A straight road driven at a constant speed: the line and the seconds at each vertex."""
    line = Polyline(east_west_line(35.0, -100.0, miles), length)
    return line, [m / mph * 3600 for m in line.miles]


class PlaceTests(SimpleTestCase):
    def test_markers_every_interval_then_the_destination(self):
        line, seconds = steady_route(100, length=112.0)
        points = place(line, seconds, 25)
        self.assertEqual([round(c.mile, 3) for c in points], [0, 25, 50, 75, 100, 112])
        self.assertEqual([round(c.covers_miles, 3) for c in points], [25, 25, 25, 25, 12, 0])
        self.assertAlmostEqual(points[2].seconds, 50 / 60 * 3600)
        self.assertEqual((points[0].lat, points[0].lon), line.points[0])
        self.assertEqual((points[-1].lat, points[-1].lon), line.points[-1])

    def test_a_marker_just_short_of_the_destination_is_dropped(self):
        line, seconds = steady_route(100, length=100.4)
        self.assertEqual([round(c.mile, 1) for c in place(line, seconds, 25)], [0, 25, 50, 75, 100.4])

    def test_a_trip_shorter_than_the_interval_keeps_both_ends(self):
        line, seconds = steady_route(1, length=0.6)
        self.assertEqual([c.mile for c in place(line, seconds, 10)], [0, 0.6])

    def test_positions_follow_the_road(self):
        line, seconds = steady_route(100)
        points = place(line, seconds, 50)
        lat, lon = line.position(50)
        self.assertAlmostEqual(points[1].lat, lat)
        self.assertAlmostEqual(points[1].lon, lon)


class IntervalTests(SimpleTestCase):
    def test_requested_interval_stands_when_the_route_is_short_enough(self):
        self.assertEqual(choose_interval(10, 800), 10)
        self.assertEqual(choose_interval(25, 800), 25)

    def test_coarsened_for_very_long_routes(self):
        self.assertEqual(choose_interval(10, 10 * MAX_PER_ROUTE + 1), 25)
        self.assertEqual(choose_interval(10, 2800), 50)
        self.assertEqual(choose_interval(25, 2400), 25)
        self.assertEqual(choose_interval(25, 25 * MAX_PER_ROUTE + 1), 50)
        self.assertEqual(choose_interval(50, 10_000), 50)

    def test_default_by_length(self):
        self.assertEqual(default_interval(120), 10)
        self.assertEqual(default_interval(600), 25)
        self.assertEqual(default_interval(2800), 50)
