# tw watch tree - Design Document

**Date:** 2025-12-04
**Issue:** TW-30
**Status:** Design Complete

## Overview

Add `tw watch tree` command for continuous monitoring of issue tree. Uses file system notifications and polling to auto-refresh the display as TaskWarrior data changes.

## Use Case

Primary use case is continuous monitoring while working - keep `tw tree` open in a terminal pane/window and see updates as you work on issues in another terminal.

## Command Interface

```bash
tw watch tree [TW_ID] [-n SECONDS]
```

**Arguments:**
- `tree` - Required positional argument (only supported subcommand for now)
- `TW_ID` - Optional issue ID to filter tree view (passed through to underlying tree command)
- `-n, --interval` - Poll interval in seconds (default: 60)

**Examples:**
```bash
tw watch tree              # Watch full tree, refresh every 60s
tw watch tree TW-30        # Watch TW-30 and descendants
tw watch tree -n 10        # Watch with 10s poll interval
tw watch tree TW-30 -n 5   # Combined
```

**Validation:**
- Only `tree` subcommand supported (hard error for others)
- Interval must be positive integer

## Architecture

### Components

**New File: `src/tw/watch.py`**

Core watch functionality:

1. `get_taskwarrior_data_dir() -> Path`
   - Queries TaskWarrior config: `task _get rc.data.location`
   - Returns resolved Path to data directory
   - Respects custom TaskWarrior configurations

2. `WatchHandler(FileSystemEventHandler)`
   - Watchdog event handler
   - Debounces rapid successive changes (100ms window)
   - Filters for `.data` file modifications
   - Sets threading.Event when change detected

3. `watch_tree(service, tw_id, interval, console)`
   - Main watch loop
   - Coordinates file watching + polling
   - Manages Rich.Live display
   - Handles graceful shutdown

**Changes: `src/tw/cli.py`**

Add new `watch` command:
```python
@main.command()
@click.argument("subcommand")
@click.argument("tw_id", required=False)
@click.option("-n", "--interval", default=60, type=int)
@click.pass_context
def watch(ctx, subcommand, tw_id, interval):
    # Validate subcommand == "tree"
    # Validate interval > 0
    # Call watch.watch_tree()
```

**Changes: `pyproject.toml`**

Add dependency:
```toml
dependencies = [
    # ... existing
    "watchdog>=3.0",
]
```

### Code Reuse

The watch command reuses existing functionality:
- `service.get_issue_tree_with_backlog(tw_id)` - Fetch tree data
- `render_tree_with_backlog(hierarchy, backlog)` - Render tree output

New code only handles watch-specific concerns: file monitoring, polling, display loop.

## File Watching Strategy

### Data Directory Detection

Query TaskWarrior's actual configuration:
```python
result = subprocess.run(
    ["task", "rc.confirmation=off", "_get", "rc.data.location"],
    capture_output=True, text=True
)
data_dir = Path(result.stdout.strip()).expanduser().resolve()
```

### Watchdog Configuration

- Monitor entire data directory
- Trigger on any `.data` file modification
- Debounce rapid changes (100ms window)
  - TaskWarrior may write multiple files in sequence
  - Wait 100ms after first change before triggering refresh
  - Reset timer if more changes arrive

### Hybrid Refresh Mechanism

Two triggers for refresh:
1. **File system event** - Watchdog detects .data file changes (after debounce)
2. **Timeout** - Poll interval expires (default 60s)

Coordination via `threading.Event`:
- Watchdog handler sets event on file change
- Main loop waits on event with timeout
- Either trigger causes immediate refresh

### Fallback Behavior

If watchdog fails to initialize (import error, observer setup fails):
- Log warning: `warning: file watching unavailable, using polling only`
- Continue in polling-only mode
- User experience degrades gracefully

## Display Implementation

### Rich.Live

Use Rich's Live display for auto-updating output:

```python
from rich.live import Live
from rich.text import Text

with Live(console=console, refresh_per_second=4) as live:
    while True:
        tree_output = render_tree_with_backlog(hierarchy, backlog)

        # Build display with header
        display = Text()
        display.append(f"Every {interval}s: tw tree", style="bold")
        display.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n",
                      style="dim")
        display.append(tree_output)

        live.update(display)

        # Wait for change or timeout
        wait_for_change_or_timeout(interval)
```

### Header Format

Similar to Unix `watch`:
- Line 1: Command + interval (bold) + timestamp (dim)
- Line 2: Blank separator
- Lines 3+: Tree output

