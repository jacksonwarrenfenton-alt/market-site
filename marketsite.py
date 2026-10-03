"""jman's market site -- three tabs in one self-contained HTML file."""
import pandas as pd, numpy as np, os, re, html, json, datetime as dt

D = os.path.expanduser("~/pos")
RESEARCH_DIR = "/Users/JacksonsMacBook/Desktop/untitled folder"

SOURCE_PAT = [
    (r"verrone",                    "Verrone"),
    (r"degra+f",                    "DeGraaf"),
    (r"\bwsg\b|renmac|bluematrix",  "RenMac / WSG"),
    (r"srptechnical|\bsrp\b",       "SRP Technical"),
    (r"hartnett|\bbofa\b",          "Hartnett / BofA"),
]

def _parse(name):
    """(source, date) from a filename.

    Dates are ambiguous here -- WSG-010162026.pdf is MMDDYYYY while
    SRPTechnicalResearch20260301.pdf is YYYYMMDD, and a naive YYYYMMDD-first
    regex turns the former into 2026-10-16, months in the future. So try every
    interpretation and keep only real dates not in the future.
    """
    low = name.lower()
    src = next((lab for pat, lab in SOURCE_PAT if re.search(pat, low)), "Other")
    today = dt.date.today()
    cands = []
    m = re.search(r"(20\d{2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})", name)
    if m:
        try: cands.append(dt.datetime.strptime(
            f"{m.group(1)} {m.group(2)} {m.group(3)}", "%Y %b %d").date())
        except Exception: pass
    # Format order is a PREFERENCE, not a fallback: 04072026 parses under both
    # %m%d%Y (7 Apr) and %d%m%Y (4 Jul). US month-first wins because that is how
    # these desks name files; taking max() picked 4 Jul and was wrong.
    for run in re.findall(r"\d{8}", name):
        for fmt in ("%Y%m%d", "%m%d%Y", "%d%m%Y"):
            try:
                d = dt.datetime.strptime(run, fmt).date()
            except ValueError:
                continue
            if dt.date(2000, 1, 1) <= d <= today:
                cands.append(d); break
    m = re.search(r"(20\d{2})[-_ ](0[1-9]|1[0-2])[-_ ](0[1-9]|[12]\d|3[01])", name)
    if m:
        try:
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d <= today: cands.append(d)
        except ValueError: pass
    return src, (cands[0] if cands else None)

def research_index(entries):
    rows = []
    for e in entries:
        n = e.get("name", "")
        if not n.lower().endswith(".pdf"): continue
        src, d = _parse(n)
        rows.append({"name": n, "src": src, "date": d.isoformat() if d else None,
                     "mb": round(e.get("size", 0)/1e6, 1)})
    rows.sort(key=lambda r: (r["date"] or "0000"), reverse=True)
    return rows

def research_html(rows):
    if not rows:
        return ('<p class="none">No research library indexed yet. Connect the folder '
                'holding the Verrone / DeGraaf / RenMac notes and re-run.</p>')
    srcs = sorted({r["src"] for r in rows})
    chips = ('<div class="chips"><button class="chip on" data-rs="all">All '
             f'<span>{len(rows)}</span></button>' + "".join(
        f'<button class="chip" data-rs="{html.escape(s)}">{html.escape(s)} '
        f'<span>{sum(1 for r in rows if r["src"]==s)}</span></button>' for s in srcs)
        + '</div>')
    tr = "".join(
        f'<tr data-rs="{html.escape(r["src"])}">'
        f'<td class="dim">{r["date"] or "&mdash;"}</td>'
        f'<td>{html.escape(r["src"])}</td>'
        f'<td><a href="computer://{html.escape(RESEARCH_DIR)}/{html.escape(r["name"])}">'
        f'{html.escape(r["name"])}</a></td>'
        f'<td class="dim">{r["mb"]:.1f} MB</td></tr>' for r in rows)
    return (chips + '<table class="mini research"><thead><tr><th>Date</th><th>Source</th>'
            '<th>Document</th><th>Size</th></tr></thead><tbody>' + tr + '</tbody></table>')

def regime_html(r):
    tone = {"BREAKOUT": "good", "CHOPPY": "warn", "DOWNTREND": "bad"}[r["regime"]]
    votes = "".join(
        f'<div class="vote"><span class="vn">{html.escape(k)}</span>'
        f'<span class="vv {"up" if v>0.1 else ("dn" if v<-0.1 else "nu")}">'
        f'{"+" if v>0.1 else ("&minus;" if v<-0.1 else "&middot;")}</span></div>'
        for k, v in r["signals"].items())
    d = r["detail"]
    bits = []
    if "breadth" in d:
        bits.append(f'{d["breadth"]["pct_above_50"]:.0f}% of groups above their 50d, '
                    f'{d["breadth"]["pct_above_200"]:.0f}% above 200d')
    if "vol" in d:
        v = d["vol"]; s = f'VIX {v["vix"]:.1f} ({v["chg10d"]:+.1f} over 10d)'
        if "vix3m_vix" in v: s += f' &middot; VIX3M/VIX {v["vix3m_vix"]:.2f}'
        bits.append(s)
    if "credit" in d: bits.append(f'HYG/LQD {d["credit"]["vs_50d"]:+.1f}% vs its 50d')
    if "rates" in d:
        rr = d["rates"]; bits.append(
            f'TLT {"above" if rr["px"]>rr["ma50"] else "below"} 50d and '
            f'{"above" if rr["px"]>rr["ma200"] else "below"} 200d')
    setups = "".join(f'<li>{html.escape(s)}</li>' for s in r["setups"])
    return (f'<div class="regime {tone}"><div class="rgh"><span class="rgl">MARKET REGIME</span>'
            f'<span class="rgv">{r["regime"]}</span>'
            f'<span class="rgs">score {r["score"]:+.2f}</span></div>'
            f'<div class="votes">{votes}</div>'
            f'<p class="rgd">{" &middot; ".join(bits)}</p>'
            f'<div class="rgset"><h4>Setups live in this regime</h4><ul>{setups}</ul></div></div>')

def _ord(v):
    """12 -> '12th', 2 -> '2nd', 1 -> '1st' (percentiles in prose)."""
    n = int(round(float(v)))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def auto_read(conf, sig, flows_latest, si, reg, fresh, brows=None, sbrow=None):
    L = []
    hot = conf[conf.verdict.isin(["CROWDED", "WASHED OUT"])] if conf is not None and len(conf) else None
    if hot is not None and len(hot):
        for _, t in hot.head(4).iterrows():
            # Only the legs that exist for this theme -- a missing one used to
            # print as "nanth" / "+nanpp".
            parts = []
            if np.isfinite(t.cot): parts.append(f'COT specs at the {_ord(t.cot)} percentile')
            if np.isfinite(t.flow_pct): parts.append(f'flows {t.flow_pct:+.2f}% of AUM')
            if np.isfinite(t.si_z): parts.append(f'short-interest breadth tilt {t.si_z:+.0f}pp')
            L.append(f'<b>{html.escape(t.theme)}</b> is <b>{t.verdict}</b> '
                     f'({int(t.agree)}/3 datasets agree) &mdash; ' + ", ".join(parts) + '.')
    if sig is not None and len(sig):
        a = sig.iloc[0]; b = sig[sig["read"] != sig.iloc[0]["read"]].head(1)
        L.append(f'Top-ranked positioning signal is <b>{html.escape(str(a["name"]))}</b> &mdash; '
                 f'{html.escape(a.phrase)}, reading <b>{a["read"]}</b> '
                 f'({_ord(a.pct52)} on 52w, {_ord(a.pct3y)} on 3yr).')
        if len(b):
            b = b.iloc[0]
            L.append(f'Best signal the other way is <b>{html.escape(str(b["name"]))}</b> &mdash; '
                     f'{html.escape(b.phrase)}, reading <b>{b["read"]}</b>.')
    if flows_latest is not None and len(flows_latest):
        f = flows_latest.sort_values("z_1w")
        lo, hi = f.iloc[0], f.iloc[-1]
        L.append(f'Flows: <b>{html.escape(hi.basket)}</b> took the biggest inflow '
                 f'({hi.flow_1w/1e9:+.1f}B, {hi.z_1w:+.1f}&sigma;) and '
                 f'<b>{html.escape(lo.basket)}</b> the biggest outflow '
                 f'({lo.flow_1w/1e9:+.1f}B, {lo.z_1w:+.1f}&sigma;).')
        lev = flows_latest[flows_latest.basket == "Index Long (leveraged)"]
        inv = flows_latest[flows_latest.basket == "Index Short (inverse)"]
        if len(lev) and len(inv):
            lv, iv = lev.iloc[0], inv.iloc[0]
            L.append(f'Index leverage: <b>{lv.flow_1w/1e6:+.0f}M</b> into levered longs '
                     f'({lv.pct_1w:+.2f}% of AUM) against <b>{iv.flow_1w/1e6:+.0f}M</b> into '
                     f'inverse funds ({iv.pct_1w:+.2f}%). Money into the short basket is '
                     f'bearish positioning building &mdash; it is not sign-flipped.')
    if brows is not None and len(brows):
        t = brows[brows.group == "TOTAL MARKET"]
        if len(t):
            t = t.iloc[0]
            best = brows[brows.group != "TOTAL MARKET"].sort_values("net_ratio")
            L.append(f'Tape: <b>{t.net:+,}</b> net advancers ({t.net_ratio:+.0f}%), '
                     f'{int(t.hi52)} new highs vs {int(t.lo52)} new lows, up/down volume '
                     f'{t.updn:.2f}, {t.pct50:.0f}% of names above their 50d. '
                     f'Strongest sector <b>{html.escape(str(best.iloc[-1].group))}</b> '
                     f'({best.iloc[-1].net_ratio:+.0f}%), weakest '
                     f'<b>{html.escape(str(best.iloc[0].group))}</b> '
                     f'({best.iloc[0].net_ratio:+.0f}%).')
    if sbrow is not None:
        L.append(f'Stockbee: <b>{sbrow["up4"]:,}</b> stocks up 4% today against '
                 f'<b>{sbrow["dn4"]:,}</b> down 4% (day ratio {sbrow["r1"]:.2f}), '
                 f'5-day {sbrow["r5"]:.2f} and 10-day {sbrow["r10"]:.2f} &mdash; '
                 f'<b>{sbrow["verdict"]}</b>. Quarterly cohort {sbrow["up25q"]:,} up 25% '
                 f'vs {sbrow["dn25q"]:,} down.')
    L.append(f'Regime reads <b>{reg["regime"]}</b> at {reg["score"]:+.2f} &mdash; '
             f'{"run the breakout book" if reg["regime"]=="BREAKOUT" else ("stay with RS leaders on pullbacks and tight ranges" if reg["regime"]=="CHOPPY" else "short into descending averages, keep size small")}.')
    stale = [f["feed"] for f in fresh if f.get("stale")]
    if stale: L.append(f'<b class="bad">Stale or unavailable feed:</b> {", ".join(stale)}.')
    return '<ul class="read">' + "".join(f"<li>{x}</li>" for x in L) + "</ul>"

