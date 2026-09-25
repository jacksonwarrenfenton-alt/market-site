"""Earnings-reaction breadth, by sector -- a ROLLING quarter, not a calendar
one. jman's own framing: don't reset the count on the calendar-quarter
boundary -- a name that reported in the tail of last quarter and one that
reported at the start of this quarter are part of the same earnings season
and should stay counted together. So the "current" read here is a trailing
~1-quarter (91 calendar day) window computed fresh every run with no fixed
start or end date -- it just slides forward.

History accumulates PERMANENTLY in earnrx.parquet (appended, never truncated
or overwritten wholesale) so the interactive chart can show this rolling-
quarter read as far back as this board has ever captured it. fetch() is
INCREMENTAL -- each run only re-walks a short overlap window plus whatever
new weekdays have passed since the last stored date, so it is cheap enough to
run inside every site rebuild instead of needing its own schedule.
backfill(days=...) is the one-time deep pull that seeds history further back
than this board has been running; it chunks its writes so a long backfill can
be interrupted and resumed without losing progress.

Sector comes from the custom roster's own naming convention -- every basket
in custom176-rosters.txt is already named "<Sector> - <subindustry>" (see
ROSTER_UPDATE_2026-08-29.md), so the prefix before " - " is the sector with
no separate mapping to maintain.
"""
import pandas as pd, numpy as np, os, sys, json
import earnings as EA

D = os.path.expanduser("~/pos")
OUT = f"{D}/earnrx.parquet"
ROLL_DAYS = 91          # ~1 calendar quarter, ROLLING -- never resets on a quarter boundary
OVERLAP_DAYS = 5        # re-check the last few days every run (late/corrected reactions)
BACKFILL_DAYS_DEFAULT = 3 * 365
CHUNK = 20              # weekdays per backfill write -- resumable if interrupted

PALETTE = ["#3987e5", "#e66767", "#1baf7a", "#fab219", "#9085e9", "#5ec8d8",
           "#eb6834", "#e0709a", "#c98a2b", "#898781", "#0ca30c", "#d03b3b"]


def _sector_map():
    p = f"{D}/custom176-rosters.txt"
    if not os.path.exists(p): return {}
    m = {}
    for line in open(p):
        line = line.strip()
        if not line or "|" not in line: continue
        name, syms = line.split("|", 1)
        sector = name.split(" - ")[0].strip()
        for t in syms.split(","):
            t = t.strip().upper()
            if t and t not in m: m[t] = sector
    return m


def _weekdays(start, end):
    d = pd.date_range(start, end, freq="D")
    return [x.strftime("%Y-%m-%d") for x in d if x.dayofweek < 5]


def _reactions_for_dates(dates):
    """dates: 'YYYY-MM-DD' weekday strings. Returns symbol/date/sector/chg rows
    for whichever of those dates had reports AND enough price history on both
    sides to compute a reaction -- a report from the last session or two has
    no "next session" yet and is silently skipped, picked up on a later run
    once that session exists."""
    rows = []
    for ds in dates:
        for r in EA._day(ds):
            sym = str(r.get("symbol") or "").upper()
            if not sym: continue
            rows.append({"date": ds, "symbol": sym,
                        "when": (r.get("time") or "").replace("time-", "")})
    if not rows: return None
    e = pd.DataFrame(rows).drop_duplicates(["symbol", "date"])

    import prices as P
    px = P.fetch_list(sorted(e.symbol.unique()))
    sect = _sector_map()

    out = []
    for _, r in e.iterrows():
        sym = r.symbol
        if sym not in px.columns: continue
        s = px[sym].dropna()
        rd = pd.Timestamp(r.date)
        # Before-open reports react same-session; after-close reports react
        # in the NEXT session.
        anchor = rd if r["when"] != "after-hours" else rd + pd.Timedelta(days=1)
        after = s[s.index >= anchor]
        before = s[s.index < anchor]
        if not len(after) or not len(before): continue
        chg = 100 * (after.iloc[0] / before.iloc[-1] - 1)
        if not np.isfinite(chg): continue
        out.append({"symbol": sym, "date": r.date,
                    "sector": sect.get(sym, "Unmapped"), "chg": round(float(chg), 2)})
    return pd.DataFrame(out) if out else None


