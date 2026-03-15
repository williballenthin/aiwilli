from pathlib import Path

from margin.sources import (
    build_git_checkout_command,
    build_git_fetch_command,
    build_github_clone_command,
    build_source_snapshot,
)
from tests.conftest import init_git_repository


def test_build_source_snapshot_respects_gitignore(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (root / "keep.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "ignored.txt").write_text("ignore me\n", encoding="utf-8")

    commit_sha = init_git_repository(root)

    snapshot = build_source_snapshot(
        root=root,
        source_kind="local",
        source_label=str(root),
        title=None,
        max_file_bytes=64_000,
    )

    paths = [file.path for file in snapshot.files]
    assert snapshot.snapshot_id == commit_sha
    assert "keep.py" in paths
    assert "ignored.txt" not in paths


def test_build_source_snapshot_hashes_non_git_directory(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.py").write_text("value = 1\n", encoding="utf-8")
    (root / "notes.txt").write_text("hello\n", encoding="utf-8")
    (root / "binary.bin").write_bytes(b"\x00\x01\x02")
    (root / ".venv").mkdir()
    (root / ".venv" / "skip.py").write_text("ignored = True\n", encoding="utf-8")

    snapshot = build_source_snapshot(
        root=root,
        source_kind="local",
        source_label=str(root),
        title="Plain",
        max_file_bytes=64_000,
    )

    paths = [file.path for file in snapshot.files]
    assert snapshot.snapshot_id.startswith("sha256:")
    assert paths == ["a.py", "notes.txt"]


def test_build_github_commands(tmp_path: Path) -> None:
    destination = tmp_path / "checkout"

    assert build_github_clone_command("acme/widgets", destination) == [
        "gh",
        "repo",
        "clone",
        "acme/widgets",
        str(destination),
        "--",
        "--depth=1",
    ]
    assert build_git_fetch_command(destination, "feature/demo") == [
        "git",
        "-C",
        str(destination),
        "fetch",
        "--depth=1",
        "origin",
        "feature/demo",
    ]
    assert build_git_checkout_command(destination) == [
        "git",
        "-C",
        str(destination),
        "checkout",
        "--detach",
        "FETCH_HEAD",
    ]