def subsector_html(board):
    return ('<div class="pending"><h3>Waiting on the 176-basket roster</h3>'
            '<p>The subsector scan lives in the <b>Custom Scanner</b> project. Drop '
            '<code>custom176-rosters.txt</code> into <code>~/pos/</code> or a connected '
            'folder and this tab switches over automatically.</p></div>')

TAB_CSS = """
tr.grow.clk{cursor:pointer}
tr.grow.clk:hover td.nm{color:#fff}
tr.grow .caret{display:inline-block;margin-right:6px;color:var(--mut);transition:transform .12s}
tr.grow.open .caret{transform:rotate(90deg);color:var(--cool)}
.t10grp{display:inline-flex;gap:2px;margin-right:5px;vertical-align:1px}
.t10{display:inline-flex;align-items:center;justify-content:center;width:13px;height:13px;
border-radius:3px;font-size:8px;font-weight:700;line-height:1;color:#fff}
.t10.tw{background:var(--cool)}
.t10.tm{background:var(--vio)}
.t10.tq{background:var(--warn);color:#1a1a18}
.t10.tr{background:var(--good)}
p.grpnote .t10{margin:0 2px;vertical-align:-1px}
tr.det{display:none}
tr.det.on{display:table-row}
tr.det>td{background:#101010;padding:6px 10px 10px 34px}
table.cons{width:auto;min-width:460px}
table.cons td,table.cons th{text-align:right;padding:2px 10px}
table.cons td.t,table.cons th:first-child{text-align:left;color:#fff;font-weight:600}
.sbbox{margin:14px 0;border:1px solid var(--grid);border-radius:6px;padding:12px 14px;background:var(--s)}
.sbh{display:flex;align-items:baseline;gap:12px;margin-bottom:10px}
.sbl{font-size:10px;letter-spacing:.09em;color:var(--mut);text-transform:uppercase}
.sbv{font-size:13px;font-weight:700;letter-spacing:.05em}
.sbv.good{color:#1baf7a}.sbv.warn{color:#fab219}.sbv.bad{color:#e66767}.sbv.dim{color:var(--mut)}
.sbgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:10px}
.sbc{display:flex;flex-direction:column;gap:1px}
.sbc span{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut)}
.sbc b{font-size:17px;font-variant-numeric:tabular-nums}
.sbc b.up{color:#1baf7a}.sbc b.dn{color:#e66767}
.sbc i{font-size:10px;color:var(--mut);font-style:normal}
table.sub td{text-align:right;font-variant-numeric:tabular-nums}
table.sub td.nm{text-align:left}
table.sub td.up{color:#1baf7a}table.sub td.dn{color:#e66767}
table.breadth td{font-variant-numeric:tabular-nums;text-align:right;padding:4px 7px}
table.breadth tr.tot{background:#141413}
table.breadth tr.tot td.nm{font-weight:700;color:#fff}
table.breadth td.up{color:#1baf7a}table.breadth td.dn{color:#e66767}
.mcbox{margin:14px 0;border:1px solid var(--grid);border-radius:6px;padding:10px 12px;background:var(--s)}
.mch{display:flex;align-items:baseline;gap:10px;margin:8px 0 2px;font-size:11px;
text-transform:uppercase;letter-spacing:.06em;color:var(--mut)}
.mch b{font-size:13px;letter-spacing:0;font-variant-numeric:tabular-nums}
.mch b.up{color:#1baf7a}.mch b.dn{color:#e66767}
.tabs{display:flex;gap:2px;border-bottom:2px solid var(--base);margin:14px 0 0}
.tab{background:none;border:0;border-bottom:2px solid transparent;margin-bottom:-2px;
color:var(--mut);font:600 12.5px ui-sans-serif,sans-serif;letter-spacing:.06em;
text-transform:uppercase;padding:9px 16px;cursor:pointer}
.tab:hover{color:var(--ink2)}
.tab.on{color:#fff;border-bottom-color:var(--cool)}
.tabpane{display:none}
.tabpane.on{display:block}
.fresh{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 4px}
.fr{background:var(--s);border:1px solid var(--grid);border-radius:5px;padding:7px 11px;
display:flex;flex-direction:column;gap:2px;min-width:290px}
.frn{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.frv{font-size:11px;font-weight:700;letter-spacing:.05em}
.frv.good{color:#1baf7a}.frv.bad{color:#e66767}
.frd{font-size:11px;color:var(--ink2)}
.frc{font-size:10px;color:var(--mut)}
.regime{border:1px solid var(--grid);border-left-width:4px;border-radius:6px;
padding:14px 16px;background:var(--s);margin:14px 0}
.regime.good{border-left-color:#1baf7a}.regime.warn{border-left-color:#fab219}
.regime.bad{border-left-color:#e66767}
.rgh{display:flex;align-items:baseline;gap:12px}
.rgl{font-size:10px;letter-spacing:.09em;color:var(--mut);text-transform:uppercase}
.rgv{font-size:22px;font-weight:700;letter-spacing:-.01em}
.rgs{font-size:11px;color:var(--mut);font-variant-numeric:tabular-nums}
.votes{display:flex;gap:14px;margin:10px 0 6px;flex-wrap:wrap}
.vote{display:flex;align-items:center;gap:5px}
.vv{font-weight:700;font-size:13px}
.vv.up{color:#1baf7a}.vv.dn{color:#e66767}.vv.nu{color:var(--mut)}
.rgd{color:var(--ink2);font-size:12px;margin:4px 0 0}
.rgset h4{margin:12px 0 4px}
.rgset ul{margin:0;padding-left:18px;color:var(--ink2);font-size:12.5px}
.rgset li{margin:2px 0}
ul.read{padding-left:18px;color:var(--ink2);font-size:13px;line-height:1.6}
ul.read li{margin:5px 0}
ul.read b{color:#fff}
ul.read b.bad{color:#e66767}
table.research a{color:var(--cool);text-decoration:none}
table.research a:hover{text-decoration:underline}
.pending{border:1px dashed var(--base);border-radius:6px;padding:22px;color:var(--ink2);
background:var(--s)}
.pending h3{margin:0 0 8px;font-size:14px}
.pending code{background:#101010;padding:1px 5px;border-radius:3px;font-size:11.5px}
.diarynote{border:1px solid var(--grid);border-radius:6px;padding:12px 14px;
background:var(--s);margin:10px 0;color:var(--ink2);font-size:12.5px}
.diarynote b{color:#fff}
.backlink{color:var(--cool);cursor:pointer;font-size:12px;margin:0 0 8px;font-weight:600}
.backlink:hover{text-decoration:underline}
.fwgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:10px 0}
.fwcard{border:1px solid var(--grid);border-radius:6px;padding:10px 12px;background:var(--s)}
.fwcard h6{margin:0 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.fwcard .s{font-size:11.5px;color:var(--ink2);margin-bottom:6px}
.fwbands{margin-top:6px;display:flex;flex-direction:column;gap:2px}
.fwrow{display:flex;align-items:center;gap:6px;font-size:10.5px}
.fwrow.cur .fwb{color:#fff;font-weight:700}
.fwb{width:82px;flex:none;color:var(--mut);font-variant-numeric:tabular-nums}
.fwbar{flex:1;height:8px;background:#141413;border-radius:2px;overflow:hidden}
.fwbar i{display:block;height:100%;background:var(--cool);border-radius:2px}
.fwrow.cur .fwbar i{background:var(--vio)}
.fwp{width:40px;text-align:right;flex:none;font-variant-numeric:tabular-nums;color:var(--ink2)}
.altiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:10px 0}
.altile{border:1px solid var(--grid);border-radius:6px;padding:10px 12px;background:var(--s)}
.altile h6{margin:0 0 4px;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.altile .v{font-size:16px;font-weight:700}
.altile .v.good{color:#1baf7a}.altile .v.crit{color:#e66767}.altile .v.dim{color:var(--mut)}
.altile .s{font-size:11px;color:var(--ink2);margin-top:2px}
.ungrid{display:flex;flex-direction:column;gap:8px;margin-top:8px}
.unrow{border:1px solid var(--grid);border-left-width:3px;border-left-color:var(--vio);
border-radius:6px;padding:9px 12px;background:var(--s)}
.unhead{font-size:12.5px;color:var(--ink2)}
.unbody{font-size:12.5px;color:var(--ink2);margin-top:4px}
.undim{font-size:11px;color:var(--mut);margin-top:4px}
"""

