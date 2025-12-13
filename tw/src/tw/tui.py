"""Modern TUI for tw issue tracker using Textual best practices."""

import logging
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from rich.segment import Segment
from rich.style import Style as RichStyle
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color, Gradient
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.css.styles import RulesMap
from textual.events import Click
from textual.geometry import Offset
from textual.message import Message
from textual.reactive import reactive, var
from textual.strip import Strip
from textual.style import Style
from textual.timer import Timer
from textual.visual import RenderOptions, Visual
from textual.widget import Widget
from textual.widgets import Footer, Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from tw.backend import TaskWarriorBackend
from tw.config import get_prefix, get_project
from tw.models import AnnotationType, Issue, IssueStatus, IssueType, is_backlog_type
from tw.render import (
    generate_edit_template,
    parse_edited_content,
    render_view_body,
    render_view_links,
    status_timestamp,
)
from tw.service import IssueService
from tw.watch import WatchHandler, get_taskwarrior_data_dir

logger = logging.getLogger(__name__)

THROBBER_COLORS = [
    "#881177", "#aa3355", "#cc6666", "#ee9944",
    "#eedd00", "#99dd55", "#44dd88", "#22ccbb",
]


class ThrobberVisual(Visual):
    """Animated gradient bar visual for loading indicator."""

    gradient = Gradient.from_colors(*[Color.parse(c) for c in THROBBER_COLORS])

    def render_strips(
        self, width: int, height: int | None, style: Style, options: RenderOptions
    ) -> list[Strip]:
        time = monotonic()
        gradient = self.gradient
        background = style.rich_style.bgcolor
        strips = [
            Strip(
                [
                    Segment(
                        "━",
                        RichStyle.from_color(
                            gradient.get_rich_color((offset / width - time) % 1.0),
                            background,
                        ),
                    )
                    for offset in range(width)
                ],
                width,
            )
        ]
        return strips

    def get_optimal_width(self, rules: RulesMap, container_width: int) -> int:
        return container_width

    def get_height(self, rules: RulesMap, width: int) -> int:
        return 1


class Throbber(Widget):
    """Animated loading indicator widget."""

    DEFAULT_CSS = """
    Throbber {
        height: 1;
        width: 1fr;
        dock: top;
        layer: float;
        visibility: hidden;
        &.-busy {
            visibility: visible;
        }
    }
    """

    def on_mount(self) -> None:
        self.auto_refresh = 1 / 15

    def render(self) -> ThrobberVisual:
        return ThrobberVisual()


class Flash(Static):
    """Transient status message widget with auto-dismiss."""

    DEFAULT_CSS = """
    Flash {
        height: 1;
        width: 1fr;
        text-align: center;
        visibility: hidden;
        layer: float;
        dock: top;
        margin-top: 1;

        &.-visible {
            visibility: visible;
        }
        &.-success {
            background: $success 15%;
            color: $text;
        }
        &.-warning {
            background: $warning 15%;
            color: $text;
        }
        &.-error {
            background: $error 15%;
            color: $text;
        }
    }
    """

    flash_timer: Timer | None = None

    def flash(
        self,
        message: str,
        style: str = "success",
        duration: float = 2.5,
    ) -> None:
        if self.flash_timer is not None:
            self.flash_timer.stop()
        self.remove_class("-visible", "-success", "-warning", "-error")
        self.update(message)
        self.add_class("-visible", f"-{style}")

        def hide() -> None:
            self.remove_class("-visible")

        self.flash_timer = self.set_timer(duration, hide)


