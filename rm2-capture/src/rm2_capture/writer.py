import logging
from datetime import datetime
from pathlib import Path

from .models import Attachment, IncomingEmail, NoteResult

logger = logging.getLogger(__name__)


class Writer:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def pdf_exists(self, received: datetime, filename: str) -> bool:
        date_folder = self.output_dir / received.strftime("%Y-%m-%d")
        return (date_folder / "_attachments" / filename).exists()

    def save_pdf(self, email: IncomingEmail, attachment: Attachment) -> Path:
        """
        Save PDF attachment to the output directory.

        Returns the path to the saved PDF.
        """
        date_folder = self._ensure_date_folder(email.received)
        pdf_path = date_folder / "_attachments" / attachment.filename
        pdf_path.write_bytes(attachment.content)
        logger.debug(f"Wrote PDF: {pdf_path}")
        return pdf_path

    def write_markdown(
        self,
        email: IncomingEmail,
        attachment: Attachment,
        pdf_path: Path,
        content: str | None,
        error: str | None,
    ) -> NoteResult:
        """
        Write markdown note to the output directory.

        Assumes PDF has already been saved via save_pdf.
        """
        date_folder = pdf_path.parent.parent

        timestamp = email.received.strftime("%H:%M")
        stem = Path(attachment.filename).stem
        md_filename = f"{timestamp} - {stem}.md"
        md_path = date_folder / md_filename

        if content is not None:
            md_content = self._render_note(email, attachment, content)
        else:
            md_content = self._render_error_note(email, attachment, error or "Unknown error")

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

    def _render_note(self, email: IncomingEmail, attachment: Attachment, content: str) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        received = email.received.isoformat(timespec="seconds")
        return f"""---
subject: "{email.subject}"
attachment: "{attachment.filename}"
received: {received}
transcribed: {now}
---

![[_attachments/{attachment.filename}]]

{content}
"""

    def _render_error_note(self, email: IncomingEmail, attachment: Attachment, error: str) -> str:
        received = email.received.isoformat(timespec="seconds")
        return f"""---
subject: "{email.subject}"
attachment: "{attachment.filename}"
received: {received}
error: "{error}"
---

![[_attachments/{attachment.filename}]]

<!-- TRANSCRIPTION_FAILED: {error} -->
"""
