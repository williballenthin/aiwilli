"""Shared pytest fixtures."""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from tw.backend import SqliteBackend
from tw.service import IssueService


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for test-local resources."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)




@pytest.fixture
def sqlite_env(temp_dir: Path) -> Generator[dict[str, str], None, None]:
    """Provide isolated SQLite environment for testing.

    Creates a temporary database and sets required environment variables.
    """
    db_path = temp_dir / "tw.db"

    env = os.environ.copy()
    env["TW_DB_PATH"] = str(db_path)
    env["TW_PREFIX"] = "TEST"

    yield env


@pytest.fixture
def sqlite_service(temp_dir: Path) -> IssueService:
    """Provide an IssueService with SqliteBackend for testing.

    Creates a temporary SQLite database and initializes the service.
    """
    db_path = temp_dir / "test.db"
    backend = SqliteBackend(db_path)
    return IssueService(backend, prefix="TEST")
