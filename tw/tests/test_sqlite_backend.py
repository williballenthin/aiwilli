"""Tests for SQLite backend."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tw.backend import SqliteBackend
from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType


class TestSqliteBackendCreation:
    """Test SqliteBackend class creation and initialization."""

    def test_creates_sqlite_backend_instance(self, temp_dir: Path) -> None:
        """Create a SqliteBackend instance."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        assert backend is not None

    def test_initializes_database_on_creation(self, temp_dir: Path) -> None:
        """Backend initializes the database automatically."""
        db_path = temp_dir / "test.db"
        SqliteBackend(db_path)
        assert db_path.exists()


class TestGetAllIssues:
    """Test get_all_issues() method."""

    def test_returns_empty_list_for_empty_database(self, temp_dir: Path) -> None:
        """Return empty list when database has no issues."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        issues = backend.get_all_issues()
        assert issues == []

    def test_returns_all_issues_for_project(self, temp_dir: Path) -> None:
        """Return all issues in a project."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue1 = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Epic 1",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        issue2 = Issue(
            id="TEST-2",
            type=IssueType.STORY,
            title="Story 1",
            status=IssueStatus.IN_PROGRESS,
            created_at=now,
            updated_at=now,
        )

        backend.save_issue(issue1)
        backend.save_issue(issue2)

        issues = backend.get_all_issues()
        assert len(issues) == 2
        assert issues[0].id == "TEST-1"
        assert issues[1].id == "TEST-2"

    def test_returns_all_issues_without_filtering(self, temp_dir: Path) -> None:
        """Return all issues without project filtering."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue1 = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Epic 1",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        issue2 = Issue(
            id="TEST-2",
            type=IssueType.EPIC,
            title="Epic 2",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )

        backend.save_issue(issue1)
        backend.save_issue(issue2)

        all_issues = backend.get_all_issues()
        assert len(all_issues) == 2
        assert {i.id for i in all_issues} == {"TEST-1", "TEST-2"}


class TestGetIssue:
    """Test get_issue() method."""

    def test_returns_none_for_nonexistent_issue(self, temp_dir: Path) -> None:
        """Return None when issue doesn't exist."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        issue = backend.get_issue("NONEXISTENT")
        assert issue is None

    def test_retrieves_single_issue_by_id(self, temp_dir: Path) -> None:
        """Retrieve a specific issue by ID."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        original = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Test Epic",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            body="Epic body\n---\nNon-repeatable",
        )
        backend.save_issue(original)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert retrieved.id == "TEST-1"
        assert retrieved.title == "Test Epic"
        assert retrieved.body == "Epic body\n---\nNon-repeatable"

    def test_retrieves_issue_with_annotations(self, temp_dir: Path) -> None:
        """Retrieve issue with all its annotations."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Test Task",
            status=IssueStatus.IN_PROGRESS,
            created_at=now,
            updated_at=now,
            annotations=[
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=now,
                    message="Important lesson",
                ),
                Annotation(
                    type=AnnotationType.COMMIT,
                    timestamp=now,
                    message="abc123 - Implement feature",
                ),
            ],
        )
        backend.save_issue(issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert len(retrieved.annotations) == 2
        assert retrieved.annotations[0].message == "Important lesson"
        assert retrieved.annotations[1].message == "abc123 - Implement feature"

    def test_preserves_timestamps(self, temp_dir: Path) -> None:
        """Preserve created_at and updated_at timestamps."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        created = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        updated = datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Test Task",
            status=IssueStatus.NEW,
            created_at=created,
            updated_at=updated,
        )
        backend.save_issue(issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert retrieved.created_at == created
        assert retrieved.updated_at == updated


class TestSaveIssue:
    """Test save_issue() method."""

    def test_saves_new_issue(self, temp_dir: Path) -> None:
        """Save a new issue to the database."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="New Epic",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert retrieved.title == "New Epic"

    def test_updates_existing_issue(self, temp_dir: Path) -> None:
        """Update an existing issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Original Title",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(issue)

        updated_issue = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Updated Title",
            status=IssueStatus.IN_PROGRESS,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(updated_issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert retrieved.title == "Updated Title"
        assert retrieved.status == IssueStatus.IN_PROGRESS

    def test_saves_issue_with_parent(self, temp_dir: Path) -> None:
        """Save issue with parent reference."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        parent = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Parent Epic",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(parent)

        child = Issue(
            id="TEST-1-1",
            type=IssueType.STORY,
            title="Child Story",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            parent="TEST-1",
        )
        backend.save_issue(child)

        retrieved = backend.get_issue("TEST-1-1")
        assert retrieved is not None
        assert retrieved.parent == "TEST-1"

    def test_saves_issue_with_body(self, temp_dir: Path) -> None:
        """Save issue with full body content."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.STORY,
            title="Story Title",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            body="Repeatable part\n---\nNon-repeatable part",
        )
        backend.save_issue(issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert retrieved.body == "Repeatable part\n---\nNon-repeatable part"

    def test_saves_issue_with_refs(self, temp_dir: Path) -> None:
        """Save issue with references."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        target1 = Issue(
            id="TEST-2",
            type=IssueType.EPIC,
            title="Target 1",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        target2 = Issue(
            id="TEST-3",
            type=IssueType.EPIC,
            title="Target 2",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(target1)
        backend.save_issue(target2)

        issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Task Title",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            refs=["TEST-2", "TEST-3"],
        )
        backend.save_issue(issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert sorted(retrieved.refs) == ["TEST-2", "TEST-3"]

    def test_annotations_only_inserted_on_new_issue(self, temp_dir: Path) -> None:
        """Annotations are only inserted when creating a new issue, not when updating."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        ann1 = Annotation(
            type=AnnotationType.LESSON,
            timestamp=now,
            message="Lesson 1",
        )

        issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Task Title",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            annotations=[ann1],
        )
        backend.save_issue(issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert len(retrieved.annotations) == 1
        assert retrieved.annotations[0].message == "Lesson 1"

        ann2 = Annotation(
            type=AnnotationType.COMMIT,
            timestamp=now,
            message="abc123 - Update feature",
        )

        updated_issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Updated Title",
            status=IssueStatus.IN_PROGRESS,
            created_at=now,
            updated_at=now,
            annotations=[ann2],
        )
        backend.save_issue(updated_issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert len(retrieved.annotations) == 1
        assert retrieved.annotations[0].message == "Lesson 1"
        assert retrieved.title == "Updated Title"


class TestDeleteIssue:
    """Test delete_issue() method."""

    def test_deletes_existing_issue(self, temp_dir: Path) -> None:
        """Delete an issue from the database."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="To Delete",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(issue)
        backend.delete_issue("TEST-1")

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is None

    def test_raises_error_when_deleting_nonexistent_issue(self, temp_dir: Path) -> None:
        """Raise KeyError when deleting non-existent issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)

        with pytest.raises(KeyError):
            backend.delete_issue("NONEXISTENT")

    def test_deletes_issue_annotations_on_cascade(self, temp_dir: Path) -> None:
        """Deleting issue also deletes its annotations."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Task with annotations",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            annotations=[
                Annotation(
                    type=AnnotationType.LESSON,
                    timestamp=now,
                    message="Lesson 1",
                )
            ],
        )
        backend.save_issue(issue)
        backend.delete_issue("TEST-1")

        # Verify issue is deleted
        retrieved = backend.get_issue("TEST-1")
        assert retrieved is None


class TestAddAnnotation:
    """Test add_annotation() method."""

    def test_adds_annotation_to_existing_issue(self, temp_dir: Path) -> None:
        """Add annotation to an existing issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Task Title",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(issue)

        annotation = Annotation(
            type=AnnotationType.LESSON,
            timestamp=now,
            message="Important lesson",
        )
        backend.add_annotation("TEST-1", annotation)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert len(retrieved.annotations) == 1
        assert retrieved.annotations[0].message == "Important lesson"

    def test_adds_multiple_annotations(self, temp_dir: Path) -> None:
        """Add multiple annotations to an issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.TASK,
            title="Task Title",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(issue)

        ann1 = Annotation(
            type=AnnotationType.LESSON,
            timestamp=now,
            message="Lesson 1",
        )
        ann2 = Annotation(
            type=AnnotationType.COMMIT,
            timestamp=now,
            message="abc123 - Feature",
        )

        backend.add_annotation("TEST-1", ann1)
        backend.add_annotation("TEST-1", ann2)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert len(retrieved.annotations) == 2
        assert retrieved.annotations[0].type == AnnotationType.LESSON
        assert retrieved.annotations[1].type == AnnotationType.COMMIT

    def test_raises_error_when_adding_to_nonexistent_issue(
        self, temp_dir: Path
    ) -> None:
        """Raise KeyError when adding annotation to non-existent issue."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        annotation = Annotation(
            type=AnnotationType.LESSON,
            timestamp=now,
            message="Lesson",
        )

        with pytest.raises(KeyError):
            backend.add_annotation("NONEXISTENT", annotation)


class TestGetAllIds:
    """Test get_all_ids() method."""

    def test_returns_empty_list_for_empty_project(self, temp_dir: Path) -> None:
        """Return empty list for project with no issues."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        ids = backend.get_all_ids()
        assert ids == []

    def test_returns_all_ids_for_project(self, temp_dir: Path) -> None:
        """Return all issue IDs in a project."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        for i in range(3):
            issue = Issue(
                id=f"TEST-{i+1}",
                type=IssueType.EPIC,
                title=f"Epic {i+1}",
                status=IssueStatus.NEW,
                created_at=now,
                updated_at=now,
            )
            backend.save_issue(issue)

        ids = backend.get_all_ids()
        assert sorted(ids) == ["TEST-1", "TEST-2", "TEST-3"]

    def test_returns_all_ids_without_filtering(self, temp_dir: Path) -> None:
        """Return all issue IDs without project filtering."""
        db_path = temp_dir / "test.db"
        backend = SqliteBackend(db_path)
        now = datetime.now(UTC)

        issue1 = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Epic 1",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        issue2 = Issue(
            id="TEST-2",
            type=IssueType.EPIC,
            title="Epic 2",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )

        backend.save_issue(issue1)
        backend.save_issue(issue2)

        all_ids = backend.get_all_ids()
        assert set(all_ids) == {"TEST-1", "TEST-2"}
