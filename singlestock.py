"""Single-stock page: where the datasets land on the SAME name, and on the same group.

Two questions this answers that no individual panel can.

OVERLAP. Short interest, social attention, earnings and group strength each
produce their own list. A name that appears on one is noise; a name that appears
on three at once is where a setup actually lives. This counts the hits per
ticker and shows what is stacking.

SECTOR HEAT. One heavily shorted name is a stock story. Three or more inside the
same industry group is a theme -- the market is expressing a view on the whole
basket, and that is a different trade. The threshold is 3 because below that the
count is indistinguishable from how many names the group happens to contain.
"""
import pandas as pd, numpy as np, json, os, html

D = os.path.expanduser("~/pos")
Z_HEAVY = 1.5          # a name's own-history sigma before it counts as a signal
Z_LEVEL = 1.5          # short base already high in its own range
DTC_PCTL = 85          # days-to-cover percentile, measured ACROSS names
GROUP_MIN = 3          # names before a group is even considered
LIFT_MIN = 1.6         # and it must run this many times the base rate
EARN_DAYS = 14


def _si():
    try:
        import sitables
        d = sitables.build()
        return d if d is not None else None
    except Exception:
        return None


def _social():
    """Latest liqn per-ticker tables, flattened into signal sets."""
    out = {"loud": {}, "brk": {}, "gain": {}, "cool": {}, "lose": {}}
    try:
        import liqn
        d = liqn.load()
        if d is None or not len(d): return out
        r = d.iloc[-1]
        def J(k):
            try: return json.loads(r.get(k) or "[]")
            except Exception: return []
        for x in J("loudest"):    out["loud"][x["t"]] = x.get("share")
        for x in J("breakouts"):  out["brk"][x["t"]] = x.get("x")
        for x in J("gaining"):    out["gain"][x["t"]] = x.get("pct")
        for x in J("breakdowns"): out["cool"][x["t"]] = x.get("pct")
        for x in J("losing"):     out["lose"][x["t"]] = x.get("pct")
    except Exception:
        pass
    return out


def _earn():
    try:
        p = f"{D}/earnings.parquet"
        if not os.path.exists(p): return {}
        e = pd.read_parquet(p)
        t0 = pd.Timestamp.today().normalize()
        e = e[(pd.to_datetime(e.date) >= t0) &
              (pd.to_datetime(e.date) <= t0 + pd.Timedelta(days=EARN_DAYS))]
        return dict(zip(e.symbol, e.date))
    except Exception:
        return {}


def _groups():
    g = {}
    p = f"{D}/custom176-rosters.txt"
    if os.path.exists(p):
        for line in open(p):
            if "|" not in line: continue
            n, syms = line.split("|", 1)
            for s in syms.strip().split(","):
                s = s.strip().upper()
                if s: g.setdefault(s, []).append(n.strip())
    return g


def build():
    si, soc, earn, grp = _si(), _social(), _earn(), _groups()
    rows = {}

    def hit(t, kind, label, tone):
        t = str(t).upper()
        rows.setdefault(t, {"t": t, "sig": []})["sig"].append((kind, label, tone))

    if si is not None and len(si):
        for t, r in si.iterrows():
            if np.isfinite(r.chg_z):
                if r.chg_z <= -Z_HEAVY:
                    hit(t, "si", f"covering {abs(r.chg_z):.1f}&sigma;", "up")
                elif r.chg_z >= Z_HEAVY:
                    hit(t, "si", f"building {r.chg_z:.1f}&sigma;", "dn")
            if np.isfinite(r.level_z) and r.level_z >= Z_LEVEL:
                hit(t, "si", f"short base high ({r.level_z:+.1f}&sigma;)", "dn")
    for t, v in soc["loud"].items():  hit(t, "soc", f"loudest &middot; {v}% of posts", "warn")
    for t, v in soc["brk"].items():   hit(t, "soc", f"attention {v:g}&times; baseline", "warn")
    for t, v in soc["gain"].items():  hit(t, "soc", f"crowd gaining {v:+d}%", "warn")
    for t, v in soc["cool"].items():  hit(t, "soc", f"attention {v:+d}%", "dim")
    for t, v in soc["lose"].items():  hit(t, "soc", f"crowd leaving {v:+d}%", "dim")
    for t, d in earn.items():         hit(t, "earn", f"earnings {d}", "vio")

    d = pd.DataFrame([{
        "t": v["t"], "n": len(v["sig"]),
        "kinds": len({k for k, _l, _tn in v["sig"]}),
        "sig": v["sig"], "groups": grp.get(v["t"], []),
    } for v in rows.values()])
    if not len(d): return None, None

    # ---- sector heat --------------------------------------------------
    # "Heavily shorted" has to mean something rarer than "above its own mean".
    # level_z >= 1 fires on roughly one name in six by construction, so three of
    # thirty is BELOW chance. Require either a real build, or a short base that is
    # extreme both in the name's own history and across the whole tape.
    heavy = {}
    if si is not None and len(si):
        _d = si.dtc.replace([np.inf, -np.inf], np.nan).dropna()
        _d = _d[(_d > 0) & (_d < 100)]
        dtc_cut = float(np.nanpercentile(_d.values, DTC_PCTL)) if len(_d) else np.inf
        for t, r in si.iterrows():
            build_hard = np.isfinite(r.chg_z) and r.chg_z >= Z_HEAVY
            crowded = (np.isfinite(r.level_z) and r.level_z >= Z_LEVEL
                       and np.isfinite(r.dtc) and r.dtc >= dtc_cut)
            if build_hard or crowded: heavy[str(t).upper()] = r
    neg = set(soc["cool"]) | set(soc["lose"])
    # Count only names the short-interest file actually covers. Counting names
    # with no data as "not shorted" understates every group unevenly, because
    # coverage is not uniform across sectors.
    covered = set(si.index.astype(str).str.upper()) if si is not None else set()
    gh = {}
    for t, gs in grp.items():
        if t not in covered: continue
        for g in gs:
            e = gh.setdefault(g, {"group": g, "short": [], "neg": [], "n": 0})
            e["n"] += 1
            if t in heavy: e["short"].append(t)
            if t in neg:   e["neg"].append(t)
    heat = pd.DataFrame([{
        "group": v["group"], "members": v["n"],
        "n_short": len(v["short"]), "n_neg": len(v["neg"]),
        "names": ", ".join(sorted(v["short"])[:10]),
        "share": 100.0 * len(v["short"]) / max(v["n"], 1),
    } for v in gh.values()])
    # Compare each group against the base rate. A group is only "elevated" if its
    # hit rate runs meaningfully ABOVE what the whole tape is doing -- otherwise
    # the flag just rediscovers that big groups contain more names.
    # The base rate must be measured on the SAME population the groups are drawn
    # from -- roster names with coverage -- not the whole 6,000-name tape, which
    # skews far smaller and would make every group look elevated.
    roster_cov = [t for t in grp if t in covered]
    base = 100.0 * len({t for t in roster_cov if t in heavy}) / max(len(roster_cov), 1)
    if len(heat):
        heat["lift"] = heat.share / max(base, 0.01)
        heat = heat[(heat.n_short >= GROUP_MIN) & (heat.lift >= LIFT_MIN)]
        heat = heat.sort_values(["lift", "n_short"], ascending=False)
        heat.attrs["base"] = base
    return d.sort_values(["kinds", "n"], ascending=False).reset_index(drop=True), heat


