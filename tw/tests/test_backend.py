"""Tests for TaskWarrior backend."""

import json
import shutil
from pathlib import Path

import pytest

from tw.backend import TaskWarriorBackend
from tw.models import Annotation, Issue, IssueStatus, IssueType


class TestTaskWarriorBackend:
    def test_parse_export_json(self, temp_dir: Path) -> None:
        """Parse TaskWarrior export JSON into Issue objects."""
        export_data = [
            {
                "uuid": "abc-123",
                "description": "User Authentication",
                "project": "myproject",
                "status": "pending",
                "tw_type": "epic",
                "tw_id": "PROJ-1",
                "tw_status": "new",
            },
            {
                "uuid": "def-456",
                "description": "Login Flow",
                "project": "myproject",
                "status": "pending",
                "tw_type": "story",
                "tw_id": "PROJ-1-1",
                "tw_parent": "PROJ-1",
                "tw_status": "in_progress",
                "tw_body": "Handle login\n---\nDetails",
            },
        ]

        backend = TaskWarriorBackend()
        issues = backend.parse_export(json.dumps(export_data))

        assert len(issues) == 2
        assert issues[0].tw_id == "PROJ-1"
        assert issues[0].tw_type == IssueType.EPIC
        assert issues[0].tw_status == IssueStatus.NEW
        assert issues[1].tw_parent == "PROJ-1"
        assert issues[1].tw_body == "Handle login\n---\nDetails"

    def test_parse_export_with_annotations(self) -> None:
        export_data = [
            {
                "uuid": "abc-123",
                "description": "Task",
                "project": "myproject",
                "status": "pending",
                "tw_type": "task",
                "tw_id": "PROJ-1-1a",
                "tw_status": "in_progress",
                "annotations": [
                    {
                        "entry": "20240115T103000Z",
                        "description": "[lesson] Important lesson",
                    }
                ],
            }
        ]

        backend = TaskWarriorBackend()
        issues = backend.parse_export(json.dumps(export_data))

        assert len(issues[0].annotations) == 1
        assert issues[0].annotations[0].message == "Important lesson"

    def test_build_import_json(self) -> None:
        """Build JSON for TaskWarrior import."""
        issue = Issue(
            uuid="abc-123",
            tw_id="PROJ-1",
            tw_type=IssueType.EPIC,
            title="User Auth",
            tw_status=IssueStatus.NEW,
            project="myproject",
            tw_body="Summary\n---\nDetails",
        )

        backend = TaskWarriorBackend()
        result = json.loads(backend.build_import_json(issue))

        assert result["uuid"] == "abc-123"
        assert result["description"] == "User Auth"
        assert result["tw_type"] == "epic"
        assert result["tw_id"] == "PROJ-1"
        assert result["tw_status"] == "new"
        assert result["tw_body"] == "Summary\n---\nDetails"


@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestTaskWarriorBackendIntegration:
    def test_export_project(self, taskwarrior_env: dict[str, str]) -> None:
        """Export issues for a project."""
        backend = TaskWarriorBackend(env=taskwarrior_env)

        # Initially empty
        issues = backend.export_project("testproj")
        assert issues == []

    def test_import_and_export(self, taskwarrior_env: dict[str, str]) -> None:
        """Import an issue and export it back."""
        backend = TaskWarriorBackend(env=taskwarrior_env)

        issue = Issue(
            uuid="11111111-1111-1111-1111-111111111111",
            tw_id="TEST-1",
            tw_type=IssueType.EPIC,
            title="Test Epic",
            tw_status=IssueStatus.NEW,
            project="testproj",
        )

        backend.import_issue(issue)
        issues = backend.export_project("testproj")

        assert len(issues) == 1
        assert issues[0].tw_id == "TEST-1"
        assert issues[0].title == "Test Epic"

    def test_export_all_ids(self, taskwarrior_env: dict[str, str]) -> None:
        """Get all tw_ids in a project."""
        backend = TaskWarriorBackend(env=taskwarrior_env)

        for i in range(3):
            issue = Issue(
                uuid=backend.generate_uuid(),
                tw_id=f"TEST-{i+1}",
                tw_type=IssueType.EPIC,
                title=f"Epic {i+1}",
                tw_status=IssueStatus.NEW,
                project="testproj",
            )
            backend.import_issue(issue)

        ids = backend.get_all_ids("testproj")
        assert sorted(ids) == ["TEST-1", "TEST-2", "TEST-3"]

    def test_get_all_ids_include_deleted(
        self, taskwarrior_env: dict[str, str]
    ) -> None:
        """include_deleted=True returns IDs of deleted issues."""
        backend = TaskWarriorBackend(env=taskwarrior_env)

        uuids = []
        for i in range(3):
            uuid = backend.generate_uuid()
            uuids.append(uuid)
            issue = Issue(
                uuid=uuid,
                tw_id=f"TEST-{i+1}",
                tw_type=IssueType.EPIC,
                title=f"Epic {i+1}",
                tw_status=IssueStatus.NEW,
                project="testproj",
            )
            backend.import_issue(issue)

        # Delete TEST-3
        backend.delete_issue(uuids[2])

        # Without include_deleted: excludes deleted
        ids = backend.get_all_ids("testproj")
        assert sorted(ids) == ["TEST-1", "TEST-2"]

        # With include_deleted: includes deleted
        ids_with_deleted = backend.get_all_ids("testproj", include_deleted=True)
        assert sorted(ids_with_deleted) == ["TEST-1", "TEST-2", "TEST-3"]
