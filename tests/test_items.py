"""Tests for the Plaid Item store.

Deliberately import-light: these exercise storage logic and never touch the
Plaid SDK, so they run instantly.
"""

from __future__ import annotations

import json
import os
import stat

from ingestion.items import PlaidItem, items_for_environment, load_items, save_item


def test_load_items_returns_empty_when_file_absent(tmp_path):
    assert load_items(tmp_path / "nope.json") == {}


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "items.json"
    item = PlaidItem(
        item_id="item-1",
        access_token="access-sandbox-secret",
        institution_id="ins_109508",
        institution_name="First Platypus Bank",
        environment="sandbox",
    )
    save_item(item, path)

    loaded = load_items(path)
    assert loaded == {"item-1": item}


def test_save_item_replaces_existing_and_keeps_others(tmp_path):
    path = tmp_path / "items.json"
    save_item(PlaidItem(item_id="a", access_token="token-a"), path)
    save_item(PlaidItem(item_id="b", access_token="token-b"), path)
    save_item(PlaidItem(item_id="a", access_token="token-a-rotated"), path)

    loaded = load_items(path)
    assert set(loaded) == {"a", "b"}
    assert loaded["a"].access_token == "token-a-rotated"


def test_saved_file_is_owner_only(tmp_path):
    path = tmp_path / "items.json"
    save_item(PlaidItem(item_id="a", access_token="token-a"), path)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_redacted_hides_the_token():
    item = PlaidItem(item_id="a", access_token="access-sandbox-verysecret")
    redacted = item.redacted()
    assert "verysecret" not in json.dumps(redacted)
    assert redacted["item_id"] == "a"


def test_items_for_environment_does_not_mix_sandbox_and_production(tmp_path):
    path = tmp_path / "items.json"
    save_item(PlaidItem(item_id="s", access_token="t", environment="sandbox"), path)
    save_item(PlaidItem(item_id="p", access_token="t", environment="production"), path)

    sandbox = items_for_environment("sandbox", path)
    assert [item.item_id for item in sandbox] == ["s"]
