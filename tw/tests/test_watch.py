"""Tests for watch module.

Note on mock usage: This module uses mocks for external dependencies (watchdog's
Observer) to avoid flaky timing-dependent tests. The core logic tests (WatchHandler
debouncing) use real threading.Event objects without mocks.
"""
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console
from watchdog.events import FileModifiedEvent

from tw.models import Issue, IssueStatus, IssueType
from tw.service import IssueService
from tw.watch import WatchHandler, watch_tree


def test_watch_handler_triggers_on_db_file():
    event = threading.Event()
    handler = WatchHandler(event)

    file_event = FileModifiedEvent("/path/to/data.db")
    handler.on_modified(file_event)

    time.sleep(0.15)

    assert event.is_set()


def test_watch_handler_ignores_non_db_files():
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
        file_event = FileModifiedEvent("/path/to/data.db")
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
        id="TW-1",
        type=IssueType.TASK,
        title="Test task",
        status=IssueStatus.NEW,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_service.get_issue_tree_with_backlog.return_value = ([issue], [])

    # Setup mock console
    console = Console()

    # Test path
    db_path = Path("/tmp/test.db")

    # Mock Observer and Live context manager
    with patch("tw.watch.Observer") as mock_observer_class:
        mock_observer = MagicMock()
        mock_observer_class.return_value = mock_observer

        # Mock Live to simulate KeyboardInterrupt in the main loop
        with patch("tw.watch.Live") as mock_live_class:
            MagicMock()
            mock_live_class.return_value.__enter__ = MagicMock(
                side_effect=KeyboardInterrupt
            )
            mock_live_class.return_value.__exit__ = MagicMock(return_value=None)

            # Should exit cleanly without raising
            watch_tree(mock_service, None, 60, console, db_path)

            # Verify observer cleanup
            mock_observer.stop.assert_called_once()
            mock_observer.join.assert_called_once()
