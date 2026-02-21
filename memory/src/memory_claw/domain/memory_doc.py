from __future__ import annotations

from datetime import datetime, timezone


def default_global_memory_markdown() -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return "\n".join(
        [
            "# Global Memory",
            "",
            f"Last updated: {now}",
            "",
            "## Durable Preferences and Patterns",
            "- (none yet)",
            "",
            "## Active Context",
            "- (none yet)",
            "",
            "## Recent Observations",
            "- (none yet)",
            "",
        ]
    )


def extract_section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    marker = f"## {heading}"
    try:
        start = lines.index(marker)
    except ValueError:
        return []

    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body.append(line)

    while body and body[0] == "":
        body.pop(0)
    while body and body[-1] == "":
        body.pop()
    return body
