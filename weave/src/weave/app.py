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
from collections import defaultdict
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

from weave.github_activity import (
    GhCliGitHubTimelineClient,
    GitHubActivityError,
    GitHubTimelineClient,
    collect_activity_records,
    compact_legacy_activity_section,
    fetch_user_events,
    get_default_timezone_name,
    get_timezone,
    render_compact_activity_section,
)

logger = logging.getLogger(__name__)
STDERR_CONSOLE = Console(stderr=True)

VOICE_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
type: transcript
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
type: handwriting
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
type: handwriting
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
type: todo
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
DEFAULT_DAILY_NOTE_FORMAT = "YYYY-MM-DD"
DEFAULT_NESTED_DAILY_NOTE_FORMAT = "YYYY/MM/DD/YYYY-MM-DD"
WEAVE_DAILY_RELATIVE_PATH = Path("weave") / "daily"
PERSONAL_DAILY_EMBED_START = "<!-- weave:daily-embed:start -->"
PERSONAL_DAILY_EMBED_END = "<!-- weave:daily-embed:end -->"
LEGACY_GITHUB_ACTIVITY_SECTION_HEADING = "## GitHub activity #weave"
MANAGED_NOTE_LINE_RE = re.compile(
    r"^- (?P<entry_type>[^:]+): \[\[(?P<link>[^\]]+)\]\](?: - (?P<summary>.*?))? #weave$"
)
MANAGED_TODO_LINE_RE = re.compile(
    r"^- \[ \] todo: \[\[(?P<link>[^\]]+)\]\](?: - (?P<summary>.*?))? #weave$"
)
WEAVE_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("todos", "TODOs"),
    ("meetings", "Meetings"),
    ("capture", "Capture"),
    ("agent-sessions", "Agent sessions"),
    ("github-activity", "GitHub activity"),
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

AGENT_SESSION_INDEX_SUMMARY_PROMPT = (
    "Summarize this software engineering agent session in 12 words or fewer."
    " Focus on the main task or concrete outcome."
    " Output a single plain-text phrase."
)

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
GITHUB_ACTIVITY_MANIFEST_VERSION = 1
GITHUB_ACTIVITY_PAGES = 3
GITHUB_ACTIVITY_PER_PAGE = 100
GITHUB_ACTIVITY_SYNC_INTERVAL_SECONDS = 3600
GITHUB_ACTIVITY_STABILIZATION_HOURS = 6
GITHUB_ACTIVITY_SECTION_HEADING = "## GitHub activity"
GITHUB_ACTIVITY_SECTION_START = "<!-- weave:github-activity:start -->"
GITHUB_ACTIVITY_SECTION_END = "<!-- weave:github-activity:end -->"

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


def render_daily_note_relative_path(day: dt_mod.date, format_string: str) -> Path:
    rendered = format_string
    replacements = {
        "YYYY": day.strftime("%Y"),
        "MM": day.strftime("%m"),
        "DD": day.strftime("%d"),
    }
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    if not rendered.endswith(".md"):
        rendered = f"{rendered}.md"
    return Path(rendered)


