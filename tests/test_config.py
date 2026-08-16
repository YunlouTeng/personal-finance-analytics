"""Tests for configuration loading and validation."""

from __future__ import annotations

import pytest

from ingestion.config import ConfigError, load_settings


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ENV"):
        monkeypatch.delenv(name, raising=False)


def _write_env(tmp_path, body: str):
    path = tmp_path / ".env"
    path.write_text(body)
    return path


def test_defaults_to_sandbox_when_env_unset(tmp_path, clean_env):
    env = _write_env(tmp_path, "PLAID_CLIENT_ID=abc\nPLAID_SECRET=def\n")
    settings = load_settings(env)
    assert settings.plaid_env == "sandbox"
    assert settings.is_production is False


def test_rejects_unknown_environment(tmp_path, clean_env):
    env = _write_env(
        tmp_path, "PLAID_CLIENT_ID=abc\nPLAID_SECRET=def\nPLAID_ENV=developement\n"
    )
    with pytest.raises(ConfigError, match="PLAID_ENV must be one of"):
        load_settings(env)


def test_reports_all_missing_credentials_at_once(tmp_path, clean_env):
    env = _write_env(tmp_path, "PLAID_ENV=sandbox\n")
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert "PLAID_CLIENT_ID" in str(exc.value)
    assert "PLAID_SECRET" in str(exc.value)


def test_blank_credential_counts_as_missing(tmp_path, clean_env):
    env = _write_env(tmp_path, "PLAID_CLIENT_ID=   \nPLAID_SECRET=def\n")
    with pytest.raises(ConfigError, match="PLAID_CLIENT_ID"):
        load_settings(env)
