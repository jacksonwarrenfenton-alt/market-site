"""Is every feed that is SUPPOSED to collect on a schedule actually collecting?

Why this exists
---------------
`freshness.py` / `freshbar.py` already print an as-of date per feed, and
`audit.py` already asserts cross-module references resolve. Neither answers the
question that actually matters: *for each feed, given its own cadence, is the
data we hold as current as it could be, and if not, is that expected or broken?*

Three real failures got through the existing checks, which is what this module
is built from:

1. **A third of the short-interest history was missing and nothing said so.**
   `sifinra.dates()` emitted the calendar 15th; when that is a weekend FINRA's
   settlement is the preceding business day, the API returned zero rows, and the
   collector's `if not rows: continue` dropped it. 30 of 94 settlements were
   absent. `audit.py` check 18 passed the whole time because it only asserts the
   total settlement count is >= 50. A *count* threshold cannot see a hole.

2. **Feeds that have never once worked look identical to feeds skipped on
   purpose.** ETF flows and the liqn captures degrade to `ok() ... NOT COVERED`
   so a cloud rebuild is not blocked by a device-bound input -- correct, but it
   means a task that has never produced a single row reports the same green as
   one deliberately out of scope today. This module keeps a `last_seen_good`
   per feed so "device-bound, last real data 4 days ago" and "device-bound,
   never produced anything" are different answers.

3. **A partial bar can be published as an EOD read.** `bars.parquet` captured
   while the session is open carries an unsettled close for today, so the
   advance/decline counts, every Stockbee cohort ("up 4% TODAY"), McClellan and
   the regime vote are all computed off an intraday snapshot -- with nothing in
   the page saying so. `audit.py` check 10 only looks at whether the LAST date
   has enough symbols, which an intraday bar passes easily.

Design notes
------------
* **Expected age is per-cadence, not global.** A weekly COT frame 6 days old is
  healthy; a daily bar frame 6 days old is broken. One global staleness number
  cannot express that, which is why the old single `stale` boolean was too blunt
  to catch anything.
* **Cadence is checked against the publication calendar, not the clock.** COT is
  as-of Tuesday and published Friday afternoon, so Wednesday through Friday
  morning the newest possible as-of is still last Tuesday and a 3-day-old frame
  is perfectly current. Feeds are judged against what *could* exist right now.
* **History is persisted.** A feed that silently stops advancing is invisible in
  a single run -- it still has a plausible date. `feed_history.json` records each
  feed's as-of per run, so "the as-of has not moved in 4 runs" becomes a visible
  status rather than something a human has to notice.
* **Nothing here raises.** This is a reporter. `audit.py` is the gate; a broken
  feed should be loudly visible on the page and in the run reply, not a hard
  stop that prevents the other 30 working feeds from being published.
"""
import os, json, sys, html
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")
HIST = f"{D}/feed_history.json"

# Cloud = this container can collect it unattended. Device = needs jman's Mac
# (a signed-in browser, or master CSVs that live there). The distinction is the
# whole point: a device feed reading NOT COVERED on cloud is expected, the same
# feed never having produced data anywhere is a broken scheduled task.
CLOUD, DEVICE = "cloud", "device"


def _aware(ts):
    """UTC-aware, whatever came in. The ET conversions below need a zone."""
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")


def _naive_day(ts):
    """Tz-naive midnight. Every as-of read off a parquet is naive, so every
    expected-date calculation has to land in the same space or the subtraction
    raises rather than reporting a gap."""
    ts = pd.Timestamp(ts)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _mtime(p):
    return pd.Timestamp(os.path.getmtime(p), unit="s") if os.path.exists(p) else None


def _pq_max(path, col):
    try:
        d = pd.read_parquet(path, columns=[col])
        return pd.Timestamp(pd.to_datetime(d[col]).max()).normalize()
    except Exception:
        return None


def _json_mtime(path):
    return None if not os.path.exists(path) else _mtime(path).normalize()


