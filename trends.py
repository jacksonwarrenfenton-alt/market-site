"""Google Trends search interest as a crowd-sentiment gauge.

Google Trends normalises each request to 0-100 against its own peak, so
comparability only holds WITHIN a batch of terms fetched together, not
across batches. Terms are grouped by theme for that reason -- each group is
one request, one shared 0-100 scale. Weekly, trailing 5 years.

The read: this is a raw-curiosity gauge, not a positioning gauge. A spike in
"buy the dip" searches means retail attention spiked, not that retail
bought. It pairs with the site's other sentiment work (liqn Social IQ, COT,
short interest) rather than replacing it -- treat a term sitting at or near
its own 5-year high as an attention extreme worth fading, the same way the
board already fades crowded positioning elsewhere, and note when several
groups spike together (that is the "everyone is Googling the same thing"
regime, historically the more reliable tell than any single term).
"""
import pandas as pd, numpy as np, json, os, time, sys, html

D = os.path.expanduser("~/pos")

GROUPS = [
    ("Crash & recession fear",
     ["recession", "stock market crash", "stagflation", "market correction", "buy the dip"]),
    ("Bubble & euphoria",
     ["stock market bubble", "ai bubble", "is it too late to buy stocks", "short squeeze", "meme stocks"]),
    ("Metals & crypto retail interest",
     ["gold price", "silver price", "silver squeeze", "bitcoin price", "buy bitcoin"]),
    ("Macro & rates",
     ["fed rate cut", "inflation", "interest rates", "yield curve inversion", "dollar collapse"]),
    ("Retail momentum names",
     ["palantir stock", "nvidia stock", "soxl", "tqqq", "penny stocks"]),
]

WATCHLIST_FILE = f"{D}/trends_watchlist.json"
CUSTOM_LABEL = "Custom / requested"


def _watchlist_terms():
    if not os.path.exists(WATCHLIST_FILE): return []
    try:
        return json.load(open(WATCHLIST_FILE))
    except Exception:
        return []


def add_terms(*terms):
    """Add one or more terms to the persistent custom watchlist, deduped.

    This is the "add a trend search" entry point -- there's no live fetch at
    view time (the built page is static, CSP blocks it), so a genuinely new
    term has to be added here and picked up by the next fetch() run. It is
    NOT kept just because it was asked for: fetch() validates every term
    (including the built-in ones) and drops anything that comes back as
    Google's flat all-zero "not enough data" response before it's stored or
    shown as an option.
    """
    cur = set(_watchlist_terms()) | {t.strip() for t in terms if t and t.strip()}
    cur = sorted(cur)
    json.dump(cur, open(WATCHLIST_FILE, "w"))
    return cur


def remove_terms(*terms):
    cur = set(_watchlist_terms()) - {t.strip() for t in terms}
    cur = sorted(cur)
    json.dump(cur, open(WATCHLIST_FILE, "w"))
    return cur


def _chunk(seq, n):
    return [seq[i:i+n] for i in range(0, len(seq), n)]


def _valid(vals):
    """A term "has been trending" if Google actually has signal for it --
    reject the flat all/near-zero series Google returns for terms with too
    little search volume to measure, which looks like real data but isn't."""
    if not vals or len(vals) < 20: return False
    arr = np.array(vals, dtype=float)
    if np.nanmax(arr) < 5: return False           # never registered meaningfully
    if len(set(vals)) <= 1: return False           # perfectly flat
    nonzero_frac = float((arr > 0).mean())
    return nonzero_frac >= 0.10


def _patch_urllib3():
    # pytrends 4.9.2 still calls Retry(method_whitelist=...), removed in
    # urllib3 2.x (renamed allowed_methods). Shim rather than pin urllib3.
    import urllib3
    orig = urllib3.util.retry.Retry.__init__
    if getattr(orig, "_trends_patched", False):
        return
    def patched(self, *a, **kw):
        if "method_whitelist" in kw:
            kw["allowed_methods"] = kw.pop("method_whitelist")
        return orig(self, *a, **kw)
    patched._trends_patched = True
    urllib3.util.retry.Retry.__init__ = patched


