from __future__ import annotations

import pytest

from checkin.__main__ import main

CONFIG_YAML = """
run_at: "03:20"
timezone: Asia/Shanghai
sites:
  - name: hhanclub
    url: https://hhanclub.net/attendance.php
    success: "success"
"""


@pytest.fixture
def env(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(CONFIG_YAML, encoding="utf-8")
    cookies = tmp_path / "cookies.yaml"
    cookies.write_text('hhanclub: "uid=1"\n', encoding="utf-8")
    monkeypatch.setenv("CHECKIN_CONFIG", str(config))
    monkeypatch.setenv("CHECKIN_COOKIES", str(cookies))
    monkeypatch.setenv("CHECKIN_DB", str(tmp_path / "nested" / "db.sqlite"))
    return tmp_path, config, cookies


def fake_check(result):
    def _check(_site):
        return result

    return _check


def test_env_paths_are_honoured(env, monkeypatch):
    tmp_path, _, _ = env
    from checkin.checker import CheckResult
    from checkin.store import SUCCESS

    monkeypatch.setattr("checkin.__main__.check", fake_check(CheckResult(SUCCESS, message="第264次签到", streak=1)))
    assert main(["--run-now", "hhanclub"]) == 0
    assert (tmp_path / "nested" / "db.sqlite").exists()


def test_run_now_prints_the_message(env, monkeypatch, capsys):
    from checkin.checker import CheckResult
    from checkin.store import SUCCESS

    monkeypatch.setattr("checkin.__main__.check", fake_check(CheckResult(SUCCESS, message="第264次签到", streak=1)))
    main(["--run-now", "hhanclub"])
    out = capsys.readouterr().out
    assert "hhanclub" in out and "第264次签到" in out


def test_run_now_all_sites_without_a_name(env, monkeypatch, capsys):
    from checkin.checker import CheckResult
    from checkin.store import SUCCESS

    monkeypatch.setattr("checkin.__main__.check", fake_check(CheckResult(SUCCESS, message="ok", streak=1)))
    assert main(["--run-now"]) == 0
    assert "hhanclub" in capsys.readouterr().out


def test_run_now_failure_exits_nonzero(env, monkeypatch):
    from checkin.checker import CheckResult
    from checkin.store import FAILURE

    monkeypatch.setattr(
        "checkin.__main__.check", fake_check(CheckResult(FAILURE, detail="cloudflare challenge (HTTP 403)"))
    )
    assert main(["--run-now", "hhanclub"]) == 3


def test_run_now_unknown_site_exits_nonzero(env):
    assert main(["--run-now", "ghost"]) == 2


def test_config_error_exits_nonzero_with_the_file_named(env, capsys):
    _, config, _ = env
    config.write_text("sites: [oops", encoding="utf-8")
    assert main(["--run-now"]) == 1
    assert "config.yaml" in capsys.readouterr().err
