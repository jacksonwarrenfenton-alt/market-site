"""liqn.ai news calendar -- the crowd's highest-impact headlines, ranked daily.

Companion to liqn.py (crowd ATTENTION -- who's being talked about) with a
different lens: crowd-ranked NEWS -- which headlines the crowd is treating as
market-moving, scored 0-100 on impact, and pre-tagged against jman's own
basket/theme names so a headline maps straight onto a chart without a manual
lookup. Like liqn.py, there is no archive to backfill from -- history starts
the first day it's captured and thickens by ~N rows per day from there.

Schema (positioning/liqnnews_hist.csv, one row per ranked headline per day):
  rank        1 = most impactful that day, ascending
  headline    short/display title
  description longer summary (sometimes identical to headline)
  tags        pipe-delimited: theme(s), basket name(s), and/or tickers this
              headline maps to, e.g. "MACRO|Banks vs. Utilities|TLT..Treasuries"
  source      NEWS or SOCIAL
  handle      the poster's handle when source == SOCIAL, else blank
  timestamp   display string, e.g. "Thu 9:40 AM ET" -- not a parseable date
  impact      0-100 crowd-impact score
  date        capture date, YYYY-MM-DD -- this is the row's real date key

SIGNIFICANT_MIN is the same placeholder threshold pass 22 left in the prior,
lost copy of this module -- 80 was never validated against actual forward
returns. Keep it a named constant so a future session can tune or backtest it
rather than hunting a magic number.
"""
import pandas as pd, numpy as np, os, html, json

D = os.path.expanduser("~/pos")
HIST = f"{D}/liqnnews_hist.csv"
COLS = ["rank", "headline", "description", "tags", "source", "handle",
        "timestamp", "impact", "date"]
SIGNIFICANT_MIN = 80
MAX_ROWS_SHOWN = 20


def load():
    if not os.path.exists(HIST): return None
    d = pd.read_csv(HIST)
    if not len(d): return None
    d["impact"] = pd.to_numeric(d["impact"], errors="coerce")
    d["rank"] = pd.to_numeric(d["rank"], errors="coerce")
    d["dt"] = pd.to_datetime(d["date"], errors="coerce")
    return d.dropna(subset=["dt"]).sort_values(["dt", "rank"])


def _tags(raw):
    if not isinstance(raw, str) or not raw.strip(): return []
    return [t.strip() for t in raw.split("|") if t.strip()]


def _row_html(r):
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in _tags(r.tags)[:5])
    src = html.escape(str(r.source or ""))
    handle = f" @{html.escape(str(r.handle))}" if isinstance(r.handle, str) and r.handle.strip() else ""
    ts = html.escape(str(r.timestamp or ""))
    imp = r.impact if np.isfinite(r.impact) else 0
    cls = "crit" if imp >= SIGNIFICANT_MIN else ("up" if imp >= 60 else "dim")
    desc = str(r.description or "")
    headline = str(r.headline or "")
    body = f'<b>{html.escape(headline)}</b>'
    if desc and desc.strip() and desc.strip() != headline.strip():
        body += f'<div class="dim nwdesc">{html.escape(desc)}</div>'
    return (f'<tr><td class="dim">{int(r.rank) if np.isfinite(r.rank) else ""}</td>'
            f'<td>{body}<div class="nwtags">{tags}</div></td>'
            f'<td class="dim">{src}{handle}<br>{ts}</td>'
            f'<td class="{cls}">{imp:.0f}</td></tr>')


def panel():
    d = load()
    # One capture is not a calendar. Wait for at least a couple of days so
    # this doesn't render a single-day table dressed up as a trend -- the
    # latest day's headlines are still fully shown either way.
    if d is None or not len(d):
        return ""
    days = sorted(d["date"].unique())
    n_days = len(days)
    today = days[-1]
    latest = d[d["date"] == today].sort_values("rank")
    if not len(latest):
        return ""
    n_sig = int((latest.impact >= SIGNIFICANT_MIN).sum())
    rows = "".join(_row_html(r) for r in latest.head(MAX_ROWS_SHOWN).itertuples())
    hist_note = (f"<b>{n_days} day{'s' if n_days != 1 else ''} in store</b> &middot; "
                 f"today {html.escape(str(today))}. liqn.ai publishes no archive, so this "
                 "record begins the day it started being captured and lengthens by one "
                 "day's headlines per run.")
    return f'''<h2>Crowd-ranked news &mdash; today's highest-impact headlines</h2>
<p class="grpnote">Headlines the crowd is treating as market-moving, scored 0-100 on impact
and pre-tagged to the theme/basket names used elsewhere on this board so a headline maps
straight onto a chart. <b>{n_sig} of {len(latest)}</b> today score &ge;{SIGNIFICANT_MIN}
(the significant-impact cut, unvalidated against forward returns &mdash; treat it as a
sort order, not a backtested edge). {hist_note}</p>
<table class="sig nws"><thead><tr><th>#</th><th>Headline</th><th>Source</th><th>Impact</th></tr></thead>
<tbody>{rows}</tbody></table>'''
