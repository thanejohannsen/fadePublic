"""What the feed says, and what the code is allowed to conclude from it.

These exist because of a live bug that every other test missed: `final` tested only
that both point values were present, which is true from the first score of the
first quarter. A game being played was recorded as a settled bet and the published
record moved on its score.

Nothing in `fixtures/` reaches that branch -- the current-slate capture is all
`scheduled` with no boxscore at all, and the completed-week capture is all
`complete` -- so the in-progress state is built here by hand. That gap is the
reason the bug shipped, and closing it is most of the point of this file.
"""

from __future__ import annotations

import logging
import sqlite3

from fadepublic.db import init_db
from fadepublic.splits import (
    COMPLETE_STATUS,
    parse_games,
    store_results,
    store_splits,
)


def _payload(status, *, away_points=None, home_points=None):
    """One game, shaped the way the scoreboard endpoint shapes it."""
    game = {
        "status": status,
        "start_time": "2026-10-04T13:30:00.000Z",
        "num_bets": 5000,
        "away_team_id": 1,
        "home_team_id": 2,
        "teams": [{"id": 1, "abbr": "AAA"}, {"id": 2, "abbr": "BBB"}],
        "markets": {
            "15": {
                "event": {
                    "spread": [
                        {
                            "side": "home", "value": -3.5, "odds": -110,
                            "bet_info": {"tickets": {"percent": 90},
                                         "money": {"percent": 88}},
                        },
                        {
                            "side": "away", "value": 3.5, "odds": -110,
                            "bet_info": {"tickets": {"percent": 10},
                                         "money": {"percent": 12}},
                        },
                    ]
                }
            }
        },
    }
    if away_points is not None:
        game["boxscore"] = {
            "total_away_points": away_points,
            "total_home_points": home_points,
        }
    return {"games": [game]}


# ------------------------------------------------- what counts as a finished game


def test_a_game_being_played_is_not_final_even_though_it_has_a_score():
    """The regression test for the bug this file was written for.

    `boxscore.total_*_points` is a running total, so a live game carries one. The
    feed served IND @ WAS at 10-6 mid-game and it was graded as a settled bet.
    """
    (g,) = parse_games(_payload("inprogress", away_points=10, home_points=6))

    assert g.away_points == 10, "the score is still read and still available"
    assert g.final is False, "but the game is not over, so it cannot be graded"
    assert g.started is True, "and it is under way, so it is off the board"


def test_a_completed_game_is_final():
    (g,) = parse_games(_payload(COMPLETE_STATUS, away_points=30, home_points=13))

    assert g.final is True
    assert (g.away_points, g.home_points) == (30, 13)


def test_a_scheduled_game_is_neither_started_nor_final():
    (g,) = parse_games(_payload("scheduled"))

    assert g.started is False and g.final is False
    assert g.away_points is None


def test_a_completed_game_with_no_boxscore_is_not_final():
    """The status alone is not enough -- there has to be a score to grade."""
    (g,) = parse_games(_payload(COMPLETE_STATUS))

    assert g.final is False


# --------------------------------------------- an unrecognised status fails closed


def test_an_unknown_status_carrying_a_score_is_not_treated_as_final():
    """The deliberate direction of failure.

    Grading keys off one exact string, so the alternative -- treating anything not
    known to be live as finished -- would silently grade partial scores the moment
    the feed added a state like "halftime" or "delayed". That is the bug again. This
    way an unknown state costs a run's worth of grading, not the record.
    """
    (g,) = parse_games(_payload("halftime", away_points=10, home_points=6))

    assert g.final is False


def test_an_unknown_status_carrying_a_score_says_so_out_loud(caplog):
    """The other half of failing closed: if the feed ever renames "complete", the
    record would quietly stop growing. A warning is the difference between noticing
    that in a log and noticing it in a stalled tally weeks later."""
    with caplog.at_level(logging.WARNING, logger="fadepublic.splits"):
        parse_games(_payload("final", away_points=30, home_points=13))

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, warnings
    assert "unrecognised status" in warnings[0]
    assert "AAA" in warnings[0] and "'final'" in warnings[0], (
        "names the game and the status it did not recognise"
    )


def test_a_known_live_status_is_not_warned_about(caplog):
    """In-progress is expected, not anomalous. Warning on it every run would bury
    the warning that matters under one per live game per refresh."""
    with caplog.at_level(logging.WARNING, logger="fadepublic.splits"):
        parse_games(_payload("inprogress", away_points=10, home_points=6))

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_a_scheduled_game_with_no_score_is_not_warned_about(caplog):
    """The overwhelmingly common case; it must stay silent."""
    with caplog.at_level(logging.WARNING, logger="fadepublic.splits"):
        parse_games(_payload("scheduled"))

    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


# ------------------------------------------------------- what reaches the database


