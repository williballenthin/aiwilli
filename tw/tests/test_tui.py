"""Tests for TUI application using Textual's testing framework."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from tw.models import Issue, IssueStatus, IssueType
from tw.service import IssueService
from tw.tui import (
    Flash,
    InputDialog,
    IssueDetail,
    IssueNode,
    IssueTree,
    PickerDialog,
    TwApp,
)


@pytest.fixture
def mock_service() -> MagicMock:
    """Create a mock IssueService with test data."""
    service = MagicMock(spec=IssueService)
    now = datetime.now(UTC)

    test_issues = [
        Issue(
            id="TW-1",
            type=IssueType.EPIC,
            title="Test Epic",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        ),
        Issue(
            id="TW-1-1",
            type=IssueType.STORY,
            title="Test Story",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            parent="TW-1",
        ),
        Issue(
            id="TW-1-1a",
            type=IssueType.TASK,
            title="Test Task",
            status=IssueStatus.IN_PROGRESS,
            created_at=now,
            updated_at=now,
            parent="TW-1-1",
        ),
    ]

    backlog_issues = [
        Issue(
            id="TW-10",
            type=IssueType.BUG,
            title="Test Bug",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        ),
    ]

    service.get_issue_tree_with_backlog.return_value = (test_issues, backlog_issues)
    service.get_issue.side_effect = lambda tw_id: next(
        (i for i in test_issues + backlog_issues if i.id == tw_id), None
    )
    service.get_issue_with_context.return_value = (
        test_issues[0],
        [],
        [],
        [],
        [],
        [],
    )
    service.create_issue.return_value = "TW-2"
    service.start_issue.return_value = None
    service.done_issue.return_value = None
    service.update_issue.return_value = None

    return service


class TestIssueNode:
    """Tests for IssueNode dataclass."""

    def test_issue_node_creation(self) -> None:
        """IssueNode should store issue and depth."""
        now = datetime.now(UTC)
        issue = Issue(
            id="TW-1",
            type=IssueType.EPIC,
            title="Test",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        node = IssueNode(issue=issue, depth=0)

        assert node.issue == issue
        assert node.depth == 0

    def test_issue_node_with_depth(self) -> None:
        """IssueNode should store depth correctly."""
        now = datetime.now(UTC)
        issue = Issue(
            id="TW-1-1a",
            type=IssueType.TASK,
            title="Test",
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
        )
        node = IssueNode(issue=issue, depth=2)

        assert node.depth == 2


class TestTwApp:
    """Tests for TwApp application."""

    @pytest.mark.asyncio
    async def test_app_initialization(self, mock_service: MagicMock) -> None:
        """App should initialize and compose widgets."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test():
                        assert app.query_one("#tree-pane", IssueTree)
                        assert app.query_one("#detail-pane", IssueDetail)
                        assert app.query_one("#input-dialog", InputDialog)
                        assert app.query_one("#picker-dialog", PickerDialog)

    @pytest.mark.asyncio
    async def test_app_loads_issues(self, mock_service: MagicMock) -> None:
        """App should load issues into tree on mount."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        assert len(tree._issue_map) == 4

    @pytest.mark.asyncio
    async def test_keyboard_navigation_down(self, mock_service: MagicMock) -> None:
        """Pressing j should move selection down."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        initial = tree.cursor_line
                        await pilot.press("j")
                        assert tree.cursor_line == initial + 1

    @pytest.mark.asyncio
    async def test_keyboard_navigation_up(self, mock_service: MagicMock) -> None:
        """Pressing k should move selection up."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        await pilot.press("j")
                        await pilot.press("j")
                        current = tree.cursor_line
                        await pilot.press("k")
                        assert tree.cursor_line == current - 1

    @pytest.mark.asyncio
    async def test_action_start_exists(self, mock_service: MagicMock) -> None:
        """App should have action_start method."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    assert hasattr(app, "action_start")
                    assert callable(app.action_start)

    @pytest.mark.asyncio
    async def test_action_done_exists(self, mock_service: MagicMock) -> None:
        """App should have action_done method."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    assert hasattr(app, "action_done")
                    assert callable(app.action_done)

    @pytest.mark.asyncio
    async def test_flash_message(self, mock_service: MagicMock) -> None:
        """Flash widget should show messages."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test():
                        app.flash("Test message", "success")
                        flash = app.query_one("#flash", Flash)
                        assert flash.has_class("-visible")

    @pytest.mark.asyncio
    async def test_input_dialog_show(self, mock_service: MagicMock) -> None:
        """Input dialog should show when requested."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test():
                        dialog = app.query_one("#input-dialog", InputDialog)
                        dialog.show("Test prompt:")
                        assert dialog.is_visible
                        assert dialog.has_class("-visible")

    @pytest.mark.asyncio
    async def test_picker_dialog_show(self, mock_service: MagicMock) -> None:
        """Picker dialog should show with options."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test():
                        picker = app.query_one("#picker-dialog", PickerDialog)
                        picker.show("Select:", [("opt1", "Option 1"), ("opt2", "Option 2")])
                        assert picker.is_visible
                        assert picker.has_class("-visible")

    @pytest.mark.asyncio
    async def test_escape_closes_dialogs(self, mock_service: MagicMock) -> None:
        """Escape key should close open dialogs."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        dialog = app.query_one("#input-dialog", InputDialog)
                        dialog.show("Test:")
                        assert dialog.is_visible
                        await pilot.press("escape")
                        assert not dialog.is_visible


class TestIssueTree:
    """Tests for IssueTree widget."""

    @pytest.mark.asyncio
    async def test_tree_navigation(self, mock_service: MagicMock) -> None:
        """Tree should support keyboard navigation."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        initial = tree.cursor_line
                        tree.action_cursor_down()
                        assert tree.cursor_line == initial + 1
                        tree.action_cursor_up()
                        assert tree.cursor_line == initial

    @pytest.mark.asyncio
    async def test_tree_get_selected_issue(self, mock_service: MagicMock) -> None:
        """Tree should return selected issue."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        issue = tree.get_selected_issue()
                        assert issue is not None
                        assert issue.id == "TW-1"

    @pytest.mark.asyncio
    async def test_tree_select_by_id(self, mock_service: MagicMock) -> None:
        """Tree should select issue by ID."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        assert "TW-1-1" in tree._issue_map
                        result = tree.select_issue_by_id("TW-1-1")
                        assert result is True

    @pytest.mark.asyncio
    async def test_tree_collapse_expand(self, mock_service: MagicMock) -> None:
        """Tree should support collapse/expand."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        node = tree._issue_map.get("TW-1")
                        assert node is not None
                        node.expand()
                        await pilot.pause()
                        assert node.is_expanded
                        node.collapse()
                        await pilot.pause()
                        assert not node.is_expanded
                        node.toggle()
                        await pilot.pause()
                        assert node.is_expanded

    @pytest.mark.asyncio
    async def test_tree_all_nodes_expanded_on_load(self, mock_service: MagicMock) -> None:
        """All nodes with children should be expanded after tree load."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        await pilot.pause()
                        await pilot.pause()
                        await pilot.pause()
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        for node in tree._issue_map.values():
                            if node.allow_expand:
                                assert node.is_expanded, f"Node {node.label} should be expanded"


