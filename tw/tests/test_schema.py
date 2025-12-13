"""Tests for database schema initialization."""

import sqlite3
from pathlib import Path

from tw.schema import init_db


class TestInitDb:
    def test_creates_database_file(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)
        assert db_path.exists()

    def test_creates_issues_table(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='issues'")
        result = cursor.fetchone()
        conn.close()

        assert result is not None

    def test_issues_table_has_required_columns(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(issues)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()

        required_columns = {
            "id": "INTEGER",
            "uuid": "TEXT",
            "tw_id": "TEXT",
            "tw_type": "TEXT",
            "title": "TEXT",
            "tw_status": "TEXT",
            "tw_parent": "TEXT",
            "tw_body": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }

        for col_name, col_type in required_columns.items():
            assert col_name in columns, f"Column {col_name} not found in issues table"
            assert columns[col_name] == col_type, (
                f"Column {col_name} has type {columns[col_name]}, expected {col_type}"
            )

    def test_issues_table_has_primary_key(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(issues)")
        columns = cursor.fetchall()
        conn.close()

        id_col = next((col for col in columns if col[1] == "id"), None)
        assert id_col is not None
        assert id_col[5] == 1

    def test_issues_uuid_is_unique(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type='index' AND tbl_name='issues'"
        )
        indexes = cursor.fetchall()
        conn.close()

        has_uuid_unique = any(
            (sql and "uuid" in sql and "UNIQUE" in sql) or ("uuid" in name)
            for name, sql in indexes
        )
        assert has_uuid_unique, "UUID should have a unique index"

    def test_issues_tw_id_is_unique(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type='index' AND tbl_name='issues'"
        )
        indexes = cursor.fetchall()
        conn.close()

        has_tw_id_unique = any(
            (sql and "tw_id" in sql and "UNIQUE" in sql) or ("tw_id" in name)
            for name, sql in indexes
        )
        assert has_tw_id_unique, "TW_ID should have a unique index"

    def test_creates_annotations_table(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='annotations'"
        )
        result = cursor.fetchone()
        conn.close()

        assert result is not None

    def test_annotations_table_has_required_columns(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(annotations)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()

        required_columns = {
            "id": "INTEGER",
            "issue_id": "INTEGER",
            "type": "TEXT",
            "timestamp": "TEXT",
            "message": "TEXT",
        }

        for col_name, col_type in required_columns.items():
            assert col_name in columns, f"Column {col_name} not found in annotations table"
            assert columns[col_name] == col_type, (
                f"Column {col_name} has type {columns[col_name]}, expected {col_type}"
            )

    def test_annotations_has_foreign_key_to_issues(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_key_list(annotations)")
        fks = cursor.fetchall()
        conn.close()

        assert len(fks) > 0, "Annotations table should have foreign key constraints"
        issue_fk = next((fk for fk in fks if fk[2] == "issues"), None)
        assert issue_fk is not None, "Annotations should have foreign key to issues"

    def test_annotations_has_index_on_issue_id(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT sql FROM sqlite_master"
            " WHERE type='index' AND tbl_name='annotations'"
        )
        indexes = cursor.fetchall()
        conn.close()

        index_sqls = [idx[0] for idx in indexes]
        has_issue_id_index = any("issue_id" in sql for sql in index_sqls)
        assert has_issue_id_index, "Annotations should have an index on issue_id"

    def test_idempotent_initialization(self, temp_dir: Path) -> None:
        db_path = temp_dir / "test.db"
        init_db(db_path)
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "issues" in tables
        assert "annotations" in tables
