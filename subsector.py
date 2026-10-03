"""Subsector / theme relative strength -- the rotation board."""
import pandas as pd, numpy as np, os, json, datetime as dt

D = os.path.expanduser("~/pos")
HIST = f"{D}/subsector_history.json"
ROSTER = f"{D}/custom176-rosters.txt"
MIN_MEMBERS = 5
BENCH = "SPY"

# RS rank methodology: blend a SHORT read (1w+1m) with a LONG read (1m+1Q)
# rather than ranking on the 1-month RS alone. Same short/long weighting rrg.py
# already uses for the rotation-map axes -- jman's own framing was "mix the
# 1w+1m RS with the 1m+1Q RS", which is exactly that blend, just applied to the
# single rank column instead of an x/y scatter position. Each leg is
# percentiled BEFORE blending (cross-sectional, so it's always relative to the
# other groups that day) and the blend is percentiled again after, so rs_rank
# stays a 0-99 read like it always was.
RS_W_SHORT = (0.6, 0.4)    # 1w, 1m
RS_W_LONG = (0.45, 0.55)   # 1m, 3m


def _pct(s):
    s = pd.Series(s, dtype="float64")
    if s.notna().sum() < 5: return pd.Series(np.nan, index=s.index)
    return s.rank(pct=True) * 100


def _rel(g, b):
    """The indicator's f_rel: performance relative to the benchmark as a ratio."""
    if not (np.isfinite(g) and np.isfinite(b)): return np.nan
    return ((1 + g / 100.0) / (1 + b / 100.0) - 1) * 100.0


def _rs_composite(rs_w, rs_m, rs_q):
    short = RS_W_SHORT[0] * _pct(rs_w) + RS_W_SHORT[1] * _pct(rs_m)
    long_ = RS_W_LONG[0] * _pct(rs_m) + RS_W_LONG[1] * _pct(rs_q)
    return (short + long_) / 2

def rosters(u):
    """Custom baskets when the roster file exists, else exchange industries."""
    if os.path.exists(ROSTER):
        out = {}
        for line in open(ROSTER):
            line = line.strip()
            if not line or "|" not in line: continue
            name, syms = line.split("|", 1)
            t = [s.strip().upper() for s in syms.split(",") if s.strip()]
            if len(t) >= 3: out[name.strip()] = t
        if out: return out, "custom176"
    if "industry" not in u.columns: return {}, "none"
    out = {}
    for ind, g in u.groupby("industry"):
        if not ind or str(ind).lower() == "nan": continue
        if len(g) < MIN_MEMBERS: continue
        out[str(ind)] = sorted(g.symbol.tolist())
    return out, "industry"

