"""VIX term structure: contango, backwardation, and when it is an outlier.

The curve is the signal, not the level. VIX at 16 in steep contango is a calm
market paying up for distant protection; VIX at 16 in backwardation means the
front is bid because something is happening NOW, and that inversion has marked
more turns than the level ever has.

Five tenors straight from CBOE: 1-day, 9-day, 30-day (the VIX itself), 3-month
and 6-month. The headline ratio is VIX / VIX3M -- the standard measure. Above 1
is backwardation.
"""
import urllib.request, ssl, json, os, html
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")
HIST = f"{D}/vix_term.csv"
CTX = ssl._create_unverified_context()
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/124"}
TENORS = [("_VIX1D", "VIX1D", 1), ("_VIX9D", "VIX9D", 9), ("_VIX", "VIX", 30),
          ("_VIX3M", "VIX3M", 93), ("_VIX6M", "VIX6M", 186)]


def snapshot():
    out = {}
    for sym, label, days in TENORS:
        try:
            u = f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/{sym}.json"
            r = urllib.request.urlopen(urllib.request.Request(u, headers=H),
                                       timeout=20, context=CTX)
            j = json.loads(r.read())
            v = (j.get("data") or {}).get("current_price")
            if v: out[label] = float(v)
        except Exception:
            pass
    if not out: return None
    row = {"date": pd.Timestamp.today().strftime("%Y-%m-%d"), **out}
    if "VIX" in out and "VIX3M" in out and out["VIX3M"]:
        row["ratio"] = out["VIX"] / out["VIX3M"]
    d = pd.DataFrame([row])
    if os.path.exists(HIST):
        old = pd.read_csv(HIST)
        d = pd.concat([old, d], ignore_index=True).drop_duplicates("date", keep="last")
    d.to_csv(HIST, index=False)
    return row


def panel():
    row = None
    if os.path.exists(HIST):
        h = pd.read_csv(HIST)
        if len(h): row = h.iloc[-1].to_dict()
    if row is None: row = snapshot()
    if not row: return ""
    pts = [(l, row.get(l)) for _s, l, _d in TENORS if np.isfinite(row.get(l, np.nan))]
    if len(pts) < 3: return ""
    ratio = row.get("ratio")
    if ratio is None or not np.isfinite(ratio):
        try: ratio = row["VIX"] / row["VIX3M"]
        except Exception: ratio = np.nan

    # Thresholds are the ones the curve is actually read by, not invented:
    # >1.00 is inversion, and >1.10 is the level that has historically coincided
    # with genuine stress rather than a wobble. Deep contango below 0.85 is the
    # complacent end.
    if not np.isfinite(ratio):      state, tone, say = "unavailable", "dim", ""
    elif ratio >= 1.10: state, tone = "STEEP BACKWARDATION", "crit"
    elif ratio >= 1.00: state, tone = "BACKWARDATION", "crit"
    elif ratio <= 0.82: state, tone = "STEEP CONTANGO", "warn"
    elif ratio <= 0.92: state, tone = "CONTANGO", "good"
    else:               state, tone = "FLAT", "dim"
    say = ("the front is bid because something is happening now &mdash; this is the "
           "shape that marks stress, and it unwinds fast when it resolves"
           if ratio >= 1.0 else
           "the curve is upward sloping &mdash; the market is calm and paying up for "
           "distant protection, which is the normal state and carries no urgency")

    W, Hh, PL, PR, PT, PB = 560, 190, 44, 16, 14, 26
    iw, ih = W - PL - PR, Hh - PT - PB
    vals = [v for _l, v in pts]
    mn, mx = min(vals), max(vals)
    pad = (mx - mn) * 0.22 or 1
    mn, mx = mn - pad, mx + pad
    X = lambda i: PL + iw * i / max(len(pts) - 1, 1)
    Y = lambda v: PT + ih - ih * (v - mn) / ((mx - mn) or 1)
    grid = "".join(
        f'<line x1="{PL}" y1="{PT+ih*k/3:.1f}" x2="{W-PR}" y2="{PT+ih*k/3:.1f}" '
        f'stroke="var(--grid)"/>'
        f'<text x="{PL-6}" y="{PT+ih*k/3+3.5:.1f}" text-anchor="end" class="ax">'
        f'{mx-(mx-mn)*k/3:.1f}</text>' for k in range(4))
    path = "".join(("M" if i == 0 else "L") + f"{X(i):.1f} {Y(v):.1f} "
                   for i, (_l, v) in enumerate(pts))
    dots = "".join(
        f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="3.2" fill="var(--cool)"/>'
        f'<text x="{X(i):.1f}" y="{Y(v)-9:.1f}" text-anchor="middle" class="ax sp">'
        f'{v:.1f}</text>'
        f'<text x="{X(i):.1f}" y="{Hh-8}" text-anchor="middle" class="ax">{l}</text>'
        for i, (l, v) in enumerate(pts))
    return (f'<h2>VIX term structure</h2>'
            f'<div class="vixbox"><div class="vixhead">'
            f'<div><h6>VIX / VIX3M</h6><div class="v">{ratio:.3f}</div></div>'
            f'<div><h6>Curve</h6><div class="v {tone}">{state}</div></div>'
            f'<div class="vixsay">{say}.</div></div>'
            f'<svg viewBox="0 0 {W} {Hh}" class="sbsvg vixsvg">{grid}'
            f'<path d="{path}" fill="none" stroke="var(--cool)" stroke-width="1.8"/>'
            f'{dots}</svg>'
            '<p class="dnote">Five CBOE tenors, delayed quotes. The ratio above 1.00 '
            'is inversion &mdash; the 30-day is bid over the 3-month. Above 1.10 has '
            'historically meant real stress rather than a wobble; below 0.82 is the '
            'complacent end of contango.</p></div>')
