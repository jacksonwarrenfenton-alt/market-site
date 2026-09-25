"""Short-interest breadth through time: who is covering, who is building, vs SPY.

The board's SI panel answers "what is short interest now". This answers the
question that actually drives a squeeze: how MANY names are covering hard versus
building hard, settlement by settlement, against what SPY did.

Counts, not the median. Across ~360 names the median change washes out to nearly
zero every period and never says anything; the tails are where the information
is. A name counts as COVERING when its settlement-over-settlement change in
shares short is at or below -1 sigma of its own history, and BUILDING at or
above +1 sigma.
"""
import pandas as pd, numpy as np, json, os, html

D = os.path.expanduser("~/pos")
Z = 1.0
MIN_OBS = 6


def series():
    """Prefer the FINRA bulk history -- it is the authoritative source and goes
    years deeper than the per-ticker scrape, which only keeps ~25 settlements."""
    f = f"{D}/si_finra.parquet"
    if os.path.exists(f):
        a = pd.read_parquet(f)
        if a is not None and len(a):
            h = pd.DataFrame({
                "date": pd.to_datetime(a.settlementDate),
                "symbol": a.symbolCode,
                "si": pd.to_numeric(a.currentShortPositionQuantity, errors="coerce"),
            }).dropna()
            # Keep names with real size; the long tail of micro floats adds noise,
            # not information, and would dominate a count-based breadth read.
            big = h.groupby("symbol").si.median()
            h = h[h.symbol.isin(big[big >= 250_000].index)]
            return _counts(h)
    p = f"{D}/si_hist.parquet"
    if not os.path.exists(p): return None
    h = pd.read_parquet(p)
    if h is None or not len(h): return None
    h = h[["date", "symbol", "si"]].dropna()
    return _counts(h)


def _counts(h):
    w = h.pivot_table(index="date", columns="symbol", values="si").sort_index()
    if len(w) < MIN_OBS: return None
    chg = w.pct_change() * 100
    # z of each name's change against its OWN history, so a volatile small cap
    # and a mega cap are held to the same standard.
    mu, sd = chg.mean(), chg.std().replace(0, np.nan)
    z = (chg - mu) / sd
    out = pd.DataFrame({
        "covering": (z <= -Z).sum(axis=1),
        "building": (z >= Z).sum(axis=1),
        "n": z.notna().sum(axis=1),
    })
    out = out[out.n >= 30]
    if not len(out): return None
    out["net"] = out.covering - out.building
    out["net_pct"] = 100 * out.net / out.n
    return out


