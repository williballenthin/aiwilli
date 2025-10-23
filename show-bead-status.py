#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "rich>=13.0.0",
#     "pydantic>=2.0.0",
# ]
# ///

"""Visualize Beads issue status and dependency trees."""

import argparse
import json
import subprocess
import sys
from enum import Enum

from pydantic import BaseModel
from rich.console import Console
from rich.tree import Tree


class IssueStatus(str, Enum):
    """Issue status values."""

    open = "open"
    in_progress = "in_progress"
    closed = "closed"


class Issue(BaseModel):
    """Represents a Beads issue with dependencies."""

    id: str
    title: str
    status: IssueStatus
    issue_type: str
    dependencies: list["Issue"] | None = None
    dependents: list["Issue"] | None = None

    def get_all_related(self) -> set[str]:
        """Recursively collect all related issue IDs."""
        related = {self.id}
        if self.dependencies:
            for dep in self.dependencies:
                related.update(dep.get_all_related())
        if self.dependents:
            for dep in self.dependents:
                related.update(dep.get_all_related())
        return related


def fetch_open_issues() -> list[str]:
    """Fetch all open issue IDs.

    Returns: List of issue IDs

    Raises:
        subprocess.CalledProcessError: If bd command fails
    """
    result = subprocess.run(
        ["bd", "list", "--status", "open", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    issues_data = json.loads(result.stdout)
    return [issue["id"] for issue in (issues_data or [])]


def fetch_issue_details(issue_id: str) -> Issue:
    """Fetch full issue details including dependency trees.

    Args:
        issue_id: The issue ID to fetch

    Returns: Issue object with nested dependencies/dependents

    Raises:
        subprocess.CalledProcessError: If bd command fails
    """
    result = subprocess.run(
        ["bd", "show", issue_id, "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    issue_data = json.loads(result.stdout)
    return Issue.model_validate(issue_data)


def build_issue_graph(open_issue_ids: list[str]) -> dict[str, Issue]:
    """Build unified graph of all issues related to open issues.

    Since bd show only returns shallow dependencies, we need to recursively
    fetch each dependency to build the full tree, then rebuild references.

    Args:
        open_issue_ids: List of open issue IDs to fetch

    Returns: Dictionary mapping issue ID to Issue object (deduplicated)
    """
    graph: dict[str, Issue] = {}
    to_fetch = set(open_issue_ids)
    fetched = set()

    # Phase 1: Fetch all related issues
    while to_fetch:
        issue_id = to_fetch.pop()
        if issue_id in fetched:
            continue

        fetched.add(issue_id)
        issue = fetch_issue_details(issue_id)
        graph[issue_id] = issue

        # Add dependencies and dependents to fetch queue
        if issue.dependencies:
            for dep in issue.dependencies:
                if dep.id not in fetched:
                    to_fetch.add(dep.id)

        if issue.dependents:
            for dep in issue.dependents:
                if dep.id not in fetched:
                    to_fetch.add(dep.id)

    # Phase 2: Rebuild references to point to full graph objects
    for issue_id, issue in graph.items():
        if issue.dependencies:
            # Replace shallow deps with full graph objects
            issue.dependencies = [
                graph[dep.id] for dep in issue.dependencies if dep.id in graph
            ]
        if issue.dependents:
            # Replace shallow dependents with full graph objects
            issue.dependents = [
                graph[dep.id] for dep in issue.dependents if dep.id in graph
            ]

    return graph


def _find_issue_in_tree(root: Issue, target_id: str) -> Issue | None:
    """Recursively find an issue in a tree by ID.

    Args:
        root: Root issue to search from
        target_id: Issue ID to find

    Returns: Issue if found, None otherwise
    """
    if root.id == target_id:
        return root

    if root.dependencies:
        for dep in root.dependencies:
            found = _find_issue_in_tree(dep, target_id)
            if found:
                return found

    if root.dependents:
        for dep in root.dependents:
            found = _find_issue_in_tree(dep, target_id)
            if found:
                return found

    return None


def has_open_issues(issue: Issue) -> bool:
    """Check if an issue tree contains any open issues.

    Args:
        issue: Root issue to check

    Returns: True if issue or any of its dependencies are open
    """
    if issue.status != IssueStatus.closed:
        return True

    if issue.dependencies:
        for dep in issue.dependencies:
            if has_open_issues(dep):
                return True

    return False


def render_issue_tree(
    issue: Issue, graph: dict[str, Issue], visited: set[str] | None = None
) -> Tree:
    """Render an issue and its dependencies as a Rich Tree.

    Tree structure: dependencies (prerequisites) are deeper, current issue is at root.
    This shows the flow from what must be done first (deep) to the goal (root).

    Args:
        issue: Root issue to render (the goal)
        graph: Full issue graph for lookups
        visited: Set of already-visited IDs (cycle detection)

    Returns: Rich Tree object
    """
    if visited is None:
        visited = set()

    # Prevent infinite recursion
    if issue.id in visited:
        return Tree(f"[dim]{issue.id}: {issue.title} (circular ref)[/dim]")

    visited.add(issue.id)

    # Color based on status: open=default, in_progress=green, closed=dim gray
    status_label = issue.status.value.upper()

    if issue.status == IssueStatus.open:
        # Open issues use default color (no markup)
        label = f"[{status_label}] {issue.id}: {issue.title}"
    elif issue.status == IssueStatus.in_progress:
        # In progress issues are green
        label = f"[green][{status_label}] {issue.id}: {issue.title}[/green]"
    else:  # closed
        # Closed issues are muted gray
        label = f"[dim][{status_label}] {issue.id}: {issue.title}[/dim]"

    tree = Tree(label)

    # Add dependencies (things that must be done first) as children
    # These go deeper in the tree since they happen first
    if issue.dependencies:
        for dep in issue.dependencies:
            dep_tree = render_issue_tree(dep, graph, visited.copy())
            tree.add(dep_tree)

    return tree


def main() -> int:
    """Main entry point for the tool.

    Returns: Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Visualize Beads issue status and dependency trees"
    )
    parser.add_argument(
        "--color",
        action="store_true",
        help="Force colored output even when not connected to a terminal",
    )
    args = parser.parse_args()

    console = Console(force_terminal=args.color)

    try:
        # Fetch all open issues
        open_ids = fetch_open_issues()

        if not open_ids:
            console.print("[yellow]No open issues found.[/yellow]")
            return 0

        # Build full graph
        graph = build_issue_graph(open_ids)

        # Find root issues (issues not blocked by other issues in the graph)
        # Include both open and closed issues initially
        all_dependencies = set()
        for issue_id, issue in graph.items():
            if issue.dependencies:
                for dep in issue.dependencies:
                    all_dependencies.add(dep.id)

        root_ids = [id for id in graph.keys() if id not in all_dependencies]

        # Filter roots: only show trees that contain at least one open issue
        filtered_roots = []
        for issue_id in root_ids:
            issue = graph[issue_id]
            if has_open_issues(issue):
                filtered_roots.append(issue_id)

        # Render each root issue tree
        console.print("[bold]═" * 50 + "[/bold]")
        console.print("[bold]OPEN ISSUES WITH DEPENDENCY TREES[/bold]")
        console.print("[bold]═" * 50 + "[/bold]\n")

        for issue_id in filtered_roots:
            tree = render_issue_tree(graph[issue_id], graph)
            console.print(tree)
            console.print()

        return 0

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error running bd command: {e}[/red]", stderr=True)
        return 1
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]", stderr=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
