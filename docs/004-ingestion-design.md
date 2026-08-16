# 004: Plaid ingestion design

Date: 2026-08-16

## The ordering rule that makes sync safe

`/transactions/sync` is a cursor-based delta feed. Each call returns changes
since the supplied cursor and a `next_cursor` to use next time. Once a cursor
is advanced, Plaid will never return those transactions again.

That single fact dictates the invariant: the stored cursor must never get
ahead of the rows it covers. The implementation goes one step further than
ordering and makes the whole run atomic:

1. Read the stored cursor for the Item from `RAW.SYNC_STATE`.
2. Loop calls to `/transactions/sync` while `has_more` is true, writing every
   page's rows inside an open Snowflake transaction.
3. `MERGE` the final cursor into `RAW.SYNC_STATE` in that same transaction.
4. Commit once.

A crash anywhere before the commit persists nothing: the next run re-fetches
from the old cursor with no loss and no duplicates from that failure mode.
Duplicates remain possible in principle (a replayed run after a successful
commit, Plaid re-serving history), so RAW stays append-only and dbt dedupes
by `transaction_id`.

If the cursor were ever committed ahead of its rows, those transactions would
be lost permanently, with no way to recover them from the API. This is the
difference between at-least-once and at-most-once delivery. For financial
data, always choose at-least-once and deduplicate downstream.

## Why the client knows nothing about Snowflake

`ingestion/plaid_client.py` yields payloads and has no storage imports. The
loader accepts payloads and knows nothing about Plaid. Keeping the seam there
is what lets a second data domain (Apple Health) reuse the loader unchanged,
which is a stated goal of the project.

## Access token storage

An access token grants ongoing read access to a linked bank account and does
not expire. Tokens live in `.plaid_items.json` at the repo root: gitignored,
mode 600, never in Snowflake.

Keeping them out of the warehouse is deliberate. `RAW.SYNC_STATE` holds the
Item id and cursor, both harmless, but a token in a warehouse table would be
readable by every role holding SELECT on RAW.

A plaintext local file is adequate for one user on a personal machine and
would not be acceptable in production, where tokens belong in a managed
secrets store with rotation and audit logging. The same caveat applies to
`.env`.

## Sandbox first

Sandbox can mint an access token from a script:
`/sandbox/public_token/create` followed by `/item/public_token/exchange`. No
browser, no Link session. That means the entire pipeline can be built and
tested before any real account is involved, and it produces payloads that are
safe to commit as test fixtures.

Production requires a real Link flow, which is deferred to its own branch.
`PLAID_ENV` defaults to sandbox so a missing or mistyped value fails safe
rather than reaching real accounts.

## Known compromise: the loader runs as ACCOUNTADMIN

The `pfin` connection is the only one configured, so ingestion currently
writes RAW as ACCOUNTADMIN. The production shape is a dedicated `PFIN_LOADER`
role holding INSERT on RAW and nothing else, with its own key pair. Deferred
until the pipeline is proven end to end; recorded here so it is a decision,
not an accident.
