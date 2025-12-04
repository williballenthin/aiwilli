# tw Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Use Haiku for the implementing subagents.

**Goal:** Build a TaskWarrior-backed issue tracker CLI optimized for LLM agent workflows.

**Architecture:** Python CLI using Click for commands, dataclasses for models, Rich for output. TaskWarrior interaction isolated to a backend module using `task export/import`. Pydantic for JSON serialization. Jinja for human-readable templates.

**Tech Stack:** Python 3.11+, Click, Rich, Pydantic, Jinja2, pytest, ruff, mypy

---

## Phase 1: Project Setup

### Task 1.1: Initialize Project Structure

**Files:**
- Create: `pyproject.toml`
- Create: `src/tw/__init__.py`
- Create: `src/tw/py.typed`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "tw"
version = "0.1.0"
description = "TaskWarrior-backed issue tracker for AI agents"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0",
    "rich>=13.0",
    "pydantic>=2.0",
    "jinja2>=3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-cov>=4.0",
    "ruff>=0.1.0",
    "mypy>=1.0",
]

[project.scripts]
tw = "tw.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_ignores = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --cov=tw --cov-report=term-missing"
```

**Step 2: Create directory structure**

```bash
mkdir -p src/tw tests
touch src/tw/__init__.py src/tw/py.typed tests/__init__.py
```

**Step 3: Create tests/conftest.py**

```python
"""Shared pytest fixtures."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for test-local resources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
```

**Step 4: Install in development mode**

Run: `pip install -e ".[dev]"`
Expected: Successful installation

**Step 5: Verify setup**

Run: `python -c "import tw; print('ok')"`
Expected: `ok`

**Step 6: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: initialize project structure"
```

---

## Phase 2: Core Data Models

### Task 2.1: Issue Types and Status Enums

**Files:**
- Create: `src/tw/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
"""Tests for core data models."""

from tw.models import AnnotationType, IssueStatus, IssueType


class TestIssueType:
    def test_values(self) -> None:
        assert IssueType.EPIC.value == "epic"
        assert IssueType.STORY.value == "story"
        assert IssueType.TASK.value == "task"

    def test_from_string(self) -> None:
        assert IssueType("epic") == IssueType.EPIC
        assert IssueType("story") == IssueType.STORY
        assert IssueType("task") == IssueType.TASK


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
"""Core data models for tw."""

from enum import Enum


class IssueType(str, Enum):
    """Type of issue in the hierarchy."""

    EPIC = "epic"
    STORY = "story"
    TASK = "task"


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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/models.py tests/test_models.py
git commit -m "feat: add IssueType, IssueStatus, AnnotationType enums"
```

---

### Task 2.2: Annotation Dataclass

**Files:**
- Modify: `src/tw/models.py`
- Modify: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from datetime import datetime

from tw.models import Annotation, AnnotationType


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::TestAnnotation -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

Add to `src/tw/models.py`:

```python
import re
from dataclasses import dataclass
from datetime import datetime, timezone


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

        match = re.match(r"^\[([a-z-]+)\]\s*(.*)$", description)
        if match:
            type_str, message = match.groups()
            try:
                ann_type = AnnotationType(type_str)
            except ValueError:
                ann_type = AnnotationType.COMMENT
                message = description
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::TestAnnotation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/models.py tests/test_models.py
git commit -m "feat: add Annotation dataclass with TaskWarrior conversion"
```

---

### Task 2.3: Issue Dataclass

**Files:**
- Modify: `src/tw/models.py`
- Modify: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
from tw.models import Issue, IssueStatus, IssueType


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::TestIssue -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

Add to `src/tw/models.py`:

```python
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::TestIssue -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/models.py tests/test_models.py
git commit -m "feat: add Issue dataclass with body parsing"
```

---

## Phase 3: ID Utilities

### Task 3.1: ID Parsing and Sorting

**Files:**
- Create: `src/tw/ids.py`
- Create: `tests/test_ids.py`

**Step 1: Write the failing test**

```python
"""Tests for ID utilities."""

from tw.ids import parse_id, parse_id_sort_key, sort_ids


class TestParseId:
    def test_epic_id(self) -> None:
        result = parse_id("PROJ-1")
        assert result.prefix == "PROJ"
        assert result.epic_num == 1
        assert result.story_num is None
        assert result.task_suffix is None

    def test_story_id(self) -> None:
        result = parse_id("PROJ-1-2")
        assert result.prefix == "PROJ"
        assert result.epic_num == 1
        assert result.story_num == 2
        assert result.task_suffix is None

    def test_task_id(self) -> None:
        result = parse_id("PROJ-1-2a")
        assert result.prefix == "PROJ"
        assert result.epic_num == 1
        assert result.story_num == 2
        assert result.task_suffix == "a"

    def test_task_id_double_letter(self) -> None:
        result = parse_id("PROJ-1-2aa")
        assert result.task_suffix == "aa"

    def test_invalid_id(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="Invalid tw_id format"):
            parse_id("invalid")


class TestSortIds:
    def test_sort_mixed(self) -> None:
        ids = [
            "PROJ-12",
            "PROJ-2",
            "PROJ-1-10",
            "PROJ-1-2",
            "PROJ-1",
            "PROJ-1-1a",
            "PROJ-1-1b",
            "PROJ-1-1aa",
            "PROJ-1-1",
            "PROJ-2-1",
        ]
        expected = [
            "PROJ-1",
            "PROJ-1-1",
            "PROJ-1-1a",
            "PROJ-1-1b",
            "PROJ-1-1aa",
            "PROJ-1-2",
            "PROJ-1-10",
            "PROJ-2",
            "PROJ-2-1",
            "PROJ-12",
        ]
        assert sort_ids(ids) == expected


class TestParseIdSortKey:
    def test_ordering(self) -> None:
        assert parse_id_sort_key("PROJ-1") < parse_id_sort_key("PROJ-2")
        assert parse_id_sort_key("PROJ-1-1") < parse_id_sort_key("PROJ-1-2")
        assert parse_id_sort_key("PROJ-1-1a") < parse_id_sort_key("PROJ-1-1b")
        assert parse_id_sort_key("PROJ-1-1b") < parse_id_sort_key("PROJ-1-1aa")
        assert parse_id_sort_key("PROJ-1-2") < parse_id_sort_key("PROJ-1-10")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ids.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
"""ID parsing and sorting utilities."""

import re
from dataclasses import dataclass


@dataclass
class ParsedId:
    """Parsed components of a tw_id."""

    prefix: str
    epic_num: int
    story_num: int | None = None
    task_suffix: str | None = None


def parse_id(tw_id: str) -> ParsedId:
    """Parse a tw_id into its components.

    Raises:
        ValueError: If the ID format is invalid.
    """
    # Pattern: PREFIX-N or PREFIX-N-M or PREFIX-N-Ma...
    pattern = r"^([A-Z]+)-(\d+)(?:-(\d+)([a-z]+)?)?$"
    match = re.match(pattern, tw_id)
    if not match:
        raise ValueError(f"Invalid tw_id format: {tw_id}")

    prefix, epic_str, story_str, task_suffix = match.groups()
    return ParsedId(
        prefix=prefix,
        epic_num=int(epic_str),
        story_num=int(story_str) if story_str else None,
        task_suffix=task_suffix,
    )


def parse_id_sort_key(tw_id: str) -> tuple[str, int, int, int, str]:
    """Return a sortable key for a tw_id.

    Sort order:
    1. By prefix (alphabetically)
    2. By epic number (numerically)
    3. By story number (numerically, 0 if none)
    4. By task suffix length (shorter first)
    5. By task suffix (alphabetically)
    """
    parsed = parse_id(tw_id)
    return (
        parsed.prefix,
        parsed.epic_num,
        parsed.story_num or 0,
        len(parsed.task_suffix) if parsed.task_suffix else 0,
        parsed.task_suffix or "",
    )


def sort_ids(ids: list[str]) -> list[str]:
    """Sort a list of tw_ids in logical order."""
    return sorted(ids, key=parse_id_sort_key)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ids.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/ids.py tests/test_ids.py
git commit -m "feat: add ID parsing and sorting utilities"
```

---

### Task 3.2: ID Generation

**Files:**
- Modify: `src/tw/ids.py`
- Modify: `tests/test_ids.py`

**Step 1: Write the failing test**

Add to `tests/test_ids.py`:

```python
from tw.ids import generate_next_epic_id, generate_next_story_id, generate_next_task_id


class TestGenerateNextEpicId:
    def test_first_epic(self) -> None:
        existing: list[str] = []
        assert generate_next_epic_id("PROJ", existing) == "PROJ-1"

    def test_sequential(self) -> None:
        existing = ["PROJ-1", "PROJ-2"]
        assert generate_next_epic_id("PROJ", existing) == "PROJ-3"

    def test_with_gap(self) -> None:
        existing = ["PROJ-1", "PROJ-5"]
        assert generate_next_epic_id("PROJ", existing) == "PROJ-6"

    def test_with_reserved_from_orphan(self) -> None:
        # PROJ-3 is reserved by orphan story PROJ-3-1
        existing = ["PROJ-1", "PROJ-2", "PROJ-3-1"]
        assert generate_next_epic_id("PROJ", existing) == "PROJ-4"


class TestGenerateNextStoryId:
    def test_first_story(self) -> None:
        existing: list[str] = []
        assert generate_next_story_id("PROJ-1", existing) == "PROJ-1-1"

    def test_sequential(self) -> None:
        existing = ["PROJ-1-1", "PROJ-1-2"]
        assert generate_next_story_id("PROJ-1", existing) == "PROJ-1-3"

    def test_orphan_story(self) -> None:
        # No parent specified, find next available epic slot
        existing = ["PROJ-1", "PROJ-2"]
        assert generate_next_story_id(None, existing, prefix="PROJ") == "PROJ-3-1"


class TestGenerateNextTaskId:
    def test_first_task(self) -> None:
        existing: list[str] = []
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1a"

    def test_sequential(self) -> None:
        existing = ["PROJ-1-1a", "PROJ-1-1b"]
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1c"

    def test_after_z(self) -> None:
        existing = [f"PROJ-1-1{chr(ord('a') + i)}" for i in range(26)]
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1aa"

    def test_after_az(self) -> None:
        existing = [f"PROJ-1-1{chr(ord('a') + i)}" for i in range(26)]
        existing.extend([f"PROJ-1-1a{chr(ord('a') + i)}" for i in range(26)])
        assert generate_next_task_id("PROJ-1-1", existing) == "PROJ-1-1ba"

    def test_orphan_task(self) -> None:
        existing = ["PROJ-1", "PROJ-2"]
        assert generate_next_task_id(None, existing, prefix="PROJ") == "PROJ-3-1a"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ids.py::TestGenerateNextEpicId -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

Add to `src/tw/ids.py`:

```python
def _int_to_task_suffix(n: int) -> str:
    """Convert 0-based integer to task suffix (a, b, ..., z, aa, ab, ...)."""
    if n < 26:
        return chr(ord("a") + n)
    result = ""
    while n >= 0:
        result = chr(ord("a") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


def _get_max_epic_num(prefix: str, existing_ids: list[str]) -> int:
    """Find the maximum epic number in use (including reserved by orphans)."""
    max_num = 0
    for tw_id in existing_ids:
        try:
            parsed = parse_id(tw_id)
            if parsed.prefix == prefix:
                max_num = max(max_num, parsed.epic_num)
        except ValueError:
            continue
    return max_num


def generate_next_epic_id(prefix: str, existing_ids: list[str]) -> str:
    """Generate the next available epic ID."""
    max_num = _get_max_epic_num(prefix, existing_ids)
    return f"{prefix}-{max_num + 1}"


def generate_next_story_id(
    parent_id: str | None,
    existing_ids: list[str],
    prefix: str | None = None,
) -> str:
    """Generate the next available story ID.

    Args:
        parent_id: The parent epic's tw_id, or None for orphan
        existing_ids: All existing tw_ids in the project
        prefix: Required if parent_id is None
    """
    if parent_id is None:
        if prefix is None:
            raise ValueError("prefix required for orphan story")
        # Find next epic slot and use story 1
        max_epic = _get_max_epic_num(prefix, existing_ids)
        return f"{prefix}-{max_epic + 1}-1"

    parsed_parent = parse_id(parent_id)
    prefix = parsed_parent.prefix
    epic_num = parsed_parent.epic_num

    # Find max story number under this epic
    max_story = 0
    for tw_id in existing_ids:
        try:
            parsed = parse_id(tw_id)
            if (
                parsed.prefix == prefix
                and parsed.epic_num == epic_num
                and parsed.story_num is not None
            ):
                max_story = max(max_story, parsed.story_num)
        except ValueError:
            continue

    return f"{prefix}-{epic_num}-{max_story + 1}"


def generate_next_task_id(
    parent_id: str | None,
    existing_ids: list[str],
    prefix: str | None = None,
) -> str:
    """Generate the next available task ID.

    Args:
        parent_id: The parent story's tw_id, or None for orphan
        existing_ids: All existing tw_ids in the project
        prefix: Required if parent_id is None
    """
    if parent_id is None:
        if prefix is None:
            raise ValueError("prefix required for orphan task")
        # Find next epic slot, use story 1, task a
        max_epic = _get_max_epic_num(prefix, existing_ids)
        return f"{prefix}-{max_epic + 1}-1a"

    parsed_parent = parse_id(parent_id)
    prefix = parsed_parent.prefix
    epic_num = parsed_parent.epic_num
    story_num = parsed_parent.story_num

    if story_num is None:
        raise ValueError(f"Parent {parent_id} is not a story")

    # Find existing task suffixes under this story
    existing_suffixes: list[str] = []
    for tw_id in existing_ids:
        try:
            parsed = parse_id(tw_id)
            if (
                parsed.prefix == prefix
                and parsed.epic_num == epic_num
                and parsed.story_num == story_num
                and parsed.task_suffix is not None
            ):
                existing_suffixes.append(parsed.task_suffix)
        except ValueError:
            continue

    # Find next suffix
    if not existing_suffixes:
        next_suffix = "a"
    else:
        # Sort and find max
        sorted_suffixes = sorted(existing_suffixes, key=lambda s: (len(s), s))
        max_suffix = sorted_suffixes[-1]
        # Increment
        if max_suffix[-1] == "z":
            next_suffix = "a" * (len(max_suffix) + 1)
        else:
            next_suffix = max_suffix[:-1] + chr(ord(max_suffix[-1]) + 1)

    return f"{prefix}-{epic_num}-{story_num}{next_suffix}"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ids.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/ids.py tests/test_ids.py
git commit -m "feat: add ID generation for epics, stories, tasks"
```

---

## Phase 4: TaskWarrior Backend

### Task 4.1: Backend Interface and Export

**Files:**
- Create: `src/tw/backend.py`
- Create: `tests/test_backend.py`

**Step 1: Write the failing test**

```python
"""Tests for TaskWarrior backend."""

import json
from pathlib import Path

from tw.backend import TaskWarriorBackend
from tw.models import Issue, IssueStatus, IssueType


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_backend.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
"""TaskWarrior backend abstraction."""

import json
import logging

from tw.models import Annotation, Issue, IssueStatus, IssueType

logger = logging.getLogger(__name__)


class TaskWarriorBackend:
    """Abstraction layer for TaskWarrior operations."""

    def parse_export(self, json_str: str) -> list[Issue]:
        """Parse TaskWarrior export JSON into Issue objects.

        Args:
            json_str: JSON string from `task export`
        """
        data = json.loads(json_str)
        issues = []

        for item in data:
            # Skip items without our UDAs
            if "tw_id" not in item:
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_backend.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/backend.py tests/test_backend.py
git commit -m "feat: add TaskWarrior backend with export/import JSON handling"
```

---

### Task 4.2: Backend Shell Operations

**Files:**
- Modify: `src/tw/backend.py`
- Modify: `tests/test_backend.py`
- Modify: `tests/conftest.py`

**Step 1: Add fixture for isolated TaskWarrior**

Add to `tests/conftest.py`:

```python
import os
import subprocess


@pytest.fixture
def taskwarrior_env(temp_dir: Path) -> Generator[dict[str, str], None, None]:
    """Provide isolated TaskWarrior environment.

    Creates a temporary TASKDATA directory and configures UDAs.
    """
    taskdata = temp_dir / "task"
    taskdata.mkdir()

    env = os.environ.copy()
    env["TASKDATA"] = str(taskdata)
    env["TASKRC"] = str(temp_dir / "taskrc")

    # Create minimal taskrc with UDAs
    taskrc_content = """
