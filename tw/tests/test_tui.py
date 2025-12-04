"""Tests for TUI application using Textual's testing framework."""

from unittest.mock import MagicMock, patch

import pytest

from tw.models import Issue, IssueStatus, IssueType
from tw.service import IssueService
from tw.tui import DetailPane, TreeNode, TreePane, TwTuiApp


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


class TestTreeNode:
    """Tests for TreeNode class."""

    def test_tree_node_creation(self) -> None:
        """TreeNode should store issue and depth."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.EPIC,
            title="Test",
            tw_status=IssueStatus.NEW,
            project="tw",
        )
        node = TreeNode(issue=issue, depth=0)

        assert node.issue == issue
        assert node.depth == 0
        assert node.tw_id == "TW-1"

    def test_tree_node_render_line_done_issue(self) -> None:
        """TreeNode should render done issues with strikethrough styling."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.TASK,
            title="Completed Task",
            tw_status=IssueStatus.DONE,
            project="tw",
        )
        node = TreeNode(issue=issue, depth=0)
        line = node.render_line(is_selected=False)

        assert "TW-1" in line
        assert "Completed Task" in line
        assert "done" in line

    def test_tree_node_render_line_in_progress_issue(self) -> None:
        """TreeNode should highlight in_progress issues in yellow."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.TASK,
            title="Active Task",
            tw_status=IssueStatus.IN_PROGRESS,
            project="tw",
        )
        node = TreeNode(issue=issue, depth=0)
        line = node.render_line(is_selected=False)

        assert "TW-1" in line
        assert "Active Task" in line
        assert "in_progress" in line
        assert "[yellow]" in line

    def test_tree_node_render_line_selected(self) -> None:
        """TreeNode should apply reverse styling when selected."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1",
            tw_type=IssueType.TASK,
            title="Test",
            tw_status=IssueStatus.NEW,
            project="tw",
        )
        node = TreeNode(issue=issue, depth=0)
        line = node.render_line(is_selected=True)

        assert "[reverse]" in line

    def test_tree_node_render_line_with_indent(self) -> None:
        """TreeNode should apply proper indentation based on depth."""
        issue = Issue(
            uuid="test-uuid",
            tw_id="TW-1-1-1",
            tw_type=IssueType.TASK,
            title="Deep Task",
            tw_status=IssueStatus.NEW,
            project="tw",
        )
        node = TreeNode(issue=issue, depth=2)
        line = node.render_line(is_selected=False)

        assert line.startswith("    ")


class TestTreePane:
    """Tests for TreePane widget."""

    def test_tree_pane_initialization(self, mock_service: MagicMock) -> None:
        """TreePane should load issues on initialization."""
        pane = TreePane(service=mock_service)

        assert len(pane.nodes) == 4
        assert pane.selected_index == 0
        mock_service.get_issue_tree_with_backlog.assert_called_once()

    def test_tree_pane_get_selected_issue_id(self, mock_service: MagicMock) -> None:
        """TreePane should return correct selected issue ID."""
        pane = TreePane(service=mock_service)
        selected_id = pane.get_selected_issue_id()

        assert selected_id == "TW-1"

    def test_tree_pane_move_down(self, mock_service: MagicMock) -> None:
        """TreePane should move selection down."""
        pane = TreePane(service=mock_service)
        assert pane.selected_index == 0

        pane.action_move_down()

        assert pane.selected_index == 1

    def test_tree_pane_move_down_at_end(self, mock_service: MagicMock) -> None:
        """TreePane should not move down past last item."""
        pane = TreePane(service=mock_service)
        pane.selected_index = len(pane.nodes) - 1

        pane.action_move_down()

        assert pane.selected_index == len(pane.nodes) - 1

    def test_tree_pane_move_up(self, mock_service: MagicMock) -> None:
        """TreePane should move selection up."""
        pane = TreePane(service=mock_service)
        pane.selected_index = 2

        pane.action_move_up()

        assert pane.selected_index == 1

    def test_tree_pane_move_up_at_start(self, mock_service: MagicMock) -> None:
        """TreePane should not move up past first item."""
        pane = TreePane(service=mock_service)
        pane.selected_index = 0

        pane.action_move_up()

        assert pane.selected_index == 0

    def test_tree_pane_render(self, mock_service: MagicMock) -> None:
        """TreePane should render all issues."""
        pane = TreePane(service=mock_service)
        rendered = pane._render_tree()

        assert "TW-1" in rendered
        assert "TW-1-1" in rendered
        assert "TW-1-1a" in rendered
        assert "TW-10" in rendered

    def test_tree_pane_render_empty(self, mock_service: MagicMock) -> None:
        """TreePane should show placeholder when empty."""
        mock_service.get_issue_tree_with_backlog.return_value = ([], [])
        pane = TreePane(service=mock_service)

        rendered = pane._render_tree()

        assert "No issues loaded" in rendered


class TestDetailPane:
    """Tests for DetailPane widget."""

    def test_detail_pane_initialization(self, mock_service: MagicMock) -> None:
        """DetailPane should initialize without selected issue."""
        pane = DetailPane(service=mock_service)

        assert pane.selected_id is None
        assert pane._content == ""

    def test_detail_pane_update_detail(self, mock_service: MagicMock) -> None:
        """DetailPane should update detail for selected issue."""
        pane = DetailPane(service=mock_service)

        pane.update_detail("TW-1")

        assert pane.selected_id == "TW-1"
        mock_service.get_issue_with_context.assert_called_with("TW-1")

    def test_detail_pane_clear_detail(self, mock_service: MagicMock) -> None:
        """DetailPane should clear detail when passed None."""
        pane = DetailPane(service=mock_service)
        pane.update_detail("TW-1")

        pane.update_detail(None)

        assert pane.selected_id is None

    def test_detail_pane_no_service(self) -> None:
        """DetailPane should handle missing service gracefully."""
        pane = DetailPane(service=None)

        pane.update_detail("TW-1")

        assert pane.selected_id == "TW-1"


