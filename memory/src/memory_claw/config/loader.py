from __future__ import annotations

from pathlib import Path

import yaml

from memory_claw.config.models import AppConfig


def dump_config_yaml(config: AppConfig) -> str:
    payload = config.model_dump(mode="python")
    return yaml.safe_dump(payload, sort_keys=False)


def load_config(config_path: Path) -> AppConfig:
    raw = yaml.safe_load(config_path.read_text()) or {}
    return AppConfig.model_validate(raw)
