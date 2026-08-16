# 001: Initial architecture decisions

Date: 2026-08-16

Records the decisions baked into `setup/01_infrastructure.sql` so the
reasoning is not only in SQL comments.

## VARIANT landing tables instead of typed columns

Plaid returns nested JSON whose shape Plaid can extend at any time. The RAW
layer lands each payload untouched in a single `VARIANT` column plus load
metadata (`_LOADED_AT`, `_SOURCE_FILE`, `_SYNC_CURSOR`). This is the ELT
pattern: because the original payload is always recoverable, any downstream
modeling mistake can be fixed by rebuilding dbt models rather than
re-ingesting from Plaid. Typing, renaming, and flattening happen in dbt
staging models, where they are versioned and testable.

## AUTO_SUSPEND = 60 on PFIN_WH

An XSMALL warehouse that suspends 60 seconds after the last query is the
single most important cost control at personal scale. Nothing in this
pipeline needs a warm warehouse; auto-resume covers every access pattern.

## Dedicated PFIN_TRANSFORMER role for dbt

Running dbt as ACCOUNTADMIN would work but teaches nothing and would hide
permission mistakes. The transformer role can read RAW but not write it, and
owns STAGING and MARTS. This mirrors the production pattern of separating
ingestion privileges from transformation privileges.

## Idempotent DDL, one-command rebuild

Everything is `CREATE ... IF NOT EXISTS` so `setup/bootstrap.sh` can be
re-run safely. Snowflake trial accounts expire; the environment must be
redeployable from a clean account in one command, which is also why no
objects are ever created ad hoc in Snowsight.

## Resolved on feature/snowflake-infra (2026-08-16)

All four open questions were settled before the DDL was first executed, so
they became edits rather than migrations.

1. **Sync disposition: resolved.** `RAW.PLAID_TRANSACTIONS` now carries
   `_CHANGE_TYPE` (`added` / `modified` / `removed`), plus `_ITEM_ID` and
   `_BATCH_ID` for provenance. See `003-raw-layer-design.md` for the full
   reasoning. `_ITEM_ID` and `_BATCH_ID` were added to `PLAID_ACCOUNTS` and
   `PLAID_BALANCES` too, since multi-institution support needs them
   everywhere and retrofitting after real data lands is painful.
2. **INTERMEDIATE schema: created in the setup DDL.** dbt could have made it
   via its `CREATE SCHEMA` grant, but declaring it here keeps the entire
   environment described by one script, which is the whole point of a
   reproducible setup.
3. **Role grant: hardcoded to the operator's username.** A username is not a
   credential, and inlining it removes the last manual Snowsight step, so
   `bootstrap.sh` genuinely rebuilds everything in one command. Change it
   when deploying as a different user.
4. **Idempotency: confirmed as a loader responsibility.** `SYNC_STATE` now
   declares `PRIMARY KEY (ITEM_ID)`, but Snowflake accepts constraints
   without enforcing them, so this documents intent only. The real guarantee
   is a `MERGE` on `ITEM_ID`, and on `transaction_id` downstream.

## Open questions

None currently. Next decisions land with `feature/plaid-ingestion`.