def html_panel():
    d, heat = build()
    if d is None: return ""
    multi = d[d.kinds >= 2].head(28)
    TONE = {"si": "SI", "soc": "SOCIAL", "earn": "EARNINGS"}

    def sigcell(sigs):
        return "".join(
            f'<span class="sg sg-{tn}"><i>{TONE.get(k,k)}</i>{l}</span>'
            for k, l, tn in sigs)

    body = "".join(
        f'<tr><td class="nm">{html.escape(r["t"])}</td>'
        f'<td class="sc">{int(r["kinds"])}</td>'
        f'<td>{sigcell(r["sig"])}</td>'
        f'<td class="nmw dim">{html.escape((r["groups"] or [""])[0][:34])}</td></tr>'
        for _, r in multi.iterrows())

    hbody = ""
    if heat is not None and len(heat):
        hbody = "".join(
            f'<tr><td class="nm2">{html.escape(str(r["group"]))}</td>'
            f'<td class="sc dn">{int(r["n_short"])}</td>'
            f'<td class="dim">of {int(r["members"])}</td>'
            f'<td class="sc">{r["share"]:.0f}%</td>'
            f'<td class="dim">{html.escape(str(r["names"]))}</td></tr>'
            for _, r in heat.head(16).iterrows())

    heatsec = ('<h2>Sector heat &mdash; where shorting is a theme, not a name</h2>'
               f'<p class="grpnote">Industry groups with <b>{GROUP_MIN} or more</b> '
               'members either building short at 1.5&sigma; or already sitting high '
               'in their own short-interest range. One heavily shorted name is a '
               'stock story; three in the same basket means the market is '
               'expressing a view on the whole group, which is a different trade '
               'and a different risk. Below three the count is indistinguishable '
               'from how many names a group happens to hold.</p>'
               '<table class="sig heat"><thead><tr><th>Group</th><th>Shorted</th>'
               '<th></th><th>Share</th><th>Names</th></tr></thead><tbody>'
               + hbody + '</tbody></table>') if hbody else (
               '<h2>Sector heat</h2><p class="grpnote">No industry group currently '
               f'has {GROUP_MIN} or more members under heavy short pressure. That is '
               'a real reading, not a gap &mdash; shorting is stock-specific right '
               'now rather than thematic.</p>')

    return ('<h2>Overlapping signals &mdash; where the datasets agree on a name</h2>'
            '<p class="grpnote">Tickers appearing in <b>two or more independent '
            'datasets</b> at once: short interest, social attention and an earnings '
            'date inside two weeks. One list is noise; the same name on three at '
            'once is where a setup actually lives. Sorted by how many separate '
            'datasets fire, then by how many signals within them.</p>'
            '<table class="sig ov"><thead><tr><th>Ticker</th><th>Datasets</th>'
            '<th>Signals</th><th>Group</th></tr></thead><tbody>'
            + (body or '<tr><td colspan="4" class="dim">nothing overlapping today</td></tr>')
            + '</tbody></table>' + heatsec)
