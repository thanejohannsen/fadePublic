"""Two tables: what the public looked like, and how the games finished.

The database is a working cache in one direction only. ``game_results`` can be
refetched from the feed at any time, and the current board is rebuilt from a
live fetch on every run. ``betting_splits`` is the exception: a *pre-kickoff*
ticket count cannot be recovered once the game is over, because a finished week
serves only its closing tally.

So the rows that decided a settled bet are mirrored into ``records/fade_log.json``,
which is committed. ``data/`` is gitignored and the scheduled job restores it
from a cache that gets evicted; the archive is the copy that lasts. See
``record.py`` for the load and save path.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;

-- What the betting public looked like at each refresh, one row per quoted side.
--
-- Append-only and keyed by fetch time, because the record is graded straight
-- off it: for each finished game the last snapshot at or before kickoff decides
-- whether the bet was on. That is what keeps the record honest -- it can only
-- ever use what was observable before the game -- and it is also why a game
-- that fell below the threshold during the week is simply absent from its own
-- gameday snapshot, with no bookkeeping needed to exclude it.
CREATE TABLE IF NOT EXISTS betting_splits (
    fetched_at  TEXT NOT NULL,
    kickoff_utc TEXT,
    away        TEXT NOT NULL,
    home        TEXT NOT NULL,
    market      TEXT NOT NULL,   -- 'spread' | 'total' | 'moneyline'
    side        TEXT NOT NULL,   -- home/away, or over/under
    line        REAL,
    odds        INTEGER,
    tickets_pct INTEGER NOT NULL,
    money_pct   INTEGER,
    num_bets    INTEGER,
    -- 1 for rows backfilled from a completed week, whose percentages are the
    -- closing tally rather than a pre-kickoff reading. Graded the same way, but
    -- the page says how many of the record came in on that basis.
    is_final    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (fetched_at, away, home, market, side)
);
CREATE INDEX IF NOT EXISTS idx_splits_game
    ON betting_splits(away, home, kickoff_utc, fetched_at DESC);

-- Final scores, so a bet taken from the splits above can be graded. Written
-- whenever the feed shows a game complete; the same payload carries the
-- boxscore, so this needs no second source.
CREATE TABLE IF NOT EXISTS game_results (
    away         TEXT NOT NULL,
    home         TEXT NOT NULL,
    kickoff_utc  TEXT NOT NULL,
    away_points  INTEGER NOT NULL,
    home_points  INTEGER NOT NULL,
    recorded_at  TEXT NOT NULL,
    PRIMARY KEY (away, home, kickoff_utc)
);
"""


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def open_db(path: Path | str):
    """A connection with the schema applied, closed on the way out."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()
