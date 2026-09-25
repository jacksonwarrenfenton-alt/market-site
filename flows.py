"""ETF flow engine (basket-level)."""
import requests, pandas as pd, numpy as np, os, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from universe import ETF_BASKETS, INVERSE_ETFS

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
D = os.path.expanduser("~/pos")
STORE = f"{D}/etf_snapshots.parquet"
HIST  = f"{D}/etfdb_flows.parquet"
MIN_Z_OBS = 26
MIN_GAP_DAYS = 4

def _close(sym):
    """Latest close from the history API -- an independent, unscraped number."""
    try:
        r = requests.get(f"https://stockanalysis.com/api/symbol/e/{sym.lower()}"
                         "/history?range=5D&period=Daily", headers=UA, timeout=15)
        rows = r.json().get("data") or []
        for row in rows:
            c = row.get("c")
            if c and 0.5 <= float(c) <= 5000: return float(c)
    except Exception:
        pass
    return None

def snap(sym):
    try:
        r = requests.get(f"https://stockanalysis.com/etf/{sym.lower()}/", headers=UA, timeout=20)
        t = re.sub(r"<[^>]+>", "|", r.text)
        def grab(lbl):
            j = t.find(lbl)
            if j < 0: return np.nan
            m = re.search(r"\$?([\d,.]+)\s*([MKB])?", t[j+len(lbl):j+len(lbl)+160])
            if not m: return np.nan
            return float(m.group(1).replace(",", "")) * {"K":1e3,"M":1e6,"B":1e9}.get(m.group(2) or "", 1)
        aum = grab("Assets")
        px  = grab("NAV") or grab("Price")
        sh  = grab("Shares Out")
        if not (aum > 1e7): return None
        # The page's "Shares Out" is unreliable for some funds -- VTI reads 4.56x
        # the true count while its Assets figure is right to 0.2%. AUM/close is
        # the trustworthy derivation, so take the real close from the history API
        # and let the scraped share count only stand in when that call fails.
        close = _close(sym)
        if close and aum / close > 1e4:
            sh, px = aum / close, close
        if not (sh > 0) and px > 0: sh = aum / px
        if not (sh > 1e4): return None
        implied = aum / sh
        if not (0.5 <= implied <= 5000): return None
        if not (px and 0.5 <= px <= 5000) or not (0.5 <= px/implied <= 2.0):
            px = implied
        return {"symbol": sym, "aum": aum, "nav": px, "shares": sh}
    except Exception:
        return None

def take_snapshot(asof=None):
    asof = pd.Timestamp(asof or pd.Timestamp.today().normalize())
    syms = sorted({s for v in ETF_BASKETS.values() for s in v})
    out = []
    with ThreadPoolExecutor(12) as ex:
        for f in as_completed([ex.submit(snap, s) for s in syms]):
            r = f.result()
            if r: out.append(r)
    d = pd.DataFrame(out); d["date"] = asof
    d["nav"] = np.where(d.nav.notna() & (d.nav > 0), d.nav, d.aum / d.shares)
    if os.path.exists(STORE):
        old = pd.read_parquet(STORE)
        if len(old):
            last = old.date.max()
            if (asof - last).days < MIN_GAP_DAYS:
                old = old[old.date != last]
        d = pd.concat([old[old.date != asof], d], ignore_index=True)
    d.to_parquet(STORE)
    print(f"snapshot {asof.date()}: {len(out)}/{len(syms)} ETFs", file=sys.stderr)
    return d

def _fri(ts):
    ts = pd.to_datetime(ts)
    dow = ts.dt.dayofweek if hasattr(ts, "dt") else ts.dayofweek
    return ts + pd.to_timedelta((4 - dow) % 7, unit="D")

def per_etf_weekly():
    frames = []
    if os.path.exists(HIST):
        h = pd.read_parquet(HIST)
        h = pd.DataFrame({"symbol": h.symbol, "date": pd.to_datetime(h.date),
                          "flow": h.flow_bn * 1e9, "aum": h.aum_bn * 1e9})
        frames.append(h)
    cut = frames[0].date.max() if frames else pd.Timestamp.min

    if os.path.exists(STORE):
        s = pd.read_parquet(STORE).sort_values(["symbol", "date"])
        g = s.groupby("symbol")
        s["flow"] = g.shares.diff() * s.nav
        s["gap"] = g.date.diff().dt.days
        s.loc[(s.gap > 21) | (s.gap.isna()), "flow"] = np.nan
        s = s.dropna(subset=["flow"])
        s["date"] = _fri(s.date)
        s = s[s.date > cut]
        if len(s):
            frames.append(s.groupby(["symbol", "date"], as_index=False)
                           .agg(flow=("flow", "sum"), aum=("aum", "last")))
    if not frames:
        return None
    d = pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"])
    t2b = {s: b for b, v in ETF_BASKETS.items() for s in v}
    d["basket"] = d.symbol.map(t2b)
    d["inverse"] = d.symbol.isin(INVERSE_ETFS)
    d["flow_raw"] = d.flow
    # Inverse funds are sign-flipped EVERYWHERE, including inside the dedicated
    # short baskets. Earlier this exempted them so money in read as "bearish build",
    # but that makes the chart unusable as a signal: paired with a long price proxy
    # you want the line to read as NET LONG-EQUIVALENT positioning, so a deep
    # negative extreme at price lows is the crowd maximally short -- a contrarian
    # buy -- exactly like every other basket's washed-out reading. flow_raw keeps
    # the unflipped number if the gross short build is ever wanted.
    d.loc[d.inverse, "flow"] = -d.loc[d.inverse, "flow"]
    return d.dropna(subset=["basket"])

