from __future__ import annotations

import argparse
import json
import logging
import subprocess
from collections import defaultdict
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.spinner import Spinner
from rich.text import Text

logger = logging.getLogger(__name__)
STDOUT_CONSOLE = Console()
STDERR_CONSOLE = Console(stderr=True)

COMMENT_SNIPPET_LIMIT = 68
COMMIT_SNIPPET_LIMIT = 72


class GitHubActivityError(Exception):
    """Raised when GitHub activity collection fails."""


class GitHubActorModel(BaseModel):
    """Actor metadata returned by the GitHub API."""

    model_config = ConfigDict(extra="ignore")

    login: str


class GitHubRepoModel(BaseModel):
    """Repository metadata returned by the GitHub API."""

    model_config = ConfigDict(extra="ignore")

    name: str


class GitHubEventModel(BaseModel):
    """Raw event envelope returned by the GitHub user events API."""

    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    actor: GitHubActorModel
    repo: GitHubRepoModel
    public: bool
    created_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class ActivityRecord:
    """Normalized event ready for grouping and rendering."""

    event_id: str
    repo: str
    occurred_at: datetime
    url: str | None
    summary: str


class GitHubTimelineClient(Protocol):
    """Client interface for retrieving and expanding GitHub activity."""

    def get_authenticated_login(self) -> str:
        """Return the login for the current authenticated user."""

    def get_user_events(self, username: str, page: int, per_page: int) -> list[dict[str, Any]]:
        """Return a page of user events."""

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        """Return pull request metadata."""

    def compare_commits(self, owner: str, repo: str, base: str, head: str) -> dict[str, Any]:
        """Return compare data for a push range."""


class GhCliGitHubTimelineClient:
    """GitHub timeline client backed by the `gh` CLI."""

    def __init__(self) -> None:
        self._pull_request_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._compare_cache: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def get_authenticated_login(self) -> str:
        data = self._run_json(["gh", "api", "/user"])
        login = data.get("login")
        if not isinstance(login, str) or not login:
            raise GitHubActivityError("failed to determine authenticated GitHub login")
        return login

    def get_user_events(self, username: str, page: int, per_page: int) -> list[dict[str, Any]]:
        path = f"/users/{username}/events?per_page={per_page}&page={page}"
        data = self._run_json(["gh", "api", path])
        if not isinstance(data, list):
            raise GitHubActivityError("GitHub events response was not a list")
        return [item for item in data if isinstance(item, dict)]

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        key = (owner, repo, number)
        if key not in self._pull_request_cache:
            path = f"/repos/{owner}/{repo}/pulls/{number}"
            data = self._run_json(["gh", "api", path])
            if not isinstance(data, dict):
                raise GitHubActivityError(f"pull request response was not an object: {path}")
            self._pull_request_cache[key] = data
        return self._pull_request_cache[key]

    def compare_commits(self, owner: str, repo: str, base: str, head: str) -> dict[str, Any]:
        key = (owner, repo, base, head)
        if key not in self._compare_cache:
            path = f"/repos/{owner}/{repo}/compare/{base}...{head}"
            data = self._run_json(["gh", "api", path])
            if not isinstance(data, dict):
                raise GitHubActivityError(f"compare response was not an object: {path}")
            self._compare_cache[key] = data
        return self._compare_cache[key]

    def _run_json(self, command: list[str]) -> Any:
        logger.debug("running %s", " ".join(command))
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as exc:
            raise GitHubActivityError("gh command not found") from exc
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() or exc.stdout.strip()
            raise GitHubActivityError(stderr or "gh api failed") from exc

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise GitHubActivityError("gh api returned invalid JSON") from exc


@contextmanager
def show_spinner(message: str) -> Generator[None, None, None]:
    """Display a transient spinner on stderr."""
    spinner = Spinner("dots", text=Text(message))
    with Live(
        spinner,
        console=STDERR_CONSOLE,
        transient=True,
        refresh_per_second=20,
    ):
        yield



def setup_logging(verbose: bool, quiet: bool) -> None:
    """Configure logging for the standalone script."""
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    if quiet:
        level = logging.ERROR

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=STDERR_CONSOLE, show_time=False, show_path=False)],
    )



def get_default_timezone_name() -> str:
    """Return the local timezone name when available."""
    local_tz = datetime.now().astimezone().tzinfo
    if isinstance(local_tz, ZoneInfo):
        return local_tz.key
    return "UTC"



