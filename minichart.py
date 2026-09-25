"""One chart component: dual axes, and a brush that SLICES rather than magnifies.

The viewBox brush was wrong. Narrowing a viewBox magnifies a region -- on a
chart whose aspect ratio is preserved it zooms into a corner, and even where it
does not, the y-axis keeps the full range so a zoomed window looks flat. The COT
charts never did this: they re-render for the selected window and rescale both
axes to what is actually in it, which is the only way a zoom tells you anything.

This does the same. The brush sets an index range, the component slices every
series to it and recomputes each axis from the visible points only. Series can
sit on axis 1 or 2, so a price line and a percentage line share a frame without
one flattening the other.
"""

MINI_JS = r"""
<script>
window.MC = (function(){
  function fmt(v){
    var a=Math.abs(v);
    if(a>=1e9) return (v/1e9).toFixed(1)+'B';
    if(a>=1e6) return (v/1e6).toFixed(1)+'M';
    if(a>=10000) return Math.round(v).toLocaleString();
    if(a>=100) return v.toFixed(0);
    if(a>=10) return v.toFixed(1);
    return v.toFixed(2);
  }
  function extent(arrs, i0, i1){
    var mn=Infinity, mx=-Infinity;
    arrs.forEach(function(a){
      for(var i=i0;i<=i1 && i<a.length;i++){
        var v=a[i]; if(v==null||!isFinite(v)) continue;
        if(v<mn) mn=v; if(v>mx) mx=v;
      }});
    if(!isFinite(mn)) return null;
    if(mx===mn){ mx=mn+1; mn=mn-1; }
    var p=(mx-mn)*0.08; return [mn-p, mx+p];
  }
  function tx(vals, mode, i0){
    if(mode==='raw') return vals;
    if(mode==='log'){
      return vals.map(function(v){ return (v==null||!isFinite(v)||v<=0)?null:Math.log(v); });
    }
    // index: rebase to 100 at the FIRST VISIBLE point, so the comparison is
    // always about the window you are looking at rather than 2010
    var base=null;
    for(var i=i0;i<vals.length;i++){ var v=vals[i];
      if(v!=null&&isFinite(v)&&v!==0){ base=v; break; } }
    if(base===null) return vals;
    return vals.map(function(v){ return (v==null||!isFinite(v))?null:100*v/base; });
  }
  function draw(host, spec, i0, i1){
    var D=spec.dates;
    var mode=host.__mode||spec.mode||'index';
    var S=spec.series.map(function(s){
      return Object.assign({}, s, {vals: tx(s.vals, mode, i0)});
    });
    var W=spec.w||1180, H=spec.h||240, PL=52, PR=52, PT=14, PB=26;
    var iw=W-PL-PR, ih=H-PT-PB, n=i1-i0+1;
    var a1=S.filter(function(s){return s.axis!==2;}).map(function(s){return s.vals;});
    var a2=S.filter(function(s){return s.axis===2;}).map(function(s){return s.vals;});
    var r1=extent(a1,i0,i1), r2=extent(a2,i0,i1);
    var X=function(i){return PL+iw*(n<2?0.5:(i-i0)/(n-1));};
    function Y(v,r){return PT+ih-ih*(v-r[0])/((r[1]-r[0])||1);}
    var g='';
    for(var k=0;k<=4;k++){
      var yy=PT+ih*k/4;
      g+='<line x1="'+PL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+yy.toFixed(1)+'" stroke="var(--grid)"/>';
      if(r1){ var v1=r1[1]-(r1[1]-r1[0])*k/4;
        g+='<text x="'+(PL-6)+'" y="'+(yy+3.5).toFixed(1)+'" text-anchor="end" class="ax">'
          +(mode==='log'?fmt(Math.exp(v1)):fmt(v1))+'</text>'; }
      if(r2){ var v2=r2[1]-(r2[1]-r2[0])*k/4;
        g+='<text x="'+(W-PR+6)+'" y="'+(yy+3.5).toFixed(1)+'" class="ax sp">'
          +(mode==='log'?fmt(Math.exp(v2)):fmt(v2))+'</text>'; }
    }
    var paths='', leg='';
    S.forEach(function(s){
      var r=(s.axis===2)?r2:r1; if(!r) return;
      var d='', pen=false;
      for(var i=i0;i<=i1 && i<s.vals.length;i++){
        var v=s.vals[i];
        if(v==null||!isFinite(v)){ pen=false; continue; }
        d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Y(v,r).toFixed(1)+' '; pen=true;
      }
      paths+='<path d="'+d+'" fill="none" stroke="'+s.color+'" stroke-width="'+(s.w||1.6)+'"'
           + (s.dash?' stroke-dasharray="4 3"':'') + '/>';
      leg+='<span class="k" style="background:'+s.color+'"></span>'+s.name
         + (s.axis===2?' <i class="dim">(right)</i>':'')+' ';
    });
    if(spec.zero && r1 && r1[0]<0 && r1[1]>0){
      var zy=Y(0,r1);
      g+='<line x1="'+PL+'" y1="'+zy.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+zy.toFixed(1)+'" stroke="var(--base)" stroke-dasharray="3 3"/>';
    }
    var ticks='', step=Math.max(1,Math.floor(n/8));
    for(var i=i0;i<=i1;i+=step)
      ticks+='<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" class="ax">'+(D[i]||'').slice(0,7)+'</text>';
    host.querySelector('.mcsvg').innerHTML=
      '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" class="mcs">'+g+paths+ticks+'</svg>';
    host.querySelector('.mclg').innerHTML=leg;
    var lb=host.querySelector('.tflab');
    if(lb) lb.textContent = D[i0]+'  →  '+D[i1]+'   ('+n+' points)';
  }
  function mount(id, spec){
    var host=document.getElementById(id); if(!host) return;
    var N=spec.dates.length; if(N<2) return;
    // The bar sits beside its date-range label on one row (.tfrow) -- in a
    // narrow two-column card that's the only pairing that fits at all, since
    // label+mode-buttons together are often wider than the whole card. Mode
    // buttons + reset get their own row (.tfctl) underneath.
    host.innerHTML='<div class="mcsvg"></div><div class="mclg"></div>'
      +'<div class="tfz"><div class="tfrow"><div class="tfbar"><div class="tfwin">'
      +'<i class="hl"></i><i class="hr"></i></div></div>'
      +'<span class="tflab"></span></div>'
      +'<div class="tfctl">'
      +'<span class="mcmode">'
      +'<button type="button" data-m="index" class="mcm on">Index 100</button>'
      +'<button type="button" data-m="log" class="mcm">Log</button>'
      +'<button type="button" data-m="raw" class="mcm">Raw</button></span>'
      +'<button type="button" class="tfrst">Full range</button></div></div>';
    var a=0,b=1, bar=host.querySelector('.tfbar'), win=host.querySelector('.tfwin');
    function apply(){
      if(b-a<0.02) b=a+0.02;
      if(a<0){b-=a;a=0;} if(b>1){a-=(b-1);b=1;} if(a<0)a=0;
      win.style.left=(a*100)+'%'; win.style.width=((b-a)*100)+'%';
      var i0=Math.round(a*(N-1)), i1=Math.round(b*(N-1));
      if(i1-i0<2) i1=Math.min(N-1,i0+2);
      draw(host, spec, i0, i1);
    }
    function frac(e){var r=bar.getBoundingClientRect();
      return Math.min(1,Math.max(0,(e.clientX-r.left)/(r.width||1)));}
    var drag=null;
    bar.addEventListener('pointerdown',function(e){
      var f=frac(e);
      if(e.target.classList.contains('hl')) drag={m:'l'};
      else if(e.target.classList.contains('hr')) drag={m:'r'};
      else if(win.contains(e.target)||e.target===win) drag={m:'move',f:f,a:a,b:b};
      else {var w=b-a; a=f-w/2; b=a+w; apply(); drag={m:'move',f:f,a:a,b:b};}
      bar.setPointerCapture(e.pointerId);
    });
    bar.addEventListener('pointermove',function(e){
      if(!drag) return; var f=frac(e);
      if(drag.m==='l') a=Math.min(f,b-0.02);
      else if(drag.m==='r') b=Math.max(f,a+0.02);
      else {var d=f-drag.f; a=drag.a+d; b=drag.b+d;}
      apply();
    });
    function end(e){drag=null; try{bar.releasePointerCapture(e.pointerId);}catch(_){}}
    bar.addEventListener('pointerup',end); bar.addEventListener('pointercancel',end);
    host.querySelector('.tfrst').addEventListener('click',function(){a=0;b=1;apply();});
    host.__mode = spec.mode || 'index';
    host.querySelectorAll('.mcm').forEach(function(btn){
      btn.classList.toggle('on', btn.dataset.m===host.__mode);
      btn.addEventListener('click',function(){
        host.__mode=btn.dataset.m;
        host.querySelectorAll('.mcm').forEach(function(x){
          x.classList.toggle('on', x.dataset.m===host.__mode); });
        apply();
      });
    });
    apply();
  }
  return {mount:mount};
})();
</script>
"""
