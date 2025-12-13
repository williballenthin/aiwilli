"""CLI entry point for tw."""

import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

import click
import questionary
from questionary import Style
from rich.console import Console
from rich.logging import RichHandler

from tw import watch as watch_module
from tw.backend import SqliteBackend
from tw.config import ConfigError, get_db_path, get_prefix
from tw.models import AnnotationType, Issue, IssueStatus, IssueType
from tw.render import (
    generate_edit_template,
    parse_edited_content,
    parse_groom_result,
    render_brief,
    render_digest,
    render_groom_content,
    render_onboard,
    render_tree_with_backlog,
    render_view,
)
from tw.service import IssueService
from tw.tui import run_tui

logger = logging.getLogger(__name__)

PROMPT_STYLE = Style([
    ("highlighted", "fg:white bg:blue bold"),
    ("pointer", "fg:cyan bold"),
    ("completion-menu", "bg:#333333 fg:#ffffff"),
    ("completion-menu.completion", "bg:#333333 fg:#ffffff"),
    ("completion-menu.completion.current", "bg:#0066cc fg:#ffffff bold"),
])


def get_service(ctx: click.Context) -> IssueService:
    """Get configured IssueService from context.

    Raises:
        ConfigError: If required configuration is missing.
    """
    if "db_path" not in ctx.obj or "prefix" not in ctx.obj:
        try:
            ctx.obj["db_path"] = get_db_path()
            ctx.obj["prefix"] = get_prefix()
        except ConfigError as e:
            raise click.ClickException(str(e))

    backend = SqliteBackend(ctx.obj["db_path"])
    return IssueService(
        backend=backend,
        prefix=ctx.obj["prefix"],
    )



@dataclass
class CaptureEntry:
    """Parsed entry from capture DSL."""

    issue_type: str
    title: str
    parent_title: str | None
    body: str | None = None


def parse_capture_dsl(content: str) -> list[CaptureEntry]:
    """Parse the indented DSL and return entries.

    Supports multi-line body content indented below the type: title line.
    Body uses --- separator for repeatable/non-repeatable sections.

    Args:
        content: DSL content with format "- type: title"

    Returns:
        List of CaptureEntry tuples with (type, title, parent_title, body)
    """
    import re

    entries: list[CaptureEntry] = []
    parent_stack: dict[int, str] = {}

    lines = content.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip empty lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # Check for entry start: "- type: title"
        match = re.match(r'^(\s*)-\s*(epic|story|task|bug|idea):\s*(.+)$', line)
        if not match:
            i += 1
            continue

        indent_str, issue_type, title = match.groups()
        indent = len(indent_str)

        # Determine parent from indent
        parent_title = None
        if indent > 0:
            # Find closest parent at lower indent
            for check_indent in range(indent - 1, -1, -1):
                if check_indent in parent_stack:
                    parent_title = parent_stack[check_indent]
                    break

        # Collect body lines (more indented than the - line)
        body_lines: list[str] = []
        body_indent = None  # Will be determined from first body line
        i += 1

        while i < len(lines):
            body_line = lines[i]

            # Empty line - include in body if we have content
            if not body_line.strip():
                if body_lines:
                    body_lines.append("")
                i += 1
                continue

            # Comment line in body - skip
            if body_line.strip().startswith("# tw:"):
                i += 1
                continue

            # Check if this is a new entry (starts with -)
            if re.match(r'^\s*-\s*(epic|story|task|bug|idea):', body_line):
                break

            # Check indentation - must be more indented than entry line
            line_indent = len(body_line) - len(body_line.lstrip())
            if line_indent <= indent:
                break

            # Determine body indentation from first body line
            if body_indent is None:
                body_indent = line_indent

            # Strip the body indentation
            if line_indent >= body_indent:
                stripped = body_line[body_indent:]
            else:
                stripped = body_line.strip()
            body_lines.append(stripped)
            i += 1

        # Clean up trailing empty lines
        while body_lines and not body_lines[-1]:
            body_lines.pop()

        body = "\n".join(body_lines) if body_lines else None

        entry = CaptureEntry(
            issue_type=issue_type,
            title=title.strip(),
            parent_title=parent_title,
            body=body,
        )
        entries.append(entry)

        # Track for parent lookup - use the - line indent
        parent_stack[indent] = title.strip()

    return entries


