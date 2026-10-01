# Fade the public

NFL games where **80% or more of the bet tickets** sit on one side of a spread
or total, with the other side named. A static page, rebuilt on a schedule and
published to GitHub Pages.

Tickets, not handle: a headcount, where a five-dollar parlay leg weighs the same
as a serious position. The gap between the two is the signal, so the money share
is printed beside the ticket share and left for the reader to interpret.

## The rule

- **Spreads and totals only**, at 80% of tickets.
- **A second band at 70% is displayed and never recorded.** The 80% cut is a
  cliff — a game at 79% is not meaningfully different evidence from one at 81% —
  but moving the cut would change what the record measures, and widening it would
  re-grade every past week. So the near misses sit in their own section under
  *Watching*, and the record is computed at 80 and never sees them.
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

Two bounds rather than one. Inside **two hours** of kickoff the public had
committed and the reading is what the rule aims for, so the bet is **confirmed**.
Between two and **twelve** hours it is still graded, but the row prints how far
out the deciding reading actually was, and the tally says how many came in that
way. Past twelve hours the reading predates gameday and the bet is dropped rather
than graded on a guess.

The earlier rule had a single four-hour bound and dropped everything past it,
which hid the distinction it was making: a bet decided forty minutes out and one
decided three hours out counted the same, while a bet decided four hours and one
minute out counted not at all — and since the scheduler is the thing that decides
which of those you get, the size of the record was mostly a fact about GitHub.
Annotating instead of dropping puts the evidence quality on the page per row, and
means a gap in the schedule costs precision rather than the bet.

The archive in `records/` is **not** bounded this way: it keeps every pre-kickoff
reading it saw, whatever its age. Deciding what to grade is a judgement that can
be revised later; deciding what to keep cannot.

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
.venv/bin/python -m pytest        # no network required
```

Tests run against captured real API responses in `fixtures/`, so they fail if
the undocumented endpoint changes shape — which is the point. One of them pins
the rule to a known-good outcome: week 3 of 2026 must select exactly MIA +9.5,
WAS +8.5, ARI +7.5 and over 54.5, the bets this rule actually produced that week
as reported independently of this code.

## Refresh cadence

The workflow asks in the windows before actual kickoffs rather than spreading its
asks evenly over the week: 564 asks a week against the old flat `*/15`
schedule's 672, with roughly three times the density in the hours that decide
whether a bet is confirmed, plus a two-hourly heartbeat that puts every kickoff
in the calendar within 1h59m of a scheduled ask.

That is a modest improvement, not a fix. GitHub drops scheduled runs under load,
and this project's own two measurements — an hourly cron delivering 11 runs in 43
hours, a `*/15` cron about 5 a day — suggest delivery is capped **per unit time
rather than per ask**, so four times the asking bought the same throughput.

To get a real cadence, drive `workflow_dispatch` from an external cron; manual
dispatches are not deprioritised the way schedules are. Roughly 25 calls a week
covers every game. **[CADENCE.md](CADENCE.md)** has the window table, the
copy-paste `curl`, the token scope it needs, and the gaps that are accepted on
purpose.
