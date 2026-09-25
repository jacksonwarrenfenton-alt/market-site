"""External scanner sources -- browser-scraped reads that sit alongside
tvscan.py's TradingView leg as additional independent confluence legs.

jman's own framing: these are "eight sources" of subsector triangulation he
used to run as a separate scheduled scan against a separate 176-basket price
compute in a different project. That price compute is now redundant (this
site's own roster covers 253 baskets), but the external, browser-scraped
sources themselves are not -- they are genuine outside reads with no
overlap against anything computed from our own bars, exactly like
tvscan.py's TradingView leg. This module is where those sources land as they
get built out, one at a time. Finviz industry performance is the first.

Each source follows the same shape as tvscan.py:
  - a CSV cache on disk, refreshed by a scrape (manual today; scheduled once
    a device-bound trigger can drive the browser reliably)
  - a MAX_AGE_DAYS staleness check -- an old scan says so instead of quietly
    being used
  - a crosswalk from that source's own taxonomy to our 253 basket names,
    since none of these sources know our roster
  - a leg(names) function returning a pd.Series aligned to board names, NaN
    wherever the source doesn't cover a name (no taxonomy match) or the
    whole source is stale/missing -- never imputed or guessed

FINVIZ -- finviz.com/groups.ashx?g=industry, all 7 return periods on one
page load, no login. Its 144 industries are named by business model
(GICS-style) rather than by theme, and are far coarser than our 253 custom
baskets, so the crosswalk in finviz_xmap.json is a many-to-one join: several
of our baskets legitimately share one Finviz industry (e.g. every biotech
therapeutic-area basket maps to Finviz's single "Biotechnology" bucket).
13 of our 253 baskets have no sane Finviz analog at all (crypto treasury,
space & satellites, hydrogen, streaming/gaming platforms, etc.) and are
left uncovered (NaN) rather than forced onto an unrelated bucket -- see
finviz_xmap.json's "no_match_confirmed" entries.
"""
import pandas as pd, numpy as np, os, json

D = os.path.expanduser("~/pos")
FINVIZ_SCAN = f"{D}/ext_finviz.csv"
FINVIZ_XMAP = f"{D}/finviz_xmap.json"
FINVIZ_MAX_AGE_DAYS = 10   # Finviz industry group is a weekly-cadence refresh


def load_finviz():
    """-> (DataFrame indexed by Finviz industry name, as_of date, note) or (None, None, why)."""
    if not os.path.exists(FINVIZ_SCAN):
        return None, None, "no Finviz industry scan on disk"
    d = pd.read_csv(FINVIZ_SCAN)
    if not len(d) or "industry" not in d.columns:
        return None, None, "Finviz scan is empty or malformed"
    asof = str(d["asof"].iloc[0]) if "asof" in d.columns and len(d) else None
    if asof:
        age = (pd.Timestamp.now().normalize() - pd.Timestamp(asof)).days
        if age > FINVIZ_MAX_AGE_DAYS:
            return None, asof, f"Finviz scan is {age}d old (>{FINVIZ_MAX_AGE_DAYS}d stale)"
    for c in ("d", "w", "m", "q", "h", "ytd"):
        if c in d.columns: d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.drop_duplicates("industry", keep="last").set_index("industry")
    return d, asof, f"{len(d)} Finviz industries, as of {asof}"


def _finviz_xmap():
    if not os.path.exists(FINVIZ_XMAP): return {}
    try:
        raw = json.load(open(FINVIZ_XMAP))
        return {b: v["fvz"] for b, v in raw.items() if v.get("fvz")}
    except Exception:
        return {}


def leg_finviz(names):
    """Finviz's own industry-group performance, aligned to the board's baskets.

    Raw value is a 50/50 blend of Finviz's 1-week and 3-month period returns --
    the same short+long framing every other short/long leg on this site uses --
    left as an absolute return (not RS vs SPY, since Finviz doesn't publish a
    benchmark-relative cut). confluence.py percentiles this cross-sectionally
    across our own baskets same as every other leg, so it still reads as a
    relative strength vote even though the underlying number is absolute.
    Many-to-one basket -> industry joins are expected (see module docstring)
    and mean several of our baskets legitimately carry the identical Finviz
    read; that is the coarser source speaking with one voice, not a bug.
    """
    d, asof, note = load_finviz()
    xmap = _finviz_xmap()
    if d is None:
        return pd.Series(np.nan, index=range(len(names))), asof, note
    blend = 0.5 * d["w"] + 0.5 * d["q"]
    out = []
    for n in names:
        fvz_name = xmap.get(str(n))
        out.append(blend.get(fvz_name, np.nan) if fvz_name else np.nan)
    return pd.Series(out), asof, note


# -- generic dispatch, so confluence.py and future sources share one import --
SOURCES = {
    "fvz": leg_finviz,
}


def leg(source, names):
    fn = SOURCES.get(source)
    if fn is None:
        return pd.Series(np.nan, index=range(len(names))), None, f"unknown external source {source!r}"
    return fn(names)
