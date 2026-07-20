#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planner.pipeline import load_json_object_strict
from planner.publication import (
    AUTOMATION_COMMIT_TITLE,
    AUTOMATION_BASE_BRANCH,
    GitHubApi,
    PublicationError,
    validate_automation_pull_request,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify and squash-merge the exact rolling Session Planner PR."
    )
    parser.add_argument("--repository")
    parser.add_argument("--pr-number", type=int)
    parser.add_argument("--expected-head-sha")
    parser.add_argument("--expected-base-sha")
    parser.add_argument(
        "--forecast", type=Path, default=ROOT / "data" / "session-planner.json"
    )
    parser.add_argument("--step-summary", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument(
        "--summary-only-result",
        help="Write a no-merge summary, for disabled or no-change runs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_path = args.step_summary or _environment_path("GITHUB_STEP_SUMMARY")
    output_path = args.github_output or _environment_path("GITHUB_OUTPUT")
    generated_at = _generated_timestamp(args.forecast)

    if args.summary_only_result:
        _write_summary(
            summary_path,
            pr_number=args.pr_number,
            result=args.summary_only_result,
            merged_sha=None,
            generated_at=generated_at,
        )
        return 0

    _require_merge_arguments(args)
    result = "Failed before merge; main was not intentionally changed"
    merged_sha: str | None = None
    try:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        client = GitHubApi(token)
        pull_path = f"/repos/{args.repository}/pulls/{args.pr_number}"
        pull_request = _read_mergeable_pull_request(client, pull_path)
        commits = client.get_all(f"{pull_path}/commits")
        files = client.get_all(f"{pull_path}/files")
        changed_paths = [_required_string(item, "filename") for item in files]

        validate_automation_pull_request(
            pull_request,
            commits,
            changed_paths,
            repository=args.repository,
            expected_pr_number=args.pr_number,
            expected_head_sha=args.expected_head_sha,
            expected_base_sha=args.expected_base_sha,
        )

        # Begin a final verification pass immediately before the SHA-pinned merge.
        pull_request = _read_mergeable_pull_request(client, pull_path)
        commits = client.get_all(f"{pull_path}/commits")
        files = client.get_all(f"{pull_path}/files")
        changed_paths = [_required_string(item, "filename") for item in files]
        validate_automation_pull_request(
            pull_request,
            commits,
            changed_paths,
            repository=args.repository,
            expected_pr_number=args.pr_number,
            expected_head_sha=args.expected_head_sha,
            expected_base_sha=args.expected_base_sha,
        )

        # Read main last so a base update during the PR checks is also rejected.
        main_ref = client.get(
            f"/repos/{args.repository}/git/ref/heads/"
            f"{quote(AUTOMATION_BASE_BRANCH, safe='')}"
        )
        main_object = main_ref.get("object") if isinstance(main_ref, dict) else None
        main_sha = main_object.get("sha") if isinstance(main_object, dict) else None
        if main_sha != args.expected_base_sha:
            raise PublicationError("Main advanced during generation; refusing to merge.")

        merge_response = client.request(
            "PUT",
            f"{pull_path}/merge",
            {
                "commit_title": AUTOMATION_COMMIT_TITLE,
                "merge_method": "squash",
                "sha": args.expected_head_sha,
            },
        )
        if (
            not isinstance(merge_response, dict)
            or merge_response.get("merged") is not True
        ):
            message = (
                merge_response.get("message", "unknown response")
                if isinstance(merge_response, dict)
                else "invalid response"
            )
            raise PublicationError(f"GitHub declined the squash merge: {message}")
        merged_sha = _required_string(merge_response, "sha")
        result = "Squash merge succeeded"
        _write_output(output_path, "merged_commit_sha", merged_sha)
        _write_output(output_path, "merge_result", "merged")
        return 0
    finally:
        _write_summary(
            summary_path,
            pr_number=args.pr_number,
            result=result,
            merged_sha=merged_sha,
            generated_at=generated_at,
        )


def _read_mergeable_pull_request(client: GitHubApi, path: str) -> dict[str, Any]:
    for attempt in range(6):
        payload = client.get(path)
        if not isinstance(payload, dict):
            raise PublicationError("GitHub returned invalid pull request metadata.")
        if payload.get("mergeable") is not None:
            return payload
        if attempt < 5:
            time.sleep(2)
    raise PublicationError("GitHub did not determine pull request mergeability in time.")


def _require_merge_arguments(args: argparse.Namespace) -> None:
    missing = [
        name
        for name, value in (
            ("--repository", args.repository),
            ("--pr-number", args.pr_number),
            ("--expected-head-sha", args.expected_head_sha),
            ("--expected-base-sha", args.expected_base_sha),
        )
        if not value
    ]
    if missing:
        raise SystemExit("Automatic merge requires " + ", ".join(missing))


def _generated_timestamp(path: Path) -> str:
    forecast = load_json_object_strict(path, "forecast output")
    generated_at = forecast.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at:
        raise PublicationError("Forecast output is missing generatedAt.")
    return generated_at


def _required_string(payload: Any, key: str) -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value:
        raise PublicationError(f"GitHub response is missing {key}.")
    return value


def _environment_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def _write_output(path: Path | None, name: str, value: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def _write_summary(
    path: Path | None,
    *,
    pr_number: int | None,
    result: str,
    merged_sha: str | None,
    generated_at: str,
) -> None:
    if path is None:
        return
    lines = [
        "",
        "## Automatic forecast merge",
        "",
        f"- PR number: {pr_number if pr_number is not None else 'N/A'}",
        f"- Merge result: {result}",
        f"- Merged commit SHA: {merged_sha or 'N/A'}",
        f"- Generated timestamp: {generated_at}",
        "- Reminder: verify the live site during the initial automated runs.",
        "",
    ]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
