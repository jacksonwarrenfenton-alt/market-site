"""Breadth divergences that have historically mattered.

The breadth table colours everything red or green, which means nothing stands
out. What actually matters is a small set of configurations where PRICE and
PARTICIPATION disagree, because those are the ones that start and end trends.

Three tests, each requiring price and breadth to point opposite ways:

  BULLISH  price makes a new 20-day low while the share of members above their
           50-day MA does NOT -- selling is narrowing, the last leg had fewer
           names in it than the one before.
  BEARISH  price makes a new 20-day high while participation does not confirm.
  VOLUME   the up/down volume ratio diverges from the price move -- a new low on
           materially less down-volume than the prior low is exhaustion.

Every flag is scored against its OWN history: how often has this configuration
appeared, and what did the sector do next. A divergence that fires every other
week is a description, not a signal, so the panel reports the base rate and
hides anything that is not genuinely rare.
"""
import pandas as pd, numpy as np, os, html

D = os.path.expanduser("~/pos")
LOOK = 20          # the swing window for "new low / new high"
FWD = 21           # forward window used to score what happened next
MIN_OBS = 12       # a configuration needs this many past instances to be scored
RARE = 12.0        # and must fire on fewer than this % of days to be worth a flag


def _pivot(b):
    return b.pivot_table(index="date", columns="symbol", values="close").sort_index()


def build(bars, universe=None):
    """-> DataFrame of live divergences, one row per sector, with its own record."""
    if bars is None or not len(bars): return None
    u = universe
    groups = {"TOTAL MARKET": None}
    if u is not None and "sector" in u.columns:
        for s, g in u.groupby("sector"):
            if s and str(s).lower() != "nan" and len(g) >= 25:
                groups[str(s)] = set(g.symbol)

    rows = []
    for name, members in groups.items():
        b = bars if members is None else bars[bars.symbol.isin(members)]
        c = _pivot(b)
        if c.shape[1] < 20 or len(c) < 260: continue
        live = c.notna().sum(axis=1)
        idx = c.mean(axis=1)                       # equal-weight sector index
        ma50 = c.rolling(50, min_periods=25).mean()
        ma20 = c.rolling(20, min_periods=10).mean()
        p50 = 100 * (c > ma50).sum(axis=1) / live
        p20 = 100 * (c > ma20).sum(axis=1) / live
        r = c.pct_change()
        upv = (r > 0).sum(axis=1); dnv = (r < 0).sum(axis=1)
        udr = upv / dnv.replace(0, np.nan)

        f = pd.DataFrame({"idx": idx, "p50": p50, "p20": p20, "udr": udr}).dropna()
        if len(f) < 260: continue

        lo = f.idx.rolling(LOOK).min()
        hi = f.idx.rolling(LOOK).max()
        p50lo = f.p50.rolling(LOOK).min()
        p50hi = f.p50.rolling(LOOK).max()
        udlo = f.udr.rolling(LOOK).min()

        newlow = f.idx <= lo
        newhigh = f.idx >= hi
        # participation refuses to confirm
        bull = newlow & (f.p50 > p50lo * 1.12) & (f.p20 > f.p20.rolling(LOOK).min() * 1.12)
        bear = newhigh & (f.p50 < p50hi * 0.88)
        vol = newlow & (f.udr > udlo * 1.35)

        fwd = f.idx.shift(-FWD) / f.idx - 1
        out = {"group": name, "n_days": len(f)}
        for key, mask, want in (("bull", bull, +1), ("bear", bear, -1), ("vol", vol, +1)):
            m = mask & fwd.notna()
            n = int(m.sum())
            rate = 100.0 * mask.sum() / len(f)
            base = float(fwd.median())
            med = float(fwd[m].median()) if n else np.nan
            hit = float(((fwd[m] - base) * want > 0).mean()) if n else np.nan
            out[f"{key}_live"] = bool(mask.iloc[-1])
            out[f"{key}_n"] = n
            out[f"{key}_rate"] = rate
            out[f"{key}_fwd"] = 100 * med if np.isfinite(med) else np.nan
            out[f"{key}_base"] = 100 * base
            out[f"{key}_hit"] = 100 * hit if np.isfinite(hit) else np.nan
        out["p50"] = float(f.p50.iloc[-1]); out["p20"] = float(f.p20.iloc[-1])
        out["udr"] = float(f.udr.iloc[-1])
        # Recent fires. A panel that only shows TODAY reads as broken on every
        # day nothing fires, which is most days by construction -- these are rare
        # events. The last 90 sessions show the mechanism working and give the
        # most recent instance to look back at.
        recent = []
        for key, mask in (("bull", bull), ("bear", bear), ("vol", vol)):
            m = mask.iloc[-90:]
            for dt in m[m].index[-4:]:
                recent.append({"key": key, "date": str(pd.Timestamp(dt).date())})
        out["recent"] = recent
        rows.append(out)
    return pd.DataFrame(rows) if rows else None


