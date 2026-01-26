from datetime import datetime

import pytest

from rm2_capture.models import Attachment, IncomingEmail
from rm2_capture.writer import Writer, hashed_filename


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


def test_hashed_filename():
    filename = hashed_filename("Notes - page 1.pdf", b"test content")
    assert filename.startswith("Notes - page 1-")
    assert filename.endswith(".pdf")
    assert len(filename) == len("Notes - page 1-12345678.pdf")


def test_hashed_filename_different_content_different_hash():
    f1 = hashed_filename("test.pdf", b"content A")
    f2 = hashed_filename("test.pdf", b"content B")
    assert f1 != f2


def test_hashed_filename_same_content_same_hash():
    f1 = hashed_filename("test.pdf", b"same content")
    f2 = hashed_filename("other.pdf", b"same content")
    assert f1.split("-")[-1] == f2.split("-")[-1]  # Same hash suffix


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
    assert pdf_path.name == pdf_filename
    assert "-" in pdf_filename  # Has hash


def test_write_markdown_creates_note(writer, sample_email):
    attachment = sample_email.attachments[0]
    pdf_path, pdf_filename = writer.save_pdf(sample_email, attachment)

    result = writer.write_markdown(
        sample_email, attachment, pdf_path, pdf_filename, content="# Transcribed content", error=None
    )

    assert result.md_path.exists()
    assert result.md_path.name.startswith("11:30 - Notes - page 1-")
    assert result.md_path.name.endswith(".md")

    content = result.md_path.read_text()
    assert 'subject: "Test Notes"' in content
    assert f'attachment: "{pdf_filename}"' in content
    assert "received: 2026-01-26T11:30:00" in content
    assert "transcribed:" in content
    assert f"![[_attachments/{pdf_filename}]]" in content
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
    assert f'attachment: "{pdf_filename}"' in content
    assert 'error: "LLM failed"' in content
    assert "<!-- TRANSCRIPTION_FAILED: LLM failed -->" in content
    assert "transcribed:" not in content
