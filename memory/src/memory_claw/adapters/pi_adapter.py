from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal, cast

from memory_claw.adapters.base import DiscoveredSession
from memory_claw.config.models import SourceConfig
from memory_claw.domain.messages import NormalizedMessage


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _content_to_text(content: object) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(content, str):
        return content, []

    if not isinstance(content, list):
        return "", []

    blocks: list[dict[str, Any]] = []
    texts: list[str] = []
    for raw_block in content:
        if not isinstance(raw_block, dict):
            continue
        block = cast(dict[str, Any], raw_block)
        blocks.append(block)
        text_value = block.get("text")
        if text_value:
            texts.append(str(text_value).strip())

    return "\n".join(texts).strip(), blocks


class PiTranscriptAdapter:
    name = "pi"

    def discover_sessions(self, cfg: SourceConfig) -> list[DiscoveredSession]:
        root = Path(cfg.root).expanduser()
        sessions: list[DiscoveredSession] = []
        if not root.exists():
            return sessions

        for path in root.rglob("*.jsonl"):
            sessions.append(
                DiscoveredSession(
                    source=self.name,
                    session_id=self._session_id_for_path(root, path),
                    transcript_path=path,
                    project=path.parent.name,
                    cwd=None,
                )
            )
        return sessions

    @staticmethod
    def _session_id_for_path(root: Path, transcript_path: Path) -> str:
        try:
            return transcript_path.relative_to(root).as_posix()
        except ValueError:
            return transcript_path.resolve().as_posix()

    def iter_messages(
        self,
        session: DiscoveredSession,
        from_line_exclusive: int,
    ) -> Iterator[NormalizedMessage]:
        cwd = session.cwd
        with session.transcript_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line_no <= from_line_exclusive:
                    continue

                record = json.loads(line)
                record_type = record.get("type")
                if record_type == "session" and not cwd:
                    record_cwd = record.get("cwd")
                    if isinstance(record_cwd, str):
                        cwd = record_cwd
                    continue

                if record_type != "message":
                    continue

                msg = record.get("message", {})
                if not isinstance(msg, dict):
                    continue

                role_raw = msg.get("role")
                if role_raw == "user":
                    normalized_role: Literal["user", "assistant", "tool"] = "user"
                elif role_raw == "assistant":
                    normalized_role = "assistant"
                elif role_raw == "toolResult":
                    normalized_role = "tool"
                else:
                    continue

                content_text, content_blocks = _content_to_text(msg.get("content"))
                source_message_id = record.get("id") or msg.get("id") or f"line-{line_no}"
                ts = _parse_ts(cast(str | None, record.get("timestamp") or msg.get("timestamp")))
                project = Path(cwd).name if cwd else session.project

                yield NormalizedMessage(
                    source="pi",
                    session_id=session.session_id,
                    source_message_id=str(source_message_id),
                    role=normalized_role,
                    timestamp=ts,
                    project=project,
                    cwd=cwd,
                    content_text=content_text,
                    content_blocks=content_blocks,
                    parent_id=cast(str | None, msg.get("parentId")),
                    is_sidechain=False,
                    transcript_path=str(session.transcript_path),
                    raw_type=cast(str | None, record_type),
                    line_no=line_no,
                )
