"""
The weather risk rules from the brief, applied to one place at one time.

    Condition   Low        Moderate    High        Severe      No Travel
    Wind        <25 mph    25-34       35-44       45-54       >=55 mph
    Rain        <0.10 in/h 0.10-0.25   0.25-0.50   0.50-1.00   >1.00
    Snow        <0.5 in/h  0.5-1.0     1.0-2.0     2.0-3.0     >3.0

The table is read with each band owning its lower bound, so 0.25 in/h of
rain is High and 35 mph is High. The top band is the exception the brief
spells out: wind is No Travel from 55 mph, while rain and snow have to
exceed 1.00 and 3.0.

Load rules, which only concern wind:

    >=55 mph                        No Travel, whatever the load
    45-54 mph and over 30,000 lb    No Travel
    35-44 mph and over 40,000 lb    Severe
"""

from bisect import bisect_right
from dataclasses import dataclass

LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL = range(5)
NAMES = ("Low", "Moderate", "High", "Severe", "No Travel")

WIND_MPH = (25.0, 35.0, 45.0, 55.0)
RAIN_INCHES_PER_HOUR = (0.10, 0.25, 0.50, 1.00)
SNOW_INCHES_PER_HOUR = (0.5, 1.0, 2.0, 3.0)

HEAVY_LOAD_LB = 30_000
VERY_HEAVY_LOAD_LB = 40_000


def wind_level(mph):
    return bisect_right(WIND_MPH, mph)


def rain_level(inches_per_hour):
    if inches_per_hour > RAIN_INCHES_PER_HOUR[-1]:
        return NO_TRAVEL
    return bisect_right(RAIN_INCHES_PER_HOUR[:-1], inches_per_hour)


def snow_level(inches_per_hour):
    if inches_per_hour > SNOW_INCHES_PER_HOUR[-1]:
        return NO_TRAVEL
    return bisect_right(SNOW_INCHES_PER_HOUR[:-1], inches_per_hour)


@dataclass(frozen=True)
class Assessment:
    level: int
    wind: int
    rain: int
    snow: int
    load_rule: str | None  # set when the load pushed the wind level up


def assess(wind_mph, rain_inches_per_hour, snow_inches_per_hour, load_lb):
    """Classify the conditions for a truck carrying load_lb; the worst factor decides."""
    wind = wind_level(wind_mph)
    load_rule = None
    if wind == SEVERE and load_lb > HEAVY_LOAD_LB:
        wind = NO_TRAVEL
        load_rule = f"45-54 mph wind with a load over {HEAVY_LOAD_LB:,} lb"
    elif wind == HIGH and load_lb > VERY_HEAVY_LOAD_LB:
        wind = SEVERE
        load_rule = f"35-44 mph wind with a load over {VERY_HEAVY_LOAD_LB:,} lb"
    rain = rain_level(rain_inches_per_hour)
    snow = snow_level(snow_inches_per_hour)
    return Assessment(max(wind, rain, snow), wind, rain, snow, load_rule)
