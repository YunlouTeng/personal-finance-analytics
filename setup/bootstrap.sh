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

# Resolve paths against this script rather than the caller's working
# directory, so the script behaves the same from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Testing connection: ${CONN}"
snow connection test -c "${CONN}"

echo "Applying infrastructure..."
snow sql -f "${SCRIPT_DIR}/01_infrastructure.sql" -c "${CONN}"

echo "Done. Environment is ready."
