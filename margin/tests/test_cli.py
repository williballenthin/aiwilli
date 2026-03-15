from pathlib import Path

from rich.console import Console

from margin.cli import build_parser, run_cli


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


def test_build_parser_accepts_serve_commands(tmp_path: Path) -> None:
    parser = build_parser()

    serve_args = parser.parse_args(["serve", str(tmp_path), "--port", "5174"])
    serve_github_args = parser.parse_args(["serve-github", "acme/widgets", "--ref", "main"])

    assert serve_args.command == "serve"
    assert serve_args.port == 5174
    assert serve_github_args.command == "serve-github"
    assert serve_github_args.ref == "main"
