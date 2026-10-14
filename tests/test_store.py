from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from checkin.store import ALREADY, FAILURE, SUCCESS, Attempt, Store

TZ = ZoneInfo("Asia/Shanghai")
TODAY = date(2026, 10, 13)
YESTERDAY = date(2026, 10, 12)


def at(hour, minute=0, day=TODAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def store(tmp_path):
    return Store(tmp_path / "d.sqlite")


def test_record_and_latest(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "第264次签到", 1, None, at(3, 20)))
    assert s.latest("hhanclub").message == "第264次签到"
    assert s.latest("hhanclub").streak == 1
    assert s.latest("hhanclub").at == at(3, 20)


def test_latest_unknown_site_is_none(tmp_path):
    assert store(tmp_path).latest("nope") is None


def test_latest_is_the_most_recent_attempt(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", FAILURE, None, None, "boom", at(3, 20)))
    s.record(Attempt("hhanclub", SUCCESS, "第264次签到", 1, None, at(3, 35)))
    assert s.latest("hhanclub").outcome == SUCCESS


def test_latest_is_scoped_to_the_site(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hdfans", SUCCESS, "hdfans message", 892, None, at(3, 20)))
    assert s.latest("hhanclub") is None


def test_attempts_on_is_scoped_to_the_day_and_ordered(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", FAILURE, None, None, "boom", at(4, 20)))
    s.record(Attempt("hhanclub", FAILURE, None, None, "boom", at(3, 20)))
    s.record(Attempt("hhanclub", SUCCESS, "yesterday", None, None, at(3, 20, YESTERDAY)))
    assert [a.at.hour for a in s.attempts_on("hhanclub", TODAY)] == [3, 4]


def test_attempts_on_empty_day_is_empty(tmp_path):
    assert store(tmp_path).attempts_on("hhanclub", TODAY) == []


def test_day_outcomes_prefers_success_over_failure(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", FAILURE, None, None, "boom", at(3, 20)))
    s.record(Attempt("hhanclub", SUCCESS, "第264次签到", 1, None, at(3, 35)))
    assert s.day_outcomes("hhanclub", [TODAY]) == {TODAY: SUCCESS}


def test_day_outcomes_prefers_already_over_failure(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", FAILURE, None, None, "boom", at(3, 20)))
    s.record(Attempt("hhanclub", ALREADY, "你今天已经签到过了", None, None, at(3, 35)))
    assert s.day_outcomes("hhanclub", [TODAY]) == {TODAY: ALREADY}


def test_day_outcomes_prefers_success_over_already(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", ALREADY, "你今天已经签到过了", None, None, at(3, 20)))
    s.record(Attempt("hhanclub", SUCCESS, "第264次签到", 1, None, at(3, 35)))
    assert s.day_outcomes("hhanclub", [TODAY]) == {TODAY: SUCCESS}


def test_day_outcomes_omits_days_without_attempts(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "第264次签到", 1, None, at(3, 20)))
    assert s.day_outcomes("hhanclub", [YESTERDAY, TODAY]) == {TODAY: SUCCESS}


def test_day_outcomes_is_scoped_to_the_site(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hdfans", SUCCESS, "hdfans", 892, None, at(3, 20)))
    assert s.day_outcomes("hhanclub", [TODAY]) == {}


def test_prune_drops_old_rows_only(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "old", None, None, at(3, 20, TODAY - timedelta(days=100))))
    s.record(Attempt("hhanclub", SUCCESS, "recent", None, None, at(3, 20, YESTERDAY)))
    assert s.prune(90, TODAY) == 1
    assert s.latest("hhanclub").at.date() == YESTERDAY


def test_prune_with_nothing_old_returns_zero(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "recent", None, None, at(3, 20)))
    assert s.prune(90, TODAY) == 0


def test_schema_survives_reopen(tmp_path):
    path = tmp_path / "d.sqlite"
    Store(path).record(Attempt("hhanclub", SUCCESS, "第264次签到", 1, None, at(3, 20)))
    assert Store(path).latest("hhanclub") is not None


def test_creates_the_parent_directory(tmp_path):
    s = Store(tmp_path / "nested" / "d.sqlite")
    s.record(Attempt("hhanclub", SUCCESS, "m", None, None, at(3, 20)))
    assert s.latest("hhanclub") is not None


def test_detail_and_nulls_round_trip(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", FAILURE, None, None, "cloudflare challenge (403)", at(3, 20)))
    got = s.latest("hhanclub")
    assert got.message is None and got.streak is None
    assert got.detail == "cloudflare challenge (403)"
