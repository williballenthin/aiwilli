"""SQLite backend for issue tracking."""

import logging
import sqlite3
import uuid as uuid_module
from datetime import UTC, datetime
from pathlib import Path

from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType

logger = logging.getLogger(__name__)


class SqliteBackend:
    """SQLite backend for tw issue tracker."""

    def __init__(self, db_path: Path | str) -> None:
        """Initialize SQLite backend.

        Args:
            db_path: Path to the SQLite database file.

        Raises:
            sqlite3.DatabaseError: If database initialization fails.
        """
        self._db_path = Path(db_path)
        from tw.schema import init_db

        init_db(self._db_path)

    def get_all_issues(self) -> list[Issue]:
        """Get all issues.

        Returns:
            List of all issues.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, uuid, tw_id, tw_type, title, tw_status, "
                "tw_parent, tw_body, created_at, updated_at FROM issues"
            )
            rows = cursor.fetchall()

            issues = []
            for row in rows:
                annotations = self._get_annotations_for_issue_id(conn, row["id"])
                tw_refs = self._get_refs_for_issue_id(conn, row["id"])
                created_at = datetime.strptime(row["created_at"], "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=UTC
                )
                updated_at = datetime.strptime(row["updated_at"], "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=UTC
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

    def get_issue(self, tw_id: str) -> Issue | None:
        """Get a specific issue by ID.

        Args:
            tw_id: The issue ID

        Returns:
            The Issue object or None if not found.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, uuid, tw_id, tw_type, title, tw_status, "
                "tw_parent, tw_body, created_at, updated_at FROM issues WHERE tw_id = ?",
                (tw_id,),
            )
            row = cursor.fetchone()

            if row is None:
                return None

            annotations = self._get_annotations_for_issue_id(conn, row["id"])
            tw_refs = self._get_refs_for_issue_id(conn, row["id"])
            created_at = datetime.strptime(row["created_at"], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=UTC
            )
            updated_at = datetime.strptime(row["updated_at"], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=UTC
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

    def save_issue(self, issue: Issue) -> None:
        """Save or update an issue.

        Args:
            issue: The issue to save

        Raises:
            RuntimeError: If the save operation fails.
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
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
                        "INSERT INTO issues (uuid, tw_id, tw_type, title, tw_status, "
                        "tw_parent, tw_body, created_at, updated_at) "
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

                    for annotation in issue.annotations or []:
                        cursor.execute(
                            "INSERT INTO annotations (issue_id, type, timestamp, message) "
                            "VALUES (?, ?, ?, ?)",
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
                                "INSERT INTO issue_refs (source_issue_id, target_tw_id) "
                                "VALUES (?, ?)",
                                (issue_id, ref),
                            )

                conn.commit()
        except sqlite3.DatabaseError as e:
            logger.error(f"Failed to save issue {issue.id}: {e}")
            raise RuntimeError(f"Failed to save issue {issue.id}") from e

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
                conn.execute("PRAGMA foreign_keys = ON")
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
            conn.execute("PRAGMA foreign_keys = ON")
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

    def get_all_ids(self) -> list[str]:
        """Get all issue IDs.

        Returns:
            List of all issue IDs.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute("SELECT tw_id FROM issues")
            rows = cursor.fetchall()
            return [row[0] for row in rows]

    def _get_annotations_for_issue_id(
        self, conn: sqlite3.Connection, issue_id: int
    ) -> list[Annotation]:
        """Get all annotations for an issue (internal helper).

        Args:
            conn: Active database connection
            issue_id: The internal issue ID

        Returns:
            List of annotations for the issue.
        """
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT type, timestamp, message FROM annotations WHERE issue_id = ? ORDER BY id",
            (issue_id,),
        )
        rows = cursor.fetchall()

        annotations = []
        for row in rows:
            timestamp = datetime.strptime(row["timestamp"], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=UTC
            )
            annotation = Annotation(
                type=AnnotationType(row["type"]),
                timestamp=timestamp,
                message=row["message"],
            )
            annotations.append(annotation)

        return annotations

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
            "SELECT target_tw_id FROM issue_refs "
            "WHERE source_issue_id = ? AND target_tw_id IS NOT NULL",
            (issue_id,),
        )
        rows = cursor.fetchall()
        return [row[0] for row in rows]

    def get_issues_referencing(self, tw_id: str) -> list[str]:
        """Get all issue IDs that reference the given issue.

        Args:
            tw_id: The target issue ID

        Returns:
            List of issue IDs that reference this issue.
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.cursor()
            cursor.execute(
                "SELECT i.tw_id FROM issue_refs r "
                "JOIN issues i ON r.source_issue_id = i.id "
                "WHERE r.target_tw_id = ?",
                (tw_id,),
            )
            rows = cursor.fetchall()
            return [row[0] for row in rows]
