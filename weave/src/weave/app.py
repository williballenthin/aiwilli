from __future__ import annotations

import argparse
import datetime as dt_mod
import email
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import threading
from collections.abc import Callable, Generator, Iterable
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
from pydantic import BaseModel, Field, ValidationError
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
summary: ""
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
summary: ""
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
summary: ""
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
summary: ""
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

WEAVE_TAG = "#weave"
MANAGED_NOTE_LINE_RE = re.compile(
    r"^- (?P<entry_type>[^:]+): \[\[(?P<link>[^\]]+)\]\](?: - (?P<summary>.*?))? #weave$"
)
MANAGED_TODO_LINE_RE = re.compile(
    r"^- \[ \] todo: \[\[(?P<link>[^\]]+)\]\](?: - (?P<summary>.*?))? #weave$"
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

SUMMARY_MODEL = "gemini/gemini-3-flash-preview"
SUMMARY_PROMPT = (
    "Summarize this document in exactly one sentence."
    " This summary will appear in a daily index of notes and events."
    " Provide a high-impact overview so the reader can decide whether"
    " to click through to the full document."
)

AGENT_SESSION_SUMMARY_PROMPT = """\
You are analyzing a software engineering agent session transcript.
The transcript contains user messages (what the human said) and
assistant responses (what the AI agent said back to the human).

Provide a structured summary with:
1. ONE SENTENCE describing the overall goal of the session.
2. KEY DECISIONS made (bulleted list, skip if none).
3. WORK COMPLETED (bulleted list of concrete outcomes).
4. TOPICS covered (comma-separated tags).

Be concise. Use plain text, no markdown headers."""

HANDLER_ENTRY_TYPES: dict[str, str] = {
    "voice": "transcript",
    "rm2": "handwriting",
    "todo": "todo",
}

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
AGENT_SESSION_MUTABLE_DAYS = 7
AGENT_SESSION_MANIFEST_VERSION = 1

MONTHS: dict[str, int] = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
SECTION_DATE_RE = re.compile(r"^## (\w{3}) (\d{1,2}), (\d{4})")
CLAUDE_SESSION_FILENAME_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$",
    re.IGNORECASE,
)
PI_SESSION_FILENAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-\d+)?Z_[0-9a-f-]+\.jsonl$",
    re.IGNORECASE,
)

