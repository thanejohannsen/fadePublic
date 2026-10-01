"""Grading the contrarian rule against what was visible before kickoff.

The record is derived from stored snapshots rather than accumulated, so these
tests are really about *which reading decides*. Three boundaries carry the
whole design: a reading after kickoff must never count, a reading too far
before kickoff is not gameday evidence, and the reading that does count is the
last one before the game -- which is what makes "it fell off the board during
the week" enforce itself with no bookkeeping.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from fadepublic.db import init_db
from fadepublic.fades import find_fades
from fadepublic.record import LOCK_LEAD, MAX_STALENESS, save_log, settle, tally
from fadepublic.splits import (
    GameSplits,
    Side,
    parse_games,
    store_results,
    store_splits,
)

KICK = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    init_db(c)
    yield c
    c.close()


def _snapshot(conn, at, *, home_tickets=90, away=None, home=None, line=-3.5, kickoff=KICK):
    """One reading of one spread, with the home side carrying the tickets."""
    game = GameSplits(
        away=away or "AAA",
        home=home or "BBB",
        kickoff_utc=kickoff,
        status="scheduled",
        num_bets=5000,
        sides={
            ("spread", "home"): Side("spread", "home", line, -110, home_tickets, 88),
            ("spread", "away"): Side("spread", "away", -line, -110, 100 - home_tickets, 12),
        },
    )
    store_splits(conn, [game], fetched_at=at)


def _result(conn, away_points, home_points, away="AAA", home="BBB", kickoff=KICK):
    store_results(
        conn,
        [
            GameSplits(
                away=away, home=home, kickoff_utc=kickoff, status="complete",
                num_bets=0, away_points=away_points, home_points=home_points,
            )
        ],
    )


# ------------------------------------------------- which reading decides


def test_a_game_that_fell_off_the_board_is_never_counted():
    """The point of grading on the gameday reading.

    Lopsided on Tuesday, level by Sunday: the bet was not on the board when it
    mattered, so it must not turn up in the record either way.
    """
    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - timedelta(days=3), home_tickets=90)
    _snapshot(c, KICK - timedelta(minutes=30), home_tickets=55)
    _result(c, 30, 20)

    assert settle(c) == []


def test_a_game_that_only_qualifies_late_is_counted():
    """And the converse, so the test above cannot pass by grading nothing."""
    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - timedelta(days=3), home_tickets=55)
    _snapshot(c, KICK - timedelta(minutes=30), home_tickets=90)
    _result(c, 30, 20)

    (s,) = settle(c)
    assert s.fade.public.tickets == 90
    assert s.observed_at == KICK - timedelta(minutes=30)


def test_a_reading_taken_after_kickoff_never_decides(conn):
    """Once the game is under way the tickets include people betting it live,
    which is not the public the rule is about."""
    _snapshot(conn, KICK - timedelta(minutes=30), home_tickets=55)
    _snapshot(conn, KICK + timedelta(hours=1), home_tickets=95)
    _result(conn, 30, 20)

    assert settle(conn) == []


# ----------------------------------------------------------- staleness


@pytest.mark.parametrize(
    "lead, graded",
    [
        (timedelta(hours=3), True),
        (MAX_STALENESS, True),
        (MAX_STALENESS + timedelta(minutes=1), False),
        (timedelta(hours=13), False),
    ],
)
def test_a_reading_too_far_from_kickoff_is_not_gameday_evidence(lead, graded):
    """The scheduler drops runs, so the nearest reading can be hours old. Past
    the limit it says nothing about gameday and the bet is dropped rather than
    graded on a guess -- the boundary itself is asserted, since an off-by-one
    here silently changes how much of the record exists."""
    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - lead, home_tickets=90)
    _result(c, 30, 20)

    assert bool(settle(c)) is graded


@pytest.mark.parametrize(
    "lead, confirmed",
    [
        (timedelta(minutes=45), True),
        (LOCK_LEAD, True),
        (LOCK_LEAD + timedelta(minutes=1), False),
        (timedelta(hours=6), False),
    ],
)
def test_a_reading_outside_the_lock_window_still_grades_but_says_so(lead, confirmed):
    """The replacement for dropping everything past one bound.

    A bet decided forty minutes out and a bet decided six hours out are both real
    bets on a real price, so both are graded -- but they are not equally good
    evidence that the public was still on that side at kickoff, and the earlier
    rule threw the second away rather than say which it had. The boundary is
    asserted symbolically: it decides what the page claims, not just how much of
    the record exists.
    """
    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - lead, home_tickets=90)
    _result(c, 30, 20)

    (s,) = settle(c)
    assert s.confirmed is confirmed
    assert s.lead_time == lead, "and the row remembers how far out it was"
    assert tally([s]).outside_lock == (0 if confirmed else 1)


def test_the_lock_window_the_grader_used_is_the_one_reported():
    """``confirmed`` is stamped by ``settle``, not recomputed from the module
    constant. A configured window that disagreed with the flag on the row would
    make the page's "N decided more than 2h out" sentence a lie about its own
    record."""
    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - timedelta(hours=3), home_tickets=90)
    _result(c, 30, 20)

    (tight,) = settle(c, lock_lead=timedelta(hours=1))
    (loose,) = settle(c, lock_lead=timedelta(hours=4))
    assert tight.confirmed is False
    assert loose.confirmed is True, "the passed window decides, not LOCK_LEAD"


# ------------------------------------------------------------- grading


def test_the_unpopular_side_covering_is_a_win(conn):
    """Public on the home team -3.5; we take away +3.5 and they lose by 3."""
    _snapshot(conn, KICK - timedelta(minutes=30), home_tickets=90, line=-3.5)
    _result(conn, 20, 23)

    (s,) = settle(conn)
    assert s.fade.line_label == "AAA +3.5"
    assert s.result == "win"


def test_the_unpopular_side_failing_to_cover_is_a_loss(conn):
    _snapshot(conn, KICK - timedelta(minutes=30), home_tickets=90, line=-3.5)
    _result(conn, 20, 30)

    (s,) = settle(conn)
    assert s.result == "loss"


def test_a_spread_landing_on_the_number_is_a_push_and_not_a_decision(conn):
    """A push returns the stake, so it belongs in the log but not in the win
    rate -- counting it either way would misstate the record."""
    _snapshot(conn, KICK - timedelta(minutes=30), home_tickets=90, line=-3.0)
    _result(conn, 20, 23)

    (s,) = settle(conn)
    assert s.result == "push"

    r = tally([s])
    assert (r.wins, r.losses, r.pushes) == (0, 0, 1)
    assert r.decided == 0 and r.win_rate is None
    assert r.units == 0


def test_a_total_is_graded_on_the_combined_score(conn):
    game = GameSplits(
        away="AAA", home="BBB", kickoff_utc=KICK, status="scheduled", num_bets=5000,
        sides={
            ("total", "under"): Side("total", "under", 47.5, -110, 93, 95),
            ("total", "over"): Side("total", "over", 47.5, -110, 7, 5),
        },
    )
    store_splits(conn, [game], fetched_at=KICK - timedelta(minutes=30))
    _result(conn, 30, 24)  # 54, over 47.5

    (s,) = settle(conn)
    assert s.fade.line_label == "over 47.5"
    assert s.result == "win"


# ----------------------------------------------- the real week, end to end


@pytest.fixture
def week3(conn):
    """Week 3 of 2026, stored the way `fl fades-backfill` stores it."""
    path = pathlib.Path(__file__).parent.parent / "fixtures" / "action_network_w3.json"
    games = [g for g in parse_games(json.loads(path.read_text())) if g.final]
    for g in games:
        store_splits(conn, [g], fetched_at=g.kickoff_utc, is_final=True)
    store_results(conn, games)
    return conn


def test_week_three_reproduces_the_bets_the_rule_actually_made(week3):
    """The one test that pins the rule to a known-good outcome.

    These four are the bets the strategy this board implements made in week 3,
    reported independently of this code. If a future change to the threshold,
    the market filter, or the qualification test quietly alters what gets
    selected, nothing else here would notice -- the live board has no right
    answer to compare against, but this week does.
    """
    settled = settle(week3)
    assert {(s.game, s.fade.line_label) for s in settled} == {
        ("KC @ MIA", "MIA +9.5"),
        ("SEA @ WAS", "WAS +8.5"),
        ("ARI @ SF", "ARI +7.5"),
        ("BAL @ DAL", "over 54.5"),
    }

    r = tally(settled)
    assert (r.wins, r.losses) == (3, 1)
    assert {s.game for s in settled if s.result == "loss"} == {"KC @ MIA"}


def test_a_backfilled_week_is_marked_as_such(week3):
    """The record merges both bases into one number, so the page can only be
    honest about it if the rows remember which they are."""
    settled = settle(week3)
    assert tally(settled).from_final_tally == len(settled) == 4


def test_no_moneyline_reaches_the_record(week3):
    """Week 3 had moneylines at 98% on two games. They are excluded from the
    board by design, and the record must not quietly readmit them."""
    assert all(s.fade.market != "moneyline" for s in settle(week3))


# ------------------------------------------------- surviving a lost cache


def test_a_cold_database_grades_the_same_record_from_the_log(week3, tmp_path):
    """The bug this file exists to prevent.

    The record lived only in `data/`, which is gitignored and restored from a
    cache. A scheduled run regenerated the page from a database that had never
    seen the backfill, found nothing settled, and published an empty record --
    correctly, because the data was not there. The archive is the copy that
    survives, so a database with nothing in it must grade identically.
    """
    from fadepublic.record import load_log, save_log

    path = tmp_path / "fade_log.json"
    save_log(week3, path)
    before = settle(week3)

    cold = sqlite3.connect(":memory:")
    init_db(cold)
    assert settle(cold) == [], "the failure mode: nothing to grade"

    load_log(cold, path)
    after = settle(cold)
    assert [(s.game, s.fade.line_label, s.result) for s in after] == [
        (s.game, s.fade.line_label, s.result) for s in before
    ]
    assert tally(after).label == tally(before).label == "3-1"


def test_the_log_carries_which_rows_were_closing_counts(week3, tmp_path):
    """Lose this and the page starts claiming a pre-kickoff reading it never
    had -- the one thing the record must not overstate."""
    from fadepublic.record import load_log, save_log

    path = tmp_path / "fade_log.json"
    save_log(week3, path)

    cold = sqlite3.connect(":memory:")
    init_db(cold)
    load_log(cold, path)
    assert tally(settle(cold)).from_final_tally == 4


def test_loading_twice_changes_nothing(week3, tmp_path):
    from fadepublic.record import load_log, save_log

    path = tmp_path / "fade_log.json"
    save_log(week3, path)

    cold = sqlite3.connect(":memory:")
    init_db(cold)
    load_log(cold, path)
    once = settle(cold)
    load_log(cold, path)
    assert len(settle(cold)) == len(once)


def test_the_log_is_still_re_gradeable_at_another_threshold(week3, tmp_path):
    """Snapshots are archived rather than verdicts, so history is not frozen at
    whatever threshold happened to be configured when it was written."""
    from fadepublic.record import load_log, save_log

    path = tmp_path / "fade_log.json"
    save_log(week3, path)
    cold = sqlite3.connect(":memory:")
    init_db(cold)
    load_log(cold, path)

    assert len(settle(cold, threshold=80)) == 4
    assert len(settle(cold, threshold=90)) < 4


def test_a_kicked_off_game_is_archived_before_its_score_arrives(tmp_path):
    """Waiting for the final would leave a window where a cache eviction
    destroys a genuine pre-kickoff reading for good."""
    from fadepublic.record import load_log, save_log

    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - timedelta(minutes=30), home_tickets=90)

    path = tmp_path / "fade_log.json"
    assert save_log(c, path) == 1, "archived on kickoff, with no result yet"

    cold = sqlite3.connect(":memory:")
    init_db(cold)
    load_log(cold, path)
    assert settle(cold) == [], "nothing to grade until the score lands"

    # The score arrives on a later run; the reading is still the archived one.
    _result(cold, 20, 23)
    (s,) = settle(cold)
    assert s.observed_at == KICK - timedelta(minutes=30)
    assert s.result == "win"


def test_a_game_that_has_not_kicked_off_is_not_archived(tmp_path):
    from fadepublic.record import save_log

    c = sqlite3.connect(":memory:")
    init_db(c)
    future = datetime.now(UTC) + timedelta(days=2)
    _snapshot(c, future - timedelta(hours=1), home_tickets=90, kickoff=future)

    assert save_log(c, tmp_path / "fade_log.json") == 0


# ------------------------------------------- the watch band stays out of the record


def test_the_watch_band_never_reaches_the_record():
    """The whole safety property of the lower tier.

    The page shows games from 70% up, the record is graded at 80, and the only thing
    keeping those apart is that ``settle`` is called with the higher number. A game
    at 74% is on the page and must be absent from the record no matter what it did.
    """
    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - timedelta(minutes=30), home_tickets=74)
    _result(c, 30, 20)

    assert settle(c, threshold=80) == [], "74% is not a bet the record knows about"
    assert len(settle(c, threshold=70)) == 1, "and the band itself is really there"


def test_partitioning_one_pass_equals_asking_at_the_higher_threshold():
    """``cli`` makes one ``find_fades`` call at the watch threshold and splits the
    result, rather than calling it twice. That is only safe if the upper half is
    identical to what asking directly would have produced -- including order, since
    the board is read top to bottom."""
    path = pathlib.Path(__file__).parent.parent / "fixtures" / "action_network_nfl.json"
    games = parse_games(json.loads(path.read_text()))
    now = min(g.kickoff_utc for g in games if g.kickoff_utc) - timedelta(hours=1)

    direct = find_fades(games, threshold=80, now=now)
    partitioned = [
        f for f in find_fades(games, threshold=70, now=now) if f.public.tickets >= 80
    ]

    assert partitioned == direct
    assert len(find_fades(games, threshold=70, now=now)) > len(direct), (
        "and the lower threshold really is a superset, or this proves nothing"
    )


def test_the_archive_is_never_shrunk_by_a_narrower_grading_cap():
    """``save_log`` rewrites the file wholesale, so any bound it applied would be a
    delete. A pre-kickoff ticket count cannot be refetched once the game is over, so
    lowering the grading cap must cost re-grading, never history."""
    c = sqlite3.connect(":memory:")
    init_db(c)
    _snapshot(c, KICK - timedelta(hours=10), home_tickets=90)
    _result(c, 30, 20)

    with tempfile.TemporaryDirectory() as d:
        log = pathlib.Path(d) / "fade_log.json"
        assert save_log(c, log) == 1, "a 10h-out reading is archived"

        # Re-run the whole refresh cycle with a cap that will not grade it.
        settle(c, max_staleness=timedelta(hours=4))
        save_log(c, log)

        kept = json.loads(log.read_text())["games"]
        assert len(kept) == 1, "the reading survives a cap that cannot grade it"
