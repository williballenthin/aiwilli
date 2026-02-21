from __future__ import annotations

from collections import defaultdict
from datetime import timezone
from pathlib import Path

from memory_claw.domain.observations import ObservationBlock


def _ensure_observation_header(path: Path, extractor_name: str, prompt: str, model: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    date_part = path.stem
    path.write_text(
        "\n".join(
            [
                f"# Observations — {date_part}",
                f"# extractor: {extractor_name} ({prompt}, {model})",
                "",
            ]
        )
    )


def append_observation_blocks(
    root: Path,
    extractor_name: str,
    prompt: str,
    model: str,
    blocks: list[ObservationBlock],
) -> dict[str, int]:
    by_date: dict[str, list[ObservationBlock]] = defaultdict(list)
    for block in blocks:
        date_key = block.timestamp.astimezone(timezone.utc).date().isoformat()
        by_date[date_key].append(block)

    written: dict[str, int] = {}
    for date_key, date_blocks in by_date.items():
        file_path = root / "observations" / extractor_name / f"{date_key}.md"
        _ensure_observation_header(file_path, extractor_name, prompt, model)
        chunks: list[str] = []
        for block in date_blocks:
            stamp = block.timestamp.astimezone(timezone.utc).strftime("%H:%M")
            title = block.project or "unknown-project"
            chunks.append(f"## {stamp} — {title}")
            src_messages = ",".join(block.src_messages) if block.src_messages else "(none)"
            chunks.append(f"src: {block.src_path} msg:{src_messages}")
            chunks.append("")
            for item in block.items:
                chunks.append(f"- {item.importance} [{item.signal_type}] {item.summary} | why: {item.why}")
            chunks.append("")

        with file_path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(chunks))
            if chunks and not chunks[-1].endswith("\n"):
                handle.write("\n")
        written[date_key] = len(date_blocks)

    return written


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
    temp.replace(path)
