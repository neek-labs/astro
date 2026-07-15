from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from math import nan
from pathlib import Path

import pytest
from astropy import units as u
from astropy.coordinates import EarthLocation, SkyCoord

from planner.config import load_config
from planner.lunar import (
    MOON_ALTITUDE_COMPONENT_POINTS,
    SEPARATION_COMPONENT_POINTS,
    MoonSampleGrid,
    angular_separations_deg,
    build_moon_sample_grid,
    calculate_lunar_impact_score,
    calculate_target_lunar_impact,
    linear_interpolate,
    lunar_impact_rating,
)
from planner.visibility import (
    DarknessWindow,
    VisibilityError,
    build_nightly_visibility,
    calculate_visibility_from_altitudes,
    write_visibility_output,
)


ROOT = Path(__file__).resolve().parents[1]


def sample_times(count: int = 7) -> list[datetime]:
    start = datetime(2026, 8, 16, 4, tzinfo=UTC)
    return [start + timedelta(minutes=10 * index) for index in range(count)]


def target(ra_deg: float = 0.0, dec_deg: float = 0.0) -> dict:
    return {
        "id": "test-target",
        "display_name": "Test Target",
        "coordinates": {
            "ra_deg": ra_deg,
            "dec_deg": dec_deg,
            "frame": "ICRS",
            "equinox": "J2000",
        },
    }


def moon_grid(
    *,
    moon_ra_deg: float | list[float],
    altitudes_deg: list[float],
    illumination_percent: float,
) -> MoonSampleGrid:
    count = len(altitudes_deg)
    ras = [moon_ra_deg] * count if isinstance(moon_ra_deg, float) else moon_ra_deg
    return MoonSampleGrid(
        moments_utc=tuple(sample_times(count)),
        coordinates=SkyCoord(ra=ras * u.deg, dec=[0.0] * count * u.deg, frame="icrs"),
        altitudes_deg=tuple(altitudes_deg),
        illumination_percent=tuple([illumination_percent] * count),
    )


def visible_record(altitudes: list[float] | None = None) -> dict:
    values = altitudes or [45.0] * 7
    return calculate_visibility_from_altitudes(
        "test-target", sample_times(len(values)), values, 25.0
    )


def test_angular_separation_for_known_coordinates() -> None:
    fixed_target = SkyCoord(ra=0 * u.deg, dec=0 * u.deg, frame="icrs")
    moon_positions = SkyCoord(
        ra=[0, 90, 180] * u.deg,
        dec=[0, 0, 0] * u.deg,
        frame="icrs",
    )
    assert angular_separations_deg(fixed_target, moon_positions) == pytest.approx([0, 90, 180])


def test_fixed_astropy_moon_grid_preserves_apparent_nightly_motion() -> None:
    location = EarthLocation(lat=51.12 * u.deg, lon=-114.11 * u.deg, height=1100 * u.m)
    grid = build_moon_sample_grid(sample_times(), location)
    fixed_target = SkyCoord(ra=296.2 * u.deg, dec=50.5 * u.deg, frame="icrs")
    separations = angular_separations_deg(fixed_target, grid.coordinates)
    assert grid.coordinates.frame.name == "gcrs"
    assert max(separations) - min(separations) > 0.05
    assert build_moon_sample_grid(sample_times(), location).altitudes_deg == pytest.approx(
        grid.altitudes_deg
    )


def test_moon_below_horizon_for_entire_observable_window_scores_100() -> None:
    impact = calculate_target_lunar_impact(
        target(),
        visible_record(),
        moon_grid(moon_ra_deg=10.0, altitudes_deg=[-5.0] * 7, illumination_percent=100),
    )
    assert impact["moon_above_horizon_during_observable_window"] is False
    assert impact["lunar_impact_score"] == 100.0
    assert impact["lunar_impact_rating"] == "excellent"


