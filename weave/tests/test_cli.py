from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from weave.cli import main


def test_cli_help_lists_subcommands() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "monitor" in result.output
    assert "sync" in result.output
    assert "import" in result.output
    assert "rebuild" in result.output


def test_rebuild_daily_command_writes_weave_note(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        'summary: "Stored summary."\n'
        "---\n"
        "Body\n"
    )
    daily_path = vault_root / "daily" / "2026-03-01.md"
    daily_path.parent.mkdir(parents=True)
    daily_path.write_text("keep me\n")

    runner = CliRunner()
    result = runner.invoke(main, ["rebuild", "daily", str(vault_root)])

    assert result.exit_code == 0
    assert result.output.strip() == "rebuilt 1 daily note(s)"
    assert daily_path.read_text() == (
        "keep me\n"
        "\n"
        "<!-- weave:daily-embed:start -->\n"
        "![[daily/2026/03/01/2026-03-01 weave.md]]\n"
        "<!-- weave:daily-embed:end -->\n"
    )
    assert (vault_root / "daily" / "2026/03/01" / "2026-03-01 weave.md").read_text() == (
        "## Capture\n"
        "<!-- weave:section:capture:start -->\n"
        "- transcript: [[sink/2026/03/01/1345 - transcription.md|1345 - transcription]]"
        " — Stored summary.\n"
        "<!-- weave:section:capture:end -->\n"
    )