def get_managed_section_markers(section_name: str) -> tuple[str, str]:
    if section_name == "github-activity":
        return GITHUB_ACTIVITY_SECTION_START, GITHUB_ACTIVITY_SECTION_END
    return (
        f"<!-- weave:section:{section_name}:start -->",
        f"<!-- weave:section:{section_name}:end -->",
    )


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
    github_activity_user: str | None = None
    github_activity_timezone: str = "UTC"

    @classmethod
    def from_runtime(
        cls,
        vault_root: Path,
        poll_interval_seconds: int,
        calendar_source: str = "@hex-rays.com",
        agent_sessions_dir: Path | None = None,
        github_activity_user: str | None = None,
        github_activity_timezone: str | None = None,
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
        resolved_github_user = github_activity_user or os.environ.get("WEAVE_GITHUB_USER")
        resolved_github_timezone = (
            github_activity_timezone
            or os.environ.get("WEAVE_GITHUB_TIMEZONE")
            or get_default_timezone_name()
        )
        try:
            return cls(
                imap_host=os.environ["IMAP_HOST"],
                imap_user=os.environ["IMAP_USER"],
                imap_password=os.environ["IMAP_PASSWORD"],
                vault_root=vault_root,
                poll_interval_seconds=poll_interval_seconds,
                calendar_source=calendar_source,
                agent_sessions_dir=resolved_sessions,
                github_activity_user=resolved_github_user,
                github_activity_timezone=resolved_github_timezone,
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


class GitHubActivityManifestDay(BaseModel):
    imported_at: str
    rendered_items: int
    source_events: int


class GitHubActivityManifest(BaseModel):
    version: int = GITHUB_ACTIVITY_MANIFEST_VERSION
    days: dict[str, GitHubActivityManifestDay] = Field(default_factory=dict)


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



def get_github_activity_manifest_path() -> Path:
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_home / "wballethin" / "weave" / "github-activity-manifest.json"



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


def render_callout(callout_type: str, title: str, body: str) -> str:
    lines = [f"> [!{callout_type}] {title}".rstrip()]
    normalized_body = body.rstrip()
    if not normalized_body:
        lines.append(">")
        return "\n".join(lines)
    for line in normalized_body.splitlines():
        if line:
            lines.append(f"> {line}")
        else:
            lines.append(">")
    return "\n".join(lines)


def get_session_message_count(session: SessionData) -> int:
    return len(session.turns) + sum(len(turn.assistant_texts) for turn in session.turns)


def render_session_turns(session: SessionData) -> str:
    parts: list[str] = []
    for turn in session.turns:
        ts = turn.timestamp.strftime("%H:%M:%S") if turn.timestamp else "??:??"
        parts.append(render_callout("note", f"User · {ts}", turn.user_text))
        parts.append("")
        assistant_prefix = ""
        if turn.tool_names:
            assistant_prefix = f"tools: {', '.join(turn.tool_names)}\n\n"
        assistant_texts = turn.assistant_texts or [""]
        for index, text in enumerate(assistant_texts):
            body = text
            if index == 0 and assistant_prefix:
                body = f"{assistant_prefix}{body}" if body else assistant_prefix.rstrip()
            parts.append(render_callout("quote", "Assistant", body))
            parts.append("")
    return "\n".join(parts).strip()


AGENT_SESSION_TEMPLATE = Environment(trim_blocks=True, lstrip_blocks=True).from_string(
    """---
type: agent_session
summary: {{ index_summary_json }}
agent: {{ agent }}
project: {{ project_json }}
session_id: {{ session_id_json }}
session_sha256: {{ session_sha256_json }}
---

## Summary

{{ body_summary }}

## Metrics

| Metric | Value |
|--------|-------|
| Agent | {{ agent }} |
| Project | {{ project }} |
| Started | {{ start }} |
| Ended | {{ end }} |
| Duration | {{ duration }} |
| Model(s) | {{ models_str }} |
{% if git_branch %}
| Git branch | {{ git_branch }} |
{% endif %}
| Messages | {{ message_count }} |
| User turns | {{ user_turns }} |
| Tool calls | {{ tool_calls }} |
| Input tokens | {{ input_tokens_fmt }} |
| Output tokens | {{ output_tokens_fmt }} |
| Cache read | {{ cache_read_fmt }} |
| Cache write | {{ cache_write_fmt }} |
| Total tokens | {{ total_tokens_fmt }} |
{% if cost %}
| Cost | ${{ cost }} |
{% endif %}

## Conversation

{{ conversation }}
"""
)


def render_session_note(
    session: SessionData,
    body_summary: str,
    session_sha256: str,
    index_summary: str = "",
) -> str:
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
        project_json=json.dumps(session.project),
        session_id_json=json.dumps(session.session_id),
        session_sha256_json=json.dumps(session_sha256),
        index_summary_json=json.dumps(index_summary),
        start=session.start_time.isoformat(timespec="seconds") if session.start_time else "unknown",
        end=session.end_time.isoformat(timespec="seconds") if session.end_time else "unknown",
        duration=_format_duration(session.duration) if session.duration else "unknown",
        models_str=", ".join(session.models) or "unknown",
        git_branch=session.git_branch,
        message_count=get_session_message_count(session),
        input_tokens_fmt=f"{usage.input_tokens:,}",
        output_tokens_fmt=f"{usage.output_tokens:,}",
        cache_read_fmt=f"{usage.cache_read_tokens:,}",
        cache_write_fmt=f"{usage.cache_write_tokens:,}",
        total_tokens_fmt=f"{total:,}",
        cost=f"{usage.cost:.4f}" if usage.cost else None,
        user_turns=len(session.turns),
        tool_calls=session.total_tool_calls,
        body_summary=body_summary,
        conversation=render_session_turns(session),
    )


class AgentSessionScraper:
    def __init__(
        self,
        sessions_dir: Path,
        output_dir: Path,
        summarizer: NoteSummarizer | None = None,
        index_summarizer: NoteSummarizer | None = None,
    ):
        self.sessions_dir = sessions_dir
        self.output_dir = output_dir
        self.summarizer = summarizer
        self.index_summarizer = index_summarizer

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

        turns_text = render_session_turns(session)
        body_summary = ""
        if self.summarizer:
            body_summary = self.summarizer.summarize(turns_text)
        index_summary = ""
        if self.index_summarizer:
            index_summary = self.index_summarizer.summarize(turns_text)

        content = render_session_note(
            session,
            body_summary,
            session_sha256,
            index_summary=index_summary,
        )
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


def get_front_matter_fields(content: str) -> dict[str, str]:
    parts = split_front_matter(content)
    if parts is None:
        return {}
    front_matter, _ = parts
    fields: dict[str, str] = {}
    for line in front_matter.splitlines():
        if not line or line.startswith((" ", "\t", "-")):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        fields[key.strip()] = parse_front_matter_scalar(value)
    return fields


def get_note_summary(content: str) -> str:
    return get_front_matter_fields(content).get("summary", "")


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


class GitHubActivitySyncer:
    def __init__(
        self,
        daily_note_writer: DailyNoteWriter,
        timezone_name: str,
        username: str | None = None,
        client: GitHubTimelineClient | None = None,
    ):
        self.daily_note_writer = daily_note_writer
        self.timezone = get_timezone(timezone_name)
        self.username = username
        self.client = client or GhCliGitHubTimelineClient()
        self._username_resolution_failed = False

    def run_once(self, now: datetime | None = None) -> int:
        username = self._get_username()
        if username is None:
            return 0
        try:
            events = fetch_user_events(
                client=self.client,
                username=username,
                pages=GITHUB_ACTIVITY_PAGES,
                per_page=GITHUB_ACTIVITY_PER_PAGE,
            )
        except GitHubActivityError as exc:
            logger.warning("github activity fetch failed: %s", exc)
            return 0

        records = collect_activity_records(events=events, client=self.client, enrich=True)
        grouped_days = self._group_days(records)
        eligible_days = [
            day for day in sorted(grouped_days.keys()) if self._is_stable_day(day, now=now)
        ]
        if not eligible_days:
            return 0

        manifest_path = get_github_activity_manifest_path()
        manifest = self._load_manifest(manifest_path)
        manifest_dirty = False
        updated_daily_notes = 0
        imported_at = datetime.now(tz=UTC).isoformat()

        for day in eligible_days:
            key = self._get_manifest_key(username, day)
            if key in manifest.days:
                continue
            day_records = grouped_days[day]
            if self.daily_note_writer.has_github_activity_section(day):
                manifest.days[key] = GitHubActivityManifestDay(
                    imported_at=imported_at,
                    rendered_items=len(day_records),
                    source_events=len(events),
                )
                manifest_dirty = True
                continue
            body = render_compact_activity_section(self._group_records_by_repo(day_records))
            if body:
                daily_path = self.daily_note_writer.upsert_github_activity_section(day, body)
                logger.info("updated github activity section %s", daily_path)
                updated_daily_notes += 1
            manifest.days[key] = GitHubActivityManifestDay(
                imported_at=imported_at,
                rendered_items=len(day_records),
                source_events=len(events),
            )
            manifest_dirty = True

        if manifest_dirty:
            self._save_manifest(manifest_path, manifest)
        return updated_daily_notes

    def _get_username(self) -> str | None:
        if self.username:
            return self.username
        if self._username_resolution_failed:
            return None
        try:
            self.username = self.client.get_authenticated_login()
        except GitHubActivityError as exc:
            logger.warning("github activity disabled: %s", exc)
            self._username_resolution_failed = True
            return None
        return self.username

    def _is_stable_day(self, day: dt_mod.date, now: datetime | None = None) -> bool:
        current = now or datetime.now(tz=self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)
        else:
            current = current.astimezone(self.timezone)
        stable_at = datetime.combine(
            day + dt_mod.timedelta(days=1),
            dt_mod.time(hour=GITHUB_ACTIVITY_STABILIZATION_HOURS),
            tzinfo=self.timezone,
        )
        return current >= stable_at

    def _group_days(self, records: list[Any]) -> dict[dt_mod.date, list[Any]]:
        grouped: dict[dt_mod.date, list[Any]] = defaultdict(list)
        for record in records:
            day = record.occurred_at.astimezone(self.timezone).date()
            grouped[day].append(record)
        return grouped

    def _group_records_by_repo(self, records: list[Any]) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = defaultdict(list)
        for record in records:
            grouped[record.repo].append(record)
        return grouped

    def _get_manifest_key(self, username: str, day: dt_mod.date) -> str:
        return f"{username}:{day.isoformat()}"

    def _load_manifest(self, manifest_path: Path) -> GitHubActivityManifest:
        if not manifest_path.exists():
            return GitHubActivityManifest()
        try:
            return GitHubActivityManifest.model_validate_json(manifest_path.read_text())
        except (OSError, ValidationError, json.JSONDecodeError) as exc:
            logger.warning("github activity manifest invalid, rebuilding: %s", exc)
            return GitHubActivityManifest()

    def _save_manifest(self, manifest_path: Path, manifest: GitHubActivityManifest) -> None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest.model_dump(), indent=2, sort_keys=True))


