"""Tests for Jinja template rendering."""

import pytest
from datetime import datetime, timedelta, timezone

from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType
from tw.render import (
    render_digest,
    render_groom_content,
    relative_time,
    render_tree,
    render_view,
    parse_groom_result,
    GroomAction,
    get_status_timestamp,
    status_timestamp,
    generate_edit_template,
    parse_edited_content,
)


class TestRelativeTime:
    def test_relative_time_just_now(self) -> None:
        """Test relative time for very recent timestamps."""
        now = datetime.now(timezone.utc)
        recent = now - timedelta(seconds=30)
        assert relative_time(recent) == "just now"

    def test_relative_time_minutes(self) -> None:
        """Test relative time for minutes ago."""
        now = datetime.now(timezone.utc)
        five_min_ago = now - timedelta(minutes=5)
        assert relative_time(five_min_ago) == "5 minutes ago"
        one_min_ago = now - timedelta(minutes=1)
        assert relative_time(one_min_ago) == "1 minute ago"

    def test_relative_time_hours(self) -> None:
        """Test relative time for hours ago."""
        now = datetime.now(timezone.utc)
        three_hours_ago = now - timedelta(hours=3)
        assert relative_time(three_hours_ago) == "3 hours ago"
        one_hour_ago = now - timedelta(hours=1)
        assert relative_time(one_hour_ago) == "1 hour ago"

    def test_relative_time_days(self) -> None:
        """Test relative time for days ago."""
        now = datetime.now(timezone.utc)
        two_days_ago = now - timedelta(days=2)
        assert relative_time(two_days_ago) == "2 days ago"
        one_day_ago = now - timedelta(days=1)
        assert relative_time(one_day_ago) == "1 day ago"

    def test_relative_time_weeks(self) -> None:
        """Test relative time for weeks ago."""
        now = datetime.now(timezone.utc)
        two_weeks_ago = now - timedelta(weeks=2)
        assert relative_time(two_weeks_ago) == "2 weeks ago"
        one_week_ago = now - timedelta(weeks=1)
        assert relative_time(one_week_ago) == "1 week ago"

    def test_relative_time_months(self) -> None:
        """Test relative time for months ago."""
        now = datetime.now(timezone.utc)
        two_months_ago = now - timedelta(days=60)
        assert relative_time(two_months_ago) == "2 months ago"
        one_month_ago = now - timedelta(days=31)
        assert relative_time(one_month_ago) == "1 month ago"

    def test_relative_time_years(self) -> None:
        """Test relative time for years ago."""
        now = datetime.now(timezone.utc)
        two_years_ago = now - timedelta(days=730)
        assert relative_time(two_years_ago) == "2 years ago"
        one_year_ago = now - timedelta(days=365)
        assert relative_time(one_year_ago) == "1 year ago"


