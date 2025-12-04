"""Configuration utilities for tw."""

import os


def get_project() -> str:
    """Get project name from environment."""
    return os.environ.get(
        "TW_PROJECT_NAME", os.environ.get("PROJECT_NAME", "default")
    )


def get_prefix() -> str:
    """Get project prefix from environment."""
    return os.environ.get(
        "TW_PROJECT_PREFIX", os.environ.get("PROJECT_PREFIX", "DEFAULT")
    )
