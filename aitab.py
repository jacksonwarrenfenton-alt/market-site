"""AI desk: a ticker lookup across every dataset, and a chart builder.

Two jobs, deliberately separated into sub-tabs so neither clutters the other.

TICKER DESK answers "what does this board say about X" by querying the
pre-joined index instead of making you read four panels and do the join
yourself. It is instant and offline: the index ships with the page. Claude is
optional on top, for the synthesis a table cannot give.

CHART BUILDER is the reason the source library exists. You describe a chart in
words, or drop in a CSV, and it renders. Be straight about the boundary: a
published artifact cannot fetch the open internet -- the sandbox blocks every
host -- so "pull the data" means Claude supplies numbers it knows, which are
approximate and dated. Anything that must be exact comes from the embedded
board data or a file you upload.
"""
import json, os, html

D = os.path.expanduser("~/pos")


def panel(desk, lib=None, regime_html="", global_html=""):
    idx = json.dumps(desk, separators=(",", ":"))
    libjson = json.dumps(lib or {"dates": [], "meta": {}, "series": {}},
                         separators=(",", ":"))
    nser = len((lib or {}).get("series", {}))
    nwk = len((lib or {}).get("dates", []))
    c = desk.get("counts", {})
    regime_tab = ""
    if regime_html:
        regime_tab = '<button class="aitab" data-p="p-regime">Regime &amp; positioning</button>'
    global_tab = ""
    if global_html:
        global_tab = '<button class="aitab" data-p="p-gl">Global &amp; liquidity</button>'
    html_head = f'''<div class="aiwrap">
  <div class="aihead">
    <div>
      <h2 class="aih2">AI desk</h2>
      <p class="grpnote aisub">One ticker, every dataset this board holds &mdash;
      COT positioning, ETF flows, short interest and subsector strength, joined
      and flagged. Then a chart builder for everything the board does not hold.</p>
    </div>
    <div class="aitabs">
      <button class="aitab on" data-p="p-desk">Ticker desk</button>
      <button class="aitab" data-p="p-chart">Chart builder</button>
      {regime_tab}
      {global_tab}
    </div>
  </div>

  <section id="p-desk" class="aipane">
    <div class="askbar">
      <input id="tq" type="text" placeholder="Ticker &mdash; try GLD, NVDA, SOXL, PLTR"
             autocomplete="off" spellcheck="false">
      <button id="tgo" class="btn">Look up</button>
      <span class="dim aiidx">{c.get('tickers',0):,} tickers indexed
        &middot; {c.get('cot',0)} futures &middot; {c.get('etf',0)} ETFs
        &middot; {c.get('si',0)} short-interest names</span>
    </div>
    <div id="tout" class="deskout"></div>
    <div id="tai" class="aibox" hidden></div>
  </section>

  <section id="p-chart" class="aipane" hidden>
    <p class="grpnote cbnote">Charts are drawn from <b>{nser} series &times; {nwk}
    weeks embedded in this page</b> &mdash; prices, COT percentiles, breadth,
    basket flows and short-interest tilt. A published page cannot reach the
    internet, so nothing here is recalled from memory: Claude only chooses which
    series to plot and how to transform them, and every number comes from the
    data below or from a file you load.</p>
    <div class="askbar col">
      <textarea id="cq" rows="2" placeholder="Describe the chart &mdash; e.g. &quot;gold vs the dollar since 2015, both indexed to 100&quot; or &quot;EEM/SPY ratio against DXY&quot; or &quot;copper miners vs 10-year Treasuries&quot;"></textarea>
      <div class="askrow">
        <button id="cgo" class="btn">Build chart</button>
        <button id="cman" class="btn ghost">Pick series manually</button>
        <label class="upl">Load a CSV
          <input id="cfile" type="file" accept=".csv,.tsv,.txt" hidden></label>
        <span class="dim" id="cfname">no file &mdash; using the embedded library</span>
      </div>
      <div id="cpick" class="cpick" hidden>
        <input id="cs" type="text" placeholder="Filter series&hellip;" autocomplete="off">
        <div id="cslist" class="cslist"></div>
        <div class="askrow">
          <label class="dim">Transform
            <select id="ctr">
              <option value="raw">as reported</option>
              <option value="idx">indexed to 100</option>
              <option value="ratio">ratio (first &divide; second)</option>
              <option value="pct">% change from start</option>
              <option value="z">z-score</option>
            </select></label>
          <label class="dim">From
            <select id="cyr"></select></label>
          <button id="cdraw" class="btn">Draw</button>
        </div>
      </div>
    </div>
    <div id="cout" class="chartout"></div>
  </section>

  <section id="p-regime" class="aipane" hidden>
    {regime_html}
  </section>

  <section id="p-gl" class="aipane" hidden>
    {global_html}
  </section>
</div>
<script id="deskdata" type="application/json">{idx}</script>
<script id="libdata" type="application/json">{libjson}</script>'''
    js = r"""<script>
(function(){
var DESK=JSON.parse(document.getElementById('deskdata').textContent);
var IDX=DESK.idx||{}, GRP=DESK.groups||{};
var LEG={med:'Median RS',ew:'Equal-wt RS',short:'Short horizon',long:'Long horizon',
 thrust:'Thrust',bread:'Breadth',flow:'ETF flow',si:'Short int.',tv:'TradingView'};

document.querySelectorAll('.aitab').forEach(function(b){
  b.onclick=function(){
    document.querySelectorAll('.aitab').forEach(function(x){x.classList.remove('on');});
    b.classList.add('on');
    document.querySelectorAll('.aipane').forEach(function(p){p.hidden=true;});
    document.getElementById(b.dataset.p).hidden=false;
  };
});

function esc(s){return String(s).replace(/[&<>"]/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function num(v,d){return (v===null||v===undefined)?'&ndash;':(+v).toFixed(d===undefined?2:d);}
function money(v){if(v===null||v===undefined)return '&ndash;';
  var a=Math.abs(v); if(a>=1e9)return (v/1e9).toFixed(2)+'B';
  if(a>=1e6)return (v/1e6).toFixed(1)+'M'; return (+v).toFixed(0);}
function tone(v,hi,lo){if(v===null||v===undefined)return '';
  return v>=hi?'up':(v<=lo?'dn':'');}

function card(title,rows,note){
  var body=rows.map(function(r){
    return '<div class="kv"><span>'+r[0]+'</span><b class="'+(r[2]||'')+'">'+r[1]+'</b></div>';
  }).join('');
  return '<div class="dcard"><h4>'+title+'</h4>'+body+
    (note?'<p class="dnote">'+note+'</p>':'')+'</div>';
}

function render(t){
  var e=IDX[t], out=document.getElementById('tout');
  document.getElementById('tai').hidden=true;
  if(!e){
    out.innerHTML='<div class="empty"><b>'+esc(t)+'</b> is not on this board. '+
      'It carries the 253-group roster, 367 flow ETFs, the curated futures '+
      'universe and the short-interest panel &mdash; a name outside all four has '+
      'no reading here rather than a blank one.</div>'; return;
  }
  var cards=[];
  if(e.cot){
    var c=e.cot;
    cards.push(card('COT positioning &middot; '+esc(c.name),[
      ['Large spec &middot; 52w %ile', num(c.ls,0), tone(c.ls,85,15)],
      ['Small spec', num(c.ss,0), tone(c.ss,85,15)],
      ['Commercial', num(c.comm,0), tone(c.comm,85,15)],
      ['Open interest', num(c.oi,0)+' <span class="dim">context only</span>','dim']
    ],'As of '+c.asof+'. Percentile of the last 52 weeks. Open interest is shown '+
      'but no longer ranks &mdash; it failed at every horizon tested.'));
  }
  if(e.etf){
    var f=e.etf;
    cards.push(card('ETF flow &middot; '+esc(f.basket),[
      ['1-month flow', money(f.flow_1m)],
      ['as % of AUM', (f.pct_1m===undefined?'&ndash;':num(f.pct_1m)+'%'), tone(f.pct_1m,1,-1)],
      ['z-score', num(f.z_1m), tone(f.z_1m,1.5,-1.5)],
      ['direction', f.inverse?'inverse &mdash; sign flipped':'long']
    ],f.asof?('Week ending '+f.asof+'. Basket-level: this is the flow into the '+
      'group this fund sits in, not the fund alone.'):''));
  }
  if(e.si){
    var s=e.si;
    cards.push(card('Short interest',[
      ['Shares short', money(s.si)],
      ['Days to cover', num(s.dtc)],
      ['Change', (s.pct_chg===null?'&ndash;':num(s.pct_chg)+'%'), tone(-s.pct_chg,0,-0)],
      ['Change z', num(s.chg_z), tone(-s.chg_z,1,-1)]
    ],'Settlement '+s.settle+'. Negative change z means covering.'));
  }
  (e.groups||[]).forEach(function(g){
    var m=GRP[g]; if(!m)return;
    var legs=Object.keys(LEG).map(function(k){
      var v=m.legs?m.legs[k]:null;
      return '<span class="lg '+(v===null||v===undefined?'nc':(v>=70?'hi':(v<=30?'lo':'mid')))+
        '" title="'+LEG[k]+'"><i>'+LEG[k]+'</i>'+(v===null||v===undefined?'&ndash;':v)+'</span>';
    }).join('');
    cards.push('<div class="dcard wide"><h4>Group &middot; '+esc(g)+'</h4>'+
      '<div class="kv"><span>Rank</span><b>'+m.rank+' of 253</b></div>'+
      '<div class="kv"><span>RS rank / EW rank</span><b>'+m.rs_rank+' / '+m.ew_rank+'</b></div>'+
      '<div class="kv"><span>Confluence</span><b class="'+
        (m.conf_dir>0?'up':(m.conf_dir<0?'dn':''))+'">'+
        (m.conf_n||0)+' of '+(m.conf_cov||0)+' legs '+
        (m.conf_dir>0?'up':(m.conf_dir<0?'down':'split'))+'</b></div>'+
      '<div class="kv"><span>Spread</span><b class="'+(m.spread>=70?'warnx':'')+'">'+
        num(m.spread,0)+'</b></div>'+
      '<div class="legs2">'+legs+'</div>'+
      (m.spread>=70?'<p class="dnote">Wide spread &mdash; this rank is being carried '+
        'by one or two legs, not broad agreement.</p>':'')+'</div>');
  });
  var flags=(e.flags||[]).map(function(f){
    return '<li class="fl fl-'+f[0]+'"><b>'+f[0]+'</b>'+f[1]+'</li>';}).join('');
  out.innerHTML=(flags?'<ul class="flags">'+flags+'</ul>':
      '<ul class="flags"><li class="fl fl-ok"><b>clear</b>nothing on this name is at an extreme worth flagging</li></ul>')
    +'<div class="dgrid">'+cards.join('')+'</div>'
    +'<div class="askrow"><button id="synth" class="btn ghost">Ask Claude to read this</button>'
    +'<span class="dim">a synthesis across the datasets above</span></div>';
  var sb=document.getElementById('synth');
  if(sb) sb.onclick=function(){synth(t,e);};
}

async function synth(t,e){
  var box=document.getElementById('tai');
  box.hidden=false; box.innerHTML='<div class="dim">Thinking&hellip;</div>';
  var s=null; try{s=await window.claude?.use?.('sample');}catch(_){}
  if(!s){box.innerHTML='<div class="dim">Claude is not available in this view. '+
    'The tables above are complete without it.</div>'; return;}
  var gm=(e.groups||[]).map(function(g){return {group:g,meta:GRP[g]||null};});
  try{
    var r=await s('You are reading a market-positioning board for an experienced '+
      'swing trader. Here is every dataset it holds on '+t+', as JSON:\\n\\n'+
      JSON.stringify({ticker:t,cot:e.cot||null,etf:e.etf||null,si:e.si||null,
        groups:gm,flags:e.flags||[]})+
      '\\n\\nIn under 130 words: what is the positioning actually saying, where do '+
      'the datasets disagree, and what would falsify the read. Percentiles are '+
      'against 52 weeks. Do not invent data that is not here, do not give a '+
      'recommendation, and say plainly if the coverage is too thin to conclude '+
      'anything.',
      {onText:function(o){box.innerHTML='<p>'+esc(o.text)+'</p>';}});
    box.innerHTML='<p>'+esc(r.text)+'</p><p class="dnote">Claude&rsquo;s reading of '+
      'the tables above &mdash; not a recommendation, and no better than the data.</p>';
  }catch(err){
    box.innerHTML='<div class="dim">Could not reach Claude ('+esc(err.code||'error')+
      '). The tables above stand on their own.</div>';
  }
}

document.getElementById('tgo').onclick=function(){
  render((document.getElementById('tq').value||'').trim().toUpperCase());};
document.getElementById('tq').addEventListener('keydown',function(ev){
  if(ev.key==='Enter')document.getElementById('tgo').click();});

/* ---------------- chart builder ---------------- */
var LIB=JSON.parse(document.getElementById('libdata').textContent);
var LD=LIB.dates||[], LM=LIB.meta||{}, LS=LIB.series||{};
var SEL=[], UP=null;

document.querySelector('.upl').onclick=function(){document.getElementById('cfile').click();};
document.getElementById('cfile').onchange=function(ev){
  var f=ev.target.files[0]; if(!f)return;
  var rd=new FileReader();
  rd.onload=function(){UP={name:f.name,text:String(rd.result).slice(0,120000)};
    document.getElementById('cfname').textContent=f.name+' loaded — charts will use it';};
  rd.readAsText(f);
};

/* ---- transforms: applied here, never by Claude ---- */
function firstFinite(a,from){for(var i=from;i<a.length;i++){if(a[i]!=null&&isFinite(a[i]))return i;}return -1;}
function xform(pts,mode,from){
  var out=pts.slice();
  if(mode==='raw')return out;
  var i0=firstFinite(out,from);
  if(i0<0)return out;
  var base=out[i0];
  if(mode==='idx')return out.map(function(v){return (v==null||!isFinite(v)||!base)?null:100*v/base;});
  if(mode==='pct') return out.map(function(v){return (v==null||!isFinite(v)||!base)?null:100*(v/base-1);});
  if(mode==='z'){
    var f=out.slice(from).filter(function(v){return v!=null&&isFinite(v);});
    if(f.length<8)return out;
    var m=f.reduce(function(a,b){return a+b;},0)/f.length;
    var sd=Math.sqrt(f.reduce(function(a,b){return a+(b-m)*(b-m);},0)/f.length)||1;
    return out.map(function(v){return (v==null||!isFinite(v))?null:(v-m)/sd;});
  }
  return out;
}
function startIdx(year){
  if(!year)return 0;
  for(var i=0;i<LD.length;i++){if(LD[i]>=year+'-01-01')return i;}
  return 0;
}

function drawFromKeys(keys,mode,year,title,note){
  var out=document.getElementById('cout');
  keys=(keys||[]).filter(function(k){return LS[k];});
  if(!keys.length){out.innerHTML='<div class="empty">None of those series are in the '+
    'library. Use <b>Pick series manually</b> to see what is available.</div>';return;}
  var from=startIdx(year);
  var labels=LD.slice(from);
  var series;
  if(mode==='ratio'&&keys.length>=2){
    var a=LS[keys[0]].slice(from), b=LS[keys[1]].slice(from);
    var r=a.map(function(v,i){var w=b[i];
      return (v==null||w==null||!isFinite(v)||!isFinite(w)||!w)?null:v/w;});
    series=[{name:(LM[keys[0]].label)+' / '+(LM[keys[1]].label),axis:1,points:r}];
    keys.slice(2).forEach(function(k,i){
      series.push({name:LM[k].label,axis:2,points:LS[k].slice(from)});});
  } else {
    series=keys.map(function(k,i){
      return {name:LM[k].label,axis:(mode==='raw'&&i>0)?2:1,
              points:xform(LS[k].slice(from),mode,0)};});
  }
  drawSpec({title:title||series.map(function(s){return s.name;}).join('  ·  '),
            labels:labels,series:series,
            note:note,
            source:'Embedded library — '+keys.map(function(k){return k;}).join(', ')+
                   ' · weekly, week-ending Friday'});
}

function drawSpec(spec){
  var out=document.getElementById('cout');
  var S=(spec.series||[]).filter(function(s){return s&&s.points&&s.points.length;});
  if(!S.length){out.innerHTML='<div class="empty">No series came back.</div>';return;}
  var L=spec.labels||S[0].points.map(function(_,i){return i;});
  var W=1180,H=340,PL=60,PR=60,PT=18,PB=30,iw=W-PL-PR,ih=H-PT-PB;
  var N=Math.max.apply(null,S.map(function(s){return s.points.length;}));
  var axes=[[],[]]; S.forEach(function(s){axes[s.axis===2?1:0].push(s);});
  var rng=axes.map(function(g){
    var v=[].concat.apply([],g.map(function(s){
      return s.points.filter(function(x){return x!=null&&isFinite(x);});}));
    if(!v.length)return null;
    var mn=Math.min.apply(null,v),mx=Math.max.apply(null,v);
    if(mx===mn)mx=mn+1; var pad=(mx-mn)*0.08; return [mn-pad,mx+pad];});
  var COL=['var(--cool)','var(--warn)','var(--vio)','var(--good)','var(--crit)'];
  var X=function(i){return PL+iw*(N<2?0.5:i/(N-1));};
  function Y(v,a){var r=rng[a];return PT+ih-ih*(v-r[0])/((r[1]-r[0])||1);}
  function fmt(v){var a=Math.abs(v);
    return a>=1000?Math.round(v).toLocaleString():(a>=10?v.toFixed(1):v.toFixed(2));}
  var g='',paths='',leg='';
  for(var k=0;k<=4;k++){var yy=PT+ih*k/4;
    g+='<line x1="'+PL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+yy.toFixed(1)+'" stroke="var(--grid)"/>';
    if(rng[0])g+='<text x="'+(PL-8)+'" y="'+(yy+3.5).toFixed(1)+'" text-anchor="end" class="ax">'+
      fmt(rng[0][1]-(rng[0][1]-rng[0][0])*k/4)+'</text>';
    if(rng[1])g+='<text x="'+(W-PR+8)+'" y="'+(yy+3.5).toFixed(1)+'" class="ax sp">'+
      fmt(rng[1][1]-(rng[1][1]-rng[1][0])*k/4)+'</text>';}
  S.forEach(function(s,si){
    var a=s.axis===2?1:0,d='',pen=false;
    if(!rng[a])return;
    s.points.forEach(function(v,i){if(v==null||!isFinite(v)){pen=false;return;}
      d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v,a).toFixed(1)+' ';pen=true;});
    paths+='<path d="'+d+'" fill="none" stroke="'+COL[si%5]+'" stroke-width="1.7"/>';
    leg+='<span class="k" style="background:'+COL[si%5]+'"></span>'+esc(s.name)+
      (s.axis===2?' <i class="dim">(right)</i>':'')+' ';});
  var ticks='',step=Math.max(1,Math.floor(N/8));
  for(var i=0;i<N;i+=step)
    ticks+='<text x="'+X(i).toFixed(1)+'" y="'+(H-9)+'" text-anchor="middle" class="ax">'+
      esc(String(L[i]===undefined?i:L[i])).slice(0,7)+'</text>';
  out.innerHTML='<h4 class="ctitle">'+esc(spec.title||'Chart')+'</h4>'+
    '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" class="sbsvg">'+
    g+paths+ticks+'</svg><div class="sblg">'+leg+'</div>'+
    (spec.note?'<p class="dnote">'+esc(spec.note)+'</p>':'')+
    (spec.source?'<p class="dnote"><b>Source:</b> '+esc(spec.source)+'</p>':'');
}

/* ---- manual picker ---- */
var yrSel=document.getElementById('cyr');
for(var y=2010;y<=2026;y++){var o=document.createElement('option');
  o.value=y;o.textContent=y;if(y===2018)o.selected=true;yrSel.appendChild(o);}
function paintList(f){
  f=(f||'').toLowerCase();
  var box=document.getElementById('cslist'),h='',grp={};
  Object.keys(LM).forEach(function(k){
    var m=LM[k];
    if(f&&(m.label+' '+k).toLowerCase().indexOf(f)<0)return;
    (grp[m.group]=grp[m.group]||[]).push(k);});
  Object.keys(grp).forEach(function(gn){
    h+='<div class="csg"><span class="sbglab">'+esc(gn)+'</span>'+
      grp[gn].slice(0,90).map(function(k){
        return '<button class="sbchip'+(SEL.indexOf(k)>=0?' on':'')+'" data-k="'+
          esc(k)+'">'+esc(LM[k].label)+'</button>';}).join('')+'</div>';});
  box.innerHTML=h||'<span class="dim">nothing matches</span>';
  box.querySelectorAll('.sbchip').forEach(function(b){
    b.onclick=function(){var k=b.dataset.k,i=SEL.indexOf(k);
      if(i>=0)SEL.splice(i,1); else {if(SEL.length>=5)SEL.shift(); SEL.push(k);}
      paintList(document.getElementById('cs').value);};});
}
document.getElementById('cman').onclick=function(){
  var p=document.getElementById('cpick'); p.hidden=!p.hidden;
  if(!p.hidden)paintList('');};
document.getElementById('cs').oninput=function(){paintList(this.value);};
document.getElementById('cdraw').onclick=function(){
  drawFromKeys(SEL,document.getElementById('ctr').value,yrSel.value,null,
    'Drawn straight from the embedded library — no model involved.');};

/* ---- natural language: Claude plans, the page draws ---- */
document.getElementById('cgo').onclick=async function(){
  var q=(document.getElementById('cq').value||'').trim();
  var out=document.getElementById('cout');
  if(!q){out.innerHTML='<div class="empty">Describe the chart first.</div>';return;}
  out.innerHTML='<div class="dim">Choosing series&hellip;</div>';
  var s=null; try{s=await window.claude?.use?.('sample');}catch(_){}
  if(!s){out.innerHTML='<div class="empty">Claude is not available in this view, so '+
    'the plain-language box is off. <b>Pick series manually</b> still works &mdash; '+
    'the data is in the page.</div>';return;}
  if(UP){
    try{
      var spec=await s.json('Return JSON {"title":str,"labels":[str],"series":'+
        '[{"name":str,"axis":1|2,"points":[number|null]}],"note":str}. Use ONLY the '+
        'CSV below, parsed exactly; never substitute recalled figures. Request: '+q+
        '\n\nCSV ('+UP.name+'):\n'+UP.text.slice(0,60000),{modelTier:'complex'});
      spec.source='Your file: '+UP.name;
      drawSpec(spec);
    }catch(err){out.innerHTML='<div class="empty">Could not read that file ('+
      esc(err.code||'error')+').</div>';}
    return;
  }
  var cat=Object.keys(LM).map(function(k){return k+' = '+LM[k].label;}).join('\n');
  try{
    var plan=await s.json('You are choosing series from a fixed catalogue for a '+
      'chart. Return ONLY JSON: {"keys":[key,...],"mode":"raw|idx|ratio|pct|z",'+
      '"year":int,"title":str,"note":str}. Rules: every key MUST appear verbatim '+
      'in the catalogue; at most 4 keys; "ratio" divides the first key by the '+
      'second; "idx" rebases each to 100 at the start; use "idx" whenever series '+
      'have different units; year is the first year to show (2010-2026). In "note", '+
      'say in one sentence what the chart is testing. Do NOT return data points — '+
      'the page holds the data.\n\nCATALOGUE:\n'+cat+'\n\nREQUEST: '+q,
      {modelTier:'complex'});
    drawFromKeys(plan.keys,plan.mode||'idx',plan.year,plan.title,plan.note);
  }catch(err){
    out.innerHTML='<div class="empty">Could not build that ('+esc(err.code||'error')+
      '). Try naming the assets directly, or use <b>Pick series manually</b>.</div>';}
};

/* open on a real chart, not an empty frame */
drawFromKeys(['GLD','UUP'],'idx',2018,'Gold vs the dollar, indexed to 100',
  'The classic inverse: dollar strength is the headwind gold has to overcome.');
render('GLD');
})();
</script>"""
    return html_head + js

