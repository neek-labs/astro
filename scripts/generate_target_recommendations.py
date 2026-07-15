from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.config import ConfigError, load_config
from planner.output import OutputError, write_atomic_json
from planner.target_recommendations import (
    TargetRecommendationError,
    enrich_forecast_payload,
    load_json_object,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank nightly targets by weather-window overlap, altitude, and Moon impact."
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "session-planner.json")
    parser.add_argument("--forecast", type=Path, default=ROOT / "data" / "session-planner.json")
    parser.add_argument(
        "--visibility",
        type=Path,
        default=ROOT / "data" / "astronomy-target-visibility.json",
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=ROOT / "data" / "astronomy-targets-master-stage3b-coordinates.json",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "session-planner.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
        forecast = load_json_object(args.forecast, "forecast input")
        visibility = load_json_object(args.visibility, "visibility input")
        catalogue = load_json_object(args.catalogue, "target catalogue")
        enriched, summaries = enrich_forecast_payload(
            forecast, visibility, catalogue, config
        )
        write_atomic_json(enriched, args.output)
    except (
        ConfigError,
        OutputError,
        TargetRecommendationError,
        OSError,
        ValueError,
    ) as exc:
        print(f"Target recommendation generation failed: {exc}", file=sys.stderr)
        return 1

    for summary in summaries:
        print(f"Night: {summary['date']}")
        print(f"Weather: {summary['weather']}")
        print(f"Candidates evaluated: {summary['candidates_evaluated']}")
        print(f"Eligible candidates: {summary['eligible_candidates']}")
        for rank, target in enumerate(summary["top_targets"], start=1):
            print(f"{rank}. {target['display_name']} - {target['score']:.1f}")
        if not summary["top_targets"]:
            print("No formal target recommendations.")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
