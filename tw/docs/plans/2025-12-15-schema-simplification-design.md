# Schema Simplification Design

## Overview

Two refactors to simplify the tw database schema:
1. Remove vestigial `project` column (always "default")
2. Move `tw_refs` from comma-separated column to proper join table

## Schema Changes

### Current Schema (issues table)
```sql
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    tw_id TEXT NOT NULL,
    tw_type TEXT NOT NULL,
    title TEXT NOT NULL,
    tw_status TEXT NOT NULL,
    project TEXT NOT NULL,
    tw_parent TEXT,
    tw_body TEXT,
    tw_refs TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(tw_id, project)
);
```

### New Schema

```sql
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

CREATE TABLE IF NOT EXISTS issue_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_issue_id INTEGER NOT NULL,
    target_tw_id TEXT,
    FOREIGN KEY (source_issue_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY (target_tw_id) REFERENCES issues(tw_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_issue_refs_source ON issue_refs(source_issue_id);
CREATE INDEX IF NOT EXISTS idx_issue_refs_target ON issue_refs(target_tw_id);
```

### Key Changes
- Removed `project` column
- Removed `tw_refs` column
- Simplified uniqueness to just `tw_id`
- New `issue_refs` join table with:
  - FK to source issue (CASCADE delete)
  - FK to target tw_id (SET NULL on delete, preserves that ref existed)
  - Indexes for both forward and reverse lookups

## Backend Changes

### Method Signatures

Remove `project` parameter from all methods:

```python
# Before
def get_all_issues(self, project: str) -> list[Issue]
def get_issue(self, tw_id: str, project: str) -> Issue | None
def save_issue(self, issue: Issue, project: str) -> None
def delete_issue(self, tw_id: str, project: str) -> None
def add_annotation(self, tw_id: str, project: str, annotation: Annotation) -> None
def get_all_ids(self, project: str) -> list[str]

# After
def get_all_issues(self) -> list[Issue]
def get_issue(self, tw_id: str) -> Issue | None
def save_issue(self, issue: Issue) -> None
def delete_issue(self, tw_id: str) -> None
def add_annotation(self, tw_id: str, annotation: Annotation) -> None
def get_all_ids(self) -> list[str]
```

### New Method

```python
def get_issues_referencing(self, tw_id: str) -> list[str]:
    """Get all issue IDs that reference the given issue."""
```

### Refs Handling

In `save_issue`:
- On insert: extract refs from body, insert into `issue_refs` table
- On update: delete existing refs for issue, re-insert current refs
- Skip refs that point to non-existent issues (FK constraint rejects them)

In `get_issue` and `get_all_issues`:
- Query `issue_refs` table to populate `Issue.refs` field
- Filter out NULL entries (from deleted target issues)

## Service Layer Changes

Remove `project` from constructor:

```python
# Before
def __init__(self, backend: SqliteBackend, project: str, prefix: str) -> None:
    self._backend = backend
    self._project = project
    self._prefix = prefix

# After
def __init__(self, backend: SqliteBackend, prefix: str) -> None:
    self._backend = backend
    self._prefix = prefix
```

Update all internal methods to not pass project to backend.

## CLI Changes

In `cli.py`:
- Remove `ctx.obj["project"] = "default"` line
- Update `get_service()` to not pass project parameter

## Migration Strategy

Fresh start only - no automatic migration. Existing `.tw.db` files are incompatible; users delete and recreate their issues.

## Test Changes

- Update all backend/service tests to remove `project` parameters
- Add tests for:
  - Refs stored in join table
  - Reverse lookup via `get_issues_referencing()`
  - Delete issue sets ref to NULL
  - Refs to non-existent issues are skipped on insert