# ---- expected-newest calculators -------------------------------------------
# Each returns the newest as-of date that COULD exist right now. Comparing
# against this rather than against today is what stops a healthy weekly feed
# from being reported as 6 days stale every Wednesday.

def _exp_daily_session(now):
    """Newest settled US equity session. Before 16:00 ET the current day has not
    closed, so the newest SETTLED session is the previous weekday."""
    et = _aware(now).tz_convert("America/New_York")
    d = et.normalize().tz_localize(None)
    if et.weekday() >= 5:                       # weekend -> last Friday
        return d - pd.Timedelta(days=et.weekday() - 4)
    if et.hour < 16:                            # session not yet closed
        d = d - pd.Timedelta(days=1)
        while d.weekday() >= 5:
            d -= pd.Timedelta(days=1)
    return d


def _exp_cot(now):
    """COT is as-of Tuesday, published Friday 15:30 ET. So the newest as-of that
    can exist is last Tuesday until Friday afternoon, then this week's Tuesday."""
    et = _aware(now).tz_convert("America/New_York")
    d = et.normalize().tz_localize(None)
    released = (et.weekday() > 4) or (et.weekday() == 4 and et.hour >= 16)
    tue = d - pd.Timedelta(days=(d.weekday() - 1) % 7)
    if tue > d:
        tue -= pd.Timedelta(days=7)
    return tue if released else tue - pd.Timedelta(days=7)


def _exp_finra(now):
    """FINRA settles on the 15th and the last business day, published roughly 8
    business days later. Returns the newest settlement whose publication date has
    passed -- so the pipeline is not marked late for the ~8 days in between."""
    d = _naive_day(now)
    cands = []
    for k in (0, 1, 2):
        m = (d - pd.DateOffset(months=k)).replace(day=1)
        cands.append(m + pd.Timedelta(days=14))
        cands.append(m + pd.offsets.MonthEnd(0))
    out = []
    for c in cands:
        while c.weekday() >= 5:                 # roll back to a business day
            c -= pd.Timedelta(days=1)
        if c + pd.offsets.BDay(8) <= d:
            out.append(c)
    return max(out) if out else None


