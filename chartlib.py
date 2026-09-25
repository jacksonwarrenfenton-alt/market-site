"""The chart-page library -- the PDF corpus indexed by chart page, not filename.

What it indexes. `Chart Index.html` in jman's notes folder is an index built over
the research corpus: one record per CHART PAGE carrying that page's title, its
label line and its extracted text, tagged by source and date. 149 documents,
4,377 pages.

Why it beats the filename table it sits next to. `research_html` lists PDFs,
which only helps if you already know which document holds the chart you want.
This indexes the pages, so "put call" or "copper gold" or "market cycle clock"
lands on the actual page in the actual report -- which is the behaviour the
project brief asks for: when jman asks about an asset, pull the framework chart
rather than narrate positioning.

HARD CONSTRAINT -- read before "fixing" the source path. The parsed index is
~1.2MB of JSON. It CANNOT be stored in the project: knowledge sits at ~1.988M of
2.000M tokens (RUNBOOK step 11), so a doc that size is refused outright. The
index therefore has to come from the device on a run where the folder is
connected, and every rebuild without it must degrade silently rather than throw.
That is what `load()` returning None is for, and why `marketsite` falls back to
`research_html` -- see the hook note in CODE_PATCHES.md.

Second caveat, stated on the page itself rather than hidden: the index survives
but most of the SOURCE PDFs are no longer in the folder -- 6 of 149 at last
check. A hit names the document, the page and what is on it; it opens the PDF
only for the handful still present. Everything else is a citation, not a link.
Drop the PDFs back in and they relink on the next run.

Dates are re-derived from the filename via marketsite._parse rather than trusted
from the index: the index's own parser read WSG-010162026.pdf as October 2026,
three months into the future, and 711 records carried no date at all.
"""
import json, re, html, os, datetime as _dt

D = os.path.expanduser("~/pos")
SRC = f"{D}/chart_index_src.html"        # staged from the device when connected
CACHE = f"{D}/chart_pages.json"          # parsed form, survives within a container
TODAY = _dt.date.today().isoformat()


def _records(path):
    h = open(path, encoding="utf-8", errors="replace").read()
    j = h.index("[", h.index("R="))
    return json.JSONDecoder().raw_decode(h[j:])[0]


def _cut(s, n):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def present(folder=None):
    """Filenames actually sitting in the notes folder, so the page links only the
    PDFs that will really open. Written by whoever last listed the folder."""
    p = f"{D}/research_present.json"
    if os.path.exists(p):
        try: return set(json.load(open(p)))
        except Exception: return set()
    if folder and os.path.isdir(folder):
        return {f for f in os.listdir(folder) if f.lower().endswith(".pdf")}
    return set()


def build(path=SRC, have=None):
    """Compact page records, cached to CACHE. None when the source is absent --
    which is the normal state on a cloud rebuild, not an error."""
    if not os.path.exists(path):
        return None
    try:
        import marketsite as MS
        _parse = MS._parse
    except Exception:
        _parse = lambda n: (None, None)
    have = present() if have is None else have
    docdate, out = {}, []
    for r in _records(path):
        f = r["f"]
        if f not in docdate:
            _, dt = _parse(f)
            # Fall back to the index's own date ONLY when it is not in the
            # future. Falling back blindly reintroduced the exact Oct-2026 bug
            # this re-derivation exists to remove.
            alt = str(r.get("d") or "")
            if not dt and alt and alt[:7] > TODAY[:7]:
                alt = ""
            docdate[f] = dt.isoformat() if dt else alt
        out.append({"f": f, "p": r["p"], "s": r["s"], "d": docdate[f],
                    "t": _cut(r.get("t"), 90), "l": _cut(r.get("l"), 150),
                    "x": _cut(r.get("x"), 260), "h": 1 if f in have else 0})
    out.sort(key=lambda r: (r["d"] or "0000", r["f"], r["p"]), reverse=True)
    try:
        json.dump(out, open(CACHE, "w"), separators=(",", ":"))
    except Exception:
        pass
    return out


def load():
    """Cache, else parse, else None. Never raises -- a rebuild with no notes
    folder must lose this section quietly, not fail the build."""
    try:
        if os.path.exists(CACHE):
            return json.load(open(CACHE))
        return build()
    except Exception:
        return None


