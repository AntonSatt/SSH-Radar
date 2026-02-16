"""
Ingestion pipeline for failed login attempts.

Runs `lastb -F`, parses the output, deduplicates against existing records,
and bulk-inserts new entries into PostgreSQL.

Usage:
    # Normal operation (runs lastb on the host):
    python3 src/ingest.py

    # From a file (for testing or piping):
    python3 src/ingest.py --file tests/fixtures/sample_lastb.txt

    # From stdin:
    lastb -F | python3 src/ingest.py --stdin
"""

import argparse
import ipaddress
import subprocess
import sys
import os

# Add src to path when running as script
sys.path.insert(0, os.path.dirname(__file__))

from config import get_db_connection, logger, LASTB_COMMAND
from parser import parse_lastb_output


def get_lastb_output(source: str = "command", filepath: str | None = None) -> str:
    """
    Get lastb output from the specified source.

    Args:
        source: "command" to run lastb, "file" to read a file, "stdin" to read stdin
        filepath: Path to file if source is "file"

    Returns:
        Raw lastb output as string
    """
    if source == "file" and filepath:
        logger.info("Reading lastb data from file: %s", filepath)
        with open(filepath) as f:
            return f.read()

    if source == "stdin":
        logger.info("Reading lastb data from stdin")
        return sys.stdin.read()

    # Default: run lastb command
    logger.info("Running: %s", LASTB_COMMAND)
    try:
        result = subprocess.run(
            LASTB_COMMAND.split(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and result.stderr:
            logger.warning("lastb stderr: %s", result.stderr.strip())
        return result.stdout
    except FileNotFoundError:
        logger.error("lastb command not found. Are you running on a Linux system?")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        logger.error("lastb command timed out after 30 seconds")
        sys.exit(1)
    except PermissionError:
        logger.error("Permission denied. lastb requires root privileges.")
        sys.exit(1)


def is_valid_ip(value: str) -> bool:
    """Check if a string is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def insert_records(records: list[dict]) -> int:
    """
    Insert parsed login attempt records into the database.

    Uses ON CONFLICT DO NOTHING for deduplication.

    Args:
        records: List of parsed record dicts from parser.py

    Returns:
        Number of new records inserted
    """
    if not records:
        logger.info("No records to insert")
        return 0

    conn = get_db_connection()
    inserted = 0

    try:
        cur = conn.cursor()

        for record in records:
            # Validate IP — if it's a hostname (not an IP), set to NULL
            source_ip = record["source_ip"]
            if source_ip and not is_valid_ip(source_ip):
                logger.debug(
                    "Non-IP source '%s' for user '%s' — storing as NULL",
                    source_ip,
                    record["username"],
                )
                source_ip = None

            cur.execute(
                """
                INSERT INTO failed_logins (username, source_ip, timestamp, terminal, protocol, raw_line)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (username, source_ip, timestamp) DO NOTHING
                """,
                (
                    record["username"],
                    source_ip,
                    record["timestamp"],
                    record["terminal"],
                    record["protocol"],
                    record["raw_line"],
                ),
            )
            if cur.rowcount > 0:
                inserted += 1

        conn.commit()
        logger.info("Inserted %d new records (out of %d parsed)", inserted, len(records))

    except Exception:
        conn.rollback()
        logger.exception("Failed to insert records")
        raise
    finally:
        conn.close()

    return inserted


def refresh_views() -> None:
    """Refresh materialized views after ingestion."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT refresh_materialized_views()")
        conn.commit()
        logger.info("Materialized views refreshed")
    except Exception:
        conn.rollback()
        logger.warning("Could not refresh materialized views (they may not exist yet)")
    finally:
        conn.close()


def run_geolocation() -> None:
    """Run geolocation enrichment for new IPs (imported here to avoid circular deps)."""
    try:
        from geolocate import enrich_new_ips
        enriched = enrich_new_ips()
        logger.info("Geolocated %d new IPs", enriched)
    except ImportError:
        logger.debug("geolocate module not available — skipping geolocation")
    except FileNotFoundError:
        logger.warning("GeoLite2 database not found — skipping geolocation")
    except Exception:
        logger.exception("Geolocation enrichment failed")


def main():
    arg_parser = argparse.ArgumentParser(description="Ingest failed login attempts from lastb")
    source_group = arg_parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--file", "-f",
        help="Read lastb data from a file instead of running lastb",
    )
    source_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read lastb data from stdin",
    )
    args = arg_parser.parse_args()

    # Determine source
    if args.file:
        source, filepath = "file", args.file
    elif args.stdin:
        source, filepath = "stdin", None
    else:
        source, filepath = "command", None

    # Step 1: Get raw output
    raw_output = get_lastb_output(source=source, filepath=filepath)
    if not raw_output.strip():
        logger.info("No lastb data to process")
        return

    # Step 2: Parse
    records = parse_lastb_output(raw_output)
    logger.info("Parsed %d records from lastb output", len(records))
    if not records:
        return

    # Step 3: Insert into database
    inserted = insert_records(records)

    # Step 4: Geolocate new IPs
    if inserted > 0:
        run_geolocation()

    # Step 5: Refresh materialized views
    refresh_views()

    logger.info("Ingestion complete: %d new records", inserted)


if __name__ == "__main__":
    main()