def get_timezone(name: str) -> tzinfo:
    """Resolve a timezone name to a tzinfo object.

    Raises:
        GitHubActivityError: If the timezone name is invalid.
    """
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise GitHubActivityError(f"unknown timezone: {name}") from exc



def fetch_user_events(
    client: GitHubTimelineClient,
    username: str,
    pages: int,
    per_page: int,
) -> list[GitHubEventModel]:
    """Fetch and validate recent GitHub events for a user."""
    events: list[GitHubEventModel] = []
    for page in range(1, pages + 1):
        raw_events = client.get_user_events(username=username, page=page, per_page=per_page)
        if not raw_events:
            break
        events.extend(GitHubEventModel.model_validate(raw) for raw in raw_events)
        if len(raw_events) < per_page:
            break
    return events



def collect_activity_records(
    events: Sequence[GitHubEventModel],
    client: GitHubTimelineClient,
    enrich: bool,
) -> list[ActivityRecord]:
    """Normalize raw GitHub events into renderable records."""
    records: list[ActivityRecord] = []
    for event in events:
        records.extend(build_activity_records(event=event, client=client, enrich=enrich))
    return records



def build_activity_records(
    event: GitHubEventModel,
    client: GitHubTimelineClient,
    enrich: bool,
) -> list[ActivityRecord]:
    """Convert one GitHub event into one or more normalized activity records."""
    if event.type == "PushEvent":
        return build_push_records(event=event, client=client, enrich=enrich)
    if event.type == "PullRequestEvent":
        return [build_pull_request_record(event=event, client=client, enrich=enrich)]
    if event.type == "IssueCommentEvent":
        return [build_issue_comment_record(event=event)]
    if event.type == "PullRequestReviewEvent":
        return [build_pull_request_review_record(event=event, client=client, enrich=enrich)]
    if event.type == "PullRequestReviewCommentEvent":
        return [
            build_pull_request_review_comment_record(
                event=event,
                client=client,
                enrich=enrich,
            )
        ]
    if event.type == "CreateEvent":
        return [build_create_record(event=event)]
    if event.type == "WatchEvent":
        return [build_watch_record(event=event)]
    return [
        ActivityRecord(
            event_id=event.id,
            repo=event.repo.name,
            occurred_at=event.created_at,
            url=get_repo_url(event.repo.name),
            summary=event.type,
        )
    ]



def build_push_records(
    event: GitHubEventModel,
    client: GitHubTimelineClient,
    enrich: bool,
) -> list[ActivityRecord]:
    """Render push events, collapsing expanded pushes into commit entries."""
    payload = event.payload
    repo_name = event.repo.name
    repo_url = get_repo_url(repo_name)
    branch = get_branch_name(payload.get("ref"))

    before = payload.get("before")
    head = payload.get("head")
    if enrich and isinstance(before, str) and isinstance(head, str) and before and head:
        owner, repo = split_repo_name(repo_name)
        try:
            compare = client.compare_commits(owner=owner, repo=repo, base=before, head=head)
        except GitHubActivityError as exc:
            logger.warning("compare failed for %s: %s", repo_name, exc)
        else:
            commits = compare.get("commits")
            compare_url = get_str(compare.get("html_url")) or repo_url
            if isinstance(commits, list) and commits:
                return build_commit_records(
                    commits=commits,
                    event=event,
                    branch=branch,
                    compare_url=compare_url,
                )

    url = repo_url
    summary = f"pushed to {branch}"
    if isinstance(head, str) and head:
        url = get_commit_url(repo_name, head)
        summary = f"pushed to {branch} ({head[:7]})"

    return [
        ActivityRecord(
            event_id=event.id,
            repo=repo_name,
            occurred_at=event.created_at,
            url=url,
            summary=summary,
        )
    ]



def build_commit_records(
    commits: Sequence[Any],
    event: GitHubEventModel,
    branch: str,
    compare_url: str,
) -> list[ActivityRecord]:
    """Convert expanded compare commits into top-level activity entries."""
    records: list[ActivityRecord] = []
    for index, commit in enumerate(commits):
        if not isinstance(commit, dict):
            continue
        sha = get_str(commit.get("sha")) or "unknown"
        commit_url = get_str(commit.get("html_url")) or get_commit_url(event.repo.name, sha)
        message = commit.get("commit", {}).get("message", "")
        headline = clean_snippet(get_str(message) or "commit", limit=COMMIT_SNIPPET_LIMIT)
        summary = f"committed {render_link(sha[:7], commit_url)} to {branch}: {headline}"
        records.append(
            ActivityRecord(
                event_id=f"{event.id}:{index:03d}",
                repo=event.repo.name,
                occurred_at=event.created_at,
                url=compare_url,
                summary=summary,
            )
        )
    return records



