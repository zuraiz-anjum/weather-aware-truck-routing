from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

import trips.geocoding
from trips.geocoding import GeocodingError, Place, PlaceNotFound, label, locate, suggest

from .support import CacheTestCase, FakeResponse


def feature(lon, lat, **properties):
    return {"geometry": {"coordinates": [lon, lat]}, "properties": properties}


DENVER = feature(-104.98, 39.74, name="Denver", state="Colorado", countrycode="US", osm_key="place", osm_value="city")
DENVER_IA = feature(-92.33, 42.67, name="Denver", state="Iowa", countrycode="US", osm_key="place", osm_value="village")
DENVER_AGAIN = feature(-104.99, 39.75, name="Denver", state="Colorado", countrycode="US", osm_key="place", osm_value="county")
CANADA = feature(-79.38, 43.65, name="Denver Street", city="Toronto", state="Ontario", countrycode="CA")
BROKEN = {"geometry": {"coordinates": [None, 1]}, "properties": {"name": "x", "countrycode": "US"}}


@override_settings(PHOTON_URL="http://photon.test")
class SuggestTests(CacheTestCase):
    def answer(self, features, status_code=200):
        get = mock.patch.object(
            trips.geocoding._session, "get", return_value=FakeResponse({"features": features}, status_code)
        ).start()
        self.addCleanup(mock.patch.stopall)
        return get

    def test_us_places_only_without_repeats_in_photon_order(self):
        self.answer([CANADA, DENVER, DENVER_AGAIN, BROKEN, DENVER_IA])
        self.assertEqual(
            suggest("denver"),
            [Place("Denver, Colorado", 39.74, -104.98), Place("Denver, Iowa", 42.67, -92.33)],
        )

    def test_limit_and_request_shape(self):
        get = self.answer([DENVER, DENVER_IA])
        self.assertEqual(len(suggest("denver", limit=1)), 1)
        params = get.call_args[1]["params"]
        self.assertEqual(params["q"], "denver")
        self.assertEqual(params["lang"], "en")
        self.assertEqual(params["limit"], 3)
        self.assertIn("bbox", params)

    def test_short_or_blank_text_asks_nothing(self):
        get = self.answer([DENVER])
        self.assertEqual(suggest(" d "), [])
        self.assertEqual(suggest(""), [])
        get.assert_not_called()

    def test_whitespace_is_collapsed_and_results_cached_by_text(self):
        get = self.answer([DENVER])
        suggest("  denver   co ")
        suggest("Denver CO")
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args[1]["params"]["q"], "denver co")

    def test_failures_are_geocoding_errors(self):
        self.answer([], 503)
        with self.assertRaises(GeocodingError):
            suggest("denver")
        mock.patch.object(trips.geocoding._session, "get", side_effect=requests.ConnectionError("down")).start()
        with self.assertRaises(GeocodingError):
            suggest("denver")


@override_settings(PHOTON_URL="http://photon.test")
class LocateTests(CacheTestCase):
    def test_first_match_or_not_found(self):
        with mock.patch.object(trips.geocoding._session, "get", return_value=FakeResponse({"features": [DENVER_IA, DENVER]})):
            self.assertEqual(locate("denver"), Place("Denver, Iowa", 42.67, -92.33))
        with mock.patch.object(trips.geocoding._session, "get", return_value=FakeResponse({"features": [CANADA]})):
            with self.assertRaises(PlaceNotFound):
                locate("denver street toronto")


class LabelTests(SimpleTestCase):
    def test_town_address_and_named_building(self):
        self.assertEqual(label({"name": "Denver", "state": "Colorado"}), "Denver, Colorado")
        self.assertEqual(
            label({"housenumber": "1600", "street": "Pennsylvania Avenue NW", "city": "Washington", "state": "District of Columbia"}),
            "1600 Pennsylvania Avenue NW, Washington, District of Columbia",
        )
        self.assertEqual(label({"name": "White House", "city": "Washington", "state": "District of Columbia"}),
                         "White House, Washington, District of Columbia")

    def test_a_city_is_not_repeated_after_its_own_name(self):
        self.assertEqual(label({"name": "Houston", "city": "Houston", "state": "Texas"}), "Houston, Texas")

    def test_nothing_usable_gives_an_empty_label(self):
        self.assertEqual(label({}), "")
