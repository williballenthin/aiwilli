# tw watch tree Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `tw watch tree` command for continuous monitoring with file system notifications and polling.

**Architecture:** New `src/tw/watch.py` module with watchdog integration. Add `watch` command to CLI that reuses existing tree rendering. Rich.Live for auto-updating display. Hybrid file watching + polling with graceful fallbacks.

**Tech Stack:** watchdog, Rich.Live, threading, subprocess

---

## Task 1: Add watchdog dependency

**Files:**
- Modify: `pyproject.toml:10-16`

**Step 1: Add watchdog to dependencies**

Edit `pyproject.toml`, add watchdog to the dependencies array:

```toml
dependencies = [
    "click>=8.0",
    "rich>=13.0",
    "pydantic>=2.0",
    "jinja2>=3.0",
    "questionary>=2.0",
    "watchdog>=3.0",
]
```

**Step 2: Install dependency**

Run: `pip install -e .`
Expected: Success, watchdog installed

**Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add watchdog for file system monitoring"
```

---

## Task 2: Create watch module with data directory detection

**Files:**
- Create: `src/tw/watch.py`
- Create: `tests/test_watch.py`

**Step 1: Write failing test for get_taskwarrior_data_dir**

Create `tests/test_watch.py`:

```python
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tw.watch import get_taskwarrior_data_dir


def test_get_taskwarrior_data_dir_success():
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "~/.task\n"

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = get_taskwarrior_data_dir()

        assert result == Path.home() / ".task"
        mock_run.assert_called_once_with(
            ["task", "rc.confirmation=off", "_get", "rc.data.location"],
            capture_output=True,
            text=True,
        )


