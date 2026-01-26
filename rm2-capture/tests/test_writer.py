from datetime import datetime

import pytest

from rm2_capture.models import Attachment, IncomingEmail
from rm2_capture.writer import Writer


@pytest.fixture
def output_dir(tmp_path):
    return tmp_path / "notes"


@pytest.fixture
def writer(output_dir):
    output_dir.mkdir()
    return Writer(output_dir)


@pytest.fixture
def sample_email():
    return IncomingEmail(
        uid=123,
        subject="Test Notes",
        received=datetime(2026, 1, 26, 11, 30, 0),
        attachments=[
            Attachment(filename="Notes - page 1.pdf", content=b"%PDF-1.4 fake pdf content")
        ],
    )


def test_pdf_exists_false_when_missing(writer, sample_email):
    attachment = sample_email.attachments[0]
    assert not writer.pdf_exists(sample_email.received, attachment)


def test_pdf_exists_true_after_save(writer, sample_email):
    attachment = sample_email.attachments[0]
    writer.save_pdf(sample_email, attachment)

    assert writer.pdf_exists(sample_email.received, attachment)


def test_save_pdf_creates_directory_structure(writer, sample_email):
    attachment = sample_email.attachments[0]
    pdf_path, pdf_filename = writer.save_pdf(sample_email, attachment)

    assert pdf_path.exists()
    assert pdf_path.parent.name == "_attachments"
    assert pdf_path.parent.parent.name == "2026-01-26"
    assert pdf_path.read_bytes() == b"%PDF-1.4 fake pdf content"
    assert pdf_path.name == "11:30 - Notes - page 1.pdf"
    assert pdf_filename == "11:30 - Notes - page 1.pdf"


def test_write_markdown_creates_note(writer, sample_email):
    attachment = sample_email.attachments[0]
    pdf_path, pdf_filename = writer.save_pdf(sample_email, attachment)

    result = writer.write_markdown(
        sample_email, attachment, pdf_path, pdf_filename, content="# Transcribed content", error=None
    )

    assert result.md_path.exists()
    assert result.md_path.name == "11:30 - Notes - page 1.md"

    content = result.md_path.read_text()
    assert 'subject: "Test Notes"' in content
    assert 'attachment: "11:30 - Notes - page 1.pdf"' in content
    assert "received: 2026-01-26T11:30:00" in content
    assert "transcribed:" in content
    assert "![[_attachments/11:30 - Notes - page 1.pdf]]" in content
    assert "# Transcribed content" in content


def test_write_markdown_creates_error_note(writer, sample_email):
    attachment = sample_email.attachments[0]
    pdf_path, pdf_filename = writer.save_pdf(sample_email, attachment)

    result = writer.write_markdown(
        sample_email, attachment, pdf_path, pdf_filename, content=None, error="LLM failed"
    )

    assert result.md_path.exists()
    assert result.error == "LLM failed"

    content = result.md_path.read_text()
    assert 'attachment: "11:30 - Notes - page 1.pdf"' in content
    assert 'error: "LLM failed"' in content
    assert "<!-- TRANSCRIPTION_FAILED: LLM failed -->" in content
    assert "transcribed:" not in content
