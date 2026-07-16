from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Sequence
from zoneinfo import ZoneInfo

from planner.astronomy import observing_bounds
from planner.lunar import (
    ILLUMINATION_WEIGHT,
    LUNAR_IMPACT_FIELDS,
    MOON_ALTITUDE_WEIGHT,
    SEPARATION_WEIGHT,
    MoonSampleGrid,
    build_moon_sample_grid,
    calculate_target_lunar_impact,
    lunar_impact_rating,
)
from planner.output import write_atomic_json


LOGGER = logging.getLogger(__name__)

ASTRONOMICAL_DARKNESS_DEG = -18.0
IMAGING_DARKNESS_DEG = -12.0
VISUAL_DARKNESS_DEG = -6.0

RATING_PRIORITY = {
    "unavailable": 0,
    "short": 1,
    "usable": 2,
    "good": 3,
    "excellent": 4,
}


class VisibilityError(RuntimeError):
    """Raised when visibility input or output cannot be processed safely."""


@dataclass(frozen=True)
class DarknessWindow:
    """A local, timezone-aware interval used for target calculations."""

    start: datetime | None
    end: datetime | None
    source: str
    sun_altitude_threshold_deg: float | None = None
    review_flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return (
            self.start is not None
            and self.end is not None
            and self.start.tzinfo is not None
            and self.end.tzinfo is not None
            and self.end.astimezone(UTC) > self.start.astimezone(UTC)
        )

    @property
    def minutes(self) -> int:
        if not self.is_valid or self.start is None or self.end is None:
            return 0
        return _elapsed_minutes(self.start, self.end)


