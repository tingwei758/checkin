from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from checkin.config import Config, Site
from checkin.store import ALREADY, FAILURE, SUCCESS, Attempt, Store
from checkin.view import build_page

TZ = ZoneInfo("Asia/Shanghai")
TODAY = date(2026, 10, 13)
NEXT = datetime(2026, 10, 14, 3, 20, tzinfo=TZ)


def site(name, cookie="uid=1", enabled=True):
    return Site(
        name=name,
        url="https://%s.example/attendance.php" % name,
        success="success",
        already="already",
        streak="streak (\\d+)",
        impersonate="chrome",
        headers={"Cookie": cookie} if cookie else {},
        cookie=cookie,
        enabled=enabled,
    )


def config(*sites, **kwargs):
    return Config(sites=tuple(sites), history_days=kwargs.get("history_days", 7))


def at(hour=3, minute=20, day=TODAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def store(tmp_path):
    return Store(tmp_path / "d.sqlite")


def test_every_configured_site_gets_a_row_even_with_no_history(tmp_path):
    page = build_page(config(site("hhanclub"), site("hdfans")), store(tmp_path), TODAY, NEXT)
    assert [r.name for r in page.rows] == ["hhanclub", "hdfans"]
    assert page.rows[0].last_result == "never run"
    assert all(d.outcome is None for d in page.rows[0].dots)
    assert page.site_count == 2


def test_dots_are_history_days_long_oldest_first(tmp_path):
    page = build_page(config(site("hhanclub")), store(tmp_path), TODAY, NEXT)
    dots = page.rows[0].dots
    assert len(dots) == 7
    assert dots[-1].day == TODAY
    assert dots[0].day == TODAY - timedelta(days=6)


def test_history_days_is_honoured(tmp_path):
    page = build_page(config(site("hhanclub"), history_days=3), store(tmp_path), TODAY, NEXT)
    assert len(page.rows[0].dots) == 3


def test_row_shows_the_sites_message_and_streak(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "这是您的第264次签到，已连续签到1天", 1, None, at()))
    page = build_page(config(site("hhanclub")), s, TODAY, NEXT)
    assert "第264次签到" in page.rows[0].last_result
    assert page.rows[0].streak == 1
    assert page.rows[0].last_at == at()


def test_dot_for_today_reflects_the_outcome(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "m", 1, None, at()))
    page = build_page(config(site("hhanclub")), s, TODAY, NEXT)
    assert page.rows[0].dots[-1].outcome == SUCCESS


def test_failed_row_shows_the_reason_and_attempt_count(tmp_path):
    s = store(tmp_path)
    for hour in (3, 3, 4):
        s.record(Attempt("hhanclub", FAILURE, None, None, "cloudflare challenge (HTTP 403)", at(hour)))
    page = build_page(config(site("hhanclub")), s, TODAY, NEXT)
    assert page.rows[0].failed is True
    assert "cloudflare" in page.rows[0].last_result.lower()
    assert page.rows[0].attempts_today == 3


def test_site_without_cookie_says_so(tmp_path):
    page = build_page(config(site("hhanclub", cookie=None)), store(tmp_path), TODAY, NEXT)
    assert page.rows[0].has_cookie is False
    assert page.rows[0].last_result == "no cookie configured"


def test_disabled_site_is_listed_but_not_counted_as_ok(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "m", 1, None, at()))
    s.record(Attempt("hdfans", SUCCESS, "m", 1, None, at()))
    page = build_page(config(site("hhanclub"), site("hdfans", enabled=False)), s, TODAY, NEXT)
    assert page.rows[1].enabled is False
    assert page.ok_today == 1


def test_ok_today_counts_success_and_already(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "m", 1, None, at()))
    s.record(Attempt("hdfans", ALREADY, "你今天已经签到过了", None, None, at()))
    page = build_page(config(site("hhanclub"), site("hdfans")), s, TODAY, NEXT)
    assert page.ok_today == 2


def test_already_outcome_is_not_marked_failed(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", ALREADY, "你今天已经签到过了", None, None, at()))
    page = build_page(config(site("hhanclub")), s, TODAY, NEXT)
    assert page.rows[0].failed is False


def test_yesterdays_failure_does_not_mark_the_row_failed_today(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", FAILURE, None, None, "boom", at(day=TODAY - timedelta(days=1))))
    page = build_page(config(site("hhanclub")), s, TODAY, NEXT)
    assert page.rows[0].failed is False
    assert page.rows[0].attempts_today == 0


def test_streak_falls_back_to_the_last_known_value(tmp_path):
    s = store(tmp_path)
    s.record(Attempt("hhanclub", SUCCESS, "m", 892, None, at(day=TODAY - timedelta(days=1))))
    s.record(Attempt("hhanclub", FAILURE, None, None, "boom", at()))
    page = build_page(config(site("hhanclub")), s, TODAY, NEXT)
    assert page.rows[0].streak == 892


def test_next_run_is_carried_through(tmp_path):
    page = build_page(config(site("hhanclub")), store(tmp_path), TODAY, NEXT)
    assert page.next_run == NEXT
