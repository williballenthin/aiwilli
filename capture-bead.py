#!/usr/bin/env python3
"""Capture user input and create a Beads issue via Claude in YOLO mode.

# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "rich>=13.0.0",
# ]
# ///
"""

import json
import subprocess
import sys

from rich.console import Console
from rich.json import JSON
from rich.progress import Progress, SpinnerColumn, TextColumn

BD_QUICKSTART_OUTPUT = """bd - Dependency-Aware Issue Tracker

Issues chained together like beads.

GETTING STARTED
  bd init   Initialize bd in your project
            Creates .beads/ directory with project-specific database
            Auto-detects prefix from directory name (e.g., myapp-1, myapp-2)

  bd init --prefix api   Initialize with custom prefix
            Issues will be named: api-1, api-2, ...

CREATING ISSUES
  bd create "Fix login bug"
  bd create "Add auth" -p 0 -t feature
  bd create "Write tests" -d "Unit tests for auth" --assignee alice

VIEWING ISSUES
  bd list       List all issues
  bd list --status open  List by status
  bd list --priority 0  List by priority (0-4, 0=highest)
  bd show bd-1       Show issue details

MANAGING DEPENDENCIES
  bd dep add bd-1 bd-2     Add dependency (bd-2 blocks bd-1)
  bd dep tree bd-1  Visualize dependency tree
  bd dep cycles      Detect circular dependencies

DEPENDENCY TYPES
  blocks  Task B must complete before task A
  related  Soft connection, doesn't block progress
  parent-child  Epic/subtask hierarchical relationship
  discovered-from  Auto-created when AI discovers related work

READY WORK
  bd ready       Show issues ready to work on
            Ready = status is 'open' AND no blocking dependencies
            Perfect for agents to claim next work!

UPDATING ISSUES
  bd update bd-1 --status in_progress
  bd update bd-1 --priority 0
  bd update bd-1 --assignee bob

CLOSING ISSUES
  bd close bd-1
  bd close bd-2 bd-3 --reason "Fixed in PR #42"

DATABASE LOCATION
  bd automatically discovers your database:
    1. --db /path/to/db.db flag
    2. $BEADS_DB environment variable
    3. .beads/*.db in current directory or ancestors
    4. ~/.beads/default.db as fallback

AGENT INTEGRATION
  bd is designed for AI-supervised workflows:
    • Agents create issues when discovering new work
    • bd ready shows unblocked work ready to claim
    • Use --json flags for programmatic parsing
    • Dependencies prevent agents from duplicating effort

DATABASE EXTENSION
  Applications can extend bd's SQLite database:
    • Add your own tables (e.g., myapp_executions)
    • Join with issues table for powerful queries
    • See database extension docs for integration patterns:
      https://github.com/steveyegge/beads/blob/main/EXTENDING.md

GIT WORKFLOW (AUTO-SYNC)
  bd automatically keeps git in sync:
    • ✓ Export to JSONL after CRUD operations (5s debounce)
    • ✓ Import from JSONL when newer than DB (after git pull)
    • ✓ Works seamlessly across machines and team members
    • No manual export/import needed!
  Disable with: --no-auto-flush or --no-auto-import

Ready to start!
Run bd create "My first issue" to create your first issue.
"""


def collect_input() -> str:
    """Prompt the user for input repeatedly until EOF signal.

    Returns: concatenated input with newlines

    Raises: KeyboardInterrupt if user presses Ctrl+C
    """
    import platform

    console = Console()

    if platform.system() == "Windows":
        eof_key = "Ctrl+Z then Enter"
    else:
        eof_key = "Ctrl+D"

    console.print(
        f"Enter your input (press [bold cyan]{eof_key}[/] to finish):",
        style="bold yellow",
    )
    lines = []

    while True:
        try:
            line = input()
            lines.append(line)
        except EOFError:
            break

    return "\n".join(lines)


def invoke_claude(input_text: str) -> None:
    """Invoke Claude with dangerously-skip-permissions to create a Beads issue.

    Args:
        input_text: the concatenated user input
    """
    console = Console()
    prompt = f"""Here is the Beads quickstart guide:

{BD_QUICKSTART_OUTPUT}

Now use beads to create an issue with the following context: {input_text}"""

    cmd = ["claude", "--dangerously-skip-permissions", "--model", "haiku", "-p", prompt]

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]Invoking Claude to create Beads issue..."),
            console=console,
        ) as progress:
            progress.add_task("invoke", total=None)
            subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        console.print(f"Error invoking Claude: {e}", style="bold red", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        console.print(
            "Error: 'claude' command not found. Is it installed and in your PATH?",
            style="bold red",
            file=sys.stderr,
        )
        sys.exit(1)


def display_most_recent_issue() -> None:
    """Display a syntax-highlighted JSON representation of the most recently created issue."""
    console = Console()

    try:
        result = subprocess.run(
            ["bd", "list", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )

        issues = json.loads(result.stdout)
        if not issues:
            console.print("Warning: No issues found", style="yellow")
            return

        most_recent = max(issues, key=lambda x: x["created_at"])

        console.print("\n[bold cyan]Created issue:[/]")
        json_obj = JSON(json.dumps(most_recent, indent=2))
        console.print(json_obj)
        console.print()
    except subprocess.CalledProcessError as e:
        console.print(
            f"Warning: Failed to display issue: {e}", style="yellow", file=sys.stderr
        )
    except (json.JSONDecodeError, KeyError) as e:
        console.print(
            f"Warning: Failed to parse issues: {e}", style="yellow", file=sys.stderr
        )


def commit_issues_file() -> None:
    """Commit the .beads/issues.jsonl file after creating a new issue."""
    console = Console()

    try:
        subprocess.run(
            ["git", "add", ".beads/issues.jsonl"], check=True, capture_output=True
        )

        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet", ".beads/issues.jsonl"],
            capture_output=True,
        )

        if result.returncode != 0:
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    "chore: add new bead issue via capture-bead.py",
                ],
                check=True,
                capture_output=True,
            )
            console.print("✓ Committed .beads/issues.jsonl", style="bold green")
        else:
            console.print("No changes to commit", style="yellow")
    except subprocess.CalledProcessError as e:
        console.print(
            f"Warning: Failed to commit issues.jsonl: {e}",
            style="yellow",
            file=sys.stderr,
        )


def main() -> None:
    """Main entry point - loops continuously until Ctrl+C."""
    console = Console()

    console.print(
        "\n[bold cyan]Bead Capture Tool[/] - Press Ctrl+C to exit\n", style="dim"
    )

    while True:
        try:
            user_input = collect_input()

            if not user_input.strip():
                console.print("No input provided. Skipping...\n", style="yellow")
                continue

            invoke_claude(user_input)
            display_most_recent_issue()
            commit_issues_file()

            console.print("\n" + "=" * 60 + "\n", style="dim")
        except KeyboardInterrupt:
            console.print(
                "\n\n[bold green]Exiting capture-bead tool. Goodbye![/]", style="dim"
            )
            sys.exit(0)


if __name__ == "__main__":
    main()
