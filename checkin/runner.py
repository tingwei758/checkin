"""The thing that actually checks in, on a schedule.

One daily cron job spreads the sites across a jitter window; each site's
failures earn two retries and then the day is over. Config and cookies are
re-read from disk on every run, so replacing an expired cookie needs no
restart.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional
from zoneinfo import ZoneInfo

from .checker import CheckResult, check
from .config import Config, Site, load_config
from .schedule import jitter_seconds, next_run_time, retry_delay, should_attempt
from .store import FAILURE, Attempt, Store

log = logging.getLogger("checkin")


class Runner:
    def __init__(
        self,
        config_path: Path,
        cookies_path: Path,
        store: Store,
        scheduler=None,
        check_fn: Callable[[Site], CheckResult] = check,
    ):
        self.config_path = Path(config_path)
        self.cookies_path = Path(cookies_path)
        self.store = store
        self.check_fn = check_fn
        self._scheduler = scheduler if scheduler is not None else _background_scheduler()

    def config(self) -> Config:
        return load_config(self.config_path, self.cookies_path)

    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.config().timezone)

    def now(self) -> datetime:
        return datetime.now(self.tz())

    def next_run(self) -> datetime:
        config = self.config()
        tz = ZoneInfo(config.timezone)
        return next_run_time(datetime.now(tz), config.run_at, tz)

    def run_site(self, site: Site, *, force: bool = False) -> CheckResult:
        now = self.now()
        attempts = self.store.attempts_on(site.name, now.date())

        if not force and not should_attempt(attempts):
            last = attempts[-1]
            log.info("%s: skipped, already %s today", site.name, last.outcome)
            return CheckResult(last.outcome, message=last.message, streak=last.streak, detail=last.detail)

        result = self.check_fn(site)
        attempt_number = len(attempts) + 1
        self.store.record(
            Attempt(
                site=site.name,
                outcome=result.outcome,
                message=result.message,
                streak=result.streak,
                detail=result.detail,
                at=now,
            )
        )
        log.info(
            "%s: %s (attempt %d) %s",
            site.name,
            result.outcome,
            attempt_number,
            result.message or result.detail or "",
        )

        if not force and result.outcome == FAILURE:
            self._schedule_retry(site, attempt_number, now)

        return result

    def run_named(self, name: str, *, force: bool = True) -> CheckResult:
        for site in self.config().sites:
            if site.name == name:
                return self.run_site(site, force=force)
        raise KeyError(name)

    def run_all(self, *, force: bool = False) -> Dict[str, CheckResult]:
        return {
            site.name: self.run_site(site, force=force)
            for site in self.config().sites
            if site.enabled
        }

    def run_daily(self) -> None:
        """Spread today's check-ins across the jitter window."""
        config = self.config()
        now = self.now()
        for site in config.sites:
            if not site.enabled:
                continue
            delay = jitter_seconds(site.name, now.date(), config.jitter_minutes)
            run_date = now + _seconds(delay)
            log.info("%s: scheduled for %s", site.name, run_date.isoformat(timespec="seconds"))
            self._scheduler.add_job(
                _SiteJob(self, site.name),
                "date",
                run_date=run_date,
                id="checkin-%s-%s" % (site.name, now.date().isoformat()),
                replace_existing=True,
            )

    def prune(self) -> int:
        config = self.config()
        removed = self.store.prune(config.retention_days, self.now().date())
        if removed:
            log.info("pruned %d attempt(s) older than %d days", removed, config.retention_days)
        return removed

    def start(self) -> None:
        config = self.config()
        tz = ZoneInfo(config.timezone)
        self._scheduler.add_job(
            self.run_daily,
            "cron",
            hour=config.run_at.hour,
            minute=config.run_at.minute,
            timezone=tz,
            id="checkin-daily",
            replace_existing=True,
            # A missed 03:20 is skipped, never caught up.
            coalesce=True,
            misfire_grace_time=300,
        )
        self._scheduler.add_job(
            self.prune,
            "cron",
            hour=4,
            minute=0,
            timezone=tz,
            id="checkin-prune",
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=300,
        )
        self._scheduler.start()
        log.info("next run at %s", self.next_run().isoformat(timespec="seconds"))

    def _schedule_retry(self, site: Site, attempt_number: int, now: datetime) -> None:
        delay = retry_delay(attempt_number)
        if delay is None:
            log.info("%s: out of retries for today", site.name)
            return
        run_date = now + delay
        log.info("%s: retrying at %s", site.name, run_date.isoformat(timespec="seconds"))
        self._scheduler.add_job(
            _SiteJob(self, site.name),
            "date",
            run_date=run_date,
            id="retry-%s-%s" % (site.name, run_date.isoformat(timespec="seconds")),
            replace_existing=True,
        )


class _SiteJob:
    """A picklable, re-reading job: looks the site up again when it fires."""

    def __init__(self, runner: Runner, name: str):
        self.runner = runner
        self.name = name

    def __call__(self) -> Optional[CheckResult]:
        try:
            return self.runner.run_named(self.name, force=False)
        except KeyError:
            log.warning("%s: no longer configured, job dropped", self.name)
            return None
        except Exception:  # noqa: BLE001 - a scheduled job must not take the process down
            log.exception("%s: job failed", self.name)
            return None


def _seconds(count: int):
    from datetime import timedelta

    return timedelta(seconds=count)


def _background_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    return BackgroundScheduler()
