"""Cross-asset regime read: where equity / bond / commodity / cash weight
should lean, built from liqn's market-stress verdict, the GLI liquidity
composite, MOVE, the 10-year yield trend and the dollar -- then a sector
drill-down using the subsector board's own current rankings, so the
top-level call and the sector list come from the same run instead of two
separate opinions.

This is a DIFFERENT question from regime.py's BREAKOUT/CHOPPY/DOWNTREND
call. regime.py answers "which of jman's setups is live" from short-term
trend and breadth -- a tactical, days-to-weeks read. This answers "what
backdrop is macro/positioning setting" from liquidity and rates -- a
slower, more structural one. The two are meant to be read together, not
reconciled: a tactical breakout inside a macro backdrop that does not
support it is a different trade than one where both agree.

Every input here already exists elsewhere on the board (GLI, liqn's stress
history, the embedded chart library, the subsector rankings) -- this adds
zero new fetches, it only combines what is already computed.
"""
import numpy as np, pandas as pd, html

WIN = 156  # 3yr weekly, matches gli.py's own z-window


def _z_last(series):
    s = pd.Series(series, dtype="float64").dropna()
    if len(s) < 60: return None
    w = s.tail(WIN)
    mu, sd = w.mean(), w.std()
    if not sd or not np.isfinite(sd): return None
    return float((s.iloc[-1] - mu) / sd)


def _chg(series, weeks=13):
    s = pd.Series(series, dtype="float64").dropna()
    if len(s) <= weeks: return None
    return float(100 * (s.iloc[-1] / s.iloc[-1 - weeks] - 1))


def _read(lib):
    """The scored components, kept in one small transparent table rather
    than a black-box number -- every input that moved the call is visible."""
    import gli as GLI
    import liqn as LQ

    bits = []  # (label, state_text, tone, score_contribution)
    score = 0.0

    gobj = GLI.build(lib)
    if gobj is not None:
        cur = float(gobj["gli"].iloc[-1])
        state = "LOOSE" if cur >= 0.5 else ("TIGHT" if cur <= -0.5 else "NEUTRAL")
        s = 1 if state == "LOOSE" else (-1 if state == "TIGHT" else 0)
        score += s
        bits.append(("Global liquidity composite", f"{state} ({cur:+.2f})",
                    "good" if s > 0 else ("crit" if s < 0 else "dim"), s))

    try:
        sd = LQ.load_stress()
    except Exception:
        sd = None
    if sd is not None and len(sd):
        verdict = str(sd.iloc[-1].verdict).rstrip(".")
        s = {"Normal": 0, "Stealth Rotation": 0, "Shock": -2, "Regime Break": -2}.get(verdict, 0)
        score += s
        bits.append(("Market stress monitor", verdict,
                    "good" if s == 0 else "crit", s))

    S = lib.get("series", {})
    mz = _z_last(S.get("^MOVE"))
    if mz is not None:
        s = -1 if mz >= 1.0 else (1 if mz <= -0.5 else 0)
        score += s
        bits.append(("MOVE (rate volatility)", f"{mz:+.1f}&sigma; vs its own 3yr range",
                    "crit" if s < 0 else ("good" if s > 0 else "dim"), s))

    dchg = _chg(S.get("UUP"))
    dollar_tone = 0
    if dchg is not None:
        dollar_tone = -1 if dchg >= 1.5 else (1 if dchg <= -1.5 else 0)
        bits.append(("US dollar, 13-week change", f"{dchg:+.1f}%",
                    "crit" if dollar_tone < 0 else ("good" if dollar_tone > 0 else "dim"), dollar_tone))

    ychg = _chg(S.get("^TNX"))
    yield_up = ychg is not None and ychg >= 3.0
    if ychg is not None:
        bits.append(("10-year yield, 13-week change", f"{ychg:+.1f}%",
                    "warn" if yield_up else "dim", 0))

    return score, dollar_tone, yield_up, bits


