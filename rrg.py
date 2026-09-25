"""Rotation map: every group placed by short-horizon strength against long.

The board ranks groups on one number. That tells you who is strong; it does not
tell you which way they are travelling, and rotation is the whole point -- a
group at rank 40 improving fast is a very different proposition from one at rank
40 rolling over.

  x  long horizon:  a blend of 1-month and 3-month relative strength, percentiled
  y  short horizon: a blend of 1-week and 1-month relative strength, percentiled

Long on the bottom is the right way round: the x position is where a group HAS
been, the y position is what it is doing NOW, so vertical movement is the thing
that changes week to week and the eye reads it as motion.

Both axes are cross-sectional percentiles of the 253 groups, so the picture is
always about where a group sits RELATIVE to the rest of the board rather than
against an absolute return that drifts with the market.

Quadrants read clockwise from top right: LEADING (strong and still pushing),
WEAKENING (still strong, losing the short end first -- this is where tops start),
LAGGING, then IMPROVING (weak but the short end has turned, where bottoms start).
"""
import pandas as pd, numpy as np, json, html

# short blend leans on the most recent week; long blend leans on the quarter
W_SHORT = (0.6, 0.4)      # 1w, 1m
W_LONG  = (0.45, 0.55)    # 1m, 3m

SECTORS = ["Communications", "Technology", "Industrials", "Financials",
           "Consumer Discretionary", "Consumer Staples", "Healthcare",
           "Utilities", "Energy", "Materials", "Real Estate"]
COLOR = {"Communications": "#c78ce0", "Technology": "#3987e5",
         "Industrials": "#9aa0a6", "Financials": "#3fd39b",
         "Consumer Discretionary": "#f0883e", "Consumer Staples": "#e06c9f",
         "Healthcare": "#5ec8d8", "Utilities": "#fab219",
         "Energy": "#e05c4a", "Materials": "#b58b4a", "Real Estate": "#8f7fe8"}


MIN_N = 8        # a basket this thin is one or two stocks wearing a group's name
MIN_COV = 6      # of the nine confluence legs, this many must actually cover it
MIN_AGREE = 4    # and this many must agree, or the placement is not confirmed


def _pct(s):
    s = pd.Series(s, dtype="float64")
    if s.notna().sum() < 5: return pd.Series(np.nan, index=s.index)
    return (s.rank(pct=True) * 100).round(1)


def payload(df):
    if df is None or not len(df): return None
    need = {"rs_w", "rs_m", "rs_q"}
    if not need <= set(df.columns): return None
    d = df.copy()
    # Only large, confirmed baskets belong on a rotation map. A four-member
    # group can sit in the LEADING corner on one stock, and a group the legs
    # disagree about has no reliable position to plot -- both would read as
    # signal at a glance while being noise.
    n_all = len(d)
    if "n" in d.columns:
        d = d[d.n >= MIN_N]
    if "c_cov" in d.columns:
        d = d[d.c_cov.fillna(0) >= MIN_COV]
    if "c_n" in d.columns:
        d = d[d.c_n.fillna(0) >= MIN_AGREE]
    if not len(d): return None
    short = W_SHORT[0] * _pct(d.rs_w) + W_SHORT[1] * _pct(d.rs_m)
    long_ = W_LONG[0] * _pct(d.rs_m) + W_LONG[1] * _pct(d.rs_q)
    d["x"] = _pct(long_); d["y"] = _pct(short)
    d["sec"] = d.name.map(lambda n: str(n).split(" - ")[0].strip())
    d = d.dropna(subset=["x", "y"])
    pts = [{
        "n": str(r["name"]).split(" - ")[-1][:34],
        "f": str(r["name"]),
        "s": r["sec"] if r["sec"] in COLOR else "Industrials",
        "x": float(r.x), "y": float(r.y),
        "w": None if not np.isfinite(r.rs_w) else round(float(r.rs_w), 1),
        "m": None if not np.isfinite(r.rs_m) else round(float(r.rs_m), 1),
        "q": None if not np.isfinite(r.rs_q) else round(float(r.rs_q), 1),
        "r": int(r["rank"]) if "rank" in d.columns and np.isfinite(r.get("rank", np.nan)) else None,
    } for _, r in d.iterrows()]
    # Significance shading. A group is only "notably" strong or weak when it is
    # far from the middle on BOTH axes at once -- distance from the centre, with
    # the cut taken from this board's own distribution rather than a fixed
    # number, so the shaded area moves as the market compresses or spreads out.
    dist = np.sqrt((d.x - 50) ** 2 + (d.y - 50) ** 2)
    r = float(np.nanpercentile(dist, 85)) if dist.notna().sum() >= 20 else 45.0
    r = max(18.0, min(r, 62.0))
    strong = int(((dist >= r) & (d.x >= 50) & (d.y >= 50)).sum())
    weak = int(((dist >= r) & (d.x < 50) & (d.y < 50)).sum())
    return {"pts": pts, "color": COLOR, "r": round(r, 1),
            "nstrong": strong, "nweak": weak, "n_all": n_all}


