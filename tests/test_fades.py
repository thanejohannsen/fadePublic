"""The contrarian board.

The rule is narrow on purpose -- spreads and totals, tickets not money, games
that have not started -- and each of those boundaries is one a future change
could quietly erode. Moneylines in particular: they reach any threshold almost
automatically, so letting them back in would flood the board with rows that say
nothing while still looking like the rule working.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta

import pytest

from fadepublic.fades import find_fades
from fadepublic.splits import GameSplits, Side, parse_games

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=2)


def side(market, s, tickets, money=None, line=None, odds=-110):
    return Side(market=market, side=s, line=line, odds=odds, tickets=tickets, money=money)


def game(sides, kickoff=LATER, status="scheduled", away="AAA", home="BBB"):
    return GameSplits(
        away=away,
        home=home,
        kickoff_utc=kickoff,
        status=status,
        num_bets=5000,
        sides={(x.market, x.side): x for x in sides},
    )


# ------------------------------------------------------------ the rule


def test_a_lopsided_spread_puts_the_other_side_on_the_board():
    g = game([
        side("spread", "home", 88, money=70, line=-3.5),
        side("spread", "away", 12, money=30, line=3.5),
    ])
    (fade,) = find_fades([g], threshold=80, now=NOW)

    assert fade.public.side == "home" and fade.public.tickets == 88
    assert fade.bet.side == "away", "we take the unpopular side"
    assert fade.bet.line == 3.5, "and its own line, not the negation of theirs"
    assert fade.line_label == "AAA +3.5", "named by team, not by which end of the fixture"


def test_a_lopsided_total_is_labelled_so_the_direction_can_be_checked():
    """The feed's over/under labelling looked transposed until it was checked
    against independent boards, so the board states the bet outright rather
    than leaving the reader to flip it."""
    g = game([
        side("total", "under", 93, money=95, line=47.5),
        side("total", "over", 7, money=5, line=47.5),
    ])
    (fade,) = find_fades([g], threshold=80, now=NOW)

    assert fade.public.side == "under"
    assert fade.line_label == "over 47.5"


def test_a_moneyline_never_reaches_the_board():
    """Excluded by design: everyone takes the big favourite for a small payout,
    so the threshold stops discriminating. Over three weeks the rule produced 35
    moneyline bets at a 34% win rate against 8 spread bets.
    """
    g = game([
        side("moneyline", "home", 96, money=80),
        side("moneyline", "away", 4, money=20),
    ])
    assert find_fades([g], threshold=80, now=NOW) == []


def test_a_side_below_the_threshold_is_not_on_the_board():
    g = game([
        side("spread", "home", 79, line=-3.5),
        side("spread", "away", 21, line=3.5),
    ])
    assert find_fades([g], threshold=80, now=NOW) == []
    assert len(find_fades([g], threshold=75, now=NOW)) == 1


# --------------------------------------------------- games you cannot bet


def test_a_game_already_under_way_drops_off():
    """The rule is about a price still available."""
    g = game(
        [side("spread", "home", 90, line=-3.5), side("spread", "away", 10, line=3.5)],
        kickoff=NOW - timedelta(minutes=1),
    )
    assert find_fades([g], threshold=80, now=NOW) == []


def test_a_game_the_feed_calls_started_drops_off_even_without_a_kickoff():
    g = game(
        [side("spread", "home", 90, line=-3.5), side("spread", "away", 10, line=3.5)],
        kickoff=None,
        status="inprogress",
    )
    assert find_fades([g], threshold=80, now=NOW) == []


def test_half_a_market_is_not_a_market():
    """Without the other side there is no price to take, so nothing is shown."""
    g = game([side("spread", "home", 90, line=-3.5)])
    assert find_fades([g], threshold=80, now=NOW) == []


# ------------------------------------------------------------ ordering


def test_the_board_reads_in_the_order_games_need_deciding():
    soon = game(
        [side("spread", "home", 85, line=-3), side("spread", "away", 15, line=3)],
        kickoff=NOW + timedelta(hours=2), away="EARLY", home="ONE",
    )
    late = game(
        [side("spread", "home", 95, line=-7), side("spread", "away", 5, line=7)],
        kickoff=NOW + timedelta(days=3), away="LATE", home="TWO",
    )
    order = [f.game for f in find_fades([late, soon], threshold=80, now=NOW)]
    assert order == ["EARLY @ ONE", "LATE @ TWO"], "soonest first, not most lopsided"


# ------------------------------------------------- tickets versus money


def test_divergence_separates_a_crowd_from_an_informed_minority():
    """The whole reason the rule counts tickets rather than handle."""
    sharp = game([
        side("spread", "home", 90, money=55, line=-3.5),
        side("spread", "away", 10, money=45, line=3.5),
    ])
    consensus = game([
        side("spread", "home", 90, money=92, line=-3.5),
        side("spread", "away", 10, money=8, line=3.5),
    ])
    assert find_fades([sharp], now=NOW)[0].divergence == -35
    assert find_fades([consensus], now=NOW)[0].divergence == +2


def test_missing_money_is_not_reported_as_agreement():
    g = game([
        side("spread", "home", 90, money=None, line=-3.5),
        side("spread", "away", 10, money=None, line=3.5),
    ])
    assert find_fades([g], now=NOW)[0].divergence is None


# ------------------------------------------------------ the real payload


@pytest.fixture
def payload():
    path = pathlib.Path(__file__).parent.parent / "fixtures" / "action_network_nfl.json"
    return json.loads(path.read_text())


def test_the_captured_feed_parses(payload):
    games = parse_games(payload)
    assert games and all(g.away and g.home for g in games)
    assert all(g.kickoff_utc is None or g.kickoff_utc.tzinfo is not None for g in games)


def test_each_side_of_a_market_appears_once(payload):
    """The payload repeats every market across all six requested book ids.

    Keying by (market, side) is what collapses them, so this guards a refactor
    that keyed by book as well and quietly multiplied the board. It does *not*
    exercise the preference for book 15 -- every book returns identical
    consensus figures, so which one wins is unobservable in the values and
    matters only for determinism.
    """
    games = parse_games(payload)
    for g in games:
        for market in ("spread", "total"):
            sides = [k for k in g.sides if k[0] == market]
            assert len(sides) <= 2, f"{g.label} {market} kept {len(sides)} rows"


def test_ticket_shares_sum_to_a_hundred(payload):
    """A cheap integrity check on the feed: if this ever fails, the percentages
    are not what they claim and nothing downstream should be trusted."""
    for g in parse_games(payload):
        for market in ("spread", "total", "moneyline"):
            pair = [s for (m, _), s in g.sides.items() if m == market]
            if len(pair) == 2:
                assert pair[0].tickets + pair[1].tickets == 100, f"{g.label} {market}"


# ------------------------------------------- naming the popular side, not keying it


def test_the_popular_side_is_named_the_way_the_bet_is():
    """"away 88%" made the reader map a fixture end onto a team to know what the
    crowd was actually on -- the same failure the bet column was given a team name
    to avoid."""
    g = game([
        side("spread", "away", 88, money=70, line=-9.5),
        side("spread", "home", 12, money=30, line=9.5),
    ])
    (fade,) = find_fades([g], threshold=80, now=NOW)

    assert fade.public_label == "AAA -9.5", "the crowd's team and the crowd's number"
    assert fade.line_label == "BBB +9.5", "and the bet unchanged beside it"


def test_a_total_carries_its_number_on_both_sides():
    """Both halves of a total quote the same line, so it reads twice in one row.
    Worth it: "over 72%" alone does not say what is being bet over."""
    g = game([
        side("total", "under", 93, money=95, line=47.5),
        side("total", "over", 7, money=5, line=47.5),
    ])
    (fade,) = find_fades([g], threshold=80, now=NOW)

    assert fade.public_label == "under 47.5"
    assert fade.line_label == "over 47.5"


def test_the_popular_side_prints_its_own_line_not_the_negation_of_the_bet():
    """The two halves of a spread are usually mirror images, and the feed does not
    promise it: in the week 3 fixture LAC @ BUF is quoted 7 / -7.5 and MIN @ TB
    -1.5 / 1. Deriving one label from the other would print a price no book ever
    offered, and nothing else in the suite would notice."""
    g = game([
        side("spread", "away", 88, money=70, line=7),
        side("spread", "home", 12, money=30, line=-7.5),
    ])
    (fade,) = find_fades([g], threshold=80, now=NOW)

    assert fade.public_label == "AAA +7", "the feed's own number for that side"
    assert fade.public_label != "AAA +7.5", "which is not the bet's line negated"
    assert fade.line_label == "BBB -7.5"


def test_a_side_with_no_line_is_still_named():
    """A market can arrive without a price. The label degrades to the name rather
    than printing None beside a percentage."""
    g = game([
        side("spread", "away", 88, money=70, line=None),
        side("spread", "home", 12, money=30, line=None),
    ])
    (fade,) = find_fades([g], threshold=80, now=NOW)

    assert fade.public_label == "AAA"
    assert fade.line_label == "BBB"


# -------------------------------------------- one cut per market


def test_a_market_can_have_its_own_cut():
    """Spreads fire at 70 and totals at 80. The two arms were measured apart over
    NFL weeks 1-6 -- spreads 19-5 at 80% with 12-3-2 in the band beneath, totals
    showing nothing under 80% -- so they stopped sharing a number."""
    g = game([
        side("spread", "home", 72, money=70, line=-3.5),
        side("spread", "away", 28, money=30, line=3.5),
        side("total", "over", 72, money=70, line=47.5),
        side("total", "under", 28, money=30, line=47.5),
    ])
    cuts = {"spread": 70, "total": 80}
    picked = find_fades([g], threshold=cuts, now=NOW)

    assert [f.market for f in picked] == ["spread"], "the total at 72% is short of 80"


def test_a_market_absent_from_the_mapping_is_not_looked_at():
    """How the watch band is made totals-only: it names `total` and says nothing
    about `spread`, so no spread can ever land in it."""
    g = game([
        side("spread", "home", 95, money=90, line=-3.5),
        side("spread", "away", 5, money=10, line=3.5),
    ])
    assert find_fades([g], threshold={"total": 70}, now=NOW) == []


def test_a_plain_number_still_applies_to_every_market():
    """The scalar spelling has to keep working: the college board uses one cut for
    both markets, and every test written before per-market cuts passes an int."""
    g = game([
        side("spread", "home", 85, money=80, line=-3.5),
        side("spread", "away", 15, money=20, line=3.5),
        side("total", "over", 85, money=80, line=47.5),
        side("total", "under", 15, money=20, line=47.5),
    ])
    assert len(find_fades([g], threshold=80, now=NOW)) == 2


# ------------------------------------------------- describing an empty board


def test_the_slate_summary_counts_what_has_been_played():
    from fadepublic.fades import summarise_slate

    played = game(
        [side("spread", "home", 88, money=70, line=-3.5),
         side("spread", "away", 12, money=30, line=3.5)],
        status="complete", away="DONE", home="GAME",
    )
    upcoming = game([
        side("spread", "home", 57, money=55, line=-4.5),
        side("spread", "away", 43, money=45, line=4.5),
    ])
    s = summarise_slate([played, upcoming], threshold={"spread": 70}, now=NOW)

    assert (s.total, s.finished) == (2, 1)
    assert s.next_kickoff == LATER


def test_the_leader_is_drawn_only_from_games_you_can_still_bet():
    """It reuses find_fades rather than scanning again, so a finished game cannot
    be named as the most lopsided side still open -- the 88% above is exactly the
    row that would win such a scan."""
    from fadepublic.fades import summarise_slate

    played = game(
        [side("spread", "home", 88, money=70, line=-3.5),
         side("spread", "away", 12, money=30, line=3.5)],
        status="complete", away="DONE", home="GAME",
    )
    upcoming = game([
        side("spread", "home", 57, money=55, line=-4.5),
        side("spread", "away", 43, money=45, line=4.5),
    ])
    s = summarise_slate([played, upcoming], threshold={"spread": 70}, now=NOW)

    assert s.best is not None and s.best.public.tickets == 57
    assert s.best.game == "AAA @ BBB", "the upcoming game, not the finished one"
    assert s.best_cut == 70 and s.shortfall == 13


def test_a_fully_played_slate_reports_itself_as_such():
    from fadepublic.fades import summarise_slate

    played = game(
        [side("spread", "home", 88, money=70, line=-3.5),
         side("spread", "away", 12, money=30, line=3.5)],
        status="complete",
    )
    s = summarise_slate([played], threshold={"spread": 70}, now=NOW)

    assert s.all_played and s.best is None and s.next_kickoff is None
    assert s.shortfall is None, "nothing open means nothing to be short of"


def test_a_leader_already_past_its_cut_is_short_by_nothing():
    """Possible between the fetch and the render on a live slate; the message must
    not print 'short by -4'."""
    from fadepublic.fades import summarise_slate

    g = game([
        side("spread", "home", 74, money=70, line=-3.5),
        side("spread", "away", 26, money=30, line=3.5),
    ])
    assert summarise_slate([g], threshold={"spread": 70}, now=NOW).shortfall == 0
