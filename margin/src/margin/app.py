from __future__ import annotations

import logging
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from margin.models import SourceSnapshot
from margin.render import render_review_document
from margin.sources import (
    DEFAULT_MAX_FILE_BYTES,
    build_source_snapshot,
    checkout_github_repository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalBuildRequest:
    root: Path
    output_path: Path
    title: str | None = None
    open_browser: bool = False
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


@dataclass(frozen=True)
class GitHubBuildRequest:
    repository: str
    output_path: Path
    ref: str | None = None
    title: str | None = None
    open_browser: bool = False
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES


@dataclass(frozen=True)
class BuildResult:
    output_path: Path
    snapshot_id: str
    file_count: int


def build_local_review(request: LocalBuildRequest) -> BuildResult:
    """Build a review artifact from a local directory.

    Args:
        request: Local build request.
    """
    snapshot = build_source_snapshot(
        root=request.root,
        source_kind="local",
        source_label=str(request.root.resolve()),
        title=request.title,
        max_file_bytes=request.max_file_bytes,
    )
    return write_review_artifact(snapshot, request.output_path, request.open_browser)


def build_github_review(request: GitHubBuildRequest) -> BuildResult:
    """Build a review artifact from a GitHub repository checkout.

    Args:
        request: GitHub build request.
    """
    with checkout_github_repository(request.repository, request.ref) as checkout_path:
        label = request.repository if request.ref is None else f"{request.repository}@{request.ref}"
        snapshot = build_source_snapshot(
            root=checkout_path,
            source_kind="github",
            source_label=label,
            title=request.title,
            max_file_bytes=request.max_file_bytes,
        )
    return write_review_artifact(snapshot, request.output_path, request.open_browser)


def write_review_artifact(
    snapshot: SourceSnapshot,
    output_path: Path,
    open_browser: bool,
) -> BuildResult:
    """Render and write a review artifact.

    Args:
        snapshot: Source snapshot model.
        output_path: Destination HTML file.
        open_browser: Whether to open the browser after writing.
    """
    document = render_review_document(snapshot)
    resolved_output_path = output_path.resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_output_path.write_text(document, encoding="utf-8")
    logger.info("Wrote review artifact to %s", resolved_output_path)
    if open_browser:
        webbrowser.open(resolved_output_path.as_uri())
    return BuildResult(
        output_path=resolved_output_path,
        snapshot_id=snapshot.snapshot_id,
        file_count=len(snapshot.files),
    )
