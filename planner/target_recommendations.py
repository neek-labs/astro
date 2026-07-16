from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from planner.output import OutputError, validate_output


DURATION_COMPONENT_POINTS = (
    (0.0, 0.0),
    (30.0, 20.0),
    (60.0, 50.0),
    (120.0, 80.0),
    (180.0, 100.0),
)
ALTITUDE_COMPONENT_POINTS = (
    (25.0, 0.0),
    (35.0, 35.0),
    (45.0, 65.0),
    (60.0, 90.0),
    (75.0, 100.0),
)
WAIT_COMPONENT_POINTS = (
    (0.0, 100.0),
    (30.0, 75.0),
    (60.0, 50.0),
    (120.0, 0.0),
)
MAXIMUM_ALTITUDE_SHARE = 0.60
REPRESENTATIVE_ALTITUDE_SHARE = 0.40
TIMING_PEAK_SHARE = 0.40
TIMING_WINDOW_COVERAGE_SHARE = 0.40
TIMING_WAIT_SHARE = 0.20
NEUTRAL_CATALOGUE_PRIORITY = 50.0


class TargetRecommendationError(RuntimeError):
    """Raised when Stage 4C inputs or output are incompatible or unsafe."""


@dataclass(frozen=True)
class WindowOverlap:
    start: datetime
    end: datetime
    minutes: int


