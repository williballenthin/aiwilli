"""Tests for SQLite backend."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from tw.backend import SqliteBackend
from tw.models import Issue, IssueStatus, IssueType


@pytest.fixture
def backend(temp_dir: Path) -> SqliteBackend:
    """Provide a fresh SqliteBackend for testing."""
    db_path = temp_dir / "test.db"
    return SqliteBackend(db_path)


class TestBackendRefs:
    def test_refs_stored_in_join_table(self, backend: SqliteBackend) -> None:
        """Refs should be stored in issue_refs table, not as comma-separated."""
        now = datetime.now(UTC)

        target = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Target",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(target)

        source = Issue(
            id="TEST-2",
            type=IssueType.EPIC,
            title="Source",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            refs=["TEST-1"],
        )
        backend.save_issue(source)

        retrieved = backend.get_issue("TEST-2")
        assert retrieved is not None
        assert retrieved.refs == ["TEST-1"]

    def test_refs_reverse_lookup(self, backend: SqliteBackend) -> None:
        """Should be able to find issues that reference a given issue."""
        now = datetime.now(UTC)

        target = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Target",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(target)

        source1 = Issue(
            id="TEST-2",
            type=IssueType.EPIC,
            title="Source 1",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            refs=["TEST-1"],
        )
        backend.save_issue(source1)

        source2 = Issue(
            id="TEST-3",
            type=IssueType.EPIC,
            title="Source 2",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            refs=["TEST-1"],
        )
        backend.save_issue(source2)

        referencing = backend.get_issues_referencing("TEST-1")
        assert set(referencing) == {"TEST-2", "TEST-3"}

    def test_delete_issue_sets_ref_to_null(self, backend: SqliteBackend) -> None:
        """Deleting a referenced issue should set refs to NULL, not delete the row."""
        now = datetime.now(UTC)

        target = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Target",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(target)

        source = Issue(
            id="TEST-2",
            type=IssueType.EPIC,
            title="Source",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            refs=["TEST-1"],
        )
        backend.save_issue(source)

        backend.delete_issue("TEST-1")

        retrieved = backend.get_issue("TEST-2")
        assert retrieved is not None
        assert retrieved.refs == []

    def test_refs_to_nonexistent_issue_skipped(self, backend: SqliteBackend) -> None:
        """Refs to non-existent issues should be silently skipped."""
        now = datetime.now(UTC)

        source = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Source",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            refs=["TEST-999"],
        )
        backend.save_issue(source)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert retrieved.refs == []


class TestBackendBasics:
    def test_save_and_retrieve_issue(self, backend: SqliteBackend) -> None:
        """Basic save and retrieve should work without project parameter."""
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Test Epic",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(issue)

        retrieved = backend.get_issue("TEST-1")
        assert retrieved is not None
        assert retrieved.id == "TEST-1"
        assert retrieved.title == "Test Epic"

    def test_get_all_issues(self, backend: SqliteBackend) -> None:
        """get_all_issues should return all issues."""
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

        issues = backend.get_all_issues()
        assert len(issues) == 3

    def test_get_all_ids(self, backend: SqliteBackend) -> None:
        """get_all_ids should return all issue IDs."""
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
        assert set(ids) == {"TEST-1", "TEST-2", "TEST-3"}

    def test_delete_issue(self, backend: SqliteBackend) -> None:
        """delete_issue should remove the issue."""
        now = datetime.now(UTC)

        issue = Issue(
            id="TEST-1",
            type=IssueType.EPIC,
            title="Test Epic",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        backend.save_issue(issue)
        backend.delete_issue("TEST-1")

        assert backend.get_issue("TEST-1") is None

    def test_delete_nonexistent_issue_raises(self, backend: SqliteBackend) -> None:
        """delete_issue should raise KeyError for non-existent issue."""
        with pytest.raises(KeyError, match="not found"):
            backend.delete_issue("TEST-999")
