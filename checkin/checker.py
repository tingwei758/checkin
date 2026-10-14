"""One request per site, and reading what came back.

`classify` is where the site's own wording turns into one of three
outcomes; `fetch` is the only place that touches the network.
"""

from __future__ import annotations

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


@dataclass(frozen=True)
class CheckResult:
    outcome: str
    message: Optional[str] = None
    streak: Optional[int] = None
    detail: Optional[str] = None


def classify(site: Site, status_code: int, body: str) -> CheckResult:
    body = body or ""

    if _looks_like_cloudflare(status_code, body):
        return CheckResult(FAILURE, detail="cloudflare challenge (HTTP %d)" % status_code)

    if status_code >= 400:
        return CheckResult(FAILURE, detail="HTTP %d" % status_code)

    match = re.search(site.success, body)
    if match:
        return CheckResult(SUCCESS, message=_collapse(match.group(0)), streak=_streak(site, body))

    if site.already:
        match = re.search(site.already, body)
        if match:
            return CheckResult(ALREADY, message=_collapse(match.group(0)), streak=_streak(site, body))

    return CheckResult(FAILURE, detail="no pattern match: " + _excerpt(body))


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
        detail = "%s: %s" % (type(exc).__name__, exc)
        return CheckResult(FAILURE, detail=detail[:EXCERPT_CHARS + 40])

    return classify(site, status_code, body)


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
