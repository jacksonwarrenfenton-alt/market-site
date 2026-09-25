"""Most crowded / most washed-out names, at a glance.

The ranked board gives one row per contract with the winning cohort. What it
does not do is answer the first question anyone actually asks: where is the
crowd most one-sided RIGHT NOW, across everything, in one short list.

Crowding is measured as distance from neutral on the 52-week percentile, and a
name only qualifies if its extremity clears the same bar the ranked board uses,
so this list can never disagree with the board beneath it.

Open interest is deliberately absent: it was removed as a signal after failing
at every horizon and tail, so including it here would smuggle it back in.
"""
import pandas as pd, numpy as np, html

TOP = 8
MIN_E = 0.60

COHORTS = [("ls",   "ls_pctile52",   "Large spec", -1),
           ("ss",   "ss_pctile52",   "Small spec", -1),
           ("comm", "comm_pctile52", "Commercial", +1)]


def build(cu):
    rows = []
    for _, r in cu.iterrows():
        best = None
        for ck, col, label, sign in COHORTS:
            v = r.get(col)
            if v is None or pd.isna(v): continue
            e = (float(v) - 50) / 50
            if best is None or abs(e) > abs(best["e"]):
                best = {"name": r.get("disp") or r.get("cftc_contract_market_code"),
                        "cls": r.get("cls"), "cohort": label, "pct": float(v), "e": e,
                        "sign": sign, "code": r.get("cftc_contract_market_code")}
        if best and abs(best["e"]) >= MIN_E:
            # A positive `read` means the positioning is bullish for price.
            bullish = (best["e"] > 0) == (best["sign"] > 0)
            best["read"] = "washed out" if bullish else "crowded"
            rows.append(best)
    if not rows: return pd.DataFrame()
    d = pd.DataFrame(rows)
    d["absE"] = d.e.abs()
    return d.sort_values("absE", ascending=False).reset_index(drop=True)


def html_panel(cu):
    d = build(cu)
    if d is None or d.empty: return ""
    crowd = d[d.read == "crowded"].head(TOP)
    wash  = d[d.read == "washed out"].head(TOP)

    def col(title, sub, x, tone):
        if not len(x):
            return (f'<div><h5>{title}<span class="dim"> &middot; {sub}</span></h5>'
                    '<ul><li class="dim">nothing at this extremity</li></ul></div>')
        li = "".join(
            f'<li><b class="{tone}">{r.pct:.0f}</b> '
            f'<span class="nm2">{html.escape(str(r["name"]))}</span>'
            f'<span class="dim"> &middot; {html.escape(str(r.cohort))}</span></li>'
            for _, r in x.iterrows())
        return f'<div><h5>{title}<span class="dim"> &middot; {sub}</span></h5><ul>{li}</ul></div>'

    return ('<div class="cfx crowdx"><h4>Most crowded right now</h4>'
            '<p class="grpnote">The widest positioning extremes on the board, by '
            'distance from neutral on each cohort&rsquo;s 52-week percentile. '
            '<b>Crowded</b> means the crowd is already positioned the way price '
            'has been going &mdash; the side with less left to buy. <b>Washed '
            'out</b> means they have given up. The number is the percentile. '
            'Open interest is excluded here for the same reason it no longer '
            'ranks: it failed at every horizon tested.</p>'
            '<div class="cf3">'
            + col("Crowded", "the fade candidates", crowd, "dn")
            + col("Washed out", "the give-up candidates", wash, "up")
            + f'<div><h5>Spread<span class="dim"> &middot; how one-sided overall</span></h5>'
              f'<ul><li><b>{len(d[d.read=="crowded"])}</b> crowded vs '
              f'<b>{len(d[d.read=="washed out"])}</b> washed out</li>'
              f'<li class="dim">{len(d)} of {len(cu)} contracts clear the '
              f'{MIN_E:.2f} extremity bar</li>'
              f'<li class="dim">widest reading {d.absE.max()*50+50:.0f} '
              f'percentile</li></ul></div>'
            + '</div></div>')
