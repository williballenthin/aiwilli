"""Jinja template rendering for human-readable output."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from tw.models import AnnotationType, Issue

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), trim_blocks=True, lstrip_blocks=True)


def relative_time(dt: datetime) -> str:
    """Convert a datetime to a human-readable relative time string.

    Args:
        dt: The datetime to convert

    Returns:
        A human-readable relative time string like "3 hours ago" or "2 days ago"
    """
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = now - dt
    seconds = delta.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif seconds < 2592000:
        weeks = int(seconds / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    elif seconds < 31536000:
        months = int(seconds / 2592000)
        return f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = int(seconds / 31536000)
        return f"{years} year{'s' if years != 1 else ''} ago"


_env.filters["relative_time"] = relative_time


def status_timestamp(issue: Issue) -> str | None:
    """Get formatted timestamp for status display in templates.

    Returns the relative time of the most relevant status timestamp,
    or None if no timestamp should be displayed.

    Args:
        issue: The issue to get the timestamp for

    Returns:
        Formatted relative time string or None
    """
    ts = get_status_timestamp(issue)
    if ts is None:
        return None
    return relative_time(ts)


_env.filters["status_timestamp"] = status_timestamp


def get_status_timestamp(issue: Issue) -> datetime | None:
    """Get the most relevant timestamp for an issue's status.

    For different statuses, returns:
    - blocked: The timestamp of the BLOCKED annotation
    - in_progress/stopped: The timestamp of the WORK_BEGIN annotation
    - new/done: None (no timestamp to display)

    Args:
        issue: The issue to get the timestamp for

    Returns:
        The most relevant datetime for the status, or None if no relevant timestamp
    """
    if not issue.annotations:
        return None

    if issue.tw_status.value == "blocked":
        for ann in issue.annotations:
            if ann.type == AnnotationType.BLOCKED:
                return ann.timestamp
    elif issue.tw_status.value in ("in_progress", "stopped"):
        for ann in issue.annotations:
            if ann.type == AnnotationType.WORK_BEGIN:
                return ann.timestamp

    return None


def render_issue_tree_line(issue: Issue, depth: int = 0) -> str:
    """Render a single issue as a tree line with status and repeatable body.

    Args:
        issue: The issue to render
        depth: Indentation depth

    Returns:
        Formatted tree line for the issue
    """
    indent = "  " * depth
    ts = status_timestamp(issue)

    if issue.tw_status.value == 'done':
        line = f"{indent}[gray69]{issue.tw_type.value}[/gray69][gray69]:[/gray69] [gray69]{issue.title}[/gray69] [gray69]([/gray69][blue]{issue.tw_id}[/blue][gray69], done)[/gray69]"
    elif issue.tw_status.value == 'in_progress':
        ts_part = f" ({ts})" if ts else ""
        line = f"{indent}[gray69]{issue.tw_type.value}[/gray69][gray69]:[/gray69] [default]{issue.title}[/default] [gray69]([/gray69][blue]{issue.tw_id}[/blue][gray69], [/gray69][yellow]in_progress[/yellow]{ts_part}[gray69])[/gray69]"
    elif issue.tw_status.value in ('blocked', 'stopped'):
        ts_part = f" ({ts})" if ts else ""
        line = f"{indent}[gray69]{issue.tw_type.value}[/gray69][gray69]:[/gray69] [default]{issue.title}[/default] [gray69]([/gray69][blue]{issue.tw_id}[/blue][gray69], [/gray69][red]{issue.tw_status.value}[/red]{ts_part}[gray69])[/gray69]"
    else:
        line = f"{indent}[gray69]{issue.tw_type.value}[/gray69][gray69]:[/gray69] [default]{issue.title}[/default] [gray69]([/gray69][blue]{issue.tw_id}[/blue][gray69])[/gray69]"

    result = [line]

    if issue.tw_body:
        repeatable_body = issue.tw_body.split('---')[0].strip() if '---' in issue.tw_body else issue.tw_body.strip()
        if repeatable_body:
            for body_line in repeatable_body.splitlines():
                result.append(f"[dim]{indent}  {body_line}[/dim]")

    if issue.tw_type.value == 'task' and issue.annotations:
        for ann in issue.annotations:
            if ann.type.value not in ('work-begin', 'work-end'):
                first_line = ann.message.split('\n')[0]
                result.append(f"[dim]{indent}  {ann.type.value}: {relative_time(ann.timestamp)}, {first_line}[/dim]")

    return "\n".join(result)


def render_issue_list_as_tree(issues: list[Issue]) -> str:
    """Render a flat list of issues as tree lines with repeatable bodies.

    Args:
        issues: List of issues to render (flat, not hierarchical)

    Returns:
        Tree-formatted text output
    """
    lines = []
    for issue in issues:
        lines.append(render_issue_tree_line(issue, depth=0))
    return "\n".join(lines)


_env.filters["render_tree_line"] = lambda issue, depth=0: render_issue_tree_line(issue, depth)


def render_view(
    issue: Issue,
    ancestors: list[Issue] | None = None,
    siblings: list[Issue] | None = None,
    descendants: list[Issue] | None = None,
    referenced: list[Issue] | None = None,
    referencing: list[Issue] | None = None,
) -> str:
    """Render a single issue with full context as markdown.

    Args:
        issue: The issue to render
        ancestors: List of ancestor issues (parent to root)
        siblings: List of sibling issues
        descendants: List of descendant issues
        referenced: Issues referenced by this issue
        referencing: Issues that reference this issue

    Returns:
        Markdown formatted issue view with context
    """
    template = _env.get_template("view.md.j2")
    return template.render(
        issue=issue,
        ancestors=ancestors or [],
        siblings=siblings or [],
        descendants=descendants or [],
        referenced=referenced or [],
        referencing=referencing or [],
    )


def render_view_body(issue: Issue) -> str:
    """Render just the issue body as markdown (for TUI markdown widget).

    Args:
        issue: The issue to render

    Returns:
        Markdown formatted issue body with header and annotations
    """
    template = _env.get_template("view_body.md.j2")
    return template.render(issue=issue)


def render_view_links(
    ancestors: list[Issue] | None = None,
    siblings: list[Issue] | None = None,
    descendants: list[Issue] | None = None,
    referenced: list[Issue] | None = None,
    referencing: list[Issue] | None = None,
) -> str:
    """Render linked issues with Rich markup (for TUI static widget).

    Args:
        ancestors: List of ancestor issues
        siblings: List of sibling issues
        descendants: List of descendant issues
        referenced: Issues referenced by this issue
        referencing: Issues that reference this issue

    Returns:
        Rich markup formatted linked issues
    """
    template = _env.get_template("view_links.txt.j2")
    return template.render(
        ancestors=ancestors or [],
        siblings=siblings or [],
        descendants=descendants or [],
        referenced=referenced or [],
        referencing=referencing or [],
    )


def render_tree(issues: list[Issue]) -> str:
    """Render a list of issues as a tree structure.

    Args:
        issues: List of issues to render

    Returns:
        Tree-formatted text output
    """
    issue_map = {issue.tw_id: issue for issue in issues}

    def compute_depth(issue: Issue) -> int:
        """Compute the depth of an issue in the tree."""
        depth = 0
        current = issue
        while current.tw_parent:
            depth += 1
            parent_issue = issue_map.get(current.tw_parent)
            if not parent_issue:
                break
            current = parent_issue
        return depth

    issues_with_depth = [(issue, compute_depth(issue)) for issue in issues]

    template = _env.get_template("tree.txt.j2")
    return template.render(issues_with_depth=issues_with_depth, backlog_with_depth=[])


def render_tree_with_backlog(hierarchy: list[Issue], backlog: list[Issue]) -> str:
    """Render tree with separate backlog section.

    Args:
        hierarchy: List of issues in the hierarchy tree
        backlog: List of backlog issues

    Returns:
        Tree-formatted text output with backlog section
    """
    issue_map = {issue.tw_id: issue for issue in hierarchy}

    def compute_depth(issue: Issue) -> int:
        """Compute the depth of an issue in the tree."""
        depth = 0
        current = issue
        while current.tw_parent:
            depth += 1
            parent_issue = issue_map.get(current.tw_parent)
            if not parent_issue:
                break
            current = parent_issue
        return depth

    hierarchy_with_depth = [(issue, compute_depth(issue)) for issue in hierarchy]
    backlog_with_depth = [(issue, 0) for issue in backlog]

    template = _env.get_template("tree.txt.j2")
    return template.render(
        issues_with_depth=hierarchy_with_depth,
        backlog_with_depth=backlog_with_depth,
    )


def render_digest(parent: Issue, children: list[Issue]) -> str:
    """Render parent issue with summary of children.

    Args:
        parent: The parent issue
        children: List of child issues

    Returns:
        Markdown formatted digest
    """
    template = _env.get_template("digest.md.j2")
    return template.render(parent=parent, children=children)


def render_groom_content(issues: list[Issue]) -> str:
    """Render backlog issues for groom editor.

    Format:
    # TEST-1 (bug)
    - bug: title
        body line 1
        body line 2

    Args:
        issues: List of backlog issues to render

    Returns:
        Formatted content for groom editor
    """
    lines: list[str] = []

    for issue in issues:
        # Comment with ID
        lines.append(f"# {issue.tw_id} ({issue.tw_type.value})")

        # Entry line
        lines.append(f"- {issue.tw_type.value}: {issue.title}")

        # Body lines (indented)
        if issue.tw_body:
            for body_line in issue.tw_body.splitlines():
                lines.append(f"    {body_line}")

        lines.append("")  # Blank line between entries

    return "\n".join(lines)


@dataclass
class GroomAction:
    """Action to take during groom processing."""

    action: str  # "unchanged", "resolve", "create"
    original_id: str | None = None
    issue_type: str | None = None
    title: str | None = None
    body: str | None = None
    parent_title: str | None = None


def parse_groom_result(
    content: str, original_ids: list[str]
) -> list[GroomAction]:
    """Parse groom editor result and determine actions.

    Compares edited content against original IDs to determine:
    - unchanged: ID present with same type
    - resolve: ID removed or transformed
    - create: new entry to create

    Args:
        content: Edited content from groom editor
        original_ids: List of original backlog issue IDs

    Returns:
        List of GroomAction objects describing what to do
    """
    import re
    from tw.cli import parse_capture_dsl

    actions: list[GroomAction] = []
    seen_ids: set[str] = set()

    # Track which ID each entry is associated with
    lines = content.splitlines()
    current_id: str | None = None
    entries_by_id: dict[str | None, list] = {}

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for ID comment: # TEST-1 (bug)
        if line.startswith("#") and "(" in line and ")" in line:
            match = re.match(r'^#\s*([A-Z]+-\d+(?:-\d+)?(?:[a-z]+)?)\s*\(', line)
            if match:
                current_id = match.group(1)
                i += 1
                continue

        # Check for entry start
        if re.match(r'^\s*-\s*(epic|story|task|bug|idea):', line):
            # Parse from this point using capture DSL
            remaining = "\n".join(lines[i:])
            entries = parse_capture_dsl(remaining)
            if entries:
                entry = entries[0]
                if current_id not in entries_by_id:
                    entries_by_id[current_id] = []
                entries_by_id[current_id].append(entry)
                seen_ids.add(current_id) if current_id else None

                # Skip past this entry's lines
                # Find next entry or ID comment
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if next_line.startswith("#") or re.match(r'^\s*-\s*(epic|story|task|bug|idea):', next_line):
                        break
                    i += 1
                current_id = None
                continue

        i += 1
        current_id = None

    # Determine actions
    # 1. IDs not seen -> resolve
    for orig_id in original_ids:
        if orig_id not in seen_ids:
            actions.append(GroomAction(action="resolve", original_id=orig_id))

    # 2. Process entries by ID
    for assoc_id, entries in entries_by_id.items():
        for entry in entries:
            if assoc_id in original_ids:
                # Check if unchanged (same type as backlog)
                if entry.issue_type in ("bug", "idea"):
                    actions.append(GroomAction(
                        action="unchanged",
                        original_id=assoc_id,
                    ))
                else:
                    # Transformed
                    actions.append(GroomAction(action="resolve", original_id=assoc_id))
                    actions.append(GroomAction(
                        action="create",
                        issue_type=entry.issue_type,
                        title=entry.title,
                        body=entry.body,
                        parent_title=entry.parent_title,
                    ))
            else:
                # New entry (no associated ID)
                actions.append(GroomAction(
                    action="create",
                    issue_type=entry.issue_type,
                    title=entry.title,
                    body=entry.body,
                    parent_title=entry.parent_title,
                ))

    return actions


def render_onboard() -> str:
    """Render the onboarding guide for tw.

    Returns:
        Markdown formatted onboarding guide
    """
    template = _env.get_template("onboard.md.j2")
    return template.render()


def generate_edit_template(title: str, body: str | None) -> str:
    """Generate a markdown template for editing an issue.

    The template includes the title, body, and instructional comments.
    If the body contains a separator (---), it's preserved.
    Otherwise, a separator is added to encourage split between summary and details.

    Args:
        title: The current issue title
        body: The current issue body (may be None or contain --- separator)

    Returns:
        Markdown formatted template with title, body, separator, and comments
    """
    current_title = title or "<title>"
    current_body = body or ""

    lines = [current_title]
    lines.append("# tw: Enter the issue title on the first line above")
    lines.append("")

    if "---" in current_body:
        repeatable, details = current_body.split("---", 1)
        lines.append(repeatable.strip())
        lines.append("# tw: Enter a brief summary above the separator")
        lines.append("# tw: This will be shown in context views for related issues")
        lines.append("---")
        lines.append(details.strip())
    else:
        if current_body:
            lines.append(current_body.strip())
        lines.append("# tw: Enter a brief summary above the separator")
        lines.append("# tw: This will be shown in context views for related issues")
        lines.append("---")

    lines.append("# tw: Enter implementation details below")
    lines.append("# tw: Lines starting with '# tw:' will be ignored")

    return "\n".join(lines) + "\n"


def parse_edited_content(content: str) -> tuple[str, str | None]:
    """Parse edited markdown content to extract title and body.

    Lines starting with '# tw:' are treated as comments and ignored.
    The first line becomes the title.
    Remaining lines become the body (or None if empty).

    Args:
        content: Raw markdown content from editor

    Returns:
        Tuple of (title, body) where body may be None if empty

    Raises:
        ValueError: If content is empty or contains only whitespace
    """
    lines = [
        line for line in content.split("\n") if not line.startswith("# tw:")
    ]
    content = "\n".join(lines).strip()

    if not content:
        raise ValueError("Content cannot be empty")

    if "\n" in content:
        new_title = content.split("\n", 1)[0].strip()
        rest = content.split("\n", 1)[1].strip()
        new_body = rest if rest else None
    else:
        new_title = content.strip()
        new_body = None

    return new_title, new_body
