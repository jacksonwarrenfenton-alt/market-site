"""Cold-start a fresh container into a full site build, in one command.

    python3 bootstrap.py            # every step, then marketsite.build()
    python3 bootstrap.py --no-build # data only
    python3 bootstrap.py cot si     # just the named steps (no build)

This is the daily trigger's Step 2 / 2.5 / 3 recipe as code instead of prose,
so a rebuild no longer depends on a long prompt being followed exactly. Each
step is independent: a failure is logged and the next step still runs, and
the summary at the end says exactly which feeds are missing. Device-bound
feeds (TradingView walk, liqn.ai, etfdb flows) cannot be pulled from a cloud
container and are not attempted -- their panels render as unavailable.
"""
import os, sys, shutil, subprocess, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.expanduser("~/pos")
sys.path.insert(0, HERE)


def _seed():
    os.makedirs(D, exist_ok=True)
    # The build reads the roster from ~/pos, but its source of truth is the repo.
    shutil.copy(f"{HERE}/custom176-rosters.txt", f"{D}/custom176-rosters.txt")


def _cot():
    import cot
    d = cot.build(cot.fetch(force=True))
    d.to_parquet(f"{D}/cot_built.parquet")


def _deepbars():
    import breadth, deepbars
    deepbars.fetch(sorted(breadth.universe().symbol.unique()))


def _sbstat():
    subprocess.run([sys.executable, f"{HERE}/run_sbstat.py"], check=True, cwd=HERE)


STEPS = [
    ("si",        lambda: __import__("si").screener()),
    ("cot",       _cot),
    ("sifinra",   lambda: __import__("sifinra").build()),
    ("breadth",   lambda: __import__("breadth").build(force=True)),
    ("deepbars",  _deepbars),
    ("sbstat",    _sbstat),
    ("daily",     lambda: __import__("daily_refresh").run()),
    ("ratioscan", lambda: __import__("ratioscan").save()),
    ("tickerdesk", lambda: __import__("tickerdesk").save()),
]


def main(argv):
    only = {a for a in argv if not a.startswith("--")}
    build = "--no-build" not in argv and not only
    _seed()
    ok, failed = [], []
    for name, fn in STEPS:
        if only and name not in only:
            continue
        t = time.time()
        print(f"bootstrap: {name} ...", file=sys.stderr, flush=True)
        try:
            fn()
            ok.append(name)
            print(f"bootstrap: {name} ok ({time.time()-t:.0f}s)", file=sys.stderr, flush=True)
        except Exception as e:
            failed.append(name)
            print(f"bootstrap: {name} FAILED ({time.time()-t:.0f}s): {e}", file=sys.stderr, flush=True)
            traceback.print_exc()
    print(f"bootstrap: data {len(ok)}/{len(ok)+len(failed)} ok"
          + (f" -- failed: {failed}" if failed else ""), file=sys.stderr, flush=True)
    if build:
        import marketsite
        p, c, s, r = marketsite.build()
        print(f"bootstrap: built {p} (regime {r['regime']})", file=sys.stderr, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
