"""Upcoming earnings for every name this board tracks.

Earnings are the single biggest scheduled catalyst in a swing book -- a name at
a positioning extreme two days before it reports is a different proposition from
the same name four weeks out. Nasdaq publishes a per-day calendar covering the
whole tape; this pulls the forward window and keeps only names the board knows
about, then joins whatever else it holds on them.
"""
import urllib.request, ssl, json, time, os, sys
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")
OUT = f"{D}/earnings.parquet"
CTX = ssl._create_unverified_context()
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/124", "Accept": "application/json"}


def _day(date):
    u = f"https://api.nasdaq.com/api/calendar/earnings?date={date}"
    for a in range(2):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=H),
                                       timeout=25, context=CTX)
            j = json.loads(r.read())
            return ((j.get("data") or {}).get("rows")) or []
        except Exception:
            time.sleep(1 + a)
    return []


def _money(s):
    try: return float(str(s).replace("$", "").replace(",", ""))
    except Exception: return np.nan


def build(days=90, universe=None, verbose=True):
    start = pd.Timestamp.today().normalize()
    rows = []
    for i in range(days):
        d = start + pd.Timedelta(days=i)
        if d.dayofweek >= 5:      # the calendar is empty at weekends
            continue
        ds = d.strftime("%Y-%m-%d")
        got = _day(ds)
        for r in got:
            rows.append({
                "date": ds, "symbol": str(r.get("symbol") or "").upper(),
                "name": r.get("name"), "when": (r.get("time") or "").replace("time-", ""),
                "eps_est": r.get("epsForecast"), "n_est": r.get("noOfEsts"),
                "mcap": _money(r.get("marketCap")),
                "last_eps": r.get("lastYearEPS"), "fq": r.get("fiscalQuarterEnding"),
            })
        if verbose and (i + 1) % 20 == 0:
            print(f"  earnings {i+1}/{days} days, {len(rows)} rows",
                  file=sys.stderr, flush=True)
        time.sleep(0.12)
    if not rows: return None
    e = pd.DataFrame(rows).drop_duplicates(["symbol", "date"], keep="first")
    if universe:
        e = e[e.symbol.isin({u.upper() for u in universe})]
    e = e.sort_values(["date", "mcap"], ascending=[True, False])
    e.to_parquet(OUT)
    if verbose:
        print(f"earnings: {len(e):,} rows, {e.symbol.nunique():,} names, "
              f"{e.date.min()} -> {e.date.max()}", file=sys.stderr, flush=True)
    return e


if __name__ == "__main__":
    import json as _j
    u = None
    p = f"{D}/tickerdesk.json"
    if os.path.exists(p):
        u = list(_j.load(open(p))["idx"].keys())
    build(days=int(sys.argv[1]) if len(sys.argv) > 1 else 90, universe=u)


def html_panel(days=21, top=40):
    """The next few weeks, weighted to names the board already has a view on."""
    import json as _j, html as _h
    if not os.path.exists(OUT): return ""
    e = pd.read_parquet(OUT)
    if e is None or not len(e): return ""
    start = pd.Timestamp.today().normalize()
    e = e[(pd.to_datetime(e.date) >= start) &
          (pd.to_datetime(e.date) <= start + pd.Timedelta(days=days))].copy()
    if not len(e): return ""

    # join what the board knows, so the calendar is not just a list of dates
    desk = {}
    p = f"{D}/tickerdesk.json"
    if os.path.exists(p):
        desk = _j.load(open(p)).get("idx", {})
    def ctx(sym):
        x = desk.get(sym) or {}
        bits = []
        if x.get("si") and x["si"].get("chg_z") is not None:
            z = x["si"]["chg_z"]
            if abs(z) >= 1.5:
                bits.append(("si", f"shorts {'covering' if z < 0 else 'building'} {abs(z):.1f}&sigma;"))
        g = (x.get("groups") or [None])[0]
        if g: bits.append(("grp", str(g).split(" - ")[-1][:30]))
        return bits

    e["has_view"] = e.symbol.map(lambda s: s in desk)
    e = e.sort_values(["date", "has_view", "mcap"], ascending=[True, False, False])
    e = e.head(top)
    rows = []
    cur = None
    for _, r in e.iterrows():
        if r["date"] != cur:
            cur = r["date"]
            dd = pd.Timestamp(cur)
            rows.append(f'<tr class="dhdr"><td colspan="5">{dd:%a %d %b}</td></tr>')
        when = {"pre-market": "before open", "after-hours": "after close"}.get(
            r["when"], r["when"] or "")
        chips = "".join(f'<span class="ec ec-{k}">{v}</span>' for k, v in ctx(r["symbol"]))
        mc = (f"${r['mcap']/1e9:.1f}B" if np.isfinite(r["mcap"]) and r["mcap"] else "&ndash;")
        rows.append(
            f'<tr><td class="nm">{_h.escape(str(r["symbol"]))}</td>'
            f'<td class="nmw">{_h.escape(str(r["name"] or "")[:30])}</td>'
            f'<td class="dim">{when}</td><td>{mc}</td><td>{chips}</td></tr>')
    n_all = int(pd.read_parquet(OUT).symbol.nunique())
    return ('<h2>Earnings ahead</h2>'
            f'<p class="grpnote">Next {days} days, from a {n_all:,}-name calendar '
            'covering everything this board tracks. Names the board already has a '
            'view on sort first, and carry that view beside them &mdash; a '
            'positioning extreme days before a print is a different trade from the '
            'same extreme a month out. Refreshed with the weekly rebuild.</p>'
            '<table class="sig earn"><thead><tr><th>Ticker</th><th>Name</th>'
            '<th>When</th><th>Mkt cap</th><th>What the board says</th></tr></thead>'
            '<tbody>' + "".join(rows) + '</tbody></table>')


