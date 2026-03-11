from __future__ import annotations

import datetime as dt_mod
import json
import os
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytest

from weave.app import (
    AgentSessionScraper,
    CalendarScraper,
    ConfigError,
    DailyNoteWriter,
    IncomingMessage,
    RemarkableSnapshotHandler,
    RouteConfig,
    RouteResolver,
    SessionData,
    SessionTokenUsage,
    SessionTurn,
    TodoHandler,
    TranscriptionError,
    VoiceNoteHandler,
    WeaveConfig,
    WeaveService,
    _format_duration,
    detect_session_format,
    extract_section_for_date,
    get_agent_session_manifest_path,
    get_variant_address,
    is_gemini_notes,
    is_shared_notes,
    parse_claude_session,
    parse_pi_session,
    parse_session,
    render_session_note,
    render_session_turns,
    sanitize_filename,
)


class StaticTranscriber:
    def __init__(self, text: str):
        self.text = text

    def get_transcription(self, pdf_path: Path) -> str:
        return self.text


class FailingTranscriber:
    def get_transcription(self, pdf_path: Path) -> str:
        raise TranscriptionError("failed")


def build_message_with_body_and_attachment() -> bytes:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "target@example.com"
    message["Subject"] = "Voice note"
    message.set_content("hello from voice")
    message.add_attachment(
        b"fake-image-bytes",
        maintype="image",
        subtype="png",
        filename="clip.png",
    )
    return message.as_bytes()


def build_message_with_pdf() -> bytes:
    message = EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "target@example.com"
    message["Subject"] = "Snapshot"
    message.set_content("remarkable")
    message.add_attachment(
        b"%PDF-1.4 data",
        maintype="application",
        subtype="pdf",
        filename="page.pdf",
    )
    return message.as_bytes()


def build_incoming(raw_email: bytes, subject: str) -> IncomingMessage:
    return IncomingMessage(
        uid=5,
        subject=subject,
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        sender="sender@example.com",
        to_addresses=["target@example.com"],
        raw_email=raw_email,
    )


def test_route_resolver_matches_to_and_sender() -> None:
    resolver = RouteResolver(
        routes=(
            RouteConfig(
                name="voice",
                to_address="target@example.com",
                allowed_senders=("sender@example.com",),
                handler_key="voice",
                sink_relative=Path("sink"),
            ),
        )
    )

    route = resolver.get_route_for_message(
        to_addresses=["TARGET@example.com"],
        sender="SENDER@example.com",
    )

    assert route is not None
    assert route.name == "voice"


def test_get_variant_address_builds_plus_alias() -> None:
    assert get_variant_address("name@example.com", "+vnote") == "name+vnote@example.com"


def test_get_variant_address_rejects_malformed_base() -> None:
    with pytest.raises(ConfigError):
        get_variant_address("bad-address", "+vnote")


def test_daily_note_writer_uses_obsidian_daily_folder(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("content")

    writer = DailyNoteWriter(vault_root=vault_root)
    writer.append_note_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
        entry_type="transcript",
    )

    daily_path = vault_root / "personal" / "daily" / "2026-03-01.md"
    assert daily_path.exists()
    assert daily_path.read_text() == (
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] #weave\n"
    )


def test_daily_note_writer_deduplicates_existing_embed(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("content")
    daily_path = vault_root / "personal" / "daily" / "2026-03-01.md"
    daily_path.parent.mkdir(parents=True)
    daily_path.write_text("seed\n")

    writer = DailyNoteWriter(vault_root=vault_root)
    writer.append_note_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
        entry_type="transcript",
    )
    writer.append_note_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
        entry_type="transcript",
    )

    content = daily_path.read_text()
    assert content.count("[[sink/2026/03/01/1345 - transcription.md]]") == 1


class CallCountSummarizer:
    def __init__(self) -> None:
        self.call_count = 0

    def summarize(self, content: str) -> str:
        self.call_count += 1
        return f"summary attempt {self.call_count}"


def test_daily_note_writer_deduplicates_by_link_ignoring_summary(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("content")

    summarizer = CallCountSummarizer()
    writer = DailyNoteWriter(vault_root=vault_root, summarizer=summarizer)
    writer.append_note_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
        entry_type="transcript",
    )
    writer.append_note_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
        entry_type="transcript",
    )

    daily_path = vault_root / "personal" / "daily" / "2026-03-01.md"
    content = daily_path.read_text()
    assert content.count("[[sink/2026/03/01/1345 - transcription.md]]") == 1
    assert summarizer.call_count == 1


