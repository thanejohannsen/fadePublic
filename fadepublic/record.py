"""How the contrarian rule has actually done.

The record is **derived, never accumulated**. ``betting_splits`` already holds
every reading the refresh ever took, each stamped with when it was taken, so
for any finished game the question "was this bet on?" has one answer that can be
recomputed from scratch at any time. Nothing is locked, nothing can drift out of
sync with the board, and raising the threshold re-grades every past week for
free.

Which reading decides
---------------------
The last snapshot **at or before kickoff**. Not the earliest, not an average:
the rule is about where the public ended up once it had finished betting, and a
reading taken after kickoff is contaminated by people betting the live game.

This is what makes "it fell off the board during the week" self-enforcing. A
game carrying 85% of tickets on Tuesday that has drifted to 70% by Sunday is
simply not lopsided in its own gameday snapshot, so it never enters the record.
No separate bookkeeping, and no way for the board and the record to disagree
about what qualified -- both run the same ``find_fades``.

When there is no gameday reading
--------------------------------
The scheduled refresh is not reliable -- GitHub drops runs under load, and an
hourly cron measured over two days fired eleven times in forty-three hours. So
the snapshot nearest kickoff can be hours stale, and the rule has to say what
that costs.

Two bounds rather than one. Inside ``LOCK_LEAD`` the public had committed and the
reading is what the rule aims for, so the bet is **confirmed**. Between
``LOCK_LEAD`` and ``MAX_STALENESS`` the bet is still graded, but it carries the
lead time of the reading that decided it, and the page says how many of the
record came in that way. Beyond ``MAX_STALENESS`` the reading predates gameday
and is dropped rather than graded on a guess.

The earlier rule had one bound and dropped everything past it, which hid the
distinction it was actually making: a bet decided five hours out and a bet
decided forty minutes out counted the same, and a bet decided five hours and one
minute out counted not at all. Annotating instead of dropping keeps the evidence
quality visible per row, and means a gap in the schedule costs precision rather
than the bet.
"""

from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .splits import GameSplits, Side
from .fades import DEFAULT_THRESHOLD, FADEABLE_MARKETS, Fade, find_fades

log = logging.getLogger(__name__)

# The reading the rule aims for: inside this of kickoff the public has committed,
# and the bet is confirmed rather than inferred from a stale snapshot.
LOCK_LEAD = timedelta(hours=2)

# Past this a reading predates gameday and the bet is dropped. Generous next to
# LOCK_LEAD on purpose -- the scheduler misses its window often enough that a cap
# this tight would be the main thing deciding the record's size, which is a fact
# about GitHub rather than about the rule.
MAX_STALENESS = timedelta(hours=12)

# Both sides of a fadeable market are laid at roughly -110, so a win returns
# this and a loss costs 1. Used only for the units line on the page.
_PAYOUT = 100 / 110

WIN, LOSS, PUSH = "win", "loss", "push"


@dataclass(frozen=True)
class Settled:
    """One bet the rule made, and what happened to it."""

    fade: Fade
    observed_at: datetime
    from_final_tally: bool
    result: str
    away_points: int
    home_points: int
    # Was the deciding reading inside the lock window? Set by ``settle`` from the
    # ``lock_lead`` it was called with, deliberately not derived from the module
    # constant: the window is configurable, and a property reading LOCK_LEAD here
    # would report against a different number than the one that did the grading.
    confirmed: bool = True

    @property
    def game(self) -> str:
        return self.fade.game

    @property
    def score(self) -> str:
        return f"{self.away_points}-{self.home_points}"

    @property
    def lead_time(self) -> timedelta | None:
        """How far before kickoff the deciding reading was taken."""
        if self.fade.kickoff_utc is None:
            return None
        return self.fade.kickoff_utc - self.observed_at


@dataclass(frozen=True)
class Record:
    wins: int
    losses: int
    pushes: int
    from_final_tally: int
    # How many were decided by a reading outside the lock window. Reported beside
    # the tally rather than split out of it, the same way from_final_tally is: the
    # figure to act on is the whole record, with its basis said plainly.
    outside_lock: int = 0

    @property
    def decided(self) -> int:
        """Pushes are not decisions, so they are not in the denominator."""
        return self.wins + self.losses

    @property
    def label(self) -> str:
        base = f"{self.wins}-{self.losses}"
        return f"{base}-{self.pushes}" if self.pushes else base

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.decided if self.decided else None

    @property
    def units(self) -> float:
        """Net units at -110. A push returns the stake, so it is worth nothing."""
        return self.wins * _PAYOUT - self.losses


