"""Schedule parsing — interval and simple cron support, no external deps."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Pattern: "every 6h", "every 30m", "every 1d"
_INTERVAL_RE = re.compile(r"^every\s+(\d+)\s*([hmd])$", re.IGNORECASE)

# Simple cron: "M H * * *" (minute hour day-of-month month day-of-week)
_CRON_RE = re.compile(r"^(\d+|\*)\s+(\d+|\*)\s+(\S+)\s+(\S+)\s+(\S+)$")

_UNIT_MAP = {
    "m": "minutes",
    "h": "hours",
    "d": "days",
}


def parse_interval(schedule: str) -> timedelta | None:
    """Parse an interval string like 'every 6h' into a timedelta.

    Returns None if the schedule is not an interval format.
    """
    m = _INTERVAL_RE.match(schedule.strip())
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    return timedelta(**{_UNIT_MAP[unit]: amount})


def next_run(schedule: str, after: datetime) -> datetime | None:
    """Compute next run time for a schedule string.

    Supports:
    - Intervals: "every 6h", "every 30m", "every 1d"
    - Simple cron: "M H * * *" (only minute+hour fields, rest must be *)

    Returns None if the schedule string cannot be parsed.
    """
    schedule = schedule.strip()

    # Try interval
    delta = parse_interval(schedule)
    if delta is not None:
        return after + delta

    # Try simple cron
    m = _CRON_RE.match(schedule)
    if not m:
        return None

    minute_s, hour_s, dom, mon, dow = m.groups()

    # Only support minute+hour with wildcards for the rest
    if dom != "*" or mon != "*" or dow != "*":
        return None
    if minute_s == "*" or hour_s == "*":
        return None

    target_minute = int(minute_s)
    target_hour = int(hour_s)

    if not (0 <= target_hour <= 23 and 0 <= target_minute <= 59):
        return None

    # Build candidate for today
    candidate = after.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def is_due(schedule: str, last_run: datetime | None, now: datetime | None = None) -> bool:
    """Check if a schedule is due to run.

    Returns True if:
    - Never run before (last_run is None), or
    - now >= next_run(schedule, last_run)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    if last_run is None:
        return True

    nr = next_run(schedule, last_run)
    if nr is None:
        return False

    return now >= nr
