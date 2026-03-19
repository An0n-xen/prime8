"""Timezone and time formatting helpers."""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_timezone(dt: datetime, tz_name: str = "UTC") -> datetime:
    """Convert a datetime to the given timezone."""
    target_tz = ZoneInfo(tz_name)
    return dt.astimezone(target_tz)


def iso_now() -> str:
    """Current time as ISO 8601 string."""
    return now_utc().isoformat()


def human_delta(dt: datetime) -> str:
    """Return a human-readable 'in X hours/days' string."""
    now = now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    delta = dt - now

    if delta.total_seconds() < 0:
        return "already passed"
    elif delta.days > 0:
        return f"in {delta.days} day(s)"
    elif delta.seconds >= 3600:
        hours = delta.seconds // 3600
        return f"in {hours} hour(s)"
    else:
        minutes = delta.seconds // 60
        return f"in {minutes} minute(s)"
