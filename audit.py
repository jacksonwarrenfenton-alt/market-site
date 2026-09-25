"""Cross-module consistency audit.

Every check here is a reference that crosses a module boundary and would fail
SILENTLY rather than loudly. Run before every publish; report.py calls it.
"""
import pandas as pd, numpy as np, os

D = os.path.expanduser("~/pos")

def run(strict=True, verbose=True):
    import universe as U, themes as TH, efficacy as EFF, signals as SG
    problems, notes = [], []

    def bad(msg): problems.append(msg)
    def ok(msg):  notes.append(msg)

    tickers = {s for v in U.ETF_BASKETS.values() for s in v}
    bkeys = set(U.ETF_BASKETS)

    # 1 -- theme -> basket names (the bug that started this)
    dead = {t: [b for b in v[1] if b not in bkeys] for t, v in TH.THEMES.items()}
    dead = {t: b for t, b in dead.items() if b}
    bad(f"THEMES -> unknown baskets: {dead}") if dead else ok(f"THEMES: all {len(TH.THEMES)} map to live baskets")

    # 2 -- theme -> COT codes
    dcodes = {t: [c for c in v[0] if c not in U.COT_UNIVERSE] for t, v in TH.THEMES.items()}
    dcodes = {t: c for t, c in dcodes.items() if c}
    bad(f"THEMES -> unknown COT codes: {dcodes}") if dcodes else ok("THEMES: all COT codes are in the curated universe")

    # 3 -- every basket has a price proxy, and the proxy is a member
    nop = sorted(bkeys - set(U.BASKET_PROXY))
    bad(f"baskets with no BASKET_PROXY: {nop}") if nop else ok("BASKET_PROXY: covers every basket")
    orph = sorted(set(U.BASKET_PROXY) - bkeys)
    if orph: bad(f"BASKET_PROXY names that are not baskets: {orph}")
    _exempt = getattr(U, "PROXY_NOT_MEMBER", set())
    notmem = sorted(b for b, t in U.BASKET_PROXY.items()
                    if b in bkeys and t not in U.ETF_BASKETS.get(b, []) and b not in _exempt)
    if notmem: bad(f"BASKET_PROXY ticker not a member of its own basket: {notmem}")
    else: ok(f"BASKET_PROXY: members verified ({len(_exempt)} documented inverse exceptions)")

    # 4 -- inverse list must be tickers we actually track
    orphi = sorted(U.INVERSE_ETFS - tickers)
    bad(f"INVERSE_ETFS not in any basket (sign flip would never apply): {orphi}") if orphi \
        else ok(f"INVERSE_ETFS: all {len(U.INVERSE_ETFS)} are tracked")

    # 5 -- no ticker in two baskets (would be double counted)
    seen, dup = set(), set()
    for v in U.ETF_BASKETS.values():
        for s in v:
            if s in seen: dup.add(s)
            seen.add(s)
    bad(f"tickers in more than one basket (double counted): {sorted(dup)}") if dup else ok("baskets: no ticker double counted")

    # 6 -- PRICE_MAP keys must be real contracts
    orphp = sorted(set(U.PRICE_MAP) - set(U.COT_UNIVERSE))
    bad(f"PRICE_MAP codes not in COT_UNIVERSE: {orphp}") if orphp else ok("PRICE_MAP: every code is a curated contract")

    # 7 -- flow history covers every tracked ticker
    if os.path.exists(f"{D}/etfdb_flows.parquet"):
        have = set(pd.read_parquet(f"{D}/etfdb_flows.parquet").symbol.unique())
        miss = sorted(tickers - have)
        bad(f"{len(miss)} tracked ETFs have NO flow history: {miss[:20]}") if miss \
            else ok(f"flow history: all {len(tickers)} tracked ETFs present")
    else:
        ok("flow history: NOT COVERED this run -- etfdb_flows.parquet absent "
           "(Mac-only); check 7 skipped, page renders flows as unavailable")

    # 8 -- price cache covers COT tickers and basket proxies
    if os.path.exists(f"{D}/prices.parquet"):
        pc = set(pd.read_parquet(f"{D}/prices.parquet").columns)
        miss = sorted({t for t, _ in U.PRICE_MAP.values()} - pc)
        bad(f"COT price tickers missing from cache: {miss}") if miss else ok("prices: every COT ticker cached")
    if os.path.exists(f"{D}/etf_prices.parquet"):
        ec = set(pd.read_parquet(f"{D}/etf_prices.parquet").columns)
        miss = sorted(set(U.BASKET_PROXY.values()) - ec)
        bad(f"basket proxy tickers missing from cache: {miss}") if miss else ok("prices: every basket proxy cached")

    # 9 -- cohort column names used by efficacy/signals must exist on the frame
    if os.path.exists(f"{D}/cot_built.parquet"):
        cols = set(pd.read_parquet(f"{D}/cot_built.parquet").columns)
        need = {c for c, _, _ in EFF.COHORTS.values()}
        need |= {c for _, c, _, _, _ in SG.COHORTS} | {c for _, _, c, _, _ in SG.COHORTS}
        miss = sorted(need - cols)
        bad(f"cohort columns referenced but not built: {miss}") if miss else ok("cohort columns: all present on the COT frame")

    # 10 -- the bar cache behind breadth / stockbee / subsector
    if os.path.exists(f"{D}/bars.parquet"):
        b = pd.read_parquet(f"{D}/bars.parquet")
        last = pd.Timestamp(b.date.max())
        age = (pd.Timestamp.today().normalize() - last).days
        cov = b.groupby("date").symbol.nunique()
        if age > 4: bad(f"bar cache last bar is {last.date()} ({age}d old)")
        else: ok(f"bars: {b.symbol.nunique():,} symbols through {last.date()}")
        if cov.iloc[-1] < 0.5 * cov.tail(20).max():
            bad(f"last bar date covers only {int(cov.iloc[-1])} symbols vs "
                f"{int(cov.tail(20).max())} typical -- breadth would read near-zero")

    # 11 (PATCH A3) -- signals cohort keys must resolve in report.py's CTX pane map.
    import re, inspect
    try:
        src = inspect.getsource(__import__("report"))
        m = re.search(r"const CTX = \{\{(.*?)\}\};", src, re.S)
        ctx = set(re.findall(r"(\w+)\s*:\s*\[", m.group(1))) if m else set()
        miss = sorted({c for c, _, _, _, _ in SG.COHORTS} - ctx)
        bad(f"signals cohort keys with no CTX pane map in report.py "
            f"(modal would open every pane): {miss}") if miss \
            else ok(f"CTX pane map: all {len(SG.COHORTS)} signal cohorts resolve")
    except Exception as e:
        bad(f"could not verify the CTX pane map: {e}")

    # 12 (PATCH D3) -- the arrows must be single-sourced and toggleable. Both
    # halves have regressed once already and neither is visible to any other check.
    try:
        cjs = inspect.getsource(__import__("chartui"))
        rjs = inspect.getsource(__import__("report"))
        miss = []
        if "activeSrc.has('arrows')" not in cjs: miss.append("arrows toggle gate (D1a)")
        if "spec.primary && src.k!==spec.primary" not in cjs: miss.append("single-source guard (D1b)")
        if 'data-p="arrows"' not in rjs: miss.append("arrows button (D2a)")
        if "spec.primary = PRIMARY[" not in rjs: miss.append("primary assignment (D2b)")
        bad(f"marker discipline patch D not applied: {miss}") if miss \
            else ok("marker discipline: arrows are single-sourced and toggleable")
    except Exception as e:
        bad(f"could not verify marker discipline: {e}")

    # 13 (PATCH E3) -- index leverage must live in its own baskets, and the short
    # basket must be exempt from the sign flip. Both are silent failures: a levered
    # fund back inside a cash basket just makes that basket noisier, and a flipped
    # short basket prints its headline backwards.
    try:
        import flows as _FL
        LEV = {"Index Long (leveraged)", "Index Short (inverse)",
               "Sector Long (leveraged)", "Sector Short (inverse)"}
        missing = sorted(LEV - bkeys)
        if missing:
            bad(f"index leverage baskets missing: {missing}")
        else:
            cash = set()
            for _b in ("Broad US Equity","Technology","Semiconductors","Financials",
                       "Health Care","Energy","Industrials","Consumer Disc","Utilities",
                       "Real Estate","Precious Metals"):
                cash |= set(U.ETF_BASKETS.get(_b, []))
            stray = sorted(cash & {"TQQQ","SQQQ","QID","QLD","SSO","SPXL","SPXS","SH",
                                   "SDS","SPXU","UPRO","TNA","TZA","RWM","PSQ","DOG",
                                   "URTY","SRTY","MIDU","UDOW","SDOW","TWM","SPUU",
                                   "SOXL","USD","TECL","FNGU","FAS","DPST","LABU","CURE",
                                   "PILL","ERX","GUSH","NRGU","DFEN","DUSL","NAIL","RETL",
                                   "WANT","UTSL","DRN","NUGT","JNUG","SOXS","SSG","TECS",
                                   "FNGD","FAZ","SKF","LABD","ERY","DRIP","DUG","DRV",
                                   "DUST","JDST"})
            bad(f"index levered/inverse funds still inside a cash basket: {stray}") if stray \
                else ok(f"leverage split: {len(LEV)} dedicated baskets (index + sector), cash baskets clean")
            src2 = inspect.getsource(_FL.per_etf_weekly)
            bad("inverse funds are no longer sign-flipped -- short baskets would "
                "print gross builds instead of net long-equivalent positioning") \
                if "d.loc[d.inverse" not in src2 \
                else ok("sign flip: inverse flipped everywhere -> net long-equivalent")
    except Exception as e:
        bad(f"could not verify index leverage baskets: {e}")

    # 14 (PATCH F) -- the equal-weight cross-check must survive both ends of the
    # pipe. subsector.py can emit the columns and marketsite.py can quietly stop
    # rendering them (or the reverse), and the board still looks correct.
    try:
        import subsector as _SS, marketsite as _MS
        ssrc = inspect.getsource(_SS.build)
        miss = [c for c in ("ew_rs_m", "ew_rank", "xchk") if f'"{c}"' not in ssrc]
        if miss:
            bad(f"subsector.py stopped emitting EW cross-check columns: {miss}")
        else:
            msrc = inspect.getsource(_MS.subsector_board)
            if "xcell" not in msrc or "EW rank" not in msrc:
                bad("marketsite.py is not rendering the EW cross-check column")
            elif 'colspan="15"' not in msrc:
                bad("constituent drop-down colspan does not match the column count")
            else:
                ok("EW cross-check: computed in subsector, rendered in the board")
        rl = [l for l in open(_SS.ROSTER) if "|" in l]
        nb = len(rl)
        nc = sum(len(l.split("|", 1)[1].split(",")) for l in rl)
        bad(f"roster shrank to {nb} baskets -- expected 253") if nb < 253 \
            else ok(f"roster: {nb} baskets / {nc:,} constituents")
        if "176 custom baskets" in inspect.getsource(_MS.subsector_board):
            bad("subsector note still hardcodes 176 baskets")
    except Exception as e:
        bad(f"could not verify the EW cross-check: {e}")

    # 15 (PATCH F2) -- the confluence panel is the headline of the Subsector tab.
    # Every leg is optional by design, so a leg that silently stops covering any
    # group would just shrink the count and look like a quiet week.
    try:
        import confluence as _CF, marketsite as _MS2
        if len(_CF.LEGS) != 10:
            bad(f"confluence has {len(_CF.LEGS)} legs, expected 10")
        # The TradingView leg must vote at most once per group.
        import tvscan as _TVA
        _td, _ta, _tn = _TVA.load()
        if _td is None:
            ok(f"TradingView leg: not available ({_tn})")
        elif _td.index.duplicated().any():
            bad("TradingView scan has duplicate groups -- a source would vote twice")
        else:
            ok(f"TradingView leg: {len(_td)} groups, one vote each, as of {_ta}")
        # The Finviz leg: same one-vote-per-group rule, plus the crosswalk
        # itself should still cover a large majority of the roster -- a big
        # drop would mean the roster changed shape under the crosswalk.
        import extscan as _FVA
        _fd, _fa, _fn = _FVA.load_finviz()
        if _fd is None:
            ok(f"Finviz leg: not available ({_fn})")
        elif _fd.index.duplicated().any():
            bad("Finviz scan has duplicate industries -- a source would vote twice")
        else:
            _fx = _FVA._finviz_xmap()
            if len(_fx) < 200:
                bad(f"Finviz crosswalk covers only {len(_fx)} baskets -- expected 200+")
            else:
                ok(f"Finviz leg: {len(_fd)} industries, {len(_fx)} baskets crosswalked, as of {_fa}")
        msrc2 = inspect.getsource(_MS2.subsector_board)
        for tok in ("ccell", "scell", "legstrip", "conf_panel"):
            if tok not in msrc2: bad(f"confluence renderer missing: {tok}")
        rl2 = [l.split("|", 1)[0].strip() for l in open(_CF.__dict__["os"].path
               .expanduser("~/pos/custom176-rosters.txt")) if "|" in l]
        unmapped = sorted({r for r in rl2 if not _CF.basket_of(r)})
        bad(f"groups with no ETF flow basket: {unmapped[:6]}") if unmapped \
            else ok(f"confluence: {len(_CF.LEGS)} legs, all {len(rl2)} groups map to a flow basket")
    except Exception as e:
        bad(f"could not verify the confluence panel: {e}")

    # 16 (PATCH G) -- open interest must stay OUT of the ranked signals, and the
    # Stockbee significance table must stay wired in. Both are silent failures:
    # OI creeping back would quietly re-rank contracts on a cohort measured at
    # 48% hit, and a missing stats table just looks like a shorter page.
    try:
        import signals as _SG2, marketsite as _MS3, os as _os
        cks = [c[0] for c in _SG2.COHORTS]
        bad("open interest is back in the ranked signals -- it tested at 48.2% "
            "hit (13w) and fails at every tail out to the 100th percentile") \
            if "oi" in cks else ok(f"ranked cohorts: {cks} (OI correctly excluded)")
        _src3 = inspect.getsource(_MS3)
        for _tok in ("sb_explorer_html", "si_history_panel", "liqn_panel"):
            if _tok not in _src3: bad(f"panel not wired into the site: {_tok}")
        if not _os.path.exists(f"{D}/sb_hist_deep.parquet"):
            bad("sb_hist_deep.parquet missing -- the Stockbee explorer renders empty")
        else:
            _h = pd.read_parquet(f"{D}/sb_hist_deep.parquet")
            import sbui as _SBU
            _have = [k for k, _l, _g, _s in _SBU.SERIES if k in _h.columns]
            bad(f"Stockbee explorer has only {len(_have)} series, expected 20+") \
                if len(_have) < 20 else \
                ok(f"Stockbee explorer: {len(_have)} series x {len(_h):,} sessions "
                   f"({_h.index.min().date()} to {_h.index.max().date()})")
    except Exception as e:
        bad(f"could not verify the OI removal / Stockbee stats: {e}")

    # 17 -- the liqn.ai crowd record is append-only and browser-captured. If a
    # run silently fails to capture, the panel keeps rendering yesterday's row
    # and looks current, which is the worst failure mode for a sentiment gauge.
    try:
        import liqn as _LQ
        _d = _LQ.load()
        if _d is None or not len(_d):
            ok("liqn crowd: NOT COVERED this run -- no capture in this container "
               "(device-bound); panel renders as unavailable")
        else:
            _age = (pd.Timestamp.today().normalize() - _d.dt.max()).days
            bad(f"liqn crowd snapshot is {_age} days old -- capture is failing") \
                if _age > 10 else \
                ok(f"liqn crowd: {len(_d)} snapshot(s), newest {_d.dt.max().date()}")
    except Exception as e:
        bad(f"could not verify the liqn crowd record: {e}")

    # 18 -- the short-interest record must stay on the FINRA bulk source. The
    # Nasdaq per-ticker scrape only keeps ~25 settlements on ~360 names, so a
    # silent fallback would quietly shorten the history by years.
    try:
        import os as _os3
        _p = f"{D}/si_finra.parquet"
        if not _os3.path.exists(_p):
            bad("si_finra.parquet missing -- SI history falls back to the "
                "shallow Nasdaq scrape")
        else:
            _a = pd.read_parquet(_p)
            _ns = _a.settlementDate.nunique()
            bad(f"FINRA SI history shrank to {_ns} settlements") if _ns < 50 else \
                ok(f"FINRA SI: {_ns} settlements, {len(_a):,} rows, "
                   f"{_a.settlementDate.min()} to {_a.settlementDate.max()}")
    except Exception as e:
        bad(f"could not verify the FINRA SI history: {e}")

    # 19 -- the AI desk is only as good as its index. An empty or shallow index
    # renders a working-looking page that answers every lookup with "not covered".
    try:
        import os as _os4, json as _js
        _p = f"{D}/tickerdesk.json"
        if not _os4.path.exists(_p):
            bad("tickerdesk.json missing -- the AI desk will answer nothing")
        else:
            _o = _js.load(open(_p)); _c = _o.get("counts", {})
            if _c.get("tickers", 0) < 2000:
                bad(f"ticker index only covers {_c.get('tickers',0)} tickers")
            elif not _o.get("groups"):
                bad("ticker index has no group metadata -- group cards render empty")
            else:
                ok(f"AI desk index: {_c['tickers']:,} tickers "
                   f"({_c.get('cot',0)} futures, {_c.get('etf',0)} ETFs, "
                   f"{_c.get('si',0)} SI, {len(_o['groups'])} groups)")
        import os as _os4b
        if not _os4b.path.exists(f"{D}/market_sentiment.html"):
            ok("sentiment page: NOT COVERED this run -- market_sentiment.html is an "
               "output of the build the audit gates, so it cannot exist on a fresh "
               "container; verified on the next run")
        else:
            _sc = open(f"{D}/market_sentiment.html").read()
            _miss = [t for t in ("p-desk", "p-chart", "p-regime", "p-gl") if t not in _sc]
            bad(f"sentiment page missing AI-desk sub-panes: {_miss}") if _miss \
                else ok("sentiment page: all four AI-desk sub-panes present")
        import marketsite as _MS4
        if 'data-pane="p-ai"' in inspect.getsource(_MS4):
            bad("AI desk tab is still wired into market_site.html -- it should have "
                "moved to market_sentiment.html")
        # The chart builder draws from embedded series. Without them it silently
        # degrades to "Claude, recall some numbers", which is exactly the failure
        # this design exists to prevent.
        _cp = f"{D}/chartdata.json"
        if not _os4.path.exists(_cp):
            bad("chartdata.json missing -- the chart builder has no data to plot")
        else:
            _cl = _js.load(open(_cp))
            _n = len(_cl.get("series", {}))
            bad(f"chart library only has {_n} series") if _n < 150 else \
                ok(f"chart library: {_n} series x {len(_cl.get('dates',[]))} weeks")
    except Exception as e:
        bad(f"could not verify the AI desk: {e}")

    # 20 -- the three front-page panels added on 2026-09-01. Each renders empty
    # on failure rather than erroring, so absence is invisible without a check.
    try:
        import os as _os5, report as _RP
        import marketsite as _MS6
        _ms = inspect.getsource(_MS6)
        for _tok in ("singlestock", "earnings", "liqn", "sitables"):
            if _tok not in _ms:
                bad(f"single-stock page is missing its {_tok} panel")
        if 'data-pane="p-stock"' not in _ms:
            bad("Single stock tab is not wired into the page")
        import singlestock as _SS2
        _od, _oh = _SS2.build()
        if _od is None:
            bad("overlap table built nothing")
        else:
            _n2 = int((_od.kinds >= 2).sum())
            ok(f"overlap: {_n2} tickers on 2+ datasets; sector heat: "
               f"{0 if _oh is None else len(_oh)} groups above "
               f"{_oh.attrs.get('base', 0):.1f}% base rate")
        _ep = f"{D}/earnings.parquet"
        if not _os5.path.exists(_ep):
            bad("earnings.parquet missing -- the calendar renders empty")
        else:
            _e = pd.read_parquet(_ep)
            _fut = _e[pd.to_datetime(_e.date) >= pd.Timestamp.today().normalize()]
            bad(f"earnings calendar has only {len(_fut)} forward rows -- stale") \
                if len(_fut) < 50 else \
                ok(f"earnings: {_e.symbol.nunique():,} names, {len(_fut):,} ahead, "
                   f"through {_e.date.max()}")
        import liqn as _LQ2
        _ld = _LQ2.load()
        if _ld is not None and len(_ld):
            import json as _j2
            _n = len(_j2.loads(_ld.iloc[-1].get("loudest") or "[]"))
            bad("liqn snapshot has no per-ticker tables -- crowd panel renders empty") \
                if _n == 0 else ok(f"crowd panel: {_n} loudest names captured")
    except Exception as e:
        bad(f"could not verify the front-page panels: {e}")

    # 21 -- the panels added 2026-09-02. Each fails soft (returns "") so a break
    # looks like a shorter page, not an error.
    try:
        import marketsite as _MS7
        _s7 = inspect.getsource(_MS7)
        for _tok in ("vixterm", "diverge", "econcal", "freshbar", "calendar_panel"):
            if _tok not in _s7: bad(f"panel not wired: {_tok}")
        if "{zoom_js}" not in _s7: bad("timeframe brush script is not injected")
        import zoomjs as _ZJ
        if "tfbar" not in _ZJ.ZOOM_JS: bad("brush markup missing from the zoom script")
        if "wheel" in _ZJ.ZOOM_JS:
            bad("wheel-zoom is back -- the control is a brush under the chart, "
                "and wheel handlers hijack page scrolling")
        if "_rrg(df)" not in _s7: bad("rotation map is not wired into the subsector board")
        # Global & liquidity moved from a top-level tab to the 4th AI-desk
        # sub-tab (2026-09-21). Verify it is wired THERE now, and that the old
        # top-level tab is genuinely gone rather than orphaned alongside it.
        if 'data-pane="p-global"' in _s7:
            bad("Global & liquidity is a top-level tab in market_site.html -- it should "
                "be on the sentiment page only")
        if 'data-pane="p-ai"' in _s7:
            bad("AI desk is still a top-level tab in market_site.html -- it should have "
                "moved to market_sentiment.html")
        import aitab as _AIT, inspect as _insp
        _a7 = _insp.getsource(_AIT.panel)
        if 'data-p="p-gl"' not in _a7:
            bad("Global & liquidity sub-tab is not wired into the AI desk")
        if 'global_html=globalpage' not in _s7:
            bad("globalpage is not passed into the AI desk panel")
        import os as _o9
        if not _o9.path.exists(f"{D}/market_sentiment.html"):
            ok("Global & liquidity: NOT COVERED this run -- sentiment page not yet "
               "written (see check 19)")
        else:
            _sc2 = open(f"{D}/market_sentiment.html").read()
            _m2 = [l for t, l in (("fwgrid","fed watch"), ("vixbox","vix term"),
                                  ("Google Trends","google trends"),
                                  ("Correlation","ratio scan")) if t not in _sc2]
            bad(f"sentiment page missing: {_m2}") if _m2 else \
                ok("Global & liquidity: on market_sentiment.html, absent from market_site.html")
        if "GLI.panel" not in _s7: bad("liquidity composite is not on the global tab")
        if "RSC.html_panel" not in _s7: bad("correlation scan is not on the global tab")
        import minichart as _MC3
        if "mcmode" not in _MC3.MINI_JS:
            bad("chart scale toggle missing -- multi-series charts render illegibly "
                "when series share one linear axis")
        import os as _o8
        if _o8.path.exists(f"{D}/ratioscan.parquet"):
            _rs = pd.read_parquet(f"{D}/ratioscan.parquet")
            ok(f"correlation scan: {len(_rs)} pairs that have tracked, "
               f"{int((_rs.absz>=1.5).sum())} currently stretched")
        else:
            bad("ratioscan.parquet missing -- correlation scan renders empty")
        import gli as _GLI, json as _j5
        _o5 = _GLI.build(_j5.load(open(f"{D}/chartdata.json")))
        if _o5 is None: bad("liquidity composite built nothing")
        else:
            _g5 = _o5["gli"]
            ok(f"liquidity composite: {len(_o5['Z'].columns)} components, "
               f"{len(_g5)} weeks, now {_g5.iloc[-1]:+.2f}")
        import minichart as _MC2
        if "MC.mount" not in _s7 and "mount" not in _MC2.MINI_JS:
            bad("minichart component missing")
        import vixterm as _VT
        _vr = _VT.panel()
        bad("VIX term structure renders empty") if not _vr else ok("VIX term structure live")
        import econcal as _EC
        _ec = _EC.panel()
        bad("macro calendar renders empty") if not _ec else ok("macro calendar live")
        import os as _o7
        if _o7.path.exists(f"{D}/diverge.parquet"):
            _dv = pd.read_parquet(f"{D}/diverge.parquet")
            ok(f"divergences: {len(_dv)} sectors scored")
        else:
            bad("diverge.parquet missing -- divergence panel renders empty")
        import freshbar as _FB
        _st = [f["name"] for f in _FB.feeds() if f["stale"]]
        ok(f"freshness: {len(_FB.feeds())} feeds tracked"
           + (f", stale: {_st}" if _st else ", none stale"))
    except Exception as e:
        bad(f"could not verify the 2026-09-02 panels: {e}")

    if verbose:
        for n in notes: print("  ok   ", n)
        for p in problems: print("  FAIL ", p)
    if problems and strict:
        raise ValueError("audit failed:\n" + "\n".join(problems))
    return problems

if __name__ == "__main__":
    run(strict=False)
