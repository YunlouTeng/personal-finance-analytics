"""Snowflake writes for the ingestion pipeline.

Knows nothing about Plaid. It accepts dicts and writes them to RAW tables,
which is the seam that lets another data domain reuse this module.

All statements use fully qualified names because the connection deliberately
sets no default database. Money-adjacent payloads are landed as VARIANT via
PARSE_JSON; typing happens in dbt.

The connection authenticates via ~/.snowflake/connections.toml (key-pair
JWT). It currently runs as ACCOUNTADMIN, which is a documented compromise:
a production deployment would use a dedicated loader role holding INSERT on
RAW and nothing else.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Self

import snowflake.connector

logger = logging.getLogger(__name__)

DB = "PERSONAL_FINANCE"
TRANSACTIONS_TABLE = f"{DB}.RAW.PLAID_TRANSACTIONS"
ACCOUNTS_TABLE = f"{DB}.RAW.PLAID_ACCOUNTS"
BALANCES_TABLE = f"{DB}.RAW.PLAID_BALANCES"
SYNC_STATE_TABLE = f"{DB}.RAW.SYNC_STATE"


def _to_json(payload: dict[str, Any]) -> str:
    """Serialize a payload for PARSE_JSON.

    The Plaid SDK deserializes dates into datetime.date objects, which the
    stdlib json module rejects; default=str turns them back into ISO
    strings, matching what the API sent over the wire.
    """
    return json.dumps(payload, default=str)


class SnowflakeLoader:
    """Writes Plaid payloads and sync cursors to RAW.

    Usage:
        with SnowflakeLoader(connection_name="pfin") as loader:
            with loader.transaction():
                loader.insert_transactions(...)
                loader.upsert_cursor(...)
    """

    def __init__(self, connection_name: str = "pfin") -> None:
        self._conn = snowflake.connector.connect(
            connection_name=connection_name,
            autocommit=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """One atomic unit of work.

        Rows and the cursor that covers them commit together or not at all.
        A crash before commit persists nothing, so the next run re-fetches
        from the old cursor: no loss, no duplicates from this failure mode.
        """
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    # -- transactions ----------------------------------------------------

    def insert_transactions(
        self,
        payloads: Sequence[dict[str, Any]],
        change_type: str,
        item_id: str,
        batch_id: str,
        sync_cursor: str,
    ) -> int:
        """Append one bucket of /transactions/sync results.

        Allowed change types mirror the dbt accepted_values test; Snowflake
        itself enforces nothing beyond NOT NULL, so this guard is the only
        write-time check the values ever get.
        """
        if change_type not in ("added", "modified", "removed"):
            raise ValueError(f"invalid change_type: {change_type!r}")
        if not payloads:
            return 0
        rows = [
            (_to_json(p), change_type, item_id, batch_id, sync_cursor)
            for p in payloads
        ]
        self._insert_rows(
            TRANSACTIONS_TABLE,
            "PAYLOAD, _CHANGE_TYPE, _ITEM_ID, _BATCH_ID, _SYNC_CURSOR",
            rows,
        )
        logger.info("wrote %d %s rows for item %s", len(rows), change_type, item_id)
        return len(rows)


    # Rows per INSERT statement. Each row binds len(columns) parameters and
    # Snowflake caps binds per statement at 16,384, so 500 rows of up to 5
    # columns stays an order of magnitude under the limit.
    _CHUNK = 500

    def _insert_rows(
        self, table: str, columns: str, rows: Sequence[tuple]
    ) -> None:
        """Multi-row insert through SELECT ... FROM VALUES.

        The first column of every row is a JSON string landed via
        PARSE_JSON. A plain executemany cannot do this: the connector
        fails to rewrite INSERT ... SELECT into its bulk form (error
        252001), so we build the multi-row statement ourselves.
        """
        width = len(rows[0])
        placeholder = "(" + ", ".join(["%s"] * width) + ")"
        select_cols = ", ".join(
            ["parse_json(column1)"] + [f"column{i}" for i in range(2, width + 1)]
        )
        with self._conn.cursor() as cur:
            for start in range(0, len(rows), self._CHUNK):
                chunk = rows[start : start + self._CHUNK]
                values = ", ".join([placeholder] * len(chunk))
                params = [value for row in chunk for value in row]
                cur.execute(
                    f"insert into {table} ({columns}) "
                    f"select {select_cols} from values {values}",
                    params,
                )

    # -- snapshots -------------------------------------------------------

    def insert_snapshot(
        self,
        table: str,
        payloads: Sequence[dict[str, Any]],
        item_id: str,
        batch_id: str,
    ) -> int:
        """Append account or balance snapshot payloads."""
        if table not in (ACCOUNTS_TABLE, BALANCES_TABLE):
            raise ValueError(f"unexpected snapshot table: {table!r}")
        if not payloads:
            return 0
        rows = [(_to_json(p), item_id, batch_id) for p in payloads]
        self._insert_rows(table, "PAYLOAD, _ITEM_ID, _BATCH_ID", rows)
        return len(rows)

    # -- cursor state ----------------------------------------------------

    def get_cursor(self, item_id: str) -> str | None:
        """Return the stored cursor for an Item, or None on first sync."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"select CURSOR from {SYNC_STATE_TABLE} where ITEM_ID = %s",
                (item_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def upsert_cursor(
        self, item_id: str, cursor: str, institution: str | None = None
    ) -> None:
        """MERGE the new cursor for an Item.

        MERGE rather than insert because SYNC_STATE's PRIMARY KEY is not
        enforced by Snowflake; this statement is what actually guarantees
        one row per Item.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                merge into {SYNC_STATE_TABLE} target
                using (select %s as ITEM_ID, %s as CURSOR, %s as INSTITUTION) source
                on target.ITEM_ID = source.ITEM_ID
                when matched then update set
                    CURSOR = source.CURSOR,
                    INSTITUTION = coalesce(source.INSTITUTION, target.INSTITUTION),
                    LAST_SYNCED_AT = current_timestamp()
                when not matched then insert (ITEM_ID, INSTITUTION, CURSOR)
                    values (source.ITEM_ID, source.INSTITUTION, source.CURSOR)
                """,
                (item_id, cursor, institution),
            )