@click.group(invoke_without_command=True)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-error output")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option(
    "--color",
    type=click.Choice(["always", "never", "auto"]),
    default="auto",
    help="Control color output",
)
@click.version_option(version="0.1.0")
@click.pass_context
def main(
    ctx: click.Context,
    verbose: bool,
    quiet: bool,
    json_output: bool,
    color: str,
) -> None:
    """tw - SQLite-backed issue tracker for AI agents."""
    ctx.ensure_object(dict)

    # Create consoles based on color flag
    if color == "always":
        stdout_console = Console(force_terminal=True)
        stderr_console = Console(stderr=True, force_terminal=True)
    elif color == "never":
        stdout_console = Console(no_color=True, force_terminal=False)
        stderr_console = Console(stderr=True, no_color=True, force_terminal=False)
    else:  # auto
        stdout_console = Console()
        stderr_console = Console(stderr=True)

    # Configure logging
    handlers = [RichHandler(console=stderr_console, rich_tracebacks=verbose)]
    if verbose:
        logging.basicConfig(level=logging.DEBUG, handlers=handlers, force=True)
        logging.getLogger("markdown_it").setLevel(logging.INFO)
    elif quiet or json_output:
        logging.basicConfig(level=logging.ERROR, handlers=handlers, force=True)
    else:
        logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)

    ctx.obj["json"] = json_output
    ctx.obj["stdout"] = stdout_console
    ctx.obj["stderr"] = stderr_console

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        click.echo()
        ctx.invoke(tree)


@main.command()
@click.argument("issue_type", type=click.Choice(["epic", "story", "task", "bug", "idea"]))
@click.option("--title", "-t", required=True, help="Issue title")
@click.option("--parent", "-p", default=None, help="Parent issue ID")
@click.option("--body", "-b", default=None, help="Issue body (or - for stdin)")
@click.pass_context
def new(
    ctx: click.Context,
    issue_type: str,
    title: str,
    parent: str | None,
    body: str | None,
) -> None:
    """Create a new issue."""
    try:
        service = get_service(ctx)

        if body == "-":
            body = sys.stdin.read()

        tw_id = service.create_issue(
            issue_type=IssueType(issue_type),
            title=title,
            parent_id=parent,
            body=body,
        )

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id}))
        else:
            console.print(f"Created {issue_type} {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.pass_context
def start(ctx: click.Context, tw_id: str) -> None:
    """Start work on an issue (NEW/STOPPED → IN_PROGRESS)."""
    try:
        service = get_service(ctx)
        service.start_issue(tw_id)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id, "status": "started"}))
        else:
            console.print(f"Started work on {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.option("--message", "-m", default="", help="Completion message")
@click.option("--force", is_flag=True, hidden=True, help="Bypass status check")
@click.option("--recursive", is_flag=True, hidden=True, help="Mark all children as done")
@click.pass_context
def done(ctx: click.Context, tw_id: str, message: str, force: bool, recursive: bool) -> None:
    """Mark an issue as done (IN_PROGRESS → DONE)."""
    try:
        service = get_service(ctx)

        if recursive:
            service.done_issue_recursive(tw_id, force=force)
        else:
            service.done_issue(tw_id, force=force)

        if message:
            service.record_annotation(tw_id, AnnotationType.COMMENT, message)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id, "status": "done"}))
        else:
            console.print(f"Marked {tw_id} as done")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.option("--reason", "-r", required=True, help="Reason for blocking")
