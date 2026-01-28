#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "imapclient>=3.0.0",
#     "rich>=13.0.0",
#     "llm",
#     "llm-gemini",
# ]
# ///
"""
rm2-pipe-obsidian: Capture Remarkable 2 handwritten notes via email to Obsidian markdown.

Monitors an IMAP mailbox for emails with PDF attachments from allowed senders,
transcribes handwritten notes using an LLM, and saves them as markdown files.

Required environment variables:
    IMAP_HOST          - IMAP server (e.g., imap.gmail.com)
    IMAP_USER          - Email account username
    IMAP_PASSWORD      - Password or app-specific password
    FILTER_TO_ADDRESS  - Target email address to filter (e.g., user+remarkable@gmail.com)
    ALLOWED_SENDERS    - Comma-separated list of allowed sender addresses

Usage:
    ./rm2-pipe-obsidian <output_dir> [--poll-interval=300] [--verbose] [--quiet]
"""
from __future__ import annotations

import argparse
import email
import logging
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Generator

from imapclient import IMAPClient
from rich.logging import RichHandler

logger = logging.getLogger(__name__)

# LLM Configuration
MODEL = "gemini/gemini-3-flash-preview"

PROMPT = """Transcribe this handwritten note verbatim. Output ONLY a single markdown
code block containing the transcription. Preserve the structure including:
- Bullet points and indentation
- Tables (as markdown tables)
- Paragraphs

Its ok to rejoin/wrap lines if it appears the original text was wrapping, but
maintain line breaks if they indicate structure or format.

Do not add any commentary, analysis, or text outside the code block."""


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class Attachment:
    filename: str
    content: bytes


@dataclass
class IncomingEmail:
    uid: int
    subject: str
    received: datetime
    attachments: list[Attachment]


@dataclass
class NoteResult:
    pdf_path: Path
    md_path: Path
    content: str | None
    error: str | None


# =============================================================================
# Configuration
# =============================================================================


class ConfigError(Exception):
    pass


@dataclass
class Config:
    imap_host: str
    imap_user: str
    imap_password: str
    filter_to_address: str
    allowed_senders: list[str]

    @classmethod
    def from_env(cls) -> Config:
        required = [
            "IMAP_HOST",
            "IMAP_USER",
            "IMAP_PASSWORD",
            "FILTER_TO_ADDRESS",
            "ALLOWED_SENDERS",
        ]
        missing = [var for var in required if not os.environ.get(var)]

        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

        return cls(
            imap_host=os.environ["IMAP_HOST"],
            imap_user=os.environ["IMAP_USER"],
            imap_password=os.environ["IMAP_PASSWORD"],
            filter_to_address=os.environ["FILTER_TO_ADDRESS"],
            allowed_senders=[s.strip() for s in os.environ["ALLOWED_SENDERS"].split(",")],
        )


# =============================================================================
# Email Monitor
# =============================================================================


