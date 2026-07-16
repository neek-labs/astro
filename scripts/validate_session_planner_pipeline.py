from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.pipeline import PipelineValidationError, validate_pipeline_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the complete generated Session Planner pipeline."
    )
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
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "session-planner.json")
    parser.add_argument("--now", help="Timezone-aware ISO validation time for deterministic testing.")
    parser.add_argument("--maximum-age-minutes", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
        if args.maximum_age_minutes < 1:
            raise PipelineValidationError("--maximum-age-minutes must be positive.")
        validate_pipeline_files(
            args.forecast,
            args.visibility,
            args.catalogue,
            args.config,
            now=now,
            maximum_age=timedelta(minutes=args.maximum_age_minutes),
        )
    except (PipelineValidationError, ValueError) as exc:
        print(f"Session Planner pipeline validation failed: {exc}", file=sys.stderr)
        return 1
    print("Session Planner pipeline validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
