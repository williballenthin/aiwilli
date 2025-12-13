"""Tests for Jinja template rendering."""

from datetime import UTC, datetime, timedelta

import pytest

from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType
from tw.render import (
    generate_edit_template,
    get_status_timestamp,
    parse_edited_content,
    parse_groom_result,
    relative_time,
    render_brief,
    render_digest,
    render_groom_content,
    render_tree,
    render_view,
    status_timestamp,
)


class TestRelativeTime:
    def test_relative_time_just_now(self) -> None:
        """Test relative time for very recent timestamps."""
        now = datetime.now(UTC)
        recent = now - timedelta(seconds=30)
        assert relative_time(recent) == "just now"

    def test_relative_time_minutes(self) -> None:
        """Test relative time for minutes ago."""
        from datetime import datetime
        now = datetime.now(UTC)
        five_min_ago = now - timedelta(minutes=5)
        assert relative_time(five_min_ago) == "5 minutes ago"
        one_min_ago = now - timedelta(minutes=1)
        assert relative_time(one_min_ago) == "1 minute ago"

    def test_relative_time_hours(self) -> None:
        """Test relative time for hours ago."""
        now = datetime.now(UTC)
        three_hours_ago = now - timedelta(hours=3)
        assert relative_time(three_hours_ago) == "3 hours ago"
        one_hour_ago = now - timedelta(hours=1)
        assert relative_time(one_hour_ago) == "1 hour ago"

    def test_relative_time_days(self) -> None:
        """Test relative time for days ago."""
        from datetime import datetime
        now = datetime.now(UTC)
        two_days_ago = now - timedelta(days=2)
        assert relative_time(two_days_ago) == "2 days ago"
        one_day_ago = now - timedelta(days=1)
        assert relative_time(one_day_ago) == "1 day ago"

    def test_relative_time_weeks(self) -> None:
        """Test relative time for weeks ago."""
        now = datetime.now(UTC)
        two_weeks_ago = now - timedelta(weeks=2)
        assert relative_time(two_weeks_ago) == "2 weeks ago"
        one_week_ago = now - timedelta(weeks=1)
        assert relative_time(one_week_ago) == "1 week ago"

    def test_relative_time_months(self) -> None:
        """Test relative time for months ago."""
        from datetime import datetime
        now = datetime.now(UTC)
        two_months_ago = now - timedelta(days=60)
        assert relative_time(two_months_ago) == "2 months ago"
        one_month_ago = now - timedelta(days=31)
        assert relative_time(one_month_ago) == "1 month ago"

    def test_relative_time_years(self) -> None:
        """Test relative time for years ago."""
        now = datetime.now(UTC)
        two_years_ago = now - timedelta(days=730)
        assert relative_time(two_years_ago) == "2 years ago"
        one_year_ago = now - timedelta(days=365)
        assert relative_time(one_year_ago) == "1 year ago"


