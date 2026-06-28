from __future__ import annotations

import datetime as dt_mod
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from weave.app import DailyNoteWriter, VaultActivitySyncer
from weave.vault_index import (
    DEFAULT_EXCLUDE_AT_ROOT,
    build_entry,
    collect_day_entries,
    get_created_at,
    iter_markdown_files,
    render_activity_body,
    render_entry_line,
    stat_file,
)


def _set_file_times(path: Path, *, mtime: datetime) -> None:
    ts = mtime.timestamp()
    os.utime(path, (ts, ts))


def test_iter_markdown_files_skips_excluded_subtrees(tmp_path: Path) -> None:
    vault = tmp_path
    (vault / "Projects").mkdir()
    (vault / "Projects" / "foo.md").write_text("foo")
    (vault / "Projects" / "image.png").write_bytes(b"")
    (vault / "Areas").mkdir()
    (vault / "Areas" / "bar.md").write_text("bar")
    (vault / "daily" / "2026" / "05" / "10").mkdir(parents=True)
    (vault / "daily" / "2026" / "05" / "10" / "skip.md").write_text("skip")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "config.md").write_text("skip")
    (vault / ".trash").mkdir()
    (vault / ".trash" / "deleted.md").write_text("skip")
    (vault / "_weave").mkdir()
    (vault / "_weave" / "skip.md").write_text("skip")
    (vault / "sink" / "2026" / "05" / "10").mkdir(parents=True)
    (vault / "sink" / "2026" / "05" / "10" / "skip.md").write_text("skip")

    found = {path.relative_to(vault).as_posix() for path in iter_markdown_files(vault)}
    assert found == {"Projects/foo.md", "Areas/bar.md"}


def test_iter_markdown_files_skips_nested_underscore_dirs(tmp_path: Path) -> None:
    vault = tmp_path
    (vault / "Projects" / "_weave").mkdir(parents=True)
    (vault / "Projects" / "_weave" / "skip.md").write_text("skip")
    (vault / "Projects" / "real.md").write_text("real")
    (vault / "Projects" / "_attachments").mkdir()
    (vault / "Projects" / "_attachments" / "skip.md").write_text("skip")

    found = {path.relative_to(vault).as_posix() for path in iter_markdown_files(vault)}
    assert found == {"Projects/real.md"}


def test_get_created_at_prefers_birthtime() -> None:
    class FakeStat:
        st_ctime = 100.0
        st_birthtime = 50.0

    assert get_created_at(FakeStat()) == 50.0  # type: ignore[arg-type]


def test_get_created_at_falls_back_to_ctime() -> None:
    class FakeStat:
        st_ctime = 100.0

    assert get_created_at(FakeStat()) == 100.0  # type: ignore[arg-type]


def test_stat_file_returns_tz_aware_datetimes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("hi")
    when = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    _set_file_times(note, mtime=when)

    stats = stat_file(note, tz=UTC)
    assert stats is not None
    assert stats.modified_at.tzinfo is not None
    assert stats.modified_at == when


def test_build_entry_pulls_label_and_summary_from_frontmatter(tmp_path: Path) -> None:
    note = tmp_path / "Projects" / "foo.md"
    note.parent.mkdir()
    note.write_text(
        "---\n"
        'title: "Foo Project"\n'
        'summary: "Plans and notes for the foo initiative."\n'
        "---\n\nBody.\n"
    )

    entry = build_entry(vault_root=tmp_path, path=note, status="created")
    assert entry is not None
    assert entry.label == "Foo Project"
    assert entry.summary == "Plans and notes for the foo initiative."
    assert entry.relative_path == Path("Projects/foo.md")


def test_build_entry_falls_back_to_stem(tmp_path: Path) -> None:
    note = tmp_path / "Projects" / "bar.md"
    note.parent.mkdir()
    note.write_text("no frontmatter here")

    entry = build_entry(vault_root=tmp_path, path=note, status="modified")
    assert entry is not None
    assert entry.label == "bar"
    assert entry.summary == ""


def test_render_entry_line_includes_status_and_summary(tmp_path: Path) -> None:
    note = tmp_path / "Projects" / "foo.md"
    note.parent.mkdir()
    note.write_text('---\ntitle: "Foo"\nsummary: "a summary"\n---\n')

    entry = build_entry(vault_root=tmp_path, path=note, status="created")
    assert entry is not None
    assert render_entry_line(entry) == "- created: [[Projects/foo]] — a summary"


