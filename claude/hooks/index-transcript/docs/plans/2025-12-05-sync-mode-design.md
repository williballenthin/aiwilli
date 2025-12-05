# Sync Mode Design

## Overview

Add a `sync` subcommand to `index_transcript.py` that imports all existing transcripts from `~/.claude/projects/` into the database.

## Invocation

```bash
uv run index_transcript.py sync
```

## Dependencies

Adds `rich` to PEP 723 dependencies for progress bar.

## Behavior

1. Load `session_id → project_dir` mapping from `~/.claude/history.jsonl`
2. Find all `*.jsonl` files in `~/.claude/projects/`
3. Show Rich progress bar with live stats
4. For each transcript file:
   - Extract `session_id` from filename (stem)
   - Parse JSONL content
   - Look up `project_dir` (history.jsonl → fallback to `cwd` in messages)
   - `index_messages()` (append-only via INSERT OR IGNORE)
   - Update stats
5. Bulk FTS sync (single query for all un-indexed messages)
6. Vacuum
7. Print final summary

## Progress Display

```
Syncing transcripts ━━━━━━━━━━━━━━━━━━━━ 50% 378/756 • 6,230 msgs • 42.1 MB
```

## Final Output

```
Synced 756 transcripts
Messages: 45,230 total (12,450 new)
Processed: 128.5 MB
FTS synced: 12,450 entries
```

## New Functions

```python
def load_session_project_map() -> dict[str, str]:
    """Load session_id -> project_dir mapping from history.jsonl"""

def find_all_transcripts() -> list[Path]:
    """Find all *.jsonl files in ~/.claude/projects/"""

def extract_project_dir_from_messages(messages: list[dict]) -> str:
    """Extract cwd from first message that has it (fallback)"""

def bulk_sync_fts(conn: sqlite3.Connection) -> int:
    """Sync all un-indexed messages to FTS, return count"""

def handle_sync() -> None:
    """Main sync handler with Rich progress"""
```

## Configuration Changes

- Cache size increased to 256MB (`PRAGMA cache_size = -262144`)

## Exit Codes

- 0: success
- 1: error (with message to stderr)
