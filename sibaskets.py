"""Short interest by BASKET across recent settlements, plus the absolute extremes.

What was missing before this module
-----------------------------------
Every short-interest panel on the board ranked names by CHANGE over ONE
settlement: `sitables.py` (covers/builds with a per-name z), `report.si_section`
(z-ranked and raw-%), `etfsi.py` (a curated ETF list). `si_market.parquet` was
the only multi-settlement view and it collapses the entire market to a single
chain-linked line.

So two questions the board could not answer:

* **Which baskets is the crowd shorting, and for how long?** A single 2w/2w
  change cannot separate "one settlement of noise" from "six straight
  settlements of shorts building in the same group". Group-level aggregation
  across settlements is the read jman actually wants -- shorting as a *theme*,
  not a name.
* **Where is short interest highest outright?** Every existing rank is a
  derivative. `level_z` is a name against its OWN history, which is not the same
  as being top of the board, and neither answers "which names sit at a record
  short position".

Why this is only now trustworthy
--------------------------------
`sifinra.dates()` asked FINRA for the calendar 15th of each month. When the 15th
is a weekend the settlement lands on the preceding business day, the API returned
zero rows, and the collector silently skipped it -- **30 of 94 settlements were
missing, at irregular intervals.** Multi-settlement arithmetic on that history
was worse than useless: a "3-settlement change" was sometimes a 5-settlement
change, and nothing said which. The gap is fixed and backfilled, so a fixed
number of settlements back is now a fixed amount of calendar time.

Composition safety
------------------
The panel is not a constant set of names. Symbols enter and leave FINRA's file,
and the screened universe changes. So **every change here is computed on the
intersection of symbols present at BOTH endpoints**, the same discipline
`si_market` uses -- otherwise a group gaining two members prints as a short
build. The member count behind each reading is shown, and any group whose
overlap falls below a floor is dropped rather than quietly estimated.
"""
import os, html, json
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")
SRC = f"{D}/si_finra.parquet"
ROSTER = f"{D}/custom176-rosters.txt"
OUT = f"{D}/si_baskets.parquet"

MIN_MEMBERS = 3        # a "basket" read off 2 names is a name, not a basket
MIN_OVERLAP = 3        # and a change needs that many names at both endpoints
TOP_N = 15


def load():
    """Long frame: date, symbol, si, dtc, adv. One row per symbol-settlement."""
    if not os.path.exists(SRC):
        return None
    a = pd.read_parquet(SRC, columns=[
        "settlementDate", "symbolCode", "currentShortPositionQuantity",
        "daysToCoverQuantity", "averageDailyVolumeQuantity"])
    a = a.rename(columns={"symbolCode": "symbol",
                          "currentShortPositionQuantity": "si",
                          "daysToCoverQuantity": "dtc",
                          "averageDailyVolumeQuantity": "adv"})
    a["date"] = pd.to_datetime(a.settlementDate)
    for c in ("si", "dtc", "adv"):
        a[c] = pd.to_numeric(a[c], errors="coerce")
    a = a.dropna(subset=["si"])
    # FINRA's 999.99 is a sentinel for undefined (ADV ~ 0), not a thousand days.
    # Left in place it wins every days-to-cover ranking by default.
    a.loc[a.dtc >= DTC_SENTINEL, "dtc"] = np.nan
    # One row per symbol per settlement. FINRA can carry a symbol on more than
    # one market class; summing would double-count the same short position.
    return (a.sort_values(["date", "symbol", "si"])
             .drop_duplicates(["date", "symbol"], keep="last")
             [["date", "symbol", "si", "dtc", "adv"]])


def screened():
    """The same screened universe every other panel on this board uses
    (mcap >= $300M, real common stock, price > $1).

    Without this the extremes tables are worthless. FINRA's file covers ~19,000
    symbols including foreign ordinaries and OTC ADRs, and those dominate every
    absolute ranking: the first cut of "highest days to cover" returned AACAF,
    AAGR, AALBF, AANNF -- alphabetical order among names all tied at FINRA's
    **999.99 sentinel**, which does not mean a thousand days to cover, it means
    average daily volume is ~zero so the ratio is undefined. Those are not
    squeeze candidates, they are untradeable listings.
    """
    try:
        import breadth as BR
        u = BR.universe()
        if u is not None and len(u):
            return set(u.symbol.astype(str).str.upper())
    except Exception:
        pass
    return None