def build_pull_request_record(
    event: GitHubEventModel,
    client: GitHubTimelineClient,
    enrich: bool,
) -> ActivityRecord:
    """Render a pull request lifecycle event."""
    payload = event.payload
    action = str(payload.get("action", "updated"))
    number = get_event_number(payload.get("number"), payload.get("pull_request"))
    title = None
    url = None

    if enrich and number is not None:
        title, url = get_pull_request_metadata(
            client=client,
            repo_name=event.repo.name,
            number=number,
        )

    if number is not None and url is None:
        url = get_pull_request_url(event.repo.name, number)

    summary = f"{action} pull request"
    if number is not None:
        summary = f"{action} PR #{number}"
    if title:
        summary = f"{summary}: {title}"

    return ActivityRecord(
        event_id=event.id,
        repo=event.repo.name,
        occurred_at=event.created_at,
        url=url,
        summary=summary,
    )



def build_issue_comment_record(event: GitHubEventModel) -> ActivityRecord:
    """Render an issue or PR conversation comment."""
    payload = event.payload
    comment = payload.get("comment", {})
    issue = payload.get("issue", {})
    number = get_number(issue.get("number"))
    issue_url = get_str(issue.get("html_url"))
    comment_url = get_str(comment.get("html_url"))
    body = clean_snippet(
        get_str(comment.get("body")) or get_str(issue.get("title")) or "commented",
        limit=COMMENT_SNIPPET_LIMIT,
    )

    subject = "item"
    if issue_url and "/pull/" in issue_url:
        subject = "PR"
    elif number is not None:
        subject = "issue"

    if number is None:
        summary = f"commented on {subject}: {body}"
    else:
        summary = f"commented on {subject} #{number}: {body}"

    return ActivityRecord(
        event_id=event.id,
        repo=event.repo.name,
        occurred_at=event.created_at,
        url=comment_url,
        summary=summary,
    )



def build_pull_request_review_record(
    event: GitHubEventModel,
    client: GitHubTimelineClient,
    enrich: bool,
) -> ActivityRecord:
    """Render a pull request review submission event."""
    payload = event.payload
    review = payload.get("review", {})
    number = get_event_number(payload.get("number"), payload.get("pull_request"))
    title = None
    if enrich and number is not None:
        title, _ = get_pull_request_metadata(
            client=client,
            repo_name=event.repo.name,
            number=number,
        )

    state = (get_str(review.get("state")) or str(payload.get("action", "reviewed"))).lower()
    body = clean_snippet(
        get_str(review.get("body")) or title or "review",
        limit=COMMENT_SNIPPET_LIMIT,
    )

    summary = f"submitted {state} review"
    if number is not None:
        summary = f"submitted {state} review on PR #{number}: {body}"
    else:
        summary = f"submitted {state} review: {body}"

    return ActivityRecord(
        event_id=event.id,
        repo=event.repo.name,
        occurred_at=event.created_at,
        url=get_str(review.get("html_url")),
        summary=summary,
    )



def build_pull_request_review_comment_record(
    event: GitHubEventModel,
    client: GitHubTimelineClient,
    enrich: bool,
) -> ActivityRecord:
    """Render an inline pull request review comment."""
    payload = event.payload
    comment = payload.get("comment", {})
    number = get_event_number(payload.get("number"), payload.get("pull_request"))
    if enrich and number is not None:
        get_pull_request_metadata(
            client=client,
            repo_name=event.repo.name,
            number=number,
        )

    body = clean_snippet(
        get_str(comment.get("body")) or "review comment",
        limit=COMMENT_SNIPPET_LIMIT,
    )
    path = get_str(comment.get("path"))
    subject = "left review comment on pull request"
    if number is not None:
        subject = f"left review comment on PR #{number}"
    if path:
        summary = f"{subject} in {path}: {body}"
    else:
        summary = f"{subject}: {body}"

    return ActivityRecord(
        event_id=event.id,
        repo=event.repo.name,
        occurred_at=event.created_at,
        url=get_str(comment.get("html_url")),
        summary=summary,
    )



