"""Settings, read from config.toml beside the repo root."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .fades import DEFAULT_THRESHOLD, DEFAULT_WATCH_THRESHOLD, Threshold, limits


@dataclass(frozen=True)
class Config:
    # Share of *tickets* -- a headcount, not money -- that makes a side "the
    # public" and puts the other side on the board. One number for every market,
    # or one per market: the two markets no longer share a cut, because the
    # spread arm measured 19-5 at 80% over NFL weeks 1-6 with the 70-79% band
    # beneath it at 12-3, while totals showed nothing under 80%.
    threshold: Threshold = DEFAULT_THRESHOLD
    # A second, lower band that is shown on the page and never graded. It exists
    # because a cut is a cliff: a game at 79% is indistinguishable from one at
    # 81% as evidence, but only one of them was visible. Displaying the near
    # misses without recording them keeps the record's definition unchanged.
    #
    # Per market, and deliberately partial. Spreads now fire at 70 and so have no
    # band left underneath worth watching; naming only `total` here is what makes
    # the watch list totals-only.
    watch_threshold: Threshold = DEFAULT_WATCH_THRESHOLD
    # Moneylines are deliberately absent: they reach any threshold almost
    # automatically, because everyone takes the big favourite for a small
    # payout. See fades.py.
    markets: tuple[str, ...] = ("spread", "total")
    season: int = 2026

    # How close to kickoff a reading has to be for the bet to count as confirmed
    # rather than inferred from a stale snapshot. See record.py. Fractional hours
    # are allowed, so 1.5 is a legal lock window.
    lock_lead_hours: float = 2
    # Past this, a reading says nothing about gameday and the bet is dropped.
    max_staleness_hours: float = 12

    def __post_init__(self) -> None:
        """Validated here rather than in ``load_config``.

        ``load_config`` returns a bare ``Config()`` when there is no file on disk, so
        a check living there would be bypassable. Both failures below would otherwise
        surface as a silently missing section or an empty record rather than an error.
        """
        counted, watched = self.counted(), self.watched()
        if not counted:
            raise ValueError(
                f"no market has a threshold: markets={list(self.markets)} but "
                f"threshold names {sorted(limits(self.threshold, self.markets))}"
            )
        for market, low in watched.items():
            high = counted.get(market)
            if high is None:
                raise ValueError(
                    f"{market!r} has a watch threshold ({low}) but no threshold to "
                    f"sit below; a band needs both ends"
                )
            if low >= high:
                raise ValueError(
                    f"watch threshold for {market!r} ({low}) must be below its "
                    f"threshold ({high}); the band is the gap between them"
                )
        if self.max_staleness_hours < self.lock_lead_hours:
            raise ValueError(
                f"max_staleness_hours ({self.max_staleness_hours}) must be at least "
                f"lock_lead_hours ({self.lock_lead_hours}); a bet cannot be dropped "
                f"for staleness inside the window that confirms it"
            )

    def counted(self) -> dict[str, int]:
        """Per-market cut at which a bet goes on the board and into the record."""
        return limits(self.threshold, self.markets)

    def watched(self) -> dict[str, int]:
        """Per-market floor of the watch band. Markets absent have no band."""
        return limits(self.watch_threshold, self.markets)

    def floor(self) -> dict[str, int]:
        """The lowest cut per market, so one pass fetches both tables' rows.

        Asking ``find_fades`` once at this floor and partitioning its output keeps
        a single definition of what qualifies; asking twice would run the rule
        twice and invite the two to drift.
        """
        watched = self.watched()
        return {m: min(c, watched.get(m, c)) for m, c in self.counted().items()}

    db: Path = field(default_factory=lambda: Path("data/fadepublic.db"))
    site: Path = field(default_factory=lambda: Path("docs"))
    # Tracked, unlike the database. A pre-kickoff ticket count cannot be
    # refetched once the game is over, so the settled history lives here.
    fade_log: Path = field(default_factory=lambda: Path("records/fade_log.json"))


def _cuts(raw, default: int) -> Threshold:
    """A TOML scalar or table, as an int or a per-market mapping.

    Both spellings are accepted so a single number still configures every market,
    which is what the college board and every test that predates per-market cuts
    rely on.
    """
    if raw is None:
        return default
    if isinstance(raw, Mapping):
        return {str(k): int(v) for k, v in raw.items()}
    return int(raw)


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path)
    if not path.exists():
        return Config()

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    root = path.resolve().parent
    fades = raw.get("fades") or {}
    paths = raw.get("paths") or {}

    # Bounds are validated by Config.__post_init__, so this just reads.
    return Config(
        threshold=_cuts(fades.get("threshold"), DEFAULT_THRESHOLD),
        watch_threshold=_cuts(fades.get("watch_threshold"), DEFAULT_WATCH_THRESHOLD),
        markets=tuple(fades.get("markets", ("spread", "total"))),
        season=int(raw.get("season", 2026)),
        lock_lead_hours=float(fades.get("lock_lead_hours", 2)),
        max_staleness_hours=float(fades.get("max_staleness_hours", 12)),
        db=root / paths.get("db", "data/fadepublic.db"),
        site=root / paths.get("site", "docs"),
        fade_log=root / paths.get("fade_log", "records/fade_log.json"),
    )