def _tilt(label, verdict, tone, why):
    return (f'<div class="altile"><h6>{label}</h6>'
            f'<div class="v {tone}">{verdict}</div><div class="s">{why}</div></div>')


def panel(sub, lib):
    if not lib or not lib.get("series"): return ""
    score, dollar_tone, yield_up, bits = _read(lib)

    if score >= 1.5:   eq, comm, cash = ("OVERWEIGHT", "good"), ("OVERWEIGHT", "good"), ("UNDERWEIGHT", "crit")
    elif score <= -1.5: eq, comm, cash = ("UNDERWEIGHT", "crit"), ("UNDERWEIGHT", "crit"), ("OVERWEIGHT", "good")
    else:              eq, comm, cash = ("NEUTRAL", "dim"), ("NEUTRAL", "dim"), ("NEUTRAL", "dim")
    # Commodities get an extra nudge from the dollar specifically -- jman's
    # own stated read (DXY up hurts metals/crypto/EM/ARKK/credit together).
    if dollar_tone > 0 and comm[0] != "OVERWEIGHT": comm = ("OVERWEIGHT", "good")
    elif dollar_tone < 0 and comm[0] != "UNDERWEIGHT": comm = ("UNDERWEIGHT", "crit")
    # Bonds get their own call off the yield trend regardless of the overall
    # score: a rising-yield backdrop is a duration-risk call jman already
    # holds (short the long end on inflation underpriced), not something the
    # broad liquidity score should overrule.
    if yield_up:
        bond = ("UNDERWEIGHT", "crit")
    elif score >= 1.5:
        bond = ("NEUTRAL", "dim")
    elif score <= -1.5:
        bond = ("OVERWEIGHT", "good")
    else:
        bond = ("NEUTRAL", "dim")

    tiles = (_tilt("Equity", eq[0], eq[1], f"net regime score {score:+.1f}")
             + _tilt("Bonds / duration", bond[0], bond[1],
                    "10y yield uptrend -- duration risk" if yield_up else f"net regime score {score:+.1f}")
             + _tilt("Commodities", comm[0], comm[1],
                    "dollar trend adjusted" if dollar_tone else f"net regime score {score:+.1f}")
             + _tilt("Cash", cash[0], cash[1], f"net regime score {score:+.1f}"))

    rows = "".join(
        f'<div class="clrow"><span class="cln">{lbl}</span>'
        f'<span class="clv {("up" if s>0 else ("dn" if s<0 else "dim"))}">{state}</span></div>'
        for lbl, state, tone, s in bits)

    sector_html = ""
    if sub is not None and len(sub) and "rank" in sub.columns:
        top = sub.sort_values("rank").head(8)
        sector_rows = "".join(
            f'<tr><td class="nm">{html.escape(str(r["name"]))}</td>'
            f'<td>{int(r["rank"])}</td></tr>'
            for _, r in top.iterrows())
        sector_html = (
            '<h5>Sector / industry drill-down &mdash; top-ranked groups right now</h5>'
            '<p class="dnote">Same subsector board as the Subsector tab, filtered to the '
            'current top ranks -- the allocation call above says how much risk to run; '
            'this says where, using this run&rsquo;s own rankings rather than a second '
            'opinion.</p>'
            '<table class="mini"><thead><tr><th>Group</th><th>Rank</th></tr></thead>'
            '<tbody>' + sector_rows + '</tbody></table>')

    return (
        '<h2>Regime &amp; allocation read</h2>'
        '<p class="grpnote">A structural, macro/positioning-driven backdrop read -- '
        'liquidity, stress, rate volatility, the dollar and the yield trend -- distinct '
        'from the tactical BREAKOUT/CHOPPY/DOWNTREND call elsewhere on this board, which '
        'is built from short-term trend and breadth. The two can disagree; when they do, '
        'that disagreement is itself worth noting. This is a framework, not a '
        'backtested signal -- treat the tilt as a starting weight to argue with, not a '
        'position size.</p>'
        f'<div class="altiles">{tiles}</div>'
        f'<div class="clist" style="margin-top:8px">{rows}</div>'
        + sector_html)
