"""Thin wrapper over the Plaid API.

Deliberately does not know about Snowflake. It yields payloads; storage is
somebody else's job. That separation is what lets a second data domain
(Apple Health) reuse the loader without dragging Plaid along.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.products import Products
from plaid.model.sandbox_public_token_create_request import (
    SandboxPublicTokenCreateRequest,
)
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from ingestion.config import Settings

logger = logging.getLogger(__name__)

# Plaid caps /transactions/sync at 500 records per page.
MAX_PAGE_SIZE = 500


@dataclass
class SyncPage:
    """One page of /transactions/sync results.

    `removed` entries carry only a transaction_id, not a full transaction
    object, so downstream code must handle two payload shapes.
    """

    added: list[dict[str, Any]] = field(default_factory=list)
    modified: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: str = ""
    has_more: bool = False

    @property
    def total_records(self) -> int:
        return len(self.added) + len(self.modified) + len(self.removed)


def build_client(settings: Settings) -> plaid_api.PlaidApi:
    """Construct an authenticated Plaid API client."""
    configuration = plaid.Configuration(
        host=settings.plaid_host,
        api_key={
            "clientId": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def create_sandbox_item(
    client: plaid_api.PlaidApi,
    institution_id: str = "ins_109508",
) -> str:
    """Mint a sandbox access token without the browser-based Link flow.

    Sandbox lets us exchange a public token directly, so the whole pipeline
    can be developed and tested from a script. Production requires a real
    Link session, which is a separate piece of work.

    Default institution is First Platypus Bank, Plaid's standard sandbox
    fixture institution.
    """
    if not institution_id.startswith("ins_"):
        raise ValueError(f"institution_id must look like ins_..., got {institution_id!r}")

    public_token = client.sandbox_public_token_create(
        SandboxPublicTokenCreateRequest(
            institution_id=institution_id,
            initial_products=[Products("transactions")],
        )
    ).public_token

    return client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    ).access_token


def get_item_id(client: plaid_api.PlaidApi, access_token: str) -> str:
    """Resolve the Item id for an access token."""
    return client.accounts_get(
        AccountsGetRequest(access_token=access_token)
    ).item.item_id


def sync_transactions(
    client: plaid_api.PlaidApi,
    access_token: str,
    cursor: str | None = None,
    initial_attempts: int = 5,
    initial_backoff_seconds: float = 4.0,
) -> Iterator[SyncPage]:
    """Yield pages of transaction changes from /transactions/sync.

    Pagination is driven by `has_more`, following the cursor returned by each
    page. The caller is responsible for the ordering rule that makes this
    safe: persist every page before advancing the stored cursor. Advancing
    the cursor first would permanently lose any transactions in a page that
    failed to write, because Plaid never returns them again.

    On the first ever sync for an Item (no cursor), Plaid may still be
    performing its initial transaction pull. It signals this with an empty
    success response, not an error, which is indistinguishable from "nothing
    new has happened". So the first sync retries a few times before accepting
    an empty result. Later syncs take an empty page at face value, because by
    then it genuinely means no changes.
    """
    is_initial_sync = not cursor
    attempts_remaining = initial_attempts if is_initial_sync else 1
    page_number = 0
    while True:
        request = TransactionsSyncRequest(
            access_token=access_token,
            count=MAX_PAGE_SIZE,
        )
        # Plaid rejects an explicit null cursor; omit it entirely on the
        # first ever sync for an Item.
        if cursor:
            request.cursor = cursor

        response = client.transactions_sync(request).to_dict()
        page_number += 1

        page = SyncPage(
            added=response.get("added", []),
            modified=response.get("modified", []),
            removed=response.get("removed", []),
            next_cursor=response.get("next_cursor", ""),
            has_more=response.get("has_more", False),
        )
        logger.info(
            "sync page %d: %d added, %d modified, %d removed, has_more=%s",
            page_number,
            len(page.added),
            len(page.modified),
            len(page.removed),
            page.has_more,
        )
        # An empty first page means Plaid is probably still preparing the
        # Item. Wait and ask again rather than storing a cursor that skips
        # the initial backfill.
        if (
            is_initial_sync
            and page.total_records == 0
            and not page.has_more
            and attempts_remaining > 1
        ):
            attempts_remaining -= 1
            logger.info(
                "initial sync not ready, retrying in %.1fs (%d attempts left)",
                initial_backoff_seconds,
                attempts_remaining,
            )
            time.sleep(initial_backoff_seconds)
            continue

        yield page

        if not page.has_more:
            return
        cursor = page.next_cursor
        is_initial_sync = False


def get_accounts(client: plaid_api.PlaidApi, access_token: str) -> dict[str, Any]:
    """Fetch account metadata for an Item."""
    return client.accounts_get(AccountsGetRequest(access_token=access_token)).to_dict()


def get_balances(client: plaid_api.PlaidApi, access_token: str) -> dict[str, Any]:
    """Fetch a point-in-time balance snapshot for an Item."""
    return client.accounts_balance_get(
        AccountsBalanceGetRequest(access_token=access_token)
    ).to_dict()


def get_institution_name(
    client: plaid_api.PlaidApi, institution_id: str
) -> str | None:
    """Look up a human readable institution name, or None if unavailable."""
    from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest

    try:
        response = client.institutions_get_by_id(
            InstitutionsGetByIdRequest(
                institution_id=institution_id,
                country_codes=[CountryCode("US")],
            )
        )
        return response.institution.name
    except plaid.ApiException:
        logger.warning("could not resolve institution %s", institution_id)
        return None
