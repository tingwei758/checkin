"""Turning config plus history into the rows the page draws.

Pure: no Flask, no SQL beyond what the store exposes. The row list comes
from config, so a site that has never run still gets a line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from .config import Config
from .store import ALREADY, FAILURE, SUCCESS, Store

OK_OUTCOMES = (SUCCESS, ALREADY)


@dataclass(frozen=True)
class Dot:
    day: date
    outcome: Optional[str]


@dataclass(frozen=True)
class Row:
    name: str
    enabled: bool
    dots: List[Dot]
    streak: Optional[int]
    last_result: str
    last_at: Optional[datetime]
    failed: bool
    attempts_today: int
    has_cookie: bool


@dataclass(frozen=True)
class Page:
    rows: List[Row]
    site_count: int
    ok_today: int
    next_run: datetime


def build_page(config: Config, store: Store, today: date, next_run: datetime) -> Page:
    days = [today - timedelta(days=offset) for offset in range(config.history_days - 1, -1, -1)]

    rows = []
    ok_today = 0
    for site in config.sites:
        outcomes = store.day_outcomes(site.name, days)
        attempts_today = store.attempts_on(site.name, today)
        latest = store.latest(site.name)

        today_outcome = outcomes.get(today)
        if site.enabled and today_outcome in OK_OUTCOMES:
            ok_today += 1

        rows.append(
            Row(
                name=site.name,
                enabled=site.enabled,
                dots=[Dot(day, outcomes.get(day)) for day in days],
                streak=_streak(store, site.name, latest),
                last_result=_last_result(site.cookie, latest),
                last_at=latest.at if latest else None,
                failed=today_outcome == FAILURE,
                attempts_today=len(attempts_today),
                has_cookie=bool(site.cookie),
            )
        )

    return Page(rows=rows, site_count=len(config.sites), ok_today=ok_today, next_run=next_run)


def _last_result(cookie: Optional[str], latest) -> str:
    if not cookie:
        return "no cookie configured"
    if latest is None:
        return "never run"
    return latest.message or latest.detail or latest.outcome


def _streak(store: Store, name: str, latest) -> Optional[int]:
    """The last streak the site told us about, even if today failed."""
    if latest is None:
        return None
    if latest.streak is not None:
        return latest.streak
    for attempt in store.recent(name, limit=30):
        if attempt.streak is not None:
            return attempt.streak
    return None
