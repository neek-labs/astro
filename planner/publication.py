from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from planner.pipeline import PipelineValidationError, validate_changed_paths


AUTOMATION_BASE_BRANCH = "main"
AUTOMATION_HEAD_BRANCH = "automation/session-planner-refresh"
AUTOMATION_PR_TITLE = "[automation] Refresh session planner forecast"
AUTOMATION_COMMIT_TITLE = "chore: refresh session planner forecast"
GITHUB_ACTIONS_BOT_LOGIN = "github-actions[bot]"
GITHUB_ACTIONS_BOT_EMAIL = (
    "41898282+github-actions[bot]@users.noreply.github.com"
)


class PublicationError(PipelineValidationError):
    """Raised when the rolling automation pull request is unsafe to merge."""


@dataclass(frozen=True)
class MergeDecision:
    pr_number: int
    head_sha: str
    base_sha: str
    changed_paths: tuple[str, ...]


def validate_automation_pull_request(
    pull_request: Mapping[str, Any],
    commits: Iterable[Mapping[str, Any]],
    changed_paths: Iterable[str],
    *,
    repository: str,
    expected_pr_number: int,
    expected_head_sha: str,
    expected_base_sha: str,
) -> MergeDecision:
    """Fail closed unless this is the exact safe Stage 4D automation PR."""

    if pull_request.get("number") != expected_pr_number:
        raise PublicationError("Pull request number does not match the expected PR.")
    if pull_request.get("title") != AUTOMATION_PR_TITLE:
        raise PublicationError("Pull request title does not match the automation title.")
    if pull_request.get("state") != "open" or pull_request.get("merged") is True:
        raise PublicationError("Automation pull request must be open and unmerged.")
    if pull_request.get("draft") is True:
        raise PublicationError("Automation pull request must not be a draft.")

    base = _mapping(pull_request.get("base"), "pull request base")
    head = _mapping(pull_request.get("head"), "pull request head")
    if base.get("ref") != AUTOMATION_BASE_BRANCH:
        raise PublicationError("Pull request base branch is not main.")
    if head.get("ref") != AUTOMATION_HEAD_BRANCH:
        raise PublicationError("Pull request head branch is not the automation branch.")
    if _repository_name(base) != repository or _repository_name(head) != repository:
        raise PublicationError("Pull request head and base must belong to this repository.")
    if head.get("sha") != expected_head_sha:
        raise PublicationError("Pull request head SHA does not match the pushed commit.")
    if base.get("sha") != expected_base_sha:
        raise PublicationError("Main advanced during generation; refusing to merge.")
    if pull_request.get("mergeable") is not True:
        raise PublicationError("Automation pull request is not currently mergeable.")

    try:
        normalized_paths = validate_changed_paths(changed_paths)
    except PipelineValidationError as exc:
        raise PublicationError(str(exc)) from exc
    if not normalized_paths:
        raise PublicationError("Automation pull request has no changed files.")
    changed_file_count = pull_request.get("changed_files")
    if not isinstance(changed_file_count, int) or changed_file_count != len(
        normalized_paths
    ):
        raise PublicationError("Pull request changed-file count could not be verified.")

    commit_list = tuple(commits)
    commit_count = pull_request.get("commits")
    if not isinstance(commit_count, int) or commit_count != len(commit_list):
        raise PublicationError("Pull request commit count could not be verified.")
    if not commit_list:
        raise PublicationError("Automation pull request contains no commits.")
    for commit in commit_list:
        _validate_bot_commit(commit)

    return MergeDecision(
        pr_number=expected_pr_number,
        head_sha=expected_head_sha,
        base_sha=expected_base_sha,
        changed_paths=normalized_paths,
    )


class GitHubApi:
    """Small authenticated client for the narrowly scoped merge script."""

    def __init__(self, token: str, *, api_url: str = "https://api.github.com") -> None:
        if not token:
            raise PublicationError("GITHUB_TOKEN is required for automatic merge.")
        self._token = token
        self._api_url = api_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self._api_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "neek-labs-astro-session-planner-automation",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PublicationError(
                f"GitHub API {method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, OSError, ValueError) as exc:
            raise PublicationError(
                f"GitHub API {method} {path} could not be completed: {exc}"
            ) from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def get_all(self, path: str) -> list[Any]:
        results: list[Any] = []
        page = 1
        while True:
            separator = "&" if "?" in path else "?"
            query = urlencode({"per_page": 100, "page": page})
            payload = self.get(f"{path}{separator}{query}")
            if not isinstance(payload, list):
                raise PublicationError("GitHub API pagination returned a non-list payload.")
            results.extend(payload)
            if len(payload) < 100:
                return results
            page += 1


def _validate_bot_commit(commit: Mapping[str, Any]) -> None:
    author = _mapping(commit.get("author"), "commit author")
    committer = _mapping(commit.get("committer"), "commit committer")
    git_commit = _mapping(commit.get("commit"), "Git commit")
    git_author = _mapping(git_commit.get("author"), "Git commit author")
    git_committer = _mapping(git_commit.get("committer"), "Git commit committer")
    if (
        author.get("login") != GITHUB_ACTIONS_BOT_LOGIN
        or committer.get("login") != GITHUB_ACTIONS_BOT_LOGIN
        or git_author.get("email") != GITHUB_ACTIONS_BOT_EMAIL
        or git_committer.get("email") != GITHUB_ACTIONS_BOT_EMAIL
    ):
        raise PublicationError("Automation branch contains a non-bot commit.")


def _repository_name(branch: Mapping[str, Any]) -> str | None:
    repository = branch.get("repo")
    if not isinstance(repository, Mapping):
        return None
    value = repository.get("full_name")
    return value if isinstance(value, str) else None


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PublicationError(f"GitHub response is missing {label} metadata.")
    return value