def test_daily_note_writer_deduplicates_todo_by_link(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - buy-milk.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("content")

    summarizer = CallCountSummarizer()
    writer = DailyNoteWriter(vault_root=vault_root, summarizer=summarizer)
    writer.append_todo_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )
    writer.append_todo_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )

    daily_path = vault_root / "personal" / "daily" / "2026-03-01.md"
    content = daily_path.read_text()
    assert content.count("[[sink/2026/03/01/1345 - buy-milk.md]]") == 1
    assert summarizer.call_count == 1


def test_voice_handler_writes_markdown_and_attachment(tmp_path: Path) -> None:
    handler = VoiceNoteHandler(output_dir=tmp_path)
    message = build_incoming(build_message_with_body_and_attachment(), subject="Voice note")

    result = handler.handle_message(message)

    assert result.handled is True
    note_path = tmp_path / "2026/03/01" / "1345 - transcription.md"
    attachment_path = tmp_path / "2026/03/01" / "_attachments" / "1345 - clip.png"
    assert note_path.exists()
    assert attachment_path.exists()
    assert result.note_paths == [note_path]
    content = note_path.read_text()
    assert "hello from voice" in content
    assert "![[_attachments/1345 - clip.png]]" in content


def test_remarkable_handler_writes_pdf_and_markdown(tmp_path: Path) -> None:
    handler = RemarkableSnapshotHandler(
        output_dir=tmp_path,
        transcriber=StaticTranscriber("line one"),
    )
    message = build_incoming(build_message_with_pdf(), subject="Snapshot")

    result = handler.handle_message(message)

    assert result.handled is True
    pdf_path = tmp_path / "2026/03/01" / "_attachments" / "1345 - page.pdf"
    note_path = tmp_path / "2026/03/01" / "1345 - page.md"
    assert pdf_path.exists()
    assert note_path.exists()
    assert result.note_paths == [note_path]
    content = note_path.read_text()
    assert "line one" in content
    assert "![[_attachments/1345 - page.pdf]]" in content


def test_remarkable_handler_writes_error_note_on_transcription_failure(tmp_path: Path) -> None:
    handler = RemarkableSnapshotHandler(output_dir=tmp_path, transcriber=FailingTranscriber())
    message = build_incoming(build_message_with_pdf(), subject="Snapshot")

    result = handler.handle_message(message)

    assert result.handled is True
    note_path = tmp_path / "2026/03/01" / "1345 - page.md"
    assert result.note_paths == [note_path]
    content = note_path.read_text()
    assert "TRANSCRIPTION_FAILED" in content


def test_sanitize_filename_strips_unsafe_chars() -> None:
    assert sanitize_filename('Fix: the "thing"') == "Fix- the -thing"
    assert sanitize_filename("slashes/and\\back") == "slashes-and-back"
    assert sanitize_filename("???") == "untitled"
    assert sanitize_filename("ok name") == "ok name"


def test_todo_handler_writes_note_with_heading_and_attachments(tmp_path: Path) -> None:
    handler = TodoHandler(output_dir=tmp_path)
    raw = build_message_with_body_and_attachment()
    message = build_incoming(raw, subject="Buy groceries")

    result = handler.handle_message(message)

    assert result.handled is True
    note_path = tmp_path / "2026/03/01" / "1345 - Buy groceries.md"
    attachment_path = tmp_path / "2026/03/01" / "_attachments" / "1345 - clip.png"
    assert note_path.exists()
    assert attachment_path.exists()
    assert result.note_paths == []
    assert result.todo_entries == [("Buy groceries", note_path)]
    content = note_path.read_text()
    assert "## Buy groceries" in content
    assert "hello from voice" in content
    assert "![[_attachments/1345 - clip.png]]" in content


def test_todo_handler_skips_existing_note(tmp_path: Path) -> None:
    handler = TodoHandler(output_dir=tmp_path)
    raw = build_message_with_body_and_attachment()
    message = build_incoming(raw, subject="Buy groceries")
    date_folder = tmp_path / "2026/03/01"
    date_folder.mkdir(parents=True)
    (date_folder / "1345 - Buy groceries.md").write_text("existing")

    result = handler.handle_message(message)

    assert result.handled is True
    assert result.created_paths == []
    assert result.todo_entries == []


def test_daily_note_writer_appends_todo_embed(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - Buy groceries.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("content")

    writer = DailyNoteWriter(vault_root=vault_root)
    writer.append_todo_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )

    daily_path = vault_root / "personal" / "daily" / "2026-03-01.md"
    assert daily_path.exists()
    assert daily_path.read_text() == (
        "- [ ] todo: [[sink/2026/03/01/1345 - Buy groceries.md]] #weave\n"
    )


