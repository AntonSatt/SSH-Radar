"""
Correct failed logins that were stored from truncated lastb output.

Until 2026-11-03, ingest.py ran `lastb -F` without -w. lastb then cut
usernames to 8 characters ("minecraft" became "minecraf"), and the parser
misread two kinds of lines: an empty username left "ssh:notty" in the
username column and the IP in the terminal column, and attempts with the
usernames "reboot" and "shutdown" were dropped as if they were reboots.

This reads a btmp file twice, narrow (the old format, which is what the
stored raw_line holds) and wide, pairs the lines and corrects the stored
rows. Only attempts still in a btmp file can be corrected; older rows keep
the truncated names.

Dry run by default. Needs root to read btmp:

    sudo scripts/run_backfill.sh /var/log/btmp.1 /var/log/btmp
    sudo scripts/run_backfill.sh --apply /var/log/btmp.1 /var/log/btmp
"""

import argparse
import ipaddress
import os
import subprocess
import sys
from collections import Counter, defaultdict

from psycopg2.extras import RealDictCursor, execute_batch

# Add src to path when running as script
sys.path.insert(0, os.path.dirname(__file__))

from config import get_db_connection, logger
from ingest import LASTB_ENV, refresh_views, run_geolocation, to_db_values
from parser import parse_lastb_line


def read_btmp(path: str, wide: bool) -> list[str]:
    """Run lastb on a btmp file and return its output lines."""
    cmd = ["lastb", "-F", "-w", "-f", path] if wide else ["lastb", "-F", "-f", path]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300, env=LASTB_ENV, check=True
    )
    return result.stdout.splitlines()


def _key(username: str, source_ip, timestamp) -> tuple:
    """Unique key of failed_logins, with the IP in canonical form."""
    if source_ip is not None:
        source_ip = ipaddress.ip_address(source_ip).compressed
    return (username, source_ip, timestamp)


def _reason(row: dict, values: tuple) -> str:
    """Classify a correction for the summary."""
    old, new = row["username"], values[0]
    if not new and old.startswith("ssh:"):
        return "empty username"
    if len(old) == 8 and len(new) > 8 and new.startswith(old):
        return "truncated username"
    return "other"


def plan_changes(pairs: list[tuple[str, str]], stored_rows: list[dict]) -> list[tuple]:
    """
    Decide how to correct the stored rows for one btmp file.

    Args:
        pairs: (narrow_line, wide_line) for every line in the file
        stored_rows: rows of failed_logins in the file's time range, with
            source_ip as text

    Returns:
        (action, row, values) tuples. action is "update", "delete" or
        "insert", row is the stored row (None for "insert") and values are
        the corrected column values from to_db_values() (None for "delete").
    """
    by_line = defaultdict(list)
    keys = set()
    for row in stored_rows:
        by_line[(row["timestamp"], row["raw_line"])].append(row)
        keys.add(_key(row["username"], row["source_ip"], row["timestamp"]))

    changes = []
    for narrow, wide in pairs:
        record = parse_lastb_line(wide)
        if record is None:
            continue
        values = to_db_values(record)
        new_key = _key(*values[:3])

        candidates = by_line.get((record["timestamp"], narrow))
        if not candidates:
            # Never stored: a dropped "reboot"/"shutdown" attempt, or a second
            # username that collapsed into the same truncated one
            if new_key not in keys:
                changes.append(("insert", None, values))
                keys.add(new_key)
            continue

        row = candidates.pop(0)
        old_key = _key(row["username"], row["source_ip"], row["timestamp"])
        stored = (*old_key, row["terminal"], row["protocol"], row["raw_line"])
        if stored == (*new_key, *values[3:]):
            continue

        keys.discard(old_key)
        if new_key != old_key and new_key in keys:
            # The corrected row is already stored, e.g. ingested after the fix
            changes.append(("delete", row, None))
        else:
            changes.append(("update", row, values))
            keys.add(new_key)
    return changes


