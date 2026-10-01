"""Settings, read from config.toml beside the repo root."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # Share of *tickets* -- a headcount, not money -- that makes a side "the
    # public" and puts the other side on the board.
    threshold: int = 80
    # Moneylines are deliberately absent: they reach any threshold almost
    # automatically, because everyone takes the big favourite for a small
    # payout. See fades.py.
    markets: tuple[str, ...] = ("spread", "total")
    season: int = 2026

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
    return Config(
        threshold=int(fades.get("threshold", 80)),
        markets=tuple(fades.get("markets", ("spread", "total"))),
        season=int(raw.get("season", 2026)),
        db=root / paths.get("db", "data/fadepublic.db"),
        site=root / paths.get("site", "docs"),
        fade_log=root / paths.get("fade_log", "records/fade_log.json"),
    )
