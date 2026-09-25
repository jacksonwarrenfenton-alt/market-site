"""TradingView Data Window scan -- the one external leg.

Everything else on the board is computed here from bars. This leg is the only
read that comes from outside, so it is the only one that can catch a mistake in
our own roster or return maths. It is harvested by walking one probe ticker per
group through the chart's Data Window; see TV_WALK_NOTES.md for the procedure
and the crosshair trap that will silently poison it.
"""
import pandas as pd, numpy as np, os

D = os.path.expanduser("~/pos")
SCAN = f"{D}/tv_scan.csv"
MAX_AGE_DAYS = 12          # a fortnight-old scan is stale; say so rather than use it


def _num(v):
    if v is None: return np.nan
    v = str(v).replace("−", "-").replace(",", "").strip()
    try: return float(v)
    except Exception: return np.nan


def load():
    """-> (DataFrame indexed by group name, as_of date, note) or (None, None, why)."""
    if not os.path.exists(SCAN):
        return None, None, "no TradingView scan on disk"
    d = pd.read_csv(SCAN)
    if not len(d):
        return None, None, "TradingView scan is empty"
    for c in ("score", "grp_id", "members", "rs1d", "rs5d", "rs21d", "rs63d"):
        d[c] = d[c].map(_num)

    # Rows the walk itself flagged. NOGROUP means the probe has no listing;
    # MISMATCH means the symbol or date did not verify. Neither is usable.
    flagged = d.date.astype(str).str.contains("MISMATCH|NOGROUP", na=False)
    bad = int(flagged.sum())
    d = d[~flagged]

    # The crosshair trap: every row must carry the SAME session. A row on a
    # different date was read at a stale crosshair and is a different week's
    # number wearing this week's label.
    dates = d.date.astype(str).value_counts()
    asof = dates.index[0] if len(dates) else None
    off = int((d.date.astype(str) != asof).sum())
    d = d[d.date.astype(str) == asof]

    # The scan predicts each group's numeric id independently of TradingView.
    # Disagreement means the probe landed in a different group than we think it
    # belongs to, so the row describes the wrong basket.
    wrong = int((d.grp_id != d.numeric_id).sum())
    d = d[d.grp_id == d.numeric_id]

    # The scan keys on the group CODE; the board keys on the group NAME. Join
    # through the probe map that generated the walk so the two cannot drift.
    pm = pd.read_csv(f"{D}/tv_probes_253.csv")[["code", "group"]]
    d = d.merge(pm, on="code", how="left")
    d = d.dropna(subset=["rs21d", "group"]).drop_duplicates("group", keep="last")
    note = (f"{len(d)} of 253 groups; {bad} unusable, {off} off-session, "
            f"{wrong} id mismatch")
    return d.set_index("group"), asof, note


def leg(names):
    """TradingView's own relative-strength read, aligned to the board's groups.

    ONE vote per group, always. Several of the 253 baskets deliberately overlap
    (multiple biotech groups, several bank size-tiers), and a ticker sitting in
    more than one of them must not let this source speak twice -- the join is on
    the group NAME, so each basket takes exactly one row and no row is reused
    across baskets.
    """
    d, asof, note = load()
    if d is None:
        return pd.Series(np.nan, index=range(len(names))), None, note
    # Blend 21D and 63D the way the indicator's own score does, so this leg is
    # TradingView's opinion rather than our re-weighting of its parts.
    v = (d.rs21d + d.rs63d) / 2.0
    return pd.Series([v.get(str(n), np.nan) for n in names]), asof, note
