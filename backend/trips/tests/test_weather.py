from datetime import datetime, timedelta, timezone
from unittest import mock

import requests
from django.test import override_settings

import trips.weather
from trips.weather import POINTS_PER_REQUEST, Hourly, WeatherBusy, WeatherError, forecast, horizon, midnight_after

from .support import CacheTestCase, FakeResponse

T0 = 1_800_000_000  # some hour, in unix seconds


def at(hour, minute=0):
    return datetime.fromtimestamp(T0 + hour * 3600 + minute * 60, timezone.utc)


def body_for(count, hours=49):
    times = [T0 + h * 3600 for h in range(hours)]
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


@override_settings(OPEN_METEO_URL="http://meteo.test")
class ForecastTests(CacheTestCase):
    def answer(self, body, status_code=200):
        get = mock.patch.object(trips.weather._session, "get", return_value=FakeResponse(body, status_code)).start()
        self.addCleanup(mock.patch.stopall)
        return get

    def soon(self, hours=0):
        return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)

    def test_window_and_units_in_the_request(self):
        get = self.answer(body_for(2))
        start = self.soon(2)
        forecast([(35.0, -100.0), (36.0, -101.0)], start, start + timedelta(hours=48))
        params = get.call_args[1]["params"]
        self.assertEqual(params["latitude"], "35.0000,36.0000")
        self.assertEqual(params["longitude"], "-100.0000,-101.0000")
        self.assertEqual(params["hourly"], "wind_speed_10m,rain,showers,snowfall")
        self.assertEqual(params["wind_speed_unit"], "mph")
        self.assertEqual(params["precipitation_unit"], "inch")
        self.assertEqual(params["timezone"], "UTC")
        midnight = start.replace(hour=0, minute=0, second=0)
        self.assertEqual(params["start_hour"], midnight.strftime("%Y-%m-%dT%H:%M"))
        self.assertEqual(params["end_hour"], (midnight + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"))
        self.assertNotIn("past_days", params)

    def test_a_long_trip_pushes_the_window_out_to_a_midnight(self):
        get = self.answer(body_for(1))
        start = self.soon(2)
        end = start + timedelta(hours=100)
        forecast([(35.0, -100.0)], start, end)
        expected = midnight_after(end + timedelta(hours=1))
        self.assertEqual(get.call_args[1]["params"]["end_hour"], expected.strftime("%Y-%m-%dT%H:%M"))

    def test_the_window_never_runs_past_the_horizon(self):
        get = self.answer(body_for(1))
        start = horizon() - timedelta(hours=60)
        forecast([(35.0, -100.0)], start, start + timedelta(hours=48))
        self.assertEqual(get.call_args[1]["params"]["end_hour"], horizon().strftime("%Y-%m-%dT%H:%M"))

    def test_a_departure_late_yesterday_just_starts_the_window_earlier(self):
        get = self.answer(body_for(1))
        yesterday = datetime.now(timezone.utc) - timedelta(hours=25)
        forecast([(35.0, -100.0)], yesterday, yesterday + timedelta(hours=2))
        params = get.call_args[1]["params"]
        self.assertEqual(params["start_hour"], yesterday.strftime("%Y-%m-%dT00:00"))
        self.assertNotIn("past_days", params)

    def test_departures_on_the_same_day_share_one_fetch_however_long_the_trip(self):
        get = self.answer(body_for(1))
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
        self.assertEqual(len(hourly.wind), 49)
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

    def test_the_minute_allowance_running_out_is_its_own_error(self):
        self.answer({"error": True, "reason": "Minutely API request limit exceeded. Please try again in one minute."}, 429)
        with self.assertRaises(WeatherBusy):
            forecast([(35.0, -100.0)], at(0), at(48))

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
