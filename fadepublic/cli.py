"""Two commands: rebuild the board, and seed the record from finished weeks."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta

from .config import load_config
from .db import open_db
from .fades import find_fades
from .record import load_log, save_log, settle, tally
from .render import render_page
from .splits import fetch_splits, store_results, store_splits

log = logging.getLogger(__name__)


def cmd_refresh(args: argparse.Namespace) -> int:
    """Fetch the current splits, rebuild the board, regrade the record."""
    cfg = load_config(args.config)
    now = datetime.now(UTC)

    with open_db(cfg.db) as conn:
        fades: list = []
        watch: list = []
        games = fetch_splits()
        if games:
            store_splits(conn, games, now)
            store_results(conn, games)
            # One pass at the lower threshold, then split. Asking find_fades twice
            # would run the rule twice; partitioning its output keeps a single
            # definition of what qualifies and inherits its sort order for both
            # tables. The watch band is the gap between the two thresholds, so a
            # game cannot appear in both.
            qualifying = find_fades(
                games, threshold=cfg.watch_threshold, now=now, markets=cfg.markets
            )
            fades = [f for f in qualifying if f.public.tickets >= cfg.threshold]
            watch = [f for f in qualifying if f.public.tickets < cfg.threshold]
        else:
            # The feed is undocumented and not ours. An outage should empty the
            # board for one run, not take the record down with it.
            log.warning("No splits this run; the board will be empty")

        # The committed archive first: data/ is gitignored and the scheduled job
        # restores it from a cache that gets evicted, so without this a run on a
        # fresh checkout would grade an empty history.
        load_log(conn, cfg.fade_log)
        # The record is graded at cfg.threshold, never at cfg.watch_threshold, so
        # the watch band is structurally incapable of entering it.
        settled = settle(
            conn,
            threshold=cfg.threshold,
            markets=cfg.markets,
            lock_lead=timedelta(hours=cfg.lock_lead_hours),
            max_staleness=timedelta(hours=cfg.max_staleness_hours),
        )
        # No cap passed: the archive keeps every pre-kickoff reading it saw, even
        # ones currently too stale to grade. See save_log's docstring.
        save_log(conn, cfg.fade_log)

    cfg.site.mkdir(parents=True, exist_ok=True)
    target = cfg.site / "index.html"
    target.write_text(
        render_page(
            fades,
            cfg.threshold,
            settled,
            now,
            watch=watch,
            watch_threshold=cfg.watch_threshold,
            lock_lead=timedelta(hours=cfg.lock_lead_hours),
            max_staleness=timedelta(hours=cfg.max_staleness_hours),
        ),
        encoding="utf-8",
    )

    r = tally(settled)
    print(f"Page written to {target}")
    print(f"Board: {len(fades)} qualifying at {cfg.threshold}% of tickets")
    print(f"Watching: {len(watch)} between {cfg.watch_threshold}% and {cfg.threshold}%")
    print(f"Record: {r.label} over {len(settled)} settled bets", end="")
    print(f" ({r.outside_lock} outside the lock window)" if r.outside_lock else "")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Seed the record from weeks that finished before this existed.

    A completed week serves only its *closing* ticket counts, so these rows are
    stamped with each game's kickoff and flagged ``is_final`` -- graded through
    the ordinary path, but distinguishable from a genuine pre-kickoff reading,
    which the page says out loud.
    """
    cfg = load_config(args.config)
    weeks = [int(w) for w in args.weeks.split(",") if w.strip()]
    season = args.season or cfg.season

    with open_db(cfg.db) as conn:
        for week in weeks:
            games = fetch_splits(week=week, season=season)
            final = [g for g in games if g.final and g.kickoff_utc is not None]
            if not final:
                print(f"week {week}: nothing completed, skipped")
                continue
            for game in final:
                store_splits(conn, [game], fetched_at=game.kickoff_utc, is_final=True)
            store_results(conn, final)
            print(f"week {week}: {len(final)} completed games")

        load_log(conn, cfg.fade_log)
        settled = settle(
            conn,
            threshold=cfg.threshold,
            markets=cfg.markets,
            lock_lead=timedelta(hours=cfg.lock_lead_hours),
            max_staleness=timedelta(hours=cfg.max_staleness_hours),
        )
        # No cap passed: the archive keeps every pre-kickoff reading it saw, even
        # ones currently too stale to grade. See save_log's docstring.
        save_log(conn, cfg.fade_log)

    print(f"Record: {tally(settled).label} over {len(settled)} settled bets")
    for s in settled:
        print(f"  {s.game:12} {s.fade.line_label:14} {s.score:>7}  {s.result}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fade", description=__doc__)
    parser.add_argument("-c", "--config", default="config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_refresh = sub.add_parser("refresh", help="rebuild the board and publish it")
    p_refresh.set_defaults(func=cmd_refresh)

    p_back = sub.add_parser("backfill", help="seed the record from completed weeks")
    p_back.add_argument("--weeks", default="1,2,3", help="comma-separated, e.g. 1,2,3")
    p_back.add_argument("--season", type=int, default=None)
    p_back.set_defaults(func=cmd_backfill)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return args.func(args)
    except (LookupError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
