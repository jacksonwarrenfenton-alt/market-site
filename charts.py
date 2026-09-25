"""COT panel charts -> compact client-side specs (see chartui.py)."""
import pandas as pd, numpy as np, html
from universe import PRICE_MAP, COT_UNIVERSE

W, PADL, PADR, PADT, PADB = 780, 62, 14, 18, 30
H_PRICE, H_PANE, H_COMP = 132, 104, 104
MUT, GRID = "#898781", "#2c2c2a"
PRICE, LS, SS, CM, OI, BAND = "#c3c2b7", "#3987e5", "#eb6834", "#1baf7a", "#eda100", "#383835"
WARM, COOL = "#e66767", "#3987e5"
MA50, MA200 = "#3987e5", "#e66767"

BASE_LIM, LIM_MIN, LIM_MAX = 5.0, 3.0, 12.0
LIM_EXPO = 0.5

def band_ratio(s, win=52, minp=40, smooth=13):
    """r_t = IQR(trailing 52w) / IQR(that series' all history to t), smoothed."""
    x = pd.Series(s).astype(float).reset_index(drop=True)
    r = x.rolling(win, min_periods=minp)
    e = x.expanding(min_periods=minp)
    iqr_w = r.quantile(.75) - r.quantile(.25)
    iqr_a = e.quantile(.75) - e.quantile(.25)
    ratio = (iqr_w / iqr_a.where(iqr_a > 0)).values
    return pd.Series(ratio).rolling(smooth, min_periods=1).mean().values

def adaptive_band(s, ratio=None, ref=None, win=52, minp=40,
                  base=BASE_LIM, lo=LIM_MIN, hi=LIM_MAX):
    """Per-series significance threshold, calibrated against the board."""
    v = np.asarray(pd.Series(s).astype(float).values, float)
    n = len(v)
    if ratio is None: ratio = band_ratio(s, win, minp)
    r = np.asarray(ratio, float)
    if ref is None: ref = np.full(n, np.nan)
    ref = np.asarray(ref, float)
    qlo = np.full(n, np.nan); qhi = np.full(n, np.nan)
    med = np.full(n, np.nan); lim = np.full(n, np.nan)
    for i in range(n):
        w = v[max(0, i-win+1): i+1]; w = w[np.isfinite(w)]
        if len(w) < minp: continue
        rr = ref[i] if i < len(ref) else np.nan
        rel = (r[i] / rr) if (np.isfinite(r[i]) and np.isfinite(rr) and rr > 0) else 1.0
        L = float(min(max(base * (rel ** LIM_EXPO), lo), hi))
        lim[i] = L
        qlo[i] = np.percentile(w, L)
        qhi[i] = np.percentile(w, 100 - L)
        med[i] = np.median(w)
    return qlo, qhi, med, lim

def board_reference(d, codes, keys=("ls_pct","ss_pct","comm_pct","open_interest_all")):
    """Cross-contract median of r_t, so each contract's threshold is set against
    what the rest of the board is doing that week rather than against itself."""
    grp = {c: g.sort_values("date") for c, g in
           d[d.cftc_contract_market_code.isin(codes)].groupby("cftc_contract_market_code")}
    ref, cache = {}, {}
    for k in keys:
        cols = {}
        for code, g in grp.items():
            if len(g) < 60 or k not in g: continue
            r = band_ratio(g[k])
            cache[(code, k)] = r
            cols[code] = pd.Series(r, index=pd.DatetimeIndex(g.date))
        if not cols: continue
        m = pd.DataFrame(cols).median(axis=1, skipna=True)
        ref[k] = m.groupby(level=0).median().sort_index()
    return ref, cache

PANES = [("price","Price"), ("ls","Large spec"), ("ss","Small spec"),
         ("cm","Commercial"), ("oi","Open interest"), ("comp","Composition")]

def _arr(s, nd=5):
    out = []
    for x in pd.Series(s).astype(float).values:
        out.append(None if not np.isfinite(x) else round(float(x), nd))
    return out

def _sig(s, digits=6):
    """Significant figures, not decimal places -- _arr(px,4) wrote 65123.4567
    on bitcoin, which is four digits of pure noise per point (PATCH B2)."""
    out = []
    for x in pd.Series(s).astype(float).values:
        if not np.isfinite(x): out.append(None); continue
        if x == 0: out.append(0); continue
        nd = digits - 1 - int(np.floor(np.log10(abs(x))))
        out.append(round(float(x), max(nd, 0)) if nd > 0 else float(round(x, nd)))
    return out

def _limstats(s):
    x = pd.Series(s).astype(float).dropna()
    if x.empty: return None, None, None
    return round(float(x.iloc[-1]), 1), round(float(x.min()), 1), round(float(x.max()), 1)