@click.pass_context
def blocked(ctx: click.Context, tw_id: str, reason: str) -> None:
    """Mark an issue as blocked (IN_PROGRESS → BLOCKED)."""
    try:
        service = get_service(ctx)
        service.block_issue(tw_id, reason)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id, "status": "blocked"}))
        else:
            console.print(f"Blocked {tw_id}: {reason}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.option("--message", "-m", default="", help="Unblock message")
@click.pass_context
def unblock(ctx: click.Context, tw_id: str, message: str) -> None:
    """Unblock an issue (BLOCKED → IN_PROGRESS)."""
    try:
        service = get_service(ctx)
        service.unblock_issue(tw_id, message)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id, "status": "unblocked"}))
        else:
            console.print(f"Unblocked {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.option("--status", "-s", required=True, help="Current status summary")
@click.option("--completed", "-c", required=True, help="Work completed")
@click.option("--remaining", "-r", required=True, help="Work remaining")
@click.pass_context
def handoff(
    ctx: click.Context,
    tw_id: str,
    status: str,
    completed: str,
    remaining: str,
) -> None:
    """Hand off an issue with structured summary (IN_PROGRESS → STOPPED)."""
    try:
        service = get_service(ctx)
        service.handoff_issue(tw_id, status, completed, remaining)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id, "status": "handed_off"}))
        else:
            console.print(f"Handed off {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.option("--message", "-m", required=True, help="Comment message")
@click.pass_context
def comment(ctx: click.Context, tw_id: str, message: str) -> None:
    """Add a comment annotation to an issue."""
    try:
        service = get_service(ctx)
        service.record_annotation(tw_id, AnnotationType.COMMENT, message)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id, "action": "commented"}))
        else:
            console.print(f"Added comment to {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.pass_context
def delete(ctx: click.Context, tw_id: str) -> None:
    """Delete an issue (only if it has no children)."""
    try:
        service = get_service(ctx)
        service.delete_issue(tw_id)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id, "status": "deleted"}))
        else:
            console.print(f"Deleted {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.argument("record_type", type=click.Choice(["lesson", "deviation", "commit"]))
@click.option("--message", "-m", required=True, help="Annotation message")
@click.pass_context
def record(ctx: click.Context, tw_id: str, record_type: str, message: str) -> None:
    """Record an annotation (lesson, deviation, or commit) on an issue."""
    try:
        service = get_service(ctx)
        ann_type = AnnotationType(record_type)
        service.record_annotation(tw_id, ann_type, message)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(
                json.dumps({"tw_id": tw_id, "annotation_type": record_type})
            )
        else:
            console.print(f"Recorded {record_type} on {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.pass_context
def view(ctx: click.Context, tw_id: str) -> None:
    """View an issue without related context."""
    try:
        service = get_service(ctx)
        result = service.get_issue_with_context(tw_id)
        issue, ancestors, siblings, descendants, referenced, referencing = result

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            output = {
                "tw_id": issue.id,
                "tw_type": issue.type.value,
                "title": issue.title,
                "tw_status": issue.status.value,
                "tw_parent": issue.parent,
                "tw_body": issue.body,
                "tw_refs": issue.refs,
                "created_at": issue.created_at.isoformat(),
                "updated_at": issue.updated_at.isoformat(),
                "annotations": [
                    {
                        "type": ann.type.value,
                        "timestamp": ann.timestamp.isoformat(),
                        "message": ann.message,
                    }
                    for ann in (issue.annotations or [])
                ],
            }
            # Use click.echo for JSON to avoid Rich's word-wrapping
            click.echo(json.dumps(output, indent=2))
        else:
            rendered = render_view(
                issue, ancestors, siblings, descendants, referenced, referencing
            )
            console.print(rendered)

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.pass_context
def brief(ctx: click.Context, tw_id: str) -> None:
    """Output a focused coder briefing for a subagent.

    Provides everything a coder subagent needs in one document:
    task context, sibling lessons, ancestor context, protocol, and workflow.

    Use this when dispatching subagents to implement tasks.
    """
    try:
        service = get_service(ctx)
        result = service.get_issue_with_context(tw_id)
        issue, ancestors, siblings, descendants, referenced, referencing = result
        click.echo(render_brief(
            issue, ancestors, siblings, descendants, referenced, referencing
        ))
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id", required=False, default=None)
@click.option("--title", "-t", default=None, help="New issue title")
@click.option("--body", "-b", default=None, help="New issue body (or - for stdin)")
@click.pass_context
def edit(
    ctx: click.Context, tw_id: str | None, title: str | None, body: str | None
) -> None:
    """Edit an issue's title and/or body.

    If no issue ID is provided, shows an interactive selection of open issues.
    """
    try:
        service = get_service(ctx)

        if tw_id is None:
            issues = service.get_issue_tree()
            if not issues:
                click.echo("No open issues to edit", err=True)
                ctx.exit(1)

            choices = [
                questionary.Choice(
                    title=f"{issue.id}: {issue.title}",
                    value=issue.id,
                )
                for issue in issues
            ]

            selected = questionary.select(
                "Select an issue to edit:",
                choices=choices,
                style=PROMPT_STYLE,
            ).ask()

            if selected is None:
                ctx.exit(0)

            tw_id = selected

        if title is None and body is None:
            issue = service.get_issue(tw_id)

            editor = os.environ.get("EDITOR", "nano")

            template = generate_edit_template(issue.title, issue.body)

            with tempfile.NamedTemporaryFile(
                mode="w+", suffix=".md", delete=False
            ) as tmp:
                tmp.write(template)
                tmp_path = tmp.name

            try:
                subprocess.run([editor, tmp_path], check=True)

                with open(tmp_path) as f:
                    content = f.read()

                new_title, new_body = parse_edited_content(content)
                service.update_issue(tw_id, title=new_title, body=new_body)

            finally:
                os.unlink(tmp_path)

        else:
            if body == "-":
                body = sys.stdin.read()

            service.update_issue(tw_id, title=title, body=body)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            console.print(json.dumps({"tw_id": tw_id}))
        else:
            console.print(f"Updated {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id", required=False, default=None)
@click.pass_context
def tree(ctx: click.Context, tw_id: str | None) -> None:
    """Show tree of all epics, stories, and tasks.

    If tw_id is provided, shows only that issue and its descendants.
    """
    try:
        service = get_service(ctx)
        hierarchy, backlog = service.get_issue_tree_with_backlog(root_id=tw_id)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            def issue_to_dict(issue: Issue) -> dict[str, Any]:
                return {
                    "tw_id": issue.id,
                    "tw_type": issue.type.value,
                    "title": issue.title,
                    "tw_status": issue.status.value,
                    "tw_parent": issue.parent,
                    "tw_body": issue.body,
                    "tw_refs": issue.refs,
                    "created_at": issue.created_at.isoformat(),
                    "updated_at": issue.updated_at.isoformat(),
                    "annotations": [
                        {
                            "type": ann.type.value,
                            "timestamp": ann.timestamp.isoformat(),
                            "message": ann.message,
                        }
                        for ann in (issue.annotations or [])
                    ],
                }

            output = {
                "hierarchy": [issue_to_dict(issue) for issue in hierarchy],
                "backlog": [issue_to_dict(issue) for issue in backlog],
            }
            console.print(json.dumps(output, indent=2))
        else:
            console.print(render_tree_with_backlog(hierarchy, backlog), markup=True)

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("subcommand")
@click.argument("tw_id", required=False, default=None)
@click.option(
    "-n",
    "--interval",
    default=60,
    type=int,
    help="Refresh interval in seconds (default: 60)",
)
@click.pass_context
def watch(ctx: click.Context, subcommand: str, tw_id: str | None, interval: int) -> None:
    """Watch command output with auto-refresh.

    Currently only supports 'tree' subcommand.

    Examples:
        tw watch tree              # Watch full tree
        tw watch tree TW-30        # Watch specific issue
        tw watch tree -n 10        # Custom interval
    """
    if subcommand != "tree":
        click.echo("error: only 'tree' subcommand is supported", err=True)
        ctx.exit(1)

    if interval <= 0:
        click.echo("error: interval must be positive", err=True)
        ctx.exit(1)

    try:
        service = get_service(ctx)
        console: Console = ctx.obj["stdout"]
        watch_module.watch_tree(service, tw_id, interval, console, ctx.obj["db_path"])
    except RuntimeError as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.argument("tw_id")
@click.pass_context
def digest(ctx: click.Context, tw_id: str) -> None:
    """Display parent issue with summary of children."""
    try:
        service = get_service(ctx)
        parent, children = service.get_issue_with_children(tw_id)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            parent_dict = {
                "tw_id": parent.id,
                "tw_type": parent.type.value,
                "title": parent.title,
                "tw_status": parent.status.value,
                "tw_parent": parent.parent,
                "tw_body": parent.body,
                "tw_refs": parent.refs,
                "created_at": parent.created_at.isoformat(),
                "updated_at": parent.updated_at.isoformat(),
                "annotations": [
                    {
                        "type": ann.type.value,
                        "timestamp": ann.timestamp.isoformat(),
                        "message": ann.message,
                    }
                    for ann in (parent.annotations or [])
                ],
            }
            children_list = [
                {
                    "tw_id": child.id,
                    "tw_type": child.type.value,
                    "title": child.title,
                    "tw_status": child.status.value,
                    "tw_parent": child.parent,
                    "tw_body": child.body,
                    "tw_refs": child.refs,
                    "created_at": child.created_at.isoformat(),
                    "updated_at": child.updated_at.isoformat(),
                    "annotations": [
                        {
                            "type": ann.type.value,
                            "timestamp": ann.timestamp.isoformat(),
                            "message": ann.message,
                        }
                        for ann in (child.annotations or [])
                    ],
                }
                for child in children
            ]
            output = {"parent": parent_dict, "children": children_list}
            console.print(json.dumps(output, indent=2))
        else:
            console.print(render_digest(parent, children))

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.pass_context
def onboard(ctx: click.Context) -> None:
    """Display onboarding guide for tw."""
    console: Console = ctx.obj["stdout"]
    console.print(render_onboard())


@main.command()
@click.argument("input_source", required=False, default=None)
@click.pass_context
def capture(ctx: click.Context, input_source: str | None) -> None:
    """Create multiple issues from indented DSL.

    Pass - to read from stdin, or omit to open $EDITOR.
    """
    try:
        service = get_service(ctx)

        if input_source == "-":
            content = sys.stdin.read()
        elif input_source is None:
            editor = os.environ.get("EDITOR", "vi")
            template = """\n\n# Capture issues using indented DSL
# Format: - type: title
# Types: epic, story, task
# Lines starting with # are ignored
#
# - epic: example epic
#   - story: example story
#     - task: example task
"""
            with tempfile.NamedTemporaryFile(
                mode="w+", suffix=".txt", delete=False
            ) as f:
                f.write(template)
                temp_path = f.name

            try:
                subprocess.run([editor, temp_path], check=True)
                with open(temp_path) as f:
                    content = f.read()
            finally:
                os.unlink(temp_path)
        else:
            click.echo("error: invalid argument", err=True)
            ctx.exit(1)
            return

        entries = parse_capture_dsl(content)

        created: list[dict[str, str]] = []
        title_to_id: dict[str, str] = {}

        for entry in entries:
            parent_id = None
            if entry.parent_title:
                parent_id = title_to_id.get(entry.parent_title)

            tw_id = service.create_issue(
                issue_type=IssueType(entry.issue_type),
                title=entry.title,
                parent_id=parent_id,
                body=entry.body,
            )

            title_to_id[entry.title] = tw_id
            created.append({"tw_id": tw_id, "title": entry.title})

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            click.echo(json.dumps({"created": created}))
        else:
            if created:
                for item in created:
                    console.print(f"Created {item['tw_id']}: {item['title']}")
            else:
                console.print("No issues created")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.pass_context
def groom(ctx: click.Context) -> None:
    """Open editor to groom all backlog items."""
    try:
        service = get_service(ctx)
        backlog = service.get_backlog_issues()

        console: Console = ctx.obj["stdout"]

        if not backlog:
            console.print("No backlog items to groom")
            return

        original_ids = [i.id for i in backlog]
        content = render_groom_content(backlog)

        # Open editor
        editor = os.environ.get("EDITOR", "vi")
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.write("\n# Instructions:\n")
            f.write("# - Transform bug/idea to epic/story/task to convert\n")
            f.write("# - Remove entry entirely to dismiss\n")
            f.write("# - Leave unchanged to keep in backlog\n")
            f.write("# - Add new entries without # ID comment\n")
            temp_path = f.name

        try:
            subprocess.run([editor, temp_path], check=True)
            with open(temp_path) as f:
                edited = f.read()
        finally:
            os.unlink(temp_path)

        # Parse result and apply actions
        actions = parse_groom_result(edited, original_ids)

        title_to_id: dict[str, str] = {}
        summary: dict[str, int] = {"resolved": 0, "created": 0, "unchanged": 0}

        for action in actions:
            if action.action == "resolve":
                if action.original_id:
                    service.done_issue(action.original_id)
                    summary["resolved"] += 1
            elif action.action == "create":
                if not action.title or not action.issue_type:
                    continue
                parent_id = title_to_id.get(action.parent_title) if action.parent_title else None
                tw_id = service.create_issue(
                    issue_type=IssueType(action.issue_type),
                    title=action.title,
                    parent_id=parent_id,
                    body=action.body,
                )
                title_to_id[action.title] = tw_id
                summary["created"] += 1
                console.print(f"Created {action.issue_type} {tw_id}: {action.title}")
            elif action.action == "unchanged":
                summary["unchanged"] += 1

        if ctx.obj["json"]:
            click.echo(json.dumps(summary))
        else:
            console.print(
                f"Groomed: {summary['resolved']} resolved, "
                f"{summary['created']} created, {summary['unchanged']} unchanged"
            )

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command()
@click.pass_context
def tui(ctx: click.Context) -> None:
    """Launch the interactive TUI for tw issue tracker."""
    try:
        run_tui()
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


@main.command("claude")
@click.argument("tw_id", required=False, default=None)
@click.option("--opus", is_flag=True, help="Use Claude Opus model")
@click.option("--sonnet", is_flag=True, help="Use Claude Sonnet model")
@click.option("--haiku", is_flag=True, help="Use Claude Haiku model")
@click.pass_context
def claude_cmd(
    ctx: click.Context, tw_id: str | None, opus: bool, sonnet: bool, haiku: bool
) -> None:
    """Launch Claude with an issue brief as the initial prompt.

    If no issue ID is provided, shows an interactive selection of actionable issues.
    """
    try:
        service = get_service(ctx)

        if tw_id is None:
            issues = service.get_issue_tree()
            actionable = [i for i in issues if i.status != IssueStatus.DONE]

            if not actionable:
                click.echo("No actionable issues", err=True)
                ctx.exit(1)

            choices = [f"{issue.id}: {issue.title}" for issue in actionable]

            selected = questionary.autocomplete(
                "Select an issue:",
                choices=choices,
                style=PROMPT_STYLE,
            ).ask()

            if selected is None:
                ctx.exit(0)

            tw_id = selected.split(":")[0]

        model = None
        if sum([opus, sonnet, haiku]) > 1:
            click.echo("error: only one model flag can be specified", err=True)
            ctx.exit(1)
        elif opus:
            model = "opus"
        elif sonnet:
            model = "sonnet"
        elif haiku:
            model = "haiku"
        else:
            model_choice = questionary.select(
                "Select model:",
                choices=[
                    questionary.Choice("Opus", value="opus"),
                    questionary.Choice("Sonnet", value="sonnet"),
                    questionary.Choice("Haiku", value="haiku"),
                ],
                style=PROMPT_STYLE,
            ).ask()

            if model_choice is None:
                ctx.exit(0)

            model = model_choice

        issue, ancestors, siblings, descendants, referenced, referencing = (
            service.get_issue_with_context(tw_id)
        )
        brief_output = render_brief(
            issue, ancestors, siblings, descendants, referenced, referencing
        )
        subprocess.run(["claude", "--dangerously-skip-permissions", "--model", model, brief_output])
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)


if __name__ == "__main__":
    main()