class TestRenderView:
    def test_render_view_minimal(self) -> None:
        """Render single issue with minimal fields."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="User Authentication",
            tw_status=IssueStatus.NEW,
            project="myproject",
        )
        result = render_view(issue)
        assert "PROJ-1" in result
        assert "epic" in result
        assert "User Authentication" in result
        assert "new" in result

    def test_render_view_with_parent(self) -> None:
        """Render issue with parent reference."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1-1",
            tw_type=IssueType.STORY,
            title="Login Flow",
            tw_status=IssueStatus.IN_PROGRESS,
            project="myproject",
            tw_parent="PROJ-1",
        )
        result = render_view(issue)
        assert "PROJ-1-1" in result
        assert "PROJ-1" in result
        assert "Login Flow" in result

    def test_render_view_with_body(self) -> None:
        """Render issue with body text."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.TASK,
            title="Implement OAuth",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_body="Add OAuth 2.0 support\n---\nMore details here",
        )
        result = render_view(issue)
        assert "Implement OAuth" in result
        assert "Add OAuth 2.0 support" in result

    def test_render_view_with_refs(self) -> None:
        """Render issue with references."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="User Authentication",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_refs=["PROJ-2", "PROJ-3"],
        )
        result = render_view(issue)
        assert "PROJ-2" in result
        assert "PROJ-3" in result

    def test_render_view_with_annotations(self) -> None:
        """Render issue with annotations (excluding system annotations)."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.TASK,
            title="Implement OAuth",
            tw_status=IssueStatus.IN_PROGRESS,
            project="myproject",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
                    message="Starting work on OAuth implementation",
                ),
                Annotation(
                    type=AnnotationType.COMMIT,
                    timestamp=datetime(2024, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
                    message="Added OAuth client configuration",
                ),
            ],
        )
        result = render_view(issue)
        assert "## Annotations" in result
        assert "[work-begin]" not in result
        assert "[commit]" in result
        assert "2024-01-15 14:00:00" in result
        assert "Added OAuth client configuration" in result

    def test_render_view_stopped_with_handoff(self) -> None:
        """Render stopped issue with handoff annotation prominently displayed."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="User Profile Page",
            tw_status=IssueStatus.STOPPED,
            project="myproject",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                    message="Starting profile work",
                ),
                Annotation(
                    type=AnnotationType.HANDOFF,
                    timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=timezone.utc),
                    message="Need to wait for API endpoint deployment before continuing",
                ),
            ],
        )
        result = render_view(issue)
        assert "**HANDOFF:**" in result
        assert "Need to wait for API endpoint deployment before continuing" in result
        lines = result.split("\n")
        handoff_line = next(i for i, line in enumerate(lines) if "**HANDOFF:**" in line)
        props_line = next(i for i, line in enumerate(lines) if "stopped" in line)
        assert handoff_line < props_line

    def test_render_view_filters_work_begin_end_annotations(self) -> None:
        """Work-begin and work-end annotations should not appear in rendered view."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.TASK,
            title="Task with system annotations",
            tw_status=IssueStatus.DONE,
            project="myproject",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                    message="",
                ),
                Annotation(
                    type=AnnotationType.COMMIT,
                    timestamp=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
                    message="abc123 - Implemented feature",
                ),
                Annotation(
                    type=AnnotationType.WORK_END,
                    timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                    message="",
                ),
            ],
        )
        result = render_view(issue)
        assert "[work-begin]" not in result
        assert "[work-end]" not in result
        assert "[commit]" in result
        assert "abc123 - Implemented feature" in result

    def test_render_view_filters_empty_annotations(self) -> None:
        """Annotations with empty messages should not appear in rendered view."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.TASK,
            title="Task with empty annotations",
            tw_status=IssueStatus.IN_PROGRESS,
            project="myproject",
            annotations=[
                Annotation(
                    type=AnnotationType.COMMENT,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                    message="",
                ),
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
                    message="    ",
                ),
                Annotation(
                    type=AnnotationType.DEVIATION,
                    timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                    message="Changed approach to use Redis",
                ),
            ],
        )
        result = render_view(issue)
        assert "[comment]" not in result
        assert "[lesson]" not in result
        assert "[deviation]" in result
        assert "Changed approach to use Redis" in result

    def test_render_view_no_annotation_section_when_all_filtered(self) -> None:
        """Annotations section should not appear when all annotations are filtered."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.TASK,
            title="Task with only system annotations",
            tw_status=IssueStatus.DONE,
            project="myproject",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                    message="",
                ),
                Annotation(
                    type=AnnotationType.WORK_END,
                    timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                    message="",
                ),
            ],
        )
        result = render_view(issue)
        assert "## Annotations" not in result

    def test_render_view_shows_first_line_of_multiline_annotation(self) -> None:
        """Only first line of multiline annotation messages should be shown."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.TASK,
            title="Task with multiline annotation",
            tw_status=IssueStatus.IN_PROGRESS,
            project="myproject",
            annotations=[
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                    message="First line is important\nSecond line has details\nThird line has more",
                ),
            ],
        )
        result = render_view(issue)
        assert "First line is important" in result
        assert "Second line has details" not in result
        assert "Third line has more" not in result

    def test_render_view_siblings_with_tree_format(self) -> None:
        """Siblings should be rendered with tree format showing status and type."""
        sibling1 = Issue(
            uuid="abc-1",
            tw_id="PROJ-1-1",
            tw_type=IssueType.TASK,
            title="Sibling Task 1",
            tw_status=IssueStatus.DONE,
            project="myproject",
            tw_parent="PROJ-1",
        )
        sibling2 = Issue(
            uuid="abc-2",
            tw_id="PROJ-1-2",
            tw_type=IssueType.TASK,
            title="Sibling Task 2",
            tw_status=IssueStatus.IN_PROGRESS,
            project="myproject",
            tw_parent="PROJ-1",
        )
        issue = Issue(
            uuid="abc-3",
            tw_id="PROJ-1-3",
            tw_type=IssueType.TASK,
            title="Current Task",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_parent="PROJ-1",
        )
        result = render_view(issue, siblings=[sibling1, sibling2])
        assert "## Siblings" in result
        assert "PROJ-1-1" in result
        assert "PROJ-1-2" in result
        assert "Sibling Task 1" in result
        assert "Sibling Task 2" in result
        assert "done" in result
        assert "in_progress" in result

    def test_render_view_siblings_show_repeatable_body(self) -> None:
        """Siblings should show their repeatable bodies using tree format."""
        sibling = Issue(
            uuid="abc-1",
            tw_id="PROJ-1-1",
            tw_type=IssueType.STORY,
            title="Sibling Story",
            tw_status=IssueStatus.DONE,
            project="myproject",
            tw_parent="PROJ-1",
            tw_body="This is repeatable context\nWith multiple lines\n---\nThis is non-repeatable detail",
        )
        issue = Issue(
            uuid="abc-2",
            tw_id="PROJ-1-2",
            tw_type=IssueType.STORY,
            title="Current Story",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_parent="PROJ-1",
        )
        result = render_view(issue, siblings=[sibling])
        assert "## Siblings" in result
        assert "Sibling Story" in result
        assert "This is repeatable context" in result
        assert "With multiple lines" in result
        assert "This is non-repeatable detail" not in result

    def test_render_view_siblings_show_annotations(self) -> None:
        """Siblings should show annotations (excluding work-begin/work-end) using tree format."""
        now = datetime.now(timezone.utc)
        sibling = Issue(
            uuid="abc-1",
            tw_id="PROJ-1-1",
            tw_type=IssueType.TASK,
            title="Sibling Task",
            tw_status=IssueStatus.DONE,
            project="myproject",
            tw_parent="PROJ-1",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=now - timedelta(hours=2),
                    message="",
                ),
                Annotation(
                    type=AnnotationType.COMMIT,
                    timestamp=now - timedelta(hours=1),
                    message="abc123 - Implemented feature",
                ),
                Annotation(
                    type=AnnotationType.WORK_END,
                    timestamp=now - timedelta(minutes=30),
                    message="",
                ),
            ],
        )
        issue = Issue(
            uuid="abc-2",
            tw_id="PROJ-1-2",
            tw_type=IssueType.TASK,
            title="Current Task",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_parent="PROJ-1",
        )
        result = render_view(issue, siblings=[sibling])
        assert "## Siblings" in result
        assert "commit:" in result
        assert "abc123 - Implemented feature" in result
        assert "work-begin:" not in result
        assert "work-end:" not in result


