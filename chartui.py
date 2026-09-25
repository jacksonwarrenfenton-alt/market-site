"""Client-side chart renderer -- the JS that draws every chart on the site.

The Python side (charts.build_specs / flowcharts.build_specs / marketsite.pz_host)
emits a compact spec per chart; everything below turns a spec plus a window
[i0,i1] into SVG.

Three controls sit on every chart, COT and breadth alike:

  MA      5/10/20/50/200 bar moving averages, toggled per chart, drawn on every
          visible pane. "Bar" is whatever that chart's row is -- a week on the
          COT panes, a session on the Stockbee and McClellan panes -- and the
          unit is printed next to the buttons so MA50 is never ambiguous.
  band    the significance band. AUTO is whatever the Python side shipped
          (charts.adaptive_band for COT/flow; nothing for series that were never
          calibrated, which then get a plain rolling 5th/95th). Dragging the
          slider overrides it with a flat p-th/(100-p)-th band recomputed in the
          browser; 0 removes it. Dots AND the price-pane arrows both read the
          band in force, so markers move with the slider.
  SPY     a reference pane over the identical window, carrying the same arrows,
          so an extreme can be read against what the index did next.

Spec shape:
  {t:[dates], spy:[...], unit:'weeks'|'sessions', bw:52,
   panes:[{k, lab, fmt:'n'|'p', c, v, ov:[{v,c,l}], lo, hi, md,
           limNow, limMin, limMax, bw, band, area, stack, ref}]}
"""

