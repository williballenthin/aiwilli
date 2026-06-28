from __future__ import annotations

import datetime as dt_mod
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from weave.app import DailyNoteWriter, DriveActivitySyncer
from weave.drive_activity import (
    DOC_MIME_TYPE,
    SHEETS_MIME_TYPE,
    SLIDES_MIME_TYPE,
    DriveEntry,
    build_drive_query,
    classify_entries,
    collect_day_entries,
    derive_web_view_link,
    merge_entries,
    parse_rfc3339,
    parse_snapshot_entries,
    render_activity_body,
    render_entry_line,
)


class FakeDriveClient:
    def __init__(self, files_by_call: list[list[dict[str, Any]]]):
        self.files_by_call = list(files_by_call)
        self.calls: list[dict[str, Any]] = []

    def list_recent_files(
        self,
        since: datetime,
        mime_types: Iterable[str],
    ) -> Iterator[dict[str, Any]]:
        self.calls.append({"since": since, "mime_types": tuple(mime_types)})
        if not self.files_by_call:
            return iter([])
        return iter(self.files_by_call.pop(0))


def _build_writer(tmp_path: Path) -> DailyNoteWriter:
    config_dir = tmp_path / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    return DailyNoteWriter(vault_root=tmp_path)


def _doc(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "doc1",
        "name": "Project Notes",
        "mimeType": DOC_MIME_TYPE,
        "webViewLink": "https://docs.google.com/document/d/doc1/edit",
        "createdTime": "2026-05-08T10:00:00.000Z",
        "modifiedTime": "2026-05-10T14:00:00.000Z",
        "modifiedByMeTime": "2026-05-10T14:00:00.000Z",
        "viewedByMeTime": "2026-05-10T16:00:00.000Z",
        "owners": [{"emailAddress": "me@example.com", "me": True}],
        "lastModifyingUser": {"emailAddress": "me@example.com", "me": True},
    }
    base.update(overrides)
    return base


def test_parse_rfc3339_handles_zulu_suffix() -> None:
    parsed = parse_rfc3339("2026-05-10T14:00:00.000Z")
    assert parsed == datetime(2026, 5, 10, 14, 0, tzinfo=UTC)


def test_parse_rfc3339_returns_none_for_empty() -> None:
    assert parse_rfc3339(None) is None
    assert parse_rfc3339("") is None


def test_build_drive_query_includes_three_time_clauses_and_mimes() -> None:
    since = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
    query = build_drive_query(since=since, mime_types=[DOC_MIME_TYPE, SLIDES_MIME_TYPE])
    assert "trashed = false" in query
    assert "mimeType = 'application/vnd.google-apps.document'" in query
    assert "mimeType = 'application/vnd.google-apps.presentation'" in query
    assert "viewedByMeTime > '2026-05-10T00:00:00Z'" in query
    assert "modifiedTime > '2026-05-10T00:00:00Z'" in query
    assert "createdTime > '2026-05-10T00:00:00Z'" in query
    assert "'me' in owners" in query


def test_derive_web_view_link_matches_mime_type() -> None:
    assert "document/d/" in derive_web_view_link("foo", DOC_MIME_TYPE)
    assert "presentation/d/" in derive_web_view_link("foo", SLIDES_MIME_TYPE)
    assert "spreadsheets/d/" in derive_web_view_link("foo", SHEETS_MIME_TYPE)
    assert "drive.google.com/file/d/foo" in derive_web_view_link("foo", None)


def test_classify_entries_emits_created_modified_viewed_for_owner() -> None:
    file_resource = _doc(
        createdTime="2026-05-10T08:00:00Z",
        modifiedByMeTime="2026-05-10T09:00:00Z",
        viewedByMeTime="2026-05-10T10:00:00Z",
    )
    classification = classify_entries(
        file_resource,
        eligible_days=[dt_mod.date(2026, 5, 10)],
        tz=UTC,
    )
    assert set(classification) == {
        (dt_mod.date(2026, 5, 10), "created"),
        (dt_mod.date(2026, 5, 10), "modified"),
        (dt_mod.date(2026, 5, 10), "viewed"),
    }


def test_classify_entries_skips_created_for_non_owner() -> None:
    file_resource = _doc(
        owners=[{"emailAddress": "alice@example.com", "me": False}],
        createdTime="2026-05-10T08:00:00Z",
        modifiedByMeTime="2026-05-10T09:00:00Z",
        viewedByMeTime="2026-05-10T10:00:00Z",
    )
    classification = classify_entries(
        file_resource,
        eligible_days=[dt_mod.date(2026, 5, 10)],
        tz=UTC,
    )
    assert (dt_mod.date(2026, 5, 10), "created") not in classification
    assert (dt_mod.date(2026, 5, 10), "modified") in classification
    assert (dt_mod.date(2026, 5, 10), "viewed") in classification


