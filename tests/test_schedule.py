from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from checkin.schedule import RETRY_DELAYS, jitter_seconds, next_run_time, retry_delay, should_attempt
from checkin.store import ALREADY, FAILURE, SUCCESS, Attempt

TZ = ZoneInfo("Asia/Shanghai")
DAY = date(2026, 10, 13)
DAY2 = date(2026, 10, 14)


def a(outcome):
    return Attempt("hhanclub", outcome, None, None, None, datetime(2026, 10, 13, 3, 20, tzinfo=TZ))


def test_next_run_is_today_when_before_0320():
    now = datetime(2026, 10, 13, 1, 0, tzinfo=TZ)
    assert next_run_time(now, time(3, 20), TZ) == datetime(2026, 10, 13, 3, 20, tzinfo=TZ)


def test_next_run_is_tomorrow_when_after_0320():
    now = datetime(2026, 10, 13, 9, 0, tzinfo=TZ)
    assert next_run_time(now, time(3, 20), TZ) == datetime(2026, 10, 14, 3, 20, tzinfo=TZ)


def test_next_run_is_tomorrow_at_exactly_0320():
    now = datetime(2026, 10, 13, 3, 20, tzinfo=TZ)
    assert next_run_time(now, time(3, 20), TZ).day == 14


def test_next_run_uses_the_target_zone_not_the_host_clock():
    now = datetime(2026, 10, 12, 20, 0, tzinfo=timezone.utc)  # = 04:00 CST on the 13th
    assert next_run_time(now, time(3, 20), TZ) == datetime(2026, 10, 14, 3, 20, tzinfo=TZ)


def test_next_run_accepts_a_naive_now_as_target_zone_local():
    now = datetime(2026, 10, 13, 1, 0)
    assert next_run_time(now, time(3, 20), TZ) == datetime(2026, 10, 13, 3, 20, tzinfo=TZ)


def test_jitter_is_in_window_and_deterministic():
    first = jitter_seconds("hhanclub", DAY, 20)
    assert 0 <= first < 1200
    assert first == jitter_seconds("hhanclub", DAY, 20)


def test_jitter_differs_by_site_and_by_day():
    assert jitter_seconds("hhanclub", DAY, 20) != jitter_seconds("hdfans", DAY, 20)
    assert jitter_seconds("hhanclub", DAY, 20) != jitter_seconds("hhanclub", DAY2, 20)


def test_jitter_zero_window_is_zero():
    assert jitter_seconds("hhanclub", DAY, 0) == 0


def test_jitter_spreads_ten_sites_across_the_window():
    values = [jitter_seconds("site%d" % i, DAY, 20) for i in range(10)]
    assert len(set(values)) >= 8
    assert all(0 <= v < 1200 for v in values)


def test_retry_delays():
    assert retry_delay(1) == timedelta(minutes=15)
    assert retry_delay(2) == timedelta(hours=1)
    assert retry_delay(3) is None
    assert RETRY_DELAYS == (timedelta(minutes=15), timedelta(hours=1))


def test_should_attempt_stops_after_success_or_already():
    assert should_attempt([]) is True
    assert should_attempt([a(FAILURE)]) is True
    assert should_attempt([a(SUCCESS)]) is False
    assert should_attempt([a(ALREADY)]) is False
    assert should_attempt([a(FAILURE), a(FAILURE)]) is True
    assert should_attempt([a(FAILURE), a(FAILURE), a(FAILURE)]) is False