# ---- the registry ----------------------------------------------------------
# path, how to read its as-of, cadence label, expected-newest fn, tolerance in
# days beyond expected before it counts as LATE, and who can collect it.
REG = [
    dict(key="cot", label="CFTC Commitments of Traders", who=CLOUD,
         cadence="weekly (as-of Tue, published Fri 15:30 ET)",
         path=f"{D}/cot_built.parquet", asof=lambda p: _pq_max(p, "date"),
         exp=_exp_cot, tol=0),
    dict(key="si_finra", label="FINRA short interest (full market)", who=CLOUD,
         cadence="bi-monthly (15th + last business day, ~8 business days lag)",
         path=f"{D}/si_finra.parquet",
         asof=lambda p: _pq_max(p, "settlementDate"), exp=_exp_finra, tol=0),
    dict(key="si_latest", label="Short interest per-ticker (Nasdaq)", who=CLOUD,
         cadence="bi-monthly, tracks the FINRA settlement",
         path=f"{D}/si_latest.parquet", asof=lambda p: _pq_max(p, "settle"),
         exp=_exp_finra, tol=0),
    dict(key="bars", label="Daily bars (screened US tape)", who=CLOUD,
         cadence="daily, every trading session",
         path=f"{D}/bars.parquet", asof=lambda p: _pq_max(p, "date"),
         exp=_exp_daily_session, tol=0),
    dict(key="bars_deep", label="Deep daily bars (10 years)", who=CLOUD,
         cadence="daily", path=f"{D}/bars_deep.parquet",
         asof=lambda p: _pq_max(p, "date"), exp=_exp_daily_session, tol=0),
    dict(key="prices", label="COT-ticker price cache", who=CLOUD,
         cadence="daily", path=f"{D}/prices.parquet",
         asof=lambda p: pd.Timestamp(pd.read_parquet(p).index.max()).normalize(),
         exp=_exp_daily_session, tol=0),
    dict(key="etf_prices", label="ETF / basket-proxy price cache", who=CLOUD,
         cadence="daily", path=f"{D}/etf_prices.parquet",
         asof=lambda p: pd.Timestamp(pd.read_parquet(p).index.max()).normalize(),
         exp=_exp_daily_session, tol=0),
    dict(key="sb_hist", label="Stockbee breadth history", who=CLOUD,
         cadence="daily", path=f"{D}/sb_hist_deep.parquet",
         asof=lambda p: pd.Timestamp(pd.read_parquet(p).index.max()).normalize(),
         exp=_exp_daily_session, tol=0),
    dict(key="chartdata", label="Chart library (AI desk reads this)", who=CLOUD,
         cadence="daily", path=f"{D}/chartdata.json", asof=_json_mtime,
         exp=lambda n: _naive_day(n), tol=1),
    dict(key="vixterm", label="VIX term structure", who=CLOUD,
         cadence="daily", path=f"{D}/vix_term.csv", asof=_json_mtime,
         exp=lambda n: _naive_day(n), tol=1),
    dict(key="econcal", label="Macro calendar", who=CLOUD,
         cadence="daily", path=f"{D}/econcal.json", asof=_json_mtime,
         exp=lambda n: _naive_day(n), tol=1),
    dict(key="earnings", label="Earnings calendar", who=CLOUD,
         cadence="daily", path=f"{D}/earnings.parquet", asof=_json_mtime,
         exp=lambda n: _naive_day(n), tol=1),
    dict(key="trends", label="Google Trends", who=CLOUD,
         cadence="daily fetch, weekly resolution", path=f"{D}/trends.json",
         asof=_json_mtime, exp=lambda n: _naive_day(n), tol=1),
    dict(key="etf_snap", label="ETF shares-outstanding snapshots", who=CLOUD,
         cadence="daily", path=f"{D}/etf_snapshots.parquet",
         asof=lambda p: _pq_max(p, "date"),
         exp=lambda n: _naive_day(n), tol=1),
    dict(key="ratioscan", label="Correlation / ratio scan", who=CLOUD,
         cadence="daily (derived)", path=f"{D}/ratioscan.parquet",
         asof=_json_mtime, exp=lambda n: _naive_day(n), tol=1),
    dict(key="diverge", label="Breadth divergences", who=CLOUD,
         cadence="daily (derived)", path=f"{D}/diverge.parquet",
         asof=_json_mtime, exp=lambda n: _naive_day(n), tol=1),
    dict(key="etfdb_flows", label="ETF fund flows (etfdb masters)", who=DEVICE,
         cadence="weekly re-harvest (Fri)", path=f"{D}/etfdb_flows.parquet",
         asof=lambda p: _pq_max(p, "date"),
         exp=_exp_daily_session, tol=7),
    dict(key="liqn_crowd", label="liqn.ai crowd sentiment capture", who=DEVICE,
         cadence="daily (6pm ET)", path=f"{D}/liqn_hist.csv",
         asof=lambda p: pd.Timestamp(pd.read_csv(p).dt.max()).normalize(),
         exp=lambda n: _naive_day(n), tol=1),
    dict(key="liqn_news", label="liqn.ai news-calendar capture", who=DEVICE,
         cadence="daily (6:10pm ET)", path=f"{D}/liqn_news.csv",
         asof=lambda p: pd.Timestamp(pd.read_csv(p).dt.max()).normalize(),
         exp=lambda n: _naive_day(n), tol=1),
]


def _load_hist():
    try:
        return json.load(open(HIST))
    except Exception:
        return {}