class TestRenderTree:
    def test_render_tree_single(self) -> None:
        """Render tree with single issue."""
        issues = [
            Issue(
                uuid="abc-123",
                tw_id="PROJ-1",
                tw_type=IssueType.EPIC,
                title="User Authentication",
                tw_status=IssueStatus.NEW,
                project="myproject",
            )
        ]
        result = render_tree(issues)
        assert "PROJ-1" in result
        assert "User Authentication" in result

    def test_render_tree_multiple(self) -> None:
        """Render tree with multiple issues."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1",
                tw_type=IssueType.EPIC,
                title="User Authentication",
                tw_status=IssueStatus.NEW,
                project="myproject",
            ),
            Issue(
                uuid="abc-2",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="Login Flow",
                tw_status=IssueStatus.IN_PROGRESS,
                project="myproject",
                tw_parent="PROJ-1",
            ),
            Issue(
                uuid="abc-3",
                tw_id="PROJ-2",
                tw_type=IssueType.EPIC,
                title="Data Layer",
                tw_status=IssueStatus.NEW,
                project="myproject",
            ),
        ]
        result = render_tree(issues)
        assert "PROJ-1" in result
        assert "PROJ-1-1" in result
        assert "PROJ-2" in result
        assert "User Authentication" in result
        assert "Login Flow" in result
        assert "Data Layer" in result

    def test_render_tree_orphan_story_no_indent(self) -> None:
        """Orphan story (no parent) should render without indentation."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="Orphan Story",
                tw_status=IssueStatus.NEW,
                project="myproject",
                tw_parent=None,
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        assert "[gray69]story[/gray69]" in lines[0]
        assert "[blue]PROJ-1-1[/blue]" in lines[0]
        assert "[default]Orphan Story[/default]" in lines[0]
        assert not lines[0].startswith(" ")

    def test_render_tree_orphan_task_no_indent(self) -> None:
        """Orphan task (no parent) should render without indentation."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1a",
                tw_type=IssueType.TASK,
                title="Orphan Task",
                tw_status=IssueStatus.NEW,
                project="myproject",
                tw_parent=None,
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        assert "[gray69]task[/gray69]" in lines[0]
        assert "[blue]PROJ-1-1a[/blue]" in lines[0]
        assert "[default]Orphan Task[/default]" in lines[0]
        assert not lines[0].startswith(" ")

    def test_render_tree_child_task_indented(self) -> None:
        """Task with parent should be indented."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="Parent Story",
                tw_status=IssueStatus.NEW,
                project="myproject",
                tw_parent=None,
            ),
            Issue(
                uuid="abc-2",
                tw_id="PROJ-1-1a",
                tw_type=IssueType.TASK,
                title="Child Task",
                tw_status=IssueStatus.NEW,
                project="myproject",
                tw_parent="PROJ-1-1",
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 2
        assert "[gray69]story[/gray69]" in lines[0]
        assert not lines[0].startswith(" ")
        assert "[gray69]task[/gray69]" in lines[1]
        assert lines[1].startswith("  ")

    def test_render_tree_full_hierarchy_indentation(self) -> None:
        """Epic → Story → Task should have correct depth-based indentation."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1",
                tw_type=IssueType.EPIC,
                title="Epic",
                tw_status=IssueStatus.NEW,
                project="myproject",
                tw_parent=None,
            ),
            Issue(
                uuid="abc-2",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="Story under Epic",
                tw_status=IssueStatus.NEW,
                project="myproject",
                tw_parent="PROJ-1",
            ),
            Issue(
                uuid="abc-3",
                tw_id="PROJ-1-1a",
                tw_type=IssueType.TASK,
                title="Task under Story",
                tw_status=IssueStatus.NEW,
                project="myproject",
                tw_parent="PROJ-1-1",
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 3
        # Epic: no indent (depth 0)
        assert "[gray69]epic[/gray69]" in lines[0]
        assert not lines[0].startswith(" ")
        # Story: 2-space indent (depth 1)
        assert "[gray69]story[/gray69]" in lines[1]
        assert lines[1].startswith("  ") and not lines[1].startswith("    ")
        # Task: 4-space indent (depth 2)
        assert "[gray69]task[/gray69]" in lines[2]
        assert lines[2].startswith("    ")

    def test_render_tree_task_with_annotations(self) -> None:
        """Task with annotations should show non-work-begin/work-end annotations with relative time."""
        now = datetime.now(timezone.utc)
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1a",
                tw_type=IssueType.TASK,
                title="Task with annotations",
                tw_status=IssueStatus.IN_PROGRESS,
                project="myproject",
                annotations=[
                    Annotation(
                        type=AnnotationType.WORK_BEGIN,
                        timestamp=now - timedelta(hours=3),
                        message="Started working on feature",
                    ),
                    Annotation(
                        type=AnnotationType.COMMIT,
                        timestamp=now - timedelta(minutes=30),
                        message="Added initial implementation",
                    ),
                    Annotation(
                        type=AnnotationType.WORK_END,
                        timestamp=now - timedelta(minutes=15),
                        message="",
                    ),
                ],
            ),
        ]
        result = render_tree(issues)
        assert "work-begin:" not in result
        assert "work-end:" not in result
        assert "commit:" in result
        assert "annotation:" not in result
        assert "30 minutes ago" in result
        assert "Added initial implementation" in result

    def test_render_tree_task_annotation_multiline_truncated(self) -> None:
        """Task annotations with multiline messages should show only first line."""
        now = datetime.now(timezone.utc)
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1a",
                tw_type=IssueType.TASK,
                title="Task with multiline annotation",
                tw_status=IssueStatus.IN_PROGRESS,
                project="myproject",
                annotations=[
                    Annotation(
                        type=AnnotationType.HANDOFF,
                        timestamp=now - timedelta(hours=1),
                        message="First line of message\nSecond line should not appear\nThird line also hidden",
                    ),
                ],
            ),
        ]
        result = render_tree(issues)
        assert "handoff:" in result
        assert "First line of message" in result
        assert "Second line should not appear" not in result
        assert "Third line also hidden" not in result

    def test_render_tree_done_issue_all_gray69(self) -> None:
        """Completed (done) issues should have all text colored gray69."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1",
                tw_type=IssueType.EPIC,
                title="Completed Epic",
                tw_status=IssueStatus.DONE,
                project="myproject",
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        # Check that all parts are wrapped in gray69 (except ID which is blue)
        assert "[gray69]epic[/gray69]" in lines[0]
        assert "[gray69]Completed Epic[/gray69]" in lines[0]
        assert "[blue]PROJ-1[/blue]" in lines[0]
        # Make sure there's no yellow or other color for done issues
        assert "[yellow]" not in lines[0]
        # Check that status is shown in format (ID, status)
        assert "[blue]PROJ-1[/blue][gray69], done)[/gray69]" in lines[0]

    def test_render_tree_in_progress_status_in_parens(self) -> None:
        """In progress issues should show status in parentheses with ID."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="In Progress Story",
                tw_status=IssueStatus.IN_PROGRESS,
                project="myproject",
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        # Check format: (ID, status) with appropriate colors
        assert "[blue]PROJ-1-1[/blue][gray69], [/gray69][yellow]in_progress[/yellow]" in lines[0]

    def test_render_tree_blocked_status_in_parens(self) -> None:
        """Blocked issues should show status in parentheses with ID in red."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-2-1",
                tw_type=IssueType.STORY,
                title="Blocked Story",
                tw_status=IssueStatus.BLOCKED,
                project="myproject",
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        # Check format: (ID, status) with ID blue and status red
        assert "[blue]PROJ-2-1[/blue][gray69], [/gray69][red]blocked[/red]" in lines[0]

    def test_render_tree_stopped_status_in_parens(self) -> None:
        """Stopped issues should show status in parentheses with ID in red."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-3-1",
                tw_type=IssueType.STORY,
                title="Stopped Story",
                tw_status=IssueStatus.STOPPED,
                project="myproject",
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        # Check format: (ID, status) with ID blue and status red
        assert "[blue]PROJ-3-1[/blue][gray69], [/gray69][red]stopped[/red]" in lines[0]

    def test_render_tree_new_status_no_status_shown(self) -> None:
        """New issues should NOT show status in parentheses, just ID."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-4-1",
                tw_type=IssueType.STORY,
                title="New Story",
                tw_status=IssueStatus.NEW,
                project="myproject",
            ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        # Check format: just (ID) without status
        assert "[blue]PROJ-4-1[/blue][gray69])[/gray69]" in lines[0]
        # Make sure status is NOT shown
        assert "new)" not in result

    def test_render_tree_in_progress_with_work_begin_timestamp(self) -> None:
        """In progress issues should show work-begin timestamp next to status."""
        now = datetime.now(timezone.utc)
        work_start = now - timedelta(hours=2)
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="In Progress with Start Time",
                tw_status=IssueStatus.IN_PROGRESS,
                project="myproject",
                annotations=[
                    Annotation(
                        type=AnnotationType.WORK_BEGIN,
                        timestamp=work_start,
                        message="",
                    ),
                ],
            ),
        ]
        result = render_tree(issues)
        assert "[yellow]in_progress[/yellow] (2 hours ago)" in result

    def test_render_tree_blocked_with_blocked_timestamp(self) -> None:
        """Blocked issues should show blocked timestamp next to status."""
        now = datetime.now(timezone.utc)
        blocked_time = now - timedelta(hours=1)
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-2-1",
                tw_type=IssueType.STORY,
                title="Blocked Story",
                tw_status=IssueStatus.BLOCKED,
                project="myproject",
                annotations=[
                    Annotation(
                        type=AnnotationType.BLOCKED,
                        timestamp=blocked_time,
                        message="Waiting for approval",
                    ),
                ],
            ),
        ]
        result = render_tree(issues)
        assert "[red]blocked[/red] (1 hour ago)" in result

    def test_render_tree_stopped_with_work_begin_timestamp(self) -> None:
        """Stopped issues should show work-begin timestamp next to status."""
        now = datetime.now(timezone.utc)
        work_start = now - timedelta(hours=3)
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-3-1",
                tw_type=IssueType.STORY,
                title="Stopped Story",
                tw_status=IssueStatus.STOPPED,
                project="myproject",
                annotations=[
                    Annotation(
                        type=AnnotationType.WORK_BEGIN,
                        timestamp=work_start,
                        message="",
                    ),
                ],
            ),
        ]
        result = render_tree(issues)
        assert "[red]stopped[/red] (3 hours ago)" in result

    def test_render_tree_in_progress_without_work_begin_no_timestamp(self) -> None:
        """In progress without work-begin should not show timestamp."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="In Progress without Start",
                tw_status=IssueStatus.IN_PROGRESS,
                project="myproject",
                annotations=[],
            ),
        ]
        result = render_tree(issues)
        # Should have status but no timestamp
        assert "[yellow]in_progress[/yellow]" in result
        assert "hour" not in result
        assert "minute" not in result
        assert "day" not in result

    def test_render_tree_blocked_without_blocked_annotation_no_timestamp(self) -> None:
        """Blocked without blocked annotation should not show timestamp."""
        issues = [
            Issue(
                uuid="abc-1",
                tw_id="PROJ-2-1",
                tw_type=IssueType.STORY,
                title="Blocked Story",
                tw_status=IssueStatus.BLOCKED,
                project="myproject",
                annotations=[
                    Annotation(
                        type=AnnotationType.COMMENT,
                        timestamp=datetime.now(timezone.utc),
                        message="Some comment",
                    ),
                ],
            ),
        ]
        result = render_tree(issues)
        # Should have status but no timestamp
        assert "[red]blocked[/red]" in result
        assert "hour" not in result
        assert "minute" not in result
        assert "day" not in result


class TestGetStatusTimestamp:
    def test_get_status_timestamp_blocked(self) -> None:
        """For blocked issues, returns BLOCKED annotation timestamp."""
        now = datetime.now(timezone.utc)
        blocked_time = now - timedelta(hours=1)
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="Blocked Story",
            tw_status=IssueStatus.BLOCKED,
            project="test",
            annotations=[
                Annotation(
                    type=AnnotationType.BLOCKED,
                    timestamp=blocked_time,
                    message="Blocked reason",
                ),
            ],
        )
        result = get_status_timestamp(issue)
        assert result == blocked_time

    def test_get_status_timestamp_in_progress(self) -> None:
        """For in_progress issues, returns WORK_BEGIN annotation timestamp."""
        now = datetime.now(timezone.utc)
        work_start = now - timedelta(hours=2)
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="In Progress Story",
            tw_status=IssueStatus.IN_PROGRESS,
            project="test",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=work_start,
                    message="",
                ),
            ],
        )
        result = get_status_timestamp(issue)
        assert result == work_start

    def test_get_status_timestamp_stopped(self) -> None:
        """For stopped issues, returns WORK_BEGIN annotation timestamp."""
        now = datetime.now(timezone.utc)
        work_start = now - timedelta(hours=3)
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="Stopped Story",
            tw_status=IssueStatus.STOPPED,
            project="test",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=work_start,
                    message="",
                ),
            ],
        )
        result = get_status_timestamp(issue)
        assert result == work_start

    def test_get_status_timestamp_new_returns_none(self) -> None:
        """For new issues, returns None regardless of annotations."""
        now = datetime.now(timezone.utc)
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="New Story",
            tw_status=IssueStatus.NEW,
            project="test",
            annotations=[
                Annotation(
                    type=AnnotationType.COMMENT,
                    timestamp=now,
                    message="Some comment",
                ),
            ],
        )
        result = get_status_timestamp(issue)
        assert result is None

    def test_get_status_timestamp_done_returns_none(self) -> None:
        """For done issues, returns None regardless of annotations."""
        now = datetime.now(timezone.utc)
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="Done Story",
            tw_status=IssueStatus.DONE,
            project="test",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_END,
                    timestamp=now,
                    message="",
                ),
            ],
        )
        result = get_status_timestamp(issue)
        assert result is None

    def test_get_status_timestamp_no_annotations(self) -> None:
        """With no annotations, returns None."""
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="In Progress Story",
            tw_status=IssueStatus.IN_PROGRESS,
            project="test",
            annotations=[],
        )
        result = get_status_timestamp(issue)
        assert result is None

    def test_status_timestamp_filter(self) -> None:
        """Status timestamp filter returns formatted relative time."""
        now = datetime.now(timezone.utc)
        work_start = now - timedelta(hours=1)
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="In Progress Story",
            tw_status=IssueStatus.IN_PROGRESS,
            project="test",
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=work_start,
                    message="",
                ),
            ],
        )
        result = status_timestamp(issue)
        assert result == "1 hour ago"

    def test_status_timestamp_filter_none(self) -> None:
        """Status timestamp filter returns None when no timestamp."""
        issue = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.STORY,
            title="New Story",
            tw_status=IssueStatus.NEW,
            project="test",
        )
        result = status_timestamp(issue)
        assert result is None


class TestRenderDigest:
    def test_render_digest_single(self) -> None:
        """Render digest with parent and no children."""
        parent = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="User Authentication",
            tw_status=IssueStatus.NEW,
            project="myproject",
        )
        result = render_digest(parent, [])
        assert "PROJ-1" in result
        assert "epic" in result
        assert "User Authentication" in result
        assert "new" in result

    def test_render_digest_multiple(self) -> None:
        """Render digest with parent and children."""
        parent = Issue(
            uuid="abc-1",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="User Authentication",
            tw_status=IssueStatus.NEW,
            project="myproject",
        )
        children = [
            Issue(
                uuid="abc-2",
                tw_id="PROJ-1-1",
                tw_type=IssueType.STORY,
                title="Login Flow",
                tw_status=IssueStatus.IN_PROGRESS,
                project="myproject",
                tw_parent="PROJ-1",
            ),
        ]
        result = render_digest(parent, children)
        assert "PROJ-1" in result
        assert "PROJ-1-1" in result
        assert "User Authentication" in result
        assert "Login Flow" in result

    def test_render_digest_with_parent(self) -> None:
        """Digest shows parent info correctly."""
        parent = Issue(
            uuid="abc-123",
            tw_id="PROJ-1-1",
            tw_type=IssueType.STORY,
            title="Login Flow",
            tw_status=IssueStatus.IN_PROGRESS,
            project="myproject",
            tw_parent="PROJ-1",
        )
        result = render_digest(parent, [])
        assert "PROJ-1-1" in result
        assert "PROJ-1" in result


class TestRenderGroomContent:
    def test_render_single_bug(self) -> None:
        """Render single bug for groom editor."""
        issues = [
            Issue(
                uuid="uuid1",
                tw_id="TEST-5",
                tw_type=IssueType.BUG,
                title="Login broken",
                tw_status=IssueStatus.NEW,
                project="test",
                tw_body="The form crashes.\n---\nDetails here.",
            )
        ]

        content = render_groom_content(issues)

        assert "# TEST-5 (bug)" in content
        assert "- bug: Login broken" in content
        assert "    The form crashes." in content
        assert "    ---" in content
        assert "    Details here." in content

    def test_render_multiple_items(self) -> None:
        """Render multiple items (bug and idea) for groom editor."""
        issues = [
            Issue(
                uuid="uuid1",
                tw_id="TEST-1",
                tw_type=IssueType.BUG,
                title="Bug one",
                tw_status=IssueStatus.NEW,
                project="test",
            ),
            Issue(
                uuid="uuid2",
                tw_id="TEST-2",
                tw_type=IssueType.IDEA,
                title="Idea one",
                tw_status=IssueStatus.NEW,
                project="test",
                tw_body="Some description.",
            ),
        ]

        content = render_groom_content(issues)

        assert "# TEST-1 (bug)" in content
        assert "- bug: Bug one" in content
        assert "# TEST-2 (idea)" in content
        assert "- idea: Idea one" in content
        assert "    Some description." in content


class TestParseGroomResult:
    def test_unchanged_item(self) -> None:
        """Item left as-is should be marked unchanged."""
        from tw.render import parse_groom_result

        content = """# TEST-1 (bug)
