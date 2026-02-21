from __future__ import annotations

from pathlib import Path

from memory_claw.domain.messages import NormalizedMessage

_DOC_CANDIDATES = [
    "README.md",
    "README",
    "AGENTS.md",
    "agents.md",
    "CLAUDE.md",
    "claude.md",
]


def resolve_project_root_from_chunk(chunk: list[NormalizedMessage]) -> Path | None:
    """Best-effort project root from message cwd fields."""
    for msg in chunk:
        cwd = msg.cwd
        if not cwd:
            continue
        candidate = Path(cwd).expanduser()
        if not candidate.exists():
            continue
        start = candidate if candidate.is_dir() else candidate.parent
        root = _find_repo_root(start)
        return root or start
    return None


def _find_repo_root(start: Path) -> Path | None:
    current = start
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def load_project_docs_context(project_root: Path, max_chars: int = 12000) -> str:
    """Load README/AGENTS/CLAUDE style docs as compact context.

    Includes project root docs, and then ancestor AGENTS/CLAUDE docs up to filesystem root.
    """
    sections: list[str] = []
    remaining = max(0, max_chars)

    # First read key docs in project root.
    remaining = _collect_docs_for_dir(project_root, sections, remaining)

    # Then look for AGENTS/CLAUDE docs in parent dirs for broader guidance.
    parent = project_root.parent
    while remaining > 0 and parent != parent.parent:
        remaining = _collect_docs_for_dir(parent, sections, remaining, names=["AGENTS.md", "CLAUDE.md"])
        parent = parent.parent

    text = "\n\n".join(section for section in sections if section.strip())
    return text[:max_chars]


def _collect_docs_for_dir(
    directory: Path,
    sections: list[str],
    remaining_chars: int,
    names: list[str] | None = None,
) -> int:
    candidates = names or _DOC_CANDIDATES
    remaining = remaining_chars

    for name in candidates:
        if remaining <= 0:
            break
        path = directory / name
        if not path.exists() or not path.is_file():
            continue

        raw = path.read_text(errors="ignore")
        chunk = raw[: min(len(raw), max(500, remaining - 120))]
        label = f"## Context file: {path}"
        section = f"{label}\n{chunk}"
        sections.append(section)
        remaining -= len(section)

    return remaining