def test_an_in_progress_game_writes_no_result_row():
    """`store_results` filters on `final`, so the fix lands here: a live score must
    not reach `game_results`, because `settle` grades whatever it finds there."""
    c = sqlite3.connect(":memory:")
    init_db(c)
    (live,) = parse_games(_payload("inprogress", away_points=10, home_points=6))

    assert store_results(c, [live]) == 0
    assert c.execute("SELECT COUNT(*) FROM game_results").fetchone()[0] == 0


def test_a_completed_game_writes_its_result():
    c = sqlite3.connect(":memory:")
    init_db(c)
    (done,) = parse_games(_payload(COMPLETE_STATUS, away_points=30, home_points=13))

    assert store_results(c, [done]) == 1
    assert c.execute(
        "SELECT away_points, home_points FROM game_results"
    ).fetchone() == (30, 13)


def test_the_backfill_filter_excludes_a_game_still_being_played():
    """`cmd_backfill` filters on the same `final`, and there it gates two writes:
    the result *and* a `store_splits(..., is_final=True)` stamped at kickoff. On an
    in-progress game that would forge a pre-kickoff reading out of in-play betting,
    into the one table that cannot be refetched. Asserted on the filter itself,
    since that is what both call sites share.
    """
    games = parse_games(_payload("inprogress", away_points=10, home_points=6))
    games += parse_games(_payload(COMPLETE_STATUS, away_points=30, home_points=13))

    kept = [g for g in games if g.final and g.kickoff_utc is not None]

    assert len(kept) == 1
    assert kept[0].away_points == 30, "only the finished game is backfillable"


# ------------------------------------- an incomplete game has no result, actively


def _seeded(conn, away_points, home_points):
    """A result row written the way a pre-fix run wrote them: from a live score."""
    conn.execute(
        """INSERT OR REPLACE INTO game_results
               (away, home, kickoff_utc, away_points, home_points, recorded_at)
           VALUES ('AAA', 'BBB', '2026-10-04T13:30:00+00:00', ?, ?, 'seeded')""",
        (away_points, home_points),
    )
    conn.commit()


def _results(conn):
    return conn.execute(
        "SELECT away_points, home_points FROM game_results"
    ).fetchall()


def test_a_result_already_recorded_is_retracted_once_the_game_reads_in_progress():
    """Writing only was not enough.

    The fix to `final` stopped new live scores being written, but rows written
    before it survived and kept being graded -- the published record carried a win
    on a game still in its third quarter. A game the feed does not call complete
    has its result deleted, not merely skipped.
    """
    c = sqlite3.connect(":memory:")
    init_db(c)
    _seeded(c, 6, 16)
    (live,) = parse_games(_payload("inprogress", away_points=13, home_points=16))

    assert store_results(c, [live]) == 0, "nothing written for a live game"
    assert _results(c) == [], "and the stale row is gone, not left behind"


def test_a_completed_game_keeps_its_result_and_takes_a_correction():
    c = sqlite3.connect(":memory:")
    init_db(c)
    _seeded(c, 6, 16)
    (done,) = parse_games(_payload(COMPLETE_STATUS, away_points=30, home_points=13))

    assert store_results(c, [done]) == 1
    assert _results(c) == [(30, 13)], "the real final replaces the partial one"


def test_a_game_absent_from_the_payload_is_left_alone():
    """The guarantee that makes deletion safe. A completed game from an earlier week
    is not in the feed's response at all, so it must never be a candidate."""
    c = sqlite3.connect(":memory:")
    init_db(c)
    _seeded(c, 30, 13)
    other = parse_games(_payload("inprogress", away_points=3, home_points=0))
    object.__setattr__(other[0], "away", "CCC")

    store_results(c, other)

    assert _results(c) == [(30, 13)], "a result nobody asked about is untouched"


def test_retracting_a_result_keeps_the_pre_kickoff_reading():
    """The verdict is withdrawn; the evidence is not. Those readings cannot be
    refetched once the game is over, which is the whole reason records/ is tracked.
    """
    c = sqlite3.connect(":memory:")
    init_db(c)
    (live,) = parse_games(_payload("inprogress", away_points=13, home_points=16))
    store_splits(c, [live])
    _seeded(c, 6, 16)

    store_results(c, [live])

    assert _results(c) == []
    assert c.execute("SELECT COUNT(*) FROM betting_splits").fetchone()[0] > 0


def test_a_scheduled_game_with_a_stale_result_is_also_retracted():
    """A postponed or rescheduled game reads as scheduled again. It has not been
    played at that kickoff, so it has no result either."""
    c = sqlite3.connect(":memory:")
    init_db(c)
    _seeded(c, 6, 16)
    (sched,) = parse_games(_payload("scheduled"))

    store_results(c, [sched])

    assert _results(c) == []