CHART_JS = r"""
(function(){
const NS='http://www.w3.org/2000/svg';
const W=780, PADL=62, PADR=14, PADT=18, PADB=26;
const MUT='#898781', GRID='#2c2c2a', BAND='#383835';
const WARM='#e66767', COOL='#3987e5';
const CLIP_SIGMA=5.0;
const MA_DEF=[[5,'#e6c767'],[10,'#9085e9'],[20,'#5ec8c8'],[50,'#3987e5'],[200,'#e66767']];

function el(t,a){const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;}
function fmtN(v){const a=Math.abs(v);
  if(a>=1e9)return (v/1e9).toFixed(1)+'B';
  if(a>=1e6)return (v/1e6).toFixed(1)+'M';
  if(a>=1e3)return (v/1e3).toFixed(0)+'k';
  return (Math.round(v*1e4)/1e4).toString();}
function fmtP(v){return v.toFixed(0)+'%';}

function ticks(lo,hi,n){
  if(!(hi>lo))return[lo];
  const raw=(hi-lo)/n, mag=Math.pow(10,Math.floor(Math.log10(Math.abs(raw))));
  let best=null,bd=Infinity;
  for(const m of [1,2,2.5,5,10]){const s=m*mag,d=Math.abs(s-raw);if(d<bd){bd=d;best=s;}}
  const t0=Math.ceil(lo/best)*best, out=[];
  for(let t=t0;t<=hi+1e-9;t+=best)out.push(t);
  return out;}

function domain(arrs,floorZero){
  let v=[];for(const a of arrs){if(!a)continue;for(const x of a)if(x!=null&&isFinite(x))v.push(x);}
  if(!v.length)return[0,1,0];
  v.sort((a,b)=>a-b);
  const q=p=>v[Math.min(v.length-1,Math.max(0,Math.round(p/100*(v.length-1))))];
  const loF=v[0], hiF=v[v.length-1], med=q(50);
  const dev=v.map(x=>Math.abs(x-med)).sort((a,b)=>a-b);
  let mad=dev[Math.floor(dev.length/2)]*1.4826;
  if(!(mad>0)){const mu=v.reduce((a,b)=>a+b,0)/v.length;
    mad=Math.sqrt(v.reduce((a,b)=>a+(b-mu)*(b-mu),0)/v.length)||Math.abs(med)*0.1||1;}
  let lo=Math.max(Math.min(med-CLIP_SIGMA*mad,q(1)),loF);
  let hi=Math.min(Math.max(med+CLIP_SIGMA*mad,q(99)),hiF);
  if(!(hi>lo)){lo=loF;hi=hiF;}
  let nclip=0;for(const x of v)if(x<lo-1e-9||x>hi+1e-9)nclip++;
  const pad=(hi-lo)*0.12||Math.abs(hi)*0.1||1;
  lo-=pad;hi+=pad;
  if(floorZero){lo=Math.min(lo,0);hi=Math.max(hi,0);}
  return[lo,hi,nclip];}

// An INDICATOR pane is one that carries its own significance band, i.e. one the
// dots and the price-pane arrows are allowed to come from. Price, cumulative
// flow and any filled reference pane are explicitly excluded -- they are context.
function isIndicator(p){
  // `band` marks a pane that carries no server band but can compute one in the
  // browser (the breadth / Stockbee / short-interest series). Without it those
  // panes never get dots and never feed the arrows.
  return !!(p && (p.lo&&p.hi || p.band) && p.k!=='price' && p.k!=='spy'
            && p.k!=='cum' && !p.area && !p.ref);}

// Trailing mean over w VALID points. Missing values are skipped rather than
// treated as zero -- a gap in a weekly COT series would otherwise drag the
// average toward nothing.
function movAvg(v,w){
  const out=new Array(v.length).fill(null);
  const buf=[]; let s=0;
  for(let i=0;i<v.length;i++){
    const x=v[i];
    if(x!=null&&isFinite(x)){buf.push(x);s+=x;if(buf.length>w)s-=buf.shift();}
    if(buf.length===w)out[i]=s/w;}
  return out;}

function pctl(sorted,p){
  if(!sorted.length)return null;
  const i=(p/100)*(sorted.length-1), a=Math.floor(i), b=Math.ceil(i);
  return sorted[a]+(sorted[b]-sorted[a])*(i-a);}

// Rolling p-th/(100-p)-th band on the series' own trailing window -- the same
// construction the Python adaptive band uses, so a dot means the identical thing
// whether the band came from the server or from the slider.
function rollBand(v,win,p){
  const n=v.length, lo=new Array(n).fill(null), hi=new Array(n).fill(null);
  const minp=Math.max(12,Math.round(win*0.75));
  for(let i=0;i<n;i++){
    const w=[];
    for(let j=Math.max(0,i-win+1);j<=i;j++){const x=v[j];if(x!=null&&isFinite(x))w.push(x);}
    if(w.length<minp)continue;
    w.sort((a,b)=>a-b);
    lo[i]=pctl(w,p);hi[i]=pctl(w,100-p);}
  return {lo:lo,hi:hi};}

// The band actually in force for a pane given the host's slider.
//   null -> AUTO: the server's band if the pane shipped one, else a default
//           5/95 client band for any pane that asked for one (band:true).
//   0    -> OFF.
//   else -> client band at that percentile, cached per (pane,pct).
// Returns {lo,hi,auto,p} or null. Everything downstream -- dots, arrows, the
// header label -- reads THIS, so there is exactly one definition of "extreme"
// on screen at a time.
function bandFor(pane,bandPct){
  if(!pane||pane.stack||!pane.v)return null;
  if(bandPct===0)return null;
  if(bandPct==null){
    if(pane.lo&&pane.hi)return {lo:pane.lo,hi:pane.hi,auto:true,
      p:pane.limNow,pmin:pane.limMin,pmax:pane.limMax};
    if(!pane.band)return null;
    pane._bc=pane._bc||{};
    if(!pane._bc[5])pane._bc[5]=rollBand(pane.v,pane.bw||52,5);
    return {lo:pane._bc[5].lo,hi:pane._bc[5].hi,auto:true,p:5,pmin:5,pmax:5};}
  pane._bc=pane._bc||{};
  if(!pane._bc[bandPct])pane._bc[bandPct]=rollBand(pane.v,pane.bw||52,bandPct);
  return {lo:pane._bc[bandPct].lo,hi:pane._bc[bandPct].hi,auto:false,p:bandPct};}

function ord(n){n=Math.round(n);const a=n%100,b=n%10;
  if(a>=11&&a<=13)return n+'th';
  return n+({1:'st',2:'nd',3:'rd'}[b]||'th');}

function rollMedian(v, win, minp){
  if(!v)return null;
  const out=new Array(v.length).fill(null);
  for(let i=0;i<v.length;i++){
    const w=[];
    for(let j=Math.max(0,i-win+1);j<=i;j++){const x=v[j];if(x!=null&&isFinite(x))w.push(x);}
    if(w.length<minp)continue;
    w.sort((a,b)=>a-b);
    const m=w.length>>1;
    out[i]= w.length%2 ? w[m] : (w[m-1]+w[m])/2;}
  return out;}

function paneMedian(pane){
  if(pane.md)return pane.md;
  if(pane._md!==undefined)return pane._md;
  if(!(pane.lo&&pane.hi)){pane._md=null;return null;}
  // The flow pane's band is mu +/- k*sd -- SYMMETRIC -- so its centre line is the
  // exact midpoint of the two edges already on hand, not a median. Rolling a
  // median there would draw a different line than the band is built around.
  if(pane.bk!=null){
    pane._md = pane.lo.map((x,i)=>{const y=pane.hi[i];
      return (x==null||y==null||!isFinite(x)||!isFinite(y))?null:(x+y)/2;});
    return pane._md;}
  pane._md = rollMedian(pane.v,52,40);
  return pane._md;}

function drawPane(pane, t, i0, i1, height, activeSrc, spec, opt){
  opt=opt||{};
  const mas=opt.mas||[], bandPct=(opt.bandPct===undefined?null:opt.bandPct);
  const n=i1-i0+1;
  const svg=el('svg',{viewBox:`0 0 ${W} ${height}`,width:'100%',
    style:'display:block;font:10px ui-sans-serif,sans-serif'});
  const top=PADT, bot=height-PADB;
  const X=i=>PADL+(n<2?0:(i/(n-1))*(W-PADL-PADR));
  const cut=a=>a?a.slice(i0,i1+1):null;
  // The band in force, not the shipped one: with the slider off AUTO these are
  // the recomputed edges, and the dots below test against exactly what is drawn.
  const bnd=bandFor(pane,bandPct);
  const v=cut(pane.v), lo=cut(bnd&&bnd.lo), hi=cut(bnd&&bnd.hi);
  const md=cut((bnd&&bnd.auto)?paneMedian(pane):null);
  const ovs=(pane.ov||[]).map(o=>({v:cut(o.v),c:o.c,l:o.l}));
  // MA overlays, computed on this pane's own series over its FULL history and
  // then windowed, so the value at the left edge is not restarted by the zoom.
  if(pane.v){
    pane._ma=pane._ma||{};
    for(const md2 of MA_DEF){
      const w=md2[0];
      if(mas.indexOf(w)<0)continue;
      if(!pane._ma[w])pane._ma[w]=movAvg(pane.v,w);
      ovs.push({v:cut(pane._ma[w]),c:md2[1],l:'MA'+w});}}
  const stack=pane.stack?(function(){
    const ls=cut(pane.stack.ls), ss=cut(pane.stack.ss);
    const cm=pane.stack.cm?cut(pane.stack.cm):ls.map((x,i)=>-((x||0)+(ss[i]||0)));
    return {ls:ls,ss:ss,cm:cm};})():null;

  let dm;
  if(stack){
    let m=0;for(let i=0;i<n;i++){
      const a=Math.abs((stack.ls[i]||0)+(stack.ss[i]||0)), b=Math.abs(stack.cm[i]||0);
      m=Math.max(m,a,b);}
    dm=[-m*1.14,m*1.14,0];
  } else {
    dm=domain([v,lo,hi,md].concat(ovs.map(o=>o.v)), !!pane.area);
  }
  const [dlo,dhi,nclip]=dm;
  const Y=x=>{const c=Math.min(Math.max(x,dlo),dhi);
    return bot-(c-dlo)/((dhi-dlo)||1)*(bot-top);};

  for(const tk of ticks(dlo,dhi,3)){
    const y=Y(tk);
    svg.appendChild(el('line',{x1:PADL,y1:y.toFixed(1),x2:W-PADR,y2:y.toFixed(1),stroke:GRID}));
    const tx=el('text',{x:PADL-6,y:(y+3).toFixed(1),fill:MUT,'text-anchor':'end'});
    tx.textContent=pane.fmt==='p'?fmtP(tk):fmtN(tk);
    svg.appendChild(tx);}

  const path=a=>{let d='',started=false;
    for(let i=0;i<n;i++){const x=a[i];
      if(x==null||!isFinite(x)){continue;}
      d+=(started?' L':'M')+X(i).toFixed(1)+','+Y(x).toFixed(1);started=true;}
    return d;};

  if(stack){
    const zeroY=Y(0);
    const areaP=(base,tops)=>{let d='';
      for(let i=0;i<n;i++)d+=(i?' L':'M')+X(i).toFixed(1)+','+Y(tops[i]||0).toFixed(1);
      for(let i=n-1;i>=0;i--)d+=' L'+X(i).toFixed(1)+','+Y(base[i]||0).toFixed(1);
      return d+' Z';};
    const z=new Array(n).fill(0);
    const lsv=stack.ls.map(x=>x||0), ssv=stack.ss.map(x=>x||0), cmv=stack.cm.map(x=>x||0);
    const lsss=lsv.map((x,i)=>x+ssv[i]);
    svg.appendChild(el('path',{d:areaP(z,lsv),fill:'#3987e5','fill-opacity':.55}));
    svg.appendChild(el('path',{d:areaP(lsv,lsss),fill:'#eb6834','fill-opacity':.55}));
    svg.appendChild(el('path',{d:areaP(z,cmv),fill:'#1baf7a','fill-opacity':.28}));
    svg.appendChild(el('path',{d:path(cmv),fill:'none',stroke:'#1baf7a','stroke-width':1.6}));
    svg.appendChild(el('line',{x1:PADL,y1:zeroY.toFixed(1),x2:W-PADR,y2:zeroY.toFixed(1),stroke:MUT}));
  } else {
    if(lo&&hi){
      let d='';
      for(let i=0;i<n;i++){const x=hi[i];if(x==null||!isFinite(x))continue;
        d+=(d?' L':'M')+X(i).toFixed(1)+','+Y(x).toFixed(1);}
      for(let i=n-1;i>=0;i--){const x=lo[i];if(x==null||!isFinite(x))continue;
        d+=' L'+X(i).toFixed(1)+','+Y(x).toFixed(1);}
      if(d)svg.appendChild(el('path',{d:d+' Z',fill:BAND,'fill-opacity':.6}));
      if(md)svg.appendChild(el('path',{d:path(md),fill:'none',stroke:MUT,
        'stroke-width':1,'stroke-dasharray':'3 3'}));}
    if(pane.area&&v){
      const zeroY=Y(0);let d=path(v);
      if(d){let last=null,first=null;
        for(let i=0;i<n;i++)if(v[i]!=null&&isFinite(v[i])){if(first===null)first=i;last=i;}
        d+=` L${X(last).toFixed(1)},${zeroY.toFixed(1)} L${X(first).toFixed(1)},${zeroY.toFixed(1)} Z`;
        const col=(v[last]>=0)?'#1baf7a':'#e66767';
        svg.appendChild(el('path',{d:d,fill:col,'fill-opacity':.2}));}
      svg.appendChild(el('line',{x1:PADL,y1:zeroY.toFixed(1),x2:W-PADR,y2:zeroY.toFixed(1),
        stroke:MUT,'stroke-dasharray':'4 3'}));}
    for(const o of ovs){const d=path(o.v);if(d)svg.appendChild(
      el('path',{d:d,fill:'none',stroke:o.c,'stroke-width':1.2,'stroke-opacity':.9}));}
    if(v){const col=pane.area?((v[n-1]>=0)?'#1baf7a':'#e66767'):pane.c;
      svg.appendChild(el('path',{d:path(v),fill:'none',stroke:col,
        'stroke-width':pane.area?2:1.9,'stroke-linejoin':'round'}));}
  }

  // dots: identical test to the band that is drawn, so a dot appears if and only
  // if the line is outside the shaded region. Indicator panes only.
  if(isIndicator(pane)&&v&&lo&&hi){
    for(let i=0;i<n;i++){
      if(v[i]==null||lo[i]==null||hi[i]==null)continue;
      if(!isFinite(v[i])||!isFinite(lo[i])||!isFinite(hi[i]))continue;
      if(v[i]>=hi[i])svg.appendChild(el('circle',{cx:X(i).toFixed(1),cy:Y(v[i]).toFixed(1),r:2.4,fill:WARM}));
      else if(v[i]<=lo[i])svg.appendChild(el('circle',{cx:X(i).toFixed(1),cy:Y(v[i]).toFixed(1),r:2.4,fill:COOL}));}}

  // PATCH D1: arrows are OPT-IN and SINGLE-SOURCED. Four indicator panes
  // projecting onto one price line put ~50 triangles on a 157-week chart, which
  // is the clutter jman asked to kill. spec.primary is set at open time from the
  // row's data-ctx, so the arrows answer "where was price when THIS cohort was
  // extreme" rather than smearing every cohort together.
  if((pane.k==='price'||pane.k==='spy')&&v&&spec&&(!activeSrc||activeSrc.has('arrows'))){
    for(const src of spec.panes){
      if(!isIndicator(src))continue;
      if(spec.primary && src.k!==spec.primary)continue;
      if(activeSrc&&!activeSrc.has(src.k))continue;
      // the SOURCE pane's band in force -- so dragging the slider moves the
      // arrows on price and SPY in lockstep with the dots that produced them
      const sb=bandFor(src,bandPct);
      if(!sb)continue;
      for(let i=0;i<n;i++){
        const g=i0+i, sv=src.v[g], sl=sb.lo[g], sh=sb.hi[g];
        if(sv==null||sl==null||sh==null)continue;
        if(!isFinite(sv)||!isFinite(sl)||!isFinite(sh))continue;
        const dir = sv>=sh ? 1 : (sv<=sl ? -1 : 0);
        if(!dir)continue;
        const x=v[i];if(x==null||!isFinite(x))continue;
        svg.appendChild(el('path',{
          d:`M${(X(i)-3.4).toFixed(1)},${(Y(x)-6.5).toFixed(1)} L${X(i).toFixed(1)},${(Y(x)-1.5).toFixed(1)} L${(X(i)+3.4).toFixed(1)},${(Y(x)-6.5).toFixed(1)} Z`,
          fill:dir>0?WARM:COOL,'fill-opacity':.95}));}}}

  // carets for points clipped out of the drawn domain -- never silently hidden
  if(nclip&&v){for(let i=0;i<n;i++){const x=v[i];if(x==null||!isFinite(x))continue;
    if(x>dhi)svg.appendChild(el('path',{d:`M${(X(i)-3).toFixed(1)},${(top+5).toFixed(1)} L${X(i).toFixed(1)},${top} L${(X(i)+3).toFixed(1)},${(top+5).toFixed(1)}`,fill:'none',stroke:'#e6c767','stroke-width':1.4}));
    else if(x<dlo)svg.appendChild(el('path',{d:`M${(X(i)-3).toFixed(1)},${(bot-5).toFixed(1)} L${X(i).toFixed(1)},${bot} L${(X(i)+3).toFixed(1)},${(bot-5).toFixed(1)}`,fill:'none',stroke:'#e6c767','stroke-width':1.4}));}}

  if(v){let last=null;for(let i=n-1;i>=0;i--)if(v[i]!=null&&isFinite(v[i])){last=i;break;}
    if(last!==null){
      const col=pane.area?((v[last]>=0)?'#1baf7a':'#e66767'):pane.c;
      svg.appendChild(el('circle',{cx:X(last).toFixed(1),cy:Y(v[last]).toFixed(1),r:3.5,
        fill:col,stroke:'#141413','stroke-width':2}));
      const tx=el('text',{x:(X(last)-8).toFixed(1),y:(Y(v[last])-9).toFixed(1),fill:col,
        'font-size':10.5,'font-weight':700,'text-anchor':'end'});
      tx.textContent=pane.fmt==='p'?v[last].toFixed(1)+'%':fmtN(v[last]);
      svg.appendChild(tx);}}

  let lab=pane.lab;
  if(bnd&&bnd.auto&&bnd.p!=null){
    lab+=`  -  band AUTO ${ord(bnd.p)}-${ord(100-bnd.p)}`;
    if(bnd.pmax-bnd.pmin>0.5)lab+=` (ranged ${Math.round(bnd.pmin)}-${Math.round(bnd.pmax)})`;}
  else if(bnd)lab+=`  -  band SET ${ord(bnd.p)}-${ord(100-bnd.p)}`;
  else if(isIndicator(pane))lab+=`  -  band off`;
  if(pane.k==='flow'&&pane.bk!=null)lab+=`  -  bands +/-${pane.bk.toFixed(2)} sigma, calibrated to this basket`;
  if(nclip)lab+=`  -  ${nclip} pt clipped (carets)`;
  if(pane.c&&!stack)svg.appendChild(el('rect',{x:PADL,y:4,width:8,height:8,rx:2,fill:pane.c}));
  const h=el('text',{x:PADL+(pane.c&&!stack?12:0),y:11,fill:MUT,'font-size':9.5});
  h.textContent=lab; svg.appendChild(h);
  let lx=PADL+300;
  for(const o of ovs){
    svg.appendChild(el('rect',{x:lx,y:5,width:9,height:2.5,fill:o.c}));
    const lt=el('text',{x:lx+12,y:11,fill:MUT,'font-size':9});lt.textContent=o.l;
    svg.appendChild(lt);lx+=42;}

  // x-axis: tick every MONTH boundary rather than three fixed points. t[] entries
  // are already "Mon YY", so a change of label IS a month change. Thin to at most
  // ~13 ticks so a decade-long window stays legible.
  const marks=[];
  for(let i=0;i<n;i++){ if(i===0 || t[i0+i]!==t[i0+i-1]) marks.push(i); }
  const step=Math.max(1, Math.ceil(marks.length/13));
  const keep=marks.filter((_,k)=>k%step===0);
  if(keep.length && keep[keep.length-1]!==n-1 && (n-1)-keep[keep.length-1] > step/2) keep.push(n-1);
  for(const i of keep){
    if(i<0||i>=n)continue;
    const anc=i===0?'start':(i>=n-2?'end':'middle');
    svg.appendChild(el('line',{x1:X(i).toFixed(1),y1:bot,x2:X(i).toFixed(1),y2:(bot+3).toFixed(1),
      stroke:MUT,'stroke-opacity':.6}));
    const tx=el('text',{x:X(i).toFixed(1),y:height-6,fill:MUT,'font-size':9,'text-anchor':anc});
    tx.textContent=t[i0+i]; svg.appendChild(tx);}

  // crosshair layer -- hidden until the pointer enters the chart body. PZ.render
  // wires one listener for the whole modal so every pane tracks the SAME bar,
  // which is the entire point of locking the panes to one time scale.
  const xh=el('g',{'class':'xh','pointer-events':'none',style:'display:none'});
  const vline=el('line',{y1:top,y2:bot,stroke:'#c3c2b7','stroke-width':.9,'stroke-dasharray':'3 3','stroke-opacity':.85});
  const hline2=el('line',{x1:PADL,x2:W-PADR,stroke:'#c3c2b7','stroke-width':.9,'stroke-dasharray':'3 3','stroke-opacity':.55});
  const dot=el('circle',{r:3,fill:'#fff',stroke:'#141413','stroke-width':1.5});
  const rbg=el('rect',{rx:2,fill:'#141413','fill-opacity':.92,stroke:'#383835'});
  const rtx=el('text',{fill:'#fff','font-size':10,'font-weight':700});
  xh.appendChild(vline); xh.appendChild(hline2); xh.appendChild(dot);
  xh.appendChild(rbg); xh.appendChild(rtx);
  svg.appendChild(xh);
  svg.__xh=function(i){
    if(i==null||i<0||i>=n||!v||v[i]==null||!isFinite(v[i])){xh.style.display='none';return;}
    const x=X(i), y=Y(v[i]);
    vline.setAttribute('x1',x.toFixed(1)); vline.setAttribute('x2',x.toFixed(1));
    hline2.setAttribute('y1',y.toFixed(1)); hline2.setAttribute('y2',y.toFixed(1));
    dot.setAttribute('cx',x.toFixed(1)); dot.setAttribute('cy',y.toFixed(1));
    const txt=(pane.fmt==='p'?v[i].toFixed(2)+'%':fmtN(v[i]));
    rtx.textContent=txt;
    const wpx=txt.length*6+10, left=x+8+wpx>W-PADR;
    const rx=left?x-8-wpx:x+8, ry=Math.max(top, Math.min(bot-16, y-8));
    rbg.setAttribute('x',rx.toFixed(1)); rbg.setAttribute('y',ry.toFixed(1));
    rbg.setAttribute('width',wpx); rbg.setAttribute('height',15);
    rtx.setAttribute('x',(rx+5).toFixed(1)); rtx.setAttribute('y',(ry+11).toFixed(1));
    xh.style.display='';};
  svg.__xhHide=function(){xh.style.display='none';};
  return svg;}

function heightFor(k){
  if(k==='price')return 150;
  if(k==='spy')return 150;
  if(k==='cum')return 150;
  if(k==='flow')return 175;
  return 112;}

window.PZ = {
  render(host){
    const spec=host._spec, t=spec.t;
    const i0=host._i0, i1=host._i1;
    const active=new Set();
    host.querySelectorAll('.tg.on').forEach(b=>active.add(b.dataset.p));
    const mas=[];
    host.querySelectorAll('.mtg.on').forEach(b=>mas.push(parseInt(b.dataset.ma,10)));
    // price and SPY are reference lines: a band around a trending price is
    // noise, so they stay unbanded unless the slider is explicitly moved.
    const opt=k=>({mas:mas,
      bandPct:((k==='price'||k==='spy')&&host._band==null)?0:host._band});
    const body=host.querySelector('.pzbody');
    body.innerHTML='';
    for(const pane of spec.panes){
      if(!active.has(pane.k))continue;
      const box=document.createElement('div');
      box.className='pane';box.dataset.pane=pane.k;
      box.appendChild(drawPane(pane,t,i0,i1,heightFor(pane.k),active,spec,opt(pane.k)));
      body.appendChild(box);}
    // one pointer listener for the whole modal: every pane shows the SAME bar
    const n2=i1-i0+1;
    const svgs=[...body.querySelectorAll('svg')].filter(x=>x.__xh);
    const dateLab=host.querySelector('.pzdate');
    const idxAt=e=>{
      const r=e.currentTarget.getBoundingClientRect();
      const fx=(e.clientX-r.left)/r.width*W;
      if(fx<PADL||fx>W-PADR)return null;
      return Math.round((fx-PADL)/((W-PADL-PADR)||1)*(n2-1));};
    body.onmousemove=e=>{const i=idxAt(e);
      svgs.forEach(x=>x.__xh(i));
      if(dateLab)dateLab.textContent = (i==null?'':t[i0+i]);};
    body.onmouseleave=()=>{svgs.forEach(x=>x.__xhHide());
      if(dateLab)dateLab.textContent='';};

    const lab=host.querySelector('.pzlab');
    if(lab)lab.textContent=`${t[i0]} -> ${t[i1]}  -  ${i1-i0+1} of ${t.length} `
      +(spec.unit||'weeks');
    const bl=host.querySelector('.bandlab');
    if(bl)bl.textContent=host._band==null?'AUTO (fitted per series)'
      :(host._band===0?'OFF - no band, no dots':ord(host._band)+' / '+ord(100-host._band));
    const win=host.querySelector('.pzwin');
    if(win){const N=t.length-1||1;
      win.style.left=(100*i0/N)+'%';
      win.style.width=(100*Math.max(i1-i0,1)/N)+'%';}
  },
  setWindow(host,a,b){
    const N=host._spec.t.length;
    let i0=Math.round(a), i1=Math.round(b);
    i0=Math.max(0,Math.min(N-2,i0)); i1=Math.max(i0+7,Math.min(N-1,i1));
    if(i1-i0>N-1){i0=0;i1=N-1;}
    host._i0=i0;host._i1=i1;this.render(host);},
  init(host,spec){
    // a SPY reference pane is synthesised for any spec that ships spy data
    if(spec.spy&&!spec.panes.some(p=>p.k==='spy'))
      spec.panes.push({k:'spy',fmt:'n',c:'#c3c2b7',bw:spec.bw||52,ref:true,
        lab:'SPY - arrows mark every '+(spec.unit==='sessions'?'session':'week')
            +' a toggled pane sits outside its band',
        v:spec.spy});
    host._spec=spec;host._i0=0;host._i1=spec.t.length-1;
    if(host._band===undefined)host._band=null;
    const N=spec.t.length;
    host.querySelectorAll('.tg').forEach(b=>b.addEventListener('click',()=>{
      b.classList.toggle('on');this.render(host);}));
    host.querySelectorAll('.mtg').forEach(b=>b.addEventListener('click',()=>{
      b.classList.toggle('on');this.render(host);}));
    const sl=host.querySelector('.bandsl');
    if(sl)sl.addEventListener('input',()=>{
      host._band=parseInt(sl.value,10);
      const ab=host.querySelector('.bandauto');if(ab)ab.classList.remove('on');
      this.render(host);});
    const ab=host.querySelector('.bandauto');
    if(ab)ab.addEventListener('click',()=>{
      host._band=null;ab.classList.add('on');this.render(host);});
    const bar=host.querySelector('.pzbar');
    if(bar){
      const src=spec.panes.find(p=>p.v)||null;
      if(src&&src.v){
        const a=src.v.filter(x=>x!=null&&isFinite(x));
        if(a.length>2){
          let mn=Math.min.apply(null,a), mx=Math.max.apply(null,a);
          if(mx<=mn)mx=mn+1;
          const s=el('svg',{viewBox:'0 0 1000 26',preserveAspectRatio:'none',
            style:'position:absolute;inset:0;width:100%;height:100%;opacity:.5'});
          let d='',st=false;
          for(let i=0;i<src.v.length;i++){const x=src.v[i];
            if(x==null||!isFinite(x))continue;
            const px=(i/(src.v.length-1))*1000, py=24-((x-mn)/(mx-mn))*22;
            d+=(st?' L':'M')+px.toFixed(1)+','+py.toFixed(1);st=true;}
          s.appendChild(el('path',{d:d,fill:'none',stroke:'#898781','stroke-width':1,
            'vector-effect':'non-scaling-stroke'}));
          bar.insertBefore(s,bar.firstChild);}}
      const win=host.querySelector('.pzwin');
      let mode=null,startX=0,s0=0,s1=0;
      const pos=e=>{const r=bar.getBoundingClientRect();
        return Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*(N-1);};
      const down=(m)=>(e)=>{mode=m;startX=pos(e);s0=host._i0;s1=host._i1;
        e.preventDefault();e.stopPropagation();
        document.addEventListener('mousemove',move);document.addEventListener('mouseup',up);};
      const move=e=>{if(!mode)return;const d=pos(e)-startX;
        if(mode==='move')this.setWindow(host,s0+d,s1+d);
        else if(mode==='l')this.setWindow(host,s0+d,s1);
        else this.setWindow(host,s0,s1+d);};
      const up=()=>{mode=null;document.removeEventListener('mousemove',move);
        document.removeEventListener('mouseup',up);};
      win.addEventListener('mousedown',down('move'));
      win.querySelector('.hl').addEventListener('mousedown',down('l'));
      win.querySelector('.hr').addEventListener('mousedown',down('r'));
      bar.addEventListener('dblclick',()=>this.setWindow(host,0,N-1));}
    // Wheel-zoom removed 2026-09-02. The brush under the chart is the control:
    // it shows how much of the history you are excluding, which a cursor zoom
    // never does, and it leaves the wheel free to scroll the page it sits in.
    this.render(host);}
};
})();
"""

