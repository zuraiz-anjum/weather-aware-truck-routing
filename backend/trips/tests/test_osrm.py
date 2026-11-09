from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

import trips.osrm
from trips.geometry import MILES_PER_DEGREE, haversine_miles, interpolate
from trips.osrm import (
    METRES_PER_MILE, NoRoute, Route, RoutingError, Run, alternatives, beside, bridging, distinct, find, goes_somewhere,
    highway, road_name, via,
)

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
        (stretch,) = route.minor  # Elm Street has no route number; the arrive step has no length
        self.assertAlmostEqual(stretch[0], miles(A, B))
        self.assertAlmostEqual(stretch[1], miles(A, B) + miles(B, C))
        self.assertEqual(stretch[2], "Elm Street")
        self.assertAlmostEqual(route.minor_miles, miles(B, C))

    def test_minor_stretches_are_merged_by_road_and_measured_between_miles(self):
        steps = [
            osrm_step([A, B], miles(A, B) * METRES_PER_MILE, 600, name="Elm Street"),
            osrm_step([B, C], miles(B, C) * METRES_PER_MILE, 600, name="Elm Street"),
            osrm_step([C, D], miles(C, D) * METRES_PER_MILE, 600, name="Oak Street"),
        ]
        total = miles(A, B) + miles(B, C) + miles(C, D)
        self.answer(body(osrm_route([steps], total * METRES_PER_MILE, 1800)))
        (route,) = alternatives(A, D)
        self.assertEqual([name for _, _, name in route.minor], ["Elm Street", "Oak Street"])
        self.assertAlmostEqual(route.minor_miles, total)
        self.assertAlmostEqual(route.minor_between(0.0, miles(A, B)), miles(A, B))
        self.assertAlmostEqual(route.minor_between(total - 1.0, total + 50.0), 1.0)
        self.assertEqual(route.minor_roads(limit=1), ["Elm Street" if miles(A, B) + miles(B, C) > miles(C, D) else "Oak Street"])

    def test_seconds_are_spread_along_a_step_by_distance(self):
        mid = (35.0, -99.75)  # a bend, so it survives the thinning
        step = osrm_step([A, mid, B], (miles(A, mid) + miles(mid, B)) * METRES_PER_MILE, 1000)
        self.answer(body(osrm_route([[step]], (miles(A, mid) + miles(mid, B)) * METRES_PER_MILE, 1000)))
        (route,) = alternatives(A, B)
        share = miles(A, mid) / (miles(A, mid) + miles(mid, B))
        self.assertEqual(route.line.points, [A, mid, B])
        self.assertAlmostEqual(route.seconds[1], 1000 * share, places=3)
        self.assertAlmostEqual(interpolate(route.line.miles, route.seconds, route.line.miles[1] / 2), 500 * share, places=3)

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
        self.assertAlmostEqual(interpolate(route.line.miles, route.seconds, 5.0), 300.0, places=6)

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

    def test_which_roads_count_as_highways(self):
        for step in ({"ref": "I 40"}, {"ref": "US 54; NM 2"}, {"ref": "FM 1960"},
                     {"name": "US Highway 54 South"}, {"name": "North Sacramento Freeway"},
                     {"name": "Homestead Extension of Florida's Turnpike"}, {"name": "Old Hwy 99"}, {"name": "Express Toll Lanes"}):
            self.assertTrue(highway(step), step)
        for step in ({"ref": "NF 15"}, {"ref": "CR 1", "name": "County Road 1"}, {"ref": "CR 61", "name": "Mill Road"}, {"ref": "FR 077", "name": "National Forest Development Road 077"},
                     {"name": "Saw Mill River Parkway"}, {"name": "Camp Creek Road"}, {"name": "Highwayman Lane"}, {}):
            self.assertFalse(highway(step), step)


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
        slow = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3 * 1.61, detour=True)
        self.assertFalse(distinct(slow, [self.main]))
        self.assertTrue(distinct(fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3 * 1.59, detour=True), [self.main]))

    def test_sharing_the_ends_is_fine(self):
        shared = east_west_line(35.0, -100.0, 200)
        middle = east_west_line(35.4, shared[40][1], 120)
        bend = shared[:40] + middle + shared[160:]
        self.assertTrue(distinct(fake_route(bend, 3600 * 3.3, detour=True), [self.main]))


def with_loop(points, at_index, miles_out):
    """The same line with an out-and-back excursion to the north at one vertex: a spur, not a route."""
    lat, lon = points[at_index]
    step = miles_out / MILES_PER_DEGREE / 4
    out = [(lat + k * step, lon) for k in range(1, 5)]
    return points[: at_index + 1] + out + out[-2::-1] + points[at_index:]


