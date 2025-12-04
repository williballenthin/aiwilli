"""TaskWarrior backend abstraction."""

import json
import logging
import subprocess
import uuid as uuid_module

from tw.models import Annotation, Issue, IssueStatus, IssueType

logger = logging.getLogger(__name__)


class TaskWarriorBackend:
    """Abstraction layer for TaskWarrior operations."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        """Initialize backend.

        Args:
            env: Environment variables for subprocess calls (for testing)
        """
        self._env = env

    def parse_export(self, json_str: str) -> list[Issue]:
        """Parse TaskWarrior export JSON into Issue objects.

        Args:
            json_str: JSON string from `task export`
        """
        data = json.loads(json_str)
        issues = []

        for item in data:
            if "tw_id" not in item:
                continue
            if item.get("status") == "deleted":
                continue

            annotations = []
            for ann_data in item.get("annotations", []):
                annotations.append(
                    Annotation.from_taskwarrior(
                        entry=ann_data["entry"],
                        description=ann_data["description"],
                    )
                )

            tw_refs_str = item.get("tw_refs", "")
            tw_refs = [r.strip() for r in tw_refs_str.split(",") if r.strip()]

            issue = Issue(
                uuid=item["uuid"],
                tw_id=item["tw_id"],
                tw_type=IssueType(item["tw_type"]),
                title=item["description"],
                tw_status=IssueStatus(item["tw_status"]),
                project=item["project"],
                tw_parent=item.get("tw_parent"),
                tw_body=item.get("tw_body"),
                tw_refs=tw_refs,
                annotations=annotations,
            )
            issues.append(issue)

        return issues

    def build_import_json(self, issue: Issue) -> str:
        """Build JSON for TaskWarrior import.

        Args:
            issue: The issue to serialize
        """
        data: dict[str, object] = {
            "uuid": issue.uuid,
            "description": issue.title,
            "project": issue.project,
            "tw_type": issue.tw_type.value,
            "tw_id": issue.tw_id,
            "tw_status": issue.tw_status.value,
        }

        if issue.tw_parent:
            data["tw_parent"] = issue.tw_parent

        if issue.tw_body:
            data["tw_body"] = issue.tw_body

        if issue.tw_refs:
            data["tw_refs"] = ",".join(issue.tw_refs)

        if issue.annotations:
            data["annotations"] = [ann.to_taskwarrior() for ann in issue.annotations]

        return json.dumps(data)

    def _run_task(self, args: list[str], input_data: str | None = None) -> str:
        """Run a task command and return stdout.

        Raises:
            RuntimeError: If the command fails.
        """
        cmd = ["task", "rc.confirmation=off", "rc.verbose=nothing"] + args
        logger.debug(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            env=self._env,
        )

        if result.returncode != 0 and "No matches" not in result.stderr:
            logger.error(f"task failed: {result.stderr}")
            raise RuntimeError(f"task command failed: {result.stderr}")

        return result.stdout

    def export_project(self, project: str) -> list[Issue]:
        """Export all issues for a project.

        Args:
            project: The project name to filter by
        """
        output = self._run_task([f"project:{project}", "export"])
        if not output.strip() or output.strip() == "[]":
            return []
        return self.parse_export(output)

    def get_all_ids(
        self, project: str, *, include_deleted: bool = False
    ) -> list[str]:
        """Get all tw_ids in a project.

        Args:
            project: The project name to filter by
            include_deleted: If True, include IDs of deleted issues
        """
        if include_deleted:
            output = self._run_task([f"project:{project}", "export"])
            if not output.strip() or output.strip() == "[]":
                return []
            data = json.loads(output)
            return [item["tw_id"] for item in data if "tw_id" in item]

        issues = self.export_project(project)
        return [issue.tw_id for issue in issues]

    def import_issue(self, issue: Issue) -> None:
        """Import or update an issue.

        Args:
            issue: The issue to import
        """
        json_data = self.build_import_json(issue)
        self._run_task(["import"], input_data=json_data)

    def generate_uuid(self) -> str:
        """Generate a new UUID for an issue."""
        return str(uuid_module.uuid4())

    def delete_issue(self, uuid: str) -> None:
        """Delete an issue by UUID.

        Args:
            uuid: The UUID of the issue to delete

        Raises:
            RuntimeError: If the delete command fails.
        """
        self._run_task([uuid, "delete"])
