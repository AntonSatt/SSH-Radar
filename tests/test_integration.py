"""
Integration test for SSH Radar.

Spins up a real PostgreSQL container, feeds sample_lastb.txt through the
full pipeline, and verifies:
  - Records are inserted correctly
  - Deduplication works (re-running inserts 0 new records)
  - Geolocation enrichment handles private/reserved IPs
  - Materialized views are created and refreshable
  - The login_attempts_geo view joins correctly

Requires: Docker, psycopg2-binary, pytest
Skipped automatically if Docker is not available.

Usage:
    python3 -m pytest tests/test_integration.py -v
"""

import os
import subprocess
import time

import psycopg2
import pytest

# ---------------------------------------------------------------------------
# Container configuration
# ---------------------------------------------------------------------------
CONTAINER_NAME = "ssh-radar-test-db"
DB_PORT = 5433  # Use non-standard port to avoid conflicts
DB_NAME = "ssh_radar_test"
DB_USER = "ssh_radar_test"
DB_PASSWORD = "test_password_123"

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SQL_DIR = os.path.join(os.path.dirname(__file__), "..", "sql")
SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
SAMPLE_FILE = os.path.join(FIXTURES_DIR, "sample_lastb.txt")


def docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def wait_for_postgres(host: str, port: int, user: str, password: str, dbname: str,
                      timeout: int = 30) -> bool:
    """Wait for PostgreSQL to accept connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host=host, port=port, user=user, password=password, dbname=dbname,
            )
            conn.close()
            return True
        except psycopg2.OperationalError:
            time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pg_container():
    """Start a PostgreSQL 16 container for testing, yield, then remove it."""
    if not docker_available():
        pytest.skip("Docker is not available")

    # Clean up any leftover container from a previous run
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        capture_output=True,
    )

    # Start the container
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", CONTAINER_NAME,
            "-e", f"POSTGRES_DB={DB_NAME}",
            "-e", f"POSTGRES_USER={DB_USER}",
            "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
            "-p", f"127.0.0.1:{DB_PORT}:5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
    )

    # Wait for PostgreSQL to be ready
    ready = wait_for_postgres("127.0.0.1", DB_PORT, DB_USER, DB_PASSWORD, DB_NAME)
    if not ready:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
        pytest.fail("PostgreSQL container did not become ready in time")

    yield

    # Teardown
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


@pytest.fixture(scope="module")
def db_conn(pg_container):
    """Initialize the schema and return a connection factory."""
    conn = psycopg2.connect(
        host="127.0.0.1", port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME,
    )
    conn.autocommit = True

    # Run schema SQL files
    cur = conn.cursor()
    for sql_file in sorted(os.listdir(SQL_DIR)):
        if sql_file.endswith(".sql"):
            path = os.path.join(SQL_DIR, sql_file)
            with open(path) as f:
                sql = f.read()
            cur.execute(sql)

    conn.close()

    # Return a factory that creates new connections
    def connect():
        c = psycopg2.connect(
            host="127.0.0.1", port=DB_PORT,
            user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME,
        )
        c.autocommit = False
        return c

    return connect


# ---------------------------------------------------------------------------
# Helpers — run pipeline functions with overridden DB config
# ---------------------------------------------------------------------------

def _set_test_env():
    """Set environment variables so config.py connects to the test DB."""
    os.environ["DB_HOST"] = "127.0.0.1"
    os.environ["DB_PORT"] = str(DB_PORT)
    os.environ["DB_NAME"] = DB_NAME
    os.environ["DB_USER"] = DB_USER
    os.environ["DB_PASSWORD"] = DB_PASSWORD


def run_ingest_with_test_db(filepath: str) -> dict:
    """
    Run the ingestion pipeline against the test database.

    Sets env vars and force-reloads config so get_db_connection() uses
    the test DB settings.
    """
    import sys
    sys.path.insert(0, SRC_DIR)

    _set_test_env()

    import importlib

    # Force reload config first (reads env vars), then ingest (re-imports from config)
    if "config" in sys.modules:
        importlib.reload(sys.modules["config"])
    else:
        import config  # noqa: F401

    if "ingest" in sys.modules:
        importlib.reload(sys.modules["ingest"])
    else:
        import ingest  # noqa: F401

    import parser as lastb_parser
    import ingest

    # Read the file
    with open(filepath) as f:
        raw_output = f.read()

    # Parse
    records = lastb_parser.parse_lastb_output(raw_output)

    # Insert
    inserted = ingest.insert_records(records)

    return {"parsed": len(records), "inserted": inserted}


def run_geolocation_private_only(connect_fn) -> int:
    """
    Insert geolocation data for private IPs only (no MaxMind DB needed).
    Mimics what geolocate.py does for private/reserved IPs.
    """
    import sys
    sys.path.insert(0, SRC_DIR)

    import ipaddress

    conn = connect_fn()
    cur = conn.cursor()

    # Find IPs without geolocation — use host() to strip /32 netmask
    cur.execute("""
        SELECT DISTINCT host(fl.source_ip)
        FROM failed_logins fl
        LEFT JOIN ip_geolocations geo ON fl.source_ip = geo.ip
        WHERE fl.source_ip IS NOT NULL
          AND geo.ip IS NULL
    """)
    ips = [row[0] for row in cur.fetchall()]

    count = 0
    for ip_str in ips:
        try:
            addr = ipaddress.ip_address(ip_str)
            is_private = addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local
        except ValueError:
            is_private = False

        if is_private:
            cur.execute(
                """
                INSERT INTO ip_geolocations (ip, country_code, country, city)
                VALUES (%s, 'XX', 'Private', 'Private Network')
                ON CONFLICT (ip) DO NOTHING
                """,
                (ip_str,),
            )
            count += 1
        else:
            # For public IPs without GeoLite2 DB, insert placeholder
            cur.execute(
                """
                INSERT INTO ip_geolocations (ip, country_code, country, city)
                VALUES (%s, 'XX', 'Unknown', NULL)
                ON CONFLICT (ip) DO NOTHING
                """,
                (ip_str,),
            )
            count += 1

    conn.commit()
    conn.close()
    return count


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Test the full ingestion pipeline against a real PostgreSQL database."""

    def test_schema_created(self, db_conn):
        """Verify all tables, views, and indexes were created."""
        conn = db_conn()
        cur = conn.cursor()

        # Check tables exist
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cur.fetchall()]
        assert "failed_logins" in tables
        assert "ip_geolocations" in tables

        # Check views exist
        cur.execute("""
            SELECT table_name FROM information_schema.views
            WHERE table_schema = 'public'
        """)
        views = [row[0] for row in cur.fetchall()]
        assert "login_attempts_geo" in views

        # Check materialized views exist
        cur.execute("""
            SELECT matviewname FROM pg_matviews
            WHERE schemaname = 'public'
        """)
        matviews = [row[0] for row in cur.fetchall()]
        assert "daily_stats" in matviews
        assert "monthly_stats" in matviews
        assert "country_stats" in matviews

        # Check the refresh function exists
        cur.execute("""
            SELECT routine_name FROM information_schema.routines
            WHERE routine_schema = 'public' AND routine_name = 'refresh_materialized_views'
        """)
        assert cur.fetchone() is not None

        conn.close()

    def test_ingest_from_file(self, db_conn):
        """Feed sample_lastb.txt through the pipeline and verify insertion."""
        result = run_ingest_with_test_db(SAMPLE_FILE)

        # sample_lastb.txt has 19 lines: 15 login attempts + 2 skip (reboot, shutdown)
        # + 1 blank + 1 footer (btmp begins) = 15 parseable login attempts
        assert result["parsed"] > 0, "Parser should produce records"
        assert result["inserted"] > 0, "Should insert new records"
        assert result["inserted"] == result["parsed"], \
            "First run: all parsed records should be inserted"

        # Verify records are actually in the database
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM failed_logins")
        count = cur.fetchone()[0]
        assert count == result["inserted"]
        conn.close()

    def test_deduplication(self, db_conn):
        """Re-running the same data should insert 0 new records."""
        result = run_ingest_with_test_db(SAMPLE_FILE)
        assert result["inserted"] == 0, \
            "Second run with same data should insert 0 due to deduplication"

    def test_records_content(self, db_conn):
        """Verify that inserted records have correct field values."""
        conn = db_conn()
        cur = conn.cursor()

        # Check a known record: root from 203.0.113.50
        cur.execute("""
            SELECT username, host(source_ip), protocol, terminal
            FROM failed_logins
            WHERE username = 'root' AND source_ip = '203.0.113.50'
        """)
        row = cur.fetchone()
        assert row is not None, "Should find root@203.0.113.50"
        assert row[0] == "root"
        assert row[1] == "203.0.113.50"
        assert row[2] == "ssh"
        assert row[3] == "ssh:notty"

        # Check console login (no IP)
        cur.execute("""
            SELECT username, source_ip, protocol
            FROM failed_logins
            WHERE username = 'user' AND source_ip IS NULL
        """)
        row = cur.fetchone()
        assert row is not None, "Should find console login with NULL IP"
        assert row[0] == "user"
        assert row[1] is None
        assert row[2] == "console"

        # Check that boot/reboot lines were skipped
        cur.execute("""
            SELECT COUNT(*) FROM failed_logins
            WHERE username IN ('reboot', 'shutdown')
        """)
        assert cur.fetchone()[0] == 0, "boot/reboot lines should be skipped"

        # Check hostname entry (evil.example.com) stored as NULL IP
        cur.execute("""
            SELECT username, source_ip FROM failed_logins
            WHERE username = 'guest'
        """)
        row = cur.fetchone()
        assert row is not None
        assert row[1] is None, "Non-IP hostname should be stored as NULL"

        conn.close()

    def test_ipv6_records(self, db_conn):
        """Verify IPv6 addresses are stored correctly."""
        conn = db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT host(source_ip) FROM failed_logins
            WHERE host(source_ip) LIKE '2001:%'
        """)
        ipv6_records = [row[0] for row in cur.fetchall()]
        assert len(ipv6_records) >= 1, "Should have at least one IPv6 record"

        conn.close()

    def test_geolocation_enrichment(self, db_conn):
        """Test geolocation for private IPs (doesn't need GeoLite2 DB)."""
        enriched = run_geolocation_private_only(db_conn)
        assert enriched > 0, "Should enrich at least some IPs"

        conn = db_conn()
        cur = conn.cursor()

        # Check private IP geolocation
        cur.execute("""
            SELECT country, city FROM ip_geolocations
            WHERE ip = '10.0.0.1'
        """)
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "Private"
        assert row[1] == "Private Network"

        # Check that 192.168.1.100 is also marked as private
        cur.execute("""
            SELECT country_code FROM ip_geolocations
            WHERE ip = '192.168.1.100'
        """)
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "XX"

        conn.close()

    def test_login_attempts_geo_view(self, db_conn):
        """Verify the join view works correctly."""
        conn = db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*) FROM login_attempts_geo
        """)
        view_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM failed_logins")
        table_count = cur.fetchone()[0]

        # View should have same number of rows as failed_logins (LEFT JOIN)
        assert view_count == table_count

        # Check that geolocation data is joined for enriched IPs
        cur.execute("""
            SELECT country FROM login_attempts_geo
            WHERE source_ip = '10.0.0.1'
        """)
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "Private"

        conn.close()

    def test_materialized_views_refresh(self, db_conn):
        """Verify materialized views can be refreshed and contain data."""
        conn = db_conn()
        conn.autocommit = True
        cur = conn.cursor()

        # Refresh views
        cur.execute("SELECT refresh_materialized_views()")

        # daily_stats should have data
        cur.execute("SELECT COUNT(*), SUM(total_attempts) FROM daily_stats")
        row = cur.fetchone()
        assert row[0] > 0, "daily_stats should have rows"
        assert row[1] > 0, "daily_stats should show attempts"

        # monthly_stats should have data
        cur.execute("SELECT COUNT(*) FROM monthly_stats")
        assert cur.fetchone()[0] > 0

        # country_stats might have data if we enriched public IPs
        # (with placeholder 'Unknown' entries it won't because country_code='XX' is excluded)
        # That's fine — we just verify it doesn't error
        cur.execute("SELECT COUNT(*) FROM country_stats")
        country_count = cur.fetchone()[0]
        # Not asserting > 0 because XX entries are excluded from country_stats

        conn.close()

    def test_unique_constraint_nulls(self, db_conn):
        """Verify NULLS NOT DISTINCT works — can't insert duplicate console logins."""
        conn = db_conn()
        cur = conn.cursor()

        # Try inserting a duplicate console login (username='user', source_ip=NULL)
        cur.execute("""
            INSERT INTO failed_logins (username, source_ip, timestamp, terminal, protocol, raw_line)
            VALUES ('user', NULL, '2026-02-14 04:00:01+00', 'tty1', 'console', 'duplicate test')
            ON CONFLICT (username, source_ip, timestamp) DO NOTHING
        """)
        conn.commit()

        # Should not have created a duplicate
        cur.execute("""
            SELECT COUNT(*) FROM failed_logins
            WHERE username = 'user' AND source_ip IS NULL
        """)
        assert cur.fetchone()[0] == 1, "NULLS NOT DISTINCT should prevent duplicate NULL-IP entries"

        conn.close()

    def test_indexes_exist(self, db_conn):
        """Verify performance indexes are created."""
        conn = db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'failed_logins'
            ORDER BY indexname
        """)
        indexes = [row[0] for row in cur.fetchall()]

        assert "idx_failed_logins_timestamp" in indexes
        assert "idx_failed_logins_source_ip" in indexes
        assert "idx_failed_logins_username" in indexes
        assert "idx_failed_logins_ts_ip" in indexes

        conn.close()