Example:
```
Every 60s: tw tree  2025-12-04 14:32:15

task: implement feature (TW-1, in_progress)
...
```

If watching specific issue:
```
Every 60s: tw tree TW-30  2025-12-04 14:32:15
```

## Error Handling

### Startup Errors

**TaskWarrior not available:**
- Detect when querying data directory fails
- Exit with: `error: failed to get TaskWarrior data directory`
- Exit code: 1

**Permission denied:**
- Detect during observer setup
- Exit with: `error: permission denied watching <directory>`
- Exit code: 1

**Invalid arguments:**
- Non-positive interval: `error: interval must be positive`
- Unsupported subcommand: `error: only 'tree' subcommand is supported`
- Exit code: 1

### Runtime Errors

**Tree rendering fails:**
- Catch exceptions during `get_issue_tree_with_backlog()`
- Display error in Live display (don't crash watch loop)
- Show: `Error: <message>`
- Keep watching for next update

**Watchdog fails:**
- Detect import errors or observer setup failures
- Log warning to stderr
- Continue in polling-only mode

### Graceful Shutdown

**Ctrl+C handling:**
```python
try:
    with Live(...) as live:
        # watch loop
except KeyboardInterrupt:
    observer.stop()
    observer.join()
    return  # Exit cleanly, no error message
```

Exit code: 0 (normal termination)

## Testing Approach

### Unit Tests

**Test: `get_taskwarrior_data_dir()`**
- Mock subprocess call
- Verify Path expansion and resolution
- Test error handling (non-zero exit code)

**Test: Debouncing logic**
- Simulate rapid file events
- Verify single refresh after debounce window

**Test: Event coordination**
- Verify event triggers on file change
- Verify timeout triggers after interval
- Verify event clears after handling

### Integration Tests

**Test: Full watch loop**
- Create temp TaskWarrior data directory
- Start watch in background thread
- Modify .data file
- Verify refresh triggered
- Send KeyboardInterrupt
- Verify clean shutdown

**Test: Fallback mode**
- Mock watchdog unavailable
- Verify polling-only mode works
- Verify warning logged

### Manual Testing

- Run `tw watch tree` in one terminal
- Run `tw start <issue>` in another
- Verify tree updates immediately
- Wait 60s, verify periodic refresh
- Test with `-n 5` for faster polling
- Test Ctrl+C shutdown

## Implementation Notes

### Debounce Implementation

```python
class WatchHandler(FileSystemEventHandler):
    def __init__(self, event: threading.Event):
        self.event = event
        self.timer = None

    def on_modified(self, event):
        if not event.src_path.endswith('.data'):
            return

        # Cancel existing timer
        if self.timer:
            self.timer.cancel()

        # Set new timer
        self.timer = threading.Timer(0.1, self._trigger_refresh)
        self.timer.start()

    def _trigger_refresh(self):
        self.event.set()
```

### Event Loop

```python
def watch_tree(service, tw_id, interval, console):
    data_dir = get_taskwarrior_data_dir()
    refresh_event = threading.Event()

    # Setup watchdog
    handler = WatchHandler(refresh_event)
    observer = Observer()
    observer.schedule(handler, str(data_dir), recursive=False)
    observer.start()

    try:
        with Live(console=console) as live:
            while True:
                # Render tree
                hierarchy, backlog = service.get_issue_tree_with_backlog(tw_id)
                display = build_display(hierarchy, backlog, interval, tw_id)
                live.update(display)

                # Wait for event or timeout
                refresh_event.wait(timeout=interval)
                refresh_event.clear()

    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
```

## Future Enhancements

These are explicitly out of scope for this design:

- Support for watching other commands (`view`, `digest`, etc.)
- Interactive features (scrolling, filtering)
- Diff highlighting (show what changed)
- Sound/visual notifications on status changes
- Configuration file for default interval
- Multiple tree views in split screen

When TW-33 (`tw tui`) is implemented with Textual, that will provide a richer interactive experience. This command is focused on simple, effective continuous monitoring.

## Dependencies

**New:**
- `watchdog>=3.0` - Cross-platform file system monitoring

**Existing (no changes):**
- `rich>=13.0` - Already used, adds Live display capability
- `click>=8.0` - Already used for CLI

## Summary

`tw watch tree` provides continuous monitoring of issue tree with:
- File system notifications for immediate updates
- Periodic polling (60s default) as fallback
- Clean Rich.Live display with timestamp header
- Graceful error handling and shutdown
- Minimal code - reuses existing tree rendering logic

Simple, focused implementation that solves the core use case without over-engineering.
