# 002: Tooling decisions

Date: 2026-08-16

## No Docker for now

Every heavy component in this stack is SaaS: Snowflake holds the data and
compute, Plaid is a hosted API. What runs locally is Python scripts, dbt,
and Streamlit, and the uv-managed 3.11 virtualenv already makes that
reproducible. Containerizing today would slow down the dbt iteration loop
and add secret-handling surface (mounting `.env` and
`~/.snowflake/connections.toml` into containers) without solving any
problem we actually have.

Revisit when either trigger fires:

1. Ingestion gets scheduled (a containerized sync job on GitHub Actions or
   similar is the natural shape for that).
2. The Streamlit app gets deployed off this machine.

## Code-first Snowflake, Snowsight as a read-only explorer

All object creation goes through `setup/*.sql` executed by the snow CLI,
never by clicking in Snowsight. Two reasons:

1. Reproducibility. Trial accounts expire; the environment must rebuild
   from a clean account in one command. Objects created by hand are
   unreproducible and unreviewable.
2. Learning. The concepts that transfer (warehouses, role hierarchies,
   grants on future tables, stages, file formats) live in the DDL, not in
   the menus. Production Snowflake work is code-first, and this project is
   partly a portfolio of production habits.

Snowsight still earns its place, used read-only: Query History and query
profiles to understand performance, the warehouse monitor to watch
AUTO_SUSPEND control cost, data preview, and role/grant inspection. Build
with the CLI, inspect with the UI.

One sanctioned exception: per-user configuration such as
`ALTER USER ... SET RSA_PUBLIC_KEY` is run manually in a worksheet, since
it is account-user setup rather than project infrastructure.

## Key-pair authentication for the CLI

Snowflake is retiring single-factor password sign-ins for human users; the
final enforcement milestone lands August to October 2026. Trial accounts
are exempt only until they convert to paid. Password auth in a CLI also
degrades into interactive MFA prompts, which breaks scripted use.

Key-pair (JWT) authentication is the standard for programmatic access:
a 2048-bit RSA key pair, private key at
`~/.snowflake/keys/pfin_rsa_key.p8` with mode 600, public key registered
on the Snowflake user. A side benefit is that `connections.toml` then
contains no secret at all, only the account identifier, username, and the
path to the key file.

The private key is stored unencrypted, which is acceptable for a mode-600
file on a single-user machine holding trial credentials. If this account
ever converts to paid with real data access, encrypt the key with a
passphrase (`openssl pkcs8 -topk8` without `-nocrypt`) or move to SSO.

## snow CLI isolated from the project venv

Recorded in `requirements.txt` as well: installing `snowflake-cli` into
the same environment as `dbt-core` forces a silent resolver downgrade of
dbt to a 2019 release, because their dependency pins conflict. The snow
CLI is only ever invoked as a shell command, never imported, so it lives
in its own environment via `uv tool install snowflake-cli` and the
project venv keeps current dbt.