def test_render_activity_body_orders_created_then_modified(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "b.md").write_text("b")
    (tmp_path / "c.md").write_text("c")
    entries = [
        build_entry(tmp_path, tmp_path / "c.md", "modified"),
        build_entry(tmp_path, tmp_path / "a.md", "modified"),
        build_entry(tmp_path, tmp_path / "b.md", "created"),
    ]
    body = render_activity_body([e for e in entries if e is not None])
    lines = body.splitlines()
    assert lines[0] == "- created: [[b]]"
    assert lines[1] == "- modified: [[a]]"
    assert lines[2] == "- modified: [[c]]"


def test_collect_day_entries_buckets_created_and_modified(tmp_path: Path) -> None:
    vault = tmp_path
    (vault / "Projects").mkdir()
    new_file = vault / "Projects" / "fresh.md"
    new_file.write_text("fresh")
    edited_file = vault / "Projects" / "old.md"
    edited_file.write_text("old")

    creation_day = dt_mod.date(2026, 5, 10)
    edit_day = dt_mod.date(2026, 5, 12)
    fake_now_utc = datetime(2026, 5, 12, 14, 0, tzinfo=UTC).timestamp()
    fake_old_birth = datetime(2026, 5, 8, 12, 0, tzinfo=UTC).timestamp()

    real_stat = os.stat

    def fake_stat(path: Path | str) -> os.stat_result:
        result = real_stat(path)
        path_obj = Path(path)
        if path_obj.name == "fresh.md":
            tup = list(result)
            tup[7] = datetime(2026, 5, 10, 10, 0, tzinfo=UTC).timestamp()  # atime
            tup[8] = datetime(2026, 5, 10, 10, 0, tzinfo=UTC).timestamp()  # mtime
            tup[9] = datetime(2026, 5, 10, 10, 0, tzinfo=UTC).timestamp()  # ctime
            return os.stat_result(tup)
        if path_obj.name == "old.md":
            tup = list(result)
            tup[7] = datetime(2026, 5, 12, 9, 0, tzinfo=UTC).timestamp()
            tup[8] = datetime(2026, 5, 12, 9, 0, tzinfo=UTC).timestamp()
            tup[9] = fake_old_birth
            return os.stat_result(tup)
        return result

    del fake_now_utc  # used implicitly by patched datetime
    with patch("weave.vault_index.os.stat", side_effect=fake_stat):
        with patch.object(Path, "stat", autospec=True) as path_stat:
            path_stat.side_effect = lambda self: fake_stat(self)
            bucketed = collect_day_entries(
                vault_root=vault,
                eligible_days=[creation_day, edit_day, dt_mod.date(2026, 5, 8)],
                tz=UTC,
            )

    creation_paths = {entry.relative_path.as_posix() for entry in bucketed[creation_day]}
    assert creation_paths == {"Projects/fresh.md"}
    edit_paths = {entry.relative_path.as_posix() for entry in bucketed[edit_day]}
    assert edit_paths == {"Projects/old.md"}
    assert all(entry.status == "modified" for entry in bucketed[edit_day])
    assert all(entry.status == "created" for entry in bucketed[creation_day])
    assert {entry.relative_path.as_posix() for entry in bucketed[dt_mod.date(2026, 5, 8)]} == {
        "Projects/old.md"
    }


def test_default_exclude_at_root_covers_daily_and_sink() -> None:
    assert "daily" in DEFAULT_EXCLUDE_AT_ROOT
    assert "sink" in DEFAULT_EXCLUDE_AT_ROOT


def _build_writer(tmp_path: Path) -> DailyNoteWriter:
    config_dir = tmp_path / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    return DailyNoteWriter(vault_root=tmp_path)


