from __future__ import annotations

import copy
from datetime import UTC, date, datetime, timedelta
from math import nan
from pathlib import Path

import pytest

from planner.config import load_config
from planner.pipeline import (
    PipelineValidationError,
    build_pipeline_markdown_summary,
    validate_changed_paths,
    validate_session_planner_pipeline,
)


ROOT = Path(__file__).resolve().parents[1]
GENERATED = datetime(2026, 10, 10, 8, tzinfo=UTC)
NOW = GENERATED + timedelta(minutes=30)
FIRST_DATE = date(2026, 10, 10)


def pipeline_config() -> dict:
    return copy.deepcopy(load_config(ROOT / "config" / "session-planner.json"))


def catalogue_target(target_id: str, display_name: str) -> dict:
    return {
        "id": target_id,
        "display_name": display_name,
        "primary_catalog_id": target_id.upper(),
    }


def catalogue_payload() -> dict:
    return {
        "schema_version": "0.3",
        "targets": [
            catalogue_target("target-a", "Alpha Target"),
            catalogue_target("target-b", "Beta Target"),
        ],
    }


def visibility_target(target_id: str) -> dict:
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
        "review_flags": [],
        "moon": {
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
        },
    }


def visibility_payload() -> dict:
    nights = []
    for offset in range(7):
        observing_date = FIRST_DATE + timedelta(days=offset)
        nights.append(
            {
                "date": observing_date.isoformat(),
                "darkness_start": None,
                "darkness_end": None,
                "darkness_minutes": 0,
                "darkness_definition": {"source": "test"},
                "moon": {"illumination_percent": 20},
                "targets": [visibility_target("target-a"), visibility_target("target-b")],
            }
        )
    return {
        "schema_version": "0.3",
        "generated_at": GENERATED.isoformat(),
        "nights": nights,
    }


def top_target(rank: int = 1, target_id: str = "target-a") -> dict:
    return {
        "rank": rank,
        "targetId": target_id,
        "displayName": "Alpha Target" if target_id == "target-a" else target_id,
        "recommendationScore": 82.5,
        "usableWindowOverlapMinutes": 120,
        "maximumAltitudeDeg": 55.0,
        "lunarImpactRating": "good",
    }


def weather_night(offset: int, *, poor: bool = False) -> dict:
    observing_date = FIRST_DATE + timedelta(days=offset)
    start = datetime(2026, 10, 10 + offset, 22, tzinfo=UTC)
    if poor:
        targets = []
        target_status = "weatherBlocked"
        usable_hours = 0
        start_value = None
        end_value = None
        suggested = "No observing target recommended"
        level = "poor"
        label = "Poor conditions"
        score = 15
    else:
        targets = [top_target()]
        target_status = "available"
        usable_hours = 2
        start_value = start.isoformat()
        end_value = (start + timedelta(hours=2)).isoformat()
        suggested = "Alpha Target"
        level = "strong"
        label = "Imaging night"
        score = 80 + offset
    return {
        "date": observing_date.isoformat(),
        "weekday": observing_date.strftime("%A"),
        "forecastLeadHours": 12,
        "recommendation": {
            "label": label,
            "level": level,
            "confidence": "High",
            "score": score,
        },
        "conditions": {
            "bestWindow": "22:00-00:00 UTC" if not poor else "No usable window",
            "bestWindowStart": start_value,
            "bestWindowEnd": end_value,
            "usableHours": usable_hours,
            "averageCloudCoverPercent": 10,
            "precipitationProbabilityPercent": 0,
            "wind": {"sustainedKph": 5, "gustKph": 8},
            "temperature": {"expectedC": 5, "dewPointSpreadC": 5},
            "moon": {"illuminationPercent": 20},
        },
        "suggestedTarget": suggested,
        "suggestedEquipment": "Equipment matching is not yet implemented.",
        "warnings": [],
        "explanation": "Test forecast.",
        "targetRecommendations": {
            "status": target_status,
            "message": "Test recommendation state.",
            "candidatesEvaluated": 2,
            "eligibleCandidates": len(targets),
            "reviewFlags": [],
            "topTargets": targets,
        },
    }


def forecast_payload() -> dict:
    return {
        "sampleData": False,
        "location": {
            "name": "Calgary, Alberta",
            "latitude": 51.12,
            "longitude": -114.11,
            "timezone": "America/Edmonton",
        },
        "generatedAt": GENERATED.isoformat(),
        "dataSource": "fixed test data",
        "nights": [weather_night(offset, poor=offset == 6) for offset in range(7)],
    }


def validate(
    forecast: dict | None = None,
    visibility: dict | None = None,
    catalogue: dict | None = None,
    *,
    now: datetime = NOW,
) -> None:
    validate_session_planner_pipeline(
        forecast or forecast_payload(),
        visibility or visibility_payload(),
        catalogue or catalogue_payload(),
        pipeline_config(),
        now=now,
    )


def test_valid_matching_seven_night_pipeline() -> None:
    validate()


def test_mismatched_night_dates_are_rejected() -> None:
    visibility = visibility_payload()
    visibility["nights"][2]["date"] = "2026-11-01"
    with pytest.raises(PipelineValidationError, match="match exactly and in order"):
        validate(visibility=visibility)


