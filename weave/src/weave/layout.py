from __future__ import annotations

import datetime as dt_mod
from dataclasses import dataclass
from pathlib import Path

DAILY_RELATIVE_PATH = Path("daily")
ATTACHMENTS_DIRNAME = "_attachments"
WEAVE_DATA_DIRNAME = "_weave"
TRANSCRIPTIONS_DIRNAME = "transcriptions"
SCANS_DIRNAME = "scans"
TODO_DIRNAME = "todo"
MEETING_NOTES_DIRNAME = "meeting notes"
AGENT_SESSIONS_DIRNAME = "agent sessions"
GITHUB_ACTIVITY_SNAPSHOT_NAME = "github activity.md"


@dataclass(frozen=True)
class VaultLayout:
    vault_root: Path

    @property
    def daily_root(self) -> Path:
        return self.vault_root / DAILY_RELATIVE_PATH

    def get_day_dir(self, day: dt_mod.date) -> Path:
        return self.daily_root / day.strftime("%Y/%m/%d")

    def get_attachments_dir(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day) / ATTACHMENTS_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_weave_data_dir(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day) / WEAVE_DATA_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_transcriptions_dir(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day) / TRANSCRIPTIONS_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_scans_dir(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day) / SCANS_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_todo_dir(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day) / TODO_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_meeting_notes_dir(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day) / MEETING_NOTES_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_agent_sessions_dir(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day) / AGENT_SESSIONS_DIRNAME
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_weave_daily_note_path(self, day: dt_mod.date) -> Path:
        path = self.get_day_dir(day)
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{day.isoformat()} weave.md"

    def get_github_activity_snapshot_path(self, day: dt_mod.date) -> Path:
        return self.get_weave_data_dir(day) / GITHUB_ACTIVITY_SNAPSHOT_NAME

    def iter_day_dirs(self) -> list[Path]:
        if not self.daily_root.exists():
            return []
        return sorted(path for path in self.daily_root.glob("????/??/??") if path.is_dir())
