from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    """Raised when the session planner configuration is invalid."""


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read configuration: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Configuration is not valid JSON: {exc}") from exc

    validate_config(data)
    return data


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ConfigError("Configuration root must be an object.")

    required_sections = [
        "location",
        "forecast",
        "weather",
        "limits",
        "scoring",
        "classification",
        "scheduling",
    ]
    for section in required_sections:
        if not isinstance(config.get(section), dict):
            raise ConfigError(f"Missing configuration section: {section}.")

    location = config["location"]
    for field in ["name", "timezone"]:
        if not location.get(field):
            raise ConfigError(f"Missing location.{field}.")
    for field in ["latitude", "longitude", "elevationMeters"]:
        require_number(location, field)
    try:
        ZoneInfo(location["timezone"])
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Unknown timezone: {location['timezone']}.") from exc

    forecast = config["forecast"]
    require_int(forecast, "lengthNights", minimum=1)
    require_int(forecast, "gridMinutes", minimum=15)
    require_int(forecast, "openMeteoForecastDays", minimum=2)

    weather = config["weather"]
    if not weather.get("openMeteoUrl"):
        raise ConfigError("Missing weather.openMeteoUrl.")
    if not weather.get("userAgent"):
        raise ConfigError("Missing weather.userAgent.")
    if not isinstance(weather.get("hourlyFields"), list) or not weather["hourlyFields"]:
        raise ConfigError("weather.hourlyFields must be a non-empty list.")
    timeouts = weather.get("timeouts", {})
    require_number(timeouts, "connectSeconds", minimum=0.1)
    require_number(timeouts, "readSeconds", minimum=0.1)

    limits = config["limits"]
    for section in ["hardBlockers", "visualCandidate", "imagingCandidate", "strong", "exceptional"]:
        if not isinstance(limits.get(section), dict):
            raise ConfigError(f"Missing limits.{section}.")

    require_int(limits["visualCandidate"], "minimumMinutes", minimum=1)
    require_int(limits["imagingCandidate"], "minimumMinutes", minimum=1)
    require_int(limits["strong"], "minimumMinutes", minimum=1)
    require_int(limits["exceptional"], "minimumMinutes", minimum=1)

    weights = config["scoring"].get("weights")
    if not isinstance(weights, dict) or not weights:
        raise ConfigError("scoring.weights must be a non-empty object.")
    total = sum(float(value) for value in weights.values())
    if abs(total - 100.0) > 0.01:
        raise ConfigError(f"scoring.weights must total 100, got {total}.")

    thresholds = config["classification"].get("thresholds")
    if not isinstance(thresholds, dict):
        raise ConfigError("classification.thresholds must be an object.")
    for level in ["visual", "possible", "strong", "exceptional"]:
        require_number(thresholds, level, minimum=0, maximum=100)

    scheduling = config["scheduling"]
    if not isinstance(scheduling.get("weekendDays"), list):
        raise ConfigError("scheduling.weekendDays must be a list.")
    require_number(scheduling, "weekdayLateNightPenaltyPoints", minimum=0, maximum=20)


def require_number(
    section: dict[str, Any],
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    value = section.get(field)
    if not isinstance(value, (int, float)):
        raise ConfigError(f"Expected numeric value for {field}.")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{field} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{field} must be at most {maximum}.")


def require_int(section: dict[str, Any], field: str, *, minimum: int | None = None) -> None:
    value = section.get(field)
    if not isinstance(value, int):
        raise ConfigError(f"Expected integer value for {field}.")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{field} must be at least {minimum}.")
