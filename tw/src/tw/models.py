"""Core data models for tw."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class IssueType(str, Enum):
    """Type of issue in the hierarchy."""

    EPIC = "epic"
    STORY = "story"
    TASK = "task"
    BUG = "bug"
    IDEA = "idea"


def is_backlog_type(issue_type: IssueType) -> bool:
    """Return True if the issue type is a backlog type (bug or idea)."""
    return issue_type in (IssueType.BUG, IssueType.IDEA)


class IssueStatus(str, Enum):
    """Status of an issue."""

    NEW = "new"
    IN_PROGRESS = "in_progress"
    STOPPED = "stopped"
    BLOCKED = "blocked"
    DONE = "done"


class AnnotationType(str, Enum):
    """Type of annotation on an issue."""

    WORK_BEGIN = "work-begin"
    WORK_END = "work-end"
    LESSON = "lesson"
    DEVIATION = "deviation"
    COMMIT = "commit"
    HANDOFF = "handoff"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    COMMENT = "comment"


@dataclass
class Annotation:
    """An annotation on an issue."""

    type: AnnotationType
    timestamp: datetime
    message: str

    def render(self) -> str:
        """Render annotation for display."""
        return f"[{self.type.value}] {self.message}"

    @classmethod
    def from_taskwarrior(cls, entry: str, description: str) -> "Annotation":
        """Parse from TaskWarrior annotation format.

        Args:
            entry: ISO timestamp string (e.g., "20240115T103000Z")
            description: Annotation text, optionally with [type] prefix
        """
        timestamp = datetime.strptime(entry, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )

        match = re.match(r"^\[([a-z-]+)\]\s*(.*)$", description, re.DOTALL)
        if match:
            type_str, message = match.groups()
            try:
                ann_type = AnnotationType(type_str)
            except ValueError:
                ann_type = AnnotationType.COMMENT
        else:
            ann_type = AnnotationType.COMMENT
            message = description

        return cls(type=ann_type, timestamp=timestamp, message=message)

    def to_taskwarrior(self) -> dict[str, str]:
        """Convert to TaskWarrior annotation format."""
        return {
            "entry": self.timestamp.strftime("%Y%m%dT%H%M%SZ"),
            "description": self.render(),
        }


@dataclass
class Issue:
    """An issue (epic, story, or task)."""

    uuid: str
    tw_id: str
    tw_type: IssueType
    title: str
    tw_status: IssueStatus
    project: str
    tw_parent: str | None = None
    tw_body: str | None = None
    tw_refs: list[str] | None = None
    annotations: list[Annotation] | None = None

    def __post_init__(self) -> None:
        if self.tw_refs is None:
            self.tw_refs = []
        if self.annotations is None:
            self.annotations = []

    def get_repeatable_body(self) -> str | None:
        """Return the repeatable portion of the body (before ---)."""
        if self.tw_body is None:
            return None
        if "---" in self.tw_body:
            return self.tw_body.split("---")[0].strip()
        return self.tw_body.strip()

    def get_full_body(self) -> str | None:
        """Return the complete body."""
        return self.tw_body