- bug: original title
    original body
"""
        original_ids = ["TEST-1"]

        actions = parse_groom_result(content, original_ids)

        assert len(actions) == 1
        assert actions[0].original_id == "TEST-1"
        assert actions[0].action == "unchanged"

    def test_removed_item(self) -> None:
        """Item removed from content should be marked resolved."""
        from tw.render import parse_groom_result

        content = """# Some comment
"""
        original_ids = ["TEST-1", "TEST-2"]

        actions = parse_groom_result(content, original_ids)

        resolved = [a for a in actions if a.action == "resolve"]
        assert len(resolved) == 2

    def test_transformed_item(self) -> None:
        """Item changed to different type should create new + resolve old."""
        from tw.render import parse_groom_result

        content = """# TEST-1 (bug)
- task: fix the bug
    New description.
"""
        original_ids = ["TEST-1"]

        actions = parse_groom_result(content, original_ids)

        resolve_actions = [a for a in actions if a.action == "resolve"]
        create_actions = [a for a in actions if a.action == "create"]

        assert len(resolve_actions) == 1
        assert resolve_actions[0].original_id == "TEST-1"
        assert len(create_actions) == 1
        assert create_actions[0].issue_type == "task"
        assert create_actions[0].title == "fix the bug"

    def test_new_item_no_comment(self) -> None:
        """Item without # comment is new."""
        from tw.render import parse_groom_result

        content = """- epic: new epic
    Description.
"""
        original_ids = []

        actions = parse_groom_result(content, original_ids)

        assert len(actions) == 1
        assert actions[0].action == "create"
        assert actions[0].issue_type == "epic"
        assert actions[0].original_id is None