class EmailMonitor:
    def __init__(self, config: Config):
        self.config = config

    @contextmanager
    def connect(self) -> Generator[IMAPClient, None, None]:
        logger.debug(f"Connecting to {self.config.imap_host}")
        client = IMAPClient(self.config.imap_host, ssl=True)
        try:
            client.login(self.config.imap_user, self.config.imap_password)
            client.select_folder("INBOX")
            logger.info(f"Connected to {self.config.imap_host} as {self.config.imap_user}")
            yield client
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def fetch_matching_emails(self, client: IMAPClient) -> Generator[IncomingEmail, None, None]:
        uids = client.search(["UNSEEN"])
        logger.debug(f"Found {len(uids)} unread emails")

        for uid in uids:
            fetch_result = client.fetch([uid], ["ENVELOPE", "RFC822"])
            if uid not in fetch_result:
                continue

            data = fetch_result[uid]
            envelope = data[b"ENVELOPE"]
            raw_email = data[b"RFC822"]

            if not self._matches_to_address(envelope):
                logger.debug(f"UID {uid}: TO address doesn't match filter")
                continue

            if not self._matches_allowed_sender(envelope):
                logger.debug(f"UID {uid}: Sender not in allowlist")
                continue

            attachments = self._extract_pdf_attachments(raw_email)
            if not attachments:
                logger.debug(f"UID {uid}: No PDF attachments")
                continue

            subject = self._decode_subject(envelope.subject)
            received = self._parse_date(envelope.date)

            yield IncomingEmail(
                uid=uid,
                subject=subject,
                received=received,
                attachments=attachments,
            )

    def mark_as_read(self, client: IMAPClient, email_obj: IncomingEmail) -> None:
        client.add_flags([email_obj.uid], [b"\\Seen"])
        logger.debug(f"Marked UID {email_obj.uid} as read")

    def _matches_to_address(self, envelope) -> bool:
        if not envelope.to:
            return False
        for addr in envelope.to:
            if addr.mailbox and addr.host:
                full_addr = f"{addr.mailbox.decode()}@{addr.host.decode()}"
                if full_addr.lower() == self.config.filter_to_address.lower():
                    return True
        return False

    def _matches_allowed_sender(self, envelope) -> bool:
        if not envelope.from_:
            return False
        for addr in envelope.from_:
            if addr.mailbox and addr.host:
                full_addr = f"{addr.mailbox.decode()}@{addr.host.decode()}"
                if full_addr.lower() in [s.lower() for s in self.config.allowed_senders]:
                    return True
        return False

    def _extract_pdf_attachments(self, raw_email: bytes) -> list[Attachment]:
        msg = email.message_from_bytes(raw_email)
        attachments = []

        for part in msg.walk():
            content_type = part.get_content_type()
            filename = part.get_filename()

            if content_type == "application/pdf" and filename:
                decoded_filename = self._decode_filename(filename)
                content = part.get_payload(decode=True)
                if content:
                    attachments.append(Attachment(filename=decoded_filename, content=content))

        return attachments

    def _decode_subject(self, subject: bytes | None) -> str:
        if not subject:
            return ""
        decoded_parts = decode_header(subject.decode("utf-8", errors="replace"))
        result = []
        for data, charset in decoded_parts:
            if isinstance(data, bytes):
                result.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(data)
        return "".join(result)

    def _decode_filename(self, filename: str) -> str:
        decoded_parts = decode_header(filename)
        result = []
        for data, charset in decoded_parts:
            if isinstance(data, bytes):
                result.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(data)
        return "".join(result)

    def _parse_date(self, date: datetime | bytes | None) -> datetime:
        if isinstance(date, datetime):
            return date
        if isinstance(date, bytes):
            return parsedate_to_datetime(date.decode())
        return datetime.now()


# =============================================================================
# Transcription Processor
# =============================================================================


class TranscriptionError(Exception):
    pass


class Processor:
    def transcribe_pdf(self, pdf_path: Path) -> str:
        logger.debug(f"Transcribing {pdf_path} with model {MODEL}")

        try:
            result = subprocess.run(
                ["llm", "-m", MODEL, "-a", str(pdf_path), PROMPT],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise TranscriptionError(f"llm command failed: {e.stderr}") from e
        except FileNotFoundError as e:
            raise TranscriptionError("llm command not found - is it installed?") from e

        return self._extract_markdown(result.stdout)

    def _extract_markdown(self, response: str) -> str:
        match = re.search(r"```(?:markdown)?\n(.*?)```", response, re.DOTALL)
        if not match:
            raise TranscriptionError("No markdown code block found in response")
        return match.group(1).strip()


# =============================================================================
# Markdown Writer
# =============================================================================


class Writer:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def pdf_exists(self, received: datetime, attachment: Attachment) -> bool:
        date_folder = self.output_dir / received.strftime("%Y-%m-%d")
        timestamp = received.strftime("%H:%M")
        stem = Path(attachment.filename).stem
        filename = f"{timestamp} - {stem}.pdf"
        return (date_folder / "_attachments" / filename).exists()

    def save_pdf(self, email_obj: IncomingEmail, attachment: Attachment) -> tuple[Path, str]:
        date_folder = self._ensure_date_folder(email_obj.received)
        timestamp = email_obj.received.strftime("%H:%M")
        stem = Path(attachment.filename).stem
        filename = f"{timestamp} - {stem}.pdf"
        pdf_path = date_folder / "_attachments" / filename
        pdf_path.write_bytes(attachment.content)
        logger.debug(f"Wrote PDF: {pdf_path}")
        return pdf_path, filename

    def write_markdown(
        self,
        email_obj: IncomingEmail,
        attachment: Attachment,
        pdf_path: Path,
        pdf_filename: str,
        content: str | None,
        error: str | None,
    ) -> NoteResult:
        date_folder = pdf_path.parent.parent

        stem = Path(pdf_filename).stem
        md_filename = f"{stem}.md"
        md_path = date_folder / md_filename

        if content is not None:
            md_content = self._render_note(email_obj, pdf_filename, content)
        else:
            md_content = self._render_error_note(email_obj, pdf_filename, error or "Unknown error")

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

    def _render_note(self, email_obj: IncomingEmail, pdf_filename: str, content: str) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        received = email_obj.received.isoformat(timespec="seconds")
        return f"""---
subject: "{email_obj.subject}"
attachment: "{pdf_filename}"
received: {received}
transcribed: {now}
---

![[_attachments/{pdf_filename}]]

{content}
"""

    def _render_error_note(
        self, email_obj: IncomingEmail, pdf_filename: str, error: str
    ) -> str:
        received = email_obj.received.isoformat(timespec="seconds")
        return f"""---
subject: "{email_obj.subject}"
attachment: "{pdf_filename}"
received: {received}
error: "{error}"
---

![[_attachments/{pdf_filename}]]

<!-- TRANSCRIPTION_FAILED: {error} -->
"""


# =============================================================================
# Main Logic
# =============================================================================


def setup_logging(verbose: bool, quiet: bool) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=verbose)],
    )


