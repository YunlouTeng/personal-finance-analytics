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

3. Set up key-pair authentication. Snowflake is phasing out single-factor
   passwords for human users (MFA enforcement completes in late 2026), and
   key-pair is the standard pattern for CLI and programmatic access. It also
   means `connections.toml` contains no secret: the private key lives in its
   own file outside the repo.

   Generate the key pair (add a passphrase via `-passout` and drop
   `-nocrypt` if you want the private key encrypted at rest):

   ```bash
   mkdir -p ~/.snowflake/keys
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM \
       -out ~/.snowflake/keys/pfin_rsa_key.p8 -nocrypt
   openssl rsa -in ~/.snowflake/keys/pfin_rsa_key.p8 -pubout \
       -out ~/.snowflake/keys/pfin_rsa_key.pub
   chmod 600 ~/.snowflake/keys/pfin_rsa_key.p8
   ```

   Register the public key on your Snowflake user. In a Snowsight worksheet,
   run the following with the base64 body of the `.pub` file (everything
   between the BEGIN and END lines, newlines removed):

   ```sql
   ALTER USER <your_username> SET RSA_PUBLIC_KEY='MII...';
   ```

   This is a one-time manual step; it is user configuration, not project
   infrastructure, so it does not live in `setup/`.

4. Create `~/.snowflake/connections.toml`. Find your account identifier in
   Snowsight under Account -> View account details, in
   `<orgname>-<account_name>` form:

   ```toml
   [pfin]
   account          = "<orgname>-<account_name>"
   user             = "<your_username>"
   authenticator    = "SNOWFLAKE_JWT"
   private_key_file = "/Users/<you>/.snowflake/keys/pfin_rsa_key.p8"
   warehouse        = "PFIN_WH"
   role             = "ACCOUNTADMIN"
   ```

   The private key path is absolute because tilde expansion is not reliable
   across drivers. `role` is ACCOUNTADMIN because this connection's first job
   is running the bootstrap DDL; dbt will later get its own entry using
   `PFIN_TRANSFORMER`. No `database` is set because `PERSONAL_FINANCE` does
   not exist until bootstrap runs.

   Then restrict it and verify: `chmod 600 ~/.snowflake/connections.toml`
   and `snow connection test -c pfin`.

5. Copy `.env.example` to `.env` and fill in the Plaid credentials. `.env` is
   gitignored and must stay that way.

6. Build the Snowflake environment:

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
