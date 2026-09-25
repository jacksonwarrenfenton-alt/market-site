"""Global rotation and financial conditions, on one tab.

Two questions a US-only board cannot answer.

WHERE IS THE MONEY GOING -- US against developed and emerging, the currency that
drives that choice, and the ratios that turn before the absolute prices do.
Ratios matter more than levels here: SPY can rise while losing to EEM, and the
ratio is what a rotation trade actually owns.

WHAT ARE CONDITIONS DOING -- the dollar, credit, the curve and volatility. These
move together more often than they move alone, so they are shown as one block
rather than four unrelated charts. Nothing here is a forecast: it is the
backdrop that decides whether a breakout gets funded or sold.

Every series is drawn from the same embedded library the chart builder uses --
weekly, back to 2010 -- so the numbers here and there cannot disagree.
"""
import json, html
import pandas as pd, numpy as np

C = {"blue": "#3987e5", "amber": "#fab219", "violet": "#9085e9",
     "green": "#0ca30c", "red": "#d03b3b", "grey": "#898781", "teal": "#5ec8d8"}


def _ratio(lib, a, b):
    A, B = lib["series"].get(a), lib["series"].get(b)
    if not A or not B: return None
    out = []
    for x, y in zip(A, B):
        out.append(None if (x is None or y is None or not y) else x / y)
    return out


def _idx100(v):
    if not v: return None
    base = next((x for x in v if x is not None and np.isfinite(x)), None)
    if not base: return None
    return [None if x is None else 100 * x / base for x in v]