DTC_SENTINEL = 999.0      # FINRA writes 999.99 when ADV is ~0; not a real ratio
MIN_ADV = 50_000          # and a days-to-cover read needs real volume behind it


def group_map():
    """{symbol: basket}. jman's custom176 roster is the intended grouping; the
    exchange sector is NOT used as a fallback because mixing two different
    groupings in one table makes the ranks incomparable."""
    if not os.path.exists(ROSTER):
        return {}
    m = {}
    for line in open(ROSTER):
        if "|" not in line:
            continue
        g, syms = line.split("|", 1)
        g = g.strip()
        for s in syms.strip().split(","):
            s = s.strip().upper()
            if s:
                m[s] = g
    return m


def build(settlements=(1, 3, 6), save=True):
    """Per-basket short-interest level and change over N settlements back.

    Returns (frame, meta). Change over k settlements is computed on the symbols
    present at both ends, so it is a real position change and not composition.
    Two readings per horizon, deliberately:
      * `sum_<k>`  -- change in TOTAL shares short across the overlap. This is
        where the money is, and it is dominated by the largest names.
      * `med_<k>`  -- median of the members' own percentage changes. This is
        breadth: it says the typical name in the group moved, not just the
        biggest one. They disagree when a single name carries the group, which
        is exactly when the sum alone would mislead.
    """
    d = load()
    if d is None or d.empty:
        return None, {}
    gm = group_map()
    if not gm:
        return None, {"error": "no roster"}
    d = d[d.symbol.isin(gm)].copy()
    if d.empty:
        return None, {"error": "roster and FINRA file share no symbols"}
    d["grp"] = d.symbol.map(gm)

    dates = sorted(d.date.unique())
    last = dates[-1]
    piv = d.pivot_table(index="symbol", columns="date", values="si", aggfunc="last")
    gser = pd.Series(gm)

    rows = []
    for g, members in d[d.date == last].groupby("grp").symbol:
        mem = sorted(set(members))
        if len(mem) < MIN_MEMBERS:
            continue
        cur = piv.loc[piv.index.intersection(mem), last].dropna()
        if len(cur) < MIN_MEMBERS:
            continue
        rec = {"grp": g, "n": int(len(cur)), "si_now": float(cur.sum())}
        sub = d[(d.date == last) & (d.symbol.isin(cur.index))]
        rec["dtc_med"] = float(sub.dtc.median(skipna=True))
        for k in settlements:
            if len(dates) <= k:
                rec[f"sum_{k}"] = rec[f"med_{k}"] = np.nan
                rec[f"n_{k}"] = 0
                continue
            prev_date = dates[-1 - k]
            prev = piv.loc[piv.index.intersection(mem), prev_date].dropna()
            both = cur.index.intersection(prev.index)
            if len(both) < MIN_OVERLAP:
                rec[f"sum_{k}"] = rec[f"med_{k}"] = np.nan
                rec[f"n_{k}"] = int(len(both))
                continue
            a, b = cur[both].sum(), prev[both].sum()
            rec[f"sum_{k}"] = float(100 * (a / b - 1)) if b > 0 else np.nan
            pc = (cur[both] / prev[both].replace(0, np.nan) - 1) * 100
            rec[f"med_{k}"] = float(pc.median(skipna=True))
            rec[f"n_{k}"] = int(len(both))
        rows.append(rec)

    f = pd.DataFrame(rows)
    if f.empty:
        return None, {"error": "no basket cleared the member floor"}

    # Persistence: how many of the recent settlements moved the same way. A
    # group up in 5 of the last 6 is a trend; one big settlement is not, and the
    # single-horizon change cannot tell them apart.
    span = min(6, len(dates) - 1)
    streak = []
    for _, r in f.iterrows():
        mem = [s for s, g in gm.items() if g == r.grp]
        idx = piv.index.intersection(mem)
        ups = 0
        for j in range(span):
            c, p = dates[-1 - j], dates[-2 - j]
            cc, pp = piv.loc[idx, c].dropna(), piv.loc[idx, p].dropna()
            both = cc.index.intersection(pp.index)
            if len(both) < MIN_OVERLAP:
                continue
            if cc[both].sum() > pp[both].sum():
                ups += 1
        streak.append(ups)
    f["up_of"] = streak
    f["span"] = span
    f = f.sort_values("sum_1", ascending=False).reset_index(drop=True)
    meta = {"settle": str(pd.Timestamp(last).date()),
            "n_settlements": len(dates),
            "prior": {k: str(pd.Timestamp(dates[-1 - k]).date())
                      for k in settlements if len(dates) > k},
            "groups": int(len(f))}
    if save:
        try:
            f.to_parquet(OUT)
        except Exception:
            pass
    return f, meta


