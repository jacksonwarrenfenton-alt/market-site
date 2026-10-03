"""Crowd attention from public, login-free sources -- the cloud stand-in for liqn.ai.

liqn.ai's crowd page sits behind a Google/X sign-in, so only the Mac's browser
can read it. The same reads can be built from two free public feeds that do not
share a source with each other:

  ApeWisdom (apewisdom.io)  Reddit mention counts per ticker, now and 24h ago,
                            ~900 names. Supplies posts, top-10 share, loudest,
                            attention breakouts/breakdowns, gaining/losing.
  StockTwits (api.stocktwits.com)
                            each loud name's recent messages with the posters'
                            own Bullish/Bearish tags -> a per-name verdict, and
                            the trending list -> a cross-source agreement check.

Rows use liqn.py's COLS and JSON shapes exactly, so liqn.panel() and
liqn.crowd_panel() render them unchanged. They go to their OWN file,
crowd_hist.csv, never into liqn_hist.csv -- different universes, and mixing them
would make a liqn history that is not liqn. liqn.load() falls back to this file
only when no liqn capture exists.

History: like liqn there is no archive to backfill; each run appends today's
row. A cloud container starts empty, so the caller must restore crowd_hist.csv
before calling and save it after (the daily trigger does this through the
project doc positioning/crowd_hist.csv).
"""
import os, sys, json, time
import pandas as pd, numpy as np, requests

D = os.path.expanduser("~/pos")
HIST = f"{D}/crowd_hist.csv"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
APE = "https://apewisdom.io/api/v1.0/filter/all-stocks/page/{}"
ST_TREND = "https://api.stocktwits.com/api/2/trending/symbols.json"
ST_STREAM = "https://api.stocktwits.com/api/2/streams/symbol/{}.json"

MIN_BREAKOUT = 25     # mentions today before a surge counts -- 3 -> 12 is noise
MIN_BREAKDOWN = 50    # mentions yesterday before a collapse counts
VERDICT_MIN_TAGS = 5  # tagged StockTwits messages needed to call a name
VERDICT_LEAN = 0.65   # bull (or bear) share of tagged messages for a verdict


def _get(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=20)
            if r.status_code == 429:
                time.sleep(3 + 3 * i); continue
            r.raise_for_status()
            return r.json()
        except Exception:
            time.sleep(1 + 2 * i)
    return None


def apewisdom():
    first = _get(APE.format(1))
    if not first:
        raise RuntimeError("ApeWisdom unreachable")
    rows = list(first.get("results", []))
    for p in range(2, int(first.get("pages", 1)) + 1):
        j = _get(APE.format(p))
        if j: rows += j.get("results", [])
    d = pd.DataFrame(rows)
    for c in ("mentions", "mentions_24h_ago", "rank", "rank_24h_ago", "upvotes"):
        if c in d: d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna(subset=["mentions"]).sort_values("mentions", ascending=False)


def stocktwits_verdict(sym):
    j = _get(ST_STREAM.format(sym), tries=2)
    if not j: return None
    tags = [((m.get("entities") or {}).get("sentiment") or {}).get("basic")
            for m in j.get("messages", [])]
    bull, bear = tags.count("Bullish"), tags.count("Bearish")
    n = bull + bear
    if n < VERDICT_MIN_TAGS: return {"t": sym, "bull": bull, "bear": bear, "v": None}
    v = ("BULLISH" if bull / n >= VERDICT_LEAN else
         "BEARISH" if bear / n >= VERDICT_LEAN else "MIXED")
    return {"t": sym, "bull": bull, "bear": bear, "v": v}


def _k(x):
    x = float(x)
    return f"{x/1000:.1f}k" if x >= 1000 else f"{x:.0f}"


