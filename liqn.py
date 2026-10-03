"""liqn.ai Social IQ ("The Crowd") -- crowd-attention sentiment, tracked daily.

The page is a Next.js client render, so the container gets an empty shell and
only a real browser sees the numbers. The weekly job therefore reads it through
the browser pane and hands the page TEXT to `parse()`, which appends one row to
liqn_hist.csv. There is no historical archive to backfill from: the record
starts the first day it is captured and thickens from there. Say so on the panel
rather than implying a longer history than exists.

What is worth keeping, and why:
  top10_share  the share of all crowd chatter sitting in the ten loudest names.
               This is the froth gauge -- a narrow tape means the crowd has
               piled into a handful of names, which is the condition worth
               fading. The page reports its own typical window average, so the
               reading is interpretable from day one.
  posts        total daily crowd posts across the full census -- raw engagement.
  broad_posts  posts beyond the ten loudest: participation under the surface.
  bull/bear    counts of names the page verdicts BULLISH vs BEARISH, which is a
               breadth read on mood rather than one aggregate number.
"""
import pandas as pd, numpy as np, re, os, json, html

D = os.path.expanduser("~/pos")
HIST = f"{D}/liqn_hist.csv"
COLS = ["date", "posts", "broad_posts", "top10_share", "conc_trend",
        "typical_share", "n_names", "bull", "bear", "mixed", "themes",
        "loudest", "breakouts", "breakdowns", "gaining", "losing"]


def _num(s):
    if s is None: return np.nan
    s = str(s).replace(",", "").replace("−", "-").strip()
    m = re.match(r"^(-?[\d.]+)\s*([kKmM])?$", s)
    if not m: return np.nan
    v = float(m.group(1))
    return v * {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)


def parse(text, asof=None):
    """Turn the rendered Social IQ page text into one daily row."""
    t = re.sub(r"\s+", " ", text)
    def grab(pat, cast=_num):
        m = re.search(pat, t)
        return cast(m.group(1)) if m else np.nan

    row = {
        "date": asof or (re.search(r"AS OF · ([A-Z]{3} \d{1,2} \d{4})", t).group(1)
                         if re.search(r"AS OF · ([A-Z]{3} \d{1,2} \d{4})", t) else None),
        "posts":        grab(r"([\d,]+) posts on \w+"),
        "broad_posts":  grab(r"([\d,]+) broad-crowd posts"),
        "top10_share":  grab(r"([\d.]+)% of all crowd chatter"),
        "conc_trend":   grab(r"14-DAY TREND (−?-?[\d.]+) pts"),
        "typical_share": grab(r"window avg ([\d.]+)%"),
        "n_names":      grab(r"full ([\d,]+)-name universe"),
        "bull":  float(len(re.findall(r"\bBULLISH\b", t))),
        "bear":  float(len(re.findall(r"\bBEARISH\b", t))),
        "mixed": float(len(re.findall(r"\bMIXED\b", t))),
    }
    # Scope the theme scrape to the rotation block. Run loose over the whole
    # page and the first key swallows every heading above it.
    seg = ""
    m = re.search(r"THEME ROTATION(.*?)(?:CHATTER|CROWD TAPE|$)", t)
    if m: seg = m.group(1)
    # Per-ticker tables. The aggregate numbers say how concentrated the tape is;
    # these say WHERE, which is the part that maps onto a watchlist.
    def block(start, end, pat):
        m = re.search(start + r"(.*?)(?:" + end + r"|$)", t)
        return re.findall(pat, m.group(1)) if m else []

    loud = block(r"LOUDEST", r"MOMENTUM|GAINING",
                 r"\d+\s+([A-Z][A-Z.\-]{0,5})\s+([\d.]+k?)\s+(\d+)%")
    row["loudest"] = json.dumps([{"t": a, "posts": b, "share": int(c)}
                                 for a, b, c in loud[:12]])

    brk = block(r"ATTENTION BREAKOUTS", r"ATTENTION BREAKDOWNS|LOUDEST",
                r"\d+\s+([A-Z][A-Z.\-]{0,5})\s+([\d.]+)\u00d7\s+([\d,]+)\s*\u2192\s*([\d,]+)")
    row["breakouts"] = json.dumps([{"t": a, "x": float(b), "from": c, "to": d}
                                   for a, b, c, d in brk[:12]])

    brkd = block(r"ATTENTION BREAKDOWNS", r"LOUDEST",
                 r"\d+\s+([A-Z][A-Z.\-]{0,5})\s+(\u2212?-?\d+)%\s+([\d,]+)\s*\u2192\s*([\d,]+)")
    row["breakdowns"] = json.dumps([{"t": a, "pct": int(str(b).replace("\u2212", "-")),
                                     "from": c, "to": d} for a, b, c, d in brkd[:12]])

    # "GAINING" appears first in the section header ("GAINING VS LOSING"), so
    # anchoring on it terminates the block instantly. Take the LAST occurrence.
    gi = t.rfind("GAINING"); li = t.find("LOSING", gi if gi > 0 else 0)
    gseg = t[gi:li] if gi > 0 and li > gi else ""
    gain = re.findall(r"([A-Z][A-Z.\-]{0,5})\s+\+([\d]+)%\s+([\d.]+k?)\u2192([\d.]+k?)", gseg)
    row["gaining"] = json.dumps([{"t": a, "pct": int(b), "from": c, "to": d}
                                 for a, b, c, d in gain[:12]])

    lose = block(r"LOSING", r"SENTIMENT|CROWD BASKETS",
                 r"([A-Z][A-Z.\-]{0,5})\s+-([\d]+)%\s+([\d.]+k?)\u2192([\d.]+k?)")
    row["losing"] = json.dumps([{"t": a, "pct": -int(b), "from": c, "to": d}
                                for a, b, c, d in lose[:12]])

    themes = re.findall(r"([A-Za-z][A-Za-z \-\u2014&]{2,40}?)\s*([+-]\d+)%", seg)
    row["themes"] = json.dumps({k.strip(): int(v) for k, v in themes[:12]})
    return row