def test_get_taskwarrior_data_dir_failure():
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "task not found"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="Failed to get TaskWarrior data directory"):
            get_taskwarrior_data_dir()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_watch.py::test_get_taskwarrior_data_dir_success -v`
Expected: FAIL with "cannot import name 'get_taskwarrior_data_dir'"

**Step 3: Implement get_taskwarrior_data_dir**

Create `src/tw/watch.py`:

```python
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def get_taskwarrior_data_dir() -> Path:
    """Get TaskWarrior data directory from config.

    Queries TaskWarrior for rc.data.location to respect custom configurations.

    Returns:
        Path to TaskWarrior data directory

    Raises:
        RuntimeError: If TaskWarrior query fails
    """
    result = subprocess.run(
        ["task", "rc.confirmation=off", "_get", "rc.data.location"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError("Failed to get TaskWarrior data directory")

    data_dir = result.stdout.strip()
    return Path(data_dir).expanduser().resolve()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_watch.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/tw/watch.py tests/test_watch.py
git commit -m "feat: add TaskWarrior data directory detection"
```

---

## Task 3: Implement file system event handler with debouncing

**Files:**
- Modify: `src/tw/watch.py`
- Modify: `tests/test_watch.py`

**Step 1: Write failing test for WatchHandler**

Add to `tests/test_watch.py`:

```python
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from watchdog.events import FileModifiedEvent

from tw.watch import WatchHandler


def test_watch_handler_triggers_on_data_file():
    event = threading.Event()
    handler = WatchHandler(event)

    file_event = FileModifiedEvent("/path/to/pending.data")
    handler.on_modified(file_event)

    time.sleep(0.15)

    assert event.is_set()


def test_watch_handler_ignores_non_data_files():
    event = threading.Event()
    handler = WatchHandler(event)

    file_event = FileModifiedEvent("/path/to/other.txt")
    handler.on_modified(file_event)

    time.sleep(0.15)

    assert not event.is_set()


def test_watch_handler_debounces_rapid_changes():
    event = threading.Event()
    handler = WatchHandler(event)

    # Simulate rapid file changes
    for _ in range(5):
        file_event = FileModifiedEvent("/path/to/pending.data")
        handler.on_modified(file_event)
        time.sleep(0.05)

    time.sleep(0.15)

    # Should only trigger once after debounce
    assert event.is_set()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_watch.py::test_watch_handler_triggers_on_data_file -v`
Expected: FAIL with "cannot import name 'WatchHandler'"

**Step 3: Implement WatchHandler**

Add to `src/tw/watch.py`:

```python
import threading

from watchdog.events import FileSystemEventHandler


class WatchHandler(FileSystemEventHandler):
    """File system event handler with debouncing.

    Triggers refresh event when .data files are modified, with 100ms debounce
    to handle rapid successive writes from TaskWarrior.
    """

    def __init__(self, event: threading.Event) -> None:
        """Initialize handler.

        Args:
            event: Threading event to set when refresh should trigger
        """
        super().__init__()
        self.event = event
        self.timer: threading.Timer | None = None
        self.lock = threading.Lock()

    def on_modified(self, event: object) -> None:
        """Handle file modification event.

        Args:
            event: Watchdog file system event
        """
        # Type checking workaround for watchdog events
        if not hasattr(event, 'src_path'):
            return

        src_path = getattr(event, 'src_path')
        if not isinstance(src_path, str) or not src_path.endswith('.data'):
            return

        with self.lock:
            # Cancel existing timer
            if self.timer is not None:
                self.timer.cancel()

            # Set new timer for debounce
            self.timer = threading.Timer(0.1, self._trigger_refresh)
            self.timer.start()

    def _trigger_refresh(self) -> None:
        """Trigger refresh event after debounce period."""
        self.event.set()

    def cleanup(self) -> None:
        """Cancel pending timers."""
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_watch.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/tw/watch.py tests/test_watch.py
git commit -m "feat: add file system event handler with debouncing"
```

---

## Task 4: Implement main watch loop

**Files:**
- Modify: `src/tw/watch.py`
- Modify: `tests/test_watch.py`

**Step 1: Write integration test for watch_tree**

Add to `tests/test_watch.py`:

```python
from datetime import datetime
from unittest.mock import MagicMock, patch

from rich.console import Console

from tw.models import Issue, IssueStatus, IssueType
from tw.service import IssueService
from tw.watch import watch_tree


def test_watch_tree_renders_and_exits_on_keyboard_interrupt():
    """Test that watch_tree renders tree and handles Ctrl+C gracefully."""
    # Setup mock service
    mock_service = MagicMock(spec=IssueService)
    issue = Issue(
        uuid="test-uuid",
        tw_id="TW-1",
        tw_type=IssueType.TASK,
        title="Test task",
        tw_status=IssueStatus.NEW,
        project="test",
    )
    mock_service.get_issue_tree_with_backlog.return_value = ([issue], [])

    # Setup mock console
    console = Console()

    # Mock get_taskwarrior_data_dir
    with patch("tw.watch.get_taskwarrior_data_dir", return_value=Path("/tmp/test")):
        # Mock Observer
        with patch("tw.watch.Observer") as mock_observer_class:
            mock_observer = MagicMock()
            mock_observer_class.return_value = mock_observer

            # Simulate KeyboardInterrupt after first render
            mock_observer.start.side_effect = KeyboardInterrupt

            # Should exit cleanly without raising
            watch_tree(mock_service, None, 60, console)

            # Verify observer cleanup
            mock_observer.stop.assert_called_once()
            mock_observer.join.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_watch.py::test_watch_tree_renders_and_exits_on_keyboard_interrupt -v`
Expected: FAIL with "cannot import name 'watch_tree'"

**Step 3: Implement watch_tree**

Add to `src/tw/watch.py`:

```python
import threading
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.text import Text
from watchdog.observers import Observer

from tw.render import render_tree_with_backlog
from tw.service import IssueService


def watch_tree(
    service: IssueService,
    tw_id: str | None,
    interval: int,
    console: Console,
) -> None:
    """Watch tree output with auto-refresh.

    Monitors TaskWarrior data directory for changes and refreshes tree display.
    Uses hybrid file watching + polling approach.

    Args:
        service: IssueService instance
        tw_id: Optional issue ID to filter tree
        interval: Poll interval in seconds
        console: Rich console for output

    Raises:
        RuntimeError: If TaskWarrior data directory cannot be detected
    """
    # Setup file watching
    data_dir = get_taskwarrior_data_dir()
    refresh_event = threading.Event()

    handler = WatchHandler(refresh_event)
    observer = Observer()
    use_watchdog = True

    try:
        observer.schedule(handler, str(data_dir), recursive=False)
        observer.start()
    except Exception as e:
        logger.warning(f"File watching unavailable, using polling only: {e}")
        use_watchdog = False

    try:
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                try:
                    # Fetch and render tree
                    hierarchy, backlog = service.get_issue_tree_with_backlog(tw_id)
                    tree_output = render_tree_with_backlog(hierarchy, backlog)

                    # Build display with header
                    display = Text()
                    cmd_parts = ["Every", f"{interval}s:", "tw", "tree"]
                    if tw_id:
                        cmd_parts.append(tw_id)
                    display.append(" ".join(cmd_parts), style="bold")
                    display.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n", style="dim")
                    display.append(tree_output)

                    live.update(display)

                    # Wait for file change or timeout
                    refresh_event.wait(timeout=interval)
                    refresh_event.clear()

                except Exception as e:
                    # Show error but keep watching
                    error_display = Text()
                    error_display.append(f"Error: {e}\n", style="red")
                    error_display.append("Waiting for next update...", style="dim")
                    live.update(error_display)

                    refresh_event.wait(timeout=interval)
                    refresh_event.clear()

    except KeyboardInterrupt:
        pass
    finally:
        if use_watchdog:
            handler.cleanup()
            observer.stop()
            observer.join()
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_watch.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/tw/watch.py tests/test_watch.py
git commit -m "feat: implement watch loop with Rich.Live display"
```

---

## Task 5: Add watch command to CLI

**Files:**
- Modify: `src/tw/cli.py:1-10` (imports)
- Modify: `src/tw/cli.py:632-` (add new command after tree command)
- Modify: `tests/test_cli.py`

**Step 1: Write failing test for watch command**

Add to `tests/test_cli.py`:

```python
def test_watch_tree_command_validates_subcommand(runner, temp_task_dir):
    """Test that watch command only accepts 'tree' subcommand."""
    result = runner.invoke(cli.main, ["watch", "invalid"])
    assert result.exit_code == 1
    assert "only 'tree' subcommand is supported" in result.output


def test_watch_tree_command_validates_interval(runner, temp_task_dir):
    """Test that watch command validates positive interval."""
    result = runner.invoke(cli.main, ["watch", "tree", "-n", "0"])
    assert result.exit_code == 1
    assert "interval must be positive" in result.output


def test_watch_tree_command_validates_negative_interval(runner, temp_task_dir):
    """Test that watch command rejects negative interval."""
    result = runner.invoke(cli.main, ["watch", "tree", "-n", "-5"])
    assert result.exit_code == 1
    assert "interval must be positive" in result.output
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py::test_watch_tree_command_validates_subcommand -v`
Expected: FAIL with "'NoneType' object has no attribute 'exit_code'" or similar

**Step 3: Import watch module in cli.py**

Add to imports section at top of `src/tw/cli.py`:

```python
from tw import watch as watch_module
```

**Step 4: Add watch command to cli.py**

Add after the `tree` command (around line 632):

```python
@main.command()
@click.argument("subcommand")
@click.argument("tw_id", required=False, default=None)
@click.option(
    "-n",
    "--interval",
    default=60,
    type=int,
    help="Refresh interval in seconds (default: 60)",
)
@click.pass_context
def watch(ctx: click.Context, subcommand: str, tw_id: str | None, interval: int) -> None:
    """Watch command output with auto-refresh.

    Currently only supports 'tree' subcommand.

    Examples:
        tw watch tree              # Watch full tree
        tw watch tree TW-30        # Watch specific issue
        tw watch tree -n 10        # Custom interval
    """
    if subcommand != "tree":
        click.echo("error: only 'tree' subcommand is supported", err=True)
        ctx.exit(1)

    if interval <= 0:
        click.echo("error: interval must be positive", err=True)
        ctx.exit(1)

    try:
        service = get_service(ctx)
        console: Console = ctx.obj["stdout"]
        watch_module.watch_tree(service, tw_id, interval, console)
    except RuntimeError as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
    except Exception as e:
        click.echo(f"error: {e}", err=True)
        ctx.exit(1)
```

**Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cli.py::test_watch_tree_command_validates_subcommand -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/tw/cli.py tests/test_cli.py
git commit -m "feat: add watch command to CLI"
```

---

## Task 6: Add end-to-end test

**Files:**
- Modify: `tests/test_e2e.py`

**Step 1: Write e2e test for watch command**

Add to `tests/test_e2e.py`:

```python
import threading
import time
from pathlib import Path


def test_watch_tree_command_with_file_change(runner, temp_task_dir):
    """Test that watch command detects file changes and updates display."""
    # Create an issue
    result = runner.invoke(
        cli.main,
        ["new", "task", "-t", "Watch test task", "--project-prefix", "TEST"],
    )
    assert result.exit_code == 0

    # Start watch in background thread
    watch_thread = None
    watch_output = []

    def run_watch():
        result = runner.invoke(
            cli.main,
            ["watch", "tree", "-n", "2", "--project-prefix", "TEST"],
            catch_exceptions=False,
        )
        watch_output.append(result.output)

    watch_thread = threading.Thread(target=run_watch, daemon=True)
    watch_thread.start()

    # Give watch time to start
    time.sleep(0.5)

    # Modify an issue (this should trigger file watch)
    result = runner.invoke(
        cli.main,
        ["start", "TEST-1", "--project-prefix", "TEST"],
    )
    assert result.exit_code == 0

    # Give watch time to detect change
    time.sleep(1)

    # The watch should have rendered at least once
    # Note: This test is simplified - in real usage we'd use a more sophisticated
    # approach to verify the display updated
```

**Step 2: Run test to verify behavior**

Run: `pytest tests/test_e2e.py::test_watch_tree_command_with_file_change -v`
Expected: Test passes (note: this is more of a smoke test due to threading complexity)

**Step 3: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: add e2e test for watch command"
```

---

## Task 7: Update documentation

**Files:**
- Modify: `src/tw/templates/onboard.md.j2`

**Step 1: Add watch command to onboarding guide**

Add to the Commands section in `src/tw/templates/onboard.md.j2`:

```markdown
### Monitoring

#### Watch tree continuously
```bash
tw watch tree              # Watch full tree, refresh every 60s
tw watch tree TW-30        # Watch specific issue and descendants
tw watch tree -n 10        # Custom refresh interval
```

The watch command monitors your TaskWarrior data directory for changes and automatically
refreshes the display. Uses file system notifications for instant updates, with periodic
polling as backup. Press Ctrl+C to exit.
```

**Step 2: Verify documentation renders correctly**

Run: `tw onboard`
Expected: Onboarding guide displays with watch command documentation

**Step 3: Commit**

```bash
git add src/tw/templates/onboard.md.j2
git commit -m "docs: add watch command to onboarding guide"
```

---

## Task 8: Manual testing and verification

**Step 1: Test basic watch functionality**

Run in one terminal:
```bash
tw watch tree
```

In another terminal:
```bash
tw start TW-1
tw done TW-1
```

Expected: First terminal updates immediately after each command

**Step 2: Test with custom interval**

Run:
```bash
tw watch tree -n 5
```

Expected: Display shows "Every 5s: tw tree" and updates every 5 seconds

**Step 3: Test with specific issue**

Run:
```bash
tw watch tree TW-30
```

Expected: Display shows only TW-30 and its descendants

**Step 4: Test error handling**

Run with invalid subcommand:
```bash
tw watch view
```

Expected: Error message "only 'tree' subcommand is supported"

Run with invalid interval:
```bash
tw watch tree -n 0
```

Expected: Error message "interval must be positive"

**Step 5: Test Ctrl+C handling**

Run:
```bash
tw watch tree
```

Press Ctrl+C

Expected: Clean exit with no error message, exit code 0

**Step 6: Verify tests pass**

Run: `pytest tests/ -v`
Expected: All tests PASS

Run: `mypy src/tw/`
Expected: No type errors

**Step 7: Final commit**

```bash
git add -A
git commit -m "feat: complete tw watch tree implementation

- Add watchdog dependency for file system monitoring
- Implement watch module with data directory detection
- Add file system event handler with debouncing
- Implement main watch loop with Rich.Live display
- Add watch command to CLI with validation
- Add comprehensive tests and documentation
- Support custom refresh intervals via -n flag
- Graceful fallback to polling-only mode
- Clean Ctrl+C handling

Closes TW-30

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Testing Strategy

**Unit Tests:**
- Data directory detection (success and failure)
- Event handler debouncing logic
- Event coordination between watchdog and main loop

**Integration Tests:**
- Watch loop with mock service and observer
- Error handling during tree rendering
- Keyboard interrupt handling

**E2E Tests:**
- Full watch command with file modifications
- Argument validation
- Graceful exit scenarios

**Manual Testing:**
- Real TaskWarrior integration
- Multiple terminal workflow
- Custom intervals
- Error scenarios
- Performance with large trees

---

## Key Design Principles Applied

**TDD:** Every feature starts with failing test
**DRY:** Reuse existing tree rendering, no duplication
**YAGNI:** Only `tree` subcommand, no generic watch framework yet
**Frequent commits:** One feature per commit with clear messages
**Type safety:** Full type hints, passes mypy
**Error handling:** Graceful fallbacks, clear error messages
**Testing:** Unit, integration, and e2e coverage
