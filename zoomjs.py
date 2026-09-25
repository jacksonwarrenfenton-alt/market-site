"""A timeframe brush under every chart -- drag to shrink the window, not wheel-zoom.

The COT charts already had this control and it is the right one: a bar under the
chart showing the whole series, with a draggable window over the part you are
looking at. You can see how much of the history you are excluding, which a
cursor zoom never tells you. Wheel-zoom is also hostile inside a long scrolling
page, because the wheel is how you move down it.

Implementation is deliberately viewBox-only: the window maps to the horizontal
extent of the SVG's own viewBox, so no chart has to re-render, no data is
re-sent, and any chart drawn later picks this up through the observer. Vertical
extent is untouched -- rescaling y per window makes every window look equally
volatile, which destroys the comparison the zoom exists to serve.
"""

ZOOM_JS = """
<script>
(function(){
  function attach(svg){
    if(svg.__brushed) return; svg.__brushed = true;
    var vb = (svg.getAttribute('viewBox')||'').split(/[\\s,]+/).map(Number);
    if(vb.length !== 4 || !isFinite(vb[2])) return;
    var X0 = vb[0], W0 = vb[2];
    // Rotation-map style scatters have no time axis; a timeframe brush would be
    // meaningless there.
    if(svg.classList.contains('rrgsvg')) return;   // scatter: no time axis
    if(svg.classList.contains('vixsvg')) return;   // term structure: no time axis
    if(svg.classList.contains('mcs')) return;      // MC draws its own brush
    if(svg.closest('.mc')) return;

    var host = document.createElement('div');
    host.className = 'tfz';
    // Matches minichart.py/sbui.py's markup: bar + label share a row, the
    // reset button gets its own row underneath.
    host.innerHTML =
      '<div class="tfrow"><div class="tfbar"><div class="tfwin"><i class="hl"></i><i class="hr"></i></div></div>'
      + '<span class="tflab"></span></div>'
      + '<div class="tfctl"><button type="button" class="tfrst">Full range</button></div>';
    svg.parentNode.insertBefore(host, svg.nextSibling);

    var bar = host.querySelector('.tfbar'), win = host.querySelector('.tfwin');
    var lab = host.querySelector('.tflab');
    var a = 0, b = 1;   // window as a fraction of the full range

    function paint(){
      if(b - a < 0.02) b = a + 0.02;
      if(a < 0){ b -= a; a = 0; }
      if(b > 1){ a -= (b - 1); b = 1; }
      if(a < 0) a = 0;
      win.style.left = (a*100) + '%';
      win.style.width = ((b-a)*100) + '%';
      svg.setAttribute('viewBox', (X0 + W0*a) + ' ' + vb[1] + ' ' + (W0*(b-a)) + ' ' + vb[3]);
      lab.textContent = 'showing ' + Math.round((b-a)*100) + '% of the range';
    }
    function frac(e){
      var r = bar.getBoundingClientRect();
      return Math.min(1, Math.max(0, (e.clientX - r.left) / (r.width||1)));
    }
    var drag = null;
    bar.addEventListener('pointerdown', function(e){
      var f = frac(e);
      if(e.target.classList.contains('hl')) drag = {m:'l'};
      else if(e.target.classList.contains('hr')) drag = {m:'r'};
      else if(e.target === win || win.contains(e.target)) drag = {m:'move', f:f, a:a, b:b};
      else { var w = b - a; a = f - w/2; b = a + w; paint(); drag = {m:'move', f:f, a:a, b:b}; }
      bar.setPointerCapture(e.pointerId);
    });
    bar.addEventListener('pointermove', function(e){
      if(!drag) return;
      var f = frac(e);
      if(drag.m === 'l') a = Math.min(f, b - 0.02);
      else if(drag.m === 'r') b = Math.max(f, a + 0.02);
      else { var d = f - drag.f; a = drag.a + d; b = drag.b + d; }
      paint();
    });
    function end(e){ drag = null; try{ bar.releasePointerCapture(e.pointerId); }catch(_){ } }
    bar.addEventListener('pointerup', end);
    bar.addEventListener('pointercancel', end);
    host.querySelector('.tfrst').addEventListener('click', function(){ a=0; b=1; paint(); });
    paint();
  }
  // Stockbee's own chart (svg.sbsvg) used to get its brush from here -- a
  // viewBox-only crop, exactly the "wrong" approach this module's own docstring
  // above describes: it leaves the y-axis fixed to the full history, so a
  // narrowed window still renders flat instead of rescaling to what's visible.
  // sbui.py now ships its own slice-and-rescale brush (same technique as
  // minichart.py), so this scan intentionally finds nothing. Kept in place,
  // inert, in case a future hand-rolled chart needs a generic external brush --
  // wire its class into this selector only if it does NOT need its y-axis to
  // rescale per window (a real value series does; a scatter/no-time-axis chart
  // does not).
  function scan(){ document.querySelectorAll('svg.__unused__').forEach(attach); }
  scan();
  new MutationObserver(function(){ scan(); })
    .observe(document.body, {childList:true, subtree:true});
})();
</script>
"""
