"""Short interest engine: screen universe -> FINRA/exchange SI via Nasdaq -> 2w/2w change + z."""
import requests, pandas as pd, numpy as np, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
D = os.path.expanduser("~/pos")

MIN_MCAP   = 750e6
MIN_DOLVOL = 25e6
MIN_ATRPCT = 4.0

def screener():
    f = f"{D}/universe_raw.json"
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < 86400:
        return pd.DataFrame(json.load(open(f)))
    r = requests.get("https://api.nasdaq.com/api/screener/stocks",
                     params={"tableonly":"true","limit":"10000","download":"true"},
                     headers=UA, timeout=90)
    rows = r.json()["data"]["rows"]
    json.dump(rows, open(f,"w"))
    return pd.DataFrame(rows)

def clean_universe():
    df = screener()
    df["mcap"] = pd.to_numeric(df.marketCap.astype(str).str.replace(",","").replace("",np.nan), errors="coerce")
    df["px"]   = pd.to_numeric(df.lastsale.astype(str).str.replace(r"[\$,]","",regex=True), errors="coerce")
    df = df[(df.mcap >= MIN_MCAP) & (df.px > 1)]
    df = df[~df.symbol.str.contains(r"[\^/]", na=False)]
    df = df[~df.name.str.contains("Warrant|Right|Unit|Preferred|Depositary|Notes|Trust Units",
                                   case=False, na=False)]
    return df[["symbol","name","mcap","px"]].drop_duplicates("symbol").reset_index(drop=True)

def bars(sym):
    try:
        r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}",
                         params={"range":"6mo","interval":"1d"}, headers=UA, timeout=20)
        q = r.json()["chart"]["result"][0]
        ind = q["indicators"]["quote"][0]
        d = pd.DataFrame({k: ind[k] for k in ("high","low","close","volume")}).dropna()
        if len(d) < 30: return None
        pc = d.close.shift(1)
        tr = pd.concat([d.high-d.low, (d.high-pc).abs(), (d.low-pc).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        px  = d.close.iloc[-1]
        return {"symbol":sym, "px":float(px), "atr_pct":float(100*atr/px),
                "dolvol":float((d.close*d.volume).tail(20).mean()),
                "ret_1m":float(100*(px/d.close.iloc[-21]-1)) if len(d)>21 else np.nan,
                "ret_3m":float(100*(px/d.close.iloc[-63]-1)) if len(d)>63 else np.nan}
    except Exception:
        return None

def si_hist(sym):
    try:
        r = requests.get(f"https://api.nasdaq.com/api/quote/{sym}/short-interest",
                         params={"assetclass":"stocks"}, headers=UA, timeout=20)
        t = r.json()["data"]["shortInterestTable"]["rows"]
        out = []
        for row in t:
            out.append({"date": pd.to_datetime(row["settlementDate"]),
                        "si": float(row["interest"].replace(",","")),
                        "adv": float(row["avgDailyShareVolume"].replace(",","")),
                        "dtc": float(row["daysToCover"])})
        d = pd.DataFrame(out).sort_values("date")
        d["symbol"] = sym
        return d
    except Exception:
        return None

def si_stockanalysis(sym):
    """NYSE/AMEX fallback: current + prior settlement only (no deep history)."""
    import re
    try:
        r = requests.get(f"https://stockanalysis.com/stocks/{sym.lower()}/statistics/",
                         headers=UA, timeout=20)
        t = r.text
        i = t.find("Short Selling Information")
        if i < 0: return None
        blk = re.sub(r"<[^>]+>", "|", t[i:i+2500])
        def grab(lbl):
            j = blk.find(lbl)
            if j < 0: return np.nan
            m = re.search(r"([\d,.]+)\s*([MKB])?", blk[j+len(lbl):j+len(lbl)+160])
            if not m: return np.nan
            v = float(m.group(1).replace(",", ""))
            return v * {"K":1e3,"M":1e6,"B":1e9}.get(m.group(2) or "", 1)
        cur, prev = grab("Short Interest"), grab("Short Previous Month")
        if not (cur > 0 and prev > 0): return None
        return pd.DataFrame([{"symbol":sym, "date":pd.NaT, "si":prev, "adv":np.nan, "dtc":np.nan},
                             {"symbol":sym, "date":pd.Timestamp.today().normalize(),
                              "si":cur, "adv":np.nan, "dtc":grab("Short Ratio")}])
    except Exception:
        return None

def pmap(fn, items, workers=24, label=""):
    out = []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fn, i): i for i in items}
        for n, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r is not None: out.append(r)
            if n % 250 == 0: print(f"  {label} {n}/{len(items)}", file=sys.stderr)
    return out

