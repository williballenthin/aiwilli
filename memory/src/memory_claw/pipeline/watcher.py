from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memory_claw.adapters.base import TranscriptAdapter
from memory_claw.config.models import AppConfig
from memory_claw.store.repositories import StateRepository


@dataclass(slots=True)
class WatcherRunResult:
    sessions_seen: int = 0
    messages_ingested: int = 0
    errors: int = 0


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


class Watcher:
    def __init__(
        self,
        config: AppConfig,
        repo: StateRepository,
        adapters: dict[str, TranscriptAdapter],
    ) -> None:
        self.config = config
        self.repo = repo
        self.adapters = adapters

    def run_once(self) -> WatcherRunResult:
        result = WatcherRunResult()

        for source_name, source_cfg in self.config.sources.items():
            if not source_cfg.enabled:
                continue

            adapter = self.adapters.get(source_name)
            if adapter is None:
                continue

            sessions = adapter.discover_sessions(source_cfg)
            result.sessions_seen += len(sessions)
            for session in sessions:
                try:
                    self.repo.upsert_session(
                        source=session.source,
                        session_id=session.session_id,
                        transcript_path=str(session.transcript_path),
                        project=session.project,
                        cwd=session.cwd,
                    )

                    cursor = self.repo.get_session_cursor(session.source, session.session_id)
                    total_lines = _count_lines(session.transcript_path)
                    if total_lines <= cursor:
                        continue

                    for msg in adapter.iter_messages(session, cursor):
                        self.repo.upsert_message(msg)
                        result.messages_ingested += 1

                    self.repo.update_session_cursor(session.source, session.session_id, total_lines)
                except Exception:
                    result.errors += 1

        self.repo.commit()
        return result
