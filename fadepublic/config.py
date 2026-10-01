"""Settings, read from config.toml beside the repo root."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .fades import DEFAULT_THRESHOLD, DEFAULT_WATCH_THRESHOLD


@dataclass(frozen=True)
class Config:
    # Share of *tickets* -- a headcount, not money -- that makes a side "the
    # public" and puts the other side on the board.
    threshold: int = DEFAULT_THRESHOLD
    # A second, lower band that is shown on the page and never graded. It exists
    # because the 80% cut is a cliff: a game at 79% is indistinguishable from one
    # at 81% as evidence, but only one of them was visible. Displaying the near
    # misses without recording them keeps the record's definition unchanged.
    watch_threshold: int = DEFAULT_WATCH_THRESHOLD
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
        if self.watch_threshold >= self.threshold:
            raise ValueError(
                f"watch_threshold ({self.watch_threshold}) must be below threshold "
                f"({self.threshold}); the watch band is the gap between them"
            )
        if self.max_staleness_hours < self.lock_lead_hours:
            raise ValueError(
                f"max_staleness_hours ({self.max_staleness_hours}) must be at least "
                f"lock_lead_hours ({self.lock_lead_hours}); a bet cannot be dropped "
                f"for staleness inside the window that confirms it"
            )

    db: Path = field(default_factory=lambda: Path("data/fadepublic.db"))
    site: Path = field(default_factory=lambda: Path("docs"))
    # Tracked, unlike the database. A pre-kickoff ticket count cannot be
    # refetched once the game is over, so the settled history lives here.
    fade_log: Path = field(default_factory=lambda: Path("records/fade_log.json"))


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
        threshold=int(fades.get("threshold", DEFAULT_THRESHOLD)),
        watch_threshold=int(fades.get("watch_threshold", DEFAULT_WATCH_THRESHOLD)),
        markets=tuple(fades.get("markets", ("spread", "total"))),
        season=int(raw.get("season", 2026)),
        lock_lead_hours=float(fades.get("lock_lead_hours", 2)),
        max_staleness_hours=float(fades.get("max_staleness_hours", 12)),
        db=root / paths.get("db", "data/fadepublic.db"),
        site=root / paths.get("site", "docs"),
        fade_log=root / paths.get("fade_log", "records/fade_log.json"),
    )