class Cursor(Static):
    """Animated cursor indicator that follows the selected issue."""

    DEFAULT_CSS = """
    Cursor {
        width: 1;
        height: 1;
        border-left: outer $text-accent;
        &.-blink {
            border-left: outer $text-accent 20%;
        }
    }
    """

    follow_widget: var[Widget | None] = var(None)
    blink: var[bool] = var(True)
    _blink_timer: Timer | None = None
    _follow_timer: Timer | None = None

    def on_mount(self) -> None:
        self.display = False
        self._blink_timer = self.set_interval(0.5, self._toggle_blink, pause=True)
        self._follow_timer = self.set_interval(0.1, self._update_follow)

    def _toggle_blink(self) -> None:
        self.blink = not self.blink
        self.set_class(self.blink, "-blink")

    def _update_follow(self) -> None:
        if self.follow_widget and self.follow_widget.is_attached:
            self.styles.height = max(1, self.follow_widget.outer_size.height)
            follow_y = self.follow_widget.virtual_region.y
            self.offset = Offset(0, follow_y)

    def follow(self, widget: Widget | None) -> None:
        self.follow_widget = widget
        self.blink = False
        self.set_class(False, "-blink")
        if widget is None:
            self.display = False
            if self._blink_timer:
                self._blink_timer.pause()
        else:
            self.display = True
            if self._blink_timer:
                self._blink_timer.resume()
            self._update_follow()

    def render(self) -> str:
        return ""


@dataclass
class IssueNode:
    """Represents an issue in the tree with its display properties."""

    issue: Issue
    depth: int


