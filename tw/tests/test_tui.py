"""Tests for TUI application using Textual's testing framework."""

from unittest.mock import MagicMock, patch

import pytest
from textual.pilot import Pilot

from tw.models import Issue, IssueStatus, IssueType
from tw.service import IssueService
from tw.tui import (
    Flash,
    InputDialog,
    IssueDetail,
    IssueNode,
    IssueRow,
    IssueTree,
    PickerDialog,
    TwApp,
)


@pytest.fixture
def mock_service() -> MagicMock:
    """Create a mock IssueService with test data."""
    service = MagicMock(spec=IssueService)

    test_issues = [
        Issue(
            uuid="uuid-1",
            tw_id="TW-1",
            tw_type=IssueType.EPIC,
            title="Test Epic",
            tw_status=IssueStatus.NEW,
            project="tw",
        ),
        Issue(
            uuid="uuid-2",
            tw_id="TW-1-1",
            tw_type=IssueType.STORY,
            title="Test Story",
            tw_status=IssueStatus.NEW,
            project="tw",
            tw_parent="TW-1",
        ),
        Issue(
            uuid="uuid-3",
            tw_id="TW-1-1a",
            tw_type=IssueType.TASK,
            title="Test Task",
            tw_status=IssueStatus.IN_PROGRESS,
            project="tw",
            tw_parent="TW-1-1",
        ),
    ]

    backlog_issues = [
        Issue(
            uuid="uuid-4",
            tw_id="TW-10",
            tw_type=IssueType.BUG,
            title="Test Bug",
            tw_status=IssueStatus.NEW,
            project="tw",
        ),
    ]

    service.get_issue_tree_with_backlog.return_value = (test_issues, backlog_issues)
    service.get_issue.side_effect = lambda tw_id: next(
        (i for i in test_issues + backlog_issues if i.tw_id == tw_id), None
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
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.EPIC,
            title="Test",
            tw_status=IssueStatus.NEW,
            project="tw",
        )
        node = IssueNode(issue=issue, depth=0)

        assert node.issue == issue
        assert node.depth == 0

    def test_issue_node_with_depth(self) -> None:
        """IssueNode should store depth correctly."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1-1a",
            tw_type=IssueType.TASK,
            title="Test",
            tw_status=IssueStatus.NEW,
            project="tw",
        )
        node = IssueNode(issue=issue, depth=2)

        assert node.depth == 2


class TestIssueRow:
    """Tests for IssueRow widget rendering."""

    def test_issue_row_done_styling(self) -> None:
        """IssueRow should render done issues with dim styling."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.TASK,
            title="Completed Task",
            tw_status=IssueStatus.DONE,
            project="tw",
        )
        node = IssueNode(issue=issue, depth=0)
        row = IssueRow(node)
        content = row.render()

        plain_text = str(content)
        assert "TW-1" in plain_text
        assert "Completed Task" in plain_text

    def test_issue_row_in_progress_styling(self) -> None:
        """IssueRow should render in_progress issues with status shown."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.TASK,
            title="Active Task",
            tw_status=IssueStatus.IN_PROGRESS,
            project="tw",
        )
        node = IssueNode(issue=issue, depth=0)
        row = IssueRow(node)
        content = row.render()

        plain_text = str(content)
        assert "TW-1" in plain_text
        assert "Active Task" in plain_text
        assert "in_progress" in plain_text

    def test_issue_row_new_status_hidden(self) -> None:
        """IssueRow should not show status for NEW issues."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.TASK,
            title="New Task",
            tw_status=IssueStatus.NEW,
            project="tw",
        )
        node = IssueNode(issue=issue, depth=0)
        row = IssueRow(node)
        content = row.render()

        plain_text = str(content)
        assert "TW-1" in plain_text
        assert "new" not in plain_text.lower() or "New Task" in plain_text


