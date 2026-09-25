"""Combined per-ETF price + short-interest + flow charts.

One spec per ETF ticker, in the same {nm, sub, t, panes} shape flowcharts.py
and charts.py already use, so the existing shell()/PZ.init() modal renders
it with no new client-side chart code. Built once and referenced from two
places: click a ticker row in the ETF SI table (etfsi.py) or a constituent
row under a basket's flow chart (flowcharts.py) and land on the SAME
per-ticker card. SI and flows are the same underlying read -- positioning
in the ETF wrapper -- just two different sources, so merging them into one
card is the point, not a shortcut to save a build step.

Panes are added only when that ticker actually has the data: a flow-only
ETF (no FINRA settlement coverage, e.g. most single-sector SPDRs are
covered but a handful of thinner thematic funds are not) gets price + flow
+ cumulative flow; an SI-only ticker (tracked on the curated 36 but not a
member of any flow basket) gets price + short interest + days-to-cover.
Most of the curated 36 get all four.

Grid: for a ticker with flow history, the flow series' own weekly
(Friday-ending) dates are authoritative -- price and SI/DTC are
forward-filled onto that grid, exactly like flowcharts.py already does for
basket-level price panes. For a ticker with SI but no flow basket, a
trailing weekly grid is built from its own price history instead, with SI
and DTC forward-filled onto it from their sparser settlement dates -- FINRA
settles roughly bi-monthly, so "hold flat until the next print" is the
correct read, the same way every other SI panel on this board treats it.
157 weeks (~3 years) per ticker, the same window every other chart on this
board uses, to keep 350+ tickers' worth of specs from bloating the page.
"""
import pandas as pd, numpy as np, os
import charts as CH

WEEKS = 157
PXCOL, MA50C, MA200C = "#c3c2b7", "#3987e5", "#e66767"


def _price_panes(sp, idx):
    if sp is None or not len(sp):
        return None
    r = sp.reindex(idx, method="ffill")
    if r.notna().sum() < 8:
        return None
    return {"k": "price", "fmt": "n", "c": PXCOL, "lab": "PRICE",
            "v": CH._sig(r.values),
            "ov": [{"v": CH._sig(sp.rolling(50).mean().reindex(idx, method="ffill").values),
                    "c": MA50C, "l": "50d"},
                   {"v": CH._sig(sp.rolling(200).mean().reindex(idx, method="ffill").values),
                    "c": MA200C, "l": "200d"}]}


def build():
    import etfsi as ES, flows as FL, prices as P

    o = ES.build()
    si_piv = o["si"] if o else None
    dtc_piv = o["dtc"] if o else None

    fd = FL.per_etf_weekly()

    tickers = set(ES.ALL)
    if fd is not None and len(fd):
        tickers |= set(fd.symbol.unique())
    if not tickers:
        return {}

    px = P.fetch_list(sorted(tickers))
    out = {}

    for tkr in sorted(tickers):
        has_si = si_piv is not None and tkr in si_piv.columns and si_piv[tkr].notna().sum() >= 2
        g = fd[fd.symbol == tkr].sort_values("date") if fd is not None and len(fd) else None
        has_flow = g is not None and len(g) >= 6

        if not has_si and not has_flow:
            continue

        if has_flow:
            idx = pd.DatetimeIndex(g.date.tail(WEEKS))
        else:
            sp0 = px[tkr].dropna() if tkr in px.columns else None
            if sp0 is None or len(sp0) < 60:
                continue
            idx = pd.date_range(end=sp0.index.max(), periods=WEEKS, freq="W-FRI")

        panes = []
        sp = px[tkr].dropna() if tkr in px.columns else None
        pp = _price_panes(sp, idx)
        if pp: panes.append(pp)

        if has_si:
            sv = si_piv[tkr].reindex(idx, method="ffill")
            panes.append({"k": "si", "fmt": "n", "c": "#9085e9", "lab": "SHORT INTEREST (shares)",
                          "v": CH._sig(sv.values)})
            if dtc_piv is not None and tkr in dtc_piv.columns:
                dv = dtc_piv[tkr].reindex(idx, method="ffill")
                if dv.notna().sum() >= 4:
                    panes.append({"k": "dtc", "fmt": "n", "c": "#5ec8d8", "lab": "DAYS TO COVER",
                                  "v": CH._arr(dv.values, 2)})

        if has_flow:
            gg = g.set_index("date").reindex(idx)
            flow_mn = (gg.flow / 1e6)
            cum_mn = (g.set_index("date").flow.cumsum() / 1e6).reindex(idx, method="ffill")
            panes.append({"k": "cum", "fmt": "n", "area": True,
                          "lab": "CUMULATIVE FLOW ($mn)", "v": CH._arr(cum_mn.values, 1)})
            panes.append({"k": "flow", "fmt": "n", "c": "#c3c2b7",
                          "lab": "WEEKLY FLOW ($mn)", "v": CH._arr(flow_mn.values, 1)})

        if len(panes) < 2:
            continue

        src_bits = []
        if has_si: src_bits.append("FINRA short interest")
        if has_flow: src_bits.append("etfdb flows")
        out[tkr] = {"nm": tkr, "sub": " &amp; ".join(src_bits),
                    "t": [d.strftime("%b %y") for d in idx], "panes": panes}

    return out