class StaticSummarizer:
    def __init__(self, summary: str = "A brief summary."):
        self.summary = summary

    def summarize(self, content: str) -> str:
        return self.summary


def test_daily_note_writer_includes_summary_when_summarizer_provided(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("Some voice note content here.")

    writer = DailyNoteWriter(
        vault_root=vault_root,
        summarizer=StaticSummarizer("Voice memo about project planning."),
    )
    writer.append_note_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
        entry_type="transcript",
    )

    daily_path = vault_root / "daily" / "2026-03-01.md"
    assert daily_path.read_text() == (
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]]"
        " - Voice memo about project planning. #weave\n"
    )
    assert note_path.read_text() == (
        '---\nsummary: "Voice memo about project planning."\n---\nSome voice note content here.'
    )


def test_daily_note_writer_todo_includes_summary(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - Fix bug.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("Fix the login bug.")

    writer = DailyNoteWriter(
        vault_root=vault_root,
        summarizer=StaticSummarizer("Bug fix for login flow."),
    )
    writer.append_todo_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )

    daily_path = vault_root / "daily" / "2026-03-01.md"
    assert daily_path.read_text() == (
        "- [ ] todo: [[sink/2026/03/01/1345 - Fix bug.md]] - Bug fix for login flow. #weave\n"
    )
    assert note_path.read_text() == (
        '---\nsummary: "Bug fix for login flow."\n---\nFix the login bug.'
    )


def test_daily_note_writer_uses_stored_frontmatter_summary(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        'subject: "Voice note"\n'
        'summary: "Stored summary."\n'
        "received: 2026-03-01T13:45:00+00:00\n"
        "---\n"
        "\n"
        "Some voice note content here.\n"
    )

    summarizer = CallCountSummarizer()
    writer = DailyNoteWriter(vault_root=vault_root, summarizer=summarizer)
    writer.append_note_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
        entry_type="transcript",
    )

    daily_path = vault_root / "daily" / "2026-03-01.md"
    assert daily_path.read_text() == (
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] - Stored summary. #weave\n"
    )
    assert summarizer.call_count == 0


def test_daily_note_writer_syncs_managed_lines_from_note_summary(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        'summary: "Updated summary."\n'
        "---\n"
        "Body\n"
    )
    daily_path = vault_root / "daily" / "2026-03-01.md"
    daily_path.parent.mkdir(parents=True)
    daily_path.write_text(
        "intro\n"
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] - Old summary. #weave\n"
        "tail\n"
    )

    writer = DailyNoteWriter(vault_root=vault_root)

    assert writer.sync_all_daily_notes() == 1
    assert daily_path.read_text() == (
        "intro\n"
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] - Updated summary. #weave\n"
        "tail\n"
    )


def test_daily_note_writer_syncs_todo_lines_without_resummarizing(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - Fix bug.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        'summary: ""\n'
        "---\n"
        "Body\n"
    )
    daily_path = vault_root / "daily" / "2026-03-01.md"
    daily_path.parent.mkdir(parents=True)
    daily_path.write_text(
        "seed\n"
        "- [ ] todo: [[sink/2026/03/01/1345 - Fix bug.md]] - Old summary. #weave\n"
        "leave me alone #weave\n"
    )

    writer = DailyNoteWriter(vault_root=vault_root)

    assert writer.sync_all_daily_notes() == 1
    assert daily_path.read_text() == (
        "seed\n"
        "- [ ] todo: [[sink/2026/03/01/1345 - Fix bug.md]] #weave\n"
        "leave me alone #weave\n"
    )


def test_weave_service_runs_daily_note_sync_once_per_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text(
        "---\n"
        'summary: "First summary."\n'
        "---\n"
        "Body\n"
    )
    daily_path = vault_root / "daily" / "2026-03-01.md"
    daily_path.parent.mkdir(parents=True)
    daily_path.write_text(
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] - Stale summary. #weave\n"
    )
    monkeypatch.setattr(WeaveService, "_init_calendar_scraper", lambda self, config: None)
    config = WeaveConfig(
        imap_host="imap.example.com",
        imap_user="user",
        imap_password="password",
        vault_root=vault_root,
        poll_interval_seconds=300,
        routes=(),
    )
    service = WeaveService(config)

    assert service.run_daily_note_sync(sync_date=dt_mod.date(2026, 3, 1)) == 1
    assert daily_path.read_text() == (
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] - First summary. #weave\n"
    )

    note_path.write_text(
        "---\n"
        'summary: "Second summary."\n'
        "---\n"
        "Body\n"
    )

    assert service.run_daily_note_sync(sync_date=dt_mod.date(2026, 3, 1)) == 0
    assert daily_path.read_text() == (
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] - First summary. #weave\n"
    )

    assert service.run_daily_note_sync(sync_date=dt_mod.date(2026, 3, 2)) == 1
    assert daily_path.read_text() == (
        "- transcript: [[sink/2026/03/01/1345 - transcription.md]] - Second summary. #weave\n"
    )