def capture(asof=None, n_verdict=30):
    """One row in liqn's schema, plus a verification dict."""
    a = apewisdom()
    total = a.mentions.sum()
    prev_total = a.mentions_24h_ago.sum()
    top10 = a.head(10).mentions.sum()
    loud = [{"t": r.ticker, "posts": _k(r.mentions),
             "share": int(round(100 * r.mentions / total))}
            for r in a.head(12).itertuples()]
    b = a[(a.mentions >= MIN_BREAKOUT) & (a.mentions_24h_ago > 0)].copy()
    b["x"] = b.mentions / b.mentions_24h_ago
    brk = [{"t": r.ticker, "x": round(r.x, 1), "from": f"{r.mentions_24h_ago:,.0f}",
            "to": f"{r.mentions:,.0f}"}
           for r in b[b.x >= 2].sort_values("x", ascending=False).head(12).itertuples()]
    k = a[a.mentions_24h_ago >= MIN_BREAKDOWN].copy()
    k["pct"] = 100 * (k.mentions / k.mentions_24h_ago - 1)
    brkd = [{"t": r.ticker, "pct": int(round(r.pct)), "from": f"{r.mentions_24h_ago:,.0f}",
             "to": f"{r.mentions:,.0f}"}
            for r in k[k.pct <= -50].sort_values("pct").head(12).itertuples()]
    top = a.head(50).copy()
    top = top[top.mentions_24h_ago > 0]
    top["pct"] = 100 * (top.mentions / top.mentions_24h_ago - 1)
    mv = lambda r: {"t": r.ticker, "pct": int(round(r.pct)),
                    "from": _k(r.mentions_24h_ago), "to": _k(r.mentions)}
    gain = [mv(r) for r in top[top.pct > 0].sort_values("pct", ascending=False).head(12).itertuples()]
    lose = [mv(r) for r in top[top.pct < 0].sort_values("pct").head(12).itertuples()]

    verdicts = [v for v in (stocktwits_verdict(t) for t in a.head(n_verdict).ticker) if v]
    vs = [v["v"] for v in verdicts]

    trend = _get(ST_TREND) or {}
    st_syms = [s.get("symbol") for s in trend.get("symbols", [])]
    ape20 = set(a.head(20).ticker)
    overlap = sorted(ape20 & set(st_syms))

    asof = pd.Timestamp(asof) if asof is not None else pd.Timestamp.now("America/New_York")
    row = {
        "date": asof.strftime("%b %d %Y"),
        "posts": float(total),
        "broad_posts": float(total - top10),
        "top10_share": round(100 * top10 / total, 1) if total else np.nan,
        "conc_trend": np.nan,
        "typical_share": np.nan,
        "n_names": int(len(a)),
        "bull": vs.count("BULLISH"), "bear": vs.count("BEARISH"), "mixed": vs.count("MIXED"),
        "themes": json.dumps({}),
        "loudest": json.dumps(loud), "breakouts": json.dumps(brk),
        "breakdowns": json.dumps(brkd), "gaining": json.dumps(gain),
        "losing": json.dumps(lose),
    }
    check = {
        "source": "ApeWisdom (Reddit) + StockTwits",
        "names": int(len(a)), "posts": int(total),
        "posts_24h_ago": int(prev_total),
        "verdicts_called": sum(v is not None for v in vs), "verdicts_tried": len(verdicts),
        "stocktwits_trending": len(st_syms),
        "ape_top20_also_trending_on_stocktwits": overlap,
        "verdicts": verdicts,
    }
    return row, check


def append(row):
    import liqn
    d = pd.DataFrame([row])[liqn.COLS]
    if os.path.exists(HIST):
        old = pd.read_csv(HIST)
        d = pd.concat([old, d], ignore_index=True).drop_duplicates("date", keep="last")
    # typical_share / conc_trend are this feed's OWN history (liqn reads them off
    # its page; here they have to be earned): trailing-20-row mean of the top-10
    # share, and the change in that share over the last 14 rows.
    d["dt"] = pd.to_datetime(d.date, format="%b %d %Y", errors="coerce")
    d = d.sort_values("dt")
    s = pd.to_numeric(d.top10_share, errors="coerce")
    d["typical_share"] = s.shift().rolling(20, min_periods=3).mean().round(1)
    d["conc_trend"] = (s - s.shift(14)).round(1)
    d.drop(columns="dt").to_csv(HIST, index=False)
    return d


def run():
    row, check = capture()
    d = append(row)
    json.dump(check, open(f"{D}/crowd_verify.json", "w"), indent=1)
    print(f"crowd feed: {check['names']} names, {check['posts']:,} posts, top-10 "
          f"{row['top10_share']}%, verdicts {check['verdicts_called']}/{check['verdicts_tried']} "
          f"(bull {row['bull']} / bear {row['bear']} / mixed {row['mixed']}), "
          f"{len(check['ape_top20_also_trending_on_stocktwits'])} of Reddit's top 20 also "
          f"trending on StockTwits; history {len(d)} day(s)", file=sys.stderr, flush=True)
    return row, check


if __name__ == "__main__":
    run()
