"""Loading the site list and the cookies that go with it.

Two files on purpose: `config.yaml` is the site list you edit rarely,
`cookies.yaml` is the small file you edit when a session expires.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

DEFAULT_RUN_AT = time(3, 20)
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_JITTER_MINUTES = 20
DEFAULT_RETENTION_DAYS = 90
DEFAULT_HISTORY_DAYS = 7
DEFAULT_IMPERSONATE = "chrome"


class ConfigError(Exception):
    """A configuration file is missing something or says something impossible."""


@dataclass(frozen=True)
class Site:
    name: str
    url: str
    success: str
    already: Optional[str] = None
    streak: Optional[str] = None
    impersonate: str = DEFAULT_IMPERSONATE
    headers: Dict[str, str] = field(default_factory=dict)
    cookie: Optional[str] = None
    enabled: bool = True


@dataclass(frozen=True)
class Config:
    sites: Tuple[Site, ...]
    run_at: time = DEFAULT_RUN_AT
    jitter_minutes: int = DEFAULT_JITTER_MINUTES
    timezone: str = DEFAULT_TIMEZONE
    retention_days: int = DEFAULT_RETENTION_DAYS
    history_days: int = DEFAULT_HISTORY_DAYS


def load_config(config_path: Path, cookies_path: Path) -> Config:
    raw = _load_yaml(Path(config_path), required=True)
    cookies = _load_cookies(Path(cookies_path))

    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError("%s: `defaults` must be a mapping" % config_path)

    sites_raw = raw.get("sites")
    if not sites_raw:
        raise ConfigError("%s: no sites configured" % config_path)
    if not isinstance(sites_raw, list):
        raise ConfigError("%s: `sites` must be a list" % config_path)

    sites = []
    seen = set()
    for entry in sites_raw:
        site = _build_site(config_path, entry, defaults, cookies)
        if site.name in seen:
            raise ConfigError("%s: duplicate site name %r" % (config_path, site.name))
        seen.add(site.name)
        sites.append(site)

    return Config(
        sites=tuple(sites),
        run_at=_parse_run_at(config_path, raw.get("run_at")),
        jitter_minutes=_positive_int(config_path, raw, "jitter_minutes", DEFAULT_JITTER_MINUTES),
        timezone=raw.get("timezone") or DEFAULT_TIMEZONE,
        retention_days=_positive_int(config_path, raw, "retention_days", DEFAULT_RETENTION_DAYS),
        history_days=_positive_int(config_path, raw, "history_days", DEFAULT_HISTORY_DAYS),
    )


def _load_yaml(path: Path, required: bool) -> Dict[str, Any]:
    if not path.exists():
        if required:
            raise ConfigError("%s: file not found" % path)
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError("%s: %s" % (path, exc)) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("%s: expected a mapping at the top level" % path)
    return data


def _load_cookies(path: Path) -> Dict[str, str]:
    data = _load_yaml(path, required=False)
    cookies = {}
    for name, value in data.items():
        if not isinstance(value, str):
            raise ConfigError("%s: cookie for %r must be a string" % (path, name))
        cookies[str(name)] = value.strip()
    return cookies


def _build_site(
    config_path: Path,
    entry: Any,
    defaults: Dict[str, Any],
    cookies: Dict[str, str],
) -> Site:
    if not isinstance(entry, dict):
        raise ConfigError("%s: each site must be a mapping, got %r" % (config_path, entry))

    name = entry.get("name")
    if not name:
        raise ConfigError("%s: a site is missing `name`" % config_path)

    merged = dict(defaults)
    merged.update(entry)

    for required in ("url", "success"):
        if not merged.get(required):
            raise ConfigError("%s: site %r is missing `%s`" % (config_path, name, required))

    for pattern_field in ("success", "already", "streak"):
        pattern = merged.get(pattern_field)
        if pattern is None:
            continue
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ConfigError(
                "%s: site %r has an invalid `%s` pattern: %s" % (config_path, name, pattern_field, exc)
            ) from exc
        if pattern_field == "streak" and compiled.groups != 1:
            raise ConfigError(
                "%s: site %r `streak` must have exactly one capture group, found %d"
                % (config_path, name, compiled.groups)
            )

    headers = merged.get("headers") or {}
    if not isinstance(headers, dict):
        raise ConfigError("%s: site %r `headers` must be a mapping" % (config_path, name))
    headers = {str(k): str(v) for k, v in headers.items()}

    cookie = cookies.get(str(name)) or None
    if cookie:
        headers["Cookie"] = cookie

    return Site(
        name=str(name),
        url=str(merged["url"]),
        success=str(merged["success"]),
        already=_optional_str(merged.get("already")),
        streak=_optional_str(merged.get("streak")),
        impersonate=str(merged.get("impersonate") or DEFAULT_IMPERSONATE),
        headers=headers,
        cookie=cookie,
        enabled=bool(merged.get("enabled", True)),
    )


def _optional_str(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _parse_run_at(config_path: Path, value: Any) -> time:
    if value is None:
        return DEFAULT_RUN_AT
    if isinstance(value, time):
        return value
    text = str(value).strip()
    try:
        hour, minute = (int(part) for part in text.split(":", 1))
        return time(hour, minute)
    except ValueError as exc:
        raise ConfigError("%s: `run_at` must look like \"03:20\", got %r" % (config_path, value)) from exc


def _positive_int(config_path: Path, raw: Dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key)
    if value is None:
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("%s: `%s` must be a whole number, got %r" % (config_path, key, value)) from exc
    if number < 0:
        raise ConfigError("%s: `%s` must not be negative" % (config_path, key))
    return number
