"""Positioning-unwind watch: cross-asset squeeze setups from COT extremes.

jman's own framing: if everyone is long the dollar and gold longs are NOT
crowded (near neutral or slightly short), a squeeze that pushes the dollar
lower has room to run in gold, because gold's own positioning has not
already priced that move. This is that logic made systematic across a
curated set of pairs the desk actually watches, using large-speculator COT
percentiles (the same ls_pctile52 column signals.py ranks on) as the
crowding read.

This is a WATCHLIST heuristic, not a backtested signal -- unlike efficacy.py
(which tests every COT cohort against forward returns and reports what
actually worked), no one has tested "pair A crowded + pair B not yet
positioned for the implied move" against history here. Treat it as a
prompt to go look at the chart, not a trade by itself.

PAIRS: (code_a, code_b, sign, note). sign=+1 means the two normally move
together (a crowded-long squeeze in A implies downside pressure carries to
B too, if B has not already priced it); sign=-1 means they normally move
oppositely (a crowded-long squeeze lower in A implies upside room in B).
"""
import numpy as np
from universe import COT_UNIVERSE

PAIRS = [
    ("098662", "088691", -1, "Dollar strength is gold's standard headwind -- the classic inverse."),
    ("098662", "084691", -1, "Same dollar-gold logic, the higher-beta metal."),
    ("098662", "133741", -1, "Dollar and crypto trade as a liquidity/risk-on pair, noisier than metals."),
    ("098662", "067651", -1, "Crude is dollar-priced globally; a weaker dollar is a mechanical tailwind."),
    ("098662", "085692", -1, "Copper is the cyclical, dollar-sensitive industrial metal."),
    ("098662", "099741", -1, "Mechanical: the dollar index is majority euro-weighted."),
    ("088691", "084691", +1, "Gold and silver move together; silver is the higher-beta leg."),
    ("085692", "232741", +1, "Copper and the Aussie dollar are the classic pro-cyclical pair."),
]

EXTREME_HI, EXTREME_LO = 85, 15
ROOM_HI, ROOM_LO = 65, 35   # "not already positioned for the implied move"


def scan(cur):
    """cur: the COT current-percentile dataframe (cftc_contract_market_code,
    ls_pctile52) already built in marketsite.build() -- no new fetch."""
    if cur is None or not len(cur): return []
    pctl = dict(zip(cur.cftc_contract_market_code, cur.ls_pctile52))
    out = []
    for code_a, code_b, sign, note in PAIRS:
        pa, pb = pctl.get(code_a), pctl.get(code_b)
        if pa is None or pb is None or not (np.isfinite(pa) and np.isfinite(pb)):
            continue
        if pa >= EXTREME_HI: crowd_a = 1
        elif pa <= EXTREME_LO: crowd_a = -1
        else: continue
        unwind_a = -crowd_a               # what an unwind does to A
        expect_b = sign * unwind_a        # implied direction for B
        room = (expect_b > 0 and pb <= ROOM_HI) or (expect_b < 0 and pb >= ROOM_LO)
        if not room: continue
        out.append({
            "a": COT_UNIVERSE[code_a][0], "b": COT_UNIVERSE[code_b][0],
            "pa": float(pa), "pb": float(pb),
            "crowd_dir": "long" if crowd_a > 0 else "short",
            "unwind_dir": "falls" if unwind_a < 0 else "rises",
            "expect_dir": "up" if expect_b > 0 else "down",
            "note": note,
        })
    out.sort(key=lambda r: -abs(r["pa"] - 50))
    return out


def panel(cur):
    rows = scan(cur)
    if not rows:
        return ('<h2>Positioning-unwind watch</h2>'
                '<p class="grpnote">No pair in the curated watchlist currently has one '
                'leg at a COT crowding extreme with the other leg still unpriced for the '
                'implied move.</p>')
    body = ""
    for r in rows:
        body += (
            f'<div class="unrow"><div class="unhead">'
            f'<b>{r["a"]}</b> specs are <b class="{"up" if r["crowd_dir"]=="long" else "dn"}">'
            f'crowded {r["crowd_dir"]}</b> ({r["pa"]:.0f}th pctile 52w) &mdash; if that '
            f'unwinds, {r["a"]} likely <b>{r["unwind_dir"]}</b>.</div>'
            f'<div class="unbody">Implied move for <b>{r["b"]}</b>: <b class="'
            f'{"up" if r["expect_dir"]=="up" else "dn"}">{r["expect_dir"]}</b> &mdash; and '
            f'{r["b"]} specs sit at only the {r["pb"]:.0f}th percentile, so that move is '
            f'<b>not already priced</b> in {r["b"]}&rsquo;s own positioning.</div>'
            f'<div class="undim">{r["note"]}</div></div>')
    return (
        '<h2>Positioning-unwind watch</h2>'
        '<p class="grpnote">A curated cross-asset pair list, screened for exactly the '
        'setup jman described: one leg crowded at a COT extreme, the other leg '
        'historically linked to it but NOT yet positioned for the move a squeeze would '
        'imply. This is a prompt to go look at the chart, not a backtested signal -- '
        'unlike efficacy.py&rsquo;s cohort tests elsewhere on this board, no one has '
        'measured whether this specific heuristic predicts anything on this sample.</p>'
        f'<div class="ungrid">{body}</div>')
