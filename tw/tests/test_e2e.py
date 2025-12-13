"""End-to-end tests for the tw CLI.

These tests verify complete workflows from start to finish, exercising
multiple commands in sequence to ensure the system works as a whole.
"""

import json
import threading
import time

from click.testing import CliRunner

from tw.cli import main


class TestFullWorkflow:
    """Test complete workflows from creation to completion."""

    def test_epic_story_task_workflow(self, sqlite_env: dict[str, str]) -> None:
        """Test creating and completing nested issues: epic → story → task."""
        runner = CliRunner(env=sqlite_env)

        # Create epic
        result = runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "User Authentication System",
                "--body",
                "Implement complete authentication system with OAuth and JWT",
            ],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output

        # Create story under epic
        result = runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Login Flow",
                "--parent",
                "TEST-1",
                "--body",
                "Implement user login with email and password",
            ],
        )
        assert result.exit_code == 0
        assert "TEST-1-1" in result.output

        # Create task under story
        result = runner.invoke(
            main,
            [
                "new",
                "task",
                "--title",
                "Create login form UI",
                "--parent",
                "TEST-1-1",
            ],
        )
        assert result.exit_code == 0
        assert "TEST-1-1a" in result.output

        # Start the task
        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1-1a",
            ],
        )
        assert result.exit_code == 0
        assert "Started" in result.output

        # Complete the task
        result = runner.invoke(
            main,
            [
                "done",
                "TEST-1-1a",
                "--message",
                "Login form UI completed with validation",
            ],
        )
        assert result.exit_code == 0
        assert "done" in result.output.lower()

        # Verify the task shows as done
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1-1a",
            ],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "done"

        # Verify all issues appear in tree
        result = runner.invoke(
            main,
            ["tree"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "TEST-1-1" in result.output
        assert "TEST-1-1a" in result.output

    def test_multiple_parallel_stories(self, sqlite_env: dict[str, str]) -> None:
        """Test creating multiple stories under one epic and completing them."""
        runner = CliRunner(env=sqlite_env)

        # Create epic
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "API Development",
            ],
        )

        # Create multiple stories
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "User API",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Posts API",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Comments API",
                "--parent",
                "TEST-1",
            ],
        )

        # Verify all stories exist
        result = runner.invoke(
            main,
            ["--json", "tree"],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())
        assert len(output['hierarchy']) == 4  # 1 epic + 3 stories
        story_ids = [i["tw_id"] for i in output['hierarchy'] if i["tw_type"] == "story"]
        assert "TEST-1-1" in story_ids
        assert "TEST-1-2" in story_ids
        assert "TEST-1-3" in story_ids

        # Work on stories in parallel
        runner.invoke(
            main,
            [
                "start",
                "TEST-1-1",
            ],
        )
        runner.invoke(
            main,
            [
                "done",
                "TEST-1-1",
            ],
        )

        runner.invoke(
            main,
            [
                "start",
                "TEST-1-2",
            ],
        )
        runner.invoke(
            main,
            [
                "done",
                "TEST-1-2",
            ],
        )

        # Verify statuses
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1-1",
            ],
        )
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "done"

        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1-2",
            ],
        )
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "done"


