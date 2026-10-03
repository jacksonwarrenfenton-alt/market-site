"""Market-tab dashboard: the at-a-glance layer the rest of the board lacked.

Modelled on what the trading sites jman uses put first:
  tape()      a quote strip (MarketPulse / TradingView header) -- the handful of
              prices that frame the day, each with its own day change.
  leaders()   a group leaderboard (Deepvue's ranked list + 1-99 ratings) -- the
              strongest and weakest of the 253 custom baskets by relative
              strength, because the best trade is in the leading group.
  heatmap()   a sector heatmap (Deepvue / Finviz) -- every basket as a tile,
              grouped by sector, coloured by 1-month RS vs SPY, so rotation
              reads as a picture instead of a 253-row table.
Everything here is computed from data the build already holds (the subsector
frame and a small Yahoo price pull); nothing new is scraped.
"""
import os, html, sys
import numpy as np, pandas as pd

D = os.path.expanduser("~/pos")
TAPE = [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("IWM", "Russell 2000"),
        ("^VIX", "VIX"), ("DX-Y.NYB", "Dollar"), ("^TNX", "10y yield"),
        ("GC=F", "Gold"), ("CL=F", "WTI crude"), ("BTC-USD", "Bitcoin")]

CSS = """
.tape{display:flex;gap:0;overflow-x:auto;border:1px solid var(--grid);border-radius:6px;
background:var(--s);margin:4px 0 14px}
.tq{flex:1 0 118px;padding:8px 12px;border-right:1px solid var(--grid)}
.tq:last-child{border-right:0}
.tq span{display:block;font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut)}
.tq b{font-size:15px;font-variant-numeric:tabular-nums}
.tq i{font-style:normal;font-size:11px;font-weight:700;margin-left:6px;font-variant-numeric:tabular-nums}
.tq i.up{color:#1baf7a}.tq i.dn{color:#e66767}
.dash2{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:16px;align-items:start}
@media(max-width:1100px){.dash2{grid-template-columns:1fr}}
.card{border:1px solid var(--grid);border-radius:6px;background:var(--s);padding:12px 14px}
.card h4{margin:0 0 8px;display:flex;justify-content:space-between;align-items:baseline}
.card h4 span{font-weight:400;text-transform:none;letter-spacing:0;color:var(--mut);font-size:10.5px}
table.lead td,table.lead th{font-size:11.5px;padding:3px 6px}
table.lead td.g{text-align:left;max-width:300px;overflow:hidden;text-overflow:ellipsis}
table.lead td.g small{display:block;color:var(--mut);font-size:9.5px}
.rr{display:inline-block;min-width:26px;text-align:center;font-weight:800;font-size:11px;
border-radius:4px;padding:1px 4px;color:#fff}
td.lb{width:34%;padding:0 6px}
td.lb i{display:block;height:9px;border-radius:2px}
.rk{font-size:10px;color:var(--mut)}.rk.up{color:#1baf7a}.rk.dn{color:#e66767}
.hm{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:10px}
.hmsec h5{margin:0 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--ink2)}
.hmsec h5 i{font-style:normal;color:var(--mut);margin-left:6px}
.hmt{display:flex;flex-wrap:wrap;gap:2px}
.hmt b{flex:1 0 46px;height:34px;border-radius:3px;font-size:9px;font-weight:600;color:#fff;
padding:3px 4px;overflow:hidden;line-height:1.15;cursor:default}
.hmlg{display:flex;align-items:center;gap:8px;font-size:10px;color:var(--mut);margin:6px 0 10px}
.hmlg i{display:inline-block;width:120px;height:8px;border-radius:2px;
background:linear-gradient(90deg,rgb(230,103,103),rgb(56,56,53),rgb(27,175,122))}
"""


def _rgb(v, scale):
    if v is None or not np.isfinite(v): return "rgb(44,44,42)"
    t = max(-1.0, min(1.0, v / scale)); a = abs(t)
    pole = (27, 175, 122) if t > 0 else (230, 103, 103); mid = (56, 56, 53)
    return "rgb(%d,%d,%d)" % tuple(int(mid[i] + (pole[i] - mid[i]) * a) for i in range(3))


def _split(name):
    s, _, g = str(name).partition(" - ")
    return (s, g) if g else ("Other", s)


