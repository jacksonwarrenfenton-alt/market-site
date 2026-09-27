"""Per-group confluence: eleven independent reads, one agreement count.

The board already ranks groups. What it did not say is HOW MANY separate reads
agree on that ranking -- a group at rank 12 on one measure and rank 180 on the
next is a very different proposition from one that sits top-decile on all
eleven, and the single blended number hides exactly that.

Eight of the eleven legs are computed on jman's own 253-basket roster, so no
taxonomy crosswalk stands between the data and the group. Each returns a
percentile in 0-99 (higher = stronger) or NaN when it cannot cover that group;
NaN is carried through as "not covered" and never imputed, because a leg that
quietly defaults to 50 votes without having an opinion. The remaining three
legs (tv, fvz, moo) are genuine outside reads -- see tvscan.py, extscan.py and
moomoo.py -- so those DO cross a taxonomy join, which is why their coverage is
never 253/253.
"""
import pandas as pd, numpy as np, os

D = os.path.expanduser("~/pos")

# key, label, one-line description of what the leg actually measures
LEGS = [
    ("med",   "Median RS",    "median member return vs SPY, 1 month"),
    ("ew",    "Equal-wt RS",  "equal-weight member return vs SPY, 1 month (Pine construction)"),
    ("short", "Short horizon","1-week group return vs SPY"),
    ("long",  "Long horizon", "3-month group return vs SPY"),
    ("thrust","Thrust",       "the week in sigma of the group's own 2-year weekly history"),
    ("bread", "Breadth",      "share of members beating SPY over 1 month"),
    ("flow",  "ETF flow",     "1-month flow as % of AUM in the basket that covers this group"),
    ("si",    "Short int.",   "short-interest breadth tilt across the group's members"),
    ("tv",    "TradingView",  "the chart indicator's own 21D/63D RS, read from the Data Window"),
    ("fvz",   "Finviz group", "Finviz industry-group 1w/3m performance, crosswalked to this basket"),
    ("moo",   "moomoo group", "moomoo Sectors single-period performance, crosswalked to this basket"),
]
KEYS = [k for k, _, _ in LEGS]
HI, LO = 70, 30          # a leg only votes outside this band
MIN_LEGS = 3             # below this the count is not worth printing


# Group-prefix -> ETF flow basket. The roster's own sector prefix is the honest
# join: it is the taxonomy jman built the baskets with, so nothing is guessed
# from a third party's industry tree. Prefixes with no sensible ETF basket are
# left out on purpose and their flow leg reads "not covered".
# Sector prefix -> ETF flow basket. The 253-group roster carries its own 11
# sector prefixes, so the join is exact rather than guessed. OVERRIDES catch the
# groups whose flows are driven by a theme rather than their sector -- a bitcoin
# miner sits in Financials but trades on crypto flows, not bank flows.
SECTOR_BASKET = {
    "Communications":         "Comm Services",
    "Technology":             "Technology",
    "Industrials":            "Industrials",
    "Financials":             "Financials",
    "Consumer Discretionary": "Consumer Disc",
    "Consumer Staples":       "Cons Staples",
    "Healthcare":             "Health Care",
    "Utilities":              "Utilities",
    "Energy":                 "Energy",
    "Materials":              "Industrial & Rare Metals",
    "Real Estate":            "Real Estate",
}

OVERRIDES = [
    ("Crypto",                      "Crypto"),
    ("Bitcoin Mining",              "Crypto"),
    ("Semiconductor",               "Semiconductors"),
    ("Wafer Equipment",             "Semiconductors"),
    ("Analog, Mixed-Signal",        "Semiconductors"),
    ("Power Semiconductors",        "Semiconductors"),
    ("Interconnect Chips",          "Semiconductors"),
    ("Programmable Logic",          "Semiconductors"),
    ("Edge Chips",                  "Semiconductors"),
    ("Assembly, Packaging & Test",  "Semiconductors"),
    ("Gold",                        "Precious Metals"),
    ("Silver",                      "Precious Metals"),
    ("Precious-Metal",              "Precious Metals"),
    ("Solar",                       "Clean Energy"),
    ("Hydrogen",                    "Clean Energy"),
    ("Batteries & Energy Storage",  "Clean Energy"),
    ("Nuclear",                     "Clean Energy"),
    ("Uranium",                     "Clean Energy"),
    ("Renewable Power",             "Clean Energy"),
    ("Fertilizers",                 "Agriculture"),
    ("Agricultural Merchandising",  "Agriculture"),
]


def basket_of(name):
    n = str(name)
    for key, basket in OVERRIDES:
        if key in n: return basket
    return SECTOR_BASKET.get(n.split(" - ")[0].strip())


def _pct(s):
    s = pd.Series(s, dtype="float64")
    if s.notna().sum() < 5: return pd.Series(np.nan, index=s.index)
    return (s.rank(pct=True) * 99).round()


def _member_breadth(df, bars, bench, members):
    """Share of each group's members beating SPY over 21 sessions."""
    if bars is None or bench is None: return pd.Series(np.nan, index=df.index)
    c = bars.pivot_table(index="date", columns="symbol", values="close").sort_index()
    if len(c) < 25: return pd.Series(np.nan, index=df.index)
    r21 = (c.pct_change(21) * 100).iloc[-1]
    b = bench["SPY"].dropna() if "SPY" in bench.columns else None
    bm = float(100*(b.iloc[-1]/b.iloc[-22] - 1)) if b is not None and len(b) > 22 else float(r21.median())
    out = []
    for _, row in df.iterrows():
        m = [x["t"] for x in members.get(str(row["name"]), [])]
        v = r21.reindex(m).dropna()
        out.append(100.0 * float((v > bm).mean()) if len(v) >= 3 else np.nan)
    return pd.Series(out, index=df.index)


