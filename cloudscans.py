"""Cloud harvests of the three outside subsector reads that used to need the Mac.

All three write the exact CSV each leg already reads, so confluence.py,
tvscan.py, extscan.py and moomoo.py change nothing:

  finviz()      -> ext_finviz.csv   industry, asof, d, w, m, q, h, ytd
                   finviz.com/groups.ashx (performance view). Plain request with
                   a full browser UA; no login, no browser.
  moomoo()      -> ext_moomoo.csv   group, asof, chg
                   moomoo's Sectors tab. The table is filled by an internal
                   endpoint that needs the page's own session headers, so this
                   drives a real Chromium through the five pages of the table.
  tradingview() -> tv_scan.csv      date, code, group, grp_id, numeric_id, score,
                                    members, rs1d, rs5d, rs21d, rs63d, rs126d

THE TRADINGVIEW LEG IS A DIFFERENT MEASUREMENT FROM THE WALK IT REPLACES. The
Mac walk read jman's own Pine indicator off the chart's Data Window, which needs
his signed-in TradingView. This instead asks TradingView's public scanner for
every roster member's own performance over 1D/1W/1M/3M/6M -- TradingView's data,
not our Yahoo bars, so it stays an independent outside read -- and aggregates it
per basket with the same custom176 roster: equal-weight (mean) member return
minus SPY's over the same window -- the indicator's own "EW vs SPY"
construction, on TradingView's calendar windows (1W/1M/3M/6M) rather than its
exact 5/21/63/126-session counts. The vote uses (1M + 3M) / 2, matching the
walk's (21D + 63D) / 2. The indicator's own 0-100 score is not reproduced; the
leg never used it. Rows carry grp_id ==
numeric_id (the basket's row index) because there is no probe to mis-land.
"""
import os, re, io, sys, json, time
import pandas as pd, numpy as np, requests

D = os.path.expanduser("~/pos")
HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def _today():
    return pd.Timestamp.now("America/New_York").strftime("%Y-%m-%d")


def _pct(s):
    return pd.to_numeric(pd.Series(s).astype(str).str.replace("%", "")
                         .str.replace("+", "", regex=False), errors="coerce")