class TestRenderTreeWithBacklog:
    def test_renders_backlog_section(self) -> None:
        from tw.render import render_tree_with_backlog

        hierarchy = [
            Issue(
                uuid="u1",
                tw_id="TEST-1",
                tw_type=IssueType.EPIC,
                title="Epic One",
                tw_status=IssueStatus.NEW,
                project="test",
            )
        ]
        backlog = [
            Issue(
                uuid="u2",
                tw_id="TEST-2",
                tw_type=IssueType.BUG,
                title="Bug One",
                tw_status=IssueStatus.NEW,
                project="test",
            )
        ]

        output = render_tree_with_backlog(hierarchy, backlog)

        assert "Epic One" in output
        assert "Backlog" in output
        assert "Bug One" in output

    def test_renders_empty_backlog(self) -> None:
        from tw.render import render_tree_with_backlog

        hierarchy = [
            Issue(
                uuid="u1",
                tw_id="TEST-1",
                tw_type=IssueType.EPIC,
                title="Epic One",
                tw_status=IssueStatus.NEW,
                project="test",
            )
        ]
        backlog = []

        output = render_tree_with_backlog(hierarchy, backlog)

        assert "Epic One" in output
        assert "Backlog" not in output

    def test_renders_only_backlog(self) -> None:
        from tw.render import render_tree_with_backlog

        hierarchy = []
        backlog = [
            Issue(
                uuid="u2",
                tw_id="TEST-2",
                tw_type=IssueType.BUG,
                title="Bug One",
                tw_status=IssueStatus.NEW,
                project="test",
            )
        ]

        output = render_tree_with_backlog(hierarchy, backlog)

        assert "Backlog" in output
        assert "Bug One" in output