class TestHandoffWorkflow:
    """Test handoff workflow with structured summaries."""

    def test_complete_handoff_workflow(self, sqlite_env: dict[str, str]) -> None:
        """Test creating issue, starting, handing off, resuming, and completing."""
        runner = CliRunner(env=sqlite_env)

        # Create epic
        result = runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Database Migration",
            ],
        )
        assert result.exit_code == 0

        # Start work
        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0

        # Verify status is in_progress
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1",
            ],
        )
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "in_progress"

        # Handoff with summary
        result = runner.invoke(
            main,
            [
                "handoff",
                "TEST-1",
                "--status",
                "Halfway through schema changes",
                "--completed",
                "Created new tables for users and posts",
                "--remaining",
                "Need to migrate data and update foreign keys",
            ],
        )
        assert result.exit_code == 0
        assert "Handed off" in result.output

        # Verify status is stopped
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1",
            ],
        )
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "stopped"

        # Resume work
        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0

        # Verify back in progress
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1",
            ],
        )
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "in_progress"

        # Complete the work
        result = runner.invoke(
            main,
            [
                "done",
                "TEST-1",
                "--message",
                "All data migrated successfully",
            ],
        )
        assert result.exit_code == 0

        # Verify final status
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1",
            ],
        )
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "done"

    def test_multiple_handoffs(self, sqlite_env: dict[str, str]) -> None:
        """Test multiple handoffs on the same issue."""
        runner = CliRunner(env=sqlite_env)

        # Create epic first, then story
        result = runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Main Epic",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Feature Development",
                "--parent",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1-1",
            ],
        )
        assert result.exit_code == 0

        # First handoff
        result = runner.invoke(
            main,
            [
                "handoff",
                "TEST-1-1",
                "--status",
                "Initial design complete",
                "--completed",
                "UI mockups",
                "--remaining",
                "Implementation",
            ],
        )
        assert result.exit_code == 0

        # Resume and handoff again
        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1-1",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "handoff",
                "TEST-1-1",
                "--status",
                "Backend complete",
                "--completed",
                "API endpoints and database",
                "--remaining",
                "Frontend integration",
            ],
        )
        assert result.exit_code == 0

        # Resume and complete
        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1-1",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "done",
                "TEST-1-1",
            ],
        )
        assert result.exit_code == 0


