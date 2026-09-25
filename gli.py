"""A global liquidity composite, and what testing it actually showed.

Built from six market-priced conditions, each z-scored against its own trailing
three years so no single component dominates by units:

  dollar (inverted)   a weaker dollar loosens conditions for everyone funding in it
  credit HYG/LQD      compensation demanded for credit risk, rate move stripped out
  curve TLT/SHY       duration ratio; rises when the long end outperforms the front
  VIX (inverted)      the price of protection
  copper/gold         the cyclical-vs-defensive real-asset pair
  breakevens TIP/IEF  inflation compensation, the other side of real rates

The chain being modelled is jman's own research library's, not invented here.
WSG 2026-03-31: "higher real rates ... financial conditions tighten, growth
rerates, P/E's contract, dollar appreciates and cyclicals under-perform."

WHAT THE TEST FOUND -- and it changes how this should be used.

426 driver/target/horizon combinations, weekly 2010-2026, overlap-corrected and
Benjamini-Hochberg controlled. **Nothing leads.** Zero survived correction. The
median leading correlation is 0.045 against a median same-week correlation of
0.263: these relationships are roughly six times stronger CONTEMPORANEOUSLY than
predictively, and only 16% of tests had the lead beat the same-week reading at
all.

The coincident structure is real and the signs are exactly as WSG describes --
dollar vs EFA/SPY -0.56, VIX vs SPY -0.77, credit vs SPY +0.51, copper/gold vs
EEM +0.75. So this is a REGIME INSTRUMENT: it tells you what conditions are
right now, which is what a financial-conditions index is for. It is not a
forecast, and presenting it as one would be dressing up a coincident indicator.

The one directional pattern worth watching: sorted into terciles, LOW liquidity
readings are followed by better forward returns than HIGH ones, in 12 of 12
target/horizon cuts. EEM at 26 weeks is the widest -- +4.2% after low readings
versus -4.8% after high, a 9-point spread. That is the opposite of the popular
"liquidity up, markets up" claim; it behaves like a mean-reversion gauge. But
effective n at that horizon is 10, every individual cut has p > 0.18, and the
cuts overlap heavily, so this is a hypothesis to watch build, not an edge.
"""
import pandas as pd, numpy as np, json, os, math, html

D = os.path.expanduser("~/pos")
WIN = 156          # three years of weekly observations for the z window
COMPONENTS = [
    ("dollar_inv", "Dollar (inverted)", "UUP", None, -1),
    ("credit",     "Credit HYG/LQD",    "HYG", "LQD", +1),
    ("curve",      "Curve TLT/SHY",     "TLT", "SHY", +1),
    ("vix_inv",    "VIX (inverted)",    "^VIX", None, -1),
    ("coppergold", "Copper/Gold",       "COPX", "GLD", +1),
    ("breakeven",  "Breakevens TIP/IEF","TIP", "IEF", +1),
]


def build(lib):
    if not lib or not lib.get("series"): return None
    idx = pd.DatetimeIndex(lib["dates"])
    S = {k: pd.Series(v, index=idx, dtype="float64") for k, v in lib["series"].items()}
    cols = {}
    for key, label, a, b, sign in COMPONENTS:
        if a not in S: continue
        v = S[a] / S[b] if (b and b in S) else S[a]
        v = v.replace([np.inf, -np.inf], np.nan)
        if (v.dropna() <= 0).any(): continue
        v = sign * np.log(v)
        z = (v - v.rolling(WIN, min_periods=60).mean()) / v.rolling(WIN, min_periods=60).std()
        cols[key] = z
    if len(cols) < 4: return None
    Z = pd.DataFrame(cols)
    g = Z.mean(axis=1).dropna()
    return {"idx": idx, "Z": Z, "gli": g, "S": S}


def panel(lib):
    o = build(lib)
    if o is None: return ""
    g, Z, S = o["gli"], o["Z"], o["S"]
    cur = float(g.iloc[-1])
    pct = float((g <= cur).mean() * 100)
    chg13 = float(cur - g.iloc[-14]) if len(g) > 14 else np.nan
    state = ("LOOSE" if cur >= 0.5 else "TIGHT" if cur <= -0.5 else "NEUTRAL")
    tone = "good" if state == "LOOSE" else ("crit" if state == "TIGHT" else "dim")

    comp = ""
    for key, label, _a, _b, _s in COMPONENTS:
        if key not in Z.columns: continue
        v = Z[key].dropna()
        if not len(v): continue
        z = float(v.iloc[-1])
        w = max(-3, min(3, z))
        pos = 50 + w / 3 * 50
        comp += (f'<div class="clrow"><span class="cln">{label}</span>'
                 f'<span class="clbar"><i style="left:{min(pos,50):.1f}%;'
                 f'width:{abs(pos-50):.1f}%;background:'
                 f'{"var(--good)" if z>=0 else "var(--crit)"}"></i></span>'
                 f'<span class="clv {"up" if z>=0 else "dn"}">{z:+.2f}</span></div>')

    # No history chart here on purpose -- this is a current-reading regime tile,
    # not a multi-year chart to stare at. A short-horizon momentum book needs to
    # know where conditions sit RIGHT NOW; the trend of a weekly liquidity
    # composite since 2010 doesn't inform a trade held for days. The full test
    # this composite was built on is condensed in _findings() below, in text,
    # for the same reason.
    return (
      '<h2>Global liquidity composite</h2>'
      '<p class="grpnote">Six market-priced conditions &mdash; the dollar inverted, '
      'credit, the curve, volatility inverted, copper/gold and breakevens &mdash; each '
      'z-scored against its own trailing three years so none dominates by units. '
      'Current reading only &mdash; see the note below for why there is no chart here.</p>'
      f'<div class="glibox"><div class="glihead">'
      f'<div><h6>Composite</h6><div class="v {tone}">{cur:+.2f}</div>'
      f'<div class="s">{state} &middot; {pct:.0f}th percentile of its history</div></div>'
      f'<div><h6>13-week change</h6><div class="v">{chg13:+.2f}</div>'
      f'<div class="s">{"loosening" if chg13 > 0 else "tightening"}</div></div>'
      f'<div class="glisay">Read this as <b>where conditions are</b>, not where they '
      'are going. The components disagreeing is itself information: a composite '
      'near zero built from two strong positives and two strong negatives is a '
      'very different market from one where everything sits flat.</div></div>'
      f'<div class="clist">{comp}</div></div>'
      + _findings())


def _findings():
    # Condensed from the full 426-combination backtest table (dropped along with
    # the history chart -- this is the one-paragraph honest version, not the
    # research writeup). Full detail is in the project's positioning research
    # notes if it's ever needed again.
    return (
      '<p class="grpnote">Tested against 426 driver&times;target&times;horizon '
      'combinations, 2010&ndash;2026: <b>zero survive correction</b> as a lead. '
      'The coincident structure is real (dollar vs EFA/SPY &minus;0.56, VIX vs '
      'SPY &minus;0.77, copper/gold vs EEM +0.75) but six times stronger same-week '
      'than predictive &mdash; this composite says what conditions <i>are</i>, not '
      'where they&rsquo;re going. Treat it as a regime filter for which setup '
      'class to lean on, not a timing signal.</p>')
