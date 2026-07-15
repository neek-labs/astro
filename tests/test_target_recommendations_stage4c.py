from __future__ import annotations

import copy
import os
from datetime import date, datetime, timedelta
from math import nan
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from planner.config import ConfigError, load_config, validate_config
from planner.output import OutputError, write_atomic_json
from planner.target_recommendations import (
    ALTITUDE_COMPONENT_POINTS,
    DURATION_COMPONENT_POINTS,
    TargetRecommendationError,
    calculate_overlap,
    enrich_forecast_payload,
    linear_interpolate,
    load_json_object,
    recommendation_rating,
    recommend_targets_for_night,
    target_class_adjustment,
)


ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Edmonton")
START = datetime(2026, 10, 10, 22, tzinfo=TZ)
END = START + timedelta(hours=4)


def config() -> dict:
    return load_config(ROOT / "config" / "session-planner.json")


def weather_night(
    observing_date: date = date(2026, 10, 10),
    *,
    level: str = "possible",
    start: datetime | None = START,
    end: datetime | None = END,
) -> dict:
    return {
        "date": observing_date.isoformat(),
        "weekday": observing_date.strftime("%A"),
        "forecastLeadHours": 12,
        "recommendation": {
            "label": "Imaging possible" if level != "visual" else "Visual only",
            "level": level,
            "confidence": "High",
            "score": 70,
        },
        "conditions": {
            "bestWindow": "22:00-02:00 MDT",
            "bestWindowStart": start.isoformat() if start else None,
            "bestWindowEnd": end.isoformat() if end else None,
            "usableHours": 4,
            "visualUsableHours": 4,
            "imagingUsableHours": 4,
            "astronomicalNightOccurs": True,
            "averageCloudCoverPercent": 10,
            "averageLowCloudCoverPercent": 5,
            "precipitationProbabilityPercent": 0,
            "averageHumidityPercent": 50,
            "visibilityKm": 20,
            "wind": {"sustainedKph": 5, "gustKph": 8},
            "temperature": {"expectedC": 5, "dewPointSpreadC": 5},
            "moon": {
                "illuminationPercent": 40,
                "aboveHorizon": True,
                "altitudeDegrees": 20,
                "context": "bestWindowMidpoint",
            },
        },
        "suggestedTarget": "placeholder",
        "suggestedEquipment": "placeholder",
        "warnings": [],
        "explanation": "Weather explanation.",
        "scoreBreakdown": {},
        "reasons": [],
    }


def catalogue_target(
    target_id: str = "target-a",
    *,
    display_name: str = "Alpha Target",
    object_type: str | None = "galaxy",
    imaging_mode: str | None = "LRGB",
) -> dict:
    result = {
        "id": target_id,
        "display_name": display_name,
        "primary_catalog_id": target_id.upper(),
    }
    if object_type is not None:
        result["object_type"] = object_type
    if imaging_mode is not None:
        result["imaging_mode"] = imaging_mode
    return result


def visibility_target(
    target_id: str = "target-a",
    *,
    start: datetime = START,
    end: datetime = END,
    maximum_altitude: float = 60,
    lunar_score: float | None = 80,
    observable: bool = True,
) -> dict:
    samples = []
    current = start
    while current <= end:
        samples.append({"time": current.isoformat(), "altitude_deg": maximum_altitude})
        current += timedelta(minutes=30)
    return {
        "target_id": target_id,
        "observable": observable,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "observable_minutes": round((end - start).total_seconds() / 60),
        "maximum_altitude_deg": maximum_altitude,
        "maximum_altitude_time": (start + (end - start) / 2).isoformat(),
        "altitude_at_darkness_start_deg": maximum_altitude,
        "altitude_at_darkness_end_deg": maximum_altitude,
        "altitude_samples": samples,
        "visibility_rating": "excellent",
        "review_flags": [],
        "moon": {
            "moon_above_horizon_during_observable_window": True,
            "minimum_moon_separation_deg": 70,
            "lunar_impact_score": lunar_score,
            "lunar_impact_rating": "good" if lunar_score is not None else None,
        },
    }


def run_night(
    targets: list[dict] | None = None,
    catalogue: list[dict] | None = None,
    *,
    level: str = "possible",
) -> dict:
    result, _ = recommend_targets_for_night(
        weather_night(level=level),
        {"date": "2026-10-10", "targets": targets or [visibility_target()]},
        {target["id"]: target for target in (catalogue or [catalogue_target()])},
        config(),
    )
    return result


