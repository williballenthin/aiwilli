# Schema Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove vestigial `project` column and normalize `tw_refs` into a join table.

**Architecture:** Update schema.sql to remove project column and add issue_refs table. Update SqliteBackend to remove project parameter from all methods. Update IssueService to remove project from constructor. Update CLI to not pass project.

**Tech Stack:** SQLite, Python dataclasses, pytest

---

## Task 1: Update Schema

**Files:**
- Modify: `src/tw/schema.sql`

**Step 1: Update schema.sql with new schema**

Replace entire contents of `src/tw/schema.sql` with:

```sql
-- tw database schema
-- Stores issues and annotations for the tw issue tracker

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    tw_id TEXT NOT NULL UNIQUE,
    tw_type TEXT NOT NULL,
    title TEXT NOT NULL,
    tw_status TEXT NOT NULL,
    tw_parent TEXT,
    tw_body TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY (issue_id) REFERENCES issues(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS issue_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_issue_id INTEGER NOT NULL,
    target_tw_id TEXT,
    FOREIGN KEY (source_issue_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY (target_tw_id) REFERENCES issues(tw_id) ON DELETE SET NULL
);

-- Indexes for performance
CREATE UNIQUE INDEX IF NOT EXISTS idx_issues_uuid ON issues(uuid);
CREATE INDEX IF NOT EXISTS idx_issues_tw_id ON issues(tw_id);
CREATE INDEX IF NOT EXISTS idx_issues_tw_parent ON issues(tw_parent);
CREATE INDEX IF NOT EXISTS idx_annotations_issue_id ON annotations(issue_id);
CREATE INDEX IF NOT EXISTS idx_annotations_type ON annotations(type);
CREATE INDEX IF NOT EXISTS idx_issue_refs_source ON issue_refs(source_issue_id);
CREATE INDEX IF NOT EXISTS idx_issue_refs_target ON issue_refs(target_tw_id);
```

**Step 2: Verify schema loads correctly**

Run: `uv run python -c "from tw.schema import init_db; from pathlib import Path; import tempfile; init_db(Path(tempfile.mktemp()))"`

Expected: No errors

**Step 3: Commit**

```bash
git add src/tw/schema.sql
git commit -m "Update schema: remove project column, add issue_refs table"
```

---

## Task 2: Update Backend - Remove Project Parameter

**Files:**
- Modify: `src/tw/backend.py`

**Step 1: Update get_all_issues method**

Change signature from `def get_all_issues(self, project: str) -> list[Issue]:` to `def get_all_issues(self) -> list[Issue]:`.

Update the SQL query to remove project filter and update refs handling:

```python
def get_all_issues(self) -> list[Issue]:
    """Get all issues.

    Returns:
        List of all issues.
    """
    with sqlite3.connect(self._db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, uuid, tw_id, tw_type, title, tw_status, tw_parent, tw_body, created_at, updated_at "
            "FROM issues"
        )
        rows = cursor.fetchall()

        issues = []
        for row in rows:
            annotations = self._get_annotations_for_issue_id(conn, row["id"])
            tw_refs = self._get_refs_for_issue_id(conn, row["id"])
            created_at = datetime.strptime(row["created_at"], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            updated_at = datetime.strptime(row["updated_at"], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            issue = Issue(
                id=row["tw_id"],
                type=IssueType(row["tw_type"]),
                title=row["title"],
                status=IssueStatus(row["tw_status"]),
                created_at=created_at,
                updated_at=updated_at,
                parent=row["tw_parent"],
                body=row["tw_body"],
                refs=tw_refs,
                annotations=annotations,
            )
            issues.append(issue)

        return issues
```

**Step 2: Update get_issue method**

Change signature from `def get_issue(self, tw_id: str, project: str) -> Issue | None:` to `def get_issue(self, tw_id: str) -> Issue | None:`.

