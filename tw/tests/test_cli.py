"""Tests for CLI commands."""

import json
import shutil

import pytest
from click.testing import CliRunner

from tw.cli import main


class TestCLI:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "tw" in result.output

    def test_version(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0

    def test_no_command_shows_help_and_tree(
        self, taskwarrior_env: dict[str, str]
    ) -> None:
        """Running tw without a subcommand shows help followed by tree."""
        runner = CliRunner(env=taskwarrior_env)
        # Create an issue so tree has something to show
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Test Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST"],
        )
        assert result.exit_code == 0
        # Should contain help content
        assert "Usage:" in result.output
        assert "Commands:" in result.output
        # Should also contain tree output
        assert "Test Epic" in result.output
        assert "TEST-1" in result.output


class TestColorFlag:
    def test_color_always_flag(self, taskwarrior_env: dict[str, str]) -> None:
        """Test --color=always flag works and includes color codes."""
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--color", "always", "--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Test Epic"],
        )
        assert result.exit_code == 0
        # Should contain ANSI escape codes when color is forced
        assert "\x1b[" in result.output
        # Should contain the issue ID (possibly with color codes)
        assert "TEST-" in result.output and "1" in result.output

    def test_color_never_flag(self, taskwarrior_env: dict[str, str]) -> None:
        """Test --color=never flag disables all color output."""
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--color", "never", "--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Test Epic"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        # When color is disabled, output should not contain ANSI escape codes
        assert "\x1b[" not in result.output

    def test_color_auto_flag(self, taskwarrior_env: dict[str, str]) -> None:
        """Test --color=auto flag (default behavior)."""
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--color", "auto", "--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Test Epic"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_color_default_is_auto(self, taskwarrior_env: dict[str, str]) -> None:
        """Test that default color behavior is auto."""
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Test Epic"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_color_never_with_tree(self, taskwarrior_env: dict[str, str]) -> None:
        """Test --color=never works with tree command."""
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Test Epic"],
        )
        result = runner.invoke(
            main,
            ["--color", "never", "--project-name", "test", "--project-prefix", "TEST", "tree"],
        )
        assert result.exit_code == 0
        assert "Test Epic" in result.output
        assert "\x1b[" not in result.output

    def test_color_invalid_value(self) -> None:
        """Test that invalid color value is rejected."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--color", "invalid", "onboard"],
        )
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "invalid" in result.output.lower()


class TestOnboardCommand:
    def test_onboard_displays_guide(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["onboard"])
        assert result.exit_code == 0
        assert "tw" in result.output.lower()
        assert "command" in result.output.lower()
        assert "new" in result.output.lower()
        assert "view" in result.output.lower()
        assert "start" in result.output.lower()

    def test_onboard_ignores_json_flag(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--json", "onboard"])
        assert result.exit_code == 0
        assert "tw" in result.output.lower()


class TestNewCommand:
    def test_new_epic(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_new_story_with_parent(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        # Create epic first
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        # Create story
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story", "--parent", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1-1" in result.output

    def test_new_missing_title(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic"],
        )
        assert result.exit_code != 0
        assert "title" in result.output.lower() or "required" in result.output.lower()

    def test_new_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert "tw_id" in output
        assert output["tw_id"] == "TEST-1"

    def test_new_with_body(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth", "--body", "Implement authentication"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output


class TestStartCommand:
    def test_start_new_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_start_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert output["tw_id"] == "TEST-1"
        assert output["status"] == "started"


class TestDoneCommand:
    def test_done_in_progress_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "done", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_done_with_message(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "done", "TEST-1", "--message", "Completed successfully"],
        )
        assert result.exit_code == 0


class TestBlockCommand:
    def test_block_in_progress_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "blocked", "TEST-1", "--reason", "Waiting for API"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_block_missing_reason(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "blocked", "TEST-1"],
        )
        assert result.exit_code != 0


class TestUnblockCommand:
    def test_unblock_blocked_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "blocked", "TEST-1", "--reason", "Waiting"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "unblock", "TEST-1", "--message", "API available"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_unblock_allows_default_message(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "blocked", "TEST-1", "--reason", "Waiting"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "unblock", "TEST-1"],
        )
        assert result.exit_code == 0


class TestHandoffCommand:
    def test_handoff_in_progress_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "handoff", "TEST-1",
             "--status", "Working on auth",
             "--completed", "Login form",
             "--remaining", "Password reset"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_handoff_missing_required_fields(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "handoff", "TEST-1"],
        )
        assert result.exit_code != 0


class TestCommentCommand:
    def test_comment_adds_annotation(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "comment", "TEST-1", "--message", "This is a comment"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_comment_missing_message(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "comment", "TEST-1"],
        )
        assert result.exit_code != 0
        assert "message" in result.output.lower() or "required" in result.output.lower()

    def test_comment_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST",
             "comment", "TEST-1", "--message", "Test comment"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert output["tw_id"] == "TEST-1"
        assert "comment" in output["action"] or "commented" in output["action"]

    def test_comment_nonexistent_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "comment", "TEST-999", "--message", "Comment"],
        )
        assert result.exit_code != 0


class TestDeleteCommand:
    def test_delete_issue_without_children(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "delete", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_delete_issue_with_children_fails(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story", "--parent", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "delete", "TEST-1"],
        )
        assert result.exit_code != 0
        assert "children" in result.output.lower()

    def test_delete_nonexistent_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "delete", "TEST-999"],
        )
        assert result.exit_code != 0

    def test_delete_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "delete", "TEST-1"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert output["tw_id"] == "TEST-1"
        assert output["status"] == "deleted"

    def test_delete_parent_after_child_deleted(
        self, taskwarrior_env: dict[str, str]
    ) -> None:
        """Deleting a parent should succeed after its children are deleted."""
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story", "--parent", "TEST-1"],
        )

        # Delete child first
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "delete", "TEST-1-1"],
        )
        assert result.exit_code == 0

        # Now parent deletion should succeed
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "delete", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output


class TestRecordCommand:
    def test_record_lesson(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "record", "TEST-1", "lesson", "--message", "Always validate input"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_record_deviation(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "record", "TEST-1", "deviation", "--message", "Changed database schema"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_record_commit(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "record", "TEST-1", "commit", "--message", "abc123 - Add feature"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

    def test_record_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST",
             "record", "TEST-1", "lesson", "--message", "Test lesson"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert output["tw_id"] == "TEST-1"
        assert output["annotation_type"] == "lesson"

    def test_record_missing_message(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "record", "TEST-1", "lesson"],
        )
        assert result.exit_code != 0


class TestDigestCommand:
    def test_digest_parent_with_children(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Login form", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Password reset", "--parent", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "digest", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "User Auth" in result.output
        assert "TEST-1-1" in result.output
        assert "Login form" in result.output
        assert "TEST-1-2" in result.output
        assert "Password reset" in result.output

    def test_digest_with_lessons_and_deviations(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Login", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "record", "TEST-1-1", "lesson", "--message", "Always validate input"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "record", "TEST-1-1", "deviation", "--message", "Changed database schema"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "digest", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "lesson" in result.output.lower() or "Lessons" in result.output
        assert "Always validate input" in result.output
        assert "deviation" in result.output.lower() or "Deviations" in result.output
        assert "Changed database schema" in result.output

    def test_digest_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Login", "--parent", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "digest", "TEST-1"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert "parent" in output
        assert output["parent"]["tw_id"] == "TEST-1"
        assert "children" in output
        assert len(output["children"]) == 1
        assert output["children"][0]["tw_id"] == "TEST-1-1"

    def test_digest_no_children(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "digest", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "User Auth" in result.output

    def test_digest_nonexistent_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "digest", "TEST-999"],
        )
        assert result.exit_code != 0


class TestViewCommand:
    def test_view_basic_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth", "--body", "Implement authentication"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "User Auth" in result.output
        assert "Implement authentication" in result.output
        assert "epic" in result.output

    def test_view_issue_with_annotations(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "comment", "TEST-1", "-m", "Test comment"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "Annotations" in result.output
        assert "Test comment" in result.output

    def test_view_stopped_issue_with_handoff(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "handoff", "TEST-1",
             "--status", "Working on auth",
             "--completed", "Login form",
             "--remaining", "Password reset"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "HANDOFF" in result.output
        assert "Working on auth" in result.output

    def test_view_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert "issue" in output
        assert "ancestors" in output
        assert "siblings" in output
        assert "descendants" in output
        assert output["issue"]["tw_id"] == "TEST-1"
        assert output["issue"]["title"] == "User Auth"
        assert output["issue"]["tw_type"] == "epic"

    def test_view_nonexistent_issue(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-999"],
        )
        assert result.exit_code != 0
        assert "error" in result.output.lower()

    def test_view_shows_full_context(self, taskwarrior_env: dict[str, str]) -> None:
        """Test that view shows ancestors, siblings, and descendants."""
        runner = CliRunner(env=taskwarrior_env)

        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic 1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story 1", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story 2", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "task", "--title", "Task 1", "--parent", "TEST-1-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "task", "--title", "Task 2", "--parent", "TEST-1-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1-1"],
        )
        assert result.exit_code == 0
        assert "TEST-1-1" in result.output
        assert "Story 1" in result.output

        assert "Ancestors" in result.output
        assert "TEST-1" in result.output
        assert "Epic 1" in result.output

        assert "Siblings" in result.output
        assert "TEST-1-2" in result.output
        assert "Story 2" in result.output

        assert "Descendants" in result.output
        assert "TEST-1-1a" in result.output
        assert "Task 1" in result.output
        assert "TEST-1-1b" in result.output
        assert "Task 2" in result.output

    def test_view_full_context_json(self, taskwarrior_env: dict[str, str]) -> None:
        """Test JSON output includes full context."""
        runner = CliRunner(env=taskwarrior_env)

        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic 1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story 1", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story 2", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "task", "--title", "Task 1", "--parent", "TEST-1-1"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1-1"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())

        assert output["issue"]["tw_id"] == "TEST-1-1"

        assert len(output["ancestors"]) == 1
        assert output["ancestors"][0]["tw_id"] == "TEST-1"
        assert output["ancestors"][0]["title"] == "Epic 1"

        assert len(output["siblings"]) == 1
        assert output["siblings"][0]["tw_id"] == "TEST-1-2"
        assert output["siblings"][0]["title"] == "Story 2"

        assert len(output["descendants"]) == 1
        assert output["descendants"][0]["tw_id"] == "TEST-1-1a"
        assert output["descendants"][0]["title"] == "Task 1"


class TestTreeCommand:
    def test_tree_empty_project(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "tree"],
        )
        assert result.exit_code == 0

    def test_tree_shows_hierarchy(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Login Form", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "task", "--title", "Create UI", "--parent", "TEST-1-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "tree"],
        )
        assert result.exit_code == 0
        assert "User Auth" in result.output
        assert "Login Form" in result.output
        assert "Create UI" in result.output
        assert "TEST-1" in result.output
        assert "TEST-1-1" in result.output
        assert "TEST-1-1a" in result.output

    def test_tree_filters_completed_epics(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Complete Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Complete Story", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "done", "TEST-1-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "start", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "done", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "tree"],
        )
        assert result.exit_code == 0
        assert "Complete Epic" not in result.output

    def test_tree_shows_incomplete_epics(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Incomplete Epic"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Incomplete Story", "--parent", "TEST-1"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "tree"],
        )
        assert result.exit_code == 0
        assert "Incomplete Epic" in result.output
        assert "Incomplete Story" in result.output

    def test_tree_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "User Auth"],
        )

        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "tree"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert isinstance(output, dict)
        assert "hierarchy" in output
        assert "backlog" in output
        assert len(output["hierarchy"]) > 0
        assert output["hierarchy"][0]["tw_id"] == "TEST-1"
        assert output["hierarchy"][0]["title"] == "User Auth"

    def test_tree_with_root_id(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic 1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "story", "--title", "Story 1", "--parent", "TEST-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "task", "--title", "Task 1", "--parent", "TEST-1-1"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic 2"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "tree", "TEST-1"],
        )
        assert result.exit_code == 0
        assert "Epic 1" in result.output
        assert "Story 1" in result.output
        assert "Task 1" in result.output
        assert "Epic 2" not in result.output

    def test_tree_with_invalid_root_id(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "tree", "TEST-999"],
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_tree_shows_backlog_section(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "epic", "--title", "Epic One"],
        )
        runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST",
             "new", "bug", "--title", "Bug One"],
        )

        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "tree"],
        )

        assert result.exit_code == 0
        assert "Epic One" in result.output
        assert "Backlog" in result.output
        assert "Bug One" in result.output


class TestParseCapturesDsl:
    def test_parse_multiline_body(self) -> None:
        """Parse entries with multi-line body content."""
        from tw.cli import parse_capture_dsl, CaptureEntry

        content = """- bug: login broken
    The login form crashes.
    Discovered while working on TEST-5.