TAB_JS = """
document.querySelectorAll('table.sortable').forEach(function(t){
  const tb=t.tBodies[0]; let cur=-1, asc=false;
  t.querySelectorAll('th').forEach(function(h,i){
    h.style.cursor='pointer';
    h.onclick=function(){
      asc = (i===cur) ? !asc : false; cur=i;
      const pairs=[]; let rows=[...tb.rows];
      for(let k=0;k<rows.length;k++){
        if(rows[k].classList.contains('det')) continue;
        const det = (rows[k+1] && rows[k+1].classList.contains('det')) ? rows[k+1] : null;
        pairs.push([rows[k], det]);
      }
      pairs.sort(function(a,b){
        const x=a[0].cells[i].dataset.sort, y=b[0].cells[i].dataset.sort;
        const nx=parseFloat(x), ny=parseFloat(y);
        const c = (!isNaN(nx)&&!isNaN(ny)) ? nx-ny : String(x).localeCompare(String(y));
        return asc?c:-c;});
      pairs.forEach(function(p){ tb.appendChild(p[0]); if(p[1]) tb.appendChild(p[1]); });
      t.querySelectorAll('th').forEach(function(h2,k){
        h2.classList.toggle('sorted',k===i); h2.classList.toggle('asc',k===i&&asc);});
    };
  });
});
document.querySelectorAll('tr.grow.clk').forEach(function(r){
  r.onclick=function(){
    const d=document.querySelector('tr.det[data-for="'+CSS.escape(r.dataset.g)+'"]');
    if(!d) return;
    const open=d.classList.toggle('on');
    r.classList.toggle('open', open);
  };
});
document.querySelectorAll('.tab').forEach(function(t){
  t.onclick=function(){
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
    document.querySelectorAll('.tabpane').forEach(x=>x.classList.remove('on'));
    t.classList.add('on');
    document.getElementById(t.dataset.pane).classList.add('on');
    window.scrollTo(0,0);
  };
});
document.querySelectorAll('.chip[data-rs]').forEach(function(c){
  c.onclick=function(){
    document.querySelectorAll('.chip[data-rs]').forEach(x=>x.classList.remove('on'));
    c.classList.add('on');
    var k=c.dataset.rs;
    document.querySelectorAll('table.research tbody tr').forEach(function(r){
      r.style.display=(k==='all'||r.dataset.rs===k)?'':'none';});};
});
"""

# Caliban-style navigation: the tab bar and a row of section chips stay
# pinned while scrolling, so any panel on a long tab is one click away; and each
# section's explanatory note shows its first line until asked for the rest, so
# the data leads and the methodology is there when wanted. Built client-side
# from the h2s already on the page, so no panel has to register itself.
NAV_CSS = """
.navbar{position:sticky;top:0;z-index:40;background:var(--p);
padding-top:4px;margin:0 -22px 6px;padding-left:22px;padding-right:22px;
border-bottom:1px solid var(--grid)}
.navbar .tabs{margin:6px 0 0;align-items:flex-end}
.xlink{margin-left:auto;color:var(--cool);font-size:12px;font-weight:600;
text-decoration:none;padding:9px 4px;white-space:nowrap}
.xlink:hover{text-decoration:underline}
.secnav{display:flex;gap:6px;overflow-x:auto;padding:8px 0 9px;scrollbar-width:thin}
.secnav:empty{display:none}
.secnav a{flex:0 0 auto;font-size:11px;color:var(--ink2);background:var(--s);
border:1px solid var(--grid);border-radius:99px;padding:3px 11px;text-decoration:none;
white-space:nowrap}
.secnav a:hover{border-color:var(--cool);color:var(--ink)}
.secnav a.on{background:var(--cool);border-color:var(--cool);color:#fff}
.tabpane h2,.aipane h2{scroll-margin-top:96px}
p.grpnote.fold{display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;
overflow:hidden;cursor:pointer;position:relative;padding-right:56px}
p.grpnote.fold::after{content:"more";position:absolute;right:0;top:0;color:var(--cool);
font-weight:600;background:var(--p);padding-left:6px}
p.grpnote.unfold{cursor:pointer}
@media(max-width:700px){.navbar{margin:0 -16px 6px;padding-left:16px;padding-right:16px}
.navbar .tabs{overflow-x:auto}.tab{padding:9px 10px}.xlink{display:none}}
/* Wide data tables scroll inside their own box on narrow screens instead of
   dragging the whole page sideways. */
@media(max-width:1000px){.wrap table{display:block;overflow-x:auto;max-width:100%}
.wrap svg{max-width:100%;height:auto}header .legend{display:none}
.wrap{padding-left:16px;padding-right:16px}}
@media(max-width:700px){.cwgrid,.si2grid,.dgrid,.cf3,.split,.fwgrid,.clist,
.wrap div[style*="grid-template-columns"]{grid-template-columns:1fr!important}
.aitabs{flex-wrap:wrap}.aihead{display:block}
.tabpane{max-width:100%;overflow-x:auto}}
"""

NAV_JS = """
(function(){
  var nav=document.querySelector('.secnav'); if(!nav) return;
  function slug(t,i){return 's'+i+'-'+t.toLowerCase().replace(/[^a-z0-9]+/g,'-').slice(0,40);}
  function short(t){return t.split(/\s+[\u2014\u2013-]\s+/)[0].replace(/^\d+\s*\u00b7\s*/,'');}
  function build(){
    var pane=document.querySelector('.tabpane.on')||document.querySelector('.wrap'); nav.innerHTML='';
    if(!pane) return;
    var hs=[...pane.querySelectorAll('h2')].filter(h=>h.offsetParent!==null);
    // A head that several sections share ("Short interest -- market-wide",
    // "Short interest -- covering vs building") is labelled by its tail instead.
    var heads=hs.map(h=>short(h.textContent.trim())), seen={};
    heads.forEach(k=>seen[k]=(seen[k]||0)+1);
    hs.forEach(function(h,i){
      if(!h.id) h.id=slug(h.textContent,i);
      var full=h.textContent.trim(), lab=heads[i];
      if(seen[lab]>1){var tail=full.split(/\s+[\u2014\u2013-]\s+/).slice(1).join(' ');
        if(tail) lab=lab+' \u00b7 '+tail.charAt(0).toUpperCase()+tail.slice(1);}
      var a=document.createElement('a'); a.href='#'+h.id; a.textContent=lab.length>42?lab.slice(0,40)+'\u2026':lab;
      a.title=h.textContent.trim();
      a.onclick=function(e){e.preventDefault();h.scrollIntoView({behavior:'smooth'});};
      nav.appendChild(a);
    });
  }
  document.querySelectorAll('.tab,.aitab').forEach(function(t){t.addEventListener('click',function(){setTimeout(build,0);});});
  build();
  // highlight the section in view
  window.addEventListener('scroll',function(){
    var best=null;
    nav.querySelectorAll('a').forEach(function(a){
      var h=document.getElementById(a.getAttribute('href').slice(1));
      if(h && h.getBoundingClientRect().top<140) best=a;});
    nav.querySelectorAll('a').forEach(a=>a.classList.toggle('on',a===best));
  },{passive:true});
  // fold long explanatory notes to their first line
  document.querySelectorAll('p.grpnote').forEach(function(p){
    if(p.textContent.length<180) return;
    p.classList.add('fold'); p.title='Click for the full note';
    p.addEventListener('click',function(e){
      if(e.target.closest('a')) return;
      p.classList.toggle('fold'); p.classList.toggle('unfold');});
  });
})();
"""

ETFX_JS = """
const EFC = __EFC__;
const ETF_PANES = [['price','Price'],['si','Short interest'],['dtc','Days to cover'],
                   ['cum','Cumulative flow'],['flow','Weekly flow']];
const ETF_FOOT = '<p class="chf">Price is unadjusted close with 50/200-day moving '
  + 'averages. Short interest and days-to-cover are FINRA bi-monthly settlements, held '
  + 'flat between prints (that is a real gap in the data, not a flat market). Flows are '
  + 'from etfdb\\'s daily fund-flow series summed to week-ending Friday. A ticker missing '
  + 'a pane simply is not covered by that source -- SI and flows are independent feeds '
  + 'and do not always cover the same funds. Y-axes rescale to the visible window.</p>';
(function(){
  var _lastBasket = null;
  document.querySelectorAll('[data-f]').forEach(function(el){
    el.addEventListener('click', function(){ _lastBasket = el.dataset.f; });
  });
  document.addEventListener('click', function(e){
    var el = e.target.closest('[data-e]');
    if (!el) return;
    var sym = el.dataset.e;
    var fromModal = !!el.closest('#ovc');
    var host = document.getElementById('ovc');
    var spec = EFC[sym];
    if (!spec) {
      host.innerHTML = '<p class="nochart">No combined price/SI/flow chart for ' + sym + ' yet.</p>';
      document.getElementById('ov').classList.add('on');
      return;
    }
    spec.primary = null;
    var back = (fromModal && _lastBasket)
      ? ('<p class="backlink" data-back="1">&larr; back to ' + _lastBasket + '</p>') : '';
    host.innerHTML = back + shell(spec.nm, spec.sub, ETF_PANES, spec, null, ETF_FOOT);
    PZ.init(host, spec);
    document.getElementById('ov').classList.add('on');
    var bl = host.querySelector('[data-back]');
    if (bl) bl.onclick = function(){
      var bspec = FCH[_lastBasket];
      if (!bspec) return;
      bspec.primary = 'flow';
      host.innerHTML = shell(_lastBasket, 'ETF dollar flows', FLOW_PANES, bspec, null,
        '<h4 style="margin:14px 0 6px">Constituents &mdash; latest week</h4>'
        + (FCON[_lastBasket] || '') + FLOW_FOOT);
      PZ.init(host, bspec);
    };
  });
})();
"""