# --- Calendar scraper tests ---


SAMPLE_SHARED_NOTES = """\
## Mar 5, 2026
### Agenda
- Item A
- Item B

## Mar 6, 2026
### Standup
- Status update

## Mar 7, 2026
### Retro
- Done
"""


def test_extract_section_for_date_returns_matching_section() -> None:
    result = extract_section_for_date(SAMPLE_SHARED_NOTES, dt_mod.date(2026, 3, 6))
    assert result is not None
    assert "### Standup" in result
    assert "Status update" in result
    assert "### Agenda" not in result


def test_extract_section_for_date_returns_none_for_missing_date() -> None:
    result = extract_section_for_date(SAMPLE_SHARED_NOTES, dt_mod.date(2026, 3, 10))
    assert result is None


def test_extract_section_for_date_returns_last_section() -> None:
    result = extract_section_for_date(SAMPLE_SHARED_NOTES, dt_mod.date(2026, 3, 7))
    assert result is not None
    assert "### Retro" in result


def test_is_gemini_notes_matches_variants() -> None:
    assert is_gemini_notes("Notes by Gemini for meeting") is True
    assert is_gemini_notes("Team Sync - Notes by Gemini") is True
    assert is_gemini_notes("Regular meeting notes") is False
    assert is_gemini_notes("notes by gemini") is True


def test_is_shared_notes_matches_prefix() -> None:
    assert is_shared_notes("Notes - Team Sync") is True
    assert is_shared_notes("Notes -\u00a0Team Sync") is True
    assert is_shared_notes("Meeting notes doc") is False


class StaticDriveExporter:
    def __init__(
        self,
        doc_content: bytes = b"# Meeting\nNotes here",
        chat_content: bytes = b"Chat log",
    ):
        self.doc_content = doc_content
        self.chat_content = chat_content

    def export_document(self, file_id: str) -> bytes:
        return self.doc_content

    def get_media(self, file_id: str) -> bytes:
        return self.chat_content


def test_calendar_scraper_writes_doc_note(tmp_path: Path) -> None:
    from weave.app import CALENDAR_TEMPLATE, get_date_folder

    exporter = StaticDriveExporter(doc_content=b"# Agenda\n- discuss things")
    scraper = CalendarScraper(
        output_dir=tmp_path,
        source="@test.com",
        drive_exporter=exporter,
    )

    start_dt = datetime(2026, 3, 6, 10, 0, tzinfo=UTC)
    day_dir = get_date_folder(scraper.output_dir, start_dt)
    event_name = "Team Sync"
    out_path = day_dir / f"1000 - {event_name}.md"

    md_bytes = exporter.export_document("doc123")
    front_matter = CALENDAR_TEMPLATE.render(
        source=scraper.source,
        doc_type="meeting_notes",
        event_name=event_name,
        date=start_dt.strftime("%Y-%m-%d"),
        attended="true",
        doc_url="https://docs.google.com/document/d/doc123",
        event_url="https://calendar.google.com/event/abc",
        attendees=[{"email": "me@test.com", "responseStatus": "accepted"}],
    )
    out_path.write_bytes(front_matter.encode() + md_bytes)

    assert out_path.exists()
    content = out_path.read_text()
    assert "Team Sync" in content
    assert "discuss things" in content
    assert out_path.parent.parent.parent.parent == tmp_path


def test_calendar_scraper_skips_existing_files(tmp_path: Path) -> None:
    day_dir = tmp_path / "2026" / "03" / "06"
    day_dir.mkdir(parents=True)
    existing = day_dir / "1000 - Team Sync.md"
    existing.write_text("already here")

    assert existing.exists()
    assert existing.read_text() == "already here"


def test_calendar_scraper_creates_nested_date_dirs(tmp_path: Path) -> None:
    from weave.app import get_date_folder

    dt = datetime(2026, 3, 6, 14, 30, tzinfo=UTC)
    day_dir = get_date_folder(tmp_path, dt)

    assert day_dir == tmp_path / "2026" / "03" / "06"
    assert day_dir.exists()
    assert not (day_dir / "_attachments").exists()


# --- Agent session parsing tests ---


