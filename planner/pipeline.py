from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from math import isfinite
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from planner.config import ConfigError, validate_config
from planner.output import OutputError, validate_output
from planner.target_recommendations import (
    TargetRecommendationError,
    validate_enriched_output,
)
from planner.visibility import VisibilityError, validate_visibility_output


ALLOWED_GENERATED_PATHS = frozenset(
    {
        "data/session-planner.json",
        "data/astronomy-target-visibility.json",
    }
)
DEFAULT_MAXIMUM_AGE = timedelta(hours=2)
FUTURE_TIMESTAMP_TOLERANCE = timedelta(minutes=10)
VALID_RECOMMENDATION_STATUSES = {
    "available",
    "weatherBlocked",
    "noCandidates",
    "unavailable",
}


class PipelineValidationError(ValueError):
    """Raised when generated Stage 4D state is unsafe to publish."""


def load_json_object_strict(path: str | Path, label: str) -> dict[str, Any]:
    """Load a JSON object while rejecting JavaScript-only numeric constants."""

    source = Path(path)

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite numeric constant {value}")

    try:
        payload = json.loads(
            source.read_text(encoding="utf-8"),
            parse_constant=reject_constant,
        )
    except OSError as exc:
        raise PipelineValidationError(f"Could not read {label}: {exc}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise PipelineValidationError(f"{label} is not valid finite JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PipelineValidationError(f"{label} root must be a JSON object.")
    _validate_finite_numbers(payload, label)
    return payload


def validate_session_planner_pipeline(
    forecast: dict[str, Any],
    visibility: dict[str, Any],
    catalogue: dict[str, Any],
    config: dict[str, Any],
    *,
    now: datetime | None = None,
    maximum_age: timedelta = DEFAULT_MAXIMUM_AGE,
) -> None:
    """Validate the complete generated state without changing any input."""

    for label, payload in (
        ("forecast", forecast),
        ("visibility", visibility),
        ("target catalogue", catalogue),
        ("configuration", config),
    ):
        if not isinstance(payload, dict):
            raise PipelineValidationError(f"{label} root must be a JSON object.")
        _validate_finite_numbers(payload, label)

    try:
        validate_config(config)
        expected_forecast_nights = config["forecast"]["lengthNights"]
        expected_visibility_nights = config["targetVisibility"]["forecastDays"]
        maximum_targets = config["targetRecommendations"]["maximumResultsPerNight"]
        validate_output(forecast, expected_nights=expected_forecast_nights)
        validate_enriched_output(forecast)
        validate_visibility_output(visibility)
    except (ConfigError, OutputError, TargetRecommendationError, VisibilityError) as exc:
        raise PipelineValidationError(str(exc)) from exc

    forecast_nights = forecast["nights"]
    if visibility.get("schema_version") != "0.3":
        raise PipelineValidationError("Visibility output must use the current schema version 0.3.")
    visibility_nights = visibility.get("nights")
    if not isinstance(visibility_nights, list):
        raise PipelineValidationError("Visibility output must contain a nights array.")
    if len(visibility_nights) != expected_visibility_nights:
        raise PipelineValidationError(
            "Visibility output must contain exactly "
            f"{expected_visibility_nights} nights, found {len(visibility_nights)}."
        )

    forecast_dates = _night_dates(forecast_nights, "forecast")
    visibility_dates = _night_dates(visibility_nights, "visibility")
    if forecast_dates != visibility_dates:
        raise PipelineValidationError(
            "Forecast and visibility night dates must match exactly and in order."
        )

    reference_now = now or datetime.now(UTC)
    if reference_now.tzinfo is None:
        raise PipelineValidationError("Validation reference time must be timezone aware.")
    forecast_generated = _parse_aware_timestamp(
        forecast.get("generatedAt"), "forecast generatedAt"
    )
    visibility_generated = _parse_aware_timestamp(
        visibility.get("generated_at"), "visibility generated_at"
    )
    _validate_fresh_timestamp(
        forecast_generated, reference_now, maximum_age, "forecast generatedAt"
    )
    _validate_fresh_timestamp(
        visibility_generated, reference_now, maximum_age, "visibility generated_at"
    )

    timezone = ZoneInfo(config["location"]["timezone"])
    first_date = date.fromisoformat(forecast_dates[0])
    generated_local_date = forecast_generated.astimezone(timezone).date()
    if not generated_local_date <= first_date <= generated_local_date + timedelta(days=1):
        raise PipelineValidationError(
            "First forecast date must be the generated local date or the following date."
        )

    catalogue_ids = _catalogue_target_ids(catalogue)
    for index, (forecast_night, visibility_night) in enumerate(
        zip(forecast_nights, visibility_nights, strict=True)
    ):
        _validate_visibility_night(visibility_night, catalogue_ids, index)
        _validate_forecast_night(
            forecast_night,
            visibility_night,
            catalogue_ids,
            maximum_targets,
            index,
        )


def validate_pipeline_files(
    forecast_path: str | Path,
    visibility_path: str | Path,
    catalogue_path: str | Path,
    config_path: str | Path,
    *,
    now: datetime | None = None,
    maximum_age: timedelta = DEFAULT_MAXIMUM_AGE,
) -> None:
    forecast = load_json_object_strict(forecast_path, "forecast output")
    visibility = load_json_object_strict(visibility_path, "visibility output")
    catalogue = load_json_object_strict(catalogue_path, "target catalogue")
    config = load_json_object_strict(config_path, "session planner configuration")
    validate_session_planner_pipeline(
        forecast,
        visibility,
        catalogue,
        config,
        now=now,
        maximum_age=maximum_age,
    )


def validate_changed_paths(
    paths: Iterable[str],
    allowed_paths: Iterable[str] = ALLOWED_GENERATED_PATHS,
) -> tuple[str, ...]:
    """Return normalized changed paths or reject anything outside the allowlist."""

    allowed = {_normalize_relative_path(path) for path in allowed_paths}
    normalized = tuple(
        sorted({_normalize_relative_path(path) for path in paths if path.strip()})
    )
    unexpected = [path for path in normalized if path not in allowed]
    if unexpected:
        raise PipelineValidationError(
            "Generation changed unexpected paths: " + ", ".join(unexpected)
        )
    return normalized


def git_changed_paths(
    repository: str | Path,
    *,
    base: str | None = None,
    head: str | None = None,
) -> tuple[str, ...]:
    """Read changed paths from Git without modifying the worktree."""

    root = Path(repository)
    if (base is None) != (head is None):
        raise PipelineValidationError("Both base and head are required for a branch diff.")
    if base is not None and head is not None:
        changed = _run_git_paths(root, "diff", "--name-only", "-z", f"{base}...{head}")
    else:
        tracked = _run_git_paths(root, "diff", "--name-only", "-z", "HEAD")
        untracked = _run_git_paths(
            root, "ls-files", "--others", "--exclude-standard", "-z"
        )
        changed = (*tracked, *untracked)
    return validate_changed_paths(changed)


def build_pipeline_markdown_summary(forecast: dict[str, Any]) -> str:
    """Build deterministic Markdown for the review PR and Actions summary."""

    nights = forecast.get("nights")
    if not isinstance(nights, list) or not nights:
        raise PipelineValidationError("Forecast summary requires at least one night.")
    generated_at = forecast.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at:
        raise PipelineValidationError("Forecast summary requires generatedAt.")

    def weather_score(item: tuple[int, dict[str, Any]]) -> tuple[float, int]:
        index, night = item
        recommendation = night.get("recommendation", {})
        score = recommendation.get("score") if isinstance(recommendation, dict) else None
        numeric = float(score) if _is_finite_number(score) else -1.0
        return numeric, -index

    best_index, best_night = max(enumerate(nights), key=weather_score)
    del best_index
    available_count = 0
    poor_count = 0
    target_lines: list[str] = []
    for night in nights:
        level = night.get("recommendation", {}).get("level")
        if level == "poor":
            poor_count += 1
        recommendations = night.get("targetRecommendations", {})
        top_targets = (
            recommendations.get("topTargets", [])
            if isinstance(recommendations, dict)
            else []
        )
        if top_targets:
            available_count += 1
            top = top_targets[0]
            target_lines.append(
                f"- {night['date']}: {top['displayName']} "
                f"({float(top['recommendationScore']):.1f}/100)"
            )
        else:
            status = recommendations.get("status", "unavailable")
            target_lines.append(f"- {night['date']}: No rank-one target ({status})")

    best_recommendation = best_night["recommendation"]
    lines = [
        "## Session Planner forecast refresh",
        "",
        "This pull request contains generated forecast data. Merging it updates the static Session Planner data used by the existing site.",
        "",
        f"- Generated timestamp: `{generated_at}`",
        f"- Forecast range: `{nights[0]['date']}` through `{nights[-1]['date']}`",
        f"- Forecast nights: {len(nights)}",
        (
            f"- Best weather-rated night: `{best_night['date']}` — "
            f"{best_recommendation['label']} ({best_recommendation['score']}/100)"
        ),
        f"- Nights with target recommendations: {available_count}",
        f"- Nights blocked by poor weather: {poor_count}",
        "",
        "### Rank-one targets",
        "",
        *target_lines,
        "",
        "### Verification",
        "",
        "- Complete test suite: passed before and after generation",
        "- End-to-end pipeline validation: passed",
        "- Generated-file allowlist: passed",
        "",
        "The values in this pull request are generated; scientific values were not edited by the workflow.",
        "",
    ]
    return "\n".join(lines)


def _night_dates(nights: list[Any], label: str) -> list[str]:
    dates: list[str] = []
    for index, night in enumerate(nights):
        if not isinstance(night, dict):
            raise PipelineValidationError(f"{label} night {index} must be an object.")
        value = night.get("date")
        if not isinstance(value, str):
            raise PipelineValidationError(f"{label} night {index} has no valid date.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise PipelineValidationError(
                f"{label} night {index} date must use YYYY-MM-DD."
            ) from exc
        if parsed.isoformat() != value:
            raise PipelineValidationError(
                f"{label} night {index} date must use YYYY-MM-DD."
            )
        dates.append(value)
    if len(dates) != len(set(dates)):
        raise PipelineValidationError(f"{label.capitalize()} night dates must be unique.")
    return dates


def _parse_aware_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise PipelineValidationError(f"{label} must be an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PipelineValidationError(f"{label} must be a valid ISO timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PipelineValidationError(f"{label} must be timezone aware.")
    return parsed


def _validate_fresh_timestamp(
    value: datetime,
    reference: datetime,
    maximum_age: timedelta,
    label: str,
) -> None:
    age = reference.astimezone(UTC) - value.astimezone(UTC)
    if age > maximum_age:
        raise PipelineValidationError(f"{label} is stale by {age}.")
    if age < -FUTURE_TIMESTAMP_TOLERANCE:
        raise PipelineValidationError(f"{label} is unreasonably far in the future.")


def _catalogue_target_ids(catalogue: dict[str, Any]) -> frozenset[str]:
    targets = catalogue.get("targets")
    if not isinstance(targets, list) or not targets:
        raise PipelineValidationError("Target catalogue must contain a non-empty targets array.")
    identifiers: list[str] = []
    for index, target in enumerate(targets):
        identifier = target.get("id") if isinstance(target, dict) else None
        if not isinstance(identifier, str) or not identifier:
            raise PipelineValidationError(f"Catalogue target {index} has no valid ID.")
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        raise PipelineValidationError("Catalogue target IDs must be unique.")
    return frozenset(identifiers)


def _validate_visibility_night(
    night: dict[str, Any],
    catalogue_ids: frozenset[str],
    index: int,
) -> None:
    targets = night.get("targets")
    if not isinstance(targets, list):
        raise PipelineValidationError(f"Visibility night {index} has no targets array.")
    identifiers = [
        target.get("target_id") if isinstance(target, dict) else None for target in targets
    ]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise PipelineValidationError(f"Visibility night {index} has an invalid target ID.")
    if len(identifiers) != len(set(identifiers)):
        raise PipelineValidationError(f"Visibility night {index} has duplicate target IDs.")
    if frozenset(identifiers) != catalogue_ids:
        missing = sorted(catalogue_ids - frozenset(identifiers))
        extra = sorted(frozenset(identifiers) - catalogue_ids)
        raise PipelineValidationError(
            f"Visibility night {index} target set does not match the catalogue "
            f"(missing={missing}, extra={extra})."
        )


def _validate_forecast_night(
    night: dict[str, Any],
    visibility_night: dict[str, Any],
    catalogue_ids: frozenset[str],
    maximum_targets: int,
    index: int,
) -> None:
    recommendation = night.get("recommendation")
    if not isinstance(recommendation, dict):
        raise PipelineValidationError(f"Forecast night {index} lacks a weather recommendation.")

    conditions = night.get("conditions")
    if not isinstance(conditions, dict):
        raise PipelineValidationError(f"Forecast night {index} lacks conditions.")
    usable_hours = conditions.get("usableHours")
    if not _is_finite_number(usable_hours) or float(usable_hours) < 0:
        raise PipelineValidationError(f"Forecast night {index} usableHours is invalid.")
    if float(usable_hours) > 0:
        start = _parse_aware_timestamp(
            conditions.get("bestWindowStart"),
            f"Forecast night {index} bestWindowStart",
        )
        end = _parse_aware_timestamp(
            conditions.get("bestWindowEnd"),
            f"Forecast night {index} bestWindowEnd",
        )
        if end.astimezone(UTC) <= start.astimezone(UTC):
            raise PipelineValidationError(
                f"Forecast night {index} best window end must follow its start."
            )

    target_recommendations = night.get("targetRecommendations")
    if not isinstance(target_recommendations, dict):
        raise PipelineValidationError(
            f"Forecast night {index} lacks targetRecommendations."
        )
    status = target_recommendations.get("status")
    if status not in VALID_RECOMMENDATION_STATUSES:
        raise PipelineValidationError(
            f"Forecast night {index} has invalid target recommendation status."
        )
    top_targets = target_recommendations.get("topTargets")
    if not isinstance(top_targets, list):
        raise PipelineValidationError(
            f"Forecast night {index} targetRecommendations.topTargets must be an array."
        )
    if len(top_targets) > maximum_targets:
        raise PipelineValidationError(
            f"Forecast night {index} has more than {maximum_targets} target recommendations."
        )
    if status == "available" and not top_targets:
        raise PipelineValidationError(
            f"Forecast night {index} is available but has no target recommendations."
        )
    if recommendation.get("level") == "poor" and top_targets:
        raise PipelineValidationError(
            f"Poor-weather forecast night {index} cannot recommend targets."
        )

    visibility_ids = {
        target["target_id"]
        for target in visibility_night["targets"]
        if isinstance(target, dict) and isinstance(target.get("target_id"), str)
    }
    for expected_rank, target in enumerate(top_targets, start=1):
        if not isinstance(target, dict):
            raise PipelineValidationError(
                f"Forecast night {index} recommendation {expected_rank} must be an object."
            )
        if target.get("rank") != expected_rank:
            raise PipelineValidationError(
                f"Forecast night {index} target ranks must begin at one and be consecutive."
            )
        score = target.get("recommendationScore")
        if not _is_finite_number(score) or not 0 <= float(score) <= 100:
            raise PipelineValidationError(
                f"Forecast night {index} target recommendation score must be between 0 and 100."
            )
        target_id = target.get("targetId")
        if target_id not in catalogue_ids:
            raise PipelineValidationError(
                f"Forecast night {index} recommends target absent from catalogue: {target_id}."
            )
        if target_id not in visibility_ids:
            raise PipelineValidationError(
                f"Forecast night {index} recommends target absent from visibility output: {target_id}."
            )
        for field in ("displayName", "lunarImpactRating"):
            if not isinstance(target.get(field), str) or not target[field]:
                raise PipelineValidationError(
                    f"Forecast night {index} recommendation {expected_rank} lacks {field}."
                )
        for field in ("usableWindowOverlapMinutes", "maximumAltitudeDeg"):
            if not _is_finite_number(target.get(field)):
                raise PipelineValidationError(
                    f"Forecast night {index} recommendation {expected_rank} has invalid {field}."
                )

    if top_targets and night.get("suggestedTarget") != top_targets[0].get("displayName"):
        raise PipelineValidationError(
            f"Forecast night {index} suggestedTarget must match rank one."
        )


def _validate_finite_numbers(value: Any, path: str) -> None:
    if isinstance(value, float) and not isfinite(value):
        raise PipelineValidationError(f"Non-finite numeric value at {path}.")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_numbers(child, f"{path}[{index}]")


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(float(value))
    )


def _normalize_relative_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise PipelineValidationError(f"Changed path is not repository-relative: {value!r}.")
    return normalized


def _run_git_paths(repository: Path, *arguments: str) -> tuple[str, ...]:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PipelineValidationError(f"Could not inspect Git changes: {exc}") from exc
    return tuple(
        value.decode("utf-8")
        for value in result.stdout.split(b"\0")
        if value
    )
