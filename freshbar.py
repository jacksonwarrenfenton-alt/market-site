"""Per-feed freshness, on the page.

Every feed here updates on a different clock -- COT weekly, FINRA twice monthly,
liqn daily, earnings and the macro calendar rolling. A single "as of" date in
the header is therefore a lie about most of the page. This shows each feed's own
age and marks the ones that have gone past their expected cadence, so a stale
panel announces itself instead of quietly serving last month's reading.
"""
import os, json, html
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")


def _age(ts):
    if ts is None: return None
    try: return (pd.Timestamp.today().normalize() - pd.Timestamp(ts).normalize()).days
    except Exception: return None


def feeds():
    out = []

    def add(name, ts, expect, note=""):
        a = _age(ts)
        out.append({"name": name, "date": str(ts)[:10] if ts is not None else "—",
                    "age": a, "stale": (a is not None and a > expect), "note": note})

    try:
        c = pd.read_parquet(f"{D}/cot_built.parquet", columns=["date"])
        add("COT", c.date.max(), 10, "CFTC, weekly")
    except Exception: pass
    try:
        a = pd.read_parquet(f"{D}/si_finra.parquet", columns=["settlementDate"])
        add("Short interest", a.settlementDate.max(), 22, "FINRA, twice monthly")
    except Exception: pass
    try:
        import flows as F
        fl, _ = F.basket_flows()
        add("ETF flows", fl.date.max(), 12, "weekly")
    except Exception: pass
    try:
        b = pd.read_parquet(f"{D}/bars.parquet", columns=["date"])
        add("Prices / breadth", b.date.max(), 5, "daily bars")
    except Exception: pass
    try:
        import liqn
        d = liqn.load(); add("Crowd sentiment", d.dt.max(), 3, "liqn.ai, daily")
    except Exception: pass
    try:
        v = pd.read_csv(f"{D}/vix_term.csv"); add("VIX term", v.date.max(), 3, "CBOE, daily")
    except Exception: pass
    try:
        e = pd.read_parquet(f"{D}/earnings.parquet", columns=["date"])
        add("Earnings calendar", e.date.min(), 10, "Nasdaq, forward 90d")
    except Exception: pass
    try:
        j = json.load(open(f"{D}/econcal.json"))
        add("Macro calendar", max(x["date"] for x in j), 9, "ForexFactory, weekly")
    except Exception: pass
    try:
        s = pd.read_csv(f"{D}/tv_scan.csv")
        add("TradingView scan", s.date.iloc[-1] if "date" in s else None, 40, "manual walk")
    except Exception: pass
    return out


def panel():
    fs = feeds()
    if not fs: return ""
    n_stale = sum(1 for f in fs if f["stale"])
    chips = "".join(
        f'<span class="fchip{" old" if f["stale"] else ""}" '
        f'title="{html.escape(f["note"])}">{html.escape(f["name"])}'
        f'<i>{f["date"]}'
        + (f' &middot; {f["age"]}d' if f["age"] is not None else "")
        + '</i></span>' for f in fs)
    msg = ("every feed is inside its expected cadence" if not n_stale
           else f"<b>{n_stale}</b> feed{'s' if n_stale > 1 else ''} past the cadence "
                "it should refresh on &mdash; amber below")
    return ('<h2>Data freshness</h2>'
            f'<p class="grpnote">Each feed on its own clock, {msg}. A single '
            '&ldquo;as of&rdquo; date in the header would be wrong about most of this '
            'page, so every source carries its own. Amber means the feed has gone '
            'past its normal update window and the panel above it may be serving a '
            'stale reading.</p>'
            f'<div class="fresh">{chips}</div>')
