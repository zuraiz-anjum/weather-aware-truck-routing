from datetime import datetime, timedelta, timezone
from unittest import mock

from trips.geocoding import Place
from trips.osrm import NoRoute
from trips.planner import PlanningError, describe, plan, reason
from trips.risk import HIGH, LOW, NO_TRAVEL, SEVERE

from .support import CacheTestCase, fake_forecast, fake_route
from .test_geometry import east_west_line

ORIGIN = Place("Start, Texas", 35.0, -100.0)
DESTINATION = Place("End, Texas", 35.0, -96.5)


def three_routes():
    """A calm quick road, a windy slightly slower one, and a slow calm one, by latitude."""
    return [
        fake_route(east_west_line(35.0, -100.0, 200), 3 * 3600, roads={"I-40": 180.0, "US-83": 20.0}),
        fake_route(east_west_line(35.5, -100.0, 200), 3.2 * 3600, roads={"I-40": 120.0, "US-60": 80.0}),
        fake_route(east_west_line(34.5, -100.0, 200), 3.8 * 3600, detour=True, roads={"US-70": 200.0}),
    ]


def windy_north(lat):
    return 50.0 if lat > 35.2 else 10.0


class PlanTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        self.departure = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=2)
        self.find = mock.patch("trips.osrm.find", return_value=three_routes()).start()
        self.forecast = mock.patch("trips.weather.forecast", side_effect=fake_forecast(windy_north)).start()
        self.addCleanup(mock.patch.stopall)

    def test_routes_come_back_ranked_with_the_calm_quick_one_first(self):
        result = plan(ORIGIN, DESTINATION, self.departure, 20_000)
        routes = result["routes"]
        self.assertEqual([r["id"] for r in routes], ["A", "B", "C"])
        self.assertEqual([r["summary"]["rank"] for r in routes], [1, 2, 3])
        self.assertEqual([r["duration_seconds"] for r in routes], [3 * 3600, round(3.8 * 3600), round(3.2 * 3600)])
        self.assertTrue(routes[0]["summary"]["recommended"])
        self.assertEqual(routes[0]["summary"]["reason"], "the quickest route, and no other scores better on weather")
        self.assertIsNone(routes[1]["summary"]["reason"])
        self.assertEqual(routes[2]["summary"]["worst_level"], SEVERE)
        self.assertEqual(routes[2]["summary"]["miles_by_level"][SEVERE], routes[2]["distance_miles"])
        self.assertEqual(routes[0]["summary"]["miles_by_level"][LOW], routes[0]["distance_miles"])

    def test_a_heavy_load_turns_the_windy_road_into_no_travel(self):
        result = plan(ORIGIN, DESTINATION, self.departure, 30_001)
        windy = result["routes"][2]
        self.assertEqual(windy["summary"]["worst_level"], NO_TRAVEL)
        self.assertEqual(windy["summary"]["miles_by_level"][NO_TRAVEL], windy["distance_miles"])
        self.assertIn("30,000 lb", windy["checkpoints"][0]["load_rule"])
        self.assertIsNone(result["warning"])
        self.assertTrue(result["routes"][0]["summary"]["recommended"])

    def test_nothing_is_recommended_when_the_best_route_has_no_travel_miles(self):
        self.forecast.side_effect = fake_forecast(lambda lat: 60.0)
        result = plan(ORIGIN, DESTINATION, self.departure, 20_000)
        self.assertEqual([r["summary"]["recommended"] for r in result["routes"]], [False, False, False])
        self.assertEqual(result["routes"][0]["summary"]["rank"], 1)
        self.assertEqual(result["routes"][0]["summary"]["reason"], "the quickest route, and no other scores better on weather")
        self.assertIn("No route is clear to drive", result["warning"])
        self.assertIn("Route A is the least bad and still has 200 miles rated No Travel", result["warning"])

    def test_the_slow_calm_road_wins_when_the_quick_one_is_windy(self):
        self.forecast.side_effect = fake_forecast(lambda lat: 40.0 if lat < 35.2 and lat > 34.8 else 5.0)
        result = plan(ORIGIN, DESTINATION, self.departure, 20_000)
        self.assertEqual(result["routes"][0]["duration_seconds"], round(3.2 * 3600))
        self.assertEqual(result["routes"][0]["summary"]["reason"], "12 min slower than Route C, but fewer miles rated High")
        self.assertEqual(result["routes"][2]["summary"]["worst_level"], HIGH)
        self.assertEqual(result["routes"][2]["duration_seconds"], 3 * 3600)

    def test_checkpoints_carry_position_eta_and_the_weather_there(self):
        result = plan(ORIGIN, DESTINATION, self.departure, 20_000, interval=25)
        route = result["routes"][0]
        marks = [c["mile"] for c in route["checkpoints"]]
        self.assertEqual(marks[:3], [0.0, 25.0, 50.0])
        self.assertAlmostEqual(marks[-1], route["distance_miles"], places=1)
        third = route["checkpoints"][2]
        self.assertEqual(third["eta"], (self.departure + timedelta(seconds=third["seconds"])).isoformat())
        self.assertAlmostEqual(third["seconds"], 50 / 200 * 3 * 3600, delta=1)
        self.assertEqual(third["wind_mph"], 10.0)
        self.assertEqual((third["level"], third["wind_level"], third["rain_level"], third["snow_level"]), (LOW, LOW, LOW, LOW))
        self.assertIsNone(third["load_rule"])
        self.assertEqual(result["interval_miles"], 25)
        self.assertEqual(route["arrival"], (self.departure + timedelta(hours=3)).isoformat())

    def test_the_interval_defaults_by_length_and_is_coarsened_with_a_note(self):
        self.assertEqual(plan(ORIGIN, DESTINATION, self.departure, 20_000)["interval_miles"], 10)
        self.find.return_value = [fake_route(east_west_line(35.0, -110.0, 2800), 45 * 3600)]
        far = Place("Far, California", 35.0, -120.0)
        result = plan(ORIGIN, far, self.departure, 20_000, interval=10)
        self.assertEqual(result["interval_miles"], 50)
        self.assertIn("every 50 miles rather than 10", result["notes"][-1])
        self.assertIn("Only one distinct road route was found", result["notes"][0])

    def test_the_heatmap_has_a_level_for_every_slider_hour_of_every_cell(self):
        result = plan(ORIGIN, DESTINATION, self.departure, 20_000)
        heatmap = result["heatmap"]
        self.assertEqual(heatmap["type"], "FeatureCollection")
        self.assertGreater(len(heatmap["features"]), 100)
        for feature in heatmap["features"]:
            self.assertEqual(len(feature["properties"]["levels"]), 49)
            ring = feature["geometry"]["coordinates"][0]
            self.assertEqual(ring[0], ring[-1])
            self.assertEqual(len(ring), 5)
        north = [f for f in heatmap["features"] if f["geometry"]["coordinates"][0][0][1] > 35.3]
        self.assertTrue(north and all(f["properties"]["levels"][0] == SEVERE for f in north))

    def test_one_forecast_request_covers_checkpoints_and_cells_for_the_trip_and_the_slider(self):
        result = plan(ORIGIN, DESTINATION, self.departure, 20_000)
        (points, start, end), _ = self.forecast.call_args
        self.assertEqual(start, self.departure)
        self.assertEqual(end, self.departure + timedelta(hours=48))
        checkpoints = sum(len(r["checkpoints"]) for r in result["routes"])
        self.assertEqual(len(points), checkpoints + len(result["heatmap"]["features"]))

    def test_a_long_trip_stretches_the_forecast_window_past_the_slider(self):
        self.find.return_value = [fake_route(east_west_line(35.0, -110.0, 2800), 60 * 3600)]
        plan(ORIGIN, DESTINATION, self.departure, 20_000)
        (_, _, end), _ = self.forecast.call_args
        self.assertEqual(end, self.departure + timedelta(hours=60))

    def test_routes_are_fetched_once_for_a_pair_of_places(self):
        plan(ORIGIN, DESTINATION, self.departure, 20_000)
        plan(ORIGIN, DESTINATION, self.departure + timedelta(hours=5), 40_000)
        self.assertEqual(self.find.call_count, 1)
        plan(DESTINATION, ORIGIN, self.departure, 20_000)
        self.assertEqual(self.find.call_count, 2)

    def test_same_place_and_no_road_are_refused(self):
        with self.assertRaises(PlanningError):
            plan(ORIGIN, Place("Start again", 35.001, -100.001), self.departure, 20_000)
        self.find.side_effect = NoRoute("no road")
        with self.assertRaises(NoRoute):
            plan(ORIGIN, DESTINATION, self.departure, 20_000)

    def test_a_trip_running_past_the_forecast_is_refused(self):
        self.find.return_value = [fake_route(east_west_line(35.0, -110.0, 2800), 17 * 24 * 3600)]
        with self.assertRaises(PlanningError) as caught:
            plan(ORIGIN, DESTINATION, self.departure, 20_000)
        self.assertIn("forecast runs to", str(caught.exception))

    def test_places_and_inputs_are_echoed(self):
        result = plan(ORIGIN, DESTINATION, self.departure, 20_000)
        self.assertEqual(result["origin"], {"label": "Start, Texas", "lat": 35.0, "lon": -100.0})
        self.assertEqual(result["departure"], self.departure.isoformat())
        self.assertEqual(result["load_lb"], 20_000)
        self.assertEqual(result["slider_hours"], 48)
        self.assertEqual(result["routes"][0]["geometry"]["type"], "LineString")
        self.assertEqual(result["routes"][0]["geometry"]["coordinates"][0], [-100.0, 35.0])