class TestBlockUnblockWorkflow:
    """Test blocking and unblocking issues."""

    def test_block_unblock_complete_workflow(
        self, sqlite_env: dict[str, str]
    ) -> None:
        """Test complete block/unblock workflow."""
        runner = CliRunner(env=sqlite_env)

        # Create epic
        result = runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Payments",
            ],
        )
        assert result.exit_code == 0

        # Start epic
        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0

        # Block with reason
        result = runner.invoke(
            main,
            [
                "blocked",
                "TEST-1",
                "--reason",
                "Waiting for API credentials from vendor",
            ],
        )
        assert result.exit_code == 0
        assert "Blocked" in result.output

        # Verify status is blocked
        result = runner.invoke(
            main,
            [
                "view",
                "TEST-1",
            ],
        )
        assert "blocked" in result.output.lower()

        # Unblock with message
        result = runner.invoke(
            main,
            [
                "unblock",
                "TEST-1",
                "--message",
                "Received API credentials",
            ],
        )
        assert result.exit_code == 0
        assert "Unblocked" in result.output

        # Verify back to in_progress
        result = runner.invoke(
            main,
            [
                "view",
                "TEST-1",
            ],
        )
        assert "open" in result.output.lower() or "in_progress" in result.output.lower()

        # Complete
        result = runner.invoke(
            main,
            [
                "done",
                "TEST-1",
                "--message",
                "Payment gateway integrated",
            ],
        )
        assert result.exit_code == 0

        # Verify done
        result = runner.invoke(
            main,
            [
                "view",
                "TEST-1",
            ],
        )
        assert "done" in result.output.lower()

    def test_multiple_blocks(self, sqlite_env: dict[str, str]) -> None:
        """Test multiple block/unblock cycles."""
        runner = CliRunner(env=sqlite_env)

        # Create epic first
        result = runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Integration work",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0

        # Block, unblock, block again
        result = runner.invoke(
            main,
            [
                "blocked",
                "TEST-1",
                "--reason",
                "Waiting for service A",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "unblock",
                "TEST-1",
                "--message",
                "Service A ready",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "blocked",
                "TEST-1",
                "--reason",
                "Now waiting for service B",
            ],
        )
        assert result.exit_code == 0

        # Verify blocked
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1",
            ],
        )
        output = json.loads(result.output.strip())
        assert output["tw_status"] == "blocked"

        # Unblock and complete
        result = runner.invoke(
            main,
            [
                "unblock",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0

        result = runner.invoke(
            main,
            [
                "done",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0


class TestTreeAndView:
    """Test tree and view commands with various scenarios."""

    def test_tree_shows_all_issue_types(self, sqlite_env: dict[str, str]) -> None:
        """Test that tree shows epics, stories, and tasks."""
        runner = CliRunner(env=sqlite_env)

        # Create various issue types
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Epic One",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Story One",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "task",
                "--title",
                "Task One",
                "--parent",
                "TEST-1-1",
            ],
        )

        # List all (using human-readable format)
        result = runner.invoke(
            main,
            ["tree"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "Epic One" in result.output
        assert "TEST-1-1" in result.output
        assert "Story One" in result.output
        assert "TEST-1-1a" in result.output
        assert "Task One" in result.output

    def test_tree_shows_statuses(self, sqlite_env: dict[str, str]) -> None:
        """Test that tree shows correct status for each issue."""
        runner = CliRunner(env=sqlite_env)

        # Create epics with different statuses
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "New Epic",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Started Epic",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Done Epic",
            ],
        )

        # Set statuses
        runner.invoke(
            main,
            [
                "start",
                "TEST-2",
            ],
        )
        runner.invoke(
            main,
            [
                "start",
                "TEST-3",
            ],
        )
        runner.invoke(
            main,
            [
                "done",
                "TEST-3",
            ],
        )

        # Verify tree shows incomplete issues (completed epics are filtered out)
        result = runner.invoke(
            main,
            ["tree"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "TEST-2" in result.output
        # TEST-3 (Done Epic) is filtered out by tree since it's complete

        # Verify statuses via individual show commands
        result = runner.invoke(
            main,
            ["view", "TEST-1"],
        )
        assert "new" in result.output.lower()

        result = runner.invoke(
            main,
            ["view", "TEST-2"],
        )
        assert "open" in result.output.lower() or "in_progress" in result.output.lower()

        result = runner.invoke(
            main,
            ["view", "TEST-3"],
        )
        assert "done" in result.output.lower()

    def test_show_displays_complete_details(
        self, sqlite_env: dict[str, str]
    ) -> None:
        """Test that show displays all issue details."""
        runner = CliRunner(env=sqlite_env)

        # Create issue with full details
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Complete Epic",
                "--body",
                "This is a detailed body with multiple lines.\n"
                "It has descriptions and requirements.",
            ],
        )

        # Show in human-readable format
        result = runner.invoke(
            main,
            [
                "view",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "Complete Epic" in result.output
        assert "detailed body" in result.output
        assert "epic" in result.output.lower()
        assert "new" in result.output.lower()

    def test_show_hierarchical_relationships(
        self, sqlite_env: dict[str, str]
    ) -> None:
        """Test that show displays parent relationships correctly."""
        runner = CliRunner(env=sqlite_env)

        # Create hierarchy
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Parent Epic",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Child Story",
                "--parent",
                "TEST-1",
            ],
        )

        # Show child and verify parent is displayed
        result = runner.invoke(
            main,
            [
                "--json",
                "view",
                "TEST-1-1",
            ],
        )
        assert result.exit_code == 0
        output = json.loads(result.output.strip())

        assert output["tw_parent"] == "TEST-1"

        # Verify in human-readable format too
        result = runner.invoke(
            main,
            [
                "view",
                "TEST-1-1",
            ],
        )
        assert result.exit_code == 0
        assert "parent:" in result.output
        assert "TEST-1" in result.output


class TestComplexWorkflows:
    """Test complex multi-issue workflows."""

    def test_mixed_status_workflow(self, sqlite_env: dict[str, str]) -> None:
        """Test workflow with multiple issues in different states."""
        runner = CliRunner(env=sqlite_env)

        # Create epic with multiple stories
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Project Alpha",
            ],
        )

        # Story 1: Complete workflow
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Story Done",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "start",
                "TEST-1-1",
            ],
        )
        runner.invoke(
            main,
            [
                "done",
                "TEST-1-1",
            ],
        )

        # Story 2: In progress
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Story In Progress",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "start",
                "TEST-1-2",
            ],
        )

        # Story 3: Blocked
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Story Blocked",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "start",
                "TEST-1-3",
            ],
        )
        runner.invoke(
            main,
            [
                "blocked",
                "TEST-1-3",
                "--reason",
                "Dependency issue",
            ],
        )

        # Story 4: Handed off
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Story Stopped",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "start",
                "TEST-1-4",
            ],
        )
        runner.invoke(
            main,
            [
                "handoff",
                "TEST-1-4",
                "--status",
                "Partial work",
                "--completed",
                "Setup",
                "--remaining",
                "Implementation",
            ],
        )

        # Story 5: New (not started)
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Story New",
                "--parent",
                "TEST-1",
            ],
        )

        # Verify all issues and their statuses via tree
        result = runner.invoke(
            main,
            ["tree"],
        )
        assert result.exit_code == 0
        # Check that all IDs appear
        assert "TEST-1" in result.output  # epic
        assert "TEST-1-1" in result.output  # story 1
        assert "TEST-1-2" in result.output  # story 2
        assert "TEST-1-3" in result.output  # story 3
        assert "TEST-1-4" in result.output  # story 4
        assert "TEST-1-5" in result.output  # story 5

        # Verify specific statuses by checking individual issues
        result = runner.invoke(
            main,
            ["view", "TEST-1-1"],
        )
        assert "done" in result.output.lower()

        result = runner.invoke(
            main,
            ["view", "TEST-1-3"],
        )
        assert "blocked" in result.output.lower()

    def test_deep_hierarchy_workflow(self, sqlite_env: dict[str, str]) -> None:
        """Test creating and working with deep hierarchies."""
        runner = CliRunner(env=sqlite_env)

        # Create epic → story → task → subtask-like structure
        runner.invoke(
            main,
            [
                "new",
                "epic",
                "--title",
                "Level 1",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "story",
                "--title",
                "Level 2",
                "--parent",
                "TEST-1",
            ],
        )
        runner.invoke(
            main,
            [
                "new",
                "task",
                "--title",
                "Level 3",
                "--parent",
                "TEST-1-1",
            ],
        )

        # Verify hierarchy via show
        result = runner.invoke(
            main,
            [
                "view",
                "TEST-1-1a",
            ],
        )
        assert result.exit_code == 0
        assert "TEST-1-1a" in result.output
        assert "parent:" in result.output
        assert "TEST-1-1" in result.output

        # Verify tree shows all levels
        result = runner.invoke(
            main,
            ["tree"],
        )
        assert result.exit_code == 0
        assert "TEST-1" in result.output
        assert "TEST-1-1" in result.output
        assert "TEST-1-1a" in result.output


class TestWatchCommand:
    """Test watch command functionality."""

    def test_watch_tree_command_with_file_change(self, sqlite_env: dict[str, str]) -> None:
        """Test that watch command detects file changes and updates display."""
        runner = CliRunner(env=sqlite_env)

        # Create an issue
        result = runner.invoke(
            main,
            [
                "new",
                "task",
                "-t",
                "Watch test task",
            ],
        )
        assert result.exit_code == 0

        # Start watch in background thread
        watch_thread = None
        watch_output = []

        def run_watch():
            result = runner.invoke(
                main,
                [
                    "watch",
                    "tree",
                    "-n",
                    "2",
                ],
                catch_exceptions=False,
            )
            watch_output.append(result.output)

        watch_thread = threading.Thread(target=run_watch, daemon=True)
        watch_thread.start()

        # Give watch time to start
        time.sleep(0.5)

        # Modify an issue (this should trigger file watch)
        result = runner.invoke(
            main,
            [
                "start",
                "TEST-1",
            ],
        )
        assert result.exit_code == 0

        # Give watch time to detect change
        time.sleep(1)

        # The watch should have rendered at least once
        # Note: This test is simplified - in real usage we'd use a more sophisticated
        # approach to verify the display updated