MA_BUTTONS = "".join(
    f'<button class="mtg" data-ma="{w}">MA{w}</button>' for w in (5, 10, 20, 50, 200))

def ctl_html(unit="weeks", fitted=True):
    """MA toggles + band control, sitting between the pane toggles and the charts.

    `fitted` says what AUTO actually means on THIS chart, and the two are not the
    same thing. On the COT and flow charts AUTO is the cross-sectionally
    calibrated adaptive threshold from charts.adaptive_band -- each series scored
    against how wide the rest of the board is ranging that week. The breadth,
    Stockbee and short-interest series never go through that calibration, so
    their AUTO is a plain rolling 5th/95th on their own trailing window. Both are
    defensible; describing the second as the first is not.
    """
    one = unit[:-1] if unit.endswith("s") else unit
    return (
        '<div class="uctl">'
        f'<span class="uck">Moving averages</span>{MA_BUTTONS}'
        f'<span class="ucu">1 bar = 1 {one}</span>'
        '<span class="ucsep"></span>'
        '<span class="uck">Significance band</span>'
        '<button class="bandauto on">AUTO</button>'
        '<input class="bandsl" type="range" min="0" max="30" step="1" value="5">'
        '<span class="bandlab">AUTO (fitted per series)</span>'
        '</div>'
        '<div class="uchint">'
        + ('AUTO is the adaptive threshold fitted to each series against how wide '
           'the rest of the board is ranging that week.'
           if fitted else
           'AUTO here is a plain rolling 5th/95th on each series&rsquo; own trailing '
           'window &mdash; these series do not go through the cross-sectional '
           'calibration the COT charts use, so it is not board-relative.')
        + ' Drag the slider to force a flat band &mdash; 0 turns it off, 5 is a '
          '5th/95th, 25 a quartile band. Dots and the arrows on the price and SPY '
          'panes both follow whatever band is in force.</div>')