def append(row):
    d = pd.DataFrame([row])[COLS]
    if os.path.exists(HIST):
        old = pd.read_csv(HIST)
        d = pd.concat([old, d], ignore_index=True).drop_duplicates("date", keep="last")
    d.to_csv(HIST, index=False)
    return d


CROWD_HIST = f"{D}/crowd_hist.csv"   # crowdfeed.py: ApeWisdom + StockTwits


def source():
    """Which crowd record load() reads: liqn's own capture when it is there,
    else the login-free cloud feed. Never a blend -- different universes."""
    for p, lab in ((HIST, "liqn.ai"), (CROWD_HIST, "Reddit via ApeWisdom + StockTwits")):
        if os.path.exists(p) and len(pd.read_csv(p)):
            return p, lab
    return None, None


def backfill(points):
    """Merge liqn's own posts / top-10 history into liqn_hist.csv.

    liqn.ai's board only shows a rolling ~3 months, so every capture should
    hand over the points that chart shows and they are kept here for good.
    `points`: iterable of dicts with `date` (any parseable date), `posts`, and
    `top10_share` (percent), optionally `broad_posts`. Only dates NOT already
    in the history are added -- a full daily capture row always wins over a
    backfilled point. Returns the number of rows added.
    """
    rows = []
    for p in points:
        dt = pd.to_datetime(p.get("date"), errors="coerce")
        if pd.isna(dt): continue
        row = {c: np.nan for c in COLS}
        row.update({"date": dt.strftime("%b %d %Y"),
                    "posts": p.get("posts"), "top10_share": p.get("top10_share"),
                    "broad_posts": p.get("broad_posts",
                                         (p["posts"] * (1 - p["top10_share"] / 100))
                                         if p.get("posts") is not None and p.get("top10_share") is not None
                                         else np.nan)})
        for k in ("themes", "loudest", "breakouts", "breakdowns", "gaining", "losing"):
            row[k] = "[]" if k != "themes" else "{}"
        rows.append(row)
    if not rows: return 0
    new = pd.DataFrame(rows)[COLS]
    old = pd.read_csv(HIST) if os.path.exists(HIST) else pd.DataFrame(columns=COLS)
    have = set(pd.to_datetime(old.date, format="%b %d %Y", errors="coerce").dropna().dt.normalize())
    new = new[~pd.to_datetime(new.date, format="%b %d %Y").dt.normalize().isin(have)]
    if not len(new): return 0
    d = pd.concat([old, new], ignore_index=True)
    d["_dt"] = pd.to_datetime(d.date, format="%b %d %Y", errors="coerce")
    d.sort_values("_dt").drop(columns="_dt").to_csv(HIST, index=False)
    return len(new)


