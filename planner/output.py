from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class OutputError(RuntimeError):
    """Raised when forecast output is invalid or cannot be written safely."""


RECOMMENDATION_LEVELS = {"poor", "visual", "possible", "strong", "exceptional"}


def build_payload(config: dict[str, Any], generated_at: str, nights: list[dict[str, Any]]) -> dict[str, Any]:
    location = config["location"]
    return {
        "sampleData": False,
        "location": {
            "name": location["name"],
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "timezone": location["timezone"],
        },
        "generatedAt": generated_at,
        "dataSource": "Open-Meteo Forecast API with deterministic local solar, lunar, and scoring calculations.",
        "nights": nights,
    }


def validate_output(payload: dict[str, Any], expected_nights: int = 7) -> None:
    if not isinstance(payload, dict):
        raise OutputError("Forecast payload must be an object.")
    for field in ["sampleData", "location", "generatedAt", "dataSource", "nights"]:
        if field not in payload:
            raise OutputError(f"Forecast payload is missing {field}.")
    if payload["sampleData"] is not False:
        raise OutputError("Generated forecasts must set sampleData to false.")
    if not isinstance(payload["nights"], list) or len(payload["nights"]) != expected_nights:
        raise OutputError(f"Forecast payload must contain exactly {expected_nights} nights.")

    for index, night in enumerate(payload["nights"]):
        validate_night(night, index)


def validate_night(night: dict[str, Any], index: int) -> None:
    for field in [
        "date",
        "weekday",
        "recommendation",
        "conditions",
        "suggestedTarget",
        "suggestedEquipment",
        "warnings",
        "explanation",
    ]:
        if field not in night:
            raise OutputError(f"Night {index} is missing {field}.")
    recommendation = night["recommendation"]
    if recommendation.get("level") not in RECOMMENDATION_LEVELS:
        raise OutputError(f"Night {index} has an invalid recommendation level.")
    for field in ["label", "confidence", "score"]:
        if field not in recommendation:
            raise OutputError(f"Night {index} recommendation is missing {field}.")
    if not isinstance(recommendation["score"], (int, float)):
        raise OutputError(f"Night {index} recommendation.score must be numeric.")

    conditions = night["conditions"]
    required_conditions = [
        "bestWindow",
        "usableHours",
        "averageCloudCoverPercent",
        "precipitationProbabilityPercent",
        "wind",
        "temperature",
        "moon",
    ]
    for field in required_conditions:
        if field not in conditions:
            raise OutputError(f"Night {index} conditions is missing {field}.")
    if "sustainedKph" not in conditions["wind"] or "gustKph" not in conditions["wind"]:
        raise OutputError(f"Night {index} wind fields are incomplete.")
    if "expectedC" not in conditions["temperature"] or "dewPointSpreadC" not in conditions["temperature"]:
        raise OutputError(f"Night {index} temperature fields are incomplete.")
    illumination = conditions["moon"].get("illuminationPercent")
    if not isinstance(illumination, (int, float)) or illumination < 0 or illumination > 100:
        raise OutputError(f"Night {index} moon illumination must be between 0 and 100.")


def write_atomic_json(payload: dict[str, Any], destination: str | Path) -> None:
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=destination_path.parent,
            prefix=f".{destination_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination_path)
    except OSError as exc:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise OutputError(f"Could not write forecast atomically: {exc}") from exc
