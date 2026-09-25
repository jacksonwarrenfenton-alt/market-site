"""Is each feed actually current, and when does the next one land?"""
import pandas as pd, datetime as dt

def _bd_add(d, n):
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5: n -= 1
    return d

def cot(asof, today=None):
    """COT: Tuesday snapshot, released the following Friday 15:30 ET."""
    today = pd.Timestamp(today or dt.date.today()).normalize()
    asof = pd.Timestamp(asof).normalize()
    published = asof + pd.Timedelta(days=3)
    nxt_asof = asof + pd.Timedelta(days=7)
    nxt_pub = nxt_asof + pd.Timedelta(days=3)
    stale = today > nxt_pub
    return {"feed": "CFTC COT", "asof": asof, "published": published,
            "next_asof": nxt_asof, "next_pub": nxt_pub, "stale": stale,
            "cadence": "weekly &middot; Tue snapshot, Fri 15:30 ET release"}

def _settlements(year):
    out = []
    for m in range(1, 13):
        mid = pd.Timestamp(year=year, month=m, day=15)
        end = mid + pd.offsets.MonthEnd(0)
        for d in (mid, end):
            while d.weekday() >= 5: d -= pd.Timedelta(days=1)
            out.append(d)
    return sorted(set(out))

def finra(settle, today=None):
    """FINRA short interest: 15th and last business day, out ~8 business days."""
    today = pd.Timestamp(today or dt.date.today()).normalize()
    s = pd.Timestamp(settle).normalize()
    published = pd.Timestamp(_bd_add(s.date(), 8))
    cal = _settlements(s.year) + _settlements(s.year + 1)
    nxt = next(d for d in cal if d > s)
    nxt_pub = pd.Timestamp(_bd_add(nxt.date(), 8))
    return {"feed": "FINRA short interest", "asof": s, "published": published,
            "next_asof": nxt, "next_pub": nxt_pub, "stale": today > nxt_pub,
            "cadence": "twice monthly &middot; 15th &amp; month-end, ~8 business days later"}

def flows(asof, today=None, est_from=None):
    """est_from: the last date backed by the etfdb daily series. Weeks after it are
    reconstructed from shares outstanding (AUM/close at both endpoints) and are
    ESTIMATES -- they must never be presented as etfdb dailies."""
    today = pd.Timestamp(today or dt.date.today()).normalize()
    a = pd.Timestamp(asof).normalize()
    nxt = a + pd.Timedelta(days=7)
    cad = "weekly &middot; etfdb daily series summed to Friday"
    if est_from is not None and pd.Timestamp(est_from) < a:
        cad = (f"etfdb dailies through <b>{pd.Timestamp(est_from):%d %b}</b> &middot; "
               f"weeks after that are <b>estimated</b> from shares outstanding "
               f"(AUM/close), not etfdb dailies")
    return {"feed": "ETF flows", "asof": a, "published": a + pd.Timedelta(days=2),
            "next_asof": nxt, "next_pub": nxt + pd.Timedelta(days=2),
            "stale": today > nxt + pd.Timedelta(days=4),
            "cadence": cad}

def unavailable(feed, why, cadence=""):
    """A feed that produced NO data this run (PATCH A2).

    A feed with no data must never borrow another feed's as-of date."""
    return {"feed": feed, "missing": True, "why": why, "cadence": cadence,
            "stale": True}

def panel(rows):
    """Compact HTML strip: one line per feed with a CURRENT / STALE verdict."""
    out = []
    for r in rows:
        if r.get("missing"):
            out.append(
                f'<div class="fr"><span class="frn">{r["feed"]}</span>'
                f'<span class="frv bad">UNAVAILABLE</span>'
                f'<span class="frd">{r["why"]}</span>'
                f'<span class="frc">{r["cadence"]}</span></div>')
            continue
        tone = "bad" if r["stale"] else "good"
        word = "STALE" if r["stale"] else "CURRENT"
        out.append(
            f'<div class="fr"><span class="frn">{r["feed"]}</span>'
            f'<span class="frv {tone}">{word}</span>'
            f'<span class="frd">as of <b>{r["asof"]:%d %b}</b> &middot; '
            f'published {r["published"]:%d %b} &middot; '
            f'next <b>{r["next_asof"]:%d %b}</b> data out {r["next_pub"]:%d %b}</span>'
            f'<span class="frc">{r["cadence"]}</span></div>')
    return '<div class="fresh">' + "".join(out) + "</div>"