def load_target_catalogue(path: str | Path) -> dict[str, Any]:
    """Load the normalized target catalogue without modifying it."""

    catalogue_path = Path(path)
    try:
        payload = json.loads(catalogue_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise VisibilityError(f"Could not read target catalogue: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise VisibilityError(f"Target catalogue is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("targets"), list):
        raise VisibilityError("Target catalogue must contain a targets array.")
    return payload


def load_darkness_windows(
    path: str | Path,
    timezone_name: str,
) -> dict[str, DarknessWindow]:
    """Load explicit darkness timestamps when forecast output provides them."""

    forecast_path = Path(path)
    if not forecast_path.exists():
        return {}
    try:
        payload = json.loads(forecast_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VisibilityError(f"Could not load forecast darkness windows: {exc}") from exc

    if not isinstance(payload, dict):
        raise VisibilityError("Forecast darkness input must be a JSON object.")

    windows: dict[str, DarknessWindow] = {}
    for night in payload.get("nights", []):
        if not isinstance(night, dict) or not isinstance(night.get("date"), str):
            continue
        values = _explicit_darkness_values(night)
        if values is None:
            continue
        raw_start, raw_end = values
        try:
            start = _parse_aware_timestamp(raw_start, timezone_name)
            end = _parse_aware_timestamp(raw_end, timezone_name)
            window = DarknessWindow(start, end, "forecast")
            if not window.is_valid:
                raise ValueError("end must be later than start")
        except (TypeError, ValueError) as exc:
            LOGGER.warning("Invalid forecast darkness window for %s: %s", night["date"], exc)
            window = DarknessWindow(
                None,
                None,
                "forecast",
                review_flags=("invalid_darkness_window",),
            )
        windows[night["date"]] = window
    return windows


def _explicit_darkness_values(night: dict[str, Any]) -> tuple[Any, Any] | None:
    scopes = [night]
    if isinstance(night.get("conditions"), dict):
        scopes.append(night["conditions"])
    key_pairs = [
        ("darkness_start", "darkness_end"),
        ("darknessStart", "darknessEnd"),
        ("usefulDarknessStart", "usefulDarknessEnd"),
        ("astronomicalDarknessStart", "astronomicalDarknessEnd"),
    ]
    for scope in scopes:
        for start_key, end_key in key_pairs:
            if start_key in scope or end_key in scope:
                return scope.get(start_key), scope.get(end_key)
    return None


def _parse_aware_timestamp(value: Any, timezone_name: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError("darkness timestamps must be strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("darkness timestamps must include a UTC offset")
    return parsed.astimezone(ZoneInfo(timezone_name))


def build_observation_times(
    start: datetime,
    end: datetime,
    interval_minutes: int,
) -> list[datetime]:
    """Build an inclusive time grid while preserving local UTC offsets."""

    if start.tzinfo is None or end.tzinfo is None:
        raise VisibilityError("Observation times must be timezone aware.")
    if end <= start:
        raise VisibilityError("Darkness end must be later than darkness start.")
    if interval_minutes <= 0:
        raise VisibilityError("Time step must be positive.")

    timezone = start.tzinfo
    current_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    step = timedelta(minutes=interval_minutes)
    moments: list[datetime] = []
    while current_utc <= end_utc:
        moments.append(current_utc.astimezone(timezone))
        current_utc += step
    if moments[-1].astimezone(UTC) != end_utc:
        moments.append(end_utc.astimezone(timezone))
    return moments


def _elapsed_minutes(start: datetime, end: datetime) -> int:
    """Measure real elapsed time across offset and daylight-saving changes."""

    return round(
        (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60
    )


def calculate_useful_darkness_window(
    evening_date: date,
    config: dict[str, Any],
) -> DarknessWindow:
    """Choose astronomical darkness, falling back to existing planner thresholds."""

    try:
        from astropy import units as u
        from astropy.coordinates import AltAz, EarthLocation, get_sun
        from astropy.time import Time
        from astropy.utils import iers
    except ImportError as exc:
        raise VisibilityError("Astropy is required for darkness calculations.") from exc

    iers.conf.auto_download = False
    timezone_name = config["location"]["timezone"]
    start, end = observing_bounds(evening_date, timezone_name)
    step_minutes = config["targetVisibility"]["timeStepMinutes"]
    moments = build_observation_times(start, end, step_minutes)
    location = _earth_location(config)
    frame = AltAz(obstime=Time(moments), location=location)
    sun_altitudes = [float(value) for value in get_sun(Time(moments)).transform_to(frame).alt.deg]

    imaging_minimum = config["limits"]["imagingCandidate"]["minimumMinutes"]
    visual_minimum = config["limits"]["visualCandidate"]["minimumMinutes"]
    choices = [
        (ASTRONOMICAL_DARKNESS_DEG, imaging_minimum),
        (IMAGING_DARKNESS_DEG, imaging_minimum),
        (VISUAL_DARKNESS_DEG, visual_minimum),
    ]
    existing: list[tuple[float, datetime, datetime]] = []
    for threshold, minimum_minutes in choices:
        interval = _longest_threshold_interval(moments, sun_altitudes, threshold)
        if interval is None:
            continue
        interval_start, interval_end = interval
        existing.append((threshold, interval_start, interval_end))
        minutes = _elapsed_minutes(interval_start, interval_end)
        if minutes >= minimum_minutes:
            return DarknessWindow(
                interval_start,
                interval_end,
                "calculated",
                sun_altitude_threshold_deg=threshold,
            )

    if existing:
        threshold, interval_start, interval_end = existing[0]
        return DarknessWindow(
            interval_start,
            interval_end,
            "calculated",
            sun_altitude_threshold_deg=threshold,
            review_flags=("darkness_too_short",),
        )
    return DarknessWindow(
        None,
        None,
        "calculated",
        review_flags=("invalid_darkness_window",),
    )


def _earth_location(config: dict[str, Any]) -> Any:
    from astropy import units as u
    from astropy.coordinates import EarthLocation

    location = config["location"]
    return EarthLocation(
        lat=location["latitude"] * u.deg,
        lon=location["longitude"] * u.deg,
        height=location["elevationMeters"] * u.m,
    )


def _longest_threshold_interval(
    moments: Sequence[datetime],
    values: Sequence[float],
    threshold: float,
) -> tuple[datetime, datetime] | None:
    if len(moments) != len(values):
        raise VisibilityError("Solar altitude samples do not match observation times.")
    segments: list[tuple[int, int]] = []
    start_index: int | None = None
    for index, value in enumerate(values):
        if value < threshold and start_index is None:
            start_index = index
        elif value >= threshold and start_index is not None:
            segments.append((start_index, index - 1))
            start_index = None
    if start_index is not None:
        segments.append((start_index, len(values) - 1))
    if not segments:
        return None
    first, last = max(
        segments,
        key=lambda indexes: (
            moments[indexes[1]].astimezone(UTC) - moments[indexes[0]].astimezone(UTC),
            -indexes[0],
        ),
    )
    return moments[first], moments[last]


def rate_visibility(observable_minutes: int, maximum_altitude_deg: float | None) -> str:
    """Rate target geometry independently of weather and Moon conditions."""

    if maximum_altitude_deg is None:
        return "unavailable"
    if observable_minutes < 0:
        raise ValueError("Observable minutes cannot be negative.")
    if observable_minutes == 0:
        return "short"
    if observable_minutes < 60:
        return "short"
    if observable_minutes <= 120:
        return "usable"
    if maximum_altitude_deg >= 60:
        return "excellent"
    return "good"


def calculate_visibility_from_altitudes(
    target_id: str,
    moments: Sequence[datetime],
    altitudes_deg: Sequence[float],
    minimum_altitude_deg: float,
) -> dict[str, Any]:
    """Build a visibility record from deterministic altitude samples."""

    if not moments or len(moments) != len(altitudes_deg):
        raise VisibilityError("Target altitude samples do not match observation times.")
    if any(moment.tzinfo is None for moment in moments):
        raise VisibilityError("Target observation times must be timezone aware.")
    if any(not isfinite(float(altitude)) for altitude in altitudes_deg):
        raise VisibilityError("Target altitude samples must be finite.")

    maximum_index = max(range(len(altitudes_deg)), key=lambda index: altitudes_deg[index])
    visible_indexes = [
        index
        for index, altitude in enumerate(altitudes_deg)
        if altitude >= minimum_altitude_deg
    ]
    observable = bool(visible_indexes)
    if observable:
        first = visible_indexes[0]
        last = visible_indexes[-1]
        observable_minutes = _elapsed_minutes(moments[first], moments[last])
        window_start = moments[first].isoformat()
        window_end = moments[last].isoformat()
        review_flags: list[str] = []
        rating = rate_visibility(observable_minutes, float(altitudes_deg[maximum_index]))
    else:
        observable_minutes = 0
        window_start = None
        window_end = None
        review_flags = ["never_above_threshold"]
        rating = "unavailable"

    return {
        "target_id": target_id,
        "observable": observable,
        "window_start": window_start,
        "window_end": window_end,
        "observable_minutes": observable_minutes,
        "maximum_altitude_deg": round(float(altitudes_deg[maximum_index]), 1),
        "maximum_altitude_time": moments[maximum_index].isoformat(),
        "altitude_at_darkness_start_deg": round(float(altitudes_deg[0]), 1),
        "altitude_at_darkness_end_deg": round(float(altitudes_deg[-1]), 1),
        "altitude_samples": [
            {
                "time": moment.isoformat(),
                "altitude_deg": round(float(altitude), 1),
            }
            for moment, altitude in zip(moments, altitudes_deg)
        ],
        "visibility_rating": rating,
        "review_flags": review_flags,
    }


def calculate_target_visibility(
    target: dict[str, Any],
    moments: Sequence[datetime],
    location: Any,
    minimum_altitude_deg: float,
) -> dict[str, Any]:
    """Transform one ICRS/J2000 target to local AltAz samples."""

    target_id = _target_id(target)
    coordinates = target.get("coordinates")
    if not isinstance(coordinates, dict):
        LOGGER.warning("Target %s is missing coordinates.", target_id)
        return _unavailable_record(target_id, "missing_coordinates")

    try:
        ra_deg = float(coordinates["ra_deg"])
        dec_deg = float(coordinates["dec_deg"])
        if not isfinite(ra_deg) or not isfinite(dec_deg):
            raise ValueError("coordinates must be finite")
        if not 0 <= ra_deg < 360 or not -90 <= dec_deg <= 90:
            raise ValueError("coordinates are outside ICRS degree ranges")
        if coordinates.get("frame", "ICRS").upper() != "ICRS":
            raise ValueError("coordinate frame is not ICRS")
        if coordinates.get("equinox", "J2000").upper() != "J2000":
            raise ValueError("coordinate equinox is not J2000")
    except (KeyError, TypeError, ValueError) as exc:
        LOGGER.warning("Target %s has invalid coordinates: %s", target_id, exc)
        return _unavailable_record(target_id, "invalid_coordinates")

    from astropy import units as u
    from astropy.coordinates import AltAz, SkyCoord
    from astropy.time import Time

    target_coordinate = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    frame = AltAz(obstime=Time(list(moments)), location=location)
    altitudes = target_coordinate.transform_to(frame).alt.deg
    return calculate_visibility_from_altitudes(
        target_id,
        moments,
        [float(value) for value in altitudes],
        minimum_altitude_deg,
    )


def _target_id(target: dict[str, Any], index: int | None = None) -> str:
    value = target.get("id") if isinstance(target, dict) else None
    if isinstance(value, str) and value.strip():
        return value
    return f"unknown-target-{(index + 1) if index is not None else 1}"


def _unavailable_record(target_id: str, flag: str) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "observable": False,
        "window_start": None,
        "window_end": None,
        "observable_minutes": 0,
        "maximum_altitude_deg": None,
        "maximum_altitude_time": None,
        "altitude_at_darkness_start_deg": None,
        "altitude_at_darkness_end_deg": None,
        "altitude_samples": [],
        "visibility_rating": "unavailable",
        "review_flags": [flag],
    }


def build_nightly_visibility(
    evening_date: date,
    darkness: DarknessWindow,
    targets: Sequence[dict[str, Any]],
    config: dict[str, Any],
    *,
    calculator: Callable[[dict[str, Any], Sequence[datetime], Any, float], dict[str, Any]] = calculate_target_visibility,
    moon_grid_builder: Callable[[Sequence[datetime], Any], MoonSampleGrid] = build_moon_sample_grid,
) -> dict[str, Any]:
    """Calculate Stage 4A visibility and Stage 4B Moon impact for one night."""

    settings = config["targetVisibility"]
    records: list[tuple[dict[str, Any], str]] = []
    if darkness.is_valid and darkness.start is not None and darkness.end is not None:
        moments = build_observation_times(
            darkness.start,
            darkness.end,
            settings["timeStepMinutes"],
        )
        location = _earth_location(config)
        moon_grid = moon_grid_builder(moments, location)
    else:
        moments = []
        location = None
        moon_grid = None

    for index, raw_target in enumerate(targets):
        target = raw_target if isinstance(raw_target, dict) else {}
        target_id = _target_id(target, index)
        display_name = str(target.get("display_name") or target_id)
        if not darkness.is_valid:
            record = _unavailable_record(target_id, "invalid_darkness_window")
        else:
            try:
                record = calculator(
                    target,
                    moments,
                    location,
                    float(settings["minimumAltitudeDegrees"]),
                )
            except Exception as exc:  # keep malformed individual targets isolated
                LOGGER.warning("Visibility calculation failed for %s: %s", target_id, exc)
                record = _unavailable_record(target_id, "calculation_error")
        for flag in darkness.review_flags:
            if flag not in record["review_flags"]:
                record["review_flags"].append(flag)
        try:
            record["moon"] = calculate_target_lunar_impact(target, record, moon_grid)
        except Exception as exc:  # keep malformed individual targets isolated
            LOGGER.warning("Lunar calculation failed for %s: %s", target_id, exc)
            record["moon"] = calculate_target_lunar_impact(target, record, None)
            if "lunar_calculation_error" not in record["review_flags"]:
                record["review_flags"].append("lunar_calculation_error")
        records.append((record, display_name))

    records.sort(key=_target_sort_key)
    return {
        "date": evening_date.isoformat(),
        "darkness_start": darkness.start.isoformat() if darkness.start else None,
        "darkness_end": darkness.end.isoformat() if darkness.end else None,
        "darkness_minutes": darkness.minutes,
        "darkness_definition": (
            {"source": darkness.source, "sun_altitude_threshold_deg": darkness.sun_altitude_threshold_deg}
            if darkness.sun_altitude_threshold_deg is not None
            else {"source": darkness.source}
        ),
        "moon": {
            "illumination_percent": (
                round(moon_grid.night_illumination_percent, 1) if moon_grid is not None else None
            )
        },
        "targets": [record for record, _ in records],
    }


def _target_sort_key(item: tuple[dict[str, Any], str]) -> tuple[Any, ...]:
    record, display_name = item
    return (
        -int(bool(record["observable"])),
        -RATING_PRIORITY.get(record["visibility_rating"], -1),
        -int(record.get("observable_minutes") or 0),
        -float(record.get("maximum_altitude_deg") or -90),
        display_name.casefold(),
        record["target_id"],
    )


def build_visibility_payload(
    config: dict[str, Any],
    generated_at: datetime,
    nights: list[dict[str, Any]],
    forecast_days: int,
) -> dict[str, Any]:
    """Build the stable Stage 4A/4B output envelope."""

    if generated_at.tzinfo is None:
        raise VisibilityError("Generated timestamp must be timezone aware.")
    location = config["location"]
    settings = config["targetVisibility"]
    return {
        "schema_version": "0.3",
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "calculation_settings": {
            "minimum_altitude_deg": float(settings["minimumAltitudeDegrees"]),
            "time_step_minutes": settings["timeStepMinutes"],
            "forecast_days": forecast_days,
            "lunar_impact_heuristic": {
                "separation_weight": SEPARATION_WEIGHT,
                "illumination_weight": ILLUMINATION_WEIGHT,
                "moon_altitude_weight": MOON_ALTITUDE_WEIGHT,
            },
        },
        "location": {
            "name": location["name"],
            "latitude_deg": location["latitude"],
            "longitude_deg": location["longitude"],
            "elevation_m": location["elevationMeters"],
            "timezone": location["timezone"],
        },
        "nights": nights,
    }


def validate_visibility_output(payload: dict[str, Any]) -> None:
    """Validate the stable Stage 4A/4B output without modifying it."""

    nights = payload.get("nights")
    if not isinstance(nights, list):
        raise VisibilityError("Visibility output must contain a nights array.")
    _validate_finite_numbers(payload)
    expected_targets: int | None = None
    for night in nights:
        if not isinstance(night, dict) or not isinstance(night.get("targets"), list):
            raise VisibilityError("Every visibility night must contain a targets array.")
        night_moon = night.get("moon")
        if not isinstance(night_moon, dict):
            raise VisibilityError("Every visibility night must contain Moon context.")
        illumination = night_moon.get("illumination_percent")
        if illumination is not None and (
            isinstance(illumination, bool)
            or not isinstance(illumination, (int, float))
            or not 0 <= illumination <= 100
        ):
            raise VisibilityError("Nightly Moon illumination must be between 0 and 100.")
        if expected_targets is None:
            expected_targets = len(night["targets"])
        elif len(night["targets"]) != expected_targets:
            raise VisibilityError("Every night must contain one record per target.")
        for target in night["targets"]:
            moon = target.get("moon") if isinstance(target, dict) else None
            if not isinstance(moon, dict) or any(field not in moon for field in LUNAR_IMPACT_FIELDS):
                raise VisibilityError("Every target must contain complete lunar-impact fields.")
            score = moon["lunar_impact_score"]
            rating = moon["lunar_impact_rating"]
            if score is None:
                if rating is not None:
                    raise VisibilityError("An unavailable lunar score cannot have a rating.")
            elif (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not 0 <= score <= 100
                or rating != lunar_impact_rating(float(score))
            ):
                raise VisibilityError("Target lunar score or rating is invalid.")


def write_visibility_output(payload: dict[str, Any], destination: str | Path) -> None:
    """Atomically write visibility JSON after basic schema validation."""

    validate_visibility_output(payload)
    write_atomic_json(payload, destination)


def _validate_finite_numbers(value: Any, path: str = "root") -> None:
    if isinstance(value, float) and not isfinite(value):
        raise VisibilityError(f"Visibility output contains a non-finite number at {path}.")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_numbers(child, f"{path}[{index}]")
