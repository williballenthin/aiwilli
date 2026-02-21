from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ObservationItem(BaseModel):
    importance: Literal["🔴", "🟡", "🟢"]
    signal_type: str
    summary: str
    why: str


class ObservationBlock(BaseModel):
    timestamp: datetime
    project: str | None = None
    src_path: str
    src_messages: list[str] = Field(default_factory=list)
    items: list[ObservationItem] = Field(default_factory=list)


class ExtractorOutput(BaseModel):
    extractor_name: str
    date: date
    blocks: list[ObservationBlock] = Field(default_factory=list)


class ReflectorResult(BaseModel):
    full_markdown: str
    summary: str