def test_moon_above_horizon_and_close_to_target_is_severe() -> None:
    impact = calculate_target_lunar_impact(
        target(),
        visible_record(),
        moon_grid(moon_ra_deg=0.0, altitudes_deg=[60.0] * 7, illumination_percent=100),
    )
    assert impact["minimum_moon_separation_deg"] == pytest.approx(0.0)
    assert impact["lunar_impact_score"] == pytest.approx(5.0)
    assert impact["lunar_impact_rating"] == "severe"


def test_bright_moon_at_large_separation() -> None:
    impact = calculate_target_lunar_impact(
        target(),
        visible_record(),
        moon_grid(moon_ra_deg=120.0, altitudes_deg=[30.0] * 7, illumination_percent=100),
    )
    assert impact["lunar_impact_score"] == pytest.approx(60.0)
    assert impact["lunar_impact_rating"] == "moderate"


def test_dark_moon_at_small_separation() -> None:
    impact = calculate_target_lunar_impact(
        target(),
        visible_record(),
        moon_grid(moon_ra_deg=0.0, altitudes_deg=[30.0] * 7, illumination_percent=0),
    )
    assert impact["lunar_impact_score"] == pytest.approx(40.0)
    assert impact["lunar_impact_rating"] == "poor"


def test_target_with_no_observable_window_has_no_score() -> None:
    visibility = visible_record([5, 10, 15, 20, 15, 10, 5])
    impact = calculate_target_lunar_impact(
        target(),
        visibility,
        moon_grid(moon_ra_deg=30.0, altitudes_deg=[20.0] * 7, illumination_percent=50),
    )
    assert impact["moon_above_horizon_during_observable_window"] is False
    assert impact["minimum_moon_separation_deg"] is None
    assert impact["time_of_minimum_moon_separation"] is None
    assert impact["lunar_impact_score"] is None
    assert impact["lunar_impact_rating"] is None


def test_missing_peak_and_midpoint_timestamps_are_null() -> None:
    visibility = visible_record()
    visibility["maximum_altitude_time"] = None
    visibility["window_start"] = None
    visibility["window_end"] = None
    impact = calculate_target_lunar_impact(
        target(),
        visibility,
        moon_grid(moon_ra_deg=30.0, altitudes_deg=[20.0] * 7, illumination_percent=50),
    )
    assert impact["moon_altitude_at_target_peak_deg"] is None
    assert impact["moon_altitude_at_observable_midpoint_deg"] is None
    assert impact["moon_separation_at_target_peak_deg"] is None
    assert impact["moon_separation_at_observable_midpoint_deg"] is None
    assert impact["lunar_impact_score"] is None


@pytest.mark.parametrize(
    ("score", "rating"),
    [
        (0, "severe"),
        (24.99, "severe"),
        (25, "poor"),
        (49.99, "poor"),
        (50, "moderate"),
        (69.99, "moderate"),
        (70, "good"),
        (84.99, "good"),
        (85, "excellent"),
        (100, "excellent"),
    ],
)
def test_score_rating_boundaries(score: float, rating: str) -> None:
    assert lunar_impact_rating(score) == rating


@pytest.mark.parametrize(
    ("points", "value", "expected"),
    [
        (SEPARATION_COMPONENT_POINTS, 0, 0),
        (SEPARATION_COMPONENT_POINTS, 30, 20),
        (SEPARATION_COMPONENT_POINTS, 60, 50),
        (SEPARATION_COMPONENT_POINTS, 90, 80),
        (SEPARATION_COMPONENT_POINTS, 120, 100),
        (MOON_ALTITUDE_COMPONENT_POINTS, 0, 100),
        (MOON_ALTITUDE_COMPONENT_POINTS, 15, 75),
        (MOON_ALTITUDE_COMPONENT_POINTS, 30, 50),
        (MOON_ALTITUDE_COMPONENT_POINTS, 60, 25),
        (MOON_ALTITUDE_COMPONENT_POINTS, 90, 0),
    ],
)
def test_linear_interpolation_exact_thresholds(points, value: float, expected: float) -> None:
    assert linear_interpolate(value, points) == pytest.approx(expected)