def extremes(top=TOP_N):
    """Absolute short-interest extremes at the latest settlement.

    Four different questions, because "highest short interest" is ambiguous and
    the four answers are genuinely different names:
      * biggest position in SHARES -- where the crowd's capital actually is;
      * highest DAYS TO COVER -- how trapped it is, which is what squeezes;
      * highest % OF FLOAT -- crowding relative to what can actually be bought;
      * at a RECORD high against the name's own 94-settlement history -- not
        merely large, but larger than it has ever been here.
    The last one is the reason the backfill mattered: on a history missing a
    third of its settlements, "record" was an artefact of which ones survived.
    """
    d = load()
    if d is None or d.empty:
        return {}
    uni = screened()
    if uni:
        d = d[d.symbol.str.upper().isin(uni)]
        if d.empty:
            return {}
    dates = sorted(d.date.unique())
    last = dates[-1]
    cur = d[d.date == last].copy()
    piv = d.pivot_table(index="symbol", columns="date", values="si", aggfunc="last")

    # record high against the name's own history -- needs a real history to mean
    # anything, so require coverage across most settlements
    hist_n = piv.notna().sum(axis=1)
    eligible = hist_n[hist_n >= max(8, int(0.5 * len(dates)))].index
    pk = piv.loc[eligible].max(axis=1)
    now = piv.loc[eligible, last]
    at_high = (now >= pk * 0.999) & now.notna()
    rec = cur[cur.symbol.isin(now[at_high].index)].copy()
    rec["hist"] = rec.symbol.map(hist_n)

    flt = None
    try:
        import floatdata as FD
        want = set(cur.nlargest(top * 4, "si").symbol) | set(
            cur.nlargest(top * 4, "dtc").symbol) | set(rec.symbol)
        flt = FD.get(symbols=want)
    except Exception:
        pass

    def pct_float(df):
        if flt is None:
            return df.assign(pf=np.nan)
        import floatdata as FD
        return df.assign(pf=[FD.pct_of_float(r.si, r.symbol, flt)
                             for r in df.itertuples()])

    liq = cur[(cur.si > 1e5) & (cur.adv.fillna(0) >= MIN_ADV)]
    by_si = pct_float(cur.nlargest(top, "si"))
    by_dtc = pct_float(liq.dropna(subset=["dtc"]).nlargest(top, "dtc"))
    by_pf = pct_float(liq.nlargest(top * 4, "si"))
    by_pf = by_pf.dropna(subset=["pf"]).nlargest(top, "pf") if "pf" in by_pf else by_pf
    rec = pct_float(rec.nlargest(top, "si"))
    return {"settle": str(pd.Timestamp(last).date()), "n_settlements": len(dates),
            "by_si": by_si, "by_dtc": by_dtc, "by_pf": by_pf, "at_high": rec,
            "n_at_high": int(at_high.sum()), "n_eligible": int(len(eligible)),
            "screened": bool(uni)}


# ---- rendering --------------------------------------------------------------

def _pc(v, scale=25.0, fmt="{:+.1f}%"):
    if v is None or not np.isfinite(v):
        return '<td class="dim" data-sort="-999">&ndash;</td>'
    t = max(-1.0, min(1.0, float(v) / scale))
    a = abs(t)
    # Shorts BUILDING is the bearish/crowded side -- red. Covering is green.
    pole = (230, 103, 103) if t > 0 else (27, 175, 122)
    mid = (56, 56, 53)
    rgb = tuple(int(mid[i] + (pole[i] - mid[i]) * a) for i in range(3))
    ink = "#fff" if a > 0.45 else "#c3c2b7"
    return (f'<td data-sort="{v:.4f}" style="background:rgb{rgb};color:{ink}">'
            f'{fmt.format(v)}</td>')


