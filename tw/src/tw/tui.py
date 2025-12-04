"""TUI application using Textual."""

import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Footer, Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option
from watchdog.observers import Observer as WatchdogObserver

from tw.backend import TaskWarriorBackend
from tw.config import get_prefix, get_project
from tw.models import Issue, IssueType
from tw.render import generate_edit_template, parse_edited_content
from tw.service import IssueService
from tw.watch import WatchHandler, get_taskwarrior_data_dir

logger = logging.getLogger(__name__)


@dataclass
class TreeNode:
    """A node in the tree representing an issue."""

    issue: Issue
    depth: int

    @property
    def tw_id(self) -> str:
        """Get the issue ID."""
        return self.issue.tw_id

    def render_line(self, is_selected: bool) -> str:
        """Render this node as a line for display.

        Args:
            is_selected: Whether this node is currently selected.

        Returns:
            Styled line of text for display.
        """
        indent = "  " * self.depth
        issue = self.issue

        if issue.tw_status.value == "done":
            status_str = f"[dim]({issue.tw_id}, done)[/dim]"
            title_part = f"[dim]{issue.title}[/dim]"
            type_part = f"[dim]{issue.tw_type.value}:[/dim]"
        elif issue.tw_status.value == "in_progress":
            status_str = (
                f"[dim]([/dim][dim]{issue.tw_id}[/dim]"
                f"[dim], [/dim][yellow]in_progress[/yellow]"
                f"[dim])[/dim]"
            )
            title_part = f"{issue.title}"
            type_part = f"[dim]{issue.tw_type.value}:[/dim]"
        elif issue.tw_status.value in ("blocked", "stopped"):
            status_str = (
                f"[dim]([/dim][dim]{issue.tw_id}[/dim]"
                f"[dim], [/dim][red]{issue.tw_status.value}[/red]"
                f"[dim])[/dim]"
            )
            title_part = f"{issue.title}"
            type_part = f"[dim]{issue.tw_type.value}:[/dim]"
        else:
            status_str = f"[dim]({issue.tw_id})[/dim]"
            title_part = f"{issue.title}"
            type_part = f"[dim]{issue.tw_type.value}:[/dim]"

        line = f"{indent}{type_part} {title_part} {status_str}"

        if is_selected:
            line = f"[reverse]{line}[/reverse]"

        return line


