"""Cross-asset confluence: where COT, ETF flows and equity short interest agree."""
import pandas as pd, numpy as np, json, os, re

D = os.path.expanduser("~/pos")

THEMES = {
    "Gold & Silver":     (["088691","084691","076651","075651"], ["Precious Metals"],
                          r"gold|silver|precious|mining"),
    "Copper & Base":     (["085692","191693"], ["Industrial & Rare Metals"],
                          r"copper|steel|aluminum|metal fabricat|mining|\| Basic Materials"),
    "Crude & Products":  (["067651","06765T","111659","022651"], ["Energy"],
                          r"oil|gas prod|integrated|refin|oilfield|coal|\| Energy"),
    "Natural Gas":       (["023651"], ["Energy"], r"natural gas|pipeline"),
    "Semiconductors":    (["13874I"], ["Semiconductors"], r"semiconductor"),
    "Technology broad":  (["13874I"], ["Technology","Semiconductors"],
                          r"computer software|edp services|semiconductor|computer manuf"),
    "Financials":        (["13874C"], ["Financials"],
                          r"bank|savings institution|finance compan|insur|brokerag|invest|\| Finance"),
    "Health & Biotech":  (["13874E"], ["Health Care"],
                          r"biotech|pharmaceutic|medical|health|\| Health Care"),
    "Industrials":       (["13874F"], ["Industrials"],
                          r"aerospace|machinery|military|air freight|transportation|engineering|\| Industrials"),
    "Utilities":         (["13874J"], ["Utilities"], r"utilit|water supply|power|\| Utilities"),
    "Cons Discretionary":(["13874P"], ["Consumer Disc"],
                          r"retail|homebuild|restaurant|apparel|auto manufactur|leisure|hotel|\| Consumer Discretionary"),
    "Cons Staples":      (["138748"], ["Cons Staples"],
                          r"food|beverage|packaged goods|tobacco|household|\| Consumer Staples"),
    "Real Estate":       ([], ["Real Estate"], r"real estate|reit|\| Real Estate"),
    "Crypto":            (["133741","146021","176740"], ["Crypto"],
                          r"blank check|finance: consumer|investment manager|computer software"),
    # PATCH E1d: stays on the UNLEVERED core. The two index-leverage baskets are
    # deliberately NOT wired in -- summing a sign-flipped basket and a non-flipped
    # one into one flow number is incoherent. They earn their keep as their own
    # rows in the section-2 flow table.
    "US Equity broad":   (["13874+","20974+","239742","33874A"], ["Broad US Equity"], None),
    "Intl / EM":         (["244042","244041","240743"], ["Intl / EM"], None),
    "China":             ([], ["China"], None),
    "Rates / Duration":  (["042601","044601","043602","020601","020604","043607"],
                          ["Rates - Long","Rates - Short","Credit"], None),
    "Clean energy":      ([], ["Clean Energy"], r"solar|semiconductor|electrical products"),
    "Agriculture":       (["002602","005602","001602","001612","007601","026603"],
                          ["Agriculture"], r"agricultur|farming|fertilizer"),
    "Softs":             (["080732","033661","073732","083731"], ["Agriculture"], None),
}

def _validate():
    """Basket names here MUST exist in universe.ETF_BASKETS."""
    from universe import ETF_BASKETS
    dead = {t: [b for b in v[1] if b not in ETF_BASKETS] for t, v in THEMES.items()}
    dead = {t: b for t, b in dead.items() if b}
    if dead:
        raise ValueError(f"THEMES references baskets that do not exist: {dead}")

_validate()

EXT = 15.0
ZEXT = 1.0
SI_TILT = 12.0

def _si_sectors():
    f = f"{D}/universe_raw.json"
    if not os.path.exists(f): return {}
    return {x["symbol"]: f'{x.get("industry") or ""} | {x.get("sector") or ""}'
            for x in json.load(open(f))}

def build(cur, flows_latest, si):
    ind = _si_sectors()
    if si is not None and len(si):
        si = si.copy()
        si["industry"] = si.symbol.map(ind).fillna("")
    rows = []
    for theme, (codes, baskets, pat) in THEMES.items():
        r = {"theme": theme}
        c = cur[cur.cftc_contract_market_code.isin(codes)] if codes else cur.iloc[0:0]
        c = c.dropna(subset=["ls_pctile52"])
        if len(c):
            v = float(c.ls_pctile52.median())
            r["cot"] = v; r["cot_n"] = len(c)
            r["cot_sig"] = 1 if v >= 100-EXT else -1 if v <= EXT else 0
        else:
            r["cot"] = np.nan; r["cot_n"] = 0; r["cot_sig"] = 0

        if flows_latest is not None and len(flows_latest):
            b = flows_latest[flows_latest.basket.isin(baskets)]
            if len(b):
                tot_flow = float(b.flow_1m.sum()); tot_aum = float(b.aum.sum())
                pct = 100*tot_flow/tot_aum if tot_aum else np.nan
                zs = b.z_1m.dropna()
                z = float(zs.mean()) if len(zs) else np.nan
                r["flow_pct"] = pct; r["flow_z"] = z; r["flow_n"] = len(b)
                ref = z if not np.isnan(z) else pct*20
                r["flow_sig"] = 1 if ref >= ZEXT else -1 if ref <= -ZEXT else 0
            else:
                r.update(flow_pct=np.nan, flow_z=np.nan, flow_n=0, flow_sig=0)
        else:
            r.update(flow_pct=np.nan, flow_z=np.nan, flow_n=0, flow_sig=0)

        if si is not None and len(si) and pat:
            m = si.industry.str.contains(pat, case=False, na=False)
            g = si[m].dropna(subset=["chg_z"])
            if len(g) >= 8:
                cov = float((g.chg_z <= -1).mean() * 100)
                bld = float((g.chg_z >= 1).mean() * 100)
                tilt = cov - bld
                r["si_z"] = tilt; r["si_n"] = len(g)
                r["si_cov"], r["si_bld"] = cov, bld
                r["si_sig"] = 1 if tilt >= SI_TILT else -1 if tilt <= -SI_TILT else 0
            else:
                r.update(si_z=np.nan, si_n=len(g), si_sig=0, si_cov=np.nan, si_bld=np.nan)
        else:
            r.update(si_z=np.nan, si_n=0, si_sig=0, si_cov=np.nan, si_bld=np.nan)

        sigs = [r["cot_sig"], r["flow_sig"], r["si_sig"]]
        r["score"] = sum(sigs)
        r["agree"] = max(sum(1 for x in sigs if x > 0), sum(1 for x in sigs if x < 0))
        r["n_data"] = sum(1 for x in sigs if x != 0)
        r["verdict"] = ("CROWDED" if r["score"] >= 2 else
                        "WASHED OUT" if r["score"] <= -2 else
                        "mixed" if r["n_data"] >= 2 else "")
        rows.append(r)
    df = pd.DataFrame(rows)
    df["absscore"] = df.score.abs()
    return df.sort_values(["absscore","n_data"], ascending=False)
