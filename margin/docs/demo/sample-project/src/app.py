from pathlib import Path


def load_items(path: Path) -> list[str]:
    text = path.read_text()
    return [line.strip() for line in text.splitlines() if line.strip()]


def summarize_items(items: list[str]) -> str:
    return ", ".join(sorted(items))