def panel(spy):
    d = series()
    if d is None or len(d) < 3:
        return ('<h2>Short interest &mdash; covering vs building</h2>'
                '<p class="grpnote">Not enough settlement history yet. FINRA '
                'publishes twice a month and each name needs several settlements '
                'before its change can be standardised; this panel fills in as the '
                'record grows.</p>')
    idx = pd.DatetimeIndex(d.index)
    s = spy.dropna().reindex(idx, method="ffill") if spy is not None else pd.Series(index=idx, dtype=float)
    pay = {"dates": [x.strftime("%Y-%m-%d") for x in idx],
           "cov": [int(v) for v in d.covering], "bld": [int(v) for v in d.building],
           "net": [round(float(v), 1) for v in d.net_pct],
           "tilt": [round(float(v), 1) for v in d.net_pct.rolling(3, min_periods=1).mean()],
           "n": [int(v) for v in d.n],
           "spy": [None if not np.isfinite(v) else round(float(v), 2) for v in s.values]}
    last = d.iloc[-1]
    lean = ("covering" if last.net > 0 else "building")
    return f'''<h2>Short interest &mdash; covering vs building</h2>
<p class="grpnote">Each settlement, how many names had their shares short fall by a
standard deviation or more (<b>covering</b>) against how many built by as much
(<b>building</b>), plotted with SPY. Counts rather than the median, because
across {int(last.n)} names the median change is ~0 every period and never carries
information &mdash; the tails do. Latest settlement leans <b>{lean}</b>:
{int(last.covering)} covering vs {int(last.building)} building of {int(last.n)}.</p>
<div id="sichart"></div>
<script id="sidata" type="application/json">{json.dumps(pay, separators=(",", ":"))}</script>
<script>
(function(){{
  var P=JSON.parse(document.getElementById('sidata').textContent),N=P.dates.length;
  var W=1180,H=250,PL=46,PR=52,PT=14,PB=26,iw=W-PL-PR,ih=H-PT-PB;
  var mx=Math.max.apply(null,P.cov.concat(P.bld))||1;
  var fs=P.spy.filter(function(x){{return x!=null&&isFinite(x);}});
  var smin=Math.min.apply(null,fs),smax=Math.max.apply(null,fs);
  var bw=Math.max(2,iw/N*0.36);
  var X=function(i){{return PL+iw*(N===1?0.5:i/(N-1));}};
  var Yb=function(v){{return PT+ih-ih*v/mx;}};
  var Ys=function(v){{return PT+ih-ih*(v-smin)/((smax-smin)||1);}};
  var g='',bars='',ticks='';
  for(var k=0;k<=4;k++){{var yy=PT+ih*k/4;
    g+='<line x1="'+PL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+yy.toFixed(1)+'" stroke="var(--grid)"/>'+
       '<text x="'+(PL-6)+'" y="'+(yy+3.5).toFixed(1)+'" text-anchor="end" class="ax">'+Math.round(mx-mx*k/4)+'</text>'+
       '<text x="'+(W-PR+6)+'" y="'+(yy+3.5).toFixed(1)+'" class="ax sp">'+Math.round(smax-(smax-smin)*k/4)+'</text>';}}
  for(var i=0;i<N;i++){{
    var x=X(i);
    bars+='<rect x="'+(x-bw-1).toFixed(1)+'" y="'+Yb(P.cov[i]).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+(ih-Yb(P.cov[i])+PT-PT).toFixed(1)+'" fill="var(--good)" opacity=".8"><title>'+P.dates[i]+' — '+P.cov[i]+' covering</title></rect>';
    bars+='<rect x="'+(x+1).toFixed(1)+'" y="'+Yb(P.bld[i]).toFixed(1)+'" width="'+bw.toFixed(1)+'" height="'+(ih-Yb(P.bld[i])).toFixed(1)+'" fill="var(--crit)" opacity=".8"><title>'+P.dates[i]+' — '+P.bld[i]+' building</title></rect>';
    if(i%Math.max(1,Math.floor(N/8))===0)
      ticks+='<text x="'+x.toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" class="ax">'+P.dates[i].slice(2,7)+'</text>';
  }}
  // Tilt: covering minus building as a share of the covered universe, smoothed
  // over three settlements. The bars answer "what happened this period"; the
  // tilt answers "which way is the pressure leaning", which is the part that
  // persists and the part worth trading against.
  var tmin=Math.min.apply(null,P.tilt),tmax=Math.max.apply(null,P.tilt);
  var tspan=Math.max(Math.abs(tmin),Math.abs(tmax))||1;
  var Yt=function(v){{return PT+ih/2-(ih/2-6)*v/tspan;}};
  var tl='',tp=false;
  for(var i=0;i<N;i++){{var v=P.tilt[i]; if(v==null||!isFinite(v)){{tp=false;continue;}}
    tl+=(tp?'L':'M')+X(i).toFixed(1)+' '+Yt(v).toFixed(1)+' ';tp=true;}}
  var zero='<line x1="'+PL+'" y1="'+Yt(0).toFixed(1)+'" x2="'+(W-PR)+'" y2="'+Yt(0).toFixed(1)+'" stroke="var(--base)" stroke-dasharray="3 3"/>';
  var sp='',pen=false;
  for(var i=0;i<N;i++){{var y=P.spy[i]; if(y==null||!isFinite(y)){{pen=false;continue;}}
    sp+=(pen?'L':'M')+X(i).toFixed(1)+' '+Ys(y).toFixed(1)+' ';pen=true;}}
  document.getElementById('sichart').innerHTML=
    '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" class="sbsvg">'+g+bars+
    zero+'<path d="'+tl+'" fill="none" stroke="var(--vio)" stroke-width="1.8"/>'+
    '<path d="'+sp+'" fill="none" stroke="var(--ink2)" stroke-width="1.3"/>'+ticks+'</svg>'+
    '<div class="sblg"><span class="k good"></span>covering hard<span class="k crit"></span>building hard'+
    '<span class="k vio"></span>tilt (covering &minus; building, 3-period mean)'+
    '<span class="k ink2"></span>SPY (right axis)</div>';
}})();
</script>'''