def check(now=None, record=True):
    """One row per feed. Never raises; a reader blowing up becomes an ERROR row."""
    now = _aware(now or pd.Timestamp.now("UTC"))
    hist = _load_hist()
    rows = []
    for r in REG:
        p, key = r["path"], r["key"]
        prior = hist.get(key, {})
        asof = err = None
        if os.path.exists(p):
            try:
                asof = r["asof"](p)
            except Exception as e:
                err = str(e)[:80]
        try:
            exp = r["exp"](now)
        except Exception:
            exp = None
        exp = None if exp is None else _naive_day(exp)

        behind = None if (asof is None or exp is None) else (exp - asof).days
        if err:
            status = "ERROR"
        elif asof is None:
            # Never produced in THIS container. Whether that is expected depends
            # on who collects it -- and on whether it has ever worked at all.
            if r["who"] == DEVICE:
                status = "NOT_COVERED" if prior.get("last_seen_good") else "NEVER"
            else:
                status = "MISSING"
        elif behind is not None and behind > r["tol"]:
            status = "STALLED" if behind > max(r["tol"] + 7, 14) else "LATE"
        else:
            status = "OK"

        # Has the as-of moved since the last run? A feed can hold a plausible
        # date forever; only history shows it stopped advancing.
        runs_flat = prior.get("runs_flat", 0)
        pa = prior.get("asof")
        if asof is not None and pa == str(asof.date()):
            runs_flat = int(runs_flat) + 1
        elif asof is not None:
            runs_flat = 0

        rows.append(dict(
            key=key, label=r["label"], who=r["who"], cadence=r["cadence"],
            asof=None if asof is None else str(asof.date()),
            expected=None if exp is None else str(exp.date()),
            behind_days=behind, status=status, error=err,
            runs_flat=runs_flat,
            last_seen_good=(str(asof.date()) if asof is not None
                            else prior.get("last_seen_good")),
            captured=None if not os.path.exists(p) else str(_mtime(p))[:19]))

    if record:
        new = {}
        for x in rows:
            new[x["key"]] = {"asof": x["asof"], "runs_flat": x["runs_flat"],
                             "last_seen_good": x["last_seen_good"],
                             "status": x["status"], "run": str(now)[:19]}
        try:
            json.dump(new, open(HIST, "w"), indent=1)
        except Exception:
            pass
    return pd.DataFrame(rows)


# ---- session-integrity checks the as-of date alone cannot express ------------

def session_integrity(now=None):
    """Problems with the SHAPE of the bar frame, not its end date.

    Both cases here were live on 2026-09-23 and both passed `audit.py`:
      * a 7-symbol 2026-09-22 row sitting mid-series among 3,200-symbol days --
        2026-09-22 was not a session at all (SPY, AAPL and ^GSPC all skip it),
        so those rows are junk that invents a phantom session in the pivot;
      * today's bar captured at 11:22 ET, i.e. an unsettled intraday close
        feeding every "up 4% today" count and the regime's breadth vote.
    """
    now = _aware(now or pd.Timestamp.now("UTC"))
    out = []
    p = f"{D}/bars.parquet"
    if not os.path.exists(p):
        return [dict(kind="bars_missing", detail="bars.parquet absent")]
    b = pd.read_parquet(p, columns=["date", "symbol"])
    cov = b.groupby("date").symbol.nunique().sort_index()
    if not len(cov):
        return [dict(kind="bars_empty", detail="no dated rows")]
    typical = int(cov.tail(20).max())

    # sparse dates ANYWHERE in the recent window, not just the last one
    for d, n in cov.tail(20).items():
        if n < 0.5 * typical:
            out.append(dict(kind="sparse_session", date=str(d.date()),
                            detail=f"{int(n)} symbols vs {typical} typical -- "
                                   f"likely not a real session; drop these rows"))

    # intraday capture: last bar is today, and today's close has not happened
    last = pd.Timestamp(cov.index.max()).normalize()
    settled = _exp_daily_session(now)
    if last > settled:
        cap = _mtime(p)
        out.append(dict(kind="intraday_bar", date=str(last.date()),
                        detail=f"last bar {last.date()} is ahead of the newest "
                               f"SETTLED session ({settled.date()}) -- captured "
                               f"{str(cap)[:19]} UTC, mid-session. Every "
                               f"'today' breadth count and the regime breadth "
                               f"vote are computed off an unsettled close."))
    return out


