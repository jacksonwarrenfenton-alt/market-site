"""Ticker report data: everything the Stocks-tab lookup needs, precomputed.

One lookup should answer, for a stock or ETF: is its group leading, is the
stock leading its group, is it trending, is money flowing into its group ETF,
are shorts covering or building, how broad is its sector and subsector, what
does futures positioning say where a contract applies, and what it trades with
or against -- then a short verdict with the reasons. The browser renders it
(see LOOKUP_JS in this module); Python only ships compact numbers.

  TK[sym]   per ticker: group, 6-month price path, trend, RS, 52w-high
            distance, rank inside its group, short interest, correlations
  TG[group] per custom basket: best-matching ETF (by return correlation, so a
            bitcoin-miner basket maps to a miner ETF, not to XLK), members,
            subsector breadth, rank and RS, mapped futures contract
  TS[sec]   per sector: breadth (% above 50d / 200d)
  TC[code]  per futures contract: large-spec 52w percentile, last 52 weeks
The group ETF's flow and short-interest charts come from EFC, which the page
already carries.
"""
import os, re, json, sys
import numpy as np, pandas as pd

D = os.path.expanduser("~/pos")
CORR_SET = [("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("IWM", "Small caps"),
            ("TLT", "Long bonds"), ("UUP", "Dollar"), ("GLD", "Gold"), ("USO", "Oil"),
            ("BTC-USD", "Bitcoin"), ("HYG", "High yield"), ("XLE", "Energy"),
            ("XLF", "Financials"), ("SMH", "Semis"), ("XLU", "Utilities"), ("ARKK", "Spec growth")]
PATH_DAYS = 126   # ~6 months of closes, sampled every third day (page-size budget)
CORR_DAYS = 63


def _closes(bars):
    c = bars.pivot_table(index="date", columns="symbol", values="close").sort_index()
    return c.ffill(limit=3)


def _theme_for(group):
    """Group name -> (theme, [COT codes]) using themes.THEMES' own regexes."""
    import themes as TH
    low = group.lower()
    sec = low.split(" - ")[0]
    best = None
    for theme, (codes, _baskets, rx) in TH.THEMES.items():
        if not codes or not rx: continue
        if re.search(rx, low) or re.search(rx, "| " + sec):
            # prefer the most specific (shortest regex hit on the group part)
            if best is None or len(codes) < len(best[1]): best = (theme, codes)
    return best or (None, [])


def build(sub, efc, regime=None):
    efc_syms = list(efc)
    def _has(e, k):
        p = next((q for q in efc.get(e, {}).get('panes', []) if q.get('k') == k), None)
        return bool(p) and sum(v is not None and v == v for v in p['v'][-26:]) >= 4 and len(set(p['v'][-26:])) > 1
    import breadth as BR, prices as P
    bars = pd.read_parquet(f"{D}/bars.parquet")
    c = _closes(bars)
    c = c[c.index >= c.index.max() - pd.Timedelta(days=400)]
    epx = pd.read_parquet(f"{D}/etf_prices.parquet").sort_index()
    macro = P.fetch_list([t for t, _ in CORR_SET], cache=f"{D}/tape_prices.parquet",
                         maxage=3600, rng="1y")
    spy = macro["SPY"].dropna() if "SPY" in macro else epx["SPY"].dropna()

    rets = c.pct_change().iloc[-CORR_DAYS:]
    mret = macro.reindex(c.index).ffill().pct_change().iloc[-CORR_DAYS:]

    ma50, ma200 = c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
    last = c.iloc[-1]
    hi52 = c.iloc[-252:].max()
    def ret(n): return 100 * (c.iloc[-1] / c.iloc[-1 - n] - 1)
    spy_c = spy.reindex(c.index).ffill()
    def sret(n): return 100 * (spy_c.iloc[-1] / spy_c.iloc[-1 - n] - 1)
    rs1, rs3 = ret(21) - sret(21), ret(63) - sret(63)
    rspct = (rs3.rank(pct=True) * 0.6 + rs1.rank(pct=True) * 0.4).rank(pct=True) * 98 + 1

    # rosters
    ro = {}
    path = f"{D}/custom176-rosters.txt"
    for line in open(path):
        if "|" in line:
            g, s = line.rstrip("\n").split("|", 1)
            ro[g.strip()] = [x.strip().upper() for x in s.split(",") if x.strip()]
    s_by_name = sub.set_index("name") if sub is not None else pd.DataFrame()

    desk = json.load(open(f"{D}/tickerdesk.json")) if os.path.exists(f"{D}/tickerdesk.json") else {"idx": {}}
    idx = desk.get("idx", {})

    # group -> best ETF by correlation of the group's equal-weight daily returns
    er = epx[[e for e in efc_syms if e in epx.columns]].pct_change().iloc[-CORR_DAYS:]
    TG, TS = {}, {}
    cot = pd.read_parquet(f"{D}/cot_built.parquet") if os.path.exists(f"{D}/cot_built.parquet") else None
    TC = {}
    for g, mem in ro.items():
        m = [x for x in mem if x in c.columns]
        if not m: continue
        gr = rets[m].mean(axis=1)
        cc = er.corrwith(gr).dropna().sort_values(ascending=False)
        # The closest-trading ETF that actually carries each series: a miner
        # basket's best match may have flows but no FINRA short-interest file.
        # ...but only if it genuinely trades like the group; a loose match
        # (an EM fund standing in for bitcoin miners) misleads more than a gap.
        good = cc[cc >= 0.6].index
        fe = next((e for e in good if _has(e, "flow")), None)
        se = next((e for e in good if _has(e, "si")), None)
        etf, ec = (fe, round(float(cc[fe]), 2)) if fe else (None, None)
        sie, sic = (se, round(float(cc[se]), 2)) if se else (None, None)
        sec = g.split(" - ")[0] if " - " in g else "Other"
        above50 = (last[m] > ma50[m]).mean(); above200 = (last[m] > ma200[m]).mean()
        theme, codes = _theme_for(g)
        row = s_by_name.loc[g] if g in s_by_name.index else None
        order = sorted(m, key=lambda x: -(rs1.get(x) if np.isfinite(rs1.get(x, np.nan)) else -999))
        TG[g] = {
            "s": sec, "etf": etf, "ec": ec, "sie": sie, "sic": sic, "n": len(m),
            "b50": round(100 * above50), "b200": round(100 * above200),
            "rk": int(row["rank"]) if row is not None and np.isfinite(row["rank"]) else None,
            "rr": int(row["rs_rank"]) if row is not None and np.isfinite(row["rs_rank"]) else None,
            "rsm": round(float(row["rs_m"]), 1) if row is not None and np.isfinite(row["rs_m"]) else None,
            "mem": [[x, round(float(rs1[x]), 1) if np.isfinite(rs1.get(x, np.nan)) else None,
                     int(last[x] > ma50[x]) if np.isfinite(ma50.get(x, np.nan)) else None] for x in order],
            "th": theme, "cot": codes[:1],
        }
        for code in codes[:1]:
            if cot is not None and code not in TC:
                k = cot[cot.cftc_contract_market_code == code].sort_values("date").tail(52)
                if len(k):
                    TC[code] = {"nm": str(k.contract_market_name.iloc[-1]).title()[:40],
                                "p": round(float(k.ls_pctile52.iloc[-1])),
                                "s": [None if not np.isfinite(v) else round(float(v)) for v in k.ls_pctile52]}
    # sector breadth over every name in that sector's baskets
    for sec in {v["s"] for v in TG.values()}:
        m = sorted({x for g, v in TG.items() if v["s"] == sec for x, _, _ in v["mem"]})
        TS[sec] = {"b50": round(100 * (last[m] > ma50[m]).mean()),
                   "b200": round(100 * (last[m] > ma200[m]).mean()), "n": len(m)}

    # per ticker
    g_of = {}
    for g, v in TG.items():
        for x, _, _ in v["mem"]: g_of.setdefault(x, g)
    ranks = {g: {x: i + 1 for i, (x, _, _) in enumerate(v["mem"])} for g, v in TG.items()}
    mr = mret.dropna(axis=1, how="all")
    TK = {}
    for sym in c.columns:
        s = c[sym].dropna()
        if len(s) < 130: continue
        p = s.iloc[-PATH_DAYS::3]
        base = float(p.iloc[0])
        g = g_of.get(sym) or ((idx.get(sym, {}).get("groups") or [None])[0])
        corr = mr.corrwith(rets[sym]).dropna().sort_values()
        corr = corr.drop(sym, errors="ignore")
        e = idx.get(sym, {}).get("si") or {}
        TK[sym] = {
            "g": g,
            "p": [round(100 * (v / base - 1)) for v in p.values], "px": round(float(s.iloc[-1]), 2),
            "m50": int(last[sym] > ma50[sym]) if np.isfinite(ma50[sym]) else None,
            "m200": int(last[sym] > ma200[sym]) if np.isfinite(ma200[sym]) else None,
            "rs1": round(float(rs1[sym]), 1) if np.isfinite(rs1[sym]) else None,
            "rs3": round(float(rs3[sym]), 1) if np.isfinite(rs3[sym]) else None,
            "rr": int(rspct[sym]) if np.isfinite(rspct.get(sym, np.nan)) else None,
            "hi": round(float(100 * (last[sym] / hi52[sym] - 1)), 1),
            "gk": ranks.get(g, {}).get(sym), "gn": TG.get(g, {}).get("n"),
            "si": {k: e.get(k) for k in ("pct_chg", "chg_z", "dtc", "settle")} if e else None,
            "cp": [[k, round(float(v), 2)] for k, v in corr.tail(2).iloc[::-1].items() if v > 0.3],
            "cn": [[k, round(float(v), 2)] for k, v in corr.head(2).items() if v < -0.15],
        }
    # Futures that pertain by behaviour rather than by name: a group with no
    # themed contract still gets one if its members track an asset that has a
    # COT market (bitcoin miners -> CME bitcoin, gold miners -> gold, ...).
    ASSET_COT = {"BTC-USD": "133741", "GLD": "088691", "USO": "067651",
                 "TLT": "043602", "UUP": "098662", "QQQ": "209742", "SPY": "13874A",
                 "IWM": "239742"}
    for g, v in TG.items():
        if v["cot"]: continue
        m = [x for x, _, _ in v["mem"] if x in rets.columns]
        if not m: continue
        cc = mr[[a for a in ASSET_COT if a in mr.columns]].corrwith(rets[m].mean(axis=1)).dropna()
        cc = cc[cc.abs() >= 0.4].sort_values(ascending=False)
        for a in cc.index:
            code = ASSET_COT[a]
            if cot is not None and code not in TC:
                k = cot[cot.cftc_contract_market_code == code].sort_values("date").tail(52)
                if len(k):
                    TC[code] = {"nm": str(k.contract_market_name.iloc[-1]).title()[:40],
                                "p": round(float(k.ls_pctile52.iloc[-1])),
                                "s": [None if not np.isfinite(x) else round(float(x)) for x in k.ls_pctile52]}
            if code in TC:
                v["cot"] = [code]; v["cotr"] = round(float(cc[a]), 2); break

    # ETFs get the same per-name read (price path, trend, RS, correlations),
    # from the ETF price cache, so an ETF lookup is as complete as a stock's.
    ec_ = epx[[e for e in efc_syms if e in epx.columns]].ffill(limit=3)
    ec_ = ec_[ec_.index >= ec_.index.max() - pd.Timedelta(days=400)]
    spy_e = spy.reindex(ec_.index).ffill()
    eret = ec_.pct_change().iloc[-CORR_DAYS:]
    mre = macro.reindex(ec_.index).ffill().pct_change().iloc[-CORR_DAYS:].dropna(axis=1, how="all")
    for e in ec_.columns:
        if e in TK: continue
        s_ = ec_[e].dropna()
        if len(s_) < 210: continue
        p = s_.iloc[-PATH_DAYS::3]; base = float(p.iloc[0])
        m50, m200 = s_.rolling(50).mean().iloc[-1], s_.rolling(200).mean().iloc[-1]
        r = lambda n: 100 * (s_.iloc[-1] / s_.iloc[-1 - n] - 1)
        sr = lambda n: 100 * (spy_e.iloc[-1] / spy_e.iloc[-1 - n] - 1)
        corr = mre.corrwith(eret[e]).dropna().drop(e, errors="ignore").sort_values()
        ac = mre[[a for a in ASSET_COT if a in mre.columns]].corrwith(eret[e]).dropna()
        ac = ac[ac.abs() >= 0.4].sort_values(ascending=False)
        ecot = next(([ASSET_COT[a], round(float(ac[a]), 2)] for a in ac.index if ASSET_COT[a] in TC), None)
        if ecot is None and cot is not None:
            for a in ac.index:
                k = cot[cot.cftc_contract_market_code == ASSET_COT[a]].sort_values("date").tail(52)
                if len(k):
                    TC[ASSET_COT[a]] = {"nm": str(k.contract_market_name.iloc[-1]).title()[:40],
                                        "p": round(float(k.ls_pctile52.iloc[-1])),
                                        "s": [None if not np.isfinite(x) else round(float(x)) for x in k.ls_pctile52]}
                    ecot = [ASSET_COT[a], round(float(ac[a]), 2)]; break
        TK[e] = {"g": None, "etf": 1, "cot": ecot,
                 "p": [round(100 * (x / base - 1)) for x in p.values], "px": round(float(s_.iloc[-1]), 2),
                 "m50": int(s_.iloc[-1] > m50), "m200": int(s_.iloc[-1] > m200),
                 "rs1": round(float(r(21) - sr(21)), 1), "rs3": round(float(r(63) - sr(63)), 1),
                 "rr": None, "hi": round(float(100 * (s_.iloc[-1] / s_.iloc[-252:].max() - 1)), 1),
                 "si": None,
                 "cp": [[k, round(float(x), 2)] for k, x in corr.tail(2).iloc[::-1].items() if x > 0.3],
                 "cn": [[k, round(float(x), 2)] for k, x in corr.head(2).items() if x < -0.15]}

    labels = dict(CORR_SET)
    reg = None
    if regime is not None:
        reg = {"r": regime.get("regime"), "s": round(float(regime.get("score", 0)), 2)}
    return {"TK": TK, "TG": TG, "TS": TS, "TC": TC, "L": labels, "R": reg,
            "asof": str(c.index.max().date())}


CSS = """
.lk{border:1px solid var(--grid);border-radius:8px;background:var(--s);padding:14px 16px;margin:6px 0 18px}
.lkbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.lkbar input{font:inherit;font-size:14px;background:var(--p);color:var(--ink);border:1px solid var(--base);
border-radius:6px;padding:8px 12px;width:220px;text-transform:uppercase}
.lkbar input:focus{outline:2px solid var(--cool);outline-offset:-1px}
.lkbar .dim{font-size:11px}
.lkout{margin-top:12px}
.lkhead{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:10px}
.lkhead h3{margin:0;font-size:20px}
.lkhead .px{font-size:15px;font-variant-numeric:tabular-nums}
.vd2{font-size:12px;font-weight:800;letter-spacing:.06em;padding:3px 10px;border-radius:4px}
.vd2.good{background:rgba(27,175,122,.18);color:#3fd39b;border:1px solid rgba(27,175,122,.5)}
.vd2.warn{background:rgba(250,178,25,.12);color:#fab219;border:1px solid rgba(250,178,25,.45)}
.vd2.bad{background:rgba(230,103,103,.14);color:#f08a8a;border:1px solid rgba(230,103,103,.5)}
.lkgrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:14px}
@media(max-width:1000px){.lkgrid{grid-template-columns:1fr}}
ul.why{list-style:none;margin:0;padding:0}
ul.why li{font-size:12.5px;line-height:1.5;padding:5px 0 5px 22px;border-bottom:1px solid var(--grid);position:relative;color:var(--ink2)}
ul.why li:before{position:absolute;left:2px;font-weight:800}
ul.why li.p:before{content:"+";color:#1baf7a} ul.why li.n:before{content:"\\2212";color:#e66767}
ul.why li.o:before{content:"\\2022";color:var(--mut)}
ul.why b{color:var(--ink)}
.mini4{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.mc{border:1px solid var(--grid);border-radius:6px;padding:8px 10px;background:var(--p)}
.mc h6{margin:0 0 4px;font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);
display:flex;justify-content:space-between;gap:8px}
.mc h6 b{color:var(--ink2);font-weight:700;letter-spacing:0;text-transform:none;font-size:11px}
.mc svg{width:100%;height:64px;display:block}
.mc .na{font-size:11px;color:var(--mut);padding:20px 0;text-align:center}
.lkrow{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:14px}
@media(max-width:1000px){.lkrow{grid-template-columns:1fr}}
.lkrow h5{margin:0 0 6px;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--mut)}
.mem{display:flex;flex-wrap:wrap;gap:4px}
.mem a{font-size:11px;padding:2px 7px;border-radius:4px;border:1px solid var(--grid);color:var(--ink2);
text-decoration:none;cursor:pointer;font-variant-numeric:tabular-nums}
.mem a.me{border-color:var(--cool);color:#fff}
.mem a i{font-style:normal;margin-left:4px}
.bb{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--ink2);margin:4px 0}
.bb span{width:118px;color:var(--mut)} .bb em{font-style:normal;width:34px;text-align:right;font-variant-numeric:tabular-nums}
.bb i{flex:1;height:8px;background:#141413;border-radius:2px;position:relative;overflow:hidden}
.bb i b{position:absolute;left:0;top:0;bottom:0;border-radius:2px}
.cr{display:flex;flex-wrap:wrap;gap:5px}
.cr span{font-size:11px;padding:2px 8px;border-radius:99px;border:1px solid var(--grid)}
.cr .p{border-color:rgba(27,175,122,.5);color:#3fd39b} .cr .n{border-color:rgba(230,103,103,.5);color:#f08a8a}
"""

LOOKUP_JS = r"""
(function(){
var X=window.__LK__; if(!X) return;
var box=document.getElementById('lkout'), inp=document.getElementById('lkin');
function f1(v,s){return v==null?'&ndash;':(v>0?'+':'')+v.toFixed(1)+(s||'');}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function spark(v,o){o=o||{};var a=v.filter(x=>x!=null);if(a.length<2)return '<div class="na">no data</div>';
 var W=300,H=64,mn=Math.min.apply(null,a.concat(o.zero?[0]:[])),mx=Math.max.apply(null,a.concat(o.zero?[0]:[]));if(mx===mn)mx=mn+1;
 var x=i=>(i/(v.length-1)*W).toFixed(1),y=u=>(H-3-(u-mn)/(mx-mn)*(H-6)).toFixed(1),s='';
 if(o.bars){var bw=W/v.length;v.forEach(function(u,i){if(u==null)return;var y0=y(0),y1=y(u);
   s+='<rect x="'+(i*bw).toFixed(1)+'" width="'+Math.max(bw-1,1).toFixed(1)+'" y="'+Math.min(y0,y1)+'" height="'+Math.abs(y0-y1).toFixed(1)+'" fill="'+(u>=0?'#1baf7a':'#e66767')+'"/>';});}
 else{var d='';v.forEach(function(u,i){if(u==null)return;d+=(d?'L':'M')+x(i)+' '+y(u);});
   if(o.band){s+='<rect x="0" width="'+W+'" y="'+y(o.band[1])+'" height="'+(y(o.band[0])-y(o.band[1]))+'" fill="rgba(255,255,255,.04)"/>';}
   s+='<path d="'+d+'" fill="none" stroke="'+(o.c||'#3987e5')+'" stroke-width="1.6"/>';}
 if(o.zero&&mn<0&&mx>0)s+='<line x1="0" x2="'+W+'" y1="'+y(0)+'" y2="'+y(0)+'" stroke="#383835"/>';
 return '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+s+'</svg>';}
function pane(spec,k,n){if(!spec)return null;var p=spec.panes.find(q=>q.k===k);if(!p)return null;return p.v.slice(-n);}
function bar(lab,v,thr){var c=v>=60?'#1baf7a':v<=35?'#e66767':'#fab219';
 return '<div class="bb"><span>'+lab+'</span><i><b style="width:'+v+'%;background:'+c+'"></b></i><em>'+v+'%</em></div>';}
function show(sym){
 sym=(sym||'').trim().toUpperCase(); if(!sym) return;
 var t=X.TK[sym], EF=(typeof EFC!=='undefined'?EFC:{}), ef=EF[sym];
 if(!t&&!ef){box.innerHTML='<p class="dim">'+esc(sym)+' is not in the screened universe (US common stock over $300M) or the ETF set.</p>';return;}
 t=t||{}; var g=X.TG[t.g]||null, sec=g?X.TS[g.s]:null, etf=g&&g.etf, E=EF[ef?sym:etf], sie=ef?sym:(g&&g.sie), ES=EF[sie];
 var W=[], score=0;
 function add(cls,txt,w){W.push('<li class="'+cls+'">'+txt+'</li>');score+=w||0;}
 if(g&&g.rk){var top=g.rk<=50,bot=g.rk>=200;
   add(top?'p':bot?'n':'o','Group <b>'+esc(t.g.split(' - ').slice(1).join(' - ')||t.g)+'</b> ranks <b>#'+g.rk+' of 252</b> (RS '+g.rr+', '+f1(g.rsm,'%')+' vs SPY over 1M)'+(top?' &mdash; a leading group':bot?' &mdash; a lagging group':''),top?2:bot?-2:0);}
 if(t.gk&&t.gn){var lead=t.gk<=Math.max(2,Math.ceil(t.gn/4)),lag=t.gk>t.gn*0.75;
   add(lead?'p':lag?'n':'o','<b>#'+t.gk+' of '+t.gn+'</b> inside its group on 1M relative strength'+(lead?' &mdash; a leader of the group':lag?' &mdash; one of the group’s laggards':''),lead?1:lag?-1:0);}
 if(t.m50!=null){var up=t.m50&&t.m200,dn=!t.m50&&!t.m200;
   add(up?'p':dn?'n':'o',(up?'Uptrend: above its 50d and 200d':dn?'Downtrend: below its 50d and 200d':(t.m50?'Above its 50d, below its 200d':'Below its 50d, above its 200d'))+(t.hi!=null?' &middot; '+(t.hi>-0.5?'<b>at a 52-week high</b>':Math.abs(t.hi).toFixed(1)+'% off its 52-week high'):''),up?1.5:dn?-1.5:0);}
 if(t.rs1!=null)add(t.rs1>0&&t.rs3>0?'p':t.rs1<0&&t.rs3<0?'n':'o','Vs SPY: <b>'+f1(t.rs1,'%')+'</b> over 1M, <b>'+f1(t.rs3,'%')+'</b> over 3M (RS rating '+t.rr+')',t.rs1>0&&t.rs3>0?1:t.rs1<0&&t.rs3<0?-1:0);
 if(E){var fl=pane(E,'flow',26)||[],f4=fl.slice(-4).reduce((a,b)=>a+(b||0),0),sd=Math.sqrt(fl.reduce((a,b)=>a+(b||0)*(b||0),0)/Math.max(fl.length,1))*2;
   if(fl.length)add(f4>sd?'p':f4<-sd?'n':'o','Money into <b>'+esc(ef?sym:etf)+'</b>'+(ef?'':' (the ETF that trades most like this group, r='+g.ec+')')+': <b>'+(f4>=0?'+':'')+'$'+f4.toFixed(0)+'M</b> over 4 weeks'+(f4>sd?' &mdash; unusually strong':f4<-sd?' &mdash; unusually heavy outflow':''),f4>sd?1:f4<-sd?-1:0);}
 if(t.si&&t.si.chg_z!=null){var z=t.si.chg_z,pc=t.si.pct_chg;
   add(z<=-1?'p':'o',(z>=1?'Shorts <b>building</b> ':z<=-1?'Shorts <b>covering</b> ':'Short interest ')+f1(pc,'%')+' at the '+esc(t.si.settle)+' settlement, '+t.si.dtc+' days to cover'+(z>=1?' &mdash; fuel if it breaks out, pressure if it fails':''),z<=-1?0.5:0);}
 if(sec)add(sec.b50>=60?'p':sec.b50<=35?'n':'o','Sector breadth (<b>'+esc(g.s)+'</b>): '+sec.b50+'% of names above their 50d',sec.b50>=60?0.5:sec.b50<=35?-0.5:0);
 if(g)add(g.b50>=60?'p':g.b50<=35?'n':'o','Subsector breadth: '+g.b50+'% of the group above its 50d, '+g.b200+'% above its 200d',g.b50>=60?0.5:g.b50<=35?-0.5:0);
 var C=g&&g.cot&&g.cot[0]?X.TC[g.cot[0]]:(t.cot?X.TC[t.cot[0]]:null), cr_=g?g.cotr:(t.cot?t.cot[1]:null);
 if(C)add(C.p>=90||C.p<=10?'n':'o','Futures (<b>'+esc(C.nm)+'</b>'+(cr_?', which this '+(g?'group':'fund')+' tracks at r='+cr_:'')+'): large specs at the <b>'+C.p+(C.p%100>=11&&C.p%100<=13?'th':['th','st','nd','rd'][C.p%10]||'th')+'</b> 52-week percentile'+(C.p>=90?' &mdash; crowded long':C.p<=10?' &mdash; washed out':''),C.p>=90?-0.5:0);
 if(X.R)add('o','Market regime <b>'+esc(X.R.r)+'</b> ('+(X.R.s>0?'+':'')+X.R.s+')'+(X.R.r==='DOWNTREND'?' &mdash; long setups fight the tape':''),X.R.r==='DOWNTREND'?-1:X.R.r==='BREAKOUT'?0.5:0);
 var v=score>=3?['good','CONSTRUCTIVE']:score<=-2?['bad','AVOID / SHORT SIDE']:['warn','MIXED'];
 var px=t.px!=null?'$'+t.px.toLocaleString():'';
 var h='<div class="lkhead"><h3>'+esc(sym)+'</h3><span class="px">'+px+'</span><span class="vd2 '+v[0]+'">'+v[1]+'</span>'
   +'<span class="dim">'+(t.g?esc(t.g):(ef?esc(ef.nm):''))+'</span></div>';
 var charts=[];
 charts.push('<div class="mc"><h6>'+esc(sym)+' &middot; 6 months<b>'+f1(t.p?t.p[t.p.length-1]:null,'%')+'</b></h6>'+(t.p?spark(t.p,{c:'#c3c2b7',zero:true}):'<div class="na">no price path</div>')+'</div>');
 var fl=pane(E,'flow',26), si=pane(ES,'si',26);
 charts.push('<div class="mc"><h6>'+esc(ef?sym:(etf||'group ETF'))+' weekly flows, 6 months<b>'+(ef?'$M':(g&&g.ec?'r='+g.ec+' &middot; $M':''))+'</b></h6>'+(fl?spark(fl,{bars:true,zero:true}):'<div class="na">no ETF with flow data trades closely with this group</div>')+'</div>');
 charts.push('<div class="mc"><h6>'+esc(sie||'group ETF')+' short interest<b>'+(!ef&&g&&g.sic?'r='+g.sic+' &middot; ':'')+'shares</b></h6>'+(si?spark(si,{c:'#9085e9'}):'<div class="na">no ETF with short-interest data trades closely with this group</div>')+'</div>');
 charts.push('<div class="mc"><h6>'+(C?esc(C.nm)+' &middot; large specs':'Futures positioning')+'<b>'+(C?C.p+'th pct':'')+'</b></h6>'+(C?spark(C.s,{c:'#fab219',band:[10,90]}):'<div class="na">no futures contract maps to this group</div>')+'</div>');
 h+='<div class="lkgrid"><div><ul class="why">'+W.join('')+'</ul></div><div class="mini4">'+charts.join('')+'</div></div>';
 var row='';
 if(g){row+='<div><h5>Group stocks &middot; 1M RS vs SPY</h5><div class="mem">'+g.mem.slice(0,24).map(function(m){
   return '<a data-lk="'+m[0]+'" class="'+(m[0]===sym?'me':'')+'">'+m[0]+'<i style="color:'+(m[1]>0?'#3fd39b':'#f08a8a')+'">'+f1(m[1])+'</i></a>';}).join('')+'</div></div>';}
 row+='<div><h5>Breadth</h5>'+(sec?bar(g.s+' &gt;50d',sec.b50)+bar(g.s+' &gt;200d',sec.b200):'')+(g?bar('Group &gt;50d',g.b50)+bar('Group &gt;200d',g.b200):'')+'</div>';
 var cr=(t.cp||[]).map(c=>'<span class="p">'+esc(X.L[c[0]]||c[0])+' +'+c[1].toFixed(2)+'</span>').concat((t.cn||[]).map(c=>'<span class="n">'+esc(X.L[c[0]]||c[0])+' '+c[1].toFixed(2)+'</span>'));
 row+='<div><h5>Moves with / against (3M daily)</h5><div class="cr">'+(cr.join('')||'<span>no strong correlation</span>')+'</div></div>';
 h+='<div class="lkrow">'+row+'</div>';
 box.innerHTML=h;
 box.querySelectorAll('[data-lk]').forEach(a=>a.onclick=function(){inp.value=a.dataset.lk;show(a.dataset.lk);});
}
document.getElementById('lkgo').onclick=function(){show(inp.value);};
inp.addEventListener('keydown',function(e){if(e.key==='Enter')show(inp.value);});
var dl=document.getElementById('lklist'); if(dl) dl.innerHTML=Object.keys(X.TK).concat(Object.keys(typeof EFC!=='undefined'?EFC:{})).slice(0,6000).map(s=>'<option value="'+s+'">').join('');
var first=Object.keys(X.TG).length? X.TG[Object.keys(X.TG)[0]].mem[0][0] : null;
show(first||'SPY'); inp.value=first||'';
})();
"""


def panel(sub, efc_syms, regime=None):
    data = build(sub, efc_syms, regime)
    print(f"desk report: {len(data['TK'])} tickers, {len(data['TG'])} groups, "
          f"{len(data['TC'])} futures contracts", file=sys.stderr, flush=True)
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return (f"<style>{CSS}</style>"
            "<h2>Ticker lookup &mdash; one name, every read</h2>"
            '<p class="grpnote">Type any stock or ETF. The verdict weighs group rank, rank inside the '
            'group, trend, relative strength, money flowing into the ETF that trades most like the '
            'group, short interest, sector and subsector breadth, futures positioning where a '
            'contract applies, and the market regime &mdash; each reason is listed so the call can '
            'be checked, not taken on faith. Click any group member to look it up.</p>'
            '<div class="lk"><div class="lkbar"><input id="lkin" list="lklist" placeholder="Ticker, e.g. HUT" '
            'autocomplete="off"><button class="btn" id="lkgo">Look up</button>'
            f'<span class="dim">{len(data["TK"]):,} stocks &middot; {len(efc_syms):,} ETFs &middot; as of {data["asof"]}</span>'
            '<datalist id="lklist"></datalist></div><div class="lkout" id="lkout"></div></div>'
            f'<script>window.__LK__={payload};</script>')