def calendar_panel(months=3):
    """A month grid you can page through, not a list.

    A list answers "what is next". A calendar answers "how is the month shaped"
    -- where the clusters are, which week is loaded, what to plan around. Names
    the board has a view on are marked, so a heavy week of names you already hold
    a position read on is visible at a glance.
    """
    import json as _j, html as _h
    if not os.path.exists(OUT): return ""
    e = pd.read_parquet(OUT)
    if e is None or not len(e): return ""
    e = e.copy(); e["d"] = pd.to_datetime(e.date)
    desk = {}
    p = f"{D}/tickerdesk.json"
    if os.path.exists(p):
        try: desk = _j.load(open(p)).get("idx", {})
        except Exception: desk = {}

    by = {}
    for _, r in e.iterrows():
        k = r["d"].strftime("%Y-%m-%d")
        by.setdefault(k, []).append({
            "t": r["symbol"], "w": (r["when"] or "")[:3],
            "m": None if not np.isfinite(r["mcap"]) else round(r["mcap"] / 1e9, 1),
            "v": 1 if r["symbol"] in desk else 0})
    for k in by:
        by[k].sort(key=lambda x: (-(x["v"]), -(x["m"] or 0)))
    months_avail = sorted({d[:7] for d in by})
    if not months_avail: return ""
    pay = {"by": by, "months": months_avail}
    return ('<h2>Earnings calendar</h2>'
            f'<p class="grpnote">Every reporting date across the {e.symbol.nunique():,} '
            'names this board tracks, laid out by month. Names the board already '
            'holds a view on are marked <span class="edot"></span> and sort first '
            'within the day, so a week loaded with positions you have a read on is '
            'visible at a glance. Use the arrows to move between months.</p>'
            '<div class="calwrap">'
            '<div class="calhead"><button id="cprev" class="btn ghost">&larr;</button>'
            '<b id="clab"></b><button id="cnext" class="btn ghost">&rarr;</button>'
            '<span class="dim" id="ccount"></span></div>'
            '<div id="calgrid" class="calgrid"></div></div>'
            f'<script id="caldata" type="application/json">{_j.dumps(pay, separators=(",", ":"))}</script>'
            + CAL_JS)


CAL_JS = """
<script>
(function(){
  var P=JSON.parse(document.getElementById('caldata').textContent);
  var BY=P.by, MS=P.months, mi=0;
  var today=new Date().toISOString().slice(0,10);
  var t7=today.slice(0,7); if(MS.indexOf(t7)>=0) mi=MS.indexOf(t7);
  var DOW=['Mon','Tue','Wed','Thu','Fri'];
  function draw(){
    var m=MS[mi], y=+m.slice(0,4), mo=+m.slice(5,7);
    document.getElementById('clab').textContent =
      new Date(y,mo-1,1).toLocaleDateString('en',{month:'long',year:'numeric'});
    document.getElementById('cprev').disabled = mi<=0;
    document.getElementById('cnext').disabled = mi>=MS.length-1;
    var first=new Date(y,mo-1,1), last=new Date(y,mo,0);
    var cells='', n=0;
    // start on the Monday of the first week
    var d=new Date(first); var sh=(d.getDay()+6)%7; d.setDate(d.getDate()-sh);
    cells+=DOW.map(function(x){return '<div class="cdow">'+x+'</div>';}).join('');
    while(d<=last || ((d.getDay()+6)%7)!==0){
      var dow=(d.getDay()+6)%7;
      if(dow<5){
        var key=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+
                String(d.getDate()).padStart(2,'0');
        var out=(d.getMonth()+1)!==mo;
        var list=BY[key]||[];
        n+=list.length;
        var chips=list.slice(0,9).map(function(x){
          return '<span class="etk'+(x.v?' has':'')+'" title="'+x.t+
            (x.m?(' · $'+x.m+'B'):'')+(x.w?(' · '+x.w):'')+'">'+x.t+'</span>';}).join('');
        if(list.length>9) chips+='<span class="emore">+'+(list.length-9)+'</span>';
        cells+='<div class="cday'+(out?' out':'')+(key===today?' now':'')+'">'+
          '<div class="cnum">'+d.getDate()+(list.length?'<i>'+list.length+'</i>':'')+'</div>'+
          chips+'</div>';
      }
      d.setDate(d.getDate()+1);
      if(d.getFullYear()>y+1) break;
    }
    document.getElementById('calgrid').innerHTML=cells;
    document.getElementById('ccount').textContent=n+' reports this month';
  }
  document.getElementById('cprev').onclick=function(){if(mi>0){mi--;draw();}};
  document.getElementById('cnext').onclick=function(){if(mi<MS.length-1){mi++;draw();}};
  draw();
})();
</script>
"""