data.location={}
uda.tw_type.type=string
uda.tw_type.label=Type
uda.tw_id.type=string
uda.tw_id.label=TW ID
uda.tw_parent.type=string
uda.tw_parent.label=Parent
uda.tw_body.type=string
uda.tw_body.label=Body
uda.tw_refs.type=string
uda.tw_refs.label=Refs
uda.tw_status.type=string
uda.tw_status.label=TW Status
""".format(taskdata)

    (temp_dir / "taskrc").write_text(taskrc_content)

    yield env
```

**Step 2: Write the failing test**

Add to `tests/test_backend.py`:

```python
import os


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
                uuid=f"uuid-{i}",
                tw_id=f"TEST-{i+1}",
                tw_type=IssueType.EPIC,
                title=f"Epic {i+1}",
                tw_status=IssueStatus.NEW,
                project="testproj",
            )
            backend.import_issue(issue)

        ids = backend.get_all_ids("testproj")
        assert sorted(ids) == ["TEST-1", "TEST-2", "TEST-3"]
```

**Step 3: Write implementation**

Add to `src/tw/backend.py`:

```python
import subprocess
import uuid as uuid_module


class TaskWarriorBackend:
    """Abstraction layer for TaskWarrior operations."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        """Initialize backend.

        Args:
            env: Environment variables for subprocess calls (for testing)
        """
        self._env = env

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
        output = self._run_task(["export", f"project:{project}"])
        if not output.strip() or output.strip() == "[]":
            return []
        return self.parse_export(output)

    def get_all_ids(self, project: str) -> list[str]:
        """Get all tw_ids in a project."""
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

    # ... keep existing parse_export and build_import_json methods ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_backend.py::TestTaskWarriorBackendIntegration -v`
Expected: PASS (requires TaskWarrior installed)

**Step 5: Commit**

```bash
git add src/tw/backend.py tests/test_backend.py tests/conftest.py
git commit -m "feat: add TaskWarrior shell operations (export, import)"
```

---

## Phase 5: Core Operations

### Task 5.1: References Extraction

**Files:**
- Create: `src/tw/refs.py`
- Create: `tests/test_refs.py`

**Step 1: Write the failing test**

```python
"""Tests for references extraction."""

from tw.refs import extract_refs


class TestExtractRefs:
    def test_no_refs(self) -> None:
        text = "This is some text without any references."
        assert extract_refs(text, "PROJ") == []

    def test_single_ref(self) -> None:
        text = "See PROJ-1 for details."
        assert extract_refs(text, "PROJ") == ["PROJ-1"]

    def test_multiple_refs(self) -> None:
        text = "Related to PROJ-1, PROJ-2-1, and PROJ-3-1a."
        assert extract_refs(text, "PROJ") == ["PROJ-1", "PROJ-2-1", "PROJ-3-1a"]

    def test_sorted_output(self) -> None:
        text = "See PROJ-10, PROJ-2, PROJ-1."
        assert extract_refs(text, "PROJ") == ["PROJ-1", "PROJ-2", "PROJ-10"]

    def test_deduplicated(self) -> None:
        text = "PROJ-1 is related to PROJ-1."
        assert extract_refs(text, "PROJ") == ["PROJ-1"]

    def test_different_prefix(self) -> None:
        text = "See AUTH-1 and AUTH-2-1."
        assert extract_refs(text, "AUTH") == ["AUTH-1", "AUTH-2-1"]

    def test_ignores_other_prefixes(self) -> None:
        text = "See PROJ-1 and OTHER-2."
        assert extract_refs(text, "PROJ") == ["PROJ-1"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_refs.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
"""References extraction utilities."""

import re

from tw.ids import sort_ids


def extract_refs(text: str, prefix: str) -> list[str]:
    """Extract and sort tw_id references from text.

    Args:
        text: The text to scan for references
        prefix: The project prefix to match (e.g., "PROJ")

    Returns:
        Sorted, deduplicated list of referenced tw_ids
    """
    pattern = rf"\b({re.escape(prefix)}-\d+(?:-\d+[a-z]*)?)\b"
    matches = re.findall(pattern, text)
    unique = list(set(matches))
    return sort_ids(unique)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_refs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/refs.py tests/test_refs.py
git commit -m "feat: add references extraction from text"
```

---

### Task 5.2: Issue Service Layer

**Files:**
- Create: `src/tw/service.py`
- Create: `tests/test_service.py`

**Step 1: Write the failing test**

```python
"""Tests for issue service layer."""

from tw.backend import TaskWarriorBackend
from tw.models import IssueStatus, IssueType
from tw.service import IssueService


class TestIssueService:
    def test_create_epic(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(
            issue_type=IssueType.EPIC,
            title="User Authentication",
        )

        assert tw_id == "TEST-1"
        issue = service.get_issue(tw_id)
        assert issue.title == "User Authentication"
        assert issue.tw_status == IssueStatus.NEW

    def test_create_story_under_epic(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic")
        tw_id = service.create_issue(
            issue_type=IssueType.STORY,
            title="Login Flow",
            parent_id="TEST-1",
        )

        assert tw_id == "TEST-1-1"
        issue = service.get_issue(tw_id)
        assert issue.tw_parent == "TEST-1"

    def test_create_task_under_story(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.STORY, "Story", parent_id="TEST-1")
        tw_id = service.create_issue(
            issue_type=IssueType.TASK,
            title="Implement form",
            parent_id="TEST-1-1",
        )

        assert tw_id == "TEST-1-1a"

    def test_create_orphan_task(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(
            issue_type=IssueType.TASK,
            title="Quick fix",
        )

        assert tw_id == "TEST-1-1a"

    def test_get_issue_not_found(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        import pytest
        with pytest.raises(KeyError, match="not found"):
            service.get_issue("TEST-99")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py -v`
Expected: FAIL with import error

**Step 3: Write minimal implementation**

```python
"""Issue service layer."""

import logging

from tw.backend import TaskWarriorBackend
from tw.ids import generate_next_epic_id, generate_next_story_id, generate_next_task_id
from tw.models import Issue, IssueStatus, IssueType
from tw.refs import extract_refs

logger = logging.getLogger(__name__)


class IssueService:
    """High-level operations on issues."""

    def __init__(
        self,
        backend: TaskWarriorBackend,
        project: str,
        prefix: str,
    ) -> None:
        self._backend = backend
        self._project = project
        self._prefix = prefix

    def create_issue(
        self,
        issue_type: IssueType,
        title: str,
        parent_id: str | None = None,
        body: str | None = None,
    ) -> str:
        """Create a new issue.

        Args:
            issue_type: The type of issue to create
            title: The issue title
            parent_id: Optional parent tw_id
            body: Optional body text

        Returns:
            The generated tw_id

        Raises:
            ValueError: If the parent type is invalid for this issue type
        """
        existing_ids = self._backend.get_all_ids(self._project)

        # Generate ID based on type
        if issue_type == IssueType.EPIC:
            tw_id = generate_next_epic_id(self._prefix, existing_ids)
        elif issue_type == IssueType.STORY:
            tw_id = generate_next_story_id(parent_id, existing_ids, prefix=self._prefix)
        else:  # TASK
            tw_id = generate_next_task_id(parent_id, existing_ids, prefix=self._prefix)

        # Extract references from body
        tw_refs: list[str] = []
        if body:
            tw_refs = extract_refs(body, self._prefix)

        issue = Issue(
            uuid=self._backend.generate_uuid(),
            tw_id=tw_id,
            tw_type=issue_type,
            title=title,
            tw_status=IssueStatus.NEW,
            project=self._project,
            tw_parent=parent_id,
            tw_body=body,
            tw_refs=tw_refs,
        )

        self._backend.import_issue(issue)
        logger.info(f"Created {issue_type.value} {tw_id}: {title}")
        return tw_id

    def get_issue(self, tw_id: str) -> Issue:
        """Get an issue by tw_id.

        Raises:
            KeyError: If the issue is not found.
        """
        issues = self._backend.export_project(self._project)
        for issue in issues:
            if issue.tw_id == tw_id:
                return issue
        raise KeyError(f"Issue {tw_id} not found")

    def get_all_issues(self) -> list[Issue]:
        """Get all issues in the project."""
        return self._backend.export_project(self._project)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: add IssueService with create and get operations"
```

---

### Task 5.3: Status Transitions

**Files:**
- Modify: `src/tw/service.py`
- Modify: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `tests/test_service.py`:

```python
from tw.models import AnnotationType


class TestStatusTransitions:
    def test_start_from_new(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.tw_status == IssueStatus.IN_PROGRESS
        assert any(a.type == AnnotationType.WORK_BEGIN for a in issue.annotations)

    def test_start_from_stopped(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.handoff_issue(tw_id, "reason", "done", "remaining")
        service.start_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.tw_status == IssueStatus.IN_PROGRESS

    def test_start_invalid_state(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)

        import pytest
        with pytest.raises(ValueError, match="already in_progress"):
            service.start_issue(tw_id)

    def test_done_from_in_progress(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.done_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.tw_status == IssueStatus.DONE
        assert any(a.type == AnnotationType.WORK_END for a in issue.annotations)

    def test_blocked_and_unblock(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.block_issue(tw_id, "Waiting for API")

        issue = service.get_issue(tw_id)
        assert issue.tw_status == IssueStatus.BLOCKED

        service.unblock_issue(tw_id, "API ready")
        issue = service.get_issue(tw_id)
        assert issue.tw_status == IssueStatus.IN_PROGRESS

    def test_handoff(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.handoff_issue(
            tw_id,
            status="Context limit",
            completed="- [x] Item 1",
            remaining="- [ ] Item 2",
        )

        issue = service.get_issue(tw_id)
        assert issue.tw_status == IssueStatus.STOPPED
        handoff_ann = [a for a in issue.annotations if a.type == AnnotationType.HANDOFF]
        assert len(handoff_ann) == 1
        assert "Context limit" in handoff_ann[0].message
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestStatusTransitions -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/tw/service.py`:

```python
from datetime import datetime, timezone

from tw.models import Annotation, AnnotationType


class IssueService:
    # ... existing methods ...

    def _add_annotation(
        self, issue: Issue, ann_type: AnnotationType, message: str
    ) -> None:
        """Add an annotation to an issue and save."""
        annotation = Annotation(
            type=ann_type,
            timestamp=datetime.now(timezone.utc),
            message=message,
        )
        issue.annotations.append(annotation)
        self._backend.import_issue(issue)

    def _transition(
        self,
        tw_id: str,
        valid_from: list[IssueStatus],
        to_status: IssueStatus,
        ann_type: AnnotationType,
        message: str,
    ) -> None:
        """Perform a status transition with validation."""
        issue = self.get_issue(tw_id)

        if issue.tw_status not in valid_from:
            raise ValueError(
                f"cannot transition {tw_id}: already {issue.tw_status.value}"
            )

        issue.tw_status = to_status
        self._add_annotation(issue, ann_type, message)
        logger.info(f"{tw_id}: {to_status.value}")

    def start_issue(self, tw_id: str) -> None:
        """Start work on an issue."""
        self._transition(
            tw_id,
            valid_from=[IssueStatus.NEW, IssueStatus.STOPPED],
            to_status=IssueStatus.IN_PROGRESS,
            ann_type=AnnotationType.WORK_BEGIN,
            message="",
        )

    def done_issue(self, tw_id: str) -> None:
        """Mark an issue as done."""
        self._transition(
            tw_id,
            valid_from=[IssueStatus.IN_PROGRESS],
            to_status=IssueStatus.DONE,
            ann_type=AnnotationType.WORK_END,
            message="",
        )

    def block_issue(self, tw_id: str, reason: str) -> None:
        """Mark an issue as blocked."""
        self._transition(
            tw_id,
            valid_from=[IssueStatus.IN_PROGRESS],
            to_status=IssueStatus.BLOCKED,
            ann_type=AnnotationType.BLOCKED,
            message=reason,
        )

    def unblock_issue(self, tw_id: str, reason: str) -> None:
        """Unblock an issue."""
        self._transition(
            tw_id,
            valid_from=[IssueStatus.BLOCKED],
            to_status=IssueStatus.IN_PROGRESS,
            ann_type=AnnotationType.UNBLOCKED,
            message=reason,
        )

    def handoff_issue(
        self, tw_id: str, status: str, completed: str, remaining: str
    ) -> None:
        """Hand off an issue with structured summary."""
        message = f"{status}\n\n## Completed\n{completed}\n\n## Remaining\n{remaining}"
        self._transition(
            tw_id,
            valid_from=[IssueStatus.IN_PROGRESS],
            to_status=IssueStatus.STOPPED,
            ann_type=AnnotationType.HANDOFF,
            message=message,
        )

    def record_annotation(
        self, tw_id: str, ann_type: AnnotationType, message: str
    ) -> None:
        """Add an annotation to an issue."""
        issue = self.get_issue(tw_id)
        self._add_annotation(issue, ann_type, message)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: add status transitions (start, done, block, unblock, handoff)"
```

---

## Phase 6: CLI Commands

### Task 6.1: CLI Foundation

**Files:**
- Create: `src/tw/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write the failing test**

```python
"""Tests for CLI commands."""

from click.testing import CliRunner

from tw.cli import main


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "tw" in result.output

    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
"""CLI entry point for tw."""

import logging
import os
import sys

import click
from rich.console import Console

logger = logging.getLogger(__name__)

# Console for stdout (command output)
stdout_console = Console()

# Console for stderr (logging, spinners)
stderr_console = Console(stderr=True)


def get_project() -> str:
    """Get project name from environment."""
    return os.environ.get(
        "TW_PROJECT_NAME", os.environ.get("PROJECT_NAME", "default")
    )


def get_prefix() -> str:
    """Get project prefix from environment."""
    return os.environ.get(
        "TW_PROJECT_PREFIX", os.environ.get("PROJECT_PREFIX", "DEFAULT")
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-error output")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--project-name", envvar="TW_PROJECT_NAME", default=None)
@click.option("--project-prefix", envvar="TW_PROJECT_PREFIX", default=None)
@click.version_option(version="0.1.0")
@click.pass_context
def main(
    ctx: click.Context,
    verbose: bool,
    quiet: bool,
    json_output: bool,
    project_name: str | None,
    project_prefix: str | None,
) -> None:
    """tw - TaskWarrior-backed issue tracker for AI agents."""
    ctx.ensure_object(dict)

    # Configure logging
    if verbose:
        logging.basicConfig(level=logging.DEBUG, handlers=[])
    elif quiet:
        logging.basicConfig(level=logging.ERROR, handlers=[])
    else:
        logging.basicConfig(level=logging.INFO, handlers=[])

    ctx.obj["json"] = json_output
    ctx.obj["project"] = project_name or get_project()
    ctx.obj["prefix"] = project_prefix or get_prefix()
    ctx.obj["stdout"] = stdout_console
    ctx.obj["stderr"] = stderr_console


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: add CLI foundation with global options"
```

---

### Task 6.2: `tw new` Command

**Files:**
- Modify: `src/tw/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
import os


class TestNewCommand:
    def test_new_epic(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_new_story_with_parent(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        # Create epic first
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        # Create story
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story", "--parent", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1-1" in result.output

    def test_new_missing_title(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic"],
        )
        assert result.exit_code != 0
        assert "title" in result.output.lower() or "required" in result.output.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::TestNewCommand -v`
Expected: FAIL

**Step 3: Write implementation**

Add to `src/tw/cli.py`:

```python
from tw.backend import TaskWarriorBackend
from tw.models import IssueType
from tw.service import IssueService


def get_service(ctx: click.Context) -> IssueService:
    """Get configured IssueService from context."""
    backend = TaskWarriorBackend()
    return IssueService(
        backend=backend,
        project=ctx.obj["project"],
        prefix=ctx.obj["prefix"],
    )


@main.command()
@click.argument("issue_type", type=click.Choice(["epic", "story", "task"]))
@click.option("--title", "-t", required=True, help="Issue title")
@click.option("--parent", "-p", default=None, help="Parent issue ID")
@click.option("--body", "-b", default=None, help="Issue body (or - for stdin)")
@click.pass_context
def new(
    ctx: click.Context,
    issue_type: str,
    title: str,
    parent: str | None,
    body: str | None,
) -> None:
    """Create a new issue."""
    try:
        service = get_service(ctx)

        if body == "-":
            body = sys.stdin.read()

        tw_id = service.create_issue(
            issue_type=IssueType(issue_type),
            title=title,
            parent_id=parent,
            body=body,
        )

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            import json
            console.print(json.dumps({"tw_id": tw_id}))
        else:
            console.print(f"Created {issue_type} {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::TestNewCommand -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: add 'tw new' command"
```

---

### Task 6.3: Remaining CLI Commands

Continue with the same pattern for:

- `tw view` — Render issue with context
- `tw edit` — Edit issue (spawn $EDITOR if no options)
- `tw delete` — Delete issue
- `tw start` — Start work
- `tw done` — Complete work
- `tw blocked` — Mark blocked
- `tw unblock` — Unblock
- `tw handoff` — Structured handoff
- `tw record` — Add typed annotation
- `tw comment` — Add comment
- `tw tree` — Show hierarchy
- `tw digest` — Show parent summary
- `tw capture` — Bulk create from DSL
- `tw onboard` — Print quickstart

Each command follows the same TDD pattern:
1. Write failing test
2. Verify failure
3. Implement
4. Verify pass
5. Commit

---

## Phase 7: Templates and Rendering

### Task 7.1: Jinja Templates

**Files:**
- Create: `src/tw/templates/view.md.j2`
- Create: `src/tw/templates/tree.txt.j2`
- Create: `src/tw/templates/digest.md.j2`
- Create: `src/tw/render.py`
- Create: `tests/test_render.py`

Templates and rendering logic for human-readable output.

---

## Phase 8: Final Integration

### Task 8.1: End-to-End Tests

**Files:**
- Create: `tests/test_e2e.py`

Full workflow tests exercising the complete CLI.

### Task 8.2: Documentation

**Files:**
- Create: `README.md`
- Update: `src/tw/templates/onboard.md.j2`

---

## Execution Checklist

- [ ] Phase 1: Project Setup (Task 1.1)
- [ ] Phase 2: Core Data Models (Tasks 2.1-2.3)
- [ ] Phase 3: ID Utilities (Tasks 3.1-3.2)
- [ ] Phase 4: TaskWarrior Backend (Tasks 4.1-4.2)
- [ ] Phase 5: Core Operations (Tasks 5.1-5.3)
- [ ] Phase 6: CLI Commands (Tasks 6.1-6.3+)
- [ ] Phase 7: Templates and Rendering (Task 7.1)
- [ ] Phase 8: Final Integration (Tasks 8.1-8.2)
