# 003: Raw layer design for /transactions/sync

Date: 2026-08-16

## The problem

`/transactions/sync` is a delta endpoint. Each call returns three buckets:

- `added`: full transaction objects that are new since the last cursor
- `modified`: full transaction objects that changed
- `removed`: **only** `transaction_id` values, not full objects

Two consequences follow. First, a landing table of bare payloads cannot
tell an insert from an update. Second, the `removed` bucket has a
completely different shape from the other two, so a schema that assumes
full transaction objects breaks on the first deletion.

Deletions are not an edge case here. Plaid removes a pending transaction
when it matches to a posted one, so a normal week of activity produces
them routinely. Getting this wrong means a dashboard that double counts
every pending charge that later posts.

## The decision

One table, `RAW.PLAID_TRANSACTIONS`, with a discriminator column:

```sql
PAYLOAD         VARIANT       NOT NULL,
_CHANGE_TYPE    VARCHAR       NOT NULL,  -- added | modified | removed
_ITEM_ID        VARCHAR       NOT NULL,
_BATCH_ID       VARCHAR       NOT NULL,
_SYNC_CURSOR    VARCHAR,
_LOADED_AT      TIMESTAMP_NTZ NOT NULL DEFAULT CURRENT_TIMESTAMP(),
_SOURCE_FILE    VARCHAR
```

### Why one table rather than three

Splitting `added` / `modified` / `removed` into separate tables would make
the staging model a three-way union that has to re-establish event ordering
across tables. A single append-only log with a type column preserves
arrival order naturally and matches how change data capture is normally
modeled. `VARIANT` absorbs the shape difference between full objects and
bare ids without complaint.

### Why _ITEM_ID

A Plaid Item is one linked institution. With more than one bank connected,
a row's Item is not reliably recoverable from the payload, and it is the
join key back to `RAW.SYNC_STATE`. Without it, a failed sync for one
institution cannot be isolated and replayed.

### Why _BATCH_ID

Groups every row written by a single sync run, including across the
`has_more` pagination loop. This makes it possible to answer "what did the
run at 09:00 actually write" and to delete a bad batch without guessing at
timestamp boundaries. `_LOADED_AT` alone is insufficient because rows
within one run share a timestamp to the second.

### Why the constraint is not enforced

Snowflake accepts `PRIMARY KEY` and `CHECK` syntax but enforces neither
(only `NOT NULL` is enforced). So the `_CHANGE_TYPE` domain and the
one-row-per-Item rule in `SYNC_STATE` are guaranteed by the loader, and
asserted downstream by dbt tests (`accepted_values` and `unique`). Anyone
reading the DDL and assuming the database is protecting them would be
wrong; hence the explicit comments in the script.

## How staging will consume this

`stg_plaid__transactions` reduces the append-only log to current state:

1. Extract `transaction_id` from `PAYLOAD` for all three change types.
2. Rank rows per `transaction_id` by `_LOADED_AT` descending, breaking ties
   within a batch deterministically.
3. Keep the latest row per `transaction_id`.
4. Filter out rows whose latest `_CHANGE_TYPE` is `removed`, or carry them
   through as a soft-delete flag so downstream models can choose.

Modeled as a soft delete rather than a hard filter, because the raw log
stays immutable and a removal can be audited later. That choice belongs to
the staging branch and is recorded here as the intended direction, not a
commitment.
