"""Jinja template rendering for human-readable output."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from tw.models import Annotation, AnnotationType, Issue

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), trim_blocks=True, lstrip_blocks=True)


def relative_time(dt: datetime) -> str:
    """Convert a datetime to a human-readable relative time string.

    Args:
        dt: The datetime to convert

    Returns:
        A human-readable relative time string like "3 hours ago" or "2 days ago"
    """
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

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

    if issue.status.value == "blocked":
        for ann in issue.annotations:
            if ann.type == AnnotationType.BLOCKED:
                return ann.timestamp
    elif issue.status.value in ("in_progress", "stopped"):
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

    if issue.status.value == 'done':
        line = (
            f"{indent}[gray69]{issue.type.value}[/gray69][gray69]:[/gray69] "
            f"[gray69]{issue.title}[/gray69] [gray69]([/gray69]"
            f"[blue]{issue.id}[/blue][gray69], done)[/gray69]"
        )
    elif issue.status.value == 'in_progress':
        ts_part = f" ({ts})" if ts else ""
        line = (
            f"{indent}[gray69]{issue.type.value}[/gray69][gray69]:[/gray69] "
            f"[default]{issue.title}[/default] [gray69]([/gray69]"
            f"[blue]{issue.id}[/blue][gray69], [/gray69]"
            f"[yellow]in_progress[/yellow]{ts_part}[gray69])[/gray69]"
        )
    elif issue.status.value in ('blocked', 'stopped'):
        ts_part = f" ({ts})" if ts else ""
        line = (
            f"{indent}[gray69]{issue.type.value}[/gray69][gray69]:[/gray69] "
            f"[default]{issue.title}[/default] [gray69]([/gray69]"
            f"[blue]{issue.id}[/blue][gray69], [/gray69]"
            f"[red]{issue.status.value}[/red]{ts_part}[gray69])[/gray69]"
        )
    else:
        line = (
            f"{indent}[gray69]{issue.type.value}[/gray69][gray69]:[/gray69] "
            f"[default]{issue.title}[/default] [gray69]([/gray69]"
            f"[blue]{issue.id}[/blue][gray69])[/gray69]"
        )

    result = [line]

    if issue.body:
        if '---' in issue.body:
            repeatable_body = issue.body.split('---')[0].strip()
        else:
            repeatable_body = issue.body.strip()
        if repeatable_body:
            for body_line in repeatable_body.splitlines():
                result.append(f"[dim]{indent}  {body_line}[/dim]")

    if issue.type.value == 'task' and issue.annotations:
        for ann in issue.annotations:
            if ann.type.value not in ('work-begin', 'work-end'):
                first_line = ann.message.split('\n')[0]
                ann_info = f"{ann.type.value}: {relative_time(ann.timestamp)}, {first_line}"
                result.append(f"[dim]{indent}  {ann_info}[/dim]")

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


def _format_status(status: str) -> tuple[str, str]:
    """Return display name and color for a status.

    Args:
        status: The raw status value

    Returns:
        Tuple of (display_name, color)
    """
    if status == "in_progress":
        return ("open", "green")
    elif status == "done":
        return ("done", "gray69")
    elif status == "blocked":
        return ("blocked", "red")
    elif status == "stopped":
        return ("stopped", "red")
    else:
        return (status, "default")


def _render_issue_link_short(issue: Issue, prefix: str) -> str:
    """Render a short issue link line for the compact view.

    Format: prefix:  status | type | title (ID)

    Args:
        issue: The issue to render
        prefix: The relationship prefix (parent, child, sibling, refs)

    Returns:
        Rich markup formatted line
    """
    display_status, color = _format_status(issue.status.value)
    ts = status_timestamp(issue)
    ts_part = f", {ts}" if ts else ""

    return (
        f"[gray69]{prefix}:[/gray69]  [{color}]{display_status}[/{color}] "
        f"[gray69]|[/gray69] [gray69]{issue.type.value}[/gray69] [gray69]|[/gray69] "
        f"[default]{issue.title}[/default] [gray69]([/gray69]"
        f"[blue]{issue.id}[/blue]{ts_part}[gray69])[/gray69]"
    )


def _render_annotation_short(ann: Annotation) -> str:
    """Render a short annotation line (first line only).

    Args:
        ann: The annotation to render

    Returns:
        Rich markup formatted line
    """
    first_line = ann.message.split('\n')[0].strip()
    return f"[gray69]{ann.type.value}:[/gray69] [default]{first_line}[/default]"


def render_view(
    issue: Issue,
    ancestors: list[Issue] | None = None,
    siblings: list[Issue] | None = None,
    descendants: list[Issue] | None = None,
    referenced: list[Issue] | None = None,
    referencing: list[Issue] | None = None,
) -> str:
    """Render a single issue with short links but no full context using Rich markup.

    Args:
        issue: The issue to render
        ancestors: List of ancestor issues (parent to root) - only short links shown
        siblings: List of sibling issues - only short links shown
        descendants: List of descendant issues - only short links shown
        referenced: Issues referenced by this issue - only short links shown
        referencing: Issues that reference this issue - only short links shown

    Returns:
        Rich markup formatted issue view with short links to related issues
    """
    ancestors = ancestors or []
    siblings = siblings or []
    descendants = descendants or []
    referenced = referenced or []
    referencing = referencing or []

    lines: list[str] = []

    # Title (yellow)
    lines.append(f"[yellow]{issue.title}[/yellow]")

    # Properties line (grey, but color status)
    display_status, status_color = _format_status(issue.status.value)
    ts = status_timestamp(issue)
    ts_part = f" | {ts}" if ts else ""
    props = f"| {issue.type.value} | {issue.id}{ts_part}"
    lines.append(f"[{status_color}]{display_status}[/{status_color}] [gray69]{props}[/gray69]")

    # Handoff message if stopped
    if issue.status.value == 'stopped' and issue.annotations:
        for ann in reversed(issue.annotations):
            if ann.type == AnnotationType.HANDOFF:
                lines.append("")
                lines.append(f"[bold red]HANDOFF:[/bold red] {ann.message}")
                break

    # Repeatable body (default text color)
    if issue.body:
        if '---' in issue.body:
            repeatable_body = issue.body.split('---')[0].strip()
        else:
            repeatable_body = issue.body.strip()
        if repeatable_body:
            lines.append("")
            lines.append(repeatable_body)

    # Short issue links section (table aligned) - no repeatable body
    link_lines: list[str] = []
    if ancestors:
        parent = ancestors[0]
        link_lines.append(_render_issue_link_short(parent, "parent"))
    for child in descendants:
        link_lines.append(_render_issue_link_short(child, "child"))
    for sib in siblings:
        link_lines.append(_render_issue_link_short(sib, "sibling"))
    for ref in referenced:
        link_lines.append(_render_issue_link_short(ref, "refs"))
    for ref in referencing:
        link_lines.append(_render_issue_link_short(ref, "ref-by"))

    if link_lines:
        lines.append("")
        lines.extend(link_lines)

    # Short annotations (first line only, excluding work-begin/work-end)
    if issue.annotations:
        visible_anns = [
            ann for ann in issue.annotations
            if ann.type.value not in ('work-begin', 'work-end') and ann.message.strip()
        ]
        if visible_anns:
            lines.append("")
            for ann in visible_anns:
                lines.append(_render_annotation_short(ann))

    # Non-repeatable body
    if issue.body and '---' in issue.body:
        parts = issue.body.split('---', 1)
        if len(parts) > 1 and parts[1].strip():
            lines.append("")
            lines.append("[gray69]---[/gray69]")
            lines.append("")
            lines.append(parts[1].strip())

    # Full annotations
    if issue.annotations:
        visible_anns = [
            ann for ann in issue.annotations
            if ann.type.value not in ('work-begin', 'work-end') and ann.message.strip()
        ]
        multiline_anns = [ann for ann in visible_anns if '\n' in ann.message]
        if multiline_anns:
            lines.append("")
            lines.append("[gray69]---[/gray69]")
            for ann in multiline_anns:
                ts_str = relative_time(ann.timestamp)
                lines.append("")
                lines.append(f"[gray69]{ann.type.value}:[/gray69] [gray69]({ts_str})[/gray69]")
                lines.append(ann.message)

    return "\n".join(lines)


def render_view_body(issue: Issue) -> str:
    """Render just the issue body as markdown (for TUI markdown widget).

    Args:
        issue: The issue to render

    Returns:
        Markdown formatted issue body with header and annotations
    """
    lines: list[str] = []

    lines.append(f"# {issue.title}")

    display_status, _ = _format_status(issue.status.value)
    ts = status_timestamp(issue)
    ts_part = f" | {ts}" if ts else ""
    lines.append(f"*{display_status} | {issue.type.value} | {issue.id}{ts_part}*")

    if issue.status.value == 'stopped' and issue.annotations:
        for ann in reversed(issue.annotations):
            if ann.type == AnnotationType.HANDOFF:
                lines.append("")
                lines.append(f"> **HANDOFF:** {ann.message}")
                break

    if issue.body:
        if '---' in issue.body:
            repeatable_body = issue.body.split('---')[0].strip()
        else:
            repeatable_body = issue.body.strip()
        if repeatable_body:
            lines.append("")
            lines.append(repeatable_body)

    if issue.annotations:
        visible_anns = [
            ann for ann in issue.annotations
            if ann.type.value not in ('work-begin', 'work-end') and ann.message.strip()
        ]
        if visible_anns:
            lines.append("")
            for ann in visible_anns:
                first_line = ann.message.split('\n')[0].strip()
                lines.append(f"- **{ann.type.value}:** {first_line}")

    if issue.body and '---' in issue.body:
        parts = issue.body.split('---', 1)
        if len(parts) > 1 and parts[1].strip():
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append(parts[1].strip())

    return "\n".join(lines)


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
    ancestors = ancestors or []
    siblings = siblings or []
    descendants = descendants or []
    referenced = referenced or []
    referencing = referencing or []

    lines: list[str] = []

    if ancestors:
        parent = ancestors[0]
        lines.append(_render_issue_link_short(parent, "parent"))
    for child in descendants:
        lines.append(_render_issue_link_short(child, "child"))
    for sib in siblings:
        lines.append(_render_issue_link_short(sib, "sibling"))
    for ref in referenced:
        lines.append(_render_issue_link_short(ref, "refs"))
    for ref in referencing:
        lines.append(_render_issue_link_short(ref, "ref-by"))

    return "\n".join(lines)


def render_tree(issues: list[Issue]) -> str:
    """Render a list of issues as a tree structure.

    Args:
        issues: List of issues to render

    Returns:
        Tree-formatted text output
    """
    issue_map = {issue.id: issue for issue in issues}

    def compute_depth(issue: Issue) -> int:
        """Compute the depth of an issue in the tree."""
        depth = 0
        current = issue
        while current.parent:
            depth += 1
            parent_issue = issue_map.get(current.parent)
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
    issue_map = {issue.id: issue for issue in hierarchy}

    def compute_depth(issue: Issue) -> int:
        """Compute the depth of an issue in the tree."""
        depth = 0
        current = issue
        while current.parent:
            depth += 1
            parent_issue = issue_map.get(current.parent)
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
        lines.append(f"# {issue.id} ({issue.type.value})")

        # Entry line
        lines.append(f"- {issue.type.value}: {issue.title}")

        # Body lines (indented)
        if issue.body:
            for body_line in issue.body.splitlines():
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

    from tw.cli import CaptureEntry, parse_capture_dsl

    actions: list[GroomAction] = []
    seen_ids: set[str] = set()

    # Track which ID each entry is associated with
    lines = content.splitlines()
    current_id: str | None = None
    entries_by_id: dict[str | None, list[CaptureEntry]] = {}

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
                    issue_pattern = r'^\s*-\s*(epic|story|task|bug|idea):'
                    if next_line.startswith("#") or re.match(issue_pattern, next_line):
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


def render_brief(
    issue: Issue,
    ancestors: list[Issue] | None = None,
    siblings: list[Issue] | None = None,
    descendants: list[Issue] | None = None,
    referenced: list[Issue] | None = None,
    referencing: list[Issue] | None = None,
) -> str:
    """Render a focused coder briefing for a subagent.

    This provides everything a coder subagent needs in one document:
    - Task context (title, status, body)
    - Lessons from completed siblings
    - Ancestor context
    - Protocol (essential commands)
    - Workflow checklist

    Args:
        issue: The issue to brief on
        ancestors: List of ancestor issues (parent to root)
        siblings: List of sibling issues
        descendants: List of descendant issues
        referenced: Issues referenced by this issue
        referencing: Issues that reference this issue

    Returns:
        Plain markdown formatted coder briefing
    """
    ancestors = ancestors or []
    siblings = siblings or []
    descendants = descendants or []
    referenced = referenced or []
    referencing = referencing or []

    lines: list[str] = []
    issue_id = issue.id

    lines.append(f"# Coder Brief: {issue_id}")
    lines.append(f"type: {issue.type.value} | status: {issue.status.value}")
    lines.append("")

    if issue.status.value == "blocked":
        blocked_reason = ""
        if issue.annotations:
            for ann in reversed(issue.annotations):
                if ann.type == AnnotationType.BLOCKED:
                    blocked_reason = ann.message.split('\n')[0]
                    break
        lines.append("⚠️ **WARNING: This task is BLOCKED**")
        if blocked_reason:
            lines.append(f"Reason: {blocked_reason}")
        lines.append(f"Consider: `tw unblock {issue_id}` before proceeding")
        lines.append("")

    if issue.status.value == "stopped":
        lines.append("⚠️ **This task was handed off. Read the handoff note below.**")
        lines.append("")

    if issue.status.value == "done":
        lines.append("⚠️ **This task is already marked DONE.**")
        lines.append("")

    completed_siblings = [s for s in siblings if s.status.value == 'done']
    sibling_lessons: list[tuple[Issue, list[Annotation]]] = []
    for sib in completed_siblings:
        if sib.annotations:
            lessons = [
                ann for ann in sib.annotations
                if ann.type.value in ('lesson', 'deviation') and ann.message.strip()
            ]
            if lessons:
                sibling_lessons.append((sib, lessons))

    if sibling_lessons:
        lines.append("")
        lines.append("## Lessons from Completed Siblings")
        lines.append("")
        lines.append("**Read these first.** Previous tasks recorded these learnings:")
        for sib, lessons in sibling_lessons:
            truncated_title = sib.title[:50] + "..." if len(sib.title) > 50 else sib.title
            lines.append("")
            lines.append(f"**{sib.id}** ({truncated_title}):")
            for lesson in lessons:
                first_line = lesson.message.split('\n')[0]
                lines.append(f"- [{lesson.type.value}] {first_line}")

    lines.append("")
    lines.append("## Your Task")
    lines.append("")
    lines.append(f"**{issue.title}**")
    if issue.body:
        lines.append("")
        lines.append(issue.body)
        lines.append("")

    if issue.status.value == 'stopped' and issue.annotations:
        for ann in reversed(issue.annotations):
            if ann.type == AnnotationType.HANDOFF:
                lines.append("")
                lines.append(f"> **HANDOFF:** {ann.message}")
                break

    def render_related_issue(issue: Issue, has_repeatable_body: bool = True) -> list[str]:
        lines = []
        truncated_title = issue.title[:60] + "..." if len(issue.title) > 60 else issue.title
        status_mark = "✓" if issue.status.value == "done" else "○"
        lines.append(f"- {status_mark} **{issue.id}** [{issue.status.value}] {truncated_title}")
        if has_repeatable_body:
            rep_body = issue.get_repeatable_body()
            if rep_body:
                for body_line in rep_body.splitlines():
                    lines.append(f"> {body_line}")
                non_rep_body = issue.get_nonrepeatable_body()
                if non_rep_body:
                    lines.append(f"  (and {len(non_rep_body.splitlines())} more lines)")
                lines.append("")
        return lines

    if ancestors:
        lines.append("")
        lines.append("## Parent Context")
        lines.append("")
        for ancestor in ancestors:
            lines.extend(render_related_issue(ancestor))

    if descendants:
        lines.append("")
        lines.append("## Subtasks")
        lines.append("")
        for desc in descendants:
            lines.extend(render_related_issue(desc))

    if siblings:
        lines.append("")
        lines.append("## Sibling Tasks")
        lines.append("")
        for sib in siblings:
            lines.extend(render_related_issue(sib, has_repeatable_body=False))

    if referencing:
        lines.append("")
        lines.append("## Referencing Tasks")
        lines.append("")
        for ref in referencing:
            lines.extend(render_related_issue(ref, has_repeatable_body=False))

    if referenced:
        lines.append("")
        lines.append("## Referenced Tasks")
        lines.append("")
        for ref in referenced:
            lines.extend(render_related_issue(ref))

    lines.append("")
    lines.append("## Workflow")
    lines.append("")
    lines.append(f"1. `tw start {issue_id}`")
    lines.append("2. (optional) `tw view OTHER-123` to inspect other issue for more details")
    lines.append("3. Implement the task")
    lines.append(f"4. After each commit: `tw record {issue_id} commit -m \"hash - description\"`")
    lines.append("5. **BEFORE completing**:")
    lines.append(f"   - Patterns established? → `tw record {issue_id} lesson -m \"...\"`")
    lines.append(f"   - Changed from plan? → `tw record {issue_id} deviation -m \"...\"`")
    lines.append(f"   - Surprises? → `tw record {issue_id} lesson -m \"...\"`")
    lines.append(f"6. `tw done {issue_id}`")
    lines.append("")
    lines.append(
        "**If you need to hand off before completion** "
        "(approaching context limits or pausing work):"
    )
    lines.append("")
    lines.append(
        f"`tw handoff {issue_id} --status \"...\" --completed \"...\" --remaining \"...\"`"
    )
    lines.append("")
    lines.append(
        "Provide detailed multiline blocks for status, completed work, and remaining work."
    )
    lines.append(
        "The next agent will see this prominently when they run `tw view` or `tw brief`."
    )
    lines.append("")
    lines.append("Lessons should be useful when doing other work, not a summary of this commit.")
    lines.append("When recording annotations/commits, the first line (50 chars) is the summary.")
    lines.append("")
    lines.append(
        "**Note:** This brief contains everything you need for typical coding tasks. "
        "Only reference"
    )
    lines.append(
        "`tw onboard` if you need details on: other annotation types, status transitions, "
        "body structure,"
    )
    lines.append(
        "backlog grooming, or configuration. "
        "(Warning: `tw onboard` is 700+ lines and may bloat context.)"
    )

    lines.append("")
    lines.append("## Discovered Work")
    lines.append("")
    lines.append("If you find bugs or ideas unrelated to your task:")
    lines.append("")
    lines.append("```bash")
    lines.append(
        f"tw new bug --title \"...\" --body \"Discovered while working on {issue_id}. "
        "In file:line...\""
    )
    lines.append("tw new idea --title \"...\" --body \"...\"")
    lines.append("```")
    lines.append("")
    lines.append("**Do NOT fix unrelated issues.** Stay focused on your assigned task.")

    lines.append("")
    lines.append("## Rules")
    lines.append("")
    lines.append("- **Don't edit issues** — annotate instead (preserves history)")
    lines.append("- **Record lessons before done** — mandatory, not optional")
    lines.append("- **Use structured annotations** — lesson/deviation/commit, not generic comments")

    lines.append("")
    lines.append("## Reminder: Your Task")
    lines.append("")
    lines.append(f"**{issue.title}**")
    if issue.body:
        lines.append("")
        lines.append(issue.body)
        lines.append("")

    return "\n".join(lines)


def build_claude_prompt(brief: str, child_count: int, issue_id: str) -> str:
    """Build the complete Claude prompt from a brief.

    When the issue has children (non-leaf), generates an orchestrator prompt
    that instructs the agent to dispatch subagents for individual tasks.
    For leaf issues (no children), returns the brief unchanged.

    Args:
        brief: The rendered brief from render_brief()
        child_count: Number of direct children (not total descendants)
        issue_id: The issue ID for the orchestrator prompt

    Returns:
        The complete prompt to send to Claude
    """
    if child_count == 0:
        return brief

    orchestrator_prompt = f"""# Orchestrator Brief: {issue_id}

You are an **orchestrator** for this issue. Do not implement tasks yourself.

{brief}

---

## Your Role: Orchestrator

Address {issue_id} by acting as the orchestrator for subagents that complete specific tasks.
**Do not do any implementation work yourself.** Your role is to:

1. Review the subtasks listed above
2. Dispatch subagents using the **haiku** model to implement tasks one by one
3. Monitor task completion via `tw view` and `tw tree`
4. Mark stories as done when their child tasks are complete

## Workflow

1. Run `tw tree {issue_id}` to see current subtask status
2. Pick an actionable subtask (status: new or in_progress)
3. Dispatch a subagent: use `Task` tool with haiku model and prompt like:
   ```
   tw brief SUBTASK-ID

   Implement this task following the brief above.
   ```
4. When subagent completes, verify with `tw view SUBTASK-ID`
5. Repeat until all subtasks are done
6. Mark parent stories done when all their tasks complete
7. Finally: `tw done {issue_id}`

## Rules

- **Never implement code yourself** — dispatch subagents
- **Use haiku model** for subagents to minimize cost/latency
- **One task at a time** unless tasks are independent
- **Verify completion** before moving to next task
- Record lessons at the end: `tw record {issue_id} lesson -m "..."`
"""
    return orchestrator_prompt


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
