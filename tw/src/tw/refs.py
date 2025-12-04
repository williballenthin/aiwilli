"""References extraction utilities."""

import re

from tw.ids import sort_ids


def extract_refs(text: str, prefix: str) -> list[str]:
    """Extract and sort tw_id references from text.

    Args:
        text: The text to scan for references
        prefix: The project prefix to match (e.g., "PROJ")

    Returns:
        Sorted, deduplicated list of referenced tw_ids
    """
    pattern = rf"\b({re.escape(prefix)}-\d+(?:-\d+[a-z]*)?)\b"
    matches = re.findall(pattern, text)
    unique = list(set(matches))
    return sort_ids(unique)
