from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests


HOURLY_FIELDS = [
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "precipitation_probability",
    "precipitation",
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "visibility",
    "wind_speed_10m",
    "wind_gusts_10m",
    "weather_code",
]


class WeatherError(RuntimeError):
    """Raised when Open-Meteo data cannot be fetched or validated."""


@dataclass(frozen=True)
class WeatherForecast:
    records: dict[datetime, dict[str, float]]

    def at_or_before(self, moment: datetime) -> dict[str, float]:
        if moment.tzinfo is None:
            raise WeatherError("Weather lookup requires a timezone-aware datetime.")
        rounded = moment.replace(minute=0, second=0, microsecond=0)
        if rounded in self.records:
            return self.records[rounded]

        candidates = [time for time in self.records if time <= moment]
        if candidates:
            nearest = max(candidates)
            if moment - nearest <= timedelta(minutes=90):
                return self.records[nearest]
            raise WeatherError(f"No recent hourly weather value is available for {moment.isoformat()}.")

        future = [time for time in self.records if time > moment]
        if future:
            nearest = min(future)
            if nearest - moment <= timedelta(minutes=60):
                return self.records[nearest]
            raise WeatherError(f"No nearby hourly weather value is available for {moment.isoformat()}.")

        raise WeatherError("Weather forecast contains no hourly records.")


def fetch_open_meteo(config: dict[str, Any], session: Any = requests) -> WeatherForecast:
    location = config["location"]
    weather_config = config["weather"]
    forecast_config = config["forecast"]
    fields = weather_config.get("hourlyFields", HOURLY_FIELDS)
    timeouts = weather_config["timeouts"]

    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "timezone": location["timezone"],
        "forecast_days": forecast_config["openMeteoForecastDays"],
        "hourly": ",".join(fields),
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
    }
    headers = {"User-Agent": weather_config["userAgent"]}
    timeout = (timeouts["connectSeconds"], timeouts["readSeconds"])

    try:
        response = session.get(
            weather_config["openMeteoUrl"],
            params=params,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherError(f"Open-Meteo request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise WeatherError("Open-Meteo response was not valid JSON.") from exc

    return parse_open_meteo(payload, location["timezone"], fields)


def parse_open_meteo(
    payload: dict[str, Any],
    timezone_name: str,
    required_fields: list[str] | None = None,
) -> WeatherForecast:
    fields = required_fields or HOURLY_FIELDS
    if not isinstance(payload, dict):
        raise WeatherError("Open-Meteo response root must be an object.")
    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        raise WeatherError("Open-Meteo response is missing hourly data.")
    if not isinstance(hourly.get("time"), list):
        raise WeatherError("Open-Meteo hourly.time must be an array.")

    times = hourly["time"]
    expected_length = len(times)
    if expected_length == 0:
        raise WeatherError("Open-Meteo hourly.time is empty.")

    for field in fields:
        if field not in hourly:
            raise WeatherError(f"Open-Meteo response is missing hourly.{field}.")
        if not isinstance(hourly[field], list):
            raise WeatherError(f"Open-Meteo hourly.{field} must be an array.")
        if len(hourly[field]) != expected_length:
            raise WeatherError(
                f"Open-Meteo hourly.{field} has {len(hourly[field])} values; expected {expected_length}."
            )

    timezone = ZoneInfo(timezone_name)
    parsed_times: list[datetime] = []
    for raw_time in times:
        try:
            parsed = datetime.fromisoformat(raw_time).replace(tzinfo=timezone)
        except (TypeError, ValueError) as exc:
            raise WeatherError(f"Invalid Open-Meteo timestamp: {raw_time!r}.") from exc
        parsed_times.append(parsed)

    if len(set(parsed_times)) != len(parsed_times):
        raise WeatherError("Open-Meteo timestamps must be unique.")
    if parsed_times != sorted(parsed_times):
        raise WeatherError("Open-Meteo timestamps must be ordered.")

    records: dict[datetime, dict[str, float]] = {}
    for index, timestamp in enumerate(parsed_times):
        values: dict[str, float] = {}
        for field in fields:
            raw_value = hourly[field][index]
            if isinstance(raw_value, (int, float)):
                values[field] = float(raw_value)
            else:
                raise WeatherError(f"Open-Meteo hourly.{field} contains a missing or non-numeric value.")
        records[timestamp] = values

    return WeatherForecast(records)
