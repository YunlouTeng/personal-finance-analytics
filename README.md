# Personal Finance Analytics Platform

An end-to-end analytics pipeline over my own financial accounts:

```
Plaid API  ->  Python ingestion  ->  Snowflake (RAW)  ->  dbt  ->  Streamlit dashboard
```

This is both a working personal tool and a portfolio project. A second data
domain (Apple Health) will reuse the same ingestion and modeling pattern later.

## Repo layout

```
setup/            Snowflake DDL and bootstrap scripts (snow CLI)
ingestion/        Python: Plaid client, sync logic, Snowflake loader
dbt_project/      dbt Core project (staging -> intermediate -> marts)
streamlit_app/    Streamlit dashboard
docs/             Architecture notes, diagrams, decisions
```

Conventions, hard rules, and the git workflow live in [CLAUDE.md](CLAUDE.md).

## Prerequisites

- Python 3.11+ (managed here with [uv](https://docs.astral.sh/uv/))
- A Snowflake account
- A Plaid developer account

## First-time setup

1. Create the virtual environment and install dependencies:

   ```bash
   uv venv --python 3.11 .venv
   uv pip install --python .venv/bin/python -r requirements.txt
   ```

2. Install the Snowflake CLI as an isolated tool. It is kept out of
   `requirements.txt` on purpose; see the note in that file.

   ```bash
   uv tool install snowflake-cli
   ```

3. Create `~/.snowflake/connections.toml` with a `pfin` connection. This file
   holds real credentials and lives outside the repo:

   ```toml
   [pfin]
   account   = "<your_account_identifier>"
   user      = "<your_username>"
   password  = "<your_password>"
   warehouse = "PFIN_WH"
   database  = "PERSONAL_FINANCE"
   ```

   Then restrict it and verify: `chmod 600 ~/.snowflake/connections.toml`
   and `snow connection test -c pfin`.

4. Copy `.env.example` to `.env` and fill in the Plaid credentials. `.env` is
   gitignored and must stay that way.

5. Build the Snowflake environment:

   ```bash
   ./setup/bootstrap.sh
   ```

## Common commands

The venv must be active (`source .venv/bin/activate`) for `dbt` commands.

```bash
# Snowflake
snow connection test -c pfin
snow sql -f setup/01_infrastructure.sql -c pfin

# dbt
cd dbt_project && dbt debug
dbt build

# Streamlit
streamlit run streamlit_app/app.py

# Lint
ruff check .
```

## Status

- [x] Snowflake infrastructure DDL (`setup/`)
- [ ] Plaid ingestion (`ingestion/`)
- [ ] dbt staging, intermediate, and marts models (`dbt_project/`)
- [ ] Streamlit dashboard (`streamlit_app/`)

Design decisions are recorded in [docs/](docs/).