def compose(pos_html, subsector, diary, css_extra, js_extra, asof, stockpage="",
            si_html="", data_html=""):
    import zoomjs, minichart
    zoom_js = minichart.MINI_JS + zoomjs.ZOOM_JS
    """Split report.py's output and rewrap it as tab 1."""
    m = re.search(r'<div class="wrap">(.*)</div>\s*<div id="ov">', pos_html, re.S)
    body = m.group(1) if m else pos_html
    ov = re.search(r'(<div id="ov">.*?</div></div></div>)', pos_html, re.S)
    ovh = ov.group(1) if ov else '<div id="ov"><div id="ovb"><span id="ovx">&times;</span><div id="ovc"></div></div></div>'
    scr = re.search(r'<script>(.*)</script>', pos_html, re.S)
    posjs = scr.group(1) if scr else ""
    css = re.search(r'<style>(.*?)</style>', pos_html, re.S)
    poscss = css.group(1) if css else ""
    head = re.search(r'(<header>.*?</header>)', body, re.S)
    hdr = head.group(1) if head else ""
    body = body.replace(hdr, "") if hdr else body
    # report.py's section 3 (raw-% short-interest movers) moves to the Short
    # interest tab with every other short-interest read.
    a = body.find("<h2>3 &middot; Short interest")
    b = body.find('<div class="note" style="margin-top:28px">', a)
    if a >= 0 and b > a:
        si_html = body[a:b].replace("<h2>3 &middot; ", "<h2>") + si_html
        body = body[:a] + body[b:]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Site &mdash; {asof}</title>
<style>{poscss}{TAB_CSS}{NAV_CSS}{css_extra}</style></head><body>
<div class="wrap">
{hdr.replace("Weekly Positioning Rundown", "Market Site")}
<div class="navbar">
<div class="tabs">
  <button class="tab on" data-pane="p-diary">Market</button>
  <button class="tab" data-pane="p-sub">Groups</button>
  <button class="tab" data-pane="p-stock">Stocks</button>
  <button class="tab" data-pane="p-pos">Positioning</button>
  <button class="tab" data-pane="p-si">Short interest</button>
  <button class="tab" data-pane="p-data">Data</button>
  <a class="xlink" href="__SENTIMENT_URL__">Sentiment &amp; Regime &rarr;</a>
</div>
<div class="secnav" aria-label="Sections on this tab"></div>
</div>
<div id="p-diary" class="tabpane on">{diary}</div>
<div id="p-sub" class="tabpane">{subsector}</div>
<div id="p-stock" class="tabpane">{stockpage}</div>
<div id="p-pos" class="tabpane">{body}</div>
<div id="p-si" class="tabpane">{si_html}</div>
<div id="p-data" class="tabpane">{data_html}</div>
</div>
{ovh}
<script>{posjs}
{TAB_JS}
{NAV_JS}
{js_extra}
</script>{zoom_js}</body></html>"""

def compose_sentiment(pos_html, top_html, aidesk_body, asof, site_url=""):
    """Standalone page: regime / liqn-stress / today's-read up top, then the full
    AI desk (ticker desk, chart builder, regime & positioning, global & liquidity)
    below. Shares poscss with the main site so the same CSS vars and component
    styles resolve identically on both pages without re-declaring them."""
    import zoomjs, minichart
    # The Global & liquidity panels mount minicharts client-side (6 of them on this
    # page) and the timeframe brushes are wired by ZOOM_JS. compose() has always
    # injected both; the first cut of this split forgot to, so those panels rendered
    # as empty boxes on a page that otherwise looked fine -- no error, just blank.
    zoom_js = minichart.MINI_JS + zoomjs.ZOOM_JS
    css = re.search(r'<style>(.*?)</style>', pos_html, re.S)
    poscss = css.group(1) if css else ""
    backlink = (f'<a class="xlink" style="margin-left:0" href="{html.escape(site_url)}">'
                '&larr; Market Site (market, groups, stocks, positioning)</a>') if site_url else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market Sentiment &amp; Regime &mdash; {asof}</title>
<style>{poscss}{TAB_CSS}{NAV_CSS}</style></head><body>
<div class="wrap">
<header><h1>Market Sentiment &amp; Regime</h1>
<p class="dim">As of {asof} &middot; regime read, positioning-unwind watch, and the
Global &amp; liquidity backdrop (VIX, Fed, Google Trends, correlations), plus the AI
ticker desk and chart builder.</p></header>
<div class="navbar"><div class="tabs" style="border:0">{backlink}</div>
<div class="secnav" aria-label="Sections on this page"></div></div>
{top_html}
{aidesk_body}
</div><script>{NAV_JS}</script>{zoom_js}</body></html>"""

BREADTH_COLS = [("adv","Adv"),("dec","Decl"),("net","Net"),
                ("hi52","Highs"),("lo52","Lows"),("hl_net","Net"),
                ("updn","Up/Dn"),
                ("pct5","5"),("pct10","10"),("pct21","21"),("pct50","50"),("pct200","200"),
                ("odb","MA stack")]

def _bcell(k, v):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return '<td class="dim">&ndash;</td>'
    if k in ("adv","dec","hi52","lo52"):  return f'<td>{int(v):,}</td>'
    if k == "net":     return f'<td class="{"up" if v>0 else "dn"}"><b>{int(v):+,}</b></td>'
    if k == "hl_net":  return f'<td class="{"up" if v>0 else "dn"}">{int(v):+,}</td>'
    if k == "updn":
        return f'<td class="{"up" if v >= 1 else "dn"}">{v:.2f}</td>'
    if k == "net_ratio": t = max(-1, min(1, v/60));  txt = f"{v:+.1f}%"
    elif k == "hl_ratio": t = max(-1, min(1, v/5));  txt = f"{v:+.1f}%"
    elif k == "odb":      t = max(-1, min(1, v/60)); txt = f"{v:+.1f}"
    else:                 t = max(-1, min(1, (v-50)/50)); txt = f"{v:.1f}%"
    a = abs(t)
    pole = (27,175,122) if t > 0 else (230,103,103)
    mid = (56,56,53)
    rgb = tuple(int(mid[i] + (pole[i]-mid[i])*a) for i in range(3))
    ink = "#fff" if a > 0.45 else "#c3c2b7"
    return f'<td style="background:rgb{rgb};color:{ink}">{txt}</td>'

def breadth_html(rows):
    if rows is None or not len(rows):
        return '<p class="none">Breadth not computed this run.</p>'
    body = []
    for _, r in rows.iterrows():
        tot = r["group"] == "TOTAL MARKET"
        body.append(f'<tr class="{"tot" if tot else ""}">'
                    f'<td class="nm">{html.escape(str(r["group"]))}</td>'
                    f'<td class="dim">{int(r["n"]):,}</td>'
                    + "".join(_bcell(k, r.get(k)) for k, _ in BREADTH_COLS) + "</tr>")
    head = ('<tr class="grp2"><th rowspan="2">Group</th><th rowspan="2">#</th>'
            '<th colspan="3">Advances / declines</th>'
            '<th colspan="3">New 52-week highs / lows</th>'
            '<th rowspan="2">Up/Dn vol</th>'
            '<th colspan="5">% above moving average</th>'
            '<th rowspan="2" title="mean z of the five %-above-MA readings vs their own year">MA stack</th></tr>'
            '<tr>' + "".join(f'<th>{l}</th>' for k, l in BREADTH_COLS
                             if k not in ("updn","odb")) + '</tr>')
    return ('<table class="sig breadth"><thead>' + head + '</thead><tbody>'
            + "".join(body) + '</tbody></table>')

def mcclellan_html(hist, label="TOTAL MARKET", weeks=260):
    if hist is None or label not in hist: return ""
    h = hist[label].tail(weeks)
    if h.empty: return ""
    def spark(s, col, band=None, height=64):
        v = pd.Series(s).astype(float).dropna()
        if len(v) < 5: return ""
        n = len(v); W2, P = 780, 8
        lo, hi = float(v.min()), float(v.max())
        if hi <= lo: hi = lo + 1
        pad = (hi-lo)*0.1; lo -= pad; hi += pad
        X = lambda i: P + i/(n-1)*(W2-2*P)
        Y = lambda x: height-P - (x-lo)/(hi-lo)*(height-2*P)
        d = "M" + " L".join(f"{X(i):.0f},{Y(x):.1f}" for i, x in enumerate(v))
        z = f'<line x1="{P}" y1="{Y(0):.1f}" x2="{W2-P}" y2="{Y(0):.1f}" stroke="#898781" stroke-dasharray="3 3"/>' if lo < 0 < hi else ""
        bands = ""
        if band:
            for b, c in band:
                if lo < b < hi:
                    bands += (f'<line x1="{P}" y1="{Y(b):.1f}" x2="{W2-P}" y2="{Y(b):.1f}" '
                              f'stroke="{c}" stroke-opacity=".55" stroke-dasharray="2 4"/>')
        return (f'<svg viewBox="0 0 {W2} {height}" width="100%" style="display:block">'
                f'{z}{bands}<path d="{d}" fill="none" stroke="{col}" stroke-width="1.6"/>'
                f'<circle cx="{X(n-1):.0f}" cy="{Y(v.iloc[-1]):.1f}" r="3" fill="{col}"/></svg>')
    sd = float(h.mco.std()) or 1
    return ('<div class="mcbox">'
            f'<div class="mch"><span>McClellan Oscillator</span>'
            f'<b class="{"up" if h.mco.iloc[-1]>0 else "dn"}">{h.mco.iloc[-1]:+.1f}</b>'
            f'<span class="dim">{h.mco.iloc[-1]/sd:+.2f}&sigma;</span></div>'
            + spark(h.mco, "#3987e5", [(2*sd, "#e66767"), (-2*sd, "#3987e5")])
            + f'<div class="mch"><span>Summation Index</span>'
              f'<b class="{"up" if h.mcsi.iloc[-1]>0 else "dn"}">{h.mcsi.iloc[-1]:+,.0f}</b></div>'
            + spark(h.mcsi, "#eda100")
            + f'<div class="mch"><span>% above 50d &mdash; {html.escape(label.title())}</span>'
              f'<b>{h.pct50.iloc[-1]:.0f}%</b></div>'
            + spark(h.pct50, "#1baf7a", [(80, "#e66767"), (20, "#3987e5")])
            + '</div>')

