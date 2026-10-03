"""Recent market headlines for the top of the Market tab.

Two public RSS feeds that answer from the cloud container: MarketWatch top
stories and Yahoo Finance. Headlines are merged, de-duplicated on title, newest
first, and saved to ~/pos/news.json for the dashboard strip. A feed that fails
is skipped; if both fail the strip simply shows no news column.
"""
import os, sys, json, html, re
import xml.etree.ElementTree as ET
import requests, pandas as pd

D = os.path.expanduser("~/pos")
OUT = f"{D}/news.json"
FEEDS = [("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
         ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex")]
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def _items(src, url):
    r = requests.get(url, headers=UA, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        if not t: continue
        ts = pd.to_datetime(it.findtext("pubDate"), errors="coerce", utc=True)
        out.append({"t": html.unescape(re.sub(r"\s+", " ", t)), "u": (it.findtext("link") or "").strip(),
                    "s": src, "ts": None if pd.isna(ts) else ts.isoformat()})
    return out


# MarketWatch's top-stories feed mixes in personal-finance advice columns
# ("I'm 67 and earn ..."); they are not market news.
_NOISE = re.compile(r"^[‘'\"]|\bI[’']m\b|\bI earn\b|\bmy (wife|husband|son|daughter|kids|mom|dad|parents)\b|"
                    r"\bretire(ment)?\b|social security|moneyist|\?$", re.I)


def fetch(n=12):
    allr = []
    for src, url in FEEDS:
        try:
            allr += _items(src, url)
        except Exception as e:
            print(f"newsfeed: {src} failed: {e}", file=sys.stderr, flush=True)
    seen, rows = set(), []
    cut = (pd.Timestamp.now("UTC") - pd.Timedelta(days=3)).isoformat()
    for r in sorted(allr, key=lambda x: x["ts"] or "", reverse=True):
        if _NOISE.search(r["t"]) or (r["ts"] or "") < cut: continue
        k = r["t"].lower()[:80]
        if k in seen: continue
        seen.add(k); rows.append(r)
    rows = rows[:n]
    json.dump(rows, open(OUT, "w"))
    print(f"newsfeed: {len(rows)} headlines", file=sys.stderr, flush=True)
    return rows


def load():
    try:
        return json.load(open(OUT))
    except Exception:
        return []


if __name__ == "__main__":
    for r in fetch(): print(r["ts"], r["s"], r["t"])