def _sh(v):
    v = float(v)
    return f"{v/1e9:.2f}B" if abs(v) >= 1e9 else f"{v/1e6:.1f}M"


def basket_table(f, meta):
    if f is None or f.empty:
        return '<p class="none">No basket-level short interest this run.</p>'
    ks = [k for k in (1, 3, 6) if f"sum_{k}" in f.columns]
    body = []
    for _, r in f.iterrows():
        cells = ""
        for k in ks:
            cells += _pc(r.get(f"sum_{k}")) + _pc(r.get(f"med_{k}"))
        st = int(r.up_of); sp = int(r.span)
        tone = "dn" if st >= sp - 1 else ("up" if st <= 1 else "dim")
        body.append(
            f'<tr><td class="nm" data-sort="{html.escape(str(r.grp))}">'
            f'{html.escape(str(r.grp))}</td>'
            f'<td class="dim" data-sort="{int(r.n)}">{int(r.n)}</td>'
            f'<td data-sort="{r.si_now:.0f}">{_sh(r.si_now)}</td>'
            + cells
            + f'<td data-sort="{r.dtc_med:.2f}">'
              f'{"&ndash;" if not np.isfinite(r.dtc_med) else f"{r.dtc_med:.1f}"}</td>'
            + f'<td class="{tone}" data-sort="{st}">{st}/{sp}</td></tr>')
    hsub = "".join(f'<th>Total</th><th>Median</th>' for _ in ks)
    hmain = "".join(
        f'<th colspan="2">vs {k} settlement{"s" if k > 1 else ""} '
        f'<span class="thh">{meta["prior"].get(k, "")}</span></th>' for k in ks)
    pri = " &middot; ".join(f"{k} back = {v}" for k, v in meta["prior"].items())
    return (
        f'<p class="grpnote">Settlement <b>{meta["settle"]}</b>, '
        f'<b>{meta["groups"]}</b> of jman&rsquo;s custom baskets with at least '
        f'{MIN_MEMBERS} covered names, out of <b>{meta["n_settlements"]}</b> '
        f'settlements of FINRA history ({pri}). '
        f'<b>Total</b> is the change in summed shares short; <b>Median</b> is the '
        f'median member&rsquo;s own percentage change &mdash; when they disagree, one '
        f'large name is carrying the group and the median is the honest read. '
        f'Every change is computed only on symbols present at <b>both</b> endpoints, '
        f'so a basket gaining members cannot print as a short build. '
        f'<b class="dn">Red = shorts building</b>, <b class="up">green = covering</b>. '
        f'<b>Built</b> counts how many of the last {int(f.span.iloc[0])} settlements '
        f'rose &mdash; persistence, not one noisy print. Click any header to sort.</p>'
        '<table class="sig sortable"><thead>'
        f'<tr class="grp2"><th rowspan="2">Basket</th><th rowspan="2">n</th>'
        f'<th rowspan="2">Shares short</th>{hmain}'
        f'<th rowspan="2">DTC med</th><th rowspan="2">Built</th></tr>'
        f'<tr>{hsub}</tr></thead><tbody>' + "".join(body) + '</tbody></table>')


def _ext_tbl(df, title, sub, val, fmt):
    if df is None or not len(df):
        return f'<div><h5>{title}</h5><p class="dim">nothing this settlement</p></div>'
    rows = "".join(
        f'<tr><td class="nm" data-e="{html.escape(str(r.symbol))}">'
        f'{html.escape(str(r.symbol))}</td>'
        f'<td>{fmt(r)}</td>'
        f'<td class="dim">{_sh(r.si)}</td>'
        f'<td class="dim">{"&ndash;" if not np.isfinite(r.dtc) else f"{r.dtc:.1f}"}</td>'
        f'<td class="dim">{"&ndash;" if not np.isfinite(getattr(r, "pf", np.nan)) else f"{r.pf:.1f}%"}</td>'
        '</tr>' for r in df.itertuples())
    return (f'<div><h5>{title}</h5><p class="dim" style="font-size:10.5px;margin:0 0 5px">'
            f'{sub}</p>'
            '<table class="mini"><thead><tr><th>Sym</th><th>' + val +
            '</th><th>Shares</th><th>DTC</th><th>% float</th></tr></thead><tbody>'
            + rows + '</tbody></table></div>')


