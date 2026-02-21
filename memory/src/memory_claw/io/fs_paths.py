from __future__ import annotations

from pathlib import Path


class Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def config(self) -> Path:
        return self.root / "config.yaml"

    @property
    def global_memory(self) -> Path:
        return self.root / "global_memory.md"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"

    @property
    def observations_dir(self) -> Path:
        return self.root / "observations"

    @property
    def state_db(self) -> Path:
        return self.root / "state.db"

    @property
    def gitignore(self) -> Path:
        return self.root / ".gitignore"

    @property
    def schema(self) -> Path:
        return Path(__file__).resolve().parent.parent / "store" / "schema.sql"

    def observation_daily_file(self, extractor: str, yyyy_mm_dd: str) -> Path:
        return self.observations_dir / extractor / f"{yyyy_mm_dd}.md"
