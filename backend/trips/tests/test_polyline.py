from django.test import SimpleTestCase

from trips.polyline import decode


def encode(points, precision=5):
    """The textbook encoder, kept here to build fixtures from."""
    out, last = [], (0, 0)
    for lat, lon in points:
        now = (round(lat * 10**precision), round(lon * 10**precision))
        for delta in (now[0] - last[0], now[1] - last[1]):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        last = now
    return "".join(out)


class DecodeTests(SimpleTestCase):
    def test_the_example_from_the_format_description(self):
        self.assertEqual(
            decode("_p~iF~ps|U_ulLnnqC_mqNvxq`@"),
            [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)],
        )

    def test_round_trips_a_line_with_negative_and_tiny_deltas(self):
        points = [(32.7767, -96.797), (32.7767, -96.797), (32.77671, -96.79702), (29.7604, -95.3698), (-1.5, 179.99999)]
        decoded = decode(encode(points))
        for (lat, lon), (lat2, lon2) in zip(points, decoded):
            self.assertAlmostEqual(lat, lat2, places=5)
            self.assertAlmostEqual(lon, lon2, places=5)

    def test_precision_six_as_valhalla_uses(self):
        points = [(40.712776, -74.005974), (40.712800, -74.006000)]
        decoded = decode(encode(points, 6), 6)
        self.assertAlmostEqual(decoded[1][0], 40.7128, places=6)
        self.assertAlmostEqual(decoded[1][1], -74.006, places=6)

    def test_empty_string_is_an_empty_line(self):
        self.assertEqual(decode(""), [])

    def test_truncated_and_foreign_input_is_refused(self):
        for text in ("_p~iF", "_p~iF~ps|U_", "\x01\x02"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                decode(text)
