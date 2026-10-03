"""One place that pulls every daily-cadence feed before the site rebuilds.

The site's daily cloud rebuild (the "Daily 5pm ET" trigger) bootstraps a
fresh container each run and its own prompt already handles the
weekly/biweekly-cadence heavy lifting directly -- si.screener(),
cot.fetch(force=True)+cot.build(), sifinra.build(), breadth.build(force=True),
deepbars.fetch()+run_sbstat.py -- every single weekday, cold-start, before
this module ever runs. That is correct and sufficient: those datasets only
settle weekly (COT, Fridays) or twice a month (FINRA, 11th/27th), so a fresh
pull every weekday is already more than fresh enough. There is no separate
cloud trigger for them and none is needed -- don't add one; it would just
duplicate what Step 2 of the daily trigger's own prompt already does.

The one real gap found in that recipe (pass 17): ETF flow snapshots. Nothing
was ever calling flows.take_snapshot(), so basket_flows() read whatever the
last manual capture happened to be (it sat frozen for weeks at a time). Fixed
by adding `etfflows` below -- take_snapshot() guards its own writes against
near-duplicate captures (MIN_GAP_DAYS=4 in flows.py), so calling it daily
here is safe and correct even though the underlying flow data only usefully
diffs weekly.

Some of what's left already refreshes on every site rebuild for free, because
it's computed live from data already being pulled (breadth, stockbee,
subsector, confluence -- all inside marketsite.build() itself) or fetched
incrementally inside build() directly (earnrx). This module exists for the
rest: real network fetches that marketsite.build() was only ever reading a
cached file for, so they'd go stale silently until someone happened to re-run
them by hand. That was the actual gap behind "fed watch, stockbee, anything
that updates daily should update daily" -- stockbee was already fine; fed
watch, VIX term structure, the macro calendar and Google Trends were not.

`universe` (si.screener()) is already covered by Step 2 of the daily
trigger's own prompt above -- included here too anyway since it self-caches
for 24h internally and is nearly free to call, in case this module is ever
run standalone (e.g. by hand, mid-session) without that Step 2 having run
first.

Run this, THEN marketsite.build(). (The daily trigger's own prompt already
calls this as its Step 2.5, after its Step 2 cold-start recipe above.)
"""
import sys, traceback

STEPS = [
    ("fedwatch",   lambda: __import__("fedwatch").fetch()),
    ("vixterm",    lambda: __import__("vixterm").snapshot()),
    ("econcal",    lambda: __import__("econcal").fetch()),
    ("news",       lambda: __import__("newsfeed").fetch()),
    ("earnings",   lambda: __import__("earnings").build(days=90, verbose=False)),
    ("chartdata",  lambda: __import__("chartdata").save()),
    ("trends",     lambda: __import__("trends").fetch()),
    ("trends_hot", lambda: __import__("trends").fetch_hot()),
    ("universe",   lambda: __import__("si").screener()),
    ("etfflows",   lambda: __import__("flows").take_snapshot()),
]


def run(only=None, skip=None):
    ok, failed = [], []
    for name, fn in STEPS:
        if only and name not in only: continue
        if skip and name in skip: continue
        try:
            fn()
            ok.append(name)
            print(f"daily_refresh: {name} ok", file=sys.stderr, flush=True)
        except Exception as e:
            failed.append((name, str(e)))
            print(f"daily_refresh: {name} FAILED: {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
    total = len(only) if only else len(STEPS)
    print(f"daily_refresh: {len(ok)}/{total} ok"
          + (f" -- failed: {[n for n, _ in failed]}" if failed else ""),
          file=sys.stderr, flush=True)
    return ok, failed


if __name__ == "__main__":
    only = set(sys.argv[1:]) or None
    ok, failed = run(only)
    sys.exit(1 if failed and len(failed) == (len(only) if only else len(STEPS)) else 0)
