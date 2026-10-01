"""The board as a standalone page, written to docs/ for GitHub Pages.

Static rather than interactive because the refresh runs unattended: the page has
to be rewritten by a cron job with no session behind it. One bookmarked URL,
always current.

Everything is inlined -- no external CSS, fonts or scripts -- so it renders
identically offline and cannot break because a CDN changed.
"""

from __future__ import annotations

import html
from datetime import UTC, datetime

from .record import tally

_STYLE = """
:root {
  --bg: #fbfbf9; --panel: #ffffff; --ink: #1a1a18; --muted: #6b6b64;
  --line: #e5e4de; --accent: #1f6f5c; --warn: #a8501e; --good: #1f6f5c;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #14140f; --panel: #1c1c18; --ink: #ecece4; --muted: #9a9a90;
    --line: #2e2e28; --accent: #6cc0a4; --warn: #d99257; --good: #6cc0a4;
  }
}
:root[data-theme="dark"] {
  --bg: #14140f; --panel: #1c1c18; --ink: #ecece4; --muted: #9a9a90;
  --line: #2e2e28; --accent: #6cc0a4; --warn: #d99257; --good: #6cc0a4;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--ink); margin: 0;
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  padding: 2rem 1.25rem 4rem;
}
.wrap { max-width: 760px; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0 0 .2rem; letter-spacing: -.01em; }
.stamp { color: var(--muted); font-size: .85rem; margin: 0 0 1.5rem; }
.panel {
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 1.1rem 1.2rem; margin-bottom: 1rem;
}
.panel h2 {
  font-size: .72rem; text-transform: uppercase; letter-spacing: .09em;
  color: var(--muted); margin: 0 0 .85rem; font-weight: 600;
}
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
/* Horizontal padding between columns, but flush at the table's own edges, so a
   right-aligned number does not run into the text of the next column. */
td, th { padding: .32rem .28rem; text-align: left; border-bottom: 1px solid var(--line); }
td:first-child, th:first-child { padding-left: 0; }
td:last-child, th:last-child { padding-right: 0; }
th { font-size: .68rem; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); }
tr:last-child td { border-bottom: 0; }
.num { text-align: right; }
.slot { color: var(--muted); font-size: .8rem; }
.good { color: var(--good); }
.conflict { color: var(--warn); }
.note { color: var(--muted); font-size: .82rem; margin-top: .8rem; }
.scroll { overflow-x: auto; }
/* Cells here are short -- a team pair, a percentage, a line -- so the table has
   a low floor and the sub-lines below keep the Bet column, the only cell there
   is to act on, on screen at 390px. As six columns it was pushed off entirely. */
.scroll table.fade { min-width: 19rem; }
.fade td { white-space: nowrap; }
.fade td.pub { white-space: normal; }
.fade .detail { display: block; font-size: .8rem; color: var(--muted); }
/* The record reads before the board does: it is the reason to trust or ignore
   everything under it. */
.record { display: flex; align-items: baseline; gap: .6rem; margin: 0 0 .2rem; }
.record .tally {
  font-size: 1.9rem; font-weight: 650; letter-spacing: -.02em;
  font-variant-numeric: tabular-nums;
}
.record .recsub { color: var(--muted); font-size: .85rem; margin: 0; }
.logh {
  font-size: .78rem; text-transform: uppercase; letter-spacing: .08em;
  color: var(--muted); margin: 1.6rem 0 .4rem;
}
"""