def tape():
    try:
        import prices as P
        px = P.fetch_list([t for t, _ in TAPE], cache=f"{D}/tape_prices.parquet",
                          maxage=3600, rng="6mo")
    except Exception as e:
        print("tape failed:", e, file=sys.stderr, flush=True)
        return ""
    cells = []
    for t, lab in TAPE:
        if t not in px.columns: continue
        s = px[t].dropna()
        if len(s) < 2: continue
        last, prev = float(s.iloc[-1]), float(s.iloc[-2])
        if t == "^TNX":  # quoted in yield points: show the level, change in bp
            ch = (last - prev) * 100
            val, chs = f"{last:.2f}%", f"{ch:+.0f}bp"
        else:
            ch = 100 * (last / prev - 1)
            val = f"{last:,.0f}" if last >= 1000 else f"{last:,.2f}"
            chs = f"{ch:+.2f}%"
        cls = "up" if ch > 0 else "dn" if ch < 0 else ""
        cells.append(f'<div class="tq"><span>{lab}</span><b>{val}</b><i class="{cls}">{chs}</i></div>')
    asof = px.index.max()
    return (f'<div class="tape" title="Last close {asof:%Y-%m-%d} (Yahoo)">' + "".join(cells) + "</div>") if cells else ""


def leaders(sub, n_top=15, n_bot=8):
    if sub is None or not len(sub): return ""
    d = sub.dropna(subset=["rs_m"]).sort_values("rank")
    mx = float(np.nanmax(np.abs(d.rs_m))) or 1.0

    def rows(x):
        out = []
        for r in x.itertuples():
            sec, grp = _split(r.name)
            rr = getattr(r, "rs_rank", np.nan)
            badge = (f'<span class="rr" style="background:{_rgb(rr - 50, 50)}">{int(rr)}</span>'
                     if np.isfinite(rr) else "")
            dr = getattr(r, "d_rank", np.nan)
            mv = ("" if not np.isfinite(dr) or dr == 0 else
                  f'<span class="rk {"up" if dr > 0 else "dn"}">{"&#9650;" if dr > 0 else "&#9660;"}{abs(int(dr))}</span>')
            w = 100 * abs(r.rs_m) / mx
            out.append(
                f'<tr><td>{int(r.rank)} {mv}</td><td>{badge}</td>'
                f'<td class="g">{html.escape(grp)}<small>{html.escape(sec)} &middot; {int(r.n)} names</small></td>'
                f'<td class="lb"><i style="width:{w:.0f}%;background:{_rgb(r.rs_m, mx)}"></i></td>'
                f'<td>{r.rs_w:+.1f}</td><td><b>{r.rs_m:+.1f}</b></td><td>{r.rs_q:+.1f}</td></tr>')
        return "".join(out)

    head = ('<thead><tr><th>#</th><th>RS</th><th style="text-align:left">Group</th><th></th>'
            '<th>1W</th><th>1M</th><th>3M</th></tr></thead>')
    return (
        '<div class="card"><h4>Leading groups<span>RS vs SPY, % &middot; rating 1&ndash;99</span></h4>'
        f'<table class="lead">{head}<tbody>{rows(d.head(n_top))}</tbody></table>'
        '<h4 style="margin-top:12px">Lagging groups<span>the short side / avoid list</span></h4>'
        f'<table class="lead">{head}<tbody>{rows(d.tail(n_bot).iloc[::-1])}</tbody></table></div>')


def heatmap(sub):
    if sub is None or not len(sub): return ""
    d = sub.dropna(subset=["rs_m"]).copy()
    d["sec"], d["grp"] = zip(*d.name.map(_split))
    scale = float(np.nanpercentile(np.abs(d.rs_m), 90)) or 1.0
    secs = (d.groupby("sec").rs_m.median().sort_values(ascending=False))
    blocks = []
    for sec, med in secs.items():
        g = d[d.sec == sec].sort_values("rs_m", ascending=False)
        tiles = "".join(
            f'<b style="background:{_rgb(r.rs_m, scale)}" '
            f'title="{html.escape(r.grp)} &#10;1M RS {r.rs_m:+.1f}% &middot; 1W {r.rs_w:+.1f}% &middot; 3M {r.rs_q:+.1f}% &middot; rank {int(r.rank)}">'
            f'{html.escape(r.grp[:22])}</b>' for r in g.itertuples())
        blocks.append(f'<div class="hmsec"><h5>{html.escape(sec)}<i>{med:+.1f}% median</i></h5>'
                      f'<div class="hmt">{tiles}</div></div>')
    return ('<h2>Group heatmap &mdash; where the strength is</h2>'
            '<p class="grpnote">Every custom basket as a tile, grouped by sector and sorted '
            'strongest first; colour is 1-month relative strength vs SPY. Sectors are ordered by '
            'their median group, so rotation shows up as which blocks are green. Hover a tile '
            'for its 1W / 1M / 3M numbers; the full sortable board is on the Groups tab.</p>'
            f'<div class="hmlg">&minus;{scale:.0f}%<i></i>+{scale:.0f}%</div>'
            f'<div class="hm">{"".join(blocks)}</div>')


def top(sub, regime_html, read_html):
    """Tape, then regime + leaderboard side by side, then the written read."""
    return (f"<style>{CSS}</style>" + tape()
            + '<div class="dash2"><div>' + regime_html
            + "<h2>Today's read &mdash; written from the data below</h2>" + read_html
            + "</div>" + leaders(sub) + "</div>" + heatmap(sub))
