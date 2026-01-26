import hashlib
import logging
from datetime import datetime
from pathlib import Path

from .models import Attachment, IncomingEmail, NoteResult

logger = logging.getLogger(__name__)


def hashed_filename(original_filename: str, content: bytes) -> str:
    """
    Generate a filename with content hash to prevent collisions.

    Format: {stem}-{hash}.{ext}
    Example: "Notes - page 1.pdf" -> "Notes - page 1-a1b2c3d4.pdf"
    """
    stem = Path(original_filename).stem
    ext = Path(original_filename).suffix
    content_hash = hashlib.md5(content).hexdigest()[:8]
    return f"{stem}-{content_hash}{ext}"


class Writer:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def pdf_exists(self, received: datetime, attachment: Attachment) -> bool:
        date_folder = self.output_dir / received.strftime("%Y-%m-%d")
        filename = hashed_filename(attachment.filename, attachment.content)
        return (date_folder / "_attachments" / filename).exists()

    def save_pdf(self, email: IncomingEmail, attachment: Attachment) -> tuple[Path, str]:
        """
        Save PDF attachment to the output directory.

        Returns tuple of (path to saved PDF, hashed filename).
        """
        date_folder = self._ensure_date_folder(email.received)
        filename = hashed_filename(attachment.filename, attachment.content)
        pdf_path = date_folder / "_attachments" / filename
        pdf_path.write_bytes(attachment.content)
        logger.debug(f"Wrote PDF: {pdf_path}")
        return pdf_path, filename

    def write_markdown(
        self,
        email: IncomingEmail,
        attachment: Attachment,
        pdf_path: Path,
        pdf_filename: str,
        content: str | None,
        error: str | None,
    ) -> NoteResult:
        """
        Write markdown note to the output directory.

        Assumes PDF has already been saved via save_pdf.
        """
        date_folder = pdf_path.parent.parent

        timestamp = email.received.strftime("%H:%M")
        stem = Path(pdf_filename).stem
        md_filename = f"{timestamp} - {stem}.md"
        md_path = date_folder / md_filename

        if content is not None:
            md_content = self._render_note(email, pdf_filename, content)
        else:
            md_content = self._render_error_note(email, pdf_filename, error or "Unknown error")

        md_path.write_text(md_content)
        logger.debug(f"Wrote note: {md_path}")

        return NoteResult(
            pdf_path=pdf_path,
            md_path=md_path,
            content=content,
            error=error,
        )

    def _ensure_date_folder(self, received: datetime) -> Path:
        date_folder = self.output_dir / received.strftime("%Y-%m-%d")
        date_folder.mkdir(parents=True, exist_ok=True)
        (date_folder / "_attachments").mkdir(exist_ok=True)
        return date_folder

    def _render_note(self, email: IncomingEmail, pdf_filename: str, content: str) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        received = email.received.isoformat(timespec="seconds")
        return f"""---
subject: "{email.subject}"
attachment: "{pdf_filename}"
received: {received}
transcribed: {now}
---

![[_attachments/{pdf_filename}]]

{content}
"""

    def _render_error_note(self, email: IncomingEmail, pdf_filename: str, error: str) -> str:
        received = email.received.isoformat(timespec="seconds")
        return f"""---
subject: "{email.subject}"
attachment: "{pdf_filename}"
received: {received}
error: "{error}"
---

![[_attachments/{pdf_filename}]]

<!-- TRANSCRIPTION_FAILED: {error} -->
"""
