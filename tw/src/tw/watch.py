import logging
import threading
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.text import Text
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from tw.render import render_tree_with_backlog
from tw.service import IssueService

logger = logging.getLogger(__name__)


class WatchHandler(FileSystemEventHandler):
    """File system event handler with debouncing.

    Triggers refresh event when database files are modified, with 100ms debounce.
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
        if not hasattr(event, 'src_path'):
            return

        src_path = getattr(event, 'src_path')
        if not isinstance(src_path, str) or not src_path.endswith('.db'):
            return

        with self.lock:
            if self.timer is not None:
                self.timer.cancel()

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


def watch_tree(
    service: IssueService,
    tw_id: str | None,
    interval: int,
    console: Console,
    db_path: Path,
) -> None:
    """Watch tree output with auto-refresh.

    Monitors SQLite database file for changes and refreshes tree display.
    Uses hybrid file watching + polling approach.

    Args:
        service: IssueService instance
        tw_id: Optional issue ID to filter tree
        interval: Poll interval in seconds
        console: Rich console for output
        db_path: Path to the SQLite database file
    """
    refresh_event = threading.Event()

    handler = WatchHandler(refresh_event)
    observer = Observer()
    use_watchdog = True

    try:
        observer.schedule(handler, str(db_path.parent), recursive=False)
        observer.start()
    except Exception as e:
        logger.warning(f"File watching unavailable, using polling only: {e}")
        use_watchdog = False

    try:
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                try:
                    hierarchy, backlog = service.get_issue_tree_with_backlog(tw_id)
                    prefix = service.prefix
                    hierarchy = [i for i in hierarchy if i.id.startswith(prefix)]
                    backlog = [i for i in backlog if i.id.startswith(prefix)]
                    tree_output = render_tree_with_backlog(hierarchy, backlog)

                    display = Text()
                    cmd_parts = ["Every", f"{interval}s:", "tw", "tree"]
                    if tw_id:
                        cmd_parts.append(tw_id)
                    display.append(" ".join(cmd_parts), style="bold")
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    display.append(f"  {timestamp}\n\n", style="dim")
                    display.append(Text.from_markup(tree_output))

                    live.update(display)

                    refresh_event.wait(timeout=interval)
                    refresh_event.clear()

                except Exception as e:
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
