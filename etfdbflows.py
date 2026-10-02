"""Cloud harvest of daily ETF fund flows, cross-checked against a second source.

Replaces the Mac-only etfdb harvest. etfdb's ETF pages embed the full daily
series (~10 years) in their Highcharts containers, so one page load per fund
gives the whole history -- no paging, no API key:

  #fund-flow-chart-container  data-series = [[ms, flow $bn], ...]
  #aumcontainer               data-series = [price effect, flow, AUM $bn]

Plain requests get a Cloudflare 403; a real Chromium gets the page. In the
cloud container Chromium must trust the egress proxy's CA (see trust_proxy_ca).

Output: ~/pos/etfdb_flows.parquet with columns symbol, date, flow_bn, aum_bn --
the exact schema flows.per_etf_weekly() reads, so nothing downstream changes.

Verification (verify()): two checks against data that does not come from etfdb.
  1. AUM level  -- latest etfdb AUM vs stockanalysis.com's AUM for the same fund.
  2. Flow identity -- over each week, AUM_end - AUM_start * (P_end / P_start)
     is the flow implied by AUM and an independent Yahoo price. It should match
     the sum of etfdb's daily flows for that week. Distributions and NAV/price
     drift make it inexact, so it is scored as agreement in sign and rough size,
     never used to overwrite the reported number.
Results land in ~/pos/etfflows_verify.json and the audit reads them.
"""
import os, re, sys, json, html, time, glob, subprocess
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")
OUT = f"{D}/etfdb_flows.parquet"
VERIFY = f"{D}/etfflows_verify.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
PROXY_CA = "/root/.ccr/agent-proxy-ca.crt"


def trust_proxy_ca():
    """Cloud containers re-terminate TLS at an egress proxy. curl/requests read
    the CA from env vars, but Chromium only trusts its NSS store -- add it there
    (idempotent, no-op off the cloud)."""
    if not os.path.exists(PROXY_CA):
        return
    db = os.path.expanduser("~/.pki/nssdb")
    os.makedirs(db, exist_ok=True)
    try:
        if not os.path.exists(f"{db}/cert9.db"):
            subprocess.run(["certutil", "-N", "-d", f"sql:{db}", "--empty-password"],
                           check=True, capture_output=True)
        listed = subprocess.run(["certutil", "-L", "-d", f"sql:{db}"],
                                capture_output=True, text=True).stdout
        if "ccr-agent-proxy" not in listed:
            subprocess.run(["certutil", "-A", "-d", f"sql:{db}", "-t", "C,,",
                            "-n", "ccr-agent-proxy", "-i", PROXY_CA],
                           check=True, capture_output=True)
    except FileNotFoundError:
        # certutil ships in libnss3-tools; install it once, then retry.
        r = subprocess.run("apt-get install -y -q libnss3-tools || "
                           "(apt-get update -q && apt-get install -y -q libnss3-tools)",
                           shell=True, capture_output=True)
        if r.returncode == 0:
            return trust_proxy_ca()
        print("etfdbflows: certutil missing and apt install failed -- "
              "Chromium will reject the proxy's certificate", file=sys.stderr, flush=True)


def _chromium():
    """Pre-installed Chromium if present, else Playwright's default."""
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux*/chrome",):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def _series(page_html, cid):
    m = re.search(r'<div[^>]*id="%s"[^>]*>' % re.escape(cid), page_html)
    if not m:
        return None
    tag = m.group(0)
    s = re.search(r'data-series="([^"]*)"', tag)
    if not s:
        return None
    return json.loads(html.unescape(s.group(1)))


def parse(sym, page_html):
    flow = _series(page_html, "fund-flow-chart-container")
    aum = _series(page_html, "aumcontainer")
    if not flow:
        return None
    f = pd.DataFrame(flow, columns=["ms", "flow_bn"])
    if aum and isinstance(aum[0], list) and len(aum) >= 3:
        a = pd.DataFrame(aum[2], columns=["ms", "aum_bn"])
        f = f.merge(a, on="ms", how="left")
    else:
        f["aum_bn"] = np.nan
    f["date"] = pd.to_datetime(f.ms, unit="ms").dt.normalize()
    f["symbol"] = sym
    return f[["symbol", "date", "flow_bn", "aum_bn"]]


def _harvest_chunk(syms):
    """One browser, one tab, a slice of the funds. Runs in its own (forked)
    process -- fork, not spawn, so it works whatever __main__ is, and the parent
    never starts Playwright itself, so there is no browser state to inherit.
    sync Playwright cannot share a browser across threads, and a single tab is
    strictly serial -- so parallelism has to come from processes."""
    from playwright.sync_api import sync_playwright
    out, fails = [], []
    with sync_playwright() as p:
        kw = {"args": ["--disable-blink-features=AutomationControlled"]}
        exe = _chromium()
        if exe:
            kw["executable_path"] = exe
        b = p.chromium.launch(**kw)
        ctx = b.new_context(user_agent=UA)
        # Images/fonts/ads are most of the page weight and none of the data.
        ctx.route(re.compile(r".*\.(png|jpe?g|gif|svg|woff2?|ttf|mp4)(\?.*)?$"),
                  lambda r: r.abort())
        pg = ctx.new_page()
        for sym in syms:
            got = None
            for attempt in range(2):
                try:
                    pg.goto(f"https://etfdb.com/etf/{sym}/", timeout=45000,
                            wait_until="domcontentloaded")
                    got = parse(sym, pg.content())
                    if got is not None:
                        break
                except Exception:
                    pass
                time.sleep(2 + 3 * attempt)
            (out.append(got) if got is not None else fails.append(sym))
        b.close()
    return (pd.concat(out, ignore_index=True) if out else None), fails


