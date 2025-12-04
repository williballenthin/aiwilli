"""Issue service layer."""

import logging
from datetime import UTC, datetime

from tw.backend import TaskWarriorBackend
from tw.ids import generate_next_epic_id, generate_next_story_id, generate_next_task_id
from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType
from tw.refs import extract_refs

logger = logging.getLogger(__name__)


class IssueService:
    """High-level operations on issues."""

    def __init__(
        self,
        backend: TaskWarriorBackend,
        project: str,
        prefix: str,
    ) -> None:
        self._backend = backend
        self._project = project
        self._prefix = prefix

    def create_issue(
        self,
        issue_type: IssueType,
        title: str,
        parent_id: str | None = None,
        body: str | None = None,
    ) -> str:
        """Create a new issue.

        Args:
            issue_type: The type of issue to create
            title: The issue title
            parent_id: Optional parent tw_id
            body: Optional body text

        Returns:
            The generated tw_id

        Raises:
            ValueError: If the parent type is invalid for this issue type
        """
        from tw.models import is_backlog_type

        # Validate backlog items cannot have parents
        if is_backlog_type(issue_type) and parent_id is not None:
            raise ValueError(f"{issue_type.value} issues cannot have a parent")

        # Validate parent is not a backlog item
        if parent_id is not None:
            parent = self.get_issue(parent_id)
            if is_backlog_type(parent.tw_type):
                raise ValueError(f"{parent.tw_type.value} issues cannot have children")

        existing_ids = self._backend.get_all_ids(self._project, include_deleted=True)

        # Generate ID based on type
        if issue_type == IssueType.EPIC or is_backlog_type(issue_type):
            tw_id = generate_next_epic_id(self._prefix, existing_ids)
        elif issue_type == IssueType.STORY:
            tw_id = generate_next_story_id(parent_id, existing_ids, prefix=self._prefix)
        else:  # TASK
            tw_id = generate_next_task_id(parent_id, existing_ids, prefix=self._prefix)

        # Extract references from body
        tw_refs: list[str] = []
        if body:
            tw_refs = extract_refs(body, self._prefix)

        issue = Issue(
            uuid=self._backend.generate_uuid(),
            tw_id=tw_id,
            tw_type=issue_type,
            title=title,
            tw_status=IssueStatus.NEW,
            project=self._project,
            tw_parent=parent_id,
            tw_body=body,
            tw_refs=tw_refs,
        )

        self._backend.import_issue(issue)
        logger.debug(f"Created {issue_type.value} {tw_id}: {title}")
        return tw_id

    def get_issue(self, tw_id: str) -> Issue:
        """Get an issue by tw_id.

        Raises:
            KeyError: If the issue is not found.
        """
        issues = self._backend.export_project(self._project)
        for issue in issues:
            if issue.tw_id == tw_id:
                return issue
        raise KeyError(f"Issue {tw_id} not found")

    def get_all_issues(self) -> list[Issue]:
        """Get all issues in the project."""
        return self._backend.export_project(self._project)

    def get_issue_with_children(self, tw_id: str) -> tuple[Issue, list[Issue]]:
        """Get an issue and its direct children.

        Args:
            tw_id: The parent issue ID

        Returns:
            Tuple of (parent issue, list of child issues)

        Raises:
            KeyError: If the parent issue is not found.
        """
        parent = self.get_issue(tw_id)
        all_issues = self.get_all_issues()
        children = [issue for issue in all_issues if issue.tw_parent == tw_id]
        return parent, children

    def get_issue_with_context(
        self, tw_id: str
    ) -> tuple[Issue, list[Issue], list[Issue], list[Issue], list[Issue], list[Issue]]:
        """Get an issue with full context (ancestors, siblings, descendants, referenced, referencing).

        Args:
            tw_id: The issue ID

        Returns:
            Tuple of (issue, ancestors, siblings, descendants, referenced, referencing)
            - ancestors: List from immediate parent up to root
            - siblings: Other issues with same parent
            - descendants: All child issues recursively
            - referenced: Issues referenced by this issue
            - referencing: Issues that reference this issue

        Raises:
            KeyError: If the issue is not found.
        """
        from tw.ids import parse_id_sort_key

        issue = self.get_issue(tw_id)
        all_issues = self.get_all_issues()
        issue_by_id = {i.tw_id: i for i in all_issues}

        ancestors: list[Issue] = []
        current_parent_id = issue.tw_parent
        while current_parent_id:
            parent = issue_by_id.get(current_parent_id)
            if parent:
                ancestors.append(parent)
                current_parent_id = parent.tw_parent
            else:
                break

        if issue.tw_parent is not None:
            siblings = [
                i
                for i in all_issues
                if i.tw_parent == issue.tw_parent and i.tw_id != tw_id
            ]
            siblings = sorted(siblings, key=lambda i: parse_id_sort_key(i.tw_id))
        else:
            siblings = []

        def get_all_descendants(issue_id: str) -> list[Issue]:
            """Recursively get all descendants of an issue."""
            result = []
            children = [i for i in all_issues if i.tw_parent == issue_id]
            children = sorted(children, key=lambda i: parse_id_sort_key(i.tw_id))
            for child in children:
                result.append(child)
                result.extend(get_all_descendants(child.tw_id))
            return result

        descendants = get_all_descendants(tw_id)

        referenced = []
        if issue.tw_refs:
            for ref_id in issue.tw_refs:
                ref_issue = issue_by_id.get(ref_id)
                if ref_issue:
                    referenced.append(ref_issue)
        referenced = sorted(referenced, key=lambda i: parse_id_sort_key(i.tw_id))

        referencing = [
            i for i in all_issues
            if i.tw_refs and tw_id in i.tw_refs
        ]
        referencing = sorted(referencing, key=lambda i: parse_id_sort_key(i.tw_id))

        return issue, ancestors, siblings, descendants, referenced, referencing

    def get_issue_tree(self, root_id: str | None = None) -> list[Issue]:
        """Get all issues organized by hierarchy, filtering completed trees.

        Returns issues in tree order sorted by ID, excluding:
        - Epics where the epic AND all descendants are complete
        - Orphan stories where the story AND all descendants are complete
        - Orphan tasks that are complete

        Args:
            root_id: Optional issue ID to use as root. If provided, only returns
                that issue and its descendants.

        Returns:
            List of issues in tree order, sorted by ID

        Raises:
            KeyError: If root_id is provided but the issue is not found.
        """
        from tw.ids import parse_id_sort_key

        all_issues = self.get_all_issues()

        if root_id is not None:
            root_issue = None
            for issue in all_issues:
                if issue.tw_id == root_id:
                    root_issue = issue
                    break

            if root_issue is None:
                raise KeyError(f"Issue {root_id} not found")

            def get_all_descendants(issue_id: str) -> list[Issue]:
                """Recursively get all descendants of an issue."""
                descendants = []
                children = [i for i in all_issues if i.tw_parent == issue_id]
                for child in children:
                    descendants.append(child)
                    descendants.extend(get_all_descendants(child.tw_id))
                return descendants

            result = [root_issue]
            result.extend(get_all_descendants(root_id))

            return sorted(result, key=lambda i: parse_id_sort_key(i.tw_id))

        issue_by_id = {issue.tw_id: issue for issue in all_issues}

        def is_tree_complete(issue_id: str) -> bool:
            """Check if an issue and all its descendants are complete."""
            issue = issue_by_id.get(issue_id)
            if not issue:
                return False

            children = [
                i for i in all_issues if i.tw_parent == issue_id
            ]

            if issue.tw_status != IssueStatus.DONE:
                return False

            for child in children:
                if not is_tree_complete(child.tw_id):
                    return False

            return True

        def get_children_sorted(parent_id: str) -> list[Issue]:
            """Get children of a parent, sorted by ID."""
            children = [i for i in all_issues if i.tw_parent == parent_id]
            return sorted(children, key=lambda i: parse_id_sort_key(i.tw_id))

        # Collect all root-level issues (epics + orphan stories + orphan tasks)
        epics = [
            i for i in all_issues
            if i.tw_type == IssueType.EPIC and not is_tree_complete(i.tw_id)
        ]
        orphan_stories = [
            i for i in all_issues
            if i.tw_type == IssueType.STORY
            and i.tw_parent is None
            and not is_tree_complete(i.tw_id)
        ]
        orphan_tasks = [
            i for i in all_issues
            if i.tw_type == IssueType.TASK
            and i.tw_parent is None
            and i.tw_status != IssueStatus.DONE
        ]

        roots = epics + orphan_stories + orphan_tasks
        roots_sorted = sorted(roots, key=lambda i: parse_id_sort_key(i.tw_id))

        result = []
        for root in roots_sorted:
            result.append(root)
            if root.tw_type == IssueType.EPIC:
                for story in get_children_sorted(root.tw_id):
                    result.append(story)
                    result.extend(get_children_sorted(story.tw_id))
            elif root.tw_type == IssueType.STORY:
                result.extend(get_children_sorted(root.tw_id))

        return result

    def _add_annotation(
        self, issue: Issue, ann_type: AnnotationType, message: str
    ) -> None:
        """Add an annotation to an issue and save."""
        annotation = Annotation(
            type=ann_type,
            timestamp=datetime.now(UTC),
            message=message,
        )
        if issue.annotations is None:
            issue.annotations = []
        issue.annotations.append(annotation)
        self._backend.import_issue(issue)

    def _validate_not_backlog(self, tw_id: str, operation: str) -> Issue:
        """Validate issue is not a backlog type, return the issue.

        Args:
            tw_id: The issue ID to validate
            operation: Name of the operation being performed

        Returns:
            The issue if validation passes

        Raises:
            ValueError: If the issue is a backlog type
        """
        from tw.models import is_backlog_type

        issue = self.get_issue(tw_id)
        if is_backlog_type(issue.tw_type):
            raise ValueError(f"{operation} not supported for {issue.tw_type.value} issues")
        return issue

    def _transition(
        self,
        tw_id: str,
        valid_from: list[IssueStatus],
        to_status: IssueStatus,
        ann_type: AnnotationType,
        message: str,
    ) -> None:
        """Perform a status transition with validation."""
        issue = self.get_issue(tw_id)

        if issue.tw_status not in valid_from:
            raise ValueError(
                f"cannot transition {tw_id}: already {issue.tw_status.value}"
            )

        issue.tw_status = to_status
        self._add_annotation(issue, ann_type, message)
        logger.info(f"{tw_id}: {to_status.value}")

    def start_issue(self, tw_id: str) -> None:
        """Start work on an issue."""
        self._validate_not_backlog(tw_id, "start")
        self._transition(
            tw_id,
            valid_from=[IssueStatus.NEW, IssueStatus.STOPPED],
            to_status=IssueStatus.IN_PROGRESS,
            ann_type=AnnotationType.WORK_BEGIN,
            message="",
        )

    def done_issue(self, tw_id: str, force: bool = False) -> None:
        """Mark an issue as done."""
        from tw.models import is_backlog_type

        issue = self.get_issue(tw_id)

        if not force:
            # Backlog items can go directly from NEW to DONE
            if is_backlog_type(issue.tw_type):
                valid_from = [IssueStatus.NEW, IssueStatus.IN_PROGRESS]
            else:
                valid_from = [IssueStatus.IN_PROGRESS]

            if issue.tw_status not in valid_from:
                raise ValueError(
                    f"cannot transition {tw_id}: status is {issue.tw_status.value}"
                )

            all_issues = self.get_all_issues()
            children = [i for i in all_issues if i.tw_parent == tw_id]
            undone_children = [c for c in children if c.tw_status != IssueStatus.DONE]

            if undone_children:
                undone_ids = ", ".join(c.tw_id for c in undone_children)
                raise ValueError(
                    f"cannot mark {tw_id} as done: has undone children: {undone_ids}"
                )

        issue.tw_status = IssueStatus.DONE
        self._add_annotation(issue, AnnotationType.WORK_END, "")
        logger.info(f"{tw_id}: done")

    def done_issue_recursive(self, tw_id: str, force: bool = False) -> None:
        """Mark an issue and all its descendants as done."""
        all_issues = self.get_all_issues()

        def get_all_descendants(parent_id: str) -> list[str]:
            """Recursively get all descendant IDs."""
            descendants = []
            children = [i for i in all_issues if i.tw_parent == parent_id]
            for child in children:
                descendants.append(child.tw_id)
                descendants.extend(get_all_descendants(child.tw_id))
            return descendants

        descendants = get_all_descendants(tw_id)

        for desc_id in descendants:
            self.done_issue(desc_id, force=force)

        self.done_issue(tw_id, force=force)

    def block_issue(self, tw_id: str, reason: str) -> None:
        """Mark an issue as blocked."""
        self._validate_not_backlog(tw_id, "block")
        self._transition(
            tw_id,
            valid_from=[IssueStatus.IN_PROGRESS],
            to_status=IssueStatus.BLOCKED,
            ann_type=AnnotationType.BLOCKED,
            message=reason,
        )

    def unblock_issue(self, tw_id: str, reason: str) -> None:
        """Unblock an issue."""
        self._validate_not_backlog(tw_id, "unblock")
        self._transition(
            tw_id,
            valid_from=[IssueStatus.BLOCKED],
            to_status=IssueStatus.IN_PROGRESS,
            ann_type=AnnotationType.UNBLOCKED,
            message=reason,
        )

    def handoff_issue(
        self, tw_id: str, status: str, completed: str, remaining: str
    ) -> None:
        """Hand off an issue with structured summary."""
        self._validate_not_backlog(tw_id, "handoff")
        message = f"{status}\n\n## Completed\n{completed}\n\n## Remaining\n{remaining}"
        self._transition(
            tw_id,
            valid_from=[IssueStatus.IN_PROGRESS],
            to_status=IssueStatus.STOPPED,
            ann_type=AnnotationType.HANDOFF,
            message=message,
        )

    def record_annotation(
        self, tw_id: str, ann_type: AnnotationType, message: str
    ) -> None:
        """Add an annotation to an issue."""
        issue = self.get_issue(tw_id)
        self._add_annotation(issue, ann_type, message)

    def update_issue(
        self, tw_id: str, title: str | None = None, body: str | None = None
    ) -> None:
        """Update an issue's title and/or body.

        Args:
            tw_id: The issue ID to update
            title: New title, or None to keep existing
            body: New body, or None to keep existing

        Raises:
            KeyError: If the issue is not found.
        """
        issue = self.get_issue(tw_id)

        if title is not None:
            issue.title = title

        if body is not None:
            issue.tw_body = body if body else None
            issue.tw_refs = extract_refs(body, self._prefix) if body else []

        self._backend.import_issue(issue)
        logger.info(f"Updated {tw_id}")

    def delete_issue(self, tw_id: str) -> None:
        """Delete an issue.

        Args:
            tw_id: The issue ID to delete

        Raises:
            ValueError: If the issue has children that must be deleted first.
            KeyError: If the issue is not found.
        """
        issue = self.get_issue(tw_id)

        all_issues = self.get_all_issues()
        children = [i for i in all_issues if i.tw_parent == tw_id]

        if children:
            child_ids = ", ".join(i.tw_id for i in children)
            raise ValueError(
                f"Cannot delete {tw_id}: it has children ({child_ids}). "
                f"Delete children first."
            )

        self._backend.delete_issue(issue.uuid)
        logger.info(f"Deleted {tw_id}")

    def get_backlog_issues(self) -> list[Issue]:
        """Get all NEW backlog items (bugs and ideas).

        Returns:
            List of backlog issues with NEW status, sorted by ID
        """
        from tw.models import is_backlog_type
        from tw.ids import parse_id_sort_key

        all_issues = self.get_all_issues()
        backlog = [
            i for i in all_issues
            if is_backlog_type(i.tw_type) and i.tw_status == IssueStatus.NEW
        ]
        return sorted(backlog, key=lambda i: parse_id_sort_key(i.tw_id))

    def get_issue_tree_with_backlog(
        self, root_id: str | None = None
    ) -> tuple[list[Issue], list[Issue]]:
        """Get issue tree and backlog separately.

        Returns:
            Tuple of (hierarchy_issues, backlog_issues)
        """
        from tw.models import is_backlog_type

        backlog_issues = self.get_backlog_issues()
        tree = self.get_issue_tree(root_id)
        hierarchy_tree = [
            issue for issue in tree
            if not is_backlog_type(issue.tw_type)
        ]

        return hierarchy_tree, backlog_issues
