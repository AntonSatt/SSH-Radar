"""Tests for the lastb parser."""

import os
import sys
from datetime import datetime, timezone

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from parser import parse_lastb_line, parse_lastb_output


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return f.read()


# ── Individual line parsing ──────────────────────────────────────────


class TestParseLastbLine:
    def test_normal_ssh_login(self):
        line = "root     ssh:notty    203.0.113.50     Fri Feb 14 03:22:15 2026 - Fri Feb 14 03:22:15 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        assert result["username"] == "root"
        assert result["source_ip"] == "203.0.113.50"
        assert result["terminal"] == "ssh:notty"
        assert result["protocol"] == "ssh"
        assert result["timestamp"] == datetime(2026, 2, 14, 3, 22, 15, tzinfo=timezone.utc)
        assert result["raw_line"] == line

    def test_ipv6_address(self):
        line = "root     ssh:notty    2001:db8::1      Fri Feb 14 05:00:00 2026 - Fri Feb 14 05:00:00 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        assert result["source_ip"] == "2001:db8::1"
        assert result["protocol"] == "ssh"

    def test_long_ipv6_address(self):
        line = "root     ssh:notty    2001:db8:85a3::8a2e:370:7334 Fri Feb 14 05:01:00 2026 - Fri Feb 14 05:01:00 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        assert result["source_ip"] == "2001:db8:85a3::8a2e:370:7334"

    def test_console_login_no_ip(self):
        line = "user     tty1                          Fri Feb 14 04:00:01 2026 - Fri Feb 14 04:00:01 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        assert result["username"] == "user"
        assert result["source_ip"] is None
        assert result["terminal"] == "tty1"
        assert result["protocol"] == "console"

    def test_skip_reboot_line(self):
        line = "reboot   system boot  5.4.0-42-generic Sat Feb 15 14:00:00 2026 - Sat Feb 15 14:05:00 2026  (00:05)"
        result = parse_lastb_line(line)
        assert result is None

    def test_skip_shutdown_line(self):
        line = "shutdown system down  5.4.0-42-generic Sat Feb 15 13:59:55 2026 - Sat Feb 15 14:00:00 2026  (00:00)"
        result = parse_lastb_line(line)
        assert result is None

    def test_skip_btmp_begins(self):
        line = "btmp begins Fri Feb 14 03:22:15 2026"
        result = parse_lastb_line(line)
        assert result is None

    def test_skip_empty_line(self):
        assert parse_lastb_line("") is None
        assert parse_lastb_line("   ") is None
        assert parse_lastb_line("\n") is None

    def test_hostname_as_source(self):
        line = "guest    ssh:notty    evil.example.com Sat Feb 15 13:00:00 2026 - Sat Feb 15 13:00:00 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        assert result["username"] == "guest"
        # Hostnames are returned as-is; ingest.py handles whether to store as IP or not
        assert result["source_ip"] == "evil.example.com"

    def test_pts_terminal(self):
        line = "ftpuser  pts/0        198.51.100.50    Sun Feb 16 03:00:00 2026 - Sun Feb 16 03:00:00 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        assert result["protocol"] == "pts"
        assert result["terminal"] == "pts/0"
        assert result["source_ip"] == "198.51.100.50"

    def test_private_ip_still_parsed(self):
        line = "pi       ssh:notty    10.0.0.1         Sat Feb 15 12:30:00 2026 - Sat Feb 15 12:30:00 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        assert result["source_ip"] == "10.0.0.1"

    def test_timestamp_accuracy(self):
        line = "admin    ssh:notty    198.51.100.23    Fri Feb 14 03:22:16 2026 - Fri Feb 14 03:22:16 2026  (00:00)"
        result = parse_lastb_line(line)

        assert result is not None
        ts = result["timestamp"]
        assert ts.year == 2026
        assert ts.month == 2
        assert ts.day == 14
        assert ts.hour == 3
        assert ts.minute == 22
        assert ts.second == 16
        assert ts.tzinfo == timezone.utc


# ── Full output parsing ──────────────────────────────────────────────


class TestParseLastbOutput:
    def test_parse_fixture_file(self):
        text = _load_fixture("sample_lastb.txt")
        results = parse_lastb_output(text)

        # 19 lines total: 15 login attempts + 2 skip (reboot, shutdown) + 1 blank + 1 footer (btmp begins)
        assert len(results) == 15

    def test_no_reboot_or_shutdown_in_results(self):
        text = _load_fixture("sample_lastb.txt")
        results = parse_lastb_output(text)

        usernames = {r["username"] for r in results}
        assert "reboot" not in usernames
        assert "shutdown" not in usernames

    def test_all_results_have_required_fields(self):
        text = _load_fixture("sample_lastb.txt")
        results = parse_lastb_output(text)

        required_keys = {"username", "source_ip", "timestamp", "terminal", "protocol", "raw_line"}
        for result in results:
            assert required_keys.issubset(result.keys()), f"Missing keys in {result}"

    def test_empty_input(self):
        assert parse_lastb_output("") == []

    def test_only_header_footer(self):
        text = "\nbtmp begins Fri Feb 14 03:22:15 2026\n"
        assert parse_lastb_output(text) == []

    def test_protocols_detected(self):
        text = _load_fixture("sample_lastb.txt")
        results = parse_lastb_output(text)

        protocols = {r["protocol"] for r in results}
        assert "ssh" in protocols
        assert "console" in protocols
        assert "pts" in protocols
