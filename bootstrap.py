"""Cold-start a fresh container into a full site build, in one command.

    pip install -r requirements.txt
    python3 bootstrap.py                      # every data step, audit, build
    python3 bootstrap.py --no-build           # data only
    python3 bootstrap.py cot si_latest        # just the named steps (no build)
    python3 bootstrap.py --site-url URL --sentiment-url URL
                                              # also write publish-ready copies

This is the daily trigger's STEP 2-6 recipe as code instead of prose, so a
rebuild no longer depends on a long prompt being followed exactly (or on the
tokens it takes to follow it). Each step is independent: a failure is logged
and the next step still runs, and the summary says exactly which feeds are
missing.

TradingView, Finviz and moomoo subsector scans ARE fetched here now
(cloudscans.py), as are ETF flows (etfdbflows.py) and a login-free crowd feed
(crowdfeed.py). Inputs that are NOT fetched here -- restore them into ~/pos first if you have
them, every one degrades gracefully when absent:
  tv_probes_253.csv                TradingView walk's probe map (git has a seed)
  liqn_hist.csv, liqnnews_hist.csv liqn.ai captures (Mac, daily) -- when absent,
                                   the crowd panels read crowd_hist.csv instead
  crowd_hist.csv                   crowdfeed.py's own history: restore before,
                                   save after (this run appends today's row)
  chart_index_src.html             chartlib's page index (Mac)

With --site-url/--sentiment-url, the cross-link placeholders are substituted
and each page is stripped to <title> + <style> + body as
~/pos/market_site_artifact.html and ~/pos/market_sentiment_artifact.html,
after the same CSS integrity check the trigger used to do by hand. A page
that fails the check is NOT written, and the exit code says so.
"""
import os, re, sys, shutil, subprocess, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.expanduser("~/pos")
sys.path.insert(0, HERE)


def _log(msg):
    print(f"bootstrap: {msg}", file=sys.stderr, flush=True)


def _seed():
    os.makedirs(D, exist_ok=True)
    # The build reads these from ~/pos; their source of truth is the repo. When
    # the repo IS ~/pos (the trigger clones straight into it) there is nothing to do.
    for f in ("custom176-rosters.txt", "tv_probes_253.csv",
              "finviz_xmap.json", "moomoo_xmap.json"):
        src, dst = f"{HERE}/{f}", f"{D}/{f}"
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copy(src, dst)


def _cot():
    import cot
    cot.build(cot.fetch(force=True)).to_parquet(f"{D}/cot_built.parquet")


def _deepbars():
    import breadth, deepbars
    deepbars.fetch(sorted(breadth.universe().symbol.unique()))


def _sbstat():
    subprocess.run([sys.executable, f"{HERE}/run_sbstat.py"], check=True, cwd=HERE)


def _etfflows():
    # Cloud harvest of the daily flow history the Mac used to supply, then the
    # cross-source check. A failed check is logged, not fatal: the numbers are
    # still etfdb's own, the check only says how far to trust them.
    import etfdbflows as EF
    r = EF.verify(EF.harvest())
    if not r.get("ok"):
        _log(f"etfflows: VERIFY WEAK -- {r}")


def _derived():
    # Files the audit gates on but marketsite.build() only writes AFTER the
    # audit (or nothing writes at all), so a cold container fails the gate.
    import pandas as pd
    import prices as P, universe as U, breadth as BR, subsector as SS
    import confluence as CFL, tickerdesk as TDK, diverge as DV
    proxies = sorted(set(U.BASKET_PROXY.values()))
    epx = P.fetch_list(proxies, force=True)
    miss = sorted(set(proxies) - set(epx.columns))
    if miss:  # transient Yahoo misses -- one targeted retry merges into the cache
        time.sleep(5)
        epx = P.fetch_list(miss, force=True)
    bars = pd.read_parquet(f"{D}/bars.parquet")
    u = BR.universe()
    dv = DV.build(bars, universe=u)
    if dv is not None:
        dv.to_parquet(f"{D}/diverge.parquet")
    sub, src = SS.build(bars, u, epx)
    sp = f"{D}/si_latest.parquet"
    sil = pd.read_parquet(sp) if os.path.exists(sp) else None
    sub = CFL.build(sub, bars=bars, bench=epx, si=sil, flow_by_basket={},
                    group_basket={n: CFL.basket_of(n) for n in sub.name})
    o = TDK.save(sub)
    _log(f"subsector {len(sub)} rows src={src}, ticker desk {o['counts']}")


