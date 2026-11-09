from datetime import datetime, timedelta, timezone
from unittest import mock

import requests
from django.core.cache import cache
from django.test import override_settings

import trips.weather
from trips.weather import (POINTS_PER_REQUEST, BadForecast, Hourly, WeatherBusy, WeatherError, busy, forecast, horizon, midnight_after,
                           offer, query, supplied, window)

from .support import CacheTestCase, FakeResponse

T0 = 1_800_000_000  # some hour, in unix seconds


def at(hour, minute=0):
    return datetime.fromtimestamp(T0 + hour * 3600 + minute * 60, timezone.utc)


def body_for(count, hours=50, first=T0):
    times = [first + h * 3600 for h in range(hours)]
    one = {
        "hourly": {
            "time": times,
            "wind_speed_10m": [10.0 + h for h in range(hours)],
            "rain": [0.01 * h for h in range(hours)],
            "showers": [0.005 * h for h in range(hours)],
            "snowfall": [0.0] * hours,
        }
    }
    return one if count == 1 else [one] * count


class HourlyTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        self.hourly = Hourly([T0, T0 + 3600, T0 + 7200], [10.0, 20.0, 40.0], [0.0, 0.3, 0.6], [0.0, 0.0, 1.0])

    def test_wind_is_read_between_the_hours(self):
        self.assertEqual(self.hourly.at(at(0))[0], 10.0)
        self.assertEqual(self.hourly.at(at(0, 30))[0], 15.0)
        self.assertEqual(self.hourly.at(at(1, 45))[0], 35.0)

    def test_rain_and_snow_are_the_hour_ahead(self):
        # The value stamped 01:00 covers 00:00-01:00: it is what a truck
        # drives into at 00:00 exactly and at 00:20; from 01:00 it is the next.
        self.assertEqual(self.hourly.at(at(0))[1], 0.3)
        self.assertEqual(self.hourly.at(at(0, 20))[1], 0.3)
        self.assertEqual(self.hourly.at(at(1))[1], 0.6)
        self.assertEqual(self.hourly.at(at(1, 1))[2], 1.0)

    def test_outside_the_window_the_ends_are_used(self):
        self.assertEqual(self.hourly.at(at(-3)), (10.0, 0.0, 0.0))
        self.assertEqual(self.hourly.at(at(9)), (40.0, 0.6, 1.0))


class WindowTests(CacheTestCase):
    def test_midnight_after(self):
        noon = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
        midnight = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(midnight_after(noon), midnight)
        self.assertEqual(midnight_after(midnight), midnight)
        self.assertEqual(midnight_after(midnight + timedelta(seconds=1)), midnight + timedelta(days=1))

    def test_horizon_is_the_last_hour_of_the_sixteenth_day(self):
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        self.assertEqual(horizon(), today + timedelta(days=16) - timedelta(hours=1))

    def test_window_runs_from_midnight_of_the_first_day_to_a_midnight_at_least_three_days_on(self):
        start = datetime.now(timezone.utc).replace(hour=6, minute=30, second=0, microsecond=0) + timedelta(days=2)
        midnight = start.replace(hour=0, minute=0)
        self.assertEqual(window(start, start + timedelta(hours=48)), (midnight, midnight + timedelta(days=3)))
        self.assertEqual(window(start, start + timedelta(hours=100)), (midnight, midnight + timedelta(days=5)))


