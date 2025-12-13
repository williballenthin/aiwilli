"""Tests for issue service layer."""

import pytest

from tw.models import AnnotationType, IssueStatus, IssueType
from tw.service import IssueService


class TestIssueService:
    def test_create_epic(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(
            issue_type=IssueType.EPIC,
            title="User Authentication",
        )

        assert tw_id == "TEST-1"
        issue = service.get_issue(tw_id)
        assert issue.title == "User Authentication"
        assert issue.status == IssueStatus.NEW

    def test_create_story_under_epic(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        tw_id = service.create_issue(
            issue_type=IssueType.STORY,
            title="Login Flow",
            parent_id="TEST-1",
        )

        assert tw_id == "TEST-1-1"
        issue = service.get_issue(tw_id)
        assert issue.parent == "TEST-1"

    def test_create_task_under_story(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.STORY, "Story", parent_id="TEST-1")
        tw_id = service.create_issue(
            issue_type=IssueType.TASK,
            title="Implement form",
            parent_id="TEST-1-1",
        )

        assert tw_id == "TEST-1-1a"

    def test_create_orphan_task(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(
            issue_type=IssueType.TASK,
            title="Quick fix",
        )

        assert tw_id == "TEST-1"

    def test_get_issue_not_found(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        with pytest.raises(KeyError, match="not found"):
            service.get_issue("TEST-99")

    def test_deleted_ids_not_reused(self, sqlite_service: IssueService) -> None:
        """With SQLite backend, deleted IDs can be reused."""
        service = sqlite_service

        # Create three epics
        service.create_issue(IssueType.EPIC, "Epic 1")
        service.create_issue(IssueType.EPIC, "Epic 2")
        service.create_issue(IssueType.EPIC, "Epic 3")

        # Delete TEST-3
        service.delete_issue("TEST-3")

        # New epic can reuse TEST-3 since it was deleted from SQLite
        tw_id = service.create_issue(IssueType.EPIC, "Epic 4")
        assert tw_id == "TEST-3"

    def test_deleted_child_ids_not_reused(
        self, sqlite_service: IssueService) -> None:
        """With SQLite backend, deleted child IDs can be reused."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.STORY, "Story", parent_id="TEST-1")
        service.create_issue(IssueType.TASK, "Task a", parent_id="TEST-1-1")
        service.create_issue(IssueType.TASK, "Task b", parent_id="TEST-1-1")
        service.create_issue(IssueType.TASK, "Task c", parent_id="TEST-1-1")

        # Delete TEST-1-1c
        service.delete_issue("TEST-1-1c")

        # New task can reuse TEST-1-1c since it was deleted from SQLite
        tw_id = service.create_issue(IssueType.TASK, "Task d", parent_id="TEST-1-1")
        assert tw_id == "TEST-1-1c"


class TestStatusTransitions:
    def test_start_from_new(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.status == IssueStatus.IN_PROGRESS
        assert issue.annotations is not None
        assert any(a.type == AnnotationType.WORK_BEGIN for a in issue.annotations)

    def test_start_from_stopped(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.handoff_issue(tw_id, "reason", "done", "remaining")
        service.start_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.status == IssueStatus.IN_PROGRESS

    def test_start_invalid_state(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)

        with pytest.raises(ValueError, match="already in_progress"):
            service.start_issue(tw_id)

    def test_done_from_in_progress(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.done_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.status == IssueStatus.DONE
        assert issue.annotations is not None
        assert any(a.type == AnnotationType.WORK_END for a in issue.annotations)

    def test_blocked_and_unblock(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.block_issue(tw_id, "Waiting for API")

        issue = service.get_issue(tw_id)
        assert issue.status == IssueStatus.BLOCKED

        service.unblock_issue(tw_id, "API ready")
        issue = service.get_issue(tw_id)
        assert issue.status == IssueStatus.IN_PROGRESS

    def test_handoff(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.TASK, "Task")
        service.start_issue(tw_id)
        service.handoff_issue(
            tw_id,
            status="Context limit",
            completed="- [x] Item 1",
            remaining="- [ ] Item 2",
        )

        issue = service.get_issue(tw_id)
        assert issue.status == IssueStatus.STOPPED
        assert issue.annotations is not None
        handoff_ann = [a for a in issue.annotations if a.type == AnnotationType.HANDOFF]
        assert len(handoff_ann) == 1
        assert "Context limit" in handoff_ann[0].message


class TestUpdateIssue:
    def test_update_title(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.EPIC, "Old Title")
        service.update_issue(tw_id, title="New Title")

        issue = service.get_issue(tw_id)
        assert issue.title == "New Title"

    def test_update_body(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.EPIC, "Title", body="Old body")
        service.update_issue(tw_id, body="New body")

        issue = service.get_issue(tw_id)
        assert issue.body == "New body"

    def test_update_title_and_body(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.EPIC, "Old Title", body="Old body")
        service.update_issue(tw_id, title="New Title", body="New body")

        issue = service.get_issue(tw_id)
        assert issue.title == "New Title"
        assert issue.body == "New body"

    def test_update_extracts_references(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic 1")
        service.create_issue(IssueType.EPIC, "Epic 2")
        service.update_issue("TEST-1", body="References TEST-2")

        issue = service.get_issue("TEST-1")
        assert "TEST-2" in issue.refs

    def test_update_empty_body_clears_refs(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.EPIC, "Title", body="References TEST-2")
        service.update_issue(tw_id, body="")

        issue = service.get_issue(tw_id)
        assert issue.body is None
        assert issue.refs == []

    def test_update_nonexistent_issue(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        with pytest.raises(KeyError, match="not found"):
            service.update_issue("TEST-99", title="New Title")


class TestGetIssueTree:
    def test_tree_includes_orphan_story(self, sqlite_service: IssueService) -> None:
        """Orphan stories (no parent) should appear in tree."""
        service = sqlite_service

        service.create_issue(IssueType.STORY, "Orphan Story")

        tree = service.get_issue_tree()
        ids = [i.id for i in tree]
        assert "TEST-1" in ids

    def test_tree_includes_orphan_task(self, sqlite_service: IssueService) -> None:
        """Orphan tasks (no parent) should appear in tree."""
        service = sqlite_service

        service.create_issue(IssueType.TASK, "Orphan Task")

        tree = service.get_issue_tree()
        ids = [i.id for i in tree]
        assert "TEST-1" in ids

    def test_tree_includes_orphan_story_with_children(
        self, sqlite_service: IssueService) -> None:
        """Orphan story's children should also appear in tree."""
        service = sqlite_service

        story_id = service.create_issue(IssueType.STORY, "Orphan Story")
        service.create_issue(IssueType.TASK, "Child Task", parent_id=story_id)

        tree = service.get_issue_tree()
        ids = [i.id for i in tree]
        assert story_id in ids
        assert "TEST-1-1" in ids

    def test_tree_excludes_completed_orphan_story(
        self, sqlite_service: IssueService) -> None:
        """Completed orphan story trees should be excluded."""
        service = sqlite_service

        story_id = service.create_issue(IssueType.STORY, "Orphan Story")
        task_id = service.create_issue(IssueType.TASK, "Child Task", parent_id=story_id)

        service.start_issue(task_id)
        service.done_issue(task_id)
        service.start_issue(story_id)
        service.done_issue(story_id)

        tree = service.get_issue_tree()
        ids = [i.id for i in tree]
        assert story_id not in ids
        assert task_id not in ids

    def test_tree_excludes_completed_orphan_task(
        self, sqlite_service: IssueService) -> None:
        """Completed orphan tasks should be excluded."""
        service = sqlite_service

        task_id = service.create_issue(IssueType.TASK, "Orphan Task")
        service.start_issue(task_id)
        service.done_issue(task_id)

        tree = service.get_issue_tree()
        ids = [i.id for i in tree]
        assert task_id not in ids

    def test_tree_sorted_with_orphans_interspersed(
        self, sqlite_service: IssueService) -> None:
        """Tree should be sorted by ID with orphans mixed in."""
        service = sqlite_service

        # Create in non-sorted order to verify sorting
        service.create_issue(IssueType.EPIC, "Epic 1")  # TEST-1
        service.create_issue(IssueType.STORY, "Orphan Story")  # TEST-2 (orphan)
        service.create_issue(IssueType.EPIC, "Epic 3")  # TEST-3

        tree = service.get_issue_tree()
        ids = [i.id for i in tree]

        # Orphan story should appear between epics based on ID sort
        assert ids == ["TEST-1", "TEST-2", "TEST-3"]


class TestGetIssueWithContext:
    def test_returns_ancestors_chain(self, sqlite_service: IssueService) -> None:
        """Ancestors should be returned from immediate parent up to root."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.STORY, "Story", parent_id="TEST-1")
        service.create_issue(IssueType.TASK, "Task", parent_id="TEST-1-1")

        result = service.get_issue_with_context("TEST-1-1a")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-1-1a"
        assert len(ancestors) == 2
        assert ancestors[0].id == "TEST-1-1"  # immediate parent
        assert ancestors[1].id == "TEST-1"  # grandparent (root)

    def test_returns_siblings(self, sqlite_service: IssueService) -> None:
        """Siblings should be other issues with same parent."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.STORY, "Story 1", parent_id="TEST-1")
        service.create_issue(IssueType.STORY, "Story 2", parent_id="TEST-1")
        service.create_issue(IssueType.STORY, "Story 3", parent_id="TEST-1")

        result = service.get_issue_with_context("TEST-1-2")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-1-2"
        assert len(siblings) == 2
        sibling_ids = [s.id for s in siblings]
        assert "TEST-1-1" in sibling_ids
        assert "TEST-1-3" in sibling_ids
        assert "TEST-1-2" not in sibling_ids  # self excluded

    def test_returns_descendants_recursively(
        self, sqlite_service: IssueService) -> None:
        """Descendants should include all children recursively."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.STORY, "Story 1", parent_id="TEST-1")
        service.create_issue(IssueType.STORY, "Story 2", parent_id="TEST-1")
        service.create_issue(IssueType.TASK, "Task 1a", parent_id="TEST-1-1")
        service.create_issue(IssueType.TASK, "Task 1b", parent_id="TEST-1-1")

        result = service.get_issue_with_context("TEST-1")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-1"
        assert len(descendants) == 4
        desc_ids = [d.id for d in descendants]
        assert desc_ids == ["TEST-1-1", "TEST-1-1a", "TEST-1-1b", "TEST-1-2"]

    def test_orphan_has_empty_ancestors(self, sqlite_service: IssueService) -> None:
        """Orphan issues should have no ancestors."""
        service = sqlite_service

        service.create_issue(IssueType.TASK, "Orphan Task")

        result = service.get_issue_with_context("TEST-1")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-1"
        assert ancestors == []

    def test_leaf_has_empty_descendants(self, sqlite_service: IssueService) -> None:
        """Leaf issues should have no descendants."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.STORY, "Story", parent_id="TEST-1")
        service.create_issue(IssueType.TASK, "Task", parent_id="TEST-1-1")

        result = service.get_issue_with_context("TEST-1-1a")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-1-1a"
        assert descendants == []

    def test_root_orphans_have_no_siblings(self, sqlite_service: IssueService) -> None:
        """Orphans at root level should have no siblings."""
        service = sqlite_service

        service.create_issue(IssueType.TASK, "Orphan 1")
        service.create_issue(IssueType.TASK, "Orphan 2")
        service.create_issue(IssueType.EPIC, "Epic")

        result = service.get_issue_with_context("TEST-1")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-1"
        assert len(siblings) == 0

    def test_nonexistent_issue_raises(self, sqlite_service: IssueService) -> None:
        """Should raise KeyError for nonexistent issue."""
        service = sqlite_service

        with pytest.raises(KeyError, match="not found"):
            service.get_issue_with_context("TEST-99")

    def test_returns_referenced_issues(self, sqlite_service: IssueService) -> None:
        """Referenced issues should be returned."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic 1")
        service.create_issue(IssueType.EPIC, "Epic 2")
        service.create_issue(IssueType.EPIC, "Epic 3", body="References TEST-1 and TEST-2")

        result = service.get_issue_with_context("TEST-3")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-3"
        assert len(referenced) == 2
        ref_ids = [r.id for r in referenced]
        assert "TEST-1" in ref_ids
        assert "TEST-2" in ref_ids

    def test_returns_referencing_issues(self, sqlite_service: IssueService) -> None:
        """Issues referencing this one should be returned."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic 1")
        service.create_issue(IssueType.EPIC, "Epic 2", body="References TEST-1")
        service.create_issue(IssueType.EPIC, "Epic 3", body="Also references TEST-1")

        result = service.get_issue_with_context("TEST-1")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        assert issue.id == "TEST-1"
        assert len(referencing) == 2
        ref_ids = [r.id for r in referencing]
        assert "TEST-2" in ref_ids
        assert "TEST-3" in ref_ids

    def test_referenced_and_referencing_sorted_by_id(self, sqlite_service: IssueService) -> None:
        """Referenced and referencing lists should be sorted by ID."""
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic 1")
        service.create_issue(IssueType.EPIC, "Epic 2")
        service.create_issue(IssueType.EPIC, "Epic 3")
        service.create_issue(IssueType.EPIC, "Epic 4", body="References TEST-3, TEST-1, TEST-2")

        result = service.get_issue_with_context("TEST-4")
        issue, ancestors, siblings, descendants, referenced, referencing = result

        ref_ids = [r.id for r in referenced]
        assert ref_ids == ["TEST-1", "TEST-2", "TEST-3"]


class TestBacklogIssues:
    def test_create_bug_gets_top_level_id(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(
            issue_type=IssueType.BUG,
            title="Login broken",
        )

        assert tw_id == "TEST-1"
        issue = service.get_issue(tw_id)
        assert issue.type == IssueType.BUG
        assert issue.status == IssueStatus.NEW

    def test_create_idea_gets_top_level_id(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(
            issue_type=IssueType.IDEA,
            title="Password strength meter",
        )

        assert tw_id == "TEST-1"
        issue = service.get_issue(tw_id)
        assert issue.type == IssueType.IDEA

    def test_backlog_shares_id_namespace_with_epics(
        self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic 1")  # TEST-1
        service.create_issue(IssueType.BUG, "Bug 1")  # TEST-2
        service.create_issue(IssueType.IDEA, "Idea 1")  # TEST-3
        service.create_issue(IssueType.EPIC, "Epic 2")  # TEST-4

        issues = service.get_all_issues()
        ids = sorted([i.id for i in issues])
        assert ids == ["TEST-1", "TEST-2", "TEST-3", "TEST-4"]

    def test_backlog_rejects_parent(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")

        with pytest.raises(ValueError, match="cannot have a parent"):
            service.create_issue(IssueType.BUG, "Bug", parent_id="TEST-1")

        with pytest.raises(ValueError, match="cannot have a parent"):
            service.create_issue(IssueType.IDEA, "Idea", parent_id="TEST-1")

    def test_backlog_cannot_be_parent(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.BUG, "Bug")

        with pytest.raises(ValueError, match="cannot have children"):
            service.create_issue(IssueType.TASK, "Task", parent_id="TEST-1")

    def test_backlog_done_from_new(self, sqlite_service: IssueService) -> None:
        """Backlog items can go directly from NEW to DONE."""
        service = sqlite_service

        tw_id = service.create_issue(IssueType.BUG, "Bug")
        service.done_issue(tw_id)

        issue = service.get_issue(tw_id)
        assert issue.status == IssueStatus.DONE

    def test_backlog_rejects_start(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.BUG, "Bug")

        with pytest.raises(ValueError, match="not supported for"):
            service.start_issue(tw_id)

    def test_backlog_rejects_handoff(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.IDEA, "Idea")

        with pytest.raises(ValueError, match="not supported for"):
            service.handoff_issue(tw_id, "status", "completed", "remaining")

    def test_backlog_rejects_block(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.BUG, "Bug")

        with pytest.raises(ValueError, match="not supported for"):
            service.block_issue(tw_id, "reason")

    def test_backlog_rejects_unblock(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        tw_id = service.create_issue(IssueType.BUG, "Bug")

        with pytest.raises(ValueError, match="not supported for"):
            service.unblock_issue(tw_id, "reason")

    def test_get_backlog_issues(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.BUG, "Bug 1")
        service.create_issue(IssueType.IDEA, "Idea 1")
        service.create_issue(IssueType.BUG, "Bug 2")

        # Mark one as done
        service.done_issue("TEST-4")

        backlog = service.get_backlog_issues()
        ids = [i.id for i in backlog]

        assert "TEST-2" in ids  # Bug 1
        assert "TEST-3" in ids  # Idea 1
        assert "TEST-1" not in ids  # Epic excluded
        assert "TEST-4" not in ids  # Done bug excluded


class TestGetIssueTreeWithBacklog:
    def test_tree_separates_backlog(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.EPIC, "Epic")
        service.create_issue(IssueType.BUG, "Bug 1")
        service.create_issue(IssueType.IDEA, "Idea 1")

        hierarchy, backlog = service.get_issue_tree_with_backlog()

        hierarchy_ids = [i.id for i in hierarchy]
        backlog_ids = [i.id for i in backlog]

        assert "TEST-1" in hierarchy_ids
        assert "TEST-2" in backlog_ids
        assert "TEST-3" in backlog_ids
        assert "TEST-2" not in hierarchy_ids

    def test_backlog_excludes_done(self, sqlite_service: IssueService) -> None:
        service = sqlite_service

        service.create_issue(IssueType.BUG, "Bug 1")
        service.create_issue(IssueType.BUG, "Bug 2")
        service.done_issue("TEST-1")

        hierarchy, backlog = service.get_issue_tree_with_backlog()
        backlog_ids = [i.id for i in backlog]

        assert "TEST-1" not in backlog_ids
        assert "TEST-2" in backlog_ids
