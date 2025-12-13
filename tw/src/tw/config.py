"""Configuration utilities for tw."""

import os
from pathlib import Path


class ConfigError(Exception):
    """Raised when a required configuration is missing or invalid."""


DEFAULT_DB_PATH = Path.home() / ".local" / "state" / "tw" / "tw.db"


def get_db_path() -> Path:
    """Get database path from TW_DB_PATH or default location.

    Returns:
        Path object for the database file. Uses TW_DB_PATH if set,
        otherwise defaults to ~/.local/state/tw/tw.db.
    """
    db_path = os.environ.get("TW_DB_PATH")
    if db_path:
        return Path(db_path)
    return DEFAULT_DB_PATH


def get_prefix() -> str:
    """Get project prefix from environment.

    Checks TW_PREFIX first, then falls back to TW_PROJECT_PREFIX for
    backwards compatibility.

    Returns:
        Project prefix string.

    Raises:
        ConfigError: If neither TW_PREFIX nor TW_PROJECT_PREFIX is set.
    """
    prefix = os.environ.get("TW_PREFIX")
    if prefix:
        return prefix

    prefix = os.environ.get("TW_PROJECT_PREFIX")
    if prefix:
        return prefix

    raise ConfigError(
        "Neither TW_PREFIX nor TW_PROJECT_PREFIX environment variable is set"
    )
