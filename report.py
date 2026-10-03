"""Weekly positioning report -> self-contained HTML dashboard."""
import pandas as pd, numpy as np, os, html, json, datetime as dt
from universe import COT_UNIVERSE, CLASS_ORDER, PRICE_MAP
import flows as F, prices as P, cot as C, charts as CH, stats as ST, themes as TH, flowcharts as FC
import chartui
import signals as SG, efficacy as EFF
import audit as AUD
import floatdata as FD

D = os.path.expanduser("~/pos")
OUT = f"{D}/positioning_report.html"
EXTREME  = 15.0
SHORT_T  = 10.0
BOTH_T   = 20.0
OI_T     = 20.0
THIN_OI  = 20.0
EXCLUDE  = ("Ags", "Softs")

COOL, WARM, MID = (0x39,0x87,0xe5), (0xe6,0x67,0x67), (0x38,0x38,0x35)


def _ord(v):
    """12 -> '12th', 2 -> '2nd', 93 -> '93rd' (percentiles in prose and cells)."""
    n = int(round(float(v)))
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"

def _na(v): return v is None or (isinstance(v, float) and np.isnan(v))

def heat(pc):
    if _na(pc): return "transparent", "#898781"
    t = max(-1.0, min(1.0, (float(pc)-50.0)/50.0)); a = abs(t)
    pole = WARM if t > 0 else COOL
    rgb = tuple(int(MID[i] + (pole[i]-MID[i])*a) for i in range(3))
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})", ("#ffffff" if a > 0.45 else "#c3c2b7")

def isx(pc):
    return (not _na(pc)) and (float(pc) <= EXTREME or float(pc) >= 100-EXTREME)

def zc(pc, dim=False):
    bg, ink = heat(pc)
    txt = "&ndash;" if _na(pc) else f"{pc:.0f}"
    cls = "z" + (" x" if isx(pc) else "") + (" sm" if dim else "")
    return f'<td class="{cls}" style="background:{bg};color:{ink}">{txt}</td>'

def heatz(z, cap=3.0):
    if _na(z): return "transparent", "#898781"
    t = max(-1.0, min(1.0, float(z)/cap)); a = abs(t)
    pole = WARM if t > 0 else COOL
    rgb = tuple(int(MID[i] + (pole[i]-MID[i])*a) for i in range(3))
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})", ("#ffffff" if a > 0.45 else "#c3c2b7")

def isxz(z, lim=2.0): return (not _na(z)) and abs(float(z)) >= lim

def zcz(z):
    bg, ink = heatz(z)
    return (f'<td class="{"z x" if isxz(z) else "z"}" style="background:{bg};'
            f'color:{ink}">{"&ndash;" if _na(z) else f"{z:.2f}"}</td>')

def num(v, fmt="%.1f", cls=""):
    return f'<td class="{cls}">{"&ndash;" if _na(v) else fmt % v}</td>'

def esc(s): return html.escape(str(s))

def rg(r):
    t = r.get("regime")
    if not t or (isinstance(t, float) and pd.isna(t)): return '<td class="dim">&ndash;</td>'
    return (f'<td class="rg {r.get("regime_tone") or "neut"}">'
            f'{esc(t)}{"*" if r.get("px_proxy") else ""}</td>')

def thin(r):
    v = r.get("oi_pctile52")
    if _na(v) or v >= THIN_OI: return ""
    return (f' <span class="thin" title="Open interest in the {_ord(v)} percentile of '
            f'its own 52 weeks - the reading is real, the market is just small">THIN</span>')

def cname(r, ctx=""):
    cx = f' data-ctx="{ctx}"' if ctx else ""
    return (f'<td class="nm k" data-c="{esc(r.cftc_contract_market_code)}"{cx}>'
            f'{esc(r.disp)}{thin(r)}</td>')

def qual(v52, v3y, side):
    if _na(v52): return False
    if side < 0:
        return v52 <= SHORT_T or (v52 <= BOTH_T and (not _na(v3y)) and v3y <= BOTH_T)
    return v52 >= 100-SHORT_T or (v52 >= 100-BOTH_T and (not _na(v3y)) and v3y >= 100-BOTH_T)

def hotrow(*vs):
    return ' class="hot"' if any(isx(v) for v in vs) else ""

def load():
    d = pd.read_parquet(f"{D}/cot_built.parquet")
    last = d.date.max()
    cur = d[d.date == last].copy()
    cur["disp"] = cur.cftc_contract_market_code.map(lambda c: COT_UNIVERSE.get(c,(None,None))[0])
    cur["cls"]  = cur.cftc_contract_market_code.map(lambda c: COT_UNIVERSE.get(c,(None,None))[1])
    return last, P.attach(cur, last), d

FULL_HDR = """
<thead>
<tr class="grp2">
  <th rowspan="2">Contract</th>
  <th colspan="2">Large spec</th><th colspan="2">Small spec</th>
  <th colspan="2">Commercial</th>
  <th rowspan="2">OI %ile<br><span style="font-weight:400;text-transform:none">all-time</span></th>
  <th rowspan="2">Price/OI 13w</th>
</tr>
<tr><th>52w</th><th>3yr</th><th>52w</th><th>3yr</th><th>52w</th><th>3yr</th></tr>
</thead>"""

def fullrow(r):
    return ("<tr" + hotrow(r.ls_pctile52, r.ss_pctile52, r.comm_pctile52, r.ls_chg_pctile52) + ">"
            + cname(r)
            + zc(r.ls_pctile52)   + zc(r.ls_pctile, True)
            + zc(r.ss_pctile52)   + zc(r.ss_pctile, True)
            + zc(r.comm_pctile52) + zc(r.comm_pctile, True)
            + zc(r.oi_pctile_all) + rg(r) + "</tr>")

def board(u, sort_key="ls_pctile52"):
    rows = []
    for cls in CLASS_ORDER:
        g = u[u.cls == cls]
        if g.empty: continue
        rows.append(f'<tr class="grp"><td colspan="9">{esc(cls)}</td></tr>')
        rows += [fullrow(r) for _, r in
                 g.sort_values(sort_key, ascending=False).iterrows()]
    return "\n".join(rows)

MINI_HDR = ('<th>Contract</th><th>Class</th><th>52w</th><th>3yr</th>'
            '<th>OI %ile</th><th>Price/OI</th>')

def minirow(r, k52, k3y, ctx=""):
    return ("<tr" + hotrow(r[k52]) + ">" + cname(r, ctx)
            + f'<td class="dim">{esc(r.cls)}</td>'
            + zc(r[k52]) + zc(r[k3y], True)
            + zc(r.oi_pctile_all) + rg(r) + "</tr>")

def pair(u, k52, k3y, lo_t, hi_t, ctx="", st=None, sig_lo="", sig_hi=""):
    g = u.dropna(subset=[k52])
    lo = g[[qual(r[k52], r[k3y], -1) for _, r in g.iterrows()]].sort_values(k52)
    hi = g[[qual(r[k52], r[k3y], +1) for _, r in g.iterrows()]].sort_values(k52, ascending=False)
    def blk(df, title, sigkey):
        foot = ""
        if st and sigkey:
            txt = ST.label(st, sigkey)
            if txt:
                sd = st.get(sigkey, {})
                cls = "sig ok" if (not sd.get("insufficient") and sd.get("p", 1) < 0.05) else "sig"
                foot = f'<p class="{cls}">Historical record of this signal: {txt}</p>'
        if df.empty:
            return (f'<div class="half"><h4>{esc(title)}</h4>'
                    f'<p class="none">Nothing qualifies this week.</p>{foot}</div>')
        return (f'<div class="half"><h4>{esc(title)} <span class="cnt">{len(df)}</span></h4>'
                f'<table class="mini"><thead><tr>{MINI_HDR}</tr></thead><tbody>'
                + "".join(minirow(r, k52, k3y, ctx) for _, r in df.iterrows())
                + f"</tbody></table>{foot}</div>")
    return blk(lo, lo_t, sig_lo) + blk(hi, hi_t, sig_hi)