class BridgingTests(SimpleTestCase):
    def setUp(self):
        self.main = fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3)

    def test_a_road_of_its_own_bridges_the_whole_way(self):
        other = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        run = bridging(other, [self.main])
        self.assertIsNotNone(run)
        self.assertAlmostEqual(run.length, 200, delta=4)
        self.assertAlmostEqual(run.gap, 200, delta=4)
        self.assertAlmostEqual(run.middle[0], 35.4)
        self.assertTrue(goes_somewhere(run))

    def test_a_stretch_between_two_shared_ends_bridges_too(self):
        shared = east_west_line(35.0, -100.0, 200)
        middle = east_west_line(35.3, shared[50][1], 100)
        bend = shared[:50] + middle + shared[150:]
        run = bridging(fake_route(bend, 3600 * 3.3, detour=True), [self.main])
        self.assertIsNotNone(run)
        self.assertAlmostEqual(run.gap, 100, delta=6)
        self.assertAlmostEqual(run.middle[0], 35.3)
        self.assertTrue(goes_somewhere(run))

    def test_the_minor_miles_of_the_new_road_are_counted(self):
        forest = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True, minor=[(50.0, 150.0, "Forest Road")])
        run = bridging(forest, [self.main])
        self.assertAlmostEqual(run.minor, 100, delta=2)
        self.assertEqual(bridging(fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True), [self.main]).minor, 0.0)

    def test_an_out_and_back_excursion_is_a_spur(self):
        # The excursion is a stretch of new road, so it is found and could be
        # routed through again; it goes nowhere, so it is not a road of its own.
        spur = fake_route(with_loop(east_west_line(35.0, -100.0, 200), 100, 12.0), 3600 * 3.3, detour=True)
        run = bridging(spur, [self.main])
        self.assertAlmostEqual(run.length, 24, delta=4)
        self.assertLess(run.gap, 2)
        self.assertFalse(goes_somewhere(run))

    def test_a_road_may_bow_but_not_double_back(self):
        straight = Run(100, 100, (0, 0), 0)
        bowed = Run(100, 52, (0, 0), 0)  # Jackson to Idaho Falls by ID-33 measures 0.52
        loop = Run(50, 20, (0, 0), 0)  # a farm-road loop off I-27 measures 0.39
        forest = Run(100, 100, (0, 0), 51)
        self.assertEqual([goes_somewhere(r) for r in (straight, bowed, loop, forest)], [True, True, False, False])

    def test_a_nick_too_short_to_count_and_the_same_road_are_nothing(self):
        nick = fake_route(with_loop(east_west_line(35.0, -100.0, 200), 100, 3.0), 3600 * 3.1, detour=True)
        self.assertIsNone(bridging(nick, [self.main]))
        self.assertIsNone(bridging(fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3.1), [self.main]))