def _sbctx(row, key):
    """'-0.6 sigma - 22nd pct' sub-line. Raw counts without this are unreadable."""
    z, pc = row.get(f"{key}_z"), row.get(f"{key}_pct")
    if z is None or pc is None or not np.isfinite(z) or not np.isfinite(pc):
        return ""
    n = int(round(pc))
    sfx = "th" if 10 <= n % 100 <= 20 else {1:"st",2:"nd",3:"rd"}.get(n % 10, "th")
    return f'<i>{z:+.1f}&sigma; &middot; {n}{sfx} pct</i>'

def stockbee_html(row, h):
    if row is None: return ""
    def rat(v, good=2.0, bad=0.5):
        if not np.isfinite(v): return '<span class="dim">&ndash;</span>'
        t = "up" if v >= good else ("dn" if v <= bad else "")
        return f'<b class="{t}">{v:.2f}</b>'
    spark = ""
    if h is not None and len(h) > 10:
        v = h.r5.replace([np.inf, -np.inf], np.nan).dropna().tail(180)
        if len(v) > 5:
            W2, H2, P = 780, 60, 6
            lo, hi = float(v.min()), float(min(v.max(), 6))
            if hi <= lo: hi = lo + 1
            X = lambda i: P + i/(len(v)-1)*(W2-2*P)
            Y = lambda x: H2-P - (min(max(x, lo), hi)-lo)/(hi-lo)*(H2-2*P)
            d = "M" + " L".join(f"{X(i):.0f},{Y(x):.1f}" for i, x in enumerate(v))
            lines = "".join(
                f'<line x1="{P}" y1="{Y(b):.1f}" x2="{W2-P}" y2="{Y(b):.1f}" '
                f'stroke="{c}" stroke-opacity=".5" stroke-dasharray="2 4"/>'
                f'<text x="{W2-P-2}" y="{Y(b)-2:.1f}" fill="{c}" font-size="8" '
                f'text-anchor="end">{b:g}</text>'
                for b, c in ((2.0, "#1baf7a"), (1.0, "#898781"), (0.5, "#e66767"))
                if lo < b < hi)
            spark = (f'<svg viewBox="0 0 {W2} {H2}" width="100%" style="display:block">'
                     f'{lines}<path d="{d}" fill="none" stroke="#c3c2b7" stroke-width="1.6"/>'
                     f'<circle cx="{X(len(v)-1):.0f}" cy="{Y(v.iloc[-1]):.1f}" r="3" fill="#fff"/></svg>'
                     f'<p class="chf" style="margin-top:2px">5-day 4% ratio, last {len(v)} sessions. '
                     f'Guides at 2.0 (thrust), 1.0 (neutral) and 0.5 (washout).</p>')
    def cell(lbl, val, key=None, tone="", sub=""):
        ctx = _sbctx(row, key) if key else ""
        return (f'<div class="sbc"><span>{lbl}</span><b class="{tone}">{val}</b>'
                f'{ctx}{f"<i>{sub}</i>" if sub and not ctx else ""}</div>')
    t2108 = row.get("t2108")
    t2108s = f'{t2108:.0f}' if t2108 is not None and np.isfinite(t2108) else "&ndash;"
    return (f'<div class="sbbox"><div class="sbh">'
            f'<span class="sbl">STOCKBEE MARKET MONITOR</span>'
            f'<span class="sbv {row["tone"]}">{row["verdict"]}</span>'
            f'<span class="sbl">T2108 {t2108s}</span></div>'
            '<div class="sbgrid">'
            + cell("4% up today", f'{row["up4"]:,}', "up4", "up")
            + cell("4% down today", f'{row["dn4"]:,}', "dn4", "dn")
            + cell("Day ratio", rat(row["r1"]))
            + cell("5-day ratio", rat(row["r5"]), "r5")
            + cell("10-day ratio", rat(row["r10"]), "r10")
            + cell("T2108 (above 40d)", t2108s + "%", "t2108")
            + cell("25% up, 1 month", f'{row["up25m"]:,}', "up25m", "up")
            + cell("50% up, 1 month", f'{row.get("up50m",0):,}', "up50m", "up")
            + cell("25% up, quarter", f'{row["up25q"]:,}', "up25q", "up",
                   sub=f'vs {row["dn25q"]:,} down')
            + cell("13% up, 34d", f'{row["up13"]:,}', "up13", "up",
                   sub=f'vs {row["dn13"]:,} down')
            + '</div>' + spark +
            '<p class="chf">Momentum breadth, not advance/decline: a 4% day is a real '
            'move and a +0.1% day is noise, and an A/D line cannot tell them apart. '
            'Ratio above 2 is a thrust, below 0.5 a washout. <b>T2108</b> is the share of '
            'the universe above its own 40-day average &mdash; Bonde\'s overbought/oversold '
            'gauge, distinct from the 50-day column in the breadth table. Every count '
            'carries its own z-score and percentile against its trailing year, because a '
            'raw count says nothing about whether the reading is actually extreme.</p></div>')

def si_breadth_html(si, bars):
    """SHORT INTEREST - BREADTH FIRST.

    The four ranked tables answer "which names moved most". This answers the
    prior question: is the crowd covering or building, and is it happening in
    names that are actually working. Regressed out of the 30 Aug rebuild; the
    panel existed in the 18 Aug build and was never in CODE_BUNDLE.md.
    """
    if si is None or not len(si): return ""
    d = si.dropna(subset=["chg_z"])
    if len(d) < 20: return ""
    cov = int((d.chg_z <= -1).sum()); bld = int((d.chg_z >= 1).sum())
    n = len(d); tilt = 100.0*(cov-bld)/n
    med2w = float(d.pct_chg.median()); meddtc = float(d.dtc.median(skipna=True))
    deep = int((d.dtc >= 10).sum())
    up_names = set()
    try:
        c = bars.pivot_table(index="date", columns="symbol", values="close").sort_index()
        last = c.iloc[-1]; ma50 = c.rolling(50).mean().iloc[-1]; ma200 = c.rolling(200).mean().iloc[-1]
        up_names = {s for s in c.columns
                    if np.isfinite(last.get(s, np.nan)) and np.isfinite(ma200.get(s, np.nan))
                    and last[s] > ma50[s] and last[s] > ma200[s]}
    except Exception:
        pass
    cov_up = int(d[(d.chg_z <= -1) & (d.symbol.isin(up_names))].shape[0])
    bld_up = int(d[(d.chg_z >= 1) & (d.symbol.isin(up_names))].shape[0])
    verdict = "COVERING" if tilt >= 5 else ("BUILDING" if tilt <= -5 else "BALANCED")
    tone = "good" if tilt >= 5 else ("bad" if tilt <= -5 else "warn")
    def c_(lbl, val, sub, t=""):
        return f'<div class="sbc"><span>{lbl}</span><b class="{t}">{val}</b><i>{sub}</i></div>'
    return (f'<div class="sbbox"><div class="sbh">'
            f'<span class="sbl">SHORT INTEREST &mdash; BREADTH FIRST</span>'
            f'<span class="sbv {tone}">{verdict}</span></div><div class="sbgrid">'
            + c_("Covering hard", f'{cov}', 'z &le; &minus;1', "up")
            + c_("Building hard", f'{bld}', 'z &ge; +1', "dn")
            + c_("Breadth tilt", f'{tilt:+.0f}pp', 'covering minus building',
                 "up" if tilt>0 else "dn")
            + c_("Median 2w change", f'{med2w:+.1f}%', f'across {n} names')
            + c_("Median days to cover", f'{meddtc:.1f}', f'{deep} names &ge; 10 days')
            + c_("Covering &amp; in uptrend", f'{cov_up}', 'above 50d and 200d', "up")
            + c_("Building &amp; in uptrend", f'{bld_up}', 'above 50d and 200d', "dn")
            + '</div>'
            '<p class="chf">Breadth before names. <b>Covering hard</b> and <b>building '
            'hard</b> count the tails of the 2w/2w change z-distribution, so the tilt is '
            'the crowd\'s net direction rather than any one position. The two '
            '<b>in-uptrend</b> cells are the ones that matter for a momentum book: shorts '
            'covering in names already above their 50d and 200d is fuel behind strength, '
            'while shorts building in names still in uptrends is the squeeze setup.</p></div>')

def _rrg(df):
    try:
        import rrg
        return rrg.panel(df)
    except Exception as e:
        print("rotation map failed:", e, flush=True)
        return ""


