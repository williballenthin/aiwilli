from __future__ import annotations

import datetime as dt_mod
import json
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from weave.app import (
    CalendarScraper,
    ConfigError,
    DailyNoteWriter,
    IncomingMessage,
    RemarkableSnapshotHandler,
    RouteConfig,
    RouteResolver,
    TodoHandler,
    TranscriptionError,
    VoiceNoteHandler,
    extract_section_for_date,
    get_variant_address,
    is_gemini_notes,
    is_shared_notes,
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
    assert daily_path.read_text() == "- transcript: [[sink/2026/03/01/1345 - transcription.md]] #weave\n"


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

    writer = DailyNoteWriter(vault_root=vault_root, summarizer=StaticSummarizer("Voice memo about project planning."))
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


def test_daily_note_writer_todo_includes_summary(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "daily"}))
    note_path = vault_root / "sink" / "2026/03/01" / "1345 - Fix bug.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("Fix the login bug.")

    writer = DailyNoteWriter(vault_root=vault_root, summarizer=StaticSummarizer("Bug fix for login flow."))
    writer.append_todo_entry(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )

    daily_path = vault_root / "daily" / "2026-03-01.md"
    assert daily_path.read_text() == (
        "- [ ] todo: [[sink/2026/03/01/1345 - Fix bug.md]]"
        " - Bug fix for login flow. #weave\n"
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