def forecast_payload() -> dict:
    nights = []
    for offset in range(7):
        observing_date = date(2026, 10, 10) + timedelta(days=offset)
        start = START + timedelta(days=offset)
        nights.append(weather_night(observing_date, start=start, end=start + timedelta(hours=4)))
    return {
        "sampleData": False,
        "location": {
            "name": "Calgary, Alberta",
            "latitude": 51.12,
            "longitude": -114.11,
            "timezone": "America/Edmonton",
        },
        "generatedAt": datetime(2026, 10, 10, 12, tzinfo=TZ).isoformat(),
        "dataSource": "test",
        "nights": nights,
    }


def visibility_payload() -> dict:
    nights = []
    for offset in range(7):
        start = START + timedelta(days=offset)
        nights.append(
            {
                "date": (date(2026, 10, 10) + timedelta(days=offset)).isoformat(),
                "targets": [visibility_target(start=start, end=start + timedelta(hours=4))],
            }
        )
    return {"schema_version": "0.3", "nights": nights}


def test_nights_match_by_date_and_targets_match_by_stable_id() -> None:
    forecast = forecast_payload()
    visibility = visibility_payload()
    catalogue = {
        "targets": [
            catalogue_target(display_name="Matched by ID"),
            catalogue_target("unrelated", display_name="Same display is irrelevant"),
        ]
    }
    enriched, _ = enrich_forecast_payload(forecast, visibility, catalogue, config())
    first = enriched["nights"][0]["targetRecommendations"]["topTargets"][0]
    assert first["targetId"] == "target-a"
    assert first["displayName"] == "Matched by ID"


def test_overlap_full_partial_and_none() -> None:
    full = calculate_overlap(START, END, START, END)
    partial = calculate_overlap(START - timedelta(hours=1), START + timedelta(hours=1), START, END)
    missing = calculate_overlap(START - timedelta(hours=2), START, START, END)
    assert full and full.minutes == 240
    assert partial and partial.minutes == 60
    assert missing is None


def test_no_overlap_is_excluded() -> None:
    result = run_night(
        [visibility_target(start=START - timedelta(hours=2), end=START - timedelta(hours=1))]
    )
    assert result["status"] == "noCandidates"
    assert result["topTargets"] == []


def test_partial_overlap_measurements_are_stored() -> None:
    result = run_night(
        [visibility_target(start=START - timedelta(hours=1), end=START + timedelta(hours=1))]
    )
    candidate = result["topTargets"][0]
    assert candidate["usableWindowOverlapStart"] == START.isoformat()
    assert candidate["usableWindowOverlapEnd"] == (START + timedelta(hours=1)).isoformat()
    assert candidate["usableWindowOverlapMinutes"] == 60


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 0), (30, 20), (60, 50), (120, 80), (180, 100)],
)
def test_duration_interpolation_thresholds(value: float, expected: float) -> None:
    assert linear_interpolate(value, DURATION_COMPONENT_POINTS) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(25, 0), (35, 35), (45, 65), (60, 90), (75, 100)],
)
def test_altitude_interpolation_thresholds(value: float, expected: float) -> None:
    assert linear_interpolate(value, ALTITUDE_COMPONENT_POINTS) == pytest.approx(expected)


def test_stage4b_lunar_score_is_reused_directly() -> None:
    candidate = run_night([visibility_target(lunar_score=73.2)])["topTargets"][0]
    assert candidate["lunarImpactScore"] == 73.2
    assert candidate["scoreBreakdown"]["lunarImpact"] == 73.2


def test_target_class_adjustment_and_neutral_fallback() -> None:
    adjustment, reason = target_class_adjustment(
        catalogue_target(object_type="emission_nebula", imaging_mode="narrowband"), 10
    )
    neutral, neutral_reason = target_class_adjustment(
        catalogue_target(object_type=None, imaging_mode=None), 10
    )
    assert adjustment == 5
    assert "narrowband" in reason.lower()
    assert neutral == 0
    assert neutral_reason is None


def test_poor_weather_returns_no_formal_recommendations() -> None:
    result = run_night(level="poor")
    assert result["status"] == "weatherBlocked"
    assert result["topTargets"] == []


def test_missing_structured_best_window_is_reported_without_parsing_display_text() -> None:
    night = weather_night(start=None, end=None)
    result, _ = recommend_targets_for_night(
        night,
        {"date": night["date"], "targets": [visibility_target()]},
        {"target-a": catalogue_target()},
        config(),
    )
    assert result["status"] == "unavailable"
    assert result["reviewFlags"] == ["missing_best_window_timestamps"]


def test_visual_only_recommendations_are_labelled_opportunistic() -> None:
    result = run_night(level="visual")
    assert result["status"] == "available"
    assert "opportunistic visual" in result["message"]
    assert any("opportunistic visual" in reason.lower() for reason in result["topTargets"][0]["reasons"])


