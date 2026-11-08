from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

import trips.osrm
from trips.geometry import haversine_miles
from trips.osrm import METRES_PER_MILE, NoRoute, Route, RoutingError, alternatives, beside, distinct, find, road_name, via

from .support import FakeResponse, fake_route, osrm_route, osrm_step
from .test_geometry import east_west_line

# B sits north of the line from A to C so that the thinning keeps it.
A, B, C, D = (35.0, -100.0), (35.3, -99.5), (35.0, -99.0), (35.5, -99.0)


def body(*routes):
    return {"code": "Ok", "routes": list(routes)}


def miles(a, b):
    return haversine_miles(*a, *b)


def two_step_route():
    first = osrm_step([A, B], miles(A, B) * METRES_PER_MILE, 1800, name="Main Street", ref="I 40")
    second = osrm_step([B, C], miles(B, C) * METRES_PER_MILE, 1200, name="Elm Street")
    arrive = osrm_step([C, C], 0, 0, name="Elm Street")
    return osrm_route([[first, second, arrive]], (miles(A, B) + miles(B, C)) * METRES_PER_MILE * 1.01, 3000)


@override_settings(OSRM_URL="http://osrm.test")
class RequestTests(SimpleTestCase):
    def answer(self, payload, status_code=200):
        get = mock.patch.object(trips.osrm._session, "get", return_value=FakeResponse(payload, status_code)).start()
        self.addCleanup(mock.patch.stopall)
        return get

    def test_steps_are_stitched_into_one_line_with_a_clock(self):
        self.answer(body(two_step_route()))
        (route,) = alternatives(A, C)
        self.assertIsInstance(route, Route)
        self.assertEqual(route.line.points, [A, B, C])  # the shared vertex B appears once, the arrive step adds nothing
        self.assertEqual(route.seconds, [0.0, 1800.0, 3000.0])
        self.assertAlmostEqual(route.distance_miles, (miles(A, B) + miles(B, C)) * 1.01)
        self.assertAlmostEqual(route.line.length, route.distance_miles)
        self.assertEqual(route.duration_seconds, 3000.0)
        self.assertFalse(route.detour)
        self.assertEqual(set(route.roads), {"I-40", "Elm Street"})
        self.assertAlmostEqual(route.roads["I-40"], miles(A, B))

    def test_seconds_are_spread_along_a_step_by_distance(self):
        mid = (35.0, -99.75)  # a bend, so it survives the thinning
        step = osrm_step([A, mid, B], (miles(A, mid) + miles(mid, B)) * METRES_PER_MILE, 1000)
        self.answer(body(osrm_route([[step]], (miles(A, mid) + miles(mid, B)) * METRES_PER_MILE, 1000)))
        (route,) = alternatives(A, B)
        share = miles(A, mid) / (miles(A, mid) + miles(mid, B))
        self.assertEqual(route.line.points, [A, mid, B])
        self.assertAlmostEqual(route.seconds[1], 1000 * share, places=3)
        self.assertAlmostEqual(route.seconds_at(route.line.miles[1] / 2), 500 * share, places=3)

    def test_the_clock_lands_on_the_route_time_when_the_steps_do_not_add_up(self):
        route = two_step_route()
        route["duration"] = 3003.0  # the steps add up to 3000
        self.answer(body(route))
        (found,) = alternatives(A, C)
        self.assertEqual(found.seconds[-1], 3003.0)
        self.assertAlmostEqual(found.seconds[1], 1800 * 3003 / 3000)
        self.assertEqual(found.duration_seconds, 3003.0)

    def test_the_line_is_thinned_but_its_clock_stays_exact(self):
        straight = east_west_line(35.0, -100.0, 20, step_miles=0.1)
        step = osrm_step(straight, 20 * METRES_PER_MILE, 1200)
        self.answer(body(osrm_route([[step]], 20 * METRES_PER_MILE, 1200)))
        (route,) = alternatives(straight[0], straight[-1])
        self.assertEqual(len(route.line.points), 2)
        self.assertEqual(route.seconds, [0.0, 1200.0])
        self.assertAlmostEqual(route.seconds_at(5.0), 300.0, places=6)

    def test_request_shape(self):
        get = self.answer(body(two_step_route()))
        alternatives(A, C)
        args, kwargs = get.call_args
        self.assertEqual(args[0], "http://osrm.test/route/v1/driving/-100.000000,35.000000;-99.000000,35.000000")
        self.assertEqual(kwargs["params"]["alternatives"], 3)
        self.assertEqual(kwargs["params"]["steps"], "true")
        self.assertEqual(kwargs["params"]["overview"], "false")
        self.assertIn("User-Agent", kwargs["headers"])

    def test_via_goes_through_the_middle_point_and_is_marked_a_detour(self):
        get = self.answer(body(osrm_route([[osrm_step([A, D], 1000, 10)], [osrm_step([D, C], 1000, 10)]], 2000, 20)))
        route = via(A, D, C)
        self.assertTrue(route.detour)
        self.assertEqual(route.line.points, [A, D, C])
        self.assertEqual(route.seconds, [0.0, 10.0, 20.0])
        self.assertIn("-99.000000,35.500000;", get.call_args[0][0])
        self.assertEqual(get.call_args[1]["params"]["alternatives"], "false")

    def test_no_route_codes(self):
        for code in ("NoRoute", "NoSegment"):
            with self.subTest(code=code):
                self.answer({"code": code, "message": "x"}, 400)
                with self.assertRaises(NoRoute):
                    alternatives(A, C)

    def test_other_failures_are_routing_errors(self):
        cases = [
            ({"code": "InvalidQuery"}, 400),
            ({"code": "Ok", "routes": []}, 200),
            ([1, 2, 3], 200),
            (ValueError("not json"), 502),
            (requests.ConnectionError("down"), 0),
        ]
        for payload, status in cases:
            with self.subTest(payload=payload):
                if isinstance(payload, requests.RequestException):
                    mock.patch.object(trips.osrm._session, "get", side_effect=payload).start()
                    self.addCleanup(mock.patch.stopall)
                else:
                    self.answer(payload, status)
                with self.assertRaises(RoutingError) as caught:
                    alternatives(A, C)
                self.assertNotIsInstance(caught.exception, NoRoute)

    def test_a_route_with_a_missing_field_is_a_routing_error(self):
        broken = two_step_route()
        del broken["legs"][0]["steps"][0]["duration"]
        self.answer(body(broken))
        with self.assertRaises(RoutingError):
            alternatives(A, C)


