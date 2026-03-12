from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from weave.app import (
    AGENT_SESSION_SUMMARY_PROMPT,
    SUMMARY_PROMPT,
    AgentSessionIndexSummarizer,
    AgentSessionScraper,
    CalendarScraper,
    ConfigError,
    DailyNoteWriter,
    GitHubActivitySyncer,
    GoogleDriveExporter,
    LlmNoteSummarizer,
    WeaveConfig,
    WeaveService,
    resolve_vault_root,
    setup_logging,
)
from weave.layout import VaultLayout


def add_runtime_options(func: Callable[..., Any]) -> Callable[..., Any]:
    decorators = [
        click.argument("vault_root", type=click.Path(path_type=Path), required=False),
        click.option("--verbose", is_flag=True, help="Enable debug logging."),
        click.option("--quiet", is_flag=True, help="Only show errors."),
        click.option("--source", default="@hex-rays.com", show_default=True),
        click.option("--agent-sessions", type=click.Path(path_type=Path), default=None),
        click.option("--github-user", default=None),
        click.option("--github-timezone", default=None),
        click.option("--poll-interval", default=300, show_default=True, type=int),
    ]
    for decorator in reversed(decorators):
        func = decorator(func)
    return func


def resolve_existing_vault_root(vault_root: Path | None) -> Path:
    try:
        resolved = resolve_vault_root(vault_root)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    if not resolved.exists():
        raise click.ClickException(f"vault root does not exist: {resolved}")
    return resolved


def build_service(
    vault_root: Path | None,
    poll_interval: int,
    source: str,
    agent_sessions: Path | None,
    github_user: str | None,
    github_timezone: str | None,
) -> WeaveService:
    resolved_vault_root = resolve_existing_vault_root(vault_root)
    try:
        config = WeaveConfig.from_runtime(
            vault_root=resolved_vault_root,
            poll_interval_seconds=poll_interval,
            calendar_source=source,
            agent_sessions_dir=agent_sessions,
            github_activity_user=github_user,
            github_activity_timezone=github_timezone,
        )
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    return WeaveService(config)


def build_daily_note_writer(vault_root: Path | None) -> DailyNoteWriter:
    resolved_vault_root = resolve_existing_vault_root(vault_root)
    return DailyNoteWriter(
        vault_root=resolved_vault_root,
        summarizer=LlmNoteSummarizer(prompt=SUMMARY_PROMPT),
    )


def resolve_agent_sessions_dir(agent_sessions: Path | None) -> Path:
    if agent_sessions is not None:
        return agent_sessions
    env_value = os.environ.get("WEAVE_AGENT_SESSIONS_DIR")
    if env_value:
        return Path(env_value)
    raise click.ClickException(
        "agent sessions directory required via --agent-sessions or WEAVE_AGENT_SESSIONS_DIR"
    )


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    pass


@main.command()
@add_runtime_options
def monitor(
    vault_root: Path | None,
    verbose: bool,
    quiet: bool,
    source: str,
    agent_sessions: Path | None,
    github_user: str | None,
    github_timezone: str | None,
    poll_interval: int,
) -> None:
    setup_logging(verbose=verbose, quiet=quiet)
    service = build_service(
        vault_root=vault_root,
        poll_interval=poll_interval,
        source=source,
        agent_sessions=agent_sessions,
        github_user=github_user,
        github_timezone=github_timezone,
    )
    service.run_daemon()


@main.command()
@add_runtime_options
def sync(
    vault_root: Path | None,
    verbose: bool,
    quiet: bool,
    source: str,
    agent_sessions: Path | None,
    github_user: str | None,
    github_timezone: str | None,
    poll_interval: int,
) -> None:
    setup_logging(verbose=verbose, quiet=quiet)
    service = build_service(
        vault_root=vault_root,
        poll_interval=poll_interval,
        source=source,
        agent_sessions=agent_sessions,
        github_user=github_user,
        github_timezone=github_timezone,
    )
    count = service.run_single_batch()
    click.echo(f"synced {count} item(s)")


@main.group(name="import")
def import_group() -> None:
    pass


