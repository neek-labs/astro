from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from typing import Any, Sequence

from planner.astronomy import moon_illumination_percent_from_elongation


SEPARATION_COMPONENT_POINTS = (
    (0.0, 0.0),
    (30.0, 20.0),
    (60.0, 50.0),
    (90.0, 80.0),
    (120.0, 100.0),
)
MOON_ALTITUDE_COMPONENT_POINTS = (
    (0.0, 100.0),
    (15.0, 75.0),
    (30.0, 50.0),
    (60.0, 25.0),
    (90.0, 0.0),
)
SEPARATION_WEIGHT = 0.50
ILLUMINATION_WEIGHT = 0.30
MOON_ALTITUDE_WEIGHT = 0.20
LUNAR_IMPACT_FIELDS = (
    "moon_above_horizon_during_observable_window",
    "moon_altitude_at_darkness_start_deg",
    "moon_altitude_at_target_peak_deg",
    "moon_altitude_at_observable_midpoint_deg",
    "moon_separation_at_darkness_start_deg",
    "moon_separation_at_target_peak_deg",
    "moon_separation_at_observable_midpoint_deg",
    "minimum_moon_separation_deg",
    "time_of_minimum_moon_separation",
    "lunar_impact_score",
    "lunar_impact_rating",
)


class LunarCalculationError(RuntimeError):
    """Raised when lunar geometry cannot be calculated safely."""


@dataclass(frozen=True)
class MoonSampleGrid:
    """Moon geometry calculated once for a nightly Stage 4A timestamp grid."""

    moments_utc: tuple[datetime, ...]
    coordinates: Any
    altitudes_deg: tuple[float, ...]
    illumination_percent: tuple[float, ...]

    def __post_init__(self) -> None:
        count = len(self.moments_utc)
        if not count or len(self.altitudes_deg) != count or len(self.illumination_percent) != count:
            raise LunarCalculationError("Moon samples must have matching non-empty arrays.")
        if any(moment.tzinfo is None for moment in self.moments_utc):
            raise LunarCalculationError("Moon sample timestamps must be timezone aware.")
        if any(not isfinite(value) for value in (*self.altitudes_deg, *self.illumination_percent)):
            raise LunarCalculationError("Moon samples must contain finite numbers.")

    @property
    def night_illumination_percent(self) -> float:
        midpoint = self.moments_utc[0] + (self.moments_utc[-1] - self.moments_utc[0]) / 2
        return self.illumination_percent[self.nearest_index(midpoint)]

    def nearest_index(self, moment: datetime) -> int:
        if moment.tzinfo is None:
            raise LunarCalculationError("Lunar lookup timestamps must be timezone aware.")
        moment_utc = moment.astimezone(UTC)
        return min(
            range(len(self.moments_utc)),
            key=lambda index: abs(self.moments_utc[index] - moment_utc),
        )


def build_moon_sample_grid(moments: Sequence[datetime], location: Any) -> MoonSampleGrid:
    """Vectorize Moon positions, altitudes, and illumination over one night."""

    if not moments or any(moment.tzinfo is None for moment in moments):
        raise LunarCalculationError("Moon calculations require timezone-aware timestamps.")

    try:
        from astropy.coordinates import AltAz, get_body, get_sun
        from astropy.time import Time
        from astropy.utils import iers
    except ImportError as exc:
        raise LunarCalculationError("Astropy is required for lunar calculations.") from exc

    iers.conf.auto_download = False
    moments_utc = tuple(moment.astimezone(UTC) for moment in moments)
    astropy_times = Time(list(moments_utc))
    local_moon = get_body("moon", astropy_times, location)
    phase_moon = get_body("moon", astropy_times)
    altitudes = local_moon.transform_to(AltAz(obstime=astropy_times, location=location)).alt.deg
    elongations = get_sun(astropy_times).separation(phase_moon).deg
    illuminations = tuple(
        moon_illumination_percent_from_elongation(float(value)) for value in elongations
    )
    return MoonSampleGrid(
        moments_utc=moments_utc,
        coordinates=local_moon,
        altitudes_deg=tuple(float(value) for value in altitudes),
        illumination_percent=illuminations,
    )


