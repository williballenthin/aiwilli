# Backlog Mechanism Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `bug` and `idea` backlog types with a `tw groom` command for batch processing.

**Architecture:** Extend existing IssueType enum with two new values. Backlog items use top-level IDs (same namespace as epics), have simplified status (new→done only), and cannot have parents or children. A new `tw groom` command opens $EDITOR with all backlog items for batch conversion to epic/story/task.

**Tech Stack:** Python, Click, Pydantic-style dataclasses, Jinja2 templates, pytest

---

## Story 1: Add Backlog Types to Models

### Task 1a: Add BUG and IDEA to IssueType enum

**Files:**
- Modify: `src/tw/models.py:9-14`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_issue_type_includes_backlog_types() -> None:
    """IssueType should include bug and idea for backlog items."""
    from tw.models import IssueType

    assert IssueType.BUG.value == "bug"
    assert IssueType.IDEA.value == "idea"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_issue_type_includes_backlog_types -v`
Expected: FAIL with "AttributeError: BUG"

**Step 3: Write minimal implementation**

Modify `src/tw/models.py` IssueType enum:

```python
class IssueType(str, Enum):
    """Type of issue in the hierarchy."""

    EPIC = "epic"
    STORY = "story"
    TASK = "task"
    BUG = "bug"
    IDEA = "idea"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::test_issue_type_includes_backlog_types -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/models.py tests/test_models.py
git commit -m "feat: add BUG and IDEA to IssueType enum"
```

---

### Task 1b: Add helper to check if issue type is backlog

**Files:**
- Modify: `src/tw/models.py`
- Test: `tests/test_models.py`

**Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_is_backlog_type() -> None:
    """is_backlog_type should return True for bug/idea, False for others."""
    from tw.models import IssueType, is_backlog_type

    assert is_backlog_type(IssueType.BUG) is True
    assert is_backlog_type(IssueType.IDEA) is True
    assert is_backlog_type(IssueType.EPIC) is False
    assert is_backlog_type(IssueType.STORY) is False
    assert is_backlog_type(IssueType.TASK) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_is_backlog_type -v`
Expected: FAIL with "ImportError: cannot import name 'is_backlog_type'"

**Step 3: Write minimal implementation**

Add to `src/tw/models.py` after IssueType enum:

```python
def is_backlog_type(issue_type: IssueType) -> bool:
    """Return True if the issue type is a backlog type (bug or idea)."""
    return issue_type in (IssueType.BUG, IssueType.IDEA)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py::test_is_backlog_type -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/models.py tests/test_models.py
git commit -m "feat: add is_backlog_type helper function"
```

---

## Story 2: Service Layer Backlog Support

### Task 2a: Generate top-level IDs for backlog items

**Files:**
- Modify: `src/tw/service.py:27-77`
- Test: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `tests/test_service.py`:

```python
@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestBacklogIssues:
    def test_create_bug_gets_top_level_id(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(
            issue_type=IssueType.BUG,
            title="Login broken",
        )

        assert tw_id == "TEST-1"
        issue = service.get_issue(tw_id)
        assert issue.tw_type == IssueType.BUG
        assert issue.tw_status == IssueStatus.NEW

    def test_create_idea_gets_top_level_id(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(
            issue_type=IssueType.IDEA,
            title="Password strength meter",
        )

        assert tw_id == "TEST-1"
        issue = service.get_issue(tw_id)
        assert issue.tw_type == IssueType.IDEA

    def test_backlog_shares_id_namespace_with_epics(
        self, taskwarrior_env: dict[str, str]
    ) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic 1")  # TEST-1
        service.create_issue(IssueType.BUG, "Bug 1")  # TEST-2
        service.create_issue(IssueType.IDEA, "Idea 1")  # TEST-3
        service.create_issue(IssueType.EPIC, "Epic 2")  # TEST-4

        issues = service.get_all_issues()
        ids = sorted([i.tw_id for i in issues])
        assert ids == ["TEST-1", "TEST-2", "TEST-3", "TEST-4"]
```

