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

## Open questions (deferred to feature/snowflake-infra)

1. `RAW.PLAID_TRANSACTIONS` has no sync-disposition column. The
   `/transactions/sync` endpoint returns `added`, `modified`, and `removed`
   buckets; without a `_CHANGE_TYPE` marker, staging cannot distinguish an
   update from an insert or replay a removal. Likely fix: add the column
   before first real load.
2. No `INTERMEDIATE` schema exists even though the dbt design has an
   intermediate layer. Decide whether dbt creates it via its
   `CREATE SCHEMA` grant or it moves into the setup DDL.
3. The `GRANT ROLE PFIN_TRANSFORMER TO USER ...` statement is commented out
   (`setup/01_infrastructure.sql:146`), leaving the role assigned to nobody.
   Decide how to parameterize it so the rebuild stays one command with no
   manual Snowsight step.
4. Snowflake does not enforce primary key or unique constraints, so the
   ingestion idempotency guarantee must live in the loader as a `MERGE`
   (on `ITEM_ID` for `SYNC_STATE`, on `transaction_id` downstream), not in
   the schema.