def extremes_panel(o=None):
    o = o or extremes()
    if not o:
        return '<p class="none">No short-interest extremes this run.</p>'
    return (
        f'<p class="grpnote">The four readings of &ldquo;highest short interest&rdquo;, '
        f'at settlement <b>{o["settle"]}</b>. They are deliberately separate because '
        f'they return different names: <b>shares</b> is where the capital is, '
        f'<b>days to cover</b> is how trapped it is, <b>% of float</b> is crowding '
        f'against what can actually be bought, and <b>record high</b> is a name shorted '
        f'more heavily than at any point in its own history here. '
        f'<b>{o["n_at_high"]}</b> of {o["n_eligible"]:,} names with enough history sit '
        f'at a record, measured across {o["n_settlements"]} settlements &mdash; that '
        f'count was not trustworthy before the settlement backfill, since a third of '
        f'the history was missing and &ldquo;record&rdquo; only meant record among the '
        f'settlements that happened to be collected. '
        + ('Restricted to the screened universe (mcap &ge; $300M, real common stock) '
           'and to names with genuine volume &mdash; FINRA writes a <b>999.99</b> '
           'sentinel for days-to-cover when average volume is ~zero, and unfiltered '
           'that sentinel wins the ranking with untradeable OTC listings. '
           if o.get("screened") else '')
        + 'Click a symbol for its chart.</p>'
        '<div class="cf3">'
        + _ext_tbl(o["by_si"], "Largest short position", "by shares short",
                   "Shares", lambda r: _sh(r.si))
        + _ext_tbl(o["by_dtc"], "Most trapped", "highest days to cover",
                   "DTC", lambda r: f"{r.dtc:.1f}")
        + _ext_tbl(o["by_pf"], "Most crowded vs float", "highest % of tradeable float",
                   "% float", lambda r: "&ndash;" if not np.isfinite(r.pf) else f"{r.pf:.1f}%")
        + '</div><div class="cf3" style="margin-top:14px">'
        + _ext_tbl(o["at_high"], "At a RECORD short position",
                   "largest in this name's own FINRA history", "Shares",
                   lambda r: _sh(r.si))
        + '</div>')


def html_panel():
    try:
        f, meta = build()
    except Exception as e:
        print("sibaskets build failed:", e, flush=True)
        f, meta = None, {}
    try:
        o = extremes()
    except Exception as e:
        print("sibaskets extremes failed:", e, flush=True)
        o = {}
    if f is None and not o:
        return ""
    return ('<h2>Short interest by basket &mdash; across recent settlements</h2>'
            + (basket_table(f, meta) if f is not None else "")
            + '<h2>Short interest &mdash; the absolute extremes</h2>'
            + extremes_panel(o))


if __name__ == "__main__":
    f, meta = build()
    print(json.dumps(meta, indent=1))
    if f is not None:
        cols = ["grp", "n", "si_now", "sum_1", "med_1", "sum_3", "sum_6", "up_of"]
        print("\nTOP 12 BUILDING:")
        print(f.nlargest(12, "sum_1")[cols].to_string(index=False))
        print("\nTOP 12 COVERING:")
        print(f.nsmallest(12, "sum_1")[cols].to_string(index=False))
        print("\nMOST PERSISTENT BUILDS (up_of):")
        print(f.nlargest(12, "up_of")[cols].to_string(index=False))
    o = extremes()
    if o:
        print(f"\nsettle {o['settle']} | {o['n_at_high']} of {o['n_eligible']} at record")
        print("\nLargest short positions:")
        print(o["by_si"][["symbol", "si", "dtc"]].head(8).to_string(index=False))
        print("\nHighest DTC:")
        print(o["by_dtc"][["symbol", "si", "dtc"]].head(8).to_string(index=False))
