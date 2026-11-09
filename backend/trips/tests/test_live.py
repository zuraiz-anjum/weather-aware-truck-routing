"""
Against the real services, when LIVE_SERVICES=1 is set.

The other tests stub the three services and so take their request contracts
on trust. These check the parts of that trust that have bitten: that
Open-Meteo accepts the window the planner asks for at both ends of the
allowed range, and that a small trip goes through end to end. They cost a
few dozen forecast points and a handful of routing calls.
"""

import os
import unittest
from datetime import datetime, timedelta, timezone

from trips import geocoding, planner, weather
from trips.serializers import LATEST_AHEAD

from .support import CacheTestCase

LIVE = os.environ.get("LIVE_SERVICES") == "1"


@unittest.skipUnless(LIVE, "set LIVE_SERVICES=1 to call the real services")
class LiveServiceTests(CacheTestCase):
    def test_open_meteo_takes_a_window_starting_yesterday(self):
        yesterday = datetime.now(timezone.utc) - timedelta(hours=23, minutes=50)
        (hourly,) = weather.forecast([(35.2, -101.8)], yesterday, yesterday + timedelta(hours=48))
        self.assertLessEqual(hourly.times[0], int(yesterday.timestamp()))
        self.assertEqual(len(hourly.wind), len(hourly.times))

    def test_open_meteo_takes_the_latest_departure_the_form_allows(self):
        latest = datetime.now(timezone.utc) + LATEST_AHEAD - timedelta(minutes=5)
        (hourly,) = weather.forecast([(35.2, -101.8)], latest, latest + timedelta(hours=48))
        # Early in the UTC day the model's reach stops a few hours short of
        # the horizon and those hours are cut off; the trip's own must be there.
        self.assertGreater(hourly.times[-1], int((latest + timedelta(hours=48)).timestamp()))
        self.assertLessEqual(hourly.times[-1], int(weather.horizon().timestamp()))

    def test_a_short_trip_goes_through(self):
        origin = geocoding.locate("Amarillo, Texas")
        destination = geocoding.locate("Lubbock, Texas")
        self.assertEqual(origin.label, "Amarillo, Texas")
        departure = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=3)
        result = planner.plan(origin, destination, departure, 36_000)
        self.assertGreaterEqual(len(result["routes"]), 2)
        best = result["routes"][0]
        self.assertEqual(best["summary"]["rank"], 1)
        self.assertAlmostEqual(best["distance_miles"], 125, delta=20)
        self.assertEqual(best["checkpoints"][0]["mile"], 0.0)
        self.assertEqual(best["checkpoints"][-1]["eta"], best["arrival"])
        self.assertTrue(result["heatmap"]["features"])
