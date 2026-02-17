"""Tests for agenda schedule parsing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from openhydra.agenda.schedule import is_due, next_run, parse_interval


class TestParseInterval:
    def test_hours(self):
        assert parse_interval("every 6h") == timedelta(hours=6)

    def test_minutes(self):
        assert parse_interval("every 30m") == timedelta(minutes=30)

    def test_days(self):
        assert parse_interval("every 1d") == timedelta(days=1)

    def test_case_insensitive(self):
        assert parse_interval("Every 2H") == timedelta(hours=2)

    def test_with_spaces(self):
        assert parse_interval("every  12 h") == timedelta(hours=12)

    def test_invalid_returns_none(self):
        assert parse_interval("not a schedule") is None
        assert parse_interval("every x hours") is None
        assert parse_interval("") is None


class TestNextRun:
    def test_interval_from_epoch(self):
        after = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = next_run("every 6h", after)
        assert result == datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc)

    def test_interval_minutes(self):
        after = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = next_run("every 30m", after)
        assert result == datetime(2025, 1, 1, 12, 30, 0, tzinfo=timezone.utc)

    def test_cron_same_day(self):
        after = datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc)
        result = next_run("0 9 * * *", after)
        assert result == datetime(2025, 1, 1, 9, 0, 0, tzinfo=timezone.utc)

    def test_cron_next_day(self):
        after = datetime(2025, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        result = next_run("0 9 * * *", after)
        assert result == datetime(2025, 1, 2, 9, 0, 0, tzinfo=timezone.utc)

    def test_cron_with_minute(self):
        after = datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        result = next_run("30 14 * * *", after)
        assert result == datetime(2025, 1, 1, 14, 30, 0, tzinfo=timezone.utc)

    def test_invalid_returns_none(self):
        after = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert next_run("nonsense", after) is None

    def test_partial_cron_not_supported(self):
        after = datetime(2025, 1, 1, tzinfo=timezone.utc)
        # Day-of-month not wildcard — not supported
        assert next_run("0 9 1 * *", after) is None

    def test_wildcard_hour_not_supported(self):
        after = datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert next_run("0 * * * *", after) is None


class TestIsDue:
    def test_never_run_is_due(self):
        assert is_due("every 6h", None) is True

    def test_recently_run_not_due(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        assert is_due("every 6h", last, now) is False

    def test_past_interval_is_due(self):
        now = datetime(2025, 1, 1, 18, 0, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        assert is_due("every 6h", last, now) is True

    def test_exact_boundary_is_due(self):
        now = datetime(2025, 1, 1, 17, 0, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        assert is_due("every 6h", last, now) is True

    def test_invalid_schedule_not_due(self):
        now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        last = datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc)
        assert is_due("nonsense", last, now) is False