@import_group.command(name="email")
@add_runtime_options
def import_email(
    vault_root: Path | None,
    verbose: bool,
    quiet: bool,
    source: str,
    agent_sessions: Path | None,
    github_user: str | None,
    github_timezone: str | None,
    poll_interval: int,
) -> None:
    setup_logging(verbose=verbose, quiet=quiet)
    service = build_service(
        vault_root=vault_root,
        poll_interval=poll_interval,
        source=source,
        agent_sessions=agent_sessions,
        github_user=github_user,
        github_timezone=github_timezone,
    )
    count = service.run_email_sync()
    click.echo(f"imported {count} email item(s)")


@import_group.command(name="calendar")
@add_runtime_options
@click.option("--days", default=7, show_default=True, type=int)
def import_calendar(
    vault_root: Path | None,
    verbose: bool,
    quiet: bool,
    source: str,
    agent_sessions: Path | None,
    github_user: str | None,
    github_timezone: str | None,
    poll_interval: int,
    days: int,
) -> None:
    del agent_sessions, github_user, github_timezone, poll_interval
    setup_logging(verbose=verbose, quiet=quiet)
    resolved_vault_root = resolve_existing_vault_root(vault_root)
    writer = build_daily_note_writer(resolved_vault_root)
    creds = CalendarScraper.get_google_credentials()
    scraper = CalendarScraper(
        layout=VaultLayout(resolved_vault_root),
        source=source,
        drive_exporter=GoogleDriveExporter(creds),
    )
    results = scraper.scrape_once(days_back=days)
    for event_start, note_path, entry_type in results:
        writer.append_note_entry(
            received=event_start,
            note_path=note_path,
            entry_type=entry_type,
        )
    click.echo(f"imported {len(results)} calendar item(s)")


@import_group.command(name="agent-sessions")
@add_runtime_options
def import_agent_sessions(
    vault_root: Path | None,
    verbose: bool,
    quiet: bool,
    source: str,
    agent_sessions: Path | None,
    github_user: str | None,
    github_timezone: str | None,
    poll_interval: int,
) -> None:
    del source, github_user, github_timezone, poll_interval
    setup_logging(verbose=verbose, quiet=quiet)
    resolved_vault_root = resolve_existing_vault_root(vault_root)
    writer = build_daily_note_writer(resolved_vault_root)
    scraper = AgentSessionScraper(
        sessions_dir=resolve_agent_sessions_dir(agent_sessions),
        layout=VaultLayout(resolved_vault_root),
        summarizer=LlmNoteSummarizer(prompt=AGENT_SESSION_SUMMARY_PROMPT),
        index_summarizer=AgentSessionIndexSummarizer(),
    )

    def handle_result(result: Any) -> None:
        writer.append_note_entry(
            received=result.received,
            note_path=result.note_path,
            entry_type=result.entry_type,
        )

    run = scraper.scrape_once(on_result=handle_result)
    click.echo(run.report.model_dump_json())


@import_group.command(name="github")
@add_runtime_options
def import_github(
    vault_root: Path | None,
    verbose: bool,
    quiet: bool,
    source: str,
    agent_sessions: Path | None,
    github_user: str | None,
    github_timezone: str | None,
    poll_interval: int,
) -> None:
    del source, agent_sessions, poll_interval
    setup_logging(verbose=verbose, quiet=quiet)
    resolved_vault_root = resolve_existing_vault_root(vault_root)
    writer = build_daily_note_writer(resolved_vault_root)
    resolved_github_user = github_user or os.environ.get("WEAVE_GITHUB_USER")
    resolved_github_timezone = (
        github_timezone or os.environ.get("WEAVE_GITHUB_TIMEZONE") or "UTC"
    )
    syncer = GitHubActivitySyncer(
        daily_note_writer=writer,
        timezone_name=resolved_github_timezone,
        username=resolved_github_user,
    )
    count = syncer.run_once()
    click.echo(f"imported GitHub activity for {count} day(s)")


@main.group()
def rebuild() -> None:
    pass


@rebuild.command(name="daily")
@click.argument("vault_root", type=click.Path(path_type=Path), required=False)
@click.option("--verbose", is_flag=True, help="Enable debug logging.")
@click.option("--quiet", is_flag=True, help="Only show errors.")
def rebuild_daily(
    vault_root: Path | None,
    verbose: bool,
    quiet: bool,
) -> None:
    setup_logging(verbose=verbose, quiet=quiet)
    writer = build_daily_note_writer(vault_root)
    count = writer.sync_all_daily_notes()
    click.echo(f"rebuilt {count} daily note(s)")


__all__ = ["main"]