def build_create_record(event: GitHubEventModel) -> ActivityRecord:
    """Render a branch or tag creation event."""
    payload = event.payload
    ref_type = get_str(payload.get("ref_type")) or "ref"
    ref = get_str(payload.get("ref")) or "unknown"
    return ActivityRecord(
        event_id=event.id,
        repo=event.repo.name,
        occurred_at=event.created_at,
        url=get_ref_url(event.repo.name, ref_type, ref),
        summary=f"created {ref_type} {ref}",
    )



def build_watch_record(event: GitHubEventModel) -> ActivityRecord:
    """Render a repository star event."""
    repo_url = get_repo_url(event.repo.name)
    summary = f"starred the repository {render_link(event.repo.name, repo_url)}"
    return ActivityRecord(
        event_id=event.id,
        repo=event.repo.name,
        occurred_at=event.created_at,
        url=repo_url,
        summary=summary,
    )



def get_pull_request_metadata(
    client: GitHubTimelineClient,
    repo_name: str,
    number: int,
) -> tuple[str | None, str | None]:
    """Fetch pull request title and URL.

    Raises:
        GitHubActivityError: If the repository name is malformed.
    """
    owner, repo = split_repo_name(repo_name)
    try:
        data = client.get_pull_request(owner=owner, repo=repo, number=number)
    except GitHubActivityError as exc:
        logger.warning("pull request lookup failed for %s#%s: %s", repo_name, number, exc)
        return None, None
    return get_str(data.get("title")), get_str(data.get("html_url"))



def split_repo_name(name: str) -> tuple[str, str]:
    """Split an `owner/repo` string.

    Raises:
        GitHubActivityError: If the repository name is malformed.
    """
    owner, sep, repo = name.partition("/")
    if not sep or not owner or not repo:
        raise GitHubActivityError(f"invalid repository name: {name}")
    return owner, repo



def get_branch_name(ref: Any) -> str:
    """Extract a human-friendly branch name from a Git ref."""
    text = get_str(ref) or "unknown"
    prefix = "refs/heads/"
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text



def get_event_number(number: Any, pull_request: Any) -> int | None:
    """Extract a pull request or issue number from an event payload."""
    direct = get_number(number)
    if direct is not None:
        return direct
    if isinstance(pull_request, dict):
        return get_number(pull_request.get("number"))
    return None



def get_number(value: Any) -> int | None:
    """Return an integer when the input is an int."""
    return value if isinstance(value, int) else None



def get_str(value: Any) -> str | None:
    """Return a string when the input is a non-empty string."""
    if isinstance(value, str) and value:
        return value
    return None



def clean_snippet(text: str, limit: int) -> str:
    """Collapse whitespace, strip leading quote markers, and truncate text."""
    collapsed = " ".join(text.split())
    collapsed = collapsed.lstrip("> ")
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 1].rstrip()}…"



def get_repo_url(repo_name: str) -> str:
    """Return the GitHub HTML URL for a repository."""
    return f"https://github.com/{repo_name}"



def get_pull_request_url(repo_name: str, number: int) -> str:
    """Return the GitHub HTML URL for a pull request."""
    return f"{get_repo_url(repo_name)}/pull/{number}"



def get_commit_url(repo_name: str, sha: str) -> str:
    """Return the GitHub HTML URL for a commit."""
    return f"{get_repo_url(repo_name)}/commit/{sha}"



def get_ref_url(repo_name: str, ref_type: str, ref: str) -> str:
    """Return the best HTML URL for a created ref."""
    repo_url = get_repo_url(repo_name)
    if ref_type == "branch":
        return f"{repo_url}/tree/{ref}"
    if ref_type == "tag":
        return f"{repo_url}/releases/tag/{ref}"
    return repo_url



def render_link(text: str, url: str | None) -> str:
    """Render a markdown link when a URL is available."""
    if not url:
        return text
    return f"[{text}]({url})"