def _blocks(lib):
    S = lib["series"]
    def s(k): return S.get(k)
    B = []

    # ---- US vs the rest -------------------------------------------------
    B.append(("us-row-1", "US vs developed vs emerging",
              "All three indexed to 100 at the start of the window, so the "
              "divergence is the whole story rather than three price levels.",
              [{"name": "S&P 500", "vals": s("SPY"), "color": C["blue"]},
               {"name": "Developed ex-US", "vals": s("EFA"), "color": C["amber"]},
               {"name": "Emerging", "vals": s("EEM"), "color": C["violet"]}],
              False))
    B.append(("us-row-2", "The ratios, against the dollar",
              "EEM/SPY and EFA/SPY on the left, the dollar on the right. A rising "
              "dollar is the standard headwind for both &mdash; when the ratios rise "
              "while the dollar does too, the rotation is being driven by something "
              "other than currency and is usually more durable.",
              [{"name": "EEM / SPY", "vals": _ratio(lib, "EEM", "SPY"), "color": C["violet"]},
               {"name": "EFA / SPY", "vals": _ratio(lib, "EFA", "SPY"), "color": C["amber"]},
               {"name": "US dollar", "vals": s("UUP"), "color": C["grey"], "axis": 2}],
              False))
    B.append(("us-row-3", "Currencies",
              "The euro, yen and sterling against the dollar proxy. The yen is the "
              "one to watch for risk: it strengthens when carry unwinds, which "
              "shows up in equities before anything else does.",
              [{"name": "Euro", "vals": s("FXE"), "color": C["blue"]},
               {"name": "Yen", "vals": s("FXY"), "color": C["red"]},
               {"name": "Sterling", "vals": s("FXB"), "color": C["teal"]},
               {"name": "Dollar", "vals": s("UUP"), "color": C["grey"]}],
              False))
    B.append(("us-row-4", "Country dispersion",
              "China, Japan, Brazil and India indexed together. Emerging is not one "
              "trade &mdash; when these separate, an EEM position is really a bet on "
              "whichever of them dominates the index that year.",
              [{"name": "China", "vals": s("FXI"), "color": C["red"]},
               {"name": "Japan", "vals": s("EWJ"), "color": C["blue"]},
               {"name": "Brazil", "vals": s("EWZ"), "color": C["green"]},
               {"name": "India", "vals": s("INDA"), "color": C["amber"]}],
              False))

    # ---- conditions -----------------------------------------------------
    B.append(("fci-1", "Credit &mdash; high yield against duration",
              "HYG/LQD and HYG/IEF. Both strip out the rate move and leave the "
              "compensation demanded for credit risk. This is the cleanest daily "
              "read on conditions available without a subscription: it leads "
              "equity drawdowns more reliably than the VIX does.",
              [{"name": "HYG / LQD", "vals": _ratio(lib, "HYG", "LQD"), "color": C["green"]},
               {"name": "HYG / IEF", "vals": _ratio(lib, "HYG", "IEF"), "color": C["teal"]},
               {"name": "S&P 500", "vals": s("SPY"), "color": C["grey"], "axis": 2}],
              False))
    B.append(("fci-2", "The curve, by proxy",
              "TLT/SHY is a duration ratio, not a yield spread, but it moves with "
              "the curve: it rises when the long end outperforms the front, which "
              "is what bull flattening looks like. Shown against TIP/IEF, the "
              "market&rsquo;s inflation compensation.",
              [{"name": "TLT / SHY (curve proxy)", "vals": _ratio(lib, "TLT", "SHY"), "color": C["blue"]},
               {"name": "TIP / IEF (breakevens)", "vals": _ratio(lib, "TIP", "IEF"), "color": C["amber"]}],
              False))
    B.append(("fci-5", "Rate volatility and the real-rate proxy",
              "MOVE is the bond market&rsquo;s VIX &mdash; it moves before equity vol in "
              "most rate-driven episodes. Shown with the 10-year yield, since the "
              "level and the volatility of rates tighten conditions through "
              "different channels.",
              [{"name": "MOVE", "vals": s("^MOVE"), "color": C["red"]},
               {"name": "US 10y yield", "vals": s("^TNX"), "color": C["amber"], "axis": 2}],
              False))
    B.append(("fci-6", "The precious-metals complex",
              "Gold/silver is the classic liquidity tell &mdash; silver is the more "
              "industrial, more speculative metal, so the ratio falls when risk "
              "appetite and real activity are strong. Miners against the metal say "
              "whether the move is being believed enough to fund the equity.",
              [{"name": "Gold / silver", "vals": _ratio(lib, "GLD", "SLV"), "color": C["amber"]},
               {"name": "Miners / gold", "vals": _ratio(lib, "GDX", "GLD"), "color": C["violet"]},
               {"name": "Junior / senior gold", "vals": _ratio(lib, "GDXJ", "GDX"), "color": C["teal"]}],
              False))
    B.append(("fci-7", "Risk appetite and defensives",
              "High beta against low volatility, speculative growth against the "
              "market, and staples against discretionary on an equal-weight basis "
              "so the mega-caps do not decide the answer.",
              [{"name": "High beta / low vol", "vals": _ratio(lib, "SPHB", "SPLV"), "color": C["green"]},
               {"name": "ARKK / SPY", "vals": _ratio(lib, "ARKK", "SPY"), "color": C["violet"]},
               {"name": "Staples / disc (EW)", "vals": _ratio(lib, "RSPS", "RSPD"), "color": C["red"]}],
              False))
    B.append(("us-row-5", "EM currency effect",
              "EEM against its currency-hedged twin isolates the FX contribution: "
              "when this rises, EM equity gains are coming from the currency rather "
              "than the underlying, which is a dollar trade wearing an equity label. "
              "CEW is the EM currency basket itself.",
              [{"name": "EEM / HEEM (FX effect)", "vals": _ratio(lib, "EEM", "HEEM"), "color": C["violet"]},
               {"name": "EFA / HEFA", "vals": _ratio(lib, "EFA", "HEFA"), "color": C["amber"]},
               {"name": "EM currencies", "vals": s("CEW"), "color": C["teal"]}],
              False))
    B.append(("fci-3", "Volatility and the dollar",
              "The two prices that tighten conditions fastest. A rising dollar with "
              "rising vol is the combination that breaks trends; either alone "
              "usually does not.",
              [{"name": "VIX", "vals": s("^VIX"), "color": C["red"]},
               {"name": "US dollar", "vals": s("UUP"), "color": C["grey"], "axis": 2}],
              False))
    B.append(("fci-4", "Cyclical confirmation",
              "Copper miners, oil, banks and regional banks. Conditions readings "
              "that are not confirmed by the cyclicals tend not to hold &mdash; these "
              "are what actually has to fund.",
              [{"name": "Copper miners", "vals": s("COPX"), "color": C["amber"]},
               {"name": "Crude", "vals": s("USO"), "color": C["red"]},
               {"name": "Banks", "vals": s("XLF"), "color": C["blue"]},
               {"name": "Regional banks", "vals": s("KRE"), "color": C["teal"]}],
              False))
    return [b for b in B if any(x["vals"] for x in b[3])]


