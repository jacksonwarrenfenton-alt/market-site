"""Does any Stockbee reading actually predict SPY?

Every panel on this site shows a breadth number in context -- z-score and
percentile against its own history. That answers "is this unusual". It does NOT
answer "is this useful", and those are different questions. This module asks the
second one: when a series reaches an extreme, what does SPY do next, and is the
result distinguishable from chance.

Three things keep the answer honest:

  1. OVERLAP. Daily observations with a 13-week forward window share almost all
     of their return. Treating 2,500 overlapping days as 2,500 independent trials
     inflates significance enormously, so effective n is n / horizon_days.
  2. A BASELINE. SPY drifts up. A signal that is right 55% of the time is worth
     nothing if SPY rises 55% of the time anyway, so every return is measured as
     EXCESS over the median forward return of the same window.
  3. MULTIPLE TESTING. Testing ~14 series x 2 tails x 3 horizons is ~84 tests.
     At p<0.05 roughly four fire on noise alone, so Benjamini-Hochberg decides
     what actually survives -- not the raw p-value.
"""
import pandas as pd, numpy as np, math, os

D = os.path.expanduser("~/pos")
HORIZONS = [(5, "1w"), (21, "1m"), (63, "3m")]
TAIL_PCT = 15.0      # how extreme a reading has to be to count
MIN_N = 60

# series -> (direction the extreme is read as, human label)
#  +1 : a HIGH reading is read as bullish for SPY
#  -1 : a HIGH reading is read as bearish (an overbought / exhaustion read)
SERIES = {
    "up4":   (+1, "Stocks up 4% today"),
    "dn4":   (-1, "Stocks down 4% today"),
    "r5":    (+1, "4% ratio, 5-day"),
    "r10":   (+1, "4% ratio, 10-day"),
    "t2108": (-1, "T2108 (% above 40-day MA)"),
    "up25m": (+1, "Up 25% in a month"),
    "dn25m": (-1, "Down 25% in a month"),
    "up25q": (+1, "Up 25% in a quarter"),
    "dn25q": (-1, "Down 25% in a quarter"),
    "up13":  (+1, "Up 13% in 34 days"),
    "dn13":  (-1, "Down 13% in 34 days"),
    "up50m": (+1, "Up 50% in a month"),
    "dn50m": (-1, "Down 50% in a month"),
    "up8":    (+1, "Up 8% in a week"),
    "dn8":    (-1, "Down 8% in a week"),
    "up50q":  (+1, "Up 50% in a quarter"),
    "dn50q":  (-1, "Down 50% in a quarter"),
    "pct50":  (-1, "% above 50-day MA"),
    "pct200": (-1, "% above 200-day MA"),
    "hl_net": (-1, "Net 52-week highs minus lows"),
}


def _p_two(hit, n_eff):
    if n_eff <= 0: return 1.0
    z = (hit - 0.5) / math.sqrt(0.25 / n_eff)
    return math.erfc(abs(z) / math.sqrt(2))


def _fwd(spy, idx, days):
    s = spy.dropna()
    now = s.reindex(idx, method="ffill").values
    pos = s.index.searchsorted(idx) + days
    pos = np.clip(pos, 0, len(s) - 1)
    later = s.values[pos]
    valid = (s.index.searchsorted(idx) + days) < len(s)
    with np.errstate(all="ignore"):
        r = 100 * (later / now - 1)
    r[~valid] = np.nan
    return r


def build(hist, spy):
    """hist: the Stockbee history frame. spy: a daily close Series."""
    if hist is None or not len(hist) or spy is None or not len(spy):
        return pd.DataFrame()
    idx = pd.DatetimeIndex(hist.index)
    rows = []
    for col, (sign, label) in SERIES.items():
        if col not in hist.columns: continue
        v = pd.to_numeric(hist[col], errors="coerce").values
        if np.isfinite(v).sum() < 200: continue
        hi = np.nanpercentile(v[np.isfinite(v)], 100 - TAIL_PCT)
        lo = np.nanpercentile(v[np.isfinite(v)], TAIL_PCT)
        for days, hlabel in HORIZONS:
            f = _fwd(spy, idx, days)
            ok = np.isfinite(f) & np.isfinite(v)
            if ok.sum() < 200: continue
            base = float(np.nanmedian(f[ok]))
            for tail in ("high", "low"):
                m = ok & ((v >= hi) if tail == "high" else (v <= lo))
                n = int(m.sum())
                if n < MIN_N: continue
                # A high reading points `sign`; a low reading points the other way.
                dirn = sign if tail == "high" else -sign
                excess = (f[m] - base) * dirn
                n_eff = max(n / days, 1.0)
                hit = float((excess > 0).mean())
                rows.append({
                    "series": col, "label": label, "tail": tail,
                    "horizon": hlabel, "days": days,
                    "n": n, "n_eff": round(n_eff, 1),
                    "hit": 100 * hit,
                    "med_excess": float(np.median(excess)),
                    "base": base,
                    "p": _p_two(hit, n_eff),
                })
    df = pd.DataFrame(rows)
    if df.empty: return df
    # Benjamini-Hochberg over the whole family of tests
    p = df.p.values; order = np.argsort(p); m = len(p)
    crit = (np.arange(1, m + 1) / m) * 0.10
    passed = p[order] <= crit
    kmax = int(np.max(np.where(passed)[0]) + 1) if passed.any() else 0
    df["bh"] = False
    if kmax: df.loc[df.index[order[:kmax]], "bh"] = True
    return df.sort_values("p").reset_index(drop=True)


def verdict(r):
    if r["bh"]:            return "SURVIVES correction", "good"
    if r["p"] < 0.05:      return "p&lt;0.05, fails correction", "warn"
    if r["hit"] < 47:      return "inverted", "bad"
    return "coin flip", "dim"