def _build_claude_session_jsonl() -> str:
    base = {
        "cwd": "/Users/user/code/myproject",
        "sessionId": "abc-123",
        "version": "2.1.50",
        "gitBranch": "main",
    }
    usage_001a = {
        "input_tokens": 100,
        "cache_creation_input_tokens": 500,
        "cache_read_input_tokens": 200,
        "output_tokens": 10,
    }
    usage_001b = dict(usage_001a, output_tokens=50)
    usage_002 = {
        "input_tokens": 150,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 700,
        "output_tokens": 30,
    }
    usage_003 = {
        "input_tokens": 200,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 900,
        "output_tokens": 40,
    }
    usage_004 = {
        "input_tokens": 250,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 1100,
        "output_tokens": 20,
    }
    lines = [
        {
            **base,
            "type": "user",
            "parentUuid": None,
            "message": {"role": "user", "content": "help me fix this bug"},
            "uuid": "u1",
            "timestamp": "2026-03-04T11:00:00.000Z",
        },
        {
            **base,
            "type": "assistant",
            "parentUuid": "u1",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_001",
                "role": "assistant",
                "content": [{"type": "thinking", "thinking": "Look."}],
                "stop_reason": None,
                "usage": usage_001a,
            },
            "uuid": "a1",
            "timestamp": "2026-03-04T11:00:05.000Z",
        },
        {
            **base,
            "type": "assistant",
            "parentUuid": "a1",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_001",
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}],
                "stop_reason": None,
                "usage": usage_001b,
            },
            "uuid": "a2",
            "timestamp": "2026-03-04T11:00:06.000Z",
        },
        {
            **base,
            "type": "user",
            "parentUuid": "a2",
            "message": {
                "role": "user",
                "content": [
                    {"tool_use_id": "t1", "type": "tool_result", "content": "file content"}
                ],
            },
            "uuid": "u2",
            "timestamp": "2026-03-04T11:00:06.100Z",
        },
        {
            **base,
            "type": "assistant",
            "parentUuid": "u2",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_002",
                "role": "assistant",
                "content": [{"type": "text", "text": "I found the bug in line 42."}],
                "stop_reason": "end_turn",
                "usage": usage_002,
            },
            "uuid": "a3",
            "timestamp": "2026-03-04T11:00:10.000Z",
        },
        {
            **base,
            "type": "user",
            "parentUuid": "a3",
            "message": {"role": "user", "content": "great, fix it"},
            "uuid": "u3",
            "timestamp": "2026-03-04T11:01:00.000Z",
        },
        {
            **base,
            "type": "assistant",
            "parentUuid": "u3",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_003",
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t2", "name": "Edit", "input": {}}],
                "stop_reason": None,
                "usage": usage_003,
            },
            "uuid": "a4",
            "timestamp": "2026-03-04T11:01:05.000Z",
        },
        {
            **base,
            "type": "user",
            "parentUuid": "a4",
            "message": {
                "role": "user",
                "content": [{"tool_use_id": "t2", "type": "tool_result", "content": "edited"}],
            },
            "uuid": "u4",
            "timestamp": "2026-03-04T11:01:05.100Z",
        },
        {
            **base,
            "type": "assistant",
            "parentUuid": "u4",
            "message": {
                "model": "claude-opus-4-6",
                "id": "msg_004",
                "role": "assistant",
                "content": [{"type": "text", "text": "Fixed. Var was uninitialized."}],
                "stop_reason": "end_turn",
                "usage": usage_004,
            },
            "uuid": "a5",
            "timestamp": "2026-03-04T11:01:10.000Z",
        },
    ]
    return "\n".join(json.dumps(entry) for entry in lines) + "\n"


