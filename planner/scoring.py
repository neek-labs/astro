from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any

from planner.astronomy import AstroPoint, darkness_summary, moon_context
from planner.weather import WeatherForecast


LEVEL_LABELS = {
    "poor": "Don't bother",
    "visual": "Visual only",
    "possible": "Imaging possible",
    "strong": "Imaging night",
    "exceptional": "Exceptional imaging night",
}


@dataclass(frozen=True)
class CandidatePoint:
    astro: AstroPoint
    weather: dict[str, float]


@dataclass(frozen=True)
class CandidateWindow:
    start: datetime
    end: datetime
    minutes: int
    points: list[CandidatePoint]
    score: float
    score_breakdown: dict[str, float]


def evaluate_night(
    evening_date: date,
    astro_points: list[AstroPoint],
    weather: WeatherForecast,
    config: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    interval_minutes = config["forecast"]["gridMinutes"]
    point_rows = [CandidatePoint(point, weather.at_or_before(point.time)) for point in astro_points]

    visual_window = best_window(
        point_rows,
        config,
        threshold_degrees=-6,
        limits_name="visualCandidate",
        interval_minutes=interval_minutes,
        generated_at=generated_at,
    )
    imaging_window = best_window(
        point_rows,
        config,
        threshold_degrees=-12,
        limits_name="imagingCandidate",
        interval_minutes=interval_minutes,
        generated_at=generated_at,
    )
    chosen = imaging_window or visual_window

    if imaging_window:
        level = classify_imaging_window(imaging_window, config)
    elif visual_window:
        level = "visual" if visual_window.score >= config["classification"]["thresholds"]["visual"] else "poor"
    else:
        level = "poor"

    if level == "exceptional" and not exceptional_thresholds_met(imaging_window, config):
        level = "strong"

    warnings = build_warnings(level, chosen, point_rows, config)
    if weekday_penalty_applies(chosen, config):
        warnings.append("Weekday window runs substantially after midnight; schedule fatigue penalty applied.")

    reasons = build_reasons(level, chosen, visual_window, imaging_window, point_rows)
    score = round(chosen.score if chosen else 0)
    confidence = forecast_confidence(generated_at, evening_date)
    moon = moon_context(astro_points, chosen.start if chosen else None, chosen.end if chosen else None)
    darkness = darkness_summary(astro_points)
    metrics = summarize_window(chosen.points if chosen else []) if chosen else empty_metrics()
    visual_hours = round(visual_window.minutes / 60, 2) if visual_window else 0
    imaging_hours = round(imaging_window.minutes / 60, 2) if imaging_window else 0

    if not darkness["astronomicalNightOccurs"]:
        warnings.append("Calgary does not reach true astronomical darkness for this observing night.")

    return {
        "date": evening_date.isoformat(),
        "weekday": evening_date.strftime("%A"),
        "forecastLeadHours": forecast_lead_hours(generated_at, astro_points),
        "recommendation": {
            "label": LEVEL_LABELS[level],
            "level": level,
            "confidence": confidence,
            "score": score,
        },
        "conditions": {
            "bestWindow": format_window(chosen),
            "usableHours": round((chosen.minutes / 60) if chosen else 0, 2),
            "visualUsableHours": visual_hours,
            "imagingUsableHours": imaging_hours,
            "astronomicalNightOccurs": darkness["astronomicalNightOccurs"],
            "averageCloudCoverPercent": round(metrics["cloud_cover"]),
            "averageLowCloudCoverPercent": round(metrics["cloud_cover_low"]),
            "precipitationProbabilityPercent": round(metrics["precipitation_probability"]),
            "averageHumidityPercent": round(metrics["relative_humidity_2m"]),
            "visibilityKm": round(metrics["visibility"] / 1000, 1),
            "wind": {
                "sustainedKph": round(metrics["wind_speed_10m"]),
                "gustKph": round(metrics["wind_gusts_10m"]),
            },
            "temperature": {
                "expectedC": round(metrics["temperature_2m"], 1),
                "dewPointSpreadC": round(metrics["dew_point_spread"], 1),
            },
            "moon": moon,
        },
        "suggestedTarget": suggested_target(level),
        "suggestedEquipment": suggested_equipment(level),
        "warnings": warnings,
        "explanation": explanation_for(level, chosen, reasons),
        "scoreBreakdown": chosen.score_breakdown if chosen else {},
        "reasons": reasons,
    }


def best_window(
    points: list[CandidatePoint],
    config: dict[str, Any],
    *,
    threshold_degrees: float,
    limits_name: str,
    interval_minutes: int,
    generated_at: datetime,
) -> CandidateWindow | None:
    limits = config["limits"][limits_name]
    segments: list[list[CandidatePoint]] = []
    current: list[CandidatePoint] = []
    for point in points:
        qualifies = (
            point.astro.sun_altitude_degrees < threshold_degrees
            and weather_qualifies(point.weather, limits)
            and not hard_blocked(point.weather, config)
        )
        if qualifies:
            current.append(point)
        elif current:
            segments.append(current)
            current = []
    if current:
        segments.append(current)

    candidates: list[CandidateWindow] = []
    for segment in segments:
        minutes = len(segment) * interval_minutes
        if minutes < limits["minimumMinutes"]:
            continue
        start = segment[0].astro.time
        end = segment[-1].astro.time + timedelta(minutes=interval_minutes)
        score, breakdown = score_window(segment, minutes, config, generated_at)
        candidates.append(CandidateWindow(start, end, minutes, segment, score, breakdown))

    if not candidates:
        return None
    return max(candidates, key=lambda window: (window.score, window.minutes))


def weather_qualifies(weather: dict[str, float], limits: dict[str, Any]) -> bool:
    spread = dew_point_spread(weather)
    checks = [
        weather["cloud_cover"] <= limits["maxCloudCoverPercent"],
        weather["precipitation_probability"] <= limits["maxPrecipitationProbabilityPercent"],
        weather["precipitation"] <= limits.get("maxPrecipitationMm", 0),
        weather["wind_speed_10m"] <= limits["maxWindKph"],
        weather["wind_gusts_10m"] <= limits["maxGustKph"],
        spread >= limits["minDewPointSpreadC"],
        weather["visibility"] >= limits["minVisibilityMeters"],
    ]
    return all(checks)


def hard_blocked(weather: dict[str, float], config: dict[str, Any]) -> bool:
    limits = config["limits"]["hardBlockers"]
    return (
        weather["precipitation"] > limits["maxPrecipitationMm"]
        or weather["precipitation_probability"] > limits["maxPrecipitationProbabilityPercent"]
        or weather["cloud_cover"] > limits["maxCloudCoverPercent"]
        or weather["wind_gusts_10m"] > limits["maxGustKph"]
        or dew_point_spread(weather) < limits["minDewPointSpreadC"]
    )


def score_window(
    segment: list[CandidatePoint],
    minutes: int,
    config: dict[str, Any],
    generated_at: datetime,
) -> tuple[float, dict[str, float]]:
    metrics = summarize_window(segment)
    weights = config["scoring"]["weights"]
    exceptional_minutes = config["limits"]["exceptional"]["minimumMinutes"]
    convenience = 100 - (config["scheduling"]["weekdayLateNightPenaltyPoints"] if weekday_penalty_applies_by_times(segment[0].astro.time, segment[-1].astro.time, config) else 0)
    min_sun = min(point.astro.sun_altitude_degrees for point in segment)
    darkness = 100 if min_sun < -18 else 70 if min_sun < -12 else 40

    raw_scores = {
        "clouds": (inverse_score(metrics["cloud_cover"], 80) * 0.7) + (inverse_score(metrics["cloud_cover_low"], 80) * 0.3),
        "precipitation": inverse_score(metrics["precipitation_probability"], 40),
        "duration": min(100, minutes / exceptional_minutes * 100),
        "wind": (inverse_score(metrics["wind_speed_10m"], 40) * 0.55) + (inverse_score(metrics["wind_gusts_10m"], 50) * 0.45),
        "dewHumidity": (min(100, metrics["dew_point_spread"] / 4 * 100) * 0.65) + (inverse_score(metrics["relative_humidity_2m"], 100) * 0.35),
        "visibility": min(100, max(0, (metrics["visibility"] / 1000 - 5) / 15 * 100)),
        "darkness": darkness,
        "convenience": convenience,
    }
    score = sum(raw_scores[key] * (weights[key] / 100) for key in weights)
    return round(max(0, min(100, score)), 1), {key: round(value, 1) for key, value in raw_scores.items()}


def summarize_window(segment: list[CandidatePoint]) -> dict[str, float]:
    if not segment:
        return empty_metrics()
    weather_rows = [point.weather for point in segment]
    return {
        "cloud_cover": mean(row["cloud_cover"] for row in weather_rows),
        "cloud_cover_low": mean(row["cloud_cover_low"] for row in weather_rows),
        "precipitation_probability": mean(row["precipitation_probability"] for row in weather_rows),
        "relative_humidity_2m": mean(row["relative_humidity_2m"] for row in weather_rows),
        "visibility": mean(row["visibility"] for row in weather_rows),
        "wind_speed_10m": mean(row["wind_speed_10m"] for row in weather_rows),
        "wind_gusts_10m": mean(row["wind_gusts_10m"] for row in weather_rows),
        "temperature_2m": mean(row["temperature_2m"] for row in weather_rows),
        "dew_point_spread": mean(dew_point_spread(row) for row in weather_rows),
    }


def empty_metrics() -> dict[str, float]:
    return {
        "cloud_cover": 0,
        "cloud_cover_low": 0,
        "precipitation_probability": 0,
        "relative_humidity_2m": 0,
        "visibility": 0,
        "wind_speed_10m": 0,
        "wind_gusts_10m": 0,
        "temperature_2m": 0,
        "dew_point_spread": 0,
    }


def classify_imaging_window(window: CandidateWindow, config: dict[str, Any]) -> str:
    thresholds = config["classification"]["thresholds"]
    if window.score >= thresholds["exceptional"] and exceptional_thresholds_met(window, config):
        return "exceptional"
    if window.score >= thresholds["strong"] and named_limits_met(window, config, "strong"):
        return "strong"
    if window.score >= thresholds["possible"]:
        return "possible"
    if window.score >= thresholds["visual"]:
        return "visual"
    return "poor"


def named_limits_met(window: CandidateWindow | None, config: dict[str, Any], name: str) -> bool:
    if not window:
        return False
    limits = config["limits"][name]
    metrics = summarize_window(window.points)
    return (
        window.minutes >= limits["minimumMinutes"]
        and metrics["cloud_cover"] <= limits["maxCloudCoverPercent"]
        and metrics["precipitation_probability"] <= limits["maxPrecipitationProbabilityPercent"]
        and metrics["wind_speed_10m"] <= limits["maxWindKph"]
        and metrics["wind_gusts_10m"] <= limits["maxGustKph"]
        and metrics["dew_point_spread"] >= limits["minDewPointSpreadC"]
    )


def exceptional_thresholds_met(window: CandidateWindow | None, config: dict[str, Any]) -> bool:
    return named_limits_met(window, config, "exceptional")


def build_warnings(
    level: str,
    chosen: CandidateWindow | None,
    points: list[CandidatePoint],
    config: dict[str, Any],
) -> list[str]:
    if not chosen:
        return ["No contiguous window met the configured darkness and weather limits."]
    metrics = summarize_window(chosen.points)
    warnings: list[str] = []
    if metrics["cloud_cover"] > config["limits"]["strong"]["maxCloudCoverPercent"]:
        warnings.append("Cloud cover is above strong-imaging thresholds.")
    if metrics["dew_point_spread"] < config["limits"]["strong"]["minDewPointSpreadC"]:
        warnings.append("Dew-point spread is tight; watch for dew formation.")
    if metrics["wind_gusts_10m"] > config["limits"]["strong"]["maxGustKph"]:
        warnings.append("Wind gusts may reduce imaging quality.")
    if level in {"poor", "visual"}:
        warnings.append("Conditions are not strong enough for a planned imaging session.")
    return warnings


def build_reasons(
    level: str,
    chosen: CandidateWindow | None,
    visual_window: CandidateWindow | None,
    imaging_window: CandidateWindow | None,
    points: list[CandidatePoint],
) -> list[str]:
    if not chosen:
        return ["No qualifying contiguous visual or imaging window was found."]
    metrics = summarize_window(chosen.points)
    reasons = [
        f"Best contiguous window is {round(chosen.minutes / 60, 2)} hours.",
        f"Average cloud cover is {round(metrics['cloud_cover'])}%.",
        f"Average precipitation probability is {round(metrics['precipitation_probability'])}%.",
    ]
    if imaging_window:
        reasons.append("The selected window meets imaging darkness and weather limits.")
    elif visual_window:
        reasons.append("Only visual-usable conditions met the configured limits.")
    if level == "exceptional":
        reasons.append("Exceptional thresholds require very low cloud, calm wind, dry air, and at least three hours.")
    return reasons


def explanation_for(level: str, chosen: CandidateWindow | None, reasons: list[str]) -> str:
    if not chosen:
        return "No usable observing interval met the configured weather and darkness limits."
    return f"{LEVEL_LABELS[level]}: " + " ".join(reasons)


def suggested_target(level: str) -> str:
    if level == "poor":
        return "No observing target recommended"
    if level == "visual":
        return "Bright visual targets; detailed recommendations arrive in Stage 3"
    return "Target recommendations arrive in Stage 3"


def suggested_equipment(level: str) -> str:
    if level == "poor":
        return "None recommended"
    if level == "visual":
        return "NexStar 6SE or EdgeHD 8 on the alt-az mount"
    return "EdgeHD 8 with CGEM II or Zenithstar 61 with Star Adventurer"


def format_window(window: CandidateWindow | None) -> str:
    if not window:
        return "No reliable window"
    timezone_name = window.start.tzname() or ""
    return f"{window.start:%H:%M}-{window.end:%H:%M} {timezone_name}".strip()


def forecast_confidence(generated_at: datetime, evening_date: date) -> str:
    lead_hours = (datetime.combine(evening_date, datetime.min.time(), tzinfo=generated_at.tzinfo) - generated_at).total_seconds() / 3600
    if lead_hours <= 48:
        return "High"
    if lead_hours <= 120:
        return "Medium"
    return "Low"


def forecast_lead_hours(generated_at: datetime, astro_points: list[AstroPoint]) -> float:
    if not astro_points:
        return 0
    lead = (astro_points[0].time - generated_at).total_seconds() / 3600
    return round(max(0, lead), 1)


def weekday_penalty_applies(window: CandidateWindow | None, config: dict[str, Any]) -> bool:
    if not window:
        return False
    return weekday_penalty_applies_by_times(window.start, window.end, config)


def weekday_penalty_applies_by_times(start: datetime, end: datetime, config: dict[str, Any]) -> bool:
    if start.strftime("%A") in config["scheduling"]["weekendDays"]:
        return False
    return end.date() > start.date() and end.hour >= config["scheduling"]["lateNightHour"]


def inverse_score(value: float, max_bad: float) -> float:
    return max(0, min(100, 100 - (value / max_bad * 100)))


def dew_point_spread(weather: dict[str, float]) -> float:
    return weather["temperature_2m"] - weather["dew_point_2m"]
