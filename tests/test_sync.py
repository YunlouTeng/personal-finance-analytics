"""Tests for sync orchestration.

A FakeLoader stands in for Snowflake and records every call with its
transaction state, so these tests verify the correctness rule directly:
rows and cursor commit together, and a failure leaves nothing behind.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from ingestion.items import PlaidItem
from ingestion.plaid_client import SyncPage
from ingestion.sync import sync_item

ITEM = PlaidItem(
    item_id="item-1",
    access_token="access-sandbox-test",
    institution_name="Test Bank",
)


class FakeLoader:
    """Records loader calls and mimics transaction semantics."""

    def __init__(self, stored_cursor=None):
        self.stored_cursor = stored_cursor
        self.calls: list[tuple] = []
        self.committed: list[tuple] = []
        self.in_transaction = False

    @contextmanager
    def transaction(self):
        self.in_transaction = True
        pending_from = len(self.calls)
        try:
            yield
        except Exception:
            # rollback: pending calls are discarded
            del self.calls[pending_from:]
            raise
        else:
            self.committed.extend(self.calls[pending_from:])
        finally:
            self.in_transaction = False

    def get_cursor(self, item_id):
        return self.stored_cursor

    def insert_transactions(self, payloads, change_type, item_id, batch_id,
                            sync_cursor):
        assert self.in_transaction, "insert outside transaction"
        if payloads:
            self.calls.append(("rows", change_type, len(payloads), sync_cursor))
        return len(payloads)

    def upsert_cursor(self, item_id, cursor, institution=None):
        assert self.in_transaction, "cursor write outside transaction"
        self.calls.append(("cursor", cursor))


class FakeClient:
    pass


def _pages(monkeypatch, pages):
    def fake_sync(client, access_token, cursor=None, **kwargs):
        yield from pages

    monkeypatch.setattr("ingestion.sync.plaid_client.sync_transactions", fake_sync)


def test_rows_and_cursor_commit_together(monkeypatch):
    loader = FakeLoader()
    _pages(
        monkeypatch,
        [
            SyncPage(added=[{"a": 1}, {"a": 2}], next_cursor="c1", has_more=True),
            SyncPage(modified=[{"a": 3}], removed=[{"transaction_id": "t"}],
                     next_cursor="c2", has_more=False),
        ],
    )

    result = sync_item(FakeClient(), loader, ITEM)

    assert result.rows == {"added": 2, "modified": 1, "removed": 1}
    assert result.final_cursor == "c2"
    # The cursor write is in the same committed unit as every row write,
    # and it is the final cursor, not an intermediate page cursor.
    assert ("cursor", "c2") in loader.committed
    row_events = [c for c in loader.committed if c[0] == "rows"]
    assert len(row_events) == 3


def test_failure_mid_sync_persists_nothing(monkeypatch):
    loader = FakeLoader()

    def exploding_pages(client, access_token, cursor=None, **kwargs):
        yield SyncPage(added=[{"a": 1}], next_cursor="c1", has_more=True)
        raise RuntimeError("network died mid-pagination")

    monkeypatch.setattr(
        "ingestion.sync.plaid_client.sync_transactions", exploding_pages
    )

    with pytest.raises(RuntimeError):
        sync_item(FakeClient(), loader, ITEM)

    # Nothing committed: no rows, and critically no cursor, so the next
    # run re-fetches everything from the previous cursor.
    assert loader.committed == []


def test_empty_sync_does_not_regress_cursor(monkeypatch):
    loader = FakeLoader(stored_cursor="existing")
    _pages(monkeypatch, [SyncPage(next_cursor="c-new", has_more=False)])

    result = sync_item(FakeClient(), loader, ITEM)

    # An empty page still advances the cursor (Plaid may compact history),
    # and does so inside a committed transaction.
    assert result.total_rows == 0
    assert ("cursor", "c-new") in loader.committed


def test_removed_rows_are_written_not_dropped(monkeypatch):
    loader = FakeLoader()
    _pages(
        monkeypatch,
        [SyncPage(removed=[{"transaction_id": "gone"}], next_cursor="c",
                  has_more=False)],
    )

    sync_item(FakeClient(), loader, ITEM)

    assert ("rows", "removed", 1, "c") in loader.committed
