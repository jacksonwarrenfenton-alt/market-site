"""Which pairs actually track, and which are diverging right now.

This is the All Star Charts method made systematic rather than replaced. Those
desks find a pair that has moved together, then watch for the moment it stops --
the divergence is the signal, and the eye is good at spotting it. What the eye
is bad at is remembering which of a hundred candidate pairs ever tracked in the
first place, and noticing when an old relationship quietly comes back.

So: measure a rolling correlation for every candidate pair, keep the ones that
have EVER been reliably correlated, and rank by how far the current reading sits
from that pair's own normal. A pair at its historical extreme of divergence is
where to look.

Two deliberate choices.

  Rolling, not full-sample. A full-sample correlation of 0.2 can hide a pair
  that ran at 0.85 for three years and then broke -- which is exactly the case
  jman asked about ("if they were ever correlated and this correlation could pop
  up again I want to know").

  Correlation of RETURNS, not levels. Two rising series correlate on levels
  whatever they do in between; only returns say they move together.
"""
import pandas as pd, numpy as np, json, os, html

D = os.path.expanduser("~/pos")
WIN = 52           # one year of weekly returns per correlation window
MIN_HI = 0.55      # "has tracked" bar -- the pair must have reached this
MIN_OBS = 200


def _load():
    lib = json.load(open(f"{D}/chartdata.json"))
    idx = pd.DatetimeIndex(lib["dates"])
    S = {k: pd.Series(v, index=idx, dtype="float64") for k, v in lib["series"].items()}
    return lib, S


def scan():
    lib, S = _load()
    meta = lib["meta"]
    # candidates: every ratio in the library, plus the singles that matter as
    # liquidity/regime reads. Pairing every series with every other would be
    # 60k tests of mostly nonsense.
    ratios = [k for k in S if k.startswith("R:")]
    singles = [k for k in ("UUP", "^VIX", "^MOVE", "^TNX", "GLD", "SLV", "COPX",
                           "USO", "BTC-USD", "ARKK", "EEM", "SPY", "QQQ", "TLT",
                           "HYG", "CEW", "FXI", "KRE", "XLE", "DBA") if k in S]
    left = ratios + singles
    right = [k for k in ("SPY", "EEM", "ARKK", "BTC-USD", "UUP", "COPX", "GLD",
                         "^TNX", "^VIX", "QQQ", "KRE", "CEW") if k in S]

    rows = []
    R = {k: np.log(S[k].replace([np.inf, -np.inf], np.nan)).diff()
         for k in set(left) | set(right) if (S[k].dropna() > 0).all()}
    for a in left:
        if a not in R: continue
        for b in right:
            if b not in R or a == b: continue
            if a.startswith("R:") and b in a: continue     # ratio vs its own leg
            f = pd.concat([R[a], R[b]], axis=1).dropna()
            if len(f) < MIN_OBS: continue
            rc = f.iloc[:, 0].rolling(WIN).corr(f.iloc[:, 1]).dropna()
            if len(rc) < 100: continue
            cur = float(rc.iloc[-1])
            hi, lo = float(rc.max()), float(rc.min())
            peak = max(abs(hi), abs(lo))
            if peak < MIN_HI: continue
            mu, sd = float(rc.mean()), float(rc.std())
            z = (cur - mu) / sd if sd > 0 else np.nan
            rows.append({
                "a": a, "b": b,
                "a_label": meta.get(a, {}).get("label", a),
                "b_label": meta.get(b, {}).get("label", b),
                "cur": cur, "mean": mu, "max": hi, "min": lo,
                "peak": peak, "z": z,
                "pct": float((rc <= cur).mean() * 100),
                "n": len(rc)})
    d = pd.DataFrame(rows)
    if d.empty: return d
    d["absz"] = d.z.abs()
    return d.sort_values("absz", ascending=False).reset_index(drop=True)


def save():
    d = scan()
    if len(d): d.to_parquet(f"{D}/ratioscan.parquet")
    return d


def html_panel(d=None):
    if d is None:
        p = f"{D}/ratioscan.parquet"
        if not os.path.exists(p): return ""
        d = pd.read_parquet(p)
    if d is None or not len(d): return ""
    div = d[(d.peak >= 0.65) & (d.absz >= 1.5)].head(16)
    back = d[(d.peak >= 0.65) & (d.absz < 0.6) & (d.cur.abs() >= 0.5)].head(10)

    def tbl(x, note):
        if not len(x): return f'<p class="dim">{note}</p>'
        return ('<table class="sig dvg"><thead><tr><th>Pair</th><th>Against</th>'
                '<th>Now</th><th>Its normal</th><th>Range</th><th>z</th>'
                '<th>%ile</th></tr></thead><tbody>' + "".join(
            f'<tr><td class="nm2">{html.escape(str(r.a_label))}</td>'
            f'<td class="nm2">{html.escape(str(r.b_label))}</td>'
            f'<td class="{"up" if r.cur>=0 else "dn"}"><b>{r.cur:+.2f}</b></td>'
            f'<td class="dim">{r["mean"]:+.2f}</td>'
            f'<td class="dim">{r["min"]:+.2f} to {r["max"]:+.2f}</td>'
            f'<td class="{"dn" if abs(r.z)>=2 else ""}">{r.z:+.1f}</td>'
            f'<td>{r.pct:.0f}</td></tr>' for _, r in x.iterrows())
            + '</tbody></table>')

    return (
      '<h2>Correlation scan &mdash; what is tracking, and what just stopped</h2>'
      f'<p class="grpnote">Rolling {WIN}-week correlation of weekly <b>returns</b> '
      f'for {len(d)} pairs that have reached |r| &ge; {MIN_HI} at some point in '
      'their history. Levels are excluded on purpose: two rising series correlate '
      'on levels whatever they do in between, and only returns say they actually '
      'move together. Rolling rather than full-sample, because a full-sample 0.2 '
      'hides a pair that ran at 0.85 for three years and then broke &mdash; which is '
      'exactly the case worth knowing about.</p>'
      '<h4>Breaking down &mdash; furthest from their own normal</h4>'
      '<p class="dnote">These pairs have tracked before and are now at an extreme '
      'versus their own history. A relationship stretching is where the eye goes '
      'on an All Star Charts page; this just says which of a hundred candidates to '
      'point it at.</p>'
      + tbl(div, "nothing is more than 1.5 sigma from its own normal today")
      + '<h4 style="margin-top:16px">Back in gear &mdash; correlation has returned</h4>'
      '<p class="dnote">Pairs sitting close to their long-run relationship with a '
      'currently strong reading. An old correlation coming back is the quieter '
      'half of the same idea and the one that is easy to miss.</p>'
      + tbl(back, "no dormant pair has re-synchronised this week"))
