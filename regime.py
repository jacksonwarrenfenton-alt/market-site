"""Market regime -- which of jman's setups is actually live right now."""
import pandas as pd, numpy as np

PROBES = ["^VIX", "^VIX3M", "HYG", "LQD", "DX-Y.NYB", "TLT", "SPY", "QQQ", "IWM"]

def _tr(s):
    s = pd.Series(s).dropna()
    if len(s) < 210: return 0.0, {}
    ma50, ma200 = s.rolling(50).mean(), s.rolling(200).mean()
    px = float(s.iloc[-1])
    v = 0.0
    if px > ma50.iloc[-1]: v += 0.5
    else: v -= 0.5
    if px > ma200.iloc[-1]: v += 0.5
    else: v -= 0.5
    return v, {"px": px, "ma50": float(ma50.iloc[-1]), "ma200": float(ma200.iloc[-1]),
               "golden": bool(ma50.iloc[-1] > ma200.iloc[-1])}

def build(px, etf_px, basket_proxy):
    sig, detail = {}, {}
    try:
        import prices as P, os
        # ^VIX3M intermittently 404s at Yahoo; retry once before giving up, or the
        # VIX term-structure sub-vote silently never fires (seen 24 Aug).
        pr = P.fetch_list(PROBES, cache=os.path.expanduser("~/pos/probe_prices.parquet"))
        if "^VIX3M" not in pr.columns:
            pr2 = P.fetch_list(PROBES, cache=os.path.expanduser("~/pos/probe_prices.parquet"),
                               force=True)
            if "^VIX3M" in pr2.columns: pr = pr2
        etf_px = etf_px.join(pr[[c for c in pr.columns if c not in etf_px.columns]], how="outer")
        px = px.join(pr[[c for c in pr.columns if c not in px.columns]], how="outer")
    except Exception:
        pass

    if "SPY" in etf_px.columns:
        v, d = _tr(etf_px["SPY"]); sig["trend"] = v; detail["trend"] = d

    above50 = above200 = tot = 0
    for t in set(basket_proxy.values()):
        if t not in etf_px.columns: continue
        s = etf_px[t].dropna()
        if len(s) < 210: continue
        tot += 1
        above50 += int(s.iloc[-1] > s.rolling(50).mean().iloc[-1])
        above200 += int(s.iloc[-1] > s.rolling(200).mean().iloc[-1])
    if tot:
        p50, p200 = 100*above50/tot, 100*above200/tot
        detail["breadth"] = {"pct_above_50": p50, "pct_above_200": p200, "n": tot}
        sig["breadth"] = 1.0 if p50 >= 60 else (-1.0 if p50 <= 35 else 0.0)

    if "^VIX" in px.columns:
        v = px["^VIX"].dropna()
        lvl = float(v.iloc[-1]); chg = float(v.iloc[-1] - v.iloc[-11]) if len(v) > 11 else 0.0
        d = {"vix": lvl, "chg10d": chg}
        s = -1.0 if lvl >= 25 else (1.0 if lvl <= 16 else 0.0)
        if "^VIX3M" in px.columns:
            v3 = px["^VIX3M"].dropna()
            if len(v3):
                ts = float(v3.iloc[-1] / v.iloc[-1])
                d["vix3m_vix"] = ts
                if ts < 1.0: s = -1.0
                elif ts > 1.10 and lvl < 20: s = 1.0
        sig["vol"] = s; detail["vol"] = d

    if "HYG" in etf_px.columns and "LQD" in etf_px.columns:
        r = (etf_px["HYG"] / etf_px["LQD"]).dropna()
        if len(r) > 60:
            ma = r.rolling(50).mean()
            d = {"ratio": float(r.iloc[-1]), "vs_50d": float(r.iloc[-1]/ma.iloc[-1] - 1)*100}
            sig["credit"] = 1.0 if r.iloc[-1] > ma.iloc[-1] else -1.0
            detail["credit"] = d

    if "DX-Y.NYB" in px.columns:
        v, d = _tr(px["DX-Y.NYB"])
        sig["dollar"] = -v; detail["dollar"] = d

    if "TLT" in etf_px.columns:
        v, d = _tr(etf_px["TLT"]); sig["rates"] = v; detail["rates"] = d

    score = float(np.mean(list(sig.values()))) if sig else 0.0
    if score >= 0.35:   regime, setups = "BREAKOUT", [
        "High tight flags", "Earnings gappers - HVE, gap retest, gap AVWAP"]
    elif score <= -0.35: regime, setups = "DOWNTREND", [
        "Short into descending moving averages", "Short clear breakdowns"]
    else:                regime, setups = "CHOPPY", [
        "RS leaders on breakout pullbacks", "Tight ranges",
        "Undercuts into key MAs / VWAPs / support"]
    setups.append("Parabolic short - 4+ consecutive gap-ups, first intraday lower "
                  "high with loss of daily AVWAP (any regime)")
    return {"regime": regime, "score": score, "signals": sig,
            "detail": detail, "setups": setups}
