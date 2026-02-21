from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from memory_claw.config.models import SourceConfig
from memory_claw.domain.messages import NormalizedMessage


@dataclass(slots=True)
class DiscoveredSession:
    source: str
    session_id: str
    transcript_path: Path
    project: str | None
    cwd: str | None


class TranscriptAdapter(Protocol):
    name: str

    def discover_sessions(self, cfg: SourceConfig) -> list[DiscoveredSession]: ...

    def iter_messages(
        self,
        session: DiscoveredSession,
        from_line_exclusive: int,
    ) -> Iterator[NormalizedMessage]: ...
