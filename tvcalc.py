"""jman's TradingView indicator, computed exactly, without a browser.

"Industry Group Strength - EW vs SPY (Final Groups)" (tv_indicator.pine) is
plain arithmetic on daily closes, so the cloud can reproduce its Data Window
numbers directly instead of walking 253 probe tickers through Chrome:

  member return   ta.roc(close, n)  = 100 * (close / close[n] - 1), on that
                  symbol's own daily bars (n = 1, 5, 21, 63, 126)
  group return    equal-weight mean over members that HAVE that return
  rel perf        ((1 + group/100) / (1 + SPY/100) - 1) * 100   (a ratio,
                  not a subtraction)
  group score     100 / (1 + exp(-0.15 * (rel21 + rel63) / 2))
  members         count of members with a 21-bar return (the indicator's n21)
  numeric id      sector base + 1-based position of the group within its
                  sector, in roster order (CM 100, CD 200, CS 300, EN 400,
                  FN 500, HC 600, IN 700, MT 800, RE 900, IT 1000, UT 1100)

Closes are split-adjusted and NOT dividend-adjusted, the same as a TradingView
chart with default settings (Yahoo's chart `close`). The rosters are read from
the Pine source itself, so editing the indicator and committing the new
tv_indicator.pine is all it takes to keep this in step.

Output: ~/pos/tv_scan.csv in the walk's schema (date, code, group, grp_id,
numeric_id, score, members, rs1d, rs5d, rs21d, rs63d, rs126d) plus src=calc.
"""
import os, re, sys
import numpy as np, pandas as pd

D = os.path.expanduser("~/pos")
HERE = os.path.dirname(os.path.abspath(__file__))
PINE = f"{HERE}/tv_indicator.pine"
OUT = f"{D}/tv_scan.csv"
WIN = {"rs1d": 1, "rs5d": 5, "rs21d": 21, "rs63d": 63, "rs126d": 126}
SECTOR = [("Communications - ", 100), ("Technology - ", 1000), ("Industrials - ", 700),
          ("Financials - ", 500), ("Consumer Discretionary - ", 200),
          ("Consumer Staples - ", 300), ("Healthcare - ", 600), ("Utilities - ", 1100),
          ("Energy - ", 400), ("Materials - ", 800), ("Real Estate - ", 900)]


def groups(path=PINE):
    """[(name, [tickers]), ...] in the indicator's own order."""
    src = open(path).read()
    g = [(n, [t.strip().strip("'") for t in s.split(",")])
         for n, s in re.findall(r"industry\.new\('([^']+)',\s*array\.from\(([^)]*)\)\)", src)]
    if len(g) < 200:
        raise RuntimeError(f"tvcalc: only {len(g)} groups parsed from {path}")
    return g


def group_ids(gs):
    """Pine's f_sectorInfo + sectorLocalId: base + running count within sector."""
    seen, out = {}, []
    for name, _ in gs:
        base = next((b for p, b in SECTOR if name.startswith(p)), 700)
        seen[base] = seen.get(base, 0) + 1
        out.append(base + seen[base])
    return out


def _yahoo(t):
    return t.replace(".", "-")


def closes(tickers):
    """Daily closes (columns = TradingView tickers). The breadth bar cache
    first; anything it lacks is fetched once into its own cache."""
    px = pd.DataFrame()
    bp = f"{D}/bars.parquet"
    if os.path.exists(bp):
        b = pd.read_parquet(bp, columns=["date", "symbol", "close"])
        b = b[b.symbol.isin({_yahoo(t) for t in tickers})]
        px = b.pivot_table(index="date", columns="symbol", values="close").sort_index()
    want = sorted({_yahoo(t) for t in tickers} - set(px.columns))
    if want:
        # Fetched here rather than through prices.fetch_list, which drops any
        # series under 60 bars -- the indicator still counts a recent listing
        # in every window it has history for (1D/5D/21D for a 40-day IPO).
        import prices as P
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(6) as ex:
            got = {tk: s for tk, s in ex.map(lambda t: P._one(t, "1y"), want) if s is not None and len(s)}
        if got:
            extra = pd.DataFrame(got).sort_index()
            px = extra if px.empty else px.join(extra, how="outer")
    px.index = pd.to_datetime(px.index).normalize()
    return px.rename(columns={_yahoo(t): t for t in tickers})


def _roc(s, n):
    """ta.roc(close, n) at the symbol's latest bar, on its own bar sequence."""
    s = s.dropna()
    if len(s) <= n or s.iloc[-1 - n] == 0:
        return np.nan
    return 100.0 * (s.iloc[-1] / s.iloc[-1 - n] - 1.0)


def _rel(g, b):
    if not np.isfinite(g) or not np.isfinite(b):
        return np.nan
    return ((1 + g / 100.0) / (1 + b / 100.0) - 1.0) * 100.0


def build(write=True):
    gs = groups()
    ids = group_ids(gs)
    tickers = sorted({t for _, m in gs for t in m} | {"SPY"})
    px = closes(tickers)
    if "SPY" not in px.columns:
        raise RuntimeError("tvcalc: no SPY closes")
    spy = px["SPY"].dropna()
    asof = spy.index[-1]
    px = px[px.index <= asof]
    bench = {k: _roc(spy, n) for k, n in WIN.items()}
    # Stale members (no bar for weeks) still count in Pine -- request.security
    # carries the last value -- but a symbol with no data at all is skipped.
    probes = {}
    pp = f"{D}/tv_probes_253.csv"
    if not os.path.exists(pp): pp = f"{HERE}/tv_probes_253.csv"
    if os.path.exists(pp):
        p = pd.read_csv(pp)
        probes = {r.group: (r.code, r.numeric_id) for r in p.itertuples()}
    rows, missing = [], 0
    for (name, members), gid in zip(gs, ids):
        have = [t for t in members if t in px.columns and px[t].notna().any()]
        missing += len(members) - len(have)
        r = {}
        for k, n in WIN.items():
            v = [x for x in (_roc(px[t], n) for t in have) if np.isfinite(x)]
            r[k] = _rel(float(np.mean(v)) if v else np.nan, bench[k])
            if k == "rs21d":
                r["members"] = len(v)
        rank = (r["rs21d"] + r["rs63d"]) / 2.0
        code, nid = probes.get(name, (members[0], np.nan))
        rows.append({"date": asof.strftime("%Y-%m-%d"), "code": code, "group": name,
                     "grp_id": gid, "numeric_id": gid if pd.isna(nid) else int(nid),
                     "score": round(100.0 / (1.0 + np.exp(-0.15 * rank)), 3) if np.isfinite(rank) else np.nan,
                     "members": r["members"],
                     **{k: round(r[k], 3) if np.isfinite(r[k]) else np.nan for k in WIN},
                     "src": "calc"})
    out = pd.DataFrame(rows)[["date", "code", "group", "grp_id", "numeric_id", "score", "members",
                              "rs1d", "rs5d", "rs21d", "rs63d", "rs126d", "src"]]
    drift = int((out.grp_id != out.numeric_id).sum())
    print(f"tvcalc: {len(out)} groups as of {asof.date()}, "
          f"{len(tickers) - 1 - missing}/{len(tickers) - 1} members priced"
          + (f", {drift} probe-map id drift" if drift else ""), file=sys.stderr, flush=True)
    if write:
        out.to_csv(OUT, index=False)
    return out


if __name__ == "__main__":
    d = build()
    print(d.sort_values("score", ascending=False).head(10).to_string(index=False))
