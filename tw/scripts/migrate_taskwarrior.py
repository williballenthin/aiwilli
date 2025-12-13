#!/usr/bin/env python3
"""Migrate issues from TaskWarrior to tw SQLite database.

This script reads tw-formatted issues from TaskWarrior and imports them into
the new SQLite-based tw database. It does NOT delete any data from TaskWarrior.
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

from tw.backend import SqliteBackend
from tw.models import Annotation, AnnotationType, Issue, IssueStatus, IssueType

console = Console(stderr=True)
logger = logging.getLogger(__name__)


def parse_annotation(entry: str, description: str) -> Annotation:
    """Parse TaskWarrior annotation into Annotation object."""
    timestamp = datetime.strptime(entry, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)

    match = re.match(r"^\[([a-z-]+)\]\s*(.*)$", description, re.DOTALL)
    if match:
        type_str, message = match.groups()
        try:
            ann_type = AnnotationType(type_str)
        except ValueError:
            ann_type = AnnotationType.COMMENT
    else:
        ann_type = AnnotationType.COMMENT
        message = description

    return Annotation(type=ann_type, timestamp=timestamp, message=message)


def parse_taskwarrior_issue(item: dict) -> Issue | None:
    """Parse a TaskWarrior export item into an Issue."""
    if "tw_id" not in item:
        return None
    if item.get("status") == "deleted":
        return None

    try:
        issue_type = IssueType(item["tw_type"])
    except (KeyError, ValueError) as e:
        logger.warning(f"Invalid tw_type for {item.get('tw_id')}: {e}")
        return None

    try:
        issue_status = IssueStatus(item["tw_status"])
    except (KeyError, ValueError) as e:
        logger.warning(f"Invalid tw_status for {item.get('tw_id')}: {e}")
        return None

    annotations = []
    for ann_data in item.get("annotations", []):
        try:
            ann = parse_annotation(ann_data["entry"], ann_data["description"])
            annotations.append(ann)
        except (KeyError, ValueError) as e:
            logger.warning(f"Failed to parse annotation for {item['tw_id']}: {e}")

    tw_refs_str = item.get("tw_refs", "")
    tw_refs = [r.strip() for r in tw_refs_str.split(",") if r.strip()]

    created_str = item.get("entry", "")
    created_at = (
        datetime.strptime(created_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if created_str
        else datetime.now(timezone.utc)
    )

    modified_str = item.get("modified", "")
    updated_at = (
        datetime.strptime(modified_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        if modified_str
        else created_at
    )

    return Issue(
        id=item["tw_id"],
        type=issue_type,
        title=item["description"],
        status=issue_status,
        created_at=created_at,
        updated_at=updated_at,
        parent=item.get("tw_parent"),
        body=item.get("tw_body"),
        refs=tw_refs,
        annotations=annotations,
    )


def export_taskwarrior_project(project: str) -> list[dict]:
    """Export all tasks from a TaskWarrior project."""
    cmd = ["task", "rc.confirmation=off", "rc.verbose=nothing", f"project:{project}", "export"]
    logger.debug(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and "No matches" not in result.stderr:
        logger.error(f"task export failed: {result.stderr}")
        raise RuntimeError(f"task export failed: {result.stderr}")

    output = result.stdout.strip()
    if not output or output == "[]":
        return []

    return json.loads(output)


def get_taskwarrior_projects() -> set[str]:
    """Get all unique projects with tw_id from TaskWarrior."""
    cmd = ["task", "rc.verbose=nothing", "export"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"task export failed: {result.stderr}")

    data = json.loads(result.stdout)
    projects = set()
    for item in data:
        if "tw_id" in item and item.get("project"):
            projects.add(item["project"])
    return projects


def migrate_project(
    backend: SqliteBackend,
    source_project: str,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Migrate a single project from TaskWarrior to SQLite.

    Args:
        backend: SQLite backend instance
        source_project: TaskWarrior project name to read from

    Returns:
        Tuple of (imported_count, skipped_count)
    """
    logger.info(f"Migrating project: {source_project}")

    items = export_taskwarrior_project(source_project)
    logger.info(f"Found {len(items)} tasks in TaskWarrior project '{source_project}'")

    imported = 0
    skipped = 0

    for item in items:
        issue = parse_taskwarrior_issue(item)
        if issue is None:
            skipped += 1
            continue

        if dry_run:
            logger.info(f"[DRY RUN] Would import: {issue.id} - {issue.title}")
        else:
            existing = backend.get_issue(issue.id)
            if existing:
                logger.debug(f"Issue {issue.id} already exists, skipping")
                skipped += 1
                continue

            backend.save_issue(issue)
            logger.debug(f"Imported: {issue.id}")

        imported += 1

    return imported, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate issues from TaskWarrior to tw SQLite database"
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        help="Path to SQLite database (default: $TW_DB_PATH)",
    )
    parser.add_argument(
        "--source-project",
        help="Specific TaskWarrior project to migrate (default: all projects with tw_id)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without making changes",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_time=False, show_path=False)],
    )

    db_path = args.db_path
    if db_path is None:
        import os
        db_path_str = os.environ.get("TW_DB_PATH")
        if not db_path_str:
            console.print("[red]Error: TW_DB_PATH not set and --db-path not provided[/red]")
            return 1
        db_path = Path(db_path_str)

    if args.dry_run:
        console.print("[yellow]DRY RUN MODE - No changes will be made[/yellow]")
        backend = None
    else:
        backend = SqliteBackend(db_path)
        console.print(f"Using database: {db_path}")

    if args.source_project:
        source_projects = {args.source_project}
    else:
        source_projects = get_taskwarrior_projects()
        console.print(f"Found {len(source_projects)} projects with tw_id: {', '.join(sorted(source_projects))}")

    total_imported = 0
    total_skipped = 0

    for source_project in sorted(source_projects):
        if backend is None and not args.dry_run:
            continue

        if args.dry_run:
            items = export_taskwarrior_project(source_project)
            for item in items:
                issue = parse_taskwarrior_issue(item)
                if issue:
                    console.print(f"[dim]{source_project}[/dim] {issue.id}: {issue.title[:60]}")
                    total_imported += 1
                else:
                    total_skipped += 1
        else:
            imported, skipped = migrate_project(backend, source_project)
            total_imported += imported
            total_skipped += skipped

    console.print()
    console.print(f"[green]Migration complete![/green]")
    console.print(f"  Imported: {total_imported}")
    console.print(f"  Skipped: {total_skipped} (deleted or already exist)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
