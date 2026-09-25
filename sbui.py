"""Interactive Stockbee explorer: pick a series, set a percentile, see the history.

Deliberately NOT a statistics table. The significance work said none of these
readings is a certified edge, so presenting p-values beside them invites reading
a number as a verdict. What is genuinely useful is the SHAPE: where the series
sits against its own decade, and what SPY was doing when it got there. That is a
chart with a threshold you can move, not a table.
"""
import pandas as pd, numpy as np, json, os, html

D = os.path.expanduser("~/pos")

# key -> (label, group, +1 if a HIGH reading is the "hot" end)
SERIES = [
    ("up4",    "Up 4% today",            "Daily thrust",  +1),
    ("dn4",    "Down 4% today",          "Daily thrust",  -1),
    ("r1",     "4% ratio, daily",        "Daily thrust",  +1),
    ("r5",     "4% ratio, 5-day",        "Daily thrust",  +1),
    ("r10",    "4% ratio, 10-day",       "Daily thrust",  +1),
    ("up8",    "Up 8% in a week",        "Momentum",      +1),
    ("dn8",    "Down 8% in a week",      "Momentum",      -1),
    ("up13",   "Up 13% in 34 days",      "Momentum",      +1),
    ("dn13",   "Down 13% in 34 days",    "Momentum",      -1),
    ("up25m",  "Up 25% in a month",      "Big movers",    +1),
    ("dn25m",  "Down 25% in a month",    "Big movers",    -1),
    ("up25q",  "Up 25% in a quarter",    "Big movers",    +1),
    ("dn25q",  "Down 25% in a quarter",  "Big movers",    -1),
    ("up50m",  "Up 50% in a month",      "Big movers",    +1),
    ("dn50m",  "Down 50% in a month",    "Big movers",    -1),
    ("up50q",  "Up 50% in a quarter",    "Big movers",    +1),
    ("dn50q",  "Down 50% in a quarter",  "Big movers",    -1),
    ("t2108",  "T2108 (% > 40-day MA)",  "Participation", +1),
    ("pct50",  "% above 50-day MA",      "Participation", +1),
    ("pct200", "% above 200-day MA",     "Participation", +1),
    ("hl_net", "Net 52w highs - lows",   "Participation", +1),
]


def _series_payload(hist, spy):
    idx = pd.DatetimeIndex(hist.index)
    s = spy.dropna().reindex(idx, method="ffill")
    out = {"dates": [d.strftime("%Y-%m-%d") for d in idx],
           "spy": [None if not np.isfinite(v) else round(float(v), 2) for v in s.values],
           "series": {}}
    for key, label, grp, hot in SERIES:
        if key not in hist.columns: continue
        v = pd.to_numeric(hist[key], errors="coerce")
        if v.notna().sum() < 100: continue
        out["series"][key] = {
            "label": label, "group": grp, "hot": hot,
            "v": [None if not np.isfinite(x) else round(float(x), 3) for x in v.values],
        }
    return out


