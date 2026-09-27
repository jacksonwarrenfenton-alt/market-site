"""moomoo.com Sectors -- a third independent subsector-strength read, alongside
tvscan.py's TradingView leg and extscan.py's Finviz leg.

Source 7 of the eight-source external-triangulation plan in
EXTERNAL_SOURCES_SPEC.md (jman's own framing: cross-checking the board's own
computed subsector strength against outside reads that never touch our bars).
Only Sectors is built here -- moomoo Themes (source 8, ~105 groups) needs
stockthemes.ai's taxonomy to crosswalk sensibly and is deliberately left for
whoever builds that source; see the note at the bottom of this file.

moomoo's Sectors page has no API -- like Finviz, it's a live signed-in-capable
browser scrape (Claude in Chrome), which is why this, like etfdb and liqn,
can only run device-bound, never on the cloud cron.

THE CROSSWALK IS REUSED, NOT INDEPENDENTLY BUILT. moomoo's ~145 sector names
turned out to be near-identical GICS-style names to Finviz's own 144
industries (confirmed 125/125 of Finviz's crosswalk targets exist verbatim as
moomoo group names), so moomoo_xmap.json is generated mechanically from
finviz_xmap.json's own basket -> fvz mapping, substituting "moo" for "fvz"
wherever that name is also a real moomoo group. This is why coverage lands at
the same 240/253 baskets as the Finviz leg -- it is structurally the same
crosswalk, not an independently verified one. If moomoo renames a sector
Finviz doesn't share, that basket silently drops to NOT COVERED here (never
force-matched) rather than mismatching.

ONE REAL DIFFERENCE FROM THE FINVIZ LEG, worth knowing: moomoo's Sectors page
only exposes a single "chg" figure per group (not separate weekly/quarterly
periods the way Finviz's page does), so this leg cannot replicate Finviz's
0.5*week + 0.5*quarter blend -- it is just that one change reading, whatever
period moomoo's own page happens to show at scrape time. That makes it a
noisier, single-snapshot vote compared to the Finviz leg's blended one; still
a genuine independent outside read, just a rougher one. Worth revisiting if
moomoo's page ever exposes multiple periods.
"""
import pandas as pd, numpy as np, os, json

D = os.path.expanduser("~/pos")
MOOMOO_SCAN = f"{D}/ext_moomoo.csv"
MOOMOO_XMAP = f"{D}/moomoo_xmap.json"
MOOMOO_MAX_AGE_DAYS = 10   # same weekly-cadence assumption as the Finviz leg


def load_moomoo():
    """-> (DataFrame indexed by moomoo group name, as_of date, note) or (None, None, why)."""
    if not os.path.exists(MOOMOO_SCAN):
        return None, None, "no moomoo Sectors scan on disk"
    d = pd.read_csv(MOOMOO_SCAN)
    if not len(d) or "group" not in d.columns:
        return None, None, "moomoo scan is empty or malformed"
    asof = str(d["asof"].iloc[0]) if "asof" in d.columns and len(d) else None
    if asof:
        age = (pd.Timestamp.now().normalize() - pd.Timestamp(asof)).days
        if age > MOOMOO_MAX_AGE_DAYS:
            return None, asof, f"moomoo scan is {age}d old (>{MOOMOO_MAX_AGE_DAYS}d stale)"
    d["chg"] = pd.to_numeric(d["chg"], errors="coerce")
    d = d.drop_duplicates("group", keep="last").set_index("group")
    return d, asof, f"{len(d)} moomoo sector groups, as of {asof}"


def _moomoo_xmap():
    if not os.path.exists(MOOMOO_XMAP): return {}
    try:
        raw = json.load(open(MOOMOO_XMAP))
        return {b: v["moo"] for b, v in raw.items() if v.get("moo")}
    except Exception:
        return {}


def leg_moomoo(names):
    """moomoo's own Sectors performance, aligned to the board's baskets.

    Raw value is moomoo's single "chg" reading (see module docstring for why
    this can't be a two-period blend like the Finviz leg). confluence.py
    percentiles this cross-sectionally same as every other leg.
    """
    d, asof, note = load_moomoo()
    xmap = _moomoo_xmap()
    if d is None:
        return pd.Series(np.nan, index=range(len(names))), asof, note
    out = []
    for n in names:
        moo_name = xmap.get(str(n))
        out.append(d["chg"].get(moo_name, np.nan) if moo_name else np.nan)
    return pd.Series(out), asof, note


SOURCES = {
    "moo": leg_moomoo,
}


def leg(source, names):
    fn = SOURCES.get(source)
    if fn is None:
        return pd.Series(np.nan, index=range(len(names))), None, f"unknown moomoo source {source!r}"
    return fn(names)


# moomoo Themes (source 8) -- NOT built. It needs stockthemes.ai's taxonomy to
# crosswalk sensibly first (also unbuilt); forcing its ~105 groups onto this
# industry crosswalk would silently mismatch most of them, since Themes names
# describe trades/narratives ("AI Power Demand", "Onshoring") rather than
# GICS-style industries, and Finviz's industry crosswalk has no equivalent
# target for most of them. Do this only after stockthemes.ai's own taxonomy
# exists to crosswalk against -- see EXTERNAL_SOURCES_SPEC.md.
