"""Historical forward-performance for each signal type."""
import pandas as pd, numpy as np, os
from math import comb
from universe import PRICE_MAP

D = os.path.expanduser("~/pos")
H1, H2 = 21, 63
SHORT_T, BOTH_T, OI_T = 10.0, 20.0, 20.0

def _binom_p(k, n):
    """Two-sided sign test vs p=0.5. n is the (small) EFFECTIVE count."""
    n = int(max(n, 1)); k = int(round(k * n / 100.0))
    if n < 2: return np.nan
    tail = sum(comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2**n
    return min(1.0, 2 * tail)

def _qual(v52, v3y, side):
    if pd.isna(v52): return False
    if side < 0:
        return v52 <= SHORT_T or (v52 <= BOTH_T and pd.notna(v3y) and v3y <= BOTH_T)
    return v52 >= 100-SHORT_T or (v52 >= 100-BOTH_T and pd.notna(v3y) and v3y >= 100-BOTH_T)

def build(d, px, exclude_classes=(), universe=None):
    rows = []
    for code, (tk, _proxy) in PRICE_MAP.items():
        if tk not in px.columns: continue
        if universe is not None and code not in universe: continue
        g = d[d.cftc_contract_market_code == code].sort_values("date")
        if len(g) < 60: continue
        s = px[tk].dropna()
        if s.empty: continue
        idx = s.index
        pos = idx.searchsorted(g.date.values)
        pos = np.clip(pos, 0, len(s)-1)
        p0 = s.values[pos]
        f1 = s.values[np.clip(pos + H1, 0, len(s)-1)]
        f2 = s.values[np.clip(pos + H2, 0, len(s)-1)]
        ok = (pos + H2) < len(s)
        t = pd.DataFrame({
            "code": code, "date": g.date.values, "ok": ok,
            "r1": 100*(f1/p0 - 1), "r2": 100*(f2/p0 - 1),
            "ls52": g.ls_pctile52.values, "ls3": g.ls_pctile.values,
            "ss52": g.ss_pctile52.values, "ss3": g.ss_pctile.values,
            "cm52": g.comm_pctile52.values, "cm3": g.comm_pctile.values,
            "oia": g.oi_pctile_all.values})
        rows.append(t[t.ok])
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

SIGNALS = {
    "ls_short":  (lambda p: p.apply(lambda r: _qual(r.ls52, r.ls3, -1), axis=1), +1),
    "ls_long":   (lambda p: p.apply(lambda r: _qual(r.ls52, r.ls3, +1), axis=1), -1),
    "ss_short":  (lambda p: p.apply(lambda r: _qual(r.ss52, r.ss3, -1), axis=1), +1),
    "ss_long":   (lambda p: p.apply(lambda r: _qual(r.ss52, r.ss3, +1), axis=1), -1),
    "cm_short":  (lambda p: p.apply(lambda r: _qual(r.cm52, r.cm3, -1), axis=1), -1),
    "cm_long":   (lambda p: p.apply(lambda r: _qual(r.cm52, r.cm3, +1), axis=1), +1),
    "oi_low":    (lambda p: p.oia <= OI_T, 0),
    "oi_high":   (lambda p: p.oia >= 100-OI_T, 0),
}

def summarise(panel):
    out = {}
    if panel.empty: return out
    base1, base2 = panel.r1.median(), panel.r2.median()
    for key, (mk, direction) in SIGNALS.items():
        m = mk(panel)
        g = panel[m.fillna(False)] if hasattr(m, "fillna") else panel[m]
        n = len(g)
        if n < 20:
            out[key] = {"n": n, "insufficient": True}; continue
        med1, med2 = g.r1.median(), g.r2.median()
        if direction == 0:
            win = 100 * (g.r2.abs() > panel.r2.abs().median()).mean()
        else:
            win = 100 * ((np.sign(g.r1) == direction).mean() * 0.5
                       + (np.sign(g.r2) == direction).mean() * 0.5)
        n_eff = max(n / 13.0, 1)
        out[key] = {"n": n, "n_eff": n_eff,
                    "med21": med1, "med63": med2, "avg": (med1 + med2) / 2,
                    "excess21": med1 - base1, "excess63": med2 - base2,
                    "win": win, "p": _binom_p(win, n_eff),
                    "dir": direction, "insufficient": False}
    out["_base"] = {"med21": base1, "med63": base2, "n": len(panel)}
    return out

def label(st, key):
    s = st.get(key)
    if not s: return ""
    if s.get("insufficient"):
        return f"Only {s['n']} historical instances - too few to say anything."
    d = s["dir"]
    arrow = "up" if d > 0 else "down" if d < 0 else ""
    if d == 0:
        return (f"n={s['n']:,} (eff {s['n_eff']:.0f}) &middot; median fwd 21d "
                f"{s['med21']:+.2f}% / 63d {s['med63']:+.2f}% &middot; "
                f"{s['win']:.0f}% saw a bigger-than-typical move &middot; non-directional")
    sig = ("statistically meaningful" if s["p"] < 0.05 else
           "not statistically distinguishable from a coin flip")
    return (f"n={s['n']:,} (eff {s['n_eff']:.0f}) &middot; median fwd 21d {s['med21']:+.2f}% / "
            f"63d {s['med63']:+.2f}% &middot; <b>avg {s['avg']:+.2f}%</b> &middot; "
            f"win {s['win']:.0f}% (signal implies {arrow}) &middot; p={s['p']:.2f} - {sig}")
