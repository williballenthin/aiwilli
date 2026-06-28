from __future__ import annotations

import datetime as dt_mod
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DOC_MIME_TYPE = "application/vnd.google-apps.document"
SLIDES_MIME_TYPE = "application/vnd.google-apps.presentation"
SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
DEFAULT_MIME_TYPES: tuple[str, ...] = (
    DOC_MIME_TYPE,
    SLIDES_MIME_TYPE,
    SHEETS_MIME_TYPE,
)

DRIVE_FILE_FIELDS = (
    "files(id,name,mimeType,webViewLink,"
    "createdTime,modifiedTime,modifiedByMeTime,viewedByMeTime,"
    "owners(emailAddress,me),lastModifyingUser(emailAddress,me)),"
    "nextPageToken"
)

STATUS_ORDER: tuple[str, ...] = ("created", "modified", "viewed")
ENTRY_LINE_RE = re.compile(
    r"^- \[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)"
    r" — (?P<statuses>[a-z, ]+)"
    r"(?: <!-- weave:drive:id=(?P<file_id>[^ ]+) mime=(?P<mime>[^ ]+) -->)?$"
)


@dataclass(frozen=True)
class DriveEntry:
    file_id: str
    label: str
    url: str
    mime_type: str
    statuses: frozenset[str]

    def merged_with(self, other: DriveEntry) -> DriveEntry:
        return DriveEntry(
            file_id=self.file_id,
            label=other.label or self.label,
            url=other.url or self.url,
            mime_type=other.mime_type or self.mime_type,
            statuses=self.statuses | other.statuses,
        )


class DriveFilesClient(Protocol):
    def list_recent_files(
        self,
        since: dt_mod.datetime,
        mime_types: Iterable[str],
    ) -> Iterator[dict[str, Any]]:
        """Yield file resources touched since the given timestamp."""


class GoogleDriveFilesClient:
    def __init__(self, credentials: object, page_size: int = 200):
        from googleapiclient.discovery import build

        self.service = build("drive", "v3", credentials=credentials)
        self.page_size = page_size

    def list_recent_files(
        self,
        since: dt_mod.datetime,
        mime_types: Iterable[str],
    ) -> Iterator[dict[str, Any]]:
        query = build_drive_query(since=since, mime_types=mime_types)
        page_token: str | None = None
        while True:
            response = (
                self.service.files()
                .list(
                    q=query,
                    pageSize=self.page_size,
                    fields=DRIVE_FILE_FIELDS,
                    pageToken=page_token,
                    spaces="drive",
                    corpora="user",
                    includeItemsFromAllDrives=False,
                    supportsAllDrives=False,
                    orderBy="modifiedByMeTime desc",
                )
                .execute()
            )
            for item in response.get("files", []) or []:
                if isinstance(item, dict):
                    yield item
            page_token = response.get("nextPageToken")
            if not page_token:
                return


