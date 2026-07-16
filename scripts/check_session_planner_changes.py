from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.pipeline import PipelineValidationError, git_changed_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enforce the generated Session Planner changed-file allowlist."
    )
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--base", help="Base ref for validating an existing automation branch.")
    parser.add_argument("--head", help="Head ref for validating an existing automation branch.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        paths = git_changed_paths(
            args.repository,
            base=args.base,
            head=args.head,
        )
    except PipelineValidationError as exc:
        print(f"Generated-file allowlist check failed: {exc}", file=sys.stderr)
        return 1
    if paths:
        print("Allowed generated changes:")
        for path in paths:
            print(f"- {path}")
    else:
        print("No generated files changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
