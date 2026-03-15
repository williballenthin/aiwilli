from pathlib import Path

from rich.console import Console

from margin.cli import run_cli


def test_run_cli_build_writes_output(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("print('hello')\n", encoding="utf-8")
    output_path = tmp_path / "review.html"
    console = Console(record=True, width=120)

    exit_code = run_cli(
        ["build", str(root), "--output", str(output_path), "--title", "CLI review"],
        stdout_console=console,
    )

    assert exit_code == 0
    assert output_path.exists()
    assert str(output_path.resolve()) in console.export_text()