class TestGenerateEditTemplate:
    def test_template_with_separator_preserves_sections(self) -> None:
        title = "Test Issue"
        body = "This is repeatable\n---\nThis is detail"

        template = generate_edit_template(title, body)

        assert "Test Issue" in template
        assert "This is repeatable" in template
        assert "This is detail" in template
        assert template.count("---") == 1
        assert not template.strip().startswith("---")

    def test_template_without_separator_adds_one(self) -> None:
        title = "Test Issue"
        body = "Simple body"

        template = generate_edit_template(title, body)

        assert "Test Issue" in template
        assert "Simple body" in template
        assert "---" in template
        assert template.count("---") == 1
        assert not template.strip().startswith("---")

    def test_template_with_none_body_adds_separator(self) -> None:
        title = "Test Issue"
        body = None

        template = generate_edit_template(title, body)

        assert "Test Issue" in template
        assert "---" in template
        assert template.count("---") == 1

    def test_template_includes_instruction_comments(self) -> None:
        title = "Test Issue"
        body = "Some body"

        template = generate_edit_template(title, body)

        assert "# tw:" in template
        assert "Enter the issue title" in template
        assert "brief summary above the separator" in template
        assert "implementation details below" in template

    def test_template_preserves_multiline_sections(self) -> None:
        title = "Multi-line Test"
        body = "Line 1\nLine 2\nLine 3\n---\nDetail 1\nDetail 2"

        template = generate_edit_template(title, body)

        assert "Line 1\nLine 2\nLine 3" in template
        assert "Detail 1\nDetail 2" in template
        assert template.count("---") == 1

    def test_template_with_empty_string_body(self) -> None:
        title = "Empty Body Test"
        body = ""

        template = generate_edit_template(title, body)

        assert "Empty Body Test" in template
        assert "---" in template

    def test_template_first_line_is_title(self) -> None:
        title = "Title Line"
        body = "Body content"

        template = generate_edit_template(title, body)

        lines = template.split("\n")
        assert lines[0] == "Title Line"