def fetch(overlap_days=OVERLAP_DAYS):
    """Incremental refresh: walk from (last stored date - overlap) through
    today. Cheap -- meant to be called on every site rebuild, not scheduled
    separately."""
    today = pd.Timestamp.today().normalize()
    old = pd.read_parquet(OUT) if os.path.exists(OUT) else None
    if old is not None and len(old):
        start = pd.Timestamp(old.date.max()) - pd.Timedelta(days=overlap_days)
    else:
        start = today - pd.Timedelta(days=overlap_days)
    dates = _weekdays(start, today)
    new = _reactions_for_dates(dates)
    if new is None or not len(new):
        print("earnrx: no new reactions this run", file=sys.stderr, flush=True)
        return old
    if old is not None and len(old):
        d = pd.concat([old, new], ignore_index=True).drop_duplicates(
            ["symbol", "date"], keep="last")
    else:
        d = new
    d = d.sort_values(["date", "symbol"]).reset_index(drop=True)
    d.to_parquet(OUT)
    print(f"earnrx: {len(d):,} total reactions, {d.symbol.nunique():,} names, "
          f"{d.date.min()} -> {d.date.max()} ({len(new)} rows touched this run)",
          file=sys.stderr, flush=True)
    return d


def backfill(days=BACKFILL_DAYS_DEFAULT):
    """One-time deep pull covering the trailing `days` calendar days.

    Resumable by MISSING WEEKDAY, not just by oldest-date boundary -- early
    versions of this only compared floor vs. the stored min date, which looks
    "done" the instant any old date is on file even if there's an unfetched
    gap in the middle (e.g. incremental fetch() already seeded a recent
    island while an old backfill chunk seeded a separate older island,
    leaving the middle untouched). So: build the full target weekday list,
    subtract whatever dates are already stored, and only walk what's still
    missing -- in contiguous CHUNK-sized runs, writing after each so a long
    backfill can be killed and resumed without losing progress or re-fetching
    what it already has."""
    today = pd.Timestamp.today().normalize()
    old = pd.read_parquet(OUT) if os.path.exists(OUT) else None
    floor = today - pd.Timedelta(days=days)
    target = _weekdays(floor, today)            # list of 'YYYY-MM-DD' strings
    have = set(pd.to_datetime(old.date).dt.strftime("%Y-%m-%d")) if old is not None and len(old) else set()
    missing = [d for d in target if d not in have]
    if not missing:
        print(f"earnrx backfill: already have every weekday {floor.date()} -> {today.date()}, "
              "nothing to do", file=sys.stderr, flush=True)
        return old
    print(f"earnrx backfill: {len(missing)}/{len(target)} weekdays missing in "
          f"{floor.date()} -> {today.date()}, walking them in chunks of {CHUNK}",
          file=sys.stderr, flush=True)
    # group missing dates into contiguous runs so each write chunk fetches a
    # sensible block (an isolated single missing day still gets its own tiny
    # chunk rather than being batched miles away from its neighbors)
    ts = [pd.Timestamp(x) for x in missing]
    runs, cur = [], [missing[0]]
    for i in range(1, len(missing)):
        if (ts[i] - ts[i - 1]).days <= 3 and len(cur) < CHUNK:
            cur.append(missing[i])
        else:
            runs.append(cur); cur = [missing[i]]
    runs.append(cur)
    done = 0
    for chunk in runs:
        new = _reactions_for_dates(chunk)
        if new is not None and len(new):
            cur_d = pd.read_parquet(OUT) if os.path.exists(OUT) else None
            d = (pd.concat([cur_d, new], ignore_index=True) if cur_d is not None and len(cur_d) else new)
            d = d.drop_duplicates(["symbol", "date"], keep="last").sort_values(["date", "symbol"])
            d.to_parquet(OUT)
        done += len(chunk)
        print(f"  backfill {done}/{len(missing)} missing weekdays done "
              f"({chunk[0]} .. {chunk[-1]})", file=sys.stderr, flush=True)
    d = pd.read_parquet(OUT)
    print(f"earnrx backfill done: {len(d):,} reactions, {d.symbol.nunique():,} names, "
          f"{d.date.min()} -> {d.date.max()}", file=sys.stderr, flush=True)
    return d


def _rolling_table(d, asof=None, window=ROLL_DAYS):
    asof = pd.Timestamp(asof or d.date.max())
    dd = pd.to_datetime(d.date)
    win = d[(dd > asof - pd.Timedelta(days=window)) & (dd <= asof)]
    covered = win[win.sector != "Unmapped"]
    if not len(covered): return None
    g = covered.groupby("sector").apply(lambda x: pd.Series({
        "up": int((x.chg > 0).sum()), "down": int((x.chg < 0).sum()),
        "n": len(x), "med": float(x.chg.median())})).reset_index()
    g["net"] = g.up - g.down
    return g.sort_values("net", ascending=False)