class RoadNameTests(SimpleTestCase):
    def test_refs_are_hyphenated_and_the_first_of_a_pair_wins(self):
        self.assertEqual(road_name({"ref": "I 80", "name": "x"}), "I-80")
        self.assertEqual(road_name({"ref": "I 44; US 50"}), "I-44")
        self.assertEqual(road_name({"ref": "US 287"}), "US-287")
        self.assertEqual(road_name({"ref": "CA 99"}), "CA-99")
        self.assertEqual(road_name({"ref": "FM 1960"}), "FM-1960")

    def test_odd_refs_are_left_alone_and_names_are_the_fallback(self):
        self.assertEqual(road_name({"ref": "Loop 410"}), "Loop 410")
        self.assertEqual(road_name({"ref": "", "name": "Elm Street"}), "Elm Street")
        self.assertIsNone(road_name({"ref": "", "name": ""}))
        self.assertIsNone(road_name({}))


class BesideTests(SimpleTestCase):
    def test_lands_the_right_distance_off_the_midpoint(self):
        origin, destination = (35.0, -100.0), (35.0, -98.0)  # about 113 miles apart
        straight = haversine_miles(*origin, *destination)
        right = beside(origin, destination, 0.5, 1)
        left = beside(origin, destination, 0.5, -1)
        midpoint = (35.0, -99.0)
        for point in (right, left):
            self.assertAlmostEqual(haversine_miles(*midpoint, *point), 0.2 * straight, delta=0.5)
        self.assertGreater(right[0], 35.0)
        self.assertLess(left[0], 35.0)

    def test_offset_is_clamped_for_very_short_and_very_long_trips(self):
        short = beside((35.0, -100.0), (35.0, -99.9), 0.5, 1)
        self.assertAlmostEqual(haversine_miles(35.0, -99.95, *short), 8.0, delta=0.1)
        long = beside((40.0, -74.0), (34.0, -118.0), 0.5, 1)
        self.assertAlmostEqual(haversine_miles(37.0, -96.0, *long), 150.0, delta=15)

    def test_a_wider_offset_lands_further_out(self):
        origin, destination = (35.0, -100.0), (35.0, -98.0)
        straight = haversine_miles(*origin, *destination)
        wide = beside(origin, destination, 0.5, 1, offset=0.35)
        self.assertAlmostEqual(haversine_miles(35.0, -99.0, *wide), 0.35 * straight, delta=0.5)

    def test_fraction_moves_along_the_line(self):
        point = beside((35.0, -100.0), (35.0, -98.0), 0.25, 1)
        self.assertAlmostEqual(point[1], -99.5, places=2)

    def test_same_place(self):
        self.assertEqual(beside(A, A, 0.5, 1), A)