def _build_pi_session_jsonl() -> str:
    cost1 = {"input": 0.003, "output": 0.001, "cacheRead": 0, "cacheWrite": 0, "total": 0.004}
    cost2 = {"input": 0.005, "output": 0.002, "cacheRead": 0.001, "cacheWrite": 0, "total": 0.008}
    lines = [
        {
            "type": "session",
            "version": 3,
            "id": "pi-sess-001",
            "timestamp": "2026-03-03T16:00:00.000Z",
            "cwd": "/Users/user/code/myproject",
        },
        {
            "type": "model_change",
            "id": "mc1",
            "parentId": None,
            "timestamp": "2026-03-03T16:00:00.000Z",
            "provider": "anthropic",
            "modelId": "claude-sonnet-4-6",
        },
        {
            "type": "message",
            "id": "m1",
            "parentId": "mc1",
            "timestamp": "2026-03-03T16:00:10.000Z",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "explore the codebase"}],
            },
        },
        {
            "type": "message",
            "id": "m2",
            "parentId": "m1",
            "timestamp": "2026-03-03T16:00:20.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me look."},
                    {
                        "type": "toolCall",
                        "id": "tc1",
                        "name": "bash",
                        "arguments": {"command": "ls"},
                    },
                ],
                "usage": {
                    "input": 1000,
                    "output": 50,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "totalTokens": 1050,
                    "cost": cost1,
                },
            },
        },
        {
            "type": "message",
            "id": "m3",
            "parentId": "m2",
            "timestamp": "2026-03-03T16:00:25.000Z",
            "message": {
                "role": "toolResult",
                "content": [{"type": "text", "text": "file1.py file2.py"}],
            },
        },
        {
            "type": "message",
            "id": "m4",
            "parentId": "m3",
            "timestamp": "2026-03-03T16:00:30.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Found two files."},
                    {"type": "text", "text": "The project has two Python files."},
                ],
                "usage": {
                    "input": 1500,
                    "output": 80,
                    "cacheRead": 500,
                    "cacheWrite": 0,
                    "totalTokens": 2080,
                    "cost": cost2,
                },
            },
        },
    ]
    return "\n".join(json.dumps(entry) for entry in lines) + "\n"


@pytest.fixture
def claude_session_file(tmp_path: Path) -> Path:
    d = tmp_path / "claude" / "-Users-user-code-myproject"
    d.mkdir(parents=True)
    p = d / "abc-123.jsonl"
    p.write_text(_build_claude_session_jsonl())
    return p


@pytest.fixture
def pi_session_file(tmp_path: Path) -> Path:
    d = tmp_path / "pi" / "--Users-user-code-myproject--"
    d.mkdir(parents=True)
    p = d / "2026-03-03T16-00-00-000Z_pi-11111111-1111-1111-1111-111111111111.jsonl"
    p.write_text(_build_pi_session_jsonl())
    return p


def test_detect_format_claude(claude_session_file: Path) -> None:
    assert detect_session_format(claude_session_file) == "claude"


def test_detect_format_pi(pi_session_file: Path) -> None:
    assert detect_session_format(pi_session_file) == "pi"


def test_parse_claude_session_metadata(claude_session_file: Path) -> None:
    session = parse_claude_session(claude_session_file)
    assert session.agent == "claude"
    assert session.session_id == "abc-123"
    assert session.project == "myproject"
    assert session.cwd == "/Users/user/code/myproject"
    assert session.git_branch == "main"
    assert session.models == ["claude-opus-4-6"]
    assert session.start_time is not None
    assert session.end_time is not None
    assert session.duration is not None


def test_parse_claude_session_turns(claude_session_file: Path) -> None:
    session = parse_claude_session(claude_session_file)
    assert len(session.turns) == 2
    assert session.turns[0].user_text == "help me fix this bug"
    assert "bug" in session.turns[0].assistant_texts[0]
    assert session.turns[0].tool_names == ["Read"]
    assert session.turns[1].user_text == "great, fix it"
    assert "uninitialized" in session.turns[1].assistant_texts[0]
    assert session.turns[1].tool_names == ["Edit"]


def test_parse_claude_session_tokens(claude_session_file: Path) -> None:
    session = parse_claude_session(claude_session_file)
    # msg_001 last record: input=100, cache_create=500, cache_read=200, output=50
    # msg_002: input=150, cache_create=0, cache_read=700, output=30
    # msg_003: input=200, cache_create=0, cache_read=900, output=40
    # msg_004: input=250, cache_create=0, cache_read=1100, output=20
    assert session.usage.input_tokens == 100 + 150 + 200 + 250
    assert session.usage.output_tokens == 50 + 30 + 40 + 20
    assert session.usage.cache_write_tokens == 500
    assert session.usage.cache_read_tokens == 200 + 700 + 900 + 1100


def test_parse_claude_session_tool_and_thinking_counts(claude_session_file: Path) -> None:
    session = parse_claude_session(claude_session_file)
    assert session.total_tool_calls == 2
    assert session.total_thinking_blocks == 1


def test_parse_pi_session_metadata(pi_session_file: Path) -> None:
    session = parse_pi_session(pi_session_file)
    assert session.agent == "pi"
    assert session.session_id == "pi-sess-001"
    assert session.project == "myproject"
    assert session.cwd == "/Users/user/code/myproject"
    assert session.models == ["anthropic/claude-sonnet-4-6"]