def _grade(fade: Fade, away_points: int, home_points: int) -> str:
    """Did the side the rule took cover?"""
    bet = fade.bet
    if bet.line is None:
        return PUSH
    if fade.market == "total":
        total = away_points + home_points
        if total == bet.line:
            return PUSH
        over = total > bet.line
        return WIN if over == (bet.side == "over") else LOSS

    # A spread carries its own line, already signed from that side's point of
    # view, so the margin is computed from whichever team was backed.
    if bet.side == "away":
        margin = (away_points + bet.line) - home_points
    else:
        margin = (home_points + bet.line) - away_points
    if margin == 0:
        return PUSH
    return WIN if margin > 0 else LOSS


def _deciding_snapshot(
    conn,
    away: str,
    home: str,
    kickoff: datetime,
    max_staleness: timedelta | None = MAX_STALENESS,
):
    """The last reading taken at or before kickoff, if one is close enough.

    ``max_staleness`` of ``None`` means no bound at all, which is what the archive
    wants: deciding what to *grade* is a judgement that can be revised, deciding
    what to *keep* cannot. Returns ``(fetched_at, is_final, rows)`` or ``None``.
    """
    row = conn.execute(
        """SELECT fetched_at, MAX(is_final) FROM betting_splits
            WHERE away = ? AND home = ? AND fetched_at <= ?
            GROUP BY fetched_at
            ORDER BY fetched_at DESC LIMIT 1""",
        (away, home, kickoff.isoformat()),
    ).fetchone()
    if row is None:
        return None

    observed = datetime.fromisoformat(row[0])
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    if max_staleness is not None and kickoff - observed > max_staleness:
        log.debug(
            "%s @ %s: nearest reading %s before kickoff, not graded",
            away, home, kickoff - observed,
        )
        return None

    rows = conn.execute(
        """SELECT market, side, line, odds, tickets_pct, money_pct, num_bets
             FROM betting_splits
            WHERE away = ? AND home = ? AND fetched_at = ?""",
        (away, home, row[0]),
    ).fetchall()
    return observed, bool(row[1]), rows


def settle(
    conn,
    threshold: int = DEFAULT_THRESHOLD,
    markets: tuple[str, ...] = FADEABLE_MARKETS,
    lock_lead: timedelta = LOCK_LEAD,
    max_staleness: timedelta = MAX_STALENESS,
) -> list[Settled]:
    """Every bet the rule would have made on a finished game, graded.

    Recomputed from the stored snapshots on each call. The qualification test is
    ``find_fades`` itself rather than a second copy of the rule -- the record and
    the live board are then incapable of disagreeing about what counts.
    """
    out: list[Settled] = []
    finished = conn.execute(
        """SELECT away, home, kickoff_utc, away_points, home_points
             FROM game_results ORDER BY kickoff_utc"""
    ).fetchall()

    for away, home, kickoff_raw, away_points, home_points in finished:
        kickoff = datetime.fromisoformat(kickoff_raw)
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)

        snapshot = _deciding_snapshot(conn, away, home, kickoff, max_staleness)
        if snapshot is None:
            continue
        observed, is_final, rows = snapshot

        sides = {
            (market, side): Side(
                market=market, side=side, line=line, odds=odds,
                tickets=tickets, money=money,
            )
            for market, side, line, odds, tickets, money, _ in rows
        }
        game = GameSplits(
            away=away,
            home=home,
            kickoff_utc=kickoff,
            # The game is over, but the snapshot predates it; say scheduled so
            # find_fades judges the reading rather than today's calendar.
            status="scheduled",
            num_bets=rows[0][6] if rows else 0,
            sides=sides,
        )
        for fade in find_fades(
            [game], threshold=threshold, now=kickoff - timedelta(seconds=1), markets=markets
        ):
            out.append(
                Settled(
                    fade=fade,
                    observed_at=observed,
                    from_final_tally=is_final,
                    result=_grade(fade, away_points, home_points),
                    away_points=away_points,
                    home_points=home_points,
                    confirmed=kickoff - observed <= lock_lead,
                )
            )

    out.sort(key=lambda s: (s.fade.kickoff_utc or datetime.min.replace(tzinfo=UTC), s.game))
    return out


def tally(settled: list[Settled]) -> Record:
    return Record(
        wins=sum(s.result == WIN for s in settled),
        losses=sum(s.result == LOSS for s in settled),
        pushes=sum(s.result == PUSH for s in settled),
        from_final_tally=sum(s.from_final_tally for s in settled),
        outside_lock=sum(not s.confirmed for s in settled),
    )


