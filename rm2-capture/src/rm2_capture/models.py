from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


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
