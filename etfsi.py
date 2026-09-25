"""Short interest for the sector, broad-market and industry ETF complex.

Single names get the covering/building treatment on the Single stock page;
this is the same idea applied to the ETF wrappers themselves. Short interest
in an ETF is not usually a bet against the fund -- it is mostly hedging,
box trades and creation/redemption mechanics -- so a high DTC here reads as
"hedging demand / arb activity is elevated in this basket", not "shorts
expect this sector to fall". Framed that way it is still useful: a sector
ETF suddenly carrying unusually heavy short interest is a tell that
institutional hedging picked a side.

Same source as the rest of the board's SI work (FINRA bi-monthly bulk
settlements, sitables.py/siui.py), just re-sliced to a curated ETF list
grouped the way a trader actually thinks about the tape.
"""
import pandas as pd, numpy as np, json, os, html
import floatdata as FD

D = os.path.expanduser("~/pos")

GROUPS = [
    ("Broad market", ["SPY", "QQQ", "IWM", "DIA"]),
    ("Sector (SPDR)", ["XLB", "XLE", "XLF", "XLK", "XLV", "XLI", "XLU", "XLY", "XLP", "XLC", "XLRE"]),
    ("Industry / thematic", ["XOP", "XBI", "XME", "XHB", "XRT", "JETS", "KWEB", "ARKK", "SOXX", "IYT", "SMH", "KRE", "KBE", "IBB"]),
    ("Metals & international", ["GDX", "GDXJ", "EEM", "EFA", "FXI"]),
    ("Rates & credit", ["TLT", "HYG"]),
]
ALL = [t for _, g in GROUPS for t in g]
ELEV_Z = 1.0   # "elevated" flag threshold, level z


def _load():
    f = f"{D}/si_finra.parquet"
    if not os.path.exists(f): return None
    a = pd.read_parquet(f)
    a = a[a.symbolCode.isin(ALL)].copy()
    if not len(a): return None
    a["date"] = pd.to_datetime(a.settlementDate)
    a["si"] = pd.to_numeric(a.currentShortPositionQuantity, errors="coerce")
    a["dtc"] = pd.to_numeric(a.daysToCoverQuantity, errors="coerce")
    a.loc[(a.dtc >= 100) | (a.dtc <= 0), "dtc"] = np.nan
    return a


def build():
    a = _load()
    if a is None: return None
    si = a.pivot_table(index="date", columns="symbolCode", values="si").sort_index()
    dtc = a.pivot_table(index="date", columns="symbolCode", values="dtc").sort_index()
    if len(si) < 4: return None
    chg = si.pct_change() * 100
    z = (si - si.mean()) / si.std().replace(0, np.nan)
    last = si.index.max()
    rows = []
    for tkr in ALL:
        if tkr not in si.columns: continue
        rows.append({
            "symbol": tkr, "si": float(si[tkr].iloc[-1]) if pd.notna(si[tkr].iloc[-1]) else np.nan,
            "chg2w": float(chg[tkr].iloc[-1]) if tkr in chg.columns and pd.notna(chg[tkr].iloc[-1]) else np.nan,
            "level_z": float(z[tkr].iloc[-1]) if tkr in z.columns and pd.notna(z[tkr].iloc[-1]) else np.nan,
            "dtc": float(dtc[tkr].iloc[-1]) if tkr in dtc.columns and pd.notna(dtc[tkr].iloc[-1]) else np.nan,
        })
    d = pd.DataFrame(rows).set_index("symbol")
    return {"settle": str(last.date()), "d": d, "si": si, "dtc": dtc}


def _row(tkr, r, flt):
    def cell(v, fmt="{:+.1f}%"):
        if v is None or not np.isfinite(v): return '<td class="dim">&ndash;</td>'
        return f'<td>{fmt.format(v)}</td>'
    flag = ('<span class="dv dv-dn" title="short interest sits &ge;1&sigma; above its own history">ELEVATED</span>'
            if np.isfinite(r.level_z) and r.level_z >= ELEV_Z else "")
    si_s = f"{r.si/1e6:.1f}M" if np.isfinite(r.si) else "&ndash;"
    pct = FD.pct_of_float(r.si, tkr, flt)
    pf = f'<td>{pct:.2f}%</td>' if np.isfinite(pct) else '<td class="dim">&ndash;</td>'
    return (f'<tr><td class="nm" data-e="{tkr}" title="click for {tkr}\'s own price, short '
            f'interest and flow chart">{tkr}</td><td>{si_s}</td>' + pf
            + cell(r.chg2w) + cell(r.level_z, "{:+.2f}")
            + (f'<td>{r.dtc:.1f}</td>' if np.isfinite(r.dtc) else '<td class="dim">&ndash;</td>')
            + f'<td>{flag}</td></tr>')


def _group_table(label, tickers, d, flt):
    sub = d.reindex([t for t in tickers if t in d.index])
    if not len(sub):
        return ""
    sub = sub.sort_values("level_z", ascending=False)
    rows = "".join(_row(t, r, flt) for t, r in sub.iterrows())
    return (f'<div><h5>{label}</h5><table class="sig si2"><thead><tr>'
            '<th>Ticker</th><th>Shares short</th><th>% shares out</th><th>2w chg</th><th>Level z</th>'
            '<th>DTC</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div>')


def panel():
    o = build()
    if o is None: return ""
    d, si, dtc = o["d"], o["si"], o["dtc"]
    try:
        flt = FD.get(etfs=ALL)
    except Exception:
        flt = None

    tables = "".join(_group_table(lbl, tks, d, flt) for lbl, tks in GROUPS)
    n_elev = int((d.level_z >= ELEV_Z).sum())

    return (
        '<h2>Short interest &mdash; sector &amp; broad-market ETFs</h2>'
        f'<p class="grpnote">FINRA settlement <b>{o["settle"]}</b>, {len(d)} of '
        f'{len(ALL)} tracked ETFs covered. <b>Level z</b> is each fund&rsquo;s current '
        'shares-short standing against its own settlement history since Sept 2022 '
        '&mdash; the same standardisation used for single names. ETF short interest is '
        'mostly hedging and creation/redemption mechanics rather than a directional '
        'bet, so read <b>ELEVATED</b> as &ldquo;hedging/arb demand picked up in this '
        'basket,&rdquo; not as bearish conviction on the sector. <b>% shares out</b> '
        'is shares short against the fund&rsquo;s total shares outstanding &mdash; '
        'ETFs have no float concept since shares are created/redeemed daily against '
        'NAV, so shares outstanding is the right denominator here (from '
        'stockanalysis.com). '
        + (f'<b>{n_elev} of {len(d)}</b> ETFs are currently elevated (&ge;1&sigma; above their own history)'
           if n_elev else 'None are currently elevated &mdash; the complex sits inside its normal range')
        + '. <b>Click any ticker</b> for its own price chart alongside its own short-'
          'interest and flow history &mdash; same underlying positioning read, one card '
          'instead of a shared multi-line chart.</p>'
        + f'<div class="si2grid">{tables}</div>'
    )