class TreePane(Container, can_focus=True):
    """Widget for displaying issue tree with navigation."""

    DEFAULT_CSS = """
    TreePane {
        height: 60%;
        border: solid $primary;
    }

    TreePane VerticalScroll {
        scrollbar-gutter: stable;
    }

    TreePane #tree_content {
        width: 100%;
    }
    """

    class SelectionChanged(Message):
        """Posted when selection changes."""

        def __init__(self, selected_id: str | None) -> None:
            super().__init__()
            self.selected_id = selected_id

    def __init__(self, service: IssueService) -> None:
        """Initialize TreePane.

        Args:
            service: IssueService instance for fetching data.
        """
        super().__init__()
        self.service = service
        self.nodes: list[TreeNode] = []
        self.selected_index: int = 0
        self._load_tree()

    def compose(self) -> ComposeResult:
        """Compose the scrollable tree content."""
        with VerticalScroll():
            yield Static("", id="tree_content")

    def on_mount(self) -> None:
        """Update content after mount."""
        self._update_content()

    def _load_tree(self) -> None:
        """Load the issue tree from service."""
        try:
            hierarchy, backlog = self.service.get_issue_tree_with_backlog()
            self.nodes = self._build_nodes(hierarchy) + self._build_backlog_nodes(backlog)
            if self.nodes:
                self.selected_index = 0
            else:
                self.selected_index = -1
        except Exception as e:
            logger.error(f"Failed to load tree: {e}")
            self.nodes = []
            self.selected_index = -1

    def _build_nodes(self, issues: list[Issue]) -> list[TreeNode]:
        """Build TreeNode list from hierarchy issues.

        Args:
            issues: Flat list of issues with parent relationships.

        Returns:
            List of TreeNode objects with proper depth.
        """
        nodes = []
        issue_map = {issue.tw_id: issue for issue in issues}

        def get_depth(issue: Issue) -> int:
            """Compute the depth of an issue in the tree."""
            depth = 0
            current = issue
            while current.tw_parent:
                depth += 1
                parent_issue = issue_map.get(current.tw_parent)
                if not parent_issue:
                    break
                current = parent_issue
            return depth

        for issue in issues:
            depth = get_depth(issue)
            nodes.append(TreeNode(issue=issue, depth=depth))

        return nodes

    def _build_backlog_nodes(self, backlog: list[Issue]) -> list[TreeNode]:
        """Build TreeNode list from backlog issues.

        Args:
            backlog: List of backlog issues (bugs/ideas).

        Returns:
            List of TreeNode objects for backlog (all at depth 0).
        """
        nodes = []
        for issue in backlog:
            nodes.append(TreeNode(issue=issue, depth=0))
        return nodes

    def _render_tree(self) -> str:
        """Render the tree with selection highlight."""
        if not self.nodes:
            return "[dim]No issues loaded[/dim]"

        lines = []
        for i, node in enumerate(self.nodes):
            is_selected = i == self.selected_index
            lines.append(node.render_line(is_selected))

        return "\n".join(lines)

    def _update_content(self) -> None:
        """Update the static content widget."""
        try:
            static = self.query_one("#tree_content", Static)
            static.update(self._render_tree())
        except Exception:
            pass

    def action_move_down(self) -> None:
        """Move selection down."""
        if self.nodes and self.selected_index < len(self.nodes) - 1:
            self.selected_index += 1
        if self.nodes:
            self._emit_selection_changed()
            self._update_content()
            self._scroll_to_selection()

    def action_move_up(self) -> None:
        """Move selection up."""
        if self.nodes and self.selected_index > 0:
            self.selected_index -= 1
            self._emit_selection_changed()
            self._update_content()
            self._scroll_to_selection()

    def on_click(self, event: Click) -> None:
        """Handle mouse click to select a row."""
        if not self.nodes:
            return
        try:
            scroll = self.query_one(VerticalScroll)
            # Convert screen coordinates to position within scroll viewport
            scroll_y_on_screen = scroll.region.y
            click_in_scroll = event.screen_y - scroll_y_on_screen
            if click_in_scroll < 0:
                return
            click_y = click_in_scroll + int(scroll.scroll_y)
            if 0 <= click_y < len(self.nodes):
                self.selected_index = click_y
                self._emit_selection_changed()
                self._update_content()
        except Exception:
            pass

    def _scroll_to_selection(self) -> None:
        """Scroll to keep the selected line visible."""
        if self.selected_index < 0 or not self.nodes:
            return
        try:
            scroll = self.query_one(VerticalScroll)
            scroll.scroll_to(y=self.selected_index, animate=False)
        except Exception:
            pass

    def _emit_selection_changed(self) -> None:
        """Emit SelectionChanged event for current selection."""
        if self.nodes and 0 <= self.selected_index < len(self.nodes):
            selected_id = self.nodes[self.selected_index].tw_id
            self.post_message(self.SelectionChanged(selected_id))
        else:
            self.post_message(self.SelectionChanged(None))

    def get_selected_issue_id(self) -> str | None:
        """Get the currently selected issue ID.

        Returns:
            The selected issue's tw_id or None if nothing selected.
        """
        if self.nodes and 0 <= self.selected_index < len(self.nodes):
            return self.nodes[self.selected_index].tw_id
        return None

    def refresh_tree(self) -> None:
        """Refresh the tree data and content."""
        selected_id = self.get_selected_issue_id()
        self._load_tree()
        if selected_id:
            for i, node in enumerate(self.nodes):
                if node.tw_id == selected_id:
                    self.selected_index = i
                    break
            else:
                if self.nodes:
                    self.selected_index = 0
        self._emit_selection_changed()
        self._update_content()


