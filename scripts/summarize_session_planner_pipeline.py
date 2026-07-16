from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.pipeline import (
    PipelineValidationError,
    build_pipeline_markdown_summary,
    load_json_object_strict,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build deterministic Markdown for a Session Planner refresh."
    )
    parser.add_argument("--forecast", type=Path, default=ROOT / "data" / "session-planner.json")
    parser.add_argument("--output", type=Path, help="Write Markdown to this path instead of stdout.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        forecast = load_json_object_strict(args.forecast, "forecast output")
        summary = build_pipeline_markdown_summary(forecast)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(summary, encoding="utf-8")
        else:
            print(summary, end="")
    except (PipelineValidationError, OSError) as exc:
        print(f"Session Planner summary generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
