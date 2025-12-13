"""Test IssueService with SqliteBackend to verify polymorphism."""

from pathlib import Path

import pytest

from tw.backend import SqliteBackend
from tw.models import AnnotationType, IssueStatus, IssueType
from tw.service import IssueService


class TestIssueServiceWithSqliteBackend:
    """Test IssueService polymorphism with SqliteBackend."""

    def test_create_issue(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for create_issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        tw_id = service.create_issue(
            issue_type=IssueType.EPIC,
            title="Test Epic",
        )

        assert tw_id == "TEST-1"
        issue = service.get_issue(tw_id)
        assert issue.title == "Test Epic"
        assert issue.status == IssueStatus.NEW

    def test_get_all_issues(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for get_all_issues."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic 1")
        service.create_issue(IssueType.EPIC, "Epic 2")

        issues = service.get_all_issues()
        assert len(issues) == 2

    def test_create_hierarchy(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for hierarchy creation."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        epic_id = service.create_issue(IssueType.EPIC, "Epic")
        story_id = service.create_issue(
            IssueType.STORY, "Story", parent_id=epic_id
        )
        task_id = service.create_issue(
            IssueType.TASK, "Task", parent_id=story_id
        )

        assert task_id == "TEST-1-1a"
        task = service.get_issue(task_id)
        assert task.parent == story_id

    def test_status_transitions(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for status transitions."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        task_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(task_id)

        issue = service.get_issue(task_id)
        assert issue.status == IssueStatus.IN_PROGRESS
        assert len(issue.annotations) > 0

    def test_update_issue(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for update_issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        task_id = service.create_issue(IssueType.TASK, "Original Title")
        service.update_issue(task_id, title="Updated Title")

        issue = service.get_issue(task_id)
        assert issue.title == "Updated Title"

    def test_delete_issue(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for delete_issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        task_id = service.create_issue(IssueType.TASK, "Task to Delete")
        service.delete_issue(task_id)

        try:
            service.get_issue(task_id)
            assert False, "Should have raised KeyError"
        except KeyError:
            pass

    def test_record_annotation(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for record_annotation."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        task_id = service.create_issue(IssueType.TASK, "Task")
        service.record_annotation(task_id, AnnotationType.LESSON, "Test lesson")

        issue = service.get_issue(task_id)
        assert len(issue.annotations) > 0
        assert any(a.type == AnnotationType.LESSON for a in issue.annotations)

    def test_get_issue_with_children(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for get_issue_with_children."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        epic_id = service.create_issue(IssueType.EPIC, "Epic")
        story_id = service.create_issue(
            IssueType.STORY, "Story", parent_id=epic_id
        )

        parent, children = service.get_issue_with_children(epic_id)
        assert parent.id == epic_id
        assert len(children) == 1
        assert children[0].id == story_id

    def test_promote_issue(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for promote_issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic")
        story_id = service.create_issue(
            IssueType.STORY, "Story", parent_id="TEST-1"
        )
        task_id = service.create_issue(
            IssueType.TASK, "Task", parent_id=story_id
        )

        new_id = service.promote_issue(task_id, target_type=IssueType.STORY)
        promoted = service.get_issue(new_id)
        assert promoted.type == IssueType.STORY
        with pytest.raises(KeyError):
            service.get_issue(task_id)

    def test_reparent_issue(self, temp_dir: Path) -> None:
        """IssueService should work with SqliteBackend for reparent_issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        service = IssueService(backend, prefix="TEST")

        epic1_id = service.create_issue(IssueType.EPIC, "Epic 1")
        epic2_id = service.create_issue(IssueType.EPIC, "Epic 2")
        story_id = service.create_issue(
            IssueType.STORY, "Story", parent_id=epic1_id
        )

        new_id = service.reparent_issue(story_id, epic2_id)
        reparented = service.get_issue(new_id)
        assert reparented.parent == epic2_id
        with pytest.raises(KeyError):
            service.get_issue(story_id)
