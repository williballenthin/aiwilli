from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NormalizedMessage(BaseModel):
    source: Literal["pi", "claude"]
    session_id: str
    source_message_id: str
    role: Literal["user", "assistant", "tool"]
    timestamp: datetime
    project: str | None = None
    cwd: str | None = None
    content_text: str
    content_blocks: list[dict] = Field(default_factory=list)
    parent_id: str | None = None
    is_sidechain: bool = False
    transcript_path: str
    raw_type: str | None = None
    line_no: int