class TestRenderView:
    def test_render_view_minimal(self) -> None:
        """Render single issue with minimal fields."""
        from datetime import datetime
        issue = Issue(
            id="PROJ-1",
            type=IssueType.EPIC,
            title="User Authentication",
            status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "PROJ-1" in result
        assert "epic" in result
        assert "User Authentication" in result
        assert "new" in result

    def test_render_view_with_parent(self) -> None:
        """Render issue with parent reference."""
        issue = Issue(
            id="PROJ-1-1",
            type=IssueType.STORY,
            title="Login Flow",
            status=IssueStatus.IN_PROGRESS,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "PROJ-1-1" in result
        assert "Login Flow" in result
        assert "[green]open[/green]" in result

    def test_render_view_with_body(self) -> None:
        """Render issue with body text."""
        from datetime import datetime
        issue = Issue(
            id="PROJ-1",
            type=IssueType.TASK,
            title="Implement OAuth",
            status=IssueStatus.NEW,
            body="Add OAuth 2.0 support\n---\nMore details here",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "Implement OAuth" in result
        assert "Add OAuth 2.0 support" in result

    def test_render_view_with_refs(self) -> None:
        """Render issue with references shows refs in properties line."""
        ref1 = Issue(
            id="PROJ-2",
            type=IssueType.EPIC,
            title="Ref Issue 1",
            status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        ref2 = Issue(
            id="PROJ-3",
            type=IssueType.EPIC,
            title="Ref Issue 2",
            status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        issue = Issue(
            id="PROJ-1",
            type=IssueType.EPIC,
            title="User Authentication",
            status=IssueStatus.NEW,
            refs=["PROJ-2", "PROJ-3"],

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue, referenced=[ref1, ref2])
        assert "PROJ-2" in result
        assert "PROJ-3" in result

    def test_render_view_with_annotations(self) -> None:
        """Render issue with annotations (excluding system annotations)."""
        from datetime import datetime
        issue = Issue(
            id="PROJ-1",
            type=IssueType.TASK,
            title="Implement OAuth",
            status=IssueStatus.IN_PROGRESS,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC,
        ),
                    message="Starting work on OAuth implementation",
                ),
                Annotation(
                    type=AnnotationType.COMMIT,
                    timestamp=datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC),
                    message="Added OAuth client configuration",
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "work-begin" not in result
        assert "commit:" in result
        assert "Added OAuth client configuration" in result

    def test_render_view_stopped_with_handoff(self) -> None:
        """Render stopped issue with handoff annotation prominently displayed."""
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="User Profile Page",
            status=IssueStatus.STOPPED,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC,
        ),
                    message="Starting profile work",
                ),
                Annotation(
                    type=AnnotationType.HANDOFF,
                    timestamp=datetime(2024, 1, 15, 16, 0, 0, tzinfo=UTC),
                    message="Need to wait for API endpoint deployment before continuing",
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "HANDOFF:" in result
        assert "Need to wait for API endpoint deployment before continuing" in result
        lines = result.split("\n")
        handoff_line = next(i for i, line in enumerate(lines) if "HANDOFF:" in line)
        props_line = next(i for i, line in enumerate(lines) if "stopped" in line)
        assert handoff_line > props_line

    def test_render_view_filters_work_begin_end_annotations(self) -> None:
        """Work-begin and work-end annotations should not appear in rendered view."""
        from datetime import datetime
        issue = Issue(
            id="PROJ-1",
            type=IssueType.TASK,
            title="Task with system annotations",
            status=IssueStatus.DONE,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC,
        ),
                    message="",
                ),
                Annotation(
                    type=AnnotationType.COMMIT,
                    timestamp=datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC),
                    message="abc123 - Implemented feature",
                ),
                Annotation(
                    type=AnnotationType.WORK_END,
                    timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                    message="",
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "work-begin" not in result
        assert "work-end" not in result
        assert "commit:" in result
        assert "abc123 - Implemented feature" in result

    def test_render_view_filters_empty_annotations(self) -> None:
        """Annotations with empty messages should not appear in rendered view."""
        issue = Issue(
            id="PROJ-1",
            type=IssueType.TASK,
            title="Task with empty annotations",
            status=IssueStatus.IN_PROGRESS,
            annotations=[
                Annotation(
                    type=AnnotationType.COMMENT,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC,
        ),
                    message="",
                ),
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC),
                    message="    ",
                ),
                Annotation(
                    type=AnnotationType.DEVIATION,
                    timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                    message="Changed approach to use Redis",
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "comment:" not in result
        assert "lesson:" not in result
        assert "deviation:" in result
        assert "Changed approach to use Redis" in result

    def test_render_view_no_annotation_section_when_all_filtered(self) -> None:
        """Annotations section should not appear when all annotations are filtered."""
        from datetime import datetime
        issue = Issue(
            id="PROJ-1",
            type=IssueType.TASK,
            title="Task with only system annotations",
            status=IssueStatus.DONE,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC,
        ),
                    message="",
                ),
                Annotation(
                    type=AnnotationType.WORK_END,
                    timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
                    message="",
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "work-begin" not in result
        assert "work-end" not in result

    def test_render_view_shows_first_line_of_multiline_annotation_in_summary(self) -> None:
        """Short annotation summary shows only first line, full details in expanded section."""
        issue = Issue(
            id="PROJ-1",
            type=IssueType.TASK,
            title="Task with multiline annotation",
            status=IssueStatus.IN_PROGRESS,
            annotations=[
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC,
        ),
                    message="First line is important\nSecond line has details\nThird line has more",
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue)
        assert "First line is important" in result
        lines = result.split("\n")
        short_ann_found = False
        for line in lines:
            if "lesson:" in line and "First line is important" in line:
                if "Second line" not in line:
                    short_ann_found = True
                    break
        assert short_ann_found, "Short annotation should show only first line"

    def test_render_view_siblings_with_compact_format(self) -> None:
        """Siblings should be rendered with compact format showing status and type."""
        from datetime import datetime
        sibling1 = Issue(
            id="PROJ-1-1",
            type=IssueType.TASK,
            title="Sibling Task 1",
            status=IssueStatus.DONE,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        sibling2 = Issue(
            id="PROJ-1-2",
            type=IssueType.TASK,
            title="Sibling Task 2",
            status=IssueStatus.IN_PROGRESS,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        issue = Issue(
            id="PROJ-1-3",
            type=IssueType.TASK,
            title="Current Task",
            status=IssueStatus.NEW,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue, siblings=[sibling1, sibling2])
        assert "sibling:" in result
        assert "PROJ-1-1" in result
        assert "PROJ-1-2" in result
        assert "Sibling Task 1" in result
        assert "Sibling Task 2" in result
        assert "done" in result
        assert "open" in result

    def test_render_view_siblings_show_in_short_links(self) -> None:
        """Siblings are shown in the short links section."""
        sibling = Issue(
            id="PROJ-1-1",
            type=IssueType.STORY,
            title="Sibling Story",
            status=IssueStatus.DONE,
            parent="PROJ-1",
            body=(
                "This is repeatable context\nWith multiple lines\n---\n"
                "This is non-repeatable detail"
            ),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        issue = Issue(
            id="PROJ-1-2",
            type=IssueType.STORY,
            title="Current Story",
            status=IssueStatus.NEW,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue, siblings=[sibling])
        assert "sibling:" in result
        assert "Sibling Story" in result
        assert "This is non-repeatable detail" not in result

    def test_render_view_siblings_shown_in_links(self) -> None:
        """Siblings are shown in the short links section."""
        from datetime import datetime
        now = datetime.now(UTC)
        sibling = Issue(
            id="PROJ-1-1",
            type=IssueType.TASK,
            title="Sibling Task",
            status=IssueStatus.DONE,
            parent="PROJ-1",
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
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        issue = Issue(
            id="PROJ-1-2",
            type=IssueType.TASK,
            title="Current Task",
            status=IssueStatus.NEW,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_view(issue, siblings=[sibling])
        assert "sibling:" in result
        assert "Sibling Task" in result

    def test_render_view_shows_lessons_from_completed_siblings(self) -> None:
        """render_view should show short links to siblings but not their lessons."""
        from datetime import datetime
        now = datetime.now(UTC)
        completed_sibling = Issue(
            id="PROJ-1-1",
            type=IssueType.TASK,
            title="Completed Sibling Task",
            status=IssueStatus.DONE,
            parent="PROJ-1",
            annotations=[
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=now,
                    message="OAuth requires async handlers",
                ),
                Annotation(
                    type=AnnotationType.DEVIATION,
                    timestamp=now,
                    message="Changed from JWT to session-based auth",
                ),
            ],
            created_at=now,
            updated_at=now,
        )
        in_progress_sibling = Issue(
            id="PROJ-1-2",
            type=IssueType.TASK,
            title="In Progress Sibling",
            status=IssueStatus.IN_PROGRESS,
            parent="PROJ-1",
            annotations=[
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=now,
                    message="This should not appear - not done yet",
                ),
            ],
            created_at=now,
            updated_at=now,
        )
        current_task = Issue(
            id="PROJ-1-3",
            type=IssueType.TASK,
            title="Current Task",
            status=IssueStatus.NEW,
            parent="PROJ-1",
            created_at=now,
            updated_at=now,
        )
        result = render_view(
            current_task, siblings=[completed_sibling, in_progress_sibling]
        )
        assert "Lessons from Siblings" not in result
        assert "PROJ-1-1" in result
        assert "PROJ-1-2" in result
        assert "OAuth requires async handlers" not in result
        assert "Changed from JWT to session-based auth" not in result
        assert "This should not appear" not in result


class TestRenderTree:
    def test_render_tree_single(self) -> None:
        """Render tree with single issue."""
        issues = [
            Issue(
                id="PROJ-1",
                type=IssueType.EPIC,
                title="User Authentication",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        ]
        result = render_tree(issues)
        assert "PROJ-1" in result
        assert "User Authentication" in result

    def test_render_tree_multiple(self) -> None:
        """Render tree with multiple issues."""
        from datetime import datetime
        issues = [
            Issue(
                id="PROJ-1",
                type=IssueType.EPIC,
                title="User Authentication",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
            Issue(
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="Login Flow",
                status=IssueStatus.IN_PROGRESS,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
            Issue(
                id="PROJ-2",
                type=IssueType.EPIC,
                title="Data Layer",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="Orphan Story",
                status=IssueStatus.NEW,
            parent=None,

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        from datetime import datetime
        issues = [
            Issue(
                id="PROJ-1-1a",
                type=IssueType.TASK,
                title="Orphan Task",
                status=IssueStatus.NEW,
            parent=None,

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="Parent Story",
                status=IssueStatus.NEW,
            parent=None,

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
            Issue(
                id="PROJ-1-1a",
                type=IssueType.TASK,
                title="Child Task",
                status=IssueStatus.NEW,
            parent="PROJ-1-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        from datetime import datetime
        issues = [
            Issue(
                id="PROJ-1",
                type=IssueType.EPIC,
                title="Epic",
                status=IssueStatus.NEW,
            parent=None,

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
            Issue(
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="Story under Epic",
                status=IssueStatus.NEW,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
            Issue(
                id="PROJ-1-1a",
                type=IssueType.TASK,
                title="Task under Story",
                status=IssueStatus.NEW,
            parent="PROJ-1-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        """Task with annotations shows non-work-begin/work-end annotations."""
        now = datetime.now(UTC)
        issues = [
            Issue(
                id="PROJ-1-1a",
                type=IssueType.TASK,
                title="Task with annotations",
                status=IssueStatus.IN_PROGRESS,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
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
        from datetime import datetime
        now = datetime.now(UTC)
        issues = [
            Issue(
                id="PROJ-1-1a",
                type=IssueType.TASK,
                title="Task with multiline annotation",
                status=IssueStatus.IN_PROGRESS,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                annotations=[
                    Annotation(
                        type=AnnotationType.HANDOFF,
                        timestamp=now - timedelta(hours=1),
                        message=(
                            "First line of message\nSecond line should not appear\n"
                            "Third line also hidden"
                        ),
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
                id="PROJ-1",
                type=IssueType.EPIC,
                title="Completed Epic",
                status=IssueStatus.DONE,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        from datetime import datetime
        issues = [
            Issue(
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="In Progress Story",
                status=IssueStatus.IN_PROGRESS,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
                id="PROJ-2-1",
                type=IssueType.STORY,
                title="Blocked Story",
                status=IssueStatus.BLOCKED,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        ]
        result = render_tree(issues)
        lines = [line for line in result.strip().split("\n") if line.strip()]
        assert len(lines) == 1
        # Check format: (ID, status) with ID blue and status red
        assert "[blue]PROJ-2-1[/blue][gray69], [/gray69][red]blocked[/red]" in lines[0]

    def test_render_tree_stopped_status_in_parens(self) -> None:
        """Stopped issues should show status in parentheses with ID in red."""
        from datetime import datetime
        issues = [
            Issue(
                id="PROJ-3-1",
                type=IssueType.STORY,
                title="Stopped Story",
                status=IssueStatus.STOPPED,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
                id="PROJ-4-1",
                type=IssueType.STORY,
                title="New Story",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        from datetime import datetime
        now = datetime.now(UTC)
        work_start = now - timedelta(hours=2)
        issues = [
            Issue(
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="In Progress with Start Time",
                status=IssueStatus.IN_PROGRESS,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
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
        now = datetime.now(UTC)
        blocked_time = now - timedelta(hours=1)
        issues = [
            Issue(
                id="PROJ-2-1",
                type=IssueType.STORY,
                title="Blocked Story",
                status=IssueStatus.BLOCKED,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
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
        from datetime import datetime
        now = datetime.now(UTC)
        work_start = now - timedelta(hours=3)
        issues = [
            Issue(
                id="PROJ-3-1",
                type=IssueType.STORY,
                title="Stopped Story",
                status=IssueStatus.STOPPED,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
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
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="In Progress without Start",
                status=IssueStatus.IN_PROGRESS,
            annotations=[],

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
        from datetime import datetime
        issues = [
            Issue(
                id="PROJ-2-1",
                type=IssueType.STORY,
                title="Blocked Story",
                status=IssueStatus.BLOCKED,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                annotations=[
                    Annotation(
                        type=AnnotationType.COMMENT,
                        timestamp=datetime.now(UTC),
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
        now = datetime.now(UTC)
        blocked_time = now - timedelta(hours=1)
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="Blocked Story",
            status=IssueStatus.BLOCKED,
            annotations=[
                Annotation(
                    type=AnnotationType.BLOCKED,
                    timestamp=blocked_time,
                    message="Blocked reason",

        ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = get_status_timestamp(issue)
        assert result == blocked_time

    def test_get_status_timestamp_in_progress(self) -> None:
        """For in_progress issues, returns WORK_BEGIN annotation timestamp."""
        from datetime import datetime
        now = datetime.now(UTC)
        work_start = now - timedelta(hours=2)
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="In Progress Story",
            status=IssueStatus.IN_PROGRESS,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=work_start,
                    message="",

        ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = get_status_timestamp(issue)
        assert result == work_start

    def test_get_status_timestamp_stopped(self) -> None:
        """For stopped issues, returns WORK_BEGIN annotation timestamp."""
        now = datetime.now(UTC)
        work_start = now - timedelta(hours=3)
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="Stopped Story",
            status=IssueStatus.STOPPED,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=work_start,
                    message="",

        ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = get_status_timestamp(issue)
        assert result == work_start

    def test_get_status_timestamp_new_returns_none(self) -> None:
        """For new issues, returns None regardless of annotations."""
        from datetime import datetime
        now = datetime.now(UTC)
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="New Story",
            status=IssueStatus.NEW,
            annotations=[
                Annotation(
                    type=AnnotationType.COMMENT,
                    timestamp=now,
                    message="Some comment",

        ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = get_status_timestamp(issue)
        assert result is None

    def test_get_status_timestamp_done_returns_none(self) -> None:
        """For done issues, returns None regardless of annotations."""
        now = datetime.now(UTC)
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="Done Story",
            status=IssueStatus.DONE,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_END,
                    timestamp=now,
                    message="",

        ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = get_status_timestamp(issue)
        assert result is None

    def test_get_status_timestamp_no_annotations(self) -> None:
        """With no annotations, returns None."""
        from datetime import datetime
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="In Progress Story",
            status=IssueStatus.IN_PROGRESS,
            annotations=[],

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = get_status_timestamp(issue)
        assert result is None

    def test_status_timestamp_filter(self) -> None:
        """Status timestamp filter returns formatted relative time."""
        now = datetime.now(UTC)
        work_start = now - timedelta(hours=1)
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="In Progress Story",
            status=IssueStatus.IN_PROGRESS,
            annotations=[
                Annotation(
                    type=AnnotationType.WORK_BEGIN,
                    timestamp=work_start,
                    message="",

        ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = status_timestamp(issue)
        assert result == "1 hour ago"

    def test_status_timestamp_filter_none(self) -> None:
        """Status timestamp filter returns None when no timestamp."""
        from datetime import datetime
        issue = Issue(
            id="PROJ-1",
            type=IssueType.STORY,
            title="New Story",
            status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = status_timestamp(issue)
        assert result is None


class TestRenderDigest:
    def test_render_digest_single(self) -> None:
        """Render digest with parent and no children."""
        parent = Issue(
            id="PROJ-1",
            type=IssueType.EPIC,
            title="User Authentication",
            status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_digest(parent, [])
        assert "PROJ-1" in result
        assert "epic" in result
        assert "User Authentication" in result
        assert "new" in result

    def test_render_digest_multiple(self) -> None:
        """Render digest with parent and children."""
        from datetime import datetime
        parent = Issue(
            id="PROJ-1",
            type=IssueType.EPIC,
            title="User Authentication",
            status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        children = [
            Issue(
                id="PROJ-1-1",
                type=IssueType.STORY,
                title="Login Flow",
                status=IssueStatus.IN_PROGRESS,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
            id="PROJ-1-1",
            type=IssueType.STORY,
            title="Login Flow",
            status=IssueStatus.IN_PROGRESS,
            parent="PROJ-1",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        result = render_digest(parent, [])
        assert "PROJ-1-1" in result
        assert "PROJ-1" in result


class TestRenderGroomContent:
    def test_render_single_bug(self) -> None:
        """Render single bug for groom editor."""
        from datetime import datetime
        issues = [
            Issue(
                id="TEST-5",
                type=IssueType.BUG,
                title="Login broken",
                status=IssueStatus.NEW,
            body="The form crashes.\n---\nDetails here.",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
                id="TEST-1",
                type=IssueType.BUG,
                title="Bug one",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
            Issue(
                id="TEST-2",
                type=IssueType.IDEA,
                title="Idea one",
                status=IssueStatus.NEW,
            body="Some description.",

            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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

        content = """# Some comment
"""
        original_ids = ["TEST-1", "TEST-2"]

        actions = parse_groom_result(content, original_ids)

        resolved = [a for a in actions if a.action == "resolve"]
        assert len(resolved) == 2

    def test_transformed_item(self) -> None:
        """Item changed to different type should create new + resolve old."""

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
                id="TEST-1",
                type=IssueType.EPIC,
                title="Epic One",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        ]
        backlog = [
            Issue(
                id="TEST-2",
                type=IssueType.BUG,
                title="Bug One",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
                id="TEST-1",
                type=IssueType.EPIC,
                title="Epic One",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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
                id="TEST-2",
                type=IssueType.BUG,
                title="Bug One",
                status=IssueStatus.NEW,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
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


class TestRenderBrief:
    def test_render_brief_basic(self) -> None:
        """Brief should include task title, status, and protocol."""
        now = datetime.now(UTC)
        task = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Implement login form",
            status=IssueStatus.NEW,
            body="Add a login form with email and password fields.",
            parent="PROJ-1-1",
            created_at=now,
            updated_at=now,
        )
        result = render_brief(task)
        assert "# Coder Brief: PROJ-1-1a" in result
        assert "Implement login form" in result
        assert "type: task | status: new" in result
        assert "Add a login form" in result
        assert "tw start PROJ-1-1a" in result
        assert "tw done PROJ-1-1a" in result
        assert "tw record PROJ-1-1a lesson" in result

    def test_render_brief_with_sibling_lessons(self) -> None:
        """Brief should prominently show lessons from completed siblings."""
        now = datetime.now(UTC)
        completed_sibling = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Setup database",
            status=IssueStatus.DONE,
            parent="PROJ-1-1",
            created_at=now,
            updated_at=now,
            annotations=[
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=now,
                    message="Use COALESCE for nullable columns",
                ),
                Annotation(
                    type=AnnotationType.DEVIATION,
                    timestamp=now,
                    message="Changed from JSON to JSONB",
                ),
            ],
        )
        current_task = Issue(
            id="PROJ-1-1b",
            type=IssueType.TASK,
            title="Implement queries",
            status=IssueStatus.NEW,
            parent="PROJ-1-1",
            created_at=now,
            updated_at=now,
        )
        result = render_brief(current_task, siblings=[completed_sibling])
        assert "## Lessons from Completed Siblings" in result
        assert "PROJ-1-1a" in result
        assert "Use COALESCE for nullable columns" in result
        assert "Changed from JSON to JSONB" in result
        assert "[lesson]" in result
        assert "[deviation]" in result

    def test_render_brief_with_ancestors(self) -> None:
        """Brief should include parent context."""
        now = datetime.now(UTC)
        epic = Issue(
            id="PROJ-1",
            type=IssueType.EPIC,
            title="Authentication System",
            status=IssueStatus.IN_PROGRESS,
            body="Build complete auth system.\n---\nDetailed specs here.",
            created_at=now,
            updated_at=now,
        )
        story = Issue(
            id="PROJ-1-1",
            type=IssueType.STORY,
            title="Login Flow",
            status=IssueStatus.IN_PROGRESS,
            body="Implement OAuth login.",
            parent="PROJ-1",
            created_at=now,
            updated_at=now,
        )
        task = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Add login button",
            status=IssueStatus.NEW,
            parent="PROJ-1-1",
            created_at=now,
            updated_at=now,
        )
        result = render_brief(task, ancestors=[story, epic])
        assert "## Parent Context" in result
        assert "PROJ-1-1" in result
        assert "Login Flow" in result
        assert "Implement OAuth login" in result
        assert "PROJ-1" in result
        assert "Build complete auth system" in result

    def test_render_brief_blocked_warning(self) -> None:
        """Brief should warn when task is blocked."""
        now = datetime.now(UTC)
        task = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Blocked task",
            status=IssueStatus.BLOCKED,
            created_at=now,
            updated_at=now,
            annotations=[
                Annotation(
                    type=AnnotationType.BLOCKED,
                    timestamp=now,
                    message="Waiting for API credentials",
                ),
            ],
        )
        result = render_brief(task)
        assert "WARNING: This task is BLOCKED" in result
        assert "Waiting for API credentials" in result
        assert "tw unblock PROJ-1-1a" in result

    def test_render_brief_stopped_with_handoff(self) -> None:
        """Brief should show handoff message for stopped tasks."""
        now = datetime.now(UTC)
        task = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Handed off task",
            status=IssueStatus.STOPPED,
            created_at=now,
            updated_at=now,
            annotations=[
                Annotation(
                    type=AnnotationType.HANDOFF,
                    timestamp=now,
                    message="Completed form layout, remaining: validation",
                ),
            ],
        )
        result = render_brief(task)
        assert "handed off" in result.lower()
        assert "HANDOFF:" in result
        assert "Completed form layout" in result

    def test_render_brief_workflow_section(self) -> None:
        """Brief should include workflow checklist."""
        now = datetime.now(UTC)
        task = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Test task",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        result = render_brief(task)
        assert "## Workflow" in result
        assert "1. `tw start PROJ-1-1a`" in result
        assert "Implement the task" in result
        assert "BEFORE completing" in result
        assert "mandatory" in result.lower()

    def test_render_brief_rules_section(self) -> None:
        """Brief should include rules for coders."""
        now = datetime.now(UTC)
        task = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Test task",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        result = render_brief(task)
        assert "## Rules" in result
        assert "Don't edit issues" in result
        assert "Record lessons before done" in result

    def test_render_brief_discovered_work_section(self) -> None:
        """Brief should include guidance for discovered work."""
        now = datetime.now(UTC)
        task = Issue(
            id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Test task",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        result = render_brief(task)
        assert "## Discovered Work" in result
        assert "tw new bug" in result
        assert "tw new idea" in result
        assert "Do NOT fix unrelated issues" in result
