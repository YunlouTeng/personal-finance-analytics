"""Local storage for Plaid Item access tokens.

An access token grants read access to a linked bank account and does not
expire, so it is a long lived secret. This module keeps tokens in a
gitignored JSON file at the repo root, mode 600.

That is adequate for a single user on a personal machine and is NOT how
this should work in production, where tokens belong in a managed secrets
store (AWS Secrets Manager, Vault) with rotation and audit logging. The
`.env` file holds API credentials for the same reason and with the same
caveat.

Tokens are deliberately kept out of Snowflake: RAW.SYNC_STATE records the
cursor and Item id, both of which are safe, but a token in a warehouse
table would be readable by every role with SELECT on RAW.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from ingestion.config import REPO_ROOT

ITEM_STORE_PATH = REPO_ROOT / ".plaid_items.json"


@dataclass(frozen=True)
class PlaidItem:
    """One linked institution."""

    item_id: str
    access_token: str
    institution_id: str | None = None
    institution_name: str | None = None
    environment: str = "sandbox"

    def redacted(self) -> dict[str, str | None]:
        """Representation safe to log or print."""
        data = asdict(self)
        data["access_token"] = f"<{len(self.access_token)} chars, redacted>"
        return data


def load_items(path: Path = ITEM_STORE_PATH) -> dict[str, PlaidItem]:
    """Load all stored Items, keyed by item_id. Empty if the file is absent."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {item_id: PlaidItem(**fields) for item_id, fields in raw.items()}


def save_item(item: PlaidItem, path: Path = ITEM_STORE_PATH) -> None:
    """Add or replace an Item, then restrict the file to the owner."""
    items = load_items(path)
    items[item.item_id] = item
    path.write_text(
        json.dumps(
            {item_id: asdict(value) for item_id, value in items.items()},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    os.chmod(path, 0o600)


def items_for_environment(
    environment: str, path: Path = ITEM_STORE_PATH
) -> list[PlaidItem]:
    """Return Items belonging to one Plaid environment.

    Sandbox and production tokens are not interchangeable, so callers must
    never mix them in a single sync run.
    """
    return [
        item for item in load_items(path).values() if item.environment == environment
    ]
