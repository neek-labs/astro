from __future__ import annotations

import copy

import pytest

from planner.publication import (
    AUTOMATION_BASE_BRANCH,
    AUTOMATION_HEAD_BRANCH,
    AUTOMATION_PR_TITLE,
    GITHUB_ACTIONS_BOT_EMAIL,
    GITHUB_ACTIONS_BOT_LOGIN,
    PublicationError,
    validate_automation_pull_request,
)


REPOSITORY = "neek-labs/astro"
PR_NUMBER = 42
HEAD_SHA = "a" * 40
BASE_SHA = "b" * 40


def pull_request() -> dict:
    return {
        "number": PR_NUMBER,
        "title": AUTOMATION_PR_TITLE,
        "state": "open",
        "merged": False,
        "draft": False,
        "mergeable": True,
        "changed_files": 2,
        "commits": 1,
        "base": {
            "ref": AUTOMATION_BASE_BRANCH,
            "sha": BASE_SHA,
            "repo": {"full_name": REPOSITORY},
        },
        "head": {
            "ref": AUTOMATION_HEAD_BRANCH,
            "sha": HEAD_SHA,
            "repo": {"full_name": REPOSITORY},
        },
    }


def bot_commits() -> list[dict]:
    identity = {"login": GITHUB_ACTIONS_BOT_LOGIN}
    git_identity = {"email": GITHUB_ACTIONS_BOT_EMAIL}
    return [
        {
            "author": copy.deepcopy(identity),
            "committer": copy.deepcopy(identity),
            "commit": {
                "author": copy.deepcopy(git_identity),
                "committer": copy.deepcopy(git_identity),
            },
        }
    ]


def changed_paths() -> list[str]:
    return [
        "data/session-planner.json",
        "data/astronomy-target-visibility.json",
    ]


def decide(pr: dict | None = None, *, paths: list[str] | None = None):
    return validate_automation_pull_request(
        pr or pull_request(),
        bot_commits(),
        paths or changed_paths(),
        repository=REPOSITORY,
        expected_pr_number=PR_NUMBER,
        expected_head_sha=HEAD_SHA,
        expected_base_sha=BASE_SHA,
    )


def test_correct_automation_pr_identity_is_accepted() -> None:
    decision = decide()
    assert decision.pr_number == PR_NUMBER
    assert decision.head_sha == HEAD_SHA
    assert decision.base_sha == BASE_SHA


def test_unrelated_pr_is_rejected() -> None:
    pr = pull_request()
    pr["number"] = 99
    with pytest.raises(PublicationError, match="number"):
        decide(pr)


def test_wrong_pr_title_is_rejected() -> None:
    pr = pull_request()
    pr["title"] = "Update dependency"
    with pytest.raises(PublicationError, match="title"):
        decide(pr)


@pytest.mark.parametrize(
    ("side", "value", "message"),
    [
        ("head", "feature/unrelated", "head branch"),
        ("base", "release", "base branch"),
    ],
)
def test_unexpected_head_or_base_branch_is_rejected(
    side: str, value: str, message: str
) -> None:
    pr = pull_request()
    pr[side]["ref"] = value
    with pytest.raises(PublicationError, match=message):
        decide(pr)


def test_non_allowlisted_changed_file_is_rejected() -> None:
    pr = pull_request()
    pr["changed_files"] = 3
    with pytest.raises(PublicationError, match="unexpected paths"):
        decide(pr, paths=[*changed_paths(), "session-planner.js"])


def test_mismatched_head_sha_is_rejected() -> None:
    pr = pull_request()
    pr["head"]["sha"] = "c" * 40
    with pytest.raises(PublicationError, match="head SHA"):
        decide(pr)


def test_advanced_main_is_rejected() -> None:
    pr = pull_request()
    pr["base"]["sha"] = "d" * 40
    with pytest.raises(PublicationError, match="Main advanced"):
        decide(pr)


def test_unmergeable_pr_is_rejected() -> None:
    pr = pull_request()
    pr["mergeable"] = False
    with pytest.raises(PublicationError, match="not currently mergeable"):
        decide(pr)


def test_non_bot_commit_is_rejected() -> None:
    commits = bot_commits()
    commits[0]["author"]["login"] = "octocat"
    with pytest.raises(PublicationError, match="non-bot commit"):
        validate_automation_pull_request(
            pull_request(),
            commits,
            changed_paths(),
            repository=REPOSITORY,
            expected_pr_number=PR_NUMBER,
            expected_head_sha=HEAD_SHA,
            expected_base_sha=BASE_SHA,
        )


def test_successful_merge_decision_after_all_conditions_pass() -> None:
    decision = decide()
    assert decision.changed_paths == (
        "data/astronomy-target-visibility.json",
        "data/session-planner.json",
    )
