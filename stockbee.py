"""Stockbee Market Monitor -- Pradeep Bonde's breadth model."""
import pandas as pd, numpy as np

def _pivot(b):
    return b.pivot_table(index="date", columns="symbol", values="close").sort_index()

def _ctx(series, val, lookback=252):
    """z-score and percentile of `val` against the series' own trailing history.

    Raw breadth counts are meaningless without this: 366 stocks down 4% is only
    informative once you know it sits at the 87th percentile of its own year.
    Stripping the context (as the 30 Aug rebuild did) turns the panel into
    numbers nobody can act on.
    """
    import numpy as _np
    h = pd.Series(series).replace([np.inf,-np.inf], np.nan).dropna().tail(lookback)
    if len(h) < 40 or not np.isfinite(val): return (np.nan, np.nan)
    sd = float(h.std())
    z = (val - float(h.mean())) / sd if sd > 0 else np.nan
    pct = float((h <= val).mean() * 100)
    return (z, pct)


def build(b, members=None, label="TOTAL MARKET", lookback=260):
    if members is not None:
        b = b[b.symbol.isin(members)]
    c = _pivot(b)
    cover = c.notna().sum(axis=1) / max(c.shape[1], 1)
    good = cover >= 0.60
    if good.sum() < 40: good = cover >= cover.quantile(0.5)
    c = c[good]
    if len(c) < 70: return None, None

    def n_move(win, thr):
        r = c.pct_change(win) * 100
        return (r >= thr).sum(axis=1), (r <= -thr).sum(axis=1)

    up4, dn4 = n_move(1, 4.0)
    up25q, dn25q = n_move(63, 25.0)
    up25m, dn25m = n_move(21, 25.0)
    up13, dn13 = n_move(34, 13.0)
    up50m, dn50m = n_move(21, 50.0)          # the 50%-in-a-month cohort
    up8, dn8     = n_move(5, 8.0)            # 8% in a week -- the momentum burst
    up50q, dn50q = n_move(63, 50.0)          # 50% in a quarter -- the big movers
    # Participation gauges. These live in breadth.py for the market panels, but
    # the Stockbee model reads them as its own cohort and the significance test
    # needs them on the same index as everything else here.
    ma50  = c.rolling(50,  min_periods=25).mean()
    ma200 = c.rolling(200, min_periods=100).mean()
    live  = c.notna().sum(axis=1)
    pct50  = 100 * (c > ma50).sum(axis=1)  / live
    pct200 = 100 * (c > ma200).sum(axis=1) / live
    hi52 = (c >= c.rolling(252, min_periods=120).max()).sum(axis=1)
    lo52 = (c <= c.rolling(252, min_periods=120).min()).sum(axis=1)
    hl_net = 100 * (hi52 - lo52) / live
    # T2108 -- share of the universe above its own 40-day moving average.
    # Bonde's primary overbought/oversold gauge; NOT the same as breadth.py's
    # pct50 (50-day), which is why it has to be computed here.
    ma40 = c.rolling(40, min_periods=20).mean()
    t2108 = 100 * (c > ma40).sum(axis=1) / c.notna().sum(axis=1)

    def ratio(u, d, win):
        us, ds = u.rolling(win).sum(), d.rolling(win).sum()
        return (us / ds.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    h = pd.DataFrame({
        "up4": up4, "dn4": dn4,
        "r1": ratio(up4, dn4, 1), "r5": ratio(up4, dn4, 5), "r10": ratio(up4, dn4, 10),
        "up25q": up25q, "dn25q": dn25q, "up25m": up25m, "dn25m": dn25m,
        "up13": up13, "dn13": dn13,
        "up50m": up50m, "dn50m": dn50m, "t2108": t2108,
        "up8": up8, "dn8": dn8, "up50q": up50q, "dn50q": dn50q,
        "pct50": pct50, "pct200": pct200,
        "hi52": hi52, "lo52": lo52, "hl_net": hl_net,
    }).dropna(subset=["up4"]).tail(lookback)

    last = h.iloc[-1]
    def verdict(r5):
        if not np.isfinite(r5): return "-", "dim"
        if r5 >= 2.0:  return "THRUST", "good"
        if r5 >= 1.0:  return "constructive", "warn"
        if r5 <= 0.5:  return "WASHOUT", "bad"
        return "distribution", "bad"
    v, tone = verdict(float(last.r5))
    row = {"group": label, "up4": int(last.up4), "dn4": int(last.dn4),
           "r1": float(last.r1), "r5": float(last.r5), "r10": float(last.r10),
           "up25q": int(last.up25q), "dn25q": int(last.dn25q),
           "up25m": int(last.up25m), "dn25m": int(last.dn25m),
           "up13": int(last.up13), "dn13": int(last.dn13),
           "up50m": int(last.up50m), "dn50m": int(last.dn50m),
           "t2108": float(last.t2108),
           "up8": int(last.up8), "dn8": int(last.dn8),
           "up50q": int(last.up50q), "dn50q": int(last.dn50q),
           "pct50": float(last.pct50), "pct200": float(last.pct200),
           "hi52": int(last.hi52), "lo52": int(last.lo52),
           "hl_net": float(last.hl_net),
           "verdict": v, "tone": tone}
    # z / percentile context for every metric that has its own history
    # dn25m / dn50m / dn13 earn their own z the same way the up cohorts do: the
    # down side is the damage cohort and is read against its own history, not
    # inferred from the up count.
    for k in ("up4","dn4","r5","r10","t2108","up25m","dn25m","up50m","dn50m",
              "up25q","up13","dn13","up8","dn8","up50q","dn50q",
              "pct50","pct200","hl_net"):
        z, pc = _ctx(h[k], row[k])
        row[f"{k}_z"], row[f"{k}_pct"] = z, pc
    return row, h
