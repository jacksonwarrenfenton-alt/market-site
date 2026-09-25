"""The chart library: real series, embedded in the page.

A published artifact cannot reach the internet. That is not a reason to let
Claude recall numbers from memory -- recalled prices are approximate and dated,
and a chart drawn from them looks exactly as authoritative as one drawn from
data. So the page carries its own data, and Claude's job is reduced to the part
it is actually good at: deciding WHICH series to plot and HOW to transform them.
Claude never supplies a number.

Everything is resampled to week-ending Friday. Daily resolution would multiply
the payload by five and buy nothing on charts that span years, and the whole
library has to fit inside the artifact alongside the rest of the site.
"""
import pandas as pd, numpy as np, json, os, sys

D = os.path.expanduser("~/pos")
START = "2010-01-01"

# Broad market, factor and macro proxies -- the vocabulary of a cross-asset
# overlay. Keys are what the user types; values are how they read on a chart.
EXTRA = {
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000",
    "MDY": "S&P Midcap", "DIA": "Dow 30", "RSP": "S&P equal weight",
    "TLT": "20y+ Treasuries", "IEF": "7-10y Treasuries", "SHY": "1-3y Treasuries",
    "TIP": "TIPS", "HYG": "High yield", "LQD": "Investment grade",
    "GLD": "Gold", "SLV": "Silver", "GDX": "Gold miners", "GDXJ": "Junior miners",
    "USO": "Crude oil", "UNG": "Natural gas", "DBC": "Broad commodity",
    "DBA": "Agriculture", "DBB": "Base metals", "DBP": "Precious metals",
    "UUP": "US dollar", "FXE": "Euro", "FXY": "Yen", "FXB": "Sterling",
    "EEM": "Emerging markets", "EFA": "Developed ex-US", "FXI": "China",
    "EWJ": "Japan", "EWZ": "Brazil", "INDA": "India",
    "XLE": "Energy", "XLF": "Financials", "XLK": "Technology",
    "XLV": "Health care", "XLI": "Industrials", "XLY": "Consumer disc",
    "XLP": "Consumer staples", "XLU": "Utilities", "XLB": "Materials",
    "XLRE": "Real estate", "XLC": "Comm services",
    "SOXX": "Semiconductors", "SMH": "Semis (VanEck)", "XBI": "Biotech",
    "IBB": "Biotech (large)", "XOP": "Oil & gas E&P", "XME": "Metals & mining",
    "KRE": "Regional banks", "ITB": "Homebuilders", "JETS": "Airlines",
    "ARKK": "ARK Innovation", "MTUM": "Momentum factor", "IBIT": "Bitcoin",
    "TAN": "Solar", "URA": "Uranium", "COPX": "Copper miners",
    "^VIX": "VIX", "VIXY": "VIX futures",
    # --- added 2026-09-02 on jman's list: real rates, vol-of-rates, the
    # precious-metals complex, EM currency, and the defensive/cyclical pairs
    "GDX": "Gold miners", "GDXJ": "Junior gold miners", "SIL": "Silver miners",
    "SILJ": "Junior silver miners", "PPLT": "Platinum", "PALL": "Palladium",
    "^MOVE": "MOVE (rate vol)", "^TNX": "US 10y yield", "^FVX": "US 5y yield",
    "^TYX": "US 30y yield", "BTC-USD": "Bitcoin", "ETHA": "Ethereum",
    "HEEM": "EM hedged", "CEW": "EM currencies", "HEFA": "Developed hedged",
    "RSPS": "Staples equal-wt", "RSPD": "Discretionary equal-wt",
    "VLUE": "Value factor", "QUAL": "Quality factor",
    "SPHB": "High beta", "SPLV": "Low volatility", "EWY": "Korea",
    "PSP": "Private equity", "BIZD": "BDCs", "IEI": "3-7y Treasuries",
    "XHB": "Homebuilders",
}


