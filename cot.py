"""COT engine: full CFTC legacy universe, 3 cohorts (large spec / commercial / small spec)."""
import requests, pandas as pd, numpy as np, os, sys, json, time

CACHE = os.path.expanduser("~/pos/cot_raw.parquet")
BASE = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
COLS = ",".join([
    "report_date_as_yyyy_mm_dd","market_and_exchange_names","contract_market_name",
    "cftc_contract_market_code","cftc_market_code","commodity_name","open_interest_all",
    "noncomm_positions_long_all","noncomm_positions_short_all","noncomm_postions_spread_all",
    "comm_positions_long_all","comm_positions_short_all",
    "nonrept_positions_long_all","nonrept_positions_short_all",
])

def fetch(since="1986-01-01", force=False):
    if os.path.exists(CACHE) and not force:
        return pd.read_parquet(CACHE)
    rows, off, lim = [], 0, 50000
    while True:
        # PATCH C1: the Socrata endpoint intermittently truncates a chunked
        # response (IncompleteRead) part-way through a 50k page. Without a retry
        # the whole 1986-onward pull dies and the run has no COT data at all.
        b = None
        for attempt in range(6):
            try:
                r = requests.get(BASE, params={
                    "$select": COLS, "$where": f"report_date_as_yyyy_mm_dd >= '{since}T00:00:00'",
                    "$order": "report_date_as_yyyy_mm_dd", "$limit": lim, "$offset": off}, timeout=180)
                r.raise_for_status()
                b = r.json()
                break
            except Exception as e:
                print(f"  retry {attempt+1} at offset {off}: {e}", file=sys.stderr)
                time.sleep(3 + 4*attempt)
        if b is None:
            raise RuntimeError(f"COT fetch failed at offset {off} after 6 attempts")
        if not b: break
        rows += b; off += lim
        print(f"  fetched {off}", file=sys.stderr)
        if len(b) < lim: break
    df = pd.DataFrame(rows)
    num = [c for c in df.columns if c not in
           ("report_date_as_yyyy_mm_dd","market_and_exchange_names","contract_market_name",
            "cftc_contract_market_code","cftc_market_code","commodity_name")]
    for c in num: df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"]).dt.tz_localize(None).dt.normalize()
    df.to_parquet(CACHE)
    return df

W52, W3Y = 52, 156

def _roll(series, key, win, minp, how):
    g = series.groupby(key, sort=False)
    if how == "z":
        mu = g.transform(lambda s: s.rolling(win, min_periods=minp).mean())
        sd = g.transform(lambda s: s.rolling(win, min_periods=minp).std())
        return (series - mu) / sd.replace(0, np.nan)
    if how == "pctile":
        return g.transform(lambda s: s.rolling(win, min_periods=minp).rank(pct=True) * 100)
    raise ValueError(how)

def build(df, min_oi=5000):
    d = df.copy()
    d["ls_net"]   = d.noncomm_positions_long_all - d.noncomm_positions_short_all
    d["comm_net"] = d.comm_positions_long_all - d.comm_positions_short_all
    d["ss_net"]   = d.nonrept_positions_long_all - d.nonrept_positions_short_all
    oi = d.open_interest_all.replace(0, np.nan)
    for k in ("ls","comm","ss"):
        d[f"{k}_pct"] = 100 * d[f"{k}_net"] / oi
    d = d.sort_values(["cftc_contract_market_code","date"])
    key = d.cftc_contract_market_code

    for k in ("ls","comm","ss"):
        p, raw = d[f"{k}_pct"], d[f"{k}_net"].astype(float)
        d[f"{k}_z52"]      = _roll(p,   key, W52, 40,  "z")
        d[f"{k}_z"]        = _roll(p,   key, W3Y, 104, "z")
        d[f"{k}_pctile52"] = _roll(p,   key, W52, 40,  "pctile")
        d[f"{k}_pctile"]   = _roll(p,   key, W3Y, 104, "pctile")
        d[f"{k}_rawz52"]   = _roll(raw, key, W52, 40,  "z")
        chg = p.groupby(key, sort=False).diff()
        d[f"{k}_chg"]    = chg
        d[f"{k}_chg_z"]  = _roll(chg, key, W3Y, 104, "z")
        d[f"{k}_chg_z52"]= _roll(chg, key, W52, 40,  "z")
        d[f"{k}_chg_pctile52"] = _roll(chg, key, W52, 40, "pctile")
        d[f"{k}_denom"]  = (d[f"{k}_z52"] - d[f"{k}_rawz52"]).abs() > 1.5

    o = d.open_interest_all.astype(float)
    d["oi_z52"]      = _roll(o, key, W52, 40,  "z")
    d["oi_z"]        = _roll(o, key, W3Y, 104, "z")
    d["oi_pctile52"] = _roll(o, key, W52, 40,  "pctile")
    d["oi_pctile_all"] = (o.groupby(key, sort=False)
                           .transform(lambda s: s.expanding(min_periods=52)
                                                 .rank(pct=True) * 100))
    d["oi_chg_13w"]  = 100 * (o / o.groupby(key, sort=False).shift(13) - 1)
    d["oi_chg_13w_z"]= _roll(d.oi_chg_13w, key, W3Y, 104, "z")
    d["oi_chg_1w"]   = 100 * (o / o.groupby(key, sort=False).shift(1) - 1)
    d["oi_chg_1w_z"] = _roll(d.oi_chg_1w, key, W3Y, 104, "z")

    d = d[d.open_interest_all >= min_oi]
    return d

def identity_check(df):
    """Legacy COT is an accounting identity: the three cohort nets sum to zero."""
    t = ((df.noncomm_positions_long_all - df.noncomm_positions_short_all)
       + (df.comm_positions_long_all   - df.comm_positions_short_all)
       + (df.nonrept_positions_long_all- df.nonrept_positions_short_all))
    return float((t.abs() <= 2).mean() * 100)

def latest(d):
    last = d.date.max()
    cur = d[d.date == last].copy()
    return last, cur

if __name__ == "__main__":
    df = fetch(force="--force" in sys.argv)
    print(f"rows={len(df)} contracts={df.cftc_contract_market_code.nunique()} "
          f"latest={df.date.max().date()}")
    d = build(df)
    last, cur = latest(d)
    print(f"latest report {last.date()}, {len(cur)} contracts pass OI filter, "
          f"{cur.ls_z.notna().sum()} with full z history")
    d.to_parquet(os.path.expanduser("~/pos/cot_built.parquet"))
