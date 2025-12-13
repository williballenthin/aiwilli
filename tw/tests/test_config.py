"""Tests for configuration utilities."""

from pathlib import Path

import pytest

from tw.config import DEFAULT_DB_PATH, ConfigError, get_db_path, get_prefix


class TestGetDbPath:
    def test_returns_path_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TW_DB_PATH", "/tmp/tw.db")
        result = get_db_path()
        assert isinstance(result, Path)
        assert str(result) == "/tmp/tw.db"

    def test_returns_default_when_not_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TW_DB_PATH", raising=False)
        result = get_db_path()
        assert result == DEFAULT_DB_PATH
        assert result == Path.home() / ".local" / "state" / "tw" / "tw.db"


class TestGetPrefix:
    def test_prefers_tw_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TW_PREFIX", "TW")
        monkeypatch.setenv("TW_PROJECT_PREFIX", "PROJECT")
        result = get_prefix()
        assert result == "TW"

    def test_falls_back_to_tw_project_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TW_PREFIX", raising=False)
        monkeypatch.setenv("TW_PROJECT_PREFIX", "PROJECT")
        result = get_prefix()
        assert result == "PROJECT"

    def test_raises_config_error_when_neither_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TW_PREFIX", raising=False)
        monkeypatch.delenv("TW_PROJECT_PREFIX", raising=False)
        with pytest.raises(ConfigError):
            get_prefix()