# Ratio pairs worth carrying as first-class series: each is a relationship the
# desk actually reads, not an arbitrary quotient. Built here so the chart
# builder, the scan and the dashboards all draw the identical number.
RATIOS = [
    ("GLD/TLT",   "GLD",  "TLT",  "Gold vs long bonds"),
    ("GLD/SLV",   "GLD",  "SLV",  "Gold/silver ratio"),
    ("GDX/GDXJ",  "GDX",  "GDXJ", "Senior vs junior gold miners"),
    ("SIL/GDX",   "SIL",  "GDX",  "Silver vs gold miners"),
    ("SILJ/SIL",  "SILJ", "SIL",  "Junior vs senior silver miners"),
    ("GDX/GLD",   "GDX",  "GLD",  "Miners vs metal"),
    ("COPX/GLD",  "COPX", "GLD",  "Copper vs gold"),
    ("GLD/USO",   "GLD",  "USO",  "Gold vs oil"),
    ("DBA/USO",   "DBA",  "USO",  "Ags vs energy"),
    ("XLP/XLY",   "XLP",  "XLY",  "Staples vs discretionary"),
    ("RSPS/RSPD", "RSPS", "RSPD", "Staples vs disc, equal weight"),
    ("ARKK/SPY",  "ARKK", "SPY",  "Speculative growth vs market"),
    ("MTUM/SPY",  "MTUM", "SPY",  "Momentum vs market"),
    ("SPHB/SPLV", "SPHB", "SPLV", "High beta vs low vol"),
    ("EEM/HEEM",  "EEM",  "HEEM", "EM currency effect"),
    ("EFA/HEFA",  "EFA",  "HEFA", "Developed currency effect"),
    ("EEM/SPY",   "EEM",  "SPY",  "EM vs US"),
    ("EFA/SPY",   "EFA",  "SPY",  "Developed vs US"),
    ("EWY/QQQ",   "EWY",  "QQQ",  "Korea vs Nasdaq"),
    ("FXI/SPY",   "FXI",  "SPY",  "China vs US"),
    ("HYG/IEI",   "HYG",  "IEI",  "Credit vs duration"),
    ("IEI/HYG",   "IEI",  "HYG",  "Duration vs credit"),
    ("HYG/LQD",   "HYG",  "LQD",  "High yield vs investment grade"),
    ("PSP/SPY",   "PSP",  "SPY",  "Private equity vs market"),
    ("BIZD/HYG",  "BIZD", "HYG",  "BDCs vs high yield"),
    ("XHB/SPY",   "XHB",  "SPY",  "Homebuilders vs market"),
    ("KRE/SPY",   "KRE",  "SPY",  "Regional banks vs market"),
    ("TLT/SHY",   "TLT",  "SHY",  "Curve proxy"),
    ("TIP/IEF",   "TIP",  "IEF",  "Breakevens"),
    ("BTC/GLD",   "BTC-USD", "GLD", "Bitcoin vs gold"),
    ("VLUE/QUAL", "VLUE", "QUAL", "Value vs quality"),
]


def _weekly(s):
    s = s.dropna()
    if s.empty: return None
    w = s.resample("W-FRI").last().dropna()
    return w[w.index >= START] if len(w) else None


def _pack(w, nd=4):
    return [None if not np.isfinite(v) else float(round(v, nd)) for v in w.values]


