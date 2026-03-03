from __future__ import annotations

import json
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import pytest

from weave.app import (
    ConfigError,
    DailyNoteWriter,
    IncomingMessage,
    RemarkableSnapshotHandler,
    RouteConfig,
    RouteResolver,
    TranscriptionError,
    VoiceNoteHandler,
    get_variant_address,
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
    note_path = vault_root / "sink" / "2026-03-01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("content")

    writer = DailyNoteWriter(vault_root=vault_root)
    writer.append_note_embed(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )

    daily_path = vault_root / "personal" / "daily" / "2026-03-01.md"
    assert daily_path.exists()
    assert daily_path.read_text() == "- 13:45 ![[sink/2026-03-01/1345 - transcription.md]]\n"


def test_daily_note_writer_deduplicates_existing_embed(tmp_path: Path) -> None:
    vault_root = tmp_path
    config_dir = vault_root / ".obsidian"
    config_dir.mkdir(parents=True)
    (config_dir / "daily-notes.json").write_text(json.dumps({"folder": "personal/daily"}))
    note_path = vault_root / "sink" / "2026-03-01" / "1345 - transcription.md"
    note_path.parent.mkdir(parents=True)
    note_path.write_text("content")
    daily_path = vault_root / "personal" / "daily" / "2026-03-01.md"
    daily_path.parent.mkdir(parents=True)
    daily_path.write_text("seed\n")

    writer = DailyNoteWriter(vault_root=vault_root)
    writer.append_note_embed(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )
    writer.append_note_embed(
        received=datetime(2026, 3, 1, 13, 45, tzinfo=UTC),
        note_path=note_path,
    )

    content = daily_path.read_text()
    assert content.count("![[sink/2026-03-01/1345 - transcription.md]]") == 1


def test_voice_handler_writes_markdown_and_attachment(tmp_path: Path) -> None:
    handler = VoiceNoteHandler(output_dir=tmp_path)
    message = build_incoming(build_message_with_body_and_attachment(), subject="Voice note")

    result = handler.handle_message(message)

    assert result.handled is True
    note_path = tmp_path / "2026-03-01" / "1345 - transcription.md"
    attachment_path = tmp_path / "2026-03-01" / "_attachments" / "1345 - clip.png"
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
    pdf_path = tmp_path / "2026-03-01" / "_attachments" / "1345 - page.pdf"
    note_path = tmp_path / "2026-03-01" / "1345 - page.md"
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
    note_path = tmp_path / "2026-03-01" / "1345 - page.md"
    assert result.note_paths == [note_path]
    content = note_path.read_text()
    assert "TRANSCRIPTION_FAILED" in content
