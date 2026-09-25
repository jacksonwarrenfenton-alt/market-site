"""Per-contract, per-cohort signal efficacy."""
import pandas as pd, numpy as np, os, math

D = os.path.expanduser("~/pos")
FWD = 13
OVERLAP = FWD
THRESH = 15.0
MIN_N = 40
TILT_GAIN = 0.6

COHORTS = {
    "ls":   ("ls_pctile52",   -1, "Large spec"),
    "ss":   ("ss_pctile52",   -1, "Small spec"),
    "comm": ("comm_pctile52", +1, "Commercial"),
    "oi":   ("oi_pctile52",   -1, "Open interest"),
}

def _sign_z(hit, n_eff):
    if n_eff <= 0: return 0.0
    return (hit - 0.5) / math.sqrt(0.25 / n_eff)

def _p_two(z):
    return math.erfc(abs(z) / math.sqrt(2))

def _fwd_returns(px, dates, fwd_weeks=FWD):
    s = px.dropna()
    if s.empty: return np.full(len(dates), np.nan)
    now = s.reindex(dates, method="ffill").values
    later = s.reindex(dates + pd.Timedelta(weeks=fwd_weeks), method="ffill").values
    with np.errstate(all="ignore"):
        return 100 * (later / now - 1)

def build(d, px, universe, price_map, thresh=THRESH):
    rows = []
    for code in universe:
        tk = (price_map.get(code) or (None, None))[0]
        if not tk or tk not in px.columns: continue
        g = d[d.cftc_contract_market_code == code].sort_values("date")
        if len(g) < 120: continue
        dates = pd.DatetimeIndex(g.date)
        fwd = _fwd_returns(px[tk], dates)
        ok = np.isfinite(fwd)
        if ok.sum() < 120: continue
        base = float(np.nanmedian(fwd[ok]))
        for ck, (col, sign, label) in COHORTS.items():
            if col not in g: continue
            p = g[col].values
            for side, tail in (("long", "hi"), ("short", "lo")):
                m = ok & (np.isfinite(p))
                m &= (p >= 100 - thresh) if tail == "hi" else (p <= thresh)
                n = int(m.sum())
                if n < MIN_N: continue
                dirn = sign if side == "long" else -sign
                excess = (fwd[m] - base) * dirn
                n_eff = max(n / OVERLAP, 1.0)
                hit = float((excess > 0).mean())
                z = _sign_z(hit, n_eff)
                tilt = math.tanh(z / 2)
                rows.append({
                    "code": code, "cohort": ck, "cohort_label": label, "side": side,
                    "n": n, "n_eff": round(n_eff, 1), "hit": 100*hit,
                    "med_excess": float(np.median(excess)),
                    "base": base, "z": z, "p": _p_two(z), "tilt": tilt,
                    "w": 1 + TILT_GAIN * tilt})
    return pd.DataFrame(rows)

def table(eff):
    if eff is None or eff.empty: return {}
    return {(r.code, r.cohort, r.side): r for r in eff.itertuples()}

def bh_survivors(eff, q=0.10):
    """Benjamini-Hochberg. With 460 tests on one dataset, an uncorrected p<0.05
    would be expected to fire ~23 times on pure noise, so the uncorrected count
    is not evidence of anything on its own."""
    if eff is None or eff.empty: return 0
    p = np.sort(eff.p.values); m = len(p)
    ok = p <= (np.arange(1, m + 1) / m) * q
    return int(np.max(np.where(ok)[0]) + 1) if ok.any() else 0


def summary(eff):
    if eff is None or eff.empty: return "no efficacy rows"
    sig = eff[eff.p < 0.05]
    surv = bh_survivors(eff)
    return (f"{len(eff)} contract x cohort x side combinations tested on 1986-onward COT &middot; "
            f"median effective n {eff.n_eff.median():.0f} &middot; "
            f"{len(sig)} reach p&lt;0.05 ({100*len(sig)/len(eff):.0f}%), "
            f"{int((eff.tilt>0.3).sum())} tilt positive, {int((eff.tilt<-0.3).sum())} negative &middot; "
            f"<b>{surv} survive Benjamini-Hochberg at q=0.10</b>. Open interest was "
            f"dropped from the ranked signals on 2026-09-01 after failing at every "
            f"horizon (4w 50.0%, 13w 48.2%, 26w 48.6%) and adding nothing as a "
            f"conditioner on large-spec extremes; it remains on the charts as context.")
