"""One ranked positioning signal per contract."""
import pandas as pd, numpy as np

MIN_E = 0.60

# Open interest was REMOVED as a ranked signal on 2026-09-01. It was tested on
# the full 1986-onward record and failed everywhere it was asked to work:
#
#   OI extreme -> forward return, pooled across 116 contracts
#     4w  hit 50.0%  p=0.96   13w hit 48.2%  p=0.11   26w hit 48.6%  p=0.36
#   OI as a CONDITIONER on large-spec extremes (13w)
#     OI high 50.4%   OI low 50.2%   OI mid 50.0%   -- all p>0.82
#
# Zero of 116 contract x side combinations reached p<0.05, and none survived
# Benjamini-Hochberg at q=0.10. It is the only cohort with a NEGATIVE median
# excess at every horizon beyond four weeks. Open interest stays on the charts
# as context -- it describes participation, which is worth seeing -- but it no
# longer generates a signal or competes for a contract's ranked row.
COHORTS = [
    ("ls",   "ls_pctile52",   "ls_pctile",     "Large spec",    -1),
    ("ss",   "ss_pctile52",   "ss_pctile",     "Small spec",    -1),
    ("comm", "comm_pctile52", "comm_pctile",   "Commercial",    +1),
]

def _read(cohort, side):
    if cohort == "comm":
        return ("BULLISH", "commercials max long") if side == "long" \
          else ("BEARISH", "commercials max short")
    who = "large specs" if cohort == "ls" else "small specs"
    return ("BEARISH", f"{who} crowded long") if side == "long" \
      else ("BULLISH", f"{who} crowded short")

def build(cur, eff, disp_col="disp", class_col="cls"):
    look = {}
    if eff is not None and len(eff):
        for r in eff.itertuples():
            look[(r.code, r.cohort, r.side)] = r
    rows = []
    for _, r in cur.iterrows():
        code = r.cftc_contract_market_code
        best = None
        for ck, c52, c3y, label, sign in COHORTS:
            v52 = r.get(c52)
            if v52 is None or pd.isna(v52): continue
            v3y = r.get(c3y)
            e52 = (float(v52) - 50) / 50
            e3y = (float(v3y) - 50) / 50 if v3y is not None and pd.notna(v3y) else e52
            e = 0.6 * e52 + 0.4 * e3y
            side = "long" if e >= 0 else "short"
            ef = look.get((code, ck, side))
            w = float(ef.w) if ef is not None else 1.0
            score = 100 * abs(e) * w
            if best is None or score > best["score"]:
                read, phrase = _read(ck, side)
                best = {
                    "code": code, "name": r.get(disp_col) or code,
                    "cls": r.get(class_col), "cohort": ck, "cohort_label": label,
                    "side": side, "e": e, "extremity": abs(e),
                    "pct52": float(v52),
                    "pct3y": float(v3y) if v3y is not None and pd.notna(v3y) else np.nan,
                    "oi_all": float(r.oi_pctile_all) if pd.notna(r.get("oi_pctile_all")) else np.nan,
                    "read": read, "phrase": phrase,
                    "hit": float(ef.hit) if ef is not None else np.nan,
                    "n_eff": float(ef.n_eff) if ef is not None else np.nan,
                    "p": float(ef.p) if ef is not None else np.nan,
                    "tilt": float(ef.tilt) if ef is not None else np.nan,
                    "w": w, "score": score,
                }
        if best and best["extremity"] >= MIN_E:
            rows.append(best)
    if not rows: return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)

def edge_tag(row):
    if pd.isna(row.get("n_eff")): return "untested", "dim"
    if row["p"] < 0.05:  return f"{row['hit']:.0f}% hit &middot; p={row['p']:.3f}", "good"
    if row["tilt"] >= 0.3:  return f"{row['hit']:.0f}% hit &middot; n={row['n_eff']:.0f} eff", "warn"
    if row["tilt"] <= -0.3: return f"{row['hit']:.0f}% - inverted", "bad"
    return f"{row['hit']:.0f}% - no edge", "dim"