def market_history(h, min_symbols=150, min_overlap=100):
    """Market-wide short interest per settlement, CHAIN-LINKED.

    The naive version (sum of shares short per settlement) is worthless here
    because the panel is not constant: Nasdaq serves a rolling ~1yr per symbol,
    the ATR/$vol screen changes between settlements, and the stockanalysis
    fallback labels its names ONLY at the newest settlement. On the 30 Aug run
    that pushed coverage 359 -> 619 names in one step and printed a +57.9% jump
    that was pure composition -- exactly the kind of silent error this project
    keeps getting bitten by.

    So the level is a CHAIN-LINKED INDEX (base 100 at the first settlement):
    each step is the ratio of summed shares short across only the symbols present
    in BOTH that settlement and the one before. Composition changes then cancel
    and the index moves only on actual position changes. `total_si` is kept
    alongside as the raw sum, but it is reference, not signal, and `n_symbols`
    and `n_overlap` travel with every row so a coverage break stays visible.
    """
    if h is None or not len(h): return None
    g = h.dropna(subset=["date", "si"]).copy()
    rows = []
    for dte, x in g.groupby("date"):
        x = x.drop_duplicates("symbol")
        n = x.symbol.nunique()
        if n < min_symbols: continue
        adv = x.adv.replace(0, np.nan)
        rows.append({"date": dte, "n_symbols": n,
                     "total_si": float(x.si.sum()),
                     "med_dtc": float(x.dtc.median(skipna=True)),
                     "si_share": float(x.si.sum() / adv.sum()) if adv.notna().any() else np.nan,
                     "_map": dict(zip(x.symbol, x.si))})
    if len(rows) < 2: return None
    rows.sort(key=lambda r: r["date"])
    idx, ov = [100.0], [np.nan]
    for i in range(1, len(rows)):
        a, b = rows[i-1]["_map"], rows[i]["_map"]
        common = set(a) & set(b)
        ov.append(len(common))
        if len(common) < min_overlap:
            # too little overlap to link honestly -- carry the level, do not invent a move
            idx.append(idx[-1]); continue
        sa = sum(a[s] for s in common); sb = sum(b[s] for s in common)
        idx.append(idx[-1] * (sb / sa) if sa > 0 else idx[-1])
    for r in rows: r.pop("_map")
    m = pd.DataFrame(rows)
    m["si_index"] = idx
    m["n_overlap"] = ov
    m["chg"] = m.si_index.pct_change() * 100
    # z on the chain-linked index, EXPANDING so it is point-in-time
    mu = m.si_index.expanding(min_periods=6).mean()
    sd = m.si_index.expanding(min_periods=6).std()
    m["level_z"] = (m.si_index - mu) / sd.replace(0, np.nan)
    m.to_parquet(f"{D}/si_market.parquet")
    return m