def test_scoring_function_uses_documented_weights() -> None:
    score = calculate_lunar_impact_score(
        moon_above_horizon=True,
        minimum_separation_deg=90,
        illumination_percent=40,
        representative_moon_altitude_deg=15,
    )
    assert score == pytest.approx(80 * 0.50 + 60 * 0.30 + 75 * 0.20)


def test_fixed_inputs_produce_stable_output_and_utc_minimum_time() -> None:
    grid = moon_grid(
        moon_ra_deg=[60.0, 50.0, 40.0, 30.0, 40.0, 50.0, 60.0],
        altitudes_deg=[5, 10, 15, 20, 15, 10, 5],
        illumination_percent=25,
    )
    first = calculate_target_lunar_impact(target(), visible_record(), grid)
    second = calculate_target_lunar_impact(target(), visible_record(), grid)
    assert first == second
    assert first["time_of_minimum_moon_separation"] == "2026-08-16T04:30:00Z"


def test_nightly_integration_preserves_stage4a_fields_and_builds_moon_grid_once() -> None:
    cfg = load_config(ROOT / "config" / "session-planner.json")
    darkness = DarknessWindow(sample_times()[0], sample_times()[-1], "test")
    calls = 0

    def calculator(raw_target, moments, location, minimum_altitude):
        return calculate_visibility_from_altitudes(
            raw_target["id"], moments, [45.0] * len(moments), minimum_altitude
        )

    def grid_builder(moments, location):
        nonlocal calls
        calls += 1
        return moon_grid(
            moon_ra_deg=90.0,
            altitudes_deg=[15.0] * len(moments),
            illumination_percent=40,
        )

    expected_stage4a = calculator(target(), sample_times(), object(), 25.0)
    night = build_nightly_visibility(
        date(2026, 8, 15),
        darkness,
        [target()],
        cfg,
        calculator=calculator,
        moon_grid_builder=grid_builder,
    )
    actual = night["targets"][0]
    assert calls == 1
    assert night["moon"] == {"illumination_percent": 40.0}
    for key, value in expected_stage4a.items():
        assert actual[key] == value
    assert "moon" in actual


def test_night_without_a_darkness_window_has_null_lunar_context() -> None:
    cfg = load_config(ROOT / "config" / "session-planner.json")

    def grid_builder(moments, location):
        raise AssertionError("No Moon grid should be built without a darkness window.")

    night = build_nightly_visibility(
        date(2026, 6, 21),
        DarknessWindow(None, None, "test", review_flags=("invalid_darkness_window",)),
        [target()],
        cfg,
        moon_grid_builder=grid_builder,
    )
    assert night["moon"] == {"illumination_percent": None}
    assert night["targets"][0]["moon"]["lunar_impact_score"] is None
    assert night["targets"][0]["review_flags"] == ["invalid_darkness_window"]


def test_json_output_is_finite_and_rejects_nan(tmp_path: Path) -> None:
    destination = tmp_path / "visibility.json"
    payload = {
        "nights": [
            {
                "moon": {"illumination_percent": 50.0},
                "targets": [
                    {
                        "moon": calculate_target_lunar_impact(
                            target(),
                            visible_record(),
                            moon_grid(
                                moon_ra_deg=90.0,
                                altitudes_deg=[15.0] * 7,
                                illumination_percent=50,
                            ),
                        )
                    }
                ],
            }
        ]
    }
    write_visibility_output(payload, destination)
    parsed = json.loads(
        destination.read_text(encoding="utf-8"),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )
    assert parsed == payload

    payload["nights"][0]["targets"][0]["moon"]["lunar_impact_score"] = nan
    with pytest.raises(VisibilityError, match="non-finite"):
        write_visibility_output(payload, destination)
