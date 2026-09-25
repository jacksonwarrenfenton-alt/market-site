"""Bulk short-interest history straight from FINRA.

si.py scrapes Nasdaq one ticker at a time, which caps the record at whatever
that endpoint keeps (~25 settlements) and costs hundreds of requests. FINRA
publishes the same consolidated data as an open bulk API, one call per
settlement, with the previous position and the change already computed. That is
both the authoritative source and a far deeper one.

Settlements are twice monthly -- the 15th and the last business day -- so a year
is ~24 rows and several years is a record worth standardising against.
"""
import urllib.request, ssl, json, time, sys, os
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")
OUT = f"{D}/si_finra.parquet"
URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
CTX = ssl._create_unverified_context()
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
     "Content-Type": "application/json"}
PAGE = 5000


def _post(body):
    d = json.dumps(body).encode()
    r = urllib.request.urlopen(urllib.request.Request(URL, headers=H, data=d),
                               timeout=60, context=CTX)
    return json.loads(r.read())


def settlement(date):
    """Every row for one settlement date, paged."""
    rows, off = [], 0
    while True:
        b = {"limit": PAGE, "offset": off,
             "compareFilters": [{"fieldName": "settlementDate",
                                 "fieldValue": date, "compareType": "equal"}]}
        try:
            chunk = _post(b)
        except Exception:
            time.sleep(2)
            try: chunk = _post(b)
            except Exception: break
        if not chunk: break
        rows += chunk
        if len(chunk) < PAGE: break
        off += PAGE
        if off > 60000: break
    return rows


def dates(years=4):
    """Twice-monthly settlement calendar: the 15th and month end."""
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years)
    out = []
    for m in pd.date_range(start, end, freq="MS"):
        out.append(m.replace(day=15))
        out.append((m + pd.offsets.MonthEnd(0)))
    return [d.strftime("%Y-%m-%d") for d in sorted(set(out)) if d <= end]


def candidates(d, back=5):
    """The nominal settlement date plus the preceding weekdays, newest first.

    FINRA settles on the 15th and the last business day of each month -- but when
    that CALENDAR date falls on a weekend or a market holiday the settlement
    lands on the preceding business day. `dates()` emits the nominal calendar
    date, so the old collector asked FINRA for e.g. 2026-08-15 (a Saturday),
    received an empty response, hit `if not rows: continue`, and silently dropped
    that settlement forever. Verified against the live API: 2026-08-15 -> 0 rows
    while 2026-08-14 (Fri) -> 22,482 rows, and 2026-02-15 -> 0 rows while
    2026-02-13 (Fri) -> 21,530 rows. Both were missing from a 64-settlement
    history and NOTHING flagged it, because audit.py only asserts the total
    settlement count is >= 50.

    Probing backwards is deliberately used instead of a holiday calendar: a
    hardcoded calendar drifts out of date and fails the same way, silently. The
    first candidate that returns rows IS the settlement.
    """
    d = pd.Timestamp(d)
    return [c for c in (d - pd.Timedelta(days=k) for k in range(back))
            if c.weekday() < 5]


def build(years=4, verbose=True):
    seen = set()
    if os.path.exists(OUT):
        old = pd.read_parquet(OUT)
        seen = set(old.settlementDate.astype(str).unique())
    else:
        old = None
    frames = [] if old is None else [old]
    # A nominal date is already covered if ANY of its candidate business days is
    # in the store -- otherwise a backfilled 2026-08-14 would be re-fetched every
    # run as the still-missing 2026-08-15.
    todo = []
    for d in dates(years):
        cands = [c.strftime("%Y-%m-%d") for c in candidates(d)]
        if any(c in seen for c in cands):
            continue
        todo.append((d, cands))
    for i, (d, cands) in enumerate(todo):
        rows, used = None, d
        for c in cands:
            rows = settlement(c)
            if rows:
                used = c
                if c != d and verbose:
                    print(f"  {d} is not a settlement date; resolved to {c}",
                          file=sys.stderr, flush=True)
                break
        if not rows:
            if verbose:
                print(f"  {d}: no settlement found in {cands[0]}..{cands[-1]} "
                      f"(not published yet, or a long holiday)",
                      file=sys.stderr, flush=True)
            continue
        d = used
        f = pd.DataFrame(rows)[[
            "settlementDate", "symbolCode", "issueName", "marketClassCode",
            "currentShortPositionQuantity", "previousShortPositionQuantity",
            "changePercent", "daysToCoverQuantity", "averageDailyVolumeQuantity"]]
        frames.append(f)
        if verbose:
            print(f"  {d}: {len(rows):,} rows  ({i+1}/{len(todo)})",
                  file=sys.stderr, flush=True)
        time.sleep(0.2)
    if not frames: return None
    a = pd.concat(frames, ignore_index=True).drop_duplicates(
        ["settlementDate", "symbolCode"], keep="last")
    a.to_parquet(OUT)
    if verbose:
        print(f"FINRA SI: {len(a):,} rows, {a.settlementDate.nunique()} settlements, "
              f"{a.settlementDate.min()} -> {a.settlementDate.max()}",
              file=sys.stderr, flush=True)
    return a


if __name__ == "__main__":
    build(years=int(sys.argv[1]) if len(sys.argv) > 1 else 4)