CALENDAR_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
source: "{{ source }}"
summary: ""
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
    return date_folder


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[/\\:*?"<>|]', "-", name)
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
    agent_sessions_dir: Path | None = None

    @classmethod
    def from_runtime(
        cls,
        vault_root: Path,
        poll_interval_seconds: int,
        calendar_source: str = "@hex-rays.com",
        agent_sessions_dir: Path | None = None,
    ) -> WeaveConfig:
        """Build runtime configuration from args and environment.

        Raises:
            ConfigError: If required environment variables are missing.
        """
        required = (
            "IMAP_HOST",
            "IMAP_USER",
            "IMAP_PASSWORD",
            BASE_EMAIL_ENV,
            "WEAVE_ALLOWED_SENDERS",
        )
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")
        base_email = os.environ[BASE_EMAIL_ENV]
        allowed_senders = _parse_senders("WEAVE_ALLOWED_SENDERS")
        env_sessions = os.environ.get("WEAVE_AGENT_SESSIONS_DIR")
        resolved_sessions = agent_sessions_dir or (Path(env_sessions) if env_sessions else None)
        try:
            return cls(
                imap_host=os.environ["IMAP_HOST"],
                imap_user=os.environ["IMAP_USER"],
                imap_password=os.environ["IMAP_PASSWORD"],
                vault_root=vault_root,
                poll_interval_seconds=poll_interval_seconds,
                calendar_source=calendar_source,
                agent_sessions_dir=resolved_sessions,
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


class AgentSessionManifestEntry(BaseModel):
    session_id: str
    session_sha256: str
    sink_path: str
    source_mtime_ns: int


class AgentSessionManifest(BaseModel):
    version: int = AGENT_SESSION_MANIFEST_VERSION
    sessions: dict[str, AgentSessionManifestEntry] = Field(default_factory=dict)


class AgentSessionSyncReport(BaseModel):
    manifest_path: str
    scanned: int = 0
    imported: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_immutable: int = 0
    skipped_empty: int = 0
    failed: int = 0

    @property
    def changed_count(self) -> int:
        return self.imported + self.updated


@dataclass(frozen=True)
class AgentSessionScrapeResult:
    received: datetime
    note_path: Path
    entry_type: str
    action: str


@dataclass(frozen=True)
class AgentSessionScrapeRun:
    report: AgentSessionSyncReport
    results: list[AgentSessionScrapeResult]


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


class NoteSummarizer(Protocol):
    def summarize(self, content: str) -> str:
        """Return a brief summary of the given content."""


class LlmNoteSummarizer:
    def __init__(self, prompt: str = SUMMARY_PROMPT, model: str = SUMMARY_MODEL):
        self.prompt = prompt
        self.model = model

    def summarize(self, content: str) -> str:
        try:
            result = subprocess.run(
                ["llm", "-m", self.model, self.prompt],
                input=content,
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            logger.warning("summarization failed: %s", exc)
            return ""
        return result.stdout.strip()


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
            path.parent.mkdir(exist_ok=True)
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
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(attachment.content)
            attachment_paths.append(path)
        attachment_links = "\n".join(f"![[_attachments/{path.name}]]" for path in attachment_paths)
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
                pdf_path.parent.mkdir(exist_ok=True)
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
    return att_title.lower().startswith("notes by gemini") or (" - Notes by Gemini" in att_title)


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
        result: bytes = (
            self.service.files().export(fileId=file_id, mimeType="text/markdown").execute()
        )
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

    def scrape_once(self) -> list[tuple[datetime, Path, str]]:
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

        results: list[tuple[datetime, Path, str]] = []
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
                a
                for a in all_attachments
                if a.get("mimeType") == "application/vnd.google-apps.document"
            ]
            chat_attachments = [
                a
                for a in all_attachments
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
                    results.append((start_dt, out_path, "meeting notes"))
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
                        logger.warning("no section for %s in %s", start_dt.date(), out_path.name)
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
                results.append((start_dt, out_path, "meeting notes"))

            for att in chat_attachments:
                file_id = att["fileId"]
                name = f"{base_name} (chat)"
                out_path = day_dir / f"{name}.md"

                if out_path.exists():
                    logger.debug("calendar chat cached: %s", out_path)
                    results.append((start_dt, out_path, "meeting chat"))
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
                results.append((start_dt, out_path, "meeting chat"))

        return results


# --- Agent session parsing ---


@dataclass
class SessionTurn:
    user_text: str
    assistant_texts: list[str]
    tool_names: list[str]
    timestamp: datetime | None = None


@dataclass
class SessionTokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float | None = None


@dataclass
class SessionData:
    agent: str
    session_id: str
    project: str
    cwd: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    models: list[str] = field(default_factory=list)
    git_branch: str = ""
    usage: SessionTokenUsage = field(default_factory=SessionTokenUsage)
    turns: list[SessionTurn] = field(default_factory=list)
    total_tool_calls: int = 0
    total_thinking_blocks: int = 0

    @property
    def duration(self) -> dt_mod.timedelta | None:
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return None


def _parse_session_timestamp(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def get_agent_session_manifest_path() -> Path:
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_home / "wballethin" / "weave" / "agent-session-manifest.json"


def get_session_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def get_session_id(path: Path) -> str:
    stem = path.stem
    if detect_session_format(path) == "pi" and "_" in stem:
        return stem.split("_", 1)[1]
    if stem:
        return stem
    with path.open() as f:
        first_line = f.readline()
    obj = json.loads(first_line)
    if obj.get("type") == "session":
        return str(obj.get("id", ""))
    return str(obj.get("sessionId", ""))


def detect_session_format(path: Path) -> str:
    with open(path) as f:
        first_line = f.readline()
    obj = json.loads(first_line)
    if obj.get("type") == "session" and "version" in obj:
        return "pi"
    return "claude"


def _is_human_user_msg(obj: dict[str, Any]) -> bool:
    if obj.get("type") != "user":
        return False
    if obj.get("isMeta"):
        return False
    content = obj.get("message", {}).get("content", "")
    if isinstance(content, list):
        return False
    if isinstance(content, str):
        if content.startswith(("<bash-", "<local-command", "<task-notification")):
            return False
        return True
    return False


def _build_claude_turns(messages: list[dict[str, Any]]) -> list[SessionTurn]:
    turns: list[SessionTurn] = []
    current_user_text: str | None = None
    current_user_ts: datetime | None = None
    current_assistant_texts: list[str] = []
    current_tool_names: list[str] = []

    for obj in messages:
        if _is_human_user_msg(obj):
            if current_user_text is not None:
                turns.append(
                    SessionTurn(
                        user_text=current_user_text,
                        assistant_texts=current_assistant_texts,
                        tool_names=current_tool_names,
                        timestamp=current_user_ts,
                    )
                )
            current_user_text = obj.get("message", {}).get("content", "")
            ts_str = obj.get("timestamp")
            current_user_ts = _parse_session_timestamp(ts_str) if ts_str else None
            current_assistant_texts = []
            current_tool_names = []
        elif obj.get("type") == "assistant" and current_user_text is not None:
            for block in obj.get("message", {}).get("content", []):
                bt = block.get("type")
                if bt == "text":
                    text = block.get("text", "").strip()
                    if text and text != "No response requested.":
                        current_assistant_texts.append(text)
                elif bt == "tool_use":
                    current_tool_names.append(block.get("name", "unknown"))

    if current_user_text is not None:
        turns.append(
            SessionTurn(
                user_text=current_user_text,
                assistant_texts=current_assistant_texts,
                tool_names=current_tool_names,
                timestamp=current_user_ts,
            )
        )
    return turns


def _build_pi_turns(messages: list[dict[str, Any]]) -> list[SessionTurn]:
    turns: list[SessionTurn] = []
    current_user_text: str | None = None
    current_user_ts: datetime | None = None
    current_assistant_texts: list[str] = []
    current_tool_names: list[str] = []

    for obj in messages:
        msg = obj.get("message", {})
        role = msg.get("role")
        if role == "user":
            if current_user_text is not None:
                turns.append(
                    SessionTurn(
                        user_text=current_user_text,
                        assistant_texts=current_assistant_texts,
                        tool_names=current_tool_names,
                        timestamp=current_user_ts,
                    )
                )
            text_parts = []
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block["text"])
            current_user_text = "\n".join(text_parts)
            ts_str = obj.get("timestamp")
            current_user_ts = _parse_session_timestamp(ts_str) if ts_str else None
            current_assistant_texts = []
            current_tool_names = []
        elif role == "assistant" and current_user_text is not None:
            for block in msg.get("content", []):
                if isinstance(block, dict):
                    bt = block.get("type")
                    if bt == "text":
                        text = block.get("text", "").strip()
                        if text:
                            current_assistant_texts.append(text)
                    elif bt == "toolCall":
                        current_tool_names.append(block.get("name", "unknown"))

    if current_user_text is not None:
        turns.append(
            SessionTurn(
                user_text=current_user_text,
                assistant_texts=current_assistant_texts,
                tool_names=current_tool_names,
                timestamp=current_user_ts,
            )
        )
    return turns


def parse_claude_session(path: Path) -> SessionData:
    lines: list[dict[str, Any]] = []
    with open(path) as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(json.loads(raw))

    session = SessionData(agent="claude", session_id="", project="", cwd="")
    last_usage_by_msg_id: dict[str, dict[str, Any]] = {}
    models: set[str] = set()
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    ordered_messages: list[dict[str, Any]] = []

    for obj in lines:
        ts_str = obj.get("timestamp")
        if ts_str:
            ts = _parse_session_timestamp(ts_str)
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

        if not session.session_id and obj.get("sessionId"):
            session.session_id = obj["sessionId"]
        if not session.cwd and obj.get("cwd"):
            session.cwd = obj["cwd"]
        if not session.git_branch and obj.get("gitBranch"):
            session.git_branch = obj["gitBranch"]

        if obj.get("type") in ("user", "assistant"):
            ordered_messages.append(obj)

        if obj.get("type") == "assistant":
            msg = obj.get("message", {})
            msg_id = msg.get("id")
            model = msg.get("model")
            if model and model != "<synthetic>":
                models.add(model)
            msg_usage = msg.get("usage")
            if msg_id and msg_usage:
                last_usage_by_msg_id[msg_id] = msg_usage
            for block in msg.get("content", []):
                bt = block.get("type")
                if bt == "tool_use":
                    session.total_tool_calls += 1
                elif bt == "thinking":
                    session.total_thinking_blocks += 1

    for msg_usage in last_usage_by_msg_id.values():
        session.usage.input_tokens += msg_usage.get("input_tokens", 0)
        session.usage.output_tokens += msg_usage.get("output_tokens", 0)
        session.usage.cache_read_tokens += msg_usage.get("cache_read_input_tokens", 0)
        session.usage.cache_write_tokens += msg_usage.get("cache_creation_input_tokens", 0)

    session.start_time = first_ts
    session.end_time = last_ts
    session.models = sorted(models)
    session.project = Path(session.cwd).name if session.cwd else "unknown"
    session.turns = _build_claude_turns(ordered_messages)
    return session


def parse_pi_session(path: Path) -> SessionData:
    entries: list[dict[str, Any]] = []
    with open(path) as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                entries.append(json.loads(raw))

    session = SessionData(agent="pi", session_id="", project="", cwd="")
    total_cost = 0.0
    models: set[str] = set()
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    ordered_messages: list[dict[str, Any]] = []

    for obj in entries:
        ts_str = obj.get("timestamp")
        if ts_str:
            ts = _parse_session_timestamp(ts_str)
            if first_ts is None or ts < first_ts:
                first_ts = ts
            if last_ts is None or ts > last_ts:
                last_ts = ts

        entry_type = obj.get("type")
        if entry_type == "session":
            session.session_id = obj.get("id", "")
            session.cwd = obj.get("cwd", "")
        elif entry_type == "model_change":
            model_id = obj.get("modelId", "")
            provider = obj.get("provider", "")
            if model_id:
                models.add(f"{provider}/{model_id}" if provider else model_id)
        elif entry_type == "message":
            ordered_messages.append(obj)
            msg = obj.get("message", {})
            if msg.get("role") == "assistant":
                msg_usage = msg.get("usage")
                if msg_usage:
                    session.usage.input_tokens += msg_usage.get("input", 0)
                    session.usage.output_tokens += msg_usage.get("output", 0)
                    session.usage.cache_read_tokens += msg_usage.get("cacheRead", 0)
                    session.usage.cache_write_tokens += msg_usage.get("cacheWrite", 0)
                    total_cost += msg_usage.get("cost", {}).get("total", 0)
                for block in msg.get("content", []):
                    if isinstance(block, dict):
                        bt = block.get("type")
                        if bt == "toolCall":
                            session.total_tool_calls += 1
                        elif bt == "thinking":
                            session.total_thinking_blocks += 1

    session.usage.cost = total_cost if total_cost > 0 else None
    session.start_time = first_ts
    session.end_time = last_ts
    session.models = sorted(models)
    session.project = Path(session.cwd).name if session.cwd else "unknown"
    session.turns = _build_pi_turns(ordered_messages)
    return session


def parse_session(path: Path) -> SessionData:
    fmt = detect_session_format(path)
    if fmt == "pi":
        return parse_pi_session(path)
    return parse_claude_session(path)


def _format_duration(td: dt_mod.timedelta) -> str:
    total_secs = int(td.total_seconds())
    hours, remainder = divmod(total_secs, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def render_session_turns(session: SessionData) -> str:
    parts: list[str] = []
    for i, turn in enumerate(session.turns, 1):
        ts = turn.timestamp.strftime("%H:%M:%S") if turn.timestamp else "??:??"
        parts.append(f"### Turn {i} [{ts}]")
        parts.append("")
        parts.append(f"**USER:** {turn.user_text}")
        parts.append("")
        if turn.tool_names:
            parts.append(f"*tools: {', '.join(turn.tool_names)}*")
            parts.append("")
        for text in turn.assistant_texts:
            parts.append(f"**ASSISTANT:** {text}")
            parts.append("")
    return "\n".join(parts)


AGENT_SESSION_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
type: agent_session
summary: ""
agent: {{ agent }}
project: "{{ project }}"
session_id: "{{ session_id }}"
session_sha256: "{{ session_sha256 }}"
start: {{ start }}
end: {{ end }}
duration: "{{ duration }}"
models:
{% for m in models %}
  - "{{ m }}"
{% endfor %}
{% if git_branch %}
git_branch: "{{ git_branch }}"
{% endif %}
input_tokens: {{ input_tokens }}
output_tokens: {{ output_tokens }}
total_tokens: {{ total_tokens }}
{% if cost %}
cost: {{ cost }}
{% endif %}
user_turns: {{ user_turns }}
tool_calls: {{ tool_calls }}
---

## Summary

{{ summary }}

## Metrics

| Metric | Value |
|--------|-------|
| Agent | {{ agent }} |
| Project | {{ project }} |
| Duration | {{ duration }} |
| Model(s) | {{ models_str }} |
| Input tokens | {{ input_tokens_fmt }} |
| Output tokens | {{ output_tokens_fmt }} |
| Cache read | {{ cache_read_fmt }} |
| Cache write | {{ cache_write_fmt }} |
| Total tokens | {{ total_tokens_fmt }} |
{% if cost %}
| Cost | ${{ cost }} |
{% endif %}
| User turns | {{ user_turns }} |
| Tool calls | {{ tool_calls }} |

## Conversation

{{ conversation }}
"""
)


def render_session_note(session: SessionData, summary: str, session_sha256: str) -> str:
    usage = session.usage
    total = (
        usage.input_tokens
        + usage.output_tokens
        + usage.cache_read_tokens
        + usage.cache_write_tokens
    )
    return AGENT_SESSION_TEMPLATE.render(
        agent=session.agent,
        project=session.project,
        session_id=session.session_id,
        session_sha256=session_sha256,
        start=session.start_time.isoformat(timespec="seconds") if session.start_time else "",
        end=session.end_time.isoformat(timespec="seconds") if session.end_time else "",
        duration=_format_duration(session.duration) if session.duration else "unknown",
        models=session.models,
        models_str=", ".join(session.models) or "unknown",
        git_branch=session.git_branch,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=total,
        input_tokens_fmt=f"{usage.input_tokens:,}",
        output_tokens_fmt=f"{usage.output_tokens:,}",
        cache_read_fmt=f"{usage.cache_read_tokens:,}",
        cache_write_fmt=f"{usage.cache_write_tokens:,}",
        total_tokens_fmt=f"{total:,}",
        cost=f"{usage.cost:.4f}" if usage.cost else None,
        user_turns=len(session.turns),
        tool_calls=session.total_tool_calls,
        summary=summary,
        conversation=render_session_turns(session),
    )


class AgentSessionScraper:
    def __init__(
        self,
        sessions_dir: Path,
        output_dir: Path,
        summarizer: NoteSummarizer | None = None,
    ):
        self.sessions_dir = sessions_dir
        self.output_dir = output_dir
        self.summarizer = summarizer

    def scrape_once(
        self,
        on_result: Callable[[AgentSessionScrapeResult], None] | None = None,
    ) -> AgentSessionScrapeRun:
        manifest_path = get_agent_session_manifest_path()
        manifest = self._load_manifest(manifest_path)
        report = AgentSessionSyncReport(manifest_path=str(manifest_path))
        results: list[AgentSessionScrapeResult] = []
        now = datetime.now(tz=UTC)
        seen_sources: set[str] = set()
        manifest_dirty = False

        for jsonl_path in self._find_session_files():
            source_key = str(jsonl_path.resolve())
            seen_sources.add(source_key)
            report.scanned += 1
            try:
                result = self._sync_session(
                    jsonl_path=jsonl_path,
                    source_key=source_key,
                    manifest=manifest,
                    now=now,
                )
            except Exception as exc:
                report.failed += 1
                logger.warning("failed to process session %s: %s", jsonl_path.name, exc)
                continue

            if result is None:
                report.skipped_empty += 1
                continue

            status, note_result, manifest_changed = result
            if status == "imported":
                report.imported += 1
            elif status == "updated":
                report.updated += 1
            elif status == "unchanged":
                report.unchanged += 1
            elif status == "skipped_immutable":
                report.skipped_immutable += 1
            elif status == "skipped_empty":
                report.skipped_empty += 1

            if note_result is not None:
                results.append(note_result)
                if on_result is not None:
                    on_result(note_result)
            if manifest_changed:
                manifest_dirty = True
            if manifest_dirty:
                self._save_manifest(manifest_path, manifest)
                manifest_dirty = False

        stale_sources = set(manifest.sessions) - seen_sources
        for source_key in stale_sources:
            del manifest.sessions[source_key]
            manifest_dirty = True
        if manifest_dirty or not manifest_path.exists():
            self._save_manifest(manifest_path, manifest)
        return AgentSessionScrapeRun(report=report, results=results)

    def _find_session_files(self) -> list[Path]:
        paths: list[Path] = []
        for agent_dir, filename_re in (
            ("claude", CLAUDE_SESSION_FILENAME_RE),
            ("pi", PI_SESSION_FILENAME_RE),
        ):
            agent_path = self.sessions_dir / agent_dir
            if not agent_path.is_dir():
                continue
            for jsonl in agent_path.rglob("*.jsonl"):
                if "/subagents/" in str(jsonl):
                    continue
                if not filename_re.match(jsonl.name):
                    continue
                paths.append(jsonl)
        return sorted(paths)

    def _load_manifest(self, manifest_path: Path) -> AgentSessionManifest:
        if not manifest_path.exists():
            return AgentSessionManifest()
        try:
            return AgentSessionManifest.model_validate_json(manifest_path.read_text())
        except (OSError, ValidationError, json.JSONDecodeError) as exc:
            logger.warning("agent session manifest invalid, rebuilding: %s", exc)
            return AgentSessionManifest()

    def _save_manifest(self, manifest_path: Path, manifest: AgentSessionManifest) -> None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2, sort_keys=True))

    def _is_mutable(self, source_mtime: datetime, now: datetime) -> bool:
        return source_mtime >= now - dt_mod.timedelta(days=AGENT_SESSION_MUTABLE_DAYS)

    def _output_path_for_session(self, session: SessionData) -> Path | None:
        if session.start_time is None or not session.session_id:
            return None
        day_dir = get_date_folder(self.output_dir, session.start_time)
        name = sanitize_filename(session.session_id)
        return day_dir / f"{name}.md"

    def _sync_session(
        self,
        jsonl_path: Path,
        source_key: str,
        manifest: AgentSessionManifest,
        now: datetime,
    ) -> tuple[str, AgentSessionScrapeResult | None, bool] | None:
        stat = jsonl_path.stat()
        if stat.st_size == 0:
            return ("skipped_empty", None, False)
        source_mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
        source_mtime_ns = stat.st_mtime_ns
        entry = manifest.sessions.get(source_key)
        sink_path = Path(entry.sink_path) if entry else None
        sink_exists = sink_path.exists() if sink_path else False

        if entry and sink_exists and not self._is_mutable(source_mtime, now):
            return ("skipped_immutable", None, False)

        if entry and sink_exists and entry.source_mtime_ns == source_mtime_ns:
            return ("unchanged", None, False)

        session_sha256 = get_session_sha256(jsonl_path)
        if entry and sink_exists and entry.session_sha256 == session_sha256:
            manifest.sessions[source_key] = AgentSessionManifestEntry(
                session_id=entry.session_id,
                session_sha256=entry.session_sha256,
                sink_path=entry.sink_path,
                source_mtime_ns=source_mtime_ns,
            )
            return ("unchanged", None, True)

        session = parse_session(jsonl_path)
        session.session_id = session.session_id or get_session_id(jsonl_path)
        if not session.turns or session.start_time is None or not session.session_id:
            return None

        out_path = self._output_path_for_session(session)
        if out_path is None:
            return None

        if entry and entry.sink_path != str(out_path.resolve()):
            old_path = Path(entry.sink_path)
            if old_path.exists():
                old_path.unlink()

        summary = ""
        if self.summarizer:
            turns_text = render_session_turns(session)
            summary = self.summarizer.summarize(turns_text)

        content = render_session_note(session, summary, session_sha256)
        out_path.write_text(content)
        logger.info("wrote agent session: %s", out_path)

        manifest.sessions[source_key] = AgentSessionManifestEntry(
            session_id=session.session_id,
            session_sha256=session_sha256,
            sink_path=str(out_path.resolve()),
            source_mtime_ns=source_mtime_ns,
        )
        action = "updated" if entry else "imported"
        return (
            action,
            AgentSessionScrapeResult(
                received=session.start_time,
                note_path=out_path,
                entry_type="agent session",
                action=action,
            ),
            True,
        )


def split_front_matter(content: str) -> tuple[str, str] | None:
    match = re.match(r"\A---\n(?P<front>.*?)\n---\n?(?P<body>.*)\Z", content, re.DOTALL)
    if match is None:
        return None
    return match.group("front"), match.group("body")


def parse_front_matter_scalar(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.startswith('"'):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped.strip('"')
        return parsed if isinstance(parsed, str) else stripped
    if stripped.startswith("'") and stripped.endswith("'"):
        return stripped[1:-1].replace("''", "'")
    return stripped


def get_note_summary(content: str) -> str:
    parts = split_front_matter(content)
    if parts is None:
        return ""
    front_matter, _ = parts
    for line in front_matter.splitlines():
        if not line.startswith("summary:"):
            continue
        _, _, value = line.partition(":")
        return parse_front_matter_scalar(value)
    return ""


def set_note_summary(content: str, summary: str) -> str:
    summary_line = f"summary: {json.dumps(summary)}"
    parts = split_front_matter(content)
    if parts is None:
        return f"---\n{summary_line}\n---\n{content}"
    front_matter, body = parts
    lines = front_matter.splitlines()
    updated_lines: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("summary:"):
            if not replaced:
                updated_lines.append(summary_line)
                replaced = True
            continue
        updated_lines.append(line)
    if not replaced:
        updated_lines.append(summary_line)
    updated_front_matter = "\n".join(updated_lines)
    return f"---\n{updated_front_matter}\n---\n{body}"


class DailyNoteWriter:
    def __init__(self, vault_root: Path, summarizer: NoteSummarizer | None = None):
        self.vault_root = vault_root
        self.summarizer = summarizer
        self._lock = threading.RLock()

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

    def append_note_entry(self, received: datetime, note_path: Path, entry_type: str) -> Path:
        with self._lock:
            daily_path = self.get_daily_note_path(received)
            link = f"[[{self._get_relative_path(note_path).as_posix()}]]"
            summary = self._get_or_create_summary(note_path)
            line = self.render_entry_line(entry_type, note_path, summary)
            return self._upsert_line(daily_path, link, line)

    def append_todo_entry(self, received: datetime, note_path: Path) -> Path:
        with self._lock:
            daily_path = self.get_daily_note_path(received)
            link = f"[[{self._get_relative_path(note_path).as_posix()}]]"
            summary = self._get_or_create_summary(note_path)
            line = self.render_todo_line(note_path, summary)
            return self._upsert_line(daily_path, link, line)

    def sync_all_daily_notes(self) -> int:
        with self._lock:
            daily_folder = self.get_daily_notes_folder()
            if not daily_folder.exists():
                return 0
            updated_count = 0
            for daily_path in sorted(daily_folder.glob("????-??-??.md")):
                if self.sync_daily_note(daily_path):
                    updated_count += 1
            return updated_count

    def sync_daily_note(self, daily_path: Path) -> bool:
        with self._lock:
            if not daily_path.exists():
                return False
            content = daily_path.read_text()
            lines = content.splitlines()
            updated_lines: list[str] = []
            changed = False
            for line in lines:
                updated_line = self._sync_managed_line(line)
                if updated_line != line:
                    changed = True
                updated_lines.append(updated_line)
            if not changed:
                return False
            trailing_newline = "\n" if content.endswith("\n") else ""
            daily_path.write_text("\n".join(updated_lines) + trailing_newline)
            return True

    def _sync_managed_line(self, line: str) -> str:
        parsed = self._parse_managed_line(line)
        if parsed is None:
            return line
        is_todo, entry_type, note_path = parsed
        summary = self._get_summary_for_sync(note_path)
        if summary is None:
            return line
        if is_todo:
            return self.render_todo_line(note_path, summary)
        return self.render_entry_line(entry_type, note_path, summary)

    def _parse_managed_line(self, line: str) -> tuple[bool, str, Path] | None:
        todo_match = MANAGED_TODO_LINE_RE.match(line)
        if todo_match is not None:
            return True, "todo", self._resolve_note_path(todo_match.group("link"))
        note_match = MANAGED_NOTE_LINE_RE.match(line)
        if note_match is None:
            return None
        return (
            False,
            note_match.group("entry_type"),
            self._resolve_note_path(note_match.group("link")),
        )

    def _resolve_note_path(self, link: str) -> Path:
        link_path = Path(link)
        if link_path.is_absolute():
            return link_path
        return self.vault_root / link_path

    def _upsert_line(self, daily_path: Path, link: str, line: str) -> Path:
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        if not daily_path.exists():
            daily_path.write_text(f"{line}\n")
            return daily_path
        content = daily_path.read_text()
        lines = content.splitlines()
        for index, existing_line in enumerate(lines):
            if link in existing_line and WEAVE_TAG in existing_line:
                if existing_line == line:
                    return daily_path
                lines[index] = line
                trailing_newline = "\n" if content.endswith("\n") else ""
                daily_path.write_text("\n".join(lines) + trailing_newline)
                return daily_path
        separator = "" if content.endswith("\n") or content == "" else "\n"
        daily_path.write_text(f"{content}{separator}{line}\n")
        return daily_path

    def _get_summary_for_sync(self, note_path: Path) -> str | None:
        try:
            content = note_path.read_text()
        except OSError:
            return None
        return get_note_summary(content)

    def _get_or_create_summary(self, note_path: Path) -> str:
        try:
            content = note_path.read_text()
        except OSError:
            return ""
        existing_summary = get_note_summary(content)
        if existing_summary:
            return existing_summary
        if self.summarizer is None:
            return ""
        summary = self.summarizer.summarize(content)
        if not summary:
            return ""
        note_path.write_text(set_note_summary(content, summary))
        return summary

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

    def _get_relative_path(self, note_path: Path) -> Path:
        try:
            return note_path.relative_to(self.vault_root)
        except ValueError:
            return note_path

    def render_entry_line(self, entry_type: str, note_path: Path, summary: str = "") -> str:
        relative = self._get_relative_path(note_path)
        parts = [f"- {entry_type}: [[{relative.as_posix()}]]"]
        if summary:
            parts.append(f"- {summary}")
        parts.append(WEAVE_TAG)
        return " ".join(parts)

    def render_todo_line(self, note_path: Path, summary: str = "") -> str:
        relative = self._get_relative_path(note_path)
        parts = [f"- [ ] todo: [[{relative.as_posix()}]]"]
        if summary:
            parts.append(f"- {summary}")
        parts.append(WEAVE_TAG)
        return " ".join(parts)


class WeaveService:
    def __init__(self, config: WeaveConfig):
        self.config = config
        self.monitor = MailboxMonitor(config)
        self.route_resolver = RouteResolver(config.routes)
        self.handlers = self.get_handlers(config)
        self.daily_note_writer = DailyNoteWriter(
            vault_root=config.vault_root,
            summarizer=LlmNoteSummarizer(prompt=SUMMARY_PROMPT),
        )
        self._last_daily_note_sync_on: dt_mod.date | None = None
        self._shutdown = threading.Event()
        self.calendar_scraper: CalendarScraper | None = None
        self._init_calendar_scraper(config)
        self.agent_session_scraper: AgentSessionScraper | None = None
        if config.agent_sessions_dir:
            self._init_agent_session_scraper(config)

    def _init_agent_session_scraper(self, config: WeaveConfig) -> None:
        if config.agent_sessions_dir and not config.agent_sessions_dir.is_dir():
            raise ConfigError(f"Agent sessions directory not found: {config.agent_sessions_dir}")
        output_dir = config.vault_root / SINK_RELATIVE_PATH
        self.agent_session_scraper = AgentSessionScraper(
            sessions_dir=config.agent_sessions_dir,  # type: ignore[arg-type]
            output_dir=output_dir,
            summarizer=LlmNoteSummarizer(prompt=AGENT_SESSION_SUMMARY_PROMPT),
        )
        logger.info("agent session scraper enabled: %s", config.agent_sessions_dir)

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
        for event_start, note_path, entry_type in results:
            self.daily_note_writer.append_note_entry(
                received=event_start,
                note_path=note_path,
                entry_type=entry_type,
            )
        return len(results)

    def run_agent_session_scrape(self) -> int:
        if self.agent_session_scraper is None:
            return 0
        def handle_result(result: AgentSessionScrapeResult) -> None:
            self.daily_note_writer.append_note_entry(
                received=result.received,
                note_path=result.note_path,
                entry_type=result.entry_type,
            )

        try:
            run = self.agent_session_scraper.scrape_once(on_result=handle_result)
        except Exception as exc:
            logger.warning("agent session scrape failed: %s", exc)
            return 0
        logger.info(
            "agent session sync: scanned=%d imported=%d updated=%d "
            "unchanged=%d skipped_immutable=%d skipped_empty=%d failed=%d",
            run.report.scanned,
            run.report.imported,
            run.report.updated,
            run.report.unchanged,
            run.report.skipped_immutable,
            run.report.skipped_empty,
            run.report.failed,
        )
        print(run.report.model_dump_json())
        return run.report.changed_count

    def run_daily_note_sync(self, sync_date: dt_mod.date | None = None) -> int:
        current_date = sync_date or dt_mod.date.today()
        if self._last_daily_note_sync_on == current_date:
            return 0
        try:
            count = self.daily_note_writer.sync_all_daily_notes()
        except Exception as exc:
            logger.warning("daily note sync failed: %s", exc)
            return 0
        self._last_daily_note_sync_on = current_date
        return count

    def run_calendar_loop(self, interval: int = 300) -> None:
        while not self._shutdown.is_set():
            count = self.run_calendar_scrape()
            if count > 0:
                logger.info("calendar scrape: %d note(s)", count)
            self._shutdown.wait(timeout=interval)

    def run_agent_session_loop(self, interval: int = 300) -> None:
        while not self._shutdown.is_set():
            count = self.run_agent_session_scrape()
            if count > 0:
                logger.info("agent session scrape: %d note(s)", count)
            self._shutdown.wait(timeout=interval)

    def run_daily_note_sync_loop(self, interval: int = 300) -> None:
        while not self._shutdown.is_set():
            count = self.run_daily_note_sync()
            if count > 0:
                logger.info("daily note sync: %d daily note(s)", count)
            self._shutdown.wait(timeout=interval)

    def run_single_batch(self) -> int:
        with self.monitor.connect() as client:
            email_count = self.get_processed_count(client)
        cal_count = self.run_calendar_scrape()
        session_count = self.run_agent_session_scrape()
        self.run_daily_note_sync()
        return email_count + cal_count + session_count

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
                entry_type = HANDLER_ENTRY_TYPES.get(route.handler_key, "note")
                for note_path in result.note_paths:
                    daily_path = self.daily_note_writer.append_note_entry(
                        received=message.received,
                        note_path=note_path,
                        entry_type=entry_type,
                    )
                    logger.info("updated daily note %s", daily_path)
                for _subject, note_path in result.todo_entries:
                    daily_path = self.daily_note_writer.append_todo_entry(
                        received=message.received,
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
        calendar_thread = threading.Thread(
            target=self.run_calendar_loop,
            daemon=True,
            name="calendar-maintenance",
        )
        calendar_thread.start()
        logger.info("started calendar maintenance thread")
        if self.agent_session_scraper is not None:
            agent_thread = threading.Thread(
                target=self.run_agent_session_loop,
                daemon=True,
                name="agent-session-maintenance",
            )
            agent_thread.start()
            logger.info("started agent session maintenance thread")
        daily_note_thread = threading.Thread(
            target=self.run_daily_note_sync_loop,
            daemon=True,
            name="daily-note-maintenance",
        )
        daily_note_thread.start()
        logger.info("started daily note maintenance thread")
        idle_chunk = min(self.config.poll_interval_seconds, 30)
        while not self._shutdown.is_set():
            try:
                with self.monitor.connect() as client:
                    if self._shutdown.is_set():
                        break
                    count = self.get_processed_count(client)
                    if count > 0:
                        logger.info("processed %s message(s)", count)
                    elapsed = 0
                    while not self._shutdown.is_set():
                        client.idle()
                        responses = client.idle_check(timeout=idle_chunk)
                        client.idle_done()
                        if self._shutdown.is_set():
                            break
                        elapsed += idle_chunk
                        if responses or elapsed >= self.config.poll_interval_seconds:
                            elapsed = 0
                            count = self.get_processed_count(client)
                            if count > 0:
                                logger.info("processed %s message(s)", count)
            except Exception as exc:
                if self._shutdown.is_set():
                    break
                logger.warning("connection error: %s", exc)
                self._shutdown.wait(timeout=5)
        logger.info("shutdown complete")

    def register_signal_handlers(self) -> None:
        def handle_signal(signum: int, frame: object) -> None:
            logger.info("shutting down")
            self._shutdown.set()

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
    parser.add_argument(
        "--agent-sessions",
        type=Path,
        default=None,
        help="Directory containing agent session JSONL files (or set WEAVE_AGENT_SESSIONS_DIR)",
    )
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
            agent_sessions_dir=args.agent_sessions,
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