# --------------------------------------------------------------- the archive
#
# Everything above derives the record from the database. That is the right
# shape, but it put the record somewhere it could not survive: `data/` is
# gitignored and the scheduled job restores it from a GitHub Actions cache,
# which is evicted after a week without a hit.
#
# For the rest of the database that is fine -- it can all be refetched. A
# *pre-kickoff* ticket count cannot. Once a game is over the feed serves only
# the closing tally, which is exactly why backfilled rows are flagged. So the
# deciding snapshots are mirrored into the repository, and that copy is the one
# that lasts.
#
# Snapshots are archived, not verdicts. Which reading decides depends only on
# time, never on the threshold, so freezing it keeps the record re-gradeable:
# raise the threshold and every past week re-grades from the archive alone.
#
# That invariant now has one qualifier worth stating. The *staleness cap* is
# configurable, so which reading decides depends on time and on config -- which is
# exactly why this function applies no cap at all. The archive holds the last
# pre-kickoff reading for every game regardless of age, so lowering the cap narrows
# what gets graded without destroying what could be graded if it were raised again.
# Keep it that way: a bound here would turn a change of mind into data loss.

LOG_VERSION = 1


def _iso(value: datetime) -> str:
    return value.isoformat()


def save_log(conn, path) -> int:
    """Mirror every kicked-off game's deciding snapshot into ``path``.

    Written as soon as kickoff passes rather than when the score lands: waiting
    for the final leaves a window in which a cache eviction would destroy a real
    pre-kickoff reading for good. The score is filled in on a later run.

    Deliberately **unbounded**, and deliberately not given the grading cap. This
    function rewrites the file wholesale, so a cap here is a delete: lower
    ``max_staleness_hours`` in config, and the next run would erase every archived
    reading now beyond it, then push the deletion. Those are pre-kickoff ticket
    counts that cannot be refetched, which is the one thing this file exists to
    prevent. Archiving a reading that is currently too stale to grade costs a few
    hundred bytes; dropping it is permanent, and a later change of mind about the
    cap can only re-grade history that is still there.
    """
    path = pathlib.Path(path)
    games = conn.execute(
        """SELECT DISTINCT away, home, kickoff_utc FROM betting_splits
            WHERE kickoff_utc IS NOT NULL ORDER BY kickoff_utc, away"""
    ).fetchall()

    now = datetime.now(UTC)
    entries = []
    for away, home, kickoff_raw in games:
        kickoff = datetime.fromisoformat(kickoff_raw)
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=UTC)
        if kickoff > now:
            continue

        # No cap: see the docstring. The archive keeps what it saw.
        snapshot = _deciding_snapshot(conn, away, home, kickoff, max_staleness=None)
        if snapshot is None:
            continue
        observed, is_final, rows = snapshot

        score = conn.execute(
            """SELECT away_points, home_points FROM game_results
                WHERE away = ? AND home = ? AND kickoff_utc = ?""",
            (away, home, kickoff.isoformat()),
        ).fetchone()

        entries.append(
            {
                "away": away,
                "home": home,
                "kickoff_utc": _iso(kickoff),
                "observed_at": _iso(observed),
                "is_final": int(is_final),
                "away_points": score[0] if score else None,
                "home_points": score[1] if score else None,
                "sides": [
                    {
                        "market": market, "side": side, "line": line, "odds": odds,
                        "tickets": tickets, "money": money, "num_bets": num_bets,
                    }
                    for market, side, line, odds, tickets, money, num_bets in rows
                ],
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": LOG_VERSION, "games": entries}, indent=1, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return len(entries)


def load_log(conn, path) -> int:
    """Read an archive back into the tables ``settle`` grades from.

    Idempotent, and it never overwrites a row the database already holds: a live
    pre-kickoff reading taken by this machine is better evidence than anything
    replayed, so ``INSERT OR IGNORE`` leaves it alone.
    """
    path = pathlib.Path(path)
    if not path.exists():
        return 0

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != LOG_VERSION:
        log.warning("Ignoring fade log at version %r", payload.get("version"))
        return 0

    loaded = 0
    for entry in payload.get("games") or []:
        conn.executemany(
            """INSERT OR IGNORE INTO betting_splits
                   (fetched_at, kickoff_utc, away, home, market, side,
                    line, odds, tickets_pct, money_pct, num_bets, is_final)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    entry["observed_at"], entry["kickoff_utc"],
                    entry["away"], entry["home"], s["market"], s["side"],
                    s["line"], s["odds"], s["tickets"], s["money"],
                    s.get("num_bets"), entry.get("is_final", 0),
                )
                for s in entry["sides"]
            ],
        )
        if entry.get("away_points") is not None:
            conn.execute(
                """INSERT OR IGNORE INTO game_results
                       (away, home, kickoff_utc, away_points, home_points, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entry["away"], entry["home"], entry["kickoff_utc"],
                    entry["away_points"], entry["home_points"], entry["observed_at"],
                ),
            )
        loaded += 1

    conn.commit()
    return loaded