def load():
    p, _ = source()
    if p is None: return None
    d = pd.read_csv(p)
    d["dt"] = pd.to_datetime(d.date, format="%b %d %Y", errors="coerce")
    return d.dropna(subset=["dt"]).sort_values("dt")


def _hist_chart(d):
    """Total daily posts (bars) with the top-10 share of chatter (line), the
    same view liqn's own board draws -- but over the FULL stored history, not
    liqn's rolling three months."""
    pay = {"dates": [x.strftime("%Y-%m-%d") for x in d.dt],
           "share": [None if not np.isfinite(v) else float(v) for v in d.top10_share],
           "posts": [None if not np.isfinite(v) else float(v) for v in d.posts],
           "broad": [None if not np.isfinite(v) else float(v) for v in d.broad_posts],
           "bull":  [int(v) if np.isfinite(v) else 0 for v in d.bull],
           "bear":  [int(v) if np.isfinite(v) else 0 for v in d.bear]}
    return f'''<div id="lqchart"></div>
<script id="lqdata" type="application/json">{json.dumps(pay, separators=(",", ":"))}</script>
<script>
(function(){{
  var P=JSON.parse(document.getElementById('lqdata').textContent),N=P.dates.length;
  var box=document.getElementById('lqchart');
  if(N<1){{return;}}
  var W=1180,H=250,PL=52,PR=52,PT=14,PB=26,iw=W-PL-PR,ih=H-PT-PB;
  var fp=P.posts.filter(function(x){{return x!=null;}});
  var pmax=Math.max.apply(null,fp)*1.08||1;
  var fs=P.share.filter(function(x){{return x!=null;}});
  var mn=Math.min.apply(null,fs),mx=Math.max.apply(null,fs);
  if(mx-mn<8){{mn=Math.max(0,mn-4);mx=Math.min(100,mx+4);}}
  var X=function(i){{return PL+iw*(N===1?0.5:i/(N-1));}};
  var Yp=function(v){{return PT+ih-ih*v/pmax;}};
  var Ys=function(v){{return PT+ih-ih*(v-mn)/((mx-mn)||1);}};
  var bw=Math.max(2,Math.min(16,iw/N*0.62));
  var g='',bars='',ticks='';
  for(var k=0;k<=4;k++){{var yy=PT+ih*k/4;
    g+='<line x1="'+PL+'" y1="'+yy.toFixed(1)+'" x2="'+(W-PR)+'" y2="'+yy.toFixed(1)+'" stroke="var(--grid)"/>'+
       '<text x="'+(PL-6)+'" y="'+(yy+3.5).toFixed(1)+'" text-anchor="end" class="ax">'+Math.round((pmax-pmax*k/4)/1000)+'K</text>'+
       '<text x="'+(W-PR+6)+'" y="'+(yy+3.5).toFixed(1)+'" class="ax sp">'+(mx-(mx-mn)*k/4).toFixed(0)+'%</text>';}}
  for(var i=0;i<N;i++){{
    var tot=P.posts[i], br=P.broad[i];
    if(tot==null)continue;
    var x=X(i)-bw/2;
    // Total is the full bar; the darker foot is the broad crowd beyond the ten
    // loudest, so the gap between them IS the concentration.
    bars+='<rect x="'+x.toFixed(1)+'" y="'+Yp(tot).toFixed(1)+'" width="'+bw.toFixed(1)+
          '" height="'+(ih+PT-Yp(tot)).toFixed(1)+'" fill="var(--cool)" opacity=".38"><title>'+
          P.dates[i]+' — '+Math.round(tot).toLocaleString()+' posts</title></rect>';
    if(br!=null)
      bars+='<rect x="'+x.toFixed(1)+'" y="'+Yp(br).toFixed(1)+'" width="'+bw.toFixed(1)+
            '" height="'+(ih+PT-Yp(br)).toFixed(1)+'" fill="var(--cool)" opacity=".85"><title>'+
            P.dates[i]+' — '+Math.round(br).toLocaleString()+' broad-crowd posts</title></rect>';
  }}
  var d='',pen=false;
  for(var i=0;i<N;i++){{var v=P.share[i]; if(v==null){{pen=false;continue;}}
    d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Ys(v).toFixed(1)+' ';pen=true;}}
  var step=Math.max(1,Math.floor(N/8));
  for(var i=0;i<N;i+=step)
    ticks+='<text x="'+X(i).toFixed(1)+'" y="'+(H-8)+'" text-anchor="middle" class="ax">'+P.dates[i].slice(5)+'</text>';
  box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none" class="sbsvg">'+g+bars+
    '<path d="'+d+'" fill="none" stroke="var(--vio)" stroke-width="1.8"/>'+ticks+'</svg>'+
    '<div class="sblg"><span class="k cool"></span>total daily posts (left)'+
    '<span class="k cool2"></span>broad crowd, beyond the ten loudest'+
    '<span class="k vio"></span>top-10 share of chatter (right)</div>';
}})();
</script>'''




