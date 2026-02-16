#!/usr/bin/env bash
#
# Download/update the MaxMind GeoLite2-City database.
#
# Requires a free MaxMind license key:
#   1. Sign up at https://www.maxmind.com/en/geolite2/signup
#   2. Generate a license key at https://www.maxmind.com/en/accounts/current/license-key
#   3. Add MAXMIND_ACCOUNT_ID and MAXMIND_LICENSE_KEY to your .env file
#
# Usage:
#   bash src/update_geodb.sh
#
# The script auto-loads .env from the project root.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="${GEODB_DIR:-$PROJECT_DIR/data}"
DB_FILE="$DATA_DIR/GeoLite2-City.mmdb"

# ── Load .env if present ────────────────────────────────────────────

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

# ── Check for license key ───────────────────────────────────────────

if [ -z "${MAXMIND_LICENSE_KEY:-}" ]; then
    echo "ERROR: MAXMIND_LICENSE_KEY environment variable is not set."
    echo ""
    echo "To get a free license key:"
    echo "  1. Sign up at https://www.maxmind.com/en/geolite2/signup"
    echo "  2. Generate a key at https://www.maxmind.com/en/accounts/current/license-key"
    echo "  3. Run: export MAXMIND_ACCOUNT_ID='your_account_id'"
    echo "         export MAXMIND_LICENSE_KEY='your_key_here'"
    exit 1
fi

if [ -z "${MAXMIND_ACCOUNT_ID:-}" ]; then
    echo "ERROR: MAXMIND_ACCOUNT_ID environment variable is not set."
    echo ""
    echo "Your Account ID is shown at https://www.maxmind.com/en/accounts/current"
    echo "  Run: export MAXMIND_ACCOUNT_ID='your_account_id'"
    exit 1
fi

# ── Download ─────────────────────────────────────────────────────────

mkdir -p "$DATA_DIR"

DOWNLOAD_URL="https://download.maxmind.com/geoip/databases/GeoLite2-City/download?suffix=tar.gz"
TEMP_FILE=$(mktemp /tmp/geolite2-city.XXXXXX.tar.gz)

echo "Downloading GeoLite2-City database..."
if ! curl -sS -u "${MAXMIND_ACCOUNT_ID}:${MAXMIND_LICENSE_KEY}" -o "$TEMP_FILE" "$DOWNLOAD_URL"; then
    echo "ERROR: Download failed. Check your license key."
    rm -f "$TEMP_FILE"
    exit 1
fi

# Verify it's actually a gzip file (not an error page)
if ! file "$TEMP_FILE" | grep -q "gzip"; then
    echo "ERROR: Downloaded file is not a valid gzip archive."
    echo "This usually means the license key is invalid."
    cat "$TEMP_FILE"
    rm -f "$TEMP_FILE"
    exit 1
fi

# ── Extract ──────────────────────────────────────────────────────────

echo "Extracting..."
TEMP_DIR=$(mktemp -d /tmp/geolite2-city.XXXXXX)
tar -xzf "$TEMP_FILE" -C "$TEMP_DIR"

# Find the .mmdb file in the extracted archive
MMDB_FILE=$(find "$TEMP_DIR" -name "GeoLite2-City.mmdb" -type f | head -1)

if [ -z "$MMDB_FILE" ]; then
    echo "ERROR: Could not find GeoLite2-City.mmdb in the archive."
    rm -rf "$TEMP_FILE" "$TEMP_DIR"
    exit 1
fi

# Move to data directory
mv "$MMDB_FILE" "$DB_FILE"
rm -rf "$TEMP_FILE" "$TEMP_DIR"

echo "GeoLite2-City database updated: $DB_FILE"
echo "File size: $(du -h "$DB_FILE" | cut -f1)"
echo "Last modified: $(date -r "$DB_FILE")"
