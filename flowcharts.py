"""Clickable ETF flow charts, Strategas format."""
import pandas as pd, numpy as np, html
from universe import ETF_BASKETS, BASKET_PROXY, INVERSE_ETFS
import flows as FL

W, PADL, PADR, PADT, PADB = 780, 66, 16, 20, 30
H_FLOW = 190
MUT, GRID = "#898781", "#2c2c2a"
BAND_HI, BAND_LO, ZERO = "#e66767", "#3987e5", "#898781"
POS, NEG = "#1baf7a", "#e66767"
CLIP_SIGMA = 5.0
MIN_CHART_OBS = 8
PXCOL, MA50C, MA200C = "#c3c2b7", "#3987e5", "#e66767"
K_TARGET, K_MIN, K_MAX = 5.0, 1.5, 3.0

def band_k(roll, mu, sd, target=K_TARGET, lo=K_MIN, hi=K_MAX):
    """Per-basket band multiple, calibrated on that basket's own history."""
    z = (np.asarray(roll, float) - np.asarray(mu, float)) / np.asarray(sd, float)
    z = np.abs(z[np.isfinite(z)])
    if len(z) < 30: return 2.0
    return float(min(max(np.percentile(z, 100 - target), lo), hi))

def _bn(v):
    return f"{v/1e9:+.1f}B" if abs(v) >= 1e9 else f"{v/1e6:+.0f}M"

def constituents(d, basket, asof):
    g = d[(d.basket == basket) & (d.date == asof)].dropna(subset=["flow"])
    if g.empty:
        return '<p class="none">No constituent flows for this week.</p>'
    g = g.assign(pct=np.where(g.aum > 0, 100*g.flow/g.aum, np.nan)).sort_values("flow", ascending=False)
    inv = set(INVERSE_ETFS)
    noflip = basket == "Index Short (inverse)"
    mx = max(float(g.flow.abs().max()), 1.0)
    rows = []
    for _, r in g.iterrows():
        w = 100*abs(r.flow)/mx
        col = POS if r.flow >= 0 else NEG
        side = "left:50%" if r.flow >= 0 else "right:50%"
        pct = "&mdash;" if not np.isfinite(r.pct) else f"{r.pct:+.3f}%"
        tag = ""
        if r.symbol in inv:
            tag = ('<span class="inv" title="inverse fund - sign NOT flipped in this basket">INV</span>'
                   if noflip else
                   '<span class="inv" title="inverse fund - flow sign flipped">INV</span>')
        rows.append(
            f'<tr><td class="nm" data-e="{html.escape(r.symbol)}" '
            f'title="click for {html.escape(r.symbol)}\'s own price and flow chart">'
            f'{html.escape(r.symbol)}{tag}</td>'
            f'<td>{_bn(r.flow)}</td><td>{pct}</td>'
            f'<td class="dim">{r.aum/1e9:.1f}B</td>'
            f'<td class="bar"><span style="{side};width:{w*0.5:.1f}%;background:{col}"></span></td></tr>')
    return ('<table class="mini"><thead><tr><th>ETF</th><th>Flow</th>'
            '<th>% of AUM</th><th>AUM</th><th>flow</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")

def build_specs(win=4):
    """{basket: (spec, constituents_html)} for the client-side renderer."""
    import charts as CH
    d = FL.per_etf_weekly()
    if d is None or d.empty: return {}
    bf = FL.basket_weekly()
    asof = d.date.max()
    try:
        import prices as P
        epx = P.fetch_list(sorted(set(BASKET_PROXY.values())))
    except Exception:
        epx = pd.DataFrame()
    out = {}
    for b in ETF_BASKETS:
        hist = bf[bf.basket == b].dropna(subset=["flow"]).reset_index(drop=True)
        if len(hist) < MIN_CHART_OBS: continue
        idx = pd.DatetimeIndex(hist.date)
        roll = hist.flow.rolling(win, min_periods=1).sum()
        mu = roll.expanding(min_periods=2).mean()
        sd = roll.expanding(min_periods=2).std().fillna(0)
        k = band_k(roll, mu, sd.replace(0, np.nan))
        up, dn = (mu + k*sd).ffill().bfill(), (mu - k*sd).ffill().bfill()
        cum = hist.flow.cumsum()

        panes = []
        tkr = BASKET_PROXY.get(b)
        if tkr and tkr in getattr(epx, "columns", []):
            sp = epx[tkr].dropna()
            # PATCH B3: no "mk" blob -- arrows derive client-side from the flow
            # pane's own band. PATCH B2's _sig for the price line and both MAs.
            panes.append({"k":"price", "fmt":"n", "c":PXCOL, "lab":f"PRICE - {tkr}",
                "v":CH._sig(sp.reindex(idx, method="ffill").values),
                "ov":[{"v":CH._sig(sp.rolling(50).mean().reindex(idx, method="ffill").values),
                       "c":MA50C, "l":"50d"},
                      {"v":CH._sig(sp.rolling(200).mean().reindex(idx, method="ffill").values),
                       "c":MA200C, "l":"200d"}]})
        panes.append({"k":"cum", "fmt":"n", "area":True,
            "lab":"CUMULATIVE FLOW - every ETF in the group, summed",
            "v":CH._arr(cum, 0)})
        # "md" dropped: paneMedian() rebuilds the centre from the symmetric band.
        panes.append({"k":"flow", "fmt":"n", "c":"#c3c2b7", "bk":round(float(k),2),
            "lab":f"ROLLING {win}-WEEK FLOW SUM",
            "v":CH._arr(roll,0), "lo":CH._arr(dn,0), "hi":CH._arr(up,0)})
        # PATCH E1c: state the sign convention or the chart is unreadable.
        _inv = b in ("Index Short (inverse)", "Sector Short (inverse)")
        conv = (" &middot; NET LONG-EQUIVALENT: inverse flows are sign-flipped, so a deep "
                "negative extreme = crowd maximally short. Price pane is the thing being "
                "shorted, not the decaying inverse fund."
                if _inv else
                " &middot; money in = leverage demand rising"
                if b in ("Index Long (leveraged)", "Sector Long (leveraged)") else "")
        for pn in panes:
            pn.setdefault("bw", 52)
            pn.setdefault("band", True)
        spec = {"nm": b,
                "sub": f"ETF dollar flows &middot; etfdb history from {hist.date.iloc[0]:%b %Y}{conv}",
                "t":[f"{x:%b %y}" for x in hist.date], "panes":panes,
                "unit":"weeks", "bw":52}
        try:
            import prices as _P
            _spy = _P.spy()
            if _spy is not None:
                spec["spy"] = CH._arr(_spy.reindex(idx, method="ffill").values, 2)
        except Exception:
            pass
        out[b] = (spec, constituents(d, b, asof))
    return out
