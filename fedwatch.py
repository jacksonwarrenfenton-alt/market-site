"""Fed rate path, priced by the options market -- jman's "Fed Watch" panel.

CME's own FedWatch tool is the industry-standard version of this, built off
30-Day Fed Funds futures. It is not usable here: CME's site returns an
explicit 403 citing its own Data Terms of Use the moment a script requests
it ("This IP address is blocked due to suspected web scraping activity...
strictly prohibited"), and there is no free public endpoint behind it --
only a paid FedWatch API product. Respecting that block rather than working
around it, this uses the free, public substitute a real desk would reach
for next: the Atlanta Fed's own Market Probability Tracker, republished as
a downloadable historical file. It answers the same question -- what does
the market think the policy rate will be -- from CME 3-month SOFR OPTIONS
instead of Fed Funds FUTURES, and organised by IMM-dated quarterly windows
(the SOFR contract's own expiries) rather than individual FOMC meeting
dates. Close enough in spirit to read as "Fed Watch"; different enough in
mechanics that it is never labelled as CME's own number.

"Prob: hike" / "Prob: cut" are the Atlanta Fed's own field names: the
probability the average SOFR over that 3-month window sits above / below
the CURRENT target range -- a drift measure over the whole window, not a
single up/down vote at one meeting. Read the per-window bar chart (which
25bp band gets the most weight) as the actual path read; treat the
cut/hike headline as a coarser summary of the same distribution.
"""
import pandas as pd, numpy as np, json, os, sys, html, urllib.request, ssl

D = os.path.expanduser("~/pos")
OUT = f"{D}/fedwatch.json"
URL = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/"
       "cenfis/market-probability-tracker/mpt_histdata.xlsx")
CTX = ssl._create_unverified_context()
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/124"}
N_WINDOWS = 4          # nearest quarters shown
HIST_DAYS = 120        # trailing window for the nearest-quarter drift chart


def fetch():
    try:
        req = urllib.request.Request(URL, headers=H)
        raw = urllib.request.urlopen(req, timeout=60, context=CTX).read()
        tmp = f"{D}/_mpt_raw.xlsx"
        open(tmp, "wb").write(raw)
        d = pd.read_excel(tmp, sheet_name="DATA")
    except Exception as e:
        print("fedwatch fetch failed:", e, flush=True)
        return None
    finally:
        try: os.remove(f"{D}/_mpt_raw.xlsx")
        except Exception: pass

    d["date"] = pd.to_datetime(d.date)
    last = d.date.max()
    cur = d[d.date == last]
    if not len(cur): return None
    windows = sorted(cur.reference_start.unique())[:N_WINDOWS]
    target_now = str(cur.target_range.iloc[0])

    quarters = []
    for w in windows:
        sub = cur[cur.reference_start == w]
        bands = []
        for _, r in sub[sub.field.str.startswith("Prob: ") & sub.field.str.contains("bps")].iterrows():
            bands.append({"band": r.field.replace("Prob: ", ""), "p": round(float(r.value), 2)})
        bands.sort(key=lambda b: int(b["band"].split("bps")[0]))
        def _get(fld):
            v = sub[sub.field == fld].value
            return round(float(v.iloc[0]), 2) if len(v) else None
        quarters.append({
            "window": pd.Timestamp(w).strftime("%Y-%m-%d"),
            "bands": bands,
            "prob_cut": _get("Prob: cut"),
            "prob_hike": _get("Prob: hike"),
            "rate_mean": _get("Rate: mean"),
            "rate_mode": _get("Rate: mode"),
        })

    # Drift history for the nearest window only -- how the market's read of
    # THIS specific quarter has moved as new pricing came in.
    near = windows[0]
    h = d[(d.reference_start == near) & (d.date >= last - pd.Timedelta(days=HIST_DAYS))]
    h = h[h.field.isin(["Prob: cut", "Prob: hike"])]
    hist = []
    if len(h):
        piv = h.pivot_table(index="date", columns="field", values="value")
        for dt, row in piv.iterrows():
            hist.append({"date": dt.strftime("%Y-%m-%d"),
                         "cut": None if pd.isna(row.get("Prob: cut")) else round(float(row["Prob: cut"]), 2),
                         "hike": None if pd.isna(row.get("Prob: hike")) else round(float(row["Prob: hike"]), 2)})

    out = {"asof": last.strftime("%Y-%m-%d"), "target_now": target_now,
           "quarters": quarters, "hist": hist}
    json.dump(out, open(OUT, "w"))
    return out


