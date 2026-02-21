from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def ensure_repo_initialized(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if (root / ".git").exists():
        return
    _run_git(root, "init")


def commit_if_dirty(root: Path, message: str, paths: list[str] | None = None) -> bool:
    if paths:
        _run_git(root, "add", *paths)
    else:
        _run_git(root, "add", "-A")

    status = _run_git(root, "status", "--porcelain")
    if not status.stdout.strip():
        return False

    commit = _run_git(root, "commit", "-m", message)
    return commit.returncode == 0