def panel(df):
    pay = payload(df)
    if not pay: return ""
    n = len(pay["pts"])
    legend = "".join(
        f'<button class="rsec" data-s="{html.escape(s)}" '
        f'style="--c:{COLOR[s]}">{html.escape(s)}</button>'
        for s in SECTORS)
    return f'''<div class="rrgwrap">
  <div class="rrghead">
    <button id="rrgtog" class="btn ghost">Show rotation map</button>
    <span class="dim">{n} groups &middot; short horizon across, long horizon up
      &mdash; both percentiled against the board</span>
  </div>
  <div id="rrgbody" hidden>
    <p class="grpnote">{n} of {pay['n_all']} groups shown &mdash; only baskets with
    at least {MIN_N} members that {MIN_AGREE} or more of the nine confluence legs
    cover and agree on. A four-member basket can sit in the leading corner on one
    stock, and a group the legs disagree about has no reliable position to plot;
    both would read as signal at a glance. Each group placed by <b>short-horizon strength</b> (60%
    1-week, 40% 1-month) against <b>long-horizon strength</b> (45% 1-month, 55%
    3-month), both as percentiles of all {n} groups. Reading clockwise from top
    right: <b>Leading</b> is strong and still pushing; <b>Weakening</b> is still
    strong but losing the short end first, which is where tops begin;
    <b>Lagging</b>; and <b>Improving</b>, weak but with the short end already
    turned, which is where bottoms begin. Click a sector to isolate it, click
    again to restore. Hover any point for its actual returns.</p>
    <div class="rleg">{legend}<button class="rsec on" data-s="ALL">All</button></div>
    <div id="rrgchart"></div>
  </div>
</div>
<script id="rrgdata" type="application/json">{json.dumps(pay, separators=(",", ":"))}</script>
<script>
(function(){{
  var P=JSON.parse(document.getElementById('rrgdata').textContent);
  var PTS=P.pts, COL=P.color, only=null, drawn=false;
  function esc(s){{return String(s).replace(/[&<>"]/g,function(c){{
    return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c];}});}}
  function draw(){{
    var W=1180,H=620,PL=44,PR=18,PT=18,PB=34,iw=W-PL-PR,ih=H-PT-PB;
    var X=function(v){{return PL+iw*v/100;}}, Y=function(v){{return PT+ih-ih*v/100;}};
    var mx=X(50), my=Y(50);
    // Shade ONLY the significant corners: beyond the radius, in the strong and
    // weak quadrants. The middle is left clean because that is the honest
    // statement -- most groups sit near the median and mean nothing.
    var rx = iw*P.r/100, ry = ih*P.r/100;
    var q='<defs>'
      +'<clipPath id="rcS"><rect x="'+mx+'" y="'+PT+'" width="'+(W-PR-mx)+'" height="'+(my-PT)+'"/></clipPath>'
      +'<clipPath id="rcW"><rect x="'+PL+'" y="'+my+'" width="'+(mx-PL)+'" height="'+(PT+ih-my)+'"/></clipPath>'
      +'<mask id="rmS"><rect x="0" y="0" width="'+W+'" height="'+H+'" fill="#fff"/>'
      +'<ellipse cx="'+mx+'" cy="'+my+'" rx="'+rx+'" ry="'+ry+'" fill="#000"/></mask>'
      +'<mask id="rmW"><rect x="0" y="0" width="'+W+'" height="'+H+'" fill="#fff"/>'
      +'<ellipse cx="'+mx+'" cy="'+my+'" rx="'+rx+'" ry="'+ry+'" fill="#000"/></mask>'
      +'</defs>'
      +'<rect x="'+mx+'" y="'+PT+'" width="'+(W-PR-mx)+'" height="'+(my-PT)+'" '
      +'fill="#0ca30c" opacity=".13" clip-path="url(#rcS)" mask="url(#rmS)"/>'
      +'<rect x="'+PL+'" y="'+my+'" width="'+(mx-PL)+'" height="'+(PT+ih-my)+'" '
      +'fill="#d03b3b" opacity=".13" clip-path="url(#rcW)" mask="url(#rmW)"/>'
      +'<ellipse cx="'+mx+'" cy="'+my+'" rx="'+rx+'" ry="'+ry+'" fill="none" '
      +'stroke="var(--base)" stroke-dasharray="3 4"/>';
    var lab=''
      +'<text x="'+(W-PR-10)+'" y="'+(PT+16)+'" text-anchor="end" class="rq" fill="#0ca30c">LEADING</text>'
      +'<text x="'+(PL+10)+'" y="'+(PT+16)+'" class="rq" fill="#3987e5">IMPROVING</text>'
      +'<text x="'+(PL+10)+'" y="'+(PT+ih-8)+'" class="rq" fill="#d03b3b">LAGGING</text>'
      +'<text x="'+(W-PR-10)+'" y="'+(PT+ih-8)+'" text-anchor="end" class="rq" fill="#fab219">WEAKENING</text>';
    var g='';
    for(var k=0;k<=4;k++){{
      var gx=PL+iw*k/4, gy=PT+ih*k/4;
      g+='<line x1="'+gx+'" y1="'+PT+'" x2="'+gx+'" y2="'+(PT+ih)+'" stroke="var(--grid)"/>'
       +'<line x1="'+PL+'" y1="'+gy+'" x2="'+(W-PR)+'" y2="'+gy+'" stroke="var(--grid)"/>'
       +'<text x="'+gx+'" y="'+(H-12)+'" text-anchor="middle" class="ax">'+(k*25)+'</text>'
       +'<text x="'+(PL-7)+'" y="'+(gy+3.5)+'" text-anchor="end" class="ax">'+(100-k*25)+'</text>';
    }}
    g+='<line x1="'+mx+'" y1="'+PT+'" x2="'+mx+'" y2="'+(PT+ih)+'" stroke="var(--base)"/>'
     +'<line x1="'+PL+'" y1="'+my+'" x2="'+(W-PR)+'" y2="'+my+'" stroke="var(--base)"/>';
    var dots='';
    PTS.forEach(function(p){{
      var on = !only || p.s===only;
      var c = COL[p.s]||'#9aa0a6';
      var cx=X(p.x), cy=Y(p.y);
      dots+='<g opacity="'+(on?1:0.12)+'">'
        +'<circle cx="'+cx.toFixed(1)+'" cy="'+cy.toFixed(1)+'" r="3.4" fill="'+c+'">'
        +'<title>'+esc(p.f)+(p.r?('  ·  rank '+p.r):'')
        +'\\n1w '+(p.w===null?'–':p.w+'%')+'   1m '+(p.m===null?'–':p.m+'%')
        +'   3m '+(p.q===null?'–':p.q+'%')+'</title></circle>'
        // labels flip to the left of the dot near the right edge, or they run
        // off the plot and the strongest groups become the unreadable ones
        +(on?('<text x="'+(p.x>72?(cx-5):(cx+5)).toFixed(1)+'" y="'+(cy+2.6).toFixed(1)
             +'" class="rlab"'+(p.x>72?' text-anchor="end"':'')+'>'+esc(p.n)+'</text>'):'')
        +'</g>';
    }});
    document.getElementById('rrgchart').innerHTML=
      '<svg viewBox="0 0 '+W+' '+H+'" class="sbsvg rrgsvg">'+q+g+lab+dots+
      '<text x="'+(PL+iw/2)+'" y="'+(H-1)+'" text-anchor="middle" class="ax">'
      +'long horizon percentile (1m/3m)</text>'
      +'<text transform="translate(11,'+(PT+ih/2)+') rotate(-90)" text-anchor="middle" '
      +'class="ax">short horizon percentile (1w/1m)</text></svg>';
  }}
  document.getElementById('rrgtog').onclick=function(){{
    var b=document.getElementById('rrgbody');
    b.hidden=!b.hidden;
    this.textContent=b.hidden?'Show rotation map':'Hide rotation map';
    if(!b.hidden&&!drawn){{drawn=true;draw();}}
  }};
  document.querySelectorAll('.rsec').forEach(function(b){{
    b.onclick=function(){{
      var s=b.dataset.s;
      only=(s==='ALL'||only===s)?null:s;
      document.querySelectorAll('.rsec').forEach(function(x){{
        x.classList.toggle('on', only===null ? x.dataset.s==='ALL' : x.dataset.s===only);}});
      if(drawn) draw();
    }};
  }});
}})();
</script>'''