def render_activity_report(
    records: Sequence[ActivityRecord],
    username: str,
    timezone: tzinfo,
    fetched_at: datetime | None = None,
    source_event_count: int | None = None,
) -> str:
    """Render activity records as a grouped markdown report."""
    generated_at = fetched_at or datetime.now(tz=UTC)
    grouped: dict[str, dict[str, list[ActivityRecord]]] = defaultdict(lambda: defaultdict(list))

    for record in records:
        local_dt = record.occurred_at.astimezone(timezone)
        date_key = local_dt.strftime("%Y-%m-%d")
        grouped[date_key][record.repo].append(record)

    lines: list[str] = [
        f"# GitHub activity for {username}",
        "",
        f"Generated: {generated_at.astimezone(timezone).isoformat()}",
        f"Timezone: {get_timezone_label(timezone)}",
    ]
    if source_event_count is not None:
        lines.append(f"Source events: {source_event_count}")
    lines.append(f"Rendered items: {len(records)}")

    for date_key in sorted(grouped.keys(), reverse=True):
        lines.append("")
        lines.append(f"## {date_key}")
        section = render_activity_section(grouped[date_key], timezone)
        if section:
            lines.append("")
            lines.append(section.rstrip())

    return "\n".join(lines) + "\n"



def render_activity_section(
    grouped_records: dict[str, list[ActivityRecord]] | None,
    timezone: tzinfo,
) -> str:
    """Render one day's repository-grouped activity section."""
    if not grouped_records:
        return ""

    lines: list[str] = []
    for repo_name in sorted(grouped_records.keys()):
        repo_url = get_repo_url(repo_name)
        lines.append(f"### {render_link(repo_name, repo_url)}")
        events = sorted(
            grouped_records[repo_name],
            key=lambda record: (record.occurred_at.astimezone(timezone), record.event_id),
        )
        for record in events:
            local_dt = record.occurred_at.astimezone(timezone)
            time_link = render_link(local_dt.strftime("%H:%M:%S"), record.url)
            lines.append(f"- {time_link} {record.summary}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"



def get_records_for_local_day(
    records: Sequence[ActivityRecord],
    day: date,
    timezone: tzinfo,
) -> list[ActivityRecord]:
    """Return records whose local timestamp falls on the requested day."""
    return [record for record in records if record.occurred_at.astimezone(timezone).date() == day]



def get_timezone_label(timezone: tzinfo) -> str:
    """Return a readable timezone label."""
    if isinstance(timezone, ZoneInfo):
        return timezone.key
    return str(timezone)



def output_report(console: Console, report: str, output_path: Path | None) -> None:
    """Write the rendered report to stdout or a file."""
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report)
        return
    console.file.write(report)



def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the standalone renderer."""
    parser = argparse.ArgumentParser(
        description="Render recent GitHub activity from the user events feed"
    )
    parser.add_argument(
        "--user",
        help="GitHub username to query (defaults to the authenticated user)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of events pages to fetch (max practical value: 3)",
    )
    parser.add_argument(
        "--per-page",
        type=int,
        default=100,
        help="Number of events per page (max: 100)",
    )
    parser.add_argument(
        "--timezone",
        default=get_default_timezone_name(),
        help="IANA timezone for day grouping and displayed timestamps",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip follow-up pull request and compare lookups",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the rendered report to a file instead of stdout",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--quiet", action="store_true", help="Only show errors on stderr")
    return parser.parse_args(argv)



def main(argv: Sequence[str] | None = None) -> int:
    """Run the standalone GitHub activity renderer.

    Raises:
        GitHubActivityError: If fetching or rendering fails.
    """
    args = parse_args(argv)
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    if args.pages < 1:
        raise GitHubActivityError("--pages must be at least 1")
    if not 1 <= args.per_page <= 100:
        raise GitHubActivityError("--per-page must be between 1 and 100")

    timezone = get_timezone(args.timezone)
    client = GhCliGitHubTimelineClient()

    username = args.user
    if username is None:
        with show_spinner("Resolving authenticated GitHub user"):
            username = client.get_authenticated_login()

    with show_spinner(f"Fetching GitHub events for {username}"):
        events = fetch_user_events(
            client=client,
            username=username,
            pages=args.pages,
            per_page=args.per_page,
        )

    with show_spinner("Rendering activity report"):
        records = collect_activity_records(
            events=events,
            client=client,
            enrich=not args.no_enrich,
        )
        report = render_activity_report(
            records=records,
            username=username,
            timezone=timezone,
            source_event_count=len(events),
        )

    output_report(console=STDOUT_CONSOLE, report=report, output_path=args.output)
    return 0
