"""Tests for ingest helpers that need no database."""

import os
import sys
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ingest import misses_rotated_records


def _at(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, tzinfo=timezone.utc)


def _records(*timestamps: datetime) -> list[dict]:
    return [{"timestamp": ts} for ts in timestamps]


class TestMissesRotatedRecords:
    def test_current_btmp_overlaps_stored_history(self):
        records = _records(_at(1, 0, 0, 3), _at(3, 11, 50))
        assert misses_rotated_records(records, _at(3, 11, 45)) is False

    def test_rotated_since_last_run(self):
        # Last run stored 23:55 on the 30th; the new btmp starts after midnight
        records = _records(datetime(2026, 12, 1, 0, 0, 4, tzinfo=timezone.utc))
        latest = datetime(2026, 11, 30, 23, 55, 1, tzinfo=timezone.utc)
        assert misses_rotated_records(records, latest) is True

    def test_empty_btmp_right_after_rotation(self):
        assert misses_rotated_records([], _at(30, 23, 55)) is True

    def test_newest_stored_is_oldest_in_btmp(self):
        assert misses_rotated_records(_records(_at(1, 0, 0, 3)), _at(1, 0, 0, 3)) is False

    def test_empty_table_reads_only_current_btmp(self):
        assert misses_rotated_records(_records(_at(1, 0, 0, 3)), None) is False
        assert misses_rotated_records([], None) is False