def _tiles(lib):
    """Where things stand right now, as changes rather than levels."""
    S = lib["series"]
    def chg(v, w):
        if not v: return None
        a = [x for x in v if x is not None and np.isfinite(x)]
        if len(a) <= w: return None
        return 100 * (a[-1] / a[-1 - w] - 1)
    rows = [
        ("EEM / SPY", _ratio(lib, "EEM", "SPY")),
        ("EFA / SPY", _ratio(lib, "EFA", "SPY")),
        ("HYG / LQD", _ratio(lib, "HYG", "LQD")),
        ("TLT / SHY", _ratio(lib, "TLT", "SHY")),
        ("US dollar", S.get("UUP")),
        ("VIX", S.get("^VIX")),
    ]
    out = ""
    for name, v in rows:
        c4, c13 = chg(v, 4), chg(v, 13)
        if c4 is None: continue
        tone = "up" if c4 >= 0 else "dn"
        out += (f'<div class="gtile"><h6>{name}</h6>'
                f'<div class="v {tone}">{c4:+.1f}%</div>'
                f'<div class="s">4 weeks &middot; 13w '
                f'{"&ndash;" if c13 is None else f"{c13:+.1f}%"}</div></div>')
    return f'<div class="gtiles">{out}</div>' if out else ""


def panel(lib):
    if not lib or not lib.get("series"): return ""
    blocks = _blocks(lib)
    if not blocks: return ""
    # Group by section rather than trust insertion order -- the EM-currency
    # block (us-row-5) was appended after the FCI group in _blocks, which
    # split "US vs the rest of the world" into two pieces with the credit
    # section's header repeated in between. Sorting by prefix here means a
    # future block landing out of order degrades to "shows up in the wrong
    # spot within its section" instead of "duplicates a heading".
    blocks = [b for b in blocks if b[0].startswith("us-")] + \
             [b for b in blocks if not b[0].startswith("us-")]
    dates = lib["dates"]
    specs = {}
    body = ""
    section = None
    for bid, title, why, series, zero in blocks:
        sec = "US vs the rest of the world" if bid.startswith("us-") else \
              "Credit, liquidity and financial conditions"
        if sec != section:
            section = sec
            body += f'<h2>{sec}</h2>'
            if sec.startswith("US"):
                body += ('<p class="grpnote">Ratios rather than levels: the S&amp;P can '
                         'rise while losing to emerging markets, and a rotation trade '
                         'owns the ratio, not the index. Every chart has its own '
                         'timeframe brush &mdash; drag an edge and both axes rescale to '
                         'what is inside the window.</p>' + _tiles(lib))
            else:
                body += ('<p class="grpnote">The backdrop that decides whether a '
                         'breakout gets funded or sold. These move together far more '
                         'often than they move alone, which is why they sit in one '
                         'block. None of it forecasts direction; it sets the odds on '
                         'whatever the price is already doing.</p>')
        body += (f'<div class="gblock"><h4>{title}</h4>'
                 f'<p class="dnote">{why}</p><div id="{bid}" class="mc"></div></div>')
        specs[bid] = {"dates": dates, "zero": zero, "mode": "index",
                      "series": [{"name": s["name"], "vals": s["vals"],
                                  "color": s["color"], "axis": s.get("axis", 1)}
                                 for s in series if s["vals"]]}
    return (body + f'<script id="gdata" type="application/json">'
            f'{json.dumps(specs, separators=(",", ":"))}</script>'
            '<script>(function(){var G=JSON.parse(document.getElementById("gdata").textContent);'
            'function go(){ if(!window.MC){ return setTimeout(go,40); } '
            'Object.keys(G).forEach(function(k){ MC.mount(k, G[k]); }); } go();})();</script>')


def _ctiles(lib):
    """Quick 4w/13w reads on the handful of commodity series jman actually
    watches for the inflation-underpriced thesis (WSG commodity-basket note,
    DBA/DBB/DBC/DBP), same tile format as the rotation tab's _tiles()."""
    S = lib["series"]
    def chg(v, w):
        if not v: return None
        a = [x for x in v if x is not None and np.isfinite(x)]
        if len(a) <= w: return None
        return 100 * (a[-1] / a[-1 - w] - 1)
    rows = [("Gold", S.get("GLD")), ("Silver", S.get("SLV")),
            ("Copper miners", S.get("COPX")), ("Crude", S.get("USO")),
            ("Broad commodity", S.get("DBC")), ("Agriculture", S.get("DBA"))]
    out = ""
    for name, v in rows:
        c4, c13 = chg(v, 4), chg(v, 13)
        if c4 is None: continue
        tone = "up" if c4 >= 0 else "dn"
        out += (f'<div class="gtile"><h6>{name}</h6>'
                f'<div class="v {tone}">{c4:+.1f}%</div>'
                f'<div class="s">4 weeks &middot; 13w '
                f'{"&ndash;" if c13 is None else f"{c13:+.1f}%"}</div></div>')
    return f'<div class="gtiles">{out}</div>' if out else ""


