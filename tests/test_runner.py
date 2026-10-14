from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from checkin.checker import CheckResult
from checkin.runner import Runner
from checkin.store import ALREADY, FAILURE, SUCCESS, Attempt, Store

TZ = ZoneInfo("Asia/Shanghai")

CONFIG_YAML = """
run_at: "03:20"
timezone: Asia/Shanghai
jitter_minutes: 20
sites:
  - name: hhanclub
    url: https://hhanclub.net/attendance.php
    success: "success"
  - name: hdfans
    url: https://hdfans.org/attendance.php
    success: "success"
    enabled: false
"""


class FakeJob:
    def __init__(self, trigger, run_date=None, kwargs=None):
        self.trigger = trigger
        self.run_date = run_date
        self.kwargs = kwargs or {}

    @property
    def delay(self):
        now = datetime.now(TZ)
        seconds = round((self.run_date - now).total_seconds() / 60.0) * 60
        return timedelta(seconds=seconds)


class FakeScheduler:
    def __init__(self):
        self.jobs = []
        self.started = False

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append(FakeJob(trigger, run_date=kwargs.get("run_date"), kwargs=kwargs))

    def start(self):
        self.started = True


@pytest.fixture
def paths(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG_YAML, encoding="utf-8")
    cookies = tmp_path / "cookies.yaml"
    cookies.write_text('hhanclub: "uid=1"\nhdfans: "uid=2"\n', encoding="utf-8")
    return config, cookies


def success_result():
    return CheckResult(SUCCESS, message="第264次签到", streak=1)


def failure_result():
    return CheckResult(FAILURE, detail="cloudflare challenge (HTTP 403)")


def build(paths, tmp_path, check_fn, scheduler=None):
    config, cookies = paths
    store = Store(tmp_path / "d.sqlite")
    scheduler = scheduler or FakeScheduler()
    runner = Runner(config, cookies, store, scheduler=scheduler, check_fn=check_fn)
    return runner, store, scheduler


def site_of(runner, name="hhanclub"):
    return next(s for s in runner.config().sites if s.name == name)


def today():
    return datetime.now(TZ).date()


def test_run_site_records_the_attempt(paths, tmp_path):
    runner, store, _ = build(paths, tmp_path, lambda s: success_result())
    runner.run_site(site_of(runner))
    assert store.latest("hhanclub").outcome == SUCCESS
    assert store.latest("hhanclub").message == "第264次签到"
    assert store.latest("hhanclub").streak == 1


def test_failure_schedules_the_15_minute_retry(paths, tmp_path):
    runner, _, sched = build(paths, tmp_path, lambda s: failure_result())
    runner.run_site(site_of(runner))
    assert [j.trigger for j in sched.jobs] == ["date"]
    assert sched.jobs[0].delay == timedelta(minutes=15)


def test_second_failure_schedules_the_one_hour_retry(paths, tmp_path):
    runner, store, sched = build(paths, tmp_path, lambda s: failure_result())
    store.record(Attempt("hhanclub", FAILURE, None, None, "boom", datetime.now(TZ)))
    runner.run_site(site_of(runner))
    assert sched.jobs[0].delay == timedelta(hours=1)


def test_third_failure_schedules_nothing(paths, tmp_path):
    runner, store, sched = build(paths, tmp_path, lambda s: failure_result())
    for _ in range(2):
        store.record(Attempt("hhanclub", FAILURE, None, None, "boom", datetime.now(TZ)))
    runner.run_site(site_of(runner))
    assert sched.jobs == []


def test_success_schedules_no_retry(paths, tmp_path):
    runner, _, sched = build(paths, tmp_path, lambda s: success_result())
    runner.run_site(site_of(runner))
    assert sched.jobs == []


