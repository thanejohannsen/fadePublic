"""Games where the tickets are lopsided enough to bet against.

The rule: when roughly eighty per cent or more of *bet tickets* sit on one side
of a spread or a total, take the other side. Tickets, not money -- a headcount,
where every five-dollar parlay leg weighs the same as a serious position.

Why tickets rather than handle
------------------------------
Because the gap between them is the signal. Eighty per cent of tickets next to
half the money means the twenty per cent are betting far larger, which is the
only thing separating a crowd from an informed minority. Handle alone cannot say
that, and neither can tickets alone -- so both are carried through to the board
even though only the ticket share decides what qualifies.

Why moneylines are excluded
---------------------------
They reach eighty per cent almost automatically: everyone takes the big
favourite for a small payout, so the threshold stops meaning anything. Over 2026
weeks 1-3 the rule produced 35 moneyline bets at a 34% win rate against 8 spread
bets, which is mostly a statement about which market the filter happens to fire
on rather than about the public being wrong.

What this is not
----------------
It is not a claim of edge. Three weeks of backtest put the spread arm at 6-2,
whose confidence interval runs from 45% to 105% -- consistent with anything at
all. This produces a board so a forward record can accumulate against a rule
fixed in advance, which is the only way the question gets answered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from .splits import GameSplits, Side

# Moneylines are deliberately absent. See the module docstring.
FADEABLE_MARKETS = ("spread", "total")

DEFAULT_THRESHOLD = 80

# A threshold is either one number for every market, or one per market. The
# second form exists because the two markets stopped deserving the same cut: the
# NFL spread arm was measured at 19-5 over weeks 1-6 at 80%, and the 70-79% band
# beneath it at 12-3, while totals showed nothing below 80%. Spreads therefore
# fire at 70 and totals at 80.
#
# A market absent from the mapping is not looked at, which is how the watch band
# is made totals-only: it names `total` and says nothing about `spread`.
Threshold = int | Mapping[str, int]

# The lower bound of the watch band: shown on the page, never graded. Lives here
# beside the threshold it is paired with so the two cannot drift apart, even though
# nothing in this module reads it -- the band is applied by partitioning find_fades'
# output, not by a second rule.
DEFAULT_WATCH_THRESHOLD = 70


@dataclass(frozen=True)
class Fade:
    """One lopsided market, and the side the rule says to take."""

    game: str
    kickoff_utc: datetime | None
    market: str
    public: Side
    bet: Side
    num_bets: int
    # Carried so a spread can be written as "MIA +9.5" rather than "home +9.5".
    # The bet has to name the team you are backing: a reader who has to map
    # home onto a team from the fixture beside it is a reader who can get it
    # the wrong way round, which is the whole failure this board exists to
    # avoid on the over/under side.
    away: str = ""
    home: str = ""

    @property
    def divergence(self) -> int | None:
        """Money share minus ticket share on the popular side.

        Strongly negative means the money is not following the crowd, which is
        the case the rule is really reaching for. Zero or positive means the
        handle agrees, and fading it means fading everyone.
        """
        if self.public.money is None:
            return None
        return self.public.money - self.public.tickets

    @property
    def bet_name(self) -> str:
        """Who you are backing: a team for a spread, over/under for a total."""
        return self._name(self.bet)

    @property
    def line_label(self) -> str:
        """The bet as it would be written on a ticket."""
        return self._label(self.bet)

    @property
    def public_label(self) -> str:
        """The popular side, written the same way the bet is.

        It used to print the raw feed key -- "away 79%" -- which made the reader
        map a fixture end onto a team to know what the crowd was actually on. That
        is the same failure the bet column was given a team name to avoid; the
        public column simply never got the same treatment.
        """
        return self._label(self.public)

    def _name(self, side: Side) -> str:
        """A side as a person would say it, not as the feed keys it."""
        if self.market == "total":
            return side.side
        team = {"away": self.away, "home": self.home}.get(side.side, "")
        return team or side.side

    def _label(self, side: Side) -> str:
        """``_name`` plus the side's own line.

        Reads ``side.line`` rather than negating the other side's. The two halves of
        a spread are usually mirror images but the feed does not promise it -- in
        the week 3 fixture LAC @ BUF is quoted 7 / -7.5 and MIN @ TB -1.5 / 1 -- and
        deriving one from the other would print a number no book ever offered.
        """
        name = self._name(side)
        if side.line is None:
            return name
        if self.market == "total":
            return f"{name} {side.line:g}"
        return f"{name} {side.line:+g}"


def limits(threshold: Threshold, markets: tuple[str, ...]) -> dict[str, int]:
    """Per-market cuts, whichever form the caller used.

    A plain int applies to every market in ``markets``. A mapping is filtered by
    ``markets`` and keeps only what it names, so a partial mapping silently
    excludes the markets it omits -- which is the behaviour the watch band wants
    and the reason this is a named function rather than a dict comprehension
    inlined at each call site.
    """
    if isinstance(threshold, Mapping):
        return {m: int(threshold[m]) for m in markets if m in threshold}
    return {m: int(threshold) for m in markets}


def find_fades(
    games: list[GameSplits],
    threshold: Threshold = DEFAULT_THRESHOLD,
    now: datetime | None = None,
    markets: tuple[str, ...] = FADEABLE_MARKETS,
) -> list[Fade]:
    """Every spread or total currently carrying a lopsided ticket count.

    Recomputed from scratch on every call rather than maintained as a list.
    Availability is derived the same way everywhere else in this project, and it
    means a game that stops qualifying simply stops appearing -- there is no
    stale entry to remove and nothing to go out of sync.

    Games already under way are dropped: the rule is about a price you can still
    take.
    """
    now = now or datetime.now(UTC)
    cuts = limits(threshold, markets)
    out: list[Fade] = []
    for game in games:
        if game.started:
            continue
        if game.kickoff_utc is not None and game.kickoff_utc <= now:
            continue
        for (market, _side), public in game.sides.items():
            cut = cuts.get(market)
            if cut is None or public.tickets < cut:
                continue
            bet = game.opposite(public)
            if bet is None:
                # Half a market is not a market: without the other side there is
                # no price to take, so there is nothing to show.
                continue
            out.append(
                Fade(
                    game=game.label,
                    kickoff_utc=game.kickoff_utc,
                    market=market,
                    public=public,
                    bet=bet,
                    num_bets=game.num_bets,
                    away=game.away,
                    home=game.home,
                )
            )

    # Soonest first -- the board is read in the order the games need deciding.
    return sorted(
        out,
        key=lambda f: (
            f.kickoff_utc or datetime.max.replace(tzinfo=UTC),
            -f.public.tickets,
            f.game,
        ),
    )


@dataclass(frozen=True)
class Slate:
    """What the feed is showing, for a page that has to prove it is alive.

    An empty board beside a timestamp from last night is indistinguishable from a
    job that died three days ago -- and this project has already shipped the
    second thing once, when the record silently vanished and the page reported it
    perfectly calmly. The board being empty is usually just Monday: the slate has
    been played and the next one has not been posted.

    So the empty state carries its own evidence. How much of the slate is already
    finished, when the next game that could still qualify kicks off, and how far
    its most lopsided side is from the cut. All three move when the feed is
    working and freeze when it is not.
    """

    total: int
    finished: int
    next_kickoff: datetime | None
    best: Fade | None
    best_cut: int | None

    @property
    def all_played(self) -> bool:
        return self.total > 0 and self.finished == self.total

    @property
    def shortfall(self) -> int | None:
        """Points of ticket share the leader still needs to reach its cut."""
        if self.best is None or self.best_cut is None:
            return None
        return max(0, self.best_cut - self.best.public.tickets)


def summarise_slate(
    games: list[GameSplits],
    threshold: Threshold = DEFAULT_THRESHOLD,
    now: datetime | None = None,
    markets: tuple[str, ...] = FADEABLE_MARKETS,
) -> Slate:
    """Describe the slate behind an empty board.

    The leader is found by running ``find_fades`` at a threshold of zero rather
    than by a second scan: that inherits the rule's own handling of started games
    and its labelling, so the message cannot describe a game the board would have
    excluded, or name a side differently from how the board would have named it.
    """
    now = now or datetime.now(UTC)
    still_open = find_fades(games, threshold=0, now=now, markets=markets)
    best = max(still_open, key=lambda f: f.public.tickets, default=None)
    cuts = limits(threshold, markets)
    kickoffs = [
        g.kickoff_utc
        for g in games
        if not g.started and g.kickoff_utc is not None and g.kickoff_utc > now
    ]
    return Slate(
        total=len(games),
        finished=sum(1 for g in games if g.started),
        next_kickoff=min(kickoffs, default=None),
        best=best,
        best_cut=cuts.get(best.market) if best else None,
    )
