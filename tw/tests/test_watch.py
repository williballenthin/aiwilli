"""Tests for watch module.

Note on mock usage: This module uses mocks for external dependencies (subprocess
calls to TaskWarrior CLI and watchdog's Observer) which would otherwise require
TaskWarrior installation and create flaky timing-dependent tests. The core logic
tests (WatchHandler debouncing) use real threading.Event objects without mocks.
"""
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from watchdog.events import FileModifiedEvent

from tw.models import Issue, IssueStatus, IssueType
from tw.service import IssueService
from tw.watch import WatchHandler, get_taskwarrior_data_dir, watch_tree


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
        # Mock Observer and Live context manager
        with patch("tw.watch.Observer") as mock_observer_class:
            mock_observer = MagicMock()
            mock_observer_class.return_value = mock_observer

            # Mock Live to simulate KeyboardInterrupt in the main loop
            with patch("tw.watch.Live") as mock_live_class:
                mock_live_context = MagicMock()
                mock_live_class.return_value.__enter__ = MagicMock(
                    side_effect=KeyboardInterrupt
                )
                mock_live_class.return_value.__exit__ = MagicMock(return_value=None)

                # Should exit cleanly without raising
                watch_tree(mock_service, None, 60, console)

                # Verify observer cleanup
                mock_observer.stop.assert_called_once()
                mock_observer.join.assert_called_once()