def conf_panel(df, LEGS):
    """Ten-leg agreement, summarised. Leads the tab because the count is the
    first question -- how many separate reads say the same thing -- and the rank
    is only worth reading once you know how much of the evidence backs it."""
    if not LEGS or "c_n" not in df.columns:
        return ""
    cov = df["c_cov"].fillna(0)
    up  = df[df.c_dir == 1]; dn = df[df.c_dir == -1]
    def top(x, n=5):
        if not len(x): return '<li class="dim">none this week</li>'
        x = x.sort_values(["c_n", "c_spread"], ascending=[False, True]).head(n)
        return "".join(
            f'<li><b>{int(r.c_n)}/{int(r.c_cov)}</b> {html.escape(str(r["name"]))}'
            f'<span class="dim"> &middot; spread {int(r.c_spread)}</span></li>'
            for _, r in x.iterrows())
    # A group can rank well and still be a single-leg story. These are the ones
    # where the legs most violently disagree, which is where the rank lies most.
    div = df[cov >= 5].sort_values("c_spread", ascending=False).head(5)
    divl = "".join(
        f'<li>{html.escape(str(r["name"]))}'
        f'<span class="dim"> &middot; spread {int(r.c_spread)}, '
        f'{int(r.c_n)}/{int(r.c_cov)} agree</span></li>'
        for _, r in div.iterrows()) or '<li class="dim">none</li>'
    legcov = df.attrs.get("leg_cov", {})
    chips = "".join(
        f'<span class="chip{"" if legcov.get(k,0) >= len(df)*0.5 else " thin"}" '
        f'title="{html.escape(d)} &mdash; covers {legcov.get(k,0)} of {len(df)} groups">'
        f'{html.escape(l)}<i>{legcov.get(k,0)}</i></span>' for k, l, d in LEGS)
    n7u = int(((df.c_dir==1)&(df.c_n>=7)).sum())
    n7d = int(((df.c_dir==-1)&(df.c_n>=7)).sum())
    return (
      f'<div class="cfx"><h4>Confluence &mdash; how many of the {len(LEGS)} legs agree</h4>'
      '<p class="grpnote">Each leg scores all groups 0&ndash;99 and only votes '
      'outside 30/70, so a leg with no opinion stays silent instead of drifting to '
      'the middle. <b>Conf</b> is agreeing legs out of covering legs; <b>Spread</b> '
      'is the gap between the strongest and weakest leg &mdash; high agreement with '
      'a low spread is the clean read, a good rank with a wide spread is one leg '
      'carrying the story. Nothing is imputed: a leg that cannot see a group is '
      'marked not-covered and is excluded from both numbers.</p>'
      f'<div class="chips">{chips}</div>'
      f'<div class="cf3"><div><h5>Strongest agreement &mdash; up '
      f'<span class="dim">({n7u} at 7+)</span></h5><ul>{top(up)}</ul></div>'
      f'<div><h5>Strongest agreement &mdash; down '
      f'<span class="dim">({n7d} at 7+)</span></h5><ul>{top(dn)}</ul></div>'
      f'<div><h5>Widest disagreement <span class="dim">(read the rank with care)'
      f'</span></h5><ul>{divl}</ul></div></div></div>')


def subsector_board(df, src):
    if df is None or not len(df):
        return subsector_html(None)
    _nb = len(df)
    try:
        import subsector as _SS
        _rl = [l for l in open(_SS.ROSTER) if "|" in l]
        _nb, _nc = len(_rl), sum(len(l.split("|",1)[1].split(",")) for l in _rl)
    except Exception:
        _nc = int(df.n.sum())
    note = (f'Your <b>{_nb} custom baskets</b>, {_nc:,} constituents.' if src == "custom176" else
            'Built from the <b>exchange industry groups</b> with five or more liquid '
            'names, as a stand-in until the custom176 roster is in reach &mdash; drop '
            '<code>custom176-rosters.txt</code> into <code>~/pos/</code> and this switches '
            'over automatically, same columns.')
    def cell(v, scale, fmt="{:+.2f}%"):
        if v is None or not np.isfinite(v): return '<td class="dim" data-sort="-999">&ndash;</td>'
        t = max(-1, min(1, v/scale)); a = abs(t)
        pole = (27,175,122) if t > 0 else (230,103,103); mid = (56,56,53)
        rgb = tuple(int(mid[i] + (pole[i]-mid[i])*a) for i in range(3))
        ink = "#fff" if a > 0.45 else "#c3c2b7"
        return f'<td data-sort="{v:.4f}" style="background:rgb{rgb};color:{ink}">{fmt.format(v)}</td>'
    try:
        import confluence as _CF
        LEGS = df.attrs.get("legs", _CF.LEGS)
    except Exception:
        LEGS = df.attrs.get("legs", [])

    def ccell(r):
        n, dr, cov = r.get("c_n"), r.get("c_dir"), r.get("c_cov")
        if n is None or not np.isfinite(n) or not cov or int(dr or 0) == 0:
            return '<td class="dim" data-sort="-999">&ndash;</td>'
        n, dr, cov = int(n), int(dr), int(cov)
        arrow = "&#9650;" if dr > 0 else "&#9660;"
        cls = "up" if dr > 0 else "dn"
        # Sort key folds direction in so one click groups the strongest agreement
        # at one end and the strongest disagreement at the other.
        return (f'<td class="sc {cls}" data-sort="{dr*n:.0f}" '
                f'title="{n} of {cov} covering legs agree; {cov} of {len(LEGS)} legs cover this group">'
                f'{n}<span class="xd">/{cov}{arrow}</span></td>')

    def scell(r):
        v = r.get("c_spread")
        if v is None or not np.isfinite(v):
            return '<td class="dim" data-sort="-999">&ndash;</td>'
        v = float(v)
        cls = "warnx" if v >= 70 else ("dim" if v < 40 else "")
        return f'<td class="{cls}" data-sort="{v:.1f}">{v:.0f}</td>'

    def legstrip(r):
        cells = []
        for k, lbl, desc in LEGS:
            v = r.get(f"L_{k}")
            if v is None or not np.isfinite(v):
                cells.append(f'<div class="leg nc" title="{html.escape(lbl)} &mdash; '
                             f'{html.escape(desc)}: not covered for this group">'
                             f'<b>{html.escape(lbl)}</b><i>&ndash;</i></div>')
                continue
            v = int(v)
            tone = "hi" if v >= 70 else ("lo" if v <= 30 else "mid")
            cells.append(f'<div class="leg {tone}" title="{html.escape(lbl)} &mdash; '
                         f'{html.escape(desc)}">'
                         f'<b>{html.escape(lbl)}</b><i>{v}</i></div>')
        return '<div class="legs">' + "".join(cells) + '</div>'

    def xcell(r):
        # Median cross-check: the same roster and blend scored on the median
        # member. Wide gaps flag a group whose median and mean disagree.
        mr, x = r.get("med_rank"), r.get("xchk")
        if mr is None or not np.isfinite(mr):
            return '<td class="dim" data-sort="-999">&ndash;</td>'
        mr, x = int(mr), int(x)
        cls = "dim" if abs(x) < 10 else ("up" if x > 0 else "dn")
        return (f'<td class="sc {cls}" data-sort="{mr}" '
                f'title="median RS rank {mr}; RS rank is {x:+d} vs it">'
                f'{mr}<span class="xd">{x:+d}</span></td>')
    # Top-10 badges: a group sorted out of view on one column (say you're
    # sorted by Conf) can still be flagged as a top-10 performer on Week,
    # Month, Quarter or RS rank -- the four reads jman asked to keep visible
    # regardless of current sort. nlargest ignores NaN on its own.
    top_w = set(df.nlargest(10, "w").name) if df.w.notna().sum() else set()
    top_m = set(df.nlargest(10, "m").name) if df.m.notna().sum() else set()
    top_q = set(df.nlargest(10, "q").name) if df.q.notna().sum() else set()
    top_r = set(df.nlargest(10, "rs_rank").name) if df.rs_rank.notna().sum() else set()

    def badges(key):
        b = (('<i class="t10 tw" title="Top 10 &middot; 1-week return">W</i>' if key in top_w else '')
             + ('<i class="t10 tm" title="Top 10 &middot; 1-month return">M</i>' if key in top_m else '')
             + ('<i class="t10 tq" title="Top 10 &middot; 1-quarter return">Q</i>' if key in top_q else '')
             + ('<i class="t10 tr" title="Top 10 &middot; RS rank">R</i>' if key in top_r else ''))
        return f'<span class="t10grp">{b}</span>' if b else ''

    members = df.attrs.get("members", {})
    body = []
    for _, r in df.iterrows():
        dr = r.get("d_rank")
        drs = ('<td class="dim" data-sort="-999">new</td>' if dr is None or not np.isfinite(dr)
               else f'<td data-sort="{dr:.0f}" class="{"up" if dr>0 else ("dn" if dr<0 else "dim")}">{int(dr):+d}</td>')
        key = str(r["name"])
        has = key in members and len(members[key])
        body.append(
            f'<tr class="grow{" clk" if has else ""}" data-g="{html.escape(key)}">'
            f'<td class="sc" data-sort="{int(r["rank"])}">{int(r["rank"])}</td>'
            f'<td class="nm" data-sort="{html.escape(key)}">'
            + ('<span class="caret">&#9656;</span>' if has else '') + badges(key)
            + html.escape(key) + '</td>'
            f'<td class="dim" data-sort="{int(r["n"])}">{int(r["n"])}</td>'
            + cell(r["d"], 3) + cell(r["w"], 6) + cell(r["m"], 15) + cell(r["q"], 30)
            + cell(r["rs_m"], 15) + cell(r["rs_q"], 25)
            + f'<td class="sc" data-sort="{int(r["rs_rank"])}">{int(r["rs_rank"])}</td>'
            + xcell(r) + ccell(r) + scell(r)
            + cell(r["thrust"], 2.5, "{:+.2f}") + drs + '</tr>')
        if has:
            sub = "".join(
                f'<tr><td class="t">{html.escape(m["t"])}</td>'
                f'<td>{m["d"]:+.2f}%</td><td>{m["w"]:+.2f}%</td>'
                f'<td>{m["m"]:+.2f}%</td><td>{m["q"]:+.2f}%</td></tr>' for m in members[key])
            body.append(
                f'<tr class="det" data-for="{html.escape(key)}"><td colspan="15">'
                + (legstrip(r) if LEGS else '')
                + '<table class="mini cons"><thead><tr><th>Ticker</th><th>Day</th>'
                '<th>Week</th><th>Month</th><th>Quarter</th></tr></thead><tbody>'
                + sub + '</tbody></table></td></tr>')
    heads = ["#","Group","n","Day","Week","Month","Quarter","RS 1m","RS 3m","RS rank",
             "Med rank","Conf","Spread","Thrust","&Delta; rank"]
    hdr = "".join(f'<th data-s="{i}">{h}</th>' for i, h in enumerate(heads))
    return (conf_panel(df, LEGS)
            + _rrg(df)
            + f'<p class="grpnote">{note} <b>RS rank</b> blends a short read '
            f'(60% 1-week + 40% 1-month relative strength) with a long read '
            f'(45% 1-month + 55% 1-quarter), each percentiled against the board before '
            f'and after the blend &mdash; same short/long construction as the rotation map '
            f'below, just collapsed to one 0&ndash;99 number instead of an x/y position. '
            f'<b>Click any column header to sort</b>. <b>Click a group name</b> to drop down '
            f'its constituents. Thrust is the week in sigma of that group&rsquo;s own '
            f'two-year weekly history; &Delta; is the rank move since the previous stored '
            f'run. Returns and RS are your TradingView indicator&rsquo;s construction: '
            f'the <b>equal-weight average</b> of the group&rsquo;s members, relative to SPY '
            f'as a ratio. <b>Med rank</b> is the same roster and blend scored on the '
            f'<b>median</b> member instead, with RS rank&rsquo;s gap to it beside it: '
            f'<span class="up">green</span> means a few strong members are carrying the '
            f'group, <span class="dn">red</span> means the median member is stronger than '
            f'the average. The letter badges beside '
            f'a group name mark <b>top-10 out of {_nb}</b> on that read even when you&rsquo;ve '
            f'sorted by something else: <i class="t10 tw">W</i> week, '
            f'<i class="t10 tm">M</i> month, <i class="t10 tq">Q</i> quarter, '
            f'<i class="t10 tr">R</i> RS rank.</p>'
            '<table class="sig sub sortable"><thead><tr>' + hdr + '</tr></thead><tbody>'
            + "".join(body) + '</tbody></table>')