```python
def get_issue(self, tw_id: str) -> Issue | None:
    """Get a specific issue by ID.

    Args:
        tw_id: The issue ID

    Returns:
        The Issue object or None if not found.
    """
    with sqlite3.connect(self._db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, uuid, tw_id, tw_type, title, tw_status, tw_parent, tw_body, created_at, updated_at "
            "FROM issues WHERE tw_id = ?",
            (tw_id,),
        )
        row = cursor.fetchone()

        if row is None:
            return None

        annotations = self._get_annotations_for_issue_id(conn, row["id"])
        tw_refs = self._get_refs_for_issue_id(conn, row["id"])
        created_at = datetime.strptime(row["created_at"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
        updated_at = datetime.strptime(row["updated_at"], "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
        issue = Issue(
            id=row["tw_id"],
            type=IssueType(row["tw_type"]),
            title=row["title"],
            status=IssueStatus(row["tw_status"]),
            created_at=created_at,
            updated_at=updated_at,
            parent=row["tw_parent"],
            body=row["tw_body"],
            refs=tw_refs,
            annotations=annotations,
        )

        return issue
```

**Step 3: Update save_issue method**

Change signature and update to use issue_refs table:

```python
def save_issue(self, issue: Issue) -> None:
    """Save or update an issue.

    Args:
        issue: The issue to save

    Raises:
        RuntimeError: If the save operation fails.
    """
    try:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM issues WHERE tw_id = ?",
                (issue.id,),
            )
            existing = cursor.fetchone()

            if existing:
                issue_id = existing[0]
                cursor.execute(
                    "UPDATE issues SET tw_type = ?, title = ?, tw_status = ?, "
                    "tw_parent = ?, tw_body = ?, updated_at = ? WHERE id = ?",
                    (
                        issue.type.value,
                        issue.title,
                        issue.status.value,
                        issue.parent,
                        issue.body,
                        issue.updated_at.strftime("%Y%m%dT%H%M%SZ"),
                        issue_id,
                    ),
                )
                cursor.execute("DELETE FROM issue_refs WHERE source_issue_id = ?", (issue_id,))
            else:
                issue_uuid = str(uuid_module.uuid4())
                cursor.execute(
                    "INSERT INTO issues (uuid, tw_id, tw_type, title, tw_status, tw_parent, tw_body, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        issue_uuid,
                        issue.id,
                        issue.type.value,
                        issue.title,
                        issue.status.value,
                        issue.parent,
                        issue.body,
                        issue.created_at.strftime("%Y%m%dT%H%M%SZ"),
                        issue.updated_at.strftime("%Y%m%dT%H%M%SZ"),
                    ),
                )
                cursor.execute(
                    "SELECT id FROM issues WHERE tw_id = ?",
                    (issue.id,),
                )
                issue_id = cursor.fetchone()[0]

                for annotation in issue.annotations:
                    cursor.execute(
                        "INSERT INTO annotations (issue_id, type, timestamp, message) VALUES (?, ?, ?, ?)",
                        (
                            issue_id,
                            annotation.type.value,
                            annotation.timestamp.strftime("%Y%m%dT%H%M%SZ"),
                            annotation.message,
                        ),
                    )

            if issue.refs:
                for ref in issue.refs:
                    cursor.execute("SELECT tw_id FROM issues WHERE tw_id = ?", (ref,))
                    if cursor.fetchone():
                        cursor.execute(
                            "INSERT INTO issue_refs (source_issue_id, target_tw_id) VALUES (?, ?)",
                            (issue_id, ref),
                        )

            conn.commit()
    except sqlite3.DatabaseError as e:
        logger.error(f"Failed to save issue {issue.id}: {e}")
        raise RuntimeError(f"Failed to save issue {issue.id}") from e
```

**Step 4: Update delete_issue method**

```python
def delete_issue(self, tw_id: str) -> None:
    """Delete an issue.

    Args:
        tw_id: The issue ID

    Raises:
        KeyError: If the issue is not found.
        RuntimeError: If the delete operation fails.
    """
    try:
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM issues WHERE tw_id = ?",
                (tw_id,),
            )
            row = cursor.fetchone()

            if row is None:
                raise KeyError(f"Issue {tw_id} not found")

            issue_id = row[0]
            cursor.execute("DELETE FROM annotations WHERE issue_id = ?", (issue_id,))
            cursor.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
            conn.commit()
    except KeyError:
        raise
    except sqlite3.DatabaseError as e:
        logger.error(f"Failed to delete issue {tw_id}: {e}")
        raise RuntimeError(f"Failed to delete issue {tw_id}") from e
```

**Step 5: Update add_annotation method**