def load_json_object(path: str | Path, label: str) -> dict[str, Any]:
    input_path = Path(path)
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TargetRecommendationError(f"Could not read {label}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TargetRecommendationError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TargetRecommendationError(f"{label} must contain a JSON object.")
    return payload


def linear_interpolate(value: float, points: Sequence[tuple[float, float]]) -> float:
    if not isfinite(value) or len(points) < 2:
        raise ValueError("Interpolation requires a finite value and at least two points.")
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if right_x <= left_x:
            raise ValueError("Interpolation points must be strictly increasing.")
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    raise AssertionError("Clamped interpolation did not find a segment.")


def calculate_overlap(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> WindowOverlap | None:
    moments = (first_start, first_end, second_start, second_end)
    if any(moment.tzinfo is None for moment in moments):
        raise ValueError("Overlap calculations require timezone-aware timestamps.")
    start = max((first_start, second_start), key=lambda moment: moment.astimezone(UTC))
    end = min((first_end, second_end), key=lambda moment: moment.astimezone(UTC))
    if end.astimezone(UTC) <= start.astimezone(UTC):
        return None
    minutes = _elapsed_minutes(start, end)
    return WindowOverlap(start=start, end=end, minutes=minutes) if minutes > 0 else None


def recommendation_rating(score: float) -> str:
    if not 0 <= score <= 100:
        raise ValueError("Recommendation score must be between 0 and 100.")
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "moderate"
    if score >= 25:
        return "weak"
    return "poor"


def target_class_adjustment(
    target: dict[str, Any], maximum_points: float
) -> tuple[float, str | None]:
    object_type = target.get("object_type")
    imaging_mode = target.get("imaging_mode")
    if not isinstance(object_type, str):
        return 0.0, None
    normalized_type = object_type.casefold()
    normalized_mode = imaging_mode.casefold() if isinstance(imaging_mode, str) else ""

    if normalized_mode == "narrowband" and "emission" in normalized_type:
        adjustment = min(5.0, maximum_points)
        return adjustment, (
            "Emission target with validated narrowband metadata; comparatively tolerant "
            "of lunar brightness."
        )
    if "galaxy" in normalized_type or normalized_type == "reflection_nebula":
        adjustment = -min(5.0, maximum_points)
        return adjustment, (
            "Broadband galaxy or reflection nebula; comparatively sensitive to lunar brightness."
        )
    if normalized_type in {"globular_cluster", "planetary_nebula"}:
        adjustment = min(3.0, maximum_points)
        return adjustment, "Bright compact target class; modestly tolerant of lunar brightness."
    return 0.0, None


def enrich_forecast_payload(
    forecast: dict[str, Any],
    visibility: dict[str, Any],
    catalogue: dict[str, Any],
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Join Stage 2/4 data and return a copied forecast plus CLI summaries."""

    try:
        validate_output(forecast)
    except OutputError as exc:
        raise TargetRecommendationError(f"Forecast schema is incompatible: {exc}") from exc
    schema_version = visibility.get("schema_version")
    if schema_version not in {"0.2", "0.3"} or not isinstance(visibility.get("nights"), list):
        raise TargetRecommendationError("Visibility input must use Stage 4B schema 0.2 or 0.3.")
    if not isinstance(catalogue.get("targets"), list):
        raise TargetRecommendationError("Catalogue input must contain a targets array.")

    catalogue_by_id, catalogue_review_flags = _index_individual_records(
        catalogue["targets"], "id", "catalogue_target"
    )
    visibility_by_date = _unique_index(visibility["nights"], "date", "visibility night")
    _unique_index(forecast["nights"], "date", "forecast night")

    enriched = copy.deepcopy(forecast)
    summaries: list[dict[str, Any]] = []
    for night in enriched["nights"]:
        date_value = night["date"]
        result, summary = recommend_targets_for_night(
            night,
            visibility_by_date.get(date_value),
            catalogue_by_id,
            config,
            base_review_flags=catalogue_review_flags,
        )
        night["targetRecommendations"] = result
        top_targets = result["topTargets"]
        night["suggestedTarget"] = (
            top_targets[0]["displayName"] if top_targets else "No observing target recommended"
        )
        night["suggestedEquipment"] = "Equipment matching is not yet implemented."
        summaries.append(summary)

    validate_enriched_output(enriched)
    return enriched, summaries


def recommend_targets_for_night(
    weather_night: dict[str, Any],
    visibility_night: dict[str, Any] | None,
    catalogue_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
    *,
    base_review_flags: Sequence[str] = (),
) -> tuple[dict[str, Any], dict[str, Any]]:
    date_value = str(weather_night.get("date") or "unknown")
    level = weather_night.get("recommendation", {}).get("level")
    label = weather_night.get("recommendation", {}).get("label")
    summary = {
        "date": date_value,
        "weather": label,
        "candidates_evaluated": 0,
        "eligible_candidates": 0,
        "top_targets": [],
    }
    if level == "poor":
        return _recommendation_result(
            "weatherBlocked",
            "Weather prevents a meaningful target recommendation for this night.",
            [],
            [],
            0,
            0,
        ), summary
    if not isinstance(visibility_night, dict) or not isinstance(
        visibility_night.get("targets"), list
    ):
        return _recommendation_result(
            "unavailable",
            "Stage 4A/4B visibility input is unavailable for this date.",
            [],
            ["missing_visibility_night"],
            0,
            0,
        ), summary

    conditions = weather_night.get("conditions")
    best_start = _parse_timestamp(conditions.get("bestWindowStart") if isinstance(conditions, dict) else None)
    best_end = _parse_timestamp(conditions.get("bestWindowEnd") if isinstance(conditions, dict) else None)
    if (
        best_start is None
        or best_end is None
        or best_end.astimezone(UTC) <= best_start.astimezone(UTC)
    ):
        return _recommendation_result(
            "unavailable",
            "Structured best-window timestamps are unavailable for this night.",
            [],
            ["missing_best_window_timestamps"],
            len(visibility_night["targets"]),
            0,
        ), summary

    visibility_by_id, visibility_review_flags = _index_individual_records(
        visibility_night["targets"], "target_id", "visibility_target"
    )
    candidates: list[dict[str, Any]] = []
    review_flags = [*base_review_flags, *visibility_review_flags]
    summary["candidates_evaluated"] = len(visibility_by_id)
    for target_id, visibility_target in visibility_by_id.items():
        catalogue_target = catalogue_by_id.get(target_id)
        if catalogue_target is None:
            review_flags.append(f"unknown_catalogue_target:{target_id}")
            continue
        try:
            candidate = _build_candidate(
                weather_night,
                visibility_target,
                catalogue_target,
                best_start,
                best_end,
                config,
            )
        except (KeyError, TypeError, ValueError) as exc:
            review_flags.append(f"malformed_target:{target_id}:{exc}")
            continue
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=_candidate_sort_key)
    maximum = config["targetRecommendations"]["maximumResultsPerNight"]
    top_targets = candidates[:maximum]
    for rank, candidate in enumerate(top_targets, start=1):
        candidate["rank"] = rank
    summary["eligible_candidates"] = len(candidates)
    summary["top_targets"] = [
        {"display_name": target["displayName"], "score": target["recommendationScore"]}
        for target in top_targets
    ]

    if not top_targets:
        status = "noCandidates"
        message = "No target has enough observable overlap with the best weather window."
    elif level == "visual":
        status = "available"
        message = (
            f"{len(top_targets)} opportunistic visual target candidate"
            f"{'s are' if len(top_targets) != 1 else ' is'} well placed during the usable window."
        )
    else:
        status = "available"
        message = (
            f"{len(top_targets)} target recommendation"
            f"{'s are' if len(top_targets) != 1 else ' is'} well placed during the best observing window."
        )
    return _recommendation_result(
        status,
        message,
        top_targets,
        review_flags,
        len(visibility_by_id),
        len(candidates),
    ), summary


def _build_candidate(
    weather_night: dict[str, Any],
    visibility_target: dict[str, Any],
    catalogue_target: dict[str, Any],
    best_start: datetime,
    best_end: datetime,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    if visibility_target.get("observable") is not True:
        return None
    observable_minutes = _finite_number(visibility_target.get("observable_minutes"))
    maximum_altitude = _finite_number(visibility_target.get("maximum_altitude_deg"))
    lunar = visibility_target.get("moon")
    lunar_score = _finite_number(lunar.get("lunar_impact_score") if isinstance(lunar, dict) else None)
    if observable_minutes is None or observable_minutes <= 0 or maximum_altitude is None:
        return None
    if not -90 <= maximum_altitude <= 90:
        raise ValueError("maximum altitude is outside the valid range")
    if lunar_score is None or not 0 <= lunar_score <= 100:
        return None

    target_start = _parse_timestamp(visibility_target.get("window_start"))
    target_end = _parse_timestamp(visibility_target.get("window_end"))
    if target_start is None or target_end is None:
        return None
    overlap = calculate_overlap(target_start, target_end, best_start, best_end)
    minimum_overlap = config["targetRecommendations"]["minimumUsableOverlapMinutes"]
    if overlap is None or overlap.minutes < minimum_overlap:
        return None

    overlap_start_utc = overlap.start.astimezone(UTC)
    overlap_end_utc = overlap.end.astimezone(UTC)
    overlap_midpoint = (
        overlap_start_utc + (overlap_end_utc - overlap_start_utc) / 2
    ).astimezone(overlap.start.tzinfo)
    representative_altitude = _altitude_near(
        visibility_target.get("altitude_samples"), overlap_midpoint
    )
    warnings: list[str] = []
    if representative_altitude is None:
        representative_altitude = maximum_altitude
        warnings.append(
            "Representative altitude sample is unavailable; maximum altitude was used."
        )

    overlap_component = linear_interpolate(overlap.minutes, DURATION_COMPONENT_POINTS)
    maximum_altitude_component = linear_interpolate(maximum_altitude, ALTITUDE_COMPONENT_POINTS)
    representative_component = linear_interpolate(
        representative_altitude, ALTITUDE_COMPONENT_POINTS
    )
    altitude_component = (
        maximum_altitude_component * MAXIMUM_ALTITUDE_SHARE
        + representative_component * REPRESENTATIVE_ALTITUDE_SHARE
    )
    peak_time = _parse_timestamp(visibility_target.get("maximum_altitude_time"))
    peak_inside = peak_time is not None and _within(peak_time, overlap.start, overlap.end)
    weather_window_minutes = _elapsed_minutes(best_start, best_end)
    weather_coverage = min(100.0, overlap.minutes / weather_window_minutes * 100)
    wait_minutes = max(0.0, _elapsed_minutes(best_start, overlap.start))
    timing_component = (
        (100.0 if peak_inside else 50.0) * TIMING_PEAK_SHARE
        + weather_coverage * TIMING_WINDOW_COVERAGE_SHARE
        + linear_interpolate(wait_minutes, WAIT_COMPONENT_POINTS) * TIMING_WAIT_SHARE
    )

    weights = config["targetRecommendations"]["weights"]
    components = {
        "usableWindowOverlap": overlap_component,
        "altitudeQuality": altitude_component,
        "lunarImpact": lunar_score,
        "timingConvenience": timing_component,
        "cataloguePriority": NEUTRAL_CATALOGUE_PRIORITY,
    }
    base_score = sum(components[name] * weights[name] / 100 for name in components)
    adjustment, adjustment_reason = target_class_adjustment(
        catalogue_target,
        float(config["targetRecommendations"]["targetClassAdjustmentMaximumPoints"]),
    )
    final_score = round(max(0.0, min(100.0, base_score + adjustment)), 1)
    rounded_base = round(max(0.0, min(100.0, base_score)), 1)

    reasons = _build_reasons(
        overlap,
        maximum_altitude,
        peak_time,
        peak_inside,
        lunar,
        weather_night,
        config["location"]["timezone"],
    )
    _extend_warnings(
        warnings,
        overlap,
        representative_altitude,
        wait_minutes,
        lunar,
        weather_night,
    )
    target_type = _display_target_type(catalogue_target.get("object_type"))
    return {
        "rank": 0,
        "targetId": catalogue_target["id"],
        "displayName": str(catalogue_target.get("display_name") or catalogue_target["id"]),
        "primaryCatalogId": str(
            catalogue_target.get("primary_catalog_id") or catalogue_target["id"]
        ),
        "targetType": target_type,
        "recommendationScore": final_score,
        "baseRecommendationScore": rounded_base,
        "recommendationRating": recommendation_rating(final_score),
        "usableWindowOverlapStart": overlap.start.isoformat(),
        "usableWindowOverlapEnd": overlap.end.isoformat(),
        "usableWindowOverlapMinutes": overlap.minutes,
        "maximumAltitudeDeg": round(maximum_altitude, 1),
        "representativeAltitudeDeg": round(representative_altitude, 1),
        "maximumAltitudeTime": visibility_target.get("maximum_altitude_time"),
        "lunarImpactScore": round(lunar_score, 1),
        "lunarImpactRating": lunar.get("lunar_impact_rating"),
        "scoreBreakdown": {
            **{name: round(value, 1) for name, value in components.items()},
            "targetClassAdjustment": round(adjustment, 1),
        },
        "targetClassAdjustmentReason": adjustment_reason,
        "reasons": reasons,
        "warnings": warnings,
    }


def _build_reasons(
    overlap: WindowOverlap,
    maximum_altitude: float,
    peak_time: datetime | None,
    peak_inside: bool,
    lunar: dict[str, Any],
    weather_night: dict[str, Any],
    timezone_name: str,
) -> list[str]:
    reasons = [
        f"Observable for {overlap.minutes} minutes during the best weather window.",
    ]
    if peak_time is not None:
        local_peak = peak_time.astimezone(ZoneInfo(timezone_name))
        reasons.append(
            f"Reaches {maximum_altitude:.1f} degrees altitude near {local_peak:%H:%M %Z}."
        )
    else:
        reasons.append(f"Reaches {maximum_altitude:.1f} degrees maximum altitude.")
    if lunar.get("moon_above_horizon_during_observable_window") is False:
        reasons.append("The Moon remains below the horizon during the target's observable period.")
    else:
        rating = lunar.get("lunar_impact_rating")
        reasons.append(f"Lunar interference is rated {rating} for this target.")
    if peak_inside:
        reasons.append("Peaks inside the best weather window.")
    if weather_night.get("recommendation", {}).get("level") == "visual":
        reasons.append("Weather supports an opportunistic visual session rather than planned imaging.")
    return reasons


def _extend_warnings(
    warnings: list[str],
    overlap: WindowOverlap,
    representative_altitude: float,
    wait_minutes: float,
    lunar: dict[str, Any],
    weather_night: dict[str, Any],
) -> None:
    if representative_altitude < 35:
        warnings.append("Target remains below 35 degrees near the middle of the usable overlap.")
    minimum_separation = _finite_number(lunar.get("minimum_moon_separation_deg"))
    if minimum_separation is not None and minimum_separation < 40:
        warnings.append(f"Moon separation drops to {minimum_separation:.1f} degrees.")
    if wait_minutes > 60:
        warnings.append("Target becomes available more than an hour after the best window begins.")
    if overlap.minutes < 60:
        warnings.append(f"Only {overlap.minutes} minutes overlap the usable forecast window.")
    if weather_night.get("recommendation", {}).get("confidence") == "Low":
        warnings.append("Forecast confidence is lower this far into the week.")


def _altitude_near(samples: Any, moment: datetime) -> float | None:
    if not isinstance(samples, list):
        return None
    valid: list[tuple[datetime, float]] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        timestamp = _parse_timestamp(sample.get("time"))
        altitude = _finite_number(sample.get("altitude_deg"))
        if timestamp is not None and altitude is not None and -90 <= altitude <= 90:
            valid.append((timestamp, altitude))
    if not valid:
        return None
    moment_utc = moment.astimezone(UTC)
    return min(valid, key=lambda item: abs(item[0].astimezone(UTC) - moment_utc))[1]


def _recommendation_result(
    status: str,
    message: str,
    top_targets: list[dict[str, Any]],
    review_flags: list[str],
    evaluated: int,
    eligible: int,
) -> dict[str, Any]:
    return {
        "status": status,
        "message": message,
        "candidatesEvaluated": evaluated,
        "eligibleCandidates": eligible,
        "reviewFlags": review_flags,
        "topTargets": top_targets,
    }


def _unique_index(
    values: list[Any], key: str, label: str
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for position, value in enumerate(values):
        if not isinstance(value, dict):
            raise TargetRecommendationError(f"Malformed {label} at index {position}.")
        identifier = value.get(key)
        if not isinstance(identifier, str) or not identifier:
            raise TargetRecommendationError(f"Malformed {label} ID at index {position}.")
        if identifier in index:
            raise TargetRecommendationError(f"Duplicate {label} ID: {identifier}.")
        index[identifier] = value
    return index


def _index_individual_records(
    values: list[Any], key: str, flag_prefix: str
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    index: dict[str, dict[str, Any]] = {}
    review_flags: list[str] = []
    for position, value in enumerate(values):
        if not isinstance(value, dict):
            review_flags.append(f"malformed_{flag_prefix}:{position}")
            continue
        identifier = value.get(key)
        if not isinstance(identifier, str) or not identifier:
            review_flags.append(f"missing_{flag_prefix}_id:{position}")
            continue
        if identifier in index:
            raise TargetRecommendationError(f"Duplicate {flag_prefix} ID: {identifier}.")
        index[identifier] = value
    return index, review_flags


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -candidate["recommendationScore"],
        -candidate["usableWindowOverlapMinutes"],
        -candidate["lunarImpactScore"],
        -candidate["maximumAltitudeDeg"],
        candidate["displayName"].casefold(),
        candidate["targetId"],
    )


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _elapsed_minutes(start: datetime, end: datetime) -> int:
    return round(
        (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60
    )


def _within(moment: datetime, start: datetime, end: datetime) -> bool:
    moment_utc = moment.astimezone(UTC)
    return start.astimezone(UTC) <= moment_utc <= end.astimezone(UTC)


def _display_target_type(value: Any) -> str:
    return str(value).replace("_", " ").title() if isinstance(value, str) else "Unavailable"


def validate_enriched_output(payload: dict[str, Any]) -> None:
    """Validate Stage 4C fields without modifying the forecast payload."""

    _validate_finite(payload)
    for night in payload["nights"]:
        recommendations = night.get("targetRecommendations")
        if not isinstance(recommendations, dict) or not isinstance(
            recommendations.get("topTargets"), list
        ):
            raise TargetRecommendationError("Every night must contain target recommendations.")
        if len(recommendations["topTargets"]) > 3:
            raise TargetRecommendationError("A night cannot contain more than three targets.")
        for expected_rank, target in enumerate(recommendations["topTargets"], start=1):
            if target.get("rank") != expected_rank:
                raise TargetRecommendationError("Target recommendation ranks are invalid.")
            score = _finite_number(target.get("recommendationScore"))
            if score is None or not 0 <= score <= 100:
                raise TargetRecommendationError("Target recommendation score is invalid.")
        if recommendations["topTargets"] and night.get("suggestedTarget") != recommendations["topTargets"][0].get("displayName"):
            raise TargetRecommendationError("suggestedTarget must match the first recommendation.")


def _validate_finite(value: Any, path: str = "root") -> None:
    if isinstance(value, float) and not isfinite(value):
        raise TargetRecommendationError(f"Non-finite number found at {path}.")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite(child, f"{path}[{index}]")
