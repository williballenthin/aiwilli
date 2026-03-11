from __future__ import annotations

import argparse
import datetime as dt_mod
import email
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol

from imapclient import IMAPClient
from jinja2 import Environment
from pydantic import BaseModel, ValidationError
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.spinner import Spinner
from rich.text import Text

logger = logging.getLogger(__name__)
STDERR_CONSOLE = Console(stderr=True)

VOICE_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
subject: \"{{ subject }}\"
received: {{ received }}
saved: {{ saved }}
---
{% if attachment_links %}
{{ attachment_links }}

{% endif %}
{{ body }}
"""
)

RM2_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
subject: \"{{ subject }}\"
attachment: \"{{ attachment_filename }}\"
received: {{ received }}
transcribed: {{ transcribed }}
---

![[_attachments/{{ attachment_filename }}]]

{{ content }}
"""
)

RM2_ERROR_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
subject: \"{{ subject }}\"
attachment: \"{{ attachment_filename }}\"
received: {{ received }}
error: \"{{ error }}\"
---

![[_attachments/{{ attachment_filename }}]]

<!-- TRANSCRIPTION_FAILED: {{ error }} -->
"""
)

TODO_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
subject: \"{{ subject }}\"
received: {{ received }}
saved: {{ saved }}
---

## {{ subject }}

{{ body }}
{% if attachment_links %}

{{ attachment_links }}
{% endif %}
"""
)

RM2_MODEL = "gemini/gemini-3-flash-preview"
RM2_PROMPT = """Transcribe this handwritten note verbatim. Output ONLY a single markdown
code block containing the transcription. Preserve the structure including:
- Bullet points and indentation
- Tables (as markdown tables)
- Paragraphs

Its ok to rejoin/wrap lines if it appears the original text was wrapping, but
maintain line breaks if they indicate structure or format.

Do not add any commentary, analysis, or text outside the code block."""

BASE_EMAIL_ENV = "WEAVE_BASE_EMAIL"
VOICE_VARIANT = "+vnote"
RM2_VARIANT = "+rm2"
TODO_VARIANT = "+todo"
SINK_RELATIVE_PATH = Path("sink")

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]
GOOGLE_CONFIG_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "wballenthin" / "weave"
)
GOOGLE_CREDENTIALS_PATH = GOOGLE_CONFIG_DIR / "credentials.json"
GOOGLE_TOKEN_PATH = GOOGLE_CONFIG_DIR / "token.json"

MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
SECTION_DATE_RE = re.compile(r"^## (\w{3}) (\d{1,2}), (\d{4})")

CALENDAR_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
source: "{{ source }}"
type: {{ doc_type }}
calendar: primary
event: "{{ event_name }}"
date: {{ date }}
attended: {{ attended }}
url: "{{ doc_url }}"
event_url: "{{ event_url }}"
attendees:
{% for a in attendees %}
  - name: "{{ a.get("displayName", "") }}"
    email: "{{ a["email"] }}"
    status: "{{ a.get("responseStatus", "unknown") }}"
{% endfor %}
---