def test_upsert_vault_activity_section_writes_snapshot_and_daily_note(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    body = "- created: [[Projects/foo.md|foo]]\n- modified: [[Areas/bar.md|bar]]"

    writer.upsert_vault_activity_section(dt_mod.date(2026, 5, 10), body)

    snapshot = tmp_path / "daily" / "2026" / "05" / "10" / "_weave" / "vault activity.md"
    assert snapshot.exists()
    assert snapshot.read_text().rstrip() == body

    weave_note = tmp_path / "daily" / "2026" / "05" / "10" / "2026-05-10 weave.md"
    content = weave_note.read_text()
    assert "## Vault activity" in content
    assert "<!-- weave:section:vault-activity:start -->" in content
    assert "<!-- weave:section:vault-activity:end -->" in content
    assert "[[Projects/foo.md|foo]]" in content


def test_vault_activity_section_rendered_after_github_activity(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    writer.upsert_github_activity_section(
        dt_mod.date(2026, 5, 10),
        "### owner/repo\n- did things",
    )
    writer.upsert_vault_activity_section(
        dt_mod.date(2026, 5, 10),
        "- created: [[foo.md|foo]]",
    )

    content = (tmp_path / "daily" / "2026" / "05" / "10" / "2026-05-10 weave.md").read_text()
    github_idx = content.index("## GitHub activity")
    vault_idx = content.index("## Vault activity")
    assert github_idx < vault_idx


def test_has_vault_activity_section_reflects_snapshot(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    day = dt_mod.date(2026, 5, 10)

    assert writer.has_vault_activity_section(day) is False
    writer.upsert_vault_activity_section(day, "- created: [[x.md|x]]")
    assert writer.has_vault_activity_section(day) is True


def test_remove_legacy_weave_content_strips_vault_section(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    content = (
        "My personal note\n"
        "<!-- weave:section:vault-activity:start -->\n"
        "- modified: [[x.md|x]]\n"
        "<!-- weave:section:vault-activity:end -->\n"
        "More personal content\n"
    )
    cleaned = writer._remove_legacy_weave_content(content)
    assert "vault-activity" not in cleaned
    assert "My personal note" in cleaned
    assert "More personal content" in cleaned


def test_syncer_skips_unstable_days(tmp_path: Path) -> None:
    writer = _build_writer(tmp_path)
    (tmp_path / "Projects").mkdir()
    note = tmp_path / "Projects" / "foo.md"
    note.write_text("hi")
    when = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    _set_file_times(note, mtime=when)

    syncer = VaultActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=3,
    )
    very_early_next_day = datetime(2026, 5, 15, 1, 0, tzinfo=UTC)
    count = syncer.run_once(now=very_early_next_day)
    assert count == 0
    snapshot = tmp_path / "daily" / "2026" / "05" / "14" / "_weave" / "vault activity.md"
    assert not snapshot.exists()


def test_syncer_finalizes_stabilized_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))

    writer = _build_writer(tmp_path)
    (tmp_path / "Projects").mkdir()
    note = tmp_path / "Projects" / "foo.md"
    note.write_text("hi")
    when = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    _set_file_times(note, mtime=when)

    syncer = VaultActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=3,
    )
    well_past_stabilization = datetime(2026, 5, 15, 8, 0, tzinfo=UTC)
    count = syncer.run_once(now=well_past_stabilization)
    assert count == 1

    snapshot = tmp_path / "daily" / "2026" / "05" / "14" / "_weave" / "vault activity.md"
    assert snapshot.exists()
    assert "[[Projects/foo]]" in snapshot.read_text()


def test_syncer_manifest_dedupes_subsequent_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))

    writer = _build_writer(tmp_path)
    (tmp_path / "Projects").mkdir()
    note = tmp_path / "Projects" / "foo.md"
    note.write_text("hi")
    _set_file_times(note, mtime=datetime(2026, 5, 14, 12, 0, tzinfo=UTC))

    syncer = VaultActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=3,
    )
    now = datetime(2026, 5, 15, 8, 0, tzinfo=UTC)
    first = syncer.run_once(now=now)
    second = syncer.run_once(now=now)
    assert first == 1
    assert second == 0


def test_syncer_excludes_daily_subtree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))

    writer = _build_writer(tmp_path)
    weave_managed = tmp_path / "daily" / "2026" / "05" / "14" / "transcriptions"
    weave_managed.mkdir(parents=True)
    note = weave_managed / "1200 - transcription.md"
    note.write_text("hi")
    _set_file_times(note, mtime=datetime(2026, 5, 14, 12, 0, tzinfo=UTC))

    syncer = VaultActivitySyncer(
        daily_note_writer=writer,
        timezone_name="UTC",
        window_days=3,
    )
    syncer.run_once(now=datetime(2026, 5, 15, 8, 0, tzinfo=UTC))

    snapshot = tmp_path / "daily" / "2026" / "05" / "14" / "_weave" / "vault activity.md"
    assert not snapshot.exists()


def test_syncer_respects_local_timezone_for_day_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))

    writer = _build_writer(tmp_path)
    (tmp_path / "Projects").mkdir()
    note = tmp_path / "Projects" / "foo.md"
    note.write_text("hi")
    # 03:00 UTC on May 15 is 23:00 May 14 in America/New_York.
    _set_file_times(note, mtime=datetime(2026, 5, 15, 3, 0, tzinfo=UTC))

    syncer = VaultActivitySyncer(
        daily_note_writer=writer,
        timezone_name="America/New_York",
        window_days=5,
    )
    # 08:00 May 16 in NY is past the May 14 stabilization at 06:00 May 15 NY.
    ny = ZoneInfo("America/New_York")
    syncer.run_once(now=datetime(2026, 5, 16, 8, 0, tzinfo=ny))

    snapshot = tmp_path / "daily" / "2026" / "05" / "14" / "_weave" / "vault activity.md"
    assert snapshot.exists()