- idea: password meter
    Would improve UX.
"""
        entries = parse_capture_dsl(content)

        assert len(entries) == 2
        assert entries[0].issue_type == "bug"
        assert entries[0].title == "login broken"
        assert entries[0].body == "The login form crashes.\nDiscovered while working on TEST-5."
        assert entries[1].issue_type == "idea"
        assert entries[1].title == "password meter"
        assert entries[1].body == "Would improve UX."

    def test_parse_multiline_with_separator(self) -> None:
        """Parse entries with --- separator in body."""
        from tw.cli import parse_capture_dsl

        content = """- task: implement form
    Repeatable summary here.
    ---
    Non-repeatable details.
"""
        entries = parse_capture_dsl(content)

        assert len(entries) == 1
        assert entries[0].body == "Repeatable summary here.\n---\nNon-repeatable details."

    def test_parse_preserves_hierarchy_with_multiline(self) -> None:
        """Multi-line bodies work with hierarchy."""
        from tw.cli import parse_capture_dsl

        content = """- epic: auth system
    High level description.
  - story: login
      Story details here.
    - task: form
        Task details.
"""
        entries = parse_capture_dsl(content)

        assert len(entries) == 3
        assert entries[0].parent_title is None
        assert entries[0].body == "High level description."
        assert entries[1].parent_title == "auth system"
        assert entries[1].body == "Story details here."
        assert entries[2].parent_title == "login"
        assert entries[2].body == "Task details."


class TestCaptureCommand:
    def test_capture_from_stdin(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        dsl_input = """- epic: user authentication
  - story: login page
    - task: implement form
    - task: add validation
  - story: password reset
    - task: send email