@override_settings(OPEN_METEO_URL="http://meteo.test")
class ForecastTests(CacheTestCase):
    def answer(self, body, status_code=200):
        get = mock.patch.object(trips.weather._session, "get", return_value=FakeResponse(body, status_code)).start()
        self.addCleanup(mock.patch.stopall)
        return get

    def answer_the_window_asked_for(self):
        """Hours covering exactly the window each request names, for however many points it names."""

        def respond(url, params, headers, timeout):
            first = datetime.strptime(params["start_hour"], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
            last = datetime.strptime(params["end_hour"], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
            hours = int((last - first).total_seconds() // 3600) + 1
            return FakeResponse(body_for(params["latitude"].count(",") + 1, hours, int(first.timestamp())))

        get = mock.patch.object(trips.weather._session, "get", side_effect=respond).start()
        self.addCleanup(mock.patch.stopall)
        return get

    def soon(self, hours=0):
        return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)

    def test_window_and_units_in_the_request(self):
        get = self.answer_the_window_asked_for()
        # Tomorrow at six, so that the slider's end lands inside the three-day
        # minimum whatever the time of day the test runs at.
        start = self.soon(24).replace(hour=6, minute=0, second=0)
        forecast([(35.0, -100.0), (36.0, -101.0)], start, start + timedelta(hours=48))
        midnight = start.replace(hour=0, minute=0, second=0)
        # The whole query, so that nothing is added or dropped unnoticed; a
        # browser asked to fetch for us is given the same one (below).
        self.assertEqual(get.call_args[1]["params"], {
            "latitude": "35.0000,36.0000",
            "longitude": "-100.0000,-101.0000",
            "hourly": "wind_speed_10m,rain,showers,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "timeformat": "unixtime",
            "start_hour": midnight.strftime("%Y-%m-%dT%H:%M"),
            "end_hour": (midnight + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
        })

    @override_settings(OPEN_METEO_API_KEY="secret", OPEN_METEO_PUBLIC_URL="http://public.meteo.test")
    def test_a_browser_is_offered_the_requests_own_query_less_the_points_and_the_key(self):
        get = self.answer_the_window_asked_for()
        start = self.soon(24).replace(hour=6, minute=0, second=0)
        end = start + timedelta(hours=48)
        forecast([(35.0, -100.0)], start, end)
        sent = get.call_args[1]["params"]
        self.assertEqual(sent["apikey"], "secret")
        offered = offer([(35.0, -100.0), (36.12346, -101.98764)], start, end)
        self.assertEqual(offered["url"], "http://public.meteo.test/v1/forecast")
        self.assertEqual(offered["params"], {k: v for k, v in sent.items() if k not in ("latitude", "longitude", "apikey")})
        self.assertEqual(offered["params"], query(*window(start, end)))
        self.assertEqual(offered["points"], [[35.0, -100.0], [36.1235, -101.9876]])

    def test_a_long_trip_pushes_the_window_out_to_a_midnight(self):
        get = self.answer_the_window_asked_for()
        start = self.soon(2)
        end = start + timedelta(hours=100)
        forecast([(35.0, -100.0)], start, end)
        expected = midnight_after(end + timedelta(hours=1))
        self.assertEqual(get.call_args[1]["params"]["end_hour"], expected.strftime("%Y-%m-%dT%H:%M"))

    def test_the_window_never_runs_past_the_horizon(self):
        get = self.answer_the_window_asked_for()
        start = horizon() - timedelta(hours=60)
        forecast([(35.0, -100.0)], start, start + timedelta(hours=48))
        self.assertEqual(get.call_args[1]["params"]["end_hour"], horizon().strftime("%Y-%m-%dT%H:%M"))

    def test_a_departure_late_yesterday_just_starts_the_window_earlier(self):
        get = self.answer_the_window_asked_for()
        yesterday = datetime.now(timezone.utc) - timedelta(hours=25)
        forecast([(35.0, -100.0)], yesterday, yesterday + timedelta(hours=2))
        params = get.call_args[1]["params"]
        self.assertEqual(params["start_hour"], yesterday.strftime("%Y-%m-%dT00:00"))
        self.assertNotIn("past_days", params)

    def test_departures_on_the_same_day_share_one_fetch_however_long_the_trip(self):
        get = self.answer_the_window_asked_for()
        morning = self.soon(2).replace(hour=6)
        forecast([(35.0, -100.0)], morning, morning + timedelta(hours=60))
        forecast([(35.0, -100.0)], morning + timedelta(hours=1), morning + timedelta(hours=61))
        self.assertEqual(get.call_count, 1)

    def test_points_go_out_a_hundred_at_a_time_and_come_back_in_order(self):
        calls = []

        def get(url, params, headers, timeout):
            count = params["latitude"].count(",") + 1
            calls.append(count)
            return FakeResponse(body_for(count))

        mock.patch.object(trips.weather._session, "get", side_effect=get).start()
        self.addCleanup(mock.patch.stopall)
        points = [(30.0 + k * 0.01, -100.0) for k in range(250)]
        hourlies = forecast(points, at(0), at(48))
        self.assertEqual(len(hourlies), 250)
        self.assertEqual(sorted(calls), [50, 100, 100])
        self.assertEqual(hourlies[0].times[0], T0)

    def test_a_single_point_comes_back_bare_and_rain_includes_showers(self):
        self.answer(body_for(1))
        (hourly,) = forecast([(35.0, -100.0)], at(0), at(48))
        self.assertEqual(len(hourly.wind), 50)
        self.assertAlmostEqual(hourly.rain[10], 0.15)
        self.assertEqual(hourly.snow[10], 0.0)

    def test_second_call_is_served_from_the_cache(self):
        get = self.answer(body_for(1))
        for _ in range(2):
            forecast([(35.0, -100.0)], at(0), at(48))
        self.assertEqual(get.call_count, 1)

    def test_a_missing_value_refuses_the_plan_rather_than_reading_calm(self):
        body = body_for(1)
        body["hourly"]["rain"][5] = None
        self.answer(body)
        with self.assertRaises(WeatherError) as caught:
            forecast([(35.0, -100.0)], at(0), at(48))
        self.assertIn("no forecast for part of this trip", str(caught.exception))

    def past_the_reach(self):
        """The last five hours null in every column, as the sixteenth day comes back before the day's first model run."""
        body = body_for(1)
        for name in ("wind_speed_10m", "rain", "showers", "snowfall"):
            body["hourly"][name][-5:] = [None] * 5
        return body

    def test_hours_past_the_models_reach_are_cut_off_when_the_trip_ends_before_them(self):
        self.answer(self.past_the_reach())
        (hourly,) = forecast([(35.0, -100.0)], at(0), at(43, 59))
        self.assertEqual(len(hourly.times), 45)
        self.assertEqual(hourly.times[-1], T0 + 44 * 3600)
        self.assertEqual(len(hourly.wind), len(hourly.rain))

    def test_a_trip_that_runs_into_the_hours_past_the_reach_is_refused(self):
        self.answer(self.past_the_reach())
        # Rain at 44:00 is the hour that ends at 45:00, and there is none.
        with self.assertRaises(WeatherError) as caught:
            forecast([(35.0, -100.0)], at(0), at(44))
        self.assertIn("no forecast for part of this trip", str(caught.exception))

    def test_an_allowance_running_out_is_its_own_error_and_says_how_long_to_wait(self):
        cases = [
            ("Minutely API request limit exceeded. Please try again in one minute.", "minutely", 60, "in a minute"),
            ("Hourly API request limit exceeded. Please try again in the next hour.", "hourly", 3600, "in an hour"),
            ("Daily API request limit exceeded. Please try again tomorrow.", "daily", None, "tomorrow"),
            ("API request limit exceeded.", "minutely", 60, "in a minute"),
        ]
        for reason, allowance, seconds, when in cases:
            with self.subTest(reason=reason):
                self.answer({"error": True, "reason": reason}, 429)
                with self.assertRaises(WeatherBusy) as caught:
                    forecast([(35.0, -100.0)], at(0), at(48))
                self.assertEqual(caught.exception.allowance, allowance)
                self.assertEqual(caught.exception.retry_after, seconds or trips.weather.wait(allowance))
                self.assertIn(when, str(caught.exception))

    def test_the_days_allowance_comes_back_at_midnight_utc(self):
        cases = [
            (datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc), 4 * 3600),
            (datetime(2026, 11, 10, 23, 58, 59, 500000, tzinfo=timezone.utc), 61),
            # Never less than a minute: a retry on the stroke of midnight would be early.
            (datetime(2026, 11, 10, 23, 59, 30, tzinfo=timezone.utc), 60),
            (datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc), 60),
        ]
        for clock, seconds in cases:
            with self.subTest(clock=clock.isoformat()), mock.patch("trips.weather.datetime") as fixed:
                fixed.now.return_value = clock
                spent = busy("Daily API request limit exceeded. Please try again tomorrow.")
                self.assertEqual((spent.allowance, spent.retry_after), ("daily", seconds))
                self.assertIn("try again tomorrow", str(spent))

    def test_failures(self):
        cases = [
            ({"error": True, "reason": "bad"}, 400),
            ([{"hourly": {"time": []}}], 200),
            ([{"hourly": {"time": [T0], "wind_speed_10m": [1.0], "rain": [], "showers": [0.0], "snowfall": [0.0]}}], 200),
            ([], 200),
            (ValueError("no json"), 502),
        ]
        for body, status in cases:
            with self.subTest(body=body):
                self.answer(body, status)
                with self.assertRaises(WeatherError):
                    forecast([(35.0, -100.0)], at(0), at(48))
        mock.patch.object(trips.weather._session, "get", side_effect=requests.ConnectionError("down")).start()
        with self.assertRaises(WeatherError):
            forecast([(35.0, -100.0)], at(0), at(48))

    def test_the_chunk_size_is_what_open_meteo_handles_comfortably(self):
        self.assertEqual(POINTS_PER_REQUEST, 100)


class SuppliedTests(CacheTestCase):
    """Series a browser fetched when asked to: Open-Meteo's hourly members, read as a fetch of our own would be."""

    def series(self, count=2):
        body = body_for(count)
        return [item["hourly"] for item in (body if isinstance(body, list) else [body])]

    def test_the_browsers_series_give_the_hourlies_fetching_them_here_would(self):
        series = self.series()
        mock.patch.object(trips.weather._session, "get", return_value=FakeResponse(body_for(2))).start()
        self.addCleanup(mock.patch.stopall)
        with mock.patch.object(cache, "set", wraps=cache.set) as set_:
            hourlies = supplied(series, at(0), at(48))
        self.assertEqual(hourlies, forecast([(35.0, -100.0), (36.0, -101.0)], at(0), at(48)))
        self.assertEqual(hourlies, [trips.weather._hourly(data) for data in series])
        self.assertAlmostEqual(hourlies[0].rain[10], 0.15)
        # What the browser sent is its own; the next plan fetches for itself.
        set_.assert_not_called()

    def test_hours_past_the_models_reach_are_cut_off_as_they_are_from_a_fetch(self):
        (series,) = self.series(1)
        for name in ("wind_speed_10m", "rain", "showers", "snowfall"):
            series[name][-5:] = [None] * 5
        (hourly,) = supplied([series], at(0), at(43, 59))
        self.assertEqual(len(hourly.times), 45)
        self.assertEqual(hourly.times[-1], T0 + 44 * 3600)
        with self.assertRaises(BadForecast) as caught:
            supplied([series], at(0), at(44))
        self.assertIn("does not cover the whole trip", str(caught.exception))

    def test_series_that_cannot_be_read_are_refused_with_the_reason(self):
        (series,) = self.series(1)
        cases = [
            ({**series, "rain": series["rain"][:5] + [None] + series["rain"][6:]}, at(0), at(48), "has no value for part of this trip"),
            ({**series, "rain": series["rain"][:-1]}, at(0), at(48), "is not in the shape Open-Meteo sends"),
            ({k: v for k, v in series.items() if k != "showers"}, at(0), at(48), "is not in the shape Open-Meteo sends"),
            ({**series, "time": []}, at(0), at(48), "is not in the shape Open-Meteo sends"),
            # Fifty hours from T0 run to 49:00; rain at 49:00 would be read from the stamp after it.
            (series, at(0), at(49), "does not cover the whole trip"),
            (series, at(-1), at(40), "does not cover the whole trip"),
        ]
        for data, start, end, message in cases:
            with self.subTest(message=message, start=start.isoformat()):
                with self.assertRaises(BadForecast) as caught:
                    supplied([data], start, end)
                self.assertIn(message, str(caught.exception))
