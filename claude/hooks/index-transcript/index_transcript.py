#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Claude session transcript indexer hook."""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(
    os.environ.get(
        "CLAUDE_TRANSCRIPT_DB",
        "~/.local/share/claude-transcripts/db.sqlite",
    )
).expanduser().parent

DB_PATH = DATA_DIR / "db.sqlite"
LOG_PATH = DATA_DIR / "indexer.log"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    content TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS messages (
    uuid TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    message_index INTEGER NOT NULL,
    message TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, message_index);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    uuid,
    session_id,
    message,
    tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS session_metadata (
    session_id TEXT PRIMARY KEY,
    project_dir TEXT,
    transcript_path TEXT,
    first_timestamp TEXT,
    last_timestamp TEXT,
    message_count INTEGER,
    indexed_at TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
) STRICT;
"""

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        PRAGMA journal_mode = WAL;
        PRAGMA busy_timeout = 5000;
        PRAGMA synchronous = NORMAL;
        PRAGMA cache_size = -64000;
        PRAGMA foreign_keys = true;
        PRAGMA temp_store = memory;
        PRAGMA auto_vacuum = INCREMENTAL;
    """)
    conn.executescript(SCHEMA)
    return conn


def parse_transcript(transcript_path: Path) -> tuple[str, list[dict]]:
    """
    Parse JSONL transcript file.

    Returns (full_content, list_of_messages).
    """
    content = transcript_path.read_text()
    messages = []
    for line in content.strip().split("\n"):
        if line:
            messages.append(json.loads(line))
    return content, messages


def index_messages(
    conn: sqlite3.Connection,
    session_id: str,
    transcript_path: Path,
    project_dir: str,
) -> None:
    """Index session and messages (Stop/SubagentStop behavior)."""
    content, messages = parse_transcript(transcript_path)

    timestamps = [m.get("timestamp") for m in messages if m.get("timestamp")]
    first_timestamp = min(timestamps) if timestamps else None
    last_timestamp = max(timestamps) if timestamps else None

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, content) VALUES (?, ?)",
            (session_id, content),
        )

        for idx, msg in enumerate(messages):
            uuid = msg.get("uuid")
            if not uuid:
                continue
            message_content = json.dumps(msg.get("message", {}))
            conn.execute(
                "INSERT OR IGNORE INTO messages (uuid, session_id, message_index, message) VALUES (?, ?, ?, ?)",
                (uuid, session_id, idx, message_content),
            )

        conn.execute(
            """INSERT OR REPLACE INTO session_metadata
               (session_id, project_dir, transcript_path, first_timestamp, last_timestamp, message_count, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                project_dir,
                str(transcript_path),
                first_timestamp,
                last_timestamp,
                len(messages),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise


def sync_fts(conn: sqlite3.Connection, session_id: str) -> None:
    """Sync FTS index for a session (SessionEnd behavior)."""
    conn.execute(
        """INSERT INTO messages_fts(uuid, session_id, message)
           SELECT m.uuid, m.session_id, m.message
           FROM messages m
           WHERE m.session_id = ?
             AND m.uuid NOT IN (SELECT uuid FROM messages_fts WHERE session_id = ?)""",
        (session_id, session_id),
    )
    conn.commit()


def run_vacuum(conn: sqlite3.Connection) -> None:
    """Run incremental vacuum (SessionStart behavior)."""
    conn.execute("PRAGMA incremental_vacuum")
    conn.commit()


def handle_stop(hook_input: dict) -> None:
    """Handle Stop and SubagentStop events."""
    session_id = hook_input.get("session_id")
    transcript_path = hook_input.get("transcript_path")
    project_dir = hook_input.get("cwd", "")

    if not session_id or not transcript_path:
        logger.warning("Missing session_id or transcript_path in hook input")
        return

    path = Path(transcript_path)
    if not path.exists():
        logger.warning(f"Transcript path does not exist: {path}")
        return

    conn = get_connection()
    try:
        index_messages(conn, session_id, path, project_dir)
        logger.info(f"Indexed session {session_id}")
    finally:
        conn.close()


def handle_session_end(hook_input: dict) -> None:
    """Handle SessionEnd event (index + FTS sync)."""
    session_id = hook_input.get("session_id")
    transcript_path = hook_input.get("transcript_path")
    project_dir = hook_input.get("cwd", "")

    if not session_id or not transcript_path:
        logger.warning("Missing session_id or transcript_path in hook input")
        return

    path = Path(transcript_path)
    if not path.exists():
        logger.warning(f"Transcript path does not exist: {path}")
        return

    conn = get_connection()
    try:
        index_messages(conn, session_id, path, project_dir)
        sync_fts(conn, session_id)
        logger.info(f"Indexed session {session_id} with FTS sync")
    finally:
        conn.close()


def handle_session_start(hook_input: dict) -> None:
    """Handle SessionStart event (vacuum)."""
    conn = get_connection()
    try:
        run_vacuum(conn)
        logger.debug("Ran incremental vacuum")
    finally:
        conn.close()


def main() -> None:
    setup_logging()

    try:
        raw_input = sys.stdin.read()
        hook_input = json.loads(raw_input) if raw_input.strip() else {}

        event = hook_input.get("hook_event_name", "")
        logger.debug(f"Received event: {event}")

        if event == "SessionStart":
            handle_session_start(hook_input)
        elif event == "SessionEnd":
            handle_session_end(hook_input)
        elif event in ("Stop", "SubagentStop"):
            handle_stop(hook_input)
        else:
            logger.warning(f"Unknown event: {event}")
    except Exception:
        logger.exception("Error processing hook")


if __name__ == "__main__":
    main()
    sys.exit(0)