def panel(spy=None):
    """Kept for callers; the history chart now lives inside crowd_panel()."""
    return ""


def crowd_panel():
    """Where the crowd actually is -- the per-ticker read, not just the aggregate."""
    d = load()
    if d is None or not len(d): return ""
    r = d.iloc[-1]
    def J(k):
        try: return json.loads(r.get(k) or "[]")
        except Exception: return []
    loud, brk, brkd = J("loudest"), J("breakouts"), J("breakdowns")
    gain, lose = J("gaining"), J("losing")
    if not (loud or brk or gain): return ""
    share = r.get("top10_share"); typ = r.get("typical_share")
    hot = np.isfinite(share) and np.isfinite(typ) and share > typ
    verdict = "HIGHLY CONCENTRATED" if hot else "BROAD"
    top = loud[0] if loud else None

    def tiles():
        t = [("Top-10 share of posts", f"{share:.0f}%",
              "of all 48h posts sit in ten tickers")]
        if top: t.append(("Loudest single name", top["t"],
                          f"{top['share']}% of all posts on its own"))
        posts = r.get("posts")
        if posts is not None and np.isfinite(posts):
            prev = d.posts.iloc[-2] if len(d) > 1 else np.nan
            chg = (f"{100*(posts/prev-1):+.0f}% vs prior capture"
                   if np.isfinite(prev) and prev else "total crowd posts")
            t.append(("Total posts", f"{posts:,.0f}", chg))
        return "".join(f'<div><h6>{a}</h6><div class="v">{b}</div>'
                       f'<div class="s">{c}</div></div>' for a, b, c in t)

    def bars(rows):
        if not rows: return ""
        mx = max([x["share"] for x in rows] or [1]) or 1
        return ('<table class="sig cw"><thead><tr><th>Ticker</th><th>Posts</th>'
                '<th>Share</th><th></th></tr></thead><tbody>'
                + "".join(
            f'<tr><td class="nm">{html.escape(x["t"])}</td>'
            f'<td>{html.escape(str(x["posts"]))} posts</td>'
            f'<td>{x["share"]}%</td>'
            f'<td class="bar"><i style="width:{100*x["share"]/mx:.0f}%"></i></td></tr>'
            for x in rows) + '</tbody></table>')

    def surges(rows):
        if not rows: return ""
        return ('<table class="sig cw"><thead><tr><th>Ticker</th>'
                '<th>Posts/day</th><th>Surge</th></tr></thead><tbody>'
                + "".join(
            f'<tr><td class="nm">{html.escape(x["t"])}</td>'
            f'<td class="dim">{html.escape(str(x["from"]))} &rarr; '
            f'{html.escape(str(x["to"]))}</td>'
            f'<td class="up">{x["x"]:g}&times;</td></tr>' for x in rows) +
            '</tbody></table>')

    def moves(rows, up=True):
        if not rows: return ""
        return ('<table class="sig cw"><thead><tr><th>Ticker</th><th>Posts</th>'
                '<th>Change</th></tr></thead><tbody>'
                + "".join(
            f'<tr><td class="nm">{html.escape(x["t"])}</td>'
            f'<td class="dim">{html.escape(str(x["from"]))}&rarr;'
            f'{html.escape(str(x["to"]))}</td>'
            f'<td class="{"up" if up else "dn"}">{x["pct"]:+d}%</td></tr>'
            for x in rows) + '</tbody></table>')

    _, src = source()
    is_liqn = src == "liqn.ai"
    win = "7d vs prior 7d" if is_liqn else "24h vs prior 24h"
    return (f'<h2>Social sentiment &mdash; crowd concentration</h2>'
            f'<div class="cwbox"><div class="cwhead">'
            f'<span class="dim">{"liqn.ai Social IQ" if is_liqn else html.escape(src)} &middot; {r["date"]}</span>'
            f'<b class="{"crit" if hot else "good"}">{verdict}</b></div>'
            f'<div class="cwtiles">{tiles()}</div>'
            # Posts and top-10 share over the whole stored record -- liqn's own
            # board only keeps ~3 months, this keeps every captured day.
            f'<h5 style="margin:4px 0 6px">Total posts &amp; top-10 share of chatter'
            f'<span class="dim"> &middot; {len(d)} day{"s" if len(d) != 1 else ""} stored</span></h5>'
            + _hist_chart(d) +
            '<div class="cwgrid" style="margin-top:12px">'
            f'<div><h5>Loudest<span class="dim"> &middot; share of all posts</span></h5>{bars(loud)}</div>'
            f'<div><h5>Gaining the crowd<span class="dim"> &middot; {win}</span></h5>{moves(gain,True)}</div>'
            '</div>'
            + ('<p class="dnote">Retail attention on X. ' if is_liqn else
               '<p class="dnote">Retail attention on Reddit (ApeWisdom mention counts); '
               'bull/bear verdicts from StockTwits posters&rsquo; own tags. ')
            + 'Top-10 share is the '
            'concentration read &mdash; the sentiment analogue of a crowded COT '
            'cohort. liqn&rsquo;s own caveat is worth keeping: attention is '
            'coincident and sometimes contrarian, and peak hype can mark a local '
            'top. Context, never a signal.</p></div>')