class FindTests(SimpleTestCase):
    def setUp(self):
        self.offered = [fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3)]
        self.sides = {}
        mock.patch("trips.osrm.alternatives", side_effect=lambda o, d: list(self.offered)).start()
        mock.patch("trips.osrm.via", side_effect=self.side).start()
        # Side points land 0.4 degrees north or south of the line, at -99.
        mock.patch("trips.osrm.beside", side_effect=lambda o, d, f, s, offset: (35.0 + 0.4 * s, -99.0)).start()
        self.addCleanup(mock.patch.stopall)

    def side(self, origin, through, destination):
        """What routing through a point gives, by the point's latitude to two places."""
        answer = self.sides.get(round(through[0], 2))
        if answer is None:
            raise RoutingError("nothing there")
        return answer

    def test_offered_routes_are_topped_up_from_side_points(self):
        north = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        south = fake_route(east_west_line(34.6, -100.0, 200), 3600 * 3.2, detour=True)
        self.sides = {35.4: north, 34.6: south}
        found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual([r.duration_seconds for r in found.routes], [3600 * 3, 3600 * 3.2, 3600 * 3.4])
        self.assertEqual([r.detour for r in found.routes], [False, True, True])
        self.assertEqual(found.missed, 0)

    def test_a_promising_candidate_is_routed_again_through_its_own_new_road(self):
        # The side point at 35.4 gives a slow route that runs along 35.3 with
        # an excursion; routing through a point on 35.3 gives the clean road.
        wiggly = fake_route(with_loop(east_west_line(35.3, -100.0, 200), 100, 10.0), 3600 * 4.5, detour=True)
        clean = fake_route(east_west_line(35.3, -100.0, 200), 3600 * 3.3, detour=True)
        self.sides = {35.4: wiggly, 35.3: clean}
        with self.assertLogs("trips.osrm", "INFO"):  # the southern side point has nothing
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertIn(clean, found.routes)
        self.assertNotIn(wiggly, found.routes)

    def test_spurs_are_refused_whatever_their_time(self):
        spur = fake_route(with_loop(east_west_line(35.0, -100.0, 200), 100, 12.0), 3600 * 3.2, detour=True)
        self.sides = {35.4: spur, 34.6: spur}
        with self.assertLogs("trips.osrm", "INFO"):  # routing again through the top of the loop finds nothing here
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(found.routes), 1)

    def test_a_new_road_mostly_on_minor_roads_is_refused(self):
        forest = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.2, detour=True, minor=[(20.0, 180.0, "Forest Road")])
        county = fake_route(east_west_line(34.6, -100.0, 200), 3600 * 3.4, detour=True, minor=[(20.0, 60.0, "County Road 12")])
        self.sides = {35.4: forest, 34.6: county}
        found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(found.routes, [self.offered[0], county])
        self.assertEqual(found.missed, 0)

    def test_a_candidate_is_routed_again_only_when_it_is_reached(self):
        self.offered.append(fake_route(east_west_line(35.8, -100.0, 200), 3600 * 3.1))
        north = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        south = fake_route(east_west_line(34.6, -100.0, 200), 3600 * 3.2, detour=True)
        self.sides = {35.4: north, 34.6: south}
        with mock.patch("trips.osrm.via", wraps=self.side) as via_:
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(found.routes), 3)
        self.assertNotIn(north, found.routes)
        self.assertEqual(via_.call_count, 3)  # the first pair, then the quicker one again through its own road

    def test_a_failed_request_is_not_held_against_a_full_set(self):
        north = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        south = fake_route(east_west_line(34.6, -100.0, 200), 3600 * 3.2, detour=True)
        self.sides = {35.4: north, 34.6: south}

        def via_(origin, through, destination):
            if through[1] != -99.0:  # not a side point, so the routing again through the road itself
                raise RoutingError("busy")
            return self.side(origin, through, destination)

        with mock.patch("trips.osrm.via", side_effect=via_), self.assertLogs("trips.osrm", "INFO") as logged:
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(found.routes), 3)
        self.assertEqual(found.missed, 0)
        self.assertEqual(len(logged.output), 2)

        self.sides = {35.4: north}
        with mock.patch("trips.osrm.via", side_effect=via_), mock.patch.object(trips.osrm, "DETOUR_ROUNDS", trips.osrm.DETOUR_ROUNDS[:1]), \
                self.assertLogs("trips.osrm", "INFO"):
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(found.routes), 2)
        self.assertEqual(found.missed, 2)  # the southern side point and the northern road routed again

    def test_every_round_is_tried_before_giving_up_and_failures_are_counted(self):
        same = fake_route(east_west_line(35.0, -100.0, 200), 3600 * 3.1, detour=True)
        self.sides = {35.4: same}
        spots = []
        with mock.patch("trips.osrm.beside", side_effect=lambda o, d, f, s, offset: spots.append((f, s, offset)) or (35.0 + 0.4 * s, -99.0)), \
                self.assertLogs("trips.osrm", "INFO"):
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(found.routes), 1)
        self.assertEqual(found.missed, 4)  # the southern point failed in every round
        self.assertEqual(sorted(set(spots)), sorted({(0.5, 1, 0.2), (0.5, -1, 0.2), (0.33, 1, 0.2), (0.33, -1, 0.2),
                                                     (0.67, 1, 0.2), (0.67, -1, 0.2), (0.5, 1, 0.35), (0.5, -1, 0.35)}))

    def test_a_side_point_with_no_road_is_not_a_failure(self):
        north = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        self.sides = {35.4: north}
        with mock.patch("trips.osrm.via", side_effect=lambda o, t, d: self.side(o, t, d) if t[0] > 35 else (_ for _ in ()).throw(NoRoute("sea"))):
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(found.routes), 2)
        self.assertEqual(found.missed, 0)

    def test_a_later_round_stops_once_three_are_in_hand(self):
        north = fake_route(east_west_line(35.4, -100.0, 200), 3600 * 3.4, detour=True)
        south = fake_route(east_west_line(34.6, -100.0, 200), 3600 * 3.2, detour=True)
        self.sides = {35.4: north, 34.6: south}
        with mock.patch("trips.osrm.via", wraps=self.side) as via_:
            find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(via_.call_count, 4)  # two side points, each routed again through its own road

    def test_three_offered_routes_need_no_side_points(self):
        self.offered = [fake_route(east_west_line(35.0 + k * 0.3, -100.0, 200), 3600 * (3 + k)) for k in range(3)]
        with mock.patch("trips.osrm.via", side_effect=RoutingError("unused")) as via_, self.assertLogs("trips.osrm", "INFO"):
            found = find((35.0, -100.0), (35.0, -96.5))
        self.assertEqual(len(found.routes), 3)
        self.assertEqual(via_.call_count, 2)  # the first pair goes out regardless; the second does not

    def test_no_route_from_the_main_request_propagates(self):
        mock.patch("trips.osrm.alternatives", side_effect=NoRoute("none")).start()
        with self.assertRaises(NoRoute):
            find((35.0, -100.0), (35.0, -96.5))
