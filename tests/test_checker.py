from __future__ import annotations

import pytest

from checkin.checker import check, classify
from checkin.config import Site
from checkin.store import ALREADY, FAILURE, SUCCESS

HHAN = (
    "<div>这是您的第264次签到，已连续签到1天，本次签到获得10个憨豆。"
    "你目前拥有补签卡37张</div>"
)
HDFANS = (
    "签到成功\n这是您的第 1314 次签到，已连续签到 892 天，本次签到获得 100 个魔力值。"
    "点击白色背景的圆点进行补签。你目前拥有补签卡 10 张。"
)

SUCCESS_PATTERN = "这是您的第\\s*\\d+\\s*次签到[^<]*"
ALREADY_PATTERN = "你今天已经签到过了"
STREAK_PATTERN = "已连续签到\\s*(\\d+)\\s*天"


def site(name="hhanclub", cookie="uid=1", streak=STREAK_PATTERN, already=ALREADY_PATTERN):
    headers = {"Cookie": cookie} if cookie else {}
    return Site(
        name=name,
        url="https://%s.example/attendance.php" % name,
        success=SUCCESS_PATTERN,
        already=already,
        streak=streak,
        impersonate="chrome",
        headers=headers,
        cookie=cookie,
        enabled=True,
    )


def exploding_fetch(_site):
    raise AssertionError("fetch must not be called")


def test_success_keeps_the_sites_own_message():
    r = classify(site(), 200, HHAN)
    assert r.outcome == SUCCESS
    assert "第264次签到" in r.message and "10个憨豆" in r.message
    assert r.streak == 1


def test_success_with_spaced_numbers():
    r = classify(site("hdfans"), 200, HDFANS)
    assert r.outcome == SUCCESS
    assert r.streak == 892


def test_success_message_is_whitespace_collapsed():
    r = classify(site("hdfans"), 200, HDFANS.replace("，已连续", "，\n   已连续"))
    assert "\n" not in r.message
    assert "， 已连续签到 892 天" in r.message


def test_already_checked_in():
    r = classify(site(), 200, "你今天已经签到过了")
    assert r.outcome == ALREADY
    assert r.message == "你今天已经签到过了"


def test_already_without_a_pattern_falls_through_to_failure():
    r = classify(site(already=None), 200, "你今天已经签到过了")
    assert r.outcome == FAILURE


def test_streak_missing_is_none_not_an_error():
    r = classify(site(streak=None), 200, HHAN)
    assert r.outcome == SUCCESS and r.streak is None


def test_streak_pattern_that_does_not_match_is_none():
    r = classify(site(streak="连续了\\s*(\\d+)\\s*年"), 200, HHAN)
    assert r.outcome == SUCCESS and r.streak is None


def test_login_page_is_a_failure_with_an_excerpt():
    r = classify(site(), 200, "<html><title>登录</title>" + "x" * 500)
    assert r.outcome == FAILURE
    assert "no pattern match" in r.detail
    assert len(r.detail) <= 240


def test_cloudflare_challenge_is_named_as_such():
    r = classify(site(), 403, "<title>Just a moment...</title>")
    assert r.outcome == FAILURE
    assert "cloudflare" in r.detail.lower()


def test_cloudflare_body_on_a_200_is_still_cloudflare():
    r = classify(site(), 200, "<div id='cf-browser-verification'>Checking your browser</div>")
    assert r.outcome == FAILURE
    assert "cloudflare" in r.detail.lower()


def test_http_500_is_a_failure_naming_the_status():
    assert "500" in classify(site(), 500, "").detail


def test_http_302_to_login_is_a_failure():
    r = classify(site(), 200, "<html><body>Please login first</body></html>")
    assert r.outcome == FAILURE


def test_missing_cookie_short_circuits():
    r = check(site(cookie=None), fetch_fn=exploding_fetch)
    assert r.outcome == FAILURE
    assert r.detail == "no cookie configured"


def test_network_exception_becomes_a_failure_result():
    def boom(_site):
        raise TimeoutError("timed out after 30s")

    r = check(site(), fetch_fn=boom)
    assert r.outcome == FAILURE
    assert "TimeoutError" in r.detail and "timed out" in r.detail


def test_long_exception_message_is_truncated():
    def boom(_site):
        raise RuntimeError("x" * 500)

    assert len(check(site(), fetch_fn=boom).detail) <= 240


def test_non_utf8_body_still_classifies():
    body = b"\xff\xfe" + "这是您的第264次签到，已连续签到1天".encode("utf-8")
    assert classify(site(), 200, body.decode("utf-8", "replace")).outcome == SUCCESS


def test_check_passes_site_headers_to_fetch():
    seen = {}

    def spy(s):
        seen["headers"] = s.headers
        return 200, HHAN

    check(site(), fetch_fn=spy)
    assert "Cookie" in seen["headers"]


def test_check_returns_the_classified_result():
    assert check(site(), fetch_fn=lambda s: (200, HHAN)).streak == 1
