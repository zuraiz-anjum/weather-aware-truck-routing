import logging
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.conf import settings
from django.test import override_settings

from trips.geocoding import GeocodingError, Place, PlaceNotFound
from trips.osrm import Found, NoRoute, RoutingError
from trips.views import PlanThrottle
from trips.weather import WeatherError

from .support import CacheTestCase, fake_forecast, fake_route
from .test_geometry import east_west_line
from .test_planner import fetched_by_browser, spent


def soon(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0)


# The bad requests and failing services these tests arrange on purpose are
# not worth a log line each in the test output.
QUIET = (("django.request", logging.CRITICAL), ("trips.views", logging.ERROR), ("trips.planner", logging.WARNING))
_levels = {}


def setUpModule():
    for name, level in QUIET:
        _levels[name] = logging.getLogger(name).level
        logging.getLogger(name).setLevel(level)


def tearDownModule():
    for name, level in _levels.items():
        logging.getLogger(name).setLevel(level)


class PlanViewTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        self.routes = [fake_route(east_west_line(35.0 + k * 0.4, -100.0, 200), (3 + k) * 3600) for k in range(3)]
        mock.patch("trips.osrm.find", return_value=Found(self.routes, 0)).start()
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
            ({"load_lb": None}, "load_lb: This field may not be null"),
            ({"load_lb": 250000}, "load_lb: Ensure this value is less than or equal to 200000"),
            ({"interval_miles": 15}, 'interval_miles: "15" is not a valid choice'),
            ({"departure": soon(-3).isoformat()}, "the departure is in the past"),
            ({"departure": (soon() + timedelta(days=13)).isoformat()}, "the departure is too far ahead; the latest is "),
            ({"origin": {"lat": 35.0}}, "origin: give both lat and lon, or neither"),
            ({"origin": {"lat": 48.85, "lon": 2.35}}, "origin: coordinates are outside North America"),
            ({"origin": {"text": "  "}}, "origin: give a place name or coordinates"),
            ({"departure": "yesterday"}, "departure: Datetime has wrong format"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes):
                response = self.post(**changes)
                self.assertEqual(response.status_code, 400)
                self.assertIn(message, response.json()["detail"])
                self.assertNotIn("departure: the departure", response.json()["detail"])
                self.assertIn("errors", response.json())

    def test_missing_fields(self):
        response = self.client.post("/api/plan/", {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        for field in ("origin", "destination", "departure", "load_lb"):
            self.assertIn(f"{field}: This field is required", detail)
        self.assertNotIn(".;", detail)  # the framework's full stops do not run into the semicolons

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
        with mock.patch("trips.weather.forecast", side_effect=spent("minutely")):
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "60")
        # The minute is waited out by the page; nothing is asked of the browser.
        self.assertEqual(response.json(), {"detail": "the weather service's free allowance for the minute is spent; try again in a minute"})

    @override_settings(OPEN_METEO_PUBLIC_URL="http://public.meteo.test", OPEN_METEO_API_KEY="secret")
    def test_a_spent_hour_or_day_is_503_with_what_the_browser_needs_to_fetch_the_forecast_itself(self):
        for allowance, span in (("daily", "the day"), ("hourly", "the hour")):
            with self.subTest(allowance=allowance), mock.patch("trips.weather.forecast", side_effect=spent(allowance)) as forecast:
                response = self.post()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response["Retry-After"], str(forecast.side_effect.retry_after))
                body = response.json()
                self.assertIn("free allowance for %s is spent" % span, body["detail"])
                offer = body["forecast"]
                (points, start, end), _ = forecast.call_args
                self.assertEqual(offer["url"], "http://public.meteo.test/v1/forecast")
                self.assertEqual(offer["points"], [[lat, lon] for lat, lon in points])
                self.assertTrue(all(round(c, 4) == c for p in offer["points"] for c in p))
                self.assertEqual(offer["params"]["hourly"], "wind_speed_10m,rain,showers,snowfall")
                self.assertEqual(offer["params"]["timeformat"], "unixtime")
                self.assertEqual(offer["params"]["start_hour"], soon().strftime("%Y-%m-%dT00:00"))
                self.assertGreater(offer["params"]["end_hour"], offer["params"]["start_hour"])
                for key in ("apikey", "latitude", "longitude"):
                    self.assertNotIn(key, offer["params"])

    def test_the_forecast_the_browser_fetched_is_used_when_it_is_for_the_points_asked_for(self):
        with mock.patch("trips.weather.forecast", side_effect=spent()) as forecast:
            offer = self.post().json()["forecast"]
            (points, start, end), _ = forecast.call_args
            sent = {"points": offer["points"], "hourly": fetched_by_browser(points, start, end, lambda lat: 10.0)}
            response = self.post(forecast=sent)
            self.assertEqual(forecast.call_count, 1)
        self.assertEqual(response.status_code, 200, response.content)
        plan = response.json()
        self.assertEqual([r["id"] for r in plan["routes"]], ["A", "B", "C"])
        self.assertTrue(plan["routes"][0]["summary"]["recommended"])
        self.assertEqual(plan["routes"][0]["checkpoints"][0]["wind_mph"], 10.0)
        self.assertEqual(plan["heatmap"]["type"], "FeatureCollection")

    def test_a_forecast_of_the_wrong_shape_is_refused_before_anything_is_planned(self):
        (series,) = fetched_by_browser([(35.0, -100.0)], soon(), soon(50), lambda lat: 10.0)
        good = {"points": [[35.0, -100.0]], "hourly": [series]}
        cases = [
            (None, "forecast: This field may not be null"),
            ([], "forecast: Expected a dictionary of items"),
            ({"points": good["points"]}, "forecast: give points and hourly, each a list"),
            ({**good, "points": [[35.0, -100.0], [36.0, -100.0]]}, "forecast: give one hourly series per point"),
            ({**good, "points": [[35.0]]}, "forecast: point 0 is not [lat, lon] in North America"),
            ({**good, "points": [[48.85, 2.35]]}, "forecast: point 0 is not [lat, lon] in North America"),
            ({**good, "points": [["35.0", "-100.0"]]}, "forecast: point 0 is not [lat, lon] in North America"),
            ({**good, "hourly": [{k: v for k, v in series.items() if k != "showers"}]}, "forecast: hourly series 0 is not Open-Meteo's hourly member"),
            ({**good, "hourly": [{**series, "gusts": series["rain"]}]}, "forecast: hourly series 0 is not Open-Meteo's hourly member"),
            ({**good, "hourly": [{**series, "rain": series["rain"][:-1]}]}, "forecast: the columns of hourly series 0 are not lists of one length"),
            ({**good, "hourly": [{**series, "rain": "wet"}]}, "forecast: the columns of hourly series 0 are not lists of one length"),
            ({**good, "hourly": [{**series, "rain": ["wet"] + series["rain"][1:]}]}, "forecast: hourly series 0 has a value that is not a number or null"),
            ({**good, "hourly": [{**series, "rain": [True] + series["rain"][1:]}]}, "forecast: hourly series 0 has a value that is not a number or null"),
            ({**good, "hourly": [{k: v * 11 for k, v in series.items()}]}, "forecast: hourly series 0 runs longer than the forecast does"),
            ({"points": good["points"] * 401, "hourly": good["hourly"] * 401}, "forecast: more than 400 points"),
        ]
        with mock.patch("trips.osrm.find") as find:
            for forecast, message in cases:
                with self.subTest(message=message):
                    response = self.post(forecast=forecast)
                    self.assertEqual(response.status_code, 400, response.content)
                    self.assertIn(message, response.json()["detail"])
                    self.assertIn("forecast", response.json()["errors"])
            find.assert_not_called()

    def test_unusable_readings_from_the_browser_are_refused_as_a_bad_request(self):
        with mock.patch("trips.weather.forecast", side_effect=spent()) as forecast:
            offer = self.post().json()["forecast"]
            (points, start, end), _ = forecast.call_args
            hourly = fetched_by_browser(points, start, end, lambda lat: 10.0)
            hourly[3]["wind_speed_10m"][5] = None
            response = self.post(forecast={"points": offer["points"], "hourly": hourly})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"detail": "the supplied forecast has no value for part of this trip"})
            # A series that stops short of the trip is no better.
            hourly = fetched_by_browser(points, start, end, lambda lat: 10.0)
            hourly[0] = {name: column[:-5] for name, column in hourly[0].items()}
            response = self.post(forecast={"points": offer["points"], "hourly": hourly})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"detail": "the supplied forecast does not cover the whole trip"})

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


class PageTests(CacheTestCase):
    @unittest.skipUnless((settings.FRONTEND_DIST / "index.html").exists(), "the React app is not built (npm run build in frontend/)")
    def test_the_page_may_not_be_framed_and_is_not_held_by_the_browser(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div id="root"', b"".join(response.streaming_content))
        # WhiteNoise answers for the page itself, so the header has to be put on above it.
        self.assertEqual(response["X-Frame-Options"], "DENY")
        # The page names the bundles of the moment; a held copy would name a deploy's old ones.
        self.assertEqual(response["Cache-Control"], "max-age=0, public")


class NotFoundTests(CacheTestCase):
    def test_a_missing_api_path_answers_in_json_like_the_rest_of_the_api(self):
        response = self.client.get("/api/nothing/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "not found"})
        self.assertEqual(response["X-Frame-Options"], "DENY")

    def test_anything_else_missing_gets_the_usual_page(self):
        response = self.client.get("/nothing/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response["Content-Type"].startswith("text/html"))
        self.assertIn(b"Not Found", response.content)