class ReasonTests(CacheTestCase):
    def test_against_the_quickest_route(self):
        quickest = (0, 20, 0, 0.5, 3600)
        self.assertEqual(reason(quickest, quickest, "A"), "the quickest route, and no other scores better on weather")
        self.assertEqual(reason((0, 0, 0, 0.1, 4500), quickest, "B"), "15 min slower than Route B, but fewer miles rated Severe")
        self.assertEqual(reason((0, 20, 0, 0.2, 9000), quickest, "C"), "1.5 h slower than Route C, but a lower average risk")
        self.assertEqual(reason((0, 0, 0, 0, 3600), (50, 0, 0, 0, 3600), "A"), "0 min slower than Route A, but fewer miles rated No Travel")


class DescribeTests(CacheTestCase):
    def test_top_road_and_the_road_that_sets_a_route_apart(self):
        routes = three_routes()
        self.assertEqual(describe(routes), ["via I-40 and US-83", "via I-40 and US-60", "via US-70"])

    def test_a_road_shared_with_the_others_is_named_when_nothing_sets_the_route_apart(self):
        a = fake_route(east_west_line(35.0, -100.0, 400), 3600, roads={"I-40": 250.0, "I-75": 140.0, "SR-9": 10.0})
        b = fake_route(east_west_line(35.5, -100.0, 400), 3600, roads={"I-40": 250.0, "I-75": 140.0, "SR-11": 10.0})
        self.assertEqual(describe([a, b]), ["via I-40 and I-75", "via I-40 and I-75"])

    def test_an_interstate_is_named_before_a_longer_state_road(self):
        a = fake_route(east_west_line(35.0, -100.0, 700), 3600, roads={"I-65": 400.0, "SR-111": 60.0, "I-24": 50.0, "I-75": 190.0})
        b = fake_route(east_west_line(35.5, -100.0, 700), 3600, roads={"US-41": 500.0, "I-75": 200.0})
        self.assertEqual(describe([a, b]), ["via I-65 and I-24", "via US-41 and I-75"])

    def test_a_lone_route_names_its_two_main_roads(self):
        self.assertEqual(describe([three_routes()[1]]), ["via I-40 and US-60"])
        self.assertEqual(describe([fake_route(east_west_line(35.0, -100.0, 200), 3600, roads={"I-40": 195.0, "Elm Street": 5.0})]),
                         ["via I-40"])

    def test_a_short_detour_is_told_apart_by_a_few_miles_of_another_road(self):
        a = fake_route(east_west_line(39.7, -105.0, 68), 4800, roads={"I-25": 68.0})
        b = fake_route(east_west_line(39.9, -105.0, 86), 6660, detour=True, roads={"I-25": 60.0, "CO-83": 14.0, "CO-86": 12.0})
        self.assertEqual(describe([a, b]), ["via I-25", "via I-25 and CO-83"])

    def test_no_roads_at_all(self):
        self.assertEqual(describe([fake_route(east_west_line(35.0, -100.0, 20), 3600)]), ["via local roads"])
