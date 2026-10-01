# Fade the public

NFL games where **80% or more of the bet tickets** sit on one side of a spread
or total, with the other side named. A static page, rebuilt on a schedule and
published to GitHub Pages.

Tickets, not handle: a headcount, where a five-dollar parlay leg weighs the same
as a serious position. The gap between the two is the signal, so the money share
is printed beside the ticket share and left for the reader to interpret.

## The rule

- **Spreads and totals only**, at 80% of tickets.
- **Moneylines are excluded.** They reach any threshold almost automatically,
  because everyone takes the big favourite for a small payout, so the threshold
  stops discriminating. Over three weeks the rule fired on 35 moneylines at a
  34% win rate against 8 spreads — mostly a statement about which market the
  filter lands on rather than about the public being wrong.
- **Games already under way drop off.** The rule is about a price you can still
  take.
- The board is **recomputed from scratch every run**, so a game that stops
  qualifying simply stops appearing. There is no stale row to remove and nothing
  to go out of sync.

## The record

A tally sits above the board. It is **derived, never accumulated**: every
refresh appends what it saw to `betting_splits` with a timestamp, so for any
finished game the question "was this bet on?" has one answer that can be
recomputed from scratch — and is, on every run. Raising the threshold re-grades
every past week for free.

The deciding reading is **the last snapshot at or before kickoff**. That makes
"it fell off the board during the week" enforce itself with no bookkeeping: a
game carrying 85% of tickets on Tuesday that has drifted to 70% by Sunday is not
lopsided in its own gameday snapshot, so it never enters the record. A reading
taken after kickoff is never used — by then the tickets include people betting
the live game.

Past **four hours** from kickoff a reading is not evidence about gameday at all,
and the bet is dropped rather than graded on a guess. A smaller honest record
beats a larger invented one.

### Why `records/` is committed and `data/` is not

`data/` is gitignored and the scheduled job restores it from a GitHub Actions
cache. That is fine for everything except one thing: a **pre-kickoff** ticket
count cannot be refetched, because once a game is over the feed serves only its
closing tally. An evicted cache would silently downgrade the season's record to
closing tallies with nothing on the page to show it.

So the reading that decided each settled bet is mirrored to
`records/fade_log.json`, which is tracked. `fade refresh` loads it before
grading and writes it back after. A clone with no database reproduces the record
exactly.

It stores **snapshots, not verdicts** — which reading decides depends only on
time, never on the threshold — so history stays re-gradeable. A game is archived
as soon as its kickoff passes rather than when the score lands, so a cache
eviction can cost at most one refresh interval.

## What this is not

**It is a log, not a claim of edge.** The record opened at 16-4 over 2026 weeks
1-3, which is twenty bets: the 95% interval runs roughly 54% to 88% against a
52.4% break-even, so the lower bound clears the hurdle only barely. Worse, the
rule was found on the very weeks it is scored against — the ordinary way a
number like this appears and then evaporates. The forward record is the only
thing that will settle it.

Weeks 1-3 were seeded with `fade backfill`, and those rows are graded from each
game's **closing** ticket count, because a finished week is all the feed still
serves. Live rows use a genuine pre-kickoff reading. The page says which is
which once the record holds both.

## One oddity worth knowing

This feed reports the **under** ahead on tickets in 52 of 64 sampled games,
which inverts the best-documented bias in betting. That looked like transposed
labels, so it was checked: two live totals pointing in opposite directions each
matched an independent public board exactly, money share included, and a
full-slate comparison against a second provider agreed on all 16 totals. The
labels are right. Why the crowd sits on unders is a real question and an open
one.

These percentages are **provider-dependent** — each source counts only its own
partner books — which bounds what any record can prove. Both sides and their
shares stay on the page so the next such check costs one glance.

## Data source

| Source | Used for | Auth |
| --- | --- | --- |
| Action Network web scoreboard | ticket and money splits, final scores | none |

Undocumented and not ours, so it is wrapped behind one module (`splits.py`) with
fixture-backed tests. Any failure empties the board for a run rather than taking
the record down with it.

## Usage

```bash
pip install -e .

fade refresh                      # rebuild the board and the record
fade backfill --weeks 1,2,3       # seed the record from completed weeks
```

```bash
.venv/bin/python -m pytest        # 44 tests, no network required
```

Tests run against captured real API responses in `fixtures/`, so they fail if
the undocumented endpoint changes shape — which is the point. One of them pins
the rule to a known-good outcome: week 3 of 2026 must select exactly MIA +9.5,
WAS +8.5, ARI +7.5 and over 54.5, the bets this rule actually produced that week
as reported independently of this code.

## Refresh cadence

The workflow asks every fifteen minutes. GitHub delivers about five runs a day —
scheduled workflows are best-effort and dropped under load, not queued. Since a
bet needs a reading within four hours of kickoff, sparse delivery drops bets
rather than mis-grading them.

To get a real cadence, drive the `workflow_dispatch` trigger from an external
cron; manual dispatches are not deprioritised the way schedules are. NFL
kickoffs cluster tightly enough — Thursday ~20:15 ET, Sunday 13:00/16:05/16:25/
20:20, Monday 20:15 — that firing every 30 minutes inside those windows covers
every game in about 25 calls a week.
