# Refresh cadence

How often the board actually refreshes, and how to make it refresh when it matters.

This file lives at the repository root rather than in `docs/`. `docs/` is the
published Pages directory and the refresh job diffs it to decide whether to commit,
so a note in there would be served as a web page and would churn the board's commit
gate every time it was edited.

## What the schedule asks for, and what GitHub delivers

Scheduled workflows are **best-effort**. GitHub drops them under load rather than
queuing them, and the drop rate is high enough to be the main thing deciding how
good a reading the record gets.

Two measurements from this project:

| Asked | Delivered | Throughput |
| --- | --- | --- |
| hourly | 11 runs in 43 hours | ~0.26/hour |
| every 15 min | ~5 runs a day | ~0.21/hour |

Four times the asking for the same throughput. That is the important fact: delivery
looks capped **per unit time, not per ask**, so asking more often does not
proportionally buy more runs. It only makes a missed slot cost minutes instead of
hours.

## What the schedule does about it

`.github/workflows/refresh.yml` concentrates its asks in the windows before actual
kickoffs instead of spreading them evenly over the week — 564 asks a week against the
old flat schedule's 672, with roughly three times the density in the hours that
decide whether a bet is confirmed.

Cron in GitHub Actions is **UTC only**; it does not honour `CRON_TZ`. Every window is
therefore the union of its EDT (UTC−4) and EST (UTC−5) placements, which is why each
looks about an hour wider than the kickoff needs.

| Window (UTC) | Covers |
| --- | --- |
| Sun `0-2,10-23` | Saturday-night tail, then the full Sunday card (09:30 ET international → 20:20 ET) |
| Mon `0-2,21-23` | Sunday-night tail, then Monday night (21 catches a 19:15 ET kickoff under EDT) |
| Tue `0-2` | Monday-night tail |
| Thu `22-23` | Thursday night |
| Fri `0-2` | Thursday-night tail |
| Sat `15-23` | Late-season Saturday slate |
| `17 */2 * * *` | Heartbeat |

The heartbeat is every **two** hours deliberately. At :17 of every even hour, no
kickoff in the calendar is more than 1h59m from a scheduled ask — inside the
two-hour lock window — so even a game with no dense window can be confirmed if its
heartbeat run is delivered.

### Known gaps, accepted on purpose

Thanksgiving's two daytime games, Black Friday, and Christmas when it falls midweek
(it is a **Friday** in 2026) have no standing windows. Giving them one would cost
~84 asks a week all season for three games a year. They fall through to the
heartbeat, and because the record now annotates a stale reading instead of dropping
the bet, missing them costs the *confirmed* label rather than the bet itself.

If you want those games locked, fire a dispatch by hand on the day.

## The actual fix: drive it from an external cron

`workflow_dispatch` is **not** deprioritised the way `schedule` is. A manual dispatch
runs when you ask for it. Driving it from anything with a reliable clock gets a real
cadence for about 25 calls a week.

```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/thanejohannsen/fadepublic/actions/workflows/refresh.yml/dispatches \
  -d '{"ref":"main"}'
```

Notes on that call:

- `"ref"` is **mandatory**. Use the default branch — `schedule` only ever fires from
  the default branch, so anything else is not a schedule-equivalent run.
- `$GH_TOKEN` needs a fine-grained PAT with **Actions: write** on this repository.
  Nothing else.
- A 204 with an empty body is success.

Firing every 30 minutes inside the kickoff windows covers every game in roughly 25
calls a week, because a bet only needs one reading inside the lock window.

## Two things that look like problems and are not

**Cancelled runs.** `concurrency: {group: refresh, cancel-in-progress: false}` keeps
only one pending run per group, so when the scheduler delivers a backlog burst the
surplus runs are cancelled rather than queued. At 12 asks an hour expect to see
some. They are not failures.

**No commit on most runs.** The publish step skips any change that only moved the
timestamp, so a delivered run that found nothing new makes no commit. That is
working as intended — but note the consequence: GitHub disables scheduled workflows
after 60 days of repository inactivity, and an off-season with an empty board makes
no commits at all. Re-enable the schedule, or dispatch once, before a season starts.