def sbstats_html():
    """Which Stockbee readings actually predict SPY -- the answer, not the hope."""
    import os
    p = f"{D}/sbstats.parquet"
    if not os.path.exists(p):
        return ""
    r = pd.read_parquet(p)
    if r is None or not len(r): return ""
    surv = int(r.bh.sum()); raw = int((r.p < 0.05).sum())
    import sbstats as _SS
    body = []
    for _, x in r.iterrows():
        v, tone = _SS.verdict(x)
        hit = x["hit"]; ex = x["med_excess"]
        body.append(
            f'<tr><td class="nmw">{html.escape(str(x["label"]))}</td>'
            f'<td class="dim">{x["tail"]}</td><td class="dim">{x["horizon"]}</td>'
            f'<td>{int(x["n"])}</td><td>{x["n_eff"]:.0f}</td>'
            f'<td class="{"up" if hit>=50 else "dn"}">{hit:.1f}%</td>'
            f'<td class="{"up" if ex>=0 else "dn"}">{ex:+.2f}%</td>'
            f'<td>{x["p"]:.3f}</td><td class="{tone}">{v}</td></tr>')
    heads = ["Series","Tail","Horizon","n","Eff n","Hit","Median excess","p","Verdict"]
    hdr = "".join(f"<th>{h}</th>" for h in heads)
    return ('<h2>Stockbee &mdash; does any of it predict SPY?</h2>'
            '<p class="grpnote">Every panel above shows a breadth reading in context, '
            'which answers <i>is this unusual</i>. This table asks the harder question: '
            'when a series hits its top or bottom 15%, what does SPY do next, and can '
            'that be told apart from chance. Measured on <b>ten years of daily bars '
            '(2016&ndash;2026, 3,111 symbols)</b> as <b>excess over the median forward '
            'return</b> of the same window, because SPY drifts up and a signal has to '
            'beat that drift, not ride it. Effective n is n divided by the horizon in '
            'days &mdash; overlapping windows share nearly all their return, and counting '
            'them as independent would inflate significance by an order of magnitude.</p>'
            f'<p class="grpnote"><b>Result: {surv} of {len(r)} tests survive '
            f'Benjamini-Hochberg at q=0.10, and {raw} reach even an uncorrected '
            f'p&lt;0.05.</b> Not one of these readings is a certified edge on this '
            'sample. That is a real finding, not a gap to paper over: use them to '
            'describe where the market is, not to justify a trade on their own. '
            'Several washout readings lean <i>inverted</i> at one week &mdash; '
            '"down 50% in a month" hits 42.7% &mdash; which is the opposite of how a '
            'capitulation signal is usually read, though it too is inside the noise.</p>'
            '<table class="sig sortable"><thead><tr>' + hdr + '</tr></thead><tbody>'
            + "".join(body) + '</tbody></table>')


def liqn_panel():
    try:
        import liqn
        return liqn.panel()
    except Exception as e:
        print("liqn panel failed:", e, flush=True)
        return ""


def sb_explorer_html():
    """Ten-year Stockbee history, clickable, with a percentile slider."""
    import os
    p = f"{D}/sb_hist_deep.parquet"
    if not os.path.exists(p): return ""
    try:
        import sbui, prices as _P
        h = pd.read_parquet(p)
        spy = _P.fetch_list(["SPY"])["SPY"]
        return sbui.panel(h, spy)
    except Exception as e:
        print("sb explorer failed:", e, flush=True)
        return ""


def si_history_panel(epx):
    try:
        import siui
        spy = epx["SPY"] if epx is not None and "SPY" in epx.columns else None
        if spy is None:
            import prices as _P
            spy = _P.fetch_list(["SPY"])["SPY"]
        return siui.panel(spy)
    except Exception as e:
        print("si history failed:", e, flush=True)
        return ""