# Kept out of the f-string template: JavaScript braces collide with f-string
# interpolation, and escaping every one of them is a needless hazard.
_SCRIPT = """<script>
// Countdowns are recomputed in the browser from absolute kickoff times, so the
// page stays correct between scheduled refreshes. Without this the publisher
// would have to rewrite and commit the page every hour purely to keep a
// relative time honest. Server-rendered text remains the no-JavaScript
// fallback.
(function () {
  function label(ms) {
    if (ms <= 0) return "started";
    var m = Math.floor(ms / 60000), d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60);
    if (d) return d + "d " + h + "h";
    if (h) return h + "h " + (m % 60) + "m";
    return m + "m";
  }
  function tick() {
    var now = Date.now();
    document.querySelectorAll("[data-kickoff]").forEach(function (el) {
      var t = Date.parse(el.getAttribute("data-kickoff"));
      if (!isNaN(t)) el.textContent = label(t - now);
    });
  }
  tick();
  setInterval(tick, 30000);
})();
</script>"""


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _record_strip(settled) -> str:
    """How the rule has actually done, above the board rather than below it.

    One merged number. Some of it was graded from closing ticket counts rather
    than a pre-kickoff reading, because a finished week is all the feed still
    serves -- said plainly underneath instead of split into a second total,
    since the figure to act on is the whole record.
    """
    if not settled:
        return (
            '<p class="note">No bet has settled yet. The record starts once a '
            "game that qualified near kickoff has finished.</p>"
        )

    r = tally(settled)
    bits = []
    if r.win_rate is not None:
        bits.append(f"{r.win_rate:.0%}")
    bits.append(f"{r.units:+.1f}u at -110")
    sub = " &middot; ".join(bits)

    n = len(settled)
    if r.from_final_tally == n:
        basis = (
            f"All {n} were graded from the closing ticket count rather than a "
            "pre-kickoff reading, which is all the feed still serves for a "
            "finished week"
        )
    elif r.from_final_tally:
        basis = (
            f"{r.from_final_tally} of {n} were graded from the closing ticket "
            "count rather than a pre-kickoff reading, and are marked below"
        )
    else:
        basis = f"{n} settled bets"

    return (
        f'<div class="record"><span class="tally">{r.label}</span>'
        f'<span class="recsub">{sub}</span></div>'
        f'<p class="note">{_esc(basis)}. A bet is decided by the last snapshot '
        f"within 4 hours of kickoff, so a game that fell off the board during "
        f"the week is never counted.</p>"
    )


def _settled_table(settled) -> str:
    """Every graded bet, newest first -- the log the record is computed from."""
    if not settled:
        return ""

    # Marking the basis per row only says something once the record holds both
    # kinds. While every row is a closing count the strip above has already said
    # so, and repeating it twenty times is noise on a phone.
    finals = sum(s.from_final_tally for s in settled)
    mixed = 0 < finals < len(settled)

    rows = []
    for s in reversed(settled):
        cls = {"win": "good", "loss": "conflict"}.get(s.result, "slot")
        when = f"{s.fade.kickoff_utc:%b %-d}" if s.fade.kickoff_utc else ""
        flag = (
            '<span class="detail">closing count</span>'
            if mixed and s.from_final_tally
            else ""
        )
        # Result sits under the score rather than in a column of its own: at
        # 360px a fourth column pushed the table past its pane, and "34-31"
        # with "win" beneath it is how the rest of this board already reads.
        rows.append(
            f"<tr><td>{_esc(s.game)}"
            f'<span class="detail">{_esc(when)}</span></td>'
            f"<td>{_esc(s.fade.line_label)}"
            f'<span class="detail">public {_esc(s.fade.public.side)} '
            f"{s.fade.public.tickets}%</span>{flag}</td>"
            f'<td class="num">{_esc(s.score)}'
            f'<span class="detail {cls}">{s.result}</span></td></tr>'
        )

    return (
        f'<h3 class="logh">Settled</h3>'
        f'<div class="scroll"><table class="fade">'
        f"<tr><th>Game</th><th>Bet</th><th>Score</th></tr>"
        f'{"".join(rows)}</table></div>'
    )