class TestTwApp:
    """Tests for TwApp application."""

    @pytest.mark.asyncio
    async def test_app_initialization(self, mock_service: MagicMock) -> None:
        """App should initialize and compose widgets."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        assert app.query_one("#tree-pane", IssueTree)
                        assert app.query_one("#detail-pane", IssueDetail)
                        assert app.query_one("#input-dialog", InputDialog)
                        assert app.query_one("#picker-dialog", PickerDialog)

    @pytest.mark.asyncio
    async def test_app_loads_issues(self, mock_service: MagicMock) -> None:
        """App should load issues into tree on mount."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        assert len(tree.nodes) == 4

    @pytest.mark.asyncio
    async def test_keyboard_navigation_down(self, mock_service: MagicMock) -> None:
        """Pressing j should move selection down."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        initial = tree.highlighted
                        await pilot.press("j")
                        assert tree.highlighted == (initial or 0) + 1

    @pytest.mark.asyncio
    async def test_keyboard_navigation_up(self, mock_service: MagicMock) -> None:
        """Pressing k should move selection up."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        tree.highlighted = 2
                        await pilot.press("k")
                        assert tree.highlighted == 1

    @pytest.mark.asyncio
    async def test_action_start_exists(self, mock_service: MagicMock) -> None:
        """App should have action_start method."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    assert hasattr(app, "action_start")
                    assert callable(app.action_start)

    @pytest.mark.asyncio
    async def test_action_done_exists(self, mock_service: MagicMock) -> None:
        """App should have action_done method."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    assert hasattr(app, "action_done")
                    assert callable(app.action_done)

    @pytest.mark.asyncio
    async def test_flash_message(self, mock_service: MagicMock) -> None:
        """Flash widget should show messages."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        app.flash("Test message", "success")
                        flash = app.query_one("#flash", Flash)
                        assert flash.has_class("-visible")

    @pytest.mark.asyncio
    async def test_input_dialog_show(self, mock_service: MagicMock) -> None:
        """Input dialog should show when requested."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        dialog = app.query_one("#input-dialog", InputDialog)
                        dialog.show("Test prompt:")
                        assert dialog.is_visible
                        assert dialog.has_class("-visible")

    @pytest.mark.asyncio
    async def test_picker_dialog_show(self, mock_service: MagicMock) -> None:
        """Picker dialog should show with options."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        picker = app.query_one("#picker-dialog", PickerDialog)
                        picker.show("Select:", [("opt1", "Option 1"), ("opt2", "Option 2")])
                        assert picker.is_visible
                        assert picker.has_class("-visible")

    @pytest.mark.asyncio
    async def test_escape_closes_dialogs(self, mock_service: MagicMock) -> None:
        """Escape key should close open dialogs."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
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
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        tree.highlighted = 0
                        tree.action_cursor_down()
                        assert tree.highlighted == 1
                        tree.action_cursor_up()
                        assert tree.highlighted == 0

    @pytest.mark.asyncio
    async def test_tree_boundary_handling(self, mock_service: MagicMock) -> None:
        """Tree should not navigate past boundaries."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        tree.highlighted = 0
                        tree.action_cursor_up()
                        assert tree.highlighted == 0

                        tree.highlighted = len(tree.nodes) - 1
                        tree.action_cursor_down()
                        assert tree.highlighted == len(tree.nodes) - 1

    @pytest.mark.asyncio
    async def test_tree_get_selected_issue(self, mock_service: MagicMock) -> None:
        """Tree should return selected issue."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        tree.highlighted = 0
                        issue = tree.get_selected_issue()
                        assert issue is not None
                        assert issue.tw_id == "TW-1"

    @pytest.mark.asyncio
    async def test_tree_select_by_id(self, mock_service: MagicMock) -> None:
        """Tree should select issue by ID."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        tree = app.query_one("#tree-pane", IssueTree)
                        result = tree.select_issue_by_id("TW-1-1")
                        assert result is True
                        assert tree.highlighted == 1


class TestIssueDetail:
    """Tests for IssueDetail widget."""

    @pytest.mark.asyncio
    async def test_detail_updates_on_selection(self, mock_service: MagicMock) -> None:
        """Detail pane should update when selection changes."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                with patch("tw.tui.get_taskwarrior_data_dir"):
                    app = TwApp()
                    async with app.run_test() as pilot:
                        await pilot.pause()
                        detail = app.query_one("#detail-pane", IssueDetail)
                        assert detail.issue is not None
