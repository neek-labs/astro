from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from planner.config import load_config
from planner.visibility import (
    DarknessWindow,
    build_nightly_visibility,
    build_observation_times,
    build_visibility_payload,
    calculate_target_visibility,
    calculate_visibility_from_altitudes,
    rate_visibility,
)


ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Edmonton")


def moments(count: int = 7) -> list[datetime]:
    start = datetime(2026, 8, 15, 22, tzinfo=TZ)
    return [start + timedelta(minutes=10 * index) for index in range(count)]


def config() -> dict:
    return load_config(ROOT / "config" / "session-planner.json")


def target(target_id: str, *, coordinates: dict | None = None) -> dict:
    value = {"id": target_id, "display_name": target_id}
    if coordinates is not None:
        value["coordinates"] = coordinates
    return value


def test_target_above_threshold_for_whole_interval() -> None:
    sample_times = moments()
    record = calculate_visibility_from_altitudes(
        "always-up", sample_times, [45, 46, 47, 48, 47, 46, 45], 25
    )
    assert record["observable"] is True
    assert record["window_start"] == sample_times[0].isoformat()
    assert record["window_end"] == sample_times[-1].isoformat()
    assert record["observable_minutes"] == 60
    assert record["altitude_samples"][0] == {
        "time": sample_times[0].isoformat(),
        "altitude_deg": 45.0,
    }
    assert len(record["altitude_samples"]) == len(sample_times)


def test_target_rises_above_threshold_partway_through_night() -> None:
    sample_times = moments()
    record = calculate_visibility_from_altitudes(
        "rising", sample_times, [10, 20, 24.9, 25, 30, 35, 40], 25
    )
    assert record["window_start"] == sample_times[3].isoformat()
    assert record["observable_minutes"] == 30


def test_target_never_reaches_threshold() -> None:
    record = calculate_visibility_from_altitudes(
        "too-low", moments(), [5, 10, 15, 20, 24.9, 20, 10], 25
    )
    assert record["observable"] is False
    assert record["visibility_rating"] == "unavailable"
    assert record["review_flags"] == ["never_above_threshold"]


def test_observation_grid_crosses_midnight_with_local_offsets() -> None:
    start = datetime(2026, 8, 15, 23, 50, tzinfo=TZ)
    end = datetime(2026, 8, 16, 0, 20, tzinfo=TZ)
    grid = build_observation_times(start, end, 10)
    assert grid[0].date() == date(2026, 8, 15)
    assert grid[-1].date() == date(2026, 8, 16)
    assert all(value.tzinfo is not None and value.utcoffset() is not None for value in grid)


def test_missing_coordinates_produce_output_record() -> None:
    record = calculate_target_visibility(target("missing"), moments(), object(), 25)
    assert record["target_id"] == "missing"
    assert record["review_flags"] == ["missing_coordinates"]


@pytest.mark.parametrize(
    ("minutes", "maximum_altitude", "expected"),
    [
        (59, 80, "short"),
        (60, 80, "usable"),
        (120, 80, "usable"),
        (121, 59.9, "good"),
        (121, 60, "excellent"),
    ],
)
def test_visibility_rating_boundaries(
    minutes: int, maximum_altitude: float, expected: str
) -> None:
    assert rate_visibility(minutes, maximum_altitude) == expected


def test_payload_timestamps_are_timezone_aware_iso() -> None:
    generated_at = datetime(2026, 7, 14, 19, tzinfo=TZ)
    payload = build_visibility_payload(config(), generated_at, [], 1)
    parsed = datetime.fromisoformat(payload["generated_at"])
    assert parsed.utcoffset() == timedelta(hours=-6)


def test_every_target_gets_record_when_one_calculation_fails() -> None:
    cfg = config()
    darkness = DarknessWindow(
        datetime(2026, 8, 15, 22, tzinfo=TZ),
        datetime(2026, 8, 15, 23, tzinfo=TZ),
        "test",
    )

    def calculator(raw_target, sample_times, location, minimum_altitude):
        if raw_target["id"] == "broken":
            raise RuntimeError("synthetic failure")
        return calculate_visibility_from_altitudes(
            raw_target["id"], sample_times, [45] * len(sample_times), minimum_altitude
        )

    night = build_nightly_visibility(
        date(2026, 8, 15),
        darkness,
        [target("healthy"), target("broken")],
        cfg,
        calculator=calculator,
    )
    assert {record["target_id"] for record in night["targets"]} == {"healthy", "broken"}
    broken = next(record for record in night["targets"] if record["target_id"] == "broken")
    assert broken["review_flags"] == ["calculation_error"]
