"""Entrypoint: scheduler plus status page, or one check from the shell.

    python -m checkin                     # scheduler + page
    python -m checkin --run-now hhanclub  # one forced check, printed
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .checker import check
from .config import ConfigError
from .runner import Runner
from .store import FAILURE, Store
from .web import create_app

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_UNKNOWN_SITE = 2
EXIT_CHECK_FAILED = 3


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    _setup_logging()

    config_path = Path(os.environ.get("CHECKIN_CONFIG", "/config/config.yaml"))
    cookies_path = Path(os.environ.get("CHECKIN_COOKIES", "/config/cookies.yaml"))
    db_path = Path(os.environ.get("CHECKIN_DB", "/data/checkin.sqlite"))

    store = Store(db_path)
    runner = Runner(config_path, cookies_path, store, check_fn=check)

    try:
        runner.config()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG

    if args.run_now is not None:
        return _run_now(runner, args.run_now)

    runner.start()
    app = create_app(runner, store)
    host = os.environ.get("CHECKIN_HOST", "0.0.0.0")
    port = int(os.environ.get("CHECKIN_PORT", "8080"))
    logging.getLogger("checkin").info("status page on http://%s:%d", host, port)
    app.run(host=host, port=port, threaded=True, use_reloader=False)
    return EXIT_OK


def _run_now(runner: Runner, name: str) -> int:
    if name:
        try:
            results = {name: runner.run_named(name, force=True)}
        except KeyError:
            print("no site named %r in the config" % name, file=sys.stderr)
            return EXIT_UNKNOWN_SITE
    else:
        results = runner.run_all(force=True)

    worst = EXIT_OK
    for site_name, result in results.items():
        print("%s: %s — %s" % (site_name, result.outcome, result.message or result.detail or ""))
        if result.outcome == FAILURE:
            worst = EXIT_CHECK_FAILED
    return worst


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="checkin", description=__doc__)
    parser.add_argument(
        "--run-now",
        nargs="?",
        const="",
        default=None,
        metavar="SITE",
        help="check in once, right now, for SITE (or every enabled site), then exit",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