# --- Market environment (liqn.ai "Market Stress Monitor") --------------------
#
# 283 factors scored on two axes, each a percentile against the trailing year:
#   turbulence   how unusual today's factor moves are (size + co-movement)
#   churn        how much the factor leaderboard has reshuffled vs 1 month ago
# 80+ on either axis flips the quadrant. This is a regime read that actually
# fits a short-horizon momentum book: NORMAL (quiet, same leaders) is when
# breakout/HTF setups get followed through; ROTATION (churn without
# turbulence) is exactly the "new leadership" signal that should redirect RS
# scans toward the names now gaining rank; SHOCK/BREAK (turbulence, with or
# without churn) is when the downtrend/parabolic-short setups are favored and
# breakout entries should be trusted less. Same capture pattern as the crowd
# page above -- no API, browser-only, history starts the day it is captured.
SHIST = f"{D}/liqn_stress_hist.csv"
SCOLS = ["date", "verdict", "turb", "turb_pct", "churn", "churn_pct",
         "down_n", "down_total", "median_pct", "desk_note", "up", "down"]

SETUP_READ = {
    "Normal":          ("up", "Quiet tape, same leaders. Breakout / HTF and gap "
                                "setups get the most follow-through here."),
    "Stealth Rotation": ("warn", "Leadership is changing under a quiet tape. Redirect "
                                 "RS scans toward the names gaining rank below -- this "
                                 "is the choppy-market, new-leader setup."),
    "Shock":           ("crit", "Unusual moves, same leaders -- a broad, violent tape "
                                "rather than a rotation. Trust breakout entries less; "
                                "this is where stops matter most."),
    "Regime Break":    ("crit", "Both unusual moves and reshuffling leadership at "
                                "once -- the rare one. Favor the downtrend / parabolic-"
                                "short setups over breakouts until this clears."),
}


