"""Tests for the edit command."""

import json

from click.testing import CliRunner

from tw.cli import main


class TestEditCommand:
    def test_edit_with_title_only(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Old Title"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-1", "--title", "New Title"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

        view_result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert "New Title" in view_result.output
        assert "Old Title" not in view_result.output

    def test_edit_with_body_only(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Title", "--body", "Old body"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-1", "--body", "New body content"],
        )
        assert result.exit_code == 0

        view_result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert "New body content" in view_result.output

    def test_edit_with_title_and_body(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Old Title", "--body", "Old body"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-1", "--title", "New Title", "--body", "New body"],
        )
        assert result.exit_code == 0

        view_result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert "New Title" in view_result.output
        assert "New body" in view_result.output

    def test_edit_with_stdin_body(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Title"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-1", "--body", "-"],
            input="Body from stdin",
        )
        assert result.exit_code == 0

        view_result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert "Body from stdin" in view_result.output

    def test_edit_extracts_references(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic 1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic 2"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-1", "--body", "This references TEST-2"],
        )
        assert result.exit_code == 0

        view_result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        output = json.loads(view_result.output.strip())
        assert "TEST-2" in output["issue"]["tw_refs"]

    def test_edit_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Title"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-1", "--title", "New Title"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert output["tw_id"] == "TEST-1"

    def test_edit_nonexistent_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-999", "--title", "Title"],
        )
        assert result.exit_code != 0

    def test_edit_empty_body_clears_content(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Title", "--body", "Original body"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "edit", "TEST-1", "--body", ""],
        )
        assert result.exit_code == 0

        view_result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        output = json.loads(view_result.output.strip())
        assert output["issue"]["tw_body"] is None or output["issue"]["tw_body"] == ""

    def test_edit_no_id_no_issues_shows_error(
        self, taskwarrior_env: dict[str, str]
    ) -> None:
        """When no ID provided and no open issues exist, show error."""
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "edit"],
        )
        assert result.exit_code != 0
        assert "No open issues to edit" in result.output
