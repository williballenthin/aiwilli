"""Tests for core data models."""

from datetime import datetime

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

    def test_from_taskwarrior(self) -> None:
        """Parse TaskWarrior annotation format."""
        ann = Annotation.from_taskwarrior(
            entry="20240115T103000Z",
            description="[lesson] Key rotation is tricky",
        )
        assert ann.type == AnnotationType.LESSON
        assert ann.message == "Key rotation is tricky"
        assert ann.timestamp.year == 2024

    def test_from_taskwarrior_unknown_type(self) -> None:
        """Unknown types default to comment."""
        ann = Annotation.from_taskwarrior(
            entry="20240115T103000Z",
            description="Some random text",
        )
        assert ann.type == AnnotationType.COMMENT
        assert ann.message == "Some random text"

    def test_from_taskwarrior_unknown_type_with_prefix(self) -> None:
        """Unknown type prefixes are handled, message extracted correctly."""
        ann = Annotation.from_taskwarrior(
            entry="20240115T103000Z",
            description="[unknown-type] Some message",
        )
        assert ann.type == AnnotationType.COMMENT
        assert ann.message == "Some message"

    def test_to_taskwarrior(self) -> None:
        ts = datetime(2024, 1, 15, 10, 30, 0)
        ann = Annotation(
            type=AnnotationType.LESSON,
            timestamp=ts,
            message="Key rotation is tricky",
        )
        result = ann.to_taskwarrior()
        assert result["description"] == "[lesson] Key rotation is tricky"
        assert "entry" in result


class TestIssue:
    def test_create_minimal(self) -> None:
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="User Authentication",
            tw_status=IssueStatus.NEW,
            project="myproject",
        )
        assert issue.tw_id == "PROJ-1"
        assert issue.tw_type == IssueType.EPIC
        assert issue.title == "User Authentication"
        assert issue.tw_parent is None
        assert issue.tw_body is None
        assert issue.tw_refs == []
        assert issue.annotations == []

    def test_create_full(self) -> None:
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1-1a",
            tw_type=IssueType.TASK,
            title="Implement login",
            tw_status=IssueStatus.IN_PROGRESS,
            project="myproject",
            tw_parent="PROJ-1-1",
            tw_body="Summary here\n---\nDetails here",
            tw_refs=["PROJ-2", "PROJ-3"],
        )
        assert issue.tw_parent == "PROJ-1-1"
        assert issue.tw_body == "Summary here\n---\nDetails here"
        assert issue.tw_refs == ["PROJ-2", "PROJ-3"]

    def test_get_repeatable_body(self) -> None:
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="Auth",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_body="This is repeatable.\n---\nThis is not.",
        )
        assert issue.get_repeatable_body() == "This is repeatable."

    def test_get_repeatable_body_no_separator(self) -> None:
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="Auth",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_body="All of this is repeatable.",
        )
        assert issue.get_repeatable_body() == "All of this is repeatable."

    def test_get_repeatable_body_none(self) -> None:
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="Auth",
            tw_status=IssueStatus.NEW,
            project="myproject",
        )
        assert issue.get_repeatable_body() is None

    def test_get_full_body(self) -> None:
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="Auth",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_body="Repeatable.\n---\nDetails.",
        )
        assert issue.get_full_body() == "Repeatable.\n---\nDetails."
