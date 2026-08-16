"""Sync orchestration: Plaid pages in, Snowflake rows out.

This module owns the correctness rule of the whole pipeline: every row from
a sync run and the cursor that covers them are committed in one Snowflake
transaction. A crash anywhere before the commit persists nothing, so the
next run re-fetches from the previous cursor. No data loss, and no
duplicates from that failure mode.

Duplicates can still occur if Plaid re-serves data after a commit (or the
same run is replayed end to end); RAW is append-only and dbt deduplicates
by transaction_id, so at-least-once delivery is the contract, exactly-once
is not.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from plaid.api import plaid_api

from ingestion import plaid_client
from ingestion.items import PlaidItem
from ingestion.loader import ACCOUNTS_TABLE, BALANCES_TABLE, SnowflakeLoader

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Outcome of one sync run for one Item."""

    item_id: str
    batch_id: str
    pages: int = 0
    rows: dict[str, int] = field(
        default_factory=lambda: {"added": 0, "modified": 0, "removed": 0}
    )
    final_cursor: str = ""

    @property
    def total_rows(self) -> int:
        return sum(self.rows.values())


def sync_item(
    client: plaid_api.PlaidApi,
    loader: SnowflakeLoader,
    item: PlaidItem,
) -> SyncResult:
    """Sync one Item's transactions into RAW, atomically with its cursor."""
    stored_cursor = loader.get_cursor(item.item_id)
    batch_id = uuid.uuid4().hex
    result = SyncResult(item_id=item.item_id, batch_id=batch_id)

    logger.info(
        "syncing item %s from %s",
        item.item_id,
        "start of history" if stored_cursor is None else "stored cursor",
    )

    with loader.transaction():
        for page in plaid_client.sync_transactions(
            client, item.access_token, cursor=stored_cursor
        ):
            result.pages += 1
            for change_type in ("added", "modified", "removed"):
                payloads = getattr(page, change_type)
                written = loader.insert_transactions(
                    payloads,
                    change_type=change_type,
                    item_id=item.item_id,
                    batch_id=batch_id,
                    sync_cursor=page.next_cursor,
                )
                result.rows[change_type] += written
            result.final_cursor = page.next_cursor

        # Same transaction as the rows above: this is the ordering rule.
        # Committing the cursor without the rows would lose data forever;
        # committing rows without the cursor would only duplicate.
        if result.final_cursor:
            loader.upsert_cursor(
                item.item_id, result.final_cursor, item.institution_name
            )

    logger.info(
        "item %s: %d pages, %s, batch %s",
        item.item_id,
        result.pages,
        result.rows,
        batch_id,
    )
    return result


def snapshot_item(
    client: plaid_api.PlaidApi,
    loader: SnowflakeLoader,
    item: PlaidItem,
) -> dict[str, int]:
    """Land point-in-time account and balance snapshots for one Item."""
    batch_id = uuid.uuid4().hex
    accounts = plaid_client.get_accounts(client, item.access_token)
    balances = plaid_client.get_balances(client, item.access_token)

    with loader.transaction():
        wrote_accounts = loader.insert_snapshot(
            ACCOUNTS_TABLE,
            accounts.get("accounts", []),
            item_id=item.item_id,
            batch_id=batch_id,
        )
        wrote_balances = loader.insert_snapshot(
            BALANCES_TABLE,
            balances.get("accounts", []),
            item_id=item.item_id,
            batch_id=batch_id,
        )
    return {"accounts": wrote_accounts, "balances": wrote_balances}