BRUSH_HTML = ('<div class="pzctl"><div class="pzbar"><div class="pzwin">'
              '<span class="hl"></span><span class="hr"></span></div></div>'
              '<div class="pzlab"></div><div class="pzdate"></div>'
              '<div class="pzhint">drag the window to scroll &middot; drag an edge to magnify &middot; '
              'double-click the bar to reset &middot; '
              'every pane stays on the same time scale</div></div>')

BRUSH_CSS = """
.pzctl{margin:10px 0 2px}
.pzbar{position:relative;height:26px;background:#141413;border:1px solid var(--grid);
border-radius:4px;cursor:crosshair;overflow:hidden}
.pzwin{position:absolute;top:0;bottom:0;background:rgba(57,135,229,.20);
border-left:1px solid var(--cool);border-right:1px solid var(--cool);cursor:grab;min-width:8px}
.pzwin:active{cursor:grabbing}
.pzwin .hl,.pzwin .hr{position:absolute;top:0;bottom:0;width:9px;cursor:ew-resize}
.pzwin .hl{left:-4px}.pzwin .hr{right:-4px}
.pzwin .hl:hover,.pzwin .hr:hover{background:rgba(57,135,229,.5)}
.pzlab{color:var(--ink2);font-size:10.5px;margin-top:5px;font-variant-numeric:tabular-nums}
.pzdate{color:#fff;font-size:11px;font-weight:700;height:14px;font-variant-numeric:tabular-nums}
.pzhint{color:var(--mut);font-size:10px;margin-top:2px}
.uctl{display:flex;align-items:center;flex-wrap:wrap;gap:6px;margin:8px 0 3px;
padding:7px 9px;background:#141413;border:1px solid var(--grid);border-radius:5px}
.uctl .uck{color:var(--mut);font-size:10px;text-transform:uppercase;
letter-spacing:.05em;margin-right:2px}
.uctl .ucu{color:var(--mut);font-size:10px;font-style:italic;margin-left:4px}
.uctl .ucsep{flex:0 0 1px;height:16px;background:var(--grid);margin:0 8px}
.uctl button{background:#1c1c1a;border:1px solid var(--grid);color:var(--ink2);
font:inherit;font-size:10.5px;padding:2px 7px;border-radius:4px;cursor:pointer}
.uctl button.on{background:rgba(57,135,229,.22);border-color:var(--cool);color:#fff}
.uctl .bandsl{width:140px;accent-color:var(--cool)}
.uctl .bandlab{color:var(--ink2);font-size:10.5px;font-variant-numeric:tabular-nums;
min-width:96px}
.uchint{color:var(--mut);font-size:10px;margin:0 0 4px}
.pzhost{margin:12px 0 6px;border:1px solid var(--grid);border-radius:6px;
padding:10px 12px;background:#131312}
.pzhost .chd{margin-bottom:7px}
.mcnow{display:flex;gap:20px;flex-wrap:wrap;margin:10px 0 0;font-size:11px;
text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
.mcnow b{font-size:14px;letter-spacing:0;margin-left:5px;font-variant-numeric:tabular-nums}
.mcnow b.up{color:#1baf7a}.mcnow b.dn{color:#e66767}
"""