def build(max_series=460):
    lib, meta = {}, {}
    idx = None

    def add(key, label, group, w, unit=""):
        nonlocal idx
        if w is None or len(w) < 60: return
        if idx is None: idx = w.index
        else: idx = idx.union(w.index)
        lib[key] = w
        meta[key] = {"label": label, "group": group, "unit": unit}

    # ---- prices: ETFs and macro proxies ---------------------------------
    try:
        import prices as P
        want = sorted(EXTRA)
        px = P.fetch_list(want)
        for t in want:
            if t in px.columns:
                add(t, EXTRA[t], "Price", _weekly(px[t]), "px")
    except Exception as e:
        print("chartdata prices failed:", e, flush=True)

    # ---- ratios ---------------------------------------------------------
    try:
        for key, a, b, label in RATIOS:
            if a in lib and b in lib:
                r = (lib[a] / lib[b]).replace([np.inf, -np.inf], np.nan)
                add(f"R:{key}", label + f"  ({key})", "Ratio", r.dropna(), "ratio")
    except Exception as e:
        print("chartdata ratios failed:", e, flush=True)

    # ---- futures continuous, already cached ------------------------------
    try:
        pf = pd.read_parquet(f"{D}/prices.parquet")
        import universe as U
        cand = {}
        for code, (tk, _inv) in U.PRICE_MAP.items():
            if tk in pf.columns and tk not in lib:
                cand[tk] = tk
        for tk in list(cand)[:40]:
            add(tk, tk.replace("=F", " futures"), "Futures", _weekly(pf[tk]), "px")
    except Exception as e:
        print("chartdata futures failed:", e, flush=True)

    # ---- COT: percentile series per curated contract ---------------------
    try:
        cb = pd.read_parquet(f"{D}/cot_built.parquet")
        import universe as U
        for code in U.COT_UNIVERSE:
            g = cb[cb.cftc_contract_market_code == code]
            if not len(g): continue
            nm = str(g.contract_market_name.iloc[-1]).title()[:26]
            s = g.set_index("date").sort_index()
            for col, lab in (("ls_pctile52", "large spec %ile"),
                             ("comm_pctile52", "commercial %ile")):
                if col in s.columns:
                    add(f"COT:{code}:{col[:2]}", f"{nm} — {lab}", "COT",
                        _weekly(s[col]), "pct")
    except Exception as e:
        print("chartdata cot failed:", e, flush=True)

    # ---- breadth / Stockbee ---------------------------------------------
    try:
        h = pd.read_parquet(f"{D}/sb_hist_deep.parquet")
        import sbui
        for k, label, grp, _hot in sbui.SERIES:
            if k in h.columns:
                add(f"SB:{k}", label, "Breadth", _weekly(h[k]), "n")
    except Exception as e:
        print("chartdata breadth failed:", e, flush=True)

    # ---- market internals: McClellan + raw advance/decline -----------------
    # sb_hist_deep carries the Stockbee cohorts and pct50/pct200, but NOT the
    # McClellan oscillator/summation, the raw advance-decline line, up/down
    # volume, or the shorter %-above-MA windows. Those are computed inside
    # breadth.compute() and were never persisted, so the chart library -- and
    # therefore the AI chart builder and ticker desk that read it -- had no
    # access to them at all. Recomputed here from bars.parquet rather than
    # adding a new pipeline artefact, so nothing upstream has to change.
    # Wrapped: on the first (pre-step-2) chartdata run bars.parquet may not
    # exist yet, which is exactly why the recipe re-saves after step 2.
    try:
        import breadth as _BR
        _b = pd.read_parquet(f"{D}/bars.parquet")
        _r, _bh = _BR.compute(_b, None, "TOTAL MARKET")
        _INT = [("mco",   "McClellan Oscillator",        "n"),
                ("mcsi",  "McClellan Summation Index",   "n"),
                ("net",   "Net advancers (adv - decl)",  "n"),
                ("adv",   "Advancing issues",            "n"),
                ("dec",   "Declining issues",            "n"),
                ("hi52",  "New 52-week highs",           "n"),
                ("lo52",  "New 52-week lows",            "n"),
                ("pct5",  "% above 5-day MA",            "pct"),
                ("pct10", "% above 10-day MA",           "pct"),
                ("pct21", "% above 21-day MA",           "pct")]
        for col, label, unit in _INT:
            if col in _bh.columns:
                add(f"BR:{col}", label, "Breadth", _weekly(_bh[col]), unit)
        # up/down volume as a ratio -- the raw sums are dollar-ish magnitudes
        # that make any shared axis useless, the ratio is what gets read.
        if "upvol" in _bh.columns and "dnvol" in _bh.columns:
            _udr = (_bh.upvol / _bh.dnvol.replace(0, np.nan)).replace(
                [np.inf, -np.inf], np.nan)
            add("BR:updn", "Up/down volume ratio", "Breadth", _weekly(_udr), "x")
    except Exception as e:
        print("chartdata internals failed:", e, flush=True)

    # ---- ETF basket flows ------------------------------------------------
    try:
        import flows as F
        bw = F.basket_weekly()
        for b, g in bw.groupby("basket"):
            s = g.set_index("date").sort_index()
            add(f"FLOW:{b}", f"{b} — weekly flow $mn", "Flows",
                _weekly(s.flow / 1e6), "$mn")
    except Exception as e:
        print("chartdata flows failed:", e, flush=True)

    # ---- short interest breadth -----------------------------------------
    try:
        import siui
        d = siui.series()
        if d is not None and len(d):
            add("SI:net", "SI tilt — covering minus building %", "Short interest",
                _weekly(d.net_pct), "%")
            add("SI:cov", "Names covering hard", "Short interest",
                _weekly(d.covering), "n")
            add("SI:bld", "Names building hard", "Short interest",
                _weekly(d.building), "n")
    except Exception as e:
        print("chartdata si failed:", e, flush=True)

    if idx is None: return None
    idx = pd.DatetimeIndex(sorted(idx))
    keys = list(lib)[:max_series]
    out = {"dates": [d.strftime("%Y-%m-%d") for d in idx],
           "meta": {k: meta[k] for k in keys},
           "series": {k: _pack(lib[k].reindex(idx)) for k in keys}}
    return out


def save():
    o = build()
    if o is None:
        print("chartdata: nothing built", flush=True); return None
    p = f"{D}/chartdata.json"
    with open(p, "w") as f:
        json.dump(o, f, separators=(",", ":"))
    print(f"chart library: {len(o['series'])} series x {len(o['dates'])} weeks, "
          f"{os.path.getsize(p)/1e6:.1f} MB", flush=True)
    return o