def test_only_observable_targets_with_lunar_scores_are_eligible() -> None:
    result = run_night(
        [
            visibility_target("not-observable", observable=False),
            visibility_target("missing-lunar", lunar_score=None),
            visibility_target("valid"),
        ],
        [
            catalogue_target("not-observable"),
            catalogue_target("missing-lunar"),
            catalogue_target("valid"),
        ],
    )
    assert [target["targetId"] for target in result["topTargets"]] == ["valid"]


def test_deterministic_tie_breaking_and_maximum_three() -> None:
    targets = [visibility_target(target_id) for target_id in ["d", "c", "b", "a"]]
    catalogue = [
        catalogue_target(target_id, display_name=f"Name {target_id.upper()}", object_type=None)
        for target_id in ["d", "c", "b", "a"]
    ]
    first = run_night(targets, catalogue)
    second = run_night(list(reversed(targets)), list(reversed(catalogue)))
    assert [target["targetId"] for target in first["topTargets"]] == ["a", "b", "c"]
    assert first == second


def test_fewer_than_three_candidates_are_not_padded() -> None:
    result = run_night(
        [visibility_target("a"), visibility_target("b")],
        [catalogue_target("a"), catalogue_target("b")],
    )
    assert len(result["topTargets"]) == 2


def test_recommendation_weights_must_sum_to_100() -> None:
    cfg = config()
    cfg["targetRecommendations"]["weights"]["lunarImpact"] = 20
    with pytest.raises(ConfigError, match="must total 100"):
        validate_config(cfg)


@pytest.mark.parametrize(
    ("score", "rating"),
    [(0, "poor"), (25, "weak"), (50, "moderate"), (70, "good"), (85, "excellent")],
)
def test_target_recommendation_rating_boundaries(score: float, rating: str) -> None:
    assert recommendation_rating(score) == rating


def test_final_score_is_clamped_to_100() -> None:
    candidate = run_night(
        [visibility_target(maximum_altitude=80, lunar_score=100)],
        [
            catalogue_target(
                object_type="emission_nebula", imaging_mode="narrowband"
            )
        ],
    )["topTargets"][0]
    assert candidate["recommendationScore"] == 100


def test_existing_weather_fields_are_preserved_and_alias_matches_top_target() -> None:
    forecast = forecast_payload()
    original_conditions = copy.deepcopy(forecast["nights"][0]["conditions"])
    enriched, _ = enrich_forecast_payload(
        forecast, visibility_payload(), {"targets": [catalogue_target()]}, config()
    )
    night = enriched["nights"][0]
    assert night["conditions"] == original_conditions
    assert night["suggestedTarget"] == night["targetRecommendations"]["topTargets"][0]["displayName"]
    assert forecast["nights"][0]["suggestedTarget"] == "placeholder"


def test_duplicate_ids_are_rejected_and_malformed_individual_is_flagged() -> None:
    with pytest.raises(TargetRecommendationError, match="Duplicate catalogue_target ID"):
        enrich_forecast_payload(
            forecast_payload(),
            visibility_payload(),
            {"targets": [catalogue_target(), catalogue_target()]},
            config(),
        )

    visibility = visibility_payload()
    visibility["nights"][0]["targets"].append({"observable": True})
    enriched, _ = enrich_forecast_payload(
        forecast_payload(), visibility, {"targets": [catalogue_target()]}, config()
    )
    assert "missing_visibility_target_id:1" in enriched["nights"][0]["targetRecommendations"]["reviewFlags"]


def test_non_finite_generated_values_are_rejected() -> None:
    forecast = forecast_payload()
    forecast["nights"][0]["conditions"]["averageCloudCoverPercent"] = nan
    with pytest.raises(TargetRecommendationError, match="Non-finite"):
        enrich_forecast_payload(
            forecast, visibility_payload(), {"targets": [catalogue_target()]}, config()
        )


def test_missing_file_and_incompatible_visibility_schema_fail_safely(tmp_path: Path) -> None:
    with pytest.raises(TargetRecommendationError, match="Could not read"):
        load_json_object(tmp_path / "missing.json", "forecast input")
    incompatible = visibility_payload()
    incompatible["schema_version"] = "0.1"
    with pytest.raises(TargetRecommendationError, match="schema 0.2 or 0.3"):
        enrich_forecast_payload(
            forecast_payload(), incompatible, {"targets": [catalogue_target()]}, config()
        )


def test_atomic_failure_preserves_previous_forecast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "session-planner.json"
    destination.write_text('{"previous": true}\n', encoding="utf-8")

    def fail_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OutputError):
        write_atomic_json({"next": True}, destination)
    assert destination.read_text(encoding="utf-8") == '{"previous": true}\n'
