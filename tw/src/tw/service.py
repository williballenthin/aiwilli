"""Issue service layer."""

import logging
from datetime import UTC, datetime

from tw.backend import SqliteBackend
from tw.ids import generate_next_epic_id, generate_next_story_id, generate_next_task_id
from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType
from tw.refs import extract_refs

logger = logging.getLogger(__name__)


class IssueService:
    """High-level operations on issues."""

    def __init__(
        self,
        backend: SqliteBackend,
        prefix: str,
    ) -> None:
        self._backend = backend
        self._prefix = prefix

    def _get_all_issues(self) -> list[Issue]:
        """Get all issues from backend."""
        return self._backend.get_all_issues()

    def _save_issue(self, issue: Issue) -> None:
        """Save an issue to the backend."""
        self._backend.save_issue(issue)

    def _get_all_ids(self, include_deleted: bool = False) -> list[str]:
        """Get all issue IDs."""
        return self._backend.get_all_ids()

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
            if is_backlog_type(parent.type):
                raise ValueError(f"{parent.type.value} issues cannot have children")

        existing_ids = self._get_all_ids(include_deleted=True)

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

        now = datetime.now(UTC)
        issue = Issue(
            id=tw_id,
            type=issue_type,
            title=title,
            status=IssueStatus.NEW,
            created_at=now,
            updated_at=now,
            parent=parent_id,
            body=body,
            refs=tw_refs,
        )

        self._save_issue(issue)
        logger.debug(f"Created {issue_type.value} {tw_id}: {title}")
        return tw_id

    def get_issue(self, tw_id: str) -> Issue:
        """Get an issue by tw_id.

        Raises:
            KeyError: If the issue is not found.
        """
        issue = self._backend.get_issue(tw_id)
        if issue is None:
            raise KeyError(f"Issue {tw_id} not found")
        return issue

    def get_all_issues(self) -> list[Issue]:
        """Get all issues in the project."""
        return self._get_all_issues()

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
        children = [issue for issue in all_issues if issue.parent == tw_id]
        return parent, children

    def get_issue_with_context(
        self, tw_id: str
    ) -> tuple[Issue, list[Issue], list[Issue], list[Issue], list[Issue], list[Issue]]:
        """Get an issue with full context.

        Context includes: ancestors, siblings, descendants, referenced, referencing.

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
        issue_by_id = {i.id: i for i in all_issues}

        ancestors: list[Issue] = []
        current_parent_id = issue.parent
        while current_parent_id:
            parent = issue_by_id.get(current_parent_id)
            if parent:
                ancestors.append(parent)
                current_parent_id = parent.parent
            else:
                break

        if issue.parent is not None:
            siblings = [
                i
                for i in all_issues
                if i.parent == issue.parent and i.id != tw_id
            ]
            siblings = sorted(siblings, key=lambda i: parse_id_sort_key(i.id))
        else:
            siblings = []

        def get_all_descendants(issue_id: str) -> list[Issue]:
            """Recursively get all descendants of an issue."""
            result = []
            children = [i for i in all_issues if i.parent == issue_id]
            children = sorted(children, key=lambda i: parse_id_sort_key(i.id))
            for child in children:
                result.append(child)
                result.extend(get_all_descendants(child.id))
            return result

        descendants = get_all_descendants(tw_id)

        referenced = []
        if issue.refs:
            for ref_id in issue.refs:
                ref_issue = issue_by_id.get(ref_id)
                if ref_issue:
                    referenced.append(ref_issue)
        referenced = sorted(referenced, key=lambda i: parse_id_sort_key(i.id))

        referencing = [
            i for i in all_issues
            if i.refs and tw_id in i.refs
        ]
        referencing = sorted(referencing, key=lambda i: parse_id_sort_key(i.id))

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
                if issue.id == root_id:
                    root_issue = issue
                    break

            if root_issue is None:
                raise KeyError(f"Issue {root_id} not found")

            def get_all_descendants(issue_id: str) -> list[Issue]:
                """Recursively get all descendants of an issue."""
                descendants = []
                children = [i for i in all_issues if i.parent == issue_id]
                for child in children:
                    descendants.append(child)
                    descendants.extend(get_all_descendants(child.id))
                return descendants

            result = [root_issue]
            result.extend(get_all_descendants(root_id))

            return sorted(result, key=lambda i: parse_id_sort_key(i.id))

        issue_by_id = {issue.id: issue for issue in all_issues}

        def is_tree_complete(issue_id: str) -> bool:
            """Check if an issue and all its descendants are complete."""
            issue = issue_by_id.get(issue_id)
            if not issue:
                return False

            children = [
                i for i in all_issues if i.parent == issue_id
            ]

            if issue.status != IssueStatus.DONE:
                return False

            for child in children:
                if not is_tree_complete(child.id):
                    return False

            return True

        def get_children_sorted(parent_id: str) -> list[Issue]:
            """Get children of a parent, sorted by ID."""
            children = [i for i in all_issues if i.parent == parent_id]
            return sorted(children, key=lambda i: parse_id_sort_key(i.id))

        # Collect all root-level issues (epics + orphan stories + orphan tasks)
        epics = [
            i for i in all_issues
            if i.type == IssueType.EPIC and not is_tree_complete(i.id)
        ]
        orphan_stories = [
            i for i in all_issues
            if i.type == IssueType.STORY
            and i.parent is None
            and not is_tree_complete(i.id)
        ]
        orphan_tasks = [
            i for i in all_issues
            if i.type == IssueType.TASK
            and i.parent is None
            and i.status != IssueStatus.DONE
        ]

        roots = epics + orphan_stories + orphan_tasks
        roots_sorted = sorted(roots, key=lambda i: parse_id_sort_key(i.id))

        result = []
        for root in roots_sorted:
            result.append(root)
            if root.type == IssueType.EPIC:
                for story in get_children_sorted(root.id):
                    result.append(story)
                    result.extend(get_children_sorted(story.id))
            elif root.type == IssueType.STORY:
                result.extend(get_children_sorted(root.id))

        return result

    def _add_annotation(
        self, issue: Issue, ann_type: AnnotationType, message: str
    ) -> None:
        """Add an annotation to an issue and save."""
        now = datetime.now(UTC)
        annotation = Annotation(
            type=ann_type,
            timestamp=now,
            message=message,
        )
        if issue.annotations is None:
            issue.annotations = []
        issue.annotations.append(annotation)
        issue.updated_at = now

        self._backend.add_annotation(issue.id, annotation)
        self._backend.save_issue(issue)

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
        if is_backlog_type(issue.type):
            raise ValueError(f"{operation} not supported for {issue.type.value} issues")
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

        if issue.status not in valid_from:
            raise ValueError(
                f"cannot transition {tw_id}: already {issue.status.value}"
            )

        issue.status = to_status
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
            if is_backlog_type(issue.type):
                valid_from = [IssueStatus.NEW, IssueStatus.IN_PROGRESS]
            else:
                valid_from = [IssueStatus.IN_PROGRESS]

            if issue.status not in valid_from:
                raise ValueError(
                    f"cannot transition {tw_id}: status is {issue.status.value}"
                )

            all_issues = self.get_all_issues()
            children = [i for i in all_issues if i.parent == tw_id]
            undone_children = [c for c in children if c.status != IssueStatus.DONE]

            if undone_children:
                undone_ids = ", ".join(c.id for c in undone_children)
                raise ValueError(
                    f"cannot mark {tw_id} as done: has undone children: {undone_ids}"
                )

        issue.status = IssueStatus.DONE
        self._add_annotation(issue, AnnotationType.WORK_END, "")
        logger.info(f"{tw_id}: done")

    def done_issue_recursive(self, tw_id: str, force: bool = False) -> None:
        """Mark an issue and all its descendants as done."""
        all_issues = self.get_all_issues()

        def get_all_descendants(parent_id: str) -> list[str]:
            """Recursively get all descendant IDs."""
            descendants = []
            children = [i for i in all_issues if i.parent == parent_id]
            for child in children:
                descendants.append(child.id)
                descendants.extend(get_all_descendants(child.id))
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
            issue.body = body if body else None
            issue.refs = extract_refs(body, self._prefix) if body else []

        issue.updated_at = datetime.now(UTC)
        self._save_issue(issue)
        logger.info(f"Updated {tw_id}")

    def delete_issue(self, tw_id: str) -> None:
        """Delete an issue.

        Args:
            tw_id: The issue ID to delete

        Raises:
            ValueError: If the issue has children that must be deleted first.
            KeyError: If the issue is not found.
        """
        self.get_issue(tw_id)

        all_issues = self.get_all_issues()
        children = [i for i in all_issues if i.parent == tw_id]

        if children:
            child_ids = ", ".join(i.id for i in children)
            raise ValueError(
                f"Cannot delete {tw_id}: it has children ({child_ids}). "
                f"Delete children first."
            )

        self._backend.delete_issue(tw_id)
        logger.info(f"Deleted {tw_id}")

    def promote_issue(
        self,
        tw_id: str,
        target_type: IssueType | None = None,
        new_parent_id: str | None = None,
    ) -> str:
        """Promote an issue to a specific type or parent.

        Creates a new issue with the specified type and parent, copies all
        metadata (title, body, annotations, status), and deletes the original.
        If the issue has children, they are recursively moved as well.

        Args:
            tw_id: The issue ID to promote
            target_type: The desired issue type (epic, story, task). If None,
                type is inferred from parent.
            new_parent_id: The new parent's tw_id, or None for orphan

        Returns:
            The new tw_id of the promoted issue

        Raises:
            ValueError: If the promotion is invalid
            KeyError: If the issue or parent is not found.
        """
        from tw.models import is_backlog_type

        issue = self.get_issue(tw_id)

        if new_parent_id == tw_id:
            raise ValueError("Cannot promote an issue to itself")

        if new_parent_id is not None:
            new_parent = self.get_issue(new_parent_id)
            if is_backlog_type(new_parent.type):
                raise ValueError(f"Cannot promote to a {new_parent.type.value}")

            ancestors = []
            current = new_parent
            while current.parent:
                ancestors.append(current.parent)
                try:
                    current = self.get_issue(current.parent)
                except KeyError:
                    break
            if tw_id in ancestors:
                raise ValueError("Cannot promote an issue to one of its descendants")

        all_issues = self.get_all_issues()
        children = [i for i in all_issues if i.parent == tw_id]
        existing_ids = self._get_all_ids(include_deleted=True)

        if target_type is not None:
            new_type = target_type
            if new_type == IssueType.EPIC or is_backlog_type(new_type):
                if new_parent_id is not None:
                    raise ValueError("Epics and backlog items cannot have parents")
                new_id = generate_next_epic_id(self._prefix, existing_ids)
            elif new_type == IssueType.STORY:
                if new_parent_id is not None:
                    parent = self.get_issue(new_parent_id)
                    if parent.type != IssueType.EPIC:
                        raise ValueError("Stories can only be children of epics")
                    new_id = generate_next_story_id(new_parent_id, existing_ids, self._prefix)
                else:
                    new_id = generate_next_story_id(None, existing_ids, self._prefix)
            else:
                if new_parent_id is not None:
                    new_id = generate_next_task_id(new_parent_id, existing_ids, self._prefix)
                else:
                    new_id = generate_next_task_id(None, existing_ids, self._prefix)
        elif new_parent_id is None:
            new_type = IssueType.EPIC
            new_id = generate_next_epic_id(self._prefix, existing_ids)
        else:
            new_parent = self.get_issue(new_parent_id)
            if new_parent.type == IssueType.EPIC:
                new_type = IssueType.STORY
                new_id = generate_next_story_id(new_parent_id, existing_ids, self._prefix)
            else:
                new_type = IssueType.TASK
                new_id = generate_next_task_id(new_parent_id, existing_ids, self._prefix)

        now = datetime.now(UTC)
        new_issue = Issue(
            id=new_id,
            type=new_type,
            title=issue.title,
            status=issue.status,
            created_at=issue.created_at,
            updated_at=now,
            parent=new_parent_id,
            body=issue.body,
            refs=issue.refs,
            annotations=issue.annotations,
        )
        self._save_issue(new_issue)
        existing_ids.append(new_id)

        for child in children:
            self.reparent_issue(child.id, new_id)
        self._backend.delete_issue(tw_id)
        logger.info(f"Promoted {tw_id} -> {new_id}")
        return new_id

    def reparent_issue(self, tw_id: str, new_parent_id: str | None) -> str:
        """Move an issue to a new parent.

        Creates a new issue under the new parent with a new ID, copies all
        metadata (title, body, annotations, status), and deletes the original.
        If the issue has children, they are recursively moved as well.

        Args:
            tw_id: The issue ID to move
            new_parent_id: The new parent's tw_id, or None to make it a
                top-level issue

        Returns:
            The new tw_id of the moved issue

        Raises:
            ValueError: If the move is invalid (e.g., moving to self, invalid
                parent type, or backlog item)
            KeyError: If the issue or parent is not found.
        """
        from tw.models import is_backlog_type

        issue = self.get_issue(tw_id)

        if is_backlog_type(issue.type):
            raise ValueError("Cannot re-parent backlog items; use promote instead")

        if new_parent_id == tw_id:
            raise ValueError("Cannot re-parent an issue to itself")

        if new_parent_id is not None:
            new_parent = self.get_issue(new_parent_id)
            if is_backlog_type(new_parent.type):
                raise ValueError(f"Cannot re-parent to a {new_parent.type.value}")

            ancestors = []
            current = new_parent
            while current.parent:
                ancestors.append(current.parent)
                try:
                    current = self.get_issue(current.parent)
                except KeyError:
                    break
            if tw_id in ancestors:
                raise ValueError("Cannot re-parent an issue to one of its descendants")

        all_issues = self.get_all_issues()
        children = [i for i in all_issues if i.parent == tw_id]
        existing_ids = self._get_all_ids(include_deleted=True)

        if new_parent_id is None:
            new_type = IssueType.EPIC
            new_id = generate_next_epic_id(self._prefix, existing_ids)
        else:
            new_parent = self.get_issue(new_parent_id)
            if new_parent.type == IssueType.EPIC:
                new_type = IssueType.STORY
                new_id = generate_next_story_id(new_parent_id, existing_ids, self._prefix)
            else:
                new_type = IssueType.TASK
                new_id = generate_next_task_id(new_parent_id, existing_ids, self._prefix)

        now = datetime.now(UTC)
        new_issue = Issue(
            id=new_id,
            type=new_type,
            title=issue.title,
            status=issue.status,
            created_at=issue.created_at,
            updated_at=now,
            parent=new_parent_id,
            body=issue.body,
            refs=issue.refs,
            annotations=issue.annotations,
        )
        self._save_issue(new_issue)
        existing_ids.append(new_id)

        for child in children:
            self.reparent_issue(child.id, new_id)
        self._backend.delete_issue(tw_id)
        logger.info(f"Re-parented {tw_id} -> {new_id}")
        return new_id

    def get_backlog_issues(self) -> list[Issue]:
        """Get all NEW backlog items (bugs and ideas).

        Returns:
            List of backlog issues with NEW status, sorted by ID
        """
        from tw.ids import parse_id_sort_key
        from tw.models import is_backlog_type

        all_issues = self.get_all_issues()
        backlog = [
            i for i in all_issues
            if is_backlog_type(i.type) and i.status == IssueStatus.NEW
        ]
        return sorted(backlog, key=lambda i: parse_id_sort_key(i.id))

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
            if not is_backlog_type(issue.type)
        ]

        return hierarchy_tree, backlog_issues
