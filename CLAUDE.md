# Personal Finance Analytics Platform

## What this project is

An end-to-end analytics pipeline over my own financial accounts:

```
Plaid API  ->  Python ingestion  ->  Snowflake (RAW)  ->  dbt  ->  Streamlit dashboard
```

This is both a working personal tool and a portfolio project. Code quality,
commit hygiene, and documentation matter as much as the output. A second
data domain (Apple Health) will reuse the same pattern later, so keep
ingestion and modeling logic modular rather than Plaid-specific where it is
cheap to do so.

## Repo layout

```
setup/            Snowflake DDL and bootstrap scripts (snow CLI)
ingestion/        Python: Plaid client, sync logic, Snowflake loader
dbt_project/      dbt Core project (staging -> intermediate -> marts)
streamlit_app/    Streamlit dashboard
docs/             Architecture notes, diagrams, decisions
```

## Hard rules

1. **Never commit secrets.** No API keys, client IDs, client secrets, Plaid
   access tokens, account numbers, or Snowflake passwords in tracked files,
   ever. This includes example values in docstrings and comments.
2. Credentials come from `.env` (loaded with `python-dotenv`) and from
   `~/.snowflake/connections.toml`. Both live outside version control.
3. `.gitignore` must always cover: `.env`, `.env.*`, `*.log`, `__pycache__/`,
   `dbt_packages/`, `target/`, `logs/`, `data/raw/`, `.DS_Store`,
   `.streamlit/secrets.toml`.
4. Never commit real transaction data, account balances, institution names,
   or exported JSON payloads. Sample and test fixtures use Plaid Sandbox
   data only.
5. Do not run destructive Snowflake statements (`DROP`, `TRUNCATE`,
   `DELETE`) without asking me first. `CREATE OR REPLACE` on a RAW table
   counts as destructive.
6. Ask before installing new dependencies or adding a new service to the
   stack. Prefer the standard library and what is already in
   `requirements.txt`.

## Conventions

**Python**
- Python 3.11+, type hints on function signatures, `ruff` for linting.
- Configuration through environment variables, never hardcoded.
- Ingestion is idempotent: re-running a sync must not duplicate rows.

**SQL and dbt**
- Lowercase SQL keywords in dbt models, uppercase in `setup/*.sql` DDL.
- Model naming: `stg_<source>__<entity>`, `int_<description>`,
  `fct_<entity>`, `dim_<entity>`.
- Staging models: rename, cast, and clean only. No joins, no business logic.
- Every model gets a description and column-level tests in the matching
  `.yml`. At minimum `unique` and `not_null` on the primary key.
- Use `ref()` and `source()` everywhere. Never a hardcoded table name.
- Money is `NUMBER(18,2)`. Dates are `DATE`, timestamps are `TIMESTAMP_NTZ`.

**Snowflake**
- Objects live in `PERSONAL_FINANCE`. Warehouse is `PFIN_WH`.
- All infrastructure changes go in `setup/*.sql` so the environment stays
  reproducible from a clean account. Do not create objects ad hoc in
  Snowsight without adding them to the setup scripts.

## Git workflow

- `main` is stable and protected. Never commit directly to it.
- One branch per unit of work: `feature/plaid-ingestion`,
  `feature/dbt-staging`, `feature/net-worth-mart`, `fix/duplicate-txns`.
- Conventional commit messages: `feat:`, `fix:`, `docs:`, `refactor:`,
  `test:`, `chore:`.
- Every branch merges through a pull request with a real description of
  what changed and why, even though I am the only contributor.
- Do not push or open a PR without asking me.

## Useful commands

```bash
# Snowflake
snow connection test -c pfin
snow sql -f setup/01_infrastructure.sql -c pfin
snow sql -q "select count(*) from personal_finance.raw.plaid_transactions" -c pfin

# dbt
cd dbt_project && dbt debug
dbt build --select staging
dbt build          # run + test everything
dbt docs generate && dbt docs serve

# Streamlit
streamlit run streamlit_app/app.py
```

## Working style I want from you

- Explain the reasoning behind a design choice before writing the code,
  especially for the dbt layering and incremental logic. Learning the
  patterns is a goal of this project, not just shipping the tool.
- Prefer small, reviewable changes over large multi-file rewrites.
- Verify your work by running queries through `snow sql` rather than
  assuming a model built correctly.
- Flag anything that would not hold up in a production environment, even if
  it works here.
- No em dashes in documentation, comments, or README text.