class DetailPane(Container):
    """Widget for displaying issue detail view with full context."""

    DEFAULT_CSS = """
    DetailPane {
        height: 40%;
        border: solid $accent;
        overflow-y: auto;
    }

    DetailPane Markdown {
        padding: 0 1;
    }

    DetailPane #detail_links {
        padding: 0 1;
    }
    """

    def __init__(self, service: IssueService | None) -> None:
        """Initialize DetailPane.

        Args:
            service: IssueService instance for fetching data.
        """
        super().__init__()
        self.service = service
        self.selected_id: str | None = None
        self._content: str = ""

    def compose(self) -> ComposeResult:
        """Compose the Markdown and Static widgets."""
        yield Markdown("", id="detail_markdown")
        yield Static("", id="detail_links")

    def update_detail(self, issue_id: str | None) -> None:
        """Update detail pane with issue view data.

        Args:
            issue_id: The ID of the issue to display, or None to clear.
        """
        self.selected_id = issue_id
        if not issue_id or not self.service:
            self._content = ""
            self._update_content("", "")
            return

        try:
            from tw.render import render_view_body, render_view_links

            issue, ancestors, siblings, descendants, referenced, referencing = (
                self.service.get_issue_with_context(issue_id)
            )
            body_content = render_view_body(issue)
            links_content = render_view_links(
                ancestors=ancestors,
                siblings=siblings,
                descendants=descendants,
                referenced=referenced,
                referencing=referencing,
            )
            self._content = body_content + links_content
        except Exception as e:
            logger.error(f"Failed to load detail for {issue_id}: {e}")
            self._content = f"Error: {e}"
            self._update_content(f"Error: {e}", "")
            return

        self._update_content(body_content, links_content)

    def _update_content(self, body: str, links: str) -> None:
        """Update the Markdown and Static widget contents."""
        try:
            md = self.query_one("#detail_markdown", Markdown)
            md.update(body or "*No issue selected*")
        except Exception:
            pass
        try:
            static = self.query_one("#detail_links", Static)
            static.update(links)
        except Exception:
            pass


class InputDialog(Static):
    """Modal input dialog for creating new issues."""

    DEFAULT_CSS = """
    InputDialog {
        width: 100%;
        height: auto;
        dock: bottom;
    }

    InputDialog Input {
        width: 100%;
        border: none;
        background: $panel;
    }
    """

    def __init__(self, title: str, callback: Any) -> None:
        """Initialize InputDialog.

        Args:
            title: Prompt title to display.
            callback: Function to call with input value on submit.
        """
        super().__init__()
        self.title_text = title
        self.callback = callback
        self.input_widget: Input | None = None

    def compose(self) -> ComposeResult:
        """Compose the input widget."""
        self.input_widget = Input(id="issue_input", placeholder=self.title_text)
        yield self.input_widget

    def on_mount(self) -> None:
        """Focus the input widget when mounted."""
        if self.input_widget:
            self.input_widget.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        event.stop()
        if self.input_widget:
            self.callback(self.input_widget.value)
        self._remove_dialog()

    def action_close_dialog(self) -> None:
        """Close the dialog on escape."""
        self._remove_dialog()

    def _remove_dialog(self) -> None:
        """Remove the dialog from the app."""
        try:
            self.remove()
        except Exception:
            pass


