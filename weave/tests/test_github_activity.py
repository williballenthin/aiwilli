from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from weave.github_activity import (
    ActivityRecord,
    GitHubEventModel,
    GitHubTimelineClient,
    collect_activity_records,
    compact_legacy_activity_section,
    render_activity_report,
    render_compact_activity_section,
)


class StaticGitHubTimelineClient:
    def __init__(
        self,
        pull_requests: dict[tuple[str, str, int], dict[str, Any]] | None = None,
        compares: dict[tuple[str, str, str, str], dict[str, Any]] | None = None,
    ) -> None:
        self.pull_requests = pull_requests or {}
        self.compares = compares or {}

    def get_authenticated_login(self) -> str:
        return "tester"

    def get_user_events(self, username: str, page: int, per_page: int) -> list[dict[str, Any]]:
        raise AssertionError("not used in unit tests")

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self.pull_requests[(owner, repo, number)]

    def compare_commits(self, owner: str, repo: str, base: str, head: str) -> dict[str, Any]:
        return self.compares[(owner, repo, base, head)]


def build_event(
    *,
    event_id: str,
    event_type: str,
    repo: str,
    created_at: str,
    payload: dict[str, Any],
) -> GitHubEventModel:
    return GitHubEventModel.model_validate(
        {
            "id": event_id,
            "type": event_type,
            "actor": {"login": "tester"},
            "repo": {"name": repo},
            "public": True,
            "created_at": created_at,
            "payload": payload,
        }
    )


def test_render_activity_report_formats_supported_events() -> None:
    events = [
        build_event(
            event_id="1",
            event_type="CreateEvent",
            repo="acme/app",
            created_at="2026-03-11T08:30:00Z",
            payload={
                "ref_type": "branch",
                "ref": "feature/demo",
                "full_ref": "refs/heads/feature/demo",
            },
        ),
        build_event(
            event_id="2",
            event_type="PushEvent",
            repo="acme/app",
            created_at="2026-03-11T09:00:00Z",
            payload={
                "before": "aaaa1111",
                "head": "bbbb2222",
                "ref": "refs/heads/main",
            },
        ),
        build_event(
            event_id="3",
            event_type="PullRequestEvent",
            repo="acme/app",
            created_at="2026-03-11T10:00:00Z",
            payload={
                "action": "opened",
                "number": 42,
                "pull_request": {
                    "number": 42,
                    "url": "https://api.github.com/repos/acme/app/pulls/42",
                    "head": {"ref": "feature/demo", "sha": "bbbb2222"},
                    "base": {"ref": "main", "sha": "aaaa1111"},
                },
            },
        ),
        build_event(
            event_id="4",
            event_type="IssueCommentEvent",
            repo="acme/app",
            created_at="2026-03-11T11:00:00Z",
            payload={
                "action": "created",
                "comment": {
                    "html_url": "https://github.com/acme/app/issues/9#issuecomment-1",
                    "body": "I think this needs one more test case.",
                },
                "issue": {
                    "number": 9,
                    "title": "Parser crashes on empty input",
                    "html_url": "https://github.com/acme/app/issues/9",
                },
            },
        ),
        build_event(
            event_id="5",
            event_type="PullRequestReviewEvent",
            repo="acme/app",
            created_at="2026-03-11T12:00:00Z",
            payload={
                "action": "created",
                "pull_request": {"number": 42},
                "review": {
                    "state": "approved",
                    "body": "looks good to me",
                    "html_url": "https://github.com/acme/app/pull/42#pullrequestreview-7",
                },
            },
        ),
        build_event(
            event_id="6",
            event_type="PullRequestReviewCommentEvent",
            repo="acme/app",
            created_at="2026-03-11T12:30:00Z",
            payload={
                "action": "created",
                "pull_request": {"number": 42},
                "comment": {
                    "html_url": "https://github.com/acme/app/pull/42#discussion_r1",
                    "body": "can we extract this into a helper?",
                    "path": "src/app.py",
                },
            },
        ),
        build_event(
            event_id="7",
            event_type="WatchEvent",
            repo="acme/lib",
            created_at="2026-03-11T13:30:00Z",
            payload={"action": "started"},
        ),
    ]
    client = StaticGitHubTimelineClient(
        pull_requests={
            ("acme", "app", 42): {
                "title": "Add activity renderer",
                "html_url": "https://github.com/acme/app/pull/42",
            },
        },
        compares={
            ("acme", "app", "aaaa1111", "bbbb2222"): {
                "html_url": "https://github.com/acme/app/compare/aaaa1111...bbbb2222",
                "commits": [
                    {
                        "sha": "abc12345",
                        "html_url": "https://github.com/acme/app/commit/abc12345",
                        "commit": {"message": "Fix parser crash\n\nExtra detail"},
                    },
                    {
                        "sha": "def67890",
                        "html_url": "https://github.com/acme/app/commit/def67890",
                        "commit": {"message": "Add regression test"},
                    },
                ],
            },
        },
    )

    records = collect_activity_records(events=events, client=client, enrich=True)
    report = render_activity_report(
        records=records,
        username="tester",
        timezone=ZoneInfo("UTC"),
        fetched_at=datetime(2026, 3, 11, 14, 0, tzinfo=UTC),
        source_event_count=len(events),
    )

    assert "# GitHub activity for tester" in report
    assert "Source events: 7" in report
    assert "Rendered items: 8" in report
    assert "## 2026-03-11" in report
    assert "### [acme/app](https://github.com/acme/app)" in report
    assert "#### " not in report
    assert (
        "- [08:30:00](https://github.com/acme/app/tree/feature/demo) "
        "created branch feature/demo" in report
    )
    assert (
        "- [09:00:00](https://github.com/acme/app/compare/aaaa1111...bbbb2222) "
        "committed [abc1234](https://github.com/acme/app/commit/abc12345) to main: "
        "Fix parser crash" in report
    )
    assert (
        "- [09:00:00](https://github.com/acme/app/compare/aaaa1111...bbbb2222) "
        "committed [def6789](https://github.com/acme/app/commit/def67890) to main: "
        "Add regression test" in report
    )
    assert (
        "- [10:00:00](https://github.com/acme/app/pull/42) opened PR #42: Add activity renderer"
        in report
    )
    assert (
        "- [11:00:00](https://github.com/acme/app/issues/9#issuecomment-1) "
        "commented on issue #9: I think this needs one more test case."
        in report
    )
    assert (
        "- [12:00:00](https://github.com/acme/app/pull/42#pullrequestreview-7) "
        "submitted approved review on PR #42: looks good to me"
        in report
    )
    assert (
        "- [12:30:00](https://github.com/acme/app/pull/42#discussion_r1) "
        "left review comment on PR #42 in src/app.py: can we extract this into a helper?"
        in report
    )
    assert "### [acme/lib](https://github.com/acme/lib)" in report
    assert (
        "- [13:30:00](https://github.com/acme/lib) starred the repository "
        "[acme/lib](https://github.com/acme/lib)"
        in report
    )