@dataclass(frozen=True)
class DailyIndexEntry:
    category: str
    entry_type: str
    note_path: Path
    label: str
    summary: str
    project: str = ""
    session_id: str = ""
    message_count: int | None = None


class DailyNoteWriter:
    def __init__(self, vault_root: Path, summarizer: NoteSummarizer | None = None):
        self.vault_root = vault_root
        self.summarizer = summarizer
        self._lock = threading.RLock()

    def append_note_entry(self, received: datetime, note_path: Path, entry_type: str) -> Path:
        with self._lock:
            self._get_or_create_summary(note_path)
            daily_path, _ = self._refresh_day(received.date())
            return daily_path

    def append_todo_entry(self, received: datetime, note_path: Path) -> Path:
        with self._lock:
            self._get_or_create_summary(note_path)
            daily_path, _ = self._refresh_day(received.date())
            return daily_path

    def has_github_activity_section(self, day: dt_mod.date) -> bool:
        with self._lock:
            weave_path = self.get_weave_daily_note_path_for_date(day)
            for path in (weave_path, self.get_daily_note_path_for_date(day)):
                try:
                    content = path.read_text()
                except OSError:
                    continue
                if self._get_section_body(content, "github-activity") is not None:
                    return True
            return False

    def upsert_github_activity_section(self, day: dt_mod.date, body: str) -> Path:
        with self._lock:
            return self._refresh_day(day, github_body=body)[0]

    def generate_all_weave_daily_notes(self) -> int:
        with self._lock:
            updated_count = 0
            for day in self._discover_days():
                _, changed = self._refresh_day(day, sync_personal=False)
                if changed:
                    updated_count += 1
            return updated_count

    def sync_all_daily_notes(self) -> int:
        with self._lock:
            updated_count = 0
            for day in self._discover_days():
                _, changed = self._refresh_day(day)
                if changed:
                    updated_count += 1
            return updated_count

    def sync_daily_note(self, daily_path: Path) -> bool:
        with self._lock:
            day = self._parse_day_from_path(daily_path)
            if day is None:
                return False
            _, changed = self._refresh_day(day)
            return changed

    def migrate_personal_daily_layout(self, format_string: str) -> int:
        with self._lock:
            folder = self.get_daily_notes_folder()
            settings = self._load_daily_note_settings()
            moved = 0
            for old_path in sorted(self._iter_personal_daily_note_paths()):
                day = self._parse_day_from_path(old_path)
                if day is None:
                    continue
                new_path = folder / render_daily_note_relative_path(day, format_string)
                if new_path == old_path:
                    continue
                new_path.parent.mkdir(parents=True, exist_ok=True)
                if new_path.exists():
                    if new_path.read_text() != old_path.read_text():
                        raise ConfigError(f"daily note destination already exists: {new_path}")
                    old_path.unlink()
                else:
                    old_path.replace(new_path)
                self._prune_empty_parents(old_path.parent, stop_at=folder)
                moved += 1
            settings["format"] = format_string
            self._write_daily_note_settings(settings)
            return moved

    def get_daily_note_path(self, received: datetime) -> Path:
        return self.get_daily_note_path_for_date(received.date())

    def get_daily_note_path_for_date(self, day: dt_mod.date) -> Path:
        folder = self.get_daily_notes_folder()
        return folder / render_daily_note_relative_path(day, self.get_daily_note_format())

    def get_weave_daily_note_path_for_date(self, day: dt_mod.date) -> Path:
        return self.vault_root / WEAVE_DAILY_RELATIVE_PATH / render_daily_note_relative_path(
            day,
            DEFAULT_NESTED_DAILY_NOTE_FORMAT,
        )

    def get_daily_notes_folder(self) -> Path:
        settings = self._load_daily_note_settings()
        folder = settings.get("folder")
        if isinstance(folder, str) and folder.strip():
            return self.vault_root / Path(folder)
        return self.vault_root

    def get_daily_note_format(self) -> str:
        settings = self._load_daily_note_settings()
        format_string = settings.get("format")
        if isinstance(format_string, str) and format_string.strip():
            return format_string
        return DEFAULT_DAILY_NOTE_FORMAT

    def render_entry_line(self, entry_type: str, note_path: Path, summary: str = "") -> str:
        label = sanitize_filename(note_path.stem)
        link = self.render_wikilink(note_path, label)
        parts = [f"- {entry_type}: {link}"]
        if summary and summary != label:
            parts.append(f"— {summary}")
        return " ".join(parts)

    def render_todo_line(self, note_path: Path, summary: str = "") -> str:
        label = sanitize_filename(note_path.stem)
        link = self.render_wikilink(note_path, label)
        parts = [f"- [ ] {link}"]
        if summary and summary != label:
            parts.append(f"— {summary}")
        return " ".join(parts)

    def render_wikilink(self, note_path: Path, label: str | None = None) -> str:
        relative = self._get_relative_path(note_path).as_posix()
        if label:
            safe_label = label.replace("]", "")
            return f"[[{relative}|{safe_label}]]"
        return f"[[{relative}]]"

    def render_embed(self, note_path: Path) -> str:
        relative = self._get_relative_path(note_path).as_posix()
        return f"![[{relative}]]"

    def render_managed_section(self, heading: str, section_name: str, body: str) -> str:
        start_marker, end_marker = get_managed_section_markers(section_name)
        lines = [heading, start_marker]
        normalized_body = body.rstrip()
        if normalized_body:
            lines.extend(normalized_body.splitlines())
        lines.append(end_marker)
        return "\n".join(lines)

    def render_github_activity_section(self, body: str) -> str:
        return self.render_managed_section(GITHUB_ACTIVITY_SECTION_HEADING, "github-activity", body)

    def render_weave_daily_note(
        self,
        entries: list[DailyIndexEntry],
        github_body: str | None = None,
    ) -> str:
        sections: list[str] = []
        for section_name, heading in WEAVE_SECTION_ORDER:
            if section_name == "github-activity":
                normalized_github = (github_body or "").strip()
                if normalized_github:
                    sections.append(
                        self.render_managed_section(
                            heading=f"## {heading}",
                            section_name=section_name,
                            body=normalized_github,
                        )
                    )
                continue
            if section_name == "agent-sessions":
                body = self._render_agent_session_section(
                    [entry for entry in entries if entry.category == section_name]
                )
            else:
                body = self._render_standard_section(
                    [entry for entry in entries if entry.category == section_name]
                )
            if body:
                sections.append(
                    self.render_managed_section(
                        heading=f"## {heading}",
                        section_name=section_name,
                        body=body,
                    )
                )
        if not sections:
            return ""
        return "\n\n".join(sections).rstrip() + "\n"

    def _refresh_day(
        self,
        day: dt_mod.date,
        github_body: str | None = None,
        sync_personal: bool = True,
    ) -> tuple[Path, bool]:
        personal_path = self.get_daily_note_path_for_date(day)
        weave_path = self.get_weave_daily_note_path_for_date(day)

        personal_content = ""
        if personal_path.exists():
            personal_content = personal_path.read_text()

        resolved_github_body = github_body
        if resolved_github_body is None and weave_path.exists():
            resolved_github_body = self._get_section_body(weave_path.read_text(), "github-activity")
        if resolved_github_body is None:
            resolved_github_body = self._get_section_body(personal_content, "github-activity")
        if resolved_github_body is not None:
            resolved_github_body = compact_legacy_activity_section(resolved_github_body)

        entries = self._collect_day_entries(day)
        new_weave_content = self.render_weave_daily_note(entries, github_body=resolved_github_body)
        weave_changed = False
        if new_weave_content:
            weave_changed = self._write_text_if_changed(weave_path, new_weave_content)
        elif weave_path.exists():
            weave_path.unlink()
            weave_changed = True

        personal_changed = False
        if sync_personal:
            personal_changed = self._sync_personal_daily_note(
                personal_path=personal_path,
                weave_path=weave_path,
                weave_exists=bool(new_weave_content),
                existing_content=personal_content,
            )
        result_path = personal_path if sync_personal else weave_path
        return result_path, weave_changed or personal_changed

    def _sync_personal_daily_note(
        self,
        personal_path: Path,
        weave_path: Path,
        weave_exists: bool,
        existing_content: str,
    ) -> bool:
        updated = self._remove_legacy_weave_content(existing_content)
        if weave_exists:
            updated = self._upsert_embed_region(updated, weave_path)
        if not existing_content and not updated:
            return False
        if existing_content == updated and personal_path.exists():
            return False
        personal_path.parent.mkdir(parents=True, exist_ok=True)
        personal_path.write_text(updated)
        return True

    def _remove_legacy_weave_content(self, content: str) -> str:
        if not content:
            return ""
        lines = content.splitlines()
        updated_lines: list[str] = []
        skip_github = False
        for line in lines:
            if line == LEGACY_GITHUB_ACTIVITY_SECTION_HEADING:
                continue
            if line == GITHUB_ACTIVITY_SECTION_START:
                skip_github = True
                continue
            if line == GITHUB_ACTIVITY_SECTION_END:
                skip_github = False
                continue
            if skip_github:
                continue
            if MANAGED_NOTE_LINE_RE.match(line) or MANAGED_TODO_LINE_RE.match(line):
                continue
            updated_lines.append(line)
        trailing_newline = "\n" if content.endswith("\n") else ""
        return "\n".join(updated_lines) + trailing_newline

    def _upsert_embed_region(self, content: str, weave_path: Path) -> str:
        region = (
            f"{PERSONAL_DAILY_EMBED_START}\n"
            f"{self.render_embed(weave_path)}\n"
            f"{PERSONAL_DAILY_EMBED_END}"
        )
        start = content.find(PERSONAL_DAILY_EMBED_START)
        end = content.find(PERSONAL_DAILY_EMBED_END)
        if start != -1 and end != -1 and end >= start:
            end += len(PERSONAL_DAILY_EMBED_END)
            return f"{content[:start]}{region}{content[end:]}"
        if not content:
            return f"{region}\n"
        if content.endswith("\n\n"):
            separator = ""
        elif content.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
        return f"{content}{separator}{region}\n"

    def _collect_day_entries(self, day: dt_mod.date) -> list[DailyIndexEntry]:
        day_dir = self.vault_root / SINK_RELATIVE_PATH / day.strftime("%Y/%m/%d")
        if not day_dir.exists():
            return []
        entries: list[DailyIndexEntry] = []
        for note_path in sorted(day_dir.glob("*.md")):
            entry = self._build_day_entry(note_path)
            if entry is not None:
                entries.append(entry)
        return entries

    def _build_day_entry(self, note_path: Path) -> DailyIndexEntry | None:
        try:
            content = note_path.read_text()
        except OSError:
            return None
        fields = get_front_matter_fields(content)
        summary = self._get_or_create_summary(note_path)
        note_type = fields.get("type", "")
        body = split_front_matter(content)
        body_text = body[1] if body else content
        label = fields.get("subject") or fields.get("event") or note_path.stem

        if note_type == "todo" or (fields.get("subject") and body_text.lstrip().startswith("## ")):
            return DailyIndexEntry(
                category="todos",
                entry_type="todo",
                note_path=note_path,
                label=fields.get("subject") or note_path.stem,
                summary=summary,
            )
        if note_type in {"meeting_notes", "meeting_chat"}:
            return DailyIndexEntry(
                category="meetings",
                entry_type=note_type.replace("_", " "),
                note_path=note_path,
                label=label,
                summary=summary,
            )
        if note_type == "agent_session":
            return DailyIndexEntry(
                category="agent-sessions",
                entry_type="agent session",
                note_path=note_path,
                label=note_path.stem,
                summary=summary,
                project=fields.get("project", "unknown") or "unknown",
                session_id=fields.get("session_id", note_path.stem),
                message_count=self._get_message_count(content),
            )
        if note_type == "transcript" or note_path.name.endswith("transcription.md"):
            return DailyIndexEntry(
                category="capture",
                entry_type="transcript",
                note_path=note_path,
                label=label,
                summary=summary,
            )
        if note_type == "handwriting" or fields.get("attachment", "").endswith(".pdf"):
            return DailyIndexEntry(
                category="capture",
                entry_type="handwriting",
                note_path=note_path,
                label=label,
                summary=summary,
            )
        return None

    def _render_standard_section(self, entries: list[DailyIndexEntry]) -> str:
        if not entries:
            return ""
        lines: list[str] = []
        for entry in entries:
            if entry.entry_type == "todo":
                line = f"- [ ] {self.render_wikilink(entry.note_path, entry.label)}"
            else:
                line = f"- {entry.entry_type}: {self.render_wikilink(entry.note_path, entry.label)}"
            if entry.summary and entry.summary != entry.label:
                line = f"{line} — {entry.summary}"
            lines.append(line)
        return "\n".join(lines)

    def _render_agent_session_section(self, entries: list[DailyIndexEntry]) -> str:
        if not entries:
            return ""
        grouped: dict[str, list[DailyIndexEntry]] = defaultdict(list)
        for entry in entries:
            grouped[entry.project].append(entry)
        lines: list[str] = []
        for project in sorted(grouped.keys()):
            lines.append(f"- {project}")
            for entry in sorted(grouped[project], key=lambda item: item.session_id):
                short_label = self._get_short_session_label(entry.session_id)
                line = f"  - {self.render_wikilink(entry.note_path, short_label)}"
                if entry.summary:
                    line = f"{line} — {entry.summary}"
                if entry.message_count is not None:
                    line = f"{line} ({entry.message_count} messages)"
                lines.append(line)
        return "\n".join(lines)

    def _get_short_session_label(self, session_id: str) -> str:
        tail = session_id.rsplit("/", 1)[-1]
        compact = re.sub(r"[^0-9a-zA-Z]", "", tail)
        if len(compact) >= 12:
            return compact[-12:]
        if len(tail) <= 12:
            return tail
        return tail[-12:]

    def _get_message_count(self, content: str) -> int | None:
        match = re.search(r"^\| Messages \| (?P<value>.+?) \|$", content, re.MULTILINE)
        if match is None:
            return None
        raw_value = match.group("value").replace(",", "").strip()
        return int(raw_value) if raw_value.isdigit() else None

    def _discover_days(self) -> list[dt_mod.date]:
        days: set[dt_mod.date] = set()
        sink_root = self.vault_root / SINK_RELATIVE_PATH
        if sink_root.exists():
            for note_path in sink_root.glob("????/??/??/*.md"):
                try:
                    relative = note_path.relative_to(sink_root)
                    days.add(
                        dt_mod.date(
                            int(relative.parts[0]),
                            int(relative.parts[1]),
                            int(relative.parts[2]),
                        )
                    )
                except (ValueError, IndexError):
                    continue
        for note_path in self._iter_personal_daily_note_paths():
            day = self._parse_day_from_path(note_path)
            if day is not None:
                days.add(day)
        weave_root = self.vault_root / WEAVE_DAILY_RELATIVE_PATH
        if weave_root.exists():
            for note_path in weave_root.rglob("*.md"):
                day = self._parse_day_from_path(note_path)
                if day is not None:
                    days.add(day)
        return sorted(days)

    def _iter_personal_daily_note_paths(self) -> list[Path]:
        folder = self.get_daily_notes_folder()
        if not folder.exists():
            return []
        return [path for path in folder.rglob("*.md") if path.is_file()]

    def _parse_day_from_path(self, path: Path) -> dt_mod.date | None:
        try:
            return dt_mod.date.fromisoformat(path.stem)
        except ValueError:
            return None

    def _get_section_body(self, content: str, section_name: str) -> str | None:
        if not content:
            return None
        start_marker, end_marker = get_managed_section_markers(section_name)
        start = content.find(start_marker)
        end = content.find(end_marker)
        if start == -1 or end == -1 or end < start:
            return None
        body_start = content.find("\n", start)
        if body_start == -1:
            return ""
        return content[body_start + 1 : end].strip("\n")

    def _write_text_if_changed(self, path: Path, content: str) -> bool:
        existing = None
        if path.exists():
            existing = path.read_text()
            if existing == content:
                return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return True

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

    def _get_relative_path(self, note_path: Path) -> Path:
        try:
            return note_path.relative_to(self.vault_root)
        except ValueError:
            return note_path

    def _load_daily_note_settings(self) -> dict[str, Any]:
        settings_path = self.vault_root / ".obsidian" / "daily-notes.json"
        if not settings_path.exists():
            return {}
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            return {}
        return settings if isinstance(settings, dict) else {}

    def _write_daily_note_settings(self, settings: dict[str, Any]) -> None:
        settings_path = self.vault_root / ".obsidian" / "daily-notes.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(settings, indent=2, sort_keys=True))

    def _prune_empty_parents(self, directory: Path, stop_at: Path) -> None:
        current = directory
        while current != stop_at and current.exists():
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


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
        self.github_activity_syncer = GitHubActivitySyncer(
            daily_note_writer=self.daily_note_writer,
            timezone_name=config.github_activity_timezone,
            username=config.github_activity_user,
        )

    def _init_agent_session_scraper(self, config: WeaveConfig) -> None:
        if config.agent_sessions_dir and not config.agent_sessions_dir.is_dir():
            raise ConfigError(f"Agent sessions directory not found: {config.agent_sessions_dir}")
        output_dir = config.vault_root / SINK_RELATIVE_PATH
        self.agent_session_scraper = AgentSessionScraper(
            sessions_dir=config.agent_sessions_dir,  # type: ignore[arg-type]
            output_dir=output_dir,
            summarizer=LlmNoteSummarizer(prompt=AGENT_SESSION_SUMMARY_PROMPT),
            index_summarizer=LlmNoteSummarizer(prompt=AGENT_SESSION_INDEX_SUMMARY_PROMPT),
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

    def run_github_activity_sync(self, now: datetime | None = None) -> int:
        try:
            return self.github_activity_syncer.run_once(now=now)
        except Exception as exc:
            logger.warning("github activity sync failed: %s", exc)
            return 0

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

    def run_github_activity_loop(
        self,
        interval: int = GITHUB_ACTIVITY_SYNC_INTERVAL_SECONDS,
    ) -> None:
        while not self._shutdown.is_set():
            count = self.run_github_activity_sync()
            if count > 0:
                logger.info("github activity sync: %d daily note(s)", count)
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
        github_count = self.run_github_activity_sync()
        self.run_daily_note_sync()
        return email_count + cal_count + session_count + github_count

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
        github_thread = threading.Thread(
            target=self.run_github_activity_loop,
            daemon=True,
            name="github-activity-maintenance",
        )
        github_thread.start()
        logger.info("started github activity maintenance thread")
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
    parser.add_argument(
        "--github-user",
        default=None,
        help="GitHub username override for daily activity import (or set WEAVE_GITHUB_USER)",
    )
    parser.add_argument(
        "--github-timezone",
        default=None,
        help="Timezone for GitHub activity day boundaries (or set WEAVE_GITHUB_TIMEZONE)",
    )
    parser.add_argument(
        "--generate-weave-daily-notes-only",
        action="store_true",
        help="Regenerate weave daily notes without touching personal daily notes, then exit",
    )
    parser.add_argument(
        "--migrate-daily-notes",
        action="store_true",
        help="Regenerate weave daily notes, clean legacy managed content, and exit",
    )
    parser.add_argument(
        "--daily-note-format",
        default=None,
        help=(
            "When used with --migrate-daily-notes, update Obsidian daily note layout "
            "to this format and move existing daily notes"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = get_args(argv)
    setup_logging(verbose=args.verbose, quiet=args.quiet)
    if not args.vault_root.exists():
        logger.error("vault root does not exist: %s", args.vault_root)
        raise SystemExit(1)
    if args.generate_weave_daily_notes_only and args.migrate_daily_notes:
        logger.error(
            "choose either --generate-weave-daily-notes-only or --migrate-daily-notes"
        )
        raise SystemExit(1)
    if args.generate_weave_daily_notes_only and args.daily_note_format:
        logger.error("--daily-note-format requires --migrate-daily-notes")
        raise SystemExit(1)
    if args.generate_weave_daily_notes_only:
        writer = DailyNoteWriter(vault_root=args.vault_root)
        count = writer.generate_all_weave_daily_notes()
        logger.info("regenerated %s weave daily note day(s)", count)
        return
    if args.migrate_daily_notes:
        writer = DailyNoteWriter(
            vault_root=args.vault_root,
            summarizer=LlmNoteSummarizer(prompt=SUMMARY_PROMPT),
        )
        if args.daily_note_format:
            moved = writer.migrate_personal_daily_layout(args.daily_note_format)
            logger.info("migrated %s personal daily note(s)", moved)
        count = writer.sync_all_daily_notes()
        logger.info("regenerated %s weave daily note day(s)", count)
        return
    try:
        config = WeaveConfig.from_runtime(
            vault_root=args.vault_root,
            poll_interval_seconds=args.poll_interval,
            calendar_source=args.source,
            agent_sessions_dir=args.agent_sessions,
            github_activity_user=args.github_user,
            github_activity_timezone=args.github_timezone,
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
