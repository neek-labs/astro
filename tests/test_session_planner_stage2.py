from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.astronomy import AstroPoint, darkness_summary, moon_context
from planner.config import ConfigError, load_config, validate_config
from planner.output import OutputError, build_payload, validate_output, write_atomic_json
from planner.scoring import evaluate_night, score_window
from planner.weather import HOURLY_FIELDS, WeatherError, WeatherForecast, parse_open_meteo


TZ = ZoneInfo("America/Edmonton")


def config() -> dict:
    return load_config(ROOT / "config" / "session-planner.json")


def weather_payload(hours: int = 4, start: datetime | None = None, **overrides: float) -> dict:
    start = start or datetime(2026, 10, 10, 20, 0)
    defaults = {
        "cloud_cover": 10,
        "cloud_cover_low": 5,
        "cloud_cover_mid": 5,
        "cloud_cover_high": 5,
        "precipitation_probability": 0,
        "precipitation": 0,
        "temperature_2m": 6,
        "dew_point_2m": 0,
        "relative_humidity_2m": 55,
        "visibility": 24000,
        "wind_speed_10m": 8,
        "wind_gusts_10m": 14,
        "weather_code": 0,
    }
    defaults.update(overrides)
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)]
    hourly = {"time": times}
    for field in HOURLY_FIELDS:
        hourly[field] = [defaults[field] for _ in range(hours)]
    return {"hourly": hourly}


def make_weather(start: datetime, hours: int, **overrides: float) -> WeatherForecast:
    return parse_open_meteo(weather_payload(hours, start.replace(tzinfo=None), **overrides), "America/Edmonton")


def astro_points(
    start: datetime,
    count: int,
    sun_altitude: float = -20,
    *,
    step_minutes: int = 30,
) -> list[AstroPoint]:
    return [
        AstroPoint(
            time=start + timedelta(minutes=step_minutes * index),
            sun_altitude_degrees=sun_altitude,
            moon_altitude_degrees=-10 + index,
            moon_illumination_percent=40,
        )
        for index in range(count)
    ]


def evaluate_with_weather(
    *,
    start: datetime,
    count: int,
    sun_altitude: float,
    weather_overrides: dict[str, float] | None = None,
    cfg: dict | None = None,
) -> dict:
    cfg = cfg or config()
    points = astro_points(start, count, sun_altitude)
    forecast = make_weather(start.replace(minute=0), 12, **(weather_overrides or {}))
    return evaluate_night(start.date(), points, forecast, cfg, datetime(2026, 10, 10, 12, tzinfo=TZ))


def test_valid_open_meteo_response_parsing() -> None:
    forecast = parse_open_meteo(weather_payload(), "America/Edmonton")
    assert len(forecast.records) == 4
    first = min(forecast.records)
    assert forecast.records[first]["cloud_cover"] == 10


def test_missing_hourly_field_is_rejected() -> None:
    payload = weather_payload()
    del payload["hourly"]["cloud_cover"]
    with pytest.raises(WeatherError, match="cloud_cover"):
        parse_open_meteo(payload, "America/Edmonton")


def test_mismatched_hourly_array_lengths_are_rejected() -> None:
    payload = weather_payload()
    payload["hourly"]["cloud_cover"].append(20)
    with pytest.raises(WeatherError, match="expected"):
        parse_open_meteo(payload, "America/Edmonton")


def test_malformed_configuration_is_rejected() -> None:
    cfg = config()
    cfg["scoring"]["weights"]["clouds"] = 10
    with pytest.raises(ConfigError, match="total"):
        validate_config(cfg)


def test_wet_overcast_night_is_poor() -> None:
    night = evaluate_with_weather(
        start=datetime(2026, 10, 10, 21, tzinfo=TZ),
        count=10,
        sun_altitude=-20,
        weather_overrides={"cloud_cover": 95, "precipitation_probability": 80, "precipitation": 2},
    )
    assert night["recommendation"]["level"] == "poor"


def test_marginal_twilight_cloud_conditions_are_visual() -> None:
    night = evaluate_with_weather(
        start=datetime(2026, 10, 10, 21, tzinfo=TZ),
        count=6,
        sun_altitude=-8,
        weather_overrides={"cloud_cover": 55, "cloud_cover_low": 35, "wind_gusts_10m": 28},
    )
    assert night["recommendation"]["level"] == "visual"


def test_short_clear_interval_is_possible() -> None:
    night = evaluate_with_weather(
        start=datetime(2026, 10, 10, 23, tzinfo=TZ),
        count=4,
        sun_altitude=-16,
        weather_overrides={"cloud_cover": 32, "cloud_cover_low": 15, "wind_speed_10m": 12},
    )
    assert night["recommendation"]["level"] == "possible"


def test_strong_clear_interval_is_strong() -> None:
    night = evaluate_with_weather(
        start=datetime(2026, 10, 10, 22, tzinfo=TZ),
        count=6,
        sun_altitude=-20,
        weather_overrides={"cloud_cover": 18, "cloud_cover_low": 8, "wind_speed_10m": 10, "wind_gusts_10m": 18},
    )
    assert night["recommendation"]["level"] == "strong"


def test_exceptional_conditions_are_exceptional() -> None:
    night = evaluate_with_weather(
        start=datetime(2026, 10, 10, 22, tzinfo=TZ),
        count=8,
        sun_altitude=-22,
        weather_overrides={"cloud_cover": 4, "cloud_cover_low": 2, "wind_speed_10m": 5, "wind_gusts_10m": 9},
    )
    assert night["recommendation"]["level"] == "exceptional"


