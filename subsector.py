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

    def ret(win):
        return (c.pct_change(win) * 100).iloc[-1]

    R = {w: ret(w) for w in (1, 5, 21, 63)}
    bench = {}
    if bench_px is not None and BENCH in bench_px.columns:
        s = bench_px[BENCH].dropna()
        for w in (1, 5, 21, 63):
            bench[w] = float(100*(s.iloc[-1]/s.iloc[-1-w] - 1)) if len(s) > w else 0.0
    else:
        for w in (1, 5, 21, 63): bench[w] = float(R[w].median())

    groups, src = rosters(u)
    rows = []
    weekly = c.resample("W-FRI").last().pct_change() * 100
    for name, syms in groups.items():
        m = [s for s in syms if s in c.columns]
        if len(m) < 3: continue
        r = {w: float(R[w][m].median()) for w in (1, 5, 21, 63)}
        # Equal-weight (arithmetic mean) replicates the Pine indicator's
        # EW-vs-SPY construction on the identical roster. Median is robust to a
        # single blown-up member; EW is what the on-chart table shows. Carrying
        # both makes disagreement visible instead of silently picking one.
        e = {w: float(R[w][m].mean()) for w in (1, 5, 21, 63)}
        wk = weekly[m].median(axis=1).dropna()
        sd = float(wk.tail(104).std()) or np.nan
        rows.append({
            "name": name, "n": len(m),
            "d": r[1], "w": r[5], "m": r[21], "q": r[63],
            "rs_w": r[5] - bench[5], "rs_m": r[21] - bench[21], "rs_q": r[63] - bench[63],
            "ew_d": e[1], "ew_w": e[5], "ew_m": e[21], "ew_q": e[63],
            "ew_rs_w": e[5] - bench[5], "ew_rs_m": e[21] - bench[21],
            "ew_rs_q": e[63] - bench[63],
            "thrust": (r[5]/sd) if sd and np.isfinite(sd) else np.nan,
        })
    if not rows: return None, src
    df = pd.DataFrame(rows)
    df["rs_rank"] = (_rs_composite(df.rs_w, df.rs_m, df.rs_q).rank(pct=True) * 99).round().astype(int)
    df["ew_rank"] = (_rs_composite(df.ew_rs_w, df.ew_rs_m, df.ew_rs_q).rank(pct=True) * 99).round().astype(int)
    # Positive = the equal-weight read is BETTER than the median read, i.e. the
    # group is being carried by a few strong members rather than broadly strong.
    df["xchk"] = df.ew_rank - df.rs_rank
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