def settlement_gaps():
    """Holes in the MIDDLE of the FINRA settlement record.

    Currency checks cannot see this. The store can end on exactly the right
    settlement and still be missing a third of the ones before it -- which is
    precisely what happened: `sifinra.dates()` asked for the calendar 15th, got
    zero rows whenever that was a weekend, and skipped it. The end date looked
    perfect. `audit.py` check 18 passed because it only asserts a total count
    >= 50.

    So this enumerates the settlement calendar independently (15th + last
    business day, rolled back off weekends) and reports which expected dates are
    absent. Anything still inside its ~8-business-day publication lag is not a
    gap and is excluded.
    """
    p = f"{D}/si_finra.parquet"
    if not os.path.exists(p):
        return {"error": "si_finra.parquet absent"}
    have = set(pd.read_parquet(p, columns=["settlementDate"])
               .settlementDate.astype(str).unique())
    if not have:
        return {"error": "no settlements"}
    first = pd.Timestamp(min(have))
    today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
    # A settlement is satisfied by ANY of its candidate business days, exactly as
    # sifinra.candidates() resolves them. Rolling back off weekends alone is not
    # enough: 2024-01-15 was MLK Day and 2024-03-29 was Good Friday -- both are
    # weekdays, both were market holidays, and both settled one day earlier. The
    # first cut of this check reported them as missing when they were present as
    # 2024-01-12 and 2024-03-28, i.e. it manufactured two false alarms about the
    # very bug it exists to detect. The expectation has to mirror the collector.
    exp, missing = [], []
    for m in pd.date_range(first.replace(day=1), today, freq="MS"):
        for c in (m + pd.Timedelta(days=14), m + pd.offsets.MonthEnd(0)):
            while c.weekday() >= 5:
                c -= pd.Timedelta(days=1)
            if not (c >= first and c + pd.offsets.BDay(8) <= today):
                continue
            exp.append(c)
            cands = [(c - pd.Timedelta(days=k)) for k in range(5)]
            cands = [x for x in cands if x.weekday() < 5]
            if not any(str(x.date()) in have for x in cands):
                missing.append(str(c.date()))
    exp = sorted(set(exp))
    return {"expected": len(exp), "have": len(have), "missing": missing,
            "first": str(first.date()), "last": str(max(have))}


STATUS_TONE = {"OK": "good", "LATE": "warn", "STALLED": "bad", "MISSING": "bad",
               "NEVER": "bad", "NOT_COVERED": "warn", "ERROR": "bad"}