def test_parse_pi_session_turns(pi_session_file: Path) -> None:
    session = parse_pi_session(pi_session_file)
    assert len(session.turns) == 1
    assert session.turns[0].user_text == "explore the codebase"
    assert "Python files" in session.turns[0].assistant_texts[0]
    assert session.turns[0].tool_names == ["bash"]


def test_parse_pi_session_tokens(pi_session_file: Path) -> None:
    session = parse_pi_session(pi_session_file)
    assert session.usage.input_tokens == 1000 + 1500
    assert session.usage.output_tokens == 50 + 80
    assert session.usage.cache_read_tokens == 500
    assert session.usage.cost == pytest.approx(0.012)


def test_parse_pi_session_counts(pi_session_file: Path) -> None:
    session = parse_pi_session(pi_session_file)
    assert session.total_tool_calls == 1
    assert session.total_thinking_blocks == 2


def test_parse_session_auto_detects(claude_session_file: Path, pi_session_file: Path) -> None:
    claude = parse_session(claude_session_file)
    assert claude.agent == "claude"
    pi = parse_session(pi_session_file)
    assert pi.agent == "pi"


def test_render_session_turns_includes_user_and_assistant() -> None:
    session = SessionData(
        agent="claude",
        session_id="x",
        project="proj",
        cwd="/x",
        turns=[
            SessionTurn(
                user_text="do the thing",
                assistant_texts=["done."],
                tool_names=["Edit"],
                timestamp=datetime(2026, 3, 4, 11, 0, tzinfo=UTC),
            )
        ],
    )
    rendered = render_session_turns(session)
    assert "**USER:** do the thing" in rendered
    assert "**ASSISTANT:** done." in rendered
    assert "Edit" in rendered


def test_render_session_note_has_frontmatter() -> None:
    session = SessionData(
        agent="pi",
        session_id="sess-abc",
        project="myproject",
        cwd="/x",
        start_time=datetime(2026, 3, 3, 16, 0, tzinfo=UTC),
        end_time=datetime(2026, 3, 3, 16, 5, tzinfo=UTC),
        models=["anthropic/sonnet"],
        usage=SessionTokenUsage(input_tokens=100, output_tokens=50),
        turns=[SessionTurn(user_text="hi", assistant_texts=["hello"], tool_names=[])],
        total_tool_calls=3,
    )
    note = render_session_note(
        session,
        "Built a thing.",
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    assert "type: agent_session" in note
    assert "agent: pi" in note
    assert 'project: "myproject"' in note
    assert "Built a thing." in note
    assert "**USER:** hi" in note


def test_format_duration() -> None:
    assert _format_duration(dt_mod.timedelta(seconds=45)) == "45s"
    assert _format_duration(dt_mod.timedelta(minutes=3, seconds=19)) == "3m 19s"
    assert _format_duration(dt_mod.timedelta(hours=2, minutes=5, seconds=1)) == "2h 5m 1s"


def test_agent_session_scraper_writes_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sessions_dir = tmp_path / "sessions"
    claude_dir = sessions_dir / "claude" / "-Users-user-code-proj"
    claude_dir.mkdir(parents=True)
    session_path = claude_dir / "11111111-1111-1111-1111-111111111111.jsonl"
    session_path.write_text(_build_claude_session_jsonl())

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
        summarizer=StaticSummarizer("Fixed a bug."),
    )
    run = scraper.scrape_once()

    assert run.report.scanned == 1
    assert run.report.imported == 1
    assert len(run.results) == 1
    result = run.results[0]
    assert result.entry_type == "agent session"
    note_path = result.note_path
    assert note_path.exists()
    assert note_path.name == "abc-123.md"
    content = note_path.read_text()
    assert "type: agent_session" in content
    assert 'session_id: "abc-123"' in content
    assert "session_sha256:" in content
    assert "Fixed a bug." in content
    assert "help me fix this bug" in content


def test_agent_session_scraper_uses_manifest_for_unchanged_mutable_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sessions_dir = tmp_path / "sessions"
    claude_dir = sessions_dir / "claude" / "-Users-user-code-proj"
    claude_dir.mkdir(parents=True)
    session_path = claude_dir / "11111111-1111-1111-1111-111111111111.jsonl"
    session_path.write_text(_build_claude_session_jsonl())

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
        summarizer=StaticSummarizer("summary"),
    )
    run1 = scraper.scrape_once()
    note_path = run1.results[0].note_path
    original_content = note_path.read_text()

    run2 = scraper.scrape_once()
    assert run2.report.imported == 0
    assert run2.report.updated == 0
    assert run2.report.unchanged == 1
    assert run2.results == []
    assert note_path.read_text() == original_content


