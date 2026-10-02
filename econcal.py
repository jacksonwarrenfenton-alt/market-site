"""Scheduled macro events, and where rate expectations are actually sitting.

ForexFactory publishes its calendar as JSON -- the same impact ratings the site
shows, without scraping the page. Only High and Medium impact are kept: the low
tier is noise that would bury the two or three prints a week that actually move
the tape.
"""
import urllib.request, ssl, json, os, html
import pandas as pd, numpy as np

D = os.path.expanduser("~/pos")
OUT = f"{D}/econcal.json"
CTX = ssl._create_unverified_context()
H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/124"}
URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
KEEP = {"High", "Medium"}
FOCUS = {"USD", "EUR", "GBP", "JPY", "CNY", "All"}


def fetch():
    try:
        r = urllib.request.urlopen(urllib.request.Request(URL, headers=H),
                                   timeout=25, context=CTX)
        rows = json.loads(r.read())
    except Exception as e:
        print("econcal fetch failed:", e, flush=True)
        return None
    out = []
    for x in rows:
        if x.get("impact") not in KEEP: continue
        if x.get("country") not in FOCUS: continue
        out.append({"date": (x.get("date") or "")[:10],
                    "time": (x.get("date") or "")[11:16],
                    "country": x.get("country"), "title": x.get("title"),
                    "impact": x.get("impact"), "forecast": x.get("forecast"),
                    "previous": x.get("previous")})
    if not out: return None
    json.dump(out, open(OUT, "w"))
    return out


def panel():
    rows = None
    if os.path.exists(OUT):
        try: rows = json.load(open(OUT))
        except Exception: rows = None
    if not rows: rows = fetch()
    if not rows: return ""
    d = pd.DataFrame(rows)
    d = d.sort_values(["date", "time"])
    body, cur = [], None
    for _, r in d.iterrows():
        if r["date"] != cur:
            cur = r["date"]
            dd = pd.Timestamp(cur)
            body.append(f'<tr class="dhdr"><td colspan="5">{dd:%a %d %b}</td></tr>')
        imp = "hi" if r["impact"] == "High" else "md"
        body.append(
            f'<tr><td class="dim">{html.escape(r["time"] or "")}</td>'
            f'<td><span class="cty">{html.escape(str(r["country"]))}</span></td>'
            f'<td class="nm2">{html.escape(str(r["title"]))}</td>'
            f'<td><span class="imp imp-{imp}">{r["impact"]}</span></td>'
            f'<td class="dim">fcst {html.escape(str(r["forecast"] or "–"))} '
            f'&middot; prev {html.escape(str(r["previous"] or "–"))}</td></tr>')
    n_hi = int((d.impact == "High").sum())
    return ('<h2>Macro calendar &mdash; this week</h2>'
            f'<p class="grpnote">High and medium impact only, {n_hi} high-impact '
            'prints this week. The low tier is dropped on purpose &mdash; it buries '
            'the two or three releases that actually move the tape. Source: '
            'ForexFactory&rsquo;s published calendar feed.</p>'
            '<table class="sig econ"><thead><tr><th>Time</th><th>Ccy</th>'
            '<th>Event</th><th>Impact</th><th>Forecast / previous</th></tr></thead>'
            '<tbody>' + "".join(body) + '</tbody></table>')
