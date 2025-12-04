"""ID parsing and sorting utilities."""

import re
from dataclasses import dataclass


@dataclass
class ParsedId:
    """Parsed components of a tw_id."""

    prefix: str
    epic_num: int
    story_num: int | None = None
    task_suffix: str | None = None


def parse_id(tw_id: str) -> ParsedId:
    """Parse a tw_id into its components.

    Raises:
        ValueError: If the ID format is invalid.
    """
    pattern = r"^([A-Z]+)-(\d+)(?:-(\d+)([a-z]+)?)?$"
    match = re.match(pattern, tw_id)
    if not match:
        raise ValueError(f"Invalid tw_id format: {tw_id}")

    prefix, epic_str, story_str, task_suffix = match.groups()
    return ParsedId(
        prefix=prefix,
        epic_num=int(epic_str),
        story_num=int(story_str) if story_str else None,
        task_suffix=task_suffix,
    )


def parse_id_sort_key(tw_id: str) -> tuple[str, int, int, int, str]:
    """Return a sortable key for a tw_id.

    Sort order:
    1. By prefix (alphabetically)
    2. By epic number (numerically)
    3. By story number (numerically, 0 if none)
    4. By task suffix length (shorter first)
    5. By task suffix (alphabetically)
    """
    parsed = parse_id(tw_id)
    return (
        parsed.prefix,
        parsed.epic_num,
        parsed.story_num or 0,
        len(parsed.task_suffix) if parsed.task_suffix else 0,
        parsed.task_suffix or "",
    )


def sort_ids(ids: list[str]) -> list[str]:
    """Sort a list of tw_ids in logical order."""
    return sorted(ids, key=parse_id_sort_key)


def _int_to_task_suffix(n: int) -> str:
    """Convert 0-based integer to task suffix (a, b, ..., z, aa, ab, ...)."""
    if n < 26:
        return chr(ord("a") + n)
    result = ""
    while n >= 0:
        result = chr(ord("a") + (n % 26)) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


def _get_max_epic_num(prefix: str, existing_ids: list[str]) -> int:
    """Find the maximum epic number in use (including reserved by orphans)."""
    max_num = 0
    for tw_id in existing_ids:
        try:
            parsed = parse_id(tw_id)
            if parsed.prefix == prefix:
                max_num = max(max_num, parsed.epic_num)
        except ValueError:
            continue
    return max_num


def generate_next_epic_id(prefix: str, existing_ids: list[str]) -> str:
    """Generate the next available epic ID."""
    max_num = _get_max_epic_num(prefix, existing_ids)
    return f"{prefix}-{max_num + 1}"


def generate_next_story_id(
    parent_id: str | None,
    existing_ids: list[str],
    prefix: str | None = None,
) -> str:
    """Generate the next available story ID.

    Args:
        parent_id: The parent epic's tw_id, or None for orphan
        existing_ids: All existing tw_ids in the project
        prefix: Required if parent_id is None
    """
    if parent_id is None:
        if prefix is None:
            raise ValueError("prefix required for orphan story")
        max_epic = _get_max_epic_num(prefix, existing_ids)
        return f"{prefix}-{max_epic + 1}"

    parsed_parent = parse_id(parent_id)
    prefix = parsed_parent.prefix
    epic_num = parsed_parent.epic_num

    max_story = 0
    for tw_id in existing_ids:
        try:
            parsed = parse_id(tw_id)
            if (
                parsed.prefix == prefix
                and parsed.epic_num == epic_num
                and parsed.story_num is not None
            ):
                max_story = max(max_story, parsed.story_num)
        except ValueError:
            continue

    return f"{prefix}-{epic_num}-{max_story + 1}"


def generate_next_task_id(
    parent_id: str | None,
    existing_ids: list[str],
    prefix: str | None = None,
) -> str:
    """Generate the next available task ID.

    Args:
        parent_id: The parent story's tw_id, or None for orphan
        existing_ids: All existing tw_ids in the project
        prefix: Required if parent_id is None
    """
    if parent_id is None:
        if prefix is None:
            raise ValueError("prefix required for orphan task")
        max_epic = _get_max_epic_num(prefix, existing_ids)
        return f"{prefix}-{max_epic + 1}"

    parsed_parent = parse_id(parent_id)
    prefix = parsed_parent.prefix
    epic_num = parsed_parent.epic_num
    story_num = parsed_parent.story_num

    if story_num is None:
        max_child = 0
        for tw_id in existing_ids:
            try:
                parsed = parse_id(tw_id)
                if (
                    parsed.prefix == prefix
                    and parsed.epic_num == epic_num
                    and parsed.story_num is not None
                    and parsed.task_suffix is None
                ):
                    max_child = max(max_child, parsed.story_num)
            except ValueError:
                continue

        return f"{prefix}-{epic_num}-{max_child + 1}"

    existing_suffixes: list[str] = []
    for tw_id in existing_ids:
        try:
            parsed = parse_id(tw_id)
            if (
                parsed.prefix == prefix
                and parsed.epic_num == epic_num
                and parsed.story_num == story_num
                and parsed.task_suffix is not None
            ):
                existing_suffixes.append(parsed.task_suffix)
        except ValueError:
            continue

    if not existing_suffixes:
        next_suffix = "a"
    else:
        sorted_suffixes = sorted(existing_suffixes, key=lambda s: (len(s), s))
        max_suffix = sorted_suffixes[-1]
        if all(c == "z" for c in max_suffix):
            next_suffix = "a" * (len(max_suffix) + 1)
        elif max_suffix[-1] == "z":
            next_suffix = max_suffix[:-1][:-1] + chr(ord(max_suffix[:-1][-1]) + 1) + "a"
        else:
            next_suffix = max_suffix[:-1] + chr(ord(max_suffix[-1]) + 1)

    return f"{prefix}-{epic_num}-{story_num}{next_suffix}"