def render_board(fades, threshold: int = 80, settled=None) -> str:
    """Games where the tickets are lopsided enough for the rule to fire.

    Both sides are shown with their ticket shares, and the bet is spelled out
    rather than implied. That began as a hedge -- the feed reports the under
    ahead on tickets in most games, which inverts the best-documented bias in
    betting, so the labels looked transposed. They are not; see ``splits.py``.
    Printing "under 93% / over 7% -> bet OVER" is what made that a glance rather
    than a project, so it stays: the next such question costs one look.
    """
    settled = list(settled or [])
    strip = _record_strip(settled)
    log = _settled_table(settled)

    if not fades:
        return (
            f'<div class="panel">{strip}'
            f'<p>No spread or total is currently carrying {threshold}% or more of '
            f"the tickets on one side.</p>"
            f'<p class="note">The board fills as kickoff approaches, so this is '
            f"usually empty early in the week.</p>{log}</div>"
        )

    rows = []
    for f in fades:
        # Kickoff rides under the game rather than in a column of its own: it is
        # a property of the game, and the header "Kickoff" was itself the widest
        # thing in that column, pushing the bet off a phone screen. Absolute
        # here, rewritten to a countdown by the script, so two consecutive
        # refreshes still differ only in the timestamp line.
        when = (
            f'<span class="detail" data-kickoff="{f.kickoff_utc.isoformat()}">'
            f"{_esc(f'{f.kickoff_utc:%a %H:%M}')}</span>"
            if f.kickoff_utc
            else ""
        )
        # The money share is reported and left to the reader. It used to carry a
        # verdict beside it -- "money agrees" / "money lags N" -- which said less
        # than the number did and split its colour at exactly zero, so an
        # 82-against-83 noise gap was drawn in the green reserved for a real
        # divergence. The market column went too: "over 47.5" already says it is
        # a total, and on a phone those columns pushed the bet off screen.
        detail = (
            f'<span class="detail">{f.public.money}% of money</span>'
            if f.public.money is not None
            else ""
        )
        odds = f'<span class="detail">{f.bet.odds:+d}</span>' if f.bet.odds else ""
        rows.append(
            f"<tr><td>{_esc(f.game)}{when}</td>"
            f'<td class="pub">{_esc(f.public.side)} <b>{f.public.tickets}%</b>{detail}</td>'
            f"<td><b>{_esc(f.line_label)}</b>{odds}</td></tr>"
        )

    return (
        f'<div class="panel">{strip}'
        f'<div class="scroll"><table class="fade">'
        f"<tr><th>Game</th><th>Public is on</th><th>Bet</th></tr>"
        f'{"".join(rows)}</table></div>'
        f'<p class="note">Spreads and totals only, at {threshold}% of '
        f"<b>tickets</b> -- a headcount, not money. Moneylines are excluded: they "
        f"reach this threshold almost automatically, because everyone takes the big "
        f"favourite for a small payout.</p>"
        f'<p class="note">Recomputed every refresh, so anything that stops '
        f"qualifying disappears on its own. <b>This is a log, not advice.</b> The "
        f"record below is a thin sample, and the rule was found on the same weeks "
        f"it is scored against -- the ordinary way a number like it appears and "
        f"then evaporates.</p>"
        f'<p class="note">The under leads tickets in most games here -- 52 of 64 '
        f"sampled -- which inverts the usual public bias, so the direction was "
        f"checked rather than trusted. It holds: on 30 Sep two live totals pointing "
        f"opposite ways each matched an independent public board exactly, money "
        f"share included. Why the crowd sits on unders is unexplained, but the "
        f"labels are not the reason. Both sides are printed so the next check stays "
        f"a glance.</p>{log}</div>"
    )


def render_page(fades, threshold: int = 80, settled=None, generated_at=None) -> str:
    """The whole document."""
    stamp = (generated_at or datetime.now(UTC)).strftime("%a %-d %b %H:%M UTC")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Fade the public</title>
<style>{_STYLE}</style>
</head>
<body>
<div class="wrap">
  <h1>Fade the public</h1>
  <p class="stamp">Updated {stamp}</p>
  {render_board(fades, threshold, settled)}
</div>
{_SCRIPT}
</body>
</html>
"""