class TestIssueDetail:
    """Tests for IssueDetail widget."""

    @pytest.mark.asyncio
    async def test_detail_updates_on_selection(self, mock_service: MagicMock) -> None:
        """Detail pane should update when selection changes."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        detail = app.query_one("#detail-pane", IssueDetail)
                        assert detail.issue is not None


class TestSelectionPreservation:
    """Tests for selection preservation across tree refreshes."""

    @pytest.mark.asyncio
    async def test_selection_preserved_after_refresh(self, mock_service: MagicMock) -> None:
        """Selection should be preserved when tree is refreshed."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwApp()
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.pause()
                    tree = app.query_one("#tree-pane", IssueTree)
                    tree.select_issue_by_id("TW-1-1")
                    await pilot.pause()
                    await pilot.pause()
                    assert tree.get_selected_issue() is not None
                    assert tree.get_selected_issue().id == "TW-1-1"
                    assert app._selected_issue_id == "TW-1-1"
                    app._load_tree()
                    await pilot.pause()
                    await pilot.pause()
                    await pilot.pause()
                    await pilot.pause()
                    assert tree.get_selected_issue() is not None
                    assert tree.get_selected_issue().id == "TW-1-1"

    @pytest.mark.asyncio
    async def test_selection_id_tracked_on_change(self, mock_service: MagicMock) -> None:
        """App should track selected issue ID when selection changes."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwApp()
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.pause()
                    tree = app.query_one("#tree-pane", IssueTree)
                    tree.select_issue_by_id("TW-1-1a")
                    await pilot.pause()
                    assert app._selected_issue_id == "TW-1-1a"

    @pytest.mark.asyncio
    async def test_selection_preserved_after_action(self, mock_service: MagicMock) -> None:
        """Selection should be preserved after actions that refresh the tree."""
        with patch("tw.tui.SqliteBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwApp()
                async with app.run_test() as pilot:
                    await pilot.pause()
                    await pilot.pause()
                    tree = app.query_one("#tree-pane", IssueTree)
                    tree.select_issue_by_id("TW-1-1")
                    await pilot.pause()
                    assert app._selected_issue_id == "TW-1-1"
                    app.action_refresh()
                    await pilot.pause()
                    await pilot.pause()
                    assert tree.get_selected_issue() is not None
                    assert tree.get_selected_issue().id == "TW-1-1"
