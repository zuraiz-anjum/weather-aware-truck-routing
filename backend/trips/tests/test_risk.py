from django.test import SimpleTestCase

from trips.risk import HIGH, LOW, MODERATE, NO_TRAVEL, SEVERE, assess, rain_level, read, snow_level, wind_level


class ThresholdTests(SimpleTestCase):
    def test_values_are_judged_as_they_are_shown(self):
        # 24.6 mph reads as 25 and 0.096 in/h as 0.10, so both are Moderate; a half mile an hour rounds up.
        self.assertEqual(read(24.6, 0.096, 2.996), (25.0, 0.10, 3.0))
        self.assertEqual(read(24.5, 0.094, 0), (25.0, 0.09, 0.0))
        edge = assess(24.6, 0.096, 2.996, 0)
        self.assertEqual((edge.wind, edge.rain, edge.snow), (MODERATE, MODERATE, SEVERE))
        below = assess(24.4, 0.094, 3.004, 0)
        self.assertEqual((below.wind, below.rain, below.snow), (LOW, LOW, SEVERE))

    def test_wind_bands_own_their_lower_bound(self):
        cases = [(0, LOW), (24.4, LOW), (25, MODERATE), (34.4, MODERATE), (35, HIGH), (44.4, HIGH),
                 (45, SEVERE), (54.4, SEVERE), (55, NO_TRAVEL), (90, NO_TRAVEL)]
        for mph, level in cases:
            with self.subTest(mph=mph):
                self.assertEqual(wind_level(mph), level)

    def test_rain_bands(self):
        cases = [(0, LOW), (0.09, LOW), (0.10, MODERATE), (0.24, MODERATE), (0.25, HIGH), (0.49, HIGH),
                 (0.50, SEVERE), (1.00, SEVERE), (1.01, NO_TRAVEL)]
        for rate, level in cases:
            with self.subTest(rate=rate):
                self.assertEqual(rain_level(rate), level)

    def test_snow_bands(self):
        cases = [(0, LOW), (0.49, LOW), (0.5, MODERATE), (0.99, MODERATE), (1.0, HIGH), (1.99, HIGH),
                 (2.0, SEVERE), (3.0, SEVERE), (3.01, NO_TRAVEL)]
        for rate, level in cases:
            with self.subTest(rate=rate):
                self.assertEqual(snow_level(rate), level)


class AssessTests(SimpleTestCase):
    def test_the_worst_factor_decides(self):
        a = assess(wind_mph=10, rain_inches_per_hour=0.3, snow_inches_per_hour=0, load_lb=10_000)
        self.assertEqual((a.level, a.wind, a.rain, a.snow), (HIGH, LOW, HIGH, LOW))
        self.assertIsNone(a.load_rule)

    def test_fifty_five_mph_is_no_travel_for_any_load(self):
        self.assertEqual(assess(55, 0, 0, 0).level, NO_TRAVEL)
        self.assertEqual(assess(55, 0, 0, 80_000).level, NO_TRAVEL)

    def test_heavy_load_in_severe_wind_is_no_travel(self):
        light = assess(50, 0, 0, 30_000)
        heavy = assess(50, 0, 0, 30_001)
        self.assertEqual(light.level, SEVERE)
        self.assertIsNone(light.load_rule)
        self.assertEqual(heavy.level, NO_TRAVEL)
        self.assertEqual(heavy.wind, NO_TRAVEL)
        self.assertIn("30,000 lb", heavy.load_rule)

    def test_very_heavy_load_in_high_wind_is_severe(self):
        self.assertEqual(assess(40, 0, 0, 40_000).level, HIGH)
        heavy = assess(40, 0, 0, 40_001)
        self.assertEqual(heavy.level, SEVERE)
        self.assertIn("40,000 lb", heavy.load_rule)

    def test_load_rules_do_not_touch_rain_or_snow(self):
        a = assess(10, 0.6, 2.5, 80_000)
        self.assertEqual((a.level, a.rain, a.snow), (SEVERE, SEVERE, SEVERE))
        self.assertIsNone(a.load_rule)

    def test_the_load_rule_never_lowers_a_level(self):
        # 45-54 mph with a heavy load is No Travel, which is above anything rain adds.
        self.assertEqual(assess(50, 1.5, 0, 35_000).level, NO_TRAVEL)