"""
)


class ConfigError(Exception):
    """Raised when startup configuration is invalid."""


class TranscriptionError(Exception):
    """Raised when PDF transcription fails."""


def get_variant_address(base_email: str, variant: str) -> str:
    """Build a plus-address variant from a base mailbox address.

    Raises:
        ConfigError: If base email or variant is malformed.
    """
    if "@" not in base_email:
        raise ConfigError(f"Invalid {BASE_EMAIL_ENV} value: {base_email}")
    local, domain = base_email.split("@", 1)
    if not local or not domain:
        raise ConfigError(f"Invalid {BASE_EMAIL_ENV} value: {base_email}")
    if not variant.startswith("+"):
        raise ConfigError(f"Invalid variant format: {variant}")
    return f"{local}{variant}@{domain}"


def get_date_folder(output_dir: Path, received: datetime) -> Path:
    date_folder = output_dir / received.strftime("%Y/%m/%d")
    date_folder.mkdir(parents=True, exist_ok=True)
    (date_folder / "_attachments").mkdir(exist_ok=True)
    return date_folder


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[/\\:*?"<>|]', '-', name)
    sanitized = sanitized.strip(" -")
    return sanitized[:100] if sanitized else "untitled"


@contextmanager
def show_spinner(message: str) -> Generator[None, None, None]:
    """Display a transient spinner on stderr."""
    spinner = Spinner("dots", text=Text(message))
    with Live(
        spinner,
        console=STDERR_CONSOLE,
        transient=True,
        refresh_per_second=20,
    ):
        yield


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes


@dataclass(frozen=True)
class IncomingMessage:
    uid: int
    subject: str
    received: datetime
    sender: str
    to_addresses: list[str]
    raw_email: bytes


@dataclass(frozen=True)
class HandlerResult:
    handled: bool
    created_paths: list[Path]
    note_paths: list[Path]
    todo_entries: list[tuple[str, Path]] = field(default_factory=list)


class MessageHandler(Protocol):
    def handle_message(self, message: IncomingMessage) -> HandlerResult:
        """Process a routed message."""


class RouteConfig(BaseModel):
    name: str
    to_address: str
    allowed_senders: tuple[str, ...]
    handler_key: str
    sink_relative: Path


def _parse_senders(env_var: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in os.environ[env_var].split(",") if s.strip())


class WeaveConfig(BaseModel):
    imap_host: str
    imap_user: str
    imap_password: str
    vault_root: Path
    poll_interval_seconds: int
    routes: tuple[RouteConfig, ...]
    calendar_source: str = "@hex-rays.com"
    calendar_enabled: bool = True

    @classmethod
    def from_runtime(
        cls,
        vault_root: Path,
        poll_interval_seconds: int,
        calendar_source: str = "@hex-rays.com",
        calendar_enabled: bool = True,
    ) -> WeaveConfig:
        """Build runtime configuration from args and environment.

        Raises:
            ConfigError: If required environment variables are missing.
        """
        required = ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", BASE_EMAIL_ENV, "WEAVE_ALLOWED_SENDERS")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")
        base_email = os.environ[BASE_EMAIL_ENV]
        allowed_senders = _parse_senders("WEAVE_ALLOWED_SENDERS")
        try:
            return cls(
                imap_host=os.environ["IMAP_HOST"],
                imap_user=os.environ["IMAP_USER"],
                imap_password=os.environ["IMAP_PASSWORD"],
                vault_root=vault_root,
                poll_interval_seconds=poll_interval_seconds,
                calendar_source=calendar_source,
                calendar_enabled=calendar_enabled,
                routes=(
                    RouteConfig(
                        name="voice-notes",
                        to_address=get_variant_address(base_email, VOICE_VARIANT),
                        allowed_senders=allowed_senders,
                        handler_key="voice",
                        sink_relative=SINK_RELATIVE_PATH,
                    ),
                    RouteConfig(
                        name="remarkable",
                        to_address=get_variant_address(base_email, RM2_VARIANT),
                        allowed_senders=allowed_senders,
                        handler_key="rm2",
                        sink_relative=SINK_RELATIVE_PATH,
                    ),
                    RouteConfig(
                        name="todo",
                        to_address=get_variant_address(base_email, TODO_VARIANT),
                        allowed_senders=allowed_senders,
                        handler_key="todo",
                        sink_relative=SINK_RELATIVE_PATH,
                    ),
                ),
            )
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc


class RouteResolver:
    def __init__(self, routes: tuple[RouteConfig, ...]):
        self.routes = routes

    def get_route_for_message(self, to_addresses: Iterable[str], sender: str) -> RouteConfig | None:
        sender_normalized = sender.lower()
        normalized_to = {address.lower() for address in to_addresses}
        for route in self.routes:
            if route.to_address.lower() not in normalized_to:
                continue
            allowed = {item.lower() for item in route.allowed_senders}
            if sender_normalized in allowed:
                return route
        return None


class MailboxMonitor:
    def __init__(self, config: WeaveConfig):
        self.config = config

    @contextmanager
    def connect(self) -> Generator[IMAPClient, None, None]:
        logger.debug("connecting to %s", self.config.imap_host)
        client = IMAPClient(self.config.imap_host, ssl=True)
        try:
            client.login(self.config.imap_user, self.config.imap_password)
            client.select_folder("INBOX")
            logger.info("connected to %s as %s", self.config.imap_host, self.config.imap_user)
            yield client
        finally:
            try:
                client.logout()
            except Exception:
                pass

    def get_unseen_messages(self, client: IMAPClient) -> list[IncomingMessage]:
        uids = client.search(["UNSEEN"])
        logger.debug("found %s unread emails", len(uids))
        messages: list[IncomingMessage] = []
        for uid in uids:
            fetch_result = client.fetch([uid], ["ENVELOPE", "RFC822"])
            if uid not in fetch_result:
                continue
            data = fetch_result[uid]
            envelope = data[b"ENVELOPE"]
            raw_email = data[b"RFC822"]
            to_addresses = self.get_addresses(getattr(envelope, "to", None))
            sender = self.get_first_address(getattr(envelope, "from_", None))
            messages.append(
                IncomingMessage(
                    uid=uid,
                    subject=self.get_decoded_header(getattr(envelope, "subject", None)),
                    received=self.get_parsed_date(getattr(envelope, "date", None)),
                    sender=sender,
                    to_addresses=to_addresses,
                    raw_email=raw_email,
                )
            )
        return messages

    def mark_message_seen(self, client: IMAPClient, message: IncomingMessage) -> None:
        client.add_flags([message.uid], [b"\\Seen"])
        logger.debug("marked uid %s as read", message.uid)

    def get_addresses(self, address_objects: Iterable[object] | None) -> list[str]:
        if not address_objects:
            return []
        addresses: list[str] = []
        for addr in address_objects:
            mailbox = getattr(addr, "mailbox", None)
            host = getattr(addr, "host", None)
            if not mailbox or not host:
                continue
            mailbox_text = mailbox.decode() if isinstance(mailbox, bytes) else str(mailbox)
            host_text = host.decode() if isinstance(host, bytes) else str(host)
            addresses.append(f"{mailbox_text}@{host_text}")
        return addresses

    def get_first_address(self, address_objects: Iterable[object] | None) -> str:
        addresses = self.get_addresses(address_objects)
        if not addresses:
            return ""
        return addresses[0]

    def get_decoded_header(self, value: bytes | str | None) -> str:
        if value is None:
            return ""
        raw = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        chunks = decode_header(raw)
        parts: list[str] = []
        for chunk, charset in chunks:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            else:
                parts.append(chunk)
        return "".join(parts)

    def get_parsed_date(self, value: datetime | bytes | None) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, bytes):
            return parsedate_to_datetime(value.decode())
        return datetime.now(tz=UTC)


class PdfTranscriber(Protocol):
    def get_transcription(self, pdf_path: Path) -> str:
        """Return markdown content extracted from a PDF.

        Raises:
            TranscriptionError: If transcription fails.
        """


class LlmPdfTranscriber:
    def __init__(self, model: str = RM2_MODEL):
        self.model = model

    def get_transcription(self, pdf_path: Path) -> str:
        try:
            result = subprocess.run(
                ["llm", "-m", self.model, "-a", str(pdf_path), RM2_PROMPT],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise TranscriptionError(f"llm command failed: {exc.stderr}") from exc
        except FileNotFoundError as exc:
            raise TranscriptionError("llm command not found") from exc
        return self.get_markdown_block(result.stdout)

    def get_markdown_block(self, value: str) -> str:
        match = re.search(r"```(?:markdown)?\n(.*?)```", value, re.DOTALL)
        if not match:
            raise TranscriptionError("No markdown code block found in response")
        return match.group(1).strip()


class VoiceNoteHandler:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def handle_message(self, message: IncomingMessage) -> HandlerResult:
        date_folder = get_date_folder(self.output_dir, message.received)
        timestamp = message.received.strftime("%H%M")
        note_path = date_folder / f"{timestamp} - transcription.md"
        if note_path.exists():
            logger.debug("voice note already exists at %s", note_path)
            return HandlerResult(handled=True, created_paths=[], note_paths=[])
        parsed = email.message_from_bytes(message.raw_email)
        body = self.get_plain_text_body(parsed)
        attachments = self.get_attachments(parsed)
        attachment_paths: list[Path] = []
        for attachment in attachments:
            path = date_folder / "_attachments" / f"{timestamp} - {attachment.filename}"
            path.write_bytes(attachment.content)
            attachment_paths.append(path)
        attachment_links = "\n".join(f"![[_attachments/{path.name}]]" for path in attachment_paths)
        content = VOICE_TEMPLATE.render(
            subject=message.subject,
            received=message.received.isoformat(timespec="seconds"),
            saved=datetime.now(tz=UTC).isoformat(timespec="seconds"),
            attachment_links=attachment_links,
            body=body,
        )
        note_path.write_text(content)
        created_paths = [note_path, *attachment_paths]
        return HandlerResult(handled=True, created_paths=created_paths, note_paths=[note_path])

    def get_plain_text_body(self, message: Message) -> str:
        body_parts: list[str] = []
        if message.is_multipart():
            for part in message.walk():
                disposition = str(part.get("Content-Disposition", "")).lower()
                if "attachment" in disposition:
                    continue
                if part.get_content_type() != "text/plain":
                    continue
                payload = part.get_payload(decode=True)
                if not isinstance(payload, bytes):
                    continue
                charset = part.get_content_charset() or "utf-8"
                body_parts.append(payload.decode(charset, errors="replace"))
        else:
            if message.get_content_type() == "text/plain":
                payload = message.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = message.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
        return "\n".join(body_parts).strip()

    def get_attachments(self, message: Message) -> list[Attachment]:
        attachments: list[Attachment] = []
        for part in message.walk():
            disposition = str(part.get("Content-Disposition", "")).lower()
            filename = part.get_filename()
            if "attachment" not in disposition or not filename:
                continue
            content = part.get_payload(decode=True)
            if not isinstance(content, bytes):
                continue
            attachments.append(
                Attachment(filename=self.get_decoded_filename(filename), content=content)
            )
        return attachments

    def get_decoded_filename(self, filename: str) -> str:
        chunks = decode_header(filename)
        parts: list[str] = []
        for chunk, charset in chunks:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            elif isinstance(chunk, str):
                parts.append(chunk)
            else:
                parts.append(str(chunk))
        return "".join(parts)


class TodoHandler:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def handle_message(self, message: IncomingMessage) -> HandlerResult:
        date_folder = get_date_folder(self.output_dir, message.received)
        timestamp = message.received.strftime("%H%M")
        slug = sanitize_filename(message.subject)
        note_path = date_folder / f"{timestamp} - {slug}.md"
        if note_path.exists():
            logger.debug("todo note already exists at %s", note_path)
            return HandlerResult(handled=True, created_paths=[], note_paths=[])
        parsed = email.message_from_bytes(message.raw_email)
        body = self.get_plain_text_body(parsed)
        attachments = self.get_attachments(parsed)
        attachment_paths: list[Path] = []
        for attachment in attachments:
            path = date_folder / "_attachments" / f"{timestamp} - {attachment.filename}"
            path.write_bytes(attachment.content)
            attachment_paths.append(path)
        attachment_links = "\n".join(
            f"![[_attachments/{path.name}]]" for path in attachment_paths
        )
        content = TODO_TEMPLATE.render(
            subject=message.subject,
            received=message.received.isoformat(timespec="seconds"),
            saved=datetime.now(tz=UTC).isoformat(timespec="seconds"),
            body=body,
            attachment_links=attachment_links,
        )
        note_path.write_text(content)
        created_paths = [note_path, *attachment_paths]
        return HandlerResult(
            handled=True,
            created_paths=created_paths,
            note_paths=[],
            todo_entries=[(message.subject, note_path)],
        )

    def get_plain_text_body(self, message: Message) -> str:
        body_parts: list[str] = []
        if message.is_multipart():
            for part in message.walk():
                disposition = str(part.get("Content-Disposition", "")).lower()
                if "attachment" in disposition:
                    continue
                if part.get_content_type() != "text/plain":
                    continue
                payload = part.get_payload(decode=True)
                if not isinstance(payload, bytes):
                    continue
                charset = part.get_content_charset() or "utf-8"
                body_parts.append(payload.decode(charset, errors="replace"))
        else:
            if message.get_content_type() == "text/plain":
                payload = message.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = message.get_content_charset() or "utf-8"
                    body_parts.append(payload.decode(charset, errors="replace"))
        return "\n".join(body_parts).strip()

    def get_attachments(self, message: Message) -> list[Attachment]:
        attachments: list[Attachment] = []
        for part in message.walk():
            disposition = str(part.get("Content-Disposition", "")).lower()
            filename = part.get_filename()
            if "attachment" not in disposition or not filename:
                continue
            content = part.get_payload(decode=True)
            if not isinstance(content, bytes):
                continue
            attachments.append(
                Attachment(filename=self.get_decoded_filename(filename), content=content)
            )
        return attachments

    def get_decoded_filename(self, filename: str) -> str:
        chunks = decode_header(filename)
        parts: list[str] = []
        for chunk, charset in chunks:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            elif isinstance(chunk, str):
                parts.append(chunk)
            else:
                parts.append(str(chunk))
        return "".join(parts)


class RemarkableSnapshotHandler:
    def __init__(self, output_dir: Path, transcriber: PdfTranscriber):
        self.output_dir = output_dir
        self.transcriber = transcriber

    def handle_message(self, message: IncomingMessage) -> HandlerResult:
        parsed = email.message_from_bytes(message.raw_email)
        attachments = self.get_pdf_attachments(parsed)
        if not attachments:
            logger.debug("message %s has no PDF attachments", message.uid)
            return HandlerResult(handled=False, created_paths=[], note_paths=[])
        date_folder = get_date_folder(self.output_dir, message.received)
        timestamp = message.received.strftime("%H%M")
        created_paths: list[Path] = []
        note_paths: list[Path] = []
        for attachment in attachments:
            stem = Path(attachment.filename).stem
            pdf_filename = f"{timestamp} - {stem}.pdf"
            pdf_path = date_folder / "_attachments" / pdf_filename
            if not pdf_path.exists():
                pdf_path.write_bytes(attachment.content)
                created_paths.append(pdf_path)
            with show_spinner(f"Transcribing {pdf_filename}"):
                try:
                    content = self.transcriber.get_transcription(pdf_path)
                    error = None
                except TranscriptionError as exc:
                    content = None
                    error = str(exc)
            md_path = date_folder / f"{timestamp} - {stem}.md"
            rendered = self.get_markdown(message, pdf_filename, content, error)
            md_path.write_text(rendered)
            created_paths.append(md_path)
            note_paths.append(md_path)
        return HandlerResult(handled=True, created_paths=created_paths, note_paths=note_paths)

    def get_pdf_attachments(self, message: Message) -> list[Attachment]:
        attachments: list[Attachment] = []
        for part in message.walk():
            if part.get_content_type() != "application/pdf":
                continue
            filename = part.get_filename()
            if not filename:
                continue
            content = part.get_payload(decode=True)
            if not isinstance(content, bytes):
                continue
            attachments.append(
                Attachment(filename=self.get_decoded_filename(filename), content=content)
            )
        return attachments

    def get_decoded_filename(self, filename: str) -> str:
        chunks = decode_header(filename)
        parts: list[str] = []
        for chunk, charset in chunks:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            elif isinstance(chunk, str):
                parts.append(chunk)
            else:
                parts.append(str(chunk))
        return "".join(parts)

    def get_markdown(
        self,
        message: IncomingMessage,
        pdf_filename: str,
        content: str | None,
        error: str | None,
    ) -> str:
        if content is not None:
            return RM2_TEMPLATE.render(
                subject=message.subject,
                attachment_filename=pdf_filename,
                received=message.received.isoformat(timespec="seconds"),
                transcribed=datetime.now(tz=UTC).isoformat(timespec="seconds"),
                content=content,
            )
        return RM2_ERROR_TEMPLATE.render(
            subject=message.subject,
            attachment_filename=pdf_filename,
            received=message.received.isoformat(timespec="seconds"),
            error=error or "Unknown error",
        )


def extract_section_for_date(md_text: str, target_date: dt_mod.date) -> str | None:
    lines = md_text.split("\n")
    sections: list[tuple[dt_mod.date, int]] = []
    for i, line in enumerate(lines):
        m = SECTION_DATE_RE.match(line)
        if m:
            month = MONTHS.get(m.group(1))
            if month:
                section_date = dt_mod.date(int(m.group(3)), month, int(m.group(2)))
                sections.append((section_date, i))
    for idx, (section_date, start_line) in enumerate(sections):
        if section_date != target_date:
            continue
        end_line = sections[idx + 1][1] if idx + 1 < len(sections) else len(lines)
        return "\n".join(lines[start_line:end_line]).strip()
    return None


def is_gemini_notes(att_title: str) -> bool:
    return att_title.lower().startswith("notes by gemini") or (
        " - Notes by Gemini" in att_title
    )


def is_shared_notes(att_title: str) -> bool:
    return att_title.lower().startswith("notes - ") or att_title.lower().startswith("notes -\u00a0")


class DriveExporter(Protocol):
    def export_document(self, file_id: str) -> bytes:
        """Export a Google Doc as markdown bytes.

        Raises:
            Exception: If the export fails (e.g. access denied).
        """

    def get_media(self, file_id: str) -> bytes:
        """Download raw file content (e.g. chat transcript).

        Raises:
            Exception: If the download fails.
        """


class GoogleDriveExporter:
    def __init__(self, credentials: object):
        from googleapiclient.discovery import build

        self.service = build("drive", "v3", credentials=credentials)

    def export_document(self, file_id: str) -> bytes:
        result: bytes = self.service.files().export(
            fileId=file_id, mimeType="text/markdown"
        ).execute()
        return result

    def get_media(self, file_id: str) -> bytes:
        result: bytes = self.service.files().get_media(fileId=file_id).execute()
        return result


class CalendarScraper:
    def __init__(self, output_dir: Path, source: str, drive_exporter: DriveExporter):
        self.output_dir = output_dir
        self.source = source
        self.drive_exporter = drive_exporter

    @staticmethod
    def get_google_credentials() -> object:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if GOOGLE_TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), GOOGLE_SCOPES)  # type: ignore[no-untyped-call]
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(GOOGLE_CREDENTIALS_PATH), GOOGLE_SCOPES
                )
                creds = flow.run_local_server(port=0)
            GOOGLE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            GOOGLE_TOKEN_PATH.write_text(creds.to_json())
        return creds

    def scrape_once(self) -> list[tuple[datetime, Path]]:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        creds = self.get_google_credentials()
        cal = build("calendar", "v3", credentials=creds)

        now = datetime.now(tz=UTC)
        week_ago = (now - dt_mod.timedelta(days=7)).isoformat()

        logger.info("fetching calendar events from past 7 days")
        events: list[dict[str, Any]] = (
            cal.events()
            .list(
                calendarId="primary",
                timeMin=week_ago,
                timeMax=now.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
            .get("items", [])
        )
        logger.info("found %d calendar events", len(events))

        results: list[tuple[datetime, Path]] = []
        for event in events:
            self_attendee = next(
                (a for a in event.get("attendees", []) if a.get("self")),
                None,
            )
            if self_attendee:
                attended = self_attendee.get("responseStatus") == "accepted"
            else:
                attended = True

            start_raw = event["start"].get("dateTime", event["start"].get("date"))
            start_dt = datetime.fromisoformat(start_raw)
            event_name = sanitize_filename(event.get("summary", "Untitled"))
            event_url = event.get("htmlLink", "")
            attendees: list[dict[str, str]] = event.get("attendees", [])
            all_attachments: list[dict[str, str]] = event.get("attachments", [])

            doc_attachments = [
                a for a in all_attachments
                if a.get("mimeType") == "application/vnd.google-apps.document"
            ]
            chat_attachments = [
                a for a in all_attachments
                if a.get("mimeType") == "text/plain" and a.get("title", "").endswith("- Chat")
            ]

            if not doc_attachments and not chat_attachments:
                continue

            day_dir = get_date_folder(self.output_dir, start_dt)
            time_prefix = start_dt.strftime("%H%M")
            base_name = f"{time_prefix} - {event_name}"
            has_multiple_docs = len(doc_attachments) > 1

            for att in doc_attachments:
                file_id = att["fileId"]
                att_title = att.get("title", "")

                if has_multiple_docs and is_gemini_notes(att_title):
                    name = f"{base_name} (Gemini)"
                else:
                    name = base_name

                out_path = day_dir / f"{name}.md"
                if out_path.exists():
                    logger.debug("calendar note cached: %s", out_path)
                    results.append((start_dt, out_path))
                    continue

                try:
                    md_bytes = self.drive_exporter.export_document(file_id)
                except HttpError:
                    logger.warning("calendar doc not accessible: %s", out_path.name)
                    continue

                content = md_bytes
                if is_shared_notes(att_title):
                    section = extract_section_for_date(
                        md_bytes.decode("utf-8", errors="replace"), start_dt.date()
                    )
                    if section is None:
                        logger.warning(
                            "no section for %s in %s", start_dt.date(), out_path.name
                        )
                        continue
                    content = section.encode("utf-8")

                doc_url = f"https://docs.google.com/document/d/{file_id}"
                front_matter = CALENDAR_TEMPLATE.render(
                    source=self.source,
                    doc_type="meeting_notes",
                    event_name=event_name,
                    date=start_dt.strftime("%Y-%m-%d"),
                    attended="true" if attended else "false",
                    doc_url=doc_url,
                    event_url=event_url,
                    attendees=attendees,
                )
                out_path.write_bytes(front_matter.encode() + content)
                logger.info("wrote calendar note: %s", out_path)
                results.append((start_dt, out_path))

            for att in chat_attachments:
                file_id = att["fileId"]
                name = f"{base_name} (chat)"
                out_path = day_dir / f"{name}.md"

                if out_path.exists():
                    logger.debug("calendar chat cached: %s", out_path)
                    results.append((start_dt, out_path))
                    continue

                try:
                    chat_content = self.drive_exporter.get_media(file_id)
                except HttpError:
                    logger.warning("calendar chat not accessible: %s", out_path.name)
                    continue

                doc_url = f"https://drive.google.com/file/d/{file_id}"
                front_matter = CALENDAR_TEMPLATE.render(
                    source=self.source,
                    doc_type="meeting_chat",
                    event_name=event_name,
                    date=start_dt.strftime("%Y-%m-%d"),
                    attended="true" if attended else "false",
                    doc_url=doc_url,
                    event_url=event_url,
                    attendees=attendees,
                )
                out_path.write_bytes(front_matter.encode() + chat_content)
                logger.info("wrote calendar chat: %s", out_path)
                results.append((start_dt, out_path))

        return results


class DailyNoteWriter:
    def __init__(self, vault_root: Path):
        self.vault_root = vault_root
        self._lock = threading.Lock()

    def append_line(self, received: datetime, line: str) -> Path:
        with self._lock:
            daily_path = self.get_daily_note_path(received)
            daily_path.parent.mkdir(parents=True, exist_ok=True)
            if daily_path.exists():
                content = daily_path.read_text()
                existing_lines = content.splitlines()
                if line in existing_lines:
                    return daily_path
                separator = "" if content.endswith("\n") or content == "" else "\n"
                daily_path.write_text(f"{content}{separator}{line}\n")
                return daily_path
            daily_path.write_text(f"{line}\n")
            return daily_path

    def append_note_embed(self, received: datetime, note_path: Path) -> Path:
        embed_line = self.render_embed_line(received, note_path)
        return self.append_line(received, embed_line)

    def append_todo_embed(self, received: datetime, subject: str, note_path: Path) -> Path:
        line = self.render_todo_line(subject, note_path)
        return self.append_line(received, line)

    def get_daily_note_path(self, received: datetime) -> Path:
        folder = self.get_daily_notes_folder()
        return folder / f"{received.strftime('%Y-%m-%d')}.md"

    def get_daily_notes_folder(self) -> Path:
        settings_path = self.vault_root / ".obsidian" / "daily-notes.json"
        if not settings_path.exists():
            return self.vault_root
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            return self.vault_root
        folder = settings.get("folder")
        if isinstance(folder, str) and folder.strip():
            return self.vault_root / Path(folder)
        return self.vault_root

    def render_embed_line(self, received: datetime, note_path: Path) -> str:
        try:
            relative_note_path = note_path.relative_to(self.vault_root)
        except ValueError:
            relative_note_path = note_path
        timestamp = received.strftime("%H:%M")
        return f"- {timestamp} ![[{relative_note_path.as_posix()}]]"

    def render_todo_line(self, subject: str, note_path: Path) -> str:
        try:
            relative_note_path = note_path.relative_to(self.vault_root)
        except ValueError:
            relative_note_path = note_path
        return f"- [ ] TODO: {subject} [[{relative_note_path.as_posix()}]]"


class WeaveService:
    def __init__(self, config: WeaveConfig):
        self.config = config
        self.monitor = MailboxMonitor(config)
        self.route_resolver = RouteResolver(config.routes)
        self.handlers = self.get_handlers(config)
        self.daily_note_writer = DailyNoteWriter(vault_root=config.vault_root)
        self._shutdown = threading.Event()
        self.calendar_scraper: CalendarScraper | None = None
        if config.calendar_enabled:
            self._init_calendar_scraper(config)

    def _init_calendar_scraper(self, config: WeaveConfig) -> None:
        if not GOOGLE_TOKEN_PATH.exists():
            raise ConfigError(
                f"Google token not found at {GOOGLE_TOKEN_PATH}. "
                "Run: python scripts/setup_google_credentials.py"
            )
        creds = CalendarScraper.get_google_credentials()
        output_dir = config.vault_root / SINK_RELATIVE_PATH
        self.calendar_scraper = CalendarScraper(
            output_dir=output_dir,
            source=config.calendar_source,
            drive_exporter=GoogleDriveExporter(creds),
        )

    def get_handlers(self, config: WeaveConfig) -> dict[str, MessageHandler]:
        handlers: dict[str, MessageHandler] = {}
        for route in config.routes:
            output_dir = config.vault_root / route.sink_relative
            if route.handler_key == "voice":
                handlers[route.name] = VoiceNoteHandler(output_dir=output_dir)
            elif route.handler_key == "rm2":
                handlers[route.name] = RemarkableSnapshotHandler(
                    output_dir=output_dir,
                    transcriber=LlmPdfTranscriber(),
                )
            elif route.handler_key == "todo":
                handlers[route.name] = TodoHandler(output_dir=output_dir)
            else:
                raise ConfigError(f"Unknown handler key: {route.handler_key}")
        return handlers

    def run_calendar_scrape(self) -> int:
        if self.calendar_scraper is None:
            return 0
        try:
            results = self.calendar_scraper.scrape_once()
        except Exception as exc:
            logger.warning("calendar scrape failed: %s", exc)
            return 0
        for event_start, note_path in results:
            self.daily_note_writer.append_note_embed(
                received=event_start,
                note_path=note_path,
            )
        return len(results)

    def run_calendar_loop(self, interval: int = 300) -> None:
        while not self._shutdown.is_set():
            count = self.run_calendar_scrape()
            if count > 0:
                logger.info("calendar scrape: %d note(s)", count)
            self._shutdown.wait(timeout=interval)

    def run_single_batch(self) -> int:
        with self.monitor.connect() as client:
            email_count = self.get_processed_count(client)
        cal_count = self.run_calendar_scrape()
        return email_count + cal_count

    def get_processed_count(self, client: IMAPClient) -> int:
        messages = self.monitor.get_unseen_messages(client)
        if not messages:
            logger.debug("no unread messages")
            return 0
        processed = 0
        for message in messages:
            route = self.route_resolver.get_route_for_message(
                to_addresses=message.to_addresses,
                sender=message.sender,
            )
            if route is None:
                continue
            handler = self.handlers[route.name]
            try:
                result = handler.handle_message(message)
            except Exception as exc:
                logger.warning("failed processing uid %s: %s", message.uid, exc)
                continue
            if result.handled:
                for note_path in result.note_paths:
                    daily_path = self.daily_note_writer.append_note_embed(
                        received=message.received,
                        note_path=note_path,
                    )
                    logger.info("updated daily note %s", daily_path)
                for subject, note_path in result.todo_entries:
                    daily_path = self.daily_note_writer.append_todo_embed(
                        received=message.received,
                        subject=subject,
                        note_path=note_path,
                    )
                    logger.info("updated daily note %s", daily_path)
                self.monitor.mark_message_seen(client, message)
                processed += 1
                for path in result.created_paths:
                    logger.info("wrote %s", path)
        return processed

    def run_daemon(self) -> None:
        self.register_signal_handlers()
        if self.calendar_scraper is not None:
            cal_thread = threading.Thread(
                target=self.run_calendar_loop, daemon=True, name="calendar-scraper"
            )
            cal_thread.start()
            logger.info("started calendar scraper thread")
        while True:
            try:
                with self.monitor.connect() as client:
                    count = self.get_processed_count(client)
                    if count > 0:
                        logger.info("processed %s message(s)", count)
                    while True:
                        client.idle()
                        responses = client.idle_check(timeout=self.config.poll_interval_seconds)
                        client.idle_done()
                        if responses:
                            count = self.get_processed_count(client)
                            if count > 0:
                                logger.info("processed %s message(s)", count)
            except Exception as exc:
                logger.warning("connection error: %s", exc)
                time.sleep(5)

    def register_signal_handlers(self) -> None:
        def handle_signal(signum: int, frame: object) -> None:
            logger.info("shutting down")
            self._shutdown.set()
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)


def setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.INFO
    if verbose:
        level = logging.DEBUG
    if quiet:
        level = logging.ERROR
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            RichHandler(
                console=STDERR_CONSOLE,
                rich_tracebacks=verbose,
                show_path=False,
                show_time=False,
            )
        ],
    )


def get_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Weave email ingress daemon")
    parser.add_argument("vault_root", type=Path, help="Obsidian vault root")
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=300,
        help="Idle timeout in seconds",
    )
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--quiet", action="store_true", help="Only show errors")
    parser.add_argument("--source", default="@hex-rays.com", help="Calendar source tag")
    parser.add_argument("--no-calendar", action="store_true", help="Disable calendar scraping")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = get_args(argv)
    setup_logging(verbose=args.verbose, quiet=args.quiet)
    if not args.vault_root.exists():
        logger.error("vault root does not exist: %s", args.vault_root)
        raise SystemExit(1)
    try:
        config = WeaveConfig.from_runtime(
            vault_root=args.vault_root,
            poll_interval_seconds=args.poll_interval,
            calendar_source=args.source,
            calendar_enabled=not args.no_calendar,
        )
    except ConfigError as exc:
        logger.error("configuration error: %s", exc)
        raise SystemExit(1) from exc
    service = WeaveService(config)
    if args.once:
        count = service.run_single_batch()
        logger.info("processed %s message(s)", count)
        return
    service.run_daemon()


if __name__ == "__main__":
    main()