def test_agent_session_scraper_updates_changed_mutable_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sessions_dir = tmp_path / "sessions"
    claude_dir = sessions_dir / "claude" / "-Users-user-code-proj"
    claude_dir.mkdir(parents=True)
    session_path = claude_dir / "11111111-1111-1111-1111-111111111111.jsonl"
    session_path.write_text(_build_claude_session_jsonl())

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
        summarizer=StaticSummarizer("summary"),
    )
    first_run = scraper.scrape_once()
    note_path = first_run.results[0].note_path
    first_content = note_path.read_text()

    updated_jsonl = _build_claude_session_jsonl().replace(
        "help me fix this bug",
        "help me fix this other bug",
    )
    session_path.write_text(updated_jsonl)

    second_run = scraper.scrape_once()
    assert second_run.report.updated == 1
    assert len(second_run.results) == 1
    assert second_run.results[0].note_path == note_path
    second_content = note_path.read_text()
    assert "help me fix this other bug" in second_content
    assert second_content != first_content

    manifest = json.loads(get_agent_session_manifest_path().read_text())
    entry = manifest["sessions"][str(session_path.resolve())]
    assert entry["session_id"] == "abc-123"
    assert entry["session_sha256"] in second_content


def test_agent_session_scraper_skips_immutable_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sessions_dir = tmp_path / "sessions"
    claude_dir = sessions_dir / "claude" / "-Users-user-code-proj"
    claude_dir.mkdir(parents=True)
    session_path = claude_dir / "11111111-1111-1111-1111-111111111111.jsonl"
    session_path.write_text(_build_claude_session_jsonl())

    old_ts = (datetime.now(tz=UTC) - timedelta(days=8)).timestamp()
    os.utime(session_path, (old_ts, old_ts))

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
    )
    first_run = scraper.scrape_once()
    assert first_run.report.imported == 1

    second_run = scraper.scrape_once()
    assert second_run.report.skipped_immutable == 1
    assert second_run.results == []


def test_agent_session_scraper_recovers_from_malformed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    manifest_path = get_agent_session_manifest_path()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("not-json")

    sessions_dir = tmp_path / "sessions"
    claude_dir = sessions_dir / "claude" / "-Users-user-code-proj"
    claude_dir.mkdir(parents=True)
    session_path = claude_dir / "11111111-1111-1111-1111-111111111111.jsonl"
    session_path.write_text(_build_claude_session_jsonl())

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
    )
    run = scraper.scrape_once()
    assert run.report.imported == 1
    saved_manifest = json.loads(manifest_path.read_text())
    assert saved_manifest["version"] == 1


def test_agent_session_scraper_skips_empty_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sessions_dir = tmp_path / "sessions"
    claude_dir = sessions_dir / "claude" / "-Users-user-code-proj"
    claude_dir.mkdir(parents=True)
    empty = '{"type":"file-history-snapshot","messageId":"x","snapshot":{}}\n'
    (claude_dir / "11111111-1111-1111-1111-111111111111.jsonl").write_text(empty)

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
    )
    run = scraper.scrape_once()
    assert run.report.skipped_empty == 1
    assert run.results == []


def test_agent_session_scraper_skips_subagents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sessions_dir = tmp_path / "sessions"
    subdir = sessions_dir / "claude" / "-proj" / "s1" / "subagents"
    subdir.mkdir(parents=True)
    (subdir / "agent-x.jsonl").write_text(_build_claude_session_jsonl())

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
    )
    run = scraper.scrape_once()
    assert run.report.scanned == 0
    assert run.results == []


def test_agent_session_scraper_skips_noncanonical_session_filenames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    sessions_dir = tmp_path / "sessions"
    claude_dir = sessions_dir / "claude" / "-proj"
    claude_dir.mkdir(parents=True)
    (claude_dir / "agent-a0d1b80.jsonl").write_text(_build_claude_session_jsonl())
    (claude_dir / "abc-123.jsonl").write_text(_build_claude_session_jsonl())
    (claude_dir / "11111111-1111-1111-1111-111111111111.jsonl").write_text(
        _build_claude_session_jsonl().replace("abc-123", "11111111-1111-1111-1111-111111111111")
    )

    output_dir = tmp_path / "sink"
    output_dir.mkdir()

    scraper = AgentSessionScraper(
        sessions_dir=sessions_dir,
        output_dir=output_dir,
    )
    run = scraper.scrape_once()
    assert run.report.scanned == 1
    assert len(run.results) == 1
    assert run.results[0].note_path.name == "11111111-1111-1111-1111-111111111111.md"