# ---------------------------------------------------------------- Finviz --
def finviz():
    r = requests.get("https://finviz.com/groups.ashx?g=industry&v=140&o=name",
                     headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    t = next(t for t in pd.read_html(io.StringIO(r.text)) if "Perf Week" in t.columns)
    out = pd.DataFrame({
        "industry": t["Name"], "asof": _today(),
        "d": _pct(t["Change %"]), "w": _pct(t["Perf Week"]), "m": _pct(t["Perf Month"]),
        "q": _pct(t["Perf Quart"]), "h": _pct(t["Perf Half"]), "ytd": _pct(t["Perf YTD"]),
    })
    out.to_csv(f"{D}/ext_finviz.csv", index=False)
    print(f"finviz: {len(out)} industries", file=sys.stderr, flush=True)
    return out


# ---------------------------------------------------------------- moomoo --
def moomoo():
    from playwright.sync_api import sync_playwright
    from etfdbflows import trust_proxy_ca, _chromium
    trust_proxy_ca()
    rows = {}
    with sync_playwright() as p:
        kw = {"args": ["--disable-blink-features=AutomationControlled"]}
        if _chromium(): kw["executable_path"] = _chromium()
        b = p.chromium.launch(**kw)
        pg = b.new_context(user_agent=UA, viewport={"width": 1400, "height": 2400}).new_page()

        def on(resp):
            if "get-plate-list" in resp.url:
                try:
                    for x in resp.json()["data"]["list"]:
                        rows[x["plateEnName"]] = x
                except Exception:
                    pass
        pg.on("response", on)
        pg.goto("https://www.moomoo.com/quote/us/sectors", timeout=60000,
                wait_until="domcontentloaded")
        pg.wait_for_timeout(5000)
        pg.get_by_text("Sectors", exact=True).first.click()
        pg.wait_for_timeout(6000)
        # Page through with the table's own "next" arrow until it disables --
        # clicking page numbers by text also hits other "2"/"3"s on the page.
        for _ in range(12):
            nxt = pg.locator(".base-pagination .item.next").first
            if not nxt.count() or "disabled" in (nxt.get_attribute("class") or ""):
                break
            before = len(rows)
            nxt.click()
            pg.wait_for_timeout(3000)
            if len(rows) == before:
                pg.wait_for_timeout(3000)
        b.close()
    if not rows:
        raise RuntimeError("moomoo returned no sector rows -- layout or endpoint changed")
    out = pd.DataFrame({"group": list(rows), "asof": _today(),
                        "chg": _pct([v["changeRatio"] for v in rows.values()]).values,
                        "up": [v.get("priceRiseCount") for v in rows.values()],
                        "down": [v.get("priceFallCount") for v in rows.values()]})
    out.to_csv(f"{D}/ext_moomoo.csv", index=False)
    print(f"moomoo: {len(out)} sector groups", file=sys.stderr, flush=True)
    return out


# ----------------------------------------------------------- TradingView --
TV_COLS = ["name", "change", "Perf.W", "Perf.1M", "Perf.3M", "Perf.6M"]
TV_WIN = {"rs1d": "change", "rs5d": "Perf.W", "rs21d": "Perf.1M",
          "rs63d": "Perf.3M", "rs126d": "Perf.6M"}
MIN_MEMBERS = 3   # a basket with fewer priced members than this gets no vote


def _rosters():
    path = f"{D}/custom176-rosters.txt"
    if not os.path.exists(path): path = f"{HERE}/custom176-rosters.txt"
    out = []
    for line in open(path):
        if "|" in line:
            g, syms = line.rstrip("\n").split("|", 1)
            out.append((g.strip(), [s.strip().upper() for s in syms.split(",") if s.strip()]))
    return out


def _tv_scan(tickers):
    """TradingView's public scanner, by bare ticker across US exchanges."""
    res = {}
    tickers = sorted(set(tickers))
    for i in range(0, len(tickers), 400):
        chunk = tickers[i:i + 400]
        body = {"filter": [{"left": "name", "operation": "in_range", "right": chunk}],
                "columns": TV_COLS, "range": [0, 4000],
                "options": {"lang": "en"}, "markets": ["america"]}
        for attempt in range(3):
            try:
                r = requests.post("https://scanner.tradingview.com/america/scan",
                                  json=body, headers={"User-Agent": UA}, timeout=30)
                r.raise_for_status()
                for row in r.json().get("data", []):
                    vals = dict(zip(TV_COLS, row["d"]))
                    nm = str(vals.pop("name")).upper()
                    # first listing wins; primary listings come back first
                    res.setdefault(nm, vals)
                break
            except Exception:
                time.sleep(2 + 3 * attempt)
    return pd.DataFrame.from_dict(res, orient="index")


def tradingview():
    # jman's indicator computed exactly from daily closes: tvcalc.py reads the
    # rosters and the math straight from tv_indicator.pine, so this IS the
    # Data Window reading for every group, refreshed daily. A restored
    # Chrome-walk file (no `src` column, <= 8 days old) is the first fallback,
    # the TradingView screener read the last.
    try:
        import tvcalc
        return tvcalc.build()
    except Exception as e:
        print(f"tradingview: exact indicator calc FAILED ({e}) -- trying fallbacks",
              file=sys.stderr, flush=True)
    path = f"{D}/tv_scan.csv"
    if os.path.exists(path):
        try:
            old = pd.read_csv(path)
            if "src" not in old.columns and len(old):
                dt = pd.to_datetime(old["date"].astype(str), errors="coerce").max()
                if pd.notna(dt) and (pd.Timestamp.now() - dt).days <= 8:
                    print(f"tradingview: keeping the indicator walk from {dt.date()} "
                          f"({len(old)} rows)", file=sys.stderr, flush=True)
                    return old
        except Exception:
            pass
    return _screener_read()


def _screener_read():
    ro = _rosters()
    px = _tv_scan([s for _, m in ro for s in m] + ["SPY"])
    if "SPY" not in px.index:
        raise RuntimeError("TradingView scanner returned no SPY row")
    spy = px.loc["SPY"]
    probes = {}
    pp = f"{D}/tv_probes_253.csv"
    if os.path.exists(pp):
        probes = pd.read_csv(pp).set_index("group")["code"].to_dict()
    rows = []
    for i, (g, members) in enumerate(ro):
        m = px.reindex([s for s in members if s in px.index]).dropna(how="all")
        if len(m) < MIN_MEMBERS:
            continue
        r = {"date": _today(), "src": "cloud", "code": probes.get(g, members[0]), "group": g,
             "grp_id": i, "numeric_id": i, "members": len(m)}
        for k, col in TV_WIN.items():
            # equal-weight mean, as the Pine indicator does ("EW vs SPY")
            r[k] = round(float(m[col].mean() - spy[col]), 3)
        r["score"] = round((r["rs21d"] + r["rs63d"]) / 2, 3)
        rows.append(r)
    out = pd.DataFrame(rows)[["date", "code", "group", "grp_id", "numeric_id", "score",
                              "members", "rs1d", "rs5d", "rs21d", "rs63d", "rs126d", "src"]]
    out.to_csv(f"{D}/tv_scan.csv", index=False)
    print(f"tradingview: {len(out)}/{len(ro)} baskets, {len(px)} tickers priced",
          file=sys.stderr, flush=True)
    return out


def run():
    ok = {}
    for name, fn in (("finviz", finviz), ("moomoo", moomoo), ("tradingview", tradingview)):
        try:
            ok[name] = len(fn())
        except Exception as e:
            ok[name] = f"FAILED: {e}"
            print(f"cloudscans: {name} FAILED: {e}", file=sys.stderr, flush=True)
    if all(isinstance(v, str) for v in ok.values()):
        raise RuntimeError(f"every outside scan failed: {ok}")
    return ok


if __name__ == "__main__":
    print(run())