def build():
    u = clean_universe()
    print(f"mcap-filtered universe: {len(u)}", file=sys.stderr)
    b = pd.DataFrame(pmap(bars, u.symbol.tolist(), label="bars"))
    m = u.drop(columns=["px"]).merge(b, on="symbol")
    scr = m[(m.atr_pct >= MIN_ATRPCT) & (m.dolvol >= MIN_DOLVOL)].copy()
    print(f"passes ATR/$vol screen: {len(scr)}", file=sys.stderr)

    syms = scr.symbol.tolist()
    hs = pmap(si_hist, syms, workers=16, label="si-nasdaq")
    h = pd.concat(hs) if hs else pd.DataFrame(columns=["symbol","date","si","adv","dtc"])
    missing = sorted(set(syms) - set(h.symbol.unique()))
    print(f"  nasdaq-listed covered: {h.symbol.nunique()}; "
          f"fallback needed: {len(missing)}", file=sys.stderr)
    nasdaq_settle = h.date.max() if len(h) else pd.Timestamp.today().normalize()
    hs2 = pmap(si_stockanalysis, missing, workers=12, label="si-fallback")
    if hs2:
        for x in hs2:
            x.loc[x.date.notna(), "date"] = nasdaq_settle
        h = pd.concat([h] + hs2, ignore_index=True)
    h["src"] = np.where(h.date.isna(), "prior", "cur")

    # PATCH E2a: merge with whatever history was staged from the Mac. Nasdaq only
    # serves a rolling ~1yr per symbol, so without this the series can never grow
    # past a year and any name that later fails the ATR/$vol screen loses its past.
    hp = f"{D}/si_hist.parquet"
    if os.path.exists(hp):
        try:
            old = pd.read_parquet(hp)
            h = pd.concat([old, h], ignore_index=True)
        except Exception as e:
            print(f"  could not merge prior si_hist: {e}", file=sys.stderr)
    h = (h.dropna(subset=["date"])
           .sort_values(["symbol", "date"])
           .drop_duplicates(["symbol", "date"], keep="last")
           .reset_index(drop=True))
    h.to_parquet(hp)
    print(f"si_hist: {h.symbol.nunique():,} symbols, {h.date.nunique()} settlements, "
          f"{h.date.min():%Y-%m-%d} -> {h.date.max():%Y-%m-%d}", file=sys.stderr)
    mh = market_history(h)
    if mh is not None:
        print(f"si_market: {len(mh)} settlements, "
              f"{mh.date.min():%Y-%m-%d} -> {mh.date.max():%Y-%m-%d}", file=sys.stderr)

    recs = []
    for sym, g in h.groupby("symbol"):
        g = g.sort_values("date", na_position="first").reset_index(drop=True)
        if len(g) < 2: continue
        g["pct_chg"] = g.si.pct_change() * 100
        cur = g.iloc[-1]
        deep = len(g) >= 6
        hist = g.pct_chg.iloc[:-1].dropna()
        z  = (cur.pct_chg - hist.mean()) / hist.std() if deep and len(hist) >= 5 and hist.std() > 0 else np.nan
        lvl = g.si.iloc[:-1]
        lz = (cur.si - lvl.mean()) / lvl.std() if deep and len(lvl) >= 5 and lvl.std() > 0 else np.nan
        recs.append({"symbol":sym, "settle":cur.date, "si":cur.si, "prev_si":g.si.iloc[-2],
                     "pct_chg":cur.pct_chg, "chg_z":z, "level_z":lz, "dtc":cur.dtc,
                     "si_periods":len(g)})
    r = pd.DataFrame(recs).merge(scr, on="symbol")
    r["si_dollar"] = r.si * r.px
    r.to_parquet(f"{D}/si_latest.parquet")
    return r

if __name__ == "__main__":
    r = build()
    print(f"\nSI universe: {len(r)}  latest settlement: {r.settle.max().date()}")
    show = ["symbol","name","pct_chg","chg_z","level_z","dtc","atr_pct","ret_1m"]
    x = r.dropna(subset=["chg_z"]).sort_values("chg_z")
    pd.set_option("display.width", 220)
    print("\n=== BIGGEST SHORT COVERS (2w/2w) ===")
    print(x.head(15)[show].to_string(index=False, float_format="%.2f"))
    print("\n=== BIGGEST SHORT BUILDS (2w/2w) ===")
    print(x.tail(15).iloc[::-1][show].to_string(index=False, float_format="%.2f"))
