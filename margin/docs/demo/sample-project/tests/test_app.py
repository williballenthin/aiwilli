from pathlib import Path

from src.app import load_items, summarize_items


def test_load_items(tmp_path: Path) -> None:
    data = tmp_path / "items.txt"
    data.write_text("pear\n\napple\n", encoding="utf-8")
    assert load_items(data) == ["pear", "apple"]


def test_summarize_items() -> None:
    assert summarize_items(["pear", "apple"]) == "apple, pear"
