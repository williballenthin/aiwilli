#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "imapclient>=3.0.0",
#     "rich>=13.0.0",
# ]
# ///
"""
vnote-pipe-obsidian: Capture emails to Obsidian markdown.

Monitors an IMAP mailbox for emails from allowed senders,
and saves the body text as markdown files.

Required environment variables:
    IMAP_HOST                - IMAP server (e.g., imap.gmail.com)
    IMAP_USER                - Email account username
    IMAP_PASSWORD            - Password or app-specific password
    VNOTE_FILTER_TO_ADDRESS  - Target email address to filter (e.g., user+vnote@gmail.com)
    VNOTE_ALLOWED_SENDERS    - Comma-separated list of allowed sender addresses

Usage:
    ./vnote-pipe-obsidian <output_dir> [--poll-interval=300] [--verbose] [--quiet]
"""
from __future__ import annotations

import argparse
import email
import logging
import os
import signal
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
    body: str
    attachments: list[Attachment]


@dataclass
class NoteResult:
    md_path: Path
    attachment_paths: list[Path]


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
            "VNOTE_FILTER_TO_ADDRESS",
            "VNOTE_ALLOWED_SENDERS",
        ]
        missing = [var for var in required if not os.environ.get(var)]

        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

        return cls(
            imap_host=os.environ["IMAP_HOST"],
            imap_user=os.environ["IMAP_USER"],
            imap_password=os.environ["IMAP_PASSWORD"],
            filter_to_address=os.environ["VNOTE_FILTER_TO_ADDRESS"],
            allowed_senders=[s.strip() for s in os.environ["VNOTE_ALLOWED_SENDERS"].split(",")],
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

            subject = self._decode_subject(envelope.subject)
            received = self._parse_date(envelope.date)
            body = self._extract_body(raw_email)
            attachments = self._extract_attachments(raw_email)

            yield IncomingEmail(
                uid=uid,
                subject=subject,
                received=received,
                body=body,
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

    def _extract_body(self, raw_email: bytes) -> str:
        msg = email.message_from_bytes(raw_email)
        body_parts = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body_parts.append(payload.decode(charset, errors="replace"))
        else:
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))

        return "\n".join(body_parts).strip()

    def _extract_attachments(self, raw_email: bytes) -> list[Attachment]:
        msg = email.message_from_bytes(raw_email)
        attachments = []

        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            filename = part.get_filename()

            if "attachment" in content_disposition and filename:
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
# Markdown Writer
# =============================================================================


class Writer:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def note_exists(self, received: datetime) -> bool:
        date_folder = self.output_dir / received.strftime("%Y-%m-%d")
        timestamp = received.strftime("%H:%M")
        filename = f"{timestamp} - transcription.md"
        return (date_folder / filename).exists()

    def write_note(self, email_obj: IncomingEmail) -> NoteResult:
        date_folder = self._ensure_date_folder(email_obj.received)
        timestamp = email_obj.received.strftime("%H:%M")

        # Save attachments
        attachment_paths = []
        for attachment in email_obj.attachments:
            att_path = self._save_attachment(date_folder, timestamp, attachment)
            attachment_paths.append(att_path)
            logger.debug(f"Saved attachment: {att_path}")

        # Write markdown
        md_filename = f"{timestamp} - transcription.md"
        md_path = date_folder / md_filename
        md_content = self._render_note(email_obj, attachment_paths)
        md_path.write_text(md_content)
        logger.debug(f"Wrote note: {md_path}")

        return NoteResult(md_path=md_path, attachment_paths=attachment_paths)

    def _ensure_date_folder(self, received: datetime) -> Path:
        date_folder = self.output_dir / received.strftime("%Y-%m-%d")
        date_folder.mkdir(parents=True, exist_ok=True)
        (date_folder / "_attachments").mkdir(exist_ok=True)
        return date_folder

    def _save_attachment(self, date_folder: Path, timestamp: str, attachment: Attachment) -> Path:
        att_filename = f"{timestamp} - {attachment.filename}"
        att_path = date_folder / "_attachments" / att_filename
        att_path.write_bytes(attachment.content)
        return att_path

    def _render_note(self, email_obj: IncomingEmail, attachment_paths: list[Path]) -> str:
        now = datetime.now().isoformat(timespec="seconds")
        received = email_obj.received.isoformat(timespec="seconds")

        # Build attachment links
        attachment_links = ""
        if attachment_paths:
            links = [f"![[_attachments/{p.name}]]" for p in attachment_paths]
            attachment_links = "\n" + "\n".join(links) + "\n"

        return f"""---
subject: "{email_obj.subject}"
received: {received}
saved: {now}
---
{attachment_links}
{email_obj.body}
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
    writer: Writer,
    client: IMAPClient,
) -> int:
    emails = list(monitor.fetch_matching_emails(client))

    if not emails:
        return 0

    logger.info(f"Found {len(emails)} matching emails")

    processed = 0
    for email_obj in emails:
        if writer.note_exists(email_obj.received):
            logger.debug(f"Skipping email from {email_obj.received} - already exists")
            monitor.mark_as_read(client, email_obj)
            continue

        logger.info(f"Processing email: {email_obj.subject}")

        result = writer.write_note(email_obj)
        logger.info(f"Created note: {result.md_path}")

        if result.attachment_paths:
            logger.info(f"Saved {len(result.attachment_paths)} attachment(s)")

        monitor.mark_as_read(client, email_obj)
        processed += 1

    return processed


def run_daemon(
    monitor: EmailMonitor,
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
                count = process_batch(monitor, writer, client)
                if count > 0:
                    logger.info(f"Processed {count} emails")

                while True:
                    logger.debug(f"Entering IDLE (timeout={poll_interval}s)")
                    client.idle()
                    responses = client.idle_check(timeout=poll_interval)
                    client.idle_done()

                    if responses:
                        logger.debug(f"IDLE notification: {responses}")
                        count = process_batch(monitor, writer, client)
                        if count > 0:
                            logger.info(f"Processed {count} emails")

        except Exception as e:
            logger.warning(f"Connection error: {e}")
            logger.info("Reconnecting in 5s...")
            time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture emails to Obsidian markdown"
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
    writer = Writer(args.output_dir)

    logger.info(f"Starting vnote-pipe-obsidian, writing to {args.output_dir}")
    run_daemon(monitor, writer, args.poll_interval)


if __name__ == "__main__":
    main()
