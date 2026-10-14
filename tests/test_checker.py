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


# The real hdfans reply: NexusPHP wraps every number in <b> tags.
HDFANS_TAGGED = (
    '<h2 align="left">签到成功</h2><table><tr><td class="text"> '
    "<p>这是您的第 <b>1314</b> 次签到，已连续签到 <b>892</b> 天，本次签到获得 <b>100</b> 个魔力值。"
    "点击白色背景的圆点进行补签。你目前拥有补签卡 <b>10</b> 张。"
    '<span style="float:right">今日签到排名：<b>802</b> / <b>5174</b></span></p></td></tr></table>'
)
SENTENCE_PATTERN = "这是您的第\\s*\\d+\\s*次签到[^。]*。"


def tagged_site():
    return Site(
        name="hdfans",
        url="https://hdfans.org/attendance.php",
        success=SENTENCE_PATTERN,
        already=ALREADY_PATTERN,
        streak=STREAK_PATTERN,
        impersonate="chrome",
        headers={"Cookie": "uid=1"},
        cookie="uid=1",
        enabled=True,
    )


def test_numbers_wrapped_in_tags_still_match():
    r = classify(tagged_site(), 200, HDFANS_TAGGED)
    assert r.outcome == SUCCESS
    assert r.streak == 892


def test_message_from_a_tagged_page_carries_no_markup():
    r = classify(tagged_site(), 200, HDFANS_TAGGED)
    assert "<b>" not in r.message and "<" not in r.message
    assert "这是您的第 1314 次签到" in r.message
    assert "获得 100 个魔力值" in r.message


def test_message_stops_at_the_end_of_the_sentence():
    r = classify(tagged_site(), 200, HDFANS_TAGGED)
    assert "今日签到排名" not in r.message


def test_entities_are_decoded_before_matching():
    body = "<p>这是您的第 <b>5</b> 次签到&nbsp;，已连续签到 <b>5</b> 天，获得 10 个魔力值。</p>"
    r = classify(tagged_site(), 200, body)
    assert r.outcome == SUCCESS and r.streak == 5


def test_script_contents_are_not_matched():
    body = "<script>var s = '这是您的第 1 次签到，已连续签到 1 天。';</script><p>你今天已经签到过了</p>"
    assert classify(tagged_site(), 200, body).outcome == ALREADY


def test_failure_excerpt_is_readable_text_not_markup():
    body = '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><p>请先登录</p></body></html>'
    r = classify(tagged_site(), 200, body)
    assert r.outcome == FAILURE
    assert "DOCTYPE" not in r.detail
    assert "请先登录" in r.detail