STEPS = [
    # order matters: si screener feeds breadth.universe(); chartdata runs again
    # at the end because its first pass (inside daily) predates cot/bars/sbstat.
    ("si",        lambda: __import__("si").screener()),
    ("cot",       _cot),
    ("prices",    lambda: __import__("prices").fetch(force=True)),
    ("sifinra",   lambda: __import__("sifinra").build()),
    ("si_latest", lambda: __import__("si").build()),
    ("breadth",   lambda: __import__("breadth").build(force=True)),
    ("deepbars",  _deepbars),
    ("sbstat",    _sbstat),
    ("daily",     lambda: __import__("daily_refresh").run()),
    ("chartdata", lambda: __import__("chartdata").save()),
    ("ratioscan", lambda: __import__("ratioscan").save()),
    ("etfflows",  _etfflows),
    ("crowd",     lambda: __import__("crowdfeed").run()),
    ("scans",     lambda: __import__("cloudscans").run()),
    ("derived",   _derived),
]


def _strip(page, placeholder, url, out):
    """Substitute the cross-link, CSS-check, strip to title+style+body."""
    h = open(page).read()
    if h.count(placeholder) != 1:
        raise ValueError(f"{os.path.basename(page)}: expected 1 {placeholder}, "
                         f"found {h.count(placeholder)}")
    h = h.replace(placeholder, url)
    if "__SITE_URL__" in h or "__SENTIMENT_URL__" in h:
        raise ValueError(f"{os.path.basename(page)}: a cross-link placeholder remains")
    styles = re.findall(r"<style[^>]*>.*?</style>", h, re.S)
    css = max(styles, key=len) if styles else ""
    if len(css) < 3000 or ":root" not in css or "--base" not in css:
        raise ValueError(f"{os.path.basename(page)}: CSS integrity check failed "
                         f"(largest <style> {len(css):,} chars) -- not publishable")
    title = re.search(r"<title>.*?</title>", h, re.S)
    body = re.search(r"<body[^>]*>(.*)</body>", h, re.S)
    head_styles = "".join(s for s in styles if body is None or s not in body.group(1))
    s = ((title.group(0) if title else "") + head_styles
         + (body.group(1) if body else h))
    if ":root" not in s or "--base" not in s:
        raise ValueError(f"{os.path.basename(out)}: strip dropped the style block")
    open(out, "w").write(s)
    _log(f"publish-ready {out} ({len(s):,} bytes, css {len(css):,})")


def _arg(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        return argv[i + 1] if i + 1 < len(argv) else None
    return None


def main(argv):
    site_url = _arg(argv, "--site-url")
    sent_url = _arg(argv, "--sentiment-url")
    skip = {site_url, sent_url}
    only = {a for a in argv if not a.startswith("--") and a not in skip}
    build = "--no-build" not in argv and not only
    _seed()
    ok, failed = [], []
    for name, fn in STEPS:
        if only and name not in only:
            continue
        t = time.time()
        _log(f"{name} ...")
        try:
            fn()
            ok.append(name)
            _log(f"{name} ok ({time.time()-t:.0f}s)")
        except Exception as e:
            failed.append(name)
            _log(f"{name} FAILED ({time.time()-t:.0f}s): {e}")
            traceback.print_exc()
    _log(f"data {len(ok)}/{len(ok)+len(failed)} ok"
         + (f" -- failed: {failed}" if failed else ""))
    if not build:
        return 1 if failed else 0
    # Session integrity (sparse sessions, intraday bars, FINRA holes): report
    # only -- dropping rows is a judgement call left to whoever reads it.
    subprocess.run([sys.executable, f"{HERE}/feedcheck.py"], cwd=HERE)
    import marketsite
    p, c, s, r = marketsite.build()
    _log(f"built {p} (regime {r['regime']}, score {r['score']:.2f})")
    if site_url and sent_url:
        for page, ph, url, out in (
                (f"{D}/market_site.html", "__SENTIMENT_URL__", sent_url,
                 f"{D}/market_site_artifact.html"),
                (f"{D}/market_sentiment.html", "__SITE_URL__", site_url,
                 f"{D}/market_sentiment_artifact.html")):
            try:
                _strip(page, ph, url, out)
            except Exception as e:
                failed.append(f"publish-prep {os.path.basename(page)}")
                _log(f"publish-prep FAILED: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
