"""
Google's encoded polyline format, which is how OSRM sends geometry.

Each coordinate is the delta from the previous one, times 10^precision,
zigzag-encoded and split into 5-bit chunks, low bits first, with bit 6 set
on every chunk but the last. Latitude and longitude alternate.
"""


def decode(text, precision=5):
    """Decode a polyline string into a list of (lat, lon)."""
    scale = 10**precision
    points = []
    index = 0
    lat = lon = 0
    length = len(text)
    while index < length:
        pair = []
        for _ in range(2):
            value = shift = 0
            while True:
                if index >= length:
                    raise ValueError("polyline ends in the middle of a number")
                chunk = ord(text[index]) - 63
                index += 1
                if chunk < 0:
                    raise ValueError("polyline contains a character below '?'")
                value |= (chunk & 0x1F) << shift
                shift += 5
                if chunk < 0x20:
                    break
            pair.append(~(value >> 1) if value & 1 else value >> 1)
        lat += pair[0]
        lon += pair[1]
        points.append((lat / scale, lon / scale))
    return points
