"""Modern TUI for tw issue tracker using Textual best practices."""

import asyncio
import logging
import os
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any, cast

from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.color import Color, Gradient
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Vertical, VerticalScroll
from textual.css.styles import RulesMap
from textual.message import Message
from textual.reactive import reactive, var
from textual.strip import Strip
from textual.style import Style
from textual.timer import Timer
from textual.visual import RenderOptions, Visual
from textual.widget import Widget
from textual.widgets import Footer, Input, Markdown, OptionList, Static, Tree
from textual.widgets.option_list import Option
from textual.widgets.tree import TreeNode
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from tw.backend import SqliteBackend
from tw.config import get_db_path, get_prefix
from tw.models import AnnotationType, Issue, IssueStatus, IssueType, is_backlog_type
from tw.render import (
    generate_edit_template,
    parse_edited_content,
    render_view_body,
    render_view_links,
    status_timestamp,
)
from tw.service import IssueService
from tw.watch import WatchHandler

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
        height: auto;
        width: auto;
        max-width: 40;
        padding: 1 2;
        text-align: center;
        visibility: hidden;
        layer: float;
        align: right bottom;
        offset: -2 -2;

        &.-visible {
            visibility: visible;
        }
        &.-success {
            background: $success 15%;
            color: $text;
            border: tall $success;
        }
        &.-warning {
            background: $warning 15%;
            color: $text;
            border: tall $warning;
        }
        &.-error {
            background: $error 15%;
            color: $text;
            border: tall $error;
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


@dataclass
class IssueNode:
    """Represents an issue in the tree with its display properties."""

    issue: Issue
    depth: int


class IssueTree(Tree[Issue]):
    """Tree view of issues with collapsible/expandable nodes."""

    DEFAULT_CSS = """
    IssueTree {
        height: auto;
        max-height: 100%;
        border-left: tall $secondary;
        scrollbar-gutter: stable;
        padding: 0 1 0 0;
        &:focus-within {
            border-left: tall $primary;
        }
    }
    """

    BINDINGS = [
        Binding("space", "toggle_node", "Toggle", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("Issues", **kwargs)
        self.show_root = False
        self.show_guides = True
        self.guide_depth = 2
        self._issue_map: dict[str, TreeNode[Issue]] = {}

    @dataclass
    class SelectionChanged(Message):
        """Posted when the selected issue changes."""

        tree: "IssueTree"
        issue: Issue | None

        @property
        def control(self) -> "IssueTree":
            return self.tree

    def _render_issue_label(self, issue: Issue) -> Text:
        """Render an issue as a styled label."""
        type_style = "dim"
        title_style = ""
        status_style = ""

        if issue.status == IssueStatus.DONE:
            title_style = "dim"
            status_style = "dim"
        elif issue.status == IssueStatus.IN_PROGRESS:
            status_style = "yellow"
        elif issue.status in (IssueStatus.BLOCKED, IssueStatus.STOPPED):
            status_style = "red"

        ts = status_timestamp(issue)
        ts_part = f" ({ts})" if ts and issue.status != IssueStatus.NEW else ""

        if issue.status == IssueStatus.NEW:
            status_part = ""
        else:
            status_part = f", {issue.status.value}{ts_part}"

        label = Text()
        label.append(f"{issue.type.value}", style=type_style)
        label.append(": ", style="dim")
        label.append(issue.title, style=title_style)
        label.append(" (", style="dim")
        label.append(issue.id, style="cyan")
        if status_part:
            label.append(status_part, style=status_style)
        label.append(")", style="dim")
        return label

    async def refresh_tree(
        self,
        hierarchy: list[Issue],
        backlog: list[Issue],
        selected_id: str | None = None,
        hide_done: bool = False,
    ) -> None:
        """Rebuild the tree with new issues."""
        self.clear()
        self._issue_map.clear()

        if hide_done:
            hierarchy = [i for i in hierarchy if i.status != IssueStatus.DONE]
            backlog = [i for i in backlog if i.status != IssueStatus.DONE]

        issue_by_id: dict[str, Issue] = {i.id: i for i in hierarchy + backlog}
        children_map: dict[str | None, list[Issue]] = {}
        for issue in hierarchy:
            parent_id = issue.parent
            if hide_done and parent_id and parent_id not in issue_by_id:
                parent_id = None
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(issue)

        def add_children(parent_node: TreeNode[Issue], parent_id: str | None) -> None:
            for issue in children_map.get(parent_id, []):
                has_children = issue.id in children_map
                label = self._render_issue_label(issue)
                if has_children:
                    child_node = parent_node.add(label, data=issue, expand=True, allow_expand=False)
                else:
                    child_node = parent_node.add_leaf(label, data=issue)
                self._issue_map[issue.id] = child_node
                if has_children:
                    add_children(child_node, issue.id)

        add_children(self.root, None)

        if backlog:
            backlog_label = Text("backlog", style="dim")
            backlog_node = self.root.add(backlog_label, expand=True, allow_expand=False)
            for issue in backlog:
                label = self._render_issue_label(issue)
                child_node = backlog_node.add_leaf(label, data=issue)
                self._issue_map[issue.id] = child_node

        await asyncio.sleep(0)

        if selected_id and selected_id in self._issue_map:
            self.select_node(self._issue_map[selected_id])
        elif self.root.children:
            first_child = self.root.children[0]
            if first_child.data is not None:
                self.select_node(first_child)
            elif first_child.children:
                self.select_node(first_child.children[0])

    def on_tree_node_selected(self, event: Tree.NodeSelected[Issue]) -> None:
        """Handle node selection."""
        event.stop()
        issue = event.node.data
        self.post_message(self.SelectionChanged(self, issue))

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[Issue]) -> None:
        """Handle node highlight (cursor movement)."""
        event.stop()
        issue = event.node.data
        self.post_message(self.SelectionChanged(self, issue))

    def get_selected_issue(self) -> Issue | None:
        """Get the currently selected issue."""
        if self.cursor_node and self.cursor_node.data:
            return self.cursor_node.data
        return None

    def select_issue_by_id(self, tw_id: str) -> bool:
        """Select an issue by its ID."""
        if tw_id in self._issue_map:
            self.select_node(self._issue_map[tw_id])
            return True
        return False


class IssueDetail(VerticalScroll, can_focus=False):
    """Detail pane showing selected issue context."""

    DEFAULT_CSS = """
    IssueDetail {
        height: auto;
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


class ModelPickerDialog(Widget, can_focus=True):
    """Bottom-docked model picker dialog with keyboard shortcuts."""

    DEFAULT_CSS = """
    ModelPickerDialog {
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

        &:focus {
            border: tall $primary;
        }

        #model-title {
            text-align: center;
            color: $text-muted;
            margin-bottom: 1;
        }
        #model-options {
            text-align: center;
        }
        #model-commands {
            text-align: center;
            color: $text-muted;
            margin-top: 1;
        }
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("o", "select_opus", "Opus", show=False),
        Binding("s", "select_sonnet", "Sonnet", show=False),
        Binding("h", "select_haiku", "Haiku", show=False),
    ]

    is_visible: var[bool] = var(False)
    issue_id: var[str] = var("")
    callback: var[Callable[[str], None] | None] = var(None)

    @dataclass
    class Selected(Message):
        """Posted when a model is selected."""

        dialog: "ModelPickerDialog"
        model: str

        @property
        def control(self) -> "ModelPickerDialog":
            return self.dialog

    def compose(self) -> ComposeResult:
        yield Static("", id="model-title")
        yield Static("Select model:", id="model-options")
        yield Static("[o] Opus  [s] Sonnet  [h] Haiku  [esc] Cancel", id="model-commands")

    def watch_is_visible(self, is_visible: bool) -> None:
        self.set_class(is_visible, "-visible")
        if is_visible:
            self.focus()

    def watch_issue_id(self, issue_id: str) -> None:
        self.query_one("#model-title", Static).update(f"Send {issue_id} to Claude - select model:")

    def show(self, issue_id: str, callback: Callable[[str], None] | None = None) -> None:
        self.issue_id = issue_id
        self.callback = callback
        self.is_visible = True

    def action_dismiss(self) -> None:
        self.is_visible = False

    def _select_model(self, model: str) -> None:
        self.post_message(self.Selected(self, model))
        if self.callback is not None:
            self.callback(model)
        self.is_visible = False

    def action_select_opus(self) -> None:
        self._select_model("opus")

    def action_select_sonnet(self) -> None:
        self._select_model("sonnet")

    def action_select_haiku(self) -> None:
        self._select_model("haiku")


