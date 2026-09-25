"""Market breadth -- the TLMM / Deepvue / Market Pulse style internals page."""
import requests, pandas as pd, numpy as np, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
D = os.path.expanduser("~/pos")
BARS = f"{D}/bars.parquet"
MAS = [5, 10, 21, 50, 200]
MIN_MCAP = 300e6

def _one(sym, rng="2y"):
    for attempt in range(2):
        try:
            r = requests.get(
                f"https://query{1+attempt}.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"range": rng, "interval": "1d"}, headers=UA, timeout=20)
            if r.status_code == 429:
                time.sleep(2 + 2*attempt); continue
            q = r.json()["chart"]["result"][0]
            ind = q["indicators"]["quote"][0]
            d = pd.DataFrame({"close": ind["close"], "volume": ind["volume"]},
                             index=pd.to_datetime(q["timestamp"], unit="s"))
            d.index = d.index.tz_localize(None).normalize()
            d = d.dropna()
            if len(d) < 60: return None
            d["symbol"] = sym
            return d
        except Exception:
            time.sleep(1 + attempt)
    return None

def universe():
    f = f"{D}/universe_raw.json"
    if not os.path.exists(f): return pd.DataFrame()
    df = pd.DataFrame(json.load(open(f)))
    df["mcap"] = pd.to_numeric(df.marketCap.astype(str).str.replace(",", "").replace("", np.nan),
                               errors="coerce")
    df["px"] = pd.to_numeric(df.lastsale.astype(str).str.replace(r"[\$,]", "", regex=True),
                             errors="coerce")
    df = df[(df.mcap >= MIN_MCAP) & (df.px > 1)]
    df = df[~df.symbol.str.contains(r"[\^/]", na=False)]
    df = df[~df.name.str.contains("Warrant|Right|Unit|Preferred|Depositary|Notes|Trust Units",
                                  case=False, na=False)]
    keep = [c for c in ["symbol", "name", "mcap", "sector", "industry"] if c in df.columns]
    return df[keep].drop_duplicates("symbol").reset_index(drop=True)

def fetch_bars(syms, force=False, workers=12):
    if os.path.exists(BARS) and not force and time.time() - os.path.getmtime(BARS) < 43200:
        b = pd.read_parquet(BARS)
        have = set(b.symbol.unique())
        # ~40 tickers legitimately fail every run (delisted, halted, bad symbol).
        # Requiring FULL containment made the cache never hit.
        if len(have & set(syms)) >= 0.97 * len(syms): return b
    out, fails = [], []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_one, s): s for s in syms}
        for i, f in enumerate(as_completed(futs)):
            r = f.result()
            if r is None: fails.append(futs[f])
            else: out.append(r)
            if (i+1) % 400 == 0: print(f"  bars {i+1}/{len(syms)}", file=sys.stderr)
    # Yahoo throttling looks exactly like a delisting, so retry failures serially
    for s in fails[:400]:
        r = _one(s)
        if r is not None: out.append(r)
        time.sleep(0.4)
    b = pd.concat(out).reset_index().rename(columns={"index": "date"})
    b.to_parquet(BARS)
    print(f"bars: {b.symbol.nunique()}/{len(syms)} symbols", file=sys.stderr)
    return b

def _pivot(b):
    c = b.pivot_table(index="date", columns="symbol", values="close")
    v = b.pivot_table(index="date", columns="symbol", values="volume")
    return c.sort_index(), v.reindex(c.index)

