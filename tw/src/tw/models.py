"""Core data models for tw."""

from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class Issue:
    """An issue (epic, story, or task)."""

    id: str
    type: IssueType
    title: str
    status: IssueStatus
    created_at: datetime
    updated_at: datetime
    parent: str | None = None
    body: str | None = None
    refs: list[str] | None = None
    annotations: list[Annotation] | None = None

    def __post_init__(self) -> None:
        if self.refs is None:
            self.refs = []
        if self.annotations is None:
            self.annotations = []

    def get_repeatable_body(self) -> str:
        """Return the repeatable portion of the body (before ---)."""
        if self.body is None:
            return ""
        return self.body.partition("\n---\n")[0].strip()

    def get_nonrepeatable_body(self) -> str:
        """Return the non-repeatable portion of the body (after ---)."""
        if self.body is None:
            return ""
        return self.body.partition("\n---\n")[2].strip()

    def get_full_body(self) -> str | None:
        """Return the complete body."""
        return self.body