def test_render_activity_report_formats_issues_events() -> None:
    events = [
        build_event(
            event_id="1",
            event_type="IssuesEvent",
            repo="acme/app",
            created_at="2026-03-11T15:00:00Z",
            payload={
                "action": "opened",
                "issue": {
                    "number": 17,
                    "title": "Document IssuesEvent rendering",
                    "html_url": "https://github.com/acme/app/issues/17",
                },
            },
        ),
        build_event(
            event_id="2",
            event_type="IssuesEvent",
            repo="acme/app",
            created_at="2026-03-11T16:00:00Z",
            payload={
                "action": "labeled",
                "label": {"name": "bug"},
                "issue": {
                    "number": 17,
                    "title": "Document IssuesEvent rendering",
                    "html_url": "https://github.com/acme/app/issues/17",
                },
            },
        ),
    ]

    records = collect_activity_records(
        events=events,
        client=StaticGitHubTimelineClient(),
        enrich=True,
    )
    report = render_activity_report(
        records=records,
        username="tester",
        timezone=ZoneInfo("UTC"),
        fetched_at=datetime(2026, 3, 11, 17, 0, tzinfo=UTC),
        source_event_count=len(events),
    )

    assert "Rendered items: 2" in report
    assert (
        "- [15:00:00](https://github.com/acme/app/issues/17) "
        "opened issue #17: Document IssuesEvent rendering" in report
    )
    assert (
        "- [16:00:00](https://github.com/acme/app/issues/17) "
        "labeled issue #17 (bug): Document IssuesEvent rendering" in report
    )



