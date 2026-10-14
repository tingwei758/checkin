"""Every check-in attempt, one row each, in SQLite.

The page's dots, streaks and attempt counts are queries over this table
rather than counters kept up to date by hand. Each method opens its own
short-lived connection: the scheduler thread and the Flask thread both
write, and sqlite3 connections are not safe to share across threads.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence

SUCCESS = "success"
ALREADY = "already"
FAILURE = "failure"

#: Best-first, for picking one outcome to represent a day.
OUTCOME_RANK = {SUCCESS: 0, ALREADY: 1, FAILURE: 2}

SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    site TEXT NOT NULL,
    outcome TEXT NOT NULL,
    message TEXT,
    streak INTEGER,
    detail TEXT,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_site_at ON attempts (site, at);
"""


@dataclass(frozen=True)
class Attempt:
    site: str
    outcome: str
    message: Optional[str]
    streak: Optional[int]
    detail: Optional[str]
    at: datetime


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def record(self, attempt: Attempt) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO attempts (site, outcome, message, streak, detail, at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    attempt.site,
                    attempt.outcome,
                    attempt.message,
                    attempt.streak,
                    attempt.detail,
                    attempt.at.isoformat(),
                ),
            )

    def attempts_on(self, site: str, day: date) -> List[Attempt]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT site, outcome, message, streak, detail, at FROM attempts"
                " WHERE site = ? AND at LIKE ? ORDER BY at",
                (site, day.isoformat() + "%"),
            ).fetchall()
        return [_row_to_attempt(row) for row in rows]

    def latest(self, site: str) -> Optional[Attempt]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT site, outcome, message, streak, detail, at FROM attempts"
                " WHERE site = ? ORDER BY at DESC, id DESC LIMIT 1",
                (site,),
            ).fetchone()
        return _row_to_attempt(row) if row else None

    def day_outcomes(self, site: str, days: Sequence[date]) -> Dict[date, str]:
        if not days:
            return {}
        best: Dict[date, str] = {}
        wanted = set(days)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT outcome, at FROM attempts WHERE site = ? AND at >= ? AND at < ?",
                (site, min(wanted).isoformat(), _day_after(max(wanted))),
            ).fetchall()
        for outcome, at_text in rows:
            day = date.fromisoformat(at_text[:10])
            if day not in wanted:
                continue
            current = best.get(day)
            if current is None or OUTCOME_RANK.get(outcome, 99) < OUTCOME_RANK.get(current, 99):
                best[day] = outcome
        return best

    def prune(self, keep_days: int, today: date) -> int:
        cutoff = today.toordinal() - keep_days
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM attempts WHERE at < ?",
                (date.fromordinal(cutoff).isoformat(),),
            )
            return cursor.rowcount

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def _row_to_attempt(row) -> Attempt:
    site, outcome, message, streak, detail, at_text = row
    return Attempt(
        site=site,
        outcome=outcome,
        message=message,
        streak=streak,
        detail=detail,
        at=datetime.fromisoformat(at_text),
    )


def _day_after(day: date) -> str:
    return date.fromordinal(day.toordinal() + 1).isoformat()
