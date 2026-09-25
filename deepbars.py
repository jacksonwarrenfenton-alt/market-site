"""10-year daily bar cache, used only for significance testing.

breadth.py fetches 2 years because that is all the live panels need. Testing
whether a breadth reading predicts SPY needs far more: at a 13-week forward
window, two years of daily observations is an effective n of about 10, which
cannot distinguish anything from chance. This pulls ten years into its own file
so the live cache is never disturbed.
"""
import pandas as pd, requests, time, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed

D = os.path.expanduser("~/pos")
OUT = f"{D}/bars_deep.parquet"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

def _one(sym, rng="10y"):
    for attempt in range(2):
        try:
            r = requests.get(
                f"https://query{1+attempt}.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"range": rng, "interval": "1d"}, headers=UA, timeout=25)
            if r.status_code == 429:
                time.sleep(2 + 2*attempt); continue
            q = r.json()["chart"]["result"][0]
            ind = q["indicators"]["quote"][0]
            d = pd.DataFrame({"close": ind["close"], "volume": ind["volume"]},
                             index=pd.to_datetime(q["timestamp"], unit="s"))
            d.index = d.index.tz_localize(None).normalize()
            d = d.dropna()
            if len(d) < 250: return None
            d["symbol"] = sym
            return d
        except Exception:
            time.sleep(1 + attempt)
    return None

def fetch(syms, workers=12):
    out, fails = [], []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_one, s): s for s in syms}
        for i, f in enumerate(as_completed(futs)):
            r = f.result()
            (out if r is not None else fails).append(r if r is not None else futs[f])
            if (i+1) % 400 == 0: print(f"  deep {i+1}/{len(syms)}", file=sys.stderr, flush=True)
    for s in fails[:300]:
        r = _one(s)
        if r is not None: out.append(r)
        time.sleep(0.35)
    b = pd.concat(out).reset_index().rename(columns={"index": "date"})
    b.to_parquet(OUT)
    print(f"deep bars: {b.symbol.nunique()}/{len(syms)} symbols, "
          f"{b.date.min().date()} -> {b.date.max().date()}", file=sys.stderr, flush=True)
    return b

if __name__ == "__main__":
    import breadth as BR
    u = BR.universe()
    fetch(sorted(u.symbol.unique()))