```python
def add_annotation(
    self, tw_id: str, annotation: Annotation
) -> None:
    """Add an annotation to an issue.

    Args:
        tw_id: The issue ID
        annotation: The annotation to add

    Raises:
        KeyError: If the issue is not found.
    """
    with sqlite3.connect(self._db_path) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id FROM issues WHERE tw_id = ?",
            (tw_id,),
        )
        row = cursor.fetchone()

        if row is None:
            raise KeyError(f"Issue {tw_id} not found")

        issue_id = row[0]
        cursor.execute(
            "INSERT INTO annotations (issue_id, type, timestamp, message) VALUES (?, ?, ?, ?)",
            (
                issue_id,
                annotation.type.value,
                annotation.timestamp.strftime("%Y%m%dT%H%M%SZ"),
                annotation.message,
            ),
        )
        conn.commit()
```

**Step 6: Update get_all_ids method**

```python
def get_all_ids(self) -> list[str]:
    """Get all issue IDs.

    Returns:
        List of all issue IDs.
    """
    with sqlite3.connect(self._db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tw_id FROM issues")
        rows = cursor.fetchall()
        return [row[0] for row in rows]
```

**Step 7: Add helper method for refs**

Add this method after `_get_annotations_for_issue_id`:

```python
def _get_refs_for_issue_id(
    self, conn: sqlite3.Connection, issue_id: int
) -> list[str]:
    """Get all refs for an issue (internal helper).

    Args:
        conn: Active database connection
        issue_id: The internal issue ID

    Returns:
        List of target tw_ids that this issue references.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT target_tw_id FROM issue_refs WHERE source_issue_id = ? AND target_tw_id IS NOT NULL",
        (issue_id,),
    )
    rows = cursor.fetchall()
    return [row[0] for row in rows]
```

**Step 8: Add get_issues_referencing method**

Add this public method:

```python
def get_issues_referencing(self, tw_id: str) -> list[str]:
    """Get all issue IDs that reference the given issue.

    Args:
        tw_id: The target issue ID

    Returns:
        List of issue IDs that reference this issue.
    """
    with sqlite3.connect(self._db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT i.tw_id FROM issue_refs r "
            "JOIN issues i ON r.source_issue_id = i.id "
            "WHERE r.target_tw_id = ?",
            (tw_id,),
        )
        rows = cursor.fetchall()
        return [row[0] for row in rows]
```

**Step 9: Commit**

```bash
git add src/tw/backend.py
git commit -m "Update backend: remove project parameter, use issue_refs table"
```

---

## Task 3: Update Service Layer

**Files:**
- Modify: `src/tw/service.py`

**Step 1: Update constructor**

Change from:
```python
def __init__(
    self,
    backend: SqliteBackend,
    project: str,
    prefix: str,
) -> None:
    self._backend = backend
    self._project = project
    self._prefix = prefix
```

To:
```python
def __init__(
    self,
    backend: SqliteBackend,
    prefix: str,
) -> None:
    self._backend = backend
    self._prefix = prefix
```

**Step 2: Update _get_all_issues**

Change from:
```python
def _get_all_issues(self) -> list[Issue]:
    """Get all issues for the project from backend."""
    return self._backend.get_all_issues(self._project)
```

To:
```python
def _get_all_issues(self) -> list[Issue]:
    """Get all issues from backend."""
    return self._backend.get_all_issues()
```

**Step 3: Update _save_issue**

Change from:
```python
def _save_issue(self, issue: Issue) -> None:
    """Save an issue to the backend."""
    self._backend.save_issue(issue, self._project)
```

To:
```python
def _save_issue(self, issue: Issue) -> None:
    """Save an issue to the backend."""
    self._backend.save_issue(issue)
```

**Step 4: Update _get_all_ids**

Change from:
```python
def _get_all_ids(self, include_deleted: bool = False) -> list[str]:
    """Get all issue IDs in the project."""
    return self._backend.get_all_ids(self._project)
```

To:
```python
def _get_all_ids(self, include_deleted: bool = False) -> list[str]:
    """Get all issue IDs."""
    return self._backend.get_all_ids()
```

**Step 5: Update get_issue**

Find this block (around line 110-120):
```python
if isinstance(self._backend, SqliteBackend):
    issue = self._backend.get_issue(tw_id, self._project)
```

Change to:
```python
if isinstance(self._backend, SqliteBackend):
    issue = self._backend.get_issue(tw_id)
```

**Step 6: Update _add_annotation calls**

Find all calls to `self._backend.add_annotation(issue.id, self._project, annotation)` and change to `self._backend.add_annotation(issue.id, annotation)`.