class HelpDialog(Widget):
    """Floating help dialog showing available shortcuts."""

    DEFAULT_CSS = """
    HelpDialog {
        layer: float;
        overlay: screen;
        width: 80;
        height: auto;
        max-height: 90%;
        background: $background;
        border: tall $primary;
        padding: 1;
        display: none;
        align: center middle;

        &.-visible {
            display: block;
        }

        #help-title {
            text-align: center;
            color: $text-accent;
            margin-bottom: 1;
        }
        #help-content {
            height: auto;
            max-height: 100%;
        }
        #help-footer {
            text-align: center;
            color: $text-muted;
            margin-top: 1;
        }
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close", show=False),
        Binding("question_mark", "dismiss", "Close", show=False),
    ]

    is_visible: var[bool] = var(False)

    def compose(self) -> ComposeResult:
        yield Static("tw TUI - Keyboard Shortcuts", id="help-title")
        yield VerticalScroll(Markdown(""), id="help-content")
        yield Static("Press ? or Esc to close", id="help-footer")

    def watch_is_visible(self, is_visible: bool) -> None:
        self.set_class(is_visible, "-visible")
        if is_visible:
            self.focus()

    def show(self) -> None:
        help_md = """
## Navigation
- **j** / **Down** - Move cursor down
- **k** / **Up** - Move cursor up
- **Left** - Navigate to parent issue