class DistinctTests(SimpleTestCase):
    def setUp(self):
        self.main = fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3)

    def test_a_route_on_the_same_road_is_not_distinct(self):
        same = fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3.2, detour=True)
        self.assertFalse(distinct(same, [self.main]))

    def test_a_route_on_another_road_is(self):
        other = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.5, detour=True)
        self.assertTrue(distinct(other, [self.main]))

    def test_but_not_when_it_is_far_slower(self):
        slow = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3 * 1.51, detour=True)
        self.assertFalse(distinct(slow, [self.main]))
        self.assertTrue(distinct(fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3 * 1.49, detour=True), [self.main]))

    def test_sharing_the_ends_is_fine(self):
        shared = east_west_line(35.0, -100.0, 200)
        middle = east_west_line(35.4, shared[40][1], 120)
        bend = shared[:40] + middle + shared[160:]
        self.assertTrue(distinct(fake_route(bend, 3600 * 3.3, detour=True), [self.main]))


class FindTests(SimpleTestCase):
    def setUp(self):
        self.offered = [fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3)]
        self.sides = {}
        mock.patch("trips.osrm.alternatives", side_effect=lambda o, d: list(self.offered)).start()
        mock.patch("trips.osrm.via", side_effect=self.side).start()
        self.addCleanup(mock.patch.stopall)

    def side(self, origin, through, destination):
        answer = self.sides.get(round(through[0], 2))
        if answer is None:
            raise RoutingError("nothing there")
        return answer

    def test_offered_routes_are_topped_up_from_side_points(self):
        north = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        south = fake_route(east_west_line(34.6, -100.0, 200), 3600 * 3.2, detour=True)
        self.sides = {round(north.line.points[0][0], 2): north, round(south.line.points[0][0], 2): south}
        with mock.patch("trips.osrm.beside", side_effect=lambda o, d, f, s, offset: (35.0 + 0.4 * s, -99.0)):
            routes = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual([r.duration_seconds for r in routes], [3600 * 3, 3600 * 3.2, 3600 * 3.4])
        self.assertEqual([r.detour for r in routes], [False, True, True])

    def test_every_round_is_tried_before_giving_up(self):
        same = fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3.1, detour=True)
        self.sides = {35.4: same}
        spots = []
        with mock.patch("trips.osrm.beside", side_effect=lambda o, d, f, s, offset: spots.append((f, s, offset)) or (35.0 + 0.4 * s, -99.0)):
            routes = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(routes), 1)
        self.assertEqual(sorted(set(spots)), sorted({(0.5, 1, 0.2), (0.5, -1, 0.2), (0.33, 1, 0.2), (0.33, -1, 0.2),
                                                     (0.67, 1, 0.2), (0.67, -1, 0.2), (0.5, 1, 0.35), (0.5, -1, 0.35)}))

    def test_a_later_round_stops_once_three_are_in_hand(self):
        north = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        south = fake_route(east_west_line(34.6, -100.0, 200), 3600 * 3.2, detour=True)
        self.sides = {35.4: north, 34.6: south}
        with mock.patch("trips.osrm.beside", side_effect=lambda o, d, f, s, offset: (35.0 + 0.4 * s, -99.0)), \
                mock.patch("trips.osrm.via", wraps=self.side) as via_:
            find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(via_.call_count, 2)

    def test_three_offered_routes_need_no_side_points(self):
        self.offered = [fake_route(east_west_line(35.0 + k * 0.3, -100.0, 200), 3600 * (3 + k)) for k in range(3)]
        with mock.patch("trips.osrm.via", side_effect=RoutingError("unused")) as via_:
            routes = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(routes), 3)
        self.assertEqual(via_.call_count, 2)  # the first pair goes out regardless; the second does not

    def test_no_route_from_the_main_request_propagates(self):
        mock.patch("trips.osrm.alternatives", side_effect=NoRoute("none")).start()
        with self.assertRaises(NoRoute):
            find((35.0, -100.0), (35.0, -96.5))
