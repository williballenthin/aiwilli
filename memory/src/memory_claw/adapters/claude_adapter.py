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


class ClaudeTranscriptAdapter:
    name = "claude"

    def discover_sessions(self, cfg: SourceConfig) -> list[DiscoveredSession]:
        root = Path(cfg.root).expanduser()
        sessions: list[DiscoveredSession] = []
        if not root.exists():
            return sessions

        index_map = self._load_project_index_map(root)

        for path in root.rglob("*.jsonl"):
            if path.name in {"sessions-index.jsonl", "sessions-index.json"}:
                continue
            if "subagents" in path.parts:
                continue

            project_dir = self._project_dir_for_path(root, path)
            project_meta = index_map.get(project_dir, {})

            source_session_id = path.stem
            project_path = project_meta.get(source_session_id)

            parent = path.parent
            project = parent.name
            if project_path:
                project = Path(project_path).name

            sessions.append(
                DiscoveredSession(
                    source=self.name,
                    session_id=self._session_id_for_path(root, path),
                    transcript_path=path,
                    project=project,
                    cwd=project_path,
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
        is_sidechain = "subagents" in session.transcript_path.parts
        with session.transcript_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                if line_no <= from_line_exclusive:
                    continue

                record = json.loads(line)
                if not isinstance(record, dict):
                    continue

                record_type = record.get("type")
                if record_type not in {"user", "assistant"}:
                    continue

                message = record.get("message", {})
                if not isinstance(message, dict):
                    continue

                role_raw = message.get("role")
                role = role_raw if isinstance(role_raw, str) else cast(str, record_type)
                if role == "user":
                    normalized_role: Literal["user", "assistant", "tool"] = "user"
                elif role == "assistant":
                    normalized_role = "assistant"
                else:
                    continue

                content = message.get("content")
                content_text, content_blocks = _content_to_text(content)
                source_message_id = record.get("uuid") or message.get("id") or f"line-{line_no}"
                ts = _parse_ts(cast(str | None, record.get("timestamp") or message.get("timestamp")))
                cwd = message.get("cwd") or record.get("cwd") or session.cwd
                cwd_text = str(cwd) if cwd is not None else None

                yield NormalizedMessage(
                    source="claude",
                    session_id=session.session_id,
                    source_message_id=str(source_message_id),
                    role=normalized_role,
                    timestamp=ts,
                    project=session.project or (Path(cwd_text).name if cwd_text else None),
                    cwd=cwd_text,
                    content_text=content_text,
                    content_blocks=content_blocks,
                    parent_id=cast(str | None, message.get("parentId")),
                    is_sidechain=is_sidechain,
                    transcript_path=str(session.transcript_path),
                    raw_type=cast(str | None, record_type),
                    line_no=line_no,
                )

    def _load_project_index_map(self, root: Path) -> dict[Path, dict[str, str]]:
        mapping: dict[Path, dict[str, str]] = {}
        for project_dir in root.iterdir():
            if not project_dir.is_dir():
                continue
            index_path = project_dir / "sessions-index.json"
            if not index_path.exists():
                continue

            try:
                payload = json.loads(index_path.read_text())
            except Exception:
                continue

            entries = payload.get("entries", []) if isinstance(payload, dict) else []
            project_map: dict[str, str] = {}
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                session_id = entry.get("sessionId")
                project_path = entry.get("projectPath")
                if isinstance(session_id, str) and isinstance(project_path, str):
                    project_map[session_id] = project_path

            if project_map:
                mapping[project_dir] = project_map
        return mapping

    @staticmethod
    def _project_dir_for_path(root: Path, transcript_path: Path) -> Path:
        relative = transcript_path.relative_to(root)
        return root / relative.parts[0]
