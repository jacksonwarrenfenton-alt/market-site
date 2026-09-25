"""Does anything actually lead the dollar, and does the dollar lead risk?

The dashboard asserted relationships. This tests them, because an untested
overlay is decoration.

The hypothesis comes from jman's own research library. WSG 2026-03-31 states the
chain explicitly: "higher real rates are the market's hurdle-rate, as they rise
financial conditions tighten, growth rerates, P/E's contract, dollar appreciates
and cyclicals under-perform." WSG 2026-07-21 adds the switch: "widening credit
spreads would flip healthy tightening to unhealthy."

So there are three testable links, not one vague idea:

  A  real rates  ->  dollar
  B  dollar      ->  ROW vs US, and the liquidity-sensitive assets
  C  credit      ->  equity drawdown

Method. Weekly data, 2010-2026. For a driver X and target Y we correlate the
k-week change in X with the SUBSEQUENT k-week change in Y, for k in 1..26. Two
guards make the result honest:

  * Overlapping windows share almost all their data, so a naive t-stat on 871
    weekly observations is nonsense. Effective n is n/k, and significance uses
    that.
  * With ~10 drivers x ~8 targets x 6 horizons we are running hundreds of tests.
    Benjamini-Hochberg decides what survives; an uncorrected p<0.05 here would
    fire roughly 30 times on noise alone.

Leads are also compared against the CONTEMPORANEOUS correlation. A "leading"
relationship that is weaker than the same-week correlation is not a lead at all
-- it is the same move being measured twice, and that distinction is where most
macro overlays quietly fail.
"""
import pandas as pd, numpy as np, json, math, os

D = os.path.expanduser("~/pos")
HORIZONS = [1, 2, 4, 8, 13, 26]


def _load():
    lib = json.load(open(f"{D}/chartdata.json"))
    idx = pd.DatetimeIndex(lib["dates"])
    S = {k: pd.Series(v, index=idx, dtype="float64")
         for k, v in lib["series"].items()}
    return S


def _ratio(S, a, b):
    if a not in S or b not in S: return None
    return (S[a] / S[b]).replace([np.inf, -np.inf], np.nan)


def series(S):
    """Drivers and targets, built from what the library actually holds."""
    d = {}
    # --- drivers -------------------------------------------------------
    d["Dollar"] = S.get("UUP")
    # TIP/IEF rises when breakevens rise -> real rates FALL. Invert so the
    # driver reads "real rates rising", which is the direction WSG describes.
    r = _ratio(S, "TIP", "IEF")
    d["Real rates (inv TIP/IEF)"] = -np.log(r) if r is not None else None
    d["Credit (HYG/LQD)"] = _ratio(S, "HYG", "LQD")
    d["Curve (TLT/SHY)"] = _ratio(S, "TLT", "SHY")
    d["Yen"] = S.get("FXY")
    d["VIX"] = S.get("^VIX")
    d["Copper/Gold"] = _ratio(S, "COPX", "GLD")
    d["Long bond (TLT)"] = S.get("TLT")
    # --- targets -------------------------------------------------------
    t = {}
    t["Dollar"] = S.get("UUP")
    t["EEM/SPY"] = _ratio(S, "EEM", "SPY")
    t["EFA/SPY"] = _ratio(S, "EFA", "SPY")
    t["SPY"] = S.get("SPY")
    t["EEM"] = S.get("EEM")
    t["Gold"] = S.get("GLD")
    t["Copper miners"] = S.get("COPX")
    t["Crude"] = S.get("USO")
    t["Regional banks"] = S.get("KRE")
    return ({k: v for k, v in d.items() if v is not None and v.notna().sum() > 300},
            {k: v for k, v in t.items() if v is not None and v.notna().sum() > 300})


def _chg(s, k):
    s = s.astype("float64")
    return np.log(s).diff(k) if (s.dropna() > 0).all() else s.diff(k)


def _p(r, n_eff):
    if not np.isfinite(r) or n_eff < 6: return 1.0
    r = max(min(r, 0.999), -0.999)
    t = r * math.sqrt(max(n_eff - 2, 1) / (1 - r * r))
    # normal approximation is fine at these effective sample sizes
    return math.erfc(abs(t) / math.sqrt(2))


def run():
    S = _load()
    DR, TG = series(S)
    rows = []
    for dn, dv in DR.items():
        for tn, tv in TG.items():
            if dn == tn: continue
            for k in HORIZONS:
                x = _chg(dv, k)
                y = _chg(tv, k)
                fwd = y.shift(-k)                      # strictly subsequent
                f = pd.concat([x, fwd], axis=1).dropna()
                if len(f) < 80: continue
                lead = float(f.iloc[:, 0].corr(f.iloc[:, 1]))
                c = pd.concat([x, y], axis=1).dropna()
                same = float(c.iloc[:, 0].corr(c.iloc[:, 1]))
                n_eff = len(f) / k
                rows.append({
                    "driver": dn, "target": tn, "k": k,
                    "lead_r": lead, "same_r": same,
                    "gain": abs(lead) - abs(same),
                    "n": len(f), "n_eff": round(n_eff, 1),
                    "p": _p(lead, n_eff)})
    df = pd.DataFrame(rows)
    if df.empty: return df
    p = np.sort(df.p.values); m = len(p)
    ok = p <= (np.arange(1, m + 1) / m) * 0.10
    kmax = int(np.max(np.where(ok)[0]) + 1) if ok.any() else 0
    cut = p[kmax - 1] if kmax else -1
    df["bh"] = df.p <= cut
    # A real lead must beat the same-week relationship.
    df["true_lead"] = df.bh & (df.gain > 0.02)
    return df.sort_values("p").reset_index(drop=True)


if __name__ == "__main__":
    d = run()
    d.to_parquet(f"{D}/liqstudy.parquet")
    print(f"tests {len(d)} | BH survivors {int(d.bh.sum())} | "
          f"true leads {int(d.true_lead.sum())}")
    c = ["driver", "target", "k", "lead_r", "same_r", "gain", "n_eff", "p"]
    print("\n--- strongest surviving relationships ---")
    print(d[d.bh].head(18)[c].to_string(index=False))
    print("\n--- genuine LEADS (beat the same-week correlation) ---")
    print(d[d.true_lead].head(18)[c].to_string(index=False))
