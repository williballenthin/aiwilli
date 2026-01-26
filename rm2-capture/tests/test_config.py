
import pytest

from rm2_capture.config import Config, ConfigError


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret123")
    monkeypatch.setenv("FILTER_TO_ADDRESS", "user+remarkable@example.com")
    monkeypatch.setenv("ALLOWED_SENDERS", "device@remarkable.com, other@sender.com")


def test_config_from_env(env_vars):
    config = Config.from_env()

    assert config.imap_host == "imap.example.com"
    assert config.imap_user == "user@example.com"
    assert config.imap_password == "secret123"
    assert config.filter_to_address == "user+remarkable@example.com"
    assert config.allowed_senders == ["device@remarkable.com", "other@sender.com"]


def test_config_missing_env_var(monkeypatch):
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")

    with pytest.raises(ConfigError) as exc_info:
        Config.from_env()

    assert "IMAP_USER" in str(exc_info.value)
    assert "IMAP_PASSWORD" in str(exc_info.value)


def test_config_strips_whitespace_from_senders(monkeypatch):
    monkeypatch.setenv("IMAP_HOST", "imap.example.com")
    monkeypatch.setenv("IMAP_USER", "user@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "secret123")
    monkeypatch.setenv("FILTER_TO_ADDRESS", "user+remarkable@example.com")
    monkeypatch.setenv("ALLOWED_SENDERS", "  one@test.com  ,  two@test.com  ")

    config = Config.from_env()

    assert config.allowed_senders == ["one@test.com", "two@test.com"]
