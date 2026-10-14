"""The one page, plus the two buttons that fire a check-in now.

No authentication by design: this belongs on a LAN. The buttons are plain
form posts, so the page needs no JavaScript.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, redirect, render_template, url_for

from .config import ConfigError
from .store import FAILURE, Store
from .view import build_page

log = logging.getLogger("checkin")


def create_app(runner, store: Store) -> Flask:
    app = Flask(__name__)
    # Only used to sign the flash cookie that carries the banner.
    app.secret_key = os.environ.get("CHECKIN_SECRET", os.urandom(16).hex())

    @app.get("/")
    def index():
        try:
            config = runner.config()
        except ConfigError as exc:
            return render_template("error.html", message=str(exc)), 200

        tz = ZoneInfo(config.timezone)
        now = datetime.now(tz)
        next_run = runner.next_run()
        page = build_page(config, store, now.date(), next_run)
        return render_template("status.html", page=page, now=now, countdown=_countdown(next_run - now))

    @app.post("/run/<name>")
    def run_one(name):
        try:
            result = runner.run_named(name, force=True)
        except KeyError:
            abort(404)
        flash("%s — %s" % (name, result.message or result.detail or result.outcome),
              "error" if result.outcome == FAILURE else "ok")
        return redirect(url_for("index"))

    @app.post("/run-all")
    def run_all():
        results = runner.run_all(force=True)
        failed = [name for name, result in results.items() if result.outcome == FAILURE]
        if failed:
            flash("ran %d sites, %d failed: %s" % (len(results), len(failed), ", ".join(failed)), "error")
        else:
            flash("ran %d sites, all fine" % len(results), "ok")
        return redirect(url_for("index"))

    @app.get("/healthz")
    def healthz():
        return "ok"

    return app


def _countdown(delta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return "in %dh %dm" % (hours, minutes)
    return "in %dm" % minutes