def parse_stress(text):
    lines = [l.strip() for l in text.splitlines()]
    verdict = next((l.rstrip(".") for l in lines
                     if l in ("Normal.", "Shock.", "Stealth Rotation.", "Regime Break.")), None)
    if verdict is None:
        return None
    m = re.search(r"unusualness:\s*(\d+)\w{2} percentile.*?leadership reshuffle:\s*(\d+)\w{2}", text, re.S)
    turb_pct, churn_pct = (int(m.group(1)), int(m.group(2))) if m else (np.nan, np.nan)
    m = re.search(r"turbulence \(([\d.]+)\) and churn \(([\d.]+)\)", text)
    turb, churn = (float(m.group(1)), float(m.group(2))) if m else (np.nan, np.nan)
    m = re.search(r"The tape:\s*(\d+) of (\d+) factors down.*?median\s*([+\-][\d.]+)%", text)
    down_n, down_total, median_pct = (
        (int(m.group(1)), int(m.group(2)), float(m.group(3))) if m else (np.nan, np.nan, np.nan))
    desk = ""
    if "DESK NOTE · AI-ASSISTED" in lines:
        idx = lines.index("DESK NOTE · AI-ASSISTED")
        desk = next((l for l in lines[idx + 1:] if l), "")

    def movers(marker):
        if marker not in lines: return []
        idx = lines.index(marker)
        row = next((l for l in lines[idx + 1:] if l), "")
        parts = re.findall(
            r"([A-Za-z0-9&,\.\- ]+?)\s*\(#(\d+)\s*→\s*#(\d+)\s*·\s*([+\-][\d.]+)%\s*/\s*21d\)", row)
        return [{"name": p[0].strip(), "from": int(p[1]), "to": int(p[2]), "pct": float(p[3])} for p in parts]

    return {"date": pd.Timestamp.today().strftime("%Y-%m-%d"), "verdict": verdict,
            "turb": turb, "turb_pct": turb_pct, "churn": churn, "churn_pct": churn_pct,
            "down_n": down_n, "down_total": down_total, "median_pct": median_pct,
            "desk_note": desk, "up": json.dumps(movers("▲ moving up")),
            "down": json.dumps(movers("▼ falling back"))}


def append_stress(row):
    d = pd.DataFrame([row])[SCOLS]
    if os.path.exists(SHIST):
        old = pd.read_csv(SHIST)
        d = pd.concat([old, d], ignore_index=True).drop_duplicates("date", keep="last")
    d.to_csv(SHIST, index=False)
    return d


def load_stress():
    if not os.path.exists(SHIST): return None
    d = pd.read_csv(SHIST)
    if not len(d): return None
    d["dt"] = pd.to_datetime(d.date, errors="coerce")
    return d.dropna(subset=["dt"]).sort_values("dt")