"""
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "capture", "-"],
            input=dsl_input,
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "TEST-1-1" in result.output
        assert "TEST-1-1a" in result.output
        assert "TEST-1-1b" in result.output
        assert "TEST-1-2" in result.output
        assert "TEST-1-2a" in result.output

    def test_capture_ignores_comments(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        dsl_input = """# This is a comment
- epic: user auth
# Another comment
  - story: login
"""
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "capture", "-"],
            input=dsl_input,
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "TEST-1-1" in result.output

    def test_capture_json_output(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        dsl_input = """- epic: user authentication
  - story: login page
    - task: implement form
"""
        result = runner.invoke(
            main,
            ["--json", "--project-name", "test", "--project-prefix", "TEST", "capture", "-"],
            input=dsl_input,
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert "created" in output
        assert len(output["created"]) == 3
        assert output["created"][0]["tw_id"] == "TEST-1"
        assert output["created"][1]["tw_id"] == "TEST-1-1"
        assert output["created"][2]["tw_id"] == "TEST-1-1a"

    def test_capture_empty_input(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "capture", "-"],
            input="",
        )
        assert result.exit_code == 0

    def test_capture_only_comments(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "capture", "-"],
            input="# just a comment\n# another comment\n",
        )
        assert result.exit_code == 0

    def test_capture_multiple_epics(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)
        dsl_input = """- epic: user authentication
  - story: login