def harvest(syms=None, workers=6, verbose=True):
    """One page load per fund, `workers` browsers in parallel; writes OUT."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import multiprocessing as mp
    if syms is None:
        from universe import ETF_BASKETS
        syms = sorted({s for v in ETF_BASKETS.values() for s in v})
    trust_proxy_ca()
    chunks = [syms[i::workers] for i in range(workers) if syms[i::workers]]
    out, fails, done = [], [], 0
    with ProcessPoolExecutor(len(chunks), mp_context=mp.get_context("fork")) as ex:
        for f in as_completed([ex.submit(_harvest_chunk, c) for c in chunks]):
            d, fl = f.result()
            if d is not None: out.append(d)
            fails += fl
            done += 1
            if verbose:
                print(f"  etfdb worker {done}/{len(chunks)} done ({len(fails)} failed so far)",
                      file=sys.stderr, flush=True)
    if fails:  # second chance, serially -- usually a transient Cloudflare hiccup
        d, fails = _harvest_chunk(fails)
        if d is not None: out.append(d)
    if not out:
        raise RuntimeError("etfdb harvest got nothing -- Cloudflare or layout change")
    d = pd.concat(out, ignore_index=True)
    d.to_parquet(OUT)
    print(f"etfdb flows: {d.symbol.nunique()}/{len(syms)} funds, "
          f"{d.date.min().date()} -> {d.date.max().date()}"
          + (f"; failed: {fails[:20]}" if fails else ""), file=sys.stderr, flush=True)
    return d


def _sa_aum(sym):
    import flows
    s = flows.snap(sym)
    return (s or {}).get("aum")


def verify(d=None, sample=40):
    """Cross-check etfdb against independent data; writes VERIFY and returns it."""
    import prices as P
    d = d if d is not None else pd.read_parquet(OUT)
    last = d.dropna(subset=["aum_bn"]).sort_values("date").groupby("symbol").tail(1)
    big = last.nlargest(sample, "aum_bn")
    # 1. AUM level vs stockanalysis
    aum_rows = []
    for _, r in big.iterrows():
        try:
            sa = _sa_aum(r.symbol)
        except Exception:
            sa = None
        if sa:
            aum_rows.append({"symbol": r.symbol, "etfdb_bn": round(r.aum_bn, 2),
                             "sa_bn": round(sa / 1e9, 2),
                             "diff_pct": round(100 * (r.aum_bn * 1e9 / sa - 1), 1)})
    # 2. Weekly flow identity vs Yahoo prices
    px = P.fetch_list(big.symbol.tolist())
    id_rows = []
    for sym in big.symbol:
        if sym not in px.columns:
            continue
        s = d[d.symbol == sym].set_index("date").sort_index()
        s = s[s.index >= s.index.max() - pd.Timedelta(days=200)]
        w_flow = s.flow_bn.resample("W-FRI").sum()
        w_aum = s.aum_bn.resample("W-FRI").last()
        w_px = px[sym].reindex(s.index).ffill().resample("W-FRI").last()
        implied = w_aum - w_aum.shift() * (w_px / w_px.shift())
        k = pd.concat([w_flow, implied], axis=1, keys=["rep", "imp"]).dropna()
        k = k[(k.rep.abs() > 0.01 * w_aum.reindex(k.index)) |
              (k.imp.abs() > 0.01 * w_aum.reindex(k.index))]  # material weeks only
        if len(k) < 4:
            continue
        id_rows.append({"symbol": sym, "weeks": len(k),
                        "sign_agree_pct": round(100 * (np.sign(k.rep) == np.sign(k.imp)).mean(), 0),
                        "corr": round(float(k.rep.corr(k.imp)), 2)})
    a = pd.DataFrame(aum_rows); w = pd.DataFrame(id_rows)
    res = {
        "built": str(pd.Timestamp.now("UTC")),
        "funds": int(d.symbol.nunique()),
        "through": str(d.date.max().date()),
        "aum_checked": len(a),
        "aum_within_5pct": int((a.diff_pct.abs() <= 5).sum()) if len(a) else 0,
        "aum_outliers": a[a.diff_pct.abs() > 5].to_dict("records") if len(a) else [],
        "identity_checked": len(w),
        "identity_median_sign_agree": float(w.sign_agree_pct.median()) if len(w) else None,
        "identity_median_corr": float(w["corr"].median()) if len(w) else None,
        "identity_weak": w[w["corr"] < 0.5].to_dict("records") if len(w) else [],
    }
    # Pass bar: the AUM level is the hard check (a wrong fund or unit shows up
    # there); the flow identity is noisy at the fund level -- GLD's price drifts
    # from its gold NAV, for one -- so it only has to agree on the median.
    res["ok"] = bool(res["aum_checked"] and
                     res["aum_within_5pct"] >= 0.8 * res["aum_checked"] and
                     (res["identity_median_corr"] or 0) >= 0.5)
    json.dump(res, open(VERIFY, "w"), indent=1)
    print(f"etfdb verify: AUM {res['aum_within_5pct']}/{res['aum_checked']} within 5% of "
          f"stockanalysis; flow identity median corr {res['identity_median_corr']} "
          f"sign-agree {res['identity_median_sign_agree']}% over {res['identity_checked']} funds",
          file=sys.stderr, flush=True)
    return res


if __name__ == "__main__":
    syms = sys.argv[1:] or None
    d = harvest(syms)
    verify(d)
