"""
Parser for `lastb -F` output.

Parses failed login attempt lines from lastb into structured dicts
ready for database insertion.

lastb -F output format (fixed-width columns):
    username terminal    source_ip        Day Mon DD HH:MM:SS YYYY - Day Mon DD HH:MM:SS YYYY  (duration)

Examples:
    root     ssh:notty    192.168.1.100    Fri Feb 14 03:22:15 2026 - Fri Feb 14 03:22:15 2026  (00:00)
    admin    ssh:notty    2001:db8::1      Fri Feb 14 03:22:15 2026 - Fri Feb 14 03:22:15 2026  (00:00)
    root     tty1                          Fri Feb 14 04:00:01 2026 - Fri Feb 14 04:00:01 2026  (00:00)

Lines to skip:
    - Empty lines
    - Lines starting with "btmp begins"
    - Reboot/shutdown entries
"""

import re
from datetime import datetime, timezone
from typing import Optional


# Regex to match a lastb -F line
# Groups: username, terminal, optional_ip, timestamp_start
#
# lastb uses fixed-width columns, but widths can vary across distros.
# The most reliable approach: match known structural tokens.
#
# Format: <user> <terminal> <ip?> <Day Mon DD HH:MM:SS YYYY> - <Day Mon DD HH:MM:SS YYYY> (<duration>)
_TIMESTAMP_PATTERN = r"[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+\d{4}"
_LASTB_LINE_RE = re.compile(
    r"^(\S+)\s+"                        # username
    r"(\S+)\s+"                         # terminal (e.g. ssh:notty, tty1)
    r"(.*?)\s+"                         # source (IP or hostname, may be empty)
    r"(" + _TIMESTAMP_PATTERN + r")"    # start timestamp
    r"\s+-\s+"                          # separator
    r"(" + _TIMESTAMP_PATTERN + r")"    # end timestamp (captured but not used currently)
    r"\s+\(.*\)"                        # duration
    r"\s*$"
)

# Regex to detect IPv4 or IPv6 addresses
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_IPV6_RE = re.compile(r"^[0-9a-fA-F:]+$")  # simplified; inet type in PG will validate

# Lines to skip entirely
_SKIP_PREFIXES = ("btmp begins", "wtmp begins")
_SKIP_USERNAMES = {"reboot", "shutdown"}

# Timestamp format used by lastb -F
_TIMESTAMP_FORMAT = "%a %b %d %H:%M:%S %Y"


def parse_lastb_line(line: str) -> Optional[dict]:
    """
    Parse a single lastb -F output line into a structured dict.

    Returns None for lines that should be skipped (empty, header, reboot, etc.)

    Returns dict with keys:
        - username: str
        - source_ip: str or None
        - timestamp: datetime (UTC)
        - terminal: str
        - protocol: str (inferred from terminal)
        - raw_line: str (original line)
    """
    line = line.rstrip("\n")

    # Skip empty lines and footer
    if not line.strip():
        return None
    if any(line.strip().lower().startswith(prefix) for prefix in _SKIP_PREFIXES):
        return None

    match = _LASTB_LINE_RE.match(line)
    if match is None:
        # Try a more lenient parse for edge cases
        return _parse_lenient(line)

    username = match.group(1)
    terminal = match.group(2)
    source_raw = match.group(3).strip()
    timestamp_str = match.group(4)

    # Skip reboot/shutdown entries
    if username.lower() in _SKIP_USERNAMES:
        return None

    # Parse timestamp
    try:
        timestamp = datetime.strptime(timestamp_str, _TIMESTAMP_FORMAT)
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    # Determine source IP
    source_ip = _extract_ip(source_raw) if source_raw else None

    # Infer protocol from terminal
    protocol = _infer_protocol(terminal)

    return {
        "username": username,
        "source_ip": source_ip,
        "timestamp": timestamp,
        "terminal": terminal,
        "protocol": protocol,
        "raw_line": line,
    }


def parse_lastb_output(text: str) -> list[dict]:
    """
    Parse full lastb -F output text into a list of structured dicts.

    Skips unparseable lines silently (they're logged via raw_line if needed).
    """
    results = []
    for line in text.splitlines():
        parsed = parse_lastb_line(line)
        if parsed is not None:
            results.append(parsed)
    return results


def _extract_ip(raw: str) -> Optional[str]:
    """
    Extract an IP address from the source field.
    Returns the IP string if valid, or None if it's a hostname or empty.
    For hostnames, we still return the raw value — the INET type in PG
    won't accept it, so ingest.py will set source_ip=NULL and keep
    the hostname in raw_line.
    """
    raw = raw.strip()
    if not raw:
        return None

    # IPv4 check
    if _IPV4_RE.match(raw):
        return raw

    # IPv6 check (must contain at least one colon)
    if ":" in raw and _IPV6_RE.match(raw):
        return raw

    # It's a hostname — return it, let the caller decide how to handle
    return raw


def _infer_protocol(terminal: str) -> str:
    """Infer the login protocol from the terminal field."""
    terminal_lower = terminal.lower()
    if "ssh" in terminal_lower:
        return "ssh"
    if terminal_lower.startswith("tty"):
        return "console"
    if terminal_lower.startswith("pts"):
        return "pts"
    return "unknown"


def _parse_lenient(line: str) -> Optional[dict]:
    """
    Fallback parser for lines that don't match the strict regex.

    Handles cases like:
    - Extra whitespace
    - Truncated lines
    - Slightly different column alignment across distros
    """
    stripped = line.strip()
    if not stripped:
        return None

    # Try to find a timestamp in the line
    ts_match = re.search(_TIMESTAMP_PATTERN, stripped)
    if ts_match is None:
        return None

    # Everything before the timestamp is user + terminal + source
    prefix = stripped[: ts_match.start()].strip()
    parts = prefix.split()

    if len(parts) < 1:
        return None

    username = parts[0]
    if username.lower() in _SKIP_USERNAMES:
        return None

    terminal = parts[1] if len(parts) >= 2 else "unknown"
    source_raw = parts[2] if len(parts) >= 3 else ""

    try:
        timestamp = datetime.strptime(ts_match.group(0), _TIMESTAMP_FORMAT)
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    source_ip = _extract_ip(source_raw) if source_raw else None
    protocol = _infer_protocol(terminal)

    return {
        "username": username,
        "source_ip": source_ip,
        "timestamp": timestamp,
        "terminal": terminal,
        "protocol": protocol,
        "raw_line": line.rstrip("\n"),
    }