def html_panel(now=None):
    df = check(now=now, record=False)
    ints = session_integrity(now=now)
    nbad = int((~df.status.isin(["OK", "NOT_COVERED"])).sum())
    tone = "good" if nbad == 0 and not ints else ("bad" if nbad else "warn")
    rows = []
    for _, r in df.sort_values(
            ["status", "who"], key=lambda s: s.map(
                {"STALLED": 0, "NEVER": 1, "MISSING": 2, "ERROR": 3, "LATE": 4,
                 "NOT_COVERED": 5, "OK": 6}).fillna(9)).iterrows():
        flat = (f'<span class="dim"> &middot; flat {int(float(r.runs_flat))} runs</span>'
                if (not pd.isna(r.runs_flat)) and int(float(r.runs_flat)) >= 2 else "")
        beh = ("&ndash;" if pd.isna(r.behind_days) else
               ("current" if float(r.behind_days) <= 0
                else f"{int(float(r.behind_days))}d behind"))
        seen = ("" if r["asof"] or not r.last_seen_good else
                f'<span class="dim"> last real data {r.last_seen_good}</span>')
        rows.append(
            f'<tr><td class="nm">{html.escape(r.label)}{flat}{seen}</td>'
            f'<td class="dim">{html.escape(r.who)}</td>'
            f'<td class="dim">{html.escape(r.cadence)}</td>'
            f'<td>{r["asof"] or "&ndash;"}</td>'
            f'<td class="dim">{r.expected or "&ndash;"}</td>'
            f'<td>{beh}</td>'
            f'<td class="frv {STATUS_TONE.get(r.status, "")}">{r.status}</td></tr>')
    gaps = settlement_gaps()
    ghtml = ""
    if gaps.get("missing"):
        mm = gaps["missing"]
        ghtml = (f'<p class="grpnote" style="border-left:2px solid var(--crit);'
                 f'padding-left:8px"><b class="bad">{len(mm)} FINRA settlement(s) '
                 f'missing from the middle of the record</b> &mdash; '
                 f'{html.escape(", ".join(mm[:8]))}'
                 f'{" &hellip;" if len(mm) > 8 else ""}. '
                 f'Holding {gaps["have"]} of {gaps["expected"]} expected between '
                 f'{gaps["first"]} and {gaps["last"]}. Any multi-settlement change '
                 f'spans an unknown amount of calendar time until this is backfilled.</p>')
    elif gaps.get("expected"):
        ghtml = (f'<p class="grpnote">FINRA settlement record is <b>complete</b>: '
                 f'{gaps["have"]} of {gaps["expected"]} expected settlements present '
                 f'from {gaps["first"]} to {gaps["last"]}, no holes.</p>')
    ihtml = ""
    if ints:
        ihtml = ('<ul class="read">' + "".join(
            f'<li><b class="bad">{html.escape(i["kind"])}</b> '
            f'{html.escape(i.get("date", ""))} &mdash; {html.escape(i["detail"])}</li>'
            for i in ints) + "</ul>")
    return (
        '<div class="sbbox"><div class="sbh">'
        '<span class="sbl">FEED COLLECTION AUDIT</span>'
        f'<span class="sbv {tone}">'
        f'{"ALL FEEDS CURRENT" if tone == "good" else (str(nbad) + " NOT CURRENT" if nbad else "SESSION WARNING")}'
        '</span></div>'
        '<p class="chf">Each feed judged against <b>its own cadence and publication '
        'calendar</b>, not against today &mdash; a weekly COT frame 3 days old is '
        'current, a daily bar frame 3 days old is not. <b>Expected</b> is the newest '
        'as-of that could exist right now. <b>flat N runs</b> means the as-of has not '
        'advanced in N consecutive runs, which is how a silently-stopped collector '
        'shows up while still holding a plausible date. Device feeds read NOT_COVERED '
        'on a cloud run by design, but NEVER means that task has not produced data '
        'anywhere &mdash; a broken schedule, not a skipped step.</p>'
        + ghtml + ihtml +
        '<table class="mini"><thead><tr><th>Feed</th><th>Collector</th>'
        '<th>Cadence</th><th>As of</th><th>Newest possible</th><th>Gap</th>'
        '<th>Status</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table></div>')


if __name__ == "__main__":
    now = pd.Timestamp.now("UTC")
    df = check(now=now)
    cols = ["label", "who", "asof", "expected", "behind_days", "runs_flat", "status"]
    print(df[cols].to_string(index=False))
    print()
    bad = df[~df.status.isin(["OK", "NOT_COVERED"])]
    print(f"{len(bad)} feed(s) not current" if len(bad) else "all feeds current")
    g = settlement_gaps()
    if g.get("missing"):
        print(f"  FINRA   {len(g['missing'])} settlements MISSING mid-record: "
              f"{g['missing'][:10]}")
    elif g.get("expected"):
        print(f"  FINRA   record complete: {g['have']}/{g['expected']} settlements "
              f"{g['first']} -> {g['last']}")
    for i in session_integrity(now=now):
        print(f"  SESSION  {i['kind']} {i.get('date','')}: {i['detail']}")
