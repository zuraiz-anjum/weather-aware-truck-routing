from django.test import SimpleTestCase

from trips.geometry import MILES_PER_DEGREE, Polyline, haversine_miles, interpolate, shared_fraction, simplify

NEW_YORK = (40.7128, -74.0060)
LOS_ANGELES = (34.0522, -118.2437)


def east_west_line(lat, lon_start, miles, step_miles=1.0):
    """Points along a parallel, step_miles apart, miles long."""
    import math

    per_mile = 1 / (MILES_PER_DEGREE * math.cos(math.radians(lat)))
    count = int(miles / step_miles)
    return [(lat, lon_start + k * step_miles * per_mile) for k in range(count + 1)]


class HaversineTests(SimpleTestCase):
    def test_new_york_to_los_angeles(self):
        self.assertAlmostEqual(haversine_miles(*NEW_YORK, *LOS_ANGELES), 2445, delta=5)

    def test_zero_for_the_same_point(self):
        self.assertEqual(haversine_miles(10, 20, 10, 20), 0.0)

    def test_one_degree_of_latitude(self):
        self.assertAlmostEqual(haversine_miles(0, 0, 1, 0), MILES_PER_DEGREE, places=6)


class InterpolateTests(SimpleTestCase):
    def test_between_held_flat_outside_and_exact_on_a_vertex(self):
        xs, ys = [0, 10, 30], [0, 100, 300]
        self.assertEqual(interpolate(xs, ys, 5), 50)
        self.assertEqual(interpolate(xs, ys, 20), 200)
        self.assertEqual(interpolate(xs, ys, 10), 100)
        self.assertEqual(interpolate(xs, ys, -5), 0)
        self.assertEqual(interpolate(xs, ys, 99), 300)

    def test_repeated_x_does_not_divide_by_zero(self):
        self.assertEqual(interpolate([0, 5, 5, 10], [0, 1, 2, 3], 5), 2)


class PolylineTests(SimpleTestCase):
    def test_mileage_accumulates_along_the_vertices(self):
        line = Polyline(east_west_line(35.0, -100.0, 10))
        self.assertEqual(len(line.miles), 11)
        self.assertAlmostEqual(line.length, 10.0, places=6)
        self.assertAlmostEqual(line.miles[3], 3.0, places=6)

    def test_a_reported_length_scales_the_mileage(self):
        line = Polyline(east_west_line(35.0, -100.0, 10), length=12.0)
        self.assertAlmostEqual(line.length, 12.0)
        self.assertAlmostEqual(line.miles[5], 6.0)

    def test_position_interpolates_between_vertices_and_clamps(self):
        line = Polyline([(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)])
        lat, lon = line.position(line.miles[1] / 2)
        self.assertAlmostEqual(lat, 0.0)
        self.assertAlmostEqual(lon, 0.5)
        self.assertEqual(line.position(-1), (0.0, 0.0))
        self.assertEqual(line.position(1e9), (1.0, 1.0))
        self.assertEqual(line.position(line.miles[1]), (0.0, 1.0))

    def test_markers_end_with_the_destination(self):
        line = Polyline(east_west_line(35.0, -100.0, 10), length=23.0)
        self.assertEqual(line.markers(10), [0, 10, 20, 23.0])
        self.assertEqual(Polyline(east_west_line(35.0, -100.0, 10), length=20.0).markers(10), [0, 10, 20])
        self.assertEqual(len(line.sample(10)), 4)

    def test_needs_two_points(self):
        with self.assertRaises(ValueError):
            Polyline([(1.0, 2.0)])


class SimplifyTests(SimpleTestCase):
    def test_drops_points_on_a_straight_line_and_keeps_a_corner(self):
        east = east_west_line(35.0, -100.0, 10)
        corner_lon = east[-1][1]
        points = east + [(35.0 + k * 0.01, corner_lon) for k in range(1, 6)]
        kept = simplify(points, 0.05)
        self.assertEqual(kept, [points[0], east[-1], points[-1]])

    def test_keeps_a_bend_wider_than_the_tolerance(self):
        # The middle point sits 0.02 degrees, about 1.4 miles, off the straight line.
        points = [(0.0, 0.0), (0.0, 0.5), (0.02, 1.0), (0.0, 1.5), (0.0, 2.0)]
        self.assertEqual(len(simplify(points, 1.0)), 3)
        self.assertEqual(len(simplify(points, 0.5)), 5)
        self.assertEqual(len(simplify(points, 5.0)), 2)

    def test_short_lines_are_untouched(self):
        self.assertEqual(simplify([(1.0, 1.0), (2.0, 2.0)], 1.0), [(1.0, 1.0), (2.0, 2.0)])


class SharedFractionTests(SimpleTestCase):
    def test_a_line_shares_everything_with_itself_and_nothing_with_a_distant_one(self):
        a = east_west_line(35.0, -100.0, 50)
        b = east_west_line(36.0, -100.0, 50)
        self.assertEqual(shared_fraction(a, a, 1.0), 1.0)
        self.assertEqual(shared_fraction(a, b, 1.0), 0.0)

    def test_half_overlapping_lines_share_about_half(self):
        a = east_west_line(35.0, -100.0, 100)
        b = east_west_line(35.0, -100.0, 50) + east_west_line(35.3, -99.0, 50)[1:]
        self.assertAlmostEqual(shared_fraction(a, b, 1.0), 0.5, delta=0.03)

    def test_empty_input(self):
        self.assertEqual(shared_fraction([], [(1.0, 1.0)], 1.0), 0.0)