def test_scheduled_run_skips_a_site_already_done_today(paths, tmp_path):
    def explode(_site):
        raise AssertionError("must not check in again")

    runner, store, _ = build(paths, tmp_path, explode)
    store.record(Attempt("hhanclub", SUCCESS, "第263次签到", 1, None, datetime.now(TZ)))
    result = runner.run_site(site_of(runner))
    assert result.outcome == SUCCESS
    assert len(store.attempts_on("hhanclub", today())) == 1


def test_scheduled_run_skips_a_site_with_three_failures_today(paths, tmp_path):
    def explode(_site):
        raise AssertionError("must not check in again")

    runner, store, _ = build(paths, tmp_path, explode)
    for _ in range(3):
        store.record(Attempt("hhanclub", FAILURE, None, None, "boom", datetime.now(TZ)))
    assert runner.run_site(site_of(runner)).outcome == FAILURE
    assert len(store.attempts_on("hhanclub", today())) == 3


def test_forced_run_hits_the_site_even_when_done_today(paths, tmp_path):
    runner, store, _ = build(paths, tmp_path, lambda s: success_result())
    store.record(Attempt("hhanclub", SUCCESS, "第263次签到", 1, None, datetime.now(TZ)))
    runner.run_site(site_of(runner), force=True)
    assert len(store.attempts_on("hhanclub", today())) == 2


def test_forced_run_schedules_no_retry(paths, tmp_path):
    runner, _, sched = build(paths, tmp_path, lambda s: failure_result())
    runner.run_site(site_of(runner), force=True)
    assert sched.jobs == []


def test_run_all_skips_disabled_sites(paths, tmp_path):
    runner, _, _ = build(paths, tmp_path, lambda s: success_result())
    assert set(runner.run_all()) == {"hhanclub"}


def test_run_all_returns_a_result_per_site(paths, tmp_path):
    runner, _, _ = build(paths, tmp_path, lambda s: success_result())
    assert runner.run_all()["hhanclub"].outcome == SUCCESS


def test_config_is_reread_from_disk(paths, tmp_path):
    config, cookies = paths
    runner, _, _ = build(paths, tmp_path, lambda s: success_result())
    before = runner.config().sites[0].cookie
    cookies.write_text('hhanclub: "uid=2"\n', encoding="utf-8")
    assert runner.config().sites[0].cookie != before


def test_start_registers_the_daily_run_and_the_prune(paths, tmp_path):
    runner, _, sched = build(paths, tmp_path, lambda s: success_result())
    runner.start()
    assert [j.trigger for j in sched.jobs].count("cron") == 2
    assert sched.started is True


def test_daily_job_schedules_one_jittered_job_per_enabled_site(paths, tmp_path):
    runner, _, sched = build(paths, tmp_path, lambda s: success_result())
    runner.run_daily()
    assert [j.trigger for j in sched.jobs] == ["date"]
    assert timedelta(0) <= sched.jobs[0].delay <= timedelta(minutes=20)


def test_next_run_is_in_the_future(paths, tmp_path):
    runner, _, _ = build(paths, tmp_path, lambda s: success_result())
    nxt = runner.next_run()
    assert nxt > datetime.now(TZ)
    assert (nxt.hour, nxt.minute) == (3, 20)


def test_prune_removes_old_attempts(paths, tmp_path):
    runner, store, _ = build(paths, tmp_path, lambda s: success_result())
    old = datetime.now(TZ) - timedelta(days=200)
    store.record(Attempt("hhanclub", SUCCESS, "old", None, None, old))
    assert runner.prune() == 1
    assert store.latest("hhanclub") is None


def test_run_named_runs_the_matching_site(paths, tmp_path):
    runner, store, _ = build(paths, tmp_path, lambda s: success_result())
    assert runner.run_named("hhanclub").outcome == SUCCESS
    assert store.latest("hhanclub") is not None


def test_run_named_unknown_site_is_a_key_error(paths, tmp_path):
    runner, _, _ = build(paths, tmp_path, lambda s: success_result())
    with pytest.raises(KeyError):
        runner.run_named("ghost")
