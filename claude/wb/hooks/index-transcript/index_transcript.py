#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich"]
# ///
"""Claude session transcript indexer hook."""

import json
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass, field
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

CLAUDE_PROJECTS_DIR = Path("~/.claude/projects").expanduser()
CLAUDE_HISTORY_PATH = Path("~/.claude/history.jsonl").expanduser()

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
        PRAGMA cache_size = -262144;
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
) -> int:
    """
    Index session and messages (Stop/SubagentStop behavior).

    Returns count of messages in transcript.
    """
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

    return len(messages)


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


def bulk_sync_fts(conn: sqlite3.Connection) -> int:
    """
    Sync all un-indexed messages to FTS.

    Returns count of entries added.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        cursor = conn.execute(
            """INSERT INTO messages_fts(uuid, session_id, message)
               SELECT uuid, session_id, message FROM messages
               WHERE uuid NOT IN (SELECT uuid FROM messages_fts)"""
        )
        count = cursor.rowcount
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise


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


def load_session_project_map() -> dict[str, str]:
    """Load session_id -> project_dir mapping from history.jsonl."""
    mapping: dict[str, str] = {}
    if not CLAUDE_HISTORY_PATH.exists():
        return mapping
    for line in CLAUDE_HISTORY_PATH.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            if sid := entry.get("sessionId"):
                mapping[sid] = entry.get("project", "")
        except json.JSONDecodeError:
            continue
    return mapping


def find_all_transcripts() -> list[Path]:
    """Find all *.jsonl files in ~/.claude/projects/."""
    if not CLAUDE_PROJECTS_DIR.exists():
        return []
    return sorted(CLAUDE_PROJECTS_DIR.rglob("*.jsonl"))


def extract_project_dir_from_messages(messages: list[dict]) -> str:
    """Extract cwd from first message that has it (fallback)."""
    for msg in messages:
        if cwd := msg.get("cwd"):
            return cwd
    return ""


@dataclass
class SyncStats:
    transcripts_processed: int = 0
    messages_total: int = 0
    bytes_processed: int = 0
    errors: list[str] = field(default_factory=list)


def handle_sync() -> None:
    """Main sync handler with Rich progress."""
    from rich.console import Console
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        TextColumn,
        TimeElapsedColumn,
    )

    console = Console()

    transcript_files = find_all_transcripts()
    if not transcript_files:
        console.print("[yellow]No transcript files found[/yellow]")
        return

    session_project_map = load_session_project_map()
    stats = SyncStats()
    conn = get_connection()

    def format_bytes(b: int) -> str:
        if b < 1024:
            return f"{b} B"
        elif b < 1024 * 1024:
            return f"{b / 1024:.1f} KB"
        else:
            return f"{b / (1024 * 1024):.1f} MB"

    try:
        with Progress(
            TextColumn("[bold blue]Syncing"),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("•"),
            TextColumn("[green]{task.fields[msgs]} msgs"),
            TextColumn("•"),
            TextColumn("[cyan]{task.fields[size]}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "sync",
                total=len(transcript_files),
                msgs=0,
                size="0 B",
            )

            for transcript_path in transcript_files:
                try:
                    session_id = transcript_path.stem
                    file_size = transcript_path.stat().st_size

                    project_dir = session_project_map.get(session_id, "")
                    if not project_dir:
                        try:
                            _, messages = parse_transcript(transcript_path)
                            project_dir = extract_project_dir_from_messages(messages)
                        except Exception:
                            project_dir = ""

                    msg_count = index_messages(conn, session_id, transcript_path, project_dir)

                    stats.transcripts_processed += 1
                    stats.messages_total += msg_count
                    stats.bytes_processed += file_size

                except Exception as e:
                    stats.errors.append(f"{transcript_path.name}: {e}")
                    logger.exception(f"Error processing {transcript_path}")

                progress.update(
                    task,
                    advance=1,
                    msgs=stats.messages_total,
                    size=format_bytes(stats.bytes_processed),
                )

        console.print()
        console.print(f"[bold green]Synced {stats.transcripts_processed} transcripts[/bold green]")
        console.print(f"Messages: {stats.messages_total:,}")
        console.print(f"Processed: {format_bytes(stats.bytes_processed)}")

        console.print("[dim]Syncing FTS index...[/dim]")
        fts_count = bulk_sync_fts(conn)
        console.print(f"FTS synced: {fts_count:,} entries")

        console.print("[dim]Running vacuum...[/dim]")
        run_vacuum(conn)
        console.print("[green]Vacuum complete[/green]")

        if stats.errors:
            console.print()
            console.print(f"[yellow]Encountered {len(stats.errors)} error(s):[/yellow]")
            for err in stats.errors[:10]:
                console.print(f"  [dim]• {err}[/dim]")
            if len(stats.errors) > 10:
                console.print(f"  [dim]... and {len(stats.errors) - 10} more[/dim]")

    finally:
        conn.close()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "sync":
        setup_logging()
        handle_sync()
        return

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
