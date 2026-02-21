from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from memory_claw.domain.messages import NormalizedMessage


@dataclass(slots=True)
class SessionRow:
    source: str
    session_id: str
    transcript_path: str
    project: str | None
    cwd: str | None
    last_ingested_line: int


class StateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_session(
        self,
        source: str,
        session_id: str,
        transcript_path: str,
        project: str | None,
        cwd: str | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO sessions (source, session_id, transcript_path, project, cwd, first_seen_at, last_seen_at, last_ingested_line)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(source, session_id) DO UPDATE SET
                transcript_path=excluded.transcript_path,
                project=COALESCE(excluded.project, sessions.project),
                cwd=COALESCE(excluded.cwd, sessions.cwd),
                last_seen_at=excluded.last_seen_at
            """,
            (source, session_id, transcript_path, project, cwd, now, now),
        )

    def get_session_cursor(self, source: str, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT last_ingested_line FROM sessions WHERE source = ? AND session_id = ?",
            (source, session_id),
        ).fetchone()
        return int(row[0]) if row else 0

    def update_session_cursor(self, source: str, session_id: str, line_no: int) -> None:
        self.conn.execute(
            "UPDATE sessions SET last_ingested_line = ?, last_seen_at = ? WHERE source = ? AND session_id = ?",
            (line_no, datetime.now(timezone.utc).isoformat(), source, session_id),
        )

    def upsert_message(self, msg: NormalizedMessage) -> None:
        self.conn.execute(
            """
            INSERT INTO messages (
                source, session_id, source_message_id, line_no, role, ts,
                project, cwd, transcript_path, content_text, raw_type, is_sidechain
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, session_id, source_message_id) DO UPDATE SET
                line_no=excluded.line_no,
                role=excluded.role,
                ts=excluded.ts,
                project=excluded.project,
                cwd=excluded.cwd,
                transcript_path=excluded.transcript_path,
                content_text=excluded.content_text,
                raw_type=excluded.raw_type,
                is_sidechain=excluded.is_sidechain
            """,
            (
                msg.source,
                msg.session_id,
                msg.source_message_id,
                msg.line_no,
                msg.role,
                msg.timestamp.isoformat(),
                msg.project,
                msg.cwd,
                msg.transcript_path,
                msg.content_text,
                msg.raw_type,
                int(msg.is_sidechain),
            ),
        )

    def list_sessions(self) -> list[SessionRow]:
        rows = self.conn.execute(
            "SELECT source, session_id, transcript_path, project, cwd, last_ingested_line FROM sessions"
        ).fetchall()
        return [SessionRow(**dict(row)) for row in rows]

    def get_messages_in_line_range(
        self,
        source: str,
        session_id: str,
        start_line_inclusive: int,
        end_line_inclusive: int,
    ) -> list[NormalizedMessage]:
        rows = self.conn.execute(
            """
            SELECT source, session_id, source_message_id, role, ts, project, cwd, content_text,
                   transcript_path, raw_type, line_no, is_sidechain
            FROM messages
            WHERE source = ?
              AND session_id = ?
              AND line_no >= ?
              AND line_no <= ?
            ORDER BY line_no ASC
            """,
            (source, session_id, start_line_inclusive, end_line_inclusive),
        ).fetchall()

        messages: list[NormalizedMessage] = []
        for row in rows:
            messages.append(
                NormalizedMessage(
                    source=row["source"],
                    session_id=row["session_id"],
                    source_message_id=row["source_message_id"],
                    role=row["role"],
                    timestamp=datetime.fromisoformat(row["ts"]),
                    project=row["project"],
                    cwd=row["cwd"],
                    content_text=row["content_text"],
                    transcript_path=row["transcript_path"],
                    raw_type=row["raw_type"],
                    line_no=row["line_no"],
                    is_sidechain=bool(row["is_sidechain"]),
                )
            )
        return messages

    def get_extractor_cursor(self, extractor_name: str, source: str, session_id: str) -> int:
        row = self.conn.execute(
            """
            SELECT last_processed_line
            FROM extractor_progress
            WHERE extractor_name = ? AND source = ? AND session_id = ?
            """,
            (extractor_name, source, session_id),
        ).fetchone()
        return int(row[0]) if row else 0

    def set_extractor_cursor(
        self,
        extractor_name: str,
        source: str,
        session_id: str,
        line_no: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO extractor_progress (extractor_name, source, session_id, last_processed_line, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(extractor_name, source, session_id) DO UPDATE SET
                last_processed_line=excluded.last_processed_line,
                updated_at=excluded.updated_at
            """,
            (extractor_name, source, session_id, line_no, now),
        )

    def set_reflector_state(self, last_reflected_obs_date: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """
            INSERT INTO reflector_state(id, last_reflected_at, last_reflected_obs_date)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                last_reflected_at=excluded.last_reflected_at,
                last_reflected_obs_date=COALESCE(excluded.last_reflected_obs_date, reflector_state.last_reflected_obs_date)
            """,
            (now, last_reflected_obs_date),
        )

    def fetch_counts(self) -> dict[str, int]:
        sessions = self.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        messages = self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        extractor_progress = self.conn.execute("SELECT COUNT(*) FROM extractor_progress").fetchone()[0]
        return {
            "sessions": int(sessions),
            "messages": int(messages),
            "extractor_progress": int(extractor_progress),
        }

    def commit(self) -> None:
        self.conn.commit()
