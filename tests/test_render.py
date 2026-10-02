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
from fadepublic.render import _watch_panel, render_board, render_page
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


def _settled(result="win", from_final_tally=True, tickets=88, lead=None, confirmed=True):
    return Settled(
        fade=_fade(tickets=tickets),
        observed_at=KICKOFF - (lead if lead is not None else timedelta(minutes=30)),
        from_final_tally=from_final_tally,
        result=result,
        away_points=31,
        home_points=33,
        confirmed=confirmed,
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
    # Against the bet cell's own markup, not the whole panel: now that the public
    # cell also carries a line, a bare substring check would be satisfied by either
    # cell and would stop proving the sentence in this test's name.
    assert "<td><b>under 38.5</b>" in panel, "the bet, not the popular side"
    assert '<td class="pub">over 38.5 ' in panel, "and the crowd's side says 38.5 too"


def test_a_spread_names_the_team_rather_than_an_end_of_the_fixture():
    """"home +9.5" makes the reader map a side onto a team from the fixture
    beside it, which is the same class of error the over/under display exists
    to prevent."""
    panel = render_board([_fade(side="away", tickets=86, money=80, line=-9.5, market="spread")])
    assert "WAS +9.5" in panel
    assert "home +9.5" not in panel
    # The public cell is held to the same standard the bet cell already was.
    assert "IND -9.5" in panel, "the crowd's team, not the fixture end it sits on"
    assert "away -9.5" not in panel


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
    # The whole page, because the settled log is now its own panel at the foot:
    # the tally is the summary and belongs on top, the log is detail and belongs
    # last, with the watch list in between where it can be acted on.
    page = render_page([_fade()], settled=[_settled(), _settled(), _settled("loss")])
    assert "2-1" in page
    assert page.index("2-1") < page.index("Public is on"), "above the board"
    assert "31-33" in page, "the settled log carries the score"
    assert page.index("Public is on") < page.index("31-33"), "and the log below it"


def test_a_push_is_logged_but_kept_out_of_the_win_rate():
    panel = render_board([], settled=[_settled("win"), _settled("push")])
    assert "1-0-1" in panel, "pushes are shown, and shown as distinct"
    assert "100%" in panel, "one win from one decision, the push not counted"


def test_the_closing_count_flag_appears_only_once_the_record_is_mixed():
    """While every row shares a basis the strip above has already said so, and
    repeating it on each row is noise -- but the moment the two are mixed the
    distinction is the only way to read the number honestly."""
    all_final = render_page([], settled=[_settled(), _settled()])
    assert "closing count" not in all_final

    mixed = render_page([], settled=[_settled(), _settled(from_final_tally=False)])
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


# ----------------------------------------------------- the watch band, display only


def test_the_watch_band_is_its_own_panel_and_says_it_is_not_recorded():
    """It sits next to a running win-loss record, so the one thing a visitor must
    not conclude is that these rows are in it."""
    panel = _watch_panel([_fade(tickets=74)], 70, 80)

    assert panel.count('<div class="panel"') == 1, "its own panel, not board rows"
    assert "<h2>" in panel, "with a heading, so the two sections are not one list"
    assert "Not recorded" in panel
    assert "74%" in panel, "and the actual share, like every other row here"


def test_the_watch_band_label_is_derived_from_both_thresholds():
    """Hardcoding "70-79%" would quietly lie the moment either threshold moved."""
    assert "70% and 79%" in _watch_panel([_fade(tickets=74)], 70, 80)
    assert "60% and 84%" in _watch_panel([_fade(tickets=74)], 60, 85)


def test_no_watch_panel_at_all_when_nothing_is_in_the_band():
    """A heading over an empty table is a question the reader cannot answer, and an
    unstable blank panel would also churn the published diff."""
    assert _watch_panel([], 70, 80) == ""


def test_the_watch_panel_survives_an_empty_board():
    """Early in the week the board is empty and the band is not -- the path that
    renders a bare "nothing qualifies" message must still carry the panel."""
    html = render_page([], watch=[_fade(tickets=74)])

    assert "No spread or total is currently carrying 80%" in html
    assert "Watching" in html and "74%" in html
    assert "shows under Watching below" in html, "and the two must not contradict"


def test_the_board_keeps_three_columns_with_a_watch_panel_present():
    """The watch table lives outside render_board precisely so the column-count
    guarantee stays checkable on the board alone."""
    assert render_board([_fade()]).count("<th") == 3
    assert render_page([_fade()], watch=[_fade(tickets=74)]).count('class="stamp"') == 1


# -------------------------------------------------- how stale the deciding reading was


def test_a_bet_decided_outside_the_lock_window_shows_how_far_out():
    """The replacement for silently dropping it. The number is the whole point: it
    is what separates a bet confirmed near kickoff from one inferred hours earlier."""
    stale = _settled(from_final_tally=False, lead=timedelta(hours=5, minutes=12),
                     confirmed=False)
    panel = render_page([_fade()], settled=[stale])

    assert "5h12m before kickoff" in panel
    assert "1 of 1 were decided by a reading more than 2h before kickoff" in panel


def test_a_confirmed_bet_says_nothing_about_its_lead_time():
    """Only the exceptions are worth a sub-line; annotating every row would make the
    annotation invisible."""
    panel = render_page([_fade()], settled=[_settled(from_final_tally=False)])

    # The whole page, or this would pass for the wrong reason: the settled log is no
    # longer part of render_board, so a row annotation could not appear there anyway.
    assert "31-33" in panel, "the log is really present to be checked"
    # "before kickoff" also occurs in the rule's own prose; the closing tag is what
    # makes this the per-row annotation rather than the explanation above it.
    assert "before kickoff</span>" not in panel
    assert "were decided by a reading more than" not in panel


def test_a_closing_count_is_never_also_labelled_with_a_lead_time():
    """A backfilled row is stamped at kickoff, so its lead is zero -- it would read
    "0m before kickoff", the most confident label on the row with the weakest basis.
    The two sub-lines are mutually exclusive."""
    mixed = [
        _settled(from_final_tally=True, lead=timedelta(0)),
        _settled(from_final_tally=False, lead=timedelta(hours=6), confirmed=False),
    ]
    panel = render_page([_fade()], settled=mixed)

    assert "closing count" in panel
    assert "0m before kickoff" not in panel
    assert "6h before kickoff" in panel


def test_the_staleness_rule_is_stated_from_the_constants_not_a_literal():
    """The prose said "within 4 hours of kickoff" as a hardcoded string, which went
    stale the moment the rule changed. It is now two bounds, and both come from the
    values that actually do the grading."""
    panel = render_board([_fade()], settled=[_settled()])

    assert "4 hours" not in panel
    assert "2h" in panel and "12h" in panel


def test_the_watch_list_comes_before_the_settled_log():
    """The ordering bug this structure exists to prevent.

    The watch list first shipped after the board's panel, and that panel ended with
    the settled log -- so on a real page the near misses sat below twenty-odd rows
    of history and were invisible without scrolling past the whole record. What a
    reader can still bet on has to come before what has already been graded.
    """
    page = render_page(
        [_fade()], settled=[_settled(), _settled()], watch=[_fade(tickets=74)]
    )

    assert page.index("Watching") < page.index("Settled"), (
        "the band is actionable and the log is history; actionable goes first"
    )
    assert page.index("Public is on") < page.index("Watching"), "board still leads"


def test_the_three_panels_appear_in_order_and_only_when_they_have_content():
    """Each section is its own panel so an empty one can vanish rather than leave a
    heading over nothing."""
    full = render_page([_fade()], settled=[_settled()], watch=[_fade(tickets=74)])
    assert full.count('<div class="panel"') == 3

    no_watch = render_page([_fade()], settled=[_settled()])
    assert no_watch.count('<div class="panel"') == 2
    assert "Watching" not in no_watch

    board_only = render_page([_fade()])
    assert board_only.count('<div class="panel"') == 1
    assert "Settled" not in board_only


def test_no_table_anywhere_still_prints_a_raw_feed_key():
    """The regression this change exists to prevent, checked on the whole page so a
    new table cannot reintroduce it unnoticed. "away"/"home" are feed keys, not
    things a person says."""
    page = render_page(
        [_fade(side="away", tickets=86, line=-9.5, market="spread")],
        settled=[_settled()],
        watch=[_fade(side="home", tickets=74, line=3.5, market="spread")],
    )

    assert 'class="pub">away ' not in page
    assert 'class="pub">home ' not in page
    assert "public away " not in page, "the settled log's sub-line too"
    assert "public home " not in page


def test_the_settled_log_names_both_teams():
    """The log is the record's evidence, so it has to be readable on its own: which
    team the crowd was on, and which one the rule took."""
    page = render_page([], settled=[_settled(tickets=86)])

    assert "public under 47.5 86%" in page, "named side, its line, its share"