def panel(hist, spy):
    if hist is None or not len(hist) or spy is None or not len(spy):
        return ""
    pay = _series_payload(hist, spy)
    if not pay["series"]: return ""
    n = len(pay["dates"])
    first, last = pay["dates"][0], pay["dates"][-1]

    groups = {}
    for key, label, grp, hot in SERIES:
        if key in pay["series"]: groups.setdefault(grp, []).append((key, label))
    chips = []
    for grp, items in groups.items():
        chips.append(f'<div class="sbgrp"><span class="sbglab">{html.escape(grp)}</span>'
                     + "".join(f'<button class="sbchip" data-k="{k}">{html.escape(l)}</button>'
                               for k, l in items) + '</div>')

    return f'''<h2>Stockbee &mdash; indicator history</h2>
<p class="grpnote">Ten years of daily breadth, {n:,} sessions from {first} to {last},
built on 3,111 symbols. Click any indicator to chart it against SPY. The
<b>percentile slider</b> shades every session where the series sat at or beyond
that percentile of its own ten-year history &mdash; drag it to see how often a
reading like today&rsquo;s has actually occurred, and what SPY was doing when it did.</p>
<div class="sbex">
  <div class="sbchips">{"".join(chips)}</div>
  <div class="sbctl">
    <label>Percentile <b id="sbpv">90</b></label>
    <input type="range" id="sbpct" min="50" max="99" value="90" step="1">
    <span class="sbtail">
      <button class="sbtoggle on" id="sbdir" title="Which tail to shade">upper tail</button>
    </span>
    <span class="dim" id="sbhits"></span>
  </div>
  <div id="sbchart"></div>
  <div class="tfz"><div class="tfrow"><div class="tfbar"><div class="tfwin"><i class="hl"></i><i class="hr"></i></div></div>
    <span class="tflab"></span></div>
    <div class="tfctl"><button type="button" class="tfrst">Full range</button></div></div>
</div>
<script id="sbdata" type="application/json">{json.dumps(pay, separators=(",", ":"))}</script>
<script>
(function(){{
  var P=JSON.parse(document.getElementById('sbdata').textContent);
  var cur=null, upper=true;
  var box=document.getElementById('sbchart');
  var root=box.parentNode;
  var bar=root.querySelector('.tfbar'), win=root.querySelector('.tfwin');
  var lab=root.querySelector('.tflab');
  var a=0, b=1;   // brush window as a fraction of the full series -- SLICES the
                  // data and recomputes the y-axis from what's visible, same as
                  // minichart's brush. A viewBox-only crop (zoomjs.py's approach)
                  // leaves vmin/vmax fixed to the full history, so a narrow window
                  // still renders flat -- that was the "doesn't zoom properly" bug.
  function q(arr,p){{var s=arr.filter(function(x){{return x!=null&&isFinite(x);}}).sort(function(x,y){{return x-y;}});
    if(!s.length)return NaN; var i=(s.length-1)*p/100, lo=Math.floor(i), hi=Math.ceil(i);
    return lo===hi?s[lo]:s[lo]+(s[hi]-s[lo])*(i-lo);}}
  function draw(){{
    if(!cur){{box.innerHTML='<p class="dim" style="padding:26px 2px">Pick an indicator above.</p>';
      document.getElementById('sbhits').textContent=''; root.querySelector('.tfz').style.display='none'; return;}}
    root.querySelector('.tfz').style.display='';
    var S=P.series[cur], vAll=S.v, spyAll=P.spy, N=vAll.length;
    var pct=+document.getElementById('sbpct').value;
    // The threshold and the base-rate stat describe the FULL ten-year history --
    // zooming the chart to look at one stretch shouldn't move the goalposts.
    var thr=upper?q(vAll,pct):q(vAll,100-pct);
    var hit=0;
    for(var j=0;j<N;j++){{ if(vAll[j]!=null&&isFinite(vAll[j])&&(upper?vAll[j]>=thr:vAll[j]<=thr)) hit++; }}
    document.getElementById('sbhits').textContent=hit+' of '+N+' sessions ('+(100*hit/N).toFixed(1)+'%) beyond the line, full history';

    var i0=Math.max(0,Math.round(a*(N-1))), i1=Math.min(N-1,Math.round(b*(N-1)));
    if(i1-i0<2) i1=Math.min(N-1,i0+2);
    var v=vAll.slice(i0,i1+1), spy=spyAll.slice(i0,i1+1), dates=P.dates.slice(i0,i1+1), n=v.length;

    var W=1180,H=300,PL=52,PR=52,PT=14,PB=26,iw=W-PL-PR,ih=H-PT-PB;
    var fv=v.filter(function(x){{return x!=null&&isFinite(x);}});
    var vmin=fv.length?Math.min.apply(null,fv):0, vmax=fv.length?Math.max.apply(null,fv):1;
    if(vmax===vmin){{vmax+=1;vmin-=1;}}
    var fs=spy.filter(function(x){{return x!=null&&isFinite(x);}});
    var smin=fs.length?Math.min.apply(null,fs):0, smax=fs.length?Math.max.apply(null,fs):1;
    if(smax===smin){{smax+=1;smin-=1;}}
    var X=function(i){{return PL+iw*(n<2?0.5:i/(n-1));}};
    var Yv=function(x){{return PT+ih-ih*(x-vmin)/((vmax-vmin)||1);}};
    var Ys=function(x){{return PT+ih-ih*(x-smin)/((smax-smin)||1);}};
    var bands='',run=-1;
    for(var i=0;i<n;i++){{
      var on=v[i]!=null&&isFinite(v[i])&&(upper?v[i]>=thr:v[i]<=thr);
      if(on&&run<0)run=i;
      if((!on||i===n-1)&&run>=0){{var x0=X(run),x1=X(i);
        bands+='<rect x="'+x0.toFixed(1)+'" y="'+PT+'" width="'+Math.max(x1-x0,1).toFixed(1)+'" height="'+ih+'" fill="var(--warn)" opacity=".13"/>';run=-1;}}
    }}
    function path(arr,Y){{var d='',pen=false;
      for(var i=0;i<n;i++){{var y=arr[i];
        if(y==null||!isFinite(y)){{pen=false;continue;}}
        d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(y).toFixed(1)+' ';pen=true;}}
      return d;}}
    var ticks='';
    var step=Math.max(1,Math.floor(n/9));
    for(var i=0;i<n;i+=step){{var d=dates[i];
      ticks+='<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" class="ax">'+d.slice(0,7)+'</text>';}}
    var gy='';
    for(var k=0;k<=4;k++){{var yy=PT+ih*k/4, vv=vmax-(vmax-vmin)*k/4;
      gy+='<line x1="'+PL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+yy.toFixed(1)+'" stroke="var(--grid)"/>'+
          '<text x="'+(PL-6)+'" y="'+(yy+3.5).toFixed(1)+'" text-anchor="end" class="ax">'+(Math.abs(vv)>=1000?Math.round(vv):vv.toFixed(1))+'</text>'+
          '<text x="'+(W-PR+6)+'" y="'+(yy+3.5).toFixed(1)+'" class="ax sp">'+Math.round(smax-(smax-smin)*k/4)+'</text>';}}
    var bands2='';
    if(thr>=vmin&&thr<=vmax){{ var ty=Yv(thr);
      bands2='<line x1="'+PL+'" y1="'+ty.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+ty.toFixed(1)+'" stroke="var(--warn)" stroke-dasharray="4 3"/>'; }}
    box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" class="sbsvg">'+
      bands+gy+
      '<path d="'+path(spy,Ys)+'" fill="none" stroke="var(--mut)" stroke-width="1.1" opacity=".75"/>'+
      '<path d="'+path(v,Yv)+'" fill="none" stroke="var(--cool)" stroke-width="1.4"/>'+
      bands2+ticks+'</svg>'+
      '<div class="sblg"><span class="k cool"></span>'+S.label+
      '<span class="k mut"></span>SPY (right axis)'+
      '<span class="k warn"></span>'+(upper?'at or above ':'at or below ')+
      'the '+pct+'th percentile ('+(Math.abs(thr)>=1000?Math.round(thr):thr.toFixed(2))+')'+
      (thr<vmin||thr>vmax?' <i class="dim">(off-screen in this window)</i>':'')+'</div>';
    lab.textContent=dates[0]+'  →  '+dates[dates.length-1]+'   ('+n+' points)';
  }}
  function paint(){{
    if(b-a<0.02) b=a+0.02;
    if(a<0){{b-=a;a=0;}} if(b>1){{a-=(b-1);b=1;}} if(a<0)a=0;
    win.style.left=(a*100)+'%'; win.style.width=((b-a)*100)+'%';
    draw();
  }}
  function frac(e){{var r=bar.getBoundingClientRect();
    return Math.min(1,Math.max(0,(e.clientX-r.left)/(r.width||1)));}}
  var drag=null;
  bar.addEventListener('pointerdown',function(e){{
    var f=frac(e);
    if(e.target.classList.contains('hl')) drag={{m:'l'}};
    else if(e.target.classList.contains('hr')) drag={{m:'r'}};
    else if(win.contains(e.target)||e.target===win) drag={{m:'move',f:f,a:a,b:b}};
    else {{var w=b-a; a=f-w/2; b=a+w; paint(); drag={{m:'move',f:f,a:a,b:b}};}}
    bar.setPointerCapture(e.pointerId);
  }});
  bar.addEventListener('pointermove',function(e){{
    if(!drag) return; var f=frac(e);
    if(drag.m==='l') a=Math.min(f,b-0.02);
    else if(drag.m==='r') b=Math.max(f,a+0.02);
    else {{var d=f-drag.f; a=drag.a+d; b=drag.b+d;}}
    paint();
  }});
  function endDrag(e){{drag=null; try{{bar.releasePointerCapture(e.pointerId);}}catch(_){{}}}}
  bar.addEventListener('pointerup',endDrag); bar.addEventListener('pointercancel',endDrag);
  root.querySelector('.tfrst').addEventListener('click',function(){{a=0;b=1;paint();}});

  document.querySelectorAll('.sbex .sbchip').forEach(function(btn){{
    btn.onclick=function(){{
      document.querySelectorAll('.sbex .sbchip').forEach(function(x){{x.classList.remove('on');}});
      btn.classList.add('on'); cur=btn.dataset.k; a=0; b=1; paint();}};}});
  document.getElementById('sbpct').oninput=function(){{
    document.getElementById('sbpv').textContent=this.value; draw();}};
  document.getElementById('sbdir').onclick=function(){{
    upper=!upper; this.textContent=upper?'upper tail':'lower tail';
    this.classList.toggle('on',upper); draw();}};
  var f=document.querySelector('.sbex .sbchip'); if(f){{f.click();}}
}})();
</script>'''
