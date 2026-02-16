#!/usr/bin/env bash
#
# Run the login attempt ingestion pipeline.
#
# This script runs on the HOST (not inside Docker) because it needs
# access to /var/log/btmp via the `lastb` command, which requires root.
#
# Install as a cron job:
#   sudo crontab -e
#   */5 * * * * /opt/ssh-radar/scripts/run_ingest.sh >> /var/log/ssh-radar-ingest.log 2>&1
#
# Prerequisites:
#   - Python 3 venv at PROJECT_DIR/.venv (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)
#   - PostgreSQL running (via Docker) on localhost:5432
#   - .env file at PROJECT_DIR/.env with DB credentials
#   - GeoLite2-City.mmdb downloaded to data/
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/.venv/bin/python3"

# Verify venv exists
if [ ! -x "$PYTHON" ]; then
    echo "ERROR: Python venv not found at $PROJECT_DIR/.venv"
    echo "Run: python3 -m venv $PROJECT_DIR/.venv && $PROJECT_DIR/.venv/bin/pip install -r $PROJECT_DIR/requirements.txt"
    exit 1
fi

# Load environment variables
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# Run ingestion
echo "$(date '+%Y-%m-%d %H:%M:%S') Starting ingestion..."
"$PYTHON" "$PROJECT_DIR/src/ingest.py"
echo "$(date '+%Y-%m-%d %H:%M:%S') Ingestion complete."
