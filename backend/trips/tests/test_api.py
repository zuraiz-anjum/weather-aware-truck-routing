from datetime import datetime, timedelta, timezone
from unittest import mock

from trips.geocoding import GeocodingError, Place, PlaceNotFound
from trips.osrm import NoRoute, RoutingError
from trips.views import PlanThrottle
from trips.weather import WeatherBusy, WeatherError

from .support import CacheTestCase, fake_forecast, fake_route
from .test_geometry import east_west_line


def soon(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0)


class PlanViewTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        self.routes = [fake_route(east_west_line(35.0 + k * 0.4, -100.0, 200), (3 + k) * 3600) for k in range(3)]
        mock.patch("trips.osrm.find", return_value=self.routes).start()
        mock.patch("trips.weather.forecast", side_effect=fake_forecast()).start()
        self.locate = mock.patch("trips.geocoding.locate", side_effect=self.lookup).start()
        self.addCleanup(mock.patch.stopall)

    def lookup(self, text):
        places = {"start": Place("Start, Texas", 35.0, -100.0), "end": Place("End, Texas", 35.0, -96.5)}
        if text not in places:
            raise PlaceNotFound(f"no place called {text!r}")
        return places[text]

    def body(self, **changes):
        data = {
            "origin": {"text": "start"},
            "destination": {"text": "End, Texas", "lat": 35.0, "lon": -96.5},
            "departure": soon().isoformat(),
            "load_lb": 20000,
        }
        data.update(changes)
        return data

    def post(self, **changes):
        return self.client.post("/api/plan/", self.body(**changes), content_type="application/json")

    def test_a_plan_comes_back_with_routes_heatmap_and_echoed_inputs(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.content)
        plan = response.json()
        self.assertEqual(len(plan["routes"]), 3)
        self.assertEqual(plan["routes"][0]["id"], "A")
        self.assertTrue(plan["routes"][0]["summary"]["recommended"])
        self.assertEqual(plan["origin"]["label"], "Start, Texas")
        self.assertEqual(plan["destination"], {"label": "End, Texas", "lat": 35.0, "lon": -96.5})
        self.assertEqual(plan["load_lb"], 20000)
        self.assertIsNone(plan["warning"])
        self.assertEqual(plan["heatmap"]["type"], "FeatureCollection")
        self.locate.assert_called_once_with("start")

    def test_coordinates_without_text_get_a_label_of_their_own(self):
        response = self.post(origin={"lat": 35.0, "lon": -100.0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["origin"]["label"], "35.0000, -100.0000")
        self.locate.assert_not_called()

    def test_the_interval_is_passed_through(self):
        self.assertEqual(self.post(interval_miles=50).json()["interval_miles"], 50)

    def test_validation_errors_are_flattened_into_detail(self):
        cases = [
            ({"load_lb": None}, "load_lb: This field may not be null."),
            ({"load_lb": 250000}, "load_lb: Ensure this value is less than or equal to 200000."),
            ({"interval_miles": 15}, 'interval_miles: "15" is not a valid choice.'),
            ({"departure": soon(-3).isoformat()}, "departure: the departure is in the past"),
            ({"departure": (soon() + timedelta(days=14)).isoformat()}, "departure: the departure is more than 13 days away"),
            ({"origin": {"lat": 35.0}}, "origin: give both lat and lon, or neither"),
            ({"origin": {"text": "  "}}, "origin: give a place name or coordinates"),
            ({"departure": "yesterday"}, "departure: Datetime has wrong format"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                response = self.post(**changes)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()["detail"])
                self.assertIn("errors", response.json())

    def test_missing_fields(self):
        response = self.client.post("/api/plan/", {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        for field in ("origin", "destination", "departure", "load_lb"):
            self.assertIn(f"{field}: This field is required.", detail)

    def test_unplannable_trips_are_422(self):
        self.assertEqual(self.post(origin={"text": "nowhere"}).status_code, 422)
        self.assertIn("nowhere", self.post(origin={"text": "nowhere"}).json()["detail"])
        with mock.patch("trips.osrm.find", side_effect=NoRoute("no road route between those places")):
            response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "no road route between those places"})
        response = self.post(destination={"lat": 35.001, "lon": -100.0})
        self.assertEqual(response.status_code, 422)
        self.assertIn("same place", response.json()["detail"])

    def test_upstream_failures_are_502(self):
        for target, error in (
            ("trips.osrm.find", RoutingError("the routing service could not be reached")),
            ("trips.weather.forecast", WeatherError("the weather service could not be reached")),
            ("trips.geocoding.locate", GeocodingError("the place search could not be reached")),
        ):
            with self.subTest(target=target), mock.patch(target, side_effect=error):
                response = self.post()
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json(), {"detail": str(error)})

    def test_a_busy_weather_service_is_503_with_a_retry_hint(self):
        with mock.patch("trips.weather.forecast", side_effect=WeatherBusy("try again in a minute")):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "60")
        self.assertEqual(response.json(), {"detail": "try again in a minute"})

    def test_get_is_not_allowed_but_renders_in_a_browser(self):
        response = self.client.get("/api/plan/", HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 405)
        self.assertIn(b"Method", response.content)

    def test_throttled_after_the_limit(self):
        with mock.patch.object(PlanThrottle, "THROTTLE_RATES", {"plan": "2/min"}):
            codes = [self.post().status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


class PlacesViewTests(CacheTestCase):
    def test_suggestions(self):
        with mock.patch("trips.geocoding.suggest", return_value=[Place("Denver, Colorado", 39.74, -104.98)]) as suggest:
            response = self.client.get("/api/places/", {"q": "denv"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"places": [{"label": "Denver, Colorado", "lat": 39.74, "lon": -104.98}]})
        suggest.assert_called_once_with("denv")

    def test_nothing_asked_nothing_found(self):
        with mock.patch("trips.geocoding._session.get") as get:
            response = self.client.get("/api/places/")
        self.assertEqual(response.json(), {"places": []})
        get.assert_not_called()

    def test_photon_down_is_502(self):
        with mock.patch("trips.geocoding.suggest", side_effect=GeocodingError("the place search could not be reached")):
            self.assertEqual(self.client.get("/api/places/", {"q": "denver"}).status_code, 502)


class HealthTests(CacheTestCase):
    def test_ok_in_json_and_in_a_browser(self):
        self.assertEqual(self.client.get("/api/health/").json(), {"status": "ok"})
        page = self.client.get("/api/health/", HTTP_ACCEPT="text/html")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"<title>Health", page.content)
        self.assertIn(b"&quot;status&quot;: &quot;ok&quot;", page.content)
