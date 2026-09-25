"""Price series for the price/OI regime tag."""
import requests, pandas as pd, numpy as np, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from universe import PRICE_MAP

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
D = os.path.expanduser("~/pos")
CACHE = f"{D}/prices.parquet"

def _one(tk, rng="max"):
    for attempt in range(3):
        try:
            # period1/period2, NOT range="max": range="max" with interval=1d
            # silently returns MONTHLY bars, which quietly destroys the 50/200
            # DMA and every forward-return test built on this series.
            par = ({"period1": 0, "period2": 2000000000, "interval": "1d"}
                   if rng == "max" else {"range": rng, "interval": "1d"})
            r = requests.get(f"https://query{1+attempt%2}.finance.yahoo.com/v8/finance/chart/{tk}",
                             params=par, headers=UA, timeout=30)
            if r.status_code == 429:
                time.sleep(3 + 3*attempt); continue
            q = r.json()["chart"]["result"][0]
            s = pd.Series(q["indicators"]["quote"][0]["close"],
                          index=pd.to_datetime(q["timestamp"], unit="s")).dropna()
            s.index = s.index.tz_localize(None).normalize()
            return tk, s
        except Exception:
            time.sleep(1.5 + 2*attempt)
    return tk, None

ETF_CACHE = f"{D}/etf_prices.parquet"

def fetch_list(tickers, cache=None, force=False, maxage=43200, rng="max"):
    cache = cache or ETF_CACHE
    if os.path.exists(cache) and not force and time.time()-os.path.getmtime(cache) < maxage:
        px = pd.read_parquet(cache)
        if set(tickers) <= set(px.columns): return px
    out = {}
    with ThreadPoolExecutor(6) as ex:
        for f in as_completed([ex.submit(_one, t, rng) for t in sorted(set(tickers))]):
            tk, s = f.result()
            if s is not None and len(s) > 60: out[tk] = s
    px = pd.DataFrame(out).sort_index().ffill(limit=5)
    # MERGE, never replace. A caller asking for its own 60 tickers used to
    # overwrite the shared cache and silently delete every basket proxy that
    # was not in its list -- the audit caught it, but only after the fact.
    if os.path.exists(cache):
        try:
            old_px = pd.read_parquet(cache)
            keep = [c for c in old_px.columns if c not in px.columns]
            if keep:
                px = px.join(old_px[keep], how="outer").sort_index()
        except Exception:
            pass
    px.to_parquet(cache)
    print(f"etf prices: {px.shape[1]}/{len(set(tickers))} tickers", file=sys.stderr)
    return px

def fetch(force=False):
    if os.path.exists(CACHE) and not force and time.time()-os.path.getmtime(CACHE) < 43200:
        return pd.read_parquet(CACHE)
    tks = sorted({t for t,_ in PRICE_MAP.values()})
    out = {}
    with ThreadPoolExecutor(6) as ex:
        for f in as_completed([ex.submit(_one, t) for t in tks]):
            tk, s = f.result()
            if s is not None and len(s) > 60: out[tk] = s
    px = pd.DataFrame(out).sort_index().ffill(limit=5)
    px.to_parquet(CACHE)
    print(f"prices: {px.shape[1]}/{len(tks)} tickers", file=sys.stderr)
    return px

SPY_CACHE = f"{D}/spy.parquet"

def spy():
    """Daily SPY close -- the reference line every chart on the site is read
    against. Cheap: reuses the ETF price cache when SPY is already in it."""
    for c in (ETF_CACHE, SPY_CACHE):
        if not os.path.exists(c): continue
        try:
            px = pd.read_parquet(c)
            if "SPY" in px.columns and len(px) > 200 \
               and time.time() - os.path.getmtime(c) < 43200:
                return px["SPY"].dropna()
        except Exception:
            pass
    _, s = _one("SPY")
    if s is not None and len(s) > 200:
        s.to_frame("SPY").to_parquet(SPY_CACHE)
        return s
    for c in (ETF_CACHE, SPY_CACHE):
        if os.path.exists(c):
            try:
                px = pd.read_parquet(c)
                if "SPY" in px.columns: return px["SPY"].dropna()
            except Exception:
                pass
    return None

REGIME = {(1,1):("New longs","good"), (1,-1):("Short covering","warn"),
          (-1,1):("New shorts","bad"), (-1,-1):("Long liquidation","neut")}

def attach(cur, asof, lookback=13):
    px = fetch()
    asof = pd.Timestamp(asof)
    prior = asof - pd.Timedelta(weeks=lookback)
    def chg(tk):
        if tk not in px.columns: return np.nan
        s = px[tk].loc[:asof].dropna()
        p = px[tk].loc[:prior].dropna()
        if s.empty or p.empty: return np.nan
        return 100*(s.iloc[-1]/p.iloc[-1] - 1)
    cur = cur.copy()
    meta = cur.cftc_contract_market_code.map(lambda c: PRICE_MAP.get(c))
    cur["px_tkr"]   = meta.map(lambda m: m[0] if m else None)
    cur["px_proxy"] = meta.map(lambda m: bool(m[1]) if m else False)
    cur["px_chg_13w"] = cur.px_tkr.map(lambda t: chg(t) if t else np.nan)

    def tag(r):
        if pd.isna(r.px_chg_13w) or pd.isna(r.oi_chg_13w): return (None, None)
        if abs(r.px_chg_13w) < 2 or abs(r.oi_chg_13w) < 3: return ("Flat", "neut")
        return REGIME[(1 if r.px_chg_13w > 0 else -1, 1 if r.oi_chg_13w > 0 else -1)]
    t = cur.apply(tag, axis=1)
    cur["regime"]      = [x[0] for x in t]
    cur["regime_tone"] = [x[1] for x in t]
    return cur

if __name__ == "__main__":
    px = fetch(force="--force" in sys.argv)
    print(px.shape, "missing:",
          sorted({t for t,_ in PRICE_MAP.values()} - set(px.columns)))
