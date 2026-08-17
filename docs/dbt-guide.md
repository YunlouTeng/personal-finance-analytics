# Working with dbt in this project

A hands-on guide to the dbt side of the pipeline: what is already built, why
it looks the way it does, the commands you will actually use, and what you
build next. Read it with `dbt_project/` open in the editor.

## 1. The mental model

Everything upstream of dbt lands data; everything in dbt shapes it.

```
RAW (VARIANT payloads, append-only)      <- Python ingestion writes here
  -> STAGING (rename, cast, clean)       <- views, 1:1 with source tables
    -> INTERMEDIATE (joins, logic)       <- views, reusable building blocks
      -> MARTS (facts and dimensions)    <- tables, what Streamlit reads
```

A dbt "model" is one SELECT statement in one `.sql` file. dbt compiles it,
wraps it in `create view as` or `create table as`, and runs it in Snowflake
in dependency order. You never write DDL by hand and you never say what
order to build things in. The order comes from two functions:

- `{{ source('plaid', 'plaid_transactions') }}` declares "I read a raw
  table that dbt does not own."
- `{{ ref('stg_plaid__transactions') }}` declares "I read another model."

Those two calls are the entire dependency system. dbt scans them, builds the
DAG, and runs it. This is also why the charter bans hardcoded table names:
a hardcoded name is invisible to the DAG, so dbt cannot know to build your
dependency first, and the docs lineage graph lies.

## 2. The layer contract

Each layer has one job. The discipline of not leaking work between layers is
most of what "knowing dbt" means.

**Staging** (`models/staging/`): one model per source table, named
`stg_<source>__<entity>`. Allowed: rename columns, cast types, flatten
VARIANT, deduplicate, flag soft deletes. Not allowed: joins, filters that
encode business meaning, calculations. If you are tempted to join here,
that is an intermediate model asking to exist.

**Intermediate** (`models/intermediate/`): named `int_<description>`.
Joins and business logic live here, in reusable pieces. Example for this
project: `int_transactions_enriched` joining transactions to accounts so
every downstream mart gets institution and account type without repeating
the join.

**Marts** (`models/marts/`): named `fct_<entity>` for event-grained facts
and `dim_<entity>` for descriptive lookups. Materialized as tables because
the dashboard queries them repeatedly. This is the only layer Streamlit is
allowed to read.

## 3. Tour of what exists, file by file

**`dbt_project.yml`** is the project config. The part that matters:

```yaml
models:
  personal_finance:
    staging:
      +materialized: view
      +schema: staging
```

Any model under `models/staging/` becomes a view in the STAGING schema.
Directory placement is configuration; you will never write a
`materialized=` config inside a staging model file.

**`profiles.yml`** is the connection. dbt does not read
`~/.snowflake/connections.toml`, so the connection details are duplicated
here. Two things to notice: account and username come from environment
variables (`env_var(...)`), which is why they never appear in the repo, and
dbt runs as `PFIN_TRANSFORMER`, the least-privilege role from the setup DDL,
not ACCOUNTADMIN. If dbt ever fails with a permissions error, that role's
grants in `setup/01_infrastructure.sql` are the place to look.

**`macros/generate_schema_name.sql`** overrides a dbt default. Out of the
box, dbt would concatenate the profile schema and the model schema and
build into `STAGING_STAGING`. The override makes `+schema: staging` mean
literally STAGING. Almost every serious dbt project carries this macro.

**`models/staging/plaid/_plaid__sources.yml`** declares the raw tables so
`source()` can reference them, and attaches two things: freshness config
(dbt warns when RAW has not been loaded in 7 days) and source tests,
including `accepted_values` on `_change_type`. Remember that Snowflake
enforces almost nothing; dbt tests are where the guarantees actually live.

**`stg_plaid__transactions.sql`** is the most instructive file in the
project. Raw holds an append-only event log: the same transaction appears
again every time it is modified or removed. The model reduces the log to
current state with one idiom:

```sql
qualify row_number() over (
    partition by payload:transaction_id::string
    order by _loaded_at desc, _change_type desc
) = 1
```

Read it as: group events by transaction, sort newest first, keep row one.
`qualify` is Snowflake's filter-on-window-function clause; it saves a whole
subquery. The `_change_type desc` tiebreak is a small trick worth
remembering: within one batch, alphabetical order happens to be
removed > modified > added, exactly the precedence you want, and it makes
the dedupe deterministic.

Removed transactions are not filtered out. They come through with
`is_removed = true` and null data columns (Plaid sends only the id on
removal). This is a soft delete: downstream models decide to exclude them,
and the history stays auditable. Deleting data in staging would be a
business decision made in the wrong layer.

**`_plaid__models.yml`** documents each model and declares column tests.
The charter minimum is `unique` + `not_null` on every primary key. Tests
are not decoration: `unique` on `transaction_id` is the regression alarm
for the dedupe logic. If someone breaks the qualify clause, that test is
what fails.

## 4. The commands you will actually use

All dbt commands run from `dbt_project/` with the venv active and `.env`
loaded. The loading matters: `profiles.yml` reads env vars, so a shell
without them fails with a clear env_var error.

```bash
cd ~/Documents/personaltracker
source .venv/bin/activate
set -a && source .env && set +a
cd dbt_project
```

Daily loop:

```bash
dbt build --select staging     # run models + their tests, staging only
dbt build                      # the whole DAG
dbt run --select stg_plaid__transactions   # one model, no tests
dbt test --select stg_plaid__transactions  # tests only
```

Prefer `dbt build` over `dbt run`: build runs each model and then
immediately runs its tests before moving downstream, so a broken model
stops the DAG instead of poisoning everything after it.

Selection syntax worth knowing:

```bash
dbt build --select stg_plaid__transactions+   # model and everything downstream
dbt build --select +fct_transactions          # model and everything upstream
dbt build --select staging.plaid              # a directory
```

Occasional:

```bash
dbt debug                # connection and config check
dbt compile              # write compiled SQL to target/ without running
dbt source freshness     # check RAW recency against the freshness config
dbt docs generate && dbt docs serve   # lineage graph and column docs site
```

`dbt compile` is the debugging tool people underuse: the exact SQL dbt
would run, with all Jinja resolved, lands in `target/compiled/`. When a
model errors, read the compiled SQL and paste it into Snowsight.

The iteration loop in practice: edit the model file, `dbt build --select
<model>`, and if something looks wrong, query the view directly in
Snowsight or with `snow sql`. Views rebuild in about a second, which is why
staging stays views while you are learning.

## 5. Recipe: adding a new model

Using `int_transactions_enriched` as the worked example.

1. Create the directory and file:
   `models/intermediate/int_transactions_enriched.sql`. The directory
   placement alone makes it a view in INTERMEDIATE (already configured in
   `dbt_project.yml`).

2. Write the SELECT. Reference models, never tables:

   ```sql
   with transactions as (
       select * from {{ ref('stg_plaid__transactions') }}
       where not is_removed
   ),
   accounts as (
       select * from {{ ref('stg_plaid__accounts') }}
   )
   select
       transactions.*,
       accounts.account_name,
       accounts.account_type,
       accounts.account_subtype
   from transactions
   inner join accounts using (account_id)
   ```

   Note this is where `is_removed` finally gets filtered, and where the
   join lives. Neither belonged in staging.

3. Create `models/intermediate/_int__models.yml` with a description and at
   minimum `unique` + `not_null` on `transaction_id`.

4. `dbt build --select int_transactions_enriched`. Model runs, then its
   tests run. Green means built and verified.

5. Sanity-check row counts against the layer above. Enriched should equal
   staging transactions minus removed rows. If the join dropped rows, an
   account is missing from the accounts snapshot, and an `inner join`
   silently hid it. That instinct, checking counts across layers, catches
   more modeling bugs than anything else.

## 6. Testing beyond the column tests

Three levels, in the order you will meet them:

1. **Generic tests** in yml (`unique`, `not_null`, `accepted_values`,
   `relationships`). The `relationships` test is underrated: on
   `stg_plaid__transactions.account_id` against `stg_plaid__accounts`, it
   proves every transaction points at a known account.

2. **Singular tests**: a `.sql` file in `dbt_project/tests/` that selects
   rows that should not exist; any returned row fails the test. Example
   worth writing for this project, since it guards the ingestion contract:

   ```sql
   -- removed events must carry no amount
   select *
   from {{ ref('stg_plaid__transactions') }}
   where is_removed and amount is not null
   ```

3. **Unit tests** (dbt 1.8+): declare literal input rows and expected
   output rows in yml, and dbt runs the model against the fixture. The
   dedupe logic is the natural first candidate when you want to practice.

## 7. Your assignments, in order

Each one is small, builds on the last, and ends with a PR. Do them with me
or alone; either way the review conversation is where the learning sticks.

1. **`int_transactions_enriched`**: the recipe in section 5, done for real.
   Teaches: ref(), join placement, layer discipline, count reconciliation.

2. **`dim_accounts`**: marts-layer table over accounts, joined to
   `sync_state` for institution name. Teaches: table materialization, what
   belongs in a dimension.

3. **`fct_transactions`**: the event-grained fact. Starts as a plain table;
   then we talk about `materialized='incremental'`, `is_incremental()`, and
   `unique_key`, and when the switch is actually worth it. Teaches: the
   incremental pattern, which is the single most asked-about dbt topic in
   interviews.

4. **`fct_daily_balances`**: net worth over time from the balance
   snapshots, with a date spine. Teaches: time-series modeling from
   irregular snapshots, window functions for carry-forward.

5. **Freshness + docs polish**: `dbt docs generate`, read your own lineage
   graph, fix every model missing a description. Teaches: the metadata
   surface that makes a dbt project legible to other people, which is what
   separates portfolio projects that read as real from ones that read as
   tutorials.

## 8. Gotchas that will bite you exactly once

- **Env vars not loaded.** Every new terminal needs the
  `set -a && source .env && set +a` incantation before dbt. The failure
  message mentions env_var, which is your cue.
- **VARIANT keys are case sensitive.** `payload:date` works,
  `payload:Date` is silently null. Column names in Snowflake are case
  insensitive, JSON keys are not. A staging column coming out all null
  usually means a typo on the JSON path, not missing data.
- **`limit` needs quoting in VARIANT paths.** `payload:balances."limit"`
  because limit is a reserved word. Already handled in the balances model;
  you will hit it again with other reserved words.
- **qualify runs after where.** If you filter and dedupe in one CTE, the
  filter applies first. Usually what you want, occasionally not; when in
  doubt, separate the CTEs.
- **Never build into RAW.** dbt's role cannot write there, which is by
  design. If a model errors with insufficient privileges on RAW, the model
  is misconfigured, not the grants.
- **`dbt build` output says PASS per test, not per model.** A model with
  four tests produces five lines. Read failures bottom-up: the first
  failed model usually explains the cascade of skipped ones after it.

## 9. Where this goes next

Once marts exist and are stable, the project gets a deployment story: dbt
Projects on Snowflake, where a Snowsight workspace attaches to the GitHub
repo and a Snowflake Task schedules `dbt build` inside the platform. Local
dbt Core stays the development loop; the workspace becomes the scheduled
production run. That decision and its reasoning are recorded in
`docs/002-tooling-decisions.md`.