def test_classify_entries_buckets_signals_to_local_day() -> None:
    file_resource = _doc(
        # 03:00 UTC May 11 == 23:00 May 10 in America/New_York.
        viewedByMeTime="2026-05-11T03:00:00Z",
        modifiedByMeTime="2026-05-10T16:00:00Z",
        createdTime="2026-05-09T16:00:00Z",
    )
    from zoneinfo import ZoneInfo

    ny = ZoneInfo("America/New_York")
    classification = classify_entries(
        file_resource,
        eligible_days=[dt_mod.date(2026, 5, 9), dt_mod.date(2026, 5, 10)],
        tz=ny,
    )
    assert (dt_mod.date(2026, 5, 9), "created") in classification
    assert (dt_mod.date(2026, 5, 10), "modified") in classification
    assert (dt_mod.date(2026, 5, 10), "viewed") in classification


def test_merge_entries_unions_statuses_per_file_id() -> None:
    e1 = DriveEntry(
        file_id="x", label="X", url="https://example/x",
        mime_type=DOC_MIME_TYPE, statuses=frozenset({"created"}),
    )
    e2 = DriveEntry(
        file_id="x", label="X", url="https://example/x",
        mime_type=DOC_MIME_TYPE, statuses=frozenset({"viewed"}),
    )
    merged = merge_entries([e1, e2])
    assert set(merged["x"].statuses) == {"created", "viewed"}


def test_render_entry_line_includes_statuses_and_marker() -> None:
    entry = DriveEntry(
        file_id="abc123",
        label="My Doc",
        url="https://docs.google.com/document/d/abc123",
        mime_type=DOC_MIME_TYPE,
        statuses=frozenset({"viewed", "modified", "created"}),
    )
    line = render_entry_line(entry)
    assert line.startswith("- [My Doc](https://docs.google.com/document/d/abc123)")
    assert "created, modified, viewed" in line
    assert "weave:drive:id=abc123" in line
    assert f"mime={DOC_MIME_TYPE}" in line


def test_render_activity_body_sorts_case_insensitively() -> None:
    entries = [
        DriveEntry(
            file_id="b", label="bravo", url="https://example/b",
            mime_type=DOC_MIME_TYPE, statuses=frozenset({"modified"}),
        ),
        DriveEntry(
            file_id="a", label="Alpha", url="https://example/a",
            mime_type=DOC_MIME_TYPE, statuses=frozenset({"created"}),
        ),
    ]
    body = render_activity_body(entries)
    lines = body.splitlines()
    assert "Alpha" in lines[0]
    assert "bravo" in lines[1]


def test_parse_snapshot_entries_round_trips_marker() -> None:
    entries = [
        DriveEntry(
            file_id="id1", label="Title One",
            url="https://docs.google.com/document/d/id1",
            mime_type=DOC_MIME_TYPE, statuses=frozenset({"viewed"}),
        ),
        DriveEntry(
            file_id="id2", label="Slides Two",
            url="https://docs.google.com/presentation/d/id2",
            mime_type=SLIDES_MIME_TYPE, statuses=frozenset({"created", "modified"}),
        ),
    ]
    body = render_activity_body(entries)
    parsed = parse_snapshot_entries(body)
    by_id = {entry.file_id: entry for entry in parsed}
    assert set(by_id["id1"].statuses) == {"viewed"}
    assert set(by_id["id2"].statuses) == {"created", "modified"}
    assert by_id["id2"].url.endswith("/id2")


def test_collect_day_entries_buckets_into_days() -> None:
    resource = _doc(
        createdTime="2026-05-09T10:00:00Z",
        modifiedByMeTime="2026-05-10T11:00:00Z",
        viewedByMeTime="2026-05-11T12:00:00Z",
    )
    days = [
        dt_mod.date(2026, 5, 9),
        dt_mod.date(2026, 5, 10),
        dt_mod.date(2026, 5, 11),
    ]
    bucketed = collect_day_entries(files=[resource], eligible_days=days, tz=UTC)
    assert {entry.statuses for entry in bucketed[days[0]]} == {frozenset({"created"})}
    assert {entry.statuses for entry in bucketed[days[1]]} == {frozenset({"modified"})}
    assert {entry.statuses for entry in bucketed[days[2]]} == {frozenset({"viewed"})}


def test_syncer_writes_snapshot_for_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    writer = _build_writer(tmp_path)
    client = FakeDriveClient(
        files_by_call=[
            [
                _doc(
                    id="doc-today",
                    name="Today doc",
                    createdTime="2026-05-15T08:00:00Z",
                    modifiedByMeTime="2026-05-15T09:00:00Z",
                    viewedByMeTime="2026-05-15T10:00:00Z",
                )
            ]
        ]
    )
    syncer = DriveActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=1,
        client=client,
    )
    count = syncer.run_once(now=datetime(2026, 5, 15, 12, 0, tzinfo=UTC))
    assert count == 1

    snapshot = (
        tmp_path
        / "daily" / "2026" / "05" / "15"
        / "_weave" / "google workspace activity.md"
    )
    assert snapshot.exists()
    content = snapshot.read_text()
    assert "Today doc" in content
    assert "created, modified, viewed" in content