def _load():
    if not os.path.exists(OUT): return None
    try: return json.load(open(OUT))
    except Exception: return None


def _bar(bands, target_now):
    if not bands: return ""
    mx = max(b["p"] for b in bands) or 1
    rows = ""
    for b in bands:
        w = 100 * b["p"] / mx
        cur = " cur" if b["band"] == target_now else ""
        rows += (f'<div class="fwrow{cur}"><span class="fwb">{html.escape(b["band"])}</span>'
                 f'<span class="fwbar"><i style="width:{w:.1f}%"></i></span>'
                 f'<span class="fwp">{b["p"]:.1f}%</span></div>')
    return rows


def panel():
    o = _load()
    if o is None: o = fetch()
    if not o or not o.get("quarters"): return ""

    cards = ""
    for i, q in enumerate(o["quarters"]):
        lead = max(q["bands"], key=lambda b: b["p"]) if q["bands"] else None
        headline = (f'most-likely band <b>{html.escape(lead["band"])}</b> at '
                    f'<b>{lead["p"]:.0f}%</b>' if lead else "")
        cards += (
            f'<div class="fwcard"><h6>Quarter starting {q["window"]}</h6>'
            f'<div class="s">{headline}</div>'
            f'<div class="clrow"><span class="cln">P(above current range)</span>'
            f'<b class="{"up" if (q["prob_hike"] or 0) >= 50 else ""}">{q["prob_hike"]:.1f}%</b></div>'
            f'<div class="clrow"><span class="cln">P(below current range)</span>'
            f'<b class="{"dn" if (q["prob_cut"] or 0) >= 50 else ""}">{q["prob_cut"]:.1f}%</b></div>'
            f'<div class="fwbands">{_bar(q["bands"], o["target_now"])}</div></div>')

    trend = ""
    hist = o.get("hist") or []
    if len(hist) >= 4:
        dates = [h["date"] for h in hist]
        hike = [h["hike"] for h in hist]
        cut = [h["cut"] for h in hist]
        payload = {"dates": dates,
                   "series": [{"name": "P(above current range)", "vals": hike, "color": "#d03b3b", "axis": 1},
                              {"name": "P(below current range)", "vals": cut, "color": "#3987e5", "axis": 1}]}
        trend = (f'<h5>Nearest quarter &mdash; how the read has drifted</h5>'
                 f'<div id="fw-trend" class="mc"></div>'
                 f'<script id="fw-trend-d" type="application/json">{json.dumps(payload, separators=(",", ":"))}</script>'
                 '<script>(function(){var P=JSON.parse(document.getElementById("fw-trend-d").textContent);'
                 'function go(){if(!window.MC){return setTimeout(go,40);} '
                 'MC.mount("fw-trend", {dates:P.dates, series:P.series, mode:"raw"});} go();})();</script>')

    return (
        '<h2>Fed Watch &mdash; rate path priced by the options market</h2>'
        f'<p class="grpnote">As of <b>{o["asof"]}</b>, current target range '
        f'<b>{html.escape(o["target_now"])}</b>. CME&rsquo;s own FedWatch tool (built from '
        'Fed Funds futures, per FOMC meeting) blocks automated access outright, so this is the '
        'free public equivalent: the <b>Atlanta Fed&rsquo;s Market Probability Tracker</b>, built '
        'from CME 3-month SOFR <i>options</i> and organised by the SOFR contract&rsquo;s own '
        'quarterly windows rather than individual meeting dates. &ldquo;Above/below current '
        'range&rdquo; is a drift read over the whole quarter, not a single meeting vote &mdash; '
        'read the band chart below each card for where the actual weight of probability sits.</p>'
        f'<div class="fwgrid">{cards}</div>' + trend)


if __name__ == "__main__":
    o = fetch()
    print(o["asof"] if o else "fedwatch fetch failed", flush=True)