def _weekly_series(d, window=ROLL_DAYS):
    """Weekly rolling-quarter net (up-down) per sector, as far back as
    accumulated history allows -- the line chart's data."""
    covered = d[d.sector != "Unmapped"].copy()
    if not len(covered): return None
    covered["date"] = pd.to_datetime(covered.date)
    weeks = pd.date_range(covered.date.min(), covered.date.max(), freq="W-FRI")
    if len(weeks) < 2: return None
    sectors = sorted(covered.sector.unique())
    series = {s: [] for s in sectors}
    for wk in weeks:
        win = covered[(covered.date > wk - pd.Timedelta(days=window)) & (covered.date <= wk)]
        for s in sectors:
            x = win[win.sector == s]
            series[s].append(float(len(x[x.chg > 0]) - len(x[x.chg < 0])) if len(x) else None)
    return weeks, sectors, series


def html_panel():
    if not os.path.exists(OUT): return ""
    d = pd.read_parquet(OUT)
    if d is None or not len(d): return ""

    g = _rolling_table(d)
    if g is None: return ""
    n_unmapped = int((d.sector == "Unmapped").sum())

    rows = "".join(
        f'<tr><td class="nm">{r.sector}</td>'
        f'<td data-sort="{int(r.up)}">{int(r.up)}</td>'
        f'<td data-sort="{int(r.down)}">{int(r.down)}</td>'
        f'<td class="{"up" if r.net > 0 else ("dn" if r.net < 0 else "")}" '
        f'data-sort="{int(r.net)}">{int(r.net):+d}</td>'
        f'<td class="dim" data-sort="{r.med:.2f}">{r.med:+.1f}%</td>'
        f'<td class="dim" data-sort="{int(r.n)}">{int(r.n)}</td></tr>'
        for _, r in g.iterrows())

    asof = pd.Timestamp(d.date.max())
    span_from = (asof - pd.Timedelta(days=ROLL_DAYS))
    note = (f' ({n_unmapped} names outside the roster excluded)' if n_unmapped else '')

    chart_html, span_txt = "", f"{d.date.min()} to {d.date.max()}"
    ws = _weekly_series(d)
    if ws is not None:
        weeks, sectors, series = ws
        specs = {"dates": [w.strftime("%b %y") for w in weeks], "zero": True, "mode": "raw",
                 "series": [{"name": s, "vals": series[s], "color": PALETTE[i % len(PALETTE)]}
                            for i, s in enumerate(sectors)]}
        chart_html = (
            '<div id="erx-chart" class="mc"></div>'
            '<script id="erxdata" type="application/json">'
            + json.dumps(specs, separators=(",", ":")) + '</script>'
            '<script>(function(){var G=JSON.parse(document.getElementById("erxdata").textContent);'
            'function go(){ if(!window.MC){ return setTimeout(go,40); } '
            'MC.mount("erx-chart", G); } go();})();</script>')
        span_txt = f"{weeks[0]:%b %Y} to {asof:%d %b %Y}"

    return (
        '<h2>Earnings-reaction breadth &mdash; by sector</h2>'
        f'<p class="grpnote">A <b>rolling</b> quarter (trailing {ROLL_DAYS} days as of '
        f'{asof:%d %b}), not a calendar one &mdash; a report from the tail of last '
        'quarter and one from the start of this quarter both stay counted together, '
        'so the read never resets on a fixed date. Every name that reported since '
        f'{span_from:%d %b}: did the stock get rewarded (higher the next session) or '
        'punished (lower)? Counted by <b>sector</b> &mdash; the prefix on the custom '
        'roster&rsquo;s basket names (&ldquo;Technology&rdquo;, &ldquo;Healthcare&rdquo;, '
        'etc.) &mdash; rather than by the 252 granular industry baskets, so one hot '
        f'subsector&rsquo;s cluster of prints cannot read as sector-wide strength{note}. '
        'Before-open reports react same-session; after-close reports react the next '
        'session. Refreshed daily.</p>'
        '<table class="sig sortable"><thead><tr><th>Sector</th><th>Rewarded</th>'
        '<th>Punished</th><th>Net</th><th>Median reaction</th><th>N</th></tr></thead>'
        '<tbody>' + rows + '</tbody></table>'
        + (('<h4 style="margin:16px 0 4px">Net reward/punish, rolling '
            f'{ROLL_DAYS}-day window, by sector over time</h4>'
            f'<p class="dnote">History as far back as this board has captured it '
            f'({span_txt}) &mdash; it grows one week at a time with every rebuild, plus '
            'whatever a one-time deep backfill added.</p>' + chart_html) if chart_html else ''))


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "backfill":
        d = backfill(days=int(_sys.argv[2]) if len(_sys.argv) > 2 else BACKFILL_DAYS_DEFAULT)
    else:
        d = fetch()
    print(d.shape if d is not None else "no data")