class IssueRow(Static):
    """Single row in the issue tree."""

    DEFAULT_CSS = """
    IssueRow {
        width: 1fr;
        height: 1;
        padding: 0 1;
        &:hover {
            background: $foreground 5%;
        }
        &.-selected {
            background: $primary 15%;
        }
        &.-done {
            color: $text-muted;
        }
    }
    """

    def __init__(self, node: IssueNode, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.node = node

    def render(self) -> Content:
        issue = self.node.issue
        depth = self.node.depth
        indent = "  " * depth

        type_style = "dim"
        title_style = ""
        status_style = ""

        if issue.tw_status == IssueStatus.DONE:
            title_style = "dim"
            status_style = "dim"
        elif issue.tw_status == IssueStatus.IN_PROGRESS:
            status_style = "yellow"
        elif issue.tw_status in (IssueStatus.BLOCKED, IssueStatus.STOPPED):
            status_style = "red"

        ts = status_timestamp(issue)
        ts_part = f" ({ts})" if ts and issue.tw_status != IssueStatus.NEW else ""

        if issue.tw_status == IssueStatus.NEW:
            status_part = ""
        else:
            status_part = f", {issue.tw_status.value}{ts_part}"

        parts = [
            (f"{indent}", ""),
            (f"{issue.tw_type.value}", type_style),
            (": ", "dim"),
            (issue.title, title_style),
            (" (", "dim"),
            (issue.tw_id, "cyan"),
            (status_part, status_style),
            (")", "dim"),
        ]

        return Content.assemble(*[(text, style) for text, style in parts if text])


class IssueTree(VerticalScroll):
    """Scrollable tree view of issues with keyboard navigation."""

    DEFAULT_CSS = """
    IssueTree {
        height: 1fr;
        border-left: tall $secondary;
        scrollbar-gutter: stable;
        padding: 0 1 0 0;
        &:focus-within {
            border-left: tall $primary;
        }
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
    ]

    highlighted: reactive[int | None] = reactive(None)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._issue_nodes: list[IssueNode] = []

    @property
    def nodes(self) -> list[IssueNode]:
        return self._issue_nodes

    @dataclass
    class SelectionChanged(Message):
        """Posted when the selected issue changes."""

        tree: "IssueTree"
        issue: Issue | None

        @property
        def control(self) -> "IssueTree":
            return self.tree

    def compose(self) -> ComposeResult:
        with Horizontal(id="tree-container"):
            yield Cursor(id="tree-cursor")
            yield Vertical(id="tree-rows")

    async def refresh_nodes(self, nodes: list[IssueNode]) -> None:
        """Update the tree with new nodes, properly awaiting DOM changes."""
        self._issue_nodes = nodes
        container = self.query_one("#tree-rows", Vertical)
        await container.remove_children()
        for node in nodes:
            row = IssueRow(node, id=f"row-{node.issue.tw_id}")
            await container.mount(row)
        if self.highlighted is not None and self.highlighted >= len(nodes):
            self.highlighted = len(nodes) - 1 if nodes else None
        self._update_selection_classes()
        self._sync_cursor()

    def watch_highlighted(self, old: int | None, new: int | None) -> None:
        self._update_selection_classes()
        self._sync_cursor()
        issue = self.nodes[new].issue if new is not None and new < len(self.nodes) else None
        self.post_message(self.SelectionChanged(self, issue))

    def _update_selection_classes(self) -> None:
        for i, row in enumerate(self.query(IssueRow)):
            row.set_class(i == self.highlighted, "-selected")
            row.set_class(row.node.issue.tw_status == IssueStatus.DONE, "-done")

    def _sync_cursor(self) -> None:
        cursor = self.query_one("#tree-cursor", Cursor)
        if self.highlighted is not None and self.highlighted < len(self.nodes):
            try:
                tw_id = self.nodes[self.highlighted].issue.tw_id
                row = self.query_one(f"#row-{tw_id}", IssueRow)
                cursor.follow(row)
                self.scroll_to_widget(row, animate=False)
            except Exception:
                cursor.follow(None)
        else:
            cursor.follow(None)

    def action_cursor_down(self) -> None:
        if not self.nodes:
            return
        if self.highlighted is None:
            self.highlighted = 0
        elif self.highlighted < len(self.nodes) - 1:
            self.highlighted += 1

    def action_cursor_up(self) -> None:
        if not self.nodes:
            return
        if self.highlighted is None:
            self.highlighted = len(self.nodes) - 1
        elif self.highlighted > 0:
            self.highlighted -= 1

    @on(Click)
    def on_click(self, event: Click) -> None:
        if event.widget is None:
            return
        for ancestor in event.widget.ancestors_with_self:
            if isinstance(ancestor, IssueRow):
                tw_id = ancestor.node.issue.tw_id
                for i, node in enumerate(self.nodes):
                    if node.issue.tw_id == tw_id:
                        self.highlighted = i
                        break
                break

    def get_selected_issue(self) -> Issue | None:
        if self.highlighted is not None and self.highlighted < len(self.nodes):
            return self.nodes[self.highlighted].issue
        return None

    def select_issue_by_id(self, tw_id: str) -> bool:
        for i, node in enumerate(self.nodes):
            if node.issue.tw_id == tw_id:
                self.highlighted = i
                return True
        return False


class IssueDetail(VerticalScroll):
    """Detail pane showing selected issue context."""

    DEFAULT_CSS = """
    IssueDetail {
        height: 1fr;
        border-left: tall $secondary;
        padding: 1 1 0 1;
        background: $foreground 4%;
        &:focus-within {
            border-left: tall $primary;
        }

        #detail-body {
            height: auto;
        }
        #detail-links {
            height: auto;
            margin-top: 1;
        }
    }
    """

    IssueContext = tuple[
        Issue, list[Issue], list[Issue], list[Issue], list[Issue], list[Issue]
    ]

    issue: var[Issue | None] = var(None)
    context: var[IssueContext | None] = var(None)

    def compose(self) -> ComposeResult:
        yield Markdown(id="detail-body")
        yield Static(id="detail-links")

    def watch_issue(self, issue: Issue | None) -> None:
        body_widget = self.query_one("#detail-body", Markdown)
        if issue is None:
            body_widget.update("")
        else:
            body_md = render_view_body(issue)
            body_widget.update(body_md)

    def watch_context(self, context: IssueContext | None) -> None:
        links_widget = self.query_one("#detail-links", Static)
        if context is None:
            links_widget.update("")
        else:
            _, ancestors, siblings, descendants, referenced, referencing = context
            links_markup = render_view_links(
                ancestors=ancestors,
                siblings=siblings,
                descendants=descendants,
                referenced=referenced,
                referencing=referencing,
            )
            links_widget.update(links_markup)


class InputDialog(Widget):
    """Bottom-docked input dialog for titles and comments."""

    DEFAULT_CSS = """
    InputDialog {
        dock: bottom;
        layer: float;
        overlay: screen;
        height: auto;
        width: 100%;
        background: $background;
        border: tall $secondary;
        padding: 1;
        display: none;

        &.-visible {
            display: block;
        }

        &:focus-within {
            border: tall $primary;
        }

        #input-label {
            margin-bottom: 1;
            color: $text-muted;
        }
        #input-field {
            width: 100%;
        }
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
    ]

    is_visible: var[bool] = var(False)
    prompt: var[str] = var("")
    callback: var[Callable[[str], None] | None] = var(None)

    @dataclass
    class Submitted(Message):
        """Posted when input is submitted."""

        dialog: "InputDialog"
        value: str

        @property
        def control(self) -> "InputDialog":
            return self.dialog

    def compose(self) -> ComposeResult:
        yield Static("", id="input-label")
        yield Input(id="input-field")

    def watch_is_visible(self, is_visible: bool) -> None:
        self.set_class(is_visible, "-visible")
        if is_visible:
            inp = self.query_one("#input-field", Input)
            inp.value = ""
            inp.focus()

    def watch_prompt(self, prompt: str) -> None:
        self.query_one("#input-label", Static).update(prompt)

    def show(self, prompt: str, callback: Callable[[str], None] | None = None) -> None:
        self.prompt = prompt
        self.callback = callback
        self.is_visible = True

    def action_dismiss(self) -> None:
        self.is_visible = False

    @on(Input.Submitted)
    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value.strip()
        if value:
            self.post_message(self.Submitted(self, value))
            if self.callback is not None:
                self.callback(value)
        self.is_visible = False


