"""When to check in, and when to give up for the day.

Pure arithmetic, no scheduler: APScheduler lives in `runner.py` so these
decisions can be tested without a clock.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional, Sequence

from .store import ALREADY, SUCCESS, Attempt

#: A failure is retried twice; if that doesn't fix it, retrying won't.
RETRY_DELAYS = (timedelta(minutes=15), timedelta(hours=1))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


def next_run_time(now: datetime, run_at: time, tz: tzinfo) -> datetime:
    local = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    today = local.replace(hour=run_at.hour, minute=run_at.minute, second=0, microsecond=0)
    if today > local:
        return today
    return today + timedelta(days=1)


def jitter_seconds(site_name: str, day: date, window_minutes: int) -> int:
    window = window_minutes * 60
    if window <= 0:
        return 0
    # sha256, not hash(): hash() is salted per process, which would re-roll
    # the day's offsets on every restart.
    seed = hashlib.sha256(("%s:%s" % (site_name, day.isoformat())).encode("utf-8")).digest()
    return int.from_bytes(seed[:8], "big") % window


def retry_delay(attempt_number: int) -> Optional[timedelta]:
    if 1 <= attempt_number <= len(RETRY_DELAYS):
        return RETRY_DELAYS[attempt_number - 1]
    return None


def should_attempt(attempts_today: Sequence[Attempt]) -> bool:
    if any(attempt.outcome in (SUCCESS, ALREADY) for attempt in attempts_today):
        return False
    return len(attempts_today) < MAX_ATTEMPTS
