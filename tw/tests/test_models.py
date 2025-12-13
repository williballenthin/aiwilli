"""Tests for core data models."""

from datetime import UTC, datetime

from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType


def test_is_backlog_type() -> None:
    """is_backlog_type should return True for bug/idea, False for others."""
    from tw.models import is_backlog_type

    assert is_backlog_type(IssueType.BUG) is True
    assert is_backlog_type(IssueType.IDEA) is True
    assert is_backlog_type(IssueType.EPIC) is False
    assert is_backlog_type(IssueType.STORY) is False
    assert is_backlog_type(IssueType.TASK) is False


class TestIssueType:
    def test_values(self) -> None:
        assert IssueType.EPIC.value == "epic"
        assert IssueType.STORY.value == "story"
        assert IssueType.TASK.value == "task"

    def test_from_string(self) -> None:
        assert IssueType("epic") == IssueType.EPIC
        assert IssueType("story") == IssueType.STORY
        assert IssueType("task") == IssueType.TASK

    def test_issue_type_includes_backlog_types(self) -> None:
        """IssueType should include bug and idea for backlog items."""
        assert IssueType.BUG.value == "bug"
        assert IssueType.IDEA.value == "idea"


class TestIssueStatus:
    def test_values(self) -> None:
        assert IssueStatus.NEW.value == "new"
        assert IssueStatus.IN_PROGRESS.value == "in_progress"
        assert IssueStatus.STOPPED.value == "stopped"
        assert IssueStatus.BLOCKED.value == "blocked"
        assert IssueStatus.DONE.value == "done"


class TestAnnotationType:
    def test_values(self) -> None:
        assert AnnotationType.WORK_BEGIN.value == "work-begin"
        assert AnnotationType.WORK_END.value == "work-end"
        assert AnnotationType.LESSON.value == "lesson"
        assert AnnotationType.DEVIATION.value == "deviation"
        assert AnnotationType.COMMIT.value == "commit"
        assert AnnotationType.HANDOFF.value == "handoff"
        assert AnnotationType.BLOCKED.value == "blocked"
        assert AnnotationType.UNBLOCKED.value == "unblocked"
        assert AnnotationType.COMMENT.value == "comment"


class TestAnnotation:
    def test_create(self) -> None:
        ts = datetime(2024, 1, 15, 10, 30)
        ann = Annotation(
            type=AnnotationType.LESSON,
            timestamp=ts,
            message="Key rotation is tricky",
        )
        assert ann.type == AnnotationType.LESSON
        assert ann.timestamp == ts
        assert ann.message == "Key rotation is tricky"

    def test_render(self) -> None:
        ts = datetime(2024, 1, 15, 10, 30)
        ann = Annotation(
            type=AnnotationType.LESSON,
            timestamp=ts,
            message="Key rotation is tricky",
        )
        assert ann.render() == "[lesson] Key rotation is tricky"


class TestIssue:
    def test_create_minimal(self) -> None:
        from datetime import datetime
        now = datetime.now(UTC)
        issue = Issue(id="PROJ-1",
            type=IssueType.EPIC,
            title="User Authentication",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        assert issue.id == "PROJ-1"
        assert issue.type == IssueType.EPIC
        assert issue.title == "User Authentication"
        assert issue.parent is None
        assert issue.body is None
        assert issue.refs == []
        assert issue.annotations == []

    def test_create_full(self) -> None:
        from datetime import datetime
        now = datetime.now(UTC)
        issue = Issue(id="PROJ-1-1a",
            type=IssueType.TASK,
            title="Implement login",
            status=IssueStatus.IN_PROGRESS,
            created_at=now,
            updated_at=now,
            parent="PROJ-1-1",
            body="Summary here\n---\nDetails here",
            refs=["PROJ-2", "PROJ-3"],
        )
        assert issue.parent == "PROJ-1-1"
        assert issue.body == "Summary here\n---\nDetails here"
        assert issue.refs == ["PROJ-2", "PROJ-3"]

    def test_get_repeatable_body(self) -> None:
        from datetime import datetime
        now = datetime.now(UTC)
        issue = Issue(id="PROJ-1",
            type=IssueType.EPIC,
            title="Auth",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            body="This is repeatable.\n---\nThis is not.",
        )
        assert issue.get_repeatable_body() == "This is repeatable."

    def test_get_repeatable_body_no_separator(self) -> None:
        from datetime import datetime
        now = datetime.now(UTC)
        issue = Issue(id="PROJ-1",
            type=IssueType.EPIC,
            title="Auth",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            body="All of this is repeatable.",
        )
        assert issue.get_repeatable_body() == "All of this is repeatable."

    def test_get_repeatable_body_none(self) -> None:
        from datetime import datetime
        now = datetime.now(UTC)
        issue = Issue(id="PROJ-1",
            type=IssueType.EPIC,
            title="Auth",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        assert issue.get_repeatable_body() == ""

    def test_get_full_body(self) -> None:
        from datetime import datetime
        now = datetime.now(UTC)
        issue = Issue(id="PROJ-1",
            type=IssueType.EPIC,
            title="Auth",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            body="Repeatable.\n---\nDetails.",
        )
        assert issue.get_full_body() == "Repeatable.\n---\nDetails."