def test_duplicate_dates_are_rejected() -> None:
    forecast = forecast_payload()
    forecast["nights"][1]["date"] = forecast["nights"][0]["date"]
    with pytest.raises(PipelineValidationError, match="dates must be unique"):
        validate(forecast=forecast)


def test_missing_night_is_rejected() -> None:
    forecast = forecast_payload()
    forecast["nights"].pop()
    with pytest.raises(PipelineValidationError, match="exactly 7 nights"):
        validate(forecast=forecast)


def test_invalid_generated_timestamp_is_rejected() -> None:
    forecast = forecast_payload()
    forecast["generatedAt"] = "2026-10-10T08:00:00"
    with pytest.raises(PipelineValidationError, match="timezone aware"):
        validate(forecast=forecast)


def test_stale_generated_timestamp_is_rejected() -> None:
    with pytest.raises(PipelineValidationError, match="stale"):
        validate(now=GENERATED + timedelta(hours=3))


def test_non_finite_value_is_rejected() -> None:
    forecast = forecast_payload()
    forecast["nights"][0]["recommendation"]["score"] = nan
    with pytest.raises(PipelineValidationError, match="Non-finite"):
        validate(forecast=forecast)


def test_too_many_target_recommendations_are_rejected() -> None:
    forecast = forecast_payload()
    forecast["nights"][0]["targetRecommendations"]["topTargets"] = [
        top_target(rank) for rank in range(1, 5)
    ]
    with pytest.raises(PipelineValidationError, match="more than three targets"):
        validate(forecast=forecast)


def test_invalid_recommendation_rank_sequence_is_rejected() -> None:
    forecast = forecast_payload()
    forecast["nights"][0]["targetRecommendations"]["topTargets"][0]["rank"] = 2
    with pytest.raises(PipelineValidationError, match="ranks are invalid"):
        validate(forecast=forecast)


def test_recommendation_score_outside_range_is_rejected() -> None:
    forecast = forecast_payload()
    target = forecast["nights"][0]["targetRecommendations"]["topTargets"][0]
    target["recommendationScore"] = 100.1
    with pytest.raises(PipelineValidationError, match="score is invalid"):
        validate(forecast=forecast)


def test_recommended_target_missing_from_catalogue_is_rejected() -> None:
    forecast = forecast_payload()
    target = forecast["nights"][0]["targetRecommendations"]["topTargets"][0]
    target["targetId"] = "missing-target"
    with pytest.raises(PipelineValidationError, match="absent from catalogue"):
        validate(forecast=forecast)


def test_recommended_target_missing_from_visibility_is_rejected() -> None:
    forecast = forecast_payload()
    forecast["nights"][0]["targetRecommendations"]["topTargets"][0]["targetId"] = "target-b"
    visibility = visibility_payload()
    visibility["nights"][0]["targets"] = [
        visibility_target("target-a"),
        visibility_target("target-c"),
    ]
    with pytest.raises(PipelineValidationError, match="target set does not match"):
        validate(forecast=forecast, visibility=visibility)


def test_suggested_target_must_match_rank_one() -> None:
    forecast = forecast_payload()
    forecast["nights"][0]["suggestedTarget"] = "Beta Target"
    with pytest.raises(PipelineValidationError, match="suggestedTarget"):
        validate(forecast=forecast)


def test_poor_weather_night_without_targets_is_valid() -> None:
    validate()


def test_unavailable_state_without_eligible_targets_is_valid() -> None:
    forecast = forecast_payload()
    night = forecast["nights"][0]
    night["targetRecommendations"]["status"] = "noCandidates"
    night["targetRecommendations"]["topTargets"] = []
    night["suggestedTarget"] = "No observing target recommended"
    validate(forecast=forecast)


def test_unexpected_changed_path_is_rejected() -> None:
    with pytest.raises(PipelineValidationError, match="unexpected paths"):
        validate_changed_paths(["data/session-planner.json", "planner/scoring.py"])


def test_only_generated_file_changes_are_allowed() -> None:
    assert validate_changed_paths(
        [
            "data/session-planner.json",
            "data/astronomy-target-visibility.json",
        ]
    ) == (
        "data/astronomy-target-visibility.json",
        "data/session-planner.json",
    )


def test_markdown_summary_is_deterministic() -> None:
    forecast = forecast_payload()
    first = build_pipeline_markdown_summary(forecast)
    second = build_pipeline_markdown_summary(copy.deepcopy(forecast))
    assert first == second
    assert "Generated timestamp" in first
    assert "Forecast range" in first
    assert "Best weather-rated night" in first
    assert "Alpha Target (82.5/100)" in first
    assert "generated forecast data" in first


def test_markdown_summary_handles_nights_without_targets() -> None:
    summary = build_pipeline_markdown_summary(forecast_payload())
    assert "No rank-one target (weatherBlocked)" in summary
    assert "Nights blocked by poor weather: 1" in summary


def test_validation_does_not_mutate_inputs() -> None:
    forecast = forecast_payload()
    visibility = visibility_payload()
    catalogue = catalogue_payload()
    config = pipeline_config()
    originals = copy.deepcopy((forecast, visibility, catalogue, config))
    validate_session_planner_pipeline(
        forecast,
        visibility,
        catalogue,
        config,
        now=NOW,
    )
    assert (forecast, visibility, catalogue, config) == originals