def test_render_activity_report_uses_timezone_for_local_day() -> None:
    records = [
        ActivityRecord(
            event_id="1",
            repo="acme/app",
            occurred_at=datetime(2026, 3, 11, 1, 15, tzinfo=UTC),
            url="https://github.com/acme/app/compare/aaaa1111...bbbb2222",
            summary=(
                "committed [abc1234](https://github.com/acme/app/commit/abc12345) "
                "to main: Fix parser crash"
            ),
        )
    ]

    report = render_activity_report(
        records=records,
        username="tester",
        timezone=ZoneInfo("America/New_York"),
        fetched_at=datetime(2026, 3, 11, 2, 0, tzinfo=UTC),
        source_event_count=1,
    )

    assert "## 2026-03-10" in report
    assert (
        "- [21:15:00](https://github.com/acme/app/compare/aaaa1111...bbbb2222) "
        "committed [abc1234](https://github.com/acme/app/commit/abc12345) "
        "to main: Fix parser crash" in report
    )


def test_render_compact_activity_section_summarizes_repo_activity() -> None:
    events = [
        build_event(
            event_id="1",
            event_type="PushEvent",
            repo="acme/app",
            created_at="2026-03-11T09:00:00Z",
            payload={
                "before": "aaaa1111",
                "head": "bbbb2222",
                "ref": "refs/heads/main",
            },
        ),
        build_event(
            event_id="2",
            event_type="PullRequestEvent",
            repo="acme/app",
            created_at="2026-03-11T10:00:00Z",
            payload={
                "action": "opened",
                "number": 42,
                "pull_request": {
                    "number": 42,
                    "url": "https://api.github.com/repos/acme/app/pulls/42",
                    "head": {"ref": "feature/demo", "sha": "bbbb2222"},
                    "base": {"ref": "main", "sha": "aaaa1111"},
                },
            },
        ),
        build_event(
            event_id="3",
            event_type="IssueCommentEvent",
            repo="acme/app",
            created_at="2026-03-11T11:00:00Z",
            payload={
                "action": "created",
                "comment": {
                    "html_url": "https://github.com/acme/app/issues/9#issuecomment-1",
                    "body": "I think this needs one more test case.",
                },
                "issue": {
                    "number": 9,
                    "title": "Parser crashes on empty input",
                    "html_url": "https://github.com/acme/app/issues/9",
                },
            },
        ),
    ]
    client = StaticGitHubTimelineClient(
        pull_requests={
            ("acme", "app", 42): {
                "title": "Add activity renderer",
                "html_url": "https://github.com/acme/app/pull/42",
            },
        },
        compares={
            ("acme", "app", "aaaa1111", "bbbb2222"): {
                "html_url": "https://github.com/acme/app/compare/aaaa1111...bbbb2222",
                "commits": [
                    {
                        "sha": "abc12345",
                        "html_url": "https://github.com/acme/app/commit/abc12345",
                        "commit": {"message": "Fix parser crash"},
                    },
                    {
                        "sha": "def67890",
                        "html_url": "https://github.com/acme/app/commit/def67890",
                        "commit": {"message": "Add regression test"},
                    },
                ],
            },
        },
    )

    records = collect_activity_records(events=events, client=client, enrich=True)
    grouped = {"acme/app": records}
    section = render_compact_activity_section(grouped)

    assert section == (
        "- [acme/app](https://github.com/acme/app) — "
        "2 commits ([abc1](https://github.com/acme/app/commit/abc12345), "
        "[def6](https://github.com/acme/app/commit/def67890)), "
        "1 PR ([#42](https://github.com/acme/app/pull/42)), "
        "1 comment ([#9](https://github.com/acme/app/issues/9#issuecomment-1))"
    )


def test_compact_legacy_activity_section_rewrites_detailed_markdown() -> None:
    legacy_body = "\n".join(
        (
            "### [acme/app](https://github.com/acme/app)",
            "- [09:00:00](https://github.com/acme/app/compare/aaaa...bbbb) committed "
            "[abc1234](https://github.com/acme/app/commit/abc12345) to main: "
            "Fix parser crash",
            "- [10:00:00](https://github.com/acme/app/pull/42) opened PR #42: "
            "Add activity renderer",
            "- [11:00:00](https://github.com/acme/app/issues/9#issuecomment-1) "
            "commented on issue #9: I think this needs one more test case.",
        )
    )

    assert compact_legacy_activity_section(legacy_body) == (
        "- [acme/app](https://github.com/acme/app) — "
        "1 commit ([abc1](https://github.com/acme/app/commit/abc12345)), "
        "1 PR ([#42](https://github.com/acme/app/pull/42)), "
        "1 comment ([#9](https://github.com/acme/app/issues/9#issuecomment-1))"
    )


def test_static_client_satisfies_protocol() -> None:
    client: GitHubTimelineClient = StaticGitHubTimelineClient()
    assert client.get_authenticated_login() == "tester"