def format_drive_timestamp(value: dt_mod.datetime) -> str:
    return value.astimezone(dt_mod.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_drive_query(since: dt_mod.datetime, mime_types: Iterable[str]) -> str:
    timestamp = format_drive_timestamp(since)
    mime_clause = " or ".join(f"mimeType = '{mime}'" for mime in mime_types)
    time_clause = (
        f"(viewedByMeTime > '{timestamp}'"
        f" or modifiedTime > '{timestamp}'"
        f" or (createdTime > '{timestamp}' and 'me' in owners))"
    )
    return f"trashed = false and ({mime_clause}) and {time_clause}"


def parse_rfc3339(value: str | None) -> dt_mod.datetime | None:
    if not value:
        return None
    text = value.rstrip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return dt_mod.datetime.fromisoformat(text)
    except ValueError:
        logger.debug("could not parse RFC3339 timestamp %r", value)
        return None


def is_self_owner(file_resource: dict[str, Any]) -> bool:
    owners = file_resource.get("owners")
    if not isinstance(owners, list):
        return False
    for owner in owners:
        if isinstance(owner, dict) and owner.get("me") is True:
            return True
    return False


def is_self_modifier(file_resource: dict[str, Any]) -> bool:
    modifier = file_resource.get("lastModifyingUser")
    if not isinstance(modifier, dict):
        return False
    return modifier.get("me") is True


def classify_entries(
    file_resource: dict[str, Any],
    eligible_days: Iterable[dt_mod.date],
    tz: dt_mod.tzinfo,
) -> list[tuple[dt_mod.date, str]]:
    """Return (day, status) tuples for each eligible day this file activity touches."""
    eligible_set = set(eligible_days)
    if not eligible_set:
        return []
    out: list[tuple[dt_mod.date, str]] = []

    created_at = parse_rfc3339(file_resource.get("createdTime"))
    modified_by_me_at = parse_rfc3339(file_resource.get("modifiedByMeTime"))
    viewed_by_me_at = parse_rfc3339(file_resource.get("viewedByMeTime"))

    if created_at is not None and is_self_owner(file_resource):
        created_day = created_at.astimezone(tz).date()
        if created_day in eligible_set:
            out.append((created_day, "created"))

    if modified_by_me_at is not None:
        modified_day = modified_by_me_at.astimezone(tz).date()
        if modified_day in eligible_set:
            out.append((modified_day, "modified"))

    if viewed_by_me_at is not None:
        viewed_day = viewed_by_me_at.astimezone(tz).date()
        if viewed_day in eligible_set:
            out.append((viewed_day, "viewed"))

    return out


def build_entry(file_resource: dict[str, Any], status: str) -> DriveEntry | None:
    file_id = file_resource.get("id")
    if not isinstance(file_id, str) or not file_id:
        return None
    label = file_resource.get("name") if isinstance(file_resource.get("name"), str) else ""
    url = file_resource.get("webViewLink")
    if not isinstance(url, str) or not url:
        url = derive_web_view_link(file_id, file_resource.get("mimeType"))
    raw_mime = file_resource.get("mimeType")
    mime_type = raw_mime if isinstance(raw_mime, str) else ""
    return DriveEntry(
        file_id=file_id,
        label=(label or "untitled").strip() or "untitled",
        url=url,
        mime_type=mime_type or "",
        statuses=frozenset({status}),
    )


def derive_web_view_link(file_id: str, mime_type: str | None) -> str:
    if mime_type == DOC_MIME_TYPE:
        return f"https://docs.google.com/document/d/{file_id}"
    if mime_type == SLIDES_MIME_TYPE:
        return f"https://docs.google.com/presentation/d/{file_id}"
    if mime_type == SHEETS_MIME_TYPE:
        return f"https://docs.google.com/spreadsheets/d/{file_id}"
    return f"https://drive.google.com/file/d/{file_id}"


def merge_entries(entries: Iterable[DriveEntry]) -> dict[str, DriveEntry]:
    """Collapse multiple entries per file_id into one, unioning statuses."""
    result: dict[str, DriveEntry] = {}
    for entry in entries:
        existing = result.get(entry.file_id)
        if existing is None:
            result[entry.file_id] = entry
        else:
            result[entry.file_id] = existing.merged_with(entry)
    return result


def render_status_list(statuses: Iterable[str]) -> str:
    available = set(statuses)
    ordered = [status for status in STATUS_ORDER if status in available]
    return ", ".join(ordered)


def render_entry_line(entry: DriveEntry) -> str:
    safe_label = entry.label.replace("[", "(").replace("]", ")")
    statuses_text = render_status_list(entry.statuses)
    line = f"- [{safe_label}]({entry.url}) — {statuses_text}"
    if entry.file_id and entry.mime_type:
        line = f"{line} <!-- weave:drive:id={entry.file_id} mime={entry.mime_type} -->"
    return line


def render_activity_body(entries: Iterable[DriveEntry]) -> str:
    merged = merge_entries(entries)
    if not merged:
        return ""
    ordered = sorted(merged.values(), key=lambda e: e.label.casefold())
    return "\n".join(render_entry_line(entry) for entry in ordered)


def parse_snapshot_entries(content: str) -> list[DriveEntry]:
    """Recover DriveEntry records from a previously rendered snapshot body."""
    entries: list[DriveEntry] = []
    for line in content.splitlines():
        stripped = line.rstrip()
        if not stripped:
            continue
        match = ENTRY_LINE_RE.match(stripped)
        if match is None:
            continue
        file_id = match.group("file_id")
        if not file_id:
            continue
        statuses = frozenset(
            piece.strip()
            for piece in match.group("statuses").split(",")
            if piece.strip() in STATUS_ORDER
        )
        if not statuses:
            continue
        entries.append(
            DriveEntry(
                file_id=file_id,
                label=match.group("label"),
                url=match.group("url"),
                mime_type=match.group("mime") or "",
                statuses=statuses,
            )
        )
    return entries


def collect_day_entries(
    files: Iterable[dict[str, Any]],
    eligible_days: Iterable[dt_mod.date],
    tz: dt_mod.tzinfo,
) -> dict[dt_mod.date, list[DriveEntry]]:
    """Bucket file resources into per-day DriveEntry lists."""
    eligible_set = set(eligible_days)
    by_day: dict[dt_mod.date, list[DriveEntry]] = {day: [] for day in eligible_set}
    for resource in files:
        for day, status in classify_entries(resource, eligible_set, tz):
            entry = build_entry(resource, status)
            if entry is not None:
                by_day[day].append(entry)
    return by_day