def confluence(df):
    def cell(sig, txt, sub=""):
        cls = {1:"cf up", -1:"cf dn", 0:"cf nz"}[sig]
        arrow = "&#9650;" if sig > 0 else "&#9660;" if sig < 0 else "&middot;"
        sb = f'<span class="cfs">{esc(sub)}</span>' if sub else ""
        return f'<td class="{cls}">{arrow} {esc(txt)}{sb}</td>'
    rows = []
    for _, r in df.iterrows():
        if r.n_data == 0: continue
        # Plain U+2013, not "&ndash;": cell() escapes txt, which printed the entity literally.
        cot = ("–" if _na(r.cot) else _ord(r.cot))
        flw = ("–" if _na(r.flow_pct) else f"{r.flow_pct:+.2f}%")
        sii = ("–" if _na(r.si_z) else f"{r.si_z:+.0f}pp")
        vcls = ("v3" if r.agree >= 3 else "v2" if r.agree >= 2 else "vm")
        badge = (f'<span class="vb {vcls}">{esc(r.verdict)}</span>'
                 f'<span class="vn">{int(r.agree)}/3</span>') if r.verdict else \
                '<span class="vn">&mdash;</span>'
        rows.append("<tr" + (' class="hot"' if r.agree >= 2 and r.verdict != "mixed" else "") + ">"
            + f'<td class="nm" style="cursor:default">{esc(r.theme)}</td>'
            + cell(r.cot_sig,  cot, f" ({int(r.cot_n)})"  if r.cot_n else "")
            + cell(r.flow_sig, flw, f" ({int(r.flow_n)})" if r.flow_n else "")
            + cell(r.si_sig,   sii, f" ({int(r.si_n)})"   if r.si_n else "")
            + f'<td class="vd">{badge}</td></tr>')
    return ('<table class="mini cf"><thead><tr><th>Theme</th>'
            '<th>COT specs<br><span class="thh">52w %ile</span></th>'
            '<th>ETF flow<br><span class="thh">rolling 1m, % AUM</span></th>'
            '<th>Short interest<br><span class="thh">breadth tilt: %covering &minus; %building</span></th>'
            '<th>Confluence</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>")

def tiles(u):
    g = u.dropna(subset=["ls_pctile52"])
    picks = [("Crowded LONG", g.nlargest(1,"ls_pctile52"), "ls_pctile52"),
             ("Crowded SHORT", g.nsmallest(1,"ls_pctile52"), "ls_pctile52"),
             ("Crowded SM-SPEC LONG", g.dropna(subset=["ss_pctile52"]).nlargest(1,"ss_pctile52"), "ss_pctile52"),
             ("Crowded SM-SPEC SHORT", g.dropna(subset=["ss_pctile52"]).nsmallest(1,"ss_pctile52"), "ss_pctile52"),
             ("Thinnest OI", g.dropna(subset=["oi_pctile_all"]).nsmallest(1,"oi_pctile_all"), "oi_pctile_all")]
    out = []
    for lbl, df, key in picks:
        if df.empty: continue
        r = df.iloc[0]; v = r[key]; bg, ink = heat(v)
        k = int(round(v))
        sfx = "th" if 10 <= k % 100 <= 20 else {1:"st",2:"nd",3:"rd"}.get(k % 10, "th")
        out.append(f'<div class="tile"><div class="tl">{esc(lbl)}</div>'
                   f'<div class="tv k" data-c="{esc(r.cftc_contract_market_code)}">{esc(r.disp)}</div>'
                   f'<div class="tz" style="background:{bg};color:{ink}">{k}{sfx}</div></div>')
    return '<div class="tiles">' + "".join(out) + "</div>"

def si_history_html():
    """PATCH E2c -- market-wide short interest, chain-linked, WITH AXES.

    The first version was a bare sparkline: no y scale, no dates, no gridlines.
    A line with no axes cannot be read against its own history, which is the
    only thing this panel is for.
    """
    p = f"{D}/si_market.parquet"
    if not os.path.exists(p):
        return ('<p class="none">No market-wide short-interest history yet - it '
                'accumulates from the first run that persists si_hist.parquet.</p>')
    m = pd.read_parquet(p)
    if len(m) < 4:
        return (f'<p class="none">Only {len(m)} settlements of market-wide history '
                f'so far - too few to plot.</p>')
    W2, H2 = 780, 170
    PADL, PADR, PADT, PADB = 52, 14, 14, 26
    v = m.si_index.astype(float).values
    lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
    if hi <= lo: hi = lo + 1
    pad = (hi - lo) * 0.15; lo -= pad; hi += pad
    n = len(v)
    X = lambda i: PADL + (i/max(n-1,1))*(W2-PADL-PADR)
    Y = lambda x: (H2-PADB) - (x-lo)/(hi-lo)*(H2-PADB-PADT)

    def ticks(a, b, k=4):
        raw=(b-a)/k
        if raw <= 0: return [a]
        mag=10**np.floor(np.log10(raw))
        step=min([mm*mag for mm in (1,2,2.5,5,10)], key=lambda t: abs(t-raw))
        t0=np.ceil(a/step)*step
        return [t0+i*step for i in range(int((b-t0)/step)+1)]

    parts=[f'<svg viewBox="0 0 {W2} {H2}" width="100%" '
           f'style="display:block;font:10px ui-sans-serif,sans-serif">']
    # y gridlines + labels
    for t in ticks(lo, hi):
        y=Y(t)
        parts.append(f'<line x1="{PADL}" y1="{y:.1f}" x2="{W2-PADR}" y2="{y:.1f}" '
                     f'stroke="#2c2c2a"/>')
        parts.append(f'<text x="{PADL-6}" y="{y+3:.1f}" fill="#898781" '
                     f'text-anchor="end">{t:.0f}</text>')
    # base-100 reference
    if lo < 100 < hi:
        parts.append(f'<line x1="{PADL}" y1="{Y(100):.1f}" x2="{W2-PADR}" y2="{Y(100):.1f}" '
                     f'stroke="#898781" stroke-dasharray="4 3"/>')
        parts.append(f'<text x="{W2-PADR-2}" y="{Y(100)-4:.1f}" fill="#898781" '
                     f'font-size="9" text-anchor="end">base 100</text>')
    # axis lines
    parts.append(f'<line x1="{PADL}" y1="{PADT}" x2="{PADL}" y2="{H2-PADB}" stroke="#383835"/>')
    parts.append(f'<line x1="{PADL}" y1="{H2-PADB}" x2="{W2-PADR}" y2="{H2-PADB}" stroke="#383835"/>')
    # series
    d="M"+" L".join(f"{X(i):.1f},{Y(x):.1f}" for i,x in enumerate(v))
    parts.append(f'<path d="{d}" fill="none" stroke="#eda100" stroke-width="1.8"/>')
    for i,x in enumerate(v):
        parts.append(f'<circle cx="{X(i):.1f}" cy="{Y(x):.1f}" r="1.8" fill="#eda100" '
                     f'fill-opacity=".7"/>')
    parts.append(f'<circle cx="{X(n-1):.1f}" cy="{Y(v[-1]):.1f}" r="3.4" fill="#eda100" '
                 f'stroke="#141413" stroke-width="2"/>')
    parts.append(f'<text x="{X(n-1)-8:.1f}" y="{Y(v[-1])-9:.1f}" fill="#eda100" '
                 f'font-size="11" font-weight="700" text-anchor="end">{v[-1]:.1f}</text>')
    # x labels: settlement dates
    dts=list(m.date)
    for i in {0, n//3, 2*n//3, n-1}:
        anc = "start" if i==0 else ("end" if i==n-1 else "middle")
        parts.append(f'<text x="{X(i):.1f}" y="{H2-8}" fill="#898781" font-size="9" '
                     f'text-anchor="{anc}">{pd.Timestamp(dts[i]):%b %y}</text>')
    parts.append(f'<text x="{PADL-40}" y="{PADT+4}" fill="#898781" font-size="9">index</text>')
    parts.append("</svg>")
    spark="".join(parts)

    last, prev = m.iloc[-1], m.iloc[-2]
    tone = "up" if last.si_index > prev.si_index else "dn"
    zbit = f' &middot; {last.level_z:+.2f}&sigma;' if np.isfinite(last.level_z) else ''
    return ('<div class="mcbox">'
            f'<div class="mch"><span>Market-wide short interest &mdash; chain-linked index, '
            f'{int(last.n_symbols)} names</span>'
            f'<b class="{tone}">{last.si_index:.1f}</b>'
            f'<span class="dim">{last.chg:+.1f}% vs prior settlement{zbit}</span></div>'
            + spark +
            f'<p class="chf">Shares short across the screened universe, {m.date.min():%b %Y} '
            f'to {m.date.max():%b %Y} ({len(m)} settlements), as a <b>chain-linked index</b> '
            f'(base 100 at the first settlement; y-axis is index level, x-axis is settlement '
            f'date, one dot per settlement). Median days-to-cover {last.med_dtc:.1f}. '
            f'<b>Why an index and not a total:</b> the panel is not constant &mdash; Nasdaq '
            f'serves a rolling year per symbol, the screen changes between settlements, and '
            f'the fallback scraper labels its names only at the newest date. On this run that '
            f'moved coverage from 359 to {int(last.n_symbols)} names in one step and a raw sum '
            f'would have printed a <b>+57.9% surge that was pure composition</b>. Each step '
            f'here is the ratio of summed shares short across only the symbols present in '
            f'<b>both</b> that settlement and the one before ({int(last.n_overlap)} names this '
            f'step), so composition cancels and the line moves only on real position '
            f'changes.</p></div>')

def si_section():
    p = f"{D}/si_latest.parquet"
    if not os.path.exists(p): return None, None, ""
    r = pd.read_parquet(p)
    zz = r.dropna(subset=["chg_z"]).sort_values("chg_z")
    pp = r.dropna(subset=["pct_chg"]).sort_values("pct_chg")
    blocks = [zz.head(12), zz.tail(12).iloc[::-1], pp.head(12), pp.tail(12).iloc[::-1]]
    syms = set().union(*(set(b.symbol) for b in blocks))
    try:
        flt = FD.get(symbols=syms)
    except Exception:
        flt = None
    def blk(df, title, sub):
        def pf(x):
            pct = FD.pct_of_float(x.si, x.symbol, flt)
            return f'<td>{pct:.1f}%</td>' if np.isfinite(pct) else '<td class="dim">&ndash;</td>'
        rr = "".join("<tr" + (' class="hot"' if isxz(x.chg_z) else "") + ">"
            f'<td class="nm">{esc(x.symbol)}</td>'
            f'<td class="dim nmw">{esc(str(x["name"])[:32])}</td>'
            + num(x.si/1e6, "%.1fM", "dim") + pf(x) + num(x.pct_chg, "%+.1f%%")
            + zcz(x.chg_z) + zcz(x.level_z) + num(x.dtc, "%.1f")
            + num(x.atr_pct, "%.1f") + num(x.ret_1m, "%+.1f") + "</tr>"
            for _, x in df.iterrows())
        return (f'<div class="half"><h4>{title}</h4><p class="sub">{sub}</p>'
                '<table class="mini"><thead><tr><th>Sym</th><th>Name</th><th>SI</th>'
                '<th>% float</th><th>2w/2w</th><th>&Delta;Z</th><th>Lvl Z</th><th>DTC</th><th>ATR%</th>'
                '<th>1m %</th></tr></thead><tbody>' + rr + "</tbody></table></div>")
    # The z-ranked covers/builds are the Stocks tab's "covering and building
    # hardest" table (same file, same chg_z ranking, plus trend context), so
    # this section keeps only what exists nowhere else: the raw % cut across
    # every listing, unstandardised.
    body = (blk(blocks[2], "Biggest covers &mdash; raw %", "All listings") +
            blk(blocks[3], "Biggest builds &mdash; raw %", "All listings"))
    return r.settle.max(), len(r), body

def flow_section():
    l, note = F.basket_flows()
    if l is None: return f'<p class="warn">ETF flows not yet available &mdash; {esc(note)}.</p>'
    has_n = "nflow_1w" in l.columns
    def effcell(x):
        if not has_n or _na(x.get("eff_n")): return '<td class="dim">&ndash;</td>'
        e = float(x["eff_n"]); t1 = x.get("top1"); sym = x.get("top_sym") or ""
        cls = "eff bad" if e < 2 else ("eff warn" if e < 3.5 else "eff")
        tip = (f"{sym} is {t1:.0f}% of this basket's flow" if not _na(t1) else "")
        return f'<td class="{cls}" title="{esc(tip)}">{e:.1f}</td>'
    rr = "".join("<tr" + (' class="hot"' if (isxz(x.z_1w) or isxz(x.z_1m)) else "") + ">"
        f'<td class="nm k" data-f="{esc(x.basket)}">{esc(x.basket)}</td>'
        + num(x.flow_1w/1e9, "%+.3fB") + num(x.pct_1w, "%+.3f%%") + zcz(x.z_1w)
        + (num(x.nflow_1w, "%+.3f%%") + zcz(x.nz_1w) if has_n else "")
        + num(x.flow_1m/1e9, "%+.3fB") + num(x.pct_1m, "%+.3f%%") + zcz(x.z_1m)
        + (num(x.nflow_1m, "%+.3f%%") + zcz(x.nz_1m) if has_n else "")
        + effcell(x)
        + num(x.aum/1e9, "%.1fB", "dim") + num(x.n, "%.0f", "dim")
        + "</tr>" for _, x in l.iterrows())
    ncols = ('<th colspan="2">Normalised</th>' if has_n else "")
    nsub  = ('<th>Weighted %</th><th>Z</th>' if has_n else "")
    return ('<p class="grpnote">Dollar flows, summed across every ETF in the basket. History is harvested from <b>etfdb\'s daily fund-flow series</b> (back to Aug 2015) and aggregated to week-ending Friday. Windows are <b>rolling</b>, not periodic. '
            '<b>Index Long/Short and Sector Long/Short</b> are broken out of the cash baskets: a 3x fund\'s creations are a leverage-demand signal, not a sector-allocation one. Inverse flows are sign-flipped throughout, so a short basket reads as <b>net long-equivalent</b> positioning &mdash; a deep negative extreme is the crowd maximally short. '
            '<b>Normalised</b> is the fix for one fund speaking for a whole group: each member\'s flow as a share of <i>its own</i> AUM, averaged with square-root-of-AUM weights. If every member moves +1% of its own assets the normalised number is +1% regardless of size spread, whereas the dollar column would just print the biggest fund. '
            '<b>Eff&nbsp;n</b> is 1/HHI of each member\'s share of absolute flow over the trailing 12 weeks &mdash; how many funds the basket <i>effectively behaves like</i>. Red means under 2: the dollar column there is essentially one ticker (hover for which). Treat those baskets\' normalised column as the signal and the dollar column as context. '
            f'{note} <b>Click any basket name</b> for cumulative flow, the rolling-sum chart and the per-ETF breakdown.</p>'
            '<table class="mini"><thead>'
            f'<tr class="grp2"><th rowspan="2">Basket</th><th colspan="3">Rolling 1 week</th>{ncols}'
            f'<th colspan="3">Rolling 1 month</th>{ncols}'
            '<th rowspan="2" title="1/HHI of flow concentration, trailing 12w">Eff n</th>'
            '<th rowspan="2">AUM</th><th rowspan="2">#ETFs</th></tr>'
            f'<tr><th>Flow</th><th>% AUM</th><th>Z</th>{nsub}'
            f'<th>Flow</th><th>% AUM</th><th>Z</th>{nsub}</tr>'
            '</thead><tbody>' + rr + "</tbody></table>")

COT_FOOT = '<p class="chf">Price pane carries the <b>50-day</b> and <b>200-day</b> moving averages, unadjusted closes (never dividend-adjusted &mdash; a total-return line hides the real drawdown in income-heavy tickers). The <b>triangles on the price line</b> mark every week the cohort you opened sat outside its own band, so you can read the extreme against where price actually was. They come from <b>that one cohort, not all four</b> &mdash; use the <b>Signif. arrows</b> button to turn them off, or that cohort\'s own pane toggle. Shaded band = that series\' own rolling 52-week percentile range, and the percentile is <b>calibrated per series, not fixed</b>: each week it compares how wide this series\' trailing year is against its own full history, divides by the same ratio across the whole board, and scales the threshold by the square root of the result (base 5/95, clamped 3&ndash;12). A contract compressed relative to its peers gets a wider band &mdash; it must move further in its own terms to earn a dot. Every input is as-of that week. Dashed line = 52w median. Y-axes rescale to whatever window you zoom to.</p>'
FLOW_FOOT = '<p class="chf">Dollar flows only, from etfdb\'s daily fund-flow series summed to week-ending Friday. Price is the basket\'s lead ETF at unadjusted closes with 50/200-day moving averages; <b>triangles mark weeks the rolling flow broke its band</b>. The deviation band is <b>not a universal &plusmn;2&sigma;</b> &mdash; k is set per basket as the 95th percentile of that basket\'s own standardised residuals (clamped 1.5&ndash;3), so it marks a comparably rare week in a fat-tailed group like Crypto and a well-behaved one like Cons Staples. Y-axes rescale to the visible window and clip at 5 robust sigma; clipped points get a caret rather than being dropped.</p>'

SIG_CLASSES = ["Rates","FX","Metals","Energy","Ags","Softs","Equity","Sectors",
               "Crypto","Commodity Index"]

def _sc(pc, dim=False):
    bg, ink = heat(pc)
    txt = "&ndash;" if _na(pc) else f"{pc:.0f}"
    cls = "z" + (" x" if isx(pc) else "") + (" sm" if dim else "")
    k = -1 if _na(pc) else float(pc)
    return f'<td class="{cls}" data-sort="{k:.2f}" style="background:{bg};color:{ink}">{txt}</td>'

def signal_table(sig, oicorr):
    if sig is None or sig.empty:
        return '<p class="none">No contract clears the extremity floor this week.</p>'
    chips = ('<div class="chips"><button class="chip on" data-cls="all">All '
             f'<span>{len(sig)}</span></button>' + "".join(
        f'<button class="chip" data-cls="{esc(c)}">{esc(c)} '
        f'<span>{int((sig.cls==c).sum())}</span></button>'
        for c in SIG_CLASSES if (sig.cls == c).any()) +
        '</div>')
    rr = []
    for _, x in sig.iterrows():
        tag, tone = SG.edge_tag(x)
        rd = "up" if x["read"] == "BULLISH" else "dn"
        rr.append(
            f'<tr data-cls="{esc(x.cls)}">'
            f'<td class="nm k" data-c="{esc(x.code)}" data-ctx="{esc(x.cohort)}"'
            f' data-sort="{esc(str(x["name"]))}">{esc(str(x["name"]))}</td>'
            f'<td class="dim" data-sort="{esc(x.cls)}">{esc(x.cls)}</td>'
            f'<td data-sort="{esc(x.cohort_label)}">{esc(x.cohort_label)}'
            f'<span class="ph">{esc(x.phrase)}</span></td>'
            f'<td class="rd {rd}" data-sort="{esc(x["read"])}">{esc(x["read"])}</td>'
            + _sc(x.pct52) + _sc(x.pct3y, True) + _sc(x.oi_all, True)
            + f'<td class="edge {tone}" data-sort="{x.tilt if pd.notna(x.tilt) else -9:.4f}">'
              f'{tag}</td>'
            + f'<td class="sc" data-sort="{x.score:.3f}">{x.score:.0f}</td>'
            '</tr>')
    hdr = ("".join(f'<th data-s="{i}" class="{c}">{h}</th>' for i, (h, c) in enumerate([
        ("Contract",""),("Class",""),("Cohort",""),("Read",""),
        ("52w %ile","num"),("3yr %ile","num"),("OI all-time","num"),
        ("Historical edge",""),("Score","num")])))
    return (chips + '<table class="sig board"><thead><tr>' + hdr + '</tr></thead><tbody>'
            + "".join(rr) + '</tbody></table>')

CSS = """
:root{--s:#1a1a19;--p:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;--mut:#898781;
--grid:#2c2c2a;--base:#383835;--cool:#3987e5;--warn:#fab219;--good:#0ca30c;
--crit:#d03b3b;--vio:#9085e9}
*{box-sizing:border-box}
body{margin:0;background:var(--p);color:var(--ink);
font:13px/1.45 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1560px;margin:0 auto;padding:20px 22px 60px}
header{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;
border-bottom:2px solid var(--base);padding-bottom:10px;margin-bottom:16px}
h1{font-size:19px;margin:0;letter-spacing:-.01em;white-space:nowrap}
h2{font-size:14px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink2);
margin:30px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--grid)}
h4{font-size:11.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink2);margin:0 0 5px}
.meta{color:var(--mut);font-size:11.5px}
.meta b{color:var(--ink2)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:12px}
th{text-align:right;color:var(--mut);font-weight:500;font-size:10px;
text-transform:uppercase;letter-spacing:.05em;padding:4px 6px;
border-bottom:1px solid var(--base);white-space:nowrap}
tr.grp2 th{border-bottom:1px solid var(--grid)}
th:first-child,td.nm,td.nmw,td.rg{text-align:left}
td{padding:3px 6px;text-align:right;border-bottom:1px solid var(--grid);white-space:nowrap}
td.nm{color:var(--ink);font-weight:600;cursor:pointer}
td.nm:hover{color:var(--cool)}
td.nmw{color:var(--mut);max-width:200px;overflow:hidden;text-overflow:ellipsis;cursor:default}
td.dim{color:var(--mut)}
td.z{font-weight:700}
td.z.sm{font-weight:500;font-size:10.5px;opacity:.72}
td.z.x{outline:2px solid var(--ink);outline-offset:-2px}
tr.hot td{background-image:linear-gradient(rgba(255,255,255,.045),rgba(255,255,255,.045))}
tr.hot td.nm{box-shadow:inset 3px 0 0 var(--vio)}
td.rg{font-size:10px;letter-spacing:.03em;text-transform:uppercase;font-weight:600}
td.rg.good{color:var(--good)}td.rg.bad{color:var(--crit)}
td.rg.warn{color:var(--warn)}td.rg.neut{color:var(--mut)}
tr.grp td{background:#111;color:var(--ink2);font-weight:700;font-size:10px;
text-transform:uppercase;letter-spacing:.09em;padding:6px}
.split{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.half{min-width:0}
.sub{color:var(--mut);font-size:10.5px;margin:0 0 5px}
.warn{color:var(--warn);background:#221d0a;border-left:3px solid var(--warn);padding:9px 12px;font-size:12px}
.note{background:#12161d;border-left:3px solid var(--cool);padding:11px 14px;
font-size:12px;color:var(--ink2);line-height:1.55;margin:0 0 10px}
.note b{color:var(--ink)}.note a{color:var(--cool)}
.grpnote{color:var(--mut);font-size:11px;margin:1px 0 10px;line-height:1.5}
.grpnote a{color:var(--cool)}
.tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:0 0 14px}
.tile{background:var(--s);border:1px solid var(--base);border-radius:6px;padding:9px 11px}
.tl{font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--mut)}
.tv{font-size:14.5px;font-weight:700;margin:3px 0 5px;cursor:pointer}
.tv:hover{color:var(--cool)}
.tz{display:inline-block;font-size:13px;font-weight:800;padding:1px 8px;border-radius:4px}
.thin{display:inline-block;background:#3a2a08;color:var(--warn);font-size:8px;
font-weight:800;letter-spacing:.06em;padding:0 3px;border-radius:3px;
vertical-align:1px;margin-left:4px;border:1px solid #5c4410}
.legend{display:flex;gap:12px;align-items:center;flex-wrap:wrap;color:var(--mut);font-size:10.5px}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:4px}
#ov{position:fixed;inset:0;background:rgba(6,6,6,.88);display:none;z-index:99;
align-items:center;justify-content:center;padding:22px}
#ov.on{display:flex}
#ovb{background:var(--s);border:1px solid var(--base);border-radius:8px;
padding:16px 18px 12px;max-width:900px;width:100%;max-height:94vh;overflow:auto}
#ovx{float:right;cursor:pointer;color:var(--mut);font-size:20px;line-height:1;padding:0 4px}
#ovx:hover{color:#fff}
.chd{margin-bottom:9px}
.cht{font-size:15px;font-weight:700}
.chs{color:var(--mut);font-size:10.5px;margin-left:10px}
.tog{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tg{background:#232322;border:1px solid var(--base);color:var(--mut);font:600 10px
ui-sans-serif,sans-serif;text-transform:uppercase;letter-spacing:.06em;
padding:4px 9px;border-radius:4px;cursor:pointer}
.tg.on{background:#2f3a4d;border-color:var(--cool);color:#fff}
.tg[data-p="arrows"]{margin-left:auto;border-style:dashed}
.tg[data-p="arrows"].on{border-style:solid}
.pane{margin-bottom:2px}
.pane.off{display:none}
.chf{color:var(--mut);font-size:10px;line-height:1.5;margin:8px 0 0}
table.cf td{padding:5px 8px}
td.cf{text-align:right;font-variant-numeric:tabular-nums;font-weight:600;font-size:11.5px}
td.cf.up{color:#e66767}td.cf.dn{color:#3987e5}td.cf.nz{color:var(--mut);font-weight:400}
.cfs{color:var(--mut);font-weight:400;font-size:9.5px;margin-left:3px}
td.vd{text-align:right;white-space:nowrap}
.vb{display:inline-block;font-size:9.5px;font-weight:800;letter-spacing:.07em;
padding:2px 7px;border-radius:4px}
.vb.v3{background:#7a2020;color:#fff}
.vb.v2{background:#2f3a4d;color:#fff;border:1px solid var(--cool)}
.vb.vm{background:#232322;color:var(--mut)}
.vn{color:var(--mut);font-size:9.5px;margin-left:6px}
.thh{font-weight:400;text-transform:none;letter-spacing:0;color:#6e6d69;font-size:9px}
td.bar{width:120px;position:relative;padding:0}
td.bar span{position:absolute;top:50%;transform:translateY(-50%);height:9px;border-radius:2px;display:block}
td.bar::after{content:"";position:absolute;left:50%;top:3px;bottom:3px;width:1px;background:var(--base)}
.sig{color:var(--mut);font-size:10.5px;line-height:1.5;margin:6px 0 0;padding:6px 8px;background:#161615;border-left:2px solid var(--base);border-radius:3px}
.sig b{color:var(--ink2)}
.sig.ok{border-left-color:var(--good);color:var(--ink2)}
.none{color:var(--mut);font-size:11.5px;padding:10px 0;font-style:italic}
.cnt{display:inline-block;background:#2a2a28;color:var(--ink2);font-size:9.5px;font-weight:700;padding:1px 6px;border-radius:9px;margin-left:5px;vertical-align:1px}
.nochart{color:var(--mut);font-size:12px;padding:24px 0}
@media(max-width:1200px){.split{grid-template-columns:1fr}.tiles{grid-template-columns:repeat(2,1fr)}}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 10px}
.chip{background:#141413;border:1px solid var(--grid);color:var(--ink2);
font:11px ui-sans-serif,sans-serif;padding:4px 9px;border-radius:999px;cursor:pointer}
.chip span{color:var(--mut);margin-left:4px}
.chip.on{background:var(--cool);border-color:var(--cool);color:#fff}
.chip.on span{color:#dbe8fb}
table.sig th{cursor:pointer;user-select:none;white-space:nowrap}
table.sig th:hover{color:var(--ink)}
table.sig th.sorted::after{content:" \\2193";color:var(--cool)}
table.sig th.sorted.asc::after{content:" \\2191"}
table.sig td.rd{font-weight:700;font-size:10.5px;letter-spacing:.04em}
table.sig td.rd.up{color:#1baf7a}
table.sig td.rd.dn{color:#e66767}
table.sig td .ph{display:block;color:var(--mut);font-size:10px;font-weight:400}
table.sig td.edge{font-size:10.5px;text-align:left}
table.sig td.edge.good{color:#1baf7a}
table.sig td.edge.warn{color:var(--ink2)}
table.sig td.edge.bad{color:#e66767}
table.sig td.edge.dim{color:var(--mut)}
table.sig td.sc{font-weight:700;text-align:right}
table.sig td .xd{font-weight:400;font-size:9.5px;margin-left:5px;opacity:.72}
.sbex{border:1px solid var(--grid);border-radius:6px;padding:12px 14px 14px;margin:2px 0 20px}
.sbchips{display:flex;flex-direction:column;gap:6px;margin-bottom:11px}
.sbgrp{display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.sbglab{font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);
width:92px;flex:0 0 92px}
.sbchip{font:inherit;font-size:10.5px;color:var(--ink2);background:var(--s);
border:1px solid var(--grid);border-radius:99px;padding:3px 10px;cursor:pointer}
.sbchip:hover{border-color:var(--cool);color:var(--ink)}
.sbchip.on{background:var(--cool);border-color:var(--cool);color:#fff;font-weight:600}
.sbctl{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:2px 0 8px;
padding-top:10px;border-top:1px solid var(--grid);font-size:11px;color:var(--ink2)}
.sbctl label b{color:var(--warn);font-variant-numeric:tabular-nums}
.sbctl input[type=range]{width:230px;accent-color:var(--warn)}
.sbtoggle{font:inherit;font-size:10.5px;color:var(--ink2);background:var(--s);
border:1px solid var(--grid);border-radius:4px;padding:3px 9px;cursor:pointer}
.sbtoggle.on{border-color:var(--warn);color:var(--warn)}
.sbsvg{width:100%;height:auto;display:block}
.sbsvg .ax{fill:var(--mut);font-size:9px}
.sbsvg .ax.sp{fill:var(--ink2)}
.sblg{display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:10.5px;
color:var(--mut);margin-top:7px}
.sblg .k{width:11px;height:2.5px;border-radius:2px;display:inline-block;margin-left:9px}
.sblg .k:first-child{margin-left:0}
.sblg .k.cool{background:var(--cool)} .sblg .k.mut{background:var(--mut)}
.sblg .k.warn{background:var(--warn)} .sblg .k.good{background:var(--good)}
.sblg .k.crit{background:var(--crit)} .sblg .k.ink2{background:var(--ink2)}
.sblg .k.vio{background:var(--vio)}
.sblg .k.cool2{background:var(--cool);opacity:.45}

/* ---- AI desk ------------------------------------------------------- */
.aiwrap{display:flex;flex-direction:column;gap:16px}
.aihead{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;
flex-wrap:wrap;border-bottom:1px solid var(--grid);padding-bottom:12px}
.aih2{font-size:14px;text-transform:uppercase;letter-spacing:.09em;color:var(--ink2);
margin:0 0 5px;border:0;padding:0}
.aisub{max-width:62ch;margin:0}
.aitabs{display:flex;gap:4px;flex:0 0 auto}
.aitab{font:inherit;font-size:11px;color:var(--ink2);background:var(--s);
border:1px solid var(--grid);border-radius:5px;padding:6px 14px;cursor:pointer}
.aitab:hover{border-color:var(--cool)}
.aitab.on{background:var(--cool);border-color:var(--cool);color:#fff;font-weight:600}
.askbar{display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.askbar.col{flex-direction:column;align-items:stretch}
.askrow{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:9px}
.askbar input[type=text],.askbar textarea{font:inherit;background:var(--s);color:var(--ink);
border:1px solid var(--base);border-radius:5px;padding:8px 11px}
.askbar input[type=text]{width:290px}
.askbar textarea{width:100%;resize:vertical;line-height:1.5}
.askbar input:focus,.askbar textarea:focus{outline:2px solid var(--cool);outline-offset:-1px}
.btn{font:inherit;font-size:12px;font-weight:600;background:var(--cool);color:#fff;
border:1px solid var(--cool);border-radius:5px;padding:8px 16px;cursor:pointer}
.btn:hover{filter:brightness(1.12)}
.btn.ghost{background:transparent;color:var(--vio);border-color:var(--vio);font-weight:500}
.upl{font-size:11.5px;color:var(--ink2);border:1px dashed var(--base);border-radius:5px;
padding:7px 13px;cursor:pointer}
.upl:hover{border-color:var(--cool);color:var(--ink)}
.aiidx{font-size:10.5px}
.flags{list-style:none;margin:0 0 14px;padding:0;display:flex;flex-direction:column;gap:5px}
.fl{font-size:11.5px;color:var(--ink2);padding:6px 11px;border-radius:4px;
background:var(--s);border-left:3px solid var(--mut)}
.fl b{display:inline-block;min-width:52px;font-size:9.5px;text-transform:uppercase;
letter-spacing:.07em;color:var(--mut);font-weight:600}
.fl-cot{border-left-color:var(--warn)} .fl-si{border-left-color:var(--vio)}
.fl-flow{border-left-color:var(--cool)} .fl-overlap{border-left-color:var(--base)}
.fl-ok{border-left-color:var(--good)} .fl-none{border-left-color:var(--crit)}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(272px,1fr));gap:12px}
.dcard{border:1px solid var(--grid);border-radius:6px;padding:11px 13px 12px;background:var(--s)}
.dcard.wide{grid-column:1/-1}
.dcard h4{margin:0 0 8px}
.kv{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
font-size:11.5px;color:var(--mut);padding:3px 0;border-bottom:1px solid var(--grid)}
.kv:last-of-type{border-bottom:0}
.kv b{color:var(--ink);font-variant-numeric:tabular-nums;font-weight:600}
.kv b.up{color:var(--good)} .kv b.dn{color:var(--crit)} .kv b.dim{color:var(--mut)}
.kv b.warnx{color:var(--warn)}
.dnote{font-size:10.5px;color:var(--mut);line-height:1.55;margin:9px 0 0}
.legs2{display:flex;flex-wrap:wrap;gap:4px;margin-top:10px}
.legs2 .lg{display:flex;align-items:baseline;gap:6px;font-size:10px;padding:3px 8px;
border-radius:4px;border:1px solid var(--grid);background:var(--p);
font-variant-numeric:tabular-nums;font-weight:700;color:var(--ink2)}
.legs2 .lg i{font-style:normal;font-weight:500;color:var(--mut);text-transform:uppercase;
letter-spacing:.04em}
.legs2 .lg.hi{border-color:rgba(27,175,122,.55);color:#3fd39b}
.legs2 .lg.lo{border-color:rgba(230,103,103,.55);color:#f08a8a}
.legs2 .lg.nc{border-style:dashed;opacity:.45}
.aibox{border:1px solid var(--vio);border-left-width:3px;border-radius:6px;
padding:11px 14px;background:linear-gradient(rgba(144,133,233,.05),rgba(144,133,233,.05));
font-size:12px;line-height:1.65;color:var(--ink2)}
.aibox p{margin:0 0 6px}
.empty{font-size:12px;color:var(--mut);line-height:1.6;padding:18px 2px;max-width:70ch}
.deskout{display:flex;flex-direction:column;gap:0}
.chartout{min-height:80px}
.ctitle{margin:4px 0 8px}

/* ---- crowd concentration ---- */
.cwbox,.si2grid{border:1px solid var(--grid);border-radius:6px;padding:13px 15px 14px;
margin:2px 0 18px;background:linear-gradient(rgba(255,255,255,.02),rgba(255,255,255,.02))}
.cwhead{display:flex;justify-content:space-between;align-items:baseline;gap:16px;
font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:11px}
.cwhead b.crit{color:var(--crit)} .cwhead b.good{color:var(--good)}
.cwtiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
gap:16px;padding-bottom:13px;margin-bottom:13px;border-bottom:1px solid var(--grid)}
.cwtiles h6{font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;
color:var(--mut);font-weight:600;margin:0 0 4px}
.cwtiles .v{font-size:21px;font-weight:700;letter-spacing:-.01em}
.cwtiles .s{font-size:10.5px;color:var(--mut);margin-top:2px}
.cwgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}
.cwgrid h5,.si2grid h5{font-size:10px;text-transform:uppercase;letter-spacing:.07em;
color:var(--mut);font-weight:600;margin:0 0 6px;padding-bottom:4px;
border-bottom:1px solid var(--grid)}
table.cw td,table.cw th{font-size:11px;padding:2.5px 6px}
table.cw td.bar{width:38%}
table.cw td.bar i{display:block;height:8px;border-radius:2px;background:var(--vio);opacity:.75}
.si2grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:20px}
table.si2 td,table.si2 th{font-size:10.5px;padding:2.5px 5px}
table.si2 td.nmw{max-width:150px}
table.earn td,table.earn th{font-size:11.5px}
table.earn tr.dhdr td{background:var(--s);color:var(--ink2);font-size:9.5px;
text-transform:uppercase;letter-spacing:.08em;font-weight:600;padding:5px 6px}
.ec{display:inline-block;font-size:9.5px;padding:1.5px 7px;border-radius:99px;
border:1px solid var(--grid);color:var(--mut);margin-right:4px}
.ec-si{border-color:var(--vio);color:var(--vio)}
.ec-grp{border-color:var(--base)}
table.ov td:nth-child(3),table.ov th:nth-child(3){text-align:left}
table.ov td.sc{text-align:center}
.sg{display:inline-flex;align-items:baseline;gap:5px;font-size:10px;padding:2px 8px;
border-radius:4px;border:1px solid var(--grid);background:var(--s);margin:1px 4px 1px 0;
white-space:nowrap;color:var(--ink2)}
.sg i{font-style:normal;font-size:8.5px;font-weight:600;letter-spacing:.06em;
color:var(--mut)}
.sg-up{border-color:rgba(27,175,122,.5)} .sg-up i{color:#3fd39b}
.sg-dn{border-color:rgba(230,103,103,.5)} .sg-dn i{color:#f08a8a}
.sg-warn{border-color:rgba(250,178,25,.5)} .sg-warn i{color:var(--warn)}
.sg-vio{border-color:rgba(144,133,233,.5)} .sg-vio i{color:var(--vio)}
.sg-dim{opacity:.6}
table.heat td.nm2{color:var(--ink);font-weight:600;text-align:left}
table.heat td:last-child{text-align:left;color:var(--mut);font-size:10.5px}
table.heat td,table.heat th{font-size:11.5px}
/* ---- VIX term structure ---- */
.vixbox{border:1px solid var(--grid);border-radius:6px;padding:12px 15px 14px;margin:2px 0 18px}
.vixhead{display:flex;align-items:flex-start;gap:26px;flex-wrap:wrap;margin-bottom:8px}
.vixhead h6{font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);
font-weight:600;margin:0 0 3px}
.vixhead .v{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.vixhead .v.crit{color:var(--crit)} .vixhead .v.warn{color:var(--warn)}
.vixhead .v.good{color:var(--good)} .vixhead .v.dim{color:var(--mut)}
.vixsay{font-size:11px;color:var(--mut);max-width:52ch;line-height:1.55;align-self:center}
.vixsvg{max-width:600px}
/* ---- divergences ---- */
.dv{display:inline-block;font-size:10px;padding:2px 8px;border-radius:4px;
border:1px solid var(--grid);white-space:nowrap}
.dv-up{border-color:rgba(27,175,122,.55);color:#3fd39b}
.dv-dn{border-color:rgba(230,103,103,.55);color:#f08a8a}
table.dvg td,table.dvg th{font-size:11px}
table.dvg td.nm2{color:var(--ink);font-weight:600;text-align:left}
table.dvg td:nth-child(3){text-align:left;color:var(--mut)}
/* ---- econ calendar ---- */
table.econ td,table.econ th{font-size:11.5px}
table.econ td.nm2{text-align:left;color:var(--ink)}
table.econ tr.dhdr td{background:var(--s);color:var(--ink2);font-size:9.5px;
text-transform:uppercase;letter-spacing:.08em;font-weight:600;padding:5px 6px}
.cty{font-size:9.5px;font-weight:700;color:var(--ink2);letter-spacing:.04em}
.imp{font-size:9px;padding:1.5px 7px;border-radius:99px;border:1px solid var(--grid)}
.imp-hi{border-color:var(--crit);color:var(--crit)}
.imp-md{border-color:var(--warn);color:var(--warn)}
/* ---- earnings calendar ---- */
.calwrap{border:1px solid var(--grid);border-radius:6px;padding:12px 14px 14px;margin:2px 0 18px}
.calhead{display:flex;align-items:center;gap:12px;margin-bottom:10px}
.calhead b{font-size:13px;min-width:170px}
.calhead .btn{padding:4px 12px}
.calgrid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:5px}
.cdow{font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);
font-weight:600;padding:2px 4px 4px}
.cday{border:1px solid var(--grid);border-radius:5px;padding:5px 6px 7px;min-height:82px;
background:var(--s);display:flex;flex-direction:column;gap:3px;align-content:flex-start}
.cday.out{opacity:.32} .cday.now{border-color:var(--cool);box-shadow:inset 0 0 0 1px var(--cool)}
.cnum{font-size:10.5px;color:var(--mut);font-weight:600;display:flex;justify-content:space-between}
.cnum i{font-style:normal;color:var(--ink2);font-size:9.5px}
.etk{display:inline-block;font-size:9.5px;padding:1px 5px;border-radius:3px;
background:var(--p);border:1px solid var(--grid);color:var(--ink2);margin:0 3px 2px 0}
.etk.has{border-color:var(--vio);color:var(--vio);font-weight:600}
.emore{font-size:9px;color:var(--mut)}
.edot{display:inline-block;width:7px;height:7px;border-radius:2px;border:1px solid var(--vio);
vertical-align:middle}
/* ---- freshness footer ---- */
.fresh{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0 6px}
.fchip{font-size:10px;color:var(--ink2);background:var(--s);border:1px solid var(--grid);
border-radius:99px;padding:3px 10px}
.fchip i{font-style:normal;color:var(--mut);margin-left:5px}
.fchip.old{border-color:var(--warn)} .fchip.old i{color:var(--warn)}
/* ---- rotation map ---- */
.rrgwrap{margin:2px 0 16px}
.rrghead{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.rleg{display:flex;flex-wrap:wrap;gap:5px;margin:8px 0 10px}
.rsec{font:inherit;font-size:10px;color:var(--ink2);background:var(--s);
border:1px solid var(--grid);border-left:3px solid var(--c,var(--mut));
border-radius:4px;padding:3px 9px;cursor:pointer}
.rsec:hover{color:var(--ink);border-color:var(--cool)}
.rsec.on{background:var(--cool);border-color:var(--cool);color:#fff;font-weight:600}
.rrgsvg{width:100%;height:auto;display:block;background:var(--p);
border:1px solid var(--grid);border-radius:6px}
.rrgsvg .rlab{fill:var(--mut);font-size:7px}
.rrgsvg .rq{font-size:10px;font-weight:700;letter-spacing:.09em;opacity:.62}
/* ---- timeframe brush ----
   The drag bar and its date-range/mode-button row used to stack as two full-
   width lines -- at a glance that reads as two separate empty-looking boxes
   (the bar's own fill is a faint 18%-opacity tint, easy to miss against the
   page's near-black background) rather than one control. The date-range
   label now sits BESIDE the bar on the same row (.tfrow) -- in a narrow
   card (two-column grids like Trends/ETF SI) that's the only pairing that
   actually fits; the label text alone is short, where label+mode-buttons
   together were often wider than the whole card. Mode buttons + reset drop
   to their own row (.tfctl) underneath -- small pills, doesn't read as a
   second "box" the way a second full-width bar-looking element did. */
.tfz{margin:7px 0 4px}
.tfrow{display:flex;align-items:center;gap:8px}
.tfbar{position:relative;height:22px;background:#141413;border:1px solid var(--grid);
border-radius:4px;cursor:crosshair;overflow:hidden;touch-action:none;flex:1 1 auto;min-width:70px}
.tfwin{position:absolute;top:0;bottom:0;left:0;width:100%;
background:rgba(57,135,229,.18);border-left:1px solid var(--cool);
border-right:1px solid var(--cool);cursor:grab;min-width:10px}
.tfwin:active{cursor:grabbing}
.tfwin i{position:absolute;top:0;bottom:0;width:11px;cursor:ew-resize;display:block}
.tfwin i.hl{left:-5px} .tfwin i.hr{right:-5px}
.tfwin i:hover{background:rgba(57,135,229,.45)}
.tflab{font-size:10px;color:var(--mut);white-space:nowrap;flex:0 0 auto}
.tfctl{display:flex;align-items:center;gap:10px;font-size:10px;color:var(--mut);margin-top:4px;flex-wrap:wrap}
.tfrst{font:inherit;font-size:9.5px;color:var(--ink2);background:var(--s);
border:1px solid var(--grid);border-radius:3px;padding:2px 8px;cursor:pointer}
.tfrst:hover{border-color:var(--cool);color:var(--ink)}
.mcmode{display:inline-flex;gap:3px;margin-left:4px}
.mcm{font:inherit;font-size:9.5px;color:var(--mut);background:var(--s);
border:1px solid var(--grid);border-radius:3px;padding:2px 8px;cursor:pointer}
.mcm:hover{color:var(--ink);border-color:var(--cool)}
.mcm.on{background:var(--cool);border-color:var(--cool);color:#fff;font-weight:600}

/* ---- global & liquidity ---- */
.gtiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:4px 0 16px}
.gtile{border:1px solid var(--grid);border-radius:6px;padding:9px 11px;background:var(--s)}
.gtile h6{font-size:9.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);
font-weight:600;margin:0 0 3px}
.gtile .v{font-size:18px;font-weight:700;font-variant-numeric:tabular-nums}
.gtile .v.up{color:var(--good)} .gtile .v.dn{color:var(--crit)}
.gtile .s{font-size:10px;color:var(--mut);margin-top:2px}
.gblock{border:1px solid var(--grid);border-radius:6px;padding:11px 14px 12px;margin:0 0 16px}
.gblock h4{margin:0 0 3px}
.gblock .dnote{margin:0 0 8px;max-width:88ch}
.mcs{width:100%;height:auto;display:block}
.mcs .ax{fill:var(--mut);font-size:9px} .mcs .ax.sp{fill:var(--ink2)}
.mclg{display:flex;flex-wrap:wrap;align-items:center;gap:5px;font-size:10.5px;
color:var(--mut);margin-top:6px}
.mclg .k{width:11px;height:2.5px;border-radius:2px;display:inline-block;margin-left:9px}
.mclg .k:first-child{margin-left:0}
.glibox{border:1px solid var(--grid);border-radius:6px;padding:12px 15px 13px;margin:2px 0 12px}
.glihead{display:flex;gap:26px;flex-wrap:wrap;align-items:flex-start}
.glihead h6{font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);
font-weight:600;margin:0 0 3px}
.glihead .v{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.glihead .v.good{color:var(--good)} .glihead .v.crit{color:var(--crit)}
.glihead .v.dim{color:var(--ink2)}
.glihead .s{font-size:10.5px;color:var(--mut);margin-top:2px}
.glisay{font-size:11px;color:var(--mut);line-height:1.6;max-width:58ch;align-self:center}
.clist{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:4px 22px;
margin:0 0 14px}
.clrow{display:flex;align-items:center;gap:10px;font-size:11px}
.cln{color:var(--ink2);min-width:132px}
.clbar{position:relative;flex:1;height:8px;background:var(--s);border-radius:2px;
border:1px solid var(--grid)}
.clbar::after{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;
background:var(--base)}
.clbar i{position:absolute;top:0;bottom:0;border-radius:2px;opacity:.85}
.clv{font-variant-numeric:tabular-nums;font-weight:600;min-width:46px;text-align:right}






.liqn{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:4px 0 12px}
@media(max-width:820px){.liqn{grid-template-columns:1fr}}
.lqtile{border:1px solid var(--grid);border-radius:6px;padding:10px 12px 11px;background:var(--s)}
.lqtile h4{margin:0 0 5px}
.lqtile .v{font-size:21px;font-weight:700;letter-spacing:-.01em;font-variant-numeric:tabular-nums}
.lqtile .s{font-size:10.5px;color:var(--mut);line-height:1.5;margin-top:3px}
td.warnx{color:var(--warn);font-weight:700}
.cfx{border:1px solid var(--grid);border-radius:6px;padding:12px 14px 14px;margin:2px 0 16px;
background:linear-gradient(rgba(255,255,255,.022),rgba(255,255,255,.022))}
.cfx h4{margin:0 0 4px}
.cfx .grpnote{margin-bottom:9px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin:0 0 12px}
.chip{font-size:10px;letter-spacing:.03em;color:var(--ink2);background:var(--s);
border:1px solid var(--grid);border-radius:99px;padding:2px 8px;white-space:nowrap;cursor:help}
.chip i{font-style:normal;color:var(--mut);margin-left:5px;font-variant-numeric:tabular-nums}
.chip.thin{opacity:.5;border-style:dashed}
.cf3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
@media(max-width:900px){.cf3{grid-template-columns:1fr}}
.cf3 h5{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut);
font-weight:600;margin:0 0 5px;padding-bottom:4px;border-bottom:1px solid var(--grid)}
.cf3 ul{list-style:none;margin:0;padding:0;font-size:11.5px;line-height:1.65}
.cf3 li{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cf3 li b{font-variant-numeric:tabular-nums;color:var(--ink);margin-right:5px}
.crowdx .cf3 li{font-size:12px;line-height:1.75}
.crowdx .nm2{color:var(--ink)}
.cf3 li b.dn{color:var(--crit)} .cf3 li b.up{color:var(--good)}
.legs{display:flex;flex-wrap:wrap;gap:4px;margin:2px 0 9px}
.leg{display:flex;align-items:baseline;gap:6px;font-size:10px;padding:3px 8px;
border-radius:4px;border:1px solid var(--grid);background:var(--s);cursor:help}
.leg b{font-weight:500;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}
.leg i{font-style:normal;font-weight:700;font-variant-numeric:tabular-nums;color:var(--ink2)}
.leg.hi{border-color:rgba(27,175,122,.55)} .leg.hi i{color:#3fd39b}
.leg.lo{border-color:rgba(230,103,103,.55)} .leg.lo i{color:#f08a8a}
.leg.nc{border-style:dashed;opacity:.45}
td.eff{font-weight:700;color:var(--ink2)}
td.eff.warn{color:var(--warn)}
td.eff.bad{color:#e66767;background:rgba(230,103,103,.10)}
.warn2{color:var(--mut);display:block;margin-top:6px}
details.fold{margin-top:26px;border-top:1px solid var(--grid);padding-top:10px}
details.fold summary{cursor:pointer;color:var(--ink2);font-size:12px;
text-transform:uppercase;letter-spacing:.07em}
.inv{background:#3a2a2a;color:#e66767;font-size:8.5px;padding:1px 3px;
border-radius:2px;margin-left:4px;letter-spacing:.04em}
""" + chartui.BRUSH_CSS


def build():
    AUD.run(strict=True)   # fail loudly on stale cross-module references
    last, u, full = load()
    cu = u[u.disp.notna() & u.cftc_contract_market_code.isin(PRICE_MAP)].copy()
    n_ch_univ = len(cu)
    settle, n_si, si_body = si_section()
    raw = pd.read_parquet(f"{D}/cot_raw.parquet")
    ident, nrows = C.identity_check(raw), len(raw)
    specs = CH.build_specs(full, cu)
    panel = ST.build(full, P.fetch(), universe=set(cu.cftc_contract_market_code))
    st = ST.summarise(panel)
    _fl, _ = F.basket_flows()
    _si = (pd.read_parquet(f"{D}/si_latest.parquet")
           if os.path.exists(f"{D}/si_latest.parquet") else None)
    conf = TH.build(cu, _fl, _si)
    # This panel puts COT, flows and short interest on one axis, and a theme needs
    # only two of three to earn a verdict. If one leg is a month behind the
    # others, agreement is partly an artefact of the lag -- so say which leg is
    # stale rather than letting it quietly vote.
    conf_warn = ""
    try:
        import freshness as _FR
        _fa = _fl.date.max() if _fl is not None and len(_fl) else None
        _legs = [("COT", _FR.cot(last)),
                 ("short interest", _FR.finra(settle) if settle is not None else None),
                 ("ETF flows", _FR.flows(_fa) if _fa is not None else None)]
        _bad = [(n, f) for n, f in _legs if f is not None and f["stale"]]
        if _bad:
            _names = ", ".join(n for n, _ in _bad)
            _ages = "; ".join(f'{n} as of {f["asof"]:%d %b}' for n, f in _bad)
            conf_warn = (
                f'<p class="grpnote" style="border-left:2px solid var(--bad);'
                f'padding-left:8px"><b>One leg of this panel is stale: {_names}.</b> '
                f'{_ages}, against COT through {last:%d %b}. A theme can reach a '
                f'two-of-three verdict here only if a stale reading votes, so treat any '
                f'verdict resting on {" or ".join(n for n, _ in _bad)} as unconfirmed '
                f'until that feed catches up. The dated feed strip on the Market diary '
                f'tab shows how far behind each one is.</p>')
    except Exception as e:
        print("confluence freshness note failed:", e, flush=True)
    try:
        import crowded as CR
        crowded_panel = CR.html_panel(cu)
    except Exception as e:
        print("crowded panel failed:", e, flush=True)
        crowded_panel = ""
    def _try(fn, label):
        try: return fn()
        except Exception as e:
            print(f"{label} failed:", e, flush=True); return ""
    earn_panel  = _try(lambda: __import__("earnings").html_panel(), "earnings panel")
    crowd_panel = _try(lambda: __import__("liqn").crowd_panel(), "crowd panel")
    si_tables   = _try(lambda: __import__("sitables").html_panel(), "si tables")
    eff = EFF.build(full, P.fetch(), set(cu.cftc_contract_market_code), PRICE_MAP)
    eff.to_parquet(f"{D}/efficacy.parquet")
    n_eff_tested = len(eff)
    sig = SG.build(cu, eff)
    fspecs = FC.build_specs()
    fsp = {k: v[0] for k, v in fspecs.items()}
    fcon = {k: v[1] for k, v in fspecs.items()}
    n_hot = int(sum(isx(v) for v in cu.ls_pctile52) + sum(isx(v) for v in cu.ss_pctile52)
                + sum(isx(v) for v in cu.comm_pctile52))
    v = full.dropna(subset=["ls_z52","oi_pctile52"])
    oicorr = v.oi_pctile52.corr(v.ls_z52.abs())
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # PATCH B4: the weekly date grid was serialised once per chart (~100KB).
    TS = []
    def _intern_into(specs_map, table, idx):
        for sp in specs_map.values():
            key = "\x01".join(sp["t"])
            if key not in idx:
                idx[key] = len(table); table.append(sp["t"])
            sp["ti"] = idx[key]; sp.pop("t", None)
    _tidx = {}
    _intern_into(specs, TS, _tidx)
    _intern_into(fsp, TS, _tidx)

    h = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Positioning Rundown &mdash; {last.date()}</title><style>{CSS}</style></head><body>
<div class="wrap">
<header>
  <h1>Weekly Positioning Rundown</h1>
  <span class="meta">COT <b>{last.date()}</b> &middot; SI settle
  <b>{settle.date() if settle is not None else '-'}</b> ({n_si or 0} names) &middot;
  <b>{n_hot}</b> readings outside {EXTREME:.0f}/{100-EXTREME:.0f} &middot; {now}</span>
  <span class="legend" style="margin-left:auto">
    <span><span class="sw" style="background:{heat(95)[0]}"></span>top of range</span>
    <span><span class="sw" style="background:{heat(50)[0]}"></span>50th</span>
    <span><span class="sw" style="background:{heat(5)[0]}"></span>bottom of range</span>
    <span>52w bold &middot; 3yr faded &middot; {len(specs)} charts, click any name</span>
  </span>
</header>

{tiles(cu)}

<h2>0 &middot; Cross-asset confluence &mdash; where all three datasets agree</h2>
<p class="grpnote">The only place the three datasets are put on one axis.
<b>&#9650; CROWDED</b> = specs already long &middot; money flowing in &middot; shorts covering &mdash;
everyone is in, skepticism gone. <b>&#9660; WASHED OUT</b> = specs already short &middot;
money flowing out &middot; shorts building &mdash; the crowd has given up. A theme earns a
verdict only when <b>at least two of three</b> point the same way; the badge
shows how many agree. Short interest is deliberately inverted: shorts
<i>covering</i> counts as crowded, shorts <i>building</i> as washed out.
Counts in parentheses are contracts / baskets / stocks behind each reading.</p>
{conf_warn}
{confluence(conf)}
{crowded_panel}

<h2>1 &middot; Positioning signals &mdash; one row per contract, ranked</h2>
<p class="grpnote">The single most informative positioning reading for each contract,
not every cohort of every contract. Rank blends <b>how extreme</b> the reading is
(60% of the 52-week percentile, 40% of the 3-year) with <b>how well that cohort has
actually worked for that specific contract</b>.
<b>Click any column header to sort</b>, or a class chip to filter. Clicking a
contract opens its chart with the relevant cohort panes already on.
<br><span class="warn2">Read the edge column honestly: across all
{n_eff_tested} contract&times;cohort&times;side combinations tested on 1986-onward data,
<b>none reach p&lt;0.05</b> at effective sample size. The column orders which
cohort carries more information for a given contract; it does not certify any of
them. Correlation between OI percentile and |large-spec z| is {oicorr:+.3f} &mdash; a thin
market does <b>not</b> manufacture extreme readings
(<a href="https://www.nber.org/papers/w16712">Hong &amp; Yogo, JFE 2012</a>).</span></p>
{signal_table(sig, oicorr)}

<details class="fold"><summary>Full futures board &mdash; all {n_ch_univ} contracts with a
real price series</summary>
<p class="grpnote">Everything, including what did not clear the extremity floor
above. 52-week percentile in bold, 3-year faded beside it.</p>
<table>{FULL_HDR}<tbody>{board(cu)}</tbody></table></details>

<h2>2 &middot; ETF flows &mdash; sector baskets</h2>
{flow_section()}

<h2>3 &middot; Short interest &mdash; biggest 2-week movers, raw %</h2>
<p class="grpnote">Settlement <b>{settle.date() if settle is not None else '-'}</b>,
{n_si or 0} names with a live chain-linked history. These are the <b>raw %</b>
cuts &mdash; every listing, unstandardised. The <b>z-ranked</b> cut (each name
against its own change history) is the covering/building table on the
<b>Stocks</b> tab, with price context. <b>% float</b> is shares short against the tradeable float
(shares outstanding minus insider/restricted stock), from stockanalysis.com
&mdash; blank where no float data exists (mostly OTC/pink-sheet ADRs).</p>
<div class="si2grid">{si_body}</div>

<div class="note" style="margin-top:28px">
<b>The commercial column is not independent.</b> In the legacy COT report the three
cohort nets sum to <b>exactly zero</b> &mdash; verified across all {nrows:,} rows here
({ident:.1f}% exact, remainder &plusmn;2 contracts of rounding). Commercial net is
<i>defined</i> as &minus;(large spec + small spec). Use it to read composition, not as
confirmation. Genuinely independent hedger data needs the disaggregated report's
Producer/Merchant vs Swap Dealer split.
</div>

<div class="note" style="border-left-color:var(--warn)">
<b>Price/OI regime &mdash; caveats.</b> 13-week price change vs 13-week OI change:
<b>price &uarr; OI &uarr; = new longs</b> &middot; <b>price &uarr; OI &darr; = short covering</b> &middot;
<b>price &darr; OI &uarr; = new shorts</b> &middot; <b>price &darr; OI &darr; = long liquidation</b>.
Moves under 2% price or 3% OI show as Flat. It is a descriptive futures-floor
framework with no published return statistics behind it &mdash; context, not signal.
Prices are front-month continuous, so roll effects contaminate the price leg
(worst in nat gas and crude); entries marked <b>*</b> use an ETF or index proxy.
</div>

<p class="meta" style="margin-top:18px">Sources: CFTC Commitments of Traders
(legacy, futures-only) &middot; FINRA short interest via Nasdaq &middot; ETF shares outstanding
via stockanalysis.com &middot; prices via Yahoo Finance. Not investment advice.</p>
</div>
<div id="ov"><div id="ovb"><span id="ovx">&times;</span><div id="ovc"></div></div></div>
<script>
const TS = {json.dumps(TS, separators=(",", ":"))};
const CH = {json.dumps(specs, separators=(",", ":"))};
const FCH = {json.dumps(fsp, separators=(",", ":"))};
const FCON = {json.dumps(fcon, separators=(",", ":"))};
for (const m of [CH, FCH]) for (const k in m) m[k].t = TS[m[k].ti];
{chartui.CHART_JS}

(function(){{
  const t=document.querySelector('table.sig.board'); if(!t)return;
  const tb=t.tBodies[0];
  let cur=8, asc=false;
  function sort(i, forceAsc){{
    const rows=[...tb.rows];
    if(i===cur && forceAsc===undefined) asc=!asc; else asc=(forceAsc!==undefined)?forceAsc:false;
    cur=i;
    rows.sort(function(a,b){{
      const x=a.cells[i].dataset.sort, y=b.cells[i].dataset.sort;
      const nx=parseFloat(x), ny=parseFloat(y);
      const both=!isNaN(nx)&&!isNaN(ny);
      const c = both ? nx-ny : String(x).localeCompare(String(y));
      return asc?c:-c;}});
    rows.forEach(r=>tb.appendChild(r));
    t.querySelectorAll('th').forEach(function(h,k){{
      h.classList.toggle('sorted',k===i); h.classList.toggle('asc',k===i&&asc);}});}}
  t.querySelectorAll('th').forEach(function(h,i){{h.onclick=function(){{sort(i);}};}});
  sort(8, false);
  document.querySelectorAll('.chip[data-cls]').forEach(function(c){{
    c.onclick=function(){{
      document.querySelectorAll('.chip[data-cls]').forEach(x=>x.classList.remove('on'));
      c.classList.add('on');
      const k=c.dataset.cls;
      [...tb.rows].forEach(function(r){{
        r.style.display=(k==='all'||r.dataset.cls===k)?'':'none';}});}};}});
}})();
const COT_PANES = [['price','Price'],['ls','Large spec'],['ss','Small spec'],
                   ['cm','Commercial'],['oi','Open interest'],['comp','Composition'],
                   ['spy','SPY reference']];
const FLOW_PANES = [['price','Price'],['cum','Cumulative flow'],['flow','Rolling flow'],
                    ['spy','SPY reference']];
const CTX = {{
  ls: ['price','ls','oi','comp'],
  ss: ['price','ss','oi','comp'],
  cm: ['cm','oi','comp'],
  comm: ['cm','oi','comp'],
  oi: ['price','oi','comp']
}};
const BRUSH = {json.dumps(chartui.BRUSH_HTML)};
const CTL = {json.dumps(chartui.ctl_html("weeks", fitted=True))};
function shell(title, sub, panes, spec, keep, tail){{
  const have = new Set(spec.panes.map(p => p.k));
  // PZ.init synthesises the SPY pane from spec.spy, so the button has to be
  // offered before that pane exists.
  if (spec.spy) have.add('spy');
  const btns = panes.filter(p => have.has(p[0])).map(function(p){{
    // SPY is a reference line, on by default: the point of it is reading the
    // extremes above against what the index did next.
    const on = (p[0] === 'spy' || !keep || keep.indexOf(p[0]) >= 0) ? ' on' : '';
    return '<button class="tg' + on + '" data-p="' + p[0] + '">' + p[1] + '</button>';
  }}).join('');
  // PATCH D2a: arrows are a pseudo-pane toggle. No pane has k==='arrows', so it
  // joins the active set harmlessly and the existing .tg handler re-renders free.
  // Default ON only when a cohort is in question; OFF from a tile or the board,
  // where arrows from every cohort would be exactly the smear we removed.
  const arrowOn = spec.primary ? ' on' : '';
  const arrowBtn = '<button class="tg' + arrowOn + '" data-p="arrows" ' +
    'title="Mark on the price line every week the source cohort sat outside its band">' +
    'Signif. arrows</button>';
  return '<div class="chd"><span class="cht">' + (spec.nm || title) + '</span>' +
         '<span class="chs">' + (spec.sub || sub || '') + '</span></div>' +
         '<div class="tog">' + btns + arrowBtn + '</div>' + CTL +
         '<div class="pzbody"></div>' + BRUSH + (tail || '');
}}
const COT_FOOT = {json.dumps(COT_FOOT)};
const FLOW_FOOT = {json.dumps(FLOW_FOOT)};
document.querySelectorAll('[data-f]').forEach(function(el){{
  if (FCH[el.dataset.f]) el.setAttribute('data-has','1');
  el.addEventListener('click', function(){{
    const spec = FCH[el.dataset.f];
    const host = document.getElementById('ovc');
    if (!spec) {{ host.innerHTML = '<p class="nochart">No flow chart for this basket yet.</p>';
                 document.getElementById('ov').classList.add('on'); return; }}
    // the flow modal has exactly one indicator pane; setting primary explicitly
    // stops it inheriting a stale value from a COT chart opened moments earlier
    spec.primary = 'flow';
    host.innerHTML = shell(el.dataset.f, 'ETF dollar flows',
                           FLOW_PANES, spec, null,
                           '<h4 style="margin:14px 0 6px">Constituents &mdash; latest week</h4>' +
                           (FCON[el.dataset.f] || '') + FLOW_FOOT);
    PZ.init(host, spec);
    document.getElementById('ov').classList.add('on');
  }});
}});
document.querySelectorAll('[data-c]').forEach(function(el){{
  if (CH[el.dataset.c]) el.setAttribute('data-has','1');
  el.addEventListener('click', function(){{
    const spec = CH[el.dataset.c];
    const host = document.getElementById('ovc');
    if (!spec) {{ host.innerHTML = '<p class="nochart">No chart for this contract.</p>';
      document.getElementById('ov').classList.add('on'); return; }}
    // PATCH D2b: data-ctx carries the signals.py cohort key (ls/ss/comm/oi);
    // pane keys are ls/ss/cm/oi. Same off-by-one-name that caused A1. Specs are
    // reused across opens, so primary must be assigned EVERY open, null included.
    const PRIMARY = {{ls:'ls', ss:'ss', comm:'cm', cm:'cm', oi:'oi'}};
    spec.primary = PRIMARY[el.dataset.ctx] || null;
    host.innerHTML = shell(el.dataset.name || el.dataset.c, el.dataset.sub || '',
                           COT_PANES, spec, CTX[el.dataset.ctx], COT_FOOT);
    PZ.init(host, spec);
    document.getElementById('ov').classList.add('on');
  }});
}});
document.getElementById('ov').addEventListener('click', function(e){{
  if (e.target.id === 'ov' || e.target.id === 'ovx') this.classList.remove('on');
}});
document.addEventListener('keydown', function(e){{
  if (e.key === 'Escape') document.getElementById('ov').classList.remove('on');
}});
</script>
</body></html>"""
    open(OUT, "w").write(h)
    return OUT, last, settle

if __name__ == "__main__":
    p, c, s = build()
    print(p, c.date(), s.date() if s is not None else None)