def fetch(pause=12):
    _patch_urllib3()
    from pytrends.request import TrendReq
    pt = TrendReq(hl="en-US", tz=360, timeout=(8, 20), retries=2, backoff_factor=1.0)

    # Watchlist terms (from add_terms()) ride along as extra groups, chunked
    # to 5 terms/request the same as the built-in ones -- Trends caps a
    # payload at 5 terms and comparability only holds within one request.
    custom = _watchlist_terms()
    work = list(GROUPS) + [
        (CUSTOM_LABEL if i == 0 else f"{CUSTOM_LABEL} #{i+1}", chunk)
        for i, chunk in enumerate(_chunk(custom, 5))
    ]

    out = {}
    for label, terms in work:
        ok = False
        for attempt in range(3):
            try:
                pt.build_payload(terms, timeframe="today 5-y")
                df = pt.interest_over_time()
                if "isPartial" in df.columns:
                    df = df.drop(columns=["isPartial"])
                out[label] = df
                print(f"  trends: {label} ok, {len(df)} weeks", file=sys.stderr)
                ok = True
                break
            except Exception as e:
                wait = 30 * (attempt + 1)
                print(f"  trends: {label} attempt {attempt+1} failed ({e}); waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
        if not ok:
            print(f"  trends: {label} FAILED after retries, skipping", file=sys.stderr)
        time.sleep(pause)
    if not out:
        return None

    store, dropped = {}, []
    for lbl, df in out.items():
        series = {}
        for c in df.columns:
            vals = [int(v) for v in df[c]]
            if _valid(vals):
                series[c] = vals
            else:
                dropped.append(c)
        if series:
            store[lbl] = {"dates": [d.strftime("%Y-%m-%d") for d in df.index], "series": series}
    if dropped:
        print(f"  trends: dropped (no real signal / Google 'not enough data'): {dropped}", file=sys.stderr)
    json.dump(store, open(f"{D}/trends.json", "w"))
    json.dump(dropped, open(f"{D}/trends_dropped.json", "w"))
    return store


# One seed term per group/basket -- what a "newest hot" search for that theme
# fans out from. Rising related queries are Google's own discovery mechanism:
# terms whose search volume near this seed has recently spiked, independent
# of the fixed GROUPS watchlist above. This is the "constantly find new hot
# terms" half of the panel; GROUPS above is the "track these specific terms
# over 5 years" half.
HOT_SEEDS = {
    "Crash & recession fear": "recession",
    "Bubble & euphoria": "stock market bubble",
    "Metals & crypto retail interest": "gold price",
    "Macro & rates": "fed rate cut",
    "Retail momentum names": "palantir stock",
}

# Related-queries results are Google's raw autocomplete-adjacent output, not
# a curated financial list -- a seed like "recession" pulls in "gum
# recession" (a dental term) and bare definition lookups alongside genuine
# macro spikes. This drops the categories that are reliably noise rather than
# attention worth reading as sentiment.
_JUNK_PAT = ["gum ", "graft", "meaning", "definition", "what is", "how to",
             "wiki", "synonym", "vs "]


def _is_junk(q):
    ql = q.lower()
    return any(p in ql for p in _JUNK_PAT)


def fetch_hot(pause=12):
    _patch_urllib3()
    from pytrends.request import TrendReq
    pt = TrendReq(hl="en-US", tz=360, timeout=(8, 20), retries=2, backoff_factor=1.0)
    out = {}
    for label, seed in HOT_SEEDS.items():
        ok = False
        for attempt in range(3):
            try:
                pt.build_payload([seed], timeframe="today 3-m")
                rq = pt.related_queries().get(seed, {})
                rising = rq.get("rising")
                rows = []
                if rising is not None and len(rising):
                    for _, r in rising.iterrows():
                        q = str(r["query"])
                        if _is_junk(q): continue
                        try:
                            val = int(r["value"])
                        except (TypeError, ValueError):
                            val = None
                        rows.append({"query": q, "value": val})
                        if len(rows) >= 6: break
                out[label] = {"seed": seed, "rising": rows}
                print(f"  trends hot: {label} ok, {len(rows)} rising (of {len(rising) if rising is not None else 0} raw)",
                      file=sys.stderr)
                ok = True
                break
            except Exception as e:
                wait = 30 * (attempt + 1)
                print(f"  trends hot: {label} attempt {attempt+1} failed ({e}); waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
        if not ok:
            print(f"  trends hot: {label} FAILED after retries, skipping", file=sys.stderr)
        time.sleep(pause)
    json.dump({"asof": pd.Timestamp.today().strftime("%Y-%m-%d"), "groups": out},
              open(f"{D}/trends_hot.json", "w"))
    return out


def _load():
    p = f"{D}/trends.json"
    if not os.path.exists(p): return None
    return json.load(open(p))


def _load_hot():
    p = f"{D}/trends_hot.json"
    if not os.path.exists(p): return None
    return json.load(open(p))


def panel():
    store = _load()
    if not store:
        return ""
    hot = _load_hot()
    palette = ["#9085e9", "#5ec8d8", "#fab219", "#d03b3b", "#0ca30c", "#e0709a", "#4c8bf5"]
    blocks = []
    extremes = []
    # Iterate the STORE, not the static GROUPS list -- a custom group added
    # via add_terms() lives only in the persisted JSON, not in this file.
    for label, g in store.items():
        terms = sorted(g["series"].keys())
        if not terms: continue
        dates = g["dates"]
        stat_bits = {}
        all_series = {}
        for i, term in enumerate(terms):
            vals = g["series"].get(term)
            if not vals: continue
            arr = np.array(vals, dtype=float)
            cur = arr[-1]
            pct = float((arr <= cur).mean() * 100)
            if pct >= 90:
                extremes.append((term, cur, pct))
            all_series[term] = {"name": term, "axis": 1,
                                 "color": palette[i % len(palette)], "vals": vals}
            tag = ' <span class="dv dv-dn">5y HIGH ZONE</span>' if pct >= 90 else ""
            stat_bits[term] = (f'<span class="cln">{html.escape(term)}</span> '
                                f'<b>{cur:.0f}</b><span class="dim">/100, {pct:.0f}th pctile of 5y</span>{tag}')
        if not all_series: continue
        cid = f"tr-{abs(hash(label))%100000}"
        chips = "".join(f'<button type="button" class="sbchip on" data-t="{html.escape(t)}">{html.escape(t)}</button>'
                         for t in terms)
        stat_div = "".join(f'<div class="clrow" data-stat="{html.escape(t)}">{b}</div>' for t, b in stat_bits.items())
        payload = {"dates": dates, "all": all_series}

        # "Newest hot" -- rising related queries near this basket's seed term,
        # refreshed by fetch_hot() independent of the fixed GROUPS watchlist
        # above (that's a tracked-history list; this is discovery).
        hot_html = ""
        hg = (hot or {}).get("groups", {}).get(label)
        if hg and hg.get("rising"):
            hot_asof = hot.get("asof", "")
            chips_hot = "".join(
                f'<span class="chip">{html.escape(r["query"])}'
                + (f' <i>+{r["value"]}%</i>' if isinstance(r.get("value"), int) else ' <i>new</i>')
                + '</span> '
                for r in hg["rising"])
            hot_html = (f'<div class="clrow" style="margin-top:6px"><span class="cln">&#128293; newest hot, '
                        f'related to &ldquo;{html.escape(hg["seed"])}&rdquo;</span> '
                        f'<span class="dim">as of {hot_asof}</span></div>'
                        f'<div style="margin:3px 0 2px">{chips_hot}</div>')

        blocks.append(
            f'<div><h5>{html.escape(label)}</h5>'
            f'<div class="sbchips">{chips}</div>'
            f'<div class="clist">{stat_div}</div>{hot_html}'
            f'<div id="{cid}" class="mc"></div>'
            f'<script id="{cid}-d" type="application/json">{json.dumps(payload, separators=(",", ":"))}</script>'
            '<script>(function(){'
            f'var P=JSON.parse(document.getElementById("{cid}-d").textContent);'
            'var sel={}; Object.keys(P.all).forEach(function(t){sel[t]=true;});'
            'function spec(){var s=[]; Object.keys(P.all).forEach(function(t){if(sel[t])s.push(P.all[t]);});'
            '  return {dates:P.dates, series:s, mode:"raw"};}'
            f'function go(){{if(!window.MC){{return setTimeout(go,40);}} MC.mount("{cid}", spec());}} go();'
            f'var root=document.getElementById("{cid}").parentNode;'
            'root.querySelectorAll(".sbchips .sbchip[data-t]").forEach(function(b){'
            '  b.onclick=function(){var t=b.dataset.t; sel[t]=!sel[t]; b.classList.toggle("on", !!sel[t]);'
            '    var row=root.querySelector(\'[data-stat="\'+CSS.escape(t)+\'"]\');'
            '    if(row) row.style.opacity=sel[t]?"1":".35";'
            f'    if(window.MC) MC.mount("{cid}", spec());}};}});'
            '})();</script>'
            '</div>')

    extreme_note = ""
    if extremes:
        names = ", ".join(f"<b>{html.escape(t)}</b> ({p:.0f}th)" for t, _, p in sorted(extremes, key=lambda x: -x[2])[:6])
        extreme_note = (f'<p class="grpnote"><b>{len(extremes)} term(s)</b> sitting in their own 5-year high '
                         f'zone right now: {names}. Multiple groups spiking together historically matters more '
                         'than any one term alone.</p>')

    custom_note = ""
    if _watchlist_terms():
        custom_note = (f'<p class="grpnote">Custom watchlist: {", ".join(html.escape(t) for t in _watchlist_terms())} '
                        '&mdash; tell Claude a new term to add it (it gets validated against real Google Trends '
                        'signal and baked in on the next rebuild; the page itself can\'t fetch live, so toggling '
                        'below only shows/hides terms already fetched).</p>')

    return ('<h2>Google Trends &mdash; search-interest sentiment</h2>'
            '<p class="grpnote">Weekly search interest, trailing 5 years, 0&ndash;100 scaled '
            'per group (Google normalises each request to its own peak, so compare '
            'terms within a card, not across cards). Click a term below its chart to '
            'show/hide it. Every term shown has been validated as actually having Google '
            'Trends signal &mdash; a term with too little search volume to measure (Google\'s '
            'flat &ldquo;not enough data&rdquo; response) is dropped before it ever reaches this '
            'page. Each card also surfaces <b>&#128293; newest hot</b> queries &mdash; Google\'s own '
            'rising-related-searches near that basket\'s theme, refreshed independently of the fixed '
            'terms above (that\'s discovery, not a tracked-history watchlist) and lightly filtered for '
            'junk (definition lookups, unrelated homonyms). This is an <b>attention</b> gauge, not a '
            'positioning one &mdash; pair it with the short-interest and COT reads elsewhere on this '
            'page rather than trading it alone.</p>'
            + extreme_note + custom_note
            + '<div class="si2grid">' + "".join(blocks) + '</div>')


if __name__ == "__main__":
    fetch()
    print("done")
