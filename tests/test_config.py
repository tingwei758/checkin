from __future__ import annotations

from datetime import time

import pytest

from checkin.config import ConfigError, load_config

CONFIG_YAML = """
run_at: "03:20"
timezone: Asia/Shanghai
jitter_minutes: 20
retention_days: 90
history_days: 7
defaults:
  impersonate: chrome
sites:
  - name: hhanclub
    url: https://hhanclub.net/attendance.php
    success: "success"
    already: "already"
    streak: "streak (\\\\d+)"
  - name: hdfans
    url: https://hdfans.org/attendance.php
    success: "success"
"""


def write(tmp_path, text, name="config.yaml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def write_cookies(tmp_path, text):
    return write(tmp_path, text, name="cookies.yaml")


def test_loads_sites_with_cookies(tmp_path):
    cfg = load_config(write(tmp_path, CONFIG_YAML), write_cookies(tmp_path, 'hhanclub: "uid=1"'))
    assert [s.name for s in cfg.sites] == ["hhanclub", "hdfans"]
    assert cfg.sites[0].headers["Cookie"] == "uid=1"
    assert cfg.run_at == time(3, 20)
    assert cfg.jitter_minutes == 20
    assert cfg.timezone == "Asia/Shanghai"
    assert cfg.retention_days == 90
    assert cfg.history_days == 7


def test_site_without_cookie_has_none(tmp_path):
    cfg = load_config(write(tmp_path, CONFIG_YAML), write_cookies(tmp_path, 'hhanclub: "uid=1"'))
    hdfans = cfg.sites[1]
    assert hdfans.cookie is None
    assert "Cookie" not in hdfans.headers


def test_defaults_applied_and_overridden(tmp_path):
    config = CONFIG_YAML.replace(
        "    url: https://hdfans.org/attendance.php",
        "    url: https://hdfans.org/attendance.php\n    impersonate: chrome120",
    )
    cfg = load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert cfg.sites[0].impersonate == "chrome"
    assert cfg.sites[1].impersonate == "chrome120"


def test_enabled_defaults_true_and_can_be_disabled(tmp_path):
    config = CONFIG_YAML.replace(
        "    url: https://hdfans.org/attendance.php",
        "    url: https://hdfans.org/attendance.php\n    enabled: false",
    )
    cfg = load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert cfg.sites[0].enabled is True
    assert cfg.sites[1].enabled is False


def test_extra_headers_merge_with_cookie(tmp_path):
    config = CONFIG_YAML.replace(
        "    url: https://hhanclub.net/attendance.php",
        '    url: https://hhanclub.net/attendance.php\n    headers:\n      User-Agent: "Mozilla/5.0 (custom)"',
    )
    cfg = load_config(write(tmp_path, config), write_cookies(tmp_path, 'hhanclub: "uid=1"'))
    assert cfg.sites[0].headers["User-Agent"] == "Mozilla/5.0 (custom)"
    assert cfg.sites[0].headers["Cookie"] == "uid=1"


def test_malformed_yaml_names_the_file(tmp_path):
    bad = write(tmp_path, "sites: [oops")
    with pytest.raises(ConfigError) as e:
        load_config(bad, write_cookies(tmp_path, ""))
    assert "config.yaml" in str(e.value)


def test_malformed_cookies_yaml_names_the_cookies_file(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(write(tmp_path, CONFIG_YAML), write_cookies(tmp_path, "hhanclub: [oops"))
    assert "cookies.yaml" in str(e.value)


def test_missing_required_field_names_site_and_field(tmp_path):
    config = CONFIG_YAML.replace("    url: https://hhanclub.net/attendance.php\n", "")
    with pytest.raises(ConfigError) as e:
        load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert "hhanclub" in str(e.value) and "url" in str(e.value)


def test_invalid_regex_is_a_config_error(tmp_path):
    config = CONFIG_YAML.replace('    success: "success"\n    already', '    success: "("\n    already')
    with pytest.raises(ConfigError) as e:
        load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert "success" in str(e.value)


def test_streak_without_a_capture_group_is_a_config_error(tmp_path):
    config = CONFIG_YAML.replace('    streak: "streak (\\\\d+)"', '    streak: "streak \\\\d+"')
    with pytest.raises(ConfigError) as e:
        load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert "streak" in str(e.value)


def test_cookie_for_unknown_site_is_ignored(tmp_path):
    cfg = load_config(write(tmp_path, CONFIG_YAML), write_cookies(tmp_path, 'ghost: "uid=1"'))
    assert "ghost" not in [s.name for s in cfg.sites]


def test_missing_cookies_file_is_not_an_error(tmp_path):
    cfg = load_config(write(tmp_path, CONFIG_YAML), tmp_path / "absent.yaml")
    assert all(s.cookie is None for s in cfg.sites)


def test_duplicate_site_names_rejected(tmp_path):
    config = CONFIG_YAML.replace("  - name: hdfans", "  - name: hhanclub")
    with pytest.raises(ConfigError) as e:
        load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert "hhanclub" in str(e.value)


def test_no_sites_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, "sites: []"), write_cookies(tmp_path, ""))


def test_schedule_defaults_when_omitted(tmp_path):
    config = """
sites:
  - name: hhanclub
    url: https://hhanclub.net/attendance.php
    success: "success"
"""
    cfg = load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert cfg.run_at == time(3, 20)
    assert cfg.timezone == "Asia/Shanghai"
    assert cfg.jitter_minutes == 20
    assert cfg.retention_days == 90
    assert cfg.history_days == 7


def test_bad_run_at_is_a_config_error(tmp_path):
    config = CONFIG_YAML.replace('run_at: "03:20"', 'run_at: "tea time"')
    with pytest.raises(ConfigError) as e:
        load_config(write(tmp_path, config), write_cookies(tmp_path, ""))
    assert "run_at" in str(e.value)


def test_example_config_loads(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    cfg = load_config(root / "config" / "config.example.yaml", root / "config" / "cookies.example.yaml")
    assert ["hhanclub", "hdfans"] == [s.name for s in cfg.sites][:2]
    assert cfg.sites[0].cookie is not None
    assert all(s.url.startswith("https://") and s.success for s in cfg.sites)
