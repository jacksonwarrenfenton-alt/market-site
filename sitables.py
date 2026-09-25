"""Covering hardest / building hardest, with the price context that matters.

A big change in shares short means nothing on its own. The question is always
"against what": a name covering hard while it sits above both moving averages is
a squeeze with the trend behind it; the same covering in a broken name is just
shorts giving up on a loser. So every row carries where price sits relative to
its 50- and 200-day, and its one-month move.

Two cuts, deliberately. ABOVE 50D AND 200D is the tradeable set. ALL NAMES is
the unfiltered read, because filtering before you have looked is how you miss
the thing that mattered.

Change z is standardised per name against its own settlement history, so a
volatile small cap and a mega cap are held to the same bar. Level z says whether
the resulting position is high or low in that name's own range -- a big build on
an already-crowded base is the interesting case, and only both columns together
show it.
"""
import pandas as pd, numpy as np, os, html
import floatdata as FD

D = os.path.expanduser("~/pos")
TOP = 12
MIN_SI = 250_000


def build():
    f = f"{D}/si_finra.parquet"
    if not os.path.exists(f): return None
    a = pd.read_parquet(f)
    a = a.assign(date=pd.to_datetime(a.settlementDate),
                 si=pd.to_numeric(a.currentShortPositionQuantity, errors="coerce"),
                 dtc=pd.to_numeric(a.daysToCoverQuantity, errors="coerce"))
    # FINRA uses 999.99 as a sentinel for "not meaningful" (no volume). Left in,
    # it becomes the top of every percentile and silently defines "crowded" as
    # "untradeable".
    a.loc[(a.dtc >= 100) | (a.dtc <= 0), "dtc"] = np.nan
    w = a.pivot_table(index="date", columns="symbolCode", values="si").sort_index()
    big = w.median()
    w = w[big[big >= MIN_SI].index]
    if len(w) < 6: return None
    chg = w.pct_change() * 100
    z = (chg - chg.mean()) / chg.std().replace(0, np.nan)
    lz = (w - w.mean()) / w.std().replace(0, np.nan)
    last = w.index.max()
    d = pd.DataFrame({
        "chg2w": chg.loc[last], "chg_z": z.loc[last], "level_z": lz.loc[last],
    }).dropna(subset=["chg_z"])
    d["si"] = w.loc[last].reindex(d.index)
    dt = a[a.date == last].drop_duplicates("symbolCode").set_index("symbolCode")
    d["dtc"] = dt.dtc.reindex(d.index)
    d["name"] = dt.issueName.reindex(d.index)

    # price context
    try:
        b = pd.read_parquet(f"{D}/bars_deep.parquet")
        c = b.pivot_table(index="date", columns="symbol", values="close").sort_index()
        ma50 = c.rolling(50, min_periods=25).mean().iloc[-1]
        ma200 = c.rolling(200, min_periods=100).mean().iloc[-1]
        px = c.iloc[-1]
        d["vs50"] = (100 * (px / ma50 - 1)).reindex(d.index)
        d["vs200"] = (100 * (px / ma200 - 1)).reindex(d.index)
        d["m1"] = (100 * (c.iloc[-1] / c.iloc[-22] - 1)).reindex(d.index)
    except Exception:
        d["vs50"] = d["vs200"] = d["m1"] = np.nan
    d.attrs["settle"] = str(last.date())
    return d


def _tbl(x, title, sub, flt):
    if x is None or not len(x):
        return f'<div><h5>{title}<span class="dim"> &middot; {sub}</span></h5>' \
               '<p class="dim">no names clear the bar this settlement</p></div>'
    def cell(v, fmt="{:+.1f}%", good=None):
        if v is None or not np.isfinite(v): return '<td class="dim">&ndash;</td>'
        cls = "" if good is None else ("up" if (v > 0) == good else "dn")
        return f'<td class="{cls}">{fmt.format(v)}</td>'
    def pf(i, si):
        pct = FD.pct_of_float(si, i, flt)
        return f'<td>{pct:.1f}%</td>' if np.isfinite(pct) else '<td class="dim">&ndash;</td>'
    rows = "".join(
        f'<tr><td class="nm">{html.escape(str(i))}</td>'
        f'<td class="nmw">{html.escape(str(r["name"] or "")[:26])}</td>'
        + cell(r.chg2w, "{:+.1f}%") + cell(r.chg_z, "{:+.2f}")
        + cell(r.level_z, "{:+.2f}") + pf(i, r.si)
        + (f'<td>{r.dtc:.1f}</td>' if np.isfinite(r.dtc) else '<td class="dim">&ndash;</td>')
        + cell(r.vs50, "{:+.1f}%", True) + cell(r.m1, "{:+.1f}%", True)
        + '</tr>' for i, r in x.iterrows())
    return (f'<div><h5>{title}<span class="dim"> &middot; {sub}</span></h5>'
            '<table class="sig si2"><thead><tr><th>Ticker</th><th>Name</th>'
            '<th>2w chg</th><th>Chg z</th><th>Level z</th><th>% float</th><th>DTC</th>'
            '<th>vs 50d</th><th>1M</th></tr></thead><tbody>'
            + rows + '</tbody></table></div>')


def html_panel():
    d = build()
    if d is None:
        return ""
    trend = d[(d.vs50 > 0) & (d.vs200 > 0)]
    cov_t = trend.nsmallest(TOP, "chg_z"); bld_t = trend.nlargest(TOP, "chg_z")
    cov_a = d.nsmallest(TOP, "chg_z");     bld_a = d.nlargest(TOP, "chg_z")
    syms = set(cov_t.index) | set(bld_t.index) | set(cov_a.index) | set(bld_a.index)
    try:
        flt = FD.get(symbols=syms)
    except Exception:
        flt = None
    return ('<h2>Short interest &mdash; covering and building hardest</h2>'
            f'<p class="grpnote">Settlement <b>{d.attrs["settle"]}</b>, '
            f'{len(d):,} names with at least {MIN_SI/1e3:.0f}k shares short. '
            '<b>Chg z</b> standardises each name&rsquo;s change against its own '
            'settlement history; <b>Level z</b> says whether the resulting '
            'position sits high or low in that name&rsquo;s own range. A big build '
            'on an already-crowded base is the interesting case, and only both '
            'columns together show it. <b>% float</b> is shares short against '
            'the actual tradeable float (shares outstanding minus insider/'
            'restricted stock), from stockanalysis.com &mdash; blank where no float '
            'data exists (mostly OTC/pink-sheet ADRs). Price columns are the '
            'context: covering in a name above both averages is a squeeze with '
            'the trend; the same covering in a broken name is shorts giving up.</p>'
            '<div class="si2grid">'
            + _tbl(cov_t, "Covering hardest", "above 50d and 200d", flt)
            + _tbl(bld_t, "Building hardest", "above 50d and 200d", flt)
            + _tbl(cov_a, "Covering hardest", "all names", flt)
            + _tbl(bld_a, "Building hardest", "all names", flt)
            + '</div>')