def _group_si(df, si, members):
    """Short-interest breadth tilt: covering minus building, across members.

    The median washes out across a wide group, so this counts the tails the same
    way themes.py does -- it is the only construction that ever contributes.
    """
    if si is None or not len(si): return pd.Series(np.nan, index=df.index)
    col = next((c for c in ("chg_z", "z", "si_chg_z") if c in si.columns), None)
    if col is None: return pd.Series(np.nan, index=df.index)
    z = si.set_index("symbol")[col] if "symbol" in si.columns else si[col]
    z = z[~z.index.duplicated()]
    out = []
    for _, row in df.iterrows():
        m = [x["t"] for x in members.get(str(row["name"]), [])]
        v = pd.to_numeric(z.reindex(m), errors="coerce").dropna()
        if len(v) < 4: out.append(np.nan); continue
        # shorts covering reads bullish, shorts building reads bearish
        out.append(100.0 * (float((v <= -1).mean()) - float((v >= 1).mean())))
    return pd.Series(out, index=df.index)


def _group_flow(df, flow_by_basket, proxy_of_group):
    if not flow_by_basket: return pd.Series(np.nan, index=df.index)
    return pd.Series([flow_by_basket.get(proxy_of_group.get(str(n)), np.nan)
                      for n in df.name], index=df.index)


def build(df, bars=None, bench=None, si=None, flow_by_basket=None, group_basket=None):
    """Attach the ten leg percentiles, the agreement count and the spread."""
    if df is None or not len(df): return df
    members = df.attrs.get("members", {})
    raw = pd.DataFrame(index=df.index)
    raw["med"]    = df["rs_m"]
    raw["ew"]     = df["ew_rs_m"]
    raw["short"]  = df["rs_w"]
    raw["long"]   = df["rs_q"]
    raw["thrust"] = df["thrust"]
    raw["bread"]  = _member_breadth(df, bars, bench, members)
    raw["flow"]   = _group_flow(df, flow_by_basket or {}, group_basket or {})
    raw["si"]     = _group_si(df, si, members)
    # The only leg not computed from our own bars. It votes ONCE per group --
    # the join is on group name, so overlapping baskets (several biotech groups,
    # five bank size-tiers) cannot let this source speak more than once each.
    try:
        import tvscan as _TV
        v, asof, note = _TV.leg(list(df.name))
        raw["tv"] = v.values
        df.attrs["tv_asof"], df.attrs["tv_note"] = asof, note
    except Exception as e:
        raw["tv"] = np.nan
        df.attrs["tv_asof"], df.attrs["tv_note"] = None, f"TradingView leg failed: {e}"
    # Second outside read, same one-vote-per-group rule. Finviz's own 144
    # industries are coarser than our 253 baskets (see extscan.py), so this
    # join covers ~240/253 by name and several baskets share one Finviz read
    # on purpose -- the rest are genuinely outside anything Finviz tracks.
    try:
        import extscan as _FV
        v, asof, note = _FV.leg_finviz(list(df.name))
        raw["fvz"] = v.values
        df.attrs["fvz_asof"], df.attrs["fvz_note"] = asof, note
    except Exception as e:
        raw["fvz"] = np.nan
        df.attrs["fvz_asof"], df.attrs["fvz_note"] = None, f"Finviz leg failed: {e}"
    # Third outside read, same one-vote-per-group rule. moomoo's crosswalk is
    # mechanically reused from extscan.py's Finviz mapping (see moomoo.py's
    # docstring) so its coverage tracks the Finviz leg's ~240/253 exactly --
    # that is expected, not a bug to reconcile.
    try:
        import moomoo as _MOO
        v, asof, note = _MOO.leg_moomoo(list(df.name))
        raw["moo"] = v.values
        df.attrs["moo_asof"], df.attrs["moo_note"] = asof, note
    except Exception as e:
        raw["moo"] = np.nan
        df.attrs["moo_asof"], df.attrs["moo_note"] = None, f"moomoo leg failed: {e}"

    P = pd.DataFrame({k: _pct(raw[k]) for k in KEYS})
    for k in KEYS: df[f"L_{k}"] = P[k]

    cov  = P.notna().sum(axis=1)
    up   = (P >= HI).sum(axis=1)
    dn   = (P <= LO).sum(axis=1)
    df["c_cov"]  = cov
    df["c_up"]   = up
    df["c_dn"]   = dn
    # Net direction, and the count that backs it. A group with 5 up and 2 down is
    # not the same as 5 up and 0 down, so the opposing count is kept, not netted
    # away -- that opposition IS the divergence context.
    df["c_dir"]  = np.where(up > dn, 1, np.where(dn > up, -1, 0))
    df["c_n"]    = np.where(up >= dn, up, dn)
    df["c_spread"] = P.max(axis=1) - P.min(axis=1)
    df["c_med"]  = P.median(axis=1)
    df.loc[cov < MIN_LEGS, ["c_dir", "c_n"]] = [0, 0]
    df.attrs["legs"] = LEGS
    df.attrs["leg_cov"] = {k: int(P[k].notna().sum()) for k in KEYS}
    return df
