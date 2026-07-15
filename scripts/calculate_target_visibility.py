from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.config import ConfigError, load_config
from planner.visibility import (
    DarknessWindow,
    VisibilityError,
    build_nightly_visibility,
    build_visibility_payload,
    calculate_useful_darkness_window,
    load_darkness_windows,
    load_target_catalogue,
    write_visibility_output,
)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate geometry-only visibility for the Calgary target catalogue."
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "session-planner.json")
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=ROOT / "data" / "astronomy-targets-master-stage3b-coordinates.json",
    )
    parser.add_argument("--forecast", type=Path, default=ROOT / "data" / "session-planner.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "astronomy-target-visibility.json",
    )
    parser.add_argument("--date", type=parse_date, help="First local observing date (YYYY-MM-DD).")
    parser.add_argument("--days", type=int, help="Number of observing nights to calculate.")
    return parser.parse_args()


def display_label(target: dict[str, Any]) -> str:
    name = target.get("display_name") or target.get("primary_catalog_id") or target.get("id")
    catalogue_id = target.get("primary_catalog_id")
    if catalogue_id and name != catalogue_id:
        return f"{name} ({catalogue_id})"
    return str(name)


def print_summary(
    nights: list[dict[str, Any]],
    targets: list[dict[str, Any]],
) -> None:
    labels = {target.get("id"): display_label(target) for target in targets if isinstance(target, dict)}
    for night in nights:
        records = night["targets"]
        observable = [record for record in records if record["observable"]]
        excellent = [record for record in records if record["visibility_rating"] == "excellent"]
        review = [record for record in records if record["review_flags"]]
        start = datetime.fromisoformat(night["darkness_start"]) if night["darkness_start"] else None
        end = datetime.fromisoformat(night["darkness_end"]) if night["darkness_end"] else None
        darkness_text = f"{start:%H:%M}–{end:%H:%M}" if start and end else "unavailable"
        print(f"Night: {night['date']}")
        print(f"Darkness: {darkness_text}")
        print(f"Targets processed: {len(records)}")
        print(f"Observable: {len(observable)}")
        print(f"Excellent: {len(excellent)}")
        print(f"Review required: {len(review)}")
        print("\nTop targets:")
        for index, record in enumerate(observable[:3], start=1):
            label = labels.get(record["target_id"], record["target_id"])
            print(
                f"{index}. {label} — {record['observable_minutes']} min — "
                f"{record['maximum_altitude_deg']:.1f}°"
            )
        if not observable:
            print("None")
        print()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        config = load_config(args.config)
        timezone = ZoneInfo(config["location"]["timezone"])
        generated_at = datetime.now(timezone)
        first_date = args.date or generated_at.date()
        days = args.days if args.days is not None else config["targetVisibility"]["forecastDays"]
        if days < 1:
            raise VisibilityError("--days must be at least 1.")

        catalogue = load_target_catalogue(args.catalogue)
        explicit_windows = load_darkness_windows(args.forecast, config["location"]["timezone"])
        nights: list[dict[str, Any]] = []
        for offset in range(days):
            evening_date = first_date + timedelta(days=offset)
            darkness: DarknessWindow = explicit_windows.get(evening_date.isoformat()) or (
                calculate_useful_darkness_window(evening_date, config)
            )
            nights.append(
                build_nightly_visibility(evening_date, darkness, catalogue["targets"], config)
            )

        payload = build_visibility_payload(config, generated_at, nights, days)
        write_visibility_output(payload, args.output)
    except (ConfigError, VisibilityError, RuntimeError, OSError, ValueError) as exc:
        print(f"Target visibility generation failed: {exc}", file=sys.stderr)
        return 1

    print_summary(nights, catalogue["targets"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
