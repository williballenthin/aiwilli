"""Database schema initialization."""

import sqlite3
from pathlib import Path


def init_db(db_path: Path) -> None:
    """Initialize the database with schema.

    Creates the issues and annotations tables with indexes if they don't exist.

    Args:
        db_path: Path to the SQLite database file.

    Raises:
        FileNotFoundError: If schema.sql cannot be found.
        sqlite3.DatabaseError: If database initialization fails.
    """
    schema_file = Path(__file__).parent / "schema.sql"
    schema_sql = schema_file.read_text()

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.executescript(schema_sql)
        conn.commit()
