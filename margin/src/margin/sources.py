from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pathspec import PathSpec

from margin.models import SourceFile, SourceSnapshot

logger = logging.getLogger(__name__)

DEFAULT_MAX_FILE_BYTES = 256 * 1024
EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


class SourceBuildError(RuntimeError):
    pass


class SkipFileError(SourceBuildError):
    pass


def build_source_snapshot(
    root: Path,
    source_kind: Literal["local", "github"],
    source_label: str,
    title: str | None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> SourceSnapshot:
    """Build a normalized snapshot from a directory.

    Args:
        root: Directory to scan.
        source_kind: Snapshot source type.
        source_label: Human-readable source label for the UI.
        title: Optional review title override.
        max_file_bytes: Maximum file size to include.

    Raises:
        SourceBuildError: If the root is invalid or snapshot generation fails.
    """
    resolved_root = root.resolve()
    if not resolved_root.exists() or not resolved_root.is_dir():
        raise SourceBuildError(f"source path is not a directory: {root}")

    files: list[SourceFile] = []
    for relative_path in collect_source_files(resolved_root):
        try:
            files.append(
                build_source_file(
                    root=resolved_root,
                    relative_path=relative_path,
                    max_file_bytes=max_file_bytes,
                )
            )
        except SkipFileError as error:
            logger.debug("Skipping %s: %s", relative_path, error)

    snapshot_id = get_git_head_commit(resolved_root) or calculate_snapshot_hash(files)
    review_title = title or f"Margin review — {source_label}"
    return SourceSnapshot(
        title=review_title,
        source_kind=source_kind,
        source_label=source_label,
        snapshot_id=snapshot_id,
        generated_at=datetime.now(tz=UTC),
        files=files,
    )


def collect_source_files(root: Path) -> list[Path]:
    """Collect relative file paths for a review snapshot.

    Args:
        root: Directory to scan.

    Returns:
        Sorted relative file paths.
    """
    if is_git_repository_root(root):
        return collect_git_files(root)
    return collect_walk_files(root)


def build_source_file(root: Path, relative_path: Path, max_file_bytes: int) -> SourceFile:
    """Read and validate a source file.

    Args:
        root: Snapshot root.
        relative_path: File path relative to the root.
        max_file_bytes: Maximum file size to include.

    Raises:
        SkipFileError: If the file should not be included.
    """
    absolute_path = root / relative_path
    if not absolute_path.is_file():
        raise SkipFileError("not a regular file")

    file_size = absolute_path.stat().st_size
    if file_size > max_file_bytes:
        raise SkipFileError(f"file exceeds size limit ({file_size} bytes)")

    data = absolute_path.read_bytes()
    if is_binary_data(data):
        raise SkipFileError("file appears to be binary")

    text = data.decode("utf-8", errors="replace")
    digest = hashlib.sha256(data).hexdigest()
    return SourceFile(path=relative_path.as_posix(), text=text, content_digest=digest)


def is_git_repository_root(root: Path) -> bool:
    """Return whether a path is the top-level git directory.

    Args:
        root: Directory to test.
    """
    try:
        git_root = run_text_command(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"]
        ).strip()
    except SourceBuildError:
        return False
    return Path(git_root).resolve() == root.resolve()


def collect_git_files(root: Path) -> list[Path]:
    """Collect tracked and untracked files from a git repository root.

    Args:
        root: Git repository root.

    Raises:
        SourceBuildError: If git file enumeration fails.
    """
    output = run_binary_command(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ]
    )
    paths = [Path(item.decode("utf-8")) for item in output.split(b"\x00") if item]
    return sorted(paths)


def collect_walk_files(root: Path) -> list[Path]:
    """Collect files from a non-git directory tree.

    Args:
        root: Directory root.
    """
    ignore_spec = load_root_gitignore(root)
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if should_exclude_path(relative_path):
            continue
        if ignore_spec is not None and ignore_spec.match_file(relative_path.as_posix()):
            continue
        paths.append(relative_path)
    return sorted(paths)


def load_root_gitignore(root: Path) -> PathSpec | None:
    """Load a root `.gitignore` file for non-git walks.

    Args:
        root: Directory root.
    """
    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        return None
    patterns = gitignore_path.read_text(encoding="utf-8").splitlines()
    return PathSpec.from_lines("gitwildmatch", patterns)


def should_exclude_path(relative_path: Path) -> bool:
    """Return whether a relative path should be skipped during fallback walking.

    Args:
        relative_path: Relative path beneath the snapshot root.
    """
    return any(part in EXCLUDED_DIR_NAMES for part in relative_path.parts)


def is_binary_data(data: bytes) -> bool:
    """Return whether bytes look binary.

    Args:
        data: File bytes.
    """
    return b"\x00" in data[:8192]


def get_git_head_commit(root: Path) -> str | None:
    """Return the current git commit SHA for a repository root.

    Args:
        root: Directory to inspect.
    """
    if not is_git_repository_root(root):
        return None
    return run_text_command(["git", "-C", str(root), "rev-parse", "HEAD"]).strip()


def calculate_snapshot_hash(files: list[SourceFile]) -> str:
    """Calculate a deterministic snapshot hash.

    Args:
        files: Included source files.
    """
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(file.content_digest.encode("utf-8"))
        digest.update(b"\x00")
    return f"sha256:{digest.hexdigest()}"


def build_github_clone_command(repository: str, destination: Path) -> list[str]:
    """Build the initial `gh repo clone` command.

    Args:
        repository: GitHub repository identifier.
        destination: Destination directory.
    """
    return ["gh", "repo", "clone", repository, str(destination), "--", "--depth=1"]


def build_git_fetch_command(destination: Path, ref: str) -> list[str]:
    """Build the command that fetches a specific ref into a clone.

    Args:
        destination: Checkout directory.
        ref: Ref to fetch.
    """
    return ["git", "-C", str(destination), "fetch", "--depth=1", "origin", ref]


def build_git_checkout_command(destination: Path) -> list[str]:
    """Build the command that detaches to `FETCH_HEAD`.

    Args:
        destination: Checkout directory.
    """
    return ["git", "-C", str(destination), "checkout", "--detach", "FETCH_HEAD"]


@contextmanager
def checkout_github_repository(repository: str, ref: str | None) -> Iterator[Path]:
    """Create a temporary GitHub checkout.

    Args:
        repository: GitHub repository identifier.
        ref: Optional branch, tag, or commit to fetch after clone.

    Yields:
        Path to the checkout directory.

    Raises:
        SourceBuildError: If the checkout fails.
    """
    with tempfile.TemporaryDirectory(prefix="margin-") as temp_dir:
        checkout_path = Path(temp_dir) / "repo"
        run_text_command(build_github_clone_command(repository, checkout_path))
        if ref is not None:
            run_text_command(build_git_fetch_command(checkout_path, ref))
            run_text_command(build_git_checkout_command(checkout_path))
        yield checkout_path


def run_text_command(command: list[str]) -> str:
    """Run a command and return text output.

    Args:
        command: Command argv.

    Raises:
        SourceBuildError: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise SourceBuildError(f"{' '.join(command)}: {error_text}")
    return result.stdout


def run_binary_command(command: list[str]) -> bytes:
    """Run a command and return binary output.

    Args:
        command: Command argv.

    Raises:
        SourceBuildError: If the command fails.
    """
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        error_text = result.stderr.decode("utf-8", errors="replace").strip()
        if not error_text:
            error_text = result.stdout.decode("utf-8", errors="replace").strip()
        raise SourceBuildError(f"{' '.join(command)}: {error_text or 'command failed'}")
    return result.stdout
