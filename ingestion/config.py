"""Configuration loaded from environment variables.

Credentials never appear in source. Everything comes from `.env`, which is
gitignored, and is validated here so a misconfiguration fails immediately
with a clear message rather than as a confusing API error later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import plaid
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# plaid-python 42 exposes only Sandbox and Production; the old Development
# environment was retired.
PLAID_ENVIRONMENTS = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Validated runtime configuration."""

    plaid_client_id: str
    plaid_secret: str
    plaid_env: str
    snowflake_connection: str

    @property
    def plaid_host(self) -> str:
        return PLAID_ENVIRONMENTS[self.plaid_env]

    @property
    def is_production(self) -> bool:
        return self.plaid_env == "production"


def load_settings(env_file: Path | None = None) -> Settings:
    """Read and validate configuration from the environment.

    Defaults `PLAID_ENV` to sandbox rather than production: a missing or
    mistyped value must fail safe, never silently reach real accounts.
    """
    load_dotenv(env_file or REPO_ROOT / ".env")

    plaid_env = os.getenv("PLAID_ENV", "sandbox").strip().lower()
    if plaid_env not in PLAID_ENVIRONMENTS:
        valid = ", ".join(sorted(PLAID_ENVIRONMENTS))
        raise ConfigError(f"PLAID_ENV must be one of {valid}, got {plaid_env!r}")

    missing = [
        name
        for name in ("PLAID_CLIENT_ID", "PLAID_SECRET")
        if not os.getenv(name, "").strip()
    ]
    if missing:
        raise ConfigError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill them in."
        )

    return Settings(
        plaid_client_id=os.environ["PLAID_CLIENT_ID"].strip(),
        plaid_secret=os.environ["PLAID_SECRET"].strip(),
        plaid_env=plaid_env,
        snowflake_connection=os.getenv("SNOWFLAKE_CONNECTION_NAME", "pfin").strip(),
    )