def build(b, u, bench_px=None):
    c = b.pivot_table(index="date", columns="symbol", values="close").sort_index()
    cover = c.notna().sum(axis=1) / max(c.shape[1], 1)
    c = c[cover >= 0.60]
    if len(c) < 70: return None, None

    groups, src = rosters(u)
    # Roster members outside the screened bar universe (recent listings, small
    # caps) still count in jman's indicator -- price them too, on the same
    # trading days, so each group averages its FULL roster.
    lack = sorted({t for m in groups.values() for t in m} - set(c.columns))
    if lack and src == "custom176":
        try:
            import tvcalc
            x = tvcalc.closes(lack)
            x = x[[t for t in lack if t in x.columns]].reindex(c.index)
            if len(x.columns):
                c = c.join(x)
        except Exception as e:
            print(f"subsector: extra roster pricing failed ({e})", flush=True)

    # Members with no bar in the last five sessions are delisted or acquired:
    # drop them (TradingView returns nothing for a dead symbol) rather than
    # carry a frozen price into every window.
    lastbar = c.apply(lambda col: col.last_valid_index())
    c = c[[t for t in c.columns if lastbar[t] is not None and lastbar[t] >= c.index[max(0, len(c) - 6)]]]

    def ret(win):
        # A member with no bar today carries its last close (Pine's
        # request.security does the same); a new listing with too little
        # history stays NaN and drops out of that window only.
        return (c.ffill().pct_change(win, fill_method=None) * 100).iloc[-1]

    R = {w: ret(w) for w in (1, 5, 21, 63)}
    bench = {}
    if bench_px is not None and BENCH in bench_px.columns:
        s = bench_px[BENCH].dropna()
        for w in (1, 5, 21, 63):
            bench[w] = float(100*(s.iloc[-1]/s.iloc[-1-w] - 1)) if len(s) > w else 0.0
    else:
        for w in (1, 5, 21, 63): bench[w] = float(R[w].median())

    rows = []
    weekly = c.resample("W-FRI").last().pct_change() * 100
    for name, syms in groups.items():
        m = [s for s in syms if s in c.columns]
        if len(m) < 3: continue
        # Primary read = jman's TradingView indicator ("Industry Group Strength
        # - EW vs SPY"): equal-weight MEAN of member returns, relative to SPY as
        # a RATIO, ((1+g)/(1+spy)-1). The median read is kept beside it as the
        # robustness cross-check -- a wide gap means a few members are carrying
        # (or sinking) the average.
        e = {w: float(R[w][m].mean()) for w in (1, 5, 21, 63)}
        md = {w: float(R[w][m].median()) for w in (1, 5, 21, 63)}
        wk = weekly[m].median(axis=1).dropna()
        sd = float(wk.tail(104).std()) or np.nan
        rows.append({
            "name": name, "n": len(m),
            "d": e[1], "w": e[5], "m": e[21], "q": e[63],
            "rs_w": _rel(e[5], bench[5]), "rs_m": _rel(e[21], bench[21]), "rs_q": _rel(e[63], bench[63]),
            # ew_* stay as explicit aliases of the primary read for older readers
            "ew_d": e[1], "ew_w": e[5], "ew_m": e[21], "ew_q": e[63],
            "ew_rs_w": _rel(e[5], bench[5]), "ew_rs_m": _rel(e[21], bench[21]),
            "ew_rs_q": _rel(e[63], bench[63]),
            "med_rs_w": _rel(md[5], bench[5]), "med_rs_m": _rel(md[21], bench[21]),
            "med_rs_q": _rel(md[63], bench[63]),
            "thrust": (md[5]/sd) if sd and np.isfinite(sd) else np.nan,
        })
    if not rows: return None, src
    df = pd.DataFrame(rows)
    df["rs_rank"] = (_rs_composite(df.rs_w, df.rs_m, df.rs_q).rank(pct=True) * 99).round().astype(int)
    df["ew_rank"] = df["rs_rank"]
    df["med_rank"] = (_rs_composite(df.med_rs_w, df.med_rs_m, df.med_rs_q).rank(pct=True) * 99).round().astype(int)
    # Positive = the equal-weight read is BETTER than the median read, i.e. the
    # group is being carried by a few strong members rather than broadly strong.
    df["xchk"] = df.ew_rank - df.med_rank
    df = df.sort_values("rs_rank", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    asof_now = str(pd.Timestamp(c.index[-1]).date())
    # Take the newest entry whose as_of is NOT today's: re-running on the same day
    # appends a fresh entry, and comparing against h[-1] then compares today with
    # itself and prints +0 for every basket.
    prev = {}
    if os.path.exists(HIST):
        try:
            h = json.load(open(HIST))
            older = [x for x in h if x.get("as_of") != asof_now and x.get("ranks")]
            if older: prev = older[-1]["ranks"]
        except Exception: prev = {}
    df["d_rank"] = df.apply(
        lambda r: (prev[r["name"]] - r["rank"]) if r["name"] in prev else np.nan, axis=1)

    members = {}
    for name, syms in groups.items():
        m = [x for x in syms if x in c.columns]
        if len(m) < 3: continue
        rows_m = []
        for t in m:
            rows_m.append({"t": t,
                           "d": round(float(R[1].get(t, np.nan)), 2),
                           "w": round(float(R[5].get(t, np.nan)), 2),
                           "m": round(float(R[21].get(t, np.nan)), 2),
                           "q": round(float(R[63].get(t, np.nan)), 2)})
        rows_m = [x for x in rows_m if np.isfinite(x["m"])]
        rows_m.sort(key=lambda x: -x["m"])
        members[name] = rows_m
    df.attrs["members"] = members

    hist = []
    if os.path.exists(HIST):
        try: hist = json.load(open(HIST))
        except Exception: hist = []
    hist = [x for x in hist if x.get("as_of") != asof_now]
    hist.append({"as_of": asof_now, "source": src,
                 "ranks": dict(zip(df.name, df["rank"].astype(int)))})
    json.dump(hist[-60:], open(HIST, "w"))
    return df, src