def linear_interpolate(value: float, points: Sequence[tuple[float, float]]) -> float:
    """Interpolate a clamped value over ascending (input, output) control points."""

    if not isfinite(value) or len(points) < 2:
        raise ValueError("Interpolation requires a finite value and at least two points.")
    if any(points[index][0] >= points[index + 1][0] for index in range(len(points) - 1)):
        raise ValueError("Interpolation input points must be strictly increasing.")
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    raise AssertionError("Clamped interpolation did not find a segment.")


def separation_component(separation_deg: float) -> float:
    return linear_interpolate(separation_deg, SEPARATION_COMPONENT_POINTS)


def moon_altitude_component(altitude_deg: float) -> float:
    return linear_interpolate(altitude_deg, MOON_ALTITUDE_COMPONENT_POINTS)


def calculate_lunar_impact_score(
    *,
    moon_above_horizon: bool,
    minimum_separation_deg: float | None,
    illumination_percent: float,
    representative_moon_altitude_deg: float | None,
) -> float | None:
    """Calculate the tunable Stage 4B heuristic; higher is less interference."""

    if not moon_above_horizon:
        return 100.0
    if minimum_separation_deg is None or representative_moon_altitude_deg is None:
        return None
    if not 0.0 <= illumination_percent <= 100.0:
        raise ValueError("Moon illumination must be between 0 and 100 percent.")
    score = (
        separation_component(minimum_separation_deg) * SEPARATION_WEIGHT
        + (100.0 - illumination_percent) * ILLUMINATION_WEIGHT
        + moon_altitude_component(representative_moon_altitude_deg) * MOON_ALTITUDE_WEIGHT
    )
    return max(0.0, min(100.0, score))


def lunar_impact_rating(score: float) -> str:
    if not 0.0 <= score <= 100.0:
        raise ValueError("Lunar impact score must be between 0 and 100.")
    if score >= 85.0:
        return "excellent"
    if score >= 70.0:
        return "good"
    if score >= 50.0:
        return "moderate"
    if score >= 25.0:
        return "poor"
    return "severe"


def angular_separations_deg(target_coordinate: Any, moon_coordinates: Any) -> list[float]:
    """Use Astropy coordinate separation and return finite degree values."""

    target_in_moon_frame = target_coordinate.transform_to(moon_coordinates.frame)
    values = target_in_moon_frame.separation(moon_coordinates).deg
    separations = [float(value) for value in values] if getattr(values, "ndim", 0) else [float(values)]
    if any(not isfinite(value) for value in separations):
        raise LunarCalculationError("Moon-to-target separations must be finite.")
    return separations