SQRT_W = 0.5   # AUM exponent for the normalised measure. 1.0 = pure dollar
               # weighting (one giant fund dictates), 0.0 = equal weighting (a
               # $20M fund counts as much as a $500B one). 0.5 sits between:
               # it "slightly lessens" the giants without pretending size is
               # irrelevant. Changing this changes every nflow_* number.

def basket_weekly_norm(win_hhi=12):
    """Per-basket flow INTENSITY, so one huge fund cannot speak for the group.

    The dollar sum is the real money and stays the headline, but it answers
    "how many dollars moved", not "how hard is this group being bought". In six
    of 29 baskets a single fund is >60% of all flow (SOXS 83%, XLP 81%, TLT 76%),
    so the dollar line is that one ticker wearing a basket costume.

        pct_i   = flow_i / aum_i                 each fund's own intensity
        w_i     = aum_i ** SQRT_W                sqrt-AUM weight
        nflow   = sum(w_i * pct_i) / sum(w_i)    weighted mean intensity, in %

    If every member moves +1% of its own AUM, nflow is +1% whatever the size
    spread. A giant moving alone still shows, but damped by the square root
    rather than dominating outright.

    eff_n = 1 / HHI of each member's share of ABSOLUTE flow over the trailing
    `win_hhi` weeks -- how many funds the basket effectively behaves like. It is
    the honesty column: nflow on a basket with eff_n 1.4 is still one fund.
    """
    d = per_etf_weekly()
    if d is None or d.empty: return None
    x = d.dropna(subset=["flow"]).copy()
    x["aum"] = pd.to_numeric(x["aum"], errors="coerce")
    x = x[x.aum > 0]
    if x.empty: return None
    x["pct"] = x.flow / x.aum
    x["w"] = x.aum ** SQRT_W
    x["wp"] = x.w * x.pct
    g = (x.groupby(["basket", "date"], as_index=False)
           .agg(wp=("wp", "sum"), w=("w", "sum")))
    g["nflow"] = 100 * g.wp / g.w.replace(0, np.nan)
    g = g[["basket", "date", "nflow"]]

    last = x.date.max()
    recent = x[x.date > last - pd.Timedelta(weeks=win_hhi)]
    eff = []
    for b, gg in recent.groupby("basket"):
        per = gg.groupby("symbol").flow.apply(lambda s: s.abs().sum())
        tot = per.sum()
        if tot <= 0:
            eff.append({"basket": b, "eff_n": np.nan, "top1": np.nan, "top_sym": ""})
            continue
        sh = (per / tot).sort_values(ascending=False)
        hhi = float((sh ** 2).sum())
        eff.append({"basket": b, "eff_n": 1/hhi if hhi > 0 else np.nan,
                    "top1": 100*float(sh.iloc[0]), "top_sym": str(sh.index[0])})
    return g, pd.DataFrame(eff)


def basket_weekly():
    d = per_etf_weekly()
    if d is None: return None
    return (d.groupby(["basket", "date"], as_index=False)
             .agg(flow=("flow", "sum"), aum=("aum", "sum"), n=("symbol", "nunique"))
             .sort_values(["basket", "date"]))

def basket_flows(win_1w=1, win_1m=4):
    bf = basket_weekly()
    if bf is None or bf.empty:
        return None, "no flow history"
    gb = bf.groupby("basket")
    for lbl, w in (("1w", win_1w), ("1m", win_1m)):
        roll = gb.flow.transform(lambda s: s.rolling(w, min_periods=1).sum())
        pct  = 100 * roll / bf.aum
        bf[f"flow_{lbl}"] = roll
        bf[f"pct_{lbl}"]  = pct
        gp = pct.groupby(bf.basket)
        mu = gp.transform("mean"); sd = gp.transform("std"); n = gp.transform("size")
        bf[f"z_{lbl}"] = np.where(n >= MIN_Z_OBS, (pct - mu) / sd.replace(0, np.nan), np.nan)

    # normalised intensity, rolled the same way as the dollar windows
    nrm = basket_weekly_norm()
    if nrm is not None:
        ng, eff = nrm
        bf = bf.merge(ng, on=["basket", "date"], how="left")
        gn = bf.groupby("basket")
        for lbl, w in (("1w", win_1w), ("1m", win_1m)):
            roll = gn.nflow.transform(lambda s: s.rolling(w, min_periods=1).mean())
            bf[f"nflow_{lbl}"] = roll
            gp = roll.groupby(bf.basket)
            mu = gp.transform("mean"); sd = gp.transform("std"); n = gp.transform("size")
            bf[f"nz_{lbl}"] = np.where(n >= MIN_Z_OBS,
                                       (roll - mu) / sd.replace(0, np.nan), np.nan)

    latest = bf[bf.date == bf.date.max()].copy()
    if nrm is not None:
        latest = latest.merge(eff, on="basket", how="left")
    nobs = int(gb.flow.size().min()), int(gb.flow.size().max())
    span = f"{bf.date.min():%b %Y}-{bf.date.max():%b %Y}"
    note = (f"rolling 1w and 1-month(4-week) windows &middot; {span} &middot; "
            f"{nobs[0]}-{nobs[1]} weekly observations per basket")
    return latest.sort_values("pct_1w", ascending=False), note

if __name__ == "__main__":
    l, note = basket_flows()
    print(note)
    if l is not None:
        pd.set_option("display.width", 220)
        print(l[["basket","flow_1w","pct_1w","z_1w","flow_1m","pct_1m","z_1m","aum","n"]]
              .to_string(index=False, float_format="%.3f"))