def compute(b, members=None, label="ALL"):
    if members is not None:
        b = b[b.symbol.isin(members)]
    if b.empty or b.symbol.nunique() < 5: return None
    c, v = _pivot(b)
    # Symbols do not all share a last bar -- a handful of stale or halted tickers
    # print a date almost nobody else traded, and the final pivot row then reads
    # 0 advances / 1 decline. Keep only dates where most of the group has a bar.
    cover = c.notna().sum(axis=1) / max(c.shape[1], 1)
    good = cover >= 0.60
    if good.sum() < 30: good = cover >= cover.quantile(0.5)
    c = c[good]; v = v.reindex(c.index)
    if c.empty or len(c) < 30: return None
    chg = c.diff()
    adv = (chg > 0).sum(axis=1)
    dec = (chg < 0).sum(axis=1)
    upv = (v.where(chg > 0)).sum(axis=1)
    dnv = (v.where(chg < 0)).sum(axis=1)
    # A rolling window that has not filled yet is NaN, and `c > NaN` is False --
    # which silently counts as "not above the MA" rather than "unknown". That
    # printed a flat 0% for the first ~100 sessions of % > 200d and 0 new highs
    # for the first 60, and those false zeros then dragged the MA-stack z-score
    # and every significance band built on the series. Each window now divides by
    # the names that actually HAVE that window, and reads NaN until enough do.
    def _share(mask, avail, minn=20):
        cnt = avail.sum(axis=1)
        out = 100 * (mask & avail).sum(axis=1) / cnt.replace(0, np.nan)
        return out.where(cnt >= minn)
    rmax = c.rolling(252, min_periods=60).max()
    rmin = c.rolling(252, min_periods=60).min()
    okhl = rmax.notna() & c.notna()
    nhl = okhl.sum(axis=1)
    hi52 = ((c >= rmax) & okhl).sum(axis=1).where(nhl >= 20)
    lo52 = ((c <= rmin) & okhl).sum(axis=1).where(nhl >= 20)
    pct = {}
    for m in MAS:
        ma = c.rolling(m, min_periods=max(3, m//2)).mean()
        pct[m] = _share(c > ma, ma.notna() & c.notna())
    rana = 1000 * (adv - dec) / (adv + dec).replace(0, np.nan)
    mco = rana.ewm(span=19, adjust=False).mean() - rana.ewm(span=39, adjust=False).mean()
    mcsi = mco.cumsum()
    hist = pd.DataFrame({"adv": adv, "dec": dec, "net": adv - dec,
                         "hi52": hi52, "lo52": lo52,
                         "upvol": upv, "dnvol": dnv, "mco": mco, "mcsi": mcsi})
    for m in MAS: hist[f"pct{m}"] = pct[m]
    hist = hist.dropna(subset=["adv"])
    last = hist.iloc[-1]
    n = int(c.notna().iloc[-1].sum())
    row = {"group": label, "n": n,
           "adv": int(last.adv), "dec": int(last.dec), "net": int(last.net),
           "net_ratio": 100*last.net/max(last.adv+last.dec, 1),
           "hi52": int(last.hi52) if pd.notna(last.hi52) else 0,
           "lo52": int(last.lo52) if pd.notna(last.lo52) else 0,
           "hl_net": int(last.hi52 - last.lo52),
           "hl_ratio": 100*(last.hi52-last.lo52)/max(n, 1),
           "updn": float(last.upvol/last.dnvol) if last.dnvol else np.nan,
           "mco": float(last.mco), "mcsi": float(last.mcsi)}
    for m in MAS: row[f"pct{m}"] = float(last[f"pct{m}"])
    z = []
    for m in MAS:
        s = hist[f"pct{m}"].tail(252)
        if len(s) > 40 and s.std() > 0:
            z.append(float((s.iloc[-1] - s.mean()) / s.std()))
    row["odb"] = float(np.mean(z) * 33) if z else np.nan
    return row, hist

def build(force=False):
    u = universe()
    if u.empty: return None, None, None
    b = fetch_bars(sorted(u.symbol.unique()), force=force)
    rows, hists = [], {}
    r = compute(b, None, "TOTAL MARKET")
    if r: rows.append(r[0]); hists["TOTAL MARKET"] = r[1]
    if "sector" in u.columns:
        for s, g in u.groupby("sector"):
            if not s or str(s).lower() == "nan": continue
            rr = compute(b, set(g.symbol), s)
            if rr: rows.append(rr[0]); hists[s] = rr[1]
    return pd.DataFrame(rows), hists, b