def calculate_target_lunar_impact(
    target: dict[str, Any],
    visibility: dict[str, Any],
    grid: MoonSampleGrid | None,
) -> dict[str, Any]:
    """Enrich one Stage 4A record without independently rebuilding its window."""

    result = _empty_lunar_impact()
    if grid is None:
        return result

    result["moon_altitude_at_darkness_start_deg"] = round(grid.altitudes_deg[0], 1)
    observable_indexes = _observable_indexes(visibility, grid)
    result["moon_above_horizon_during_observable_window"] = any(
        grid.altitudes_deg[index] > 0.0 for index in observable_indexes
    )

    peak_index = _optional_time_index(visibility.get("maximum_altitude_time"), grid)
    midpoint_index = _observable_midpoint_index(observable_indexes, grid)
    if peak_index is not None:
        result["moon_altitude_at_target_peak_deg"] = round(grid.altitudes_deg[peak_index], 1)
    if midpoint_index is not None:
        result["moon_altitude_at_observable_midpoint_deg"] = round(
            grid.altitudes_deg[midpoint_index], 1
        )

    target_coordinate = _target_coordinate(target)
    if target_coordinate is None:
        return result
    separations = angular_separations_deg(target_coordinate, grid.coordinates)
    result["moon_separation_at_darkness_start_deg"] = round(separations[0], 1)
    if peak_index is not None:
        result["moon_separation_at_target_peak_deg"] = round(separations[peak_index], 1)
    if midpoint_index is not None:
        result["moon_separation_at_observable_midpoint_deg"] = round(
            separations[midpoint_index], 1
        )
    if not observable_indexes:
        return result

    minimum_index = min(observable_indexes, key=lambda index: separations[index])
    minimum_separation = separations[minimum_index]
    result["minimum_moon_separation_deg"] = round(minimum_separation, 1)
    result["time_of_minimum_moon_separation"] = _utc_isoformat(grid.moments_utc[minimum_index])
    score = calculate_lunar_impact_score(
        moon_above_horizon=result["moon_above_horizon_during_observable_window"],
        minimum_separation_deg=minimum_separation,
        illumination_percent=grid.night_illumination_percent,
        representative_moon_altitude_deg=grid.altitudes_deg[midpoint_index],
    )
    if score is not None:
        rounded_score = round(score, 1)
        result["lunar_impact_score"] = rounded_score
        result["lunar_impact_rating"] = lunar_impact_rating(rounded_score)
    return result


def _target_coordinate(target: dict[str, Any]) -> Any | None:
    coordinates = target.get("coordinates")
    if not isinstance(coordinates, dict):
        return None
    try:
        ra_deg = float(coordinates["ra_deg"])
        dec_deg = float(coordinates["dec_deg"])
        if not isfinite(ra_deg) or not isfinite(dec_deg):
            return None
        if not 0 <= ra_deg < 360 or not -90 <= dec_deg <= 90:
            return None
        if coordinates.get("frame", "ICRS").upper() != "ICRS":
            return None
        if coordinates.get("equinox", "J2000").upper() != "J2000":
            return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return None

    from astropy import units as u
    from astropy.coordinates import SkyCoord

    return SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")


def _observable_indexes(visibility: dict[str, Any], grid: MoonSampleGrid) -> list[int]:
    if not visibility.get("observable"):
        return []
    start = _parse_timestamp(visibility.get("window_start"))
    end = _parse_timestamp(visibility.get("window_end"))
    if start is None or end is None:
        return []
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    return [
        index
        for index, moment in enumerate(grid.moments_utc)
        if start_utc <= moment <= end_utc
    ]


def _observable_midpoint_index(indexes: Sequence[int], grid: MoonSampleGrid) -> int | None:
    if not indexes:
        return None
    midpoint = grid.moments_utc[indexes[0]] + (
        grid.moments_utc[indexes[-1]] - grid.moments_utc[indexes[0]]
    ) / 2
    return min(indexes, key=lambda index: abs(grid.moments_utc[index] - midpoint))


def _optional_time_index(value: Any, grid: MoonSampleGrid) -> int | None:
    moment = _parse_timestamp(value)
    return grid.nearest_index(moment) if moment is not None else None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _utc_isoformat(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _empty_lunar_impact() -> dict[str, Any]:
    return {
        "moon_above_horizon_during_observable_window": False,
        "moon_altitude_at_darkness_start_deg": None,
        "moon_altitude_at_target_peak_deg": None,
        "moon_altitude_at_observable_midpoint_deg": None,
        "moon_separation_at_darkness_start_deg": None,
        "moon_separation_at_target_peak_deg": None,
        "moon_separation_at_observable_midpoint_deg": None,
        "minimum_moon_separation_deg": None,
        "time_of_minimum_moon_separation": None,
        "lunar_impact_score": None,
        "lunar_impact_rating": None,
    }
