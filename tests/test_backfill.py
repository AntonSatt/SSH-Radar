"""Tests for planning the username backfill (no database needed)."""

import os
import sys
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from backfill_usernames import plan_changes


TS = datetime(2026, 11, 3, 10, 19, 26, tzinfo=timezone.utc)
STAMP = "Tue Nov  3 10:19:26 2026 - Tue Nov  3 10:19:26 2026  (00:00)"


def _line(username_column: str, ip: str = "203.0.113.50") -> str:
    return f"{username_column} ssh:notty    {ip:<16} {STAMP}"


def _row(row_id, username, raw_line, ip="203.0.113.50", terminal="ssh:notty", protocol="ssh"):
    return {
        "id": row_id,
        "username": username,
        "source_ip": ip,
        "timestamp": TS,
        "terminal": terminal,
        "protocol": protocol,
        "raw_line": raw_line,
    }


class TestPlanChanges:
    def test_truncated_username_is_updated(self):
        narrow, wide = _line("minecraf"), _line("minecraft")
        changes = plan_changes([(narrow, wide)], [_row(1, "minecraf", narrow)])

        assert len(changes) == 1
        action, row, values = changes[0]
        assert action == "update"
        assert row["id"] == 1
        assert values[0] == "minecraft"
        assert values[5] == wide

    def test_unchanged_row_is_left_alone(self):
        line = _line("root    ")
        assert plan_changes([(line, line)], [_row(1, "root", line)]) == []

    def test_empty_username_is_repaired(self):
        line = _line("        ")
        # The old parser took the terminal as username and the IP as terminal
        stored = _row(1, "ssh:notty", line, ip=None, terminal="203.0.113.50", protocol="unknown")
        changes = plan_changes([(line, line)], [stored])

        assert len(changes) == 1
        action, _, values = changes[0]
        assert action == "update"
        assert values[:2] == ("", "203.0.113.50")
        assert values[3:5] == ("ssh:notty", "ssh")

    def test_dropped_reboot_attempt_is_inserted(self):
        line = _line("reboot  ")
        changes = plan_changes([(line, line)], [])

        assert len(changes) == 1
        action, row, values = changes[0]
        assert action == "insert"
        assert row is None
        assert values[0] == "reboot"

    def test_row_already_ingested_in_full_is_not_duplicated(self):
        narrow, wide = _line("antonsat"), _line("antonsatt")
        stored = [_row(1, "antonsat", narrow), _row(2, "antonsatt", wide)]
        changes = plan_changes([(narrow, wide)], stored)

        assert [(action, row["id"]) for action, row, _ in changes] == [("delete", 1)]

    def test_two_names_collapsed_by_truncation_are_split(self):
        narrow = _line("antonsat")
        wide_a, wide_b = _line("antonsatt"), _line("antonsatx")
        changes = plan_changes([(narrow, wide_a), (narrow, wide_b)], [_row(1, "antonsat", narrow)])

        assert [(action, values[0]) for action, _, values in changes] == [
            ("update", "antonsatt"),
            ("insert", "antonsatx"),
        ]

    def test_running_twice_changes_nothing(self):
        narrow, wide = _line("minecraf"), _line("minecraft")
        assert plan_changes([(narrow, wide)], [_row(1, "minecraft", wide)]) == []