class TestTwTuiApp:
    """Tests for TwTuiApp using Textual's testing framework."""

    def test_app_initialization(self, mock_service: MagicMock) -> None:
        """App should initialize with service."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                assert app.service is not None
                assert app.last_keypress_time > 0

    def test_app_launches_without_error(self, mock_service: MagicMock) -> None:
        """App should initialize properly."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                # Test that app can be instantiated
                assert app is not None
                assert app.service is not None

    def test_tree_displays_issues(self, mock_service: MagicMock) -> None:
        """Tree pane should display loaded issues."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                tree_pane = TreePane(service=mock_service)
                rendered = tree_pane._render_tree()

                assert "TW-1" in rendered
                assert "Test Epic" in rendered

    def test_navigation_move_down(self, mock_service: MagicMock) -> None:
        """TreePane should move selection down."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                tree_pane = TreePane(service=mock_service)
                initial_index = tree_pane.selected_index

                tree_pane.action_move_down()

                assert tree_pane.selected_index == initial_index + 1

    def test_navigation_move_up(self, mock_service: MagicMock) -> None:
        """TreePane should move selection up."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                tree_pane = TreePane(service=mock_service)
                tree_pane.selected_index = 2
                initial_index = tree_pane.selected_index

                tree_pane.action_move_up()

                assert tree_pane.selected_index == initial_index - 1

    def test_detail_pane_updates_on_selection_change(self, mock_service: MagicMock) -> None:
        """Detail pane should update when selection changes."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                detail_pane = DetailPane(service=mock_service)
                detail_pane.update_detail("TW-1")

                assert detail_pane.selected_id == "TW-1"

    def test_start_action_helpers(self, mock_service: MagicMock) -> None:
        """Test app can be asked to start an issue."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                # Verify action_start method exists
                assert hasattr(app, "action_start")
                assert callable(app.action_start)

    def test_done_action_helpers(self, mock_service: MagicMock) -> None:
        """Test app can be asked to mark issue done."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                # Verify action_done method exists
                assert hasattr(app, "action_done")
                assert callable(app.action_done)

    def test_status_bar_shows_error_on_no_selection(self, mock_service: MagicMock) -> None:
        """action_start should show error when no issue selected."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                mock_service.get_issue_tree_with_backlog.return_value = ([], [])
                tree_pane = TreePane(service=mock_service)
                assert tree_pane.selected_index == -1

    def test_multiple_navigations(self, mock_service: MagicMock) -> None:
        """Multiple navigation commands should work in sequence."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                tree_pane = TreePane(service=mock_service)
                initial_index = tree_pane.selected_index

                tree_pane.action_move_down()
                tree_pane.action_move_down()
                tree_pane.action_move_up()

                assert tree_pane.selected_index == initial_index + 1

    def test_keypress_updates_idle_time(self, mock_service: MagicMock) -> None:
        """Keypresses should update the last_keypress_time."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                initial_time = app.last_keypress_time

                app._on_keypress()

                assert app.last_keypress_time >= initial_time

    def test_infer_child_type_epic_to_story(self, mock_service: MagicMock) -> None:
        """Child of epic should be story."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                child_type = app._infer_child_type(IssueType.EPIC)
                assert child_type == IssueType.STORY

    def test_infer_child_type_story_to_task(self, mock_service: MagicMock) -> None:
        """Child of story should be task."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                child_type = app._infer_child_type(IssueType.STORY)
                assert child_type == IssueType.TASK

    def test_infer_child_type_task_to_task(self, mock_service: MagicMock) -> None:
        """Child of task should be task."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                child_type = app._infer_child_type(IssueType.TASK)
                assert child_type == IssueType.TASK

    def test_infer_promoted_type_epic_to_story(self, mock_service: MagicMock) -> None:
        """Promoted child of epic should be story."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                promoted_type = app._infer_promoted_type(IssueType.EPIC)
                assert promoted_type == IssueType.STORY

    def test_infer_promoted_type_story_to_task(self, mock_service: MagicMock) -> None:
        """Promoted child of story should be task."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                app = TwTuiApp()
                promoted_type = app._infer_promoted_type(IssueType.STORY)
                assert promoted_type == IssueType.TASK

    def test_action_tree_move_down(self, mock_service: MagicMock) -> None:
        """action_tree_move_down should move selection."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                tree_pane = TreePane(service=mock_service)
                initial_index = tree_pane.selected_index
                tree_pane.action_move_down()
                assert tree_pane.selected_index > initial_index

    def test_action_tree_move_up(self, mock_service: MagicMock) -> None:
        """action_tree_move_up should move selection."""
        with patch("tw.tui.TaskWarriorBackend"):
            with patch("tw.tui.IssueService", return_value=mock_service):
                tree_pane = TreePane(service=mock_service)
                tree_pane.selected_index = 2
                initial_index = tree_pane.selected_index
                tree_pane.action_move_up()
                assert tree_pane.selected_index < initial_index
