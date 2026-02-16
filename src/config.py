"""
Configuration for SSH Radar.

Reads settings from environment variables with sensible defaults
for local development.
"""

import os
import logging

import psycopg2
from psycopg2.extras import RealDictCursor


# ── Database settings ────────────────────────────────────────────────

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "ssh_radar")
DB_USER = os.environ.get("DB_USER", "ssh_radar")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "ssh_radar")

# ── MaxMind GeoLite2 settings ────────────────────────────────────────

MAXMIND_DB_PATH = os.environ.get(
    "MAXMIND_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "GeoLite2-City.mmdb"),
)
MAXMIND_LICENSE_KEY = os.environ.get("MAXMIND_LICENSE_KEY", "")

# ── Ingestion settings ──────────────────────────────────────────────

# Command to run for lastb output. Override for testing.
LASTB_COMMAND = os.environ.get("LASTB_COMMAND", "lastb -F")

# ── Logging ──────────────────────────────────────────────────────────

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("ssh-radar")


# ── Database connection helper ───────────────────────────────────────


def get_db_connection(cursor_factory=None):
    """
    Create and return a new database connection.

    Args:
        cursor_factory: Optional cursor factory (e.g. RealDictCursor)

    Returns:
        psycopg2 connection object
    """
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        cursor_factory=cursor_factory,
    )
    conn.autocommit = False
    return conn


def get_dict_connection():
    """Return a connection with RealDictCursor for dict-style row access."""
    return get_db_connection(cursor_factory=RealDictCursor)
