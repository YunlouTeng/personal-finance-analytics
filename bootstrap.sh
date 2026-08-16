#!/usr/bin/env bash
# ---------------------------------------------------------------------
# Rebuild the entire Snowflake environment from scratch.
#
# Usage:
#   ./setup/bootstrap.sh [connection_name]
#
# Defaults to the "pfin" connection defined in ~/.snowflake/connections.toml
# ---------------------------------------------------------------------
set -euo pipefail

CONN="${1:-pfin}"

echo "Testing connection: ${CONN}"
snow connection test -c "${CONN}"

echo "Applying infrastructure..."
snow sql -f setup/01_infrastructure.sql -c "${CONN}"

echo "Done. Environment is ready."
