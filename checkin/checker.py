"""One request per site, and reading what came back.

`classify` is where the site's own wording turns into one of three
outcomes; `fetch` is the only place that touches the network.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from .config import Site
from .store import ALREADY, FAILURE, SUCCESS

EXCERPT_CHARS = 200
DEFAULT_TIMEOUT = 30.0

#: Cloudflare's interstitials, as served to a client it doesn't believe.
CLOUDFLARE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "checking your browser",
    "__cf_chl",
    "cf-challenge",
    "attention required! | cloudflare",
)
CLOUDFLARE_STATUSES = (403, 429, 503)

#: A rejected session: the tracker served its login page instead of the
#: check-in. Worth naming, because the fix is "paste a fresh cookie".
LOGIN_MARKERS = (
    "takelogin.php",
    "login.php?returnto",
    "该页面必须在登录后才能访问",
    "未登录",
)


@dataclass(frozen=True)
class CheckResult:
    outcome: str
    message: Optional[str] = None
    streak: Optional[int] = None
    detail: Optional[str] = None


def classify(site: Site, status_code: int, body: str) -> CheckResult:
    body = body or ""

    # Cloudflare's markers live in markup and scripts, so they are matched
    # against the raw body; the site's own wording is matched against the
    # visible text, because trackers wrap their numbers in <b> tags.
    if _looks_like_cloudflare(status_code, body):
        return CheckResult(FAILURE, detail="cloudflare challenge (HTTP %d)" % status_code)

    if status_code >= 400:
        return CheckResult(FAILURE, detail="HTTP %d" % status_code)

    text = visible_text(body)

    match = re.search(site.success, text)
    if match:
        return CheckResult(SUCCESS, message=_collapse(match.group(0)), streak=_streak(site, text))

    if site.already:
        match = re.search(site.already, text)
        if match:
            return CheckResult(ALREADY, message=_collapse(match.group(0)), streak=_streak(site, text))

    if _looks_like_login(body, text):
        return CheckResult(FAILURE, detail="cookie expired (login page)")

    return CheckResult(FAILURE, detail="no pattern match: " + _excerpt(text))


def fetch(site: Site, timeout: float = DEFAULT_TIMEOUT) -> Tuple[int, str]:
    from curl_cffi import requests

    response = requests.get(
        site.url,
        headers=site.headers,
        impersonate=site.impersonate,
        timeout=timeout,
        allow_redirects=True,
    )
    return response.status_code, response.text


def check(site: Site, fetch_fn: Optional[Callable[[Site], Tuple[int, str]]] = None) -> CheckResult:
    if not site.cookie:
        return CheckResult(FAILURE, detail="no cookie configured")

    fetch_fn = fetch_fn or fetch
    try:
        status_code, body = fetch_fn(site)
    except Exception as exc:  # noqa: BLE001 - any failure is a failed check-in, not a crash
        detail = "%s: %s" % (type(exc).__name__, _without_curl_boilerplate(str(exc)))
        return CheckResult(FAILURE, detail=detail[:EXCERPT_CHARS + 40])

    return classify(site, status_code, body)


def visible_text(body: str) -> str:
    """The text a reader would see: no tags, no scripts, entities decoded."""
    without_code = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", body)
    without_tags = re.sub(r"(?s)<[^>]*>", " ", without_code)
    return _collapse(html.unescape(without_tags).replace("\xa0", " "))


def _without_curl_boilerplate(message: str) -> str:
    """curl's errors end in a documentation URL that the status page doesn't need."""
    trimmed = re.sub(r"\s*See https://curl\.se/\S*.*$", "", message).strip()
    return trimmed or message


def _looks_like_login(body: str, text: str) -> bool:
    haystack = (body + " " + text).lower()
    return any(marker.lower() in haystack for marker in LOGIN_MARKERS)


def _looks_like_cloudflare(status_code: int, body: str) -> bool:
    lowered = body[:4000].lower()
    if any(marker in lowered for marker in CLOUDFLARE_MARKERS):
        return True
    return status_code in CLOUDFLARE_STATUSES


def _streak(site: Site, body: str) -> Optional[int]:
    if not site.streak:
        return None
    match = re.search(site.streak, body)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _excerpt(body: str) -> str:
    return _collapse(body)[:EXCERPT_CHARS]