def html_block(recs, research_dir):
    if not recs:
        return ""
    srcs = {}
    for r in recs:
        srcs[r["s"]] = srcs.get(r["s"], 0) + 1
    docs = {r["f"] for r in recs}
    live = {r["f"] for r in recs if r["h"]}
    chips = ('<div class="chips clchips"><button class="chip on" data-cs="all">All '
             f'<span>{len(recs):,}</span></button>' + "".join(
                 f'<button class="chip" data-cs="{html.escape(s)}">{html.escape(s)} '
                 f'<span>{n:,}</span></button>'
                 for s, n in sorted(srcs.items(), key=lambda x: -x[1])) + '</div>')
    warn = ""
    if len(live) < len(docs):
        warn = (f'<p class="grpnote" style="border-left:2px solid var(--warn);'
                f'padding-left:8px"><b>{len(docs) - len(live)} of {len(docs)} source '
                f'documents are not in the connected folder.</b> The index is complete '
                f'&mdash; all {len(recs):,} chart pages are searchable and each says '
                f'which document, which page, and what is on it &mdash; but only '
                f'<b>{len(live)}</b> PDFs are present, so only those rows open. The rest '
                f'are citations. Put the PDFs back in the folder and they relink on the '
                f'next run.</p>')
    return (warn + chips +
            '<div class="clsearch"><input id="clq" type="search" placeholder="Search '
            f'{len(recs):,} chart pages &mdash; try &ldquo;put call&rdquo;, '
            '&ldquo;copper gold&rdquo;, &ldquo;market cycle clock&rdquo;, '
            '&ldquo;breadth thrust&rdquo;">'
            '<span id="cln" class="dim"></span></div>'
            '<table class="mini chartlib"><thead><tr><th>Date</th><th>Source</th>'
            '<th>Document</th><th>Pg</th><th>Chart</th></tr></thead>'
            '<tbody id="clb"></tbody></table>'
            '<p class="chf">Click a row to expand the extracted page text. Search matches '
            'the title, the label line and the page body. Results cap at 200 rows &mdash; '
            'narrow the query rather than scrolling.</p>')


def payload_js(recs, research_dir):
    """The data + behaviour, for marketsite to drop into its js_extra."""
    if not recs:
        return ""
    return ("\nwindow.CLIB=" + json.dumps(recs, separators=(",", ":")) + ";\n"
            "window.CLDIR=" + json.dumps(research_dir) + ";\n" + CL_JS)


CL_JS = """
(function(){
  const B=document.getElementById('clb'); if(!B||!window.CLIB)return;
  const q=document.getElementById('clq'), cn=document.getElementById('cln');
  const DIR=window.CLDIR||'';
  let src='all', term='';
  function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
  function draw(){
    const t=term.toLowerCase().split(/\\s+/).filter(Boolean);
    const hit=CLIB.filter(r=>{
      if(src!=='all'&&r.s!==src)return false;
      if(!t.length)return true;
      const hay=(r.t+' '+r.l+' '+r.x+' '+r.f).toLowerCase();
      return t.every(w=>hay.indexOf(w)>=0);});
    cn.textContent=hit.length.toLocaleString()+' page'+(hit.length===1?'':'s')
      +(hit.length>200?' - showing first 200':'');
    B.innerHTML=hit.slice(0,200).map(r=>{
      const doc=r.h? '<a href="computer://'+DIR+'/'+encodeURI(r.f)+'">'+esc(r.f)+'</a>'
                   : '<span class="nolink" title="PDF not in the connected folder">'+esc(r.f)+'</span>';
      return '<tr class="clr"><td class="dim">'+esc(r.d||'-')+'</td><td>'+esc(r.s)+'</td>'
        +'<td>'+doc+'</td><td class="dim">'+r.p+'</td>'
        +'<td><b>'+esc(r.t||'-')+'</b><i>'+esc(r.l)+'</i></td></tr>'
        +'<tr class="clx"><td colspan="5">'+esc(r.x)+'</td></tr>';}).join('');
  }
  q.addEventListener('input',()=>{term=q.value;draw();});
  document.querySelectorAll('.clchips .chip').forEach(c=>c.addEventListener('click',()=>{
    document.querySelectorAll('.clchips .chip').forEach(x=>x.classList.remove('on'));
    c.classList.add('on'); src=c.dataset.cs; draw();}));
  B.addEventListener('click',e=>{
    const tr=e.target.closest('tr.clr'); if(!tr||e.target.tagName==='A')return;
    tr.classList.toggle('open');
    if(tr.nextElementSibling)tr.nextElementSibling.classList.toggle('on');});
  draw();
})();
"""

CL_CSS = """
.clsearch{display:flex;align-items:center;gap:10px;margin:8px 0 6px}
.clsearch input{flex:1;background:#141413;border:1px solid var(--grid);color:var(--ink);
font:13px ui-sans-serif,sans-serif;padding:7px 10px;border-radius:5px}
.clsearch input:focus{outline:none;border-color:var(--cool)}
table.chartlib{width:100%}
table.chartlib td{vertical-align:top}
table.chartlib tr.clr{cursor:pointer}
table.chartlib tr.clr:hover{background:#1a1a19}
table.chartlib tr.clr.open{background:#1c2230}
table.chartlib tr.clr b{display:block;font-size:11.5px;color:var(--ink)}
table.chartlib tr.clr i{display:block;font-style:normal;font-size:10px;color:var(--mut);margin-top:1px}
table.chartlib tr.clx{display:none}
table.chartlib tr.clx.on{display:table-row}
table.chartlib tr.clx td{color:var(--ink2);font-size:10.5px;line-height:1.55;
background:#121211;padding:8px 10px;border-left:2px solid var(--cool)}
table.chartlib .nolink{color:var(--mut)}
"""