Also add import at top: `from tw.models import AnnotationType, IssueStatus, IssueType`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestBacklogIssues -v`
Expected: FAIL (IssueType.BUG doesn't exist yet, or ID generation fails)

**Step 3: Write minimal implementation**

Modify `src/tw/service.py` `create_issue` method to handle backlog types:

```python
def create_issue(
    self,
    issue_type: IssueType,
    title: str,
    parent_id: str | None = None,
    body: str | None = None,
) -> str:
    """Create a new issue."""
    from tw.models import is_backlog_type

    existing_ids = self._backend.get_all_ids(self._project)

    # Generate ID based on type
    if issue_type == IssueType.EPIC or is_backlog_type(issue_type):
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
    logger.debug(f"Created {issue_type.value} {tw_id}: {title}")
    return tw_id
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py::TestBacklogIssues -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: generate top-level IDs for backlog items"
```

---

### Task 2b: Reject parent for backlog items

**Files:**
- Modify: `src/tw/service.py`
- Test: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `TestBacklogIssues` class:

```python
    def test_backlog_rejects_parent(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic")

        with pytest.raises(ValueError, match="cannot have a parent"):
            service.create_issue(IssueType.BUG, "Bug", parent_id="TEST-1")

        with pytest.raises(ValueError, match="cannot have a parent"):
            service.create_issue(IssueType.IDEA, "Idea", parent_id="TEST-1")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_backlog_rejects_parent -v`
Expected: FAIL (no validation yet)

**Step 3: Write minimal implementation**

Add validation at the start of `create_issue`:

```python
def create_issue(
    self,
    issue_type: IssueType,
    title: str,
    parent_id: str | None = None,
    body: str | None = None,
) -> str:
    """Create a new issue."""
    from tw.models import is_backlog_type

    # Validate backlog items cannot have parents
    if is_backlog_type(issue_type) and parent_id is not None:
        raise ValueError(f"{issue_type.value} issues cannot have a parent")

    # ... rest of method
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_backlog_rejects_parent -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: reject parent for backlog items"
```

---

### Task 2c: Reject backlog items as parents

**Files:**
- Modify: `src/tw/service.py`
- Test: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `TestBacklogIssues`:

```python
    def test_backlog_cannot_be_parent(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.BUG, "Bug")

        with pytest.raises(ValueError, match="cannot have children"):
            service.create_issue(IssueType.TASK, "Task", parent_id="TEST-1")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_backlog_cannot_be_parent -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add validation in `create_issue` after checking backlog parent:

```python
    # Validate parent is not a backlog item
    if parent_id is not None:
        parent = self.get_issue(parent_id)
        if is_backlog_type(parent.tw_type):
            raise ValueError(f"{parent.tw_type.value} issues cannot have children")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_backlog_cannot_be_parent -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: reject backlog items as parents"
```

---

### Task 2d: Allow done_issue directly from NEW for backlog items

**Files:**
- Modify: `src/tw/service.py:318-326`
- Test: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `TestBacklogIssues`:

```python
    def test_backlog_done_from_new(self, taskwarrior_env: dict[str, str]) -> None:
        """Backlog items can go directly from NEW to DONE."""
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.BUG, "Bug")
        service.done_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.tw_status == IssueStatus.DONE
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_backlog_done_from_new -v`
Expected: FAIL with "cannot transition" (requires IN_PROGRESS)

**Step 3: Write minimal implementation**

Modify `done_issue` in `src/tw/service.py`:

```python
def done_issue(self, tw_id: str) -> None:
    """Mark an issue as done."""
    from tw.models import is_backlog_type

    issue = self.get_issue(tw_id)

    # Backlog items can go directly from NEW to DONE
    if is_backlog_type(issue.tw_type):
        valid_from = [IssueStatus.NEW, IssueStatus.IN_PROGRESS]
    else:
        valid_from = [IssueStatus.IN_PROGRESS]

    if issue.tw_status not in valid_from:
        raise ValueError(
            f"cannot transition {tw_id}: status is {issue.tw_status.value}"
        )

    issue.tw_status = IssueStatus.DONE
    self._add_annotation(issue, AnnotationType.WORK_END, "")
    logger.info(f"{tw_id}: done")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_backlog_done_from_new -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: allow done directly from new for backlog items"
```

---

### Task 2e: Reject workflow commands for backlog items

**Files:**
- Modify: `src/tw/service.py`
- Test: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `TestBacklogIssues`:

```python
    def test_backlog_rejects_start(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.BUG, "Bug")

        with pytest.raises(ValueError, match="not supported for"):
            service.start_issue(tw_id)

    def test_backlog_rejects_handoff(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.IDEA, "Idea")

        with pytest.raises(ValueError, match="not supported for"):
            service.handoff_issue(tw_id, "status", "completed", "remaining")

    def test_backlog_rejects_block(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        tw_id = service.create_issue(IssueType.BUG, "Bug")

        with pytest.raises(ValueError, match="not supported for"):
            service.block_issue(tw_id, "reason")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_backlog_rejects_start -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add helper method and modify existing methods:

```python
def _validate_not_backlog(self, tw_id: str, operation: str) -> Issue:
    """Validate issue is not a backlog type, return the issue."""
    from tw.models import is_backlog_type

    issue = self.get_issue(tw_id)
    if is_backlog_type(issue.tw_type):
        raise ValueError(f"{operation} not supported for {issue.tw_type.value} issues")
    return issue

def start_issue(self, tw_id: str) -> None:
    """Start work on an issue."""
    self._validate_not_backlog(tw_id, "start")
    self._transition(
        tw_id,
        valid_from=[IssueStatus.NEW, IssueStatus.STOPPED],
        to_status=IssueStatus.IN_PROGRESS,
        ann_type=AnnotationType.WORK_BEGIN,
        message="",
    )

def block_issue(self, tw_id: str, reason: str) -> None:
    """Mark an issue as blocked."""
    self._validate_not_backlog(tw_id, "block")
    self._transition(
        tw_id,
        valid_from=[IssueStatus.IN_PROGRESS],
        to_status=IssueStatus.BLOCKED,
        ann_type=AnnotationType.BLOCKED,
        message=reason,
    )

def unblock_issue(self, tw_id: str, reason: str) -> None:
    """Unblock an issue."""
    self._validate_not_backlog(tw_id, "unblock")
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
    self._validate_not_backlog(tw_id, "handoff")
    message = f"{status}\n\n## Completed\n{completed}\n\n## Remaining\n{remaining}"
    self._transition(
        tw_id,
        valid_from=[IssueStatus.IN_PROGRESS],
        to_status=IssueStatus.STOPPED,
        ann_type=AnnotationType.HANDOFF,
        message=message,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py::TestBacklogIssues -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: reject workflow commands for backlog items"
```

---

### Task 2f: Add get_backlog_issues method

**Files:**
- Modify: `src/tw/service.py`
- Test: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `TestBacklogIssues`:

```python
    def test_get_backlog_issues(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.BUG, "Bug 1")
        service.create_issue(IssueType.IDEA, "Idea 1")
        service.create_issue(IssueType.BUG, "Bug 2")

        # Mark one as done
        service.done_issue("TEST-4")

        backlog = service.get_backlog_issues()
        ids = [i.tw_id for i in backlog]

        assert "TEST-2" in ids  # Bug 1
        assert "TEST-3" in ids  # Idea 1
        assert "TEST-1" not in ids  # Epic excluded
        assert "TEST-4" not in ids  # Done bug excluded
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_get_backlog_issues -v`
Expected: FAIL with "AttributeError: get_backlog_issues"

**Step 3: Write minimal implementation**

Add to `src/tw/service.py`:

```python
def get_backlog_issues(self) -> list[Issue]:
    """Get all NEW backlog items (bugs and ideas)."""
    from tw.models import is_backlog_type
    from tw.ids import parse_id_sort_key

    all_issues = self.get_all_issues()
    backlog = [
        i for i in all_issues
        if is_backlog_type(i.tw_type) and i.tw_status == IssueStatus.NEW
    ]
    return sorted(backlog, key=lambda i: parse_id_sort_key(i.tw_id))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py::TestBacklogIssues::test_get_backlog_issues -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: add get_backlog_issues method"
```

---

## Story 3: Multi-line Capture/Groom Format

### Task 3a: Parse multi-line entries in capture DSL

**Files:**
- Modify: `src/tw/cli.py:50-100` (CaptureEntry and parse_capture_dsl)
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Create/add to `tests/test_cli.py`:

```python
from tw.cli import parse_capture_dsl, CaptureEntry


class TestParseCapturesDsl:
    def test_parse_multiline_body(self) -> None:
        """Parse entries with multi-line body content."""
        content = """- bug: login broken
    The login form crashes.
    Discovered while working on TEST-5.
- idea: password meter
    Would improve UX.
"""
        entries = parse_capture_dsl(content)

        assert len(entries) == 2
        assert entries[0].issue_type == "bug"
        assert entries[0].title == "login broken"
        assert entries[0].body == "The login form crashes.\nDiscovered while working on TEST-5."
        assert entries[1].issue_type == "idea"
        assert entries[1].title == "password meter"
        assert entries[1].body == "Would improve UX."

    def test_parse_multiline_with_separator(self) -> None:
        """Parse entries with --- separator in body."""
        content = """- task: implement form
    Repeatable summary here.
    ---
    Non-repeatable details.
"""
        entries = parse_capture_dsl(content)

        assert len(entries) == 1
        assert entries[0].body == "Repeatable summary here.\n---\nNon-repeatable details."

    def test_parse_preserves_hierarchy_with_multiline(self) -> None:
        """Multi-line bodies work with hierarchy."""
        content = """- epic: auth system
    High level description.
  - story: login
      Story details here.
    - task: form
        Task details.
"""
        entries = parse_capture_dsl(content)

        assert len(entries) == 3
        assert entries[0].parent_title is None
        assert entries[0].body == "High level description."
        assert entries[1].parent_title == "auth system"
        assert entries[1].body == "Story details here."
        assert entries[2].parent_title == "login"
        assert entries[2].body == "Task details."
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::TestParseCapturesDsl -v`
Expected: FAIL (CaptureEntry has no body field)

**Step 3: Write minimal implementation**

Update `src/tw/cli.py`:

```python
@dataclass
class CaptureEntry:
    """Parsed entry from capture DSL."""

    issue_type: str
    title: str
    parent_title: str | None
    body: str | None = None


def parse_capture_dsl(content: str) -> list[CaptureEntry]:
    """Parse the indented DSL and return entries.

    Supports multi-line body content indented below the type: title line.
    Body uses --- separator for repeatable/non-repeatable sections.
    """
    import re

    entries: list[CaptureEntry] = []
    parent_stack: dict[int, str] = {}

    lines = content.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip empty lines and comments
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue

        # Check for entry start: "- type: title"
        match = re.match(r'^(\s*)-\s*(epic|story|task|bug|idea):\s*(.+)$', line)
        if not match:
            i += 1
            continue

        indent_str, issue_type, title = match.groups()
        indent = len(indent_str)

        # Determine parent from indent
        parent_title = None
        if indent > 0:
            # Find closest parent at lower indent
            for check_indent in range(indent - 1, -1, -1):
                if check_indent in parent_stack:
                    parent_title = parent_stack[check_indent]
                    break

        # Collect body lines (more indented than the - line)
        body_lines: list[str] = []
        body_indent = indent + 2  # Expect body to be indented further
        i += 1

        while i < len(lines):
            body_line = lines[i]

            # Empty line - include in body if we have content
            if not body_line.strip():
                if body_lines:
                    body_lines.append("")
                i += 1
                continue

            # Comment line in body - skip
            if body_line.strip().startswith("# tw:"):
                i += 1
                continue

            # Check if this is a new entry (starts with -)
            if re.match(r'^\s*-\s*(epic|story|task|bug|idea):', body_line):
                break

            # Check indentation - must be more indented than entry line
            line_indent = len(body_line) - len(body_line.lstrip())
            if line_indent <= indent:
                break

            # Strip the body indentation
            stripped = body_line[body_indent:] if len(body_line) > body_indent else body_line.strip()
            body_lines.append(stripped)
            i += 1

        # Clean up trailing empty lines
        while body_lines and not body_lines[-1]:
            body_lines.pop()

        body = "\n".join(body_lines) if body_lines else None

        entry = CaptureEntry(
            issue_type=issue_type,
            title=title.strip(),
            parent_title=parent_title,
            body=body,
        )
        entries.append(entry)

        # Track for parent lookup - use the - line indent
        parent_stack[indent] = title.strip()

    return entries
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::TestParseCapturesDsl -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: parse multi-line bodies in capture DSL"
```

---

### Task 3b: Update capture command to use body

**Files:**
- Modify: `src/tw/cli.py` (capture command)
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
import shutil
import pytest
from click.testing import CliRunner
from tw.cli import main


@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestCaptureCommand:
    def test_capture_with_body(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, ["capture", "-"], input="""- bug: test bug
    This is the body.
    With multiple lines.
""")

        assert result.exit_code == 0

        # Verify body was stored
        result = runner.invoke(main, ["view", "DEFAULT-1", "--json"])
        import json
        data = json.loads(result.output)
        assert data["issue"]["tw_body"] == "This is the body.\nWith multiple lines."
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::TestCaptureCommand::test_capture_with_body -v`
Expected: FAIL (body not passed to create_issue)

**Step 3: Write minimal implementation**

Update capture command in `src/tw/cli.py`:

```python
@main.command()
@click.argument("input_source", required=False, default=None)
@click.pass_context
def capture(ctx: click.Context, input_source: str | None) -> None:
    """Create multiple issues from indented DSL."""
    try:
        service = get_service(ctx)

        if input_source == "-":
            content = sys.stdin.read()
        elif input_source is None:
            editor = os.environ.get("EDITOR", "vi")
            template = """\n\n# Capture issues using indented DSL
# Format: - type: title
# Types: epic, story, task, bug, idea
# Lines starting with # are ignored
# Body content goes on indented lines below
#
# - epic: example epic
#     Epic description here.
#   - story: example story
#       Story description.
#     - task: example task
#         Task details.
# - bug: example bug
#     Bug description.
"""
            with tempfile.NamedTemporaryFile(
                mode="w+", suffix=".txt", delete=False
            ) as f:
                f.write(template)
                temp_path = f.name

            try:
                subprocess.run([editor, temp_path], check=True)
                with open(temp_path) as f:
                    content = f.read()
            finally:
                os.unlink(temp_path)
        else:
            click.echo("error: invalid argument", err=True)
            ctx.exit(1)
            return

        entries = parse_capture_dsl(content)

        created: list[dict[str, str]] = []
        title_to_id: dict[str, str] = {}

        for entry in entries:
            parent_id = None
            if entry.parent_title:
                parent_id = title_to_id.get(entry.parent_title)

            tw_id = service.create_issue(
                issue_type=IssueType(entry.issue_type),
                title=entry.title,
                parent_id=parent_id,
                body=entry.body,  # Now passing body
            )

            title_to_id[entry.title] = tw_id
            created.append({"tw_id": tw_id, "title": entry.title})

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            click.echo(json.dumps({"created": created}))
        else:
            if created:
                for item in created:
                    console.print(f"Created {item['tw_id']}: {item['title']}")
            else:
                console.print("No issues created")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::TestCaptureCommand::test_capture_with_body -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: capture command passes body to create_issue"
```

---

## Story 4: CLI Commands for Backlog

### Task 4a: Add tw new bug command

**Files:**
- Modify: `src/tw/cli.py` (new command)
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestNewBacklogCommands:
    def test_new_bug(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, [
            "new", "bug",
            "--title", "Login broken",
            "--body", "Crashes on empty password"
        ])

        assert result.exit_code == 0
        assert "DEFAULT-1" in result.output

    def test_new_idea(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, [
            "new", "idea",
            "--title", "Password strength meter"
        ])

        assert result.exit_code == 0
        assert "DEFAULT-1" in result.output

    def test_new_bug_rejects_parent(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        runner.invoke(main, ["new", "epic", "--title", "Epic"])
        result = runner.invoke(main, [
            "new", "bug",
            "--title", "Bug",
            "--parent", "DEFAULT-1"
        ])

        assert result.exit_code == 1
        assert "cannot have a parent" in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::TestNewBacklogCommands -v`
Expected: FAIL (bug/idea not in choices)

**Step 3: Write minimal implementation**

Update the `new` command in `src/tw/cli.py`:

```python
@main.command()
@click.argument("issue_type", type=click.Choice(["epic", "story", "task", "bug", "idea"]))
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
            console.print(json.dumps({"tw_id": tw_id}))
        else:
            console.print(f"Created {issue_type} {tw_id}")

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::TestNewBacklogCommands -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: add bug and idea to tw new command"
```

---

### Task 4b: Add render_groom_content function

**Files:**
- Modify: `src/tw/render.py`
- Test: `tests/test_render.py`

**Step 1: Write the failing test**

Add to `tests/test_render.py`:

```python
from tw.models import Issue, IssueStatus, IssueType
from tw.render import render_groom_content


class TestRenderGroomContent:
    def test_render_single_bug(self) -> None:
        issues = [
            Issue(
                uuid="uuid1",
                tw_id="TEST-5",
                tw_type=IssueType.BUG,
                title="Login broken",
                tw_status=IssueStatus.NEW,
                project="test",
                tw_body="The form crashes.\n---\nDetails here.",
            )
        ]

        content = render_groom_content(issues)

        assert "# TEST-5 (bug)" in content
        assert "- bug: Login broken" in content
        assert "    The form crashes." in content
        assert "    ---" in content
        assert "    Details here." in content

    def test_render_multiple_items(self) -> None:
        issues = [
            Issue(
                uuid="uuid1",
                tw_id="TEST-1",
                tw_type=IssueType.BUG,
                title="Bug one",
                tw_status=IssueStatus.NEW,
                project="test",
            ),
            Issue(
                uuid="uuid2",
                tw_id="TEST-2",
                tw_type=IssueType.IDEA,
                title="Idea one",
                tw_status=IssueStatus.NEW,
                project="test",
                tw_body="Some description.",
            ),
        ]

        content = render_groom_content(issues)

        assert "# TEST-1 (bug)" in content
        assert "- bug: Bug one" in content
        assert "# TEST-2 (idea)" in content
        assert "- idea: Idea one" in content
        assert "    Some description." in content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py::TestRenderGroomContent -v`
Expected: FAIL with "ImportError: cannot import name 'render_groom_content'"

**Step 3: Write minimal implementation**

Add to `src/tw/render.py`:

```python
def render_groom_content(issues: list[Issue]) -> str:
    """Render backlog issues for groom editor.

    Format:
    # TEST-1 (bug)
    - bug: title
        body line 1
        body line 2
    """
    lines: list[str] = []

    for issue in issues:
        # Comment with ID
        lines.append(f"# {issue.tw_id} ({issue.tw_type.value})")

        # Entry line
        lines.append(f"- {issue.tw_type.value}: {issue.title}")

        # Body lines (indented)
        if issue.tw_body:
            for body_line in issue.tw_body.splitlines():
                lines.append(f"    {body_line}")

        lines.append("")  # Blank line between entries

    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_render.py::TestRenderGroomContent -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/render.py tests/test_render.py
git commit -m "feat: add render_groom_content function"
```

---

### Task 4c: Add parse_groom_result function

**Files:**
- Modify: `src/tw/render.py`
- Test: `tests/test_render.py`

**Step 1: Write the failing test**

Add to `tests/test_render.py`:

```python
from tw.render import parse_groom_result, GroomAction


class TestParseGroomResult:
    def test_unchanged_item(self) -> None:
        """Item left as-is should be marked unchanged."""
        content = """# TEST-1 (bug)
- bug: original title
    original body
"""
        original_ids = ["TEST-1"]

        actions = parse_groom_result(content, original_ids)

        assert len(actions) == 1
        assert actions[0].original_id == "TEST-1"
        assert actions[0].action == "unchanged"

    def test_removed_item(self) -> None:
        """Item removed from content should be marked resolved."""
        content = """# Some comment
"""
        original_ids = ["TEST-1", "TEST-2"]

        actions = parse_groom_result(content, original_ids)

        resolved = [a for a in actions if a.action == "resolve"]
        assert len(resolved) == 2

    def test_transformed_item(self) -> None:
        """Item changed to different type should create new + resolve old."""
        content = """# TEST-1 (bug)
- task: fix the bug
    New description.
"""
        original_ids = ["TEST-1"]

        actions = parse_groom_result(content, original_ids)

        # Should have: resolve TEST-1, create task
        resolve_actions = [a for a in actions if a.action == "resolve"]
        create_actions = [a for a in actions if a.action == "create"]

        assert len(resolve_actions) == 1
        assert resolve_actions[0].original_id == "TEST-1"
        assert len(create_actions) == 1
        assert create_actions[0].issue_type == "task"
        assert create_actions[0].title == "fix the bug"

    def test_new_item_no_comment(self) -> None:
        """Item without # comment is new."""
        content = """- epic: new epic
    Description.
"""
        original_ids = []

        actions = parse_groom_result(content, original_ids)

        assert len(actions) == 1
        assert actions[0].action == "create"
        assert actions[0].issue_type == "epic"
        assert actions[0].original_id is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py::TestParseGroomResult -v`
Expected: FAIL with "ImportError"

**Step 3: Write minimal implementation**

Add to `src/tw/render.py`:

```python
from dataclasses import dataclass


@dataclass
class GroomAction:
    """Action to take during groom processing."""

    action: str  # "unchanged", "resolve", "create"
    original_id: str | None = None
    issue_type: str | None = None
    title: str | None = None
    body: str | None = None
    parent_title: str | None = None


def parse_groom_result(
    content: str, original_ids: list[str]
) -> list[GroomAction]:
    """Parse groom editor result and determine actions.

    Compares edited content against original IDs to determine:
    - unchanged: ID present with same type
    - resolve: ID removed or transformed
    - create: new entry to create
    """
    from tw.cli import parse_capture_dsl

    actions: list[GroomAction] = []
    seen_ids: set[str] = set()

    # Track which ID each entry is associated with
    lines = content.splitlines()
    current_id: str | None = None
    entries_by_id: dict[str | None, list] = {}

    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for ID comment: # TEST-1 (bug)
        if line.startswith("#") and "(" in line and ")" in line:
            import re
            match = re.match(r'^#\s*([A-Z]+-\d+(?:-\d+)?(?:[a-z]+)?)\s*\(', line)
            if match:
                current_id = match.group(1)
                i += 1
                continue

        # Check for entry start
        if re.match(r'^\s*-\s*(epic|story|task|bug|idea):', line):
            # Parse from this point using capture DSL
            remaining = "\n".join(lines[i:])
            entries = parse_capture_dsl(remaining)
            if entries:
                entry = entries[0]
                if current_id not in entries_by_id:
                    entries_by_id[current_id] = []
                entries_by_id[current_id].append(entry)
                seen_ids.add(current_id) if current_id else None

                # Skip past this entry's lines
                # Find next entry or ID comment
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    if next_line.startswith("#") or re.match(r'^\s*-\s*(epic|story|task|bug|idea):', next_line):
                        break
                    i += 1
                current_id = None
                continue

        i += 1
        current_id = None

    # Determine actions
    # 1. IDs not seen -> resolve
    for orig_id in original_ids:
        if orig_id not in seen_ids:
            actions.append(GroomAction(action="resolve", original_id=orig_id))

    # 2. Process entries by ID
    for assoc_id, entries in entries_by_id.items():
        for entry in entries:
            if assoc_id in original_ids:
                # Check if unchanged (same type as backlog)
                if entry.issue_type in ("bug", "idea"):
                    actions.append(GroomAction(
                        action="unchanged",
                        original_id=assoc_id,
                    ))
                else:
                    # Transformed
                    actions.append(GroomAction(action="resolve", original_id=assoc_id))
                    actions.append(GroomAction(
                        action="create",
                        issue_type=entry.issue_type,
                        title=entry.title,
                        body=entry.body,
                        parent_title=entry.parent_title,
                    ))
            else:
                # New entry (no associated ID)
                actions.append(GroomAction(
                    action="create",
                    issue_type=entry.issue_type,
                    title=entry.title,
                    body=entry.body,
                    parent_title=entry.parent_title,
                ))

    return actions
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_render.py::TestParseGroomResult -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/render.py tests/test_render.py
git commit -m "feat: add parse_groom_result function"
```

---

### Task 4d: Add tw groom command

**Files:**
- Modify: `src/tw/cli.py`
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestGroomCommand:
    def test_groom_empty_backlog(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, ["groom"])

        assert result.exit_code == 0
        assert "No backlog items" in result.output

    def test_groom_resolves_removed(
        self, taskwarrior_env: dict[str, str], monkeypatch
    ) -> None:
        runner = CliRunner(env=taskwarrior_env)

        # Create a bug
        runner.invoke(main, ["new", "bug", "--title", "Test bug"])

        # Mock editor to return empty content (removes the item)
        def mock_editor(*args, **kwargs):
            return
        monkeypatch.setattr("subprocess.run", mock_editor)

        # Provide empty content via stdin workaround
        result = runner.invoke(main, ["groom"], input="\n")

        # The bug should be resolved
        view_result = runner.invoke(main, ["view", "DEFAULT-1", "--json"])
        import json
        data = json.loads(view_result.output)
        assert data["issue"]["tw_status"] == "done"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::TestGroomCommand -v`
Expected: FAIL (command doesn't exist)

**Step 3: Write minimal implementation**

Add to `src/tw/cli.py`:

```python
from tw.render import render_groom_content, parse_groom_result


@main.command()
@click.pass_context
def groom(ctx: click.Context) -> None:
    """Open editor to groom all backlog items."""
    try:
        service = get_service(ctx)
        backlog = service.get_backlog_issues()

        console: Console = ctx.obj["stdout"]

        if not backlog:
            console.print("No backlog items to groom")
            return

        original_ids = [i.tw_id for i in backlog]
        content = render_groom_content(backlog)

        # Open editor
        editor = os.environ.get("EDITOR", "vi")
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".md", delete=False
        ) as f:
            f.write(content)
            f.write("\n# Instructions:\n")
            f.write("# - Transform bug/idea to epic/story/task to convert\n")
            f.write("# - Remove entry entirely to dismiss\n")
            f.write("# - Leave unchanged to keep in backlog\n")
            f.write("# - Add new entries without # ID comment\n")
            temp_path = f.name

        try:
            subprocess.run([editor, temp_path], check=True)
            with open(temp_path) as f:
                edited = f.read()
        finally:
            os.unlink(temp_path)

        # Parse result and apply actions
        actions = parse_groom_result(edited, original_ids)

        title_to_id: dict[str, str] = {}
        summary: dict[str, int] = {"resolved": 0, "created": 0, "unchanged": 0}

        for action in actions:
            if action.action == "resolve":
                service.done_issue(action.original_id)
                summary["resolved"] += 1
            elif action.action == "create":
                parent_id = title_to_id.get(action.parent_title) if action.parent_title else None
                tw_id = service.create_issue(
                    issue_type=IssueType(action.issue_type),
                    title=action.title,
                    parent_id=parent_id,
                    body=action.body,
                )
                title_to_id[action.title] = tw_id
                summary["created"] += 1
                console.print(f"Created {action.issue_type} {tw_id}: {action.title}")
            elif action.action == "unchanged":
                summary["unchanged"] += 1

        if ctx.obj["json"]:
            click.echo(json.dumps(summary))
        else:
            console.print(
                f"Groomed: {summary['resolved']} resolved, "
                f"{summary['created']} created, {summary['unchanged']} unchanged"
            )

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::TestGroomCommand -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: add tw groom command"
```

---

## Story 5: Tree Display with Backlog Section

### Task 5a: Update get_issue_tree to separate backlog

**Files:**
- Modify: `src/tw/service.py`
- Test: `tests/test_service.py`

**Step 1: Write the failing test**

Add to `tests/test_service.py`:

```python
@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestGetIssueTreeWithBacklog:
    def test_tree_separates_backlog(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.BUG, "Bug 1")
        service.create_issue(IssueType.IDEA, "Idea 1")

        hierarchy, backlog = service.get_issue_tree_with_backlog()

        hierarchy_ids = [i.tw_id for i in hierarchy]
        backlog_ids = [i.tw_id for i in backlog]

        assert "TEST-1" in hierarchy_ids
        assert "TEST-2" in backlog_ids
        assert "TEST-3" in backlog_ids
        assert "TEST-2" not in hierarchy_ids
        assert "TEST-1" not in backlog_ids

    def test_backlog_excludes_done(self, taskwarrior_env: dict[str, str]) -> None:
        backend = TaskWarriorBackend(env=taskwarrior_env)
        service = IssueService(backend, project="test", prefix="TEST")

        service.create_issue(IssueType.BUG, "Bug 1")
        service.create_issue(IssueType.BUG, "Bug 2")
        service.done_issue("TEST-1")

        hierarchy, backlog = service.get_issue_tree_with_backlog()
        backlog_ids = [i.tw_id for i in backlog]

        assert "TEST-1" not in backlog_ids
        assert "TEST-2" in backlog_ids
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_service.py::TestGetIssueTreeWithBacklog -v`
Expected: FAIL with "AttributeError: get_issue_tree_with_backlog"

**Step 3: Write minimal implementation**

Add to `src/tw/service.py`:

```python
def get_issue_tree_with_backlog(
    self, root_id: str | None = None
) -> tuple[list[Issue], list[Issue]]:
    """Get issue tree and backlog separately.

    Returns:
        Tuple of (hierarchy_issues, backlog_issues)
        - hierarchy_issues: epics/stories/tasks in tree order
        - backlog_issues: bugs/ideas (NEW status only)
    """
    from tw.models import is_backlog_type

    all_issues = self.get_all_issues()

    # Separate backlog from hierarchy
    hierarchy_issues = [i for i in all_issues if not is_backlog_type(i.tw_type)]
    backlog_issues = self.get_backlog_issues()

    # Use existing tree logic for hierarchy
    # Create a temporary service view without backlog
    if root_id is not None:
        hierarchy_tree = self.get_issue_tree(root_id)
        # Filter out any backlog items that might have snuck in
        hierarchy_tree = [i for i in hierarchy_tree if not is_backlog_type(i.tw_type)]
        return hierarchy_tree, backlog_issues

    # Reuse existing tree logic but filter
    tree = self.get_issue_tree()
    hierarchy_tree = [i for i in tree if not is_backlog_type(i.tw_type)]

    return hierarchy_tree, backlog_issues
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_service.py::TestGetIssueTreeWithBacklog -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/service.py tests/test_service.py
git commit -m "feat: add get_issue_tree_with_backlog method"
```

---

### Task 5b: Update render_tree to show backlog section

**Files:**
- Modify: `src/tw/render.py`
- Modify: `src/tw/templates/tree.txt.j2`
- Test: `tests/test_render.py`

**Step 1: Write the failing test**

Add to `tests/test_render.py`:

```python
class TestRenderTreeWithBacklog:
    def test_renders_backlog_section(self) -> None:
        hierarchy = [
            Issue(
                uuid="uuid1",
                tw_id="TEST-1",
                tw_type=IssueType.EPIC,
                title="Epic One",
                tw_status=IssueStatus.NEW,
                project="test",
            )
        ]
        backlog = [
            Issue(
                uuid="uuid2",
                tw_id="TEST-2",
                tw_type=IssueType.BUG,
                title="Bug One",
                tw_status=IssueStatus.NEW,
                project="test",
            )
        ]

        from tw.render import render_tree_with_backlog
        output = render_tree_with_backlog(hierarchy, backlog)

        assert "Epic One" in output
        assert "Backlog" in output
        assert "Bug One" in output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_render.py::TestRenderTreeWithBacklog -v`
Expected: FAIL with "ImportError"

**Step 3: Write minimal implementation**

Add to `src/tw/render.py`:

```python
def render_tree_with_backlog(
    hierarchy: list[Issue], backlog: list[Issue]
) -> str:
    """Render tree with separate backlog section.

    Args:
        hierarchy: Epic/story/task issues in tree order
        backlog: Bug/idea issues

    Returns:
        Formatted tree with backlog section at bottom
    """
    issue_map = {issue.tw_id: issue for issue in hierarchy}

    def compute_depth(issue: Issue) -> int:
        depth = 0
        current = issue
        while current.tw_parent:
            depth += 1
            parent_issue = issue_map.get(current.tw_parent)
            if not parent_issue:
                break
            current = parent_issue
        return depth

    hierarchy_with_depth = [(issue, compute_depth(issue)) for issue in hierarchy]
    backlog_with_depth = [(issue, 0) for issue in backlog]  # Backlog items are flat

    template = _env.get_template("tree.txt.j2")
    return template.render(
        issues_with_depth=hierarchy_with_depth,
        backlog_with_depth=backlog_with_depth,
    )
```

Update `src/tw/templates/tree.txt.j2`:

```jinja2
{% for issue, depth in issues_with_depth %}
{% set indent = '  ' * depth %}
{% if issue.tw_status.value == 'done' %}{{ indent }}[grey69]{{ issue.tw_type.value }}[/grey69][grey69]:[/grey69] [grey69]{{ issue.title }}[/grey69] [grey69]([/grey69][grey69]{{ issue.tw_id }}[/grey69][grey69])[/grey69]
{% elif issue.tw_status.value == 'in_progress' %}{{ indent }}[grey69]{{ issue.tw_type.value }}[/grey69][grey69]:[/grey69] [default]{{ issue.title }}[/default] [grey69]([/grey69][yellow]{{ issue.tw_id }}[/yellow][grey69])[/grey69] [green][in_progress][/green]
{% elif issue.tw_status.value == 'blocked' or issue.tw_status.value == 'stopped' %}{{ indent }}[grey69]{{ issue.tw_type.value }}[/grey69][grey69]:[/grey69] [default]{{ issue.title }}[/default] [grey69]([/grey69][yellow]{{ issue.tw_id }}[/yellow][grey69])[/grey69] [red][{{ issue.tw_status.value }}][/red]
{% else %}{{ indent }}[grey69]{{ issue.tw_type.value }}[/grey69][grey69]:[/grey69] [default]{{ issue.title }}[/default] [grey69]([/grey69][yellow]{{ issue.tw_id }}[/yellow][grey69])[/grey69]
{% endif %}
{% if issue.tw_type.value == 'task' and issue.annotations %}
{% for ann in issue.annotations %}
[dim]{{ indent }}  {{ ann.type.value }}: {{ ann.timestamp|relative_time }}, {{ ann.message.split('\n')[0] }}[/dim]
{% endfor %}
{% endif %}
{% endfor %}
{% if backlog_with_depth %}

[dim]───────────────── Backlog ─────────────────[/dim]

{% for issue, depth in backlog_with_depth %}
[grey69]{{ issue.tw_type.value }}[/grey69][grey69]:[/grey69] [default]{{ issue.title }}[/default] [grey69]([/grey69][yellow]{{ issue.tw_id }}[/yellow][grey69])[/grey69]
{% endfor %}
{% endif %}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_render.py::TestRenderTreeWithBacklog -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/render.py src/tw/templates/tree.txt.j2 tests/test_render.py
git commit -m "feat: render tree with backlog section"
```

---

### Task 5c: Update tree command to use new render function

**Files:**
- Modify: `src/tw/cli.py` (tree command)
- Test: `tests/test_cli.py`

**Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestTreeWithBacklog:
    def test_tree_shows_backlog_section(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        runner.invoke(main, ["new", "epic", "--title", "Epic One"])
        runner.invoke(main, ["new", "bug", "--title", "Bug One"])

        result = runner.invoke(main, ["tree"])

        assert result.exit_code == 0
        assert "Epic One" in result.output
        assert "Backlog" in result.output
        assert "Bug One" in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::TestTreeWithBacklog -v`
Expected: FAIL (tree doesn't show backlog section)

**Step 3: Write minimal implementation**

Update tree command in `src/tw/cli.py`:

```python
from tw.render import render_tree_with_backlog


@main.command()
@click.argument("tw_id", required=False, default=None)
@click.pass_context
def tree(ctx: click.Context, tw_id: str | None) -> None:
    """Show tree of all issues with backlog section."""
    try:
        service = get_service(ctx)
        hierarchy, backlog = service.get_issue_tree_with_backlog(root_id=tw_id)

        console: Console = ctx.obj["stdout"]
        if ctx.obj["json"]:
            def issue_to_dict(issue: Issue) -> dict:
                return {
                    "uuid": issue.uuid,
                    "tw_id": issue.tw_id,
                    "tw_type": issue.tw_type.value,
                    "title": issue.title,
                    "tw_status": issue.tw_status.value,
                    "project": issue.project,
                    "tw_parent": issue.tw_parent,
                    "tw_body": issue.tw_body,
                    "tw_refs": issue.tw_refs,
                    "annotations": [
                        {
                            "type": ann.type.value,
                            "timestamp": ann.timestamp.isoformat(),
                            "message": ann.message,
                        }
                        for ann in (issue.annotations or [])
                    ],
                }

            output = {
                "hierarchy": [issue_to_dict(i) for i in hierarchy],
                "backlog": [issue_to_dict(i) for i in backlog],
            }
            console.print(json.dumps(output, indent=2))
        else:
            console.print(render_tree_with_backlog(hierarchy, backlog), markup=True)

    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py::TestTreeWithBacklog -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: update tree command to show backlog section"
```

---

## Story 6: Update onboard documentation

### Task 6a: Add backlog commands to onboard

**Files:**
- Modify: `src/tw/templates/onboard.md.j2`

**Step 1: Update onboard template**

Add to `src/tw/templates/onboard.md.j2` in the commands section:

```markdown
## Backlog Commands

Quick capture for discovered work:

```bash
# Create backlog items (bugs/ideas)
tw new bug --title "Login broken" --body "Crashes on empty password"
tw new idea --title "Password strength meter"

# Groom backlog (open editor with all backlog items)
tw groom

# View backlog in tree
tw tree  # Shows hierarchy then backlog section
```

Backlog items:
- Use top-level IDs (same namespace as epics)
- Have simplified status: new → done
- Cannot have parents or children
- Groom to convert to epic/story/task
```

**Step 2: Run full test suite**

Run: `pytest -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/tw/templates/onboard.md.j2
git commit -m "docs: add backlog commands to onboard guide"
```

---

## Final Verification

**Run full test suite:**

```bash
pytest -v --tb=short
```

**Run type checker:**

```bash
mypy src/tw
```

**Run linter:**

```bash
ruff check src/tw tests
```

**Manual verification:**

```bash
# Create some backlog items
tw new bug --title "Test bug" --body "Description"
tw new idea --title "Test idea"

# View tree (should show backlog section)
tw tree

# Groom backlog
tw groom

# Verify onboard shows new commands
tw onboard
```