def load_stored_rows(cur, first, last) -> list[dict]:
    """Fetch the stored rows between two timestamps (inclusive)."""
    cur.execute(
        """
        SELECT id, username, host(source_ip) AS source_ip, timestamp, terminal, protocol, raw_line
        FROM failed_logins
        WHERE timestamp BETWEEN %s AND %s
        """,
        (first, last),
    )
    return cur.fetchall()


def apply_changes(cur, changes: list[tuple]) -> None:
    """Write planned changes inside the caller's transaction."""
    deletes = [(row["id"],) for action, row, _ in changes if action == "delete"]
    updates = [(*values, row["id"]) for action, row, values in changes if action == "update"]
    inserts = [values for action, _, values in changes if action == "insert"]

    # Deletes first, so an update never collides with a row that is going away
    execute_batch(cur, "DELETE FROM failed_logins WHERE id = %s", deletes)
    execute_batch(
        cur,
        """
        UPDATE failed_logins
        SET username = %s, source_ip = %s, timestamp = %s, terminal = %s, protocol = %s, raw_line = %s
        WHERE id = %s
        """,
        updates,
    )
    execute_batch(
        cur,
        """
        INSERT INTO failed_logins (username, source_ip, timestamp, terminal, protocol, raw_line)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (username, source_ip, timestamp) DO NOTHING
        """,
        inserts,
    )


def summarize(path: str, changes: list[tuple]) -> None:
    """Log counts and a few examples of the planned changes."""
    counts = Counter(
        (action, _reason(row, values) if action == "update" else "")
        for action, row, values in changes
    )
    logger.info("%s: %d changes", path, len(changes))
    for (action, reason), n in sorted(counts.items()):
        logger.info("  %-6s %-18s %d", action, reason, n)

    shown = Counter()
    for action, row, values in changes:
        label = (action, _reason(row, values) if action == "update" else "")
        if shown[label] >= 3:
            continue
        shown[label] += 1
        before = repr(row["username"]) if row else "-"
        after = repr(values[0]) if values else "-"
        logger.info("  e.g. %s %s: %s -> %s", action, label[1], before, after)


def main():
    arg_parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    arg_parser.add_argument("btmp_files", nargs="+", help="btmp files to read, e.g. /var/log/btmp.1")
    arg_parser.add_argument("--apply", action="store_true", help="Write the changes (default: dry run)")
    args = arg_parser.parse_args()

    conn = get_db_connection(cursor_factory=RealDictCursor)
    try:
        cur = conn.cursor()
        if args.apply:
            # Block the cron ingest (it waits) so the plan stays valid while
            # it is written. Reads from Grafana are not blocked.
            cur.execute("SET lock_timeout = '30s'")
            cur.execute("LOCK TABLE failed_logins IN SHARE ROW EXCLUSIVE MODE")

        total = 0
        for path in args.btmp_files:
            narrow = read_btmp(path, wide=False)
            wide = read_btmp(path, wide=True)
            if len(narrow) != len(wide):
                raise RuntimeError(f"{path}: {len(narrow)} narrow lines but {len(wide)} wide lines")

            timestamps = [r["timestamp"] for r in map(parse_lastb_line, wide) if r]
            if not timestamps:
                logger.info("%s: no login attempts", path)
                continue

            stored = load_stored_rows(cur, min(timestamps), max(timestamps))
            changes = plan_changes(list(zip(narrow, wide)), stored)
            summarize(path, changes)
            total += len(changes)
            if args.apply:
                apply_changes(cur, changes)

        if not args.apply:
            conn.rollback()
            logger.info("Dry run: %d changes planned, nothing written (use --apply)", total)
            return
        conn.commit()
        logger.info("Applied %d changes", total)
    except Exception:
        conn.rollback()
        logger.exception("Backfill failed, nothing written")
        raise
    finally:
        conn.close()

    run_geolocation()
    refresh_views()


if __name__ == "__main__":
    main()