- epic: user profile
  - story: avatar upload
"""
        result = runner.invoke(
            main,
            ["--project-name", "test", "--project-prefix", "TEST", "capture", "-"],
            input=dsl_input,
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "TEST-1-1" in result.output
        assert "TEST-2" in result.output
        assert "TEST-2-1" in result.output

    def test_capture_with_body(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, ["--project-name", "test", "--project-prefix", "TEST", "capture", "-"], input="""- bug: test bug
    This is the body.
    With multiple lines.
""")

        assert result.exit_code == 0

        # Verify body was stored
        result = runner.invoke(main, ["--json", "--project-name", "test", "--project-prefix", "TEST", "view", "TEST-1"])
        data = json.loads(result.output.strip())
        assert data["issue"]["tw_body"] == "This is the body.\nWith multiple lines."


@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestNewBacklogCommands:
    def test_new_bug(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, [
            "--project-name", "test", "--project-prefix", "TEST",
            "new", "bug",
            "--title", "Login broken",
            "--body", "Crashes on empty password"
        ])

        assert result.exit_code == 0
        assert "DEFAULT-1" in result.output or "TEST-1" in result.output

    def test_new_idea(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, [
            "--project-name", "test", "--project-prefix", "TEST",
            "new", "idea",
            "--title", "Password strength meter"
        ])

        assert result.exit_code == 0
        assert "DEFAULT-1" in result.output or "TEST-1" in result.output

    def test_new_bug_rejects_parent(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        runner.invoke(main, [
            "--project-name", "test", "--project-prefix", "TEST",
            "new", "epic", "--title", "Epic"
        ])
        result = runner.invoke(main, [
            "--project-name", "test", "--project-prefix", "TEST",
            "new", "bug",
            "--title", "Bug",
            "--parent", "TEST-1"
        ])

        assert result.exit_code == 1
        assert "cannot have a parent" in result.output


@pytest.mark.skipif(shutil.which("task") is None, reason="TaskWarrior not installed")
class TestGroomCommand:
    def test_groom_empty_backlog(self, taskwarrior_env: dict[str, str]) -> None:
        runner = CliRunner(env=taskwarrior_env)

        result = runner.invoke(main, [
            "--project-name", "test", "--project-prefix", "TEST",
            "groom"
        ])

        assert result.exit_code == 0
        assert "No backlog items" in result.output

    def test_groom_resolves_removed(
        self, taskwarrior_env: dict[str, str], monkeypatch
    ) -> None:
        import subprocess

        runner = CliRunner(env=taskwarrior_env)

        # Create a bug
        runner.invoke(main, [
            "--project-name", "test", "--project-prefix", "TEST",
            "new", "bug", "--title", "Test bug"
        ])

        # Save original subprocess.run
        original_run = subprocess.run

        # Mock editor to return empty content (removes the item)
        def mock_editor(cmd, *args, **kwargs):
            # Only mock editor calls (those with .md file), let taskwarrior through
            if len(cmd) > 1 and isinstance(cmd[1], str) and cmd[1].endswith('.md'):
                # Write empty content to the file being edited
                temp_file = cmd[1]
                with open(temp_file, 'w') as f:
                    f.write("")  # Empty content means item is removed
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            else:
                # Pass through to real subprocess.run for taskwarrior commands
                return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr("tw.cli.subprocess.run", mock_editor)

        result = runner.invoke(main, [
            "--project-name", "test", "--project-prefix", "TEST",
            "groom"
        ])

        # Check the groom command succeeded
        assert result.exit_code == 0, f"groom failed: {result.output}"

        # The bug should be resolved
        view_result = runner.invoke(main, [
            "--json", "--project-name", "test", "--project-prefix", "TEST",
            "view", "TEST-1"
        ])
        assert view_result.exit_code == 0, f"view failed: {view_result.output}"
        data = json.loads(view_result.output.strip())
        assert data["issue"]["tw_status"] == "done"


class TestWatchCommand:
    def test_watch_tree_command_validates_subcommand(self, taskwarrior_env: dict[str, str]) -> None:
        """Test that watch command only accepts 'tree' subcommand."""
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(main, ["watch", "invalid"])
        assert result.exit_code == 1
        assert "only 'tree' subcommand is supported" in result.output

    def test_watch_tree_command_validates_interval(self, taskwarrior_env: dict[str, str]) -> None:
        """Test that watch command validates positive interval."""
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(main, ["watch", "tree", "-n", "0"])
        assert result.exit_code == 1
        assert "interval must be positive" in result.output

    def test_watch_tree_command_validates_negative_interval(self, taskwarrior_env: dict[str, str]) -> None:
        """Test that watch command rejects negative interval."""
        runner = CliRunner(env=taskwarrior_env)
        result = runner.invoke(main, ["watch", "tree", "-n", "-5"])
        assert result.exit_code == 1
        assert "interval must be positive" in result.output
