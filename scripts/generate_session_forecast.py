from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.astronomy import calculate_astronomy_grid, observing_bounds
from planner.config import ConfigError, load_config
from planner.output import OutputError, build_payload, validate_output, write_atomic_json
from planner.scoring import evaluate_night
from planner.weather import WeatherError, fetch_open_meteo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Calgary astronomy session forecast JSON.")
    parser.add_argument("--config", default=ROOT / "config" / "session-planner.json", type=Path)
    parser.add_argument("--output", default=ROOT / "data" / "session-planner.json", type=Path)
    parser.add_argument("--now", help="Timezone-aware ISO timestamp for deterministic local testing.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
        timezone = ZoneInfo(config["location"]["timezone"])
        generated_at = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone)
        generated_at = generated_at.astimezone(timezone)

        weather = fetch_open_meteo(config)
        nights = []
        for offset in range(config["forecast"]["lengthNights"]):
            evening_date = generated_at.date() + timedelta(days=offset)
            start, end = observing_bounds(evening_date, config["location"]["timezone"])
            astro_points = calculate_astronomy_grid(config, start, end)
            nights.append(evaluate_night(evening_date, astro_points, weather, config, generated_at))

        payload = build_payload(config, generated_at.isoformat(), nights)
        validate_output(payload, expected_nights=config["forecast"]["lengthNights"])
        write_atomic_json(payload, args.output)
    except (ConfigError, WeatherError, OutputError, RuntimeError) as exc:
        print(f"Session forecast generation failed: {exc}", file=sys.stderr)
        return 1

    print("Generated Calgary session forecast:")
    for night in payload["nights"]:
        recommendation = night["recommendation"]
        print(
            f"- {night['weekday']} {night['date']}: "
            f"{recommendation['label']} ({recommendation['score']}/100), "
            f"{night['conditions']['bestWindow']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
