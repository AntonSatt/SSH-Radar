"""
Ingestion pipeline for failed login attempts.

Runs `lastb -F -w`, parses the output, deduplicates against existing records,
and bulk-inserts new entries into PostgreSQL.

Usage:
    # Normal operation (runs lastb on the host):
    python3 src/ingest.py

    # From a file (for testing or piping):
    python3 src/ingest.py --file tests/fixtures/sample_lastb.txt

    # From stdin:
    lastb -F -w | python3 src/ingest.py --stdin
"""

import argparse
import ipaddress
import subprocess
import sys
import os

# Add src to path when running as script
sys.path.insert(0, os.path.dirname(__file__))

from config import get_db_connection, logger, BTMP_ROTATED_PATH, LASTB_COMMAND
from parser import parse_lastb_output


# Cron already runs with LANG=C.UTF-8 on the host. Pin it so lastb prints
# non-ASCII usernames as text, not as \ooo escapes, wherever this runs.
LASTB_ENV = {**os.environ, "LC_ALL": "C.UTF-8"}

# failed_logins.username is VARCHAR(64). lastb -w prints names up to the
# 32-byte utmp limit, but escapes invalid bytes as \ooo, so a pathological
# name could still be longer and would fail the whole batch.
USERNAME_MAX_LEN = 64


def get_lastb_output(
    source: str = "command", filepath: str | None = None, btmp_path: str | None = None
) -> str:
    """
    Get lastb output from the specified source.

    Args:
        source: "command" to run lastb, "file" to read a file, "stdin" to read stdin
        filepath: Path to file if source is "file"
        btmp_path: btmp file for lastb to read instead of its default

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
    cmd = LASTB_COMMAND.split() + (["-f", btmp_path] if btmp_path else [])
    logger.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            env=LASTB_ENV,
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


def get_latest_stored():
    """Timestamp of the newest stored attempt, or None for an empty table."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT max(timestamp) FROM failed_logins")
        return cur.fetchone()[0]
    finally:
        conn.close()


def misses_rotated_records(records: list[dict], latest_stored) -> bool:
    """
    True when the current btmp starts after the newest stored attempt.

    logrotate moves btmp to btmp.1 (monthly on the host). Attempts logged
    between the last run and the rotation are then only in btmp.1, and the
    new btmp no longer reaches back to anything already stored. On an empty
    table there is nothing to catch up on.
    """
    if latest_stored is None:
        return False
    return not records or min(r["timestamp"] for r in records) > latest_stored


def is_valid_ip(value: str) -> bool:
    """Check if a string is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def to_db_values(record: dict) -> tuple:
    """
    Turn a parsed record into column values for failed_logins.

    Hostnames become a NULL source_ip (the raw line keeps them), and
    usernames are cut to fit the column.

    Returns:
        (username, source_ip, timestamp, terminal, protocol, raw_line)
    """
    source_ip = record["source_ip"]
    if source_ip and not is_valid_ip(source_ip):
        logger.debug(
            "Non-IP source '%s' for user '%s' — storing as NULL",
            source_ip,
            record["username"],
        )
        source_ip = None

    return (
        record["username"][:USERNAME_MAX_LEN],
        source_ip,
        record["timestamp"],
        record["terminal"],
        record["protocol"],
        record["raw_line"],
    )


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

        # lastb is re-read in full on every run, so the vast majority of these
        # records already exist. Without a pre-filter we'd hand all ~150k+ rows
        # to INSERT ... ON CONFLICT every 5 minutes — and Postgres calls
        # nextval() for every *attempted* row, conflict or not. That silently
        # burned the id sequence to its int4 ceiling and broke ingestion. So
        # only consider attempts at or after the newest one already stored.
        cur.execute("SELECT max(timestamp) FROM failed_logins")
        latest_stored = cur.fetchone()[0]
        if latest_stored is not None:
            parsed_count = len(records)
            records = [r for r in records if r["timestamp"] >= latest_stored]
            logger.info(
                "Newest stored attempt: %s — %d of %d parsed records are new enough to check",
                latest_stored, len(records), parsed_count,
            )

        for record in records:
            cur.execute(
                """
                INSERT INTO failed_logins (username, source_ip, timestamp, terminal, protocol, raw_line)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (username, source_ip, timestamp) DO NOTHING
                """,
                to_db_values(record),
            )
            if cur.rowcount > 0:
                inserted += 1

        conn.commit()
        logger.info("Inserted %d new records (out of %d candidates)", inserted, len(records))

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

    # Right after a log rotation, also read the rotated file so the attempts
    # logged before it are not lost. The newest-stored filter in
    # insert_records() keeps the rest of that file from being re-checked.
    if source == "command" and misses_rotated_records(records, get_latest_stored()):
        rotated = parse_lastb_output(get_lastb_output(btmp_path=BTMP_ROTATED_PATH))
        logger.info(
            "btmp was rotated since the last run: parsed %d records from %s",
            len(rotated), BTMP_ROTATED_PATH,
        )
        records = rotated + records

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