def test_exceptional_conditions_are_difficult_to_reach() -> None:
    night = evaluate_with_weather(
        start=datetime(2026, 10, 10, 22, tzinfo=TZ),
        count=8,
        sun_altitude=-22,
        weather_overrides={"cloud_cover": 13, "cloud_cover_low": 4, "wind_speed_10m": 5, "wind_gusts_10m": 9},
    )
    assert night["recommendation"]["level"] == "strong"


def test_contiguous_window_detection_chooses_stronger_window() -> None:
    cfg = config()
    start = datetime(2026, 10, 10, 21, tzinfo=TZ)
    points = astro_points(start, 12, -20)
    records = {}
    for hour in range(7):
        moment = start.replace(minute=0) + timedelta(hours=hour)
        cloud = 35 if hour < 3 else 5
        if hour == 3:
            cloud = 90
        records[moment] = parse_open_meteo(weather_payload(1, moment.replace(tzinfo=None), cloud_cover=cloud), "America/Edmonton").records[moment]
    night = evaluate_night(start.date(), points, WeatherForecast(records), cfg, datetime(2026, 10, 10, 12, tzinfo=TZ))
    assert night["conditions"]["bestWindow"].startswith("01:00")


def test_clear_conditions_after_midnight_are_discovered() -> None:
    cfg = config()
    start = datetime(2026, 10, 10, 21, tzinfo=TZ)
    points = astro_points(start, 14, -20)
    records = {}
    for hour in range(8):
        moment = start.replace(minute=0) + timedelta(hours=hour)
        cloud = 90 if moment.date() == start.date() else 8
        records[moment] = parse_open_meteo(weather_payload(1, moment.replace(tzinfo=None), cloud_cover=cloud), "America/Edmonton").records[moment]
    night = evaluate_night(start.date(), points, WeatherForecast(records), cfg, datetime(2026, 10, 10, 12, tzinfo=TZ))
    assert night["conditions"]["bestWindow"].startswith("00:00")


def test_calgary_summer_no_astronomical_night_is_reported() -> None:
    points = astro_points(datetime(2026, 6, 20, 22, tzinfo=TZ), 8, -16)
    assert darkness_summary(points)["astronomicalNightOccurs"] is False


def test_moon_illumination_remains_between_zero_and_one_hundred() -> None:
    points = astro_points(datetime(2026, 10, 10, 22, tzinfo=TZ), 4, -20)
    context = moon_context(points, points[0].time, points[-1].time)
    assert 0 <= context["illuminationPercent"] <= 100


def test_weekday_inconvenience_penalty_is_small() -> None:
    cfg = config()
    start = datetime(2026, 10, 12, 23, tzinfo=TZ)
    segment = [
        type("Point", (), {"astro": point, "weather": make_weather(start, 6).at_or_before(point.time)})
        for point in astro_points(start, 6, -22)
    ]
    weekday_score, _ = score_window(segment, 180, cfg, datetime(2026, 10, 10, 12, tzinfo=TZ))
    weekend_cfg = copy.deepcopy(cfg)
    weekend_cfg["scheduling"]["weekendDays"].append("Monday")
    weekend_score, _ = score_window(segment, 180, weekend_cfg, datetime(2026, 10, 10, 12, tzinfo=TZ))
    assert 0 < weekend_score - weekday_score < 2


def test_exceptional_weekday_weather_remains_recommendable() -> None:
    night = evaluate_with_weather(
        start=datetime(2026, 10, 12, 23, tzinfo=TZ),
        count=8,
        sun_altitude=-22,
        weather_overrides={"cloud_cover": 3, "cloud_cover_low": 1, "wind_speed_10m": 4, "wind_gusts_10m": 8},
    )
    assert night["recommendation"]["level"] == "exceptional"


def test_generated_payload_has_exactly_seven_nightly_records() -> None:
    cfg = config()
    nights = [
        evaluate_with_weather(start=datetime(2026, 10, 10 + offset, 22, tzinfo=TZ), count=6, sun_altitude=-20, cfg=cfg)
        for offset in range(7)
    ]
    payload = build_payload(cfg, datetime(2026, 10, 10, 12, tzinfo=TZ).isoformat(), nights)
    validate_output(payload)
    assert len(payload["nights"]) == 7


def test_generated_json_matches_frontend_required_schema() -> None:
    cfg = config()
    night = evaluate_with_weather(start=datetime(2026, 10, 10, 22, tzinfo=TZ), count=6, sun_altitude=-20, cfg=cfg)
    payload = build_payload(cfg, datetime(2026, 10, 10, 12, tzinfo=TZ).isoformat(), [night] * 7)
    validate_output(payload)
    required = payload["nights"][0]["conditions"]
    assert "bestWindow" in required
    assert datetime.fromisoformat(required["bestWindowStart"]).tzinfo is not None
    assert datetime.fromisoformat(required["bestWindowEnd"]).tzinfo is not None
    assert "usableHours" in required
    assert "illuminationPercent" in required["moon"]


def test_atomic_replacement_succeeds(tmp_path: Path) -> None:
    destination = tmp_path / "session-planner.json"
    payload = {"sampleData": False, "location": {}, "generatedAt": "now", "dataSource": "test", "nights": []}
    write_atomic_json(payload, destination)
    assert json.loads(destination.read_text())["dataSource"] == "test"


def test_failed_generation_leaves_previous_json_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "session-planner.json"
    destination.write_text('{"previous": true}\n', encoding="utf-8")

    def fail_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OutputError):
        write_atomic_json({"next": True}, destination)

    assert destination.read_text(encoding="utf-8") == '{"previous": true}\n'
