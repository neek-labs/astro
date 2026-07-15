from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import cos, radians
from typing import Any
from zoneinfo import ZoneInfo


class AstronomyError(RuntimeError):
    """Raised when solar or lunar calculations fail."""


@dataclass(frozen=True)
class AstroPoint:
    time: datetime
    sun_altitude_degrees: float
    moon_altitude_degrees: float
    moon_illumination_percent: float


def moon_illumination_percent_from_elongation(elongation_degrees: float) -> float:
    """Return the illuminated lunar disc percentage for a Sun-Moon elongation."""

    illumination = (1 - cos(radians(float(elongation_degrees)))) * 50
    return max(0.0, min(100.0, illumination))


def observing_bounds(evening_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    start = datetime.combine(evening_date, time(12, 0), tzinfo=timezone)
    return start, start + timedelta(days=1)


def time_grid(start: datetime, end: datetime, interval_minutes: int) -> list[datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise AstronomyError("Astronomy time grid requires timezone-aware datetimes.")
    if interval_minutes <= 0:
        raise AstronomyError("Grid interval must be positive.")

    moments: list[datetime] = []
    current = start
    step = timedelta(minutes=interval_minutes)
    while current < end:
        moments.append(current)
        current += step
    return moments


def calculate_astronomy_grid(config: dict[str, Any], start: datetime, end: datetime) -> list[AstroPoint]:
    try:
        from astropy import units as u
        from astropy.coordinates import AltAz, EarthLocation, get_body, get_sun
        from astropy.time import Time
        from astropy.utils import iers
    except ImportError as exc:
        raise AstronomyError("Astropy is required for astronomy calculations.") from exc

    iers.conf.auto_download = False
    location_config = config["location"]
    forecast_config = config["forecast"]
    moments = time_grid(start, end, forecast_config["gridMinutes"])
    if not moments:
        return []

    location = EarthLocation(
        lat=location_config["latitude"] * u.deg,
        lon=location_config["longitude"] * u.deg,
        height=location_config["elevationMeters"] * u.m,
    )
    astropy_times = Time(moments)
    frame = AltAz(obstime=astropy_times, location=location)

    sun = get_sun(astropy_times)
    local_moon = get_body("moon", astropy_times, location)
    phase_moon = get_body("moon", astropy_times)
    sun_altitudes = sun.transform_to(frame).alt.deg
    moon_altitudes = local_moon.transform_to(frame).alt.deg
    elongations = sun.separation(phase_moon).deg

    points: list[AstroPoint] = []
    for index, moment in enumerate(moments):
        illumination = moon_illumination_percent_from_elongation(elongations[index])
        points.append(
            AstroPoint(
                time=moment,
                sun_altitude_degrees=float(sun_altitudes[index]),
                moon_altitude_degrees=float(moon_altitudes[index]),
                moon_illumination_percent=round(illumination, 1),
            )
        )
    return points


def darkness_summary(points: list[AstroPoint]) -> dict[str, bool]:
    return {
        "visualUsableOccurs": any(point.sun_altitude_degrees < -6 for point in points),
        "imagingUsableOccurs": any(point.sun_altitude_degrees < -12 for point in points),
        "astronomicalNightOccurs": any(point.sun_altitude_degrees < -18 for point in points),
    }


def moon_context(points: list[AstroPoint], start: datetime | None, end: datetime | None) -> dict[str, Any]:
    if not points:
        return {
            "illuminationPercent": 0,
            "aboveHorizon": False,
            "altitudeDegrees": 0,
            "context": "unavailable",
        }

    if start and end:
        midpoint = start + (end - start) / 2
        context = "bestWindowMidpoint"
    else:
        local_date = points[0].time.date()
        midpoint = datetime.combine(local_date, time(23, 59), tzinfo=points[0].time.tzinfo)
        context = "localMidnight"

    closest = min(points, key=lambda point: abs(point.time - midpoint))
    return {
        "illuminationPercent": round(closest.moon_illumination_percent, 1),
        "aboveHorizon": closest.moon_altitude_degrees > 0,
        "altitudeDegrees": round(closest.moon_altitude_degrees, 1),
        "context": context,
    }