class TestParseEditedContent:
    def test_parse_simple_title_only(self) -> None:
        content = "Just a title"

        title, body = parse_edited_content(content)

        assert title == "Just a title"
        assert body is None

    def test_parse_title_and_body(self) -> None:
        content = "Title Here\nBody content goes here"

        title, body = parse_edited_content(content)

        assert title == "Title Here"
        assert body == "Body content goes here"

    def test_parse_ignores_tw_comments(self) -> None:
        content = """Title Here
# tw: This is a comment
Body content
# tw: Another comment
More body content"""

        title, body = parse_edited_content(content)

        assert title == "Title Here"
        assert body == "Body content\nMore body content"
        assert "# tw:" not in title
        assert "# tw:" not in (body or "")

    def test_parse_with_separator(self) -> None:
        content = """Title
Summary section
---
Details section"""

        title, body = parse_edited_content(content)

        assert title == "Title"
        assert body == "Summary section\n---\nDetails section"

    def test_parse_preserves_whitespace_in_body(self) -> None:
        content = """Title
Line 1

Line 3 with gap"""

        title, body = parse_edited_content(content)

        assert title == "Title"
        assert body == "Line 1\n\nLine 3 with gap"

    def test_parse_empty_content_raises_error(self) -> None:
        with pytest.raises(ValueError, match="Content cannot be empty"):
            parse_edited_content("")

    def test_parse_only_whitespace_raises_error(self) -> None:
        with pytest.raises(ValueError, match="Content cannot be empty"):
            parse_edited_content("   \n  \n  ")

    def test_parse_only_comments_raises_error(self) -> None:
        content = """# tw: Comment 1
# tw: Comment 2
# tw: Comment 3"""

        with pytest.raises(ValueError, match="Content cannot be empty"):
            parse_edited_content(content)

    def test_parse_title_with_empty_body_lines(self) -> None:
        content = """Title


"""

        title, body = parse_edited_content(content)

        assert title == "Title"
        assert body is None

    def test_parse_multiline_body_with_comments(self) -> None:
        content = """My Title
# tw: Enter the issue title on the first line above

This is repeatable
# tw: Enter a brief summary above the separator
# tw: This will be shown in context views for related issues
---
This is detail
# tw: Enter implementation details below
# tw: Lines starting with '# tw:' will be ignored"""

        title, body = parse_edited_content(content)

        assert title == "My Title"
        assert body == "This is repeatable\n---\nThis is detail"
        assert "# tw:" not in body

    def test_roundtrip_generate_and_parse(self) -> None:
        original_title = "Original Title"
        original_body = "Summary info\n---\nDetailed info"

        template = generate_edit_template(original_title, original_body)
        parsed_title, parsed_body = parse_edited_content(template)

        assert parsed_title == original_title
        assert parsed_body == original_body