## Tree Expand/Collapse
- **Space** - Toggle expand/collapse of selected node
- **Enter** - Select current node

## Issue Management
- **s** - Start working on selected issue
- **d** - Mark selected issue as done
- **e** - Edit selected issue in editor
- **c** - Add comment to selected issue

## Creating Issues
- **n** - Create new child issue under selected
- **N** - Create new top-level epic
- **b** - Create new bug (backlog)
- **i** - Create new idea (backlog)

## Issue Organization
- **p** - Promote issue to different type/parent
- **R** - Refresh tree display

## View Options
- **h** - Toggle hiding of done issues

## Other Commands
- **C** - Send issue to Claude for assistance
- **g** - Open backlog grooming interface
- **q** - Quit application
- **Ctrl+\\\\** - Open command palette

## Tips
- Press **?** anytime to show this help
- Most commands work on the currently selected issue
- Use the command palette (Ctrl+\\\\) to search for commands
"""
        content = self.query_one("#help-content", VerticalScroll)
        content.query_one(Markdown).update(help_md)
        self.is_visible = True

    def action_dismiss(self) -> None:
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
    _filter_modified: bool = False

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
            self._filter_modified = False
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

        if not self._filter_modified and opt_list.option_count > 0:
            opt_list.highlighted = 0

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
        self._filter_modified = True
        self._update_options(event.value)

    @on(Input.Submitted, "#picker-filter")
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        opt_list = self.query_one("#picker-options", OptionList)
        if opt_list.highlighted is not None:
            opt_list.action_select()
        elif opt_list.option_count > 0:
            opt_list.highlighted = 0
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


class TwCommandProvider(Provider):
    """Command provider for tw TUI commands."""

    @property
    def _app(self) -> "TwApp":
        """Get the app with proper type."""
        return cast("TwApp", self.app)

    async def discover(self) -> Hits:
        """Show all available commands when command palette opens."""
        yield DiscoveryHit(
            "Start issue",
            self._app.action_start,
            help="Start working on the selected issue (s)",
        )
        yield DiscoveryHit(
            "Done with issue",
            self._app.action_done,
            help="Mark the selected issue as done (d)",
        )
        yield DiscoveryHit(
            "Edit issue",
            self._app.action_edit,
            help="Edit the selected issue in your editor (e)",
        )
        yield DiscoveryHit(
            "New child issue",
            self._app.action_new_child,
            help="Create a child issue under the selected issue (n)",
        )
        yield DiscoveryHit(
            "New epic",
            self._app.action_new_epic,
            help="Create a new top-level epic (N)",
        )
        yield DiscoveryHit(
            "New bug",
            self._app.action_new_bug,
            help="Create a new bug in the backlog (b)",
        )
        yield DiscoveryHit(
            "New idea",
            self._app.action_new_idea,
            help="Create a new idea in the backlog (i)",
        )
        yield DiscoveryHit(
            "Promote issue",
            self._app.action_promote,
            help="Promote the selected issue to a higher type (p)",
        )
        yield DiscoveryHit(
            "Refresh tree",
            self._app.action_refresh,
            help="Refresh the issue tree display (R)",
        )
        yield DiscoveryHit(
            "Comment on issue",
            self._app.action_comment,
            help="Add a comment to the selected issue (c)",
        )
        yield DiscoveryHit(
            "Send to Claude",
            self._app.action_send_to_claude,
            help="Send the selected issue to Claude for assistance (C)",
        )
        yield DiscoveryHit(
            "Groom backlog",
            self._app.action_groom,
            help="Open backlog grooming interface (g)",
        )
        yield DiscoveryHit(
            "Quit application",
            self._app.action_quit,
            help="Exit the tw TUI (q)",
        )

    async def search(self, query: str) -> Hits:
        """Search for commands matching the query."""
        matcher = self.matcher(query)

        commands = [
            ("Start issue", self._app.action_start, "Start working on selected issue (s)"),
            ("Done with issue", self._app.action_done, "Mark selected issue as done (d)"),
            ("Edit issue", self._app.action_edit, "Edit selected issue in editor (e)"),
            ("New child issue", self._app.action_new_child, "Create child issue (n)"),
            ("New epic", self._app.action_new_epic, "Create new top-level epic (N)"),
            ("New bug", self._app.action_new_bug, "Create new bug in backlog (b)"),
            ("New idea", self._app.action_new_idea, "Create new idea in backlog (i)"),
            ("Promote issue", self._app.action_promote, "Promote to higher type (p)"),
            ("Refresh tree", self._app.action_refresh, "Refresh tree display (R)"),
            ("Comment on issue", self._app.action_comment, "Add comment to issue (c)"),
            ("Send to Claude", self._app.action_send_to_claude, "Send to Claude (C)"),
            ("Groom backlog", self._app.action_groom, "Open backlog grooming (g)"),
            ("Quit application", self._app.action_quit, "Exit tw TUI (q)"),
        ]

        for name, callback, help_text in commands:
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    callback,
                    help=help_text,
                )


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
        height: 1fr;
        border-bottom: solid $secondary;
    }

    #detail-pane {
        height: auto;
        min-height: 3;
        max-height: 50%;
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
        Binding("question_mark", "help", "Help"),
        Binding("s", "start", "Start", show=False),
        Binding("d", "done", "Done", show=False),
        Binding("e", "edit", "Edit", show=False),
        Binding("n", "new_child", "New Child", show=False),
        Binding("N", "new_epic", "New Epic", show=False),
        Binding("b", "new_bug", "New Bug", show=False),
        Binding("i", "new_idea", "New Idea", show=False),
        Binding("p", "promote", "Promote", show=False),
        Binding("R", "refresh", "Refresh", show=False),
        Binding("c", "comment", "Comment", show=False),
        Binding("C", "send_to_claude", "Claude", show=False),
        Binding("g", "groom", "Groom", show=False),
        Binding("h", "toggle_hide_done", "Hide Done", show=False),
        Binding("q", "quit", "Quit", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("up", "cursor_up", "Up", show=False),
        Binding("left", "parent", "Parent", show=False),
        Binding("escape", "close_dialogs", "Close", show=False),
    ]

    COMMANDS = App.COMMANDS | {TwCommandProvider}

    busy_count: reactive[int] = reactive(0)
    hide_done: reactive[bool] = reactive(False)
    _service: IssueService
    _observer: BaseObserver | None = None
    _watch_handler: WatchHandler | None = None
    _refresh_event: threading.Event | None = None
    _last_action_time: float = 0.0
    _refresh_timer: Timer | None = None
    _selected_issue_id: str | None = None

    def __init__(self) -> None:
        super().__init__()
        backend = SqliteBackend(get_db_path())
        self._service = IssueService(backend, get_prefix())

    def compose(self) -> ComposeResult:
        yield Throbber(id="throbber")
        yield Flash(id="flash")
        with Vertical(id="main-container"):
            yield IssueTree(id="tree-pane")
            yield IssueDetail(id="detail-pane")
        yield InputDialog(id="input-dialog")
        yield PickerDialog(id="picker-dialog")
        yield ModelPickerDialog(id="model-picker-dialog")
        yield HelpDialog(id="help-dialog")
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
            db_path = get_db_path()
            self._refresh_event = threading.Event()
            self._watch_handler = WatchHandler(self._refresh_event)
            self._observer = Observer()
            self._observer.schedule(self._watch_handler, str(db_path.parent), recursive=False)
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
                self._load_tree()

    def _record_action(self) -> None:
        self._last_action_time = monotonic()

    def watch_busy_count(self, count: int) -> None:
        self.query_one("#throbber", Throbber).set_class(count > 0, "-busy")

    def flash(self, message: str, style: str = "success") -> None:
        self.query_one("#flash", Flash).flash(message, style)

    @work(exclusive=True)
    async def _load_tree(self, select_id: str | None = None) -> None:
        self.busy_count += 1
        try:
            tree = self.query_one("#tree-pane", IssueTree)
            if select_id is None:
                select_id = self._selected_issue_id

            hierarchy, backlog = self._service.get_issue_tree_with_backlog()
            await tree.refresh_tree(hierarchy, backlog, select_id, self.hide_done)

        finally:
            self.busy_count -= 1

    @on(IssueTree.SelectionChanged)
    async def on_selection_changed(self, event: IssueTree.SelectionChanged) -> None:
        event.stop()
        if event.issue is not None:
            self._selected_issue_id = event.issue.id
        try:
            detail = self.query_one("#detail-pane", IssueDetail)
        except Exception:
            return
        if event.issue is None:
            detail.issue = None
            detail.context = None
        else:
            detail.issue = event.issue
            try:
                context = self._service.get_issue_with_context(event.issue.id)
                detail.context = context
            except KeyError:
                detail.context = None

    def action_close_dialogs(self) -> None:
        self.query_one("#input-dialog", InputDialog).is_visible = False
        self.query_one("#picker-dialog", PickerDialog).is_visible = False
        self.query_one("#model-picker-dialog", ModelPickerDialog).is_visible = False
        self.query_one("#help-dialog", HelpDialog).is_visible = False

    def action_help(self) -> None:
        help_dialog = self.query_one("#help-dialog", HelpDialog)
        help_dialog.show()

    def action_start(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return
        if is_backlog_type(issue.type):
            self.flash("Cannot start backlog items", "warning")
            return
        try:
            self._service.start_issue(issue.id)
            self.flash(f"Started {issue.id}")
            self._load_tree()
        except ValueError as e:
            self.flash(str(e), "error")

    def action_done(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return
        try:
            self._service.done_issue(issue.id)
            self.flash(f"Completed {issue.id}")
            self._load_tree()
        except ValueError as e:
            self.flash(str(e), "error")

    def action_edit(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return

        editor = os.environ.get("EDITOR", "vi")
        template = generate_edit_template(issue.title, issue.body)

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
            self._service.update_issue(issue.id, title=new_title, body=new_body)
            self.flash(f"Updated {issue.id}")
            self._load_tree()
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
        if is_backlog_type(issue.type):
            self.flash("Cannot add children to backlog items", "warning")
            return

        child_type_map = {
            IssueType.EPIC: IssueType.STORY,
            IssueType.STORY: IssueType.TASK,
            IssueType.TASK: IssueType.TASK,
        }
        child_type = child_type_map.get(issue.type, IssueType.TASK)

        def create_child(title: str) -> None:
            try:
                new_id = self._service.create_issue(
                    child_type, title, parent_id=issue.id
                )
                self.flash(f"Created {new_id}")
                self._load_tree(new_id)
            except ValueError as e:
                self.flash(str(e), "error")

        dialog = self.query_one("#input-dialog", InputDialog)
        dialog.show(f"New {child_type.value} under {issue.id}:", create_child)

    def action_new_epic(self) -> None:
        self._record_action()

        def create_epic(title: str) -> None:
            try:
                new_id = self._service.create_issue(IssueType.EPIC, title)
                self.flash(f"Created {new_id}")
                self._load_tree(new_id)
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
                self._load_tree(new_id)
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
                self._load_tree(new_id)
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

        hierarchy, _ = self._service.get_issue_tree_with_backlog()

        options = [
            ("(epic)", "Promote to orphan epic"),
            ("(story)", "Promote to orphan story"),
            ("(task)", "Promote to orphan task"),
        ]

        parents = [
            (i.id, i.title)
            for i in hierarchy
            if i.type in (IssueType.EPIC, IssueType.STORY, IssueType.TASK)
            and i.id != issue.id
        ]
        options.extend(parents)

        def do_promote(option_id: str) -> None:
            try:
                if option_id == "(epic)":
                    new_id = self._service.promote_issue(issue.id, target_type=IssueType.EPIC)
                elif option_id == "(story)":
                    new_id = self._service.promote_issue(issue.id, target_type=IssueType.STORY)
                elif option_id == "(task)":
                    new_id = self._service.promote_issue(issue.id, target_type=IssueType.TASK)
                else:
                    new_id = self._service.promote_issue(issue.id, new_parent_id=option_id)

                self.flash(f"Promoted to {new_id}")
                self._load_tree(new_id)
            except ValueError as e:
                self.flash(str(e), "error")

        picker = self.query_one("#picker-dialog", PickerDialog)
        picker.show(f"Promote {issue.id} to:", options, do_promote)

    def action_comment(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            return

        def add_comment(comment: str) -> None:
            try:
                self._service.record_annotation(
                    issue.id, AnnotationType.COMMENT, comment
                )
                self.flash(f"Added comment to {issue.id}")
                self._load_tree()
            except ValueError as e:
                self.flash(str(e), "error")

        dialog = self.query_one("#input-dialog", InputDialog)
        dialog.show(f"Comment on {issue.id}:", add_comment)

    def action_groom(self) -> None:
        self._record_action()
        try:
            with self.suspend():
                subprocess.run(["tw", "groom"], check=True)
            self.flash("Grooming complete")
            self._load_tree()
        except subprocess.CalledProcessError as e:
            self.flash(f"Groom failed: {e}", "error")

    def action_send_to_claude(self) -> None:
        self._record_action()
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None:
            self.flash("Select an issue first", "warning")
            return

        parent, children = self._service.get_issue_with_children(issue.id)

        def run_claude(model: str) -> None:
            try:
                brief_result = subprocess.run(
                    ["tw", "brief", issue.id],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                prompt = brief_result.stdout
                if len(children) > 1:
                    prompt += (
                        "\n\nConsider chunking the work and dispatching to "
                        "parallel or sequential subagents"
                    )
            except subprocess.CalledProcessError as e:
                self.flash(f"Failed to get brief for {issue.id}: {e}", "error")
                return
            except FileNotFoundError:
                self.flash("tw command not found", "error")
                return

            try:
                with self.suspend():
                    subprocess.run(
                        ["claude", "--dangerously-skip-permissions", "--model", model, prompt],
                        check=False,
                    )
                self._load_tree()
                self.flash(f"Claude session for {issue.id} complete")
            except FileNotFoundError:
                self.flash("claude command not found", "error")

        dialog = self.query_one("#model-picker-dialog", ModelPickerDialog)
        dialog.show(issue.id, run_claude)

    def action_refresh(self) -> None:
        self._record_action()
        self._load_tree()
        self.flash("Refreshed")

    def action_toggle_hide_done(self) -> None:
        self._record_action()
        self.hide_done = not self.hide_done
        self._load_tree()
        status = "on" if self.hide_done else "off"
        self.flash(f"Hide done: {status}")

    def action_cursor_down(self) -> None:
        tree = self.query_one("#tree-pane", IssueTree)
        tree.action_cursor_down()

    def action_cursor_up(self) -> None:
        tree = self.query_one("#tree-pane", IssueTree)
        tree.action_cursor_up()

    def action_parent(self) -> None:
        tree = self.query_one("#tree-pane", IssueTree)
        issue = tree.get_selected_issue()
        if issue is None or issue.parent is None:
            return
        tree.select_issue_by_id(issue.parent)


def run_tui() -> None:
    """Run the TUI application."""
    app = TwApp()
    app.run()


if __name__ == "__main__":
    run_tui()