def build(out=None):
    import report as RPT, regime as RG, freshness as FR, prices as P, universe as U
    import cot as C, flows as F, themes as TH, signals as SG, efficacy as EFF, audit as AUD
    AUD.run(strict=True)
    out = out or f"{D}/market_site.html"

    pos_path, cot_asof, si_settle = RPT.build()
    pos_html = open(pos_path).read()
    import gc; gc.collect()

    px = P.fetch(); epx = P.fetch_list(sorted(set(U.BASKET_PROXY.values())))
    reg = RG.build(px, epx, U.BASKET_PROXY)

    fl, _ = F.basket_flows()
    if fl is not None and len(fl):
        _fm = f"{D}/flow_meta.json"
        _et = json.load(open(_fm))["etfdb_through"] if os.path.exists(_fm) else None
        flow_row = FR.flows(fl.date.max(), est_from=_et)
    else:
        # PATCH A2: a feed with no data must never borrow another feed's as-of date
        flow_row = FR.unavailable(
            "ETF flows",
            "no flow history in this container - etfdb_flows.parquet was not "
            "restored (etfdb 403s Cloudflare here; master CSVs live on the Mac)",
            "weekly &middot; etfdb daily series summed to Friday")
    # si_settle is None when si_latest.parquet is absent (si.build() not run);
    # report.py already skips the FINRA chip in that case -- do the same here.
    fresh = [FR.cot(cot_asof)] + ([FR.finra(si_settle)] if si_settle is not None else []) + [flow_row]

    bp = f"{D}/cot_built.parquet"
    d = pd.read_parquet(bp) if os.path.exists(bp) else C.build(C.fetch())
    last, cur = C.latest(d)
    cur = cur[cur.cftc_contract_market_code.isin(U.COT_UNIVERSE)
              & cur.cftc_contract_market_code.isin(U.PRICE_MAP)].copy()
    cur["disp"] = [U.COT_UNIVERSE[c][0] for c in cur.cftc_contract_market_code]
    cur["cls"]  = [U.COT_UNIVERSE[c][1] for c in cur.cftc_contract_market_code]
    eff = pd.read_parquet(f"{D}/efficacy.parquet") if os.path.exists(f"{D}/efficacy.parquet") else None
    sig = SG.build(cur, eff)
    si = pd.read_parquet(f"{D}/si_latest.parquet") if os.path.exists(f"{D}/si_latest.parquet") else None
    conf = TH.build(cur, fl, si)

    rj = f"{D}/research_index.json"
    rows = research_index(json.load(open(rj))) if os.path.exists(rj) else []

    dm = f"{D}/diary.md"
    entries = open(dm).read() if os.path.exists(dm) else ""
    ent_html = ""
    if entries.strip():
        ent_html = "".join(
            f'<div class="diarynote">{html.escape(b.strip()).replace(chr(10), "<br>")}</div>'
            for b in entries.split("\n---\n") if b.strip())

    # Built BEFORE the second COT pass and freed straight after: holding the
    # 3,300-symbol bar frame alongside two copies of the 288k-row COT frame
    # OOM-killed the process with no traceback and no output at all.
    brows = bhist = sbrow = sbh = None; sub = None; subsrc = "none"; _bars_for_si = None
    try:
        import breadth as BR, stockbee as SB, subsector as SS, gc
        brows, bhist, bars = BR.build()
        sbrow, sbh = SB.build(bars)
        _bars_for_si = bars[bars.date >= bars.date.max() - pd.Timedelta(days=420)].copy()
        sub, subsrc = SS.build(bars, BR.universe(), epx)
        # Ten-leg confluence, attached before bars are freed -- the breadth leg
        # needs the full frame and there is no second chance after the del.
        try:
            import confluence as CFL, si as _SI
            _sil = None
            _p = f"{D}/si_latest.parquet"
            if os.path.exists(_p): _sil = pd.read_parquet(_p)
            _fb = {}
            if fl is not None and len(fl):
                _last = fl[fl.date == fl.date.max()]
                _col = "pct_1m" if "pct_1m" in _last.columns else None
                if _col: _fb = dict(zip(_last.basket, _last[_col]))
            sub = CFL.build(sub, bars=bars, bench=epx, si=_sil,
                            flow_by_basket=_fb,
                            group_basket={n: CFL.basket_of(n) for n in sub.name})
        except Exception as e:
            print("confluence failed:", e, flush=True)
        del bars; gc.collect()
    except Exception as e:
        print("breadth/stockbee/subsector failed:", e, flush=True)

    def _t(fn, label):
        try: return fn()
        except Exception as e:
            print(f"{label} failed:", e, flush=True); return ""

    # Cheap (a handful of API calls, a few seconds) and incremental, so it
    # runs on every rebuild rather than needing its own schedule -- see
    # earnrx.py's own docstring for why this can't just be a fixed lookback.
    _t(lambda: __import__("earnrx").fetch(), "earnrx fetch")

    # Tabs follow the order jman actually trades in -- is the tide rising
    # (Market), which groups lead (Groups), which names (Stocks), then who is
    # positioned where (Positioning) -- with the pipeline's own bookkeeping
    # (freshness, feed audit, research index) on a Data tab instead of mixed
    # into the market read. Every fragment below is the same string the old
    # single "Market diary" tab carried; only where it lands changed.
    _div = lambda: _t(lambda: __import__("diverge").html_panel(
        pd.read_parquet(f"{D}/diverge.parquet")), "divergences")
    # Dashboard first (quote tape, regime + leaderboard, heatmap) -- the
    # at-a-glance layer the reference sites lead with -- then the evidence.
    _rg = regime_html(reg)
    _rd = _t(lambda: auto_read(conf, sig, fl, si, reg, fresh, brows, sbrow), "today's read")
    _dash = _t(lambda: __import__("dashboard").top(sub, _rg, _rd), "dashboard")
    diary = ((_dash or (_rg + "<h2>Today's read &mdash; written from the data below</h2>" + _rd))
             + "<h2>Market internals &mdash; breadth</h2>"
             + '<p class="grpnote">Computed here over the screened US tape '
               '(mcap &ge; $300M, real common stock), not scraped. <b>MA stack</b> is the '
               'mean z-score of the five %-above-MA columns against their own trailing '
               'year: positive means the group sits higher in its own MA structure than '
               'it normally does.</p>'
             + breadth_html(brows)
             + stockbee_html(sbrow, sbh)
             + mcclellan_html(bhist)
             + sb_explorer_html()
             + _div()
             + _t(lambda: __import__("earnrx").html_panel(), "earnings-reaction breadth"))
    # Every short-interest read in one place, after COT and flows on the
    # Positioning tab -- it used to be split three ways across tabs.
    si_tab = ("<h2>Short interest &mdash; market-wide</h2>"
             + '<p class="grpnote">FINRA bi-monthly settlements, chain-linked so a '
               'change in the covered panel cannot masquerade as a change in '
               'positioning. Name-level covering and building are further down '
               'this tab.</p>'
             + _t(lambda: __import__("report").si_history_html(), "si index")
             + si_history_panel(epx)
             + si_breadth_html(si, _bars_for_si)
             + _t(lambda: __import__("etfsi").panel(), "etf si")
             # Basket-level SI across recent settlements, and the absolute
             # extremes. Only trustworthy since the FINRA backfill -- 30 of 94
             # settlements were silently missing before it.
             + _t(lambda: __import__("sibaskets").html_panel(), "si baskets"))
    # Crowd attention and crowd-ranked news are about names, so they sit with
    # the single-stock reads.
    # The crowd history chart now sits inside the crowd panel itself.
    crowd_extra = _t(lambda: __import__("liqnnews").panel(), "liqn news calendar")
    data_tab = (FR.panel(fresh)
             + _t(lambda: __import__("freshbar").panel(), "freshness")
             # Per-feed collection audit: each feed against its OWN cadence and
             # publication calendar, plus session-integrity checks.
             + "<h2>Feed collection audit &mdash; is every scheduled feed actually collecting?</h2>"
             + _t(lambda: __import__("feedcheck").html_panel(), "feed check")
             + "<h2>Research library</h2>"
             + '<p class="grpnote">Everything in the connected notes folder, indexed by '
               'source and date. Links open the local file.</p>'
             + research_html(rows)
             + ("<h2>Notes</h2>" + ent_html if ent_html else ""))

    # The regime box, today's read, internals, Stockbee and divergences all
    # lead Market Site's Market tab now, and freshness lives on its Data tab;
    # repeating them here only made two pages to keep in sync. This page keeps
    # what exists nowhere else: the crowd stress read, then the research desk.
    sentiment_top = _t(lambda: __import__("liqn").stress_panel(compact=True), "liqn stress")

    try:
        import tickerdesk as TDK, aitab as AIT, chartdata as CDA, json as _json
        _lib = None
        _lp = f"{D}/chartdata.json"
        if os.path.exists(_lp):
            _lib = _json.load(open(_lp))
        else:
            _lib = CDA.save()
        import allocation as ALLOC, unwind as UNW
        regime_tab_html = (_t(lambda: ALLOC.panel(sub, _lib), "allocation")
                           + _t(lambda: UNW.panel(cur), "positioning unwind"))
        _desk_idx = TDK.save(sub)
        import gli as GLI, globaltab as GT, vixterm as VX, trends as TR, econcal as EC, fedwatch as FW
        import ratioscan as RSC
        # globaltab's old 9-chart rotation/FCI panel was dropped here on
        # purpose -- jman trades short-term momentum, and a wall of
        # decade-long ratio charts doesn't inform a trade held for days.
        # liqn's Market Stress Monitor (regime classifier, today's reading)
        # is the lead content instead: a current-conditions read, same
        # spirit as GLI's composite, just built from 283 factors.
        #
        # Below that, everything that used to be scattered across Market
        # Diary (vix term structure, Google Trends, the macro calendar) now
        # lives here under explicit sections, plus two new ones: Commodities
        # (already-fetched chart-library series, just never given their own
        # home) and Fed (the new rate-path panel + the calendar + GLI's
        # composite, since credit/curve/dollar/breakevens are overwhelmingly
        # a Fed-policy-driven backdrop).
        globalpage = (
            _t(lambda: __import__("liqn").stress_panel(compact=False), "liqn stress full")
            + "<h2>Commodities</h2>"
            + '<p class="grpnote">Precious metals, energy and ags/base metals -- the '
              'complex behind the inflation-underpriced thesis. Series already live in '
              'the chart library, just given their own section instead of one line '
              'buried inside the liquidity composite below.</p>'
            + _t(lambda: GT.commodities_panel(_lib), "commodities")
            + "<h2>Fed</h2>"
            + '<p class="grpnote">Rate path, scheduled catalysts and the financial-'
              'conditions backdrop the Fed is setting -- three different instruments '
              'reading the same policy question.</p>'
            + _t(lambda: FW.panel(), "fed watch")
            + _t(lambda: EC.panel(), "econ calendar")
            + _t(lambda: GLI.panel(_lib), "gli composite")
            + "<h2>VIX</h2>"
            + '<p class="grpnote">The curve, not just the level -- see the panel note '
              'below for why backwardation matters more than where VIX sits.</p>'
            + _t(lambda: VX.panel(), "vix term")
            + "<h2>Sentiment</h2>"
            + '<p class="grpnote">Attention and crowd-positioning reads, not price. '
              'Pair with the short-interest and COT extremes elsewhere on the board '
              'rather than trading either alone.</p>'
            + _t(lambda: TR.panel(), "google trends")
            + _t(lambda: RSC.html_panel(), "ratio scan"))
        # Global & liquidity is no longer a top-level tab: it renders as the
        # fourth AI-desk sub-tab, beside Regime & positioning. Both answer the
        # same "what backdrop am I trading in" question, so they belong behind
        # one door rather than two. Built BEFORE this call because the panel
        # now takes globalpage as an argument.
        aidesk_body = AIT.panel(_desk_idx, _lib, regime_html=regime_tab_html,
                                global_html=globalpage)
    except Exception as e:
        print("ai desk failed:", e, flush=True)
        aidesk_body = ""
    # Single-stock work lives on its own page; the market-level reads (tilt,
    # concentration) stay on the front, where they belong.
    # Every short-interest read lives on its own tab; the Stocks tab keeps the
    # name-level lookup, overlap, earnings and crowd reads.
    _ov = _t(lambda: __import__("singlestock").html_panel(), "overlap/heat")
    _hi = _ov.find("<h2>Sector heat")
    _overlap, _heat = (_ov[:_hi], _ov[_hi:]) if _hi >= 0 else (_ov, "")
    stockpage = ("".join([
        _overlap,
        _t(lambda: __import__("earnings").calendar_panel(), "earnings calendar"),
        _t(lambda: __import__("liqn").crowd_panel(), "crowd"),
    ]))
    si_tab = (si_tab + _t(lambda: __import__("sitables").html_panel(), "si tables") + _heat)
    try:
        import etfx as EX
        efc = EX.build()
    except Exception as e:
        print("etfx combined specs failed:", e, flush=True)
        efc = {}
    js_extra = ETFX_JS.replace("__EFC__", json.dumps(efc, separators=(",", ":")))
    # The single-ticker report leads the Stocks tab; its renderer reads EFC, so
    # it runs after ETFX_JS defines it.
    try:
        import deskreport as DR
        desk_html = DR.panel(sub, efc, reg)
        js_extra += DR.LOOKUP_JS
    except Exception as e:
        print("desk report failed:", e, flush=True)
        desk_html = ""
    asof_str = f"{pd.Timestamp(cot_asof):%Y-%m-%d}"
    h = compose(pos_html, subsector_board(sub, subsrc), diary, "", js_extra,
                asof_str, stockpage=desk_html + stockpage + crowd_extra, si_html=si_tab,
                data_html=data_tab)
    open(out, "w").write(h)
    # Second page, same run: no pipeline is duplicated -- this only re-assembles
    # already-computed fragments into their own file.
    # compose_sentiment has always accepted site_url and rendered a back-link from
    # it; build() simply never passed one, so the cross-link was one-way -- Market
    # Site pointed here, nothing pointed back. SITE_URL is substituted by the
    # publish step the same way __SENTIMENT_URL__ is on the other page.
    sh = compose_sentiment(pos_html, sentiment_top, aidesk_body, asof_str,
                           site_url="__SITE_URL__")
    open(f"{D}/market_sentiment.html", "w").write(sh)
    return out, cot_asof, si_settle, reg

if __name__ == "__main__":
    p, c, s, r = build()
    print(p, pd.Timestamp(c).date(), pd.Timestamp(s).date() if s is not None else None,
          r["regime"], round(r["score"], 2))
