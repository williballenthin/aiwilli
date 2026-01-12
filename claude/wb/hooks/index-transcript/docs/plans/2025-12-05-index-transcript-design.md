# Claude Session Indexer Hook Design

## Overview

A Claude Code hook that indexes session transcripts into a SQLite database for search and analysis.

**Hook events:**
- **Stop / SubagentStop**: Index messages into `messages` table
- **SessionEnd**: Sync FTS index for new messages
- **SessionStart**: Run incremental vacuum

## Database

**Location:** `~/.local/share/claude-transcripts/db.sqlite`
**Override:** `CLAUDE_TRANSCRIPT_DB` environment variable

### Schema

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    content TEXT NOT NULL
) STRICT;

CREATE TABLE messages (
    uuid TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) STRICT;

CREATE INDEX idx_messages_session ON messages(session_id, message_index);

CREATE VIRTUAL TABLE messages_fts USING fts5(
    uuid,
    session_id,
    message,
    tokenize='trigram'
);

CREATE TABLE session_metadata (
    session_id TEXT PRIMARY KEY,
    project_dir TEXT,
    transcript_path TEXT,
    first_timestamp TEXT,
    last_timestamp TEXT,
    message_count INTEGER,
    indexed_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) STRICT;
```

### SQLite Settings

```python
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;  # ~64MB (negative = KB)
PRAGMA foreign_keys = true;
PRAGMA temp_store = memory;
PRAGMA auto_vacuum = INCREMENTAL;
```

Use `BEGIN IMMEDIATE` transactions.

## Hook Behavior by Event

### Stop / SubagentStop

1. Read JSON from stdin, extract `session_id`, `transcript_path`
2. Read transcript JSONL file
3. `BEGIN IMMEDIATE` transaction:
   - Upsert into `sessions` (full transcript content)
   - `INSERT OR IGNORE` into `messages` (new messages only, UUID PK dedupes)
   - Upsert into `session_metadata`
4. Commit
5. Exit 0

### SessionEnd

1. Same as Stop, plus:
2. Sync FTS index for this session:
   ```sql
   INSERT INTO messages_fts(uuid, session_id, message)
   SELECT m.uuid, m.session_id, m.message
   FROM messages m
   WHERE m.session_id = ?
     AND m.uuid NOT IN (SELECT uuid FROM messages_fts WHERE session_id = ?);
   ```
3. Exit 0

### SessionStart

1. Run incremental vacuum (non-blocking maintenance):
   ```sql
   PRAGMA incremental_vacuum;
   ```
2. Exit 0

## Duplicate Handling

- **sessions table:** Upsert (replace with latest transcript content)
- **messages table:** Append new only (`INSERT OR IGNORE` using UUID as PK)
- **session_metadata table:** Upsert (replace with latest)
- **messages_fts table:** Append new only (checked via `NOT IN` on SessionEnd)

## Hook Configuration

**File:** `hooks/hooks.json`

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run \"${CLAUDE_PLUGIN_ROOT}/hooks/index-transcript/index_transcript.py\"",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run \"${CLAUDE_PLUGIN_ROOT}/hooks/index-transcript/index_transcript.py\"",
            "timeout": 30
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run \"${CLAUDE_PLUGIN_ROOT}/hooks/index-transcript/index_transcript.py\"",
            "timeout": 30
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "uv run \"${CLAUDE_PLUGIN_ROOT}/hooks/index-transcript/index_transcript.py\"",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

## Hook Input (JSON via stdin)

```json
{
  "session_id": "abc123...",
  "transcript_path": "/path/to/project/session.jsonl",
  "cwd": "/path/to/project",
  "hook_event_name": "Stop"
}
```

## Error Handling

- Silent failure (don't interrupt Claude)
- Log errors to `~/.local/share/claude-transcripts/indexer.log`
- Always exit 0

## File Structure

```
plugin-root/
├── hooks/
│   ├── hooks.json
│   └── index-transcript/
│       ├── index_transcript.py    # PEP 723 script (no external deps)
│       └── docs/plans/
│           └── 2025-12-05-index-transcript-design.md

~/.local/share/claude-transcripts/
├── db.sqlite
└── indexer.log
```

## Future

Potential Rust port for performance.