class PickerDialog(Static):
    """Modal picker dialog for selecting from a list with filtering."""

    DEFAULT_CSS = """
    PickerDialog {
        width: 100%;
        height: 20;
        border: heavy $primary;
        background: $panel;
        padding: 0 2;
        dock: bottom;
    }

    PickerDialog .picker-title {
        width: 100%;
        text-align: center;
        margin-bottom: 0;
        text-style: bold;
    }

    PickerDialog Input {
        width: 100%;
        margin-bottom: 0;
    }

    PickerDialog OptionList {
        width: 100%;
        height: 1fr;
    }
    """

    def __init__(self, title: str, options: list[tuple[str, str]], callback: Any) -> None:
        """Initialize PickerDialog.

        Args:
            title: Dialog title to display.
            options: List of (id, display_text) tuples for options.
            callback: Function to call with selected id on submit.
        """
        super().__init__()
        self.title_text = title
        self.options = options
        self.filtered_options = options[:]
        self.callback = callback
        self.input_widget: Input | None = None
        self.option_list: OptionList | None = None

    def render(self) -> str:
        """Render the dialog title."""
        return f"[bold]{self.title_text}[/bold]"

    def compose(self) -> ComposeResult:
        """Compose the input and option list widgets."""
        self.input_widget = Input(id="picker_input", placeholder="Type to filter...")
        yield self.input_widget
        self.option_list = OptionList()
        yield self.option_list

    def on_mount(self) -> None:
        """Focus the input widget when mounted and populate options."""
        if self.input_widget:
            self.input_widget.focus()
        self._update_option_list()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter options as user types."""
        event.stop()
        self._filter_and_update(event.value)

    def _filter_and_update(self, query: str) -> None:
        """Filter options based on query and update list.

        Args:
            query: The filter query string.
        """
        query_lower = query.lower()
        self.filtered_options = [
            (opt_id, display)
            for opt_id, display in self.options
            if query_lower in opt_id.lower() or query_lower in display.lower()
        ]
        self._update_option_list()

    def _update_option_list(self) -> None:
        """Update the option list with filtered options."""
        if not self.option_list:
            return

        self.option_list.clear_options()
        for opt_id, display in self.filtered_options:
            self.option_list.add_option(Option(display, opt_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        event.stop()
        self.callback(event.option.id)
        self._remove_dialog()

    def action_close_picker(self) -> None:
        """Close the picker on escape."""
        self._remove_dialog()

    def _remove_dialog(self) -> None:
        """Remove the dialog from the app."""
        try:
            self.remove()
        except Exception:
            pass


class TwTuiApp(App[None]):
    """Main TUI application for tw issue tracker."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("j", "tree_move_down", "Down", show=False),
        Binding("k", "tree_move_up", "Up", show=False),
        Binding("down", "tree_move_down", "Down", show=False),
        Binding("up", "tree_move_up", "Up", show=False),
        Binding("s", "start", "Start"),
        Binding("d", "done", "Done"),
        Binding("e", "edit", "Edit"),
        Binding("n", "new_child", "New"),
        Binding("N", "new_epic", "Epic"),
        Binding("b", "new_bug", "Bug"),
        Binding("i", "new_idea", "Idea"),
        Binding("p", "promote_issue", "Promote"),
        Binding("c", "comment", "Comment"),
        Binding("g", "groom", "Groom"),
        Binding("escape", "close_dialogs", "Close", show=False),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #main_container {
        height: 1fr;
        overflow: hidden;
    }
    """

    def __init__(self) -> None:
        """Initialize the app."""
        super().__init__()
        backend = TaskWarriorBackend()
        self.service: IssueService | None = None
        try:
            self.service = IssueService(
                backend=backend,
                project=get_project(),
                prefix=get_prefix(),
            )
        except Exception as e:
            logger.error(f"Failed to initialize service: {e}")
        self._input_dialog: InputDialog | None = None
        self._picker_dialog: PickerDialog | None = None
        self._file_watch_event = threading.Event()
        self._observer: WatchdogObserver | None = None  # type: ignore[valid-type]
        self._watch_handler: WatchHandler | None = None
        self.refresh_pending = False
        self.last_keypress_time = time.time()
        self._refresh_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        """Compose the layout with TreePane, DetailPane, and Footer."""
        with Container(id="main_container"):
            if self.service:
                yield TreePane(service=self.service)
            else:
                yield Static("[red]Failed to initialize service[/red]")
            if self.service:
                yield DetailPane(service=self.service)
            else:
                yield DetailPane(service=None)
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted; initialize detail pane and file watching."""
        try:
            tree_pane = self.query_one(TreePane)
            detail_pane = self.query_one(DetailPane)
            selected_id = tree_pane.get_selected_issue_id()
            if selected_id:
                detail_pane.update_detail(selected_id)
        except Exception:
            pass

        self._setup_file_watching()
        self._start_refresh_timer()

    def _setup_file_watching(self) -> None:
        """Set up file watching on TaskWarrior data directory."""
        try:
            data_dir = get_taskwarrior_data_dir()
            self._watch_handler = WatchHandler(self._file_watch_event)
            self._observer = WatchdogObserver()
            self._observer.schedule(self._watch_handler, str(data_dir), recursive=False)
            self._observer.start()
            logger.debug(f"File watching started on {data_dir}")
        except Exception as e:
            logger.warning(f"File watching setup failed: {e}")

    def _start_refresh_timer(self) -> None:
        """Start the periodic refresh timer (every 500ms)."""
        self._refresh_timer = self.set_timer(0.5, self._check_and_refresh, pause=False)

    def _check_and_refresh(self) -> None:
        """Check if refresh should happen based on file changes and idle time."""
        now = time.time()
        idle_time = now - self.last_keypress_time

        if self._file_watch_event.is_set() and idle_time > 2.0:
            self.refresh_pending = True
            self._file_watch_event.clear()

        if self.refresh_pending and idle_time > 2.0:
            self._do_refresh()
            self.refresh_pending = False

    def _do_refresh(self) -> None:
        """Perform the actual tree refresh while preserving selection."""
        self._refresh_tree()

    def _refresh_tree(self) -> None:
        """Refresh the tree pane and detail pane."""
        try:
            tree_pane = self.query_one(TreePane)
            selected_id = tree_pane.get_selected_issue_id()
            tree_pane._load_tree()
            if selected_id:
                for i, node in enumerate(tree_pane.nodes):
                    if node.tw_id == selected_id:
                        tree_pane.selected_index = i
                        break
                else:
                    if tree_pane.nodes:
                        tree_pane.selected_index = 0
            tree_pane._emit_selection_changed()
            tree_pane._update_content()
            tree_pane._scroll_to_selection()
        except Exception as e:
            logger.error(f"Failed to refresh tree: {e}")

    def _on_keypress(self) -> None:
        """Update last keypress time to detect idle."""
        self.last_keypress_time = time.time()

    def action_tree_move_down(self) -> None:
        """Move tree selection down."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            tree_pane.action_move_down()
        except Exception:
            pass

    def action_tree_move_up(self) -> None:
        """Move tree selection up."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            tree_pane.action_move_up()
        except Exception:
            pass

    def on_tree_pane_selection_changed(self, message: TreePane.SelectionChanged) -> None:
        """Handle selection change from tree pane."""
        try:
            detail_pane = self.query_one(DetailPane)
            detail_pane.update_detail(message.selected_id)
        except Exception:
            pass

    def action_start(self) -> None:
        """Start the selected issue."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            selected_id = tree_pane.get_selected_issue_id()
            if not selected_id:
                self.show_status_message("No issue selected", is_error=True)
                return

            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            try:
                self.service.start_issue(selected_id)
                self.show_status_message(f"Started {selected_id}")
                self._refresh_tree()
            except Exception as e:
                self.show_status_message(f"Failed to start: {e}", is_error=True)
        except Exception:
            pass

    def action_done(self) -> None:
        """Mark the selected issue as done."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            selected_id = tree_pane.get_selected_issue_id()
            if not selected_id:
                self.show_status_message("No issue selected", is_error=True)
                return

            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            try:
                self.service.done_issue(selected_id)
                self.show_status_message(f"Marked {selected_id} as done")
                self._refresh_tree()
            except Exception as e:
                self.show_status_message(f"Failed to mark done: {e}", is_error=True)
        except Exception:
            pass

    def action_edit(self) -> None:
        """Edit the selected issue in external editor."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            selected_id = tree_pane.get_selected_issue_id()
            if not selected_id:
                self.show_status_message("No issue selected", is_error=True)
                return

            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            try:
                issue = self.service.get_issue(selected_id)
                editor = os.environ.get("EDITOR", "vi")
                template = generate_edit_template(issue.title, issue.tw_body)

                with tempfile.NamedTemporaryFile(mode="w+", suffix=".md", delete=False) as tmp:
                    tmp.write(template)
                    tmp_path = tmp.name

                try:
                    with self.suspend():
                        subprocess.run([editor, tmp_path], check=True)

                    with open(tmp_path) as f:
                        content = f.read()

                    new_title, new_body = parse_edited_content(content)
                    self.service.update_issue(selected_id, title=new_title, body=new_body)
                    self.show_status_message(f"Updated {selected_id}")
                    self._refresh_tree()
                finally:
                    os.unlink(tmp_path)
            except Exception as e:
                self.show_status_message(f"Failed to edit: {e}", is_error=True)
        except Exception:
            pass

    def action_comment(self) -> None:
        """Add a comment to the selected issue (c)."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            selected_id = tree_pane.get_selected_issue_id()
            if not selected_id:
                self.show_status_message("No issue selected", is_error=True)
                return

            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            service = self.service

            def add_comment(text: str) -> None:
                if not text.strip():
                    return

                try:
                    from tw.models import AnnotationType

                    service.record_annotation(selected_id, AnnotationType.COMMENT, text.strip())
                    self.show_status_message(f"Added comment to {selected_id}")
                    self._refresh_tree()
                except Exception as e:
                    self.show_status_message(f"Failed to add comment: {e}", is_error=True)

            self._show_input_dialog("Comment...", add_comment)
        except Exception:
            pass

    def action_groom(self) -> None:
        """Groom backlog items via external editor (g)."""
        self._on_keypress()
        try:
            try:
                with self.suspend():
                    subprocess.run(["tw", "groom"], check=True)

                self.show_status_message("Groomed backlog")
                self._refresh_tree()
            except Exception as e:
                self.show_status_message(f"Failed to groom: {e}", is_error=True)
        except Exception:
            pass

    def show_status_message(self, text: str, is_error: bool = False) -> None:
        """Log a status message.

        Args:
            text: Message text to log.
            is_error: If True, log as error; if False, log as info.
        """
        if is_error:
            logger.error(text)
        else:
            logger.info(text)

    def _cleanup(self) -> None:
        """Clean up resources on app exit."""
        if self._refresh_timer:
            self._refresh_timer.stop()
        if self._observer:
            try:
                if self._watch_handler:
                    self._watch_handler.cleanup()
                self._observer.stop()  # type: ignore[attr-defined]
                self._observer.join(timeout=1.0)  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning(f"Error during observer cleanup: {e}")

    async def action_quit(self) -> None:
        """Handle quit action with cleanup."""
        self._cleanup()
        self.exit()

    def _show_input_dialog(self, title: str, callback: Any) -> None:
        """Show an input dialog for creating new issues.

        Args:
            title: Prompt title to display.
            callback: Function to call with input value on submit.
        """
        try:
            if self._input_dialog:
                self._input_dialog.remove()
        except Exception:
            pass

        self._input_dialog = InputDialog(title, callback)
        self.mount(self._input_dialog)

    def action_close_dialogs(self) -> None:
        """Close all dialogs on escape."""
        if self._input_dialog:
            try:
                self._input_dialog.remove()
                self._input_dialog = None
            except Exception:
                pass
        if self._picker_dialog:
            try:
                self._picker_dialog.remove()
                self._picker_dialog = None
            except Exception:
                pass

    def action_new_child(self) -> None:
        """Create a new child issue (n)."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            selected_id = tree_pane.get_selected_issue_id()
            if not selected_id:
                self.show_status_message("No issue selected", is_error=True)
                return

            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            try:
                parent_issue = self.service.get_issue(selected_id)
                service = self.service

                def create_child(title: str) -> None:
                    """Create the child issue with the provided title."""
                    if not title.strip():
                        self.show_status_message("Title cannot be empty", is_error=True)
                        return

                    try:
                        child_type = self._infer_child_type(parent_issue.tw_type)
                        new_id = service.create_issue(
                            issue_type=child_type,
                            title=title.strip(),
                            parent_id=selected_id,
                        )
                        self.show_status_message(f"Created {new_id}")
                        self._refresh_tree()
                    except Exception as e:
                        self.show_status_message(f"Failed to create child: {e}", is_error=True)

                self._show_input_dialog("Enter child issue title:", create_child)
            except Exception as e:
                self.show_status_message(f"Failed to get parent issue: {e}", is_error=True)
        except Exception:
            pass

    def action_new_epic(self) -> None:
        """Create a new top-level epic (N)."""
        self._on_keypress()
        try:
            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            service = self.service

            def create_epic(title: str) -> None:
                """Create the epic with the provided title."""
                if not title.strip():
                    self.show_status_message("Title cannot be empty", is_error=True)
                    return

                try:
                    new_id = service.create_issue(
                        issue_type=IssueType.EPIC,
                        title=title.strip(),
                    )
                    self.show_status_message(f"Created {new_id}")
                    self._refresh_tree()
                except Exception as e:
                    self.show_status_message(f"Failed to create epic: {e}", is_error=True)

            self._show_input_dialog("Enter epic title:", create_epic)
        except Exception:
            pass

    def action_new_bug(self) -> None:
        """Create a new bug in backlog (b)."""
        self._on_keypress()
        try:
            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            service = self.service

            def create_bug(title: str) -> None:
                """Create the bug with the provided title."""
                if not title.strip():
                    self.show_status_message("Title cannot be empty", is_error=True)
                    return

                try:
                    new_id = service.create_issue(
                        issue_type=IssueType.BUG,
                        title=title.strip(),
                    )
                    self.show_status_message(f"Created {new_id}")
                    self._refresh_tree()
                except Exception as e:
                    self.show_status_message(f"Failed to create bug: {e}", is_error=True)

            self._show_input_dialog("Enter bug title:", create_bug)
        except Exception:
            pass

    def action_new_idea(self) -> None:
        """Create a new idea in backlog (i)."""
        self._on_keypress()
        try:
            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            service = self.service

            def create_idea(title: str) -> None:
                """Create the idea with the provided title."""
                if not title.strip():
                    self.show_status_message("Title cannot be empty", is_error=True)
                    return

                try:
                    new_id = service.create_issue(
                        issue_type=IssueType.IDEA,
                        title=title.strip(),
                    )
                    self.show_status_message(f"Created {new_id}")
                    self._refresh_tree()
                except Exception as e:
                    self.show_status_message(f"Failed to create idea: {e}", is_error=True)

            self._show_input_dialog("Enter idea title:", create_idea)
        except Exception:
            pass

    def action_promote_issue(self) -> None:
        """Promote a backlog item to a child issue (p)."""
        self._on_keypress()
        try:
            tree_pane = self.query_one(TreePane)
            selected_id = tree_pane.get_selected_issue_id()
            if not selected_id:
                self.show_status_message("No issue selected", is_error=True)
                return

            if not self.service:
                self.show_status_message("Service not initialized", is_error=True)
                return

            try:
                selected_issue = self.service.get_issue(selected_id)
                from tw.models import is_backlog_type

                if not is_backlog_type(selected_issue.tw_type):
                    msg = (
                        f"Cannot promote {selected_issue.tw_type.value}: "
                        "only backlog items (bug/idea) can be promoted"
                    )
                    self.show_status_message(msg, is_error=True)
                    return

                hierarchy, _ = self.service.get_issue_tree_with_backlog()
                epics_and_stories = [
                    issue
                    for issue in hierarchy
                    if issue.tw_type in (IssueType.EPIC, IssueType.STORY)
                ]

                if not epics_and_stories:
                    self.show_status_message(
                        "No epics or stories available as parents", is_error=True
                    )
                    return

                options = [
                    (issue.tw_id, f"{issue.tw_id}: {issue.title}") for issue in epics_and_stories
                ]
                service = self.service

                def promote_to_parent(parent_id: str) -> None:
                    """Promote the backlog item under the selected parent."""
                    try:
                        parent_issue = service.get_issue(parent_id)
                        child_type = self._infer_promoted_type(parent_issue.tw_type)

                        new_id = service.create_issue(
                            issue_type=child_type,
                            title=selected_issue.title,
                            parent_id=parent_id,
                            body=selected_issue.tw_body,
                        )

                        service.done_issue(selected_id)
                        self.show_status_message(
                            f"Promoted {selected_id} to {new_id} under {parent_id}"
                        )
                        self._refresh_tree()
                    except Exception as e:
                        self.show_status_message(f"Failed to promote: {e}", is_error=True)

                self._show_picker_dialog("Select parent epic or story:", options, promote_to_parent)
            except Exception as e:
                self.show_status_message(f"Failed to promote: {e}", is_error=True)
        except Exception:
            pass

    def _infer_child_type(self, parent_type: IssueType) -> IssueType:
        """Infer the child issue type based on parent type.

        Args:
            parent_type: The parent issue's type.

        Returns:
            The appropriate child issue type.
        """
        if parent_type == IssueType.EPIC:
            return IssueType.STORY
        else:
            return IssueType.TASK

    def _infer_promoted_type(self, parent_type: IssueType) -> IssueType:
        """Infer the promoted issue type based on parent type.

        Args:
            parent_type: The parent issue's type.

        Returns:
            The appropriate issue type for a promoted backlog item.
        """
        if parent_type == IssueType.EPIC:
            return IssueType.STORY
        else:
            return IssueType.TASK

    def _show_picker_dialog(
        self, title: str, options: list[tuple[str, str]], callback: Any
    ) -> None:
        """Show a picker dialog for selecting from options.

        Args:
            title: Dialog title to display.
            options: List of (id, display_text) tuples for options.
            callback: Function to call with selected id on submit.
        """
        try:
            if self._picker_dialog:
                self._picker_dialog.remove()
        except Exception:
            pass

        self._picker_dialog = PickerDialog(title, options, callback)
        self.mount(self._picker_dialog)


def main() -> None:
    """Entry point for the TUI application."""
    app = TwTuiApp()
    app.run()


if __name__ == "__main__":
    main()
