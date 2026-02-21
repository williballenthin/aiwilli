from __future__ import annotations

from pathlib import Path


def load_prompt(root: Path, relative_prompt_path: str) -> str:
    prompt_path = root / relative_prompt_path
    if not prompt_path.exists():
        return ""
    return prompt_path.read_text()