def test_syncer_merges_with_existing_snapshot_to_preserve_view_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A doc viewed Monday should stay in Monday's snapshot even after Drive
    overwrites viewedByMeTime to Tuesday."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    writer = _build_writer(tmp_path)
    monday = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    tuesday = datetime(2026, 5, 12, 12, 0, tzinfo=UTC)

    monday_client = FakeDriveClient(
        files_by_call=[
            [
                _doc(
                    id="reading",
                    name="Spec",
                    owners=[{"emailAddress": "alice@example.com", "me": False}],
                    createdTime="2026-05-01T00:00:00Z",
                    modifiedByMeTime="2026-05-01T00:00:00Z",
                    viewedByMeTime="2026-05-11T10:00:00Z",
                    lastModifyingUser={"emailAddress": "alice@example.com", "me": False},
                )
            ]
        ]
    )
    syncer = DriveActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=2,
        client=monday_client,
    )
    syncer.run_once(now=monday)

    # On Tuesday, Drive reports the same doc but viewedByMeTime is now Tuesday.
    # The Monday snapshot must still list "Spec" as viewed.
    tuesday_client = FakeDriveClient(
        files_by_call=[
            [
                _doc(
                    id="reading",
                    name="Spec",
                    owners=[{"emailAddress": "alice@example.com", "me": False}],
                    createdTime="2026-05-01T00:00:00Z",
                    modifiedByMeTime="2026-05-01T00:00:00Z",
                    viewedByMeTime="2026-05-12T09:00:00Z",
                    lastModifyingUser={"emailAddress": "alice@example.com", "me": False},
                )
            ]
        ]
    )
    syncer_tuesday = DriveActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=2,
        client=tuesday_client,
    )
    syncer_tuesday.run_once(now=tuesday)

    monday_snapshot = (
        tmp_path / "daily" / "2026" / "05" / "11"
        / "_weave" / "google workspace activity.md"
    ).read_text()
    tuesday_snapshot = (
        tmp_path / "daily" / "2026" / "05" / "12"
        / "_weave" / "google workspace activity.md"
    ).read_text()
    assert "Spec" in monday_snapshot
    assert "viewed" in monday_snapshot
    assert "Spec" in tuesday_snapshot
    assert "viewed" in tuesday_snapshot


def test_syncer_skips_finalized_days_on_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    writer = _build_writer(tmp_path)
    client = FakeDriveClient(
        files_by_call=[
            [
                _doc(
                    id="doc",
                    name="Old doc",
                    createdTime="2026-05-10T08:00:00Z",
                    modifiedByMeTime="2026-05-10T09:00:00Z",
                    viewedByMeTime="2026-05-10T10:00:00Z",
                )
            ],
            [
                _doc(
                    id="doc",
                    name="Old doc",
                    createdTime="2026-05-10T08:00:00Z",
                    modifiedByMeTime="2026-05-10T09:00:00Z",
                    viewedByMeTime="2026-05-10T10:00:00Z",
                )
            ],
        ]
    )
    syncer = DriveActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=2,
        client=client,
    )
    # First run at May 13 06:00 UTC. Window=2 → candidates: May 13, 12, 11.
    # May 11 stable_at = May 13 00:00 → finalized at this clock.
    first_now = datetime(2026, 5, 13, 6, 0, tzinfo=UTC)
    syncer.run_once(now=first_now)
    # Second run later the same day. May 11 is now manifest-finalized, so
    # the query window should start at May 12 (not May 11).
    second_now = datetime(2026, 5, 13, 12, 0, tzinfo=UTC)
    syncer.run_once(now=second_now)
    assert len(client.calls) == 2
    second_since: datetime = client.calls[1]["since"]
    assert second_since.date() == dt_mod.date(2026, 5, 12)


def test_section_appears_after_vault_activity(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    day = dt_mod.date(2026, 5, 10)
    writer.upsert_vault_activity_section(day, "- created: [[foo.md|foo]]")
    writer.upsert_drive_activity_section(
        day,
        "- [Doc](https://docs.google.com/document/d/x) — viewed"
        " <!-- weave:drive:id=x mime=application/vnd.google-apps.document -->",
    )
    note = (tmp_path / "daily" / "2026" / "05" / "10" / "2026-05-10 weave.md").read_text()
    assert note.index("## Vault activity") < note.index("## Google Workspace activity")


def test_has_drive_activity_section_reflects_snapshot(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    day = dt_mod.date(2026, 5, 10)
    assert writer.has_drive_activity_section(day) is False
    writer.upsert_drive_activity_section(
        day,
        "- [Doc](https://docs.google.com/document/d/x) — viewed"
        " <!-- weave:drive:id=x mime=application/vnd.google-apps.document -->",
    )
    assert writer.has_drive_activity_section(day) is True


def test_remove_legacy_weave_content_strips_drive_section(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    content = (
        "personal\n"
        "<!-- weave:section:drive-activity:start -->\n"
        "- [Doc](url) — viewed <!-- weave:drive:id=x mime=y -->\n"
        "<!-- weave:section:drive-activity:end -->\n"
        "footer\n"
    )
    cleaned = writer._remove_legacy_weave_content(content)
    assert "drive-activity" not in cleaned
    assert "personal" in cleaned
    assert "footer" in cleaned
