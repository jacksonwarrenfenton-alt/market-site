"""Float / shares-outstanding, so short interest can be shown as % of float.

No existing feed in this codebase carries float or shares outstanding --
FINRA's bulk SI file and the NASDAQ screener cache (universe_raw.json) both
lack it, and Yahoo's batch quote endpoint (v7/finance/quote) now 401s
without an auth crumb this codebase has no mechanism to obtain. NASDAQ's own
api.nasdaq.com/api/company/{sym}/institutional-holdings carries "Total
Shares Outstanding" but nothing for ETFs, and it's shares outstanding, not
true float.

stockanalysis.com's per-symbol statistics page already gets scraped
elsewhere in this codebase (si.py's si_stockanalysis() NYSE/AMEX fallback)
and carries a genuine "Float" line for common stock -- shares outstanding
minus insider/restricted/control-block shares, the actual tradeable pool a
short position is squeezed against. Its ETF overview page carries "Shares
Out" instead: ETFs have no float concept (every share is created/redeemed
daily against NAV), so shares outstanding IS the right denominator there,
and is how exchanges themselves report ETF short-interest-as-%-of-shares.

Some names (OTC/pink-sheet ADRs, foreign private issuers with an F-suffix
ticker) have no stockanalysis.com page at all; those just come back empty
and the caller shows "--" rather than a wrong number.

Cached to floatdata.parquet keyed by symbol. Float moves slowly (buybacks,
secondary issuance, splits -- not day to day), so a rebuild only pays the
network cost for symbols not already cached inside MAX_AGE_DAYS.
"""
import pandas as pd, numpy as np, os, re, sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

D = os.path.expanduser("~/pos")
CACHE = f"{D}/floatdata.parquet"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
MAX_AGE_DAYS = 21


def _num(s):
    m = re.search(r"([\d,.]+)\s*([MKB])?", s)
    if not m:
        return np.nan
    v = float(m.group(1).replace(",", ""))
    return v * {"K": 1e3, "M": 1e6, "B": 1e9}.get(m.group(2) or "", 1)


def _grab(full_text, label, window=800, lookahead=200):
    """Find `label` in raw HTML and read the number that follows it.

    The window must be big enough to swallow whole tags before stripping --
    a short window can cut a tag off mid-attribute (e.g. `class="px-[5px]...`
    with no closing `>` yet), leaving that raw attribute text un-stripped, and
    a stray "5" from "px-[5px]" gets picked up as the value instead of the
    real number that comes later. Matches si.py's si_stockanalysis() pattern.
    Fallback only -- _grab_json below is the primary, more precise path.
    """
    j = full_text.find(label)
    if j < 0:
        return np.nan
    blk = re.sub(r"<[^>]+>", "|", full_text[j:j + window])
    return _num(blk[len(label):len(label) + lookahead])


def _grab_json(full_text, field_id):
    """The page also embeds its own stats as literal JS objects --
    {id:"float",title:"Float",value:"408.81M",hover:"408,810,880"} -- with an
    exact comma-formatted integer in `hover`. Parsing that directly sidesteps
    _grab's HTML-stripping fragility entirely; prefer this when it's present.
    """
    m = re.search(r'\{id:"' + re.escape(field_id) + r'",title:"[^"]*",value:"[^"]*",hover:"([^"]*)"\}',
                   full_text)
    if not m:
        return np.nan
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return np.nan


def _fetch_stock(sym):
    try:
        r = requests.get(f"https://stockanalysis.com/stocks/{sym.lower()}/statistics/",
                          headers=UA, timeout=20)
        if r.status_code == 200:
            t = r.text
            flt = _grab_json(t, "float")
            if not (flt > 0):
                flt = _grab(t, "Float")
            shares = _grab_json(t, "sharesout")
            if not (shares > 0):
                shares = _grab(t, "Shares Outstanding")
            if (flt > 0) or (shares > 0):
                return {"symbol": sym, "float": flt, "shares_out": shares, "kind": "stock"}
    except Exception:
        pass
    # FINRA's bulk file doesn't separate common stock from funds/ETFs/ADRs by
    # ticker alone -- a symbol that 404s as a stock (ACWX, and similar) is
    # worth one more try on the fund path before giving up on it.
    return _fetch_etf(sym)


def _fetch_etf(sym):
    try:
        r = requests.get(f"https://stockanalysis.com/etf/{sym.lower()}/",
                          headers=UA, timeout=20)
        if r.status_code != 200:
            return None
        shares = _grab(r.text, "Shares Out")
        if not (shares > 0):
            return None
        return {"symbol": sym, "float": np.nan, "shares_out": shares, "kind": "etf"}
    except Exception:
        return None


def _load_cache():
    # NB: index with ["asof"], never .asof -- DataFrame.asof is a real pandas
    # method (as-of lookups), so dot access silently returns the bound method
    # instead of the column and blows up downstream.
    if os.path.exists(CACHE):
        c = pd.read_parquet(CACHE)
        c["asof"] = pd.to_datetime(c["asof"])
        return c
    return pd.DataFrame(columns=["symbol", "float", "shares_out", "kind", "asof"])


def get(symbols=(), etfs=(), workers=12):
    """DataFrame indexed by symbol with float/shares_out, fetching only what
    the cache is missing or what's older than MAX_AGE_DAYS."""
    symbols = sorted(set(symbols) - set(etfs))
    etfs = sorted(set(etfs))
    cache = _load_cache()
    now = pd.Timestamp.today().normalize()
    fresh = set()
    if len(cache):
        fresh = set(cache[cache["asof"] >= now - pd.Timedelta(days=MAX_AGE_DAYS)].symbol)
    need_stock = [s for s in symbols if s not in fresh]
    need_etf = [s for s in etfs if s not in fresh]
    new_rows = []
    if need_stock or need_etf:
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(_fetch_stock, s): s for s in need_stock}
            futs.update({ex.submit(_fetch_etf, s): s for s in need_etf})
            for f in as_completed(futs):
                r = f.result()
                if r:
                    r["asof"] = now
                    new_rows.append(r)
        tried = set(need_stock) | set(need_etf)
        got = {r["symbol"] for r in new_rows}
        for s in tried - got:  # cache the miss too, so a dead OTC ticker isn't refetched every run
            new_rows.append({"symbol": s, "float": np.nan, "shares_out": np.nan,
                              "kind": "?", "asof": now})
    if new_rows:
        add = pd.DataFrame(new_rows)
        cache = cache[~cache.symbol.isin(add.symbol)]
        cache = pd.concat([cache, add], ignore_index=True)
        cache.to_parquet(CACHE, index=False)
    want = list(symbols) + list(etfs)
    out = cache[cache.symbol.isin(want)].drop_duplicates("symbol", keep="last")
    return out.set_index("symbol")


def pct_of_float(si, symbol, table):
    """Shares-short count -> % of float (stocks) or % of shares out (ETFs).
    NaN if the symbol has no float data (not fetched, or no page found)."""
    if table is None or symbol not in table.index or not np.isfinite(si):
        return np.nan
    row = table.loc[symbol]
    denom = row["float"]
    if not (denom > 0):
        denom = row["shares_out"]
    if not (denom > 0):
        return np.nan
    return 100.0 * si / denom


if __name__ == "__main__":
    import time
    t0 = time.time()
    syms = sys.argv[1:] or ["AAPL", "GME", "BYND", "TSGTF", "NVDA"]
    out = get(symbols=syms)
    pd.set_option("display.width", 200)
    print(out)
    print(f"{time.time()-t0:.1f}s for {len(syms)} symbols")