Also find `self._backend.save_issue(issue, self._project)` and change to `self._backend.save_issue(issue)`.

**Step 7: Update delete_issue**

Find `self._backend.delete_issue(tw_id, self._project)` and change to `self._backend.delete_issue(tw_id)`.

**Step 8: Remove any remaining self._project references**

Search for `self._project` and remove any remaining usages. There may be calls like `self._backend.export_project(self._project)` that need updating - if they exist, remove them.

**Step 9: Commit**

```bash
git add src/tw/service.py
git commit -m "Update service: remove project parameter from constructor and calls"
```

---

## Task 4: Update CLI

**Files:**
- Modify: `src/tw/cli.py`

**Step 1: Remove project from context**

Find this line (around line 220):
```python
ctx.obj["project"] = "default"
```

Delete it entirely.

**Step 2: Update get_service function**

Find the `get_service` function (around line 50-55) and change from:
```python
return IssueService(
    backend=backend,
    project=ctx.obj["project"],
    prefix=ctx.obj["prefix"],
)
```

To:
```python
return IssueService(
    backend=backend,
    prefix=ctx.obj["prefix"],
)
```

**Step 3: Commit**

```bash
git add src/tw/cli.py
git commit -m "Update CLI: remove project from context and service creation"
```

---

## Task 5: Update Test Fixtures

**Files:**
- Modify: `tests/conftest.py`

**Step 1: Update sqlite_service fixture**

Change from:
```python
@pytest.fixture
def sqlite_service(temp_dir: Path) -> IssueService:
    """Provide an IssueService with SqliteBackend for testing.

    Creates a temporary SQLite database and initializes the service.
    """
    db_path = temp_dir / "test.db"
    backend = SqliteBackend(db_path)
    return IssueService(backend, project="test", prefix="TEST")
```

To:
```python
@pytest.fixture
def sqlite_service(temp_dir: Path) -> IssueService:
    """Provide an IssueService with SqliteBackend for testing.

    Creates a temporary SQLite database and initializes the service.
    """
    db_path = temp_dir / "test.db"
    backend = SqliteBackend(db_path)
    return IssueService(backend, prefix="TEST")
```

**Step 2: Commit**

```bash
git add tests/conftest.py
git commit -m "Update test fixtures: remove project parameter"
```

---

## Task 6: Add Backend Tests for Refs

**Files:**
- Create: `tests/test_backend.py`

**Step 1: Create test file with ref tests**

Create `tests/test_backend.py`:

```python
"""Tests for SQLite backend."""

from pathlib import Path

import pytest

from tw.backend import SqliteBackend
from tw.models import Issue, IssueStatus, IssueType
from datetime import datetime, timezone


@pytest.fixture
def backend(temp_dir: Path) -> SqliteBackend:
    """Provide a fresh SqliteBackend for testing."""
    db_path = temp_dir / "test.db"
    return SqliteBackend(db_path)


class TestBackendRefs:
    def test_refs_stored_in_join_table(self, backend: SqliteBackend) -> None:
        """Refs should be stored in issue_refs table, not as comma-separated."""
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
        now = datetime.now(timezone.utc)

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
```

**Step 2: Run tests to verify**

Run: `uv run pytest tests/test_backend.py -v`

Expected: All tests pass

**Step 3: Commit**

```bash
git add tests/test_backend.py
git commit -m "Add backend tests for refs join table and basic operations"
```

---

## Task 7: Run Full Test Suite and Fix Issues

**Files:**
- Possibly modify: any files with test failures

**Step 1: Run full test suite**

Run: `uv run pytest -v --tb=short`

**Step 2: Fix any failures**

Address any test failures by updating tests or fixing code as needed.

**Step 3: Run mypy**

Run: `uv run mypy src/tw`

**Step 4: Fix any type errors**

Address any type errors found.

**Step 5: Final commit**

```bash
git add -A
git commit -m "Fix test and type issues from schema simplification"
```

---

## Verification

After completing all tasks:

1. Run: `uv run pytest -v` - All tests should pass
2. Run: `uv run mypy src/tw` - No type errors
3. Test manually:
   ```bash
   rm -f /tmp/test.db
   TW_DB_PATH=/tmp/test.db TW_PREFIX=TEST tw new epic --title "Test"
   TW_DB_PATH=/tmp/test.db TW_PREFIX=TEST tw tree
   ```