def commodities_panel(lib):
    """Precious metals, energy and ags/base metals -- the complex behind
    jman's inflation-underpriced thesis (DBA/DBB/DBC/DBP, gold/silver vs the
    dollar). Everything here is already fetched for the chart library, so
    this adds zero new network calls -- it just gives the series their own
    labelled section instead of living buried one component deep inside the
    liquidity composite."""
    if not lib or not lib.get("series"): return ""
    S = lib["series"]
    def s(k): return S.get(k)

    def ratio(a, b):
        A, B = S.get(a), S.get(b)
        if not A or not B: return None
        return [None if (x is None or y is None or not y) else x / y for x, y in zip(A, B)]

    blocks = [
        ("cm-1", "Precious metals",
         "Gold, silver, platinum and palladium indexed together. Silver is the "
         "more industrial, more speculative metal of the pair -- it leading gold "
         "higher is a real-activity/risk-appetite tell, not just a beta effect.",
         [{"name": "Gold", "vals": s("GLD"), "color": "#fab219"},
          {"name": "Silver", "vals": s("SLV"), "color": "#898781"},
          {"name": "Platinum", "vals": s("PPLT"), "color": "#5ec8d8"},
          {"name": "Palladium", "vals": s("PALL"), "color": "#9085e9"}]),
        ("cm-2", "Miners vs the metal",
         "Gold/silver ratio (classic liquidity tell -- falls when risk appetite "
         "and industrial demand are strong) against miners priced relative to "
         "gold itself, and junior vs senior miners as the speculative-tip read.",
         [{"name": "Gold / silver", "vals": ratio("GLD", "SLV"), "color": "#fab219"},
          {"name": "Miners / gold (GDX/GLD)", "vals": ratio("GDX", "GLD"), "color": "#9085e9"},
          {"name": "Junior / senior (GDXJ/GDX)", "vals": ratio("GDXJ", "GDX"), "color": "#5ec8d8"}]),
        ("cm-3", "Energy",
         "Crude, natural gas and the broad commodity index (DBC) indexed "
         "together -- energy is the single biggest weight in most broad "
         "commodity baskets, so this is usually what DBC is actually tracking.",
         [{"name": "Crude oil", "vals": s("USO"), "color": "#d03b3b"},
          {"name": "Natural gas", "vals": s("UNG"), "color": "#5ec8d8"},
          {"name": "Broad commodity (DBC)", "vals": s("DBC"), "color": "#c3c2b7"}]),
        ("cm-4", "Agriculture &amp; base metals",
         "The two DB baskets behind the inflation-underpriced thesis (DBA "
         "ags, DBB base metals) against copper miners as the cyclical-demand "
         "confirmation -- a base-metals move not echoed in copper miners is "
         "usually a supply story, not a demand one.",
         [{"name": "Agriculture (DBA)", "vals": s("DBA"), "color": "#0ca30c"},
          {"name": "Base metals (DBB)", "vals": s("DBB"), "color": "#c98a2b"},
          {"name": "Copper miners (COPX)", "vals": s("COPX"), "color": "#e0709a"}]),
        ("cm-5", "Commodities vs the dollar",
         "The broad commodity index and gold against the dollar -- the "
         "standard headwind/tailwind. A commodity move that holds up even as "
         "the dollar rises is the stronger, less currency-dependent read.",
         [{"name": "Broad commodity (DBC)", "vals": s("DBC"), "color": "#c3c2b7"},
          {"name": "Gold (GLD)", "vals": s("GLD"), "color": "#fab219"},
          {"name": "US dollar (UUP)", "vals": s("UUP"), "color": "#898781", "axis": 2}]),
    ]
    blocks = [b for b in blocks if any(x["vals"] for x in b[3])]
    if not blocks: return ""

    dates = lib["dates"]
    specs, body = {}, ""
    for bid, title, why, series in blocks:
        body += (f'<div class="gblock"><h4>{title}</h4>'
                 f'<p class="dnote">{why}</p><div id="{bid}" class="mc"></div></div>')
        specs[bid] = {"dates": dates, "zero": False, "mode": "index",
                      "series": [{"name": x["name"], "vals": x["vals"],
                                  "color": x["color"], "axis": x.get("axis", 1)}
                                 for x in series if x["vals"]]}
    return (_ctiles(lib) + body
            + '<script id="cmdata" type="application/json">'
            + json.dumps(specs, separators=(",", ":")) + '</script>'
            '<script>(function(){var G=JSON.parse(document.getElementById("cmdata").textContent);'
            'function go(){ if(!window.MC){ return setTimeout(go,40); } '
            'Object.keys(G).forEach(function(k){ MC.mount(k, G[k]); }); } go();})();</script>')