def stress_panel(compact=False):
    """compact=True renders the small reference version for Market Diary; the
    full version (default) is the lead panel on Global & liquidity."""
    d = load_stress()
    if d is None or not len(d): return ""
    r = d.iloc[-1]
    tone, read = SETUP_READ.get(r.verdict, ("warn", ""))
    n = len(d)

    def J(k):
        try: return json.loads(r.get(k) or "[]")
        except Exception: return []
    up, down = J("up"), J("down")

    def moverlist(rows, cls):
        if not rows: return '<span class="dim">none</span>'
        return " &middot; ".join(
            f'<span class="{cls}">{html.escape(x["name"])}</span> '
            f'<span class="dim">(#{x["from"]}&rarr;#{x["to"]} &middot; {x["pct"]:+.1f}%/21d)</span>'
            for x in rows)

    hist_note = (f"{n} session{'s' if n != 1 else ''} captured" if n > 1 else
                 "first session captured &mdash; liqn publishes no archive, so this "
                 "record starts today and lengthens by one row per run")

    head = (f'<div class="cwhead"><span class="dim">liqn.ai Market Stress &middot; '
            f'{r.date} &middot; {hist_note}</span><b class="{tone}">{html.escape(r.verdict).upper()}</b></div>')

    if compact:
        return (f'<h2>Market environment</h2><div class="cwbox">{head}'
                f'<p class="dnote">Turbulence {r.turb:.0f} ({int(r.turb_pct)}th pctile) &middot; '
                f'churn {r.churn:.0f} ({int(r.churn_pct)}th pctile) &middot; '
                f'{int(r.down_n)} of {int(r.down_total)} factors down, median {r.median_pct:+.1f}%. '
                f'{read} Full read on the Global &amp; liquidity tab.</p></div>')

    return (
        '<h2>Market environment &mdash; liqn.ai Market Stress Monitor</h2>'
        '<p class="grpnote">283 factors watched as one picture, two axes each a '
        'percentile against the trailing year: <b>turbulence</b> (how unusual '
        'today\'s factor moves are) and <b>leadership churn</b> (how much the '
        'factor leaderboard has reshuffled vs a month ago). 80+ on either flips '
        'the quadrant. This is a regime read, not a signal &mdash; use it to pick '
        'which of the three setups fits today, not to time an entry.</p>'
        f'<div class="cwbox">{head}'
        f'<div class="cwtiles">'
        f'<div><h6>Turbulence</h6><div class="v">{r.turb:.0f}</div>'
        f'<div class="s">{int(r.turb_pct)}th percentile of the past year</div></div>'
        f'<div><h6>Leadership churn</h6><div class="v">{r.churn:.0f}</div>'
        f'<div class="s">{int(r.churn_pct)}th percentile of the past year</div></div>'
        f'<div><h6>Tape</h6><div class="v">{int(r.down_n)}/{int(r.down_total)}</div>'
        f'<div class="s">factors down, median {r.median_pct:+.1f}%</div></div></div>'
        f'<p class="dnote"><b>What this means for your setups:</b> {read}</p>'
        f'<p class="dnote">{html.escape(r.desk_note)}</p>'
        '<div class="cwgrid">'
        f'<div><h5>Gaining rank <span class="dim">&middot; past 21 sessions</span></h5>'
        f'<p class="dnote">{moverlist(up, "up")}</p></div>'
        f'<div><h5>Falling back <span class="dim">&middot; past 21 sessions</span></h5>'
        f'<p class="dnote">{moverlist(down, "dn")}</p></div>'
        '</div>'
        '<p class="dnote">liqn&rsquo;s own framing: it measures unusualness, not '
        'pain &mdash; a broad down day where everything falls together can still '
        'read Normal. The meter fires when the market\'s <i>pattern</i> breaks, '
        'not when it drops.</p></div>')
