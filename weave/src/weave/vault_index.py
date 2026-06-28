from __future__ import annotations

import datetime as dt_mod
import json
import logging
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_DIRNAMES: frozenset[str] = frozenset(
    {
        "daily",
        "sink",
        "_weave",
        "_attachments",
    }
)
DEFAULT_EXCLUDE_AT_ROOT: frozenset[str] = frozenset({"daily", "sink"})


@dataclass(frozen=True)
class VaultFileStats:
    path: Path
    created_at: dt_mod.datetime
    modified_at: dt_mod.datetime


@dataclass(frozen=True)
class VaultActivityEntry:
    path: Path
    relative_path: Path
    status: str
    label: str
    summary: str


def _front_matter_field(content: str, field: str) -> str:
    match = re.match(r"\A---\n(?P<front>.*?)\n---", content, re.DOTALL)
    if match is None:
        return ""
    pattern = re.compile(rf"^{re.escape(field)}\s*:\s*(?P<value>.*)$", re.MULTILINE)
    field_match = pattern.search(match.group("front"))
    if field_match is None:
        return ""
    raw = field_match.group("value").strip()
    if not raw:
        return ""
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip('"').strip()
        if isinstance(parsed, str):
            return parsed.strip()
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1].replace("''", "'").strip()
    return raw


def get_created_at(stat_result: os.stat_result) -> float:
    """Get best-effort creation timestamp from a stat result.

    Uses st_birthtime when the platform/filesystem exposes it (macOS always;
    Linux 4.11+ ext4/btrfs/xfs via statx, surfaced by Python 3.12+). Falls
    back to st_ctime, which on Unix is the inode-change time and can bump on
    chmod/rename — so the "created" tag is best-effort on those filesystems.
    """
    birthtime = getattr(stat_result, "st_birthtime", None)
    if birthtime is not None:
        return float(birthtime)
    return float(stat_result.st_ctime)


def _is_excluded_dir(name: str, parent_relative: Path, exclude_at_root: Iterable[str]) -> bool:
    if name.startswith("."):
        return True
    if name in DEFAULT_EXCLUDE_DIRNAMES:
        return True
    if parent_relative == Path(".") and name in exclude_at_root:
        return True
    return False


def iter_markdown_files(
    vault_root: Path,
    exclude_at_root: Iterable[str] = DEFAULT_EXCLUDE_AT_ROOT,
) -> Iterator[Path]:
    """Yield every `.md` file under vault_root, skipping excluded subtrees."""
    exclude_at_root = frozenset(exclude_at_root)
    stack: list[Path] = [vault_root]
    while stack:
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError as exc:
            logger.debug("scandir failed for %s: %s", current, exc)
            continue
        with iterator:
            for entry in iterator:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        relative_parent = Path(entry.path).parent.relative_to(vault_root)
                        if _is_excluded_dir(entry.name, relative_parent, exclude_at_root):
                            continue
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    if not entry.name.endswith(".md"):
                        continue
                    yield Path(entry.path)
                except OSError as exc:
                    logger.debug("scan entry failed for %s: %s", entry.path, exc)


def stat_file(path: Path, tz: dt_mod.tzinfo) -> VaultFileStats | None:
    try:
        stat_result = path.stat()
    except OSError as exc:
        logger.debug("stat failed for %s: %s", path, exc)
        return None
    created_ts = get_created_at(stat_result)
    modified_ts = float(stat_result.st_mtime)
    created_at = dt_mod.datetime.fromtimestamp(created_ts, tz=tz)
    modified_at = dt_mod.datetime.fromtimestamp(modified_ts, tz=tz)
    return VaultFileStats(path=path, created_at=created_at, modified_at=modified_at)


def get_entry_label(path: Path, content: str | None) -> str:
    if content is not None:
        title = _front_matter_field(content, "title")
        if title:
            return title
    return path.stem


def get_entry_summary(content: str | None) -> str:
    if content is None:
        return ""
    return _front_matter_field(content, "summary")


def build_entry(
    vault_root: Path,
    path: Path,
    status: str,
) -> VaultActivityEntry | None:
    try:
        content: str | None = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("read failed for %s: %s", path, exc)
        content = None
    try:
        relative = path.relative_to(vault_root)
    except ValueError:
        relative = path
    label = get_entry_label(path, content)
    summary = get_entry_summary(content)
    return VaultActivityEntry(
        path=path,
        relative_path=relative,
        status=status,
        label=label,
        summary=summary,
    )


def render_entry_line(entry: VaultActivityEntry) -> str:
    link_target = entry.relative_path.with_suffix("").as_posix()
    line = f"- {entry.status}: [[{link_target}]]"
    if entry.summary:
        line = f"{line} — {entry.summary}"
    return line


def render_activity_body(entries: list[VaultActivityEntry]) -> str:
    if not entries:
        return ""
    created = sorted(
        (entry for entry in entries if entry.status == "created"),
        key=lambda entry: entry.relative_path.as_posix().casefold(),
    )
    modified = sorted(
        (entry for entry in entries if entry.status == "modified"),
        key=lambda entry: entry.relative_path.as_posix().casefold(),
    )
    lines = [render_entry_line(entry) for entry in created]
    lines.extend(render_entry_line(entry) for entry in modified)
    return "\n".join(lines)


def collect_day_entries(
    vault_root: Path,
    eligible_days: Iterable[dt_mod.date],
    tz: dt_mod.tzinfo,
    exclude_at_root: Iterable[str] = DEFAULT_EXCLUDE_AT_ROOT,
) -> dict[dt_mod.date, list[VaultActivityEntry]]:
    """Walk the vault once and bucket files by day-of-event."""
    eligible_set = set(eligible_days)
    if not eligible_set:
        return {}
    by_day: dict[dt_mod.date, list[VaultActivityEntry]] = {day: [] for day in eligible_set}
    for path in iter_markdown_files(vault_root, exclude_at_root=exclude_at_root):
        stats = stat_file(path, tz=tz)
        if stats is None:
            continue
        created_day = stats.created_at.date()
        modified_day = stats.modified_at.date()
        if created_day in eligible_set:
            entry = build_entry(vault_root, path, "created")
            if entry is not None:
                by_day[created_day].append(entry)
        if modified_day != created_day and modified_day in eligible_set:
            entry = build_entry(vault_root, path, "modified")
            if entry is not None:
                by_day[modified_day].append(entry)
    return by_day