class PickerDialog(Widget):
    """Bottom-docked picker dialog with filter and option list."""

    DEFAULT_CSS = """
    PickerDialog {
        dock: bottom;
        layer: float;
        overlay: screen;
        height: 20;
        width: 100%;
        background: $background;
        border: tall $secondary;
        padding: 1;
        display: none;

        &.-visible {
            display: block;
        }

        &:focus-within {
            border: tall $primary;
        }

        #picker-title {
            text-align: center;
            color: $text-muted;
            margin-bottom: 1;
        }
        #picker-filter {
            width: 100%;
            margin-bottom: 1;
        }
        #picker-options {
            height: 1fr;
        }
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
    ]

    is_visible: var[bool] = var(False)
    title: var[str] = var("")
    options: var[list[tuple[str, str]]] = var(list)
    callback: var[Callable[[str], None] | None] = var(None)
    _all_options: list[tuple[str, str]] = []

    @dataclass
    class Selected(Message):
        """Posted when an option is selected."""

        dialog: "PickerDialog"
        option_id: str
        option_text: str

        @property
        def control(self) -> "PickerDialog":
            return self.dialog

    def compose(self) -> ComposeResult:
        yield Static("", id="picker-title")
        yield Input(id="picker-filter", placeholder="Filter...")
        yield OptionList(id="picker-options")

    def watch_is_visible(self, is_visible: bool) -> None:
        self.set_class(is_visible, "-visible")
        if is_visible:
            inp = self.query_one("#picker-filter", Input)
            inp.value = ""
            inp.focus()
            self._update_options("")

    def watch_title(self, title: str) -> None:
        self.query_one("#picker-title", Static).update(title)

    def watch_options(self, options: list[tuple[str, str]]) -> None:
        self._all_options = options
        self._update_options("")

    def _update_options(self, filter_text: str) -> None:
        opt_list = self.query_one("#picker-options", OptionList)
        opt_list.clear_options()
        filter_lower = filter_text.lower()
        for opt_id, opt_text in self._all_options:
            if filter_lower in opt_id.lower() or filter_lower in opt_text.lower():
                opt_list.add_option(Option(f"{opt_id}: {opt_text}", id=opt_id))

    def show(
        self,
        title: str,
        options: list[tuple[str, str]],
        callback: Callable[[str], None] | None = None,
    ) -> None:
        self.title = title
        self.options = options
        self.callback = callback
        self.is_visible = True

    def action_dismiss(self) -> None:
        self.is_visible = False

    def action_cursor_up(self) -> None:
        self.query_one("#picker-options", OptionList).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one("#picker-options", OptionList).action_cursor_down()

    @on(Input.Changed, "#picker-filter")
    def on_filter_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._update_options(event.value)

    @on(Input.Submitted, "#picker-filter")
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        opt_list = self.query_one("#picker-options", OptionList)
        if opt_list.highlighted is not None:
            opt_list.action_select()

    @on(OptionList.OptionSelected)
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id:
            opt_text = ""
            for oid, otext in self._all_options:
                if oid == event.option_id:
                    opt_text = otext
                    break
            self.post_message(self.Selected(self, event.option_id, opt_text))
            if self.callback is not None:
                self.callback(event.option_id)
        self.is_visible = False


class TwApp(App[None]):
    """Modern TUI for tw issue tracker."""

    CSS = """
    TwApp {
        layers: base float;
        background: $background;
    }

    #main-container {
        height: 1fr;
        layer: base;
    }

    #tree-pane {
        height: 60%;
    }

    #detail-pane {
        height: 40%;
    }

    Footer {
        background: transparent;
        .footer-key--key {
            color: $text;
            background: transparent;
            padding: 0 1;
        }
        .footer-key--description {
            padding: 0 1 0 0;
            color: $text-muted;
        }
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start", "Start"),
        Binding("d", "done", "Done"),
        Binding("e", "edit", "Edit"),
        Binding("n", "new_child", "New Child"),
        Binding("shift+n", "new_epic", "New Epic"),
        Binding("b", "new_bug", "New Bug"),
        Binding("i", "new_idea", "New Idea"),
        Binding("p", "promote", "Promote"),
        Binding("c", "comment", "Comment"),
        Binding("g", "groom", "Groom"),
        Binding("escape", "close_dialogs", "Close", show=False),
    ]

    busy_count: reactive[int] = reactive(0)
    _service: IssueService
    _observer: BaseObserver | None = None
    _watch_handler: WatchHandler | None = None
    _refresh_event: threading.Event | None = None
    _last_action_time: float = 0.0
    _refresh_timer: Timer | None = None

    def __init__(self) -> None:
        super().__init__()
        backend = TaskWarriorBackend()
        self._service = IssueService(backend, get_project(), get_prefix())

    def compose(self) -> ComposeResult:
        yield Throbber(id="throbber")
        yield Flash(id="flash")
        with Vertical(id="main-container"):
            yield IssueTree(id="tree-pane")
            yield IssueDetail(id="detail-pane")
        yield InputDialog(id="input-dialog")
        yield PickerDialog(id="picker-dialog")
        yield Footer()

    def on_mount(self) -> None:
        self._load_tree()
        self._setup_file_watching()
        self._refresh_timer = self.set_interval(0.5, self._check_refresh)

    def on_unmount(self) -> None:
        self._cleanup_file_watching()
        if self._refresh_timer:
            self._refresh_timer.stop()

    def _setup_file_watching(self) -> None:
        try:
            data_dir = get_taskwarrior_data_dir()
            self._refresh_event = threading.Event()
            self._watch_handler = WatchHandler(self._refresh_event)
            self._observer = Observer()
            self._observer.schedule(self._watch_handler, str(data_dir), recursive=False)
            self._observer.start()
        except Exception as e:
            logger.warning(f"File watching unavailable: {e}")

    def _cleanup_file_watching(self) -> None:
        if self._watch_handler:
            self._watch_handler.cleanup()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1)

    def _check_refresh(self) -> None:
        if self._refresh_event and self._refresh_event.is_set():
            idle_time = monotonic() - self._last_action_time
            if idle_time > 2.0:
                self._refresh_event.clear()
                self._load_tree(preserve_selection=True)

    def _record_action(self) -> None:
        self._last_action_time = monotonic()

    def watch_busy_count(self, count: int) -> None:
        self.query_one("#throbber", Throbber).set_class(count > 0, "-busy")

    def flash(self, message: str, style: str = "success") -> None:
        self.query_one("#flash", Flash).flash(message, style)

    @work(exclusive=True)
    async def _load_tree(self, preserve_selection: bool = False) -> None:
        self.busy_count += 1
        try:
            tree = self.query_one("#tree-pane", IssueTree)
            selected_id = None
            if preserve_selection:
                issue = tree.get_selected_issue()
                selected_id = issue.tw_id if issue else None

            hierarchy, backlog = self._service.get_issue_tree_with_backlog()
            issue_map = {i.tw_id: i for i in hierarchy + backlog}

            def compute_depth(issue: Issue) -> int:
                depth = 0
                current = issue
                while current.tw_parent:
                    depth += 1
                    parent = issue_map.get(current.tw_parent)
                    if not parent:
                        break
                    current = parent
                return depth

            nodes = [IssueNode(issue=i, depth=compute_depth(i)) for i in hierarchy]
            nodes += [IssueNode(issue=i, depth=0) for i in backlog]

            await tree.refresh_nodes(nodes)

            if selected_id:
                tree.select_issue_by_id(selected_id)
            elif tree.highlighted is None and nodes:
                tree.highlighted = 0

        finally:
            self.busy_count -= 1

    @on(IssueTree.SelectionChanged)
    async def on_selection_changed(self, event: IssueTree.SelectionChanged) -> None:
        event.stop()
        detail = self.query_one("#detail-pane", IssueDetail)
        if event.issue is None:
            detail.issue = None
            detail.context = None
        else:
            detail.issue = event.issue
            try:
                context = self._service.get_issue_with_context(event.issue.tw_id)
                detail.context = context
            except KeyError:
                detail.context = None

    def action_close_dialogs(self) -> None:
        self.query_one("#input-dialog", InputDialog).is_visible = False
        self.query_one("#picker-dialog", PickerDialog).is_visible = False

    def action_start(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return
        if is_backlog_type(issue.tw_type):
            self.flash("Cannot start backlog items", "warning")
            return
        try:
            self._service.start_issue(issue.tw_id)
            self.flash(f"Started {issue.tw_id}")
            self._load_tree(preserve_selection=True)
        except ValueError as e:
            self.flash(str(e), "error")

    def action_done(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return
        try:
            self._service.done_issue(issue.tw_id)
            self.flash(f"Completed {issue.tw_id}")
            self._load_tree(preserve_selection=True)
        except ValueError as e:
            self.flash(str(e), "error")

    def action_edit(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return

        editor = os.environ.get("EDITOR", "vi")
        template = generate_edit_template(issue.title, issue.tw_body)

        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(template)
            temp_path = f.name

        try:
            with self.suspend():
                subprocess.run([editor, temp_path], check=True)

            with open(temp_path) as f:
                content = f.read()

            new_title, new_body = parse_edited_content(content)
            self._service.update_issue(issue.tw_id, title=new_title, body=new_body)
            self.flash(f"Updated {issue.tw_id}")
            self._load_tree(preserve_selection=True)
        except (ValueError, subprocess.CalledProcessError) as e:
            self.flash(str(e), "error")
        finally:
            import os as os_module
            os_module.unlink(temp_path)

    def action_new_child(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            self.flash("Select an issue first", "warning")
            return
        if is_backlog_type(issue.tw_type):
            self.flash("Cannot add children to backlog items", "warning")
            return

        child_type_map = {
            IssueType.EPIC: IssueType.STORY,
            IssueType.STORY: IssueType.TASK,
            IssueType.TASK: IssueType.TASK,
        }
        child_type = child_type_map.get(issue.tw_type, IssueType.TASK)

        def create_child(title: str) -> None:
            try:
                new_id = self._service.create_issue(
                    child_type, title, parent_id=issue.tw_id
                )
                self.flash(f"Created {new_id}")
                self._load_tree(preserve_selection=False)
                self.call_after_refresh(
                    lambda: self.query_one("#tree-pane", IssueTree).select_issue_by_id(new_id)
                )
            except ValueError as e:
                self.flash(str(e), "error")

        dialog = self.query_one("#input-dialog", InputDialog)
        dialog.show(f"New {child_type.value} under {issue.tw_id}:", create_child)

    def action_new_epic(self) -> None:
        self._record_action()

        def create_epic(title: str) -> None:
            try:
                new_id = self._service.create_issue(IssueType.EPIC, title)
                self.flash(f"Created {new_id}")
                self._load_tree(preserve_selection=False)
                self.call_after_refresh(
                    lambda: self.query_one("#tree-pane", IssueTree).select_issue_by_id(new_id)
                )
            except ValueError as e:
                self.flash(str(e), "error")

        dialog = self.query_one("#input-dialog", InputDialog)
        dialog.show("New epic title:", create_epic)

    def action_new_bug(self) -> None:
        self._record_action()

        def create_bug(title: str) -> None:
            try:
                new_id = self._service.create_issue(IssueType.BUG, title)
                self.flash(f"Created {new_id}")
                self._load_tree(preserve_selection=False)
                self.call_after_refresh(
                    lambda: self.query_one("#tree-pane", IssueTree).select_issue_by_id(new_id)
                )
            except ValueError as e:
                self.flash(str(e), "error")

        dialog = self.query_one("#input-dialog", InputDialog)
        dialog.show("New bug title:", create_bug)

    def action_new_idea(self) -> None:
        self._record_action()

        def create_idea(title: str) -> None:
            try:
                new_id = self._service.create_issue(IssueType.IDEA, title)
                self.flash(f"Created {new_id}")
                self._load_tree(preserve_selection=False)
                self.call_after_refresh(
                    lambda: self.query_one("#tree-pane", IssueTree).select_issue_by_id(new_id)
                )
            except ValueError as e:
                self.flash(str(e), "error")

        dialog = self.query_one("#input-dialog", InputDialog)
        dialog.show("New idea title:", create_idea)

    def action_promote(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return
        if not is_backlog_type(issue.tw_type):
            self.flash("Can only promote bugs and ideas", "warning")
            return

        hierarchy, _ = self._service.get_issue_tree_with_backlog()
        parents = [
            (i.tw_id, i.title)
            for i in hierarchy
            if i.tw_type in (IssueType.EPIC, IssueType.STORY)
        ]

        if not parents:
            self.flash("No epics or stories to promote to", "warning")
            return

        def do_promote(parent_id: str) -> None:
            try:
                parent = self._service.get_issue(parent_id)
                new_type = IssueType.STORY if parent.tw_type == IssueType.EPIC else IssueType.TASK
                new_id = self._service.create_issue(
                    new_type,
                    issue.title,
                    parent_id=parent_id,
                    body=issue.tw_body,
                )
                self._service.done_issue(issue.tw_id, force=True)
                self.flash(f"Promoted to {new_id}")
                self._load_tree(preserve_selection=False)
                self.call_after_refresh(
                    lambda: self.query_one("#tree-pane", IssueTree).select_issue_by_id(new_id)
                )
            except ValueError as e:
                self.flash(str(e), "error")

        picker = self.query_one("#picker-dialog", PickerDialog)
        picker.show(f"Promote {issue.tw_id} to:", parents, do_promote)

    def action_comment(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return

        def add_comment(comment: str) -> None:
            try:
                self._service.record_annotation(
                    issue.tw_id, AnnotationType.COMMENT, comment
                )
                self.flash(f"Added comment to {issue.tw_id}")
                self._load_tree(preserve_selection=True)
            except ValueError as e:
                self.flash(str(e), "error")

        dialog = self.query_one("#input-dialog", InputDialog)
        dialog.show(f"Comment on {issue.tw_id}:", add_comment)

    def action_groom(self) -> None:
        self._record_action()
        try:
            with self.suspend():
                subprocess.run(["tw", "groom"], check=True)
            self.flash("Grooming complete")
            self._load_tree(preserve_selection=True)
        except subprocess.CalledProcessError as e:
            self.flash(f"Groom failed: {e}", "error")


def run_tui() -> None:
    """Run the TUI application."""
    app = TwApp()
    app.run()


if __name__ == "__main__":
    run_tui()