def process_batch(
    monitor: EmailMonitor,
    processor: Processor,
    writer: Writer,
    client: IMAPClient,
) -> int:
    emails = list(monitor.fetch_matching_emails(client))

    if not emails:
        return 0

    total_attachments = sum(len(e.attachments) for e in emails)
    logger.info(f"Found {len(emails)} emails with {total_attachments} attachments")

    processed = 0
    for email_obj in emails:
        for attachment in email_obj.attachments:
            if writer.pdf_exists(email_obj.received, attachment):
                logger.debug(f"Skipping {attachment.filename} - already exists")
                continue

            logger.info(f"Processing {attachment.filename}")

            pdf_path, pdf_filename = writer.save_pdf(email_obj, attachment)
            logger.info(f"Saved PDF to {pdf_path}")

            logger.info(f"Transcribing {attachment.filename}...")
            try:
                content = processor.transcribe_pdf(pdf_path)
                error = None
            except TranscriptionError as e:
                logger.warning(f"Transcription failed: {e}")
                content = None
                error = str(e)

            result = writer.write_markdown(
                email_obj, attachment, pdf_path, pdf_filename, content, error
            )

            if result.error:
                logger.warning(f"Created error note: {result.md_path}")
            else:
                logger.info(f"Created note: {result.md_path}")

            processed += 1

        monitor.mark_as_read(client, email_obj)

    return processed


def run_daemon(
    monitor: EmailMonitor,
    processor: Processor,
    writer: Writer,
    poll_interval: int,
) -> None:
    def handle_signal(signum, frame):
        logger.info("Shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while True:
        try:
            with monitor.connect() as client:
                count = process_batch(monitor, processor, writer, client)
                if count > 0:
                    logger.info(f"Processed {count} attachments")

                while True:
                    logger.debug(f"Entering IDLE (timeout={poll_interval}s)")
                    client.idle()
                    responses = client.idle_check(timeout=poll_interval)
                    client.idle_done()

                    if responses:
                        logger.debug(f"IDLE notification: {responses}")
                        count = process_batch(monitor, processor, writer, client)
                        if count > 0:
                            logger.info(f"Processed {count} attachments")

        except Exception as e:
            logger.warning(f"Connection error: {e}")
            logger.info("Reconnecting in 5s...")
            time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture Remarkable 2 handwritten notes via email to Obsidian markdown"
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Directory to write notes",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=300,
        help="Fallback polling interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only show errors",
    )
    args = parser.parse_args()

    setup_logging(args.verbose, args.quiet)

    try:
        config = Config.from_env()
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    if not args.output_dir.exists():
        logger.error(f"Output directory does not exist: {args.output_dir}")
        sys.exit(1)

    monitor = EmailMonitor(config)
    processor = Processor()
    writer = Writer(args.output_dir)

    logger.info(f"Starting rm2-pipe-obsidian, writing to {args.output_dir}")
    run_daemon(monitor, processor, writer, args.poll_interval)


if __name__ == "__main__":
    main()
