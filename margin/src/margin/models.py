from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SourceFile(BaseModel):
    path: str
    text: str
    content_digest: str


class SourceSnapshot(BaseModel):
    title: str
    source_kind: Literal["local", "github"]
    source_label: str
    snapshot_id: str
    generated_at: datetime
    files: list[SourceFile] = Field(default_factory=list)