def build_specs(d, cur, threshold=BASE_LIM, weeks=157):
    """{code: spec dict} for the client-side renderer (see chartui.py)."""
    import prices as P
    px = P.fetch()
    spy = P.spy()
    sig = cur
    REF, RCACHE = board_reference(
        d, [c for c in cur.cftc_contract_market_code.unique() if c in COT_UNIVERSE])
    out = {}
    for _, r in sig.iterrows():
        code = r.cftc_contract_market_code
        g = d[d.cftc_contract_market_code == code].sort_values("date").copy()
        if len(g) < 60: continue
        gd = pd.DatetimeIndex(g.date)
        def _ref(key):
            rr = REF.get(key)
            return None if rr is None else rr.reindex(gd, method="ffill").values
        for k in ("ls", "ss", "comm"):
            (g[f"{k}_qlo"], g[f"{k}_qhi"], g[f"{k}_med"], g[f"{k}_lim"]) = adaptive_band(
                g[f"{k}_pct"], ratio=RCACHE.get((code, f"{k}_pct")),
                ref=_ref(f"{k}_pct"), base=threshold)
        (g["oi_qlo"], g["oi_qhi"], g["oi_med"], g["oi_lim"]) = adaptive_band(
            g.open_interest_all, ratio=RCACHE.get((code, "open_interest_all")),
            ref=_ref("open_interest_all"), base=threshold)

        tk = (PRICE_MAP.get(code) or (None, None))[0]
        if tk and tk in px.columns:
            # Yahoo's `close` is the raw traded price. adjclose is deliberately
            # NOT used -- a total-return line hides the actual drawdown in
            # income-heavy tickers like TLT and XLP.
            sp = px[tk].dropna()
            g["px"]    = sp.reindex(g.date, method="ffill").values
            g["ma50"]  = sp.rolling(50).mean().reindex(g.date, method="ffill").values
            g["ma200"] = sp.rolling(200).mean().reindex(g.date, method="ffill").values
        else:
            g["px"] = g["ma50"] = g["ma200"] = np.nan

        h = g.tail(weeks).reset_index(drop=True)
        if len(h) < 20: continue
        panes = []
        if h.px.notna().sum() > 5:
            proxy = (PRICE_MAP.get(code) or (None, False))[1]
            # PATCH B2: no "mk" blob. The price-pane arrows are DERIVED in the
            # browser from the indicator panes' own lo/hi arrays, so there is one
            # definition of "significant" instead of two that can drift apart.
            panes.append({"k":"price", "fmt":"n", "c":PRICE,
                "lab":"PRICE - " + (f"{tk} proxy" if proxy else (tk or "")),
                "v":_sig(h.px),
                "ov":[{"v":_sig(h.ma50), "c":MA50, "l":"50d"},
                      {"v":_sig(h.ma200), "c":MA200, "l":"200d"}]})
        for key, pk, col, lbl in (("ls","ls",LS,"LARGE SPEC - net % of OI"),
                                  ("ss","ss",SS,"SMALL SPEC - net % of OI"),
                                  ("comm","cm",CM,"COMMERCIAL - net % of OI")):
            ln, lmin, lmax = _limstats(h[f"{key}_lim"])
            # "md" dropped: paneMedian() rebuilds the centre line client-side.
            panes.append({"k":pk, "fmt":"p", "c":col, "lab":lbl,
                "v":_arr(h[f"{key}_pct"],2), "lo":_arr(h[f"{key}_qlo"],2),
                "hi":_arr(h[f"{key}_qhi"],2),
                "limNow":ln, "limMin":lmin, "limMax":lmax})
        ln, lmin, lmax = _limstats(h.oi_lim)
        panes.append({"k":"oi", "fmt":"n", "c":OI, "lab":"OPEN INTEREST - contracts",
            "v":_arr(h.open_interest_all,0), "lo":_arr(h.oi_qlo,0),
            "hi":_arr(h.oi_qhi,0),
            "limNow":ln, "limMin":lmin, "limMax":lmax})
        # composition ships TWO arrays; cm is rebuilt from the COT accounting
        # identity cm = -(ls+ss), which holds exactly.
        panes.append({"k":"comp", "fmt":"n",
            "lab":"COMPOSITION - net CONTRACTS, large + small spec stacked, "
                  "commercial is their exact mirror",
            "stack":{"ls":_arr(h.ls_net,0), "ss":_arr(h.ss_net,0)}})
        bits = [f"LgSpec {r.ls_pctile52:.0f}th", f"SmSpec {r.ss_pctile52:.0f}th",
                f"Comm {r.comm_pctile52:.0f}th"]
        if pd.notna(r.oi_pctile52): bits.append(f"OI {r.oi_pctile52:.0f}th")
        if pd.notna(r.get("ls_pctile")): bits.append(f"LgSpec 3yr {r.ls_pctile:.0f}th")
        spec = {"nm": str(r.get("disp") or code), "sub": "  -  ".join(bits),
                "t":[f"{x:%b %y}" for x in h.date], "panes":panes,
                "unit":"weeks", "bw":52}
        # bw is the window the browser uses when the band slider is moved off
        # AUTO; band=True lets a pane compute one even without a server band.
        for pn in panes:
            pn.setdefault("bw", 52)
            if "stack" not in pn: pn.setdefault("band", True)
        # SPY on the identical index, so the arrows land on the right weeks
        if spy is not None:
            spec["spy"] = _arr(spy.reindex(h.date, method="ffill").values, 2)
        out[code] = spec
    return out
