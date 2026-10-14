from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from checkin.checker import CheckResult
from checkin.config import load_config
from checkin.store import FAILURE, SUCCESS, Attempt, Store
from checkin.web import create_app

TZ = ZoneInfo("Asia/Shanghai")

CONFIG_YAML = """
run_at: "03:20"
timezone: Asia/Shanghai
sites:
  - name: hhanclub
    url: https://hhanclub.net/attendance.php
    success: "success"
  - name: hdfans
    url: https://hdfans.org/attendance.php
    success: "success"
  - name: ptsite4
    url: https://ptsite4.example/attendance.php
    success: "success"
"""


class FakeRunner:
    def __init__(self, config, results):
        self._config = config
        self._results = results
        self.calls = []
        self.ran_all = False

    def config(self):
        return self._config

    def next_run(self):
        return datetime.now(TZ).replace(hour=3, minute=20, second=0, microsecond=0) + timedelta(days=1)

    def run_named(self, name, force=True):
        if name not in [s.name for s in self._config.sites]:
            raise KeyError(name)
        self.calls.append((name, force))
        return self._results[name]

    def run_all(self, force=True):
        self.ran_all = True
        return dict(self._results)


@pytest.fixture
def context(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG_YAML, encoding="utf-8")
    cookies_path = tmp_path / "cookies.yaml"
    cookies_path.write_text('hhanclub: "uid=1"\nhdfans: "uid=2"\n', encoding="utf-8")
    config = load_config(config_path, cookies_path)

    store = Store(tmp_path / "d.sqlite")
    store.record(
        Attempt("hhanclub", SUCCESS, "这是您的第264次签到，已连续签到1天", 1, None, datetime.now(TZ))
    )

    runner = FakeRunner(
        config,
        {
            "hhanclub": CheckResult(SUCCESS, message="这是您的第264次签到", streak=1),
            "hdfans": CheckResult(SUCCESS, message="这是您的第1314次签到", streak=892),
            "ptsite4": CheckResult(FAILURE, detail="no cookie configured"),
        },
    )
    app = create_app(runner, store)
    app.config.update(TESTING=True)
    return app.test_client(), runner


@pytest.fixture
def client(context):
    return context[0]


@pytest.fixture
def fake_runner(context):
    return context[1]


def test_index_lists_sites_and_next_run(client):
    html = client.get("/").get_data(as_text=True)
    assert "hhanclub" in html and "hdfans" in html
    assert "03:20" in html
    assert "第264次签到" in html


def test_index_renders_never_run_sites(client):
    assert "never run" in client.get("/").get_data(as_text=True)


def test_index_shows_sites_without_a_cookie(client):
    assert "no cookie configured" in client.get("/").get_data(as_text=True)


def test_run_one_forces_a_check_and_redirects(client, fake_runner):
    resp = client.post("/run/hhanclub")
    assert resp.status_code == 302
    assert fake_runner.calls == [("hhanclub", True)]


def test_run_one_reports_the_outcome_in_a_banner(client):
    html = client.post("/run/hhanclub", follow_redirects=True).get_data(as_text=True)
    assert "hhanclub" in html and "第264次签到" in html


def test_run_one_reports_a_failure_in_the_banner(client):
    html = client.post("/run/ptsite4", follow_redirects=True).get_data(as_text=True)
    assert "no cookie configured" in html


def test_run_unknown_site_is_404(client):
    assert client.post("/run/ghost").status_code == 404


def test_run_all_runs_every_enabled_site(client, fake_runner):
    client.post("/run-all")
    assert fake_runner.ran_all is True


def test_run_all_reports_a_summary_banner(client):
    html = client.post("/run-all", follow_redirects=True).get_data(as_text=True)
    assert "3" in html


def test_healthz(client):
    assert client.get("/healthz").get_data(as_text=True) == "ok"


def test_get_on_run_is_rejected(client):
    assert client.get("/run/hhanclub").status_code == 405


def test_index_survives_a_config_error(tmp_path):
    bad = tmp_path / "config.yaml"
    bad.write_text("sites: [oops", encoding="utf-8")

    class BrokenRunner(FakeRunner):
        def config(self):
            from checkin.config import ConfigError

            raise ConfigError("%s: broken" % bad)

    store = Store(tmp_path / "d.sqlite")
    app = create_app(BrokenRunner(None, {}), store)
    app.config.update(TESTING=True)
    html = app.test_client().get("/").get_data(as_text=True)
    assert "config.yaml" in html


def _broken_app(tmp_path):
    from checkin.config import ConfigError

    class BrokenRunner(FakeRunner):
        def config(self):
            raise ConfigError("%s: broken" % (tmp_path / "config.yaml"))

        def run_named(self, name, force=True):
            raise ConfigError("%s: broken" % (tmp_path / "config.yaml"))

        def run_all(self, force=True):
            raise ConfigError("%s: broken" % (tmp_path / "config.yaml"))

    app = create_app(BrokenRunner(None, {}), Store(tmp_path / "d.sqlite"))
    app.config.update(TESTING=True)
    return app.test_client()


def test_run_one_with_a_broken_config_shows_the_problem(tmp_path):
    resp = _broken_app(tmp_path).post("/run/hhanclub", follow_redirects=True)
    assert resp.status_code == 200
    assert "config.yaml" in resp.get_data(as_text=True)


def test_run_all_with_a_broken_config_shows_the_problem(tmp_path):
    resp = _broken_app(tmp_path).post("/run-all", follow_redirects=True)
    assert resp.status_code == 200
    assert "config.yaml" in resp.get_data(as_text=True)
