import email
import logging
from contextlib import contextmanager
from datetime import datetime
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Generator

from imapclient import IMAPClient

from .config import Config
from .models import Attachment, IncomingEmail

logger = logging.getLogger(__name__)


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
            logger.debug("Connected and selected INBOX")
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
