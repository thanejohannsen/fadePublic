"""What has to survive on the page.

The board's defence against a mislabelled feed is that it prints what it saw,
not merely what it concluded, so the ticket shares and both sides are asserted
here rather than left to the eye. The layout rules are asserted too: every UI
change this board has had so far shipped a defect that only a rendered page
showed, and column count is the one part of that a test can hold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fadepublic.fades import Fade
from fadepublic.record import Settled
from fadepublic.render import render_board, render_page
from fadepublic.splits import Side

KICKOFF = datetime(2026, 9, 27, 17, 0, tzinfo=UTC)


def _fade(side="under", tickets=93, money=95, line=47.5, market="total"):
    other = {"under": "over", "over": "under", "home": "away", "away": "home"}[side]
    # Both sides of a total quote the same number; the two sides of a spread
    # quote its negation, each from its own point of view.
    other_line = line if market == "total" else -line
    return Fade(
        game="IND @ WAS",
        kickoff_utc=KICKOFF,
        market=market,
        public=Side(market, side, line, -120, tickets, money),
        bet=Side(market, other, other_line, -102, 100 - tickets, None),
        num_bets=5000,
        away="IND",
        home="WAS",
    )


def _settled(result="win", from_final_tally=True, tickets=88):
    return Settled(
        fade=_fade(tickets=tickets),
        observed_at=KICKOFF - timedelta(minutes=30),
        from_final_tally=from_final_tally,
        result=result,
        away_points=31,
        home_points=33,
    )


# ------------------------------------------------------------- the board


def test_a_fade_reaches_the_page_carrying_both_sides_and_the_bet():
    """Drop the shares and the next transposition in the feed becomes invisible
    rather than obvious -- which is how this one was caught."""
    html = render_page([_fade()])

    assert "IND @ WAS" in html
    assert "93%" in html, "the public's ticket share"
    assert "under" in html and "over 47.5" in html, "both sides, and the bet spelled out"


def test_the_board_states_the_bet_rather_than_leaving_it_implied():
    """"over 47.5" is actionable; "fade the under" makes the reader do the flip,
    and a reader doing the flip is a reader who can get it backwards."""
    panel = render_board([_fade(side="over", tickets=85, money=90, line=38.5)])
    assert "under 38.5" in panel, "the bet, not the popular side"


def test_a_spread_names_the_team_rather_than_an_end_of_the_fixture():
    """"home +9.5" makes the reader map a side onto a team from the fixture
    beside it, which is the same class of error the over/under display exists
    to prevent."""
    panel = render_board([_fade(side="away", tickets=86, money=80, line=-9.5, market="spread")])
    assert "WAS +9.5" in panel
    assert "home +9.5" not in panel


def test_the_money_share_is_reported_without_a_verdict():
    """The gloss beside it said less than the number and split its colour at
    exactly zero, so an 82-against-83 noise gap was drawn in the green kept for
    a real divergence. The percentage stays; the reading of it is the reader's.
    """
    panel = render_board([_fade(side="over", tickets=85, money=90, line=38.5)])
    assert "90% of money" in panel
    assert "money agrees" not in panel and "money lags" not in panel


def test_the_bet_is_not_pushed_off_a_phone_by_extra_columns():
    """Six columns put the Bet cell -- the only thing here to act on -- off
    screen at 390px. The market column was dropped as redundant with the bet
    label, and kickoff folded under the game it belongs to."""
    panel = render_board([_fade()])
    assert panel.count("<th") == 3, "three columns, so the bet stays on screen"
    assert ">total<" not in panel, "the market column, redundant with the bet label"
    assert "data-kickoff" in panel, "kickoff kept, as a sub-line under the game"


# ------------------------------------------------------------ the record


def test_the_record_leads_the_page_with_its_own_number():
    """It is the reason to trust or ignore everything under it, so it reads
    before the board rather than after."""
    panel = render_board([_fade()], settled=[_settled(), _settled(), _settled("loss")])
    assert "2-1" in panel
    assert panel.index("2-1") < panel.index("Public is on"), "above the board"
    assert "31-33" in panel, "the settled log carries the score"


def test_a_push_is_logged_but_kept_out_of_the_win_rate():
    panel = render_board([], settled=[_settled("win"), _settled("push")])
    assert "1-0-1" in panel, "pushes are shown, and shown as distinct"
    assert "100%" in panel, "one win from one decision, the push not counted"


def test_the_closing_count_flag_appears_only_once_the_record_is_mixed():
    """While every row shares a basis the strip above has already said so, and
    repeating it on each row is noise -- but the moment the two are mixed the
    distinction is the only way to read the number honestly."""
    all_final = render_board([], settled=[_settled(), _settled()])
    assert "closing count" not in all_final

    mixed = render_board([], settled=[_settled(), _settled(from_final_tally=False)])
    assert "closing count" in mixed


# ----------------------------------------------------------- the document


def test_only_the_timestamp_moves_between_runs():
    """The publish step commits only when something other than the stamp line
    changed. If anything else drifted run to run it would churn a commit every
    refresh and bury real changes in noise."""
    one = datetime(2026, 9, 30, 1, 0, tzinfo=UTC)
    nine = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
    a = render_page([_fade()], settled=[_settled()], generated_at=one)
    b = render_page([_fade()], settled=[_settled()], generated_at=nine)

    strip = lambda h: [ln for ln in h.splitlines() if 'class="stamp"' not in ln]  # noqa: E731
    assert strip(a) == strip(b)
    assert a != b, "the stamp itself must still move"


def test_the_stamp_class_appears_once_and_only_on_the_stamp():
    """The publish step identifies the timestamp line by this class. Reusing it
    anywhere else would make that whole line's changes invisible to the check --
    exactly the bug that stopped the record ever being published before."""
    html = render_page([_fade()], settled=[_settled()])
    assert html.count('class="stamp"') == 1
    assert 'class="stamp"' not in render_board([_fade()], settled=[_settled()])


def test_no_server_rendered_countdown_survives_in_the_page():
    """Kickoffs ship absolute and the browser rewrites them, so the page stays
    correct between refreshes without being rewritten to keep a relative time
    honest."""
    html = render_page([_fade()])
    assert "data-kickoff" in html
    assert "Sun 17:00" in html, "the no-JavaScript fallback is the absolute time"