LABEL = {"bull": ("Selling narrowing", "new 20-day low, but fewer names below their 50-day"),
         "bear": ("Advance narrowing", "new 20-day high without participation confirming"),
         "vol":  ("Down-volume drying", "new 20-day low on materially less down-volume")}


def html_panel(d):
    if d is None or not len(d): return ""
    live = []
    for _, r in d.iterrows():
        for k in ("bull", "bear", "vol"):
            if not r.get(f"{k}_live"): continue
            if not np.isfinite(r.get(f"{k}_hit", np.nan)): continue
            if r[f"{k}_n"] < MIN_OBS or r[f"{k}_rate"] > RARE: continue
            live.append((r["group"], k, r))
    # recent fires, newest first, across every sector
    rec = []
    for _, r in d.iterrows():
        # parquet returns this list-of-dicts as a numpy array, whose truthiness
        # is ambiguous -- `or []` raises rather than defaulting.
        _rc = r.get("recent")
        if _rc is None: continue
        try:
            if len(_rc) == 0: continue
        except TypeError:
            continue
        for x in _rc:
            k = x["key"]
            if r[f"{k}_n"] < MIN_OBS or r[f"{k}_rate"] > RARE: continue
            rec.append((x["date"], r["group"], k, r))
    rec.sort(key=lambda z: z[0], reverse=True)
    recbody = "".join(
        f'<tr><td class="dim">{x[0]}</td><td class="nm2">{html.escape(str(x[1]))}</td>'
        f'<td><span class="dv dv-{"up" if x[2] in ("bull","vol") else "dn"}">'
        f'{LABEL[x[2]][0]}</span></td>'
        f'<td class="{"up" if x[3][f"{x[2]}_fwd"]-x[3][f"{x[2]}_base"]>0 else "dn"}">'
        f'{x[3][f"{x[2]}_fwd"]-x[3][f"{x[2]}_base"]:+.2f}%</td>'
        f'<td>{x[3][f"{x[2]}_hit"]:.0f}%</td></tr>' for x in rec[:12])
    rectbl = ('<h4 style="margin-top:16px">Fired in the last 90 sessions</h4>'
              '<table class="sig dvg"><thead><tr><th>Date</th><th>Sector</th>'
              f'<th>Divergence</th><th>Excess {FWD}d</th><th>Beat drift</th>'
              '</tr></thead><tbody>' + recbody + '</tbody></table>') if recbody else ""

    if not live:
        return ('<h2>Breadth divergences</h2>'
                '<p class="grpnote">No sector is showing a price/participation '
                f'divergence that clears the bar today &mdash; at least {MIN_OBS} past '
                f'instances and firing on under {RARE:.0f}% of days. That is a real '
                'reading: price and breadth are agreeing, which is the normal state '
                'and the one that carries no information.</p>' + rectbl)
    live.sort(key=lambda x: -abs(x[2][f"{x[1]}_fwd"] - x[2][f"{x[1]}_base"]))
    body = ""
    for g, k, r in live[:14]:
        title, why = LABEL[k]
        tone = "up" if k in ("bull", "vol") else "dn"
        edge = r[f"{k}_fwd"] - r[f"{k}_base"]
        body += (
            f'<tr><td class="nm2">{html.escape(str(g))}</td>'
            f'<td><span class="dv dv-{tone}">{title}</span></td>'
            f'<td class="dim">{why}</td>'
            f'<td>{r[f"{k}_rate"]:.1f}%</td>'
            f'<td>{int(r[f"{k}_n"])}</td>'
            f'<td class="{"up" if edge>0 else "dn"}">{edge:+.2f}%</td>'
            f'<td>{r[f"{k}_hit"]:.0f}%</td></tr>')
    return ('<h2>Breadth divergences &mdash; where price and participation disagree</h2>'
            '<p class="grpnote">Only configurations where the index makes a new '
            f'{LOOK}-day extreme and participation refuses to confirm. Each is scored '
            'against its own history in that sector: how often it fires, how many '
            'times it has happened, the median '
            f'{FWD}-day move <b>in excess of the sector&rsquo;s normal drift</b>, and '
            'how often it beat that drift. Anything firing on more than '
            f'{RARE:.0f}% of days or with fewer than {MIN_OBS} instances is hidden &mdash; '
            'a divergence that happens every other week is a description, not a '
            'signal. Excess is what matters: a sector that rises anyway sets a high '
            'bar for its own flags.</p>'
            '<table class="sig dvg"><thead><tr><th>Sector</th><th>Divergence</th>'
            '<th>What it means</th><th>Fires on</th><th>n</th>'
            f'<th>Excess {FWD}d</th><th>Beat drift</th></tr></thead><tbody>'
            + body + '</tbody></table>' + rectbl)
